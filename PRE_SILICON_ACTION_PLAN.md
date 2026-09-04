# Pre-Silicon Readiness Audit and Action Plan

Audit date: 2026-09-03  
Branch: `proposal-canary`  
Audited commit: `206715252bb569430b0d8569393f12997b2a552b`

## Executive conclusion

The project is **physically tapeout-capable, but the repository does not yet contain
everything needed for a defensible pre-silicon research result**.

The RTL test suite and the current Tiny Tapeout hardening run are healthy: RTL tests
pass, gate-level functional tests pass, and signoff is clean for DRC, LVS, antenna,
power-grid, and hold checks. However, two issues currently block the intended timing
experiment:

1. The DUT result register is captured on every enabled clock. A timing-failed first
   capture can therefore be overwritten by the correct settled result before the
   checker compares it.
2. The reported slow-corner critical paths start at the static configuration register,
   not at a runtime-changing operand or pattern-generator register. The current worst
   slack is therefore not yet evidence of a sensitizable operating-frequency boundary.

The research topic remains feasible and can make an original contribution without a
novel canary architecture. The strongest contribution is an open, measured comparison
of extracted timing, two low-cost delay proxies, and actual workload-dependent silicon
failures across voltage, temperature, frequency, and path configurations—especially
the quantified value of guardband and one-point calibration.

## Priority 0 — fix before relying on any experiment result

### P0.1 Make the DUT result a one-shot timing capture

Current behavior is at
[`src/tt_um_echoworld424_tpv.v`](src/tt_um_echoworld424_tpv.v), lines 145–148:
`result_reg` updates whenever `update_en` is high. Operands change at a frame boundary,
the timing-critical result is first sampled on the following edge, but subsequent edges
sample the same now-settled combinational output. The comparison at the next boundary
will normally see the repaired value rather than the failed first capture.

Action:

- Gate `result_reg` with a single-cycle capture strobe, most likely `chk_start`, which
  occurs at `frame_cnt == 0` after the new operands have loaded.
- Hold `result_reg` unchanged until the checker comparison at the frame boundary.
- Preserve `FORCE_ERR` behavior on that one capture.
- Review the first frame after reset and reconfiguration to ensure no stale sample is
  counted.

Acceptance tests:

- Add an assertion/test that `result_reg` can change only on the capture edge.
- Confirm that it remains stable from capture through comparison.
- Confirm exact operation/error counts for normal, `FORCE_ERR`, freeze, reset, and
  mid-run reconfiguration cases.
- Run both RTL and functional gate-level suites after re-hardening.

### P0.2 Analyze runtime-sensitizable paths, not static configuration paths

The current slow-corner worst path is from `cfg[8]` through pattern-selection logic and
the adder/delay structure to `result_reg[16]`. All five reported slow-corner setup
violations start at `cfg[8]` and end at result bits 12–16. Since configuration is static
during measurement, these paths do not describe the runtime capture boundary.

Action:

- Keep the conservative signoff constraints; do not hide paths in the tapeout signoff
  merely to improve the headline slack.
- Add a separate, experiment-specific post-route STA flow.
- Apply case analysis for each relevant static configuration: pattern selection, four
  segment-delay selections, and other mode bits.
- Report paths from registers that actually change at runtime—pattern-generator/LFSR
  or operand registers—to the one-shot `result_reg` capture registers.
- For each configuration, record path delay/slack at fast, typical, and slow corners.
- Verify with sensitizing vectors that the selected path is functionally exercisable.

Acceptance artifact:

- A machine-readable table with at least:
  `corner, pattern, seg0..seg3, startpoint, endpoint, delay_ns, slack_ns,
  predicted_fmax_mhz, sensitizing_vector`.

## Priority 1 — build the actual pre-silicon prediction package

### P1.1 Create a reproducible prediction dataset

The repository currently describes the intended analysis, but it does not contain the
model inputs, scripts, or prediction outputs needed to compare against silicon later.

Add:

- A script that extracts experiment-specific STA results into CSV/JSON.
- SDF gate-level timing tests using sensitizing operand sequences.
- Selected-path extracted SPICE simulations where practical.
- Pre-silicon RO frequency/count predictions for both canary families.
- A model that maps STA and canary observations to a predicted DUT first-failure
  frequency, including an explicitly defined guardband.
- Versioned plots/tables for the configurations that will actually be measured.
- A data dictionary and units for every configuration field and observed quantity.

Recommended minimum prediction outputs:

