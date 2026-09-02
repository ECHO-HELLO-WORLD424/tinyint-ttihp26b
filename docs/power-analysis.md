# Post-layout power: why the dynamic accumulator saves so little

This note explains the small same-die energy reduction measured on the hardened
IHP SG13G2 implementation. All figures come from the released P03/P04 flow
(`synthesis/run_post_layout_power.sh`): the routed gate netlist simulated with
an identical 8,192-MAC mixed trace in each mode, each VCD annotated onto the
nominal extracted SPEF in the pinned LibreLane/OpenSTA image, with all 3,152
design pins/nodes annotated and zero unannotated pins.

## 1. Measured totals

| mode | sequential | combinational | clock | leakage | total |
|------|-----------:|--------------:|------:|--------:|------:|
| conventional | 219.33 uW | 64.60 uW | 109.16 uW | 1.07 uW | 393.09 uW |
| dynamic-8  | 220.87 uW | 56.73 uW | 109.16 uW | 1.06 uW | 386.76 uW |
| dynamic-12 | 220.89 uW | 58.95 uW | 109.16 uW | 1.06 uW | 389.00 uW |
| dynamic-16 | 221.42 uW | 62.48 uW | 109.16 uW | 1.06 uW | 393.06 uW |

Reduction versus conventional: dynamic-8 1.61%, dynamic-12 1.04%, dynamic-16
0.008%. The clock group is byte-identical in all four modes.

## 2. The saving is combinational-only

The clock network is 27.8% of the chip and is mode-invariant (no clock gating,
by design). Sequential power (55.8%+ of the chip) *increases* slightly in the
dynamic modes. The entire measured saving is the combinational delta: 64.60 uW
(conventional) vs 56.73 uW (dynamic-8) = 7.87 uW, of which about 1.5 uW is
returned to the sequential group, leaving 6.33 uW net.

Per-instance OpenSTA power reports (40 accumulator FFs, 20 per bank) show why:

| mode | conventional bank | dynamic bank | both banks |
|------|------------------:|-------------:|-----------:|
| conventional (conv active) | 63.08 uW | 53.21 uW (idle) | 116.29 uW |
| dynamic-8 (dyn active) | 53.18 uW (idle) | 64.12 uW | 117.30 uW |

Two facts stand out:

1. A fully *unwritten* bank still costs about 53 uW, because every FF's internal
   clock buffer and clock-to-Q path toggle at 50 MHz regardless of the write
   enable. This clocked-idle baseline is roughly 82% of the active-bank cost and
   data gating cannot touch it.
2. The dynamic bank *active* (64.12 uW) costs slightly more than the
   conventional bank active (63.08 uW) because the write-enable muxes add D-path
   capacitance. At the register level the dynamic accumulator does not save
   anything net; the 7.87 uW saving is almost entirely in combinational logic.

The per-stage breakdown of the dynamic bank confirms the data gating itself is
working. Idle per nibble is about 10.6 uW; active nibbles cost +3.3..+5.2 uW,
while cold nibbles cost only +0.3..+1.5 uW over idle. The absolute saving is
small because (a) the idle baseline dominates and is invariant, and (b) the
high bits toggle rarely anyway, so there is little activity increment to remove.

## 3. Bit-exactness fixes the state toggling

The four gate-level traces all show exactly 19,037 accumulator-state toggles:

| mode | conv bank | dyn[7:0] | dyn[11:8] | dyn[15:12] | dyn[19:16] | total |
|------|----------:|--------:|----------:|-----------:|-----------:|------:|
| conventional | 19037 | 0 | 0 | 0 | 0 | 19037 |
| dynamic-8  | 0 | 18227 | 599 | 107 | 104 | 19037 |
| dynamic-12 | 0 | 18227 | 599 | 107 | 104 | 19037 |
| dynamic-16 | 0 | 18227 | 599 | 107 | 104 | 19037 |

The dynamic accumulator is bit-exact, so the *value* sequence and therefore the
per-bit toggling are identical in every mode and identical to the conventional
bank. A high bit changes only when a carry or borrow reaches it, in either
architecture. The dynamic modes therefore reduce combinational *evaluation*,
not state transitions. The release activity assertion
(`synthesis/analyze_activity.py`) compares cold against active regions *within*
the dynamic bank, which is trivially true; it does not demonstrate any reduction
relative to the conventional bank's own high bits, because there is none.

## 4. The accumulator datapath is a small fraction of the chip

The mode deltas bound the accumulator's adder cost. Activating one more nibble
costs 2.2..3.0 uW, so the whole 20-bit adder datapath is roughly 11-12 uW,
about 3% of the 393 uW chip. Even eliminating 100% of the cold-stage adder
power would save only ~3%, and dynamic-8 already captures most of that
(6.33 uW of an ~11 uW available pool), before the dynamic event logic overhead
and the register mux penalty.

## 5. Why dynamic-16 is a non-result

Only the top nibble is cold in dynamic-16, and bits 16-19 toggle just 104 times
in the whole 8,192-MAC trace. There is almost nothing to save: 0.03 uW, 0.008%.

## 6. What would actually move the number

The dominant mode-invariant terms are the 50 MHz clock tree (109 uW) and the
clocked-idle register baseline (~53 uW for a whole idle bank, ~10.6 uW per
nibble). Within the current bit-exact, data-gated, no-clock-gating architecture
the measured 1.6% is close to the ceiling.

The one lever with real headroom is **clock gating the cold stages** (and/or the
unselected bank), which would remove most of the ~10.6 uW/nibble clocked-idle
register cost instead of only the ~1.5 uW activity increment. That is a
deliberate architecture change: it contradicts the current design goal of
synchronous data gating with a fully-routed clock network, requires
clock-gating cells, and would need re-hardening before it could be measured in
silicon. It is prototyped and quantified in `docs/clock-gating-prototype.md`.