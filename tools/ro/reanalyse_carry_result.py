#!/usr/bin/env python3
"""Re-analyse a carry/wrap run with the *current* analyzer and archive the result.

A long transient is expensive, so when the analyzer changes the right move is to
re-decode the stored rawfile rather than re-simulate.  This does for the carry
and wrap runs what `recheck_archived_counts.py` does for the window cases, but it
also rewrites the run's `*_result.json` in place (metadata from the
pre-fix record is carried over) so the archived dataset matches the fixed tool.

Usage:
  reanalyse_carry_result.py --outdir runs/freeze-validation/carry-wrap
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)

import analyse_ro_count as ana  # noqa: E402
import run_ro_carry_test as ct  # noqa: E402
import run_ro_spice_case as rc  # noqa: E402

CARRY_META = ("kind", "corner", "canary", "can_sel", "deck", "log", "wall_s",
              "tstop_ns", "en_rise_ns", "en_fall_ns", "extended_ns",
              "mask_at_ns", "freeze_windows", "reset_windows", "cycles_open",
              "role_check_ok")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--kind", default="carry")
    a = ap.parse_args()
    path = os.path.join(a.outdir, f"{a.kind}_result.json")
    rows = json.load(open(path))
    out = []
    for r in rows:
        raw = r.get("raw")
        if not raw:
            continue
        if not os.path.isabs(raw):
            raw = os.path.join(REPO, raw)
        node = r.get("loop_node") or r.get("loop_port") or ""
        res = ana.analyse(raw, vdd=r.get("vdd", 1.2),
                          loop_node="v(x1.%s)" % rc.escape_node(node))
        res["ripple"] = ct.ripple_settling(res)
        res.update({k: r.get(k) for k in CARRY_META if r.get(k) is not None})
        out.append(res)
        print(json.dumps({k: res.get(k) for k in
                          ("status", "counter_final", "ring_edges_in_window",
                           "count_ok", "count_error_circular", "count_aliased",
                           "counter_wraps_inferred",
                           "counter_edges_reconstructed",
                           "f_count_from_counter_mhz", "coverage_complete",
                           "settled", "levels_valid")}), flush=True)
    json.dump(out, open(path, "w"), indent=1, default=str)
    print("rewrote " + path)
    return 0 if all(r.get("count_ok") for r in out) else 1


if __name__ == "__main__":
    sys.exit(main())
