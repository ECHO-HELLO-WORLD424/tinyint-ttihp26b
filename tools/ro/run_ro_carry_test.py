#!/usr/bin/env python3
"""Gate 3 checks: counter carry coverage, stop/settle/readout and control cases.

The measurement-window sweep answers "does the counter count the edges its own
window offers".  This tool answers the remaining counter questions from
`docs/rtl-freeze-checklist.md` gate 3:

  carry     an extended gate-open run (a targeted carry test, *not* a window
            test) long enough for the upper ripple stages to toggle, so the
            whole 16-stage chain is exercised after reset;
  settle    per-stage ripple delay measured from a completed window run: the
            time between the ring stopping and the last counter bit settling,
            compared with the protocol's readout interval;
  mask      FORCE_CAN raised mid-run: the loop stalls and the counter holds;
  freeze    host FREEZE during an unfinished window: the gate closes, the
            counter holds, and counting resumes when FREEZE is released;
  reset     reset asserted again during an unfinished window: the counter is
            cleared and counting restarts.

Every case is analysed with `analyse_ro_count.py`, and the raw JSON keeps the
per-bit transition times so the ripple settling can be re-derived.

Usage:
  run_ro_carry_test.py --kind carry --corner nom_fast_1p32V_m40C --canary ro_gen
      --can-sel 0 --extended-ns 30000 --outdir runs/freeze-validation/carry
  run_ro_carry_test.py --kind control --outdir runs/freeze-validation/control
"""

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import analyse_ro_count as ana  # noqa: E402


def load_json(path, default):
    import json as _json
    try:
        with open(path) as fh:
            return _json.load(fh)
    except (OSError, ValueError):
        return default
import run_ro_count_case as cc  # noqa: E402
import run_ro_spice_case as rc  # noqa: E402


def run_one(kind, corner, canary, can_sel, outdir, tclk_ns=20.0, phase=0.25,
            tstep_ps=5.0, extended_ns=None, mask_at_ns=None,
            freeze_windows=(), reset_windows=(), loopdir="runs/count-loops",
            extra_settle_ns=None):
    info = cc.run_window(canary, can_sel, corner, loopdir, outdir,
                         tclk_ns=tclk_ns, win_sel=0, release_phase=phase,
                         tstep_ps=tstep_ps, solver="klu",
                         extended_ns=extended_ns, mask_at_ns=mask_at_ns,
                         freeze_windows=freeze_windows,
                         reset_windows=reset_windows,
                         extra_settle_ns=extra_settle_ns,
                         tag_suffix=f"_{kind}")
    if info["rc"] != 0:
        return dict(kind=kind, corner=corner, canary=canary, can_sel=can_sel,
                    status="ngspice_failed", rc=info["rc"], log=info["log"])
    loop_vec = "v(x1.%s)" % rc.escape_node(info["loop_port"])
    res = ana.analyse(info["raw"], vdd=info["vdd"], loop_node=loop_vec)
    res.update(kind=kind, corner=corner, canary=canary, can_sel=can_sel,
               deck=info["deck"], raw=info["raw"], log=info["log"],
               wall_s=info["wall_s"], tstop_ns=info["tstop_ns"],
               en_rise_ns=info["en_rise_ns"], en_fall_ns=info["en_fall_ns"],
               extended_ns=extended_ns, mask_at_ns=mask_at_ns,
               freeze_windows=list(freeze_windows),
               reset_windows=list(reset_windows),
               cycles_open=info["cycles_open"],
               role_check_ok=info["role_check"]["ok"])
    return res


def ripple_settling(res):
    """Per-stage ripple delay and the implied settling of the whole chain."""
    per_bit = res.get("per_bit") or {}
    transitions = {}
    for b, d in per_bit.items():
        ts = [d["first_transition_ns"], d["last_transition_ns"]]
        transitions[int(b)] = ts
    out = dict(per_stage_delay_ns={}, max_stage_delay_ns=None,
               first_stage_delay_ns=None,
               implied_15_stage_settle_ns=None,
               last_bit_transition_ns=res.get("last_bit_transition_ns"),
               gate_close_ns=res.get("t_en_fall_ns"),
               settle_after_gate_close_ns=None)
    for b in sorted(per_bit):
        if b == 0:
            continue
        prev = per_bit.get(str(b - 1)) or per_bit.get(b - 1)
        if not prev:
            continue
        d = per_bit[b]["last_transition_ns"]
        p = prev["last_transition_ns"]
        if d is not None and p is not None and d > p:
            out["per_stage_delay_ns"][b] = round(d - p, 5)
    if out["per_stage_delay_ns"]:
        out["max_stage_delay_ns"] = max(out["per_stage_delay_ns"].values())
        out["first_stage_delay_ns"] = out["per_stage_delay_ns"].get(1)
        out["implied_15_stage_settle_ns"] = round(
            15 * out["max_stage_delay_ns"], 4)
    if res.get("last_bit_transition_ns") is not None and \
            res.get("t_en_fall_ns") is not None:
        out["settle_after_gate_close_ns"] = round(
            res["last_bit_transition_ns"] - res["t_en_fall_ns"], 4)
    return out


