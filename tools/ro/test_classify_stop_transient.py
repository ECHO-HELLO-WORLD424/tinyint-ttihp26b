#!/usr/bin/env python3
"""Fixtures for the stop-transient classifier.

`classify_stop_transient.py` decides whether the RO's stop transient contains a
marginal-width ("runt") pulse.  Its first revision could not answer that for the
pulses it most needed to catch: it derived pulses from
`analyse_ro_count.rise_edges`, whose 30 %->70 % hysteresis band means a pulse
peaking *below* 70 % of the rail raises no crossing at all, so a 0.6 V pulse on a
1.2 V rail contributed nothing to `n_runt` (and neither did a 0.9 V one).  The
detector now works from the low threshold (`excursions`), so every pulse that
rises above 15 % of the rail is classified by its peak.

Fixtures:
  all_full        full-swing pulses only                      -> n_runt=0
  marginal_60pct  two pulses at 50 %of the rail               -> n_runt=2
  marginal_75pct  two pulses at 75 % of the rail              -> n_runt=2
  subthreshold    a 10 % glitch                               -> n_noise>=1
  after_close     a full pulse starting after `en` falls      -> crossings_after_close>=1

Run:
  python3 tools/ro/test_classify_stop_transient.py
Exit status is 0 only when every fixture classifies as declared.
"""

import argparse
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)

import classify_stop_transient as cls  # noqa: E402

VDD = 1.2
RAMP = 0.02           # ns, edge ramp; well under one sample of the grid
HALF = 1.0            # ns, pulse half-width (high time)
PERIOD = 10.0         # ns between pulse starts
N_PULSES = 14         # > the classifier's `tail` guard
T_EN_RISE = 5.0
T_EN_FALL = 300.0     # after the whole main train, so nothing straddles it
T_END = 400.0
TRAIN_END = 10.0 + N_PULSES * PERIOD


def build(extra=None, after_close_pulse=False, steps=None, truncated=None):
    """Segments `[(t0_ns, t1_ns, v0, v1), ...]` describing the loop waveform.

    The waveform is explicit piecewise-linear segments sampled at every segment
    boundary and midpoint, which is unambiguous: an earlier draft described it as
    a PWL point list, where consecutive points are *instantaneous jumps*, so a
    pulse written as [(10, VDD), (11, 0)] was two adjacent jumps and the sampled
    waveform never went high at all.  Every fixture silently classified zero
    pulses as a result.

    `steps` adds a level that rises before the train and persists, `extra` adds
    marginal pulses after the train, `truncated` adds a partial pulse starting
    just before the gate closes, and `after_close_pulse` adds one pulse starting
    after it.
    """
    segs = [(0.0, 5.0, 0.0, 0.0)]
    for start, frac in (steps or []):
        segs.append((start, start + RAMP, 0.0, VDD * frac))
    t = 10.0
    for _ in range(N_PULSES):
        segs.append((t, t + RAMP, 0.0, VDD))
        segs.append((t + RAMP, t + HALF, VDD, VDD))
        segs.append((t + HALF, t + HALF + RAMP, VDD, 0.0))
        t += PERIOD
    for start, frac in (extra or []):
        segs.append((start, start + RAMP, 0.0, VDD * frac))
        segs.append((start + RAMP, start + HALF, VDD * frac, VDD * frac))
        segs.append((start + HALF, start + HALF + RAMP, VDD * frac, 0.0))
    if truncated is not None:
        segs.append((T_EN_FALL - 2.0, T_EN_FALL - 2.0 + RAMP, 0.0, VDD * truncated))
        segs.append((T_EN_FALL - 2.0 + RAMP, T_END, VDD * truncated, VDD * truncated))
    if after_close_pulse:
        segs.append((T_EN_FALL + 5.0, T_EN_FALL + 5.0 + RAMP, 0.0, VDD))
        segs.append((T_EN_FALL + 5.0 + RAMP, T_EN_FALL + 5.0 + HALF, VDD, VDD))
        segs.append((T_EN_FALL + 5.0 + HALF, T_EN_FALL + 5.0 + HALF + RAMP, VDD, 0.0))
    segs = [(a, b, v0, v1) for a, b, v0, v1 in segs if b > a]
    segs.sort(key=lambda x: x[0])
    return segs


def _sample(segs, tt, default=0.0):
    """Voltage on the segment list at `tt` (flat extrapolation at both ends)."""
    for t0, t1, v0, v1 in segs:
        if tt < t0:
            return v0
        if tt <= t1:
            return v1 if t1 == t0 else v0 + (v1 - v0) * (tt - t0) / (t1 - t0)
    return segs[-1][3] if segs else default


