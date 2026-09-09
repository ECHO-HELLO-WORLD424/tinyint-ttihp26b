#!/usr/bin/env python3
"""Run the full 3 corners x 4 can_sel x 2 canaries = 24 case SPICE sweep.

Each case is one reduced-deck transient of one ring oscillator, driven by
run_case.py.  Cases are independent, so they are executed in parallel across
worker processes; ngspice itself is effectively single-threaded for these
OSDI/PSP models, so process-level parallelism is the only useful parallelism.

Per-case duration is chosen from the broken-loop STA estimate so that every
case is measured over a comparable number of settled periods (>= ~130 where
the run cap allows), rather than a fixed simulated time.

Outputs (under --outdir):
  cases/<corner>_<canary>_sel<n>.{sp,log,raw}
  spice_ro.csv / spice_ro.json   machine-readable result table with provenance

Usage:
  sweep.py --predict ../../data/safe10/ro_predict.csv --outdir . \
           [--jobs 6] [--tstep-ps 5] [--solver klu] [--periods 150] \
           [--tstop-cap-ns 2000] [--only ro_gen:0]
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

import analyse_spice_raw as analyse_raw  # noqa: E402
import run_ro_spice_case as run_case  # noqa: E402

CORNERS = list(run_case.CORNERS)


def planned_tstop(period_s, periods, cap_ns, floor_ns=60.0):
    want_ns = periods * period_s * 1e9 * 1.25 + 30.0   # + startup settling
    return round(min(max(want_ns, floor_ns), cap_ns), 1)


def run_one(job):
    (canary, can_sel, corner, outdir, tstop_ns, tstep_ps, solver,
     loop_node_raw, vdd) = job
    info = run_case.run(canary, can_sel, corner, outdir, tstop_ns, tstep_ps,
                        solver)
    rec = dict(info)
    rec["status"] = "ok" if info["rc"] == 0 else f"ngspice rc={info['rc']}"
    try:
        res = analyse_raw.analyse(info["raw"], vdd=vdd, prefer=loop_node_raw)
        rec.update({k: res[k] for k in (
            "node", "n_rise", "n_fall", "n_periods", "n_periods_raw",
            "period_s", "period_std_s", "period_min_s", "period_max_s",
            "period_median_s", "freq_hz", "vmin", "vmax")})
        rec["f_osc_mhz"] = res["freq_hz"] / 1e6
        rec["period_ns"] = res["period_s"] * 1e9
        rec["period_std_ps"] = res["period_std_s"] * 1e12
    except Exception as exc:                     # keep negative results
        rec["status"] = f"analysis failed: {exc}"
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--predict", required=True,
                    help="broken-loop STA csv (ro_predict.csv) to size runs")
    ap.add_argument("--outdir", default=os.path.join(HERE, "sweep"))
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--tstep-ps", type=float, default=5.0)
    ap.add_argument("--solver", default="klu")
    ap.add_argument("--periods", type=float, default=150.0)
    ap.add_argument("--tstop-cap-ns", type=float, default=2000.0)
    ap.add_argument("--only", default=None, help="canary:can_sel filter")
    a = ap.parse_args()

    with open(a.predict) as fh:
        rows = list(csv.DictReader(fh))
    jobs = []
    for r in rows:
        canary = r["canary"]
        can_sel = int(r["can_sel"])
        corner = r["corner"]
        if a.only:
            want_can, want_sel = a.only.split(":")
            if canary != want_can or can_sel != int(want_sel):
                continue
        loop_period = float(r["loop_delay_ns"]) * 2.0 * 1e-9
        tstop = planned_tstop(loop_period, a.periods, a.tstop_cap_ns)
        loop_node = {"ro_gen": "v(x1._1351_\\/CLK)",
                     "ro_mat": "v(x1._1367_\\/CLK)"}[canary]
        vdd = run_case.CORNERS[corner]["vdd"]
        jobs.append((canary, can_sel, corner, a.outdir, tstop, a.tstep_ps,
                     a.solver, loop_node, vdd))

    print(f"{len(jobs)} cases, jobs={a.jobs}, tstep={a.tstep_ps} ps, "
          f"solver={a.solver}")
    t0 = time.time()
    results = []
    with ProcessPoolExecutor(max_workers=a.jobs) as pool:
        futs = {pool.submit(run_one, j): j for j in jobs}
        for fut in as_completed(futs):
            j = futs[fut]
            try:
                rec = fut.result()
            except Exception as exc:
                rec = dict(corner=j[2], canary=j[0], can_sel=j[1],
                           status=f"worker failed: {exc}")
            results.append(rec)
            print(f"  {rec.get('corner','?'):24s} {rec.get('canary','?'):7s} "
                  f"sel{rec.get('can_sel','?')} "
                  f"{rec.get('status','?'):28s} "
                  f"{rec.get('f_osc_mhz', float('nan')):8.2f} MHz "
                  f"({rec.get('wall_s', 0)} s)", flush=True)

    order = {(c, can, s): i for i, (c, can, s) in enumerate(
        (r["corner"], r["canary"], int(r["can_sel"])) for r in rows)}
    results.sort(key=lambda r: order.get(
        (r.get("corner"), r.get("canary"), r.get("can_sel")), 999))
    os.makedirs(a.outdir, exist_ok=True)
    csv_path = os.path.join(a.outdir, "spice_ro.csv")
    with open(csv_path, "w", newline="") as fh:
        cols = ["corner", "canary", "can_sel", "vdd", "temp", "lib", "status",
                "f_osc_mhz", "period_ns", "period_std_ps", "n_periods",
                "n_periods_raw", "period_min_s", "period_max_s", "node",
                "vmin", "vmax", "tstop_ns", "tstep_ps", "solver", "wall_s",
                "deck", "raw", "log"]
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in results:
            w.writerow(r)
    json_path = os.path.join(a.outdir, "spice_ro.json")
    with open(json_path, "w") as fh:
        json.dump({"method": "extracted-netlist transient (ngspice), ring "
                             "subtree of the post-route extracted spice, "
                             "cell-internal parasitics only (no wire RC)",
                   "tstep_ps": a.tstep_ps, "solver": a.solver,
                   "periods_target": a.periods,
                   "tstop_cap_ns": a.tstop_cap_ns,
                   "total_wall_s": round(time.time() - t0, 1),
                   "rows": results}, fh, indent=1)
    print(f"\nwrote {csv_path}\nwrote {json_path}")
    ok = sum(1 for r in results if r.get("status") == "ok")
    print(f"{ok}/{len(results)} cases analysed; total {time.time()-t0:.0f} s")


if __name__ == "__main__":
    main()
