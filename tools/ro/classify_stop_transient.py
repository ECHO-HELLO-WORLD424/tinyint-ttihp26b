#!/usr/bin/env python3
"""Classify the ring's *stop transient*: does a marginal pulse reach the counter?

Gate 3 of the freeze checklist asks whether the RO enable can be closed at
multiple phases of the oscillation, because "at worst a marginal-width clock
pulse as `en` falls" could be captured inconsistently by the ripple stages.
`measure_stop_phase.py` reports the phase at which the gate closes; this tool
reports what actually happens to the waveform there.

For every rising crossing of the loop node in a window rawfile it finds the
pulse peak before the next falling crossing and reports the amplitude relative
to the rail:

    full  : peak >= 85 % of VDD  - a pulse the counter must capture
    runt  : peak in (15 %, 85 %) - a marginal pulse, the risk this gate names
    noise : peak <= 15 %         - a sub-threshold glitch, not a clock edge

The number of rising *crossings* is what `analyse_ro_count.py` compares the
decoded count against, so if the count equals the crossings and no crossing is
a runt, then every edge the counter was offered was a full-swing edge and no
marginal pulse was miscounted.

Usage:
  classify_stop_transient.py '<glob>' --vdd 1.2 --loop-node '_1347_/CLK'
"""

import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import analyse_ro_count as ana  # noqa: E402

LOW = 0.15
HIGH = 0.85


def excursions(t, v, vdd, low=LOW, min_width=2e-12):
    """Every upward excursion above `low`*vdd, as (start, end, peak_volts).

    This must not be built on `analyse_ro_count.rise_edges`: that detector uses a
    30 %->70 % hysteresis band, so a pulse that peaks between 30 % and 70 % of
    the rail raises no crossing at all and would be *invisible* to the
    classification below -- exactly the marginal pulse this tool exists to find.
    Instead, take the low threshold as the boundary of interest: an excursion
    starts when the signal crosses `low`*vdd upward and ends when it crosses back
    down, and its peak is the maximum in between.  A full-swing pulse yields
    exactly one excursion, and a sub-70 % pulse yields one too.
    """
    lo_v = low * vdd
    n = len(v)
    out = []
    i = 1
    while i < n:
        if v[i - 1] <= lo_v < v[i]:
            # Upward crossing of the low threshold: interpolate the start.
            frac = (lo_v - v[i - 1]) / (v[i] - v[i - 1]) if v[i] != v[i - 1] else 0
            t0 = t[i - 1] + frac * (t[i] - t[i - 1])
            j = i
            peak, peak_i = v[i], i
            while j < n and v[j] > lo_v:
                if v[j] > peak:
                    peak, peak_i = v[j], j
                j += 1
            # `j == n` means the run ends with the signal still high.
            t1 = t[j] if j < n else t[-1]
            if t1 - t0 >= min_width:
                out.append((t0, t1, peak))
            i = j + 1
        else:
            i += 1
    return out


def classify(raw, vdd, loop_node, tail=12):
    names, cols = ana.raw_io.read_raw(raw)
    t = cols[0]
    il = None
    for i, n in enumerate(names):
        if loop_node.lower().replace("\\", "") in n.lower().replace("\\", ""):
            il = i
            break
    ie = ana.find(names, "sense_en")
    if il is None or ie is None:
        return dict(raw=os.path.basename(raw), error="missing vector")
    loop = cols[il]
    pulses = excursions(t, loop, vdd)
    t_fall = ana.negedges(t, cols[ie], vdd)
    if len(pulses) < tail or not t_fall:
        return dict(raw=os.path.basename(raw), error="too few edges")
    t_close = t_fall[-1]
    cls = [(t0, peak) for t0, _t1, peak in pulses]
    n_full = sum(1 for _, v in cls if v >= HIGH * vdd)
    n_runt = sum(1 for _, v in cls if LOW * vdd < v < HIGH * vdd)
    n_noise = sum(1 for _, v in cls if v <= LOW * vdd)
    last = [(round(tt * 1e9, 4), round(v / vdd, 4)) for tt, v in cls[-tail:]]
    # Pulses *starting* after the gate closes: a pulse that begins before the
    # close and is still high when it closes is reported separately, because it
    # is the stop transient itself rather than an extra edge clocking a settled
    # counter.
    after = [t0 for t0, _t1, _p in pulses if t0 > t_close]
    straddling = [t0 for t0, t1, _p in pulses if t0 <= t_close < t1]
    return dict(raw=os.path.basename(raw), vdd=vdd,
                n_rise_crossings=len(cls), n_full=n_full, n_runt=n_runt,
                n_noise=n_noise,
                t_en_fall_ns=round(t_close * 1e9, 3),
                crossings_after_close=len(after),
                pulses_straddling_close=len(straddling),
                last_pulse_peaks_over_vdd=last)


def vdd_from_name(path):
    """Rail voltage from a rawfile name (`nom_typ_1p20V_25C` -> 1.20)."""
    import re
    m = re.search(r"_(\d)p(\d+)V_", os.path.basename(path))
    return float(f"{m.group(1)}.{m.group(2)}") if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pattern")
    ap.add_argument("--vdd", type=float, default=None,
                    help="default: read the rail from the rawfile name")
    ap.add_argument("--loop-node", default=None,
                    help="default: resolve per file from runs/count-loops")
    ap.add_argument("--loopdir", default="runs/count-loops")
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    nodes = None
    if a.loop_node is None:
        meta = json.load(open(os.path.join(a.loopdir, "ro_loop.json")))["canaries"]
        nodes = {v["loop_node"]: k for k, v in meta.items()}
    rows = []
    for f in sorted(glob.glob(a.pattern)):
        vdd = a.vdd if a.vdd is not None else vdd_from_name(f)
        if vdd is None:
            rows.append(dict(raw=os.path.basename(f), error="no rail in name"))
            continue
        if a.loop_node:
            rows.append(classify(f, vdd, a.loop_node))
        else:
            for node, canary in nodes.items():
                r = classify(f, vdd, node)
                if "n_rise_crossings" in r:
                    r["loop_node"], r["canary"] = node, canary
                    rows.append(r)
                    break
            else:
                rows.append(dict(raw=os.path.basename(f), error="no loop node"))
    for r in rows:
        print(json.dumps(r), flush=True)
    tot_runt = sum(r.get("n_runt", 0) for r in rows)
    tot_full = sum(r.get("n_full", 0) for r in rows)
    tot_noise = sum(r.get("n_noise", 0) for r in rows)
    after = sum(r.get("crossings_after_close", 0) for r in rows)
    print(f"\ncases={len(rows)} full={tot_full} runt={tot_runt} "
          f"noise={tot_noise} crossings_after_close={after}")
    if a.json:
        json.dump(rows, open(a.json, "w"), indent=1)
        print("wrote " + a.json)
    return 0 if tot_runt == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
