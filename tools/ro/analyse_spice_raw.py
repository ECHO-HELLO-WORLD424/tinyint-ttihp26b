#!/usr/bin/env python3
"""Analyse an ngspice binary rawfile: average RO period and frequency.

The raw file is written by run_case.py with every vector of the (small) ring
subcircuit.  The loop node is measured at the 50 % supply threshold, with a
hysteresis window so ringing on the edges cannot produce phantom crossings.
Crossings whose spacing deviates strongly from the median are rejected before
the mean period is computed.

ngspice lower-cases vector names in the rawfile, so name matching is
case-insensitive.
"""

import array
import struct
import sys


def read_raw(path):
    """Read an ngspice binary rawfile.

    Returns `(varnames, cols)` where each column is a compact `array('d')`.
    The arrays matter: a 25 us window at a 5-10 ps step is tens of millions of
    samples, and materialising them as Python floats would cost gigabytes per
    concurrent analysis (several analyses run at once at the end of a sweep).
    """
    with open(path, "rb") as fh:
        data = fh.read()
    idx = data.find(b"Binary:\n")
    if idx < 0:
        raise ValueError("not a binary rawfile")
    header = data[:idx].decode("latin-1")
    body = data[idx + len("Binary:\n"):]
    nvars = npoints = None
    varnames = []
    in_vars = False
    for line in header.splitlines():
        if line.startswith("No. Variables:"):
            nvars = int(line.split(":")[1])
        elif line.startswith("No. Points:"):
            npoints = int(line.split(":")[1])
        elif line.startswith("Variables:"):
            in_vars = True
        elif in_vars and line.startswith("\t"):
            parts = line.split("\t")
            varnames.append(parts[2] if len(parts) > 2 else line.strip())
    if nvars is None or npoints is None:
        raise ValueError("missing No. Variables/Points")
    n = nvars * npoints
    vals = array.array("d")
    vals.frombytes(body[:8 * n])
    if sys.byteorder != "little":          # rawfiles are little-endian doubles
        vals.byteswap()
    cols = [vals[i::nvars] for i in range(nvars)]
    del vals
    return varnames, cols


def crossings(times, volts, lo, hi, rise=True, min_width=2e-12):
    """Threshold crossings with hysteresis.

    A rising crossing is reported when the signal, having been below `lo`,
    crosses `hi` from below.  The threshold is interpolated between the
    bracketing samples.  `min_width` rejects points closer than one timestep.
    """
    out = []
    state = 0                      # 0 = armed low, 1 = armed high
    for i in range(1, len(volts)):
        a, b = volts[i - 1], volts[i]
        if state == 0 and a <= lo and b > lo:
            state = 1
        elif state == 1 and a >= hi and b < hi:
            state = 0
        if rise and state == 1 and a < hi <= b:
            out.append(times[i - 1] + (hi - a) * (times[i] - times[i - 1])
                       / (b - a))
        elif not rise and state == 0 and a > lo >= b:
            out.append(times[i - 1] + (lo - a) * (times[i] - times[i - 1])
                       / (b - a))
    clean = []
    for t in out:
        if not clean or t - clean[-1] > min_width:
            clean.append(t)
    return clean


def _stats(periods):
    ordered = sorted(periods)
    med = ordered[len(ordered) // 2]
    kept = [p for p in ordered if 0.5 * med <= p <= 1.5 * med]
    n = len(kept)
    mean = sum(kept) / n
    var = sum((p - mean) ** 2 for p in kept) / n
    return mean, var ** 0.5, min(kept), max(kept), n, med


def analyse(raw, vdd=1.2, skip=20, prefer=None):
    varnames, cols = read_raw(raw)
    times = cols[0]
    lo, hi = 0.3 * vdd, 0.7 * vdd
    names = [n.lower() for n in varnames]
    if prefer:
        prefer = prefer.lower()
        cand = [i for i, n in enumerate(names) if n == prefer]
        if not cand:
            cand = [i for i, n in enumerate(names) if prefer in n]
        if not cand:
            raise ValueError(f"preferred node {prefer!r} not in {raw}")
    else:
        cand = [i for i in range(1, len(varnames))
                if "#" not in varnames[i] and not varnames[i].endswith("#branch")
                and varnames[i] != "v(dc)"]
    for i in cand:
        v = cols[i]
        if max(v) - min(v) < 0.5 * vdd:
            continue
        rc = crossings(times, v, lo, hi, rise=True)
        fc = crossings(times, v, lo, hi, rise=False)
        if len(rc) < skip + 5:
            continue
        use = rc[skip:]
        periods = [b - a for a, b in zip(use, use[1:])]
        mean, std, pmin, pmax, n, med = _stats(periods)
        duty = None
        if len(rc) >= 3 and len(fc) >= 3:
            widths = [b - a for a, b in zip(rc, fc[:len(rc)]) if 0 < b - a < mean]
            if widths:
                duty = (sum(widths) / len(widths)) / mean
        return dict(node=varnames[i], n_rise=len(rc), n_fall=len(fc),
                    n_periods=n, n_periods_raw=len(periods),
                    period_s=mean, period_std_s=std,
                    period_min_s=pmin, period_max_s=pmax,
                    period_median_s=med, freq_hz=1.0 / mean,
                    duty=duty, vmin=min(v), vmax=max(v),
                    t_start=use[0], t_end=use[-1],
                    vdd=vdd, threshold_lo=lo, threshold_hi=hi)
    raise ValueError(f"no oscillating node found in {raw}")


if __name__ == "__main__":
    import json
    vdd = float(sys.argv[2]) if len(sys.argv) > 2 else 1.2
    prefer = sys.argv[3] if len(sys.argv) > 3 else None
    r = analyse(sys.argv[1], vdd=vdd, prefer=prefer)
    print(json.dumps(r, indent=1))
