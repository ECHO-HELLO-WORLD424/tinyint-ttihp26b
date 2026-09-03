# INT4 MAC accumulator energy proposals — comparison summary

This branch consolidates the four research proposals that attack the small
post-layout energy saving measured on the TinyInt tapeout (dynamic-8 −1.61%,
dynamic-12 −1.04%, dynamic-16 −0.008% versus the conventional accumulator;
see `docs/power-analysis.md` on `main`). Each proposal lives on its own branch
in the `proposal-mac-accu/` namespace; this branch carries the comparison
report, the raw measurement data, and the reproduction flow.

## 1. Root cause of the original 1.6% (context for every proposal)

- The routed chip is 393 µW: 219 µW sequential (56%) + 109 µW clock tree
  (28%) + 65 µW combinational + 1 µW leakage. The mode-selectable pool is
  only the cold-stage adder evaluation (~11–12 µW, ~3% of the chip).
- The duplicated accumulator banks cancel out of the A/B delta: each trace
  idles one bank at ~53 µW of clocked-idle register power (~10.6 µW per
  4-bit nibble), in *both* arms of the comparison.
- Bit-exactness fixes the state toggle sequence (19,037 toggles in every
  mode), so the architecture changes only *who evaluates the addition*,
  never *what is stored*.
- A workload sweep on the released netlist showed the mechanism is really
  **redundant sign-extension recovery**: the staged policy wins only when the
  addend's extension bits toggle (signed sign flips, ~49% of MACs) and
  crossings are rare. On carry-dense unsigned streams (+225 per MAC, ~94%
  crossings) dynamic-8 is **+1.56% worse** than conventional; on
  constant-product streams only the ~0.5–1.5 µW sequential overhead remains.

## 2. The four proposals

| branch | idea | commits |
|---|---|---|
| `proposal-mac-accu/1-unified-bank` | One five-nibble bank serves every policy; conventional ≡ boundary 20. The idle bank, bank muxes and per-bank addend gating are deleted. | `1335e6a`, audit `f9b2e02` |
| `proposal-mac-accu/2-icg-clock-gating` | Keep the dual bank but gate clocks with the real IHP library ICG cell `sg13g2_lgcp_1`: one ICG per bank root + cascaded per-cold-stage ICGs. | `0c668aa` |
| `proposal-mac-accu/3-event-scheduled` | Deferred carry/borrow: the hot path pushes ±1 events into signed counters; a maintenance engine drains cold stages on a /8 tick; READ flushes (documented 2-cycle read latency). | `2ca181e`, audit `d3e01f5` |
| `proposal-mac-accu/4-adaptive-boundary` | P1's unified bank plus an on-chip monitor: every 64 MACs, ≥16 sign-extension flips ⇒ boundary 8, otherwise boundary 20 (two-window hysteresis). Selector 3'b110 reports the effective boundary. | `3c3b110`, `2aa4477` |

## 3. Verification

All equivalence is against the frozen `main` composite core (two-compilation
byte-diff of per-cycle logs) or against the conventional bank as golden.

| proposal | core-level equivalence | leaf/behaviour suites | cocotb |
|---|---|---|---|
| P1 | 28/28 cells byte-identical (4 modes × 7 workloads incl. zero-skip and control/reset stream) | 17k-MAC 3-way leaf TB; mutation tests caught | remapped, compile-checked |
| P2 | 131,681 cycles byte-identical (all 4 modes × 4 workloads + control) | 110,667-cycle accumulator equivalence incl. reset-with-gates-closed; gating metrics TB | 33/33 |
| P3 | every-cycle represented-value + canonical + sticky-overflow equality vs conventional golden over 122,329 cycles (mixed/unsigned/const/zero/30k carry storm/30k borrow storm/random clear-load/reset) | adversarial 75k-cycle out-of-repo stress: 0 errors; core READ test (latency exactly 2, all selectors) | 33/33 |
| P4 | 28/28 cells byte-identical (selector-3'b110 upper nibble masked, the one documented deviation) | directed adaptation suite (per-phase optimal, bounded re-adaptation, CLEAR reload, per-MAC reference equality); metrics suite | remapped, monitor mirror in random model, compile-checked |

Independent audit (P1/P3): re-ran every claimed result, found no RTL bugs,
fixed two `test/Makefile` portability bugs, added the zero-skip matrix cells
(P1) and three adversarial cells (P3). Cocotb suites need the dev container
(cocotb is not installed on the host used for this comparison).

## 4. Synthesis (yosys 0.54, sg13g2_stdcell_typ_1p20V_25C, `tiny_int_core`, pre-layout)

| variant | cells | area µm² | FFs | `sg13g2_lgcp_1` | Δ area |
|---|---:|---:|---:|---:|---:|
| baseline (dual bank) | 732 | 9608.0 | 74 | — | — |
| P1 unified | 591 | 7354.8 | 53 | — | **−23.4%** |
| P2 ICG | 740 | 9671.4 | 74 | 5 | +0.7% |
| P3 event | 766 | 10125.2 | 75 | — | +5.4% |
| P4 adaptive | 654 | 8603.1 | 71 | — | −10.5% |

## 5. Gate-level power (OpenSTA 2.7.0, mixed 8192-MAC signed trace,
VCD-annotated activity, 0 unannotated pins in every run; pre-layout: no clock
tree, no wire capacitance — the routed chip adds the mode-invariant ~109 µW
clock tree to every variant, so the *ranking and register/combinational
deltas* are the signal, not the absolute watts)

