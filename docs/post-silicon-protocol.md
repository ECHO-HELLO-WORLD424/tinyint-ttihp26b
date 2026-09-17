> The 10 MHz normal-operation candidate uses the same half-cycle protocol.
> Its regenerated build-specific data are in `data/safe10/`; `data/halfcycle/`
> retains the earlier build. The 10–50 MHz sweep is intentional experimental
> overclocking above the submitted timing-safe frequency, not a guarantee of
> error-free operation. See [verification attempts](ci-timing-closure-attempts.md).

# Predeclared post-silicon protocol v2

For half-cycle RTL on `proposal-canary` (merged from `proposal-canary-dev` on
2026-09-08), model `tpv-predict-2.0.0`.
Written before silicon outcomes. This supersedes v1's full-cycle aperture and
heated fallback anchor. Follow `docs/info.md` for pins and bytes.

## Measurement matrix and hardware

Begin at nominal 1.20 V and ambient near 25 °C. A temperature sweep is optional;
125 °C is a library corner, not a required operating point or a board rating.
Only add thermal points after checking assembly/fixture limits and defining a
sensor position, uncertainty and at least 10 minutes soak. A sensor near the
package measures package/ambient temperature, not junction temperature.

Verify board power topology before any core-voltage sweep. Never infer the
voltage limit from the three library corners alone. Hold the process interpretation
fixed for a given die; label comparisons to unmatched library PVT explicitly.

Use a low-jitter external clock or characterize the actual demo-board source.
Measure frequency, HIGH time and duty cycle at the board clock input. Nominal
measurement duty is 50%; record deviations and clock-path uncertainty. Maintain
an uninterrupted waveform through each launch-to-capture interval.

Run these tiers in order:

1. seg3333 × {worst, prbs} at nominal/ambient, including the nominal anchor.
2. {0000,1111,2222,3000,0003,2130,1203} × {worst,prbs} at each verified V/T point.
3. {alt,hold} controls at nominal/ambient, including 50 MHz.

Use selection 3/window 0; FORCE_ERR and FORCE_CAN are normally zero. The example
seg3333/worst word is 0x0DFF. First perform bring-up at 1 MHz with FORCE_CAN set;
canary counts can wrap at very low clock frequencies because their window is
clock-cycle based. For ordinary measurement use the 10–50 MHz range and check
telemetry for overflow risk. Boundary values below 10 MHz require a prospectively
recorded extension and separately validated canary windows.

The canary window is **one-shot per reset**: `win_done` clears only on `rst_n`, so
the ring runs for `(window cycles − 3)` external clock periods after reset release
(the three boot cycles before the configuration commits are not counted) and then
stops for the remainder of the run. With `win_sel=0` that is 253 periods —
25.3 µs at 10 MHz, 5.06 µs at 50 MHz. The canary sample is therefore taken in the
first 26 µs of a run that may last seconds; record it as a single sample per
configuration, not as continuous telemetry, and reset between measurement points.

## FREEZE interface contract (`ui[7]`)

`FREEZE` is sampled directly by the clock enables of `frame_cnt`, `ops_cnt`,
`err_cnt`, `win_cnt`/`win_done`, `started`, `capture_pending` and `ro_en`, with **no
synchronizer** (`src/tt_um_echoworld424_tpv.v`: `wire freeze = ui_in[7]; wire
update_en = ~freeze;`). The host therefore has to supply the edge alignment that
`src/pnr.sdc` already assumes when it constrains `ui_in[7]` with
`set_input_delay 4.0000 -clock clk`. Normative for this campaign:

1. Transition `FREEZE` — assert **and** release — during the clock **HIGH** phase
   (between a rising edge and the following falling edge). That always leaves between
   half and one full clock period of settling ahead of the edge that samples it:
   50–100 ns at 10 MHz, 10–20 ns at 50 MHz. Never transition it close to a rising edge.
2. If the host can only act in the clock LOW phase, the transition must still land at
   least 20 ns (10 MHz) or 10 ns (50 MHz) before the next rising edge, proven by the
   rule-4 scope check. Both floors exceed the 4 ns input-path budget in `pnr.sdc`, and
   the HIGH-phase rule meets them at every frequency in the 10–50 MHz sweep without
   per-frequency arithmetic. At 50 MHz the LOW phase is only 10 ns long, so the HIGH
   phase is the only comfortable window there. Keep the clock waveform uninterrupted
   across the transition (procedure step 6).
3. `FREEZE` must originate in the chip's clock domain: a host FPGA register or PIO
   clocked with `clk`, or equivalent hardware. **Do not drive it from an OS-scheduled
   software GPIO write** — no such write bounds its own jitter to a sub-100 ns window.
   The reference harness `fpga/tt_fpga_pico2ice.v` routes host GPIO `ui_cfg` straight
   to `ui[7]` in the run phase and synchronizes nothing, so compliance is the
   firmware's obligation, not the harness's.
4. Check rules 1–2 once per session on a scope: probe `clk` and `ui[7]`, confirm every
   FREEZE transition clears the applicable margin ahead of the following rising edge,
   and record `host_fw` and the check in the run notes.

Consequence, stated so it cannot be discovered after the fact: if a transition violates
rules 1–2, `update_en` can resolve differently per register on that edge. The frame
counter can then stop away from the frame/ops/err relationship the analysis assumes, and
`dut_err` can compare the held `result_reg` against a *new* operand pair and count a
**fabricated error** — the primary measured quantity.

- A nonzero error count on a configuration that the model and the `alt`/`hold` controls
  say is error-free is a **suspected freeze-transition artefact** until the rule-4
  scope check is on record for that run. Hold the raw record and re-run the point.
