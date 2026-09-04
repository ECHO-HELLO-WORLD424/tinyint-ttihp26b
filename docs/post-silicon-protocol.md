# Frozen post-silicon measurement protocol

Status: **frozen before silicon**. This document predeclares the measurement
matrix, raw-data format, instruments, uncertainty budget, procedure, and
failure-boundary extraction for the post-silicon sweep. It is the measurement
counterpart to the frozen prediction protocol `docs/prediction-model.md`
(model `tpv-predict-1.0.1`) and uses the field conventions of
`docs/data-dictionary.md`. Chip-level protocol (config word, 19-cycle frame,
byte readout, FREEZE) follows `docs/info.md` ("How it works", "How to test");
any conflict with RTL behavior is recorded as an anomaly, never silently
resolved. Conventions: 19 clk cycles per timed operation, one DUT capture per
frame; all boundary arithmetic is in the clock **period** domain.

## 1. Measurement matrix (predeclared)

### 1.1 PVT grid

| Axis | Points | Notes |
| --- | --- | --- |
| Core voltage | **TBD pending board verification** | The Tiny Tapeout demo board power topology must be confirmed (see risk table in `docs/research-proposal.md`) before a voltage sweep is promised. Predeclared intent if adjustable: 1.32 / 1.20 / 1.08 V (the three STA corner voltages of `docs/data-dictionary.md` "Corners"), optional 1.26 / 1.14 V intermediates. If fixed at 1.20 V: single-V study, documented as such. |
| Temperature | Ambient lab (record actual, target ~25 °C) + hot plate ~85 °C if available | No cold control: the `nom_fast_1p32V_m40C` corner is unreachable and is documented as an exclusion, not silently dropped. Soak >= 10 min after any thermal change; sensor <= 5 cm from package; record sensor type and exact location string. Die temperature is not measured directly; package/ambient is reported honestly. |
| Clock frequency | 1–50 MHz (board range), per §1.2 | Actual frequency measured at the board clock pin, never the nominal value. |
| Seg configs | 0000, 1111, 2222, 3333, 3000, 0003, 2130, 1203 | Same set as `data/predict/predictions.csv`. |
| Patterns | prbs (0), worst (1), alt (2), hold (3) | `hold` and `alt` are controls: `hold` has no runtime path, `alt` knees (415–877 MHz) lie above the board ceiling (`docs/prediction-model.md` "Known limitations"). |

Priority tiers (run in order; a tier is complete before the next starts):

1. **T1**: seg3333 x {worst, prbs} at every reachable (V, T) — includes the
   calibration anchor and its fallback (§5 step 9).
2. **T2**: remaining six seg configs x {worst, prbs} at each reachable corner.
3. **T3**: {alt, hold} controls at nominal (1.20 V, ambient) only.

Config word for every measurement row: `cfg = segs | pat<<8 | 0xC00`
(cansel = 3, winsel = 0, FORCE_CAN = FORCE_ERR = 0), i.e. the predeclared
canary readout of `docs/prediction-model.md` ("Inputs (pinned)"). Example:
seg3333/worst = `0x0DFF` (same encoding as `data/sdfsim.csv`).

### 1.2 Frequency sweep and op counts

Predicted first-failure frequencies inside the 1–50 MHz board range
(`data/predict/summary.md`, pattern = worst): slow-corner seg3333 at
39.34 MHz STA / 39.04 ro_gen / 38.41 ro_mat (39.6 MHz for prbs), and
seg2222 at 50.25 MHz (at the ceiling). All typ and fast knees
(61.5–266 MHz) are above the ceiling. Sweep steps are therefore
**knee-anchored**, not uniform:

| Phase | Points | N_ops (host-timed) | Direction |
| --- | --- | --- | --- |
| Coarse | 1, 2, 5, 10, 20, 30, 40, 45, 50 MHz | 200 | up then down |
| Fine | period-linear, dT = 0.5 ns over [T_knee_pred − 3 ns, T_knee_pred + 3 ns] (13 points/direction; T_knee_pred from `data/predict/predictions.csv` for that corner x seg x pattern) | 1e5 | up then down |
| 1e-6 pass | the four points bracketing the final boundary (2 each side) | 3e6 | up then down |

Op-count rationale, with P(detect >= 1 error) = 1 − (1 − p)^N:

| True err rate p | N = 1/p | N = 3/p |
| --- | --- | --- |
| 1e-2 | 100 ops -> 63% | 300 ops -> 95% |
| 1e-4 | 1e4 ops -> 63% | 3e4 ops -> 95% |
| 1e-6 | 1e6 ops -> 63% | 3e6 ops -> 95% |