| variant | m0 conventional µW | m1 dynamic-8 µW | Δ m1 vs baseline |
|---|---:|---:|---:|
| baseline | 259.16 | 249.41 | — |
| P1 unified | 200.49 | 192.50 | **−22.8%** |
| P2 ICG | 209.43 | **169.00** | **−32.2%** |
| P3 event | 253.40 | 253.93 | +1.8% |
| P4 adaptive | 254.59 | 255.07 | +2.3% |

Raw reports: `data/pw_<variant>_m<mode>.rpt`; cell statistics in
`data/yosys_stat_<variant>.txt`.

Mechanism breakdown (consistent with the routed-baseline per-group numbers):

- **P2**: the gated idle bank saves ~50 µW of sequential power in every mode
  (m0: 220.8→164.5 sequential) and the gated cold stages save a further
  ~30 µW in dynamic-8 (m1 sequential 131.9 µW) at the cost of only 6.9–8.1 µW
  of ICG cells. Measured clock-edge reduction: stage 2 −86.4%, stage 3
  −99.1%, stage 4 −99.9%, idle bank −100%.
- **P1**: removing the idle bank accounts for the whole −56 µW (sequential
  220.8→164.7 in m0); the cold-adder evaluation delta on top is unchanged
  from the baseline design.
- **P3**: cold register writes drop 39/60/85% (stages 2/3/4) and cold-domain
  activity is 2.5% of cycles, but the maintenance registers (counters,
  divider, flush state) run on the always-on clock with D-gating, which
  re-introduces the clocked-idle cost the architecture removed (+7.4 µW
  sequential versus the baseline hot set).
- **P4**: the monitor retunes per phase exactly as designed (boundary 8 for
  the signed-LFSR quarters, boundary 20 for sparse/zero/dense quarters, 3
  transitions, no thrash), but its always-on activity counters cost ~58 µW
  at 100% MAC occupancy — more than they save on this trace.

## 6. Routed confirmation (CI-hardened branches, post CI-fix commits)

After the CI fixes (`24f1516` on P1, `00de0c9` on P2) both branches hardened
cleanly in the `gds` workflow. Their released artifacts (routed netlist +
nominal extracted SPEF) were simulated with the identical released 8,192-MAC
mixed trace and annotated onto the extracted SPEF (0 unannotated pins), using
the same flow that produced the baseline numbers 386.90 (m0) / 380.92 (m1) µW
on `main`. Raw reports: `data/confirm_p*_m*.rpt`.

| routed chip | Seq µW | Comb µW | Clock µW | Total µW | Δ vs baseline |
|---|---:|---:|---:|---:|---:|
| baseline (main) m0 / m1 | 218.8 / 220.0 | 58.7 / 51.5 | 109.5 / 109.5 | 386.90 / 380.92 | — |
| **P1 unified m0 / m1** | 163.9 / 164.4 | 55.4 / 46.6 | 97.7 / 97.7 | **316.94 / 308.67** | **−18.1% / −19.0%** |
| P2 ICG m0 / m1 | 163.8 / 131.3 | 60.2 / 54.4 | 295.7 / 340.4 | 519.73 / 526.06 | **+34.3% / +38.1%** |

Interpretation:

