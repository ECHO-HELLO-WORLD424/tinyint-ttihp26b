#!/usr/bin/env python3
"""Check that the counter-inclusive transient actually counted the ring edges.

Input is one rawfile produced by `run_ro_count_case.py`.  The deck saves the
loop node, every counter bit (Q0..Q15) and the control pins, so this script can
answer, without any assumption about the counter's correctness:

  * the ring frequency from the loop-node crossings;
  * the counter's final state, decoded as a binary integer;
  * the number of counter transitions (each stage's negedge is one ripple step,
    so bit 0's negedges are the increments that reached the system);
  * whether the decoded count matches the edge count implied by the measured
    ring period over the observed window.

A counter that misses ripple steps (a stage that fails to toggle at speed, or
one that toggles twice) shows up as a decoded count that disagrees with the ring
frequency, and the per-bit transition counts localise which stage failed.

Usage:
  analyse_ro_count.py <rawfile> --vdd 1.2 [--reset-release-ns 2]
                      [--json out.json]
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import analyse_spice_raw as raw_io  # noqa: E402


def find(names, want):
    """Index of the first saved vector whose (lower-cased) name matches."""
    want = want.lower()
    for i, n in enumerate(names):
        if n.lower() == want:
            return i
    for i, n in enumerate(names):
        if want in n.lower():
            return i
    return None


def negedges(times, volts, vdd, skip=0):
    """Falling threshold crossings at 50 % VDD with 30/70 % hysteresis."""
    lo, hi = 0.3 * vdd, 0.7 * vdd
    return raw_io.crossings(times, volts, lo, hi, rise=False)[skip:]


def rise_edges(times, volts, vdd):
    lo, hi = 0.3 * vdd, 0.7 * vdd
    return raw_io.crossings(times, volts, lo, hi, rise=True)


def bit_state(v, vdd):
    return 1 if v > 0.5 * vdd else 0


def decode(times, bits, vdd, t):
    """Counter value at time `t` from the saved bit waveforms."""
    val = 0
    for b, (ts, vs) in sorted(bits.items()):
        # last sample at or before t
        i = 0
        for j, x in enumerate(ts):
            if x > t:
                break
            i = j
        if bit_state(vs[i], vdd):
            val |= 1 << b
    return val


def analyse(raw, vdd=1.2, reset_release_ns=2.0, edge_skip=4,
            loop_node=None):
    names, cols = raw_io.read_raw(raw)
    times = cols[0]
    t_end = times[-1]
    out = dict(raw=os.path.basename(raw), vdd=vdd, t_end_ns=t_end * 1e9,
               n_vars=len(names))
    # The loop node is named by the caller when it is known (the extraction
    # reports it); otherwise it is the fastest-switching node in the rawfile.
    i_loop = find(names, loop_node) if loop_node else None
    if i_loop is None:
        i_loop = find(names, "_clk")
    if i_loop is None:
        best, best_sw = None, 0.0
        for i in range(1, len(names)):
            n = names[i].lower()
            if n.startswith("v(ctl") or n in ("v(sup_vdd)", "v(sup_vss)"):
                continue
            sw = max(cols[i]) - min(cols[i])
            if sw > best_sw:
                best, best_sw = i, sw
        if best is None or best_sw < 0.5 * vdd:
            raise SystemExit(f"no switching node in {raw}")
        i_loop = best
    loop_name = names[i_loop]
    loop = cols[i_loop]
    rc = rise_edges(times, loop, vdd)
    out["loop_node"] = loop_name
    out["n_rise"] = len(rc)
    if len(rc) < edge_skip + 3:
        out["status"] = "no_oscillation"
        return out
    use = rc[edge_skip:]
    t_first, t_last = use[0], use[-1]
    periods = [b - a for a, b in zip(use, use[1:])]
    ordered = sorted(periods)
    med = ordered[len(ordered) // 2]
    kept = [p for p in periods if 0.5 * med <= p <= 1.5 * med]
    mean_p = sum(kept) / len(kept)
    out["period_ns"] = mean_p * 1e9
    out["f_osc_mhz"] = 1e-6 / mean_p
    n_edges = len(use) - 1          # full ring periods inside the window
    out["edge_window_ns"] = (t_last - t_first) * 1e9
    out["n_window_periods"] = n_edges
    # counter bits
    bits = {}
    for i, n in enumerate(names):
        low = n.lower().strip()
        for b in range(16):
            # ngspice names a saved subcircuit node v(x1.q0), but a port is
            # saved under its own bare name v(q0); accept both.
            if low in (f"v(q{b})", f"v(x1.q{b})"):
                bits[b] = (times, cols[i])
    if not bits:
        out["status"] = "no_counter_bits_saved"
        return out
    out["n_bits_saved"] = len(bits)
    # The deck runs the ring for a fixed simulated time and never stops it, so
    # the counter keeps rippling to the end of the run: "all bits quiet" is NOT
    # the right check.  The counter is instead read the way the chip reads it,
    # after the clock stops: decode every bit just after bit 0's last falling
    # edge, which is a moment the ripple has settled.
    quiet_from = t_end - 0.05 * (t_end - times[0])
    per_bit = {}
    for b, (ts, vs) in sorted(bits.items()):
        neg = negedges(ts, vs, vdd)
        pos = rise_edges(ts, vs, vdd)
        last = max([x for x in neg + pos], default=None)
        per_bit[b] = dict(negedges=len(neg), riseedges=len(pos),
                          last_transition_ns=None if last is None
                          else last * 1e9)
    out["per_bit"] = per_bit

    # Counting window: bit 0 is clocked by the ring itself, so its first
    # transition ends the startup and its last transition is the last count.
    q0_neg = [x for x in negedges(*bits[0], vdd=vdd) if x > 0]
    if not q0_neg:
        out["status"] = "counter_never_toggled"
        return out
    t_count0, t_count1 = q0_neg[0], q0_neg[-1]
    # Sample a little after bit 0's last edge: later stages ripple after it
    # (bit 15's propagation is bounded by the ripple chain, ~100 ps here).
    t_sample = min(t_count1 + 0.5e-9, t_end)
    final = decode(times, bits, vdd, t_sample)
    window_edges = len([x for x in rc if t_count0 <= x <= t_count1]) - 1
    out["counter_final"] = final
    out["counter_final_hex"] = hex(final)
    out["sample_time_ns"] = t_sample * 1e9
    out["count_window_ns"] = (t_count1 - t_count0) * 1e9
    out["q0_negedges"] = len(q0_neg)
    out["ring_edges_in_count_window"] = window_edges
    # A 16-bit ripple counter wraps at 65536; the dataset records `sat_win*`
    # overflow flags for that, and this deck runs for far fewer edges.
    out["counter_mod_65536"] = final % 65536
    out["count_error_edges"] = final - window_edges
    # Bit 0's edges are the ring's own edges, so a counter that tracks the ring
    # lands within one edge of the independently measured edge count.  The
    # tolerance is one edge because the window is bounded by two bit-0 edges.
    out["count_matches_ring_edges"] = abs(final - window_edges) <= 1
    out["count_ratio"] = (final / window_edges) if window_edges else None
    out["expected_periods_in_window"] = int((t_count1 - t_count0) / mean_p)
    out["count_matches_period_estimate"] = abs(
        final - out["expected_periods_in_window"]) <= 2
    # The stages must be a binary ripple of bit 0: stage b toggles once per
    # 2**b bit-0 periods.  A missed or doubled ripple in any stage breaks this.
    ripple_ok = True
    for b in sorted(bits):
        if b == 0:
            continue
        expected = len(q0_neg) / (2.0 ** b)
        got = per_bit[b]["negedges"]
        if abs(got - expected) > 1.0:
            ripple_ok = False
    out["ripple_stage_rates_ok"] = ripple_ok
    out["status"] = ("ok" if final > 0 and out["count_matches_ring_edges"]
                     and ripple_ok else "mismatch")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("raw")
    ap.add_argument("--vdd", type=float, default=1.2)
    ap.add_argument("--reset-release-ns", type=float, default=2.0)
    ap.add_argument("--edge-skip", type=int, default=4)
    ap.add_argument("--loop-node", default=None,
                    help="rawfile vector of the ring loop node, e.g. "
                         "'v(x1._1347_\\/clk)'")
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    r = analyse(a.raw, a.vdd, a.reset_release_ns, a.edge_skip, a.loop_node)
    print(json.dumps(r, indent=1))
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(r, fh, indent=1)


if __name__ == "__main__":
    main()
