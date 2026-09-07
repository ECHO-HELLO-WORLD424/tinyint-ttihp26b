> The 10 MHz normal-operation candidate uses the same half-cycle protocol.
> Its regenerated build-specific data are in `data/safe10/`; `data/halfcycle/`
> retains the earlier build. The 10–50 MHz sweep is intentional experimental
> overclocking above the submitted timing-safe frequency, not a guarantee of
> error-free operation. See [verification attempts](ci-timing-closure-attempts.md).

# Predeclared prediction model v2

Model: **tpv-predict-2.0.0**, merged into `proposal-canary` on 2026-09-08
(developed on `proposal-canary-dev`).
Frozen before post-silicon data. This replaces the full-cycle v1 analysis for the
new half-cycle RTL; the original `data/predict/` and archived CI build remain
historical v1 results. V2 inputs/outputs are under `data/halfcycle/`.

## Timing aperture and STA predictor

Operands launch on a rising clock edge. `capture_pending` accepts that launch and
causes exactly one capture on the immediately following falling edge. The captured
result holds until the next 19-cycle frame boundary. The combinational oracle
settles on stable operands before that comparison.

For period T, high-time fraction d, and extracted setup slack S at that waveform:

- Available aperture H = d × T.
- Required aperture H_required = d × T − S.
- Predicted boundary period T_boundary = H_required / d = T − S/d.
- Predicted boundary frequency F = 1000 / T_boundary (MHz for ns inputs).

The committed nominal predictions use d = 0.5 and T = 20 ns. They include the
extracted launch/capture clock paths, clock inversion, setup and the existing
250 ps setup uncertainty. The original full-cycle formula T − S is **wrong for
this RTL**. `tools/verify_halfcycle.py` checks the formula against raw STA at
20/40 ns and duty fractions 0.4/0.5/0.6, and tests equal high times in SDF.

Use measured clock HIGH time and its uncertainty in silicon comparisons. To
compare frequencies across duty ratios, normalize to a 50% duty-equivalent
frequency F_equiv = 500 / H_measured (MHz). Clock-path duty distortion remains
part of the uncertainty; a board-pin measurement is not an internal die probe.
Do not silently calibrate away an unmeasured duty-cycle error.

STA case-analyzes static configuration and reports runtime pattern-state paths
to all 17 capture flops. The global signoff path is not substituted for these
paths. `control_slack_ns` reports the worst other register endpoint for each
case; it must remain positive throughout the claimed operating envelope.
`hold` has no runtime path; its prediction remains empty rather than zero.

## Canary predictors

The generic and matched predictors independently scale the nominal STA ladder:

P_x(c, seg, pattern) = P_STA(nominal, seg, pattern) × R_x(c).

Pre-silicon R_x(c) is the ratio of the corner's modeled RO count to the nominal
modeled count at the **same** reference clock, selection and window. The model
uses selection 3, window 0, and a 50 MHz reference clock (256 nominal cycles).
At a different measurement clock, normalize unwrapped counts to the reference
clock: N_ref = N_measured × f_measured / 50 MHz. Raw unnormalized counts at two
different clock frequencies are not a delay ratio.

Both counters are 16-bit ripple counters and wrap modulo 65536. `sat_win*` in
the RO dataset means a modeled overflow risk; there is no hardware saturation
or overflow flag for the canaries. Reject wrapped/ambiguous telemetry with a
recorded exclusion. Do not shorten counters or drop negative correlation results.

The window counter runs during enabled boot clocks, while the RO gate opens
only at boot completion. Depending on configuration's FREEZE bit during boot,
the actual initial RO interval can be shorter than the nominal window by up to
three clocks. Retain identical configuration/boot handling at calibration and
measurement; report this small window-model uncertainty. This is inherited
behavior, not resolved by the half-cycle change.

RO frequencies remain **broken-loop extracted STA estimates**, not transient
SPICE-validated oscillation measurements. The signoff SDF has disabled RO arcs;
a free-running SDF RO simulation would be invalid. The SDF sweep masks the ROs.

## Calibration and scoring

The single anchor is nominal core voltage (1.20 V), ambient near 25 °C,
seg3333/worst, selection 3/window 0, characterized 50% duty. Capture the anchor
before examining other post-silicon boundary outcomes. For each predictor:

k_x = F_measured_equiv(anchor) / P_x(anchor), and P_x_cal = k_x × P_x.

Pre-silicon k_x = 1.0 is explicitly a placeholder, not a fitted result. Apply
the same k_x to all remaining points. If the anchor is censored above 50 MHz,
report calibration unavailable. **Do not move to a heated/undervolted anchor
chosen after looking at other outcomes.** A new anchor needs a separately
versioned prospective protocol before additional outcome inspection.

Score first observed error and error probabilities 1e-6, 1e-4 and 1e-2 per
completed comparison. Preserve pass/fail brackets; do not turn censored points
into measured boundary values. Report signed/absolute/relative boundary error,
rank correlation, workload dependence, missed-failure probability, false-warning
rate and guardband cost. Compare uncalibrated and calibrated predictions on the
same held-out points. Predeclare guardband fractions 0, 5%, 10%, 20%; warn when
operating frequency exceeds (1 − guardband) × predicted boundary. Use the same
rules for both canaries and STA, and do not tune guardbands to silicon outcomes.

## Scope and limitations

The three library corners jointly vary process, voltage and temperature. They
are not three temperatures of a single die. An 85 °C observation must not be
joined to the 125 °C slow corner as an exact-PVT prediction. Quantitative V/T
validation beyond these corners requires fixed-process characterization at the
measured conditions; otherwise report model mismatch explicitly.

The full-chip timed simulation uses per-cell IOPATH SDF, with wire interconnect
and flip-flop timing checks omitted. Its boundary can differ from extracted
STA in either direction. It confirms workload sensitization and falling-edge
capture, not metastability, absolute failure probabilities or RO oscillation.
One die supports within-die workload/PVT conclusions, not a process distribution.