- **P1's advantage is confirmed on the routed chip**: −55 µW of sequential
  (the removed idle bank), −12 µW of clock tree (9 vs 17 clock buffers for
  53 vs 74 FFs), and the cold-adder combinational delta on top. ~19% chip
  level, every mode, bit-exact.
- **P2's advantage is reversed on the routed chip.** The register gating
  works exactly as designed (sequential 131–164 µW vs 219–220 µW baseline),
  but the six gated clock domains (2 bank roots + 3 cascaded stage ICGs)
  forced CTS to build six trees: **51 clock buffers (3x the baseline's 17),
  0.71 ns worst clock skew (baseline 0.27 ns), and 295–340 µW of clock
  power** (+186…+231 µW), swamping the register savings. This is the same
  fragmentation failure as the earlier hand-gated prototype, now with proper
  drivers: the ICG cell fixed the *buffer weakness*, not the *tree count*.
- Consequence for the fusion recommendation: the tapeout candidate is
  **P1 (single bank) plus CTS-tractable gating only** — ideally a single
  shared cold-domain ICG (two clock domains total, not six) or root-level
  bank gating, with the per-stage cascaded ICGs dropped or re-planned.

## 7. Findings and recommendation

1. **P2 is the biggest power win (−32.2% core)** and demonstrably fixes the
   earlier hand-gated-clock failure (which had +29…+157 µW): the library ICG
   cell and the two-tree structure keep CTS tractable. A full LibreLane
   hardening with hold signoff on the gated clock branches is the remaining
   gate before tapeout claims.
2. **P1 is the biggest structural win** (−23% area, −21 FFs) and turns the
   same-die A/B into a temporal comparison on identical cells — a cleaner
   experiment.
3. **The recommended next-tapeout candidate is P1 plus CTS-tractable gating**
   (see the routed confirmation in section 6): P1 alone is already −18…−19%
   chip-level on the routed die; adding gating must be limited to at most two
   clock domains (a single shared cold-domain ICG over the unified bank's cold
   stages, or root-level bank gating). Per-stage cascaded ICG trees are
   measurably counterproductive at this scale.
4. **P3's arithmetic is sound and novel** but its power case requires
   clocking the maintenance domain from the divided tick (i.e., adding
   P2-style gating to the event-scheduled registers). As implemented it is a
   timing/architecture exploration, not an energy win.
5. **P4's monitor is functionally correct and per-phase optimal** but costs
   more than it saves at 100% MAC occupancy. Refinement path: reuse
   `pair_count` as the window counter, gate the monitor when `done`, or move
   counting to a slower domain; the cost also scales down with real workload
   duty cycles.

## 8. Reproduction

All flows ran with the pinned `ghcr.io/librelane/librelane:3.0.0.dev44`
image (yosys 0.54, OpenSTA 2.7.0) and the IHP SG13G2 liberty at
IHP-Open-PDK commit `cb7daaa8901016cf7c5d272dfa322c41f024931f`.

```sh
# per-variant synthesis (flow/synth_<variant>.ys)
yosys -s flow/synth_base.ys          # variants: base p1 p2 p3 p4
# gate-level activity VCD (flow/tb_core.v, +MODE=0|1, +VCD=...)
iverilog -g2012 -DFUNCTIONAL -DSIM -o sim.vvp sg13g2_stdcell.v net_base.v flow/tb_core.v
vvp sim.vvp +MODE=1 +VCD=gl_base_m1.vcd
# power (flow/sta_core.tcl)
sta -no_splash -exit flow/sta_core.tcl   # env: NETLIST, ACTIVITY_VCD, POWER_REPORT
```

P2 synthesis needs the ICG blackbox (`flow/bb_lgcp.v`); simulation uses the
PDK behavioral model of `sg13g2_lgcp_1` (branch `proposal-mac-accu/2-icg-clock-gating`,
`test/sg13g2_lgcp_model.v`).

## 9. Branch index

- `main` — released tapeout, untouched by this exploration.
- `proposal-mac-accu/1-unified-bank` — single-bank unified accumulator.
- `proposal-mac-accu/2-icg-clock-gating` — library-cell ICG clock gating.
- `proposal-mac-accu/3-event-scheduled` — event-scheduled maintenance domain.
- `proposal-mac-accu/4-adaptive-boundary` — workload-adaptive boundary.
- `proposal-mac-accu/summary` — this report, raw data (`data/`), flows (`flow/`).