The 200-op coarse phase is the `N_ops >= 200` minimum of `docs/prediction-model.md`
"Ground truth (post-silicon first-failure boundary)" and resolves the 1e-2
threshold (2 errors in 200 ops); the 1e5-op fine phase resolves 1e-4 (10
expected errors at exactly 1e-4); the 3e6-op pass resolves 1e-6 at 95%.

Frame-rate arithmetic (ops/s = f_clk / 19; t_op = 19 / f_clk):

| f_clk | t_op | ops/s | 1e6 ops | 3e6 ops |
| --- | --- | --- | --- | --- |
| 50 MHz | 380 ns | 2.63e6 | 0.38 s | 1.14 s |
| 39.34 MHz | 483 ns | 2.07e6 | 0.48 s | 1.45 s |
| 10 MHz | 1.9 us | 5.26e5 | 1.9 s | 5.7 s |
| 1 MHz | 19 us | 5.26e4 | 19 s | 57 s |

A full fine sweep (13 pts x 2 directions x 3 repeats at 1e5 ops, ~39 MHz) is
< 4 s of live running; wall time is dominated by PVT changes and readout, not
data collection. The chip's `ops_cnt`/`err_cnt` saturate at 65535, so for
N_ops > 65535 the host-timed count (f_meas x unfrozen duration / 19) is
authoritative and `ops_sat = 1`; `err_cnt` saturation (65535) is recorded as
`err_sat = 1` and the rate reported as a lower bound.

Repetition policy: every fine region is swept **up then down**; repeat_idx
0, 1, 2 (three complete up/down cycles). Coarse phases are swept once each
direction. Both directions contribute to one bracket (§7).

## 2. Per-point measurement record (raw-data format)

One immutable append-only CSV per die (`data/post-silicon/raw_<die_id>.csv`),
flat header:

```
timestamp_utc,die_id,board_id,operator,host_sw,host_fw,clock_src,clock_cal,dmm_id,cfg_word_hex,seg0,seg1,seg2,seg3,pat_idx,pat_name,cansel,winsel,win_cycles,forcecan,forceerr,v_meas_mv,v_sense,t_meas_c,t_sensor,soak_min,f_meas_mhz,f_nom_mhz,sweep_dir,repeat_idx,sweep_phase,n_ops_chip,n_ops_host,ops_sat,err_cnt,err_sat,err_rate_per_op,err_seen,err_dut_b,cfg_echo_b8,stat_b9,gen_cnt,mat_cnt,gen_dead,mat_dead,wrap_suspect,frozen,git_commit,notes
```

Non-obvious fields:

| Field | Meaning |
| --- | --- |
| `v_meas_mv`, `v_sense` | Voltage in mV measured at the board (`v_sense` = measurement point), not the supply setpoint. |
| `t_meas_c`, `t_sensor` | Temperature in °C and sensor-location string. |
| `f_meas_mhz`, `f_nom_mhz` | Measured clock at the board pin; nominal kept for reference only. |
| `win_cycles` | 256 / 1024 / 4096 / 16384 per `docs/data-dictionary.md` "Canary window" (always 256 here). |
| `n_ops_chip` / `n_ops_host` / `ops_sat` | Chip op counter (saturates 65535) vs host-derived op count; host value is authoritative when `ops_sat = 1`. |
| `err_rate_per_op` | `err_cnt / n_ops_host` (raw; no smoothing). |
| `err_seen`, `err_dut_b` | Byte 9 bit 4; first-error DUT byte (byte 10). |
| `cfg_echo_b8`, `stat_b9` | Readback bytes 8–9 exactly as read (§2 of `docs/info.md` "How to test"); byte 8 = `{seg3,seg2,seg1,seg0}`, byte 9 = `{1, mat_dead, gen_dead, err_seen, cansel, winsel}`. |
| `gen_cnt`, `mat_cnt`, `gen_dead`, `mat_dead` | Canary counts (bytes 2–5) and byte-9 dead flags. |
| `wrap_suspect` | Derived flag: 1 if a canary count is inconsistent with neighbors (canary counters wrap mod 65536; see §7). |
| `frozen` | Must be 1: readout only valid after FREEZE (docs/info.md "How to test" step 3). |
| `git_commit` | Commit of the analysis scripts/host code used, per AGENTS.md provenance rule. |

Prediction join keys (applied only in derived files, §6): `v_meas_mv`/`t_meas_c`
-> nearest declared corner, plus `seg0..seg3` + `pat_idx`, joined to
`data/predict/predictions.csv` per predictor (`sta`, `ro_gen`, `ro_mat`).

## 3. Instrument requirements

