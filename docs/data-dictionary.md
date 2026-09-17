# Development v2 additions

The half-cycle packages are `data/halfcycle/` (earlier build) and
`data/safe10/` (final 10 MHz build), model `tpv-predict-2.0.0`.
The original root-level datasets and the definitions below remain historical
full-cycle baseline evidence. V2 retains their common fields and adds:

| Field | Meaning |
| --- | --- |
| `capture_duty` | Nominal clock-high fraction used by STA/SDF (0.5 in main tables) |
| `high_time_ns` | SDF clock high time; the DUT measurement aperture |
| `control_startpoint`, `control_endpoint`, `control_slack_ns` | Worst case-analyzed synchronous path ending outside the 17 DUT capture flops |
| `n_compared` | Completed comparisons, max(unsaturated launch counter − 1, 0) |
| `run_id` beginning `local-` | Local build identifier; not a GitHub Actions run |
| `git_commit` | Physical build's source commit; not necessarily the analysis commit |
| `sat_win*` | Model predicts a count beyond 65535; hardware wraps and has no saturation flag |
| `startpoint_role` | Structural role of the R2R launch register (`lfsr0`..`lfsr15`, `idx0`, `idx1`), recovered from the operand cone in `tools/sta/experiment_sta.tcl`; net names are only a cross-check |
| `sensitizing_prev_vector` | Operands applied during the frame *before* the recorded launch edge (`prev` of the recorded transition); empty when there is no runtime path |
| `sensitizing_op_index` | Index of the recorded operation in the applied-operand sequence (`tools/common.py::pattern_vectors`), 1-based because a transition is required |
| `global_startpoint_class` | Source class of the unrestricted worst path to `result_reg`: `runtime_state` (one of the 18 launch pins), `static_configuration` (`cfg`/`can_sel`), or `control` |

In v2, `sensitizing_vector` is the **current** operand triple of the recorded
transition (the longest carry chain to `endpoint_bit` among operations whose
operands change from the previous frame), and `sensitizing_chain_stages` is the
chain that vector exercises; the archived v1 table instead reports a single
static vector per row. The launch set and the coverage cross-check are archived
in `experiment_sta_launch_pins.json` (launch pins, roles, assertions enforced
in the Tcl flow, unrestricted-path classification, build hashes) and re-checked
by `tools/sta/verify_launch_coverage.py`. See
[experiment-sta-launch-coverage.md](experiment-sta-launch-coverage.md).

For v2, `predicted_fmax_mhz = 1000 / (clk_period_ns − slack_ns/capture_duty)`.
Canonical period/high-time units are ns; frequency MHz; voltage V; temperature °C.
See `post-silicon-protocol.md` for the new raw silicon schema, including measured
high time, duty, uncertainty, build/analysis commit and batch comparison count.

---

# Data dictionary — pre-silicon prediction package

Scope: field-by-field definitions for the pinned input tables
(`data/experiment_sta.csv`, `data/ro_predict.csv`, `data/sdfsim.csv`) and the
generated prediction table (`data/predict/predictions.csv`). The frozen model
protocol is `docs/prediction-model.md`; the generated package was
`data/predict/` (archived v1; the current v2 packages are
`data/halfcycle/predict/` and `data/safe10/predict/`, same fields plus the v2
additions above).

All units are ns, MHz, V, °C, cycles, or dimensionless counts, as marked.
Empty numeric fields mean "not applicable / no value" (e.g. `hold` rows have no
runtime-sensitizable path). No field is silently rounded to worse than 4
significant digits by `tools/predict_model.py`; input tables carry the
producer's own precision.

## Shared conventions