- If a host at some operating point cannot satisfy rules 1–3, that point is not
  measurable with FREEZE; record it as excluded with a reason code rather than
  reporting the count as data.
- The RTL regression and the `tools/emulator` host driver are **zero-delay functional**
  models: they exercise freeze semantics but do not model setup/hold, so passing them
  is not evidence that a host satisfies rules 1–2.

This settles finding F2 of the post-silicon readiness audit as the documented
host-contract option, not an RTL synchronizer. A two-flop synchronizer would add two
cycles of freeze latency, make the operation count at the freeze boundary
timing-dependent by one, and perturb when `ro_en` stops the ring — while `pnr.sdc`
already assumes a synchronous input. Do not add one without re-deciding this contract
and re-running the data packages it affects.

## Procedure

1. Record die/board identity, core voltage, sensor and clock measurements.
2. Assert reset and drive configuration. Release reset during the clock LOW
   phase with adequate recovery margin before the next rising edge. Hold pins
   stable through three complete rising edges after release (the configuration
   commits at the third), then release host uio drivers within the following
   clock period and drive ui[7] low. The chip takes over the uio bus on the
   fourth rising edge; holding the host drivers beyond it double-drives the
   pads, causing bus contention. Configuration is already latched at that point;
   subsequent uio values do not update it. Observe actual setup/hold constraints.
   Verify the committed word from the read-back echo (byte 8 = segment taps,
   byte 9 bits [3:0] = can_sel/win_sel) before trusting a measurement; note
   that pat_sel, FORCE_CAN and FORCE_ERR have no read-back path.
3. At 10 MHz, verify configuration echo, FORCE_ERR (errors = completed comparisons),
   FORCE_CAN (both canaries zero/dead), and ordinary zero-error operation.
4. Attempt the nominal seg3333/worst anchor. Coarse sweep at 10,15,20,25,30,35,
   40,45,50 MHz, up then down, at least 200 completed comparisons per point.
   Refine the transition with 0.5 ns period steps over a ±3 ns neighborhood.
5. Run three up/down repeats at 1e5 completed comparisons per fine point. At
   the four points bounding the transition, collect 3e6 comparisons for the
   1e-6 threshold. Split large counts into reset batches below counter saturation,
   preserving the fixed deterministic workload and recording every batch.
6. Set FREEZE high under the interface contract above — during the clock HIGH phase —
   then keep clocking for two full cycles. A launch
   accepted just before FREEZE completes its immediate falling-edge sample; no later
   sample replaces it. Read all 16 bytes only after this settling interval. Never stop
   the clock high inside an in-flight measurement aperture.
7. Check configuration/flags, append raw data, then resume or reset for the next
   point. Release FREEZE under the same contract. Freeze/resume does not create an
   additional timing capture.
8. Extract the anchor before looking at held-out boundaries. If no boundary is
   observable by 50 MHz, record right censoring and calibration unavailable.
   Do not heat the chip to force an anchor. Continue to preserve negative data.

One frame is 19 clocks. `ops_cnt` counts launches, including the initial pipeline
fill; while unsaturated, **completed comparisons = max(ops_cnt − 1, 0)**.
Error rates use completed comparisons, not launches. Both error and operation
counters saturate at 65535. Prefer batches with at most 60,000 completed comparisons
so both numerator and denominator remain exact. Large-N batches repeat the
configured deterministic sequence after reset; record this rather than claiming
independent random workload draws. The familiar 3/p observation count gives about
95% detection only under the corresponding independent-error assumption.

Canary counts are asynchronous ripple outputs. Read only after the loop has
stopped and settled. Counters wrap modulo 65536; no overflow flag exists. Record
suspected wrap, dead flags and exclusions. Normalize counts by measured clock
frequency before comparing with the model's 50 MHz reference-window predictions.
Do not treat zeros or a wrapped count as a slow canary.

## Immutable raw records

One append-only CSV per die. Minimum columns:

```
timestamp_utc,die_id,board_id,operator,host_sw,host_fw,clock_src,clock_cal,dmm_id,cfg_word_hex,seg0,seg1,seg2,seg3,pat_idx,pat_name,cansel,winsel,forcecan,forceerr,v_meas_mv,v_sense,t_meas_c,t_sensor,soak_min,f_meas_mhz,high_time_ns,duty_fraction,high_time_uncertainty_ns,sweep_dir,repeat_idx,batch_idx,sweep_phase,n_ops_chip,n_compared,ops_sat,err_cnt,err_sat,err_rate_per_op,err_seen,err_dut_b,cfg_echo_b8,stat_b9,gen_cnt,mat_cnt,gen_dead,mat_dead,wrap_suspect,frozen,build_commit,analysis_commit,model_version,notes
```

Append failures and anomalies too. Use separate derived datasets for normalization,
model joins, calibration and scoring. Hash raw files before applying predictors.
Do not map measured V/T to a nearest joint process corner without a mismatch label.

## Uncertainty and boundary reporting

Record frequency accuracy, period jitter, duty/high-time measurement accuracy,
board-to-tile duty distortion, voltage sensing point/accuracy, temperature sensor
placement/accuracy, soak time, count quantization and repeat variability. The
0.5 ns period grid at 50% duty gives a 0.25 ns aperture step; report bracket
endpoints rather than an unjustifiably precise point estimate. Clock uncertainty
already present in STA must not be added twice without an explicit accounting.

Report first-error and 1e-6/1e-4/1e-2 thresholds as brackets in HIGH time and
50%-equivalent frequency. Report all-pass/all-fail sweeps as censored. Exclude
non-path failures (configuration mismatch, bad hold control, unstable supply or
readout) with reason codes and keep their raw records. Thermal, voltage and
clock-path mismatches are limitations, not evidence of predictor error alone.