| Instrument | Minimum | Preferred | Acceptable substitute |
| --- | --- | --- | --- |
| Clock source | 1–50 MHz, characterized period jitter | FPGA host PLL, verified with counter | Signal generator (state jitter spec); TT demo board clock only as last resort — characterize it first (research-proposal risk: 50 MHz board clock noise) |
| Frequency measurement | 6-digit counter, >= 1 ppm class | + period-jitter measurement on scope | DSO period cursors if counter unavailable (record accuracy) |
| Core-voltage measurement | 4.5-digit DMM at board core test point | 5.5/6.5-digit DMM, Kelvin sense | PSU front-panel readout, flagged in `notes` |
| Supply | Bench PSU, current limit set | Remote sense | Fixed rail if board topology forbids control (§1.1) |
| Temperature | RTD/thermistor logger +/- 1 °C near package | + IR pyrometer on package top (emissivity noted) | Hot plate with built-in sensor (record offset) |
| Readout path | USB serial on TT demo board (uo/uio/ui per docs/info.md "External hardware") | Same + logic-analyzer spot check of uo[3:0] pointer | FPGA host UART, or FTDI/CH341 GPIO bit-bang (slower; acceptable because counters are frozen) |

Host controller duty: after boot, `uio` becomes an output on the chip; the
host must release its `uio` drivers after the config phase (research-proposal
risk table: uio contention).

## 4. Uncertainty budget

| Source | Predeclared assumption | How it enters the boundary error |
| --- | --- | --- |
| Clock accuracy | +/- 50 ppm (TCXO class), verified by counter | Multiplicative on `f_meas_mhz`; ppm-level, negligible vs step quantization |
| Clock jitter | period jitter <= 100 ps RMS (source datasheet; verify) | Consumes setup margin -> failures occur slightly earlier than jitter-free; ~0.4% frequency bias at a 25 ns knee; folded into the bracket, not corrected |
| Voltage accuracy | DMM +/- 0.05% + 2 mV at board; board-to-die IR drop unverified, assumed <= 2% until topology check | Shifts the (V, T) operating point vs the corner grid; the within-die sensitivity dF/dV is measured via canary telemetry across the grid, not assumed |
| Temperature | sensor +/- 1 °C; die-vs-sensor gradient unquantified (package top vs ambient reported separately) | Same channel as voltage; dominates PVT-placement error at elevated T |
| Canary quantization | +/- 1 edge on win0 counts >= 240, i.e. <= ~0.4% on count ratios (`docs/prediction-model.md` "Known limitations") | Enters the canary predictors' count ratios only |
| Error-rate quantization | 1 error / N_ops | 1e-5 at N = 1e5; sets the resolvable threshold |
| Bracket quantization | +/- dT/2 = +/- 0.25 ns | +/- ~1% frequency at a 25 ns knee; bounded by §7 rule |
| Repeatability | measured, not assumed | Reported as min–max of the three repeat midpoints |

The reported boundary error `e_abs = P_cal − F_meas` (`docs/prediction-model.md`
"Post-silicon evaluation metrics (predeclared)") carries its uncertainty as the
quadrature sum of the bracket, repeatability, clock, and jitter terms; the
V/T-placement terms are reported separately because they are shared across a
corner, not independent per point.

## 5. Procedure

1. **Fixture verification (gating)**: confirm board core-voltage accessibility
   (resolves the §1.1 TBD); characterize clock source (frequency + jitter) and
   record instrument serials/cal dates in the header of the raw CSV.
2. **Bring-up**: 1 MHz, rails measured, reset pulse, chip defaults.
3. **Config latch + echo** (`docs/info.md` "How to test" step 1): drive the
   config word while `rst_n` is low; hold it stable through three clocks after
   release; then set `ui[7]` low. Verify byte 8 equals the driven segs and
   byte 9 bits [3:0] equal {cansel, winsel}. Any mismatch = fatal anomaly.
4. **DFT gate A — FORCE_ERR** (cfg bit 15, nominal 10 MHz, N = 200): every
   compared op must error: `err_cnt == n_ops − 1`, `err_seen = 1`, byte 10 =
   captured first-error byte. Must pass before any boundary sweep is trusted.
5. **DFT gate B — FORCE_CAN** (cfg bit 14): `gen_cnt == mat_cnt == 0` and
   `gen_dead/mat_dead` set in byte 9.
6. **Zero-error sanity**: all 8 segs x 4 patterns at 10 MHz, N = 200: expect
   `err_cnt = 0` everywhere.
7. **Hold control at 50 MHz**, N = 1e5: must stay 0 (no runtime path). An
   error here indicates a non-path mechanism: record and investigate.
8. **Canary baseline**: nominal, record gen/mat win0 counts (predicted 1299 /
   384 at typ, `data/predict/summary.md`) — recorded, not gated.