| Convention | Value | Mirror |
| --- | --- | --- |
| Frame length | 19 clk cycles (`frame_cnt` runs 0..18, `FRAME_LAST = 18`); one timed DUT operation per frame | `src/tt_um_echoworld424_tpv.v` |
| DUT capture | one-shot `result_reg` capture on the falling edge immediately after an accepted rising-edge launch (`load` -> `capture_pending`); holds the first sample until compare | `src/tt_um_echoworld424_tpv.v` |
| Config word | 16 bits: `[1:0]`/`[3:2]`/`[5:4]`/`[7:6]` = seg0..seg3 taps, `[9:8]` = pattern, `[11:10]` = can_sel, `[13:12]` = win_sel, `[14]` = FORCE_CAN, `[15]` = FORCE_ERR | `src/tt_um_echoworld424_tpv.v` config capture |
| Delay-bank tap | tap n = n x 16 inverter pairs (`seg0..seg3` = cfg bits `[1:0]`..`[7:6]`) | `src/tpv_delay_line.v` |
| Canary window | win W = `2^(8 + 2*W)` clk cycles: {0:256, 1:1024, 2:4096, 3:16384} | `src/tt_um_echoworld424_tpv.v` |
| Canary counters | 16-bit rising-edge counters, wrap mod 65536 (telemetry; only `err_cnt`/`ops_cnt` saturate) | `src/tpv_ro_canary.v` (readout bytes 2-5) |
| RO frequency | `f_osc = 1e3 / (2 * T_loop)` MHz; predicted count = `floor(window_cycles * T_clk / (2 * T_loop))` | `tools/run_ro_predict.py` |
| STA failure period | `T_fail = clk_period_ns - slack_ns`; `predicted_fmax_mhz = 1e3 / T_fail` | `tools/common.py::predicted_fmax_mhz` |
| Failure threshold (SDF/silicon) | a period FAILS iff `err_cnt > 0` in the run ("first error"); measured boundary = bracket midpoint of last-failing/first-passing period | `tools/run_sdfsim.py` |
| Corners | `nom_fast_1p32V_m40C` (1.32 V, -40 °C), `nom_typ_1p20V_25C` (1.20 V, 25 °C), `nom_slow_1p08V_125C` (1.08 V, 125 °C) | IHP SG13G2 corner set, `tools/common.py::CORNER_LIBS` |
| Board clock ceiling | 20 ns (50 MHz), `src/pnr.sdc` `create_clock` | `src/pnr.sdc` |

Provenance columns (present and constant in every input table and in
`predictions.csv`): `run_id` (CI hardening run), `git_commit` (RTL commit),
`librelane_image` (tool image), `pdk_rev` (ciel PDK revision). The model
asserts they agree across all inputs and fails loudly otherwise.

## `data/experiment_sta.csv` (96 rows)

Producer: `tools/run_experiment_sta.py`. Case-analyzed post-route
extracted STA (SPEF, per-corner Liberty) of the runtime path from the pattern
generator registers (`u_pat.lfsr`/`u_pat.idx`) to the one-shot DUT capture
registers (`result_reg`), one row per corner x seg-config x pattern.

| Field | Unit | Meaning |
| --- | --- | --- |
| `corner` | - | PVT corner name |
| `v_volt` | V | corner core voltage |
| `t_celsius` | °C | corner temperature |
| `pattern` | - | pattern index 0..3 (cfg bits `[9:8]`) |
| `pat_name` | - | `prbs` / `worst` / `alt` / `hold` |
| `seg0`..`seg3` | - | delay-bank tap per DUT segment (0..3) |
| `cfg_word` | - | full 16-bit config word for the case, hex |
| `clk_period_ns` | ns | analyzed clock period (20.0) |
| `startpoint` | - | OpenSTA startpoint pin of the runtime path |
| `startpoint_reg` | - | RTL register net behind the startpoint (e.g. `u_pat.lfsr[12]`) |
| `endpoint` | - | OpenSTA endpoint pin (result_reg capture D pin) |
| `endpoint_reg` | - | RTL register net (e.g. `result_reg[16]`) |
| `endpoint_bit` | - | captured result bit index 0..16 |
| `path_delay_ns` | ns | launch-CLK to capture-D data delay (arrival minus startpoint /CLK arrival, includes clk->Q) |
| `arrival_ns` | ns | OpenSTA data arrival time |
| `required_ns` | ns | OpenSTA data required time |
| `slack_ns` | ns | setup slack at 20 ns (negative = violating) |
| `slack_met` | - | True/False |
| `predicted_fmax_mhz` | MHz | **uncalibrated STA predictor** = `1e3/(clk_period_ns - slack_ns)`; empty for `hold` |
| `sensitizing_vector` | - | operand triple `a/b/cin` maximizing the exercised carry chain to `endpoint_bit` (`tools/common.py::sensitizing_vector`); `(no runtime-sensitizable path)` for `hold` |
| `sensitizing_chain_stages` | stages | ripple stages exercised by that vector |
| `global_startpoint`/`global_startpoint_reg`/`global_endpoint`/`global_slack_ns`/`global_path_delay_ns` | ns | worst path to `result_reg` from ANY startpoint under the same case analysis; cross-check that the runtime path dominates, not the experimental boundary |
| provenance columns | - | see above |

