#!/usr/bin/env python3
# SPDX-FileCopyrightText: (c) 2026 ECHO-HELLO-WORLD424
# SPDX-License-Identifier: Apache-2.0
"""Pre-silicon prediction package builder (PRE_SILICON_ACTION_PLAN P1.1).

Joins the pinned pre-silicon inputs -- the case-analyzed experiment STA table
(data/experiment_sta.csv), the extracted RO canary table (data/ro_predict.csv)
and the SDF boundary sweep (data/sdfsim.csv) -- into the frozen prediction
package written to data/predict/:

  predictions.csv    long format: corner x seg-config x pattern x predictor
  predictions.json   same rows + provenance + cross-checks + calibration block
  summary.md         human-readable tables
  plot_data.csv      long-format plot data (always written)
  knee_ladder.svg    predicted knee ladder per corner (pattern=worst)
  canary_counts.svg  canary win0 edge counts vs corner

If matplotlib is importable (devcontainer /ttsetup/venv), plots.png/plots.pdf
replace the two SVGs. The SVGs are hand-rolled XML, so matplotlib is optional.

Predictors (frozen; protocol in docs/prediction-model.md):
  sta     per-corner extracted-STA knee, T_fail = T_clk - slack
  ro_gen  nominal STA ladder scaled by generic-RO count ratio N(c)/N(nom)
  ro_mat  nominal STA ladder scaled by matched-RO count ratio N(c)/N(nom)

Both canary predictors are monotone maps from canary count to predicted DUT
first-failure frequency built ONLY from nominal-corner structure (nominal STA
ladder + nominal count anchor); no free parameters are fitted to data that does
not exist yet. Every row carries the one-point calibration placeholder
cal_k = 1.0; the post-silicon run substitutes k = measured/predicted at the
primary anchor or its predeclared fallback and changes nothing else.

Run: python3 tools/predict_model.py [--outdir data/predict]
Stdlib only (matplotlib optional). Deterministic: fixed ordering, no
timestamps in CSVs (an optional generated_utc field exists in JSON only).
"""

import argparse
import csv
import json
import math
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

MODEL_VERSION = "tpv-predict-1.0.1"  # keep in sync with docs/prediction-model.md
PREDICTORS = ["sta", "ro_gen", "ro_mat"]
CANARIES = ["ro_gen", "ro_mat"]
NOMINAL_CORNER = "nom_typ_1p20V_25C"  # 1.20 V / 25 C calibration anchor corner
READOUT_CAN_SEL = 3                   # predeclared canary readout config
READOUT_WIN = 0                       # win0 = 256 clk cycles
WINS = [0, 1, 2, 3]
COUNTER_MAX = 65535                   # largest value before 16-bit wrap
CAL_K_PLACEHOLDER = 1.0
BOARD_FMAX_MHZ = 50.0                 # 20 ns Tiny Tapeout board clock ceiling
ANCHOR_SEGS = (3, 3, 3, 3)            # calibration anchor config
ANCHOR_PATTERN = 1                    # worst
BOUNDARY_SEG = "3333"                 # SDF boundary sweep config
BOUNDARY_PATTERN = "worst"

SEG_LABELS = ["%d%d%d%d" % segs for segs in C.SEG_CONFIGS]
CORNER_SHORT = {
    name: "%s %.2fV %gC" % (name.split("_")[1], v, t)
    for name, v, t in C.CORNERS
}

FIELDNAMES = [
    "corner", "v_volt", "t_celsius", "seg0", "seg1", "seg2", "seg3", "seg_label",
    "pattern", "pat_name", "predictor", "status",
    "sta_path_delay_ns", "sta_slack_ns", "sta_slack_met",
    "predicted_fmax_mhz", "predicted_period_ns",
    "cal_k", "predicted_fmax_mhz_cal", "predicted_period_ns_cal",
    "ro_gen_count_win0", "ro_gen_count_win1", "ro_gen_count_win2",
    "ro_gen_count_win3", "ro_gen_fosc_mhz",
    "ro_mat_count_win0", "ro_mat_count_win1", "ro_mat_count_win2",
    "ro_mat_count_win3", "ro_mat_fosc_mhz",
    "run_id", "git_commit", "librelane_image", "pdk_rev", "model_version",
]


def fail(msg):
    raise SystemExit("predict_model: FATAL: " + msg)


def sig(x, n=4):
    """Round to n significant digits (the maximum rounding used anywhere)."""
    v = float(x)
    if not math.isfinite(v):
        fail("non-finite value reached output: %r" % (x,))
    if v == 0.0:
        return 0.0
    return float(("%." + str(n) + "g") % v)


def read_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


# --- Provenance ---------------------------------------------------------------

PROV_COLS = ["run_id", "git_commit", "librelane_image", "pdk_rev"]


def check_provenance(tables):
    """Assert constant provenance columns within and across all input tables."""
    prov = {}
    for name, rows in tables:
        if not rows:
            fail("no rows in %s" % name)
        for col in PROV_COLS:
            vals = sorted({(r.get(col) or "").strip() for r in rows})
            if len(vals) != 1 or not vals[0]:
                fail("provenance column %s not constant in %s: %s"
                     % (col, name, vals))
            if col in prov and prov[col] != vals[0]:
                fail("provenance mismatch for %s: %s vs %s"
                     % (col, prov[col], vals[0]))
            prov[col] = vals[0]
    pinned = (("run_id", C.RUN_ID), ("git_commit", C.GIT_COMMIT),
              ("librelane_image", C.LL_IMAGE), ("pdk_rev", C.CIEL_PDK_REV))
    for col, expected in pinned:
        if prov[col] != expected:
            print("predict_model: WARNING: %s = %s differs from the build "
                  "pinned in tools/common.py (%s)"
                  % (col, prov[col], expected), file=sys.stderr)
    return prov


