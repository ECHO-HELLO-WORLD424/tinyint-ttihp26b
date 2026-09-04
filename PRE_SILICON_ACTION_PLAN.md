# Pre-Silicon Readiness Status

Last reconciled with the repository: 2026-09-04

Hardware and analysis revision: `1e31757e50080b19fa7642b8b9cd6822f64b1d11`

Canonical hardening run: [`33839023290`](https://github.com/ECHO-HELLO-WORLD424/tinyint-ttihp26b/actions/runs/33839023290)

Prediction model: `tpv-predict-1.0.1`

## Executive conclusion

The pre-silicon design and prediction package is complete. The original two
research-blocking issues are resolved:

1. `result_reg` captures the DUT exactly once per 19-cycle operation, on
   `chk_start`, and holds the sample until comparison. A failed timing sample
   cannot be overwritten by the later settled result.
2. Experiment-specific STA case-analyzes static configuration and reports
   runtime-sensitizable paths from `u_pat.lfsr`/`u_pat.idx` to `result_reg`.
   The static-configuration path that dominates global signoff is retained in
   conservative signoff reports but is not called the experimental boundary.

The repository now contains the final physical artifacts, raw timing reports,
machine-readable prediction datasets, reproducible analysis tools, a frozen
prediction/calibration definition, and a frozen post-silicon protocol.

This does **not** mean that the research question has been answered. The final
comparison requires silicon measurements. Two limitations remain explicit:

- The reachable post-silicon voltage range depends on the Tiny Tapeout board
  power topology. At nominal PVT the longest-path prediction is above the
  50 MHz board ceiling; reaching a measurable knee may require reduced core
  voltage and elevated temperature.
- RO frequencies are predicted with a parasitic-aware, broken-loop static
  delay model. No extracted transient SPICE simulation has been performed.
  Dynamic slew, supply-bounce, and oscillator start-up effects are therefore
  part of the model error to be tested on silicon.

## Research contribution

The contribution is experimental quantification, not a new canary topology:

> An open-source silicon test vehicle and dataset comparing case-analyzed
> extracted STA, a generic ring oscillator, and a structure-matched ring
> oscillator for predicting workload-dependent arithmetic timing failures
> across reachable PVT, including prediction error, missed-failure rate,
> false-warning rate, guardband cost, and one-point calibration benefit.

Negative results remain meaningful: weak RO/DUT correlation, an unreachable
boundary, or no advantage for the matched canary must be reported rather than
reframed after observing silicon.

## Frozen hardware and verification baseline

| Item | Result | Interpretation |
| --- | --- | --- |
| RTL cocotb | 10/10 pass | Includes one-shot capture, all patterns/taps, DFT, freeze, reset, and readout |
| Functional gate-level | 8 pass, 2 intentional skips | Zero-delay synthesized control/readout check; not timing or RO-frequency evidence |
| Tiny Tapeout precheck | 10/10 pass | Packaging/source checks clean |
| GDS / precheck / GL / viewer jobs | All successful | Canonical run `33839023290` |
| DRC / Magic DRC | 0 / 0 | Clean |
| LVS | 0 errors | Clean |
| Antenna | 0 violations | Clean |
| Power grid | 0 violations | Clean |
| Hold slack | fast +0.135 ns; typ +0.226 ns; slow +0.389 ns | Positive at every reported corner |
| Global setup slack | fast +8.571 ns; typ +3.319 ns; slow -6.074 ns | Slow global worst path starts at static `cfg[8]`; left visible in signoff |
| Slow global TNS | -10.380 ns, five paths | Conservative signoff result, not the experiment boundary |
| Max fanout / slew / cap | One report-only fanout violation; 0 slew; 0 cap | `clkbuf_0_clk/X` fanout 16 versus generic limit 8; no timing impact identified |
| Final utilization | 82.86% | 2610 instances: 1747 standard cells + 863 fill |

The functional GL suite strips RO combinational loops and removes specify
blocks. SDF is not annotated there. Timed evidence comes from the separate SDF
and case-analyzed STA flows.

## Pre-silicon prediction evidence

### Runtime STA

`data/experiment_sta.csv` contains 96 cases:

- 3 library corners
- 8 segment-tap configurations
- 4 workload patterns

The analysis reports runtime paths from pattern-generator state to the
one-shot DUT capture under case-analyzed configuration. For seg3333/worst:

| Corner | Predicted failure period | Predicted boundary |
| --- | ---: | ---: |
| fast, 1.32 V, -40 °C | 11.17 ns | 89.53 MHz |
| typical, 1.20 V, 25 °C | 16.27 ns | 61.46 MHz |
| slow, 1.08 V, 125 °C | 25.42 ns | 39.34 MHz |

`hold` has no runtime-sensitizable path. `alt` bypasses the intended carry
delay and lies far above the 50 MHz board range.

### Timed SDF cross-check

`data/sdfsim.csv` contains a full-chip IOPATH-only boundary sweep for
seg3333/worst plus a zero-delay reference:

| Corner | Last failing period | First passing period | STA failure period |
| --- | ---: | ---: | ---: |
| typical | 14 ns | 16 ns | 16.27 ns |
| slow | 22 ns | 24 ns | 25.42 ns |

Icarus crashes when full interconnect annotation is enabled, so the committed
SDF suite omits wire interconnect and is optimistic. The RO SDF cross-check is
invalid because P&R-disabled RO arcs are written as hard zero delays; its
counts are blanked and excluded. See `docs/ro-sdf-crosscheck-diagnosis.md`.

### RO delay model

`data/ro_predict.csv` contains 24 rows:

- 3 corners
- 4 `can_sel` values
- 2 canaries

Each loop is broken in two complementary OpenSTA analyses. The line segment
and gate-return segment are summed exactly once, using the routed netlist,
corner Liberty, and nominal SPEF parasitics. The estimate is then converted to
oscillation frequency and expected counter increments.

This is a first-order static oscillator model, not transient simulation. At
the predeclared readout (`can_sel=3`, win0 = 256 clock cycles), both predicted
counts fit in 16 bits at all corners. The hardware canary counters wrap modulo
65536; they do not saturate and expose no saturation flag.

### Joined prediction model

`tools/predict_model.py` joins the pinned inputs into 288 long-format rows in
`data/predict/predictions.csv`:

- `P_STA`: per-corner runtime STA knee.
- `P_GEN`: nominal STA ladder scaled by generic-RO count ratio.
- `P_MAT`: nominal STA ladder scaled by matched-RO count ratio.

The model fits no free parameters to pre-silicon corner results. A single
multiplicative calibration factor is substituted after measuring the primary
nominal anchor or its predeclared slow-corner fallback. If neither anchor is
reachable, calibration is censored and only uncalibrated results are reported.

The frozen equations, thresholds, guardband rule, and evaluation metrics are
in `docs/prediction-model.md`. Dataset fields and units are in
`docs/data-dictionary.md`.

## Artifact provenance

| Item | Value |
| --- | --- |
| Hardware commit | `1e31757e50080b19fa7642b8b9cd6822f64b1d11` |
| GDS workflow | `33839023290` |
| LibreLane image | `ghcr.io/librelane/librelane:3.0.5` |
| PDK | IHP SG13G2, ciel revision `c4b8b4e5e7a05f375cca3815d51b3a37721fbf5c` |
| Final GDS SHA-256 | `74b47cc721163b918da79a57efab4792155b3bffe9e3c85c9e726fbf9f9982f9` |
| Final netlist SHA-256 | `771567b69ed1a68f092aeb3adb4d472b80102a7ec450460f2d88673464d7f28b` |
| Nominal SPEF SHA-256 | `b472b58af73cef716c90716b9a3fd4f1ceed0546d8162cb985752387bcd68263` |

The complete staged subset and 90-file hash manifest are under
`artifacts/run-33839023290/`. Later documentation, analysis, and comment-only
changes do not alter synthesized RTL behavior, constraints, the source list,
or floorplan inputs.

## Definition of pre-silicon complete

- [x] DUT result is captured once per operation and held until comparison.
- [x] RTL and zero-delay functional GL regressions pass after the capture fix.
- [x] Fresh hardening passes Tiny Tapeout physical checks.
- [x] Experiment STA case-analyzes static configuration and reports runtime
      startpoints/endpoints.
- [x] Selected slow-corner configurations place a predicted knee within the
      nominal 1–50 MHz board range.
- [x] A timed full-chip SDF sweep brackets the selected runtime boundary, with
      the IOPATH-only limitation recorded.
- [x] Both RO loops have a parasitic-aware pre-silicon count prediction, with
      the static-model limitation recorded.
- [x] Prediction scripts, raw/intermediate tables, plots, model version, units,
      and provenance are committed.
- [x] Calibration, thresholds, guardband metrics, and censoring behavior are
      frozen before silicon data.
- [x] The post-silicon matrix, repetition policy, instruments, uncertainty,
      immutable raw-data schema, and exclusions policy are frozen.
- [x] Final physical artifacts and hashes are archived outside temporary CI
      storage.

## Remaining work

The remaining work is post-silicon preparation and report production, not a
missing pre-silicon prediction artifact:

1. Verify the demo-board core-voltage topology and safe adjustment range.
2. Decide whether an extracted transient RO simulation is feasible and worth
   adding; if not, retain the broken-loop estimate as an explicitly imperfect
   predictor.
3. Implement the host controller and post-silicon boundary-analysis pipeline
   from `docs/post-silicon-protocol.md` before measurements begin.
4. Add report-quality architecture, timing, path, layout, and experiment
   figures plus a cited related-work section.
5. After any RTL, constraint, floorplan, source-list, or physical-tool change,
   re-run hardening, STA, RO, SDF, prediction generation, and the build
   manifest. Do not combine artifacts from different hardware revisions.