## `data/ro_predict.csv` (24 rows)

Producer `tools/run_ro_predict.py`: broken-loop extracted STA of both
ring oscillators with SPEF parasitics; 3 corners x 4 can_sel x 2 canaries.

| Field | Unit | Meaning |
| --- | --- | --- |
| `corner`, `v_volt`, `t_celsius` | - | as above |
| `canary` | - | `ro_gen` (generic inverter line) or `ro_mat` (structure-matched loop) |
| `can_sel` | - | canary delay select 0..3 (cfg bits `[11:10]`) |
| `loop_delay_ns` | ns | one full loop traversal (line + gate segment sum); waveform period = `2 * T_loop` |
| `line_seg_ns` | ns | measured segment `nand_out -> line -> tail -> u_close -> u_a2/A` |
| `gate_seg_ns` | ns | measured segment `u_a2/A -> u_a2/X -> u_a3/X (nand_out)` |
| `startpoint`/`endpoint` | - | measured loop node (identical; broken-loop measurement) |
| `f_osc_mhz` | MHz | `1e3 / (2 * loop_delay_ns)` |
| `count_win0..3` | edges | predicted counter increment over the window: `floor(window_cycles * clk_period_ns / (2 * loop_delay_ns))` |
| `sat_win0..3` | - | model flag: 1 if the predicted count would exceed the 16-bit counter range (wrap mod 65536 in hardware; host-side unwrapping needed), else 0. NOT an RTL flag -- the hardware counters simply wrap |
| provenance columns | - | as above |

## `data/safe10/spice/` (extracted RO transient check, revision 3)

Producers `tools/ro/extract_ro_loop.py`, `tools/ro/run_ro_count_case.py` +
`tools/ro/sweep_ro_count.py`, `tools/ro/analyse_ro_intervals.py` and
`tools/ro/compare_ro_spice.py`. Full method and caveats:
`docs/ro-spice-validation.md`; the deck bug that shaped the `control_pins` check
is recorded in [`RO-SPICE-SEL0-ANOMALY.md`](RO-SPICE-SEL0-ANOMALY.md).

The rows are measured with the **counter-inclusive** deck
(`tools/ro/run_ro_count_case.py`), i.e. with the canary counter running, and the
frequency is the *median* rising-edge interval, not the mean. The retired
ring-only sweep (`tools/ro/sweep_ro_spice.py`) is kept for investigating the
ring-only extraction but refuses to run without `--force-ring-only`: it can
close the loop through the wrong tap for `can_sel=2` and is therefore not an
f_osc source.

| File | Contents |
| --- | --- |
| `spice_ro.csv` / `spice_ro.json` | one row per case: ngspice transient result, loop node, measured period/frequency, period spread, periods counted, simulated time, timestep, solver, wall time, deck/raw/log paths |
| `ro_spice_vs_sta.csv` / `.json` | the same rows joined with `data/safe10/ro_predict.csv`: STA frequency, SPICE frequency, `ratio_spice_over_sta`, wire share of the STA loop delay, and the STA startpoint/endpoint |
| `ro_spice_frequency.png` | predicted (STA) versus simulated (SPICE) `f_osc` for both canaries, all corners |
| `ro_spice_ratio.png` | SPICE/STA ratio per case |