# --- Input loaders ------------------------------------------------------------

def load_sta(rows):
    """Index experiment_sta.csv; enforce row counts and physical invariants."""
    n_exp = len(C.CORNER_NAMES) * len(C.SEG_CONFIGS) * len(C.PATTERNS)
    if len(rows) != n_exp:
        fail("experiment_sta.csv: expected %d rows (3 corners x 8 segs x 4 "
             "patterns), got %d" % (n_exp, len(rows)))
    idx = {}
    for r in rows:
        try:
            segs = (int(r["seg0"]), int(r["seg1"]), int(r["seg2"]), int(r["seg3"]))
            key = (r["corner"], segs, int(r["pattern"]))
        except (KeyError, ValueError) as e:
            fail("experiment_sta.csv: malformed row %r (%s)" % (r, e))
        if key in idx:
            fail("experiment_sta.csv: duplicate case %r" % (key,))
        idx[key] = r
    for corner in C.CORNER_NAMES:
        for segs in C.SEG_CONFIGS:
            for pat in C.PATTERNS:
                if (corner, segs, pat) not in idx:
                    fail("experiment_sta.csv: missing case %r"
                         % ((corner, segs, pat),))
    # hold = static operands: must have no runtime path; every other pattern
    # must carry a finite knee consistent with T_fail = T_clk - slack.
    for key, r in idx.items():
        f = r["predicted_fmax_mhz"].strip()
        if r["pat_name"] == "hold" or f == "":
            if r["pat_name"] != "hold" or f != "":
                fail("experiment_sta.csv: inconsistent empty prediction at %r"
                     % (key,))
            continue
        v = float(f)
        if not math.isfinite(v) or v <= 0:
            fail("experiment_sta.csv: bad predicted_fmax_mhz %r at %r" % (f, key))
        t_fail = float(r["clk_period_ns"]) - float(r["slack_ns"])
        if abs(1e3 / v - t_fail) > 0.05:
            fail("experiment_sta.csv: predicted_fmax inconsistent with slack "
                 "at %r" % (key,))
    # The knee must never rise when more delay taps are inserted (fixed
    # corner + pattern): the banks only sit on the carry route.
    for corner in C.CORNER_NAMES:
        for pat in C.PATTERNS:
            if C.PATTERN_NAMES[pat] == "hold":
                continue
            cells = [(segs, float(idx[(corner, segs, pat)]["predicted_fmax_mhz"]))
                     for segs in C.SEG_CONFIGS]
            for segs_a, fa in cells:
                for segs_b, fb in cells:
                    if sum(segs_a) < sum(segs_b) and fa < fb - 1e-9:
                        fail("monotonicity violated at %s pat%d: %s = %.3f MHz "
                             "< %s = %.3f MHz with fewer taps"
                             % (corner, pat, segs_a, fa, segs_b, fb))
    return idx


def load_ro(rows):
    """Index ro_predict.csv; verify 16-bit headroom of the canary counters."""
    n_exp = len(C.CORNER_NAMES) * 4 * 2
    if len(rows) != n_exp:
        fail("ro_predict.csv: expected %d rows (3 corners x 4 can_sel x 2 "
             "canaries), got %d" % (n_exp, len(rows)))
    idx = {}
    for r in rows:
        key = (r["corner"], r["canary"], int(r["can_sel"]))
        if key in idx:
            fail("ro_predict.csv: duplicate case %r" % (key,))
        idx[key] = r
    for corner in C.CORNER_NAMES:
        for can in CANARIES:
            for sel in range(4):
                if (corner, can, sel) not in idx:
                    fail("ro_predict.csv: missing case %r" % ((corner, can, sel),))
    fit = {}
    for win in WINS:
        cnt_col, sat_col = "count_win%d" % win, "sat_win%d" % win
        counts, ok = {}, True
        for corner in C.CORNER_NAMES:
            for can in CANARIES:
                r = idx[(corner, can, READOUT_CAN_SEL)]
                c = int(r[cnt_col])
                sat = r[sat_col] == "1"
                if c > COUNTER_MAX or sat:
                    ok = False
                counts["%s@%s" % (can, corner)] = {"count": c,
                                                    "would_wrap": sat}
        fit[win] = {"window_cycles": C.WINDOW_CYCLES[win],
                    "fits_16bit": ok, "counts": counts}
    if not fit[READOUT_WIN]["fits_16bit"]:
        fail("predeclared readout can_sel=%d/win%d does not fit 16 bits"
             % (READOUT_CAN_SEL, READOUT_WIN))
    return idx, fit


