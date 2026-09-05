#!/usr/bin/env python3
"""Check aperture scaling against raw extracted STA and timed simulation.

Run after run_experiment_sta.py and run_sdfsim.py in the devcontainer.
"""
import json
from pathlib import Path

import common as C
from run_experiment_sta import gen_cases_tcl, run_sta
from run_sdfsim import run_point

out = Path(C.DATA) / "verification"
out.mkdir(parents=True, exist_ok=True)
cases = out / "aperture_cases.tcl"
gen_cases_tcl(str(cases), [(3, 3, 3, 3)], [1])
corner = "nom_typ_1p20V_25C"
sta = []
for period, duty in ((20, 0.5), (40, 0.5), (20, 0.4), (20, 0.6)):
    report = out / f"aperture_p{period}_d{duty}.rpt"
    text = run_sta(corner, str(cases), str(report), period_ns=period, duty=duty)
    report.write_text(text)
    path = C.parse_case_report(text)["seg3333-pat1"]["r2r"]
    assert path is not None
    sta.append({"period_ns": period, "duty": duty,
                "slack_ns": path["slack_ns"],
                "required_high_ns": period * duty - path["slack_ns"],
                "predicted_fmax_mhz": C.predicted_fmax_mhz(path["slack_ns"], period, duty)})
# With unchanged extracted clock/data delay, required high time is invariant.
assert max(r["required_high_ns"] for r in sta) - min(r["required_high_ns"] for r in sta) < 0.03
assert abs(sta[0]["predicted_fmax_mhz"] - sta[1]["predicted_fmax_mhz"]) < 0.05

sim = []
for high_ns in (14, 18):
    rates = []
    for duty in (0.4, 0.5, 0.6):
        period = high_ns / duty
        r = run_point(period, 0x0DFF, 200, corner, forcecan=1, duty=duty)
        errors = int(r["err_cnt"])
        assert int(r["ops"]) == 200 and r["cfg_echo"] == "ff"
        rates.append(errors)
        sim.append({"period_ns": period, "duty": duty, "high_time_ns": high_ns,
                    "ops": 200, "err_cnt": errors, "log": r["log"]})
    assert len(set(rates)) == 1, "Equal high time must reproduce this deterministic workload's result"
    assert (rates[0] > 0) == (high_ns == 14)

controls = []
for pat in (0, 2, 3):
    r = run_point(20 if pat != 0 else 40, 0x0CFF | (pat << 8), 200,
                  corner, forcecan=1)
    assert int(r["err_cnt"]) == 0 and int(r["ops"]) == 200
    controls.append({"pattern": C.PATTERN_NAMES[pat], "result": r})

result = {"run_id": C.RUN_ID, "build_commit": C.GIT_COMMIT,
          "corner": corner, "sta": sta, "sdf": sim, "controls": controls,
          "limitation": "IOPATH-only SDF; no interconnect or flip-flop timing checks",
          "passed": True}
(out / "aperture-check.json").write_text(json.dumps(result, indent=2) + "\n")
print("PASS: extracted STA scaling, equal-high-time SDF equivalence, and workload controls")
