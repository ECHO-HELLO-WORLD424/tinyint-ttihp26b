#!/usr/bin/env python3
"""Measure the ring oscillator's *stop phase* from an existing window rawfile.

Gate 3 of the freeze checklist retains one coverage gap: "close the RO enable
at multiple phases of its oscillation".  The sweep already varies
`release_phase`, and the docs concluded that this does **not** vary the stop
phase, because "the ring restarts from the same state at the same `en` edge".

That conclusion is checkable without any new simulation.  A window rawfile
already contains both the ring waveform and the `en` gate waveform, so the
phase of the ring period at which `en` falls is directly observable.  This
tool reports it per case:

    stop_phase = ((t_en_fall - t_last_ring_edge) mod period) / period

`stop_phase` is 0 when `en` falls immediately after a ring edge and approaches
1 when it falls just before the next one.  A runt clock pulse is what `en`
falling at an arbitrary phase can produce, so the *spread* of `stop_phase`
across a case set is the quantity of interest: a spread near 0 means one fixed
phase is being tested (the gap is real), a spread near 1 means the phase is
already swept.

Usage:
  measure_stop_phase.py '<glob of rawfiles>' --vdd 1.2 --loop-node 'x1._1347_/CLK'
  measure_stop_phase.py --cases data/safe10/freeze/primary_windows.csv \
      --runs runs/freeze-validation

Exit status is 0 when at least one rawfile was measured, 2 otherwise.
"""

import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)

import analyse_ro_count as ana  # noqa: E402


def norm(s):
    """Lower-case and drop the rawfile's `\\/` escaping of hierarchy bounds."""
    return s.lower().replace("\\", "")


def find_loop(names, loop_node):
    """Index of the saved vector for `loop_node`, tolerant of name escaping."""
    want = norm(loop_node)
    for i, n in enumerate(names):
        if want in norm(n):
            return i
    return None


def measure(raw, vdd, loop_node, en_node="sense_en", n_periods=8):
    """Ring period and phase at gate close for one window rawfile."""
    names, cols = ana.raw_io.read_raw(raw)
    t = cols[0]
    il = find_loop(names, loop_node)
    ie = ana.find(names, en_node)
    if il is None or ie is None:
        return dict(raw=os.path.basename(raw),
                    error=f"missing vector (loop={il}, en={ie})")
    ring = ana.rise_edges(t, cols[il], vdd)
    fall = ana.negedges(t, cols[ie], vdd)
    if len(ring) < n_periods or not fall:
        return dict(raw=os.path.basename(raw),
                    error=f"too few edges (ring={len(ring)}, fall={len(fall)})")
    t_fall = fall[-1]
    before = [x for x in ring if x < t_fall]
    after = [x for x in ring if x >= t_fall]
    if len(before) < n_periods:
        return dict(raw=os.path.basename(raw), error="too few edges pre-close")
    tail = sorted(before[-(n_periods + 1):])
    intervals = sorted(tail[i + 1] - tail[i] for i in range(len(tail) - 1))
    period = intervals[len(intervals) // 2]
    last = before[-1]
    return dict(raw=os.path.basename(raw), vdd=vdd,
                period_ns=round(period * 1e9, 5),
                t_en_fall_ns=round(t_fall * 1e9, 3),
                last_edge_ns=round(last * 1e9, 4),
                stop_phase=round(((t_fall - last) % period) / period, 4),
                edges_after_close=len(after))


def measure_tree(loopdir="runs/count-loops"):
    """Every loop node declared by the extraction, as {loop_node: (canary, sel)}."""
    meta = json.load(open(os.path.join(loopdir, "ro_loop.json")))["canaries"]
    return {v["loop_node"]: k for k, v in meta.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pattern", nargs="?",
                    help="glob of rawfiles (shell-quoted)")
    ap.add_argument("--vdd", type=float, default=None)
    ap.add_argument("--loop-node", default=None)
    ap.add_argument("--loopdir", default=os.path.join(REPO, "runs/count-loops"),
                    help="resolve the loop node per rawfile from the extraction")
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    if not a.pattern:
        ap.error("give a rawfile glob")
    if a.vdd is None:
        ap.error("--vdd is required")
    files = sorted(glob.glob(a.pattern))
    if not files:
        print("no rawfiles matched " + a.pattern)
        return 2
    nodes = measure_tree(a.loopdir) if a.loop_node is None else None
    rows = []
    for f in files:
        if a.loop_node is not None:
            rows.append(measure(f, a.vdd, a.loop_node))
            continue
        # `--loopdir` mode: try each declared loop node and keep the one that
        # yields edges, so a mixed directory needs no per-case argument.
        best = None
        for node, canary in nodes.items():
            r = measure(f, a.vdd, node)
            if "stop_phase" in r:
                r["loop_node"], r["canary"] = node, canary
                if best is None or r["edges_after_close"] > best["edges_after_close"]:
                    best = r
        rows.append(best or dict(raw=os.path.basename(f),
                                 error="no declared loop node matched"))
    for r in rows:
        print(json.dumps(r), flush=True)
    good = [r for r in rows if "stop_phase" in r]
    print(f"\nn={len(rows)} measured={len(good)}")
    if good:
        ph = sorted(r["stop_phase"] for r in good)
        print("stop_phase: min=%.3f max=%.3f spread=%.3f "
              "(n distinct=%d)" % (ph[0], ph[-1], ph[-1] - ph[0], len(set(ph))))
        print("edges_after_close:",
              sorted(set(r["edges_after_close"] for r in good)))
    if a.json:
        json.dump(rows, open(a.json, "w"), indent=1)
        print("wrote " + a.json)
    return 0 if good else 2


if __name__ == "__main__":
    sys.exit(main())
