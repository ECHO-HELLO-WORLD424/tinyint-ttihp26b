# Data dictionary — pre-silicon prediction package

Scope: field-by-field definitions for the pinned input tables
(`data/experiment_sta.csv`, `data/ro_predict.csv`, `data/sdfsim.csv`) and the
generated prediction table (`data/predict/predictions.csv`). The frozen model
protocol is `docs/prediction-model.md`; the generated package is `data/predict/`.

All units are ns, MHz, V, °C, cycles, or dimensionless counts, as marked.
Empty numeric fields mean "not applicable / no value" (e.g. `hold` rows have no
runtime-sensitizable path). No field is silently rounded to worse than 4
significant digits by `tools/predict_model.py`; input tables carry the
producer's own precision.

## Shared conventions

| Convention | Value | Mirror |
| --- | --- | --- |
| Frame length | 19 clk cycles (`frame_cnt` runs 0..18, `FRAME_LAST = 18`); one timed DUT operation per frame | `src/tt_um_echoworld424_tpv.v` |
| DUT capture | one-shot `result_reg` capture at frame cycle 0 (`chk_start`); holds until compare | `src/tt_um_echoworld424_tpv.v` |
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

Producer: `tools/run_experiment_sta.py` (P0.2). Case-analyzed post-route
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

Producer `tools/run_ro_predict.py` (P1.3): broken-loop extracted STA of both
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

## `data/sdfsim.csv` (one row per SDF-sim probe point)

Producer `tools/run_sdfsim.py` (P1.2): SDF-annotated full-chip timing
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

Producer `tools/predict_model.py` (P1.1). Long format: one row per corner x
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
