#!/usr/bin/env python3
"""Measure how much the omitted wire capacitance changes the ring rate.

The counter-inclusive decks are cell-level: the Magic spiceextraction carries
transistor-level cells with cell-internal parasitics but no inter-cell wire RC
(no RC extraction was run for this tile).  `add_wire_caps.py` builds a variant
of the loop subcircuit with the SPEF's lumped capacitance added inside the
`.subckt`, so this tool can run *the same short window* with and without it and
report the frequency change directly, instead of arguing from a capacitance
ratio.

This bounds the omission; it is not post-route distributed-RC signoff.

Usage:
  run_wirecap_sensitivity.py --loopdir runs/count-loops --capdir runs/freeze-validation
      --outdir runs/freeze-validation/wirecap [--window-ns 400]
"""

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import analyse_ro_count as ana  # noqa: E402
import run_ro_count_case as cc  # noqa: E402
import run_ro_spice_case as rc  # noqa: E402

CASES = [("nom_typ_1p20V_25C", "ro_gen", 0), ("nom_typ_1p20V_25C", "ro_mat", 3),
         ("nom_fast_1p32V_m40C", "ro_gen", 0),
         ("nom_slow_1p08V_125C", "ro_mat", 3)]


def one(corner, canary, can_sel, loop_sp, outdir, window_ns, tstep_ps=5.0,
        tag="", loopdir="runs/count-loops"):
    """`loop_sp` is the subcircuit to simulate; `loopdir` supplies metadata."""
    entry = json.load(open(os.path.join(loopdir, "ro_loop.json")))[
        "canaries"][f"{canary}_sel{can_sel}"]
    portmap = entry["portmap"]
    bits = cc.bit_ports(portmap)
    lp = cc.loop_port(portmap, canary, loop_sp, entry.get("loop_node")) or \
        entry["loop_node"]
    roles = entry.get("control_roles") or {}
    chk = cc.verify_control_roles(canary, can_sel, entry)
    if not chk["ok"]:
        raise SystemExit("role check failed: " + "; ".join(chk["problems"]))
    c = cc.CORNERS[corner]
    en_rise, en_fall = 85.0, 85.0 + window_ns
    tstop = en_fall + 120.0
    raw = os.path.join(outdir, f"{corner}_{canary}_sel{can_sel}{tag}.raw")
    deck = os.path.join(outdir, f"{corner}_{canary}_sel{can_sel}{tag}.sp")
    open(deck, "w").write(cc.make_window_deck(
        canary, can_sel, corner, loop_sp, raw, portmap, lp, bits, tstop,
        tstep_ps, "klu", 20.0, en_rise, en_fall, 0.02, roles, set(), [],
        uic=True))
    # `main()` writes the shared .spiceinit before the parallel section; only
    # (re)write it here when it is absent or stale, so concurrent workers
    # cannot truncate it between an ngspice start and its read.
    init = os.path.join(outdir, ".spiceinit")
    text = "".join(rc.spiceinit_lines())
    if not os.path.exists(init) or open(init).read() != text:
        open(init, "w").write(text)
    env = dict(os.environ)
    env["PDK_ROOT"] = rc.PDK
    env["PDK"] = "ihp-sg13g2"
    env["LD_LIBRARY_PATH"] = rc.NGSPICE_LIB + ":" + env.get("LD_LIBRARY_PATH", "")
    env["SPICE_LIB_DIR"] = rc.NGSPICE_SCRIPTS
    t0 = time.time()
    import subprocess
    with open(os.path.join(outdir, f"{os.path.basename(deck)[:-3]}.log"),
              "w") as lf:
        p = subprocess.run([rc.NGSPICE, "-b", os.path.abspath(deck)],
                           stdout=lf, stderr=subprocess.STDOUT, env=env,
                           cwd=outdir)
    wall = time.time() - t0
    r = ana.analyse(raw, vdd=c["vdd"],
                    loop_node="v(x1.%s)" % rc.escape_node(lp))
    return dict(corner=corner, canary=canary, can_sel=can_sel, tag=tag,
                rc=p.returncode, wall_s=round(wall, 1),
                status=r.get("status"), count=r.get("counter_final"),
                edges=r.get("ring_edges_in_window"),
                f_mhz=r.get("f_count_mhz"),
                period_ns=r.get("period_median_ns"),
                cv=r.get("steady_std_over_mean"),
                n_modes=r.get("steady_n_modes"),
                count_ok=r.get("count_ok"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loopdir", default="runs/count-loops")
    ap.add_argument("--capdir", default="runs/freeze-validation")
    ap.add_argument("--outdir", default="runs/freeze-validation/wirecap")
    ap.add_argument("--window-ns", type=float, default=400.0)
    ap.add_argument("--tstep-ps", type=float, default=5.0)
    ap.add_argument("--jobs", type=int, default=1,
                    help="cases to run in parallel (each ngspice run is "
                         "single-threaded; the decks and rawfiles are "
                         "per-case, so only the shared .spiceinit is touched)")
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    # One .spiceinit serves every case in this output directory; write it once
    # so parallel workers cannot race on it.
    open(os.path.join(a.outdir, ".spiceinit"), "w").write(
        "".join(rc.spiceinit_lines()))
    todo = []
    for corner, canary, can_sel in CASES:
        base = os.path.join(a.loopdir, f"{canary}_sel{can_sel}_loop.sp")
        capped = os.path.join(a.capdir, f"{canary}_sel{can_sel}_wirecap.sp")
        for tag, loop_sp in (("_nocap", base), ("_wirecap", capped)):
            todo.append((corner, canary, can_sel, tag, loop_sp))
    rows = []
    if a.jobs > 1:
        from concurrent.futures import ThreadPoolExecutor

        def run(job):
            corner, canary, can_sel, tag, loop_sp = job
            if not os.path.exists(loop_sp):
                return dict(corner=corner, canary=canary, can_sel=can_sel,
                            tag=tag, status="missing_" + loop_sp)
            return one(corner, canary, can_sel, loop_sp, a.outdir,
                       a.window_ns, a.tstep_ps, tag, a.loopdir)

        with ThreadPoolExecutor(max_workers=a.jobs) as ex:
            for r in ex.map(run, todo):
                rows.append(r)
                print(json.dumps(r), flush=True)
    else:
        for corner, canary, can_sel, tag, loop_sp in todo:
            if not os.path.exists(loop_sp):
                rows.append(dict(corner=corner, canary=canary, can_sel=can_sel,
                                 tag=tag, status="missing_" + loop_sp))
                continue
            r = one(corner, canary, can_sel, loop_sp, a.outdir, a.window_ns,
                    a.tstep_ps, tag, a.loopdir)
            rows.append(r)
            print(json.dumps(r), flush=True)
    # Pairwise comparison.
    pairs = []
    for corner, canary, can_sel in CASES:
        base = next((r for r in rows if r.get("corner") == corner and
                     r.get("canary") == canary and r.get("can_sel") == can_sel
                     and r.get("tag") == "_nocap"), None)
        cap = next((r for r in rows if r.get("corner") == corner and
                    r.get("canary") == canary and r.get("can_sel") == can_sel
                    and r.get("tag") == "_wirecap"), None)
        if base and cap and base.get("f_mhz") and cap.get("f_mhz"):
            pairs.append(dict(corner=corner, canary=canary, can_sel=can_sel,
                              f_nocap_mhz=round(base["f_mhz"], 3),
                              f_wirecap_mhz=round(cap["f_mhz"], 3),
                              delta_pct=round(100.0 * (cap["f_mhz"] -
                                                       base["f_mhz"]) /
                                              base["f_mhz"], 3),
                              cv_nocap=base.get("cv"), cv_wirecap=cap.get("cv")))
    out = dict(window_ns=a.window_ns, tstep_ps=a.tstep_ps, runs=rows,
               comparison=pairs)
    path = a.json or os.path.join(a.outdir, "wirecap_sensitivity.json")
    json.dump(out, open(path, "w"), indent=1)
    print("\ncomparison:")
    for p in pairs:
        print(f"  {p['corner']:22s} {p['canary']:7s} sel{p['can_sel']} "
              f"{p['f_nocap_mhz']:9.2f} -> {p['f_wirecap_mhz']:9.2f} MHz "
              f"({p['delta_pct']:+.2f} %)  cv {p['cv_nocap']} -> "
              f"{p['cv_wirecap']}")
    print("wrote " + path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