def write_raw(path, segs, t_end=T_END):
    """Rawfile for a segment list; every boundary and midpoint is sampled."""
    times = {0.0, t_end}
    for t0, t1, _v0, _v1 in segs:
        times.add(max(0.0, min(t_end, t0)))
        times.add(max(0.0, min(t_end, t1)))
        times.add(max(0.0, min(t_end, (t0 + t1) / 2.0)))
    grid = sorted(times)

    en = [(0.0, T_EN_RISE, 0.0, 0.0),
          (T_EN_RISE, T_EN_RISE + RAMP, 0.0, VDD),
          (T_EN_RISE + RAMP, T_EN_FALL, VDD, VDD),
          (T_EN_FALL, T_EN_FALL + RAMP, VDD, 0.0),
          (T_EN_FALL + RAMP, t_end, 0.0, 0.0)]
    rst = [(0.0, 1.0, 0.0, 0.0), (1.0, 1.0 + RAMP, 0.0, VDD),
           (1.0 + RAMP, t_end, VDD, VDD)]

    names = ["time", "v(x1.LOOP)", "v(sense_en)", "v(sense_rst_n)"]
    with open(path, "wb") as fh:
        fh.write(b"Title: stop-transient fixture\n")
        fh.write(b"Plotname: Transient Analysis\n")
        fh.write(b"Flags: real\n")
        fh.write(f"No. Variables: {len(names)}\n".encode())
        fh.write(f"No. Points: {len(grid)}\n".encode())
        fh.write(b"Variables:\n")
        fh.write(b"\t0\ttime\ttime\n")
        for i, n in enumerate(names[1:], 1):
            fh.write(f"\t{i}\t{n}\tvoltage\n".encode())
        fh.write(b"Binary:\n")
        for tt in grid:
            fh.write(struct.pack("<d", tt * 1e-9))
            fh.write(struct.pack("<d", _sample(segs, tt)))
            fh.write(struct.pack("<d", _sample(en, tt)))
            fh.write(struct.pack("<d", _sample(rst, tt)))
    return path


CASES = [
    # name, kwargs, declared expectations
    ("all_full", dict(), dict(n_runt=0, n_noise=0, min_full=N_PULSES,
                              exact_after_close=0, exact_straddling=0)),
    ("marginal_60pct", dict(extra=[(TRAIN_END + 10, 0.5),
                                    (TRAIN_END + 30, 0.5)]),
     dict(n_runt=2)),
    ("marginal_75pct", dict(extra=[(TRAIN_END + 10, 0.75),
                                    (TRAIN_END + 30, 0.75)]),
     dict(n_runt=2)),
    # A level that never reaches the 15 % detection threshold is excluded by
    # design (it cannot switch an input whose threshold is ~50 % of the rail).
    ("step_below_threshold", dict(steps=[(1.0, 0.10)]),
     dict(n_noise=0, n_runt=0)),
    # A partial pulse at the gate close: it must be counted as a runt and
    # reported as straddling the close, and it must not be miscounted as an
    # edge after the close.
    ("truncated_at_close", dict(truncated=0.5),
     dict(n_runt=1, exact_after_close=0, exact_straddling=1)),
    ("after_close", dict(after_close_pulse=True), dict(min_after_close=1)),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", default=os.path.join(REPO,
                                                      "runs/transient-fixtures"))
    ap.add_argument("--summary", default=os.path.join(
        REPO, "data/safe10/freeze", "stop_transient_fixtures.json"))
    a = ap.parse_args()
    os.makedirs(a.workdir, exist_ok=True)
    rows = []
    for name, kw, want in CASES:
        path = os.path.join(a.workdir, f"fixture_{name}.raw")
        write_raw(path, build(**kw))
        res = cls.classify(path, VDD, "LOOP")
        checks = []
        for key in ("n_runt", "n_noise"):
            if key in want:
                checks.append(dict(check=f"{key}={want[key]}",
                                   ok=res.get(key) == want[key],
                                   got=res.get(key)))
        if "min_full" in want:
            checks.append(dict(check=f"n_full>={want['min_full']}",
                               ok=(res.get("n_full") or 0) >= want["min_full"],
                               got=res.get("n_full")))
        for key, want_v in (("crossings_after_close",
                             want.get("exact_after_close")),
                            ("pulses_straddling_close",
                             want.get("exact_straddling"))):
            if want_v is not None:
                checks.append(dict(check=f"{key}=={want_v}",
                                   ok=res.get(key) == want_v,
                                   got=res.get(key)))
        if "min_after_close" in want:
            checks.append(dict(
                check=f"crossings_after_close>={want['min_after_close']}",
                ok=(res.get("crossings_after_close") or 0)
                >= want["min_after_close"],
                got=res.get("crossings_after_close")))
        rows.append(dict(fixture=name, result={k: res.get(k) for k in
                                               ("n_rise_crossings", "n_full",
                                                "n_runt", "n_noise",
                                                "crossings_after_close",
                                                "pulses_straddling_close",
                                                "error")},
                         checks=checks,
                         ok=all(c["ok"] for c in checks)))
    failed = [r["fixture"] for r in rows if not r["ok"]]
    summary = dict(
        tool="tools/ro/test_classify_stop_transient.py",
        purpose="stop-transient classifier fixtures: every pulse above the low "
                "threshold must be classified by its peak, including pulses "
                "that never reach the analyzer's 70 % rise threshold",
        vdd=VDD, cases=rows, passed=not failed, failures=failed)
    os.makedirs(os.path.dirname(a.summary), exist_ok=True)
    json.dump(summary, open(a.summary, "w"), indent=1)
    for r in rows:
        print(f"  {r['fixture']:18s} ok={r['ok']}  {r['result']}")
        for c in r["checks"]:
            if not c["ok"]:
                print(f"      FAIL {c['check']}: got {c['got']}")
    print(f"summary: {a.summary}")
    if failed:
        print("FAILED: " + ", ".join(failed))
        return 1
    print(f"all {len(rows)} classifier fixtures behaved as declared")
    return 0


if __name__ == "__main__":
    sys.exit(main())