def load_sdf(rows):
    """Zero-delay reference sanity + seg3333/worst boundary bracket per corner.

    A period FAILS iff err_cnt > 0 (first-error threshold). The measured
    boundary bracket is [last failing period, first passing period above it];
    the point estimate is the bracket midpoint. Rows with FORCE_CAN off are
    the RO cross-check probe and are INVALID for boundary purposes (RO cells
    carry hard 0.000 SDF delays; docs/ro-sdf-crosscheck-diagnosis.md).
    """
    ref = [r for r in rows if not r["sdf"].strip()]
    if not ref:
        fail("sdfsim.csv: no zero-delay reference row found")
    for r in ref:
        if int(r["err_cnt"]) != 0:
            fail("sdfsim.csv: zero-delay reference row shows err_cnt=%s (%s)"
                 % (r["err_cnt"], r["log"]))
    bounds = {}
    for corner in C.CORNER_NAMES:
        sel = [r for r in rows
               if r["corner"] == corner and r["sdf"].strip()
               and r["segs"] == BOUNDARY_SEG and r["pattern"] == BOUNDARY_PATTERN
               and r["forcecan"] == "1"]
        if not sel:
            # The sweep simply does not cover this corner (e.g. fast, whose
            # predicted knee is far above the swept range); skip, don't guess.
            continue
        fails = sorted(float(r["period_ns"]) for r in sel if int(r["err_cnt"]) > 0)
        if not fails:
            fail("sdfsim.csv: no failing point for %s %s/%s -- cannot bracket "
                 "the boundary" % (corner, BOUNDARY_SEG, BOUNDARY_PATTERN))
        last_fail = max(fails)
        passes = sorted(float(r["period_ns"]) for r in sel
                        if int(r["err_cnt"]) == 0
                        and float(r["period_ns"]) > last_fail)
        if not passes:
            fail("sdfsim.csv: no passing point above %g ns for %s %s/%s"
                 % (last_fail, corner, BOUNDARY_SEG, BOUNDARY_PATTERN))
        bounds[corner] = {
            "last_fail_ns": max(fails),
            "first_pass_ns": passes[0],
            "mid_ns": (max(fails) + passes[0]) / 2.0,
            "n_points": len(sel),
            "ops": int(sel[0]["ops"]),
        }
    invalid_ro = [r for r in rows if r["sdf"].strip() and r["forcecan"] != "1"]
    return bounds, invalid_ro


# --- Model --------------------------------------------------------------------

def f_nom_ladder(sta_idx, segs, pat):
    """Nominal-corner STA knee for one (segs, pattern) cell [MHz]."""
    return float(sta_idx[(NOMINAL_CORNER, segs, pat)]["predicted_fmax_mhz"])


def build_predictions(sta_idx, ro_idx):
    """Long-format prediction rows: corner x seg-config x pattern x predictor."""
    nom_cnt = {can: int(ro_idx[(NOMINAL_CORNER, can, READOUT_CAN_SEL)]
                         ["count_win%d" % READOUT_WIN]) for can in CANARIES}
    rows = []
    for corner in C.CORNER_NAMES:
        ro_join = {}
        for can in CANARIES:
            r = ro_idx[(corner, can, READOUT_CAN_SEL)]
            for win in WINS:
                ro_join["%s_count_win%d" % (can, win)] = int(
                    r["count_win%d" % win])
            ro_join["%s_fosc_mhz" % can] = r["f_osc_mhz"]
        for segs in C.SEG_CONFIGS:
            for pat in C.PATTERNS:
                s = sta_idx[(corner, segs, pat)]
                usable = bool(s["predicted_fmax_mhz"].strip())
                pred = {}
                if usable:
                    pred["sta"] = float(s["predicted_fmax_mhz"])
                    for can in CANARIES:
                        cnt = ro_join["%s_count_win%d" % (can, READOUT_WIN)]
                        pred[can] = (f_nom_ladder(sta_idx, segs, pat)
                                     * cnt / nom_cnt[can])
                for predictor in PREDICTORS:
                    f = pred.get(predictor)
                    f = sig(f) if f is not None else None
                    row = {
                        "corner": corner,
                        "v_volt": s["v_volt"], "t_celsius": s["t_celsius"],
                        "seg0": segs[0], "seg1": segs[1], "seg2": segs[2],
                        "seg3": segs[3],
                        "seg_label": "%d%d%d%d" % segs,
                        "pattern": pat, "pat_name": C.PATTERN_NAMES[pat],
                        "predictor": predictor,
                        "status": "ok" if usable else "no_runtime_path",
                        "sta_path_delay_ns": s["path_delay_ns"],
                        "sta_slack_ns": s["slack_ns"],
                        "sta_slack_met": s["slack_met"],
                        "predicted_fmax_mhz": "" if f is None else f,
                        "predicted_period_ns": "" if f is None else sig(1e3 / f),
                        "cal_k": CAL_K_PLACEHOLDER,
                        "predicted_fmax_mhz_cal": "" if f is None else f,
                        "predicted_period_ns_cal":
                            "" if f is None else sig(1e3 / f),
                    }
                    row.update(ro_join)
                    row.update({
                        "run_id": C.RUN_ID, "git_commit": C.GIT_COMMIT,
                        "librelane_image": C.LL_IMAGE, "pdk_rev": C.CIEL_PDK_REV,
                        "model_version": MODEL_VERSION,
                    })
                    rows.append(row)
    return rows


