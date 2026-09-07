> **10 MHz submission candidate:** normal operation is specified at 10 MHz,
> 50% duty (100 ns period). The 10–50 MHz research sweep deliberately exceeds
> that timing-safe specification. Verification is tracked in
> [the attempt log](ci-timing-closure-attempts.md). Earlier physical results below
> remain evidence for the earlier build until replaced by fresh results.

# Research Proposal — Timing-Prediction Test Vehicle on IHP SG13G2 (ttihp26b)

Revision 2, development branch `proposal-canary-dev`. This proposal describes the
implemented half-cycle candidate and the prospective silicon experiment. The
original full-cycle proposal remains in Git history on `proposal-canary`; its
root-level datasets and CI run `33839023290` are historical v1 evidence.

## Research question and contribution

> How accurately can extracted pre-silicon timing analysis and two low-cost
> on-chip delay proxies predict the workload-dependent first-failure boundary of
> an arithmetic carry path across voltage, temperature, frequency and configured
> path length?

The contribution is experimental quantification: compare extracted STA, a generic
ring oscillator and a structure-matched ring oscillator against observed silicon
errors. Measure boundary prediction error, missed failures, false warnings,
guardband cost, workload dependence and the benefit of one-point calibration.
The study does not claim a novel canary architecture. One die supports within-die
PVT/workload validation; process-distribution claims require multiple samples.
Negative correlations and boundaries outside the measurement range remain results.

## Implemented architecture

The design occupies one 1x1 Tiny Tapeout tile, with the standard interface and a
normal submitted clock of 10 MHz and experimental ceiling of 50 MHz.

1. **Arithmetic DUT:** a structurally preserved 16-bit ripple-carry adder divided
   into four 4-bit segments. Each carry boundary, including final carry-out, has
   selectable delay taps at 0/16/32/48 inverter pairs. Mapped library cells and
   structural inspection preserve the physical experiment through synthesis.
2. **Half-cycle sample:** operands launch at a frame-boundary rising edge. A
   registered pending pulse captures the 17-bit DUT result exactly once on the
   immediately following falling edge. The sample holds until comparison, so a
   later settled result cannot overwrite a timing failure.
3. **Independent oracle:** a combinational reference adder computes the expected
   result from stable operands. Comparison occurs at the next frame boundary,
   after 19 cycles. Extracted case-analyzed control timing is checked separately
   from the deliberately slow DUT.
4. **Two delay proxies:** generic inverter-line and structure-matched ring
   oscillators each drive a 16-bit ripple edge counter. Windows are selectable
   from 256 to 16,384 clock cycles. RO counters wrap modulo 65,536; they have no
   saturation or overflow flag.
5. **Measurement/readout:** saturating 16-bit error and launch counters, the low
   byte of the first failed DUT result, configuration/status bytes, FREEZE and
   FORCE_ERR/FORCE_CAN test features. The chip does not store first-error operands
   or a full first-error result.

One operation launches every **19 clock cycles**. Configuration commits on the
third rising edge after reset release; pins must remain stable through that edge.
FREEZE blocks new launches while allowing an accepted falling-edge sample to
finish. Read after two complete settling clocks. The complete pin and byte
protocol is in [the datasheet](info.md).

## Why half-cycle capture

The original full-cycle design predicted a nominal boundary of 61.46 MHz,
above the planned 50 MHz sweep ceiling. Its slower library corner combined slow
process, 1.08 V and 125 °C; heating a typical die would not reproduce that corner.

The revised aperture is clock HIGH time, H = duty × period: 10 ns at
50 MHz and 50% duty. The longest-path worst-carry configuration now predicts a
nominal boundary near 31 MHz. This makes nominal-voltage ambient observation
plausible without requiring a 125 °C test. Silicon observability is still a
prediction until measured; the library temperature is not an assembly rating.

For extracted setup slack S at period T and duty d, the boundary period is
T_boundary = T − S/d. Record actual HIGH time and duty, and report the
50%-duty-equivalent frequency as 500/H MHz for H in ns.

## Experiment and prediction plan

Start at nominal 1.20 V and ambient near 25 °C. Characterize the delivered clock,
board power topology and measurement uncertainty before extending voltage or
optional temperature sweeps. The normal measurement range is 10–50 MHz; 1 MHz
bring-up uses FORCE_CAN to avoid overflowing a long clock-based RO window.

For each permitted operating point, sweep frequency up and down across path
configurations and PRBS/worst-carry patterns, with alternating and static-hold
controls. Refine observed transitions and repeat measurements. Report first-error
and 1e-6/1e-4/1e-2 error-rate thresholds as pass/fail brackets, including censored
all-pass/all-fail outcomes. Error rates use completed comparisons:
max(launch_count − 1, 0), before saturation. Split long runs into batches of at
most 60,000 comparisons; reset repeats deterministic workloads and does not
create independent random samples.

