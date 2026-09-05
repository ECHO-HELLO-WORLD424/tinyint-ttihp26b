#!/usr/bin/env python3
"""Read-only area/clock-range audit of the archived final build.

Run in the devcontainer. Estimates are not replacement STA predictions.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re

from common import CIEL_PDK_REV, GIT_COMMIT, RUN_DIR, RUN_ID


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--liberty", type=Path, default=Path(
        "/home/vscode/ttsetup/pdk/ciel/ihp-sg13g2/versions/"
        + CIEL_PDK_REV
        + "/ihp-sg13g2/libs.ref/sg13g2_stdcell/lib/"
        "sg13g2_stdcell_typ_1p20V_25C.lib"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    run = Path(RUN_DIR)
    inputs = [run / "metrics.json", run / "nl/tt_um_echoworld424_tpv.nl.v",
              root / "data/experiment_sta.csv", args.liberty]
    metrics = json.loads(inputs[0].read_text())
    area = metrics["design__instance__area__stdcell"]
    core = metrics["design__core__area"]
    # Split at cell declarations, then read the first area field in each cell.
    chunks = re.split(r"\bcell\s*\(\s*([^\s)]+)\s*\)\s*\{",
                      args.liberty.read_text())
    areas = {chunks[i]: float(re.search(r"\barea\s*:\s*([0-9.]+)",
                                       chunks[i + 1]).group(1))
             for i in range(1, len(chunks), 2)}
    cells = re.findall(r"^\s*(sg13g2_\w+)\s+(\\?[^\s(]+)\s*\(",
                       inputs[1].read_text(), re.M)
    assert len(cells) == metrics["design__instance__count"]
    assert all(cell in areas for cell, _ in cells)
    # Liberty and physical metrics have slightly different area precision.
    # Final netlist includes filler: compare total within 0.1%.
    liberty_total = sum(areas[cell] for cell, _ in cells)
    assert abs(liberty_total - core) / core < 0.001
    blocks = {}
    for prefix in ("u_dut.", "u_ro_gen.", "u_ro_mat."):
        subset = [(cell, name) for cell, name in cells
                  if name.lstrip("\\").startswith(prefix)]
        blocks[prefix] = {
            "instances": len(subset),
            "area_um2": round(sum(areas[cell] for cell, _ in subset), 4),
            "scope": "preserved named instances only; flattened counters/control excluded",
        }
    with inputs[2].open() as stream:
        rows = list(csv.DictReader(stream))
    assert {r["git_commit"] for r in rows} == {GIT_COMMIT}
    knees = [{"corner": r["corner"],
              "existing_full_cycle_sta_mhz": float(r["predicted_fmax_mhz"]),
              "hypothetical_half_cycle_estimate_mhz":
                  float(r["predicted_fmax_mhz"]) / 2}
             for r in rows if r["pat_name"] == "worst"
             and all(r[f"seg{i}"] == "3" for i in range(4))]
    output = {
        "run_id": RUN_ID, "build_commit": GIT_COMMIT, "pdk_revision": CIEL_PDK_REV,
        "sha256": {str(p.relative_to(root)) if p.is_relative_to(root) else str(p):
                   hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
        "core_area_um2": core, "active_area_um2": area,
        "liberty_total_area_um2_including_fill": round(liberty_total, 4),
        "reported_utilization_pct": metrics["design__instance__utilization"] * 100,
        "area_targets": [{"target_pct": u, "required_saving_um2": round(area - core*u/100, 3),
                          "required_active_area_reduction_pct": round(100-core*u/area, 3)}
                         for u in (70, 65, 60)],
        "preserved_blocks": blocks, "seg3333_worst_knees": knees,
        "estimate_caveat": "Half-cycle values assume unchanged delays and exactly 50% duty; "
                           "not new STA or simulation; falling-edge setup, CTS and duty distortion omitted.",
    }
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