def sta_vs_sdf(sta_idx, bounds):
    """Cross-check: STA knee vs SDF-sim measured boundary, seg3333/worst.

    err_* = STA - measured; positive means STA puts the knee at a longer
    period than the IOPATH-only simulation, i.e. STA conservative and the sim
    optimistic (wire interconnect is not annotated).
    """
    out = []
    for corner in C.CORNER_NAMES:
        if corner not in bounds:
            continue
        b = bounds[corner]
        r = sta_idx[(corner, ANCHOR_SEGS, ANCHOR_PATTERN)]
        t_sta = float(r["clk_period_ns"]) - float(r["slack_ns"])
        f_sta = float(r["predicted_fmax_mhz"])
        mid = b["mid_ns"]
        out.append({
            "corner": corner,
            "sta_t_fail_ns": sig(t_sta),
            "sta_fmax_mhz": f_sta,
            "sdf_last_fail_ns": b["last_fail_ns"],
            "sdf_first_pass_ns": b["first_pass_ns"],
            "sdf_bracket_mid_ns": sig(mid),
            "sdf_mid_fmax_mhz": sig(1e3 / mid),
            "err_sta_minus_mid_ns": sig(t_sta - mid),
            "err_sta_minus_mid_pct": sig(100.0 * (t_sta - mid) / mid),
            "err_sta_minus_first_pass_ns": sig(t_sta - b["first_pass_ns"]),
            "err_sta_minus_last_fail_ns": sig(t_sta - b["last_fail_ns"]),
            "err_sta_minus_mid_mhz": sig(f_sta - 1e3 / mid),
            "n_sdf_points": b["n_points"],
            "ops_per_point": b["ops"],
        })
    return out


def gen_mat_ratios(ro_idx):
    """Canary distinguishability metric: gen/mat win0 count ratio per corner."""
    out = {}
    for corner in C.CORNER_NAMES:
        g = int(ro_idx[(corner, "ro_gen", READOUT_CAN_SEL)]
                ["count_win%d" % READOUT_WIN])
        m = int(ro_idx[(corner, "ro_mat", READOUT_CAN_SEL)]
                ["count_win%d" % READOUT_WIN])
        out[corner] = {"gen_count": g, "mat_count": m,
                       "gen_over_mat": sig(g / m)}
    return out


# --- Output writers -----------------------------------------------------------

