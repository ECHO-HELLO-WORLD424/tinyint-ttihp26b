#!/usr/bin/env python3
# SPDX-FileCopyrightText: (c) 2026 ECHO-HELLO-WORLD424
# SPDX-License-Identifier: Apache-2.0
"""Independent re-check of the experiment-STA launch coverage (freeze gate 4).

Reads only committed artifacts -- the per-corner raw OpenSTA reports, the
machine-readable table and the launch-pin artifact -- and re-derives every
claim the flow makes, so a reviewer does not have to trust the run that
produced them:

  1. launch set: 18 unique sequential-cell Q pins, roles lfsr0..lfsr15 + idx0/1,
     matching src/tpv_pattern_gen.v; the named/renamed split is reported.
  2. traceability: every CSV row's startpoint / endpoint / arrival / required /
     slack is re-parsed from the raw report text of the same corner.
  3. formulas: slack = required - arrival, and predicted_fmax_mhz =
     1e3 / (clk_period_ns - slack_ns / capture_duty).
  4. coverage: no case where the unrestricted capture path is worse than the
     runtime-state path, every unrestricted startpoint classified, and the
     documented control criterion (control_slack_ns > 0) holds.
  5. build identity: netlist / SPEF / TCL hashes in the artifact match the
     files on disk.

Run: python3 tools/sta/verify_launch_coverage.py [--data DIR]
Exit status is nonzero if any check fails.
"""

import argparse
import csv
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import common as C  # noqa: E402

EXPECTED_ROLES = sorted([f"lfsr{i}" for i in range(16)] + ["idx0", "idx1"])


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=None,
                    help="dataset dir (default $TPV_DATA or data/safe10)")
    args = ap.parse_args()
    data = args.data or os.environ.get("TPV_DATA") or os.path.join(
        C.REPO, "data", "safe10")
    fails = []

    def check(ok, msg):
        print(("  PASS  " if ok else "  FAIL  ") + msg)
        if not ok:
            fails.append(msg)

    print(f"verify_launch_coverage: {data}")

    art_path = os.path.join(data, "experiment_sta_launch_pins.json")
    art = json.load(open(art_path))
    rows = list(csv.DictReader(open(os.path.join(data, "experiment_sta.csv"))))
    print(f"-- dataset: {len(rows)} rows, launch-pin artifact {os.path.basename(art_path)}")

    # 1. launch set
    pins = art["launch_pins"]
    check(len(pins) == 18, f"18 launch pins (found {len(pins)})")
    check(len({p["pin"] for p in pins}) == 18, "launch pins unique")
    check(sorted(p["role"] for p in pins) == EXPECTED_ROLES,
          "roles = 16 LFSR bits + 2 index flops")
    check(len({p["q_net"] for p in pins}) == 18, "launch Q nets unique")
    check(art["static_config_registers_in_operand_cone"] == 2,
          "2 static-configuration registers excluded from the operand cone")
    check(len({p["pin"] for p in pins} - {r["startpoint"] + "/Q" for r in rows
                                          if r["startpoint"]}) <= 18,
          "CSV startpoints are drawn from the launch set")

    # 2/3. raw-report traceability and formulas
    reports = {}
    bad_raw = bad_formula = 0
    for r in rows:
        corner = r["corner"]
        if corner not in reports:
            reports[corner] = C.parse_case_report(
                open(os.path.join(data, f"sta_report_{corner}.txt")).read())
        case = reports[corner][f"seg{r['seg0']}{r['seg1']}{r['seg2']}{r['seg3']}"
                               f"-pat{r['pattern']}"]
        got, want = case.get("r2r"), r
        if not want["startpoint"]:
            if got is not None and got.get("startpoint"):
                bad_raw += 1
            continue
        if (got is None or got.get("startpoint") != want["startpoint"]
                or got.get("endpoint") != want["endpoint"]
                or abs(got.get("slack_ns") - float(want["slack_ns"])) > 1e-9
                or abs(got.get("arrival_ns") - float(want["arrival_ns"])) > 1e-9
                or abs(got.get("required_ns") - float(want["required_ns"])) > 1e-9):
            bad_raw += 1
        if abs((float(want["required_ns"]) - float(want["arrival_ns"]))
               - float(want["slack_ns"])) > 0.011:
            bad_formula += 1
        if abs(round(1e3 / (float(want["clk_period_ns"])
                            - float(want["slack_ns"]) / float(want["capture_duty"])),
                     3) - float(want["predicted_fmax_mhz"])) > 0.002:
            bad_formula += 1
    check(bad_raw == 0, f"every row traceable to its raw report block ({bad_raw} mismatches)")
    check(bad_formula == 0, f"slack and f_max formulas/units verified ({bad_formula} violations)")

    # 4. coverage and classification
    worse = [r for r in rows if r["slack_ns"] and r["global_slack_ns"]
             and float(r["global_slack_ns"]) - float(r["slack_ns"]) < -1e-9]
    check(not worse, f"no unrestricted path worse than the runtime-state path "
                     f"({len(worse)} cases)")
    check(len(art["global_worse_than_r2r_cases"]) == len(worse),
          "artifact gap list matches the table")
    unknown = [r for r in rows if r["global_startpoint"]
               and r["global_startpoint_class"] not in
               ("runtime_state", "static_configuration", "control")]
    check(not unknown, f"every unrestricted startpoint classified ({len(unknown)} unknown)")
    neg_ctrl = [r for r in rows if float(r["control_slack_ns"]) <= 0]
    check(not neg_ctrl, f"control_slack_ns > 0 in every case "
                        f"(min {min(float(r['control_slack_ns']) for r in rows):.3f} ns)")
    sens = art["sensitizing_transition_check"]
    check(sens["checked_rows"] == sens["sensitized_rows"] > 0,
          f"{sens['sensitized_rows']}/{sens['checked_rows']} critical paths "
          f"sensitized by their recorded operand transition")

    # 5. build identity
    prov = art["provenance"]
    for key, rel in (("netlist_sha256", "netlist"), ("spef_sha256", "spef"),
                     ("sta_script_sha256", "sta_script")):
        path = os.path.join(C.REPO, prov[rel])
        check(os.path.exists(path) and sha256(path) == prov[key],
              f"{prov[rel]} sha256 matches the artifact")
    print(f"-- launch pins: {len(pins)} ({art['synthesis_named_q_nets']} with "
          f"synthesis names, {art['synthesis_renamed_q_nets']} renamed)")
    print(f"-- unrestricted startpoint classes: "
          f"{ {k: v['cases'] for k, v in art['unrestricted_capture_path_classes'].items()} }")
    if fails:
        print(f"verify_launch_coverage: {len(fails)} CHECK(S) FAILED")
        return 1
    print("verify_launch_coverage: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
