#!/usr/bin/env python3
"""Known-good / known-bad fixtures for the RO count analyzer.

Gate 1 of `docs/rtl-freeze-checklist.md` requires that the acceptance logic be
tested against waveforms whose correct verdict is known, instead of being
trusted because it once agreed with an older dataset.  This tool synthesises
ngspice-format rawfiles (no simulator, no PDK) that contain exactly the
waveforms a counter-inclusive run would produce, with one defect injected per
fixture, then checks both the returned status and the process exit code of
`analyse_ro_count.py`.

Fixtures:
  good                        binary ripple counting the ring edges        -> ok
  missing_edges               bit 0 drops every fourth toggle              -> mismatch
  missing_bits                bit 15 never saved                          -> missing_bits
  unexercised_upper           200 edges: bits >= 8 never toggle           -> ok_partial_coverage
  reset_transitions           toggles while reset is asserted, ignored    -> ok
  unstable_period             intervals alternate between two values      -> ok_unstable_rate
  ripple_not_settled          bit 15 still toggling inside the guard     -> unsettled
  no_oscillation              loop never switches                        -> no_oscillation
  no_gate_vector              `en` not saved                             -> invalid_window

Run:
  python3 tools/ro/test_analyse_ro_count.py [--workdir runs/analyzer-fixtures]
          [--summary data/safe10/count/analyzer_fixtures.json]
Exit status is 0 only when every fixture behaves as declared.
"""

import argparse
import json
import os
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)

import analyse_ro_count as ana  # noqa: E402
import analyse_ro_intervals as ivl  # noqa: E402

VDD = 1.2
PERIOD_S = 1e-9            # ring period
EDGE = 2e-12               # signal transition width used for sampling


class Sig:
    """Piecewise-constant logic signal: levels change at declared times."""

    def __init__(self, t0, v0=0.0):
        self.t0 = t0
        self.tr = [(t0, v0)]        # (time, level)

    def set(self, t, v):
        if self.tr and abs(self.tr[-1][0] - t) < 1e-15:
            self.tr[-1] = (t, v)
        else:
            self.tr.append((t, v))

    def value(self, t):
        v = self.tr[0][1]
        for tt, vv in self.tr:
            if tt <= t + 1e-18:
                v = vv
            else:
                break
        return v

    def transitions(self):
        return [t for t, _ in self.tr[1:]]


def write_raw(path, signals, t_end):
    """ngspice binary rawfile with a sparse grid at every transition."""
    times = {0.0, t_end}
    for s in signals.values():
        for t in s.transitions():
            times.add(max(0.0, t - EDGE))
            times.add(min(t_end, t + EDGE))
    grid = sorted(times)
    names = list(signals)
    vecs = [[s.value(t) for t in grid] for s in signals.values()]
    with open(path, "wb") as fh:
        fh.write(b"Title: analyzer fixture\n")
        fh.write(b"Plotname: Transient Analysis\n")
        fh.write(b"Flags: real\n")
        fh.write(f"No. Variables: {len(names) + 1}\n".encode())
        fh.write(f"No. Points: {len(grid)}\n".encode())
        fh.write(b"Variables:\n")
        fh.write(b"\t0\ttime\ttime\n")
        for i, n in enumerate(names):
            fh.write(f"\t{i + 1}\t{n}\tvoltage\n".encode())
        fh.write(b"Binary:\n")
        for j, t in enumerate(grid):
            fh.write(struct.pack("<d", t))
            for v in vecs:
                fh.write(struct.pack("<d", v[j]))
    return path


def build(name, n_edges=3000, t_rst=50e-9, t_en_rise=100e-9, en=True,
          rst=True, period=PERIOD_S, drop_every=0, bits=16, still_toggling=False,
          pre_reset_toggles=False, oscillate=True, alt_period=0.0):
    """Return (signals, t_end, expected) for one fixture."""
    # Ring rising edges: uniform, or alternating between two periods when a
    # non-stationary (multi-mode) waveform is wanted.
    edges = []
    t = t_en_rise
    for k in range(n_edges):
        edges.append(t)
        t += period * (1.0 + alt_period) if (alt_period and k % 2) else period
    t_en_fall = t if oscillate else t_en_rise + period
    t_end = t_en_fall + 60e-9
    sig = {}
    loop = Sig(0.0, 0.0)
    if oscillate:
        for k, te in enumerate(edges):
            p = (edges[k + 1] - te) if k + 1 < len(edges) else period
            loop.set(te, VDD)
            loop.set(te + p / 2.0, 0.0)
    else:
        loop.set(t_en_rise, VDD)
    sig["v(x1.LOOP)"] = loop

    if en:
        e = Sig(0.0, 0.0)
        e.set(t_en_rise, VDD)
        e.set(t_en_fall, 0.0)
        sig["v(sense_en)"] = e
    if rst:
        r = Sig(0.0, 0.0)
        r.set(t_rst, VDD)
        sig["v(sense_rst_n)"] = r

    # Counter bits: after `accepted` edges bit b holds bit b of the count, so
    # bit b toggles floor(accepted / 2**b) times.  `drop_every` removes toggles
    # from the clock itself, which is the "counter misses edges" defect.
    accepted = 0
    toggles = {b: [] for b in range(bits)}
    for k, te in enumerate(edges, start=1):
        if drop_every and (k % drop_every == 0):
            continue
        accepted += 1
        for b in range(bits):
            if ((accepted >> b) & 1) != (((accepted - 1) >> b) & 1):
                toggles[b].append(te + period / 4.0)
    for b in range(bits):
        q = Sig(0.0, 0.0)
        lvl = 0.0
        for t in toggles[b]:
            lvl = VDD if lvl == 0.0 else 0.0
            q.set(t, lvl)
        sig[f"v(Q{b})"] = q
    if still_toggling:
        q = sig["v(Q15)"]
        q.set(t_end - 0.2e-9, VDD if q.value(t_end - 1e-9) == 0 else 0.0)
    if pre_reset_toggles:
        # Activity while reset is asserted must not be counted.
        for b in (0, 1, 2):
            q = sig[f"v(Q{b})"]
            q.set(10e-9, VDD)
            q.set(20e-9, 0.0)
    path = None
    expected = dict(n_edges=n_edges, accepted=accepted if drop_every else n_edges)
    return sig, t_end, expected


