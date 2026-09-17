#!/usr/bin/env python3
"""Run the counter-inclusive RO transient test over a set of measurement windows.

Two decks are supported:

  window (default)  the real reset -> boot -> gate-open -> gate-close sequence
                    produced by the RTL (`run_ro_count_case.run_window`,
                    boundaries derived by `tools/ro/probe_ro_window.py`).
  free              the legacy free-running deck, which holds `en` high for the
                    whole run and therefore only demonstrates that the counter
                    counts (kept for reproducing the F5 dataset).

Every case is analysed by `analyse_ro_count.py` against the window recorded in
its own rawfile, and the per-case JSON is kept so the sweep can be resumed
after an interruption.  Failures (setup errors, ngspice failures, or an
analysis whose acceptance rule fails) are collected and make the sweep exit
non-zero; `--strict` additionally requires full bit coverage and a stable rate.

Usage:
  sweep_ro_count.py --loopdir runs/count-loops --outdir data/safe10/count
      [--mode primary|matrix] [--clocks-mhz 10,50] [--phases 0.05,0.35,0.65]
      [--can-sel 3] [--tstep-ps 5] [--jobs 12] [--strict] [--force]
      [--periods 32] [--tstop-cap-ns 4000]
"""

import argparse
import csv
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)

import analyse_ro_count as analyse_count  # noqa: E402
import run_ro_count_case as count_case  # noqa: E402
import run_ro_spice_case as ring_case  # noqa: E402

CORNERS = list(ring_case.CORNERS)
CANARIES = ("ro_gen", "ro_mat")


def case_tag(c):
    return (f"{c['corner']}_{c['canary']}_sel{c['can_sel']}"
            f"_w{c['win_sel']}_t{c['tclk_ns']:g}_p{c['phase']:g}"
            f"_dt{c['tstep_ps']:g}")


def primary_cases(clocks, phases, can_sel):
    out = []
    for corner in CORNERS:
        for canary in CANARIES:
            for tclk in clocks:
                for phase in phases:
                    out.append(dict(corner=corner, canary=canary,
                                    can_sel=can_sel, win_sel=0, tclk_ns=tclk,
                                    phase=phase, tstep_ps=5.0))
    return out


def matrix_cases(clocks, phases, sels):
    out = []
    for corner in CORNERS:
        for canary in CANARIES:
            for can_sel in sels:
                for tclk in clocks:
                    for phase in phases:
                        out.append(dict(corner=corner, canary=canary,
                                        can_sel=can_sel, win_sel=0,
                                        tclk_ns=tclk, phase=phase,
                                        tstep_ps=5.0))
    return out