Key columns of `spice_ro.csv`:

| Field | Unit | Meaning |
| --- | --- | --- |
| `status` | - | `ok` or the failure reason (failures are kept) |
| `f_osc_mhz` | MHz | measured oscillation frequency, `1 / mean_period` |
| `period_ns`, `period_std_ps` | ns / ps | mean period over settled crossings and its standard deviation |
| `n_periods`, `n_periods_raw` | - | intervals kept after outlier rejection / intervals before |
| `node` | - | measured loop node (the gate output) |
| `tstop_ns`, `tstep_ps`, `solver` | ns / ps / - | transient setup (`uic`, `.ic` on all loop nodes) |
| `control_pins` | - | `ok` when every static control pin read back from the rawfile settled within 50 mV of its deck value; otherwise the offending pins. This check caught a revision-1 deck bug (floating control pins), see `RO-SPICE-SEL0-ANOMALY.md` |
| `vmin`, `vmax` | V | measured loop-node excursion |
| `period_median_ns`, `period_mean_ns`, `period_std_ns` | ns | interval statistics; `f_osc_mhz = 1000 / period_median_ns` |
| `cv` | - | coefficient of variation of the rising-edge intervals; `< 0.01` marks a single-mode ring |
| `n_modes`, `modes` | - | interval-histogram modes (`{period_ns, share}`), for rings whose period is not single-valued |
| `measurement_source` | - | which deck produced the row, and whether a multi-mode case kept its revision-2 value |
| `note` | - | free text; multi-mode substitutions and other per-case caveats are recorded here |
| `run_id`, `git_commit`, `librelane_image`, `pdk_rev` | - | build identity of the netlist the row was measured on (currently run `35034979531`, commit `0a7cd5e`) |

**Method caveat:** the transient runs use the cell-level Magic spiceextraction
(transistor-level cells, cell-internal parasitics, **no interconnect RC**),
while `ro_predict.csv` includes SPEF wire parasitics. SPICE running faster than
STA is therefore expected; the two are independent predictions, not a
correction. Revision 3 of the dataset (current build, counter-inclusive deck)
has no outliers (mean SPICE/STA ratio 1.083, range 1.03–1.14), every case passes
the control-pin read-back check, and 20/24 cases are single-mode — the four
multi-mode configurations are flagged in the CSV's `cv`/`n_modes`/`note` columns.
Revision 2 was measured on commit `b9f03f7` with the counter held in reset and is
archived, unchanged, under `data/safe10/spice/rev2/`.

## `data/safe10/count/` (counter-inclusive RO transient check)

Producers `tools/ro/extract_ro_loop.py --counter`,
`tools/ro/run_ro_count_case.py`, `tools/ro/sweep_ro_count.py`,
`tools/ro/analyse_ro_count.py`, `tools/ro/compare_ro_count.py` and
`tools/ro/make_count_provenance.py`. Full method and results:
`docs/ro-counter-spice-validation.md`; the deck defects found while building it
and the f_osc regeneration record: `FOSC-REGEN-STATUS.md`.

**Scope note (2026-09-17).** This directory is the *free-running* deck's
revision-1 dataset: `en` is tied high, the ring never stops, and the counter is
read while it is still rippling. It shows that the ripple counter counts; it
does not show that the count belongs to the chip's measurement window. The
window deck and its dataset are in `data/safe10/freeze/`
(see `docs/rtl-freeze-validation.md`), and `ro_count.csv` here is retained as
the revision-1 record rather than regenerated.

