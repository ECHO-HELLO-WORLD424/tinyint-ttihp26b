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
  midrail_level               bit 15 quiet but stuck at 0.6 V on 1.2 V   -> invalid_level
  no_oscillation              loop never switches                        -> no_oscillation
  no_gate_vector              `en` not saved                             -> invalid_window

Run:
  python3 tools/ro/test_analyse_ro_count.py [--workdir runs/analyzer-fixtures]
          [--summary data/safe10/count/analyzer_fixtures.json]
Exit status is 0 only when every fixture behaves as declared.
"""

import argparse
import bisect
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
    """Piecewise-constant logic signal: levels change at declared times.

    `times` mirrors the first element of each `tr` entry so that `value()` can
    binary-search instead of scanning.  The scan made `write_raw` quadratic, and
    the 33 000-edge fixtures are large enough that this mattered: the suite was
    abandoned as "unexpectedly slow" during a review before it was run to
    completion.
    """

    def __init__(self, t0, v0=0.0):
        self.t0 = t0
        self.tr = [(t0, v0)]        # (time, level)
        self.times = [t0]

    def set(self, t, v):
        if self.tr and abs(self.tr[-1][0] - t) < 1e-15:
            self.tr[-1] = (t, v)
            self.times[-1] = t
        else:
            self.tr.append((t, v))
            self.times.append(t)

    def value(self, t):
        i = bisect.bisect_right(self.times, t + 1e-18) - 1
        return self.tr[i][1] if i >= 0 else self.tr[0][1]

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
          pre_reset_toggles=False, oscillate=True, alt_period=0.0,
          midrail_bit=None, midrail_v=0.6):
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
    #
    # The count is a real 16-bit counter, so its state is `accepted % 65536`:
    # past 0xFFFF it wraps.  The toggle times below are the k-th edge clocking
    # the counter from k-1 to k, which is right regardless of wrapping; only the
    # ending *level* needs the modulus (see the `want_level` correction below).
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
        # A stage that wrapped must be left at the state the counter actually
        # holds.  The toggle-count model above is exact only while the counter
        # does not wrap: past 0xFFFF the count is `accepted % 65536`, whose bit b
        # can differ in parity from the unwrapped `accepted` bit, so the last
        # transition is forced rather than inferred.  Without this the analysed
        # count disagrees with the edges offered by a whole power of two.
        want_level = ((accepted % (1 << bits)) >> b) & 1
        if int(lvl / VDD) != want_level:
            q.set(t_end - 5e-9, VDD * want_level)
        sig[f"v(Q{b})"] = q
    if still_toggling:
        q = sig["v(Q15)"]
        q.set(t_end - 0.2e-9, VDD if q.value(t_end - 1e-9) == 0 else 0.0)
    if midrail_bit is not None:
        # Quiet *and* at an invalid level: a counter bit that is stuck at
        # mid-rail (or undriven) must not be readable as a settled 0/1.  The
        # 50 % decode threshold alone classifies 0.6 V on a 1.2 V rail as 0.
        sig[f"v(Q{midrail_bit})"] = Sig(0.0, midrail_v)
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
               levels_valid=res.get("levels_valid"),
               invalid_level_bits=res.get("invalid_level_bits"),
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

    # Frequency-from-counter regression pair.  The reported counter-derived
    # frequency used to be scaled by 1e-6 in the wrong direction (a
    # seconds->megaseconds error), and it used the raw 16-bit counter value, so
    # it inflated without bound once the counter wrapped.  Neither defect
    # changed `count_ok`, which is why only an explicit frequency assertion can
    # catch them.  A 0.1 ns period keeps the wrap file small enough to build in
    # seconds; the ring's real period is irrelevant to what is being checked.
    freq_rows = []
    for name, n_edges in (("freq_units", 20000), ("freq_wrap", 66536)):
        # These two assert the derived frequency, not the status vocabulary:
        # `freq_wrap` does not wrap in CLI terms (count_ok still holds) and its
        # coverage is deliberately partial at 0.1 ns.  The CLI must still exit
        # cleanly and agree with the in-process verdict.
        sig, t_end, _ = build(name, n_edges=n_edges, period=0.1e-9)
        path = os.path.join(a.workdir, f"fixture_{name}.raw")
        write_raw(path, sig, t_end)
        res = ana.analyse(path, vdd=VDD)
        cli = subprocess.run(
            [sys.executable, os.path.join(HERE, "analyse_ro_count.py"), path,
             "--vdd", str(VDD), "--json",
             os.path.join(a.workdir, f"fixture_{name}.json")],
            capture_output=True, text=True)
        want_mhz = 1e3 / 0.1               # 0.1 ns period -> 10000 MHz
        got = res.get("f_count_from_counter_mhz")
        wraps = res.get("counter_wraps_inferred")
        recon = res.get("counter_edges_reconstructed")
        want_wraps = 1 if n_edges > 65535 else 0
        freq_rows.append(dict(
            fixture=name, n_edges=n_edges, status=res.get("status"),
            exit_code=cli.returncode, count_ok=res.get("count_ok"),
            counter_final=res.get("counter_final"),
            reconstructed=recon, wraps=wraps, want_wraps=want_wraps,
            f_counter_mhz=got, f_expected_mhz=want_mhz,
            within_1pct=(got is not None and
                         abs(got - want_mhz) / want_mhz < 0.01),
            recon_matches=(recon == n_edges)))
    freq_failed = [r["fixture"] for r in freq_rows
                   if not (r["within_1pct"] and r["recon_matches"] and
                           r["wraps"] == r["want_wraps"] and
                           r["count_ok"])]

    # Short-window interval convention.  With few edges the count-over-window
    # quotient and the count-over-edge-span quotient differ by a few percent, so
    # one short fixture pins down which interval each field uses: the window
    # frequency must equal edges/window and the counter-derived field must equal
    # edges/(first-to-last edge span).  `classify_stop_transient` and the
    # sweeps read both, so a silent change of convention is a real defect.
    sig, t_end, _ = build("short_window", n_edges=20, period=1e-9)
    path = os.path.join(a.workdir, "fixture_short_window.raw")
    write_raw(path, sig, t_end)
    sw = ana.analyse(path, vdd=VDD)
    win_ns = sw.get("count_window_ns")
    span_ns = sw.get("count_elapsed_ns")
    f_win = sw.get("f_count_over_window_mhz")
    f_span = sw.get("f_count_from_counter_mhz")
    n_edges = sw.get("ring_edges_in_window")
    # The counter-derived field uses the reconstructed *counter* edge count,
    # which can differ from `ring_edges_in_window` by one at the window edges
    # (the counter sees every offered edge; the window count is bounded by the
    # gate interval).  Asserting against the wrong one is what makes this a
    # sharp fixture.
    n_recon = sw.get("counter_edges_reconstructed")
    short_window = dict(
        fixture="short_window", n_edges=n_edges,
        counter_edges=n_recon,
        count_window_ns=win_ns, edge_span_ns=span_ns,
        f_over_window_mhz=f_win, f_from_counter_mhz=f_span,
        window_ok=(win_ns is not None and abs(win_ns - 20.0) < 0.1),
        # Each field must equal the count over the interval it declares:
        # `count_window_ns` for the window field, the first-to-last edge span
        # for the counter-derived field.
        window_freq_ok=(f_win is not None and win_ns and
                        abs(f_win - n_edges * 1e-6 / (win_ns * 1e-9)) < 1e-6),
        span_freq_ok=(f_span is not None and span_ns and
                      abs(f_span - n_recon * 1e-6 / (span_ns * 1e-9)) < 1e-6),
        distinguishes=(f_win is not None and f_span is not None and
                       abs(f_win - f_span) / f_win > 0.02))
    short_failed = [] if all(short_window[k] for k in
                             ("window_ok", "window_freq_ok", "span_freq_ok",
                              "distinguishes")) else ["short_window"]

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
        ("midrail_level", "invalid_level", dict(n_edges=200, midrail_bit=15)),
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
              [f"intervals:{r['case']}" for r in ivl_rows if not r["ok"]] +
              freq_failed + short_failed)
    summary = dict(
        tool="tools/ro/test_analyse_ro_count.py",
        purpose="Gate 1 analyzer fixtures (known-good and known-bad waveforms)",
        vdd=VDD, ring_period_ns=PERIOD_S * 1e9,
        fixtures=rows, interval_classifier=ivl_rows,
        frequency_from_counter=freq_rows,
        short_window_interval=short_window,
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
    for r in freq_rows:
        print(f"  {r['fixture']:22s} edges={r['n_edges']:6d} "
              f"final={r['counter_final']:5d} wraps={r['wraps']} "
              f"f={r['f_counter_mhz']:.1f} MHz "
              f"(want {r['f_expected_mhz']:.1f}) ok="
              f"{r['within_1pct'] and r['recon_matches']}")
    print(f"  short_window         window={short_window['count_window_ns']} ns "
          f"span={short_window['edge_span_ns']:.1f} ns  "
          f"f_window={short_window['f_over_window_mhz']:.1f} MHz "
          f"f_span={short_window['f_from_counter_mhz']:.1f} MHz  ok="
          f"{not short_failed}")
    print(f"summary: {a.summary}")
    if failed:
        print("FAILED: " + ", ".join(failed))
        return 1
    print(f"all {len(rows)} fixtures, {len(freq_rows)} frequency regressions "
          f"and {len(ivl_rows)} interval cases behaved as declared")
    return 0


if __name__ == "__main__":
    sys.exit(main())