def run_fixture(workdir, name, expect_status, expect_exit, **kw):
    sig, t_end, meta = build(name, **kw)
    path = os.path.join(workdir, f"fixture_{name}.raw")
    write_raw(path, sig, t_end)
    res = ana.analyse(path, vdd=VDD)
    cli = subprocess.run(
        [sys.executable, os.path.join(HERE, "analyse_ro_count.py"), path,
         "--vdd", str(VDD), "--json", os.path.join(workdir, f"fixture_{name}.json")],
        capture_output=True, text=True)
    ok_status = res.get("status") == expect_status
    ok_exit = cli.returncode == expect_exit
    row = dict(fixture=name, status=res.get("status"),
               expected_status=expect_status, status_ok=ok_status,
               exit_code=cli.returncode, expected_exit=expect_exit,
               exit_ok=ok_exit, count_ok=res.get("count_ok"),
               settled=res.get("settled"),
               coverage_complete=res.get("coverage_complete"),
               rate_stable=res.get("rate_stable"),
               counter_final=res.get("counter_final"),
               ring_edges=res.get("ring_edges_in_window"),
               unexercised_bits=res.get("unexercised_bits"),
               detail=res.get("detail") or res.get("coverage_detail")
               or res.get("rate_detail"))
    return row, res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", default=os.path.join(REPO,
                                                      "runs/analyzer-fixtures"))
    ap.add_argument("--summary",
                    default=os.path.join(REPO, "data/safe10/count",
                                         "analyzer_fixtures.json"))
    a = ap.parse_args()
    os.makedirs(a.workdir, exist_ok=True)
    rows = []

    # Known-good: the counter tracks the ring exactly, and enough edges are
    # offered that all 16 stages toggle (bit 15 needs 32768 edges).
    r, res = run_fixture(a.workdir, "good", "ok", 0, n_edges=33000)
    rows.append(r)
    good = res

    # Known-bad fixtures, one defect each.
    for name, status, kw in [
        ("missing_edges", "mismatch", dict(drop_every=4)),
        ("missing_bits", "missing_bits", dict(bits=15)),
        ("unexercised_upper", "ok_partial_coverage", dict(n_edges=200)),
        ("reset_transitions", "ok", dict(n_edges=33000,
                                         pre_reset_toggles=True)),
        ("unstable_period", "ok_unstable_rate",
         dict(n_edges=33000, alt_period=0.45)),
        ("ripple_not_settled", "unsettled", dict(still_toggling=True)),
        ("no_oscillation", "no_oscillation", dict(oscillate=False)),
        ("no_gate_vector", "invalid_window", dict(en=False)),
    ]:
        r, _ = run_fixture(a.workdir, name, status,
                           0 if status.startswith("ok") else 2, **kw)
        rows.append(r)

    # The reset-transition fixture must have ignored the pre-reset activity:
    # its decoded count still equals the edges offered inside the window.
    rt = [r for r in rows if r["fixture"] == "reset_transitions"][0]
    rt["reset_excluded"] = bool(rt["count_ok"])

    # Interval classifier: no clusters means "unclassified", never one mode.
    ivl_rows = []
    for label, intervals, want in [
        ("clean", [1e-9] * 40, "single_mode"),
        ("empty", [], "too_few_edges"),
        ("sparse_evidence", [1e-9] * 5, "unclassified"),
        ("two_modes", [1e-9, 1.5e-9] * 30, "multi_mode(2)"),
    ]:
        got = ivl.classify(intervals)
        ivl_rows.append(dict(case=label, got=got, want=want, ok=got == want))

    failed = ([r["fixture"] for r in rows
               if not (r["status_ok"] and r["exit_ok"])] +
              [f"intervals:{r['case']}" for r in ivl_rows if not r["ok"]])
    summary = dict(
        tool="tools/ro/test_analyse_ro_count.py",
        purpose="Gate 1 analyzer fixtures (known-good and known-bad waveforms)",
        vdd=VDD, ring_period_ns=PERIOD_S * 1e9,
        fixtures=rows, interval_classifier=ivl_rows,
        passed=not failed, failures=failed,
        good_fixture=dict(status=good.get("status"),
                          counter_final=good.get("counter_final"),
                          ring_edges=good.get("ring_edges_in_window"),
                          coverage_complete=good.get("coverage_complete"),
                          rate_stable=good.get("rate_stable")))
    with open(a.summary, "w") as fh:
        json.dump(summary, fh, indent=1)
    for r in rows:
        print(f"  {r['fixture']:22s} status={r['status']:28s} "
              f"exit={r['exit_code']} ok={r['status_ok'] and r['exit_ok']}")
    for r in ivl_rows:
        print(f"  intervals:{r['case']:16s} got={r['got']:16s} ok={r['ok']}")
    print(f"summary: {a.summary}")
    if failed:
        print("FAILED: " + ", ".join(failed))
        return 1
    print(f"all {len(rows)} fixtures and {len(ivl_rows)} interval cases behaved "
          f"as declared")
    return 0


if __name__ == "__main__":
    sys.exit(main())