| File | Contents |
| --- | --- |
| `ro_count.csv` / `ro_count.json` | one row per case: measured ring frequency and period, `q0_negedges`, decoded `counter_final`, `ring_edges_in_count_window`, `count_error_edges`, `count_matches_ring_edges`, `count_matches_period_estimate`, `ripple_stage_rates_ok`, the counting window and sampling time, and the per-stage transition counts |
| `count_vs_fosc.csv` / `.json` | the counter rows joined with `data/safe10/spice/spice_ro.csv`: the two frequencies, their difference, and the counting checks. A frequency difference is reported as a note, not a failure — it means the two decks selected different taps |
| `analyzer_fixtures.json` | the gate-1 fixture results: twelve synthesised fixtures (ten known-good/known-bad, including `midrail_level`, a counter bit quiet at 0.6 V on a 1.2 V rail, plus `freq_units` and `freq_wrap`, which assert the counter-derived frequency below and across the 16-bit wrap) and four interval-classifier cases, each with the expected and observed status and process exit code |
| `provenance.json` | commit/run/netlist identity, PDK and tool roles, file hashes, and the revision notes |
| `FOSC-REGEN-STATUS.md` | record of the f_osc regeneration: the driver bug, the window artefact, the ring-only deck defect, and the multi-mode configurations |

Key columns of `ro_count.csv` (revision 1; the window dataset uses the analysis
vocabulary documented in `docs/rtl-freeze-validation.md`):

| Field | Unit | Meaning |
| --- | --- | --- |
| `status` | - | `ok` when the count matched the ring edges and every stage rippled correctly |
| `f_osc_mhz`, `period_ns` | MHz / ns | ring frequency from the same rawfile, for the cross-check |
| `q0_negedges` | - | bit-0 falling edges, i.e. counter increments, in the window |
| `counter_final` | - | the 16 saved bits decoded after bit 0's last edge |
| `ring_edges_in_count_window` | - | ring rising edges measured independently over the same window |
| `count_error_edges` | edges | `counter_final - ring_edges_in_count_window`, unwrapped: large by construction on a run that wrapped |
| `count_error_circular` | edges | the wrap-aware distance used for the verdict, `min(|counter_final - edges % 65536|, 65536 - that)`, so a correct wrapped run is not called a mismatch |
| `count_aliased` | - | true when more than 65536 edges were offered, i.e. the counter wrapped |
| `counter_wraps_inferred`, `counter_edges_reconstructed` | - / edges | the wrap count (0–2) that best matches the independently measured edges, and `counter_final + wraps*65536` |
| `f_count_from_counter_mhz` | MHz | reconstructed edge count divided by the **first-to-last offered-edge span** — the same interval `f_count_mhz`/`f_steady_mhz` use, so the three are directly comparable |
| `count_window_ns` | ns | the declared gate-open duration, `t_en_fall - t_en_rise`; `null` unless the window is a single contiguous one (`n_en_rise <= 1`, `n_reset_releases <= 1`, gate closed in the run), because it would otherwise span the paused intervals of a FREEZE case |
| `f_count_over_window_mhz` | MHz | the count divided by `count_window_ns`; biased by up to one edge over the window (the first edge falls somewhere inside the first period), so it is reported for completeness rather than as the frequency estimate |
| `f_count_over_window_defined` | - | whether `count_window_ns` applies to this case |
| `count_matches_ring_edges`, `count_matches_period_estimate`, `ripple_stage_rates_ok` | - | the three independent checks |
| `count_window_ns`, `sample_time_ns` | ns | the counting window and when the counter was read |

## `data/safe10/freeze/` (RTL freeze validation: gates 1–3)

Producer `tools/ro/summarise_freeze.py` from the runs under
`runs/freeze-validation/` (decks, rawfiles and ngspice logs stay there; the
analysis JSONs, tables and hashes are archived here). Full method and verdicts:
`docs/rtl-freeze-validation.md`; the acceptance rules were predeclared in
`PREDECLARED-TOLERANCE.md` before the results were available.

