# Research Proposal — Timing-Prediction Test Vehicle on IHP SG13G2 (ttihp26b)

Status: RTL implemented in this repository (`src/`), validated with the cocotb suite in
`test/`. This document is the concise proposal backing the design decisions.

## Research question

> How accurately can pre-silicon timing analysis and low-cost on-chip delay proxies
> predict the workload-dependent first-failure boundary of a synthesized arithmetic
> circuit across voltage, temperature, and frequency in the IHP SG13G2 open PDK?

Secondary questions: how much guardband does each proxy need to avoid missed
failures, and how much does one-point post-silicon calibration improve prediction?

## Originality and positioning

The contribution is *experimental quantification*, not a new canary circuit (prior art:
Razor/iRazor, tunable replica circuits; the nearby Tiny Tapeout space already has
ring-oscillator arrays and metastability detectors). Deliverables:

- Prediction error of extracted STA vs. two on-chip delay proxies vs. real silicon errors.
- Missed-failure rate, false-warning guardband, operand-class dependence.
- Value of one-point (nominal V/T) calibration.
- An open-source test vehicle + pre/post-silicon dataset validating SG13G2 timing models
  (the PDK standard-cell views are recent; characterization is timely).

Both positive and negative results are publishable (technical report / workshop paper).

## Implemented architecture (1x1 Tiny Tapeout tile)

1. **DUT**: structurally preserved 16-bit ripple-carry adder (`tpv_rca16`), four 4-bit
   segments. The carry between segments and the final carry-out pass through
   configurable inverter-pair delay banks (taps at 0/16/32/48 pairs, `tpv_delay_line`),
   giving a family of selectable critical-path lengths. `dont_touch` attributes protect
   the deliberate structure from synthesis restructuring.
2. **Independent oracle**: bit-serial reference adder (`tpv_checker`) computing the
   expected 17-bit result over 17 cycles with a very short per-cycle path, making the
   chip self-checking (no result readout bandwidth needed).
3. **Two canary families**, both ring-oscillator based (area-feasible in 1x1; a
   capture-based replica canary would need ~1-clock-period delay chains, ~2x the area):
   - *Generic RO canary* (`tpv_ro_gen`): tunable inverter line, activity-blind.
   - *Structure-matched RO canary* (`tpv_ro_match`): loop passes through the same
     delay-bank + full-adder composition as a DUT segment, margin tuned by config.
   Each drives a 16-bit edge counter over a configurable measurement window
   (2^8..2^14 clk cycles), giving continuous delay telemetry, not just a binary flag.
4. **Measurement block**: frame-based operation (1 timed op per 18 cycles, operands
   registered per frame), 16-bit DUT error counter, 16-bit op counter, first-error
   operand/result capture, serial byte readout with auto-incrementing pointer,
   global freeze input for quiescent readout, and FORCE_ERR/FORCE_CAN DFT bits so the
   error-accounting path itself is verifiable pre-silicon.

## Experiment plan

Per voltage/temperature point: select path configuration + pattern class, sweep clock
frequency up then down, run a known op count, freeze, read counters. Record error rate
vs. frequency (`err_cnt/ops`), RO counts, first-error signatures. Define failure by
error-rate thresholds (first error, 1e-6, 1e-4, 1e-2 per op), not a single point.
Pattern classes: PRBS, worst-case carry, carry-free alternating, static hold — the
operand-dependence of the first-failure boundary is a primary measurement.

Pre-silicon hierarchy: RTL sim -> post-synth STA -> post-route extracted STA across
corners -> SDF gate-level sim with sensitizing vectors -> SPICE on selected paths ->
fitted canary-vs-DUT calibration model.

## Key risks and countermeasures

| Risk | Countermeasure |
| --- | --- |
| Timing knee outside the measurable clock range | Four independently selectable delay banks; complete extracted STA before tapeout freeze |
| Synthesis rewrites the deliberate path | `dont_touch` cells/banks, structural RTL, inspect netlist and layout |
| Critical path not sensitized by vectors | Worst-case carry patterns + gate-level sensitization check |
| Canary/DUT activity mismatch | Compare activity-blind generic RO against structure-matched RO (explicit study point) |
| Checker fails before DUT | Bit-serial oracle with very short path; sweep stays inside its validity band |
| RO counter metastability | Ripple counters frozen (RO NAND-gated) before any clk-domain readout |
| TT board limits (core voltage control, 50 MHz clock noise, uio contention) | Verify power topology with TinyTapeout early; external clock source; fixed pin directions per phase (config-in / status-out) |
| Single die | Frame as within-die PVT/workload study; multiple samples if available |
| 1x1 area overflow | RO canaries chosen for area; fallback: shrink delay banks (fewer pairs) |
| Deadline | DUT + checker + 2 RO canaries + counters are the minimum viable payload (already implemented) |

## Deliverables

Open-source RTL + cocotb suite (this repo), hardening reports (timing/area), pre-silicon
prediction data, post-silicon PVT dataset and error-rate contours, technical report with
quantified proxy-prediction accuracy and one-point calibration benefit.

## Contribution statement

> An open-source silicon test vehicle and dataset comparing extracted STA, a generic
> delay RO, and a structure-matched replica RO for predicting operand-dependent timing
> failures in an arithmetic carry path across PVT in IHP SG13G2, quantifying prediction
> error, missed-failure probability, guardband cost, and one-point calibration benefit.

## Pre-silicon status (this repository)

The RTL is implemented and verified, and the 1x1 tile has been hardened with the
IHP SG13G2 LibreLane flow (matching the Tiny Tapeout GDS CI):

- Cocotb RTL suite: 9/9 tests pass (config/echo, functional zero-error across all
  pattern classes and delay configurations, forced-error accounting with exact
  counter values and first-error capture, canary window counts, freeze semantics,
  mid-run reconfiguration, frame pacing).
- Gate-level suite: 8/9 pass, 1 skipped by design (the RO loops are stripped from
  zero-delay GL simulation; their counters are asserted at zero instead). The GL
  run caught two real pre-tapeout bugs: a synthesis-unsafe config-shadow register
  (async data load mis-mapped by Yosys, which would have left the chip
  unconfigurable) and a config commit race when rst_n release coincides with a
  clock edge.
- Hardening results: 2482 instances, ~82% placement utilization, zero routing DRC
  errors, zero antenna violations, LVS clean. Hold slack positive at all corners
  (+0.13/+0.22/+0.39 ns fast/typ/slow). Setup slack +8.8/+3.7 ns fast/typ; the
  -5.5 ns setup violation at the slow corner is the deliberately slow DUT carry
  path (the measured experiment boundary, by design). The fast-corner hold check
  is scoped to typ/slow corners in `src/pnr.sdc` (the flow's zero-tolerance
  checker includes 250 ps of clock-uncertainty padding); raw hold slack at the
  fast corner is positive and the corner is unreachable on the demo board.
- Canary loops are preserved through synthesis by pre-mapping them to library
  cells (plain dont_touch/keep attributes were insufficient: ABC merged inverter
  pairs into buffers and cut the loops).
