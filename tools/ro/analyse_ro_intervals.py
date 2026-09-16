#!/usr/bin/env python3
"""Characterise a ring oscillator's transient: period, jitter, and whether the
period is single-valued.

A mean threshold-crossing interval is only a meaningful "frequency" when the
ring has one period.  At several tap selections these canaries do not (see
`data/safe10/count/FOSC-REGEN-STATUS.md`), so this tool reports the interval
distribution instead of a single number:

  * `period_mean_ns`, `period_median_ns` - both, so a skewed distribution is
    visible rather than hidden;
  * `jitter_pct` - how far the mean sits from the median;
  * `n_modes` and `mode_periods_ns` - clusters in the interval histogram (1 %
    bins), which is what distinguishes "one period with noise" from "the loop
    alternates between two path lengths";
  * `std_over_mean` - coefficient of variation.

Usage:
  analyse_ro_intervals.py <rawfile> --vdd 1.2 [--node 'v(x1._1347_\\/clk)']
                          [--json out.json]
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import analyse_spice_raw as raw_io  # noqa: E402


def pick_node(names, cols, vdd, node=None):
    lowered = [n.lower() for n in names]
    if node:
        for i, n in enumerate(lowered):
            if n == node.lower():
                return i
        for i, n in enumerate(lowered):
            if node.lower() in n:
                return i
        raise SystemExit(f"node {node!r} not in rawfile")
    for i in range(1, len(names)):
        n = lowered[i]
        if n.startswith("v(ctl") or n in ("v(sup_vdd)", "v(sup_vss)"):
            continue
        if max(cols[i]) - min(cols[i]) > 0.5 * vdd:
            return i
    raise SystemExit("no switching node in rawfile")


def modes(intervals, bin_pct=2.0, min_share=0.15, min_count=6):
    """Cluster threshold crossings of the interval histogram into modes.

    Bins are `bin_pct` wide relative to the median interval.  A bin is a mode
    candidate when it holds at least `min_share` of the intervals; adjacent
    candidates are merged.  Two well-separated modes mean the loop is not
    running at a single period.
    """
    if not intervals:
        return []
    med = sorted(intervals)[len(intervals) // 2]
    width = med * bin_pct / 100.0
    # Bins closer than this can only be resolved when there are enough edges to
    # fill them: require the bin width to be large compared with the sample.

    hist = {}
    for x in intervals:
        hist[int(x / width)] = hist.get(int(x / width), 0) + 1
    n = len(intervals)
    # A candidate bin must hold a real share of the intervals *and* enough
    # intervals to not be sparse-data noise; with a handful of edges almost any
    # jitter looks like several modes.
    need = max(min_share * n, min_count)
    cand = sorted(b for b, c in hist.items() if c >= need)
    if not cand:
        return []
    groups = [[cand[0]]]
    for b in cand[1:]:
        if b - groups[-1][-1] <= 2:
            groups[-1].append(b)
        else:
            groups.append([b])
    out = []
    for g in groups:
        members = [x for x in intervals if int(x / width) in g]
        out.append(dict(period_ns=sum(members) / len(members) * 1e9,
                        share=len(members) / n))
    return sorted(out, key=lambda m: -m["share"])


def analyse(path, vdd=1.2, node=None, skip=4):
    names, cols = raw_io.read_raw(path)
    i = pick_node(names, cols, vdd, node)
    times, volts = cols[0], cols[i]
    lo, hi = 0.3 * vdd, 0.7 * vdd
    rises = raw_io.crossings(times, volts, lo, hi, rise=True)[skip:]
    falls = raw_io.crossings(times, volts, lo, hi, rise=False)
    out = dict(raw=os.path.basename(path), node=names[i], vdd=vdd,
               t_end_ns=times[-1] * 1e9, n_rise=len(rises), n_fall=len(falls),
               vmin=min(volts), vmax=max(volts))
    if len(rises) < 4:
        out["status"] = "too_few_edges"
        return out
    iv = [b - a for a, b in zip(rises, rises[1:])]
    ordered = sorted(iv)
    med = ordered[len(ordered) // 2]
    mean = sum(iv) / len(iv)
    var = sum((x - mean) ** 2 for x in iv) / len(iv)
    out.update(period_mean_ns=mean * 1e9, period_median_ns=med * 1e9,
               period_min_ns=ordered[0] * 1e9, period_max_ns=ordered[-1] * 1e9,
               period_std_ns=var ** 0.5 * 1e9,
               std_over_mean=(var ** 0.5) / mean,
               jitter_pct=100.0 * (mean - med) / med,
               n_intervals=len(iv))
    md = modes(iv)
    out["n_modes"] = len(md)
    out["modes"] = md[:6]
    out["status"] = ("single_mode" if len(md) <= 1
                     else f"multi_mode({len(md)})")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("raw")
    ap.add_argument("--vdd", type=float, default=1.2)
    ap.add_argument("--node", default=None)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    r = analyse(a.raw, a.vdd, a.node)
    print(json.dumps(r, indent=1))
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(r, fh, indent=1)


if __name__ == "__main__":
    main()