| File | Contents |
| --- | --- |
| `PREDECLARED-TOLERANCE.md` | the repeatability/convergence/coverage criteria, fixed before the sweep results |
| `freeze_summary.json` | per-gate verdicts, the RTL window probe, unstable-rate case list and the wire-capacitance comparison |
| `primary_windows.csv` / `.json` | every primary window run: controls, counts, rate, CV, coverage and acceptance |
| `matrix_windows.csv` / `.json` | the 24-case (corner × canary × `can_sel`) counter matrix at 50 MHz |
| `repeatability.csv` / `.json` | count spread across startup phases per configuration, against the 1 % criterion |
| `coverage.csv` / `.json` | per-case ring-edge count, highest exercised ripple stage, unexercised bits |
| `carry.json` | the extended-gate carry test (fastest ring, crosses 2^15) |
| `wrap_result.json` | the full-width wrap run on the same configuration with the gate open 55.2 µs (20 ps step): 65 715 edges offered, decoded 179, one inferred wrap, reconstructed 65 715, circular error 0, every stage exercised at its binary-carry rate. Regenerated from the stored rawfile by `tools/ro/reanalyse_carry_result.py` after the wrap-aware analyzer fixes |
| `control.json` | FORCE_CAN hold, FREEZE/resume and reset-during-window cases |
| `convergence.csv` / `.json` | 5/10/20/40 ps and 2 ps timestep comparison at fixed 1 µs windows |
| `stop_transient_fixtures.json` | `tools/ro/test_classify_stop_transient.py`: 6 synthetic waveforms pinning the stop-transient classifier, including 50 % and 75 % marginal pulses (invisible to the pre-fix detector, which reused the analyzer's 30 %→70 % hysteresis), a 10 % level that is excluded by design, and a truncated pulse at the gate close |
| `analyzer_recheck.json` | every archived counter waveform re-analysed by `tools/ro/recheck_archived_counts.py`, A/B against the pre-fix analyzer revision: per-case decode-point levels of all 16 bits, validity against the 15 %/85 % band, and before/after verdicts (64/64 valid, 0 verdict changes) |
| `wirecap_generation_fixture.json` | `tools/ro/test_add_wire_caps.py`: the emitted wire capacitors of a synthetic 2 fF/1 fF loop, parsed with SPICE scale suffixes and compared with the requested farads (the check that catches the missing-`p`-suffix defect) |
| `wirecap_sensitivity_corrected.json` | the valid wire-capacitance sensitivity run (`tools/ro/run_wirecap_sensitivity.py --capdir .../wirecap-correction --jobs 8`, 400 ns window, 5 ps): each corner with and without the full extracted lumped capacitance, with the per-case counts and the frequency delta. The invalid revision-1 runs stay under `runs/freeze-validation/wirecap_sensitivity.json` |
| `stop_phase_coverage.json` | gate 3 stop-phase evidence derived from the archived window waveforms by `tools/ro/archive_stop_phase.py` (no new simulation): per case, the ring period, the ring phase at gate close (`stop_phase`), the number of crossings after the gate closes, and the stop-transient amplitude classification (`n_full` / `n_runt` / `n_noise`). 42 cases, 30 distinct phases spanning 0.892 of a period, 73 343 crossings, 0 runt pulses |
| `stop_phase_sweep.json` | the targeted stop-phase sweep (`tools/ro/sweep_stop_phase.py`), which places the `en` fall at `periods + phase` ring periods after the rise so the stop phase is varied directly instead of through the host clock period; one record per phase with the analyzer verdict |
| `freeze_tables.md` | the same data as markdown tables, quoted in the validation record |
| `manifest.json` | sha256 of every archived file and of the analysis tools that produced them |


## `data/sdfsim.csv` (one row per SDF-sim probe point)

Producer `tools/run_sdfsim.py`: SDF-annotated full-chip timing
simulation of the seg3333/worst boundary sweep (IOPATH-only annotation; see
limitations in `docs/prediction-model.md`).

| Field | Unit | Meaning |
| --- | --- | --- |
| `corner` | - | corner name, or `(zero-delay reference)` for the functional sanity row |
| `period_ns`/`freq_mhz` | ns / MHz | probe clock |
| `cfg_word` | - | driven config word (`0x4DFF` = segs 3333 + worst + can_sel 3 + win0 + FORCE_CAN; `0x0DFF` = the invalid RO cross-check with FORCE_CAN off) |
| `segs` | - | segment taps as a 4-char string (`3333`) |
| `pattern` | - | pattern name (`worst`) |
| `cansel`/`winsel`/`forcecan` | - | canary select, window select, FORCE_CAN bit |
| `nframes_req` | frames | requested frames |
| `ops` | ops | operations actually run (19 cycles each) |
| `err_cnt` | errors | DUT errors observed; `> 0` marks a failing period (first-error threshold) |
| `err_rate_per_op` | errors/op | `err_cnt / ops` |
| `gen_cnt`/`mat_cnt` | edges | RO counter readback (bytes 2-5); only meaningful with FORCE_CAN off. **The existing FORCE_CAN-off row is INVALID for model purposes**: the RO loop cells carry hard 0.000 SDF delays because `src/pnr.sdc` disables RO timing arcs (`docs/ro-sdf-crosscheck-diagnosis.md`) |
| `cfg_echo` | - | readback byte 8 = segment-tap echo `{seg3,seg2,seg1,seg0}` (`ff` expected for seg3333; canary select/window come back in byte 9 bits [3:0]) |
| `stat` | - | readback byte 9 status flags `{1, mat_ro_dead, gen_ro_dead, err_seen, can_sel, win_sel}` (see `docs/info.md`) |
| `err_dut` | - | readback byte 10: low 8 bits of the first failed DUT result capture |
| `ro_note` | - | empty for DUT boundary rows; on the FORCE_CAN-off row explains why `gen_cnt`/`mat_cnt` are blanked |
| `sdf` | - | path of the annotated IOPATH SDF; empty = zero-delay reference |
| `log` | - | raw log under `data/sdfsim/` |
| provenance columns | - | as above |

## `data/predict/predictions.csv` (288 rows = 96 cells x 3 predictors)

Producer `tools/predict_model.py`. Long format: one row per corner x
seg-config x pattern x predictor, with canary telemetry joined per corner at
the predeclared readout (can_sel=3, win0).

| Field | Unit | Meaning |
| --- | --- | --- |
| `corner`, `v_volt`, `t_celsius` | - | joined from `experiment_sta.csv` |
| `seg0`..`seg3`, `seg_label` | - | delay-bank taps and their `s0s1s2s3` label |
| `pattern`, `pat_name` | - | pattern index / name |
| `predictor` | - | `sta`, `ro_gen`, or `ro_mat` (definitions in `docs/prediction-model.md`) |
| `status` | - | `ok`, or `no_runtime_path` (hold rows: no prediction exists) |
| `sta_path_delay_ns`, `sta_slack_ns`, `sta_slack_met` | ns | source STA path quantities for the cell (join context) |
| `predicted_fmax_mhz` | MHz | uncalibrated predicted first-failure frequency of `predictor` |
| `predicted_period_ns` | ns | `1e3 / predicted_fmax_mhz` |
| `cal_k` | - | one-point calibration factor; placeholder 1.0 pre-silicon |
| `predicted_fmax_mhz_cal` / `predicted_period_ns_cal` | MHz / ns | calibrated prediction; identical to uncalibrated while `cal_k = 1.0` |
| `ro_gen_count_win0..3` / `ro_mat_count_win0..3` | edges | joined canary counts at this corner, can_sel=3 (`tools/run_ro_predict.py`) |
| `ro_gen_fosc_mhz` / `ro_mat_fosc_mhz` | MHz | joined canary oscillation frequencies |
| `run_id`, `git_commit`, `librelane_image`, `pdk_rev`, `model_version` | - | provenance + frozen model id |

`data/predict/predictions.json` carries the same rows plus provenance,
predictor/calibration blocks, cross-checks (`sta_vs_sdf_seg3333_worst`,
`canary_16bit_fit`, `gen_over_mat_win0`), a `sanity` block, and an
`invalid_rows` list flagging the excluded FORCE_CAN-off SDF row.