The prospective [prediction model](prediction-model.md), version
`tpv-predict-2.0.0`, compares case-analyzed extracted STA with two separate
nominal-STA-ladder × normalized-RO-count predictors. Normalize measured counts
for the actual measurement clock before comparing them with the 50 MHz reference
window. Preserve suspected wrap and other exclusions in raw records.

Use one predeclared calibration anchor: nominal voltage/ambient,
seg3333/worst, canary selection 3/window 0, characterized 50% duty. Derive each
predictor's scale from that anchor and apply it unchanged to held-out points.
If the anchor is censored above 50 MHz, report calibration unavailable; do not
select a heated anchor after inspecting outcomes. Evaluate guardbands of
0%, 5%, 10% and 20% without fitting them to silicon results.

The [post-silicon protocol](post-silicon-protocol.md) specifies sweep steps,
sample counts, uncertainty, exclusions and immutable raw records. The
[data dictionary](data-dictionary.md) defines fields and units.

## Current pre-silicon evidence

These are **local development results**, from physical input revision
`041c1906a276211a62263dc30ce0da13b01c00ed`, run `dev-halfcycle-final`.
Documentation changes do not change those physical inputs. The build used
LibreLane 3.0.5 and IHP PDK revision
`c4b8b4e5e7a05f375cca3815d51b3a37721fbf5c`; exact tool identities, source hashes
and artifact hashes are in the [local manifest](../data/halfcycle/verification/local-build-manifest.json).

| Check | Local result |
| --- | --- |
| RTL regression | 13 pass |
| Functional gate-level regression | 9 pass, 4 intentional RTL-only skips |
| Tiny Tapeout precheck | 10 pass |
| Routing DRC / Magic DRC / LVS / antenna | 0 violations/errors |
| Max slew / max capacitance | 0 violations |
| Hold slack, fast / typical / slow | +0.1315 / +0.2189 / +0.3769 ns |
| Worst case-analyzed control setup slack at 50 MHz | +6.26 ns |
| Active standard-cell area | 20,990.8 µm²; 12.47% below original |
| Actual utilization | 72.53%; configured placement density 72% |
| Structural inspection | 384 DUT bank inverters and taps, both RO loops, 17 falling-edge captures preserved |

The approximately 70% utilization is accepted for this development candidate,
subject to the shuttle's acceptance checks. It remains above the earlier 60%
objective and is not evidence of portal approval.

Longest-path worst-carry timing evidence at 50% duty:

| Joint library corner | Extracted STA boundary | IOPATH SDF last failing / first passing period |
| --- | ---: | ---: |
| Fast, 1.32 V, −40 °C | 45.126 MHz | 20 / 22 ns |
| Typical, 1.20 V, 25 °C | 30.998 MHz | 32 / 34 ns |
| Slow, 1.08 V, 125 °C | 19.904 MHz | 46 / 48 ns |

At nominal conditions, timed simulation therefore places the transition between
29.412 and 31.25 MHz. Equal-HIGH-time tests across 40/50/60% duty confirm the
aperture behavior. These are simulated boundaries, not silicon measurements.

The v2 package in [data/halfcycle](../data/halfcycle/) contains 96 STA cases,
24 RO-model rows, a 23-point main SDF sweep and 288 derived prediction rows.
See [development validation](halfcycle-development-validation.md) for raw evidence,
reproduction commands and test scope.

## Remaining limitations and acceptance gates

**The local hardening flow exits with a setup failure.** Conservative 20 ns,
50%-duty signoff reports global fast/typical/slow setup slack of
−1.1844 / −6.2859 / −15.3976 ns. A DUT intended to fail near 31 MHz does not meet
an error-free 50 MHz requirement at maximum delay. Experiment-specific case
analysis remains separate from signoff; no false-path or multicycle exception
has been added to hide the slow path. A submission-compatible treatment must be
resolved before claiming readiness. A fresh GitHub run must be assessed on its
actual results, separately from these local checks.

Functional GL uses zero delay and stripped RO loops. It verifies digital control
and readout, not failure frequency. The separate SDF flow retains cell IOPATH
arcs but omits interconnect and flip-flop timing checks; it supports sensitization
and capture behavior, not metastability or absolute error probabilities.

RO predictions currently use extracted broken-loop STA estimates. Extracted
transient oscillation validation remains open; disabled signoff RO arcs do not
predict oscillation frequency. Boot may shorten the initial window by up to
three clocks, which remains a documented modeling uncertainty.

Joint library corners do not form a temperature sweep of one die. Quantitative
comparisons at other measured V/T points require matching characterization or
an explicit mismatch label. Clock duty distortion, checker validity, RO settling
and counter wrap must remain part of the measurement uncertainty and exclusions.

## Deliverables

An open RTL/test vehicle, reproducible final-build artifacts and manifests,
pre-silicon predictions, append-only silicon measurements, and a technical
report comparing uncalibrated and calibrated predictors. The final submission
build must be archived and its prediction package regenerated if physical inputs
or resulting implementation change. CI success and portal acceptance are separate
milestones; neither substitutes for the remaining research validation.