def control_cases(outdir, loopdir, tclk_ns=20.0):
    """FORCE_CAN, FREEZE/resume and reset during an unfinished window."""
    cases = []
    # FORCE_CAN at ~40 % into the window: loop stalls, counter holds.
    cases.append(dict(kind="mask", corner="nom_typ_1p20V_25C",
                      canary="ro_gen", can_sel=3, tclk_ns=tclk_ns,
                      mask_at_ns=20.0 + 0.25 * tclk_ns + 3 * tclk_ns + 0.4 * 253 * tclk_ns,
                      extra_settle_ns=60.0))
    # FREEZE for 40 clock cycles, 25 % into the window.
    t_rise = 20.0 + 0.25 * tclk_ns + 3 * tclk_ns
    f0 = t_rise + 0.25 * 253 * tclk_ns
    cases.append(dict(kind="freeze", corner="nom_typ_1p20V_25C",
                      canary="ro_gen", can_sel=3, tclk_ns=tclk_ns,
                      freeze_windows=[(f0, f0 + 40 * tclk_ns)],
                      extra_settle_ns=60.0))
    # Reset asserted for 5 clock cycles, 25 % into the window.
    cases.append(dict(kind="reset", corner="nom_typ_1p20V_25C",
                      canary="ro_gen", can_sel=3, tclk_ns=tclk_ns,
                      reset_windows=[(f0, f0 + 5 * tclk_ns)],
                      extra_settle_ns=60.0))
    return cases


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", default="carry",
                    choices=["carry", "control"])
    ap.add_argument("--corner", default="nom_fast_1p32V_m40C")
    ap.add_argument("--canary", default="ro_gen")
    ap.add_argument("--can-sel", type=int, default=0)
    ap.add_argument("--extended-ns", type=float, default=30000.0)
    ap.add_argument("--tclk-ns", type=float, default=20.0)
    ap.add_argument("--phase", type=float, default=0.25)
    ap.add_argument("--tstep-ps", type=float, default=5.0)
    ap.add_argument("--loopdir", default="runs/count-loops")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--json", default=None)
    ap.add_argument("--reanalyse", action="store_true",
                    help="re-analyse existing rawfiles instead of re-running "
                         "the transient (used after an analyzer fix)")
    a = ap.parse_args()

    os.makedirs(a.outdir, exist_ok=True)
    rows = []
    if a.reanalyse:
        existing = load_json(a.json or os.path.join(
            a.outdir, f"{a.kind}_result.json"), [])
        for r in existing:
            raw = r.get("raw")
            if not raw or not os.path.exists(raw):
                continue
            res = ana.analyse(raw, vdd=r.get("vdd", 1.2),
                              loop_node="v(x1.%s)" % rc.escape_node(
                                  r.get("loop_node_expected") or
                                  r.get("loop_port") or ""))
            res["ripple"] = ripple_settling(res)
            res.update({k: r.get(k) for k in
                        ("kind", "corner", "canary", "can_sel", "deck", "log",
                         "wall_s", "tstop_ns", "en_rise_ns", "en_fall_ns",
                         "extended_ns", "mask_at_ns", "freeze_windows",
                         "reset_windows", "cycles_open", "role_check_ok")
                        if r.get(k) is not None})
            rows.append(res)
            print(json.dumps({k: res.get(k) for k in
                              ("kind", "status", "counter_final",
                               "ring_edges_in_window", "count_ok",
                               "n_reset_releases")}), flush=True)
        json.dump(rows, open(a.json or os.path.join(
            a.outdir, f"{a.kind}_result.json"), "w"), indent=1, default=str)
        return 0 if all(r.get("count_ok") for r in rows) else 1
    if a.kind == "carry":
        t0 = time.time()
        r = run_one("carry", a.corner, a.canary, a.can_sel, a.outdir,
                    tclk_ns=a.tclk_ns, phase=a.phase, tstep_ps=a.tstep_ps,
                    extended_ns=a.extended_ns, loopdir=a.loopdir)
        r["ripple"] = ripple_settling(r)
        rows.append(r)
        print(json.dumps({k: r.get(k) for k in
                          ("kind", "corner", "canary", "can_sel", "status",
                           "counter_final", "ring_edges_in_window",
                           "n_bits_saved", "coverage_complete",
                           "unexercised_bits", "f_count_mhz", "wall_s")},
                         default=str), flush=True)
    else:
        for c in control_cases(a.outdir, a.loopdir, a.tclk_ns):
            r = run_one(c["kind"], c["corner"], c["canary"], c["can_sel"],
                        a.outdir, tclk_ns=c.get("tclk_ns", a.tclk_ns),
                        tstep_ps=a.tstep_ps, mask_at_ns=c.get("mask_at_ns"),
                        freeze_windows=c.get("freeze_windows", ()),
                        reset_windows=c.get("reset_windows", ()),
                        extra_settle_ns=c.get("extra_settle_ns"),
                        loopdir=a.loopdir)
            r["ripple"] = ripple_settling(r)
            rows.append(r)
            print(json.dumps({k: r.get(k) for k in
                              ("kind", "status", "counter_final",
                               "ring_edges_in_window", "settled",
                               "wall_s")}, default=str), flush=True)
    out = a.json or os.path.join(a.outdir, f"{a.kind}_result.json")
    existing = []
    if os.path.exists(out):
        with open(out) as fh:
            existing = json.load(fh)
    json.dump(existing + rows, open(out, "w"), indent=1, default=str)
    print("wrote " + out)
    return 0 if all(r.get("count_ok") for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
