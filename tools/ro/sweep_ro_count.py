#!/usr/bin/env python3
"""Run the counter-inclusive RO transient test over a set of cases.

Each case is one (corner, canary, can_sel): the ring plus its ripple edge
counter, reset released, ring running, counter bits saved.  The result answers
whether the on-chip counter counts the ring's edges (see
`docs/ro-counter-spice-validation.md`), which the f_osc sweep in
`run_ro_spice_case.py` cannot do because it holds the counter static.

The per-case transient length is sized from a period estimate (normally the
measured `data/*/spice/spice_ro.csv` of the f_osc sweep) so every case observes
a comparable number of ring periods.

Usage:
  sweep_ro_count.py --loopdir <dir from extract_ro_loop.py --counter>
                    --outdir data/safe10/count [--periods 32] [--jobs 4]
                    [--only ro_gen:0] [--from-raw]
"""

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import analyse_ro_count as analyse_count  # noqa: E402
import run_ro_count_case as count_case  # noqa: E402
import run_ro_spice_case as ring_case  # noqa: E402

CORNERS = list(ring_case.CORNERS)


def load_periods(spice_csv):
    """{(corner, canary, can_sel): period_s} from an f_osc result table."""
    out = {}
    if not spice_csv or not os.path.exists(spice_csv):
        return out
    for row in csv.DictReader(open(spice_csv)):
        try:
            out[(row["corner"], row["canary"], int(row["can_sel"]))] = \
                float(row["period_ns"]) * 1e-9
        except (KeyError, ValueError):
            continue
    return out


def run_case(args):
    (corner, canary, can_sel, loopdir, outdir, periods, tstep_ps, period_s,
     solver, reset_release_ns) = args
    # Each case's deck, log and rawfile go under <outdir>/cases so a count-case
    # rawfile can never be confused with the same-tag f_osc rawfile.
    case_dir = os.path.join(outdir, "cases")
    os.makedirs(case_dir, exist_ok=True)
    t0 = time.time()
    try:
        info = count_case.run(canary, can_sel, corner, loopdir, case_dir,
                              periods=periods, tstep_ps=tstep_ps,
                              solver=solver, period_hint_s=period_s,
                              reset_release_ns=reset_release_ns)
    except SystemExit as exc:                      # missing extraction
        return dict(corner=corner, canary=canary, can_sel=can_sel,
                    status="setup_error", detail=str(exc),
                    wall_s=round(time.time() - t0, 2))
    if info["rc"] != 0:
        return dict(corner=corner, canary=canary, can_sel=can_sel,
                    status="ngspice_failed", rc=info["rc"],
                    log=info["log"], wall_s=info["wall_s"])
    loop_vec = "v(x1.%s)" % ring_case.escape_node(info["loop_port"])
    res = analyse_count.analyse(info["raw"], vdd=info["vdd"],
                                reset_release_ns=info["reset_release_ns"],
                                loop_node=loop_vec)
    res.update(corner=corner, canary=canary, can_sel=can_sel,
               deck=info["deck"], raw=info["raw"], log=info["log"],
               tstop_ns=info["tstop_ns"], tstep_ps=info["tstep_ps"],
               wall_s=info["wall_s"], ring_cells=info["ring_cells"],
               n_chain=len(info["chain"]),
               period_hint_ns=period_s * 1e9,
               control_roles=info["control_roles"])
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loopdir", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--periods", type=float, default=32.0)
    ap.add_argument("--tstep-ps", type=float, default=5.0)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--solver", default="klu", choices=[None, "klu", "sparse"])
    ap.add_argument("--reset-release-ns", type=float, default=2.0)
    ap.add_argument("--periods-from", default=None,
                    help="f_osc result CSV to size each case from "
                         "(default: data/safe10/spice/spice_ro.csv if present)")
    ap.add_argument("--only", default=None, help="canary:can_sel filter")
    ap.add_argument("--corners", default=None, help="comma-separated subset")
    ap.add_argument("--tstop-cap-ns", type=float, default=4000.0)
    a = ap.parse_args()

    os.makedirs(a.outdir, exist_ok=True)
    count_case.EXTRA_NETS = {}
    periods_csv = a.periods_from
    if periods_csv is None:
        guess = os.path.join(os.path.dirname(HERE), "..", "data", "safe10",
                             "spice", "spice_ro.csv")
        periods_csv = os.path.normpath(guess)
    periods = load_periods(periods_csv)
    corners = a.corners.split(",") if a.corners else CORNERS

    jobs = []
    for corner in corners:
        for canary in ("ro_gen", "ro_mat"):
            for can_sel in range(4):
                if a.only and a.only != f"{canary}:{can_sel}":
                    continue
                period_s = periods.get((corner, canary, can_sel))
                if period_s is None:
                    # fall back to a conservative 2 GHz estimate
                    period_s = 0.5e-9
                jobs.append((corner, canary, can_sel, a.loopdir, a.outdir,
                             a.periods, a.tstep_ps, period_s, a.solver,
                             a.reset_release_ns))
    print(f"running {len(jobs)} counter-inclusive cases with {a.jobs} workers")
    results = []
    with ProcessPoolExecutor(max_workers=a.jobs) as pool:
        futs = {pool.submit(run_case, j): j for j in jobs}
        for fut in as_completed(futs):
            r = fut.result()
            results.append(r)
            print(f"  {r['corner']:22s} {r['canary']:7s} sel{r['can_sel']} "
                  f"-> {r.get('status'):10s} "
                  f"f={r.get('f_osc_mhz', float('nan')):.1f} MHz "
                  f"count={r.get('counter_final')} "
                  f"err={r.get('count_error_edges')} "
                  f"({r.get('wall_s')} s)")
    results.sort(key=lambda r: (r["corner"], r["canary"], r["can_sel"]))
    csv_path = os.path.join(a.outdir, "ro_count.csv")
    cols = ["corner", "canary", "can_sel", "status", "vdd", "f_osc_mhz",
            "period_ns", "n_rise", "q0_negedges", "counter_final",
            "counter_final_hex", "ring_edges_in_count_window",
            "count_error_edges", "count_ratio", "expected_periods_in_window",
            "count_matches_ring_edges", "count_matches_period_estimate",
            "ripple_stage_rates_ok", "count_window_ns", "n_bits_saved",
            "ring_cells", "n_chain", "control_roles", "tstop_ns", "tstep_ps",
            "period_hint_ns", "wall_s", "deck", "raw", "log"]
    with open(csv_path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in results:
            r = dict(r)
            r["control_roles"] = json.dumps(r.get("control_roles", {}),
                                            sort_keys=True)
            w.writerow(r)
    json_path = os.path.join(a.outdir, "ro_count.json")
    with open(json_path, "w") as fh:
        json.dump(results, fh, indent=1)
    ok = sum(1 for r in results if r.get("status") == "ok")
    print(f"\n{ok}/{len(results)} cases counted the ring edges correctly")
    print(f"wrote {csv_path} and {json_path}")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