- Predicted first-failure frequency by PVT corner, path configuration, and pattern.
- Predicted generic-RO and matched-RO count at the same points.
- Proxy-to-DUT fit, residuals, false-warning rate, and missed-failure rate.
- A predeclared one-point calibration method that can be applied unchanged after
  nominal-voltage/temperature silicon data arrives.

### P1.2 Validate what the current gate-level test does and does not prove

The existing zero-delay gate-level test validates synthesized control, configuration,
readout, and counter behavior. It does **not** validate the timing-failure experiment:

- `test/strip_ro_cells.py` removes the RO combinational cells to avoid zero-delay loops.
- Specify blocks are removed and SDF is not annotated.
- RO counters are therefore expected to remain zero.

Action:

- Retain this suite as the fast structural/functional regression.
- Add a separate SDF-annotated timing suite; do not reinterpret the present suite as
  evidence of post-layout failure frequency or RO behavior.
- If full-chip SDF simulation is impractical, document that limitation and run a
  reduced extracted path testbench plus selected-path SPICE.

### P1.3 Predict canary behavior independently of digital STA

The RO timing arcs are intentionally disabled in
[`src/pnr.sdc`](src/pnr.sdc), lines 105–109, because free-running loops are not valid
synchronous STA objects. That P&R constraint is reasonable, but it means the hardening
report contains no RO-frequency prediction.

Action:

- Extract both RO loops from the final layout/netlist with parasitics.
- Simulate oscillation period/count across representative process, voltage, and
  temperature points.
- Document start-up behavior and the counter measurement window.
- Check that predicted counts neither overflow nor quantize so coarsely that the two
  canaries cannot be distinguished.
- Treat absolute RO accuracy and correlation with the DUT as measured research
  questions, not assumed properties.

## Priority 2 — improve documentation and reproducibility

### P2.1 Correct documentation inconsistencies

- `FRAME_LAST = 18` produces a **19-cycle** frame (`0` through `18`), while parts of
  `docs/research-proposal.md` say 18 cycles.
- Replace the stale “2482 instances, ~82% utilization” statement with metrics from the
  final chosen hardening run, clearly distinguishing target utilization, placed-cell
  count, filler count, and final design utilization.
- Replace the claim that the slow-corner violation is the measured experimental path
  until case-analyzed, runtime-sensitizable STA supports that statement.
- State explicitly that the present gate-level suite is zero-delay functional testing.

### P2.2 Pin and record the final build

The devcontainer pins LibreLane but still follows mutable support-tool/base-image inputs.
The generated physical files are deliberately ignored locally and live in CI artifacts.

Action:

- Record the exact tool, container, PDK, and support-tool revisions used for the final
  submission.
- Add an artifact manifest with the Git commit, workflow/run URL, file names, hashes,
  signoff summary, and configuration.
- Archive the final Tiny Tapeout submission artifact somewhere durable; CI retention
  should not be the only copy.
- Document one command sequence for reproducing RTL tests, gate-level tests, hardening,
  and experiment-specific extraction.

Current audited artifact hashes:

| Artifact | SHA-256 |
| --- | --- |
| Final GDS | `f88fdbdfd87a7c84e986d9a881497e96c501340f886570f8b990929f28f2c697` |
| Final netlist | `954f05c17eb002f89010b4fd93ac87d0060c322c1723bf86ea0ebd1648019bda` |
| Nominal SPEF | `1a55d6c832f32cd863681c6e791e703333560486ccf91d9619f652fac791298f` |

### P2.3 Resolve or document remaining implementation warnings

- Two max-fanout violations were reported: clock-buffer output fanout 16 versus limit 8,
  and one register output fanout 10 versus limit 8. Determine whether these are real
  constraints, report-only limits, or require buffering.
- One disconnected noncritical pin appears to be the unused `ena` input; document or
  consume it intentionally.
- Fix the two RTL width warnings by comparing 10-bit counters with 10-bit constants.
  The other linter messages are PDK black-box timescale warnings.

## Current verified baseline

| Item | Audited result | Interpretation |
| --- | --- | --- |
| RTL cocotb | 9/9 pass locally | Functional regression healthy, but does not expose recapture bug |
| Gate-level functional | 8 pass, 1 intentionally skipped | Synthesized digital control/readout healthy; no SDF/RO timing evidence |
| Precheck | 10/10 pass | Tiny Tapeout packaging checks healthy |
| DRC / Magic DRC | 0 / 0 | Clean |
| LVS | 0 errors | Clean |
| Antenna | 0 violations | Clean |
| Power grid | 0 violations | Clean |
| Post-route hold slack | fast +0.134 ns; typ +0.223 ns; slow +0.384 ns | Positive at all reported corners |
| Post-route setup slack | fast +8.720 ns; typ +3.556 ns; slow -5.645 ns | Slow violation exists, but current startpoint is static config |
| Slow-corner TNS | -8.040 ns, five paths | Requires runtime case-analysis before research interpretation |
| Final design utilization | 79.544% | Fits 1x1 tile |
| Standard cells | 1688 plus 953 fill cells | Use these definitions when reporting area |

