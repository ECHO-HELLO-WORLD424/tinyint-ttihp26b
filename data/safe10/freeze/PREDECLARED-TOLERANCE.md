# Predeclared acceptance tolerances (RTL freeze validation)

Recorded **before** the window-sweep results were available (2026-09-17, while the
primary sweep was still running), so the criteria cannot be chosen after seeing
the numbers.

## Gate 2 — startup repeatability and timestep convergence

For each primary configuration (canary × corner × external clock, `can_sel=3`,
`win_sel=0`):

| Quantity | Predeclared criterion |
| --- | --- |
| Count repeatability across the three startup phases | spread ≤ **1 %** of the mean count, or ≤ the derived edge-quantization bound (±1 edge), whichever is **larger** |
| Count agreement, 5 ps vs 2 ps | same bound as above |
| Rate agreement, 5 ps vs 2 ps (steady-state mean period) | ≤ **1 %** |
| Stopped readout | every counter bit settled within the protocol's two-external-clock readout interval (200 ns at 10 MHz, 40 ns at 50 MHz) after the gate closes |
| Acceptance of a case | `count_ok` (decoded count equals the offered ring-edge count within the derived ambiguity), `settled`, and no bit moving at the decode point |

The 1 % starting point follows `docs/rtl-freeze-checklist.md` ("a suggested
starting criterion is agreement within the larger of 1 % or the explicitly
derived edge-quantization bound"); it is not tightened for this candidate because
the canary is used as a *relative* delay proxy whose calibration is fitted per
operating point, and the predictor's own accuracy target is coarser than 1 %.

Edge-quantization bound: the analyzer derives it per case from the measured `en`
transition time and the ring period (at least ±1 edge, because the gate's
threshold crossing is interpolated).

## Gate 2 — frequency stability classification

A waveform is called **stable** ("single-valued frequency prediction") only when
the steady-state interval histogram yields exactly one cluster *and* the
coefficient of variation is ≤ 0.05. Zero detected clusters is *unclassified*
(insufficient evidence), never a pass. A multi-mode waveform is recorded as
`rate_stable=false` with its interval statistics; it is not by itself a failure
of the counter (the integrated count is still validated) but it does mean no
single-frequency prediction is defined for that configuration.

## Gate 3 — carry coverage

| Claim | Required evidence |
| --- | --- |
| Stages 0–14 toggle at their binary-carry rate | per-bit observed vs expected toggles within ±2 (derived from the independently counted ring edges), in the window runs |
| Stage 15 toggles | a targeted extended-gate run long enough to cross 2^15 = 32768 edges, labelled a carry test, not a window test |
| Full-width wrap `0xFFFF → 0x0000` | **not claimed** unless a run crosses 65536 edges; the RTL regression `test_ro_ripple_counter_wrap` covers the wrap at RTL level only |
| Ripple settling | measured last-counter-bit transition after the gate closes must fit the readout interval above |
| Control cases (`FORCE_CAN`, `FREEZE`/resume, reset mid-window) | the counter holds (mask/freeze) or restarts (reset) and the stopped count still matches the edges offered while enabled |

## Gate 4 — experiment STA

Unchanged from the checklist: 18 launch registers, unique, structurally resolved,
17 capture endpoints, every unrestricted capture path classified, no case where
the unrestricted path is worse than the runtime path, `control_slack_ns > 0`
everywhere, and predictions traceable to the regenerated raw reports.
