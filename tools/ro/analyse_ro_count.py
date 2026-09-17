#!/usr/bin/env python3
"""Check a counter-inclusive transient against the measurement window it ran in.

Input is one rawfile produced by `run_ro_count_case.py` (either the
free-running deck or the `--window` deck).  The deck saves the loop node, every
counter bit (Q0..Q15) and, in window mode, the `en` and `rst_n` control nets
through zero-volt sense branches (`sense_en`, `sense_rst_n`), so this script
can answer, without assuming the counter is correct:

  * **where the measurement window is** - from the control waveforms, not from
    the counter's own first and last transitions;
  * **how many ring edges the counter was offered** - every qualified rising
    edge of the loop node after reset release and inside the gate-open
    interval, including the edges during the loop's stop transient, because
    those are edges the hardware clocks too;
  * **what the counter recorded** - all 16 bits, required present, quiet and at
    a valid logic level at the decode point, decoded after the ripple stopped;
  * **whether every stage was actually exercised** - per-bit expected and
    observed toggles, first/last post-reset transition time and an explicit
    `exercised` flag, so an upper stage that never toggled is reported as
    untested instead of passing a permissive rate check;
  * **whether a frequency prediction is available** - the interval
    distribution (coefficient of variation and detected modes) is reported
    separately from the count, because "counts edges correctly" and "has a
    stable frequency prediction" are different claims.

Status vocabulary (a single machine-readable `status`, plus the booleans
`count_ok`, `settled`, `coverage_complete`, `rate_stable`):

  ok                                     counting, coverage and rate all good
  ok_partial_coverage                    counts correctly; some stage never toggled
  ok_unstable_rate                       counts correctly; period is not single-valued
  ok_partial_coverage_unstable_rate      both qualifications
  mismatch                               decoded count disagrees with the edges
  unsettled                              a counter bit was still moving at decode time
  invalid_level                          a counter bit is not at a valid logic level
                                         at the decode point (e.g. stuck mid-rail)
  missing_bits                           fewer than 16 counter bits were saved
  invalid_window                         the control waveforms give no usable window
  no_oscillation / counter_never_toggled / no_counter_bits_saved

Exit status: 0 when the run is accepted, 2 otherwise.  `--strict` (used by the
sweeps) additionally requires complete coverage and a stable rate for exit 0;
without it, `ok_partial_coverage` / `ok_unstable_rate` still exit 0 but are
never reported as plain `ok`.

Usage:
  analyse_ro_count.py <rawfile> --vdd 1.2 [--loop-node 'v(x1.n)']
                      [--en-node sense_en] [--rst-node sense_rst_n]
                      [--json out.json] [--strict] [--cv-max 0.05]
"""

import argparse
import bisect
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import analyse_spice_raw as raw_io  # noqa: E402
import analyse_ro_intervals as intervals_mod  # noqa: E402

N_BITS = 16
COUNT_MODULUS = 1 << N_BITS


def find(names, want):
    """Index of the first saved vector whose (lower-cased) name matches."""
    if want is None:
        return None
    want = want.lower()
    for i, n in enumerate(names):
        if n.lower() == want:
            return i
    for i, n in enumerate(names):
        if want in n.lower():
            return i
    return None


def rise_edges(times, volts, vdd):
    lo, hi = 0.3 * vdd, 0.7 * vdd
    return raw_io.crossings(times, volts, lo, hi, rise=True)


def negedges(times, volts, vdd):
    lo, hi = 0.3 * vdd, 0.7 * vdd
    return raw_io.crossings(times, volts, lo, hi, rise=False)


def all_transitions(times, volts, vdd):
    return sorted(rise_edges(times, volts, vdd) + negedges(times, volts, vdd))


def bit_state(v, vdd):
    return 1 if v > 0.5 * vdd else 0


# A counter bit may only be decoded if it sits in a valid logic band at the
# decode point.  `bit_state`'s 50 % threshold on its own classifies a mid-rail
# node (0.6 V on a 1.2 V rail) as a legitimate logic 0, so "quiet" alone is not
# enough: a stuck or undriven bit would be read as a settled zero.
LEVEL_LOW_FRACTION = 0.15
LEVEL_HIGH_FRACTION = 0.85