def write_predictions_csv(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def pred_lut(rows):
    """(corner, segs, pat, predictor) -> predicted_fmax_mhz string."""
    lut = {}
    for r in rows:
        lut[(r["corner"], (r["seg0"], r["seg1"], r["seg2"], r["seg3"]),
             int(r["pattern"]), r["predictor"])] = r["predicted_fmax_mhz"]
    return lut


def write_summary(path, prov, n_in, cross, ro_idx, ratios, lut, sta_idx,
                  sdf_ref_ops):
    def f4(x):
        return "" if x == "" else ("%.4g" % float(x))

    L = []
    L.append("# Pre-silicon prediction package (model `%s`)" % MODEL_VERSION)
    L.append("")
    L.append("Generated by `tools/predict_model.py` from the pinned input "
             "tables. The frozen protocol (predictor definitions, one-point "
             "calibration, post-silicon metrics) is `docs/prediction-model.md`; "
             "field units and RTL mirrors are `docs/data-dictionary.md`.")
    L.append("")
    L.append("- Inputs: `data/experiment_sta.csv` (%d rows), "
             "`data/ro_predict.csv` (%d rows), `data/sdfsim.csv` (%d rows)"
             % (n_in["sta"], n_in["ro"], n_in["sdf"]))
    L.append("- Provenance: run `%s`, commit `%s`, image `%s`, PDK `%s`"
             % (prov["run_id"], prov["git_commit"][:12],
                prov["librelane_image"], prov["pdk_rev"][:12]))
    L.append("- Nominal corner: `%s`; predeclared canary readout: can_sel=%d, "
             "win%d (%d clk cycles)"
             % (NOMINAL_CORNER, READOUT_CAN_SEL, READOUT_WIN,
                C.WINDOW_CYCLES[READOUT_WIN]))
    L.append("- Calibration: one-point multiplicative, placeholder "
             "`cal_k = %s` on every row; the post-silicon run substitutes the "
             "measured k only (`docs/prediction-model.md`)."
             % repr(CAL_K_PLACEHOLDER))
    L.append("")
    L.append("## STA vs SDF boundary cross-check (seg3333, worst)")
    L.append("")
    L.append("The SDF boundary is bracketed by the last failing and first "
             "passing annotated period (first-error threshold, err_cnt > 0); "
             "the point estimate is the bracket midpoint.")
    L.append("")
    L.append("| corner | STA T_fail (ns) | STA Fmax (MHz) | SDF last fail (ns) "
             "| SDF first pass (ns) | bracket mid (ns) | STA - mid (ns) "
             "| STA - mid (%) | STA - first pass (ns) | STA - last fail (ns) |")
    L.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for c in cross:
        L.append("| %s | %s | %s | %g | %g | %s | %s | %s | %s | %s |" % (
            c["corner"], c["sta_t_fail_ns"], c["sta_fmax_mhz"],
            c["sdf_last_fail_ns"], c["sdf_first_pass_ns"],
            c["sdf_bracket_mid_ns"], c["err_sta_minus_mid_ns"],
            c["err_sta_minus_mid_pct"], c["err_sta_minus_first_pass_ns"],
            c["err_sta_minus_last_fail_ns"]))
    L.append("")
    L.append("Sign: positive `STA - mid` = the STA knee sits at a longer period "
             "than the IOPATH-only SDF sim, i.e. STA is conservative and the "
             "sim optimistic (wire interconnect is not annotated; Icarus's "
             "interconnect annotator crashes on this design).")
    L.append("")
    L.append("## Canary readout at can_sel=%d (predeclared)" % READOUT_CAN_SEL)
    L.append("")
    L.append("Counts are predicted edges per window (hardware counters wrap "
             "mod 65536; `*` marks a prediction exceeding one 16-bit range). "
             "`gen/mat` is the canary "
             "distinguishability ratio at win%d."
             % READOUT_WIN)
    L.append("")
    L.append("| corner | gen win0 | gen win1 | gen win2 | gen win3 "
             "| mat win0 | mat win1 | mat win2 | mat win3 | gen/mat (win0) |")
    L.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for corner in C.CORNER_NAMES:
        cells = []
        for can in CANARIES:
            r = ro_idx[(corner, can, READOUT_CAN_SEL)]
            for win in WINS:
                cnt = int(r["count_win%d" % win])
                sat = r["sat_win%d" % win] == "1"
                cells.append(("%d*" % cnt) if sat else str(cnt))
        cells.append(str(ratios[corner]["gen_over_mat"]))
        L.append("| %s | %s |" % (CORNER_SHORT[corner], " | ".join(cells)))
    L.append("")
    L.append("win%d (%d cycles) counts fit 16 bits at every corner for both "
             "canaries: **yes**. win2 also fits everywhere; win3 would wrap "
             "ro_gen at the fast/typ corners (`sat_win3` is the model's "
             "overflow-risk flag, not an RTL saturation flag) and is not a "
             "usable single-window readout there."
             % (READOUT_WIN, C.WINDOW_CYCLES[READOUT_WIN]))
    L.append("")
    head = ["seg0..3"] + ["%s %s" % (CORNER_SHORT[c].split()[0], p)
                          for c in C.CORNER_NAMES for p in
                          ("STA", "ro_gen", "ro_mat")]
    L.append("Board ceiling is %.0f MHz (20 ns); knees above it are not "
             "reachable on the demo board." % BOARD_FMAX_MHZ)
    L.append("")
    for pattern_name in ("worst", "prbs"):
        L.append("## Predicted first-failure frequency (MHz), pattern = %s"
                 % pattern_name)
        L.append("")
        L.append("| " + " | ".join(head) + " |")
        L.append("| " + " | ".join(["---"] * len(head)) + " |")
        pat = C.PATTERN_NAMES.index(pattern_name)
        for segs, label in zip(C.SEG_CONFIGS, SEG_LABELS):
            cells = [label]
            for corner in C.CORNER_NAMES:
                for predictor in PREDICTORS:
                    cells.append(f4(lut[(corner, segs, pat, predictor)]))
            L.append("| " + " | ".join(cells) + " |")
        L.append("")
    alt = {corner: float(sta_idx[(corner, C.SEG_CONFIGS[0], 2)]
                         ["predicted_fmax_mhz"])
           for corner in C.CORNER_NAMES}
    L.append("Other patterns: `alt` bypasses the delay banks (one knee per "
             "corner, seg-independent): fast %.4g, typ %.4g, slow %.4g MHz -- "
             "above the %.0f MHz board ceiling, hence not measurable there. "
             "`hold` applies static operands and has no runtime-sensitizable "
             "path, so no predictor produces a value (status "
             "`no_runtime_path`)."
             % (alt[C.CORNER_NAMES[0]], alt[C.CORNER_NAMES[1]],
                alt[C.CORNER_NAMES[2]], BOARD_FMAX_MHZ))
    L.append("")
    L.append("## One-point calibration (placeholder rows)")
    L.append("")
    L.append("Each predictor x is calibrated at the primary nominal anchor "
             "(1.20 V, 25 C, seg3333, worst), or at the predeclared slow-corner "
             "fallback if the primary boundary is above the 50 MHz ceiling. "
             "The rule is k_x = F_meas / P_x(anchor), applied as "
             "P_x_cal = k_x * P_x everywhere, unchanged. Pre-silicon every "
             "row carries `cal_k = %s` and "
             "`predicted_fmax_mhz_cal = predicted_fmax_mhz`; the post-silicon "
             "run substitutes the measured k only."
             % repr(CAL_K_PLACEHOLDER))
    L.append("")
    L.append("## Notes")
    L.append("")
    for note in (
        "The `sdfsim.csv` RO cross-check row (FORCE_CAN off) is INVALID for "
        "model purposes: the RO loop cells are annotated with hard 0.000 SDF "
        "delays because `src/pnr.sdc` disables RO timing arcs, so its "
        "gen_cnt/mat_cnt are simulator race artifacts "
        "(`docs/ro-sdf-crosscheck-diagnosis.md`). It is excluded from this "
        "package; the DUT-boundary rows (FORCE_CAN on) are unaffected.",
        "The zero-delay reference row (ops=%d, err=0) validates the testbench "
        "protocol, not timing." % sdf_ref_ops,
        "The STA knee is a linear slack translation (T_fail = T_clk - slack, "
        "clock tree/uncertainty held at the corner); validity degrades far "
        "from the analyzed 20 ns point.",
        "Frame = %d clk cycles (frame_cnt 0..18); one timed DUT operation per "
        "frame." % C.FRAME_CYCLES,
    ):
        L.append("- " + note)
    L.append("")
    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")


def write_plot_data(path, rows, ro_idx):
    """Long-format plot data (durable regardless of the plotting backend)."""
    with open(path, "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["plot", "x_label", "series", "y", "y_unit"])
        for r in rows:
            if (r["pat_name"] == "worst" and r["predictor"] == "sta"
                    and r["predicted_fmax_mhz"] != ""):
                w.writerow(["knee_ladder", r["seg_label"], r["corner"],
                            r["predicted_fmax_mhz"], "MHz"])
        for corner in C.CORNER_NAMES:
            for can in CANARIES:
                cnt = int(ro_idx[(corner, can, READOUT_CAN_SEL)]
                          ["count_win%d" % READOUT_WIN])
                w.writerow(["canary_counts", CORNER_SHORT[corner], can,
                            cnt, "edges"])


# --- Plots --------------------------------------------------------------------

SVG_COLORS = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728"]


def _xml(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def _nice_ceil(v):
    exp = 10.0 ** math.floor(math.log10(v))
    for m in (1, 2, 2.5, 5, 10):
        if m * exp >= v:
            return m * exp
    return 10 * exp


def svg_bars(path, title, subtitle, ylabel, cats, series, ref=None, footer=""):
    """Grouped bar chart written as hand-rolled SVG (no dependencies)."""
    W, H = 960, 470
    ml, mr, mt, mb = 80, 14, 78, 62
    pw, ph = W - ml - mr, H - mt - mb
    ymax = max(v for _, vals in series for v in vals)
    if ref:
        ymax = max(ymax, ref[0])
    ymax = _nice_ceil(ymax * 1.08)
    ncat, nser = len(cats), len(series)
    group_w = pw / ncat
    bar_w = 0.72 * group_w / nser
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
           'viewBox="0 0 %d %d" font-family="sans-serif">' % (W, H, W, H),
           '<rect width="%d" height="%d" fill="white"/>' % (W, H),
           '<text x="%d" y="26" font-size="17" font-weight="bold" '
           'text-anchor="middle">%s</text>' % (W // 2, _xml(title))]
    if subtitle:
        out.append('<text x="%d" y="46" font-size="12" fill="#444444" '
                   'text-anchor="middle">%s</text>' % (W // 2, _xml(subtitle)))

    def Y(v):
        return mt + ph * (1.0 - v / ymax)

    for k in range(6):
        v = ymax * k / 5.0
        lbl = "%.0f" % v if ymax >= 20 else "%.4g" % v
        out.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#dddddd"/>'
                   % (ml, Y(v), ml + pw, Y(v)))
        out.append('<text x="%d" y="%.1f" font-size="11" text-anchor="end">'
                   '%s</text>' % (ml - 6, Y(v) + 4, _xml(lbl)))
    out.append('<line x1="%d" y1="%d" x2="%d" y2="%.1f" stroke="#333333"/>'
               % (ml, mt, ml, mt + ph))
    out.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#333333"/>'
               % (ml, mt + ph, ml + pw, mt + ph))
    for si, (name, vals) in enumerate(series):
        color = SVG_COLORS[si % len(SVG_COLORS)]
        for ci, v in enumerate(vals):
            x = ml + ci * group_w + 0.14 * group_w + si * bar_w
            out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" '
                       'fill="%s"/>' % (x, Y(v), bar_w, mt + ph - Y(v), color))
            out.append('<text x="%.1f" y="%.1f" font-size="8" '
                       'text-anchor="middle">%s</text>'
                       % (x + bar_w / 2, Y(v) - 3, _xml("%.4g" % v)))
    for ci, cat in enumerate(cats):
        out.append('<text x="%.1f" y="%.1f" font-size="11" '
                   'text-anchor="middle">%s</text>'
                   % (ml + (ci + 0.5) * group_w, mt + ph + 16, _xml(cat)))
    if ref:
        value, label = ref
        out.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" '
                   'stroke="#d62728" stroke-dasharray="6,4"/>'
                   % (ml, Y(value), ml + pw, Y(value)))
        out.append('<text x="%d" y="%.1f" font-size="11" fill="#d62728" '
                   'text-anchor="end">%s</text>'
                   % (ml + pw - 4, Y(value) - 5, _xml(label)))
    lx = ml + pw
    for si in reversed(range(nser)):
        name = series[si][0]
        lw = 26 + 6.6 * len(name)
        out.append('<rect x="%.1f" y="54" width="11" height="11" fill="%s"/>'
                   % (lx - lw, SVG_COLORS[si % len(SVG_COLORS)]))
        out.append('<text x="%.1f" y="64" font-size="12">%s</text>'
                   % (lx - lw + 15, _xml(name)))
        lx -= lw + 12
    out.append('<text transform="translate(16,%d) rotate(-90)" font-size="12" '
               'text-anchor="middle">%s</text>' % (mt + ph // 2, _xml(ylabel)))
    if footer:
        out.append('<text x="%d" y="%d" font-size="9" fill="#666666">%s</text>'
                   % (ml, H - 10, _xml(footer)))
    out.append('</svg>')
    with open(path, "w") as f:
        f.write("\n".join(out) + "\n")


def plots_svg(outdir, rows, ro_idx, footer):
    """knee ladder per corner + canary counts vs corner, as plain SVG."""
    series = []
    for corner in C.CORNER_NAMES:
        vals = [float(r["predicted_fmax_mhz"]) for r in rows
                if r["corner"] == corner and r["pat_name"] == "worst"
                and r["predictor"] == "sta"]
        series.append((CORNER_SHORT[corner], vals))
    svg_bars(os.path.join(outdir, "knee_ladder.svg"),
             "STA-predicted first-failure frequency ladder (pattern = worst)",
             "model %s | extracted case-analyzed STA | T_fail = T_clk - slack"
             % MODEL_VERSION,
             "predicted Fmax (MHz)", SEG_LABELS, series,
             ref=(BOARD_FMAX_MHZ, "50 MHz board ceiling"), footer=footer)
    cats = [CORNER_SHORT[c] for c in C.CORNER_NAMES]
    series = []
    for can in CANARIES:
        vals = [int(ro_idx[(c, can, READOUT_CAN_SEL)]
                    ["count_win%d" % READOUT_WIN]) for c in C.CORNER_NAMES]
        series.append((can, vals))
    svg_bars(os.path.join(outdir, "canary_counts.svg"),
             "Canary edge counts vs PVT corner",
             "can_sel=%d, win%d (%d clk cycles); counters wrap mod 65536"
             % (READOUT_CAN_SEL, READOUT_WIN, C.WINDOW_CYCLES[READOUT_WIN]),
             "edges per window", cats, series, footer=footer)


def plots_matplotlib(outdir, rows, ro_idx, footer):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(13.0, 5.2), dpi=150)
    ax = axes[0]
    width = 0.26
    for si, corner in enumerate(C.CORNER_NAMES):
        vals = [float(r["predicted_fmax_mhz"]) for r in rows
                if r["corner"] == corner and r["pat_name"] == "worst"
                and r["predictor"] == "sta"]
        xs = [i + (si - 1) * width for i in range(len(SEG_LABELS))]
        ax.bar(xs, vals, width=width, label=CORNER_SHORT[corner])
    ax.axhline(BOARD_FMAX_MHZ, color="crimson", ls="--", lw=1)
    ax.text(0.02, BOARD_FMAX_MHZ + 12, "50 MHz board ceiling",
            color="crimson", fontsize=8)
    ax.set_xticks(range(len(SEG_LABELS)))
    ax.set_xticklabels(SEG_LABELS)
    ax.set_xlabel("segment taps (seg0seg1seg2seg3)")
    ax.set_ylabel("predicted first-failure f (MHz)")
    ax.set_title("STA-predicted knee ladder (pattern = worst)", fontsize=10)
    ax.legend(fontsize=8)
    ax = axes[1]
    for si, can in enumerate(CANARIES):
        vals = [int(ro_idx[(c, can, READOUT_CAN_SEL)]
                    ["count_win%d" % READOUT_WIN]) for c in C.CORNER_NAMES]
        ax.bar([i + (si - 0.5) * 0.35 for i in range(len(C.CORNER_NAMES))],
               vals, width=0.35, label=can)
    ax.set_xticks(range(len(C.CORNER_NAMES)))
    ax.set_xticklabels([CORNER_SHORT[c] for c in C.CORNER_NAMES], fontsize=8)
    ax.set_ylabel("edges per window")
    ax.set_title("Canary counts (can_sel=%d, win%d)"
                 % (READOUT_CAN_SEL, READOUT_WIN), fontsize=10)
    ax.legend(fontsize=8)
    fig.suptitle("model %s | run %s | commit %s"
                 % (MODEL_VERSION, C.RUN_ID, C.GIT_COMMIT[:12]), fontsize=9)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    for ext, meta in (("png", {"Software": None}),
                      ("pdf", {"CreationDate": None, "ModDate": None})):
        fig.savefig(os.path.join(outdir, "plots." + ext), metadata=meta)
    plt.close(fig)


def have_matplotlib():
    try:
        import matplotlib  # noqa: F401
        return True
    except Exception:
        return False


# --- Main ---------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Build the frozen pre-silicon prediction package (P1.1).")
    ap.add_argument("--outdir", default=os.path.join(C.DATA, "predict"),
                    help="output directory (default: data/predict)")
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)

    sta_rows = read_csv(os.path.join(C.DATA, "experiment_sta.csv"))
    ro_rows = read_csv(os.path.join(C.DATA, "ro_predict.csv"))
    sdf_rows = read_csv(os.path.join(C.DATA, "sdfsim.csv"))
    prov = check_provenance([("experiment_sta.csv", sta_rows),
                             ("ro_predict.csv", ro_rows),
                             ("sdfsim.csv", sdf_rows)])

    sta_idx = load_sta(sta_rows)
    ro_idx, ro_fit = load_ro(ro_rows)
    sdf_bounds, invalid_ro = load_sdf(sdf_rows)

    sdf_ref_ops = int(next(r["ops"] for r in sdf_rows if not r["sdf"].strip()))

    rows = build_predictions(sta_idx, ro_idx)
    cross = sta_vs_sdf(sta_idx, sdf_bounds)
    ratios = gen_mat_ratios(ro_idx)
    lut = pred_lut(rows)

    out = args.outdir
    write_predictions_csv(os.path.join(out, "predictions.csv"), rows)

    json_doc = {
        "model_version": MODEL_VERSION,
        "generated_utc": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
        "provenance": dict(prov, clk_period_ns=C.CLK_PERIOD_NS,
                           frame_cycles=C.FRAME_CYCLES,
                           nominal_corner=NOMINAL_CORNER,
                           readout={"can_sel": READOUT_CAN_SEL,
                                    "win": READOUT_WIN,
                                    "window_cycles":
                                        C.WINDOW_CYCLES[READOUT_WIN]},
                           counter_bits=16, counter_max=COUNTER_MAX),
        "predictors": {
            "sta": "per-corner case-analyzed extracted STA: T_fail = T_clk - "
                   "slack; f = 1e3/T_fail MHz (docs/prediction-model.md)",
            "ro_gen": "nominal STA ladder scaled by ro_gen count ratio "
                      "N(corner)/N(nom) at can_sel=%d, win%d"
                      % (READOUT_CAN_SEL, READOUT_WIN),
            "ro_mat": "nominal STA ladder scaled by ro_mat count ratio "
                      "N(corner)/N(nom) at can_sel=%d, win%d"
                      % (READOUT_CAN_SEL, READOUT_WIN),
        },
        "calibration": {
            "method": "one-point multiplicative (docs/prediction-model.md)",
            "primary_anchor": {"corner": NOMINAL_CORNER,
                               "seg_label": "3333", "pattern": "worst",
                               "v_volt": 1.2, "t_celsius": 25},
            "fallback_anchor": {"corner": "nom_slow_1p08V_125C",
                                "seg_label": "3333", "pattern": "worst",
                                "v_volt": 1.08,
                                "t_celsius": "maximum reachable; record actual"},
            "censor_if_unreachable": True,
            "placeholder_k": CAL_K_PLACEHOLDER,
            "note": "post-silicon run substitutes measured k_x per predictor "
                    "at the first reachable predeclared anchor and re-emits; "
                    "nothing else changes",
        },
        "notes": [
            "Frame = 19 clk cycles (frame_cnt 0..18); one timed DUT operation "
            "per frame.",
            "Canary counters are 16-bit and wrap mod 65536; sat_win fields are "
            "model overflow-risk flags, not hardware saturation flags; "
            "win0 = 256 clk cycles.",
            "The sdfsim.csv RO cross-check row (FORCE_CAN off) is INVALID for "
            "model purposes: RO loop cells carry hard 0.000 SDF delays because "
            "src/pnr.sdc disables RO timing arcs "
            "(docs/ro-sdf-crosscheck-diagnosis.md); its gen_cnt/mat_cnt are "
            "excluded.",
            "The SDF boundary is IOPATH-only annotated (no wire interconnect): "
            "the sim boundary is optimistic; positive err_sta_minus_mid_ns = "
            "STA more conservative than sim.",
        ],
        "sanity": {
            "rows_experiment_sta": len(sta_rows),
            "rows_ro_predict": len(ro_rows),
            "rows_sdfsim": len(sdf_rows),
            "monotonic_knee_vs_taps": True,
            "provenance_consistent": True,
            "zero_delay_reference_errors": 0,
            "readout_counts_fit_16bit": ro_fit[READOUT_WIN]["fits_16bit"],
        },
        "cross_checks": {
            "sta_vs_sdf_seg3333_worst": cross,
            "canary_16bit_fit": ro_fit,
            "gen_over_mat_win0": ratios,
        },
        "rows": rows,
    }
    if invalid_ro:
        json_doc["invalid_rows"] = [
            {"log": r["log"],
             "reason": "FORCE_CAN off: RO cells carry hard 0.000 SDF delays; "
                       "counts are race artifacts, excluded "
                       "(docs/ro-sdf-crosscheck-diagnosis.md)"}
            for r in invalid_ro]
    with open(os.path.join(out, "predictions.json"), "w") as f:
        json.dump(json_doc, f, indent=1)
        f.write("\n")

    n_in = {"sta": len(sta_rows), "ro": len(ro_rows), "sdf": len(sdf_rows)}
    write_summary(os.path.join(out, "summary.md"), prov, n_in, cross, ro_idx,
                  ratios, lut, sta_idx, sdf_ref_ops)
    write_plot_data(os.path.join(out, "plot_data.csv"), rows, ro_idx)

    footer = ("model %s | run %s | commit %s"
              % (MODEL_VERSION, C.RUN_ID, C.GIT_COMMIT[:12]))
    if have_matplotlib():
        plots_matplotlib(out, rows, ro_idx, footer)
        plot_mode = "plots.png/plots.pdf (matplotlib)"
    else:
        plots_svg(out, rows, ro_idx, footer)
        plot_mode = "knee_ladder.svg + canary_counts.svg (hand-rolled SVG)"

    anchor = next(r for r in rows if r["corner"] == NOMINAL_CORNER
                  and r["seg_label"] == "3333" and r["pat_name"] == "worst"
                  and r["predictor"] == "sta")
    print("predict_model: wrote %d prediction rows to %s" % (len(rows), out))
    print("  plots: %s" % plot_mode)
    print("  spot-checks:")
    print("    anchor (nom, seg3333, worst) STA knee = %s MHz; "
          "slow-corner STA knee = %s MHz (source 39.339)"
          % (anchor["predicted_fmax_mhz"],
             lut[("nom_slow_1p08V_125C", ANCHOR_SEGS, ANCHOR_PATTERN, "sta")]))
    print("    canary win0 counts (can_sel=%d): %s"
          % (READOUT_CAN_SEL, ", ".join(
              "%s %s=%d" % (CORNER_SHORT[corner], can, ratios[corner][
                  "gen_count" if can == "ro_gen" else "mat_count"])
              for corner in C.CORNER_NAMES for can in CANARIES)))
    for c in cross:
        print("    STA-vs-SDF %s: STA %s ns vs sim bracket [%g, %g] ns -> "
              "err %s ns (positive = STA conservative vs IOPATH-only sim)"
              % (c["corner"], c["sta_t_fail_ns"], c["sdf_last_fail_ns"],
                 c["sdf_first_pass_ns"], c["err_sta_minus_mid_ns"]))


if __name__ == "__main__":
    main()