Current GDS workflow:
<https://github.com/ECHO-HELLO-WORLD424/tinyint-ttihp26b/actions/runs/33827632705>

## Research risks and concrete countermeasures

| Risk | Countermeasure before tapeout | Evidence required |
| --- | --- | --- |
| DUT never fails below the 50 MHz board limit | Use case-analyzed extracted STA to choose delay taps with predicted knees spanning the available clock range | Per-configuration predicted Fmax table |
| DUT appears to pass because failed samples are overwritten | Implement one-shot capture and test that it holds through comparison | RTL assertion plus timed test |
| Reported critical path cannot be exercised | Generate and simulate sensitizing sequences for every selected measurement configuration | SDF/SPICE waveform and vector record |
| Oracle or control logic fails before the DUT | Run STA for checker/control separately and establish a safe operating envelope | Worst-slack comparison by block |
| RO proxy is poorly correlated with the DUT | Treat generic-versus-matched correlation as the experimental comparison; predeclare guardband and error metrics | Prediction model and residual analysis plan |
| RO model is unavailable from STA | Run extracted transient simulation of each loop | Frequency/count table across PVT |
| Voltage cannot be swept safely on the packaged TT board | Confirm the actual power topology and allowed core-voltage range before promising a voltage sweep | Board/tapeout constraint note |
| Temperature is not controlled or measured at the die | Define fixture, sensor location, soak time, and uncertainty; report ambient/package temperature honestly | Test protocol and uncertainty budget |
| Only one die is available | Frame claims as within-die PVT/workload validation, not process-distribution characterization | Report scope statement |
| External clock/readout introduces measurement error | Use a characterized clock source, measure actual frequency, freeze before readout, and repeat sweeps in both directions | Instrument log and repeated sweeps |

## Suggested contribution and analysis plan

Do not make novelty depend on inventing a new canary circuit. Use the following primary
claim:

> An open-source silicon test vehicle and dataset that quantify how accurately
> extracted STA, a generic ring oscillator, and a structure-matched ring oscillator
> predict operand-dependent arithmetic timing failures across measurable PVT, including
> missed-failure probability, guardband cost, and the improvement from one-point
> calibration.

Predeclare the comparison so a negative result remains useful:

- Ground truth: DUT error-rate boundary at specified thresholds.
- Predictors: case-analyzed extracted STA, generic-RO count, matched-RO count.
- Evaluation: absolute/relative boundary error, rank correlation across configurations,
  false-warning and missed-failure rates at chosen guardbands.
- Calibration comparison: uncalibrated prediction versus one nominal-point calibration.
- Scope: one die unless additional samples become available.

## Definition of “pre-silicon complete”

The pre-silicon phase is complete when all of the following are true:

- [ ] `result_reg` is a verified one-shot capture that cannot self-repair before compare.
- [ ] RTL and zero-delay gate-level regressions pass after the fix.
- [ ] A fresh hardening run passes physical checks.
- [ ] Experiment-specific, case-analyzed STA identifies runtime-sensitizable paths.
- [ ] Selected configurations place predicted timing knees inside the accessible clock
      range with margin for model error.
- [ ] Sensitizing sequences are confirmed in SDF simulation or reduced extracted timing
      simulation.
- [ ] Extracted RO simulations produce usable count ranges for both canaries.
- [ ] Prediction scripts, tables, plots, data schema, and calibration procedure are
      committed and reproducible.
- [ ] The post-silicon sweep protocol, instrument requirements, uncertainty, and raw-data
      format are written before seeing silicon results.
- [ ] Documentation uses consistent 19-cycle frame timing and final build metrics.
- [ ] The exact final submission artifact and manifest are archived outside temporary CI
      storage.

## Recommended execution order

1. Fix and test the one-shot result capture.
2. Re-harden and verify that physical signoff remains clean.
3. Run experiment-specific case-analyzed STA and choose the final measurement matrix.
4. Confirm sensitization with timed simulation and selected-path extraction.
5. Simulate both RO canaries and build the pre-silicon prediction/calibration model.
6. Freeze the research protocol and data schema.
7. Update proposal/status documentation and archive the final build manifest.