def level_valid(v, vdd, lo_fraction=LEVEL_LOW_FRACTION,
                hi_fraction=LEVEL_HIGH_FRACTION):
    """True when `v` is a valid logic low or high for the `vdd` rail."""
    return v <= lo_fraction * vdd or v >= hi_fraction * vdd


def settle_time(times, volts, vdd):
    """10-90 % transition duration of a logic net (0 if it never switches).

    Only sample pairs that span the full 10-90 % band are measured, so the
    duration is the edge itself and never the width of a pulse.
    """
    lo, hi = 0.1 * vdd, 0.9 * vdd
    durs = []
    for i in range(1, len(volts)):
        a, b = volts[i - 1], volts[i]
        dt = times[i] - times[i - 1]
        if dt <= 0:
            continue
        if a < lo and b > hi:
            t_lo = times[i - 1] + (lo - a) * dt / (b - a)
            t_hi = times[i - 1] + (hi - a) * dt / (b - a)
            durs.append(t_hi - t_lo)
        elif a > hi and b < lo:
            t_hi = times[i - 1] + (hi - a) * dt / (b - a)
            t_lo = times[i - 1] + (lo - a) * dt / (b - a)
            durs.append(t_lo - t_hi)
    return (sum(durs) / len(durs)) if durs else 0.0


def decode(times, cols, bits, vdd, t):
    """Counter value at time `t` from the saved bit waveforms."""
    i = max(0, bisect.bisect_right(times, t) - 1)
    val = 0
    for b, idx in sorted(bits.items()):
        if bit_state(cols[idx][i], vdd):
            val |= 1 << b
    return val


def value_at(times, volts, t):
    return volts[max(0, bisect.bisect_right(times, t) - 1)]