def run_case(case, loopdir, outdir, strict):
    tag = case_tag(case)
    case_dir = os.path.join(outdir, "cases")
    os.makedirs(case_dir, exist_ok=True)
    res_path = os.path.join(case_dir, tag + ".json")
    row = dict(case)
    row["tag"] = tag
    t0 = time.time()
    # Resume on the analysis JSON (written after the rawfile is analysed).  The
    # deck/rawfile names come from run_window's own tag, which is kept identical
    # to `tag` by passing the timestep as a tag suffix.
    if os.path.exists(res_path):
        try:
            with open(res_path) as fh:
                res = json.load(fh)
        except ValueError:
            res = None
        if res and res.get("status"):
            row.update(dict(status=res.get("status"), resumed=True,
                            counter_final=res.get("counter_final"),
                            ring_edges=res.get("ring_edges_in_window"),
                            wall_s=res.get("wall_s"),
                            coverage_complete=res.get("coverage_complete"),
                            rate_stable=res.get("rate_stable")))
            row["accepted"] = analyse_count.accepted(res, strict)
            return row
    try:
        info = count_case.run_window(
            case["canary"], case["can_sel"], case["corner"], loopdir, case_dir,
            tclk_ns=case["tclk_ns"], win_sel=case["win_sel"],
            release_phase=case["phase"], tstep_ps=case["tstep_ps"],
            solver="klu", tag_suffix=f"_dt{case['tstep_ps']:g}")
    except SystemExit as exc:
        row.update(status="setup_error", detail=str(exc),
                   wall_s=round(time.time() - t0, 2), accepted=False)
        return row
    if info["rc"] != 0:
        row.update(status="ngspice_failed", rc=info["rc"], log=info["log"],
                   wall_s=info["wall_s"], accepted=False)
        return row
    loop_vec = "v(x1.%s)" % ring_case.escape_node(info["loop_port"])
    res = analyse_count.analyse(info["raw"], vdd=info["vdd"],
                                loop_node=loop_vec)
    res.update(case=case, tag=tag, deck=info["deck"], raw=info["raw"],
               log=info["log"], wall_s=info["wall_s"],
               ring_cells=info["ring_cells"], n_chain=len(info["chain"]),
               control_roles=info["control_roles"],
               role_check_ok=info["role_check"]["ok"],
               role_check_problems=info["role_check"]["problems"],
               en_rise_ns=info["en_rise_ns"], en_fall_ns=info["en_fall_ns"],
               reset_release_ns=info["reset_release_ns"],
               cycles_open=info["cycles_open"], tstop_ns=info["tstop_ns"],
               edge_ns=info["edge_ns"], settle_ns=info["settle_ns"],
               loop_node_expected=info["loop_port"])
    with open(res_path, "w") as fh:
        json.dump(res, fh, indent=1)
    row.update(dict(status=res.get("status"), counter_final=res.get(
        "counter_final"), ring_edges=res.get("ring_edges_in_window"),
        f_count_mhz=res.get("f_count_mhz"),
        f_steady_mhz=res.get("steady_f_mhz"),
        cv=res.get("steady_std_over_mean"),
        coverage_complete=res.get("coverage_complete"),
        rate_stable=res.get("rate_stable"),
        unexercised_bits=res.get("unexercised_bits"),
        wall_s=info["wall_s"]))
    row["accepted"] = analyse_count.accepted(res, strict)
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loopdir", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--mode", default="primary",
                    choices=["primary", "matrix"])
    ap.add_argument("--deck", default="window", choices=["window", "free"])
    ap.add_argument("--clocks-mhz", default="10,50")
    ap.add_argument("--phases", default="0.05,0.35,0.65")
    ap.add_argument("--can-sel", default="3",
                    help="comma-separated can_sel values")
    ap.add_argument("--win-sel", type=int, default=0)
    ap.add_argument("--tstep-ps", type=float, default=5.0)
    ap.add_argument("--periods", type=float, default=32.0,
                    help="free deck only: ring periods to simulate")
    ap.add_argument("--tstop-cap-ns", type=float, default=4000.0,
                    help="free deck only: cap on the simulated time")
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="re-run cases even if a result JSON exists")
    ap.add_argument("--cases-json", default=None,
                    help="write the resolved case list here for review")
    ap.add_argument("--only", default=None,
                    help="comma-separated corner:canary:sel filters")
    a = ap.parse_args()

    # --clocks-mhz is a frequency; the deck and the RTL probe both work in
    # clock *periods*, so convert once here.
    clocks = [1000.0 / float(x) for x in a.clocks_mhz.split(",")]
    for f_mhz, t_ns in zip([float(x) for x in a.clocks_mhz.split(",")], clocks):
        if abs(1000.0 / t_ns - f_mhz) > 1e-9:
            raise SystemExit("clock conversion check failed")
    phases = [float(x) for x in a.phases.split(",")]
    sels = [int(x) for x in a.can_sel.split(",")]
    if a.mode == "primary":
        cases = primary_cases(clocks, phases, sels[0])
    else:
        cases = matrix_cases(clocks, phases, sels)
    if a.only:
        want = set()
        for spec in a.only.split(","):
            parts = spec.split(":")
            want.add(tuple(parts))
        cases = [c for c in cases
                 if (c["corner"], c["canary"], str(c["can_sel"])) in want
                 or (c["corner"], c["canary"]) in want
                 or (c["corner"],) in want]
    for c in cases:
        c["tstep_ps"] = a.tstep_ps
        c["win_sel"] = a.win_sel
    os.makedirs(a.outdir, exist_ok=True)
    if a.cases_json:
        with open(a.cases_json, "w") as fh:
            json.dump(cases, fh, indent=1)
    if a.force:
        for c in cases:
            p = os.path.join(a.outdir, "cases", case_tag(c) + ".json")
            for f in (p, p.replace(".json", ".raw")):
                if os.path.exists(f):
                    os.remove(f)

    print(f"{len(cases)} cases, {a.jobs} workers, deck={a.deck}, "
          f"strict={a.strict}", flush=True)
    rows = []
    if a.deck == "window":
        with ProcessPoolExecutor(max_workers=a.jobs) as pool:
            futs = {pool.submit(run_case, c, a.loopdir, a.outdir,
                                a.strict): c for c in cases}
            for fut in as_completed(futs):
                r = fut.result()
                rows.append(r)
                print(f"  {r['tag']:60s} {str(r.get('status')):32s} "
                      f"cnt={r.get('counter_final')} "
                      f"f={r.get('f_count_mhz') and round(r['f_count_mhz'], 1)} "
                      f"cv={r.get('cv') and round(r['cv'], 4)} "
                      f"{r.get('wall_s')}s ok={r['accepted']}", flush=True)
    else:
        rows = free_run_cases(cases, a)
    rows.sort(key=lambda r: r["tag"])
    csv_path = os.path.join(a.outdir, "ro_count.csv")
    cols = ["tag", "corner", "canary", "can_sel", "win_sel", "tclk_ns",
            "phase", "tstep_ps", "status", "accepted", "counter_final",
            "ring_edges", "f_count_mhz", "f_steady_mhz", "cv",
            "coverage_complete", "rate_stable", "unexercised_bits", "wall_s"]
    with open(csv_path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            r = dict(r)
            if isinstance(r.get("unexercised_bits"), list):
                r["unexercised_bits"] = ",".join(str(b) for b in
                                                 r["unexercised_bits"])
            w.writerow(r)
    json_path = os.path.join(a.outdir, "ro_count.json")
    with open(json_path, "w") as fh:
        json.dump(rows, fh, indent=1)
    nfail = [r["tag"] for r in rows if not r.get("accepted")]
    print(f"\n{len(rows) - len(nfail)}/{len(rows)} cases accepted "
          f"(strict={a.strict})")
    if nfail:
        print("not accepted: " + ", ".join(nfail))
    print(f"wrote {csv_path} and {json_path}")
    return 0 if not nfail else 1


def load_period_hints(path):
    """{(corner, canary, can_sel): period_s} from an f_osc result table."""
    out = {}
    if not path or not os.path.exists(path):
        return out
    for row in csv.DictReader(open(path)):
        try:
            out[(row["corner"], row["canary"], int(row["can_sel"]))] = \
                float(row["period_ns"]) * 1e-9
        except (KeyError, ValueError):
            continue
    return out


def free_run_cases(cases, a):
    """Legacy free-running deck (kept for the F5 dataset).

    The transient length is sized from a measured f_osc period when one is
    available, so `--periods` and `--tstop-cap-ns` are both honoured.
    """
    rows = []
    hints = load_period_hints(os.path.join(
        REPO_ROOT, "data", "safe10", "spice", "spice_ro.csv"))
    for c in cases:
        tag = case_tag(c)
        case_dir = os.path.join(a.outdir, "cases")
        os.makedirs(case_dir, exist_ok=True)
        t0 = time.time()
        try:
            info = count_case.run(
                c["canary"], c["can_sel"], c["corner"], a.loopdir, case_dir,
                periods=a.periods, tstep_ps=c["tstep_ps"], solver="klu",
                tstop_cap_ns=a.tstop_cap_ns,
                period_hint_s=hints.get(
                    (c["corner"], c["canary"], c["can_sel"]), 1.0e-9))
        except SystemExit as exc:
            rows.append(dict(c, tag=tag, status="setup_error", detail=str(exc),
                             accepted=False))
            continue
        if info["rc"] != 0:
            rows.append(dict(c, tag=tag, status="ngspice_failed",
                             accepted=False, rc=info["rc"], log=info["log"],
                             wall_s=info["wall_s"]))
            continue
        loop_vec = "v(x1.%s)" % ring_case.escape_node(info["loop_port"])
        res = analyse_count.analyse(info["raw"], vdd=info["vdd"],
                                    loop_node=loop_vec)
        res.update(case=c, tag=tag, deck=info["deck"], raw=info["raw"],
                   log=info["log"], wall_s=info["wall_s"],
                   tstop_ns=info["tstop_ns"], tstep_ps=info["tstep_ps"],
                   ring_cells=info["ring_cells"],
                   n_chain=len(info["chain"]))
        with open(os.path.join(case_dir, tag + ".json"), "w") as fh:
            json.dump(res, fh, indent=1)
        rows.append(dict(c, tag=tag, status=res.get("status"),
                         accepted=analyse_count.accepted(res, a.strict),
                         counter_final=res.get("counter_final"),
                         ring_edges=res.get("ring_edges_in_window"),
                         f_count_mhz=res.get("f_count_mhz"),
                         cv=res.get("steady_std_over_mean"),
                         coverage_complete=res.get("coverage_complete"),
                         rate_stable=res.get("rate_stable"),
                         wall_s=round(time.time() - t0, 1),
                         tstop_ns=info["tstop_ns"]))
    return rows


if __name__ == "__main__":
    sys.exit(main())
