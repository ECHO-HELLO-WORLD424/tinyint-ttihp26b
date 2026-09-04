# Pre-Silicon Readiness Audit and Action Plan

Audit date: 2026-09-03  
Branch: `proposal-canary`  
Audited commit: `206715252bb569430b0d8569393f12997b2a552b`

## Work-in-progress handoff (2026-09-04)

> **Status log for resuming on another machine.** Written while pausing the
> local pre-silicon tooling runs (the full-chip SDF sweep probe was consuming
> excessive CPU locally and was aborted; see "In progress" below).

### Done and pushed

| Item | State | Evidence |
| --- | --- | --- |
| P0.1 one-shot DUT capture | **Done**, RTL + cocotb test `test_oneshot_capture_holds` (verifed to fail against the old enable) | commit `21d43c6` |
| P2.3 RTL width warnings | **Done** (10/16-bit compares fixed; superseded by 16-bit counters in `1e31757`) | commit `21d43c6` |
| 16-bit RO edge counters | **Done** — extracted-RO STA showed both canary counters overflow 10 bits at nominal PVT (gen ~3555, mat ~1954 counts at 1.20V/25C, win0), making the canaries indistinguishable at the calibration point; counters widened to 16 bits (readout bytes 2-5 were already reserved) | commit `1e31757` |
| Fresh hardening runs | **Done, all green** (gds + precheck + gl_test + viewer) | run `33835818836` (8bcffc2), run `33839023290` (1e31757, final RTL) |
| P0.2 experiment STA flow | **Done** — `tools/sta/experiment_sta.tcl` + `tools/run_experiment_sta.py`; 96 case-analyzed rows (3 corners x 8 seg-configs x 4 patterns) from `u_pat.lfsr/idx` -> `result_reg`; slow-corner worst: seg3333/worst delay 24.81 ns -> predicted knee 39.6 MHz (inside the 1-50 MHz board range); `data/experiment_sta.csv/.json` + raw reports | run `33835818836` artifacts |
| P1.3 RO loop-delay prediction | **Done (first pass)** — `tools/ro/ro_predict.tcl` + `tools/run_ro_predict.py`; 24 rows (3 corners x 4 can_sel x 2 canaries); T_loop 0.47-10.24 ns; `data/ro_predict.csv/.json` | same artifacts |
| P2.1 docs (frame timing, counters) | **Done** for 19-cycle frames + 16-bit counters in `docs/info.md`, RTL header, test comments; remaining doc fixes listed below | commit `1e31757` |
| Artifact staging | **Done** — `artifacts/run-33835818836/` (final GDS/netlist/SPEF/SDF/SDC/DEF/metrics + post-PnR STA reports, 32 MB) copied from CI into the repo for local tooling and durability | this repo |

### In progress (was running when paused)

**P1.2 full-chip SDF-annotated timing sweep** (`tools/run_sdfsim.py`,
`tools/sdf/tb_sdfsim.v`, `tools/sdf/make_sdf_lib.py`, `tools/sdf/filter_sdf.py`).

Bring-up state:

- Timing-safe cell library works: `data/sdfsim/sg13g2_stdcell_sdf.v`
  (timing checks stripped, IOPATH specify arcs kept).
- Zero-delay reference probe **passes** (commit-level sanity: ops=8, err=0,
  cfg_echo=ff, gen/mat=0 with FORCE_CAN) — the TB protocol is functional.
- Full-SDF annotation with `-ginterconnect` **crashes Icarus**
  (`NULL handle passed to vpi_scan`); without it, unfiltered SDF spews
  thousands of "Could not find net" errors. Mitigation implemented:
  `tools/sdf/filter_sdf.py` reduces each corner SDF to per-cell IOPATH
  delays (`data/sdf_path/<corner>.iopath.sdf`).
- **Known issue before resuming:** the IOPATH-only probe was still consuming
  runaway CPU when aborted. Suspected cause: some cell arcs have no matching
  IOPATH in the annotation (e.g. dropped `ifnone` edge-sensitive paths on
  flop models), leaving zero-delay paths that livelock the simulator. Before
  the next run: (a) always wrap vvp in a wall-clock timeout, (b) check the
  annotation log for unannotated IOPATHs, (c) consider adding
  `-ginterconnect` + a smaller INTERCONNECT subset, or per-cell delay
  `defparam`-style annotation as a fallback, or move to the reduced
  extracted-path testbench variant the plan allows. Run the sweep on the
  faster machine with `python3 tools/run_sdfsim.py --smoke` first.

### Not started

- P1.1 prediction model + data schema (`tools/predict_model.py` not yet
  written; inputs `data/experiment_sta.csv` + `data/ro_predict.csv` exist).
- RO loop-delay model refinement: current measurement excludes the two gate
  cells at the loop break (u_a2, u_a3 ~2 gate delays); add the
  `u_a2/A -> u_a3/Y` segment to `tools/run_ro_predict.py` and re-emit.
- P1.2 documentation of GL-suite scope in `docs/research-proposal.md`.
- P2.1 remaining doc fixes: research-proposal stale metrics ("2482
  instances, ~82%" -> use `artifacts/run-*/final/metrics.json`: 2641
  instances, 1688 stdcell + 953 fill, 79.544% utilization; slow-corner
  violation claim -> now backed by `data/experiment_sta.csv` case analysis;
  "16-bit edge counter" statement now true after `1e31757`).
- P2.2 build manifest (`tools/make_manifest.py` not written) + durable
  archive of the final submission artifact (final RTL run:
  `33839023290`; download with `gh run download 33839023290 ...`).
- P2.3 fanout/disconnected-pin write-up: both max-fanout violations
  (`clkbuf_0_clk/X` fanout 16, `_1405_/Q` fanout 10, limit 8) have clean
  max-slew/max-cap checks (0 violations) -> report-only relative to the
  LibreLane generic limit; disconnected pin = `ena` (intentionally unused,
  consumed in `_unused`, 0 critical). Document in research-proposal.
- Regenerate `data/` from the FINAL artifacts (`run-33839023290`,
  commit `1e31757`) once SDF sim is stable: experiment STA, RO prediction
  (16-bit counters do not change the loops' delays; STA data identical in
  structure but should be re-emitted for provenance), SDF sweep.
- Update the "Current verified baseline" table below with the final run.

### Environment notes for the new machine

- All STA/RO/SDF tooling runs inside `ghcr.io/librelane/librelane:3.0.5`
  (tool-identical to the CI gds job). Local STA drivers call it via
  `docker run` (see `tools/common.py::docker_prefix/docker_mount_args`;
  adjust `amazing_robinson` / mount paths for the new host).
- The IHP PDK is fetched from the ciel store at the CI revision
  `c4b8b4e5e7a05f375cca3815d51b3a37721fbf5c`
  (`ciel fetch --pdk-family ihp-sg13g2 <rev>`; mounted at `/pdk`).
- Artifacts: `artifacts/run-33835818836/` (committed) and, for the final
  RTL commit, CI run `33839023290` (download `GDS_logs` artifact, copy
  `final/{gds,nl,lib,spef,sdf,sdc,def,metrics.json,commit_id.json}` +
  `54-openroad-stapostpnr` + `resolved.json` into
  `artifacts/run-33839023290/`).
- Cocotb RTL regression runs in the devcontainer (`cd test && make`;
  10/10 pass at `1e31757`). No cocotb is needed for tools/.
- `data/` currently holds results from the `8bcffc2` hardening run
  (provenance columns inside each CSV identify the run); regenerate for
  the final commit before freezing the prediction package.

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