9. **Anchor attempt** (T1, seg3333/worst, 1.20 V, ambient): coarse + fine
   sweep. Two outcomes, both predeclared:
   - Boundary found <= 50 MHz: this is `F_meas(A)` for the one-point
     calibration of `docs/prediction-model.md` "One-point calibration
     (predeclared)".
   - **Censored** (no error over N = 3e6 at 50 MHz): the predicted nominal
     knee (61.46 MHz) is above the board ceiling. Record `F_meas(A) > 50 MHz`
     and switch to the predeclared fallback anchor A' = (1.08 V, max reachable
     T, seg3333, worst), matched to corner `nom_slow_1p08V_125C`. This fallback
     is already predeclared by model `tpv-predict-1.0.1`; no model change is
     made after observing the anchor. The residual T mismatch (achievable
     T < 125 °C) is recorded and entered in §4.
10. **Matrix sweep** (T1 -> T2 -> T3): per point: reset pulse with the new
    config (counters clear only on `rst_n`, `src/tt_um_echoworld424_tpv.v`
    error/op counter block), run N_ops with `ui[7]` low, then **freeze
    (`ui[7]` high) before readout** and read all 16 status bytes
    (`docs/info.md` "How to test" step 3).
11. **Canary telemetry**: gen/mat win0 counts are read at every point (same
    run); optional extra windows at the anchor region only.
12. **Anomalies**: any unexpected row (echo mismatch, wrap_suspect, hold
    error, dead RO at alive corners) is appended with an anomaly code in
    `notes`; nothing is deleted. Exclusions are listed in
    `data/post-silicon/exclusions.md` with reasons (AGENTS.md rule).

## 6. Data recording rules (AGENTS.md)

- Provenance in every row: die/board serial, timestamp, operator, host tool +
  firmware versions, clock source + cal date, `git_commit`.
- No silent exclusion: every run produces a row; exclusions are documented
  (`exclusions.md`), negative results and out-of-range points included.
- Raw vs derived: raw CSVs are immutable (append-only; SHA-256 recorded in a
  manifest after each session). Joins, boundary extraction, and calibration
  live in separate derived files under `data/post-silicon/`.
- Prediction comparison **only after the boundary dataset is frozen** (full
  sweep done, manifest hashed). The comparison then applies
  `docs/prediction-model.md` "Post-silicon evaluation metrics (predeclared)"
  verbatim, substituting measured `k_x` values only.

## 7. Failure boundary definition and extraction

Thresholds per point (err_rate = err_cnt / N_ops):

| Threshold | Failing iff | Measured at |
| --- | --- | --- |
| first error (primary) | `err_cnt >= 1` and N_ops >= 200 (`docs/prediction-model.md` "Ground truth") | all phases |
| 1e-2 | err_rate >= 1e-2 | coarse + fine |
| 1e-4 | err_rate >= 1e-4 | fine |
| 1e-6 | err_rate >= 1e-6 | 1e-6 passes |

All four thresholds are recorded and scored under model `tpv-predict-1.0.1`;
calibration still uses the primary first-error boundary only. Canary counters
wrap mod 65536 (no saturation
logic in `src/tpv_ro_canary.v`); the predeclared win0 readout (counts <= ~1900
at all corners) cannot wrap under predicted conditions, and the `wrap_suspect`
flag of §2 catches violations of that assumption.

Extraction (period domain, matching the frozen "Ground truth" rule): after
both sweep directions and all repeats of one (corner, seg, pattern):

- `T_last_fail` = longest period at which the threshold was met,
- `T_first_pass` = shortest period at which it was not,
- boundary **bracket** = `[T_last_fail, T_first_pass]` (always reported; a
  bracket, not a point),
- `T_meas = (T_last_fail + T_first_pass) / 2`, `F_meas = 1000 / T_meas` [MHz],
- per-repeat brackets are recorded; the reported value is the median of the
  three repeat midpoints, with min–max as repeatability,
- if `T_last_fail > T_first_pass` (hysteresis exceeding the step), flag it,
  re-run the overlap region at dT/2, and keep all raw rows.

No err-rate interpolation is used; the bracket midpoint is the entire
estimator, so dT = 0.5 ns bounds the quantization to +/- 0.25 ns.

## 8. Pre-silicon freeze checklist

- [x] Measurement matrix, sweep steps, op counts, repeat policy (§1); raw CSV
      schema and prediction join keys (§2); instruments and uncertainty
      (§3–4); procedure incl. DFT gates, freeze-before-readout, anchor
      censoring fallback (§5); thresholds and bracket extraction (§7);
      provenance rules (§6) — all fixed.
- [x] This document committed **before any post-silicon measurement data
      exists**. Date of freeze: 2026-09-05. Branch: `proposal-canary`.
      Any later change requires a dated, committed protocol revision.