def analyse(raw, vdd=1.2, loop_node=None, en_node="sense_en",
            rst_node="sense_rst_n", decode_guard_ns=1.0, cv_max=0.05,
            tol_edges=1, dump_edges=False):
    names, cols = raw_io.read_raw(raw)
    times = cols[0]
    t_end = times[-1]
    t_start = times[0]
    out = dict(raw=os.path.basename(raw), vdd=vdd, n_vars=len(names),
               t_start_ns=t_start * 1e9, t_end_ns=t_end * 1e9)

    # ---------------------------------------------------------------- window --
    i_en = find(names, en_node)
    i_rst = find(names, rst_node)
    out["en_vector"] = names[i_en] if i_en is not None else None
    out["rst_vector"] = names[i_rst] if i_rst is not None else None
    t_en_rise = t_en_fall = t_rst_rise = None
    en_edge_ns = rst_edge_ns = None
    if i_en is not None:
        r = rise_edges(times, cols[i_en], vdd)
        f = negedges(times, cols[i_en], vdd)
        t_en_rise = r[0] if r else None
        t_en_fall = f[-1] if f else None
        out["n_en_rise"] = len(r)
        out["n_en_fall"] = len(f)
        en_edge_ns = settle_time(times, cols[i_en], vdd) * 1e9
    n_rst_releases = 0
    if i_rst is not None:
        r = rise_edges(times, cols[i_rst], vdd)
        # The counter's reset is asynchronous: a reset asserted *during* the
        # window clears the count and counting restarts at the last release, so
        # the counting window opens at the last release, not the first.
        n_rst_releases = len(r)
        t_rst_rise = r[-1] if r else None
        rst_edge_ns = settle_time(times, cols[i_rst], vdd) * 1e9
    out["n_reset_releases"] = n_rst_releases
    out["t_en_rise_ns"] = None if t_en_rise is None else t_en_rise * 1e9
    out["t_en_fall_ns"] = None if t_en_fall is None else t_en_fall * 1e9
    out["t_rst_release_ns"] = None if t_rst_rise is None else t_rst_rise * 1e9
    out["en_transition_ns"] = en_edge_ns
    out["rst_transition_ns"] = rst_edge_ns
    if t_en_rise is not None and t_en_fall is None:
        # The gate is still open at the end of the run: that is the legacy
        # free-running deck's contract, and the window is [rise, end of run].
        t_en_fall = t_end
        out["gate_closed_within_run"] = False
        out["window_mode"] = "open_to_end"
    else:
        out["gate_closed_within_run"] = True
        out["window_mode"] = "closed"
    if t_en_rise is None or t_en_fall is None:
        out["status"] = "invalid_window"
        out["detail"] = ("no usable gate waveform: the rawfile must save the "
                         "`en` control net (window deck sense branch)")
        out["count_ok"] = False
        out["settled"] = False
        out["invalid_level_bits"] = []
        out["levels_valid"] = False
        out["coverage_complete"] = False
        out["rate_stable"] = False
        return out
    # Both the gate and the counter's reset must have released before the first
    # edge the counter can record.
    t_open = max([x for x in (t_en_rise, t_rst_rise) if x is not None])
    out["t_count_start_ns"] = t_open * 1e9
    out["gate_open_ns"] = (t_en_fall - t_en_rise) * 1e9

    # ------------------------------------------------------------ ring edges --
    i_loop = find(names, loop_node) if loop_node else None
    if i_loop is None:
        i_loop = find(names, "_clk")
    if i_loop is None:
        best, best_sw = None, 0.0
        for i in range(1, len(names)):
            n = names[i].lower()
            if n.startswith("v(ctl") or n.startswith("v(sense_") or \
                    n in ("v(sup_vdd)", "v(sup_vss)"):
                continue
            sw = max(cols[i]) - min(cols[i])
            if sw > best_sw:
                best, best_sw = i, sw
        if best is None or best_sw < 0.5 * vdd:
            out["status"] = "no_oscillation"
            out["count_ok"] = False
            out["settled"] = False
            out["invalid_level_bits"] = []
            out["levels_valid"] = False
            out["coverage_complete"] = False
            out["rate_stable"] = False
            return out
        i_loop = best
    loop = cols[i_loop]
    out["loop_node"] = names[i_loop]
    rc = rise_edges(times, loop, vdd)
    out["n_rise_total"] = len(rc)
    if dump_edges:
        # Compact, archivable form of the waveform evidence: the edge times the
        # counter was offered, at 1 ps resolution.  Together with the per-bit
        # transition times below, this is what the count is re-derived from.
        out["loop_rising_edges_ns"] = [round(x * 1e9, 3) for x in rc]
    # Every rising edge the counter is offered: after the window opens and up
    # to the end of the run (the loop's stop transient still clocks the
    # counter, so stopping the count at the gate edge would undercount).
    offered = [x for x in rc if x > t_open + 1e-15]
    out["n_rise_offered"] = len(offered)
    # Edges that happened before the counter could record them (gate still
    # closed, or reset still asserted): reported so a run that starts mid-ring
    # cannot silently look like a clean window.
    out["pre_window_edges"] = len([x for x in rc if x <= t_open + 1e-15])
    if len(offered) < 3:
        out["status"] = "no_oscillation"
        out["detail"] = "fewer than three ring edges after the window opened"
        out["count_ok"] = False
        out["settled"] = False
        out["invalid_level_bits"] = []
        out["levels_valid"] = False
        out["coverage_complete"] = False
        out["rate_stable"] = False
        return out
    iv = [b - a for a, b in zip(offered, offered[1:])]
    ordered = sorted(iv)
    med = ordered[len(ordered) // 2]
    out["period_median_ns"] = med * 1e9
    out["f_count_mhz"] = (len(offered) - 1) / (offered[-1] - offered[0]) * 1e-6
    out["count_elapsed_ns"] = (offered[-1] - offered[0]) * 1e9
    # Boundary uncertainty: the gate edge itself is a threshold crossing with a
    # finite transition, so the edge count at the boundary is ambiguous by the
    # number of ring periods that fit in that transition, at least one edge.
    edge_amb = 1
    if en_edge_ns and med:
        edge_amb = max(1, int(en_edge_ns * 1e-9 / med) + 1)
    out["edge_ambiguity_edges"] = edge_amb
    out["tol_edges"] = max(tol_edges, edge_amb)

    # Startup vs steady state: the first two ring periods after the gate opens
    # are startup; the rest is steady state.
    t_steady = offered[0] + 2 * med
    steady = [x for x in offered if x >= t_steady]
    out["steady_state_edges"] = len(steady)
    out["startup_window_edges"] = len(offered) - len(steady)
    if len(steady) >= 4:
        s_iv = [b - a for a, b in zip(steady, steady[1:])]
        mean = sum(s_iv) / len(s_iv)
        var = sum((x - mean) ** 2 for x in s_iv) / len(s_iv)
        out["steady_period_ns"] = mean * 1e9
        out["steady_f_mhz"] = 1e-6 / mean
        out["steady_std_over_mean"] = (var ** 0.5) / mean
        modes = intervals_mod.modes(s_iv)
        out["steady_n_modes"] = len(modes)
        out["steady_modes"] = modes[:6]
        # Zero detected clusters is missing evidence, not a single mode.
        out["rate_stable"] = bool(modes) and len(modes) == 1 and \
            out["steady_std_over_mean"] <= cv_max
        out["rate_detail"] = ("unclassified_insufficient_evidence"
                              if not modes else
                              "multi_mode" if len(modes) > 1 else
                              "cv_above_limit"
                              if out["steady_std_over_mean"] > cv_max else "ok")
    else:
        out["steady_period_ns"] = None
        out["steady_f_mhz"] = None
        out["steady_std_over_mean"] = None
        out["steady_n_modes"] = None
        out["rate_stable"] = False
        out["rate_detail"] = "too_few_steady_edges"

    # ---------------------------------------------------------------- counter --
    bits = {}
    for i, n in enumerate(names):
        low = n.lower().strip()
        for b in range(N_BITS):
            if low in (f"v(q{b})", f"v(x1.q{b})", f"v(sense_q{b})"):
                bits[b] = i
    out["n_bits_saved"] = len(bits)
    if len(bits) < N_BITS:
        out["status"] = "missing_bits"
        out["detail"] = f"saved {sorted(bits)}; all {N_BITS} bits are required"
        out["count_ok"] = False
        out["settled"] = False
        out["invalid_level_bits"] = []
        out["levels_valid"] = False
        out["coverage_complete"] = False
        return out

    # Settle: the ripple must be quiet before the decode point.  The decode
    # point is the end of the run minus a guard, i.e. the earliest moment the
    # protocol's readout could sample.
    t_decode = t_end - decode_guard_ns * 1e-9
    per_bit = {}
    last_any = None
    for b in sorted(bits):
        ts, vs = times, cols[bits[b]]
        neg = [x for x in negedges(ts, vs, vdd) if x > t_open + 1e-15]
        pos = [x for x in rise_edges(ts, vs, vdd) if x > t_open + 1e-15]
        trans = sorted(neg + pos)
        last = trans[-1] if trans else None
        if last is not None and (last_any is None or last > last_any):
            last_any = last
        lvl = value_at(times, vs, t_decode)
        level_ok = level_valid(lvl, vdd)
        per_bit[b] = dict(
            toggles=len(trans),
            negedges=len(neg), riseedges=len(pos),
            first_transition_ns=None if not trans else trans[0] * 1e9,
            last_transition_ns=None if last is None else last * 1e9,
            level=bit_state(lvl, vdd),
            level_v=round(lvl, 4),
            level_valid=level_ok,
            settled=bool(last is None or last <= t_decode),
            exercised=bool(trans))
    out["per_bit"] = per_bit
    if dump_edges:
        # Archived waveform evidence: every counter bit transition, 1 ps
        # resolution, so the decoded count and the ripple rates can be
        # re-derived without the (large) rawfile.
        out["bit_transition_times_ns"] = {
            str(b): [round(x * 1e9, 3) for x in
                     sorted(negedges(times, cols[bits[b]], vdd) +
                            rise_edges(times, cols[bits[b]], vdd))]
            for b in sorted(bits)}
    out["last_bit_transition_ns"] = None if last_any is None else last_any * 1e9
    out["decode_time_ns"] = t_decode * 1e9
    out["unsettled_bits"] = [b for b in sorted(bits)
                             if not per_bit[b]["settled"]]
    out["invalid_level_bits"] = [b for b in sorted(bits)
                                 if not per_bit[b]["level_valid"]]
    out["levels_valid"] = not out["invalid_level_bits"]
    out["unexercised_bits"] = [b for b in sorted(bits)
                               if not per_bit[b]["exercised"]]
    # `settled` is about what the readout could sample at the decode point:
    # the bit must have stopped moving *and* be at a valid logic level.  A
    # stage that never toggled at all is a coverage finding, reported
    # separately in `unexercised_bits`.
    out["settled"] = (not out["unsettled_bits"]) and out["levels_valid"]
    final = decode(times, cols, bits, vdd, t_decode)
    out["counter_final"] = final
    out["counter_final_hex"] = hex(final)
    out["counter_final_settle_guard_ns"] = decode_guard_ns

    # -------------------------------------------------------------- coverage --
    # Stage b toggles once per 2**b ring edges; the expected count comes from
    # the independently observed edge count, not from the counter itself.
    n_edges = len(offered)
    cov = {}
    for b in sorted(bits):
        exp = n_edges // (2 ** b)
        got = per_bit[b]["toggles"]
        cov[b] = dict(expected=exp, observed=got, exercised=per_bit[b]["exercised"],
                      rate_ok=abs(got - exp) <= out["tol_edges"] + 1,
                      last_transition_ns=per_bit[b]["last_transition_ns"])
    out["per_bit_coverage"] = cov
    # A stage only counts as covered when it was actually exercised *and* ran at
    # its binary-carry rate: zero activity at an upper stage is untested, not a
    # pass.
    out["coverage_complete"] = all(c["rate_ok"] and c["exercised"]
                                   for c in cov.values())
    out["coverage_detail"] = (
        "all stages exercised and at rate" if out["coverage_complete"] else
        "unexercised:" + ",".join(str(b) for b in out["unexercised_bits"])
        if out["unexercised_bits"] else
        "rate_error:" + ",".join(str(b) for b, c in cov.items()
                                 if not c["rate_ok"]))

    # ------------------------------------------------------------- verdicts --
    out["ring_edges_in_window"] = n_edges
    out["counter_mod_65536"] = final % COUNT_MODULUS
    out["count_aliased"] = n_edges > COUNT_MODULUS
    # `count_error_edges` keeps its raw, unwrapped meaning: how far the 16-bit
    # counter's value sits from the offered edge count.  On an aliased run it is
    # large by construction, so it must not decide `count_ok` -- the counter can
    # only ever display `n_edges % 65536`, and a raw comparison would report a
    # mismatch for a perfectly correct run that happened to wrap.  The verdict
    # therefore uses the circular distance on the 16-bit ring.
    out["count_error_edges"] = final - n_edges
    circ = abs(final - (n_edges % COUNT_MODULUS))
    circ = min(circ, COUNT_MODULUS - circ)
    out["count_error_circular"] = circ
    out["count_ok"] = circ <= out["tol_edges"]
    # The period-estimate comparison is retained as a second, independent view,
    # but it can only be evaluated when a single period exists.
    if out.get("steady_f_mhz"):
        exp_periods = int((offered[-1] - offered[0]) /
                          (out["steady_period_ns"] * 1e-9))
        out["expected_periods_in_window"] = exp_periods
        ecirc = abs(final - (exp_periods % COUNT_MODULUS))
        out["count_matches_period_estimate"] = \
            min(ecirc, COUNT_MODULUS - ecirc) <= out["tol_edges"]
    else:
        out["expected_periods_in_window"] = None
        out["count_matches_period_estimate"] = None
    # The counter is 16 bits and wraps, so `final` alone is not an edge count
    # once more than 65535 edges have been offered: a run that wrapped reports a
    # small `final` and this quotient would be nonsense (it inflated the
    # full-width wrap run by the wrap count).  Reconstruct the edge count the
    # counter actually represents by adding the wrap count that matches the
    # independently measured edges, and say which one was used.
    elapsed_ns = (offered[-1] - offered[0]) * 1e9
    wraps_best, err_best = None, None
    for w in (0, 1, 2):
        err = abs(final + w * COUNT_MODULUS - n_edges)
        if err_best is None or err < err_best:
            wraps_best, err_best = w, err
    out["counter_wraps_inferred"] = wraps_best
    out["counter_edges_reconstructed"] = final + wraps_best * COUNT_MODULUS
    # seconds -> microseconds is a division by 1e-6 (== * 1e6); the earlier
    # revision multiplied by 1e-6 here, which is a seconds->megaseconds scale.
    out["f_count_from_counter_mhz"] = (
        (out["counter_edges_reconstructed"] * 1e-6 /
         (offered[-1] - offered[0])) if elapsed_ns > 0 else None)
    # Interval convention, stated exactly because two different intervals are in
    # play and confusing them is easy:
    #   * `f_count_from_counter_mhz`, `f_count_mhz` and `f_steady_mhz` all use
    #     the offered-edge span, `offered[-1] - offered[0]`.  The first divides
    #     the reconstructed count by it and the other two measure (edges-1)
    #     intervals over the same span, so they are directly comparable and both
    #     are free of the half-period sampling bias a window-duration quotient
    #     carries on a short run.
    #   * `count_window_ns` is the declared gate-open duration, `t_en_fall -
    #     t_en_rise`, and `f_count_over_window_mhz` is the count divided by it.
    #     That quotient is biased by up to one edge over the window (the first
    #     edge falls somewhere inside the first period), which is a few percent
    #     on a short window -- so it is reported for completeness, not as the
    #     frequency estimate.
    # For the freeze/reset control cases the window is not contiguous, and
    # `t_en_fall - t_en_rise` spans the paused intervals too, so the
    # window-duration quotient is only defined for a single, contiguous window.
    contiguous = (out.get("n_reset_releases", 0) <= 1
                  and out.get("n_en_rise", 0) <= 1
                  and out.get("gate_closed_within_run"))
    window_ns = (t_en_fall - t_en_rise) * 1e9 if contiguous else None
    out["count_window_ns"] = window_ns
    out["f_count_over_window_mhz"] = (
        n_edges * 1e-6 / (window_ns * 1e-9)
        if window_ns and window_ns > 0 else None)
    out["f_count_over_window_defined"] = bool(
        window_ns and window_ns > 0)

    # A decode taken while the ripple is still moving, or from a node that is
    # not at a valid logic level, is invalid, so both take priority over the
    # count comparison: reporting a mismatch there would blame the counter for
    # an analysis-window error.
    if out["unsettled_bits"]:
        out["status"] = "unsettled"
    elif out["invalid_level_bits"]:
        out["status"] = "invalid_level"
        out["detail"] = ("bits not at a valid logic level at the decode point: "
                         + ",".join(str(b) for b in out["invalid_level_bits"]))
    elif not out["count_ok"]:
        out["status"] = "mismatch"
    elif out["coverage_complete"] and out["rate_stable"]:
        out["status"] = "ok"
    elif out["coverage_complete"]:
        out["status"] = "ok_unstable_rate"
    elif out["rate_stable"]:
        out["status"] = "ok_partial_coverage"
    else:
        out["status"] = "ok_partial_coverage_unstable_rate"
    return out


def accepted(result, strict=False):
    """Acceptance rule shared by this tool and the sweeps."""
    if not result.get("count_ok"):
        return False
    if result.get("unsettled_bits"):
        return False
    if result.get("invalid_level_bits"):
        return False
    if strict and not (result.get("coverage_complete") and
                       result.get("rate_stable")):
        return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("raw")
    ap.add_argument("--vdd", type=float, default=1.2)
    ap.add_argument("--loop-node", default=None,
                    help="rawfile vector of the ring loop node, e.g. "
                         "'v(x1._1347_\\/clk)'")
    ap.add_argument("--en-node", default="sense_en")
    ap.add_argument("--rst-node", default="sense_rst_n")
    ap.add_argument("--decode-guard-ns", type=float, default=1.0)
    ap.add_argument("--cv-max", type=float, default=0.05,
                    help="largest steady-state interval CV still called stable")
    ap.add_argument("--strict", action="store_true",
                    help="exit 0 only for status 'ok'")
    ap.add_argument("--dump-edges", action="store_true",
                    help="also write the edge/transition time lists")
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    r = analyse(a.raw, a.vdd, a.loop_node, a.en_node, a.rst_node,
                a.decode_guard_ns, a.cv_max, dump_edges=a.dump_edges)
    print(json.dumps(r, indent=1))
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(r, fh, indent=1)
    return 0 if accepted(r, a.strict) else 2


if __name__ == "__main__":
    sys.exit(main())
