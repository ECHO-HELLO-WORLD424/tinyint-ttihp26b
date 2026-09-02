# Clock-gating prototype: recovering the energy the data-gated tapeout leaves on the table

`docs/power-analysis.md` shows the released tapeout's dynamic accumulator
saves only ~1.6% because it is bit-exact (so state transitions are identical
to the conventional bank) and data-gated (so the clocked-idle register power,
the dominant cost, is mode-invariant). The one lever with real headroom is
integrated clock gating (ICG) of the cold stages: stop their flip-flop clocks
when no carry or borrow reaches them, instead of merely gating their D inputs.

This branch prototypes that variant, proves it is bit-exact, synthesizes it to
the IHP SG13G2 library, and quantifies the clock-activity reduction.

## Design

`src/tiny_int_dynamic_accumulator_clkgate.v` keeps the exact five-nibble
datapath and bit-exact write pattern of `tiny_int_dynamic_accumulator.v`, but
replaces the D-input write-enable muxes with the standard glitch-free ICG
structure:

```text
enable_N  = clear | load | (accumulate & stage_update_event[N])
gclk_N    = clk & D-latch(enable_N)     // latch transparent while clk is low
```

- Stage 0/1 (active in every dynamic mode) are gated only by
  `accumulate`/`clear`/`load`.
- Stages 2..4 are additionally gated by their carry/borrow event, so their
  flip-flop clocks stop toggling on cycles that do not reach them.
- The enable latches are real level-sensitive cells (`sg13g2_dlhq_1`,
  transparent while GATE is high, GATE = ~clk); the state flip-flops are the
  same `sg13g2_dfrbpq_1` used by the baseline.
- `clear`/`load` open every gate so reset and bias load still write all stages.

Yosys (`yowasp-yosys`, the container's WASM build) cannot map `$dlatch` to the
library latch cells in this version, so the latches are instantiated directly;
`dfflibmap` maps the state flip-flops and `abc -liberty` maps the logic.

## Synthesis result

| | baseline | clock-gated |
|---|---|---|
| cells | 367 | 350 |
| sg13g2_dfrbpq_1 (FFs) | 21 | 21 |
| sg13g2_dlhq_1 (ICG latches) | 0 | 5 |
| behavioral always blocks | 0 | 0 |

The ICG structure is slightly *smaller* than the baseline: the five enable
latches plus clock ANDs replace the per-flip-flop D-input enable muxes.

## Functional equivalence

A side-by-side testbench (`test/acc_clkgate_equiv_tb.v`) drives dense LFSR,
75%-zero sparse, signed carry/borrow, and counter-ramp streams through all
three dynamic modes in both signed and unsigned operation and compares every
observable each cycle. It passes bit-exact over 49,153 cycles.

## Clock-activity reduction (gate-level VCD)

The same 8,192-MAC mixed trace (as `power_activity_tb`) was simulated on both
synthesized netlists. Flip-flop clock-input toggles:

| clock net | toggles | vs clk |
|---|---|---|
| clk (both) | 16,409 | — |
| gclk_01 (stages 0/1 + overflow) | 16,386 | ~100% |
| gclk_2 (stage 2, cold in dynamic-8) | 1,574 | −90% |
| gclk_3 (stage 3) | 124 | −99.2% |
| gclk_4 (stage 4) | 56 | −99.7% |

The mechanism is real: cold-stage flip-flop clocks toggle 90-99.7% less.

## Cell-level flip-flop power (pre-layout OpenSTA, per stage)

| stage | baseline | clock-gated | reduction |
|---|---|---|---|
| stage 2 (bits 8-11) | 12.86 uW | 3.59 uW | −72% |
| stage 3 (bits 12-15) | 11.62 uW | 0.35 uW | −97% |
| stage 4 (bits 16-19) | 11.21 uW | 0.19 uW | −98% |
| cold stages total | 35.69 uW | 4.13 uW | −31.6 uW |

## Why the pre-layout *total* comparison is not meaningful

Reported pre-layout total cell power is ~9 uW *higher* for the clock-gated
netlist, but that is dominated by an artifact, not a fundamental property: the
prototype gates the clocks with single 1x `sg13g2_and2_1` gates, each driving
4-9 flip-flop clock pins. A 1x AND is far too weak for that fanout; the slow
clock edges inflate the active-stage flip-flop clock internal power by ~26 uW.
A real implementation uses a buffered ICG cell or lets CTS balance the gated
clocks. The pre-layout netlist also has no clock tree at all, so it cannot see
the dominant routed clock-network power that clock gating avoids.

## Routed-chip projection

The trusted routed per-instance data (`docs/power-analysis.md`) shows the
dynamic-8 cold stages (bits 8-19) consume 34.3 uW of register power, of which
~31.9 uW is the clocked-idle baseline that ICG targets. Clock gating removes
90-99.7% of that clock activity, so roughly 25-30 uW of the routed chip's
393 uW (~6-8%) is recoverable for the cold stages, before ICG infrastructure
overhead; gating the unselected whole bank (53 uW idle) is an additional,
larger lever. This is a projection, not a claim about measured silicon:
confirming it requires re-running hardening (CTS/place/route) with the
clock-gated RTL.

## Files

- `src/tiny_int_dynamic_accumulator_clkgate.v` — the prototype RTL.
- `test/acc_clkgate_equiv_tb.v` — side-by-side bit-exact equivalence test.
- `test/sim_build/power/` — synthesis scripts, gate netlists, VCD traces,
  dlhq behavioral stub, and OpenSTA power reports used above
  (`acc_base_synth.v`, `acc_cg_synth.v`, `acc_base_gl.vcd`, `acc_cg_gl.vcd`,
  `acc_*_perinst.txt`).

## Reproduction

Inside the development container (see `synthesis/README.md`):

```sh
# RTL equivalence
iverilog -g2012 -o /tmp/eq.vvp src/tiny_int_dynamic_accumulator.v \
  src/tiny_int_dynamic_accumulator_clkgate.v \
  test/sim_build/power/dlhq_stub.v test/acc_clkgate_equiv_tb.v \
  && vvp /tmp/eq.vvp

# Synthesize both variants to sg13g2 (yowasp-yosys)
source /ttsetup/venv/bin/activate
yowasp-yosys -s test/sim_build/power/synth_base.ys
yowasp-yosys -s test/sim_build/power/synth_cg.ys

# Gate-level simulation and OpenSTA power
cd test/sim_build/power
PDK=.../sg13g2_stdcell/verilog/sg13g2_stdcell.v
iverilog -g2012 -o base.vvp $PDK acc_base_synth.v acc_cg_power_tb.v \
  && vvp base.vvp +VCD=acc_base_gl.vcd
iverilog -g2012 -DACC_CLKGATE -o cg.vvp $PDK acc_cg_synth.v acc_cg_power_tb.v \
  && vvp cg.vvp +VCD=acc_cg_gl.vcd
# ... then annotate each VCD onto its netlist with OpenSTA and report_power
```

## Caveats

- The gated clocks are not through CTS and the enable latches are
  instantiated directly; timing (hold) on the gated clock branches is not
  checked.
- The pre-layout total-power comparison is confounded by the unbuffered gated
  clocks (see above) and must not be read as "clock gating is a net loss".
- The routed projection assumes the ICG infrastructure overhead is small
  relative to the ~32 uW it targets; only re-hardening can confirm.