#!/usr/bin/env python3
"""Gate 3 stop-phase sweep: close the RO gate at many phases of the ring period.

The freeze checklist's gate 3 retains one coverage gap: "close the RO enable at
multiple phases of its oscillation".  The measurement-window sweep varies
`release_phase`, but the ring is gated off and restarted by the same `en` edge
in every case, so -- as `measure_stop_phase.py` confirms from the archived
waveforms -- the stop phase is *identical* across the three startups of a
configuration (spread 0.000) and only changes with the host clock period.

This tool varies the quantity that actually matters: `en` falls a declared
fraction of the ring period after `en` rises, so the phase at which the loop is
gated off is swept directly.  `en` rise -> `en` fall is held at an integer
number of ring periods plus `phase * period`, so the window length is the same
in every case and only the stop phase changes.

Each case is analysed by `analyse_ro_count.py`: the accepted verdict requires
the decoded count to equal the number of rising edges the counter was offered,
every bit to be at a valid logic level, and the ripple to be settled.  The stop
transient itself is classified by `classify_stop_transient.py` (runt pulses).

Usage:
  sweep_stop_phase.py --corner nom_slow_1p08V_125C --canary ro_mat --can-sel 3
      --periods 10 --phases 20 --tstep-ps 5 --jobs 6
      --outdir runs/freeze-validation/stop-phase-sweep
"""

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)

import analyse_ro_count as ana  # noqa: E402
import run_ro_count_case as cc  # noqa: E402
import run_ro_spice_case as rc  # noqa: E402


def one(corner, canary, can_sel, phase, periods, period_ns, loopdir, outdir,
        tstep_ps, en_rise_ns=100.0, edge_ns=0.02):
    """One stop-phase case: `en` closes `periods + phase` ring periods after rise."""
    entry = json.load(open(os.path.join(loopdir, "ro_loop.json")))[
        "canaries"][f"{canary}_sel{can_sel}"]
    portmap = entry["portmap"]
    bits = cc.bit_ports(portmap)
    loop_sp = os.path.join(loopdir, f"{canary}_sel{can_sel}_loop.sp")
    lp = cc.loop_port(portmap, canary, loop_sp, entry.get("loop_node")) or \
        entry["loop_node"]
    roles = entry.get("control_roles") or {}
    chk = cc.verify_control_roles(canary, can_sel, entry)
    if not chk["ok"]:
        raise SystemExit("role check failed: " + "; ".join(chk["problems"]))
    c = cc.CORNERS[corner]
    tag = f"{corner}_{canary}_sel{can_sel}_ph{phase:.4f}"
    raw = os.path.join(outdir, tag + ".raw")
    deck = os.path.join(outdir, tag + ".sp")
    en_fall_ns = en_rise_ns + (periods + phase) * period_ns
    tstop = en_fall_ns + 40.0
    open(deck, "w").write(cc.make_window_deck(
        canary, can_sel, corner, loop_sp, raw, portmap, lp, bits, tstop,
        tstep_ps, "klu", 0.0, en_rise_ns, en_fall_ns, edge_ns, roles, set(),
        [], uic=False))
    import subprocess
    env = dict(os.environ)
    env["PDK_ROOT"] = rc.PDK
    env["PDK"] = "ihp-sg13g2"
    env["LD_LIBRARY_PATH"] = rc.NGSPICE_LIB + ":" + env.get("LD_LIBRARY_PATH", "")
    env["SPICE_LIB_DIR"] = rc.NGSPICE_SCRIPTS
    t0 = time.time()
    with open(os.path.join(outdir, tag + ".log"), "w") as lf:
        subprocess.run([rc.NGSPICE, "-b", os.path.abspath(deck)],
                       stdout=lf, stderr=subprocess.STDOUT, env=env,
                       cwd=outdir, check=False)
    wall = time.time() - t0
    res = ana.analyse(raw, vdd=c["vdd"],
                      loop_node="v(x1.%s)" % rc.escape_node(lp))
    res.update(corner=corner, canary=canary, can_sel=can_sel,
               phase_requested=round(phase, 4), periods=periods,
               period_ns=period_ns, en_rise_ns=en_rise_ns,
               en_fall_ns=round(en_fall_ns, 4), wall_s=round(wall, 1),
               deck=os.path.relpath(deck, REPO),
               ramp_ns=round((periods + phase) * period_ns, 4))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corner", default="nom_slow_1p08V_125C")
    ap.add_argument("--canary", default="ro_mat")
    ap.add_argument("--can-sel", type=int, default=3)
    ap.add_argument("--periods", type=float, default=10.0)
    ap.add_argument("--period-ns", type=float, required=True,
                    help="ring period to space the sweep with (measured)")
    ap.add_argument("--phases", type=int, default=20)
    ap.add_argument("--tstep-ps", type=float, default=5.0)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--loopdir", default=os.path.join(REPO, "runs/count-loops"))
    ap.add_argument("--outdir",
                    default=os.path.join(REPO,
                                         "runs/freeze-validation/stop-phase-sweep"))
    ap.add_argument("--json",
                    default=os.path.join(REPO, "data/safe10/freeze",
                                         "stop_phase_sweep.json"))
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    open(os.path.join(a.outdir, ".spiceinit"), "w").write(
        "".join(rc.spiceinit_lines()))
    phases = [i / a.phases for i in range(a.phases)]
    todo = [(p,) for p in phases]
    rows = []

    def run(job):
        (p,) = job
        return one(a.corner, a.canary, a.can_sel, p, a.periods, a.period_ns,
                   a.loopdir, a.outdir, a.tstep_ps)

    def report(r):
        rows.append(r)
        print(json.dumps({k: r.get(k) for k in
                          ("phase_requested", "status", "count_ok",
                           "counter_final", "ring_edges_in_window",
                           "settled", "levels_valid", "wall_s")}), flush=True)

    if a.jobs > 1:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=a.jobs) as ex:
            for r in ex.map(run, todo):
                report(r)
    else:
        for job in todo:
            report(run(job))
    summary = dict(
        tool="tools/ro/sweep_stop_phase.py",
        purpose="gate 3 stop-phase sweep: close `en` at many phases of the ring",
        corner=a.corner, canary=a.canary, can_sel=a.can_sel,
        periods=a.periods, period_ns=a.period_ns, tstep_ps=a.tstep_ps,
        n_phases=len(phases),
        all_count_ok=all(r.get("count_ok") for r in rows),
        all_settled=all(r.get("settled") for r in rows),
        all_levels_valid=all(r.get("levels_valid") for r in rows),
        statuses=sorted(set(r.get("status") for r in rows)),
        cases=rows)
    os.makedirs(os.path.dirname(a.json), exist_ok=True)
    json.dump(summary, open(a.json, "w"), indent=1, default=str)
    print(json.dumps({k: summary[k] for k in
                      ("n_phases", "all_count_ok", "all_settled",
                       "all_levels_valid", "statuses")}, indent=1))
    print("wrote " + a.json)
    return 0 if summary["all_count_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
