# RTL freeze checklist

## Decision and scope

**Status: the gates are complete for the RTL question — the current RTL is the
freeze candidate, and no RTL change is required (2026-09-17). Seven
validation-tool defects were found and fixed, the corrected wire-capacitance
sensitivity run is complete, and the stop-phase coverage is measured rather than
assumed; the full `0xFFFF` wrap in SPICE is now measured too, so none of the
original coverage items is left open. See the [freeze record](#freeze-record).**

Reviewed source: `dbe8844` (analysis committed through `dd9d848`). Its RTL,
constraints and source lists are unchanged
from build commit `0a7cd5edd8cea7a45085898f84db403c93b25af0`, archived under
`artifacts/run-35034979531/`. This checklist supplements the
[readiness audit](post-silicon-readiness-audit.md); it qualifies the RO validation
completion claims using the latest review of the data and raw waveforms.

A 2026-09-17 reviewer pass re-tested this checklist's own evidence and found
**no new RTL defect**, but the validation tools did prove able to pass invalid
evidence or mis-report valid evidence. Seven defect classes were found and
fixed:
`add_wire_caps.py` emitted capacitor values without a SPICE scale suffix (10¹²
too large, which invalidated the wire-capacitance sensitivity decks);
`analyse_ro_count.py` accepted a counter bit stuck at mid-rail because it
checked transition timing but not the logic level at the readout deadline; and,
found while building the full-width wrap test, the same analyzer compared the
decoded 16-bit counter against the edge count without allowing for the counter's
wrap (so a *correct* wrapped run was reported as `mismatch`), computed
`f_count_from_counter_mhz` with an inverted scale, and derived that frequency
from the raw counter value instead of the reconstructed edge count. A second
review pass then found two more in the stop-phase tools: the stop-transient
classifier derived its pulses from the analyzer's 30 %→70 % hysteresis detector,
so a pulse peaking *below* 70 % of the rail raised no crossing and was invisible
to the classification (a 0.6 V pulse on a 1.2 V rail produced `n_runt=0`), and
the counter-derived frequency's comment and flag claimed the whole counting
interval while the code divided by the first-to-last edge span, leaving the field
convention ambiguous. All seven are fixed, covered by fixtures and re-checked
against the archived waveforms
(`data/safe10/freeze/analyzer_recheck.json`,
`data/safe10/count/analyzer_fixtures.json`,
`data/safe10/freeze/stop_transient_fixtures.json`); the claims that rested on
them are withdrawn in place rather than deleted.

The last three were latent — they cannot be triggered below 65 536 edges, which
is why the existing 64 archived records and the fixture suite passed over them —
and were only exposed by building the full-width wrap test that gate 3 had left
unclaimed.

No new RTL defect was demonstrated in that review. The remaining evidence did
not establish that the default matched canary behaves predictably over the
actual measurement window; that was resolved by gates 1–3
([`rtl-freeze-validation.md`](rtl-freeze-validation.md)), which measured the
canary with a deck that models the real reset → boot → window → readout
sequence. **Result: the matched canary is single-valued and its count decodes
exactly against the independently counted ring edges at every corner and both
host clocks, including the four configurations that were previously flagged as
multi-mode. No RTL change is required.** What remains open is validation
coverage, not RTL behaviour: the full `0xFFFF` counter wrap in SPICE. The
stop-phase question was closed by measurement in the same session — see gate 3.

Already verified during the review:

- RTL regression: 14 passed (re-run 2026-09-17). **Re-run again in this extended
  session**: `make` in `test/` inside the devcontainer → 14 tests, 14 pass, 0
  fail, 0 skip, including `test_ro_ripple_counter_wrap`.
- Functional GL on the archived netlist: 10 passed, 4 intentional skips
  (re-run 2026-09-17). **Re-run again in this extended session**:
  `make GATES=yes` → 14 tests, 10 pass, 0 fail, 4 skip (the RO-dependent
  cases, stripped for zero-delay GL).
- Bidirectional UIO handoff test: passed at 10 MHz.
- Physical structure: 384 DUT bank inverters and taps, two closed RO loops,
  17 falling-edge capture registers.
- Canonical CI: GDS, precheck, GL and viewer passed for run `35034979531`.
- Archived signoff: setup/hold clean at all three corners; DRC/LVS/antenna and
  power-grid checks clean. See [the manifest](../artifacts/run-35034979531/MANIFEST.md).

**Preserve the settled design contracts.** Keep the third-edge configuration
capture/fourth-edge UIO handoff, one-shot falling-edge DUT capture, 19-cycle
frame and documented host-synchronous FREEZE contract. Do not add a FREEZE
synchronizer or redesign the RO based only on an ambiguous simulation result.
FPGA validation is outside this checklist while the board is disconnected.

## Execution order

| Gate | Work | Required evidence | RTL change needed? | Verdict |
| --- | --- | --- | --- | --- |
| 1 | Make RO measurements and acceptance checks trustworthy | Analyzer fixtures, explicit coverage/failure statuses | No | **Pass** (readout-level check + `midrail_level` fixture added 2026-09-17) |
| 2 | Resolve default matched-canary startup and window behavior | Current-build transient waveforms and repeatable edge-count results | Only if the result demonstrates a circuit problem | **Pass** — window/count evidence stands, and the corrected lumped wire-capacitance run bounds the RC omission (8–10 % period, count exact); distributed RC remains open work |
| 3 | Exercise upper counter carries and stop/readout | Per-bit coverage and stopped-count checks | Only if a counter defect is demonstrated | **Pass** for stages 0–15, `0x7FFF→0x8000` and the full `0xFFFF` wrap (65 715 edges, `counter_final=179`, 0 circular error); **stop-phase coverage measured** (30 archived phases + 12-phase targeted sweep, 0 runt pulses) |
| 4 | Include all pattern-state launch registers in STA | Complete launch list, regenerated reports and predictions | No | **Pass** |
| 5 | Reconcile the final package and record freeze | Consistent docs, hashes, test results and final decision | Depends on gates 2–3 | **Corrected 2026-09-17 and extended**: hashes match; the RC run is complete, and both previous coverage restrictions (stop-phase sweep, full `0xFFFF` wrap) are now measured rather than documented |

Run HDL, STA and SPICE work in the devcontainer. Keep new decks, rawfiles and
logs under a separate ignored directory such as `runs/freeze-validation/`.
Archive a small machine-readable summary and hashes under a deliberate dataset
directory. Preserve failed runs and superseded datasets with their identities.
(`runs/freeze-validation/` holds the decks, rawfiles and logs; the analysis
JSONs, tables and hashes are archived in `data/safe10/freeze/`.)

## Gate 1 — Correct RO analysis and acceptance logic

Relevant tools:
`tools/ro/analyse_ro_count.py`, `tools/ro/analyse_ro_intervals.py`,
`tools/ro/run_ro_count_case.py`, `tools/ro/sweep_ro_count.py`.

**Status: complete (2026-09-17).** `analyse_ro_count.py` was rewritten around the
window the hardware actually uses. Evidence:
`data/safe10/count/analyzer_fixtures.json`,
`data/safe10/freeze/PREDECLARED-TOLERANCE.md`.

### Actions

- [x] Define measurement boundaries from the actual reset/enable/window controls,
  not from the counter's first and last transitions. The window deck
  (`run_ro_count_case.run_window`) drives `rst_n` and `en` with explicit PWL
  waveforms and saves them through zero-volt sense branches (`sense_rst_n`,
  `sense_en`), and the analyzer derives `t_count_start = max(rst release, gate
  rise)` from those waveforms. The recorded reset-release time is now used to
  bound the counting window; a run whose gate never closes is reported as
  `window_mode=open_to_end` rather than silently treated as a closed window.
- [x] Count all qualified rising edges during the declared gate-open interval.
  `ring_edges_in_window` counts every rising edge of the counter's clock net
  after the window opens, including the loop's stop transient, and
  `f_count_mhz = edges / elapsed` is reported with the boundary uncertainty
  (`edge_ambiguity_edges`, derived per case from the measured `en` transition
  and the ring period). Startup and steady-state statistics are separate fields
  (`pre_window_edges`, `startup_window_edges`, `steady_period_ns`,
  `steady_std_over_mean`, `steady_n_modes`).
- [x] Require all 16 saved counter bits and verify settled logic levels before
  decoding. Fewer than 16 saved bits gives `missing_bits`; a bit still
  transitioning at the decode point gives `unsettled` (which now takes priority
  over the count comparison, because a mid-ripple decode invalidates the count).
- [x] Require a **valid logic level** at the readout deadline, not merely a quiet
  one. The 50 % decode threshold on its own classifies a stuck mid-rail node
  (0.6 V on a 1.2 V rail) as a logic 0, so a fixture built that way returned
  `settled=True`, `count_ok=True` and was accepted. `analyse_ro_count.py` now
  reports per-bit `level_valid` and `invalid_level_bits`, refuses to call a case
  `settled` unless every bit is within 15 %/85 % of its rail at the decode point,
  returns the status `invalid_level`, and `accepted()` rejects it. The
  `midrail_level` fixture (bit 15 quiet at 0.6 V) is expected to fail for exactly
  that reason, and all 64 archived waveform records were re-checked against the
  pre-fix analyzer revision: every bit is at a rail and no verdict changes
  (`data/safe10/freeze/analyzer_recheck.json`).
- [x] Make the count verdict wrap-aware, and the counter-derived frequency
  correct, before testing the full-width wrap. Two further analyzer defects were
  found and fixed in the same session, both of which only affect runs that reach
  the 16-bit boundary — which is exactly the case gate 3's full-width wrap needs:
  * **`count_ok` compared the decoded counter against the edge count directly.**
    A 16-bit counter can only ever display `edges % 65536`, so a *correct* run
    that wrapped was reported as `mismatch` (it would have reported
    `counter_final=1000` against 66 536 edges as an error). The verdict now uses
    the circular distance on the 16-bit ring (`count_error_circular`) and reports
    `count_aliased`; `count_error_edges` keeps its raw unwrapped meaning for
    continuity. The `freq_wrap` fixture (66 536 edges, `counter_final=1000`,
    `wraps=1`) now passes and fails under the pre-fix comparison.
  * **`f_count_from_counter_mhz` was scaled the wrong way** (`* 1e-6` where a
    seconds→microseconds division by `1e-6` was meant, a 2×10¹² error) **and used
    the raw counter value**, so it inflated without bound once the counter
    wrapped. It now reconstructs the edge count as `final + wraps*65536` with the
    wrap count that matches the independently measured edges, and reports both.
    The `freq_units` (20 000 edges) and `freq_wrap` fixtures assert the value to
    1 %; the archived `0x7FFF→0x8000` carry run re-analyses to 1190.511 MHz
    against 1190.476 MHz from the edge span, where the old expression produced an
    unbounded number.
  The fixture's own synthetic counter also had to model the wrap (its upper stage
  was left at the unwrapped level), which is what makes `freq_wrap` a real
  16-bit test rather than a 17-bit one.
- [x] Fix the stop-transient classifier's detection floor, which the second
  review pass exposed. `classify_stop_transient.py` derived pulses from
  `analyse_ro_count.rise_edges`, whose hysteresis band is 30 %→70 % of the rail,
  so a pulse peaking between 30 % and 70 % raised **no crossing at all** and
  contributed nothing to `n_runt` — precisely the marginal pulse the tool exists
  to find. It now scans for excursions above a 15 % floor and classifies each by
  its measured peak, and it reports `pulses_straddling_close` separately from
  `crossings_after_close` so a pulse that begins before the gate closes and is
  still high at the close is not confused with an extra edge. Covered by
  `tools/ro/test_classify_stop_transient.py`
  (`data/safe10/freeze/stop_transient_fixtures.json`, 6 fixtures): a 50 % and a
  75 % pulse are both caught as runts (the pre-fix detector reported 0 for
  both), a 10 % level stays excluded by design, and a truncated pulse at the
  gate close is counted as a runt that straddles the close with no post-close
  edge. Re-running the corrected tool over the archive and the sweep changes
  nothing: **73 343 crossings in the 42 archived cases and 251 in the 12-phase
  sweep, 0 runts, 0 sub-threshold glitches, 0 crossings after close** — the
  earlier conclusion holds under a detector that sees pulses down to 15 % of the
  rail instead of 70 %.
- [x] State the frequency-field interval convention explicitly instead of
  leaving it to a comment. `f_count_from_counter_mhz`, `f_count_mhz` and
  `f_steady_mhz` all use the offered-edge span (the first divides the
  reconstructed count by it, the other two measure `edges-1` intervals over the
  same span), which is the estimator without the half-period sampling bias. The
  declared gate-open duration is now reported separately as `count_window_ns`
  with its own quotient `f_count_over_window_mhz`, defined **only** for a single
  contiguous window (`n_en_rise <= 1`, `n_reset_releases <= 1`, gate closed
  within the run) because `t_en_fall − t_en_rise` spans the paused intervals of a
  FREEZE case; `f_count_over_window_defined` says whether it applies. The
  `short_window` fixture pins both to the interval each declares and requires them
  to differ by more than 2 % so a silent change of convention fails the suite.
- [x] Replace the permissive ripple-rate check with explicit per-bit coverage:
  `per_bit_coverage[b] = {expected, observed, exercised, rate_ok,
  last_transition_ns}`, and `coverage_complete` requires every stage to have
  been *exercised* and to run at its binary-carry rate. An unexercised upper
  stage yields `ok_partial_coverage`, never `ok`.
- [x] Define how period-estimate disagreement affects acceptance. The count
  comparison (`count_ok`) and the frequency claim (`rate_stable`, plus
  `rate_detail`) are separate booleans; the status vocabulary distinguishes
  `ok`, `ok_partial_coverage`, `ok_unstable_rate` and
  `ok_partial_coverage_unstable_rate` from
  `mismatch`/`unsettled`/`invalid_level`/`missing_bits`.
- [x] Fix interval classification: `analyse_ro_intervals.classify()` returns
  `unclassified` when no histogram cluster is found (and `too_few_edges` when
  there is not enough data), and `single_mode` now requires one detected cluster.
- [x] Add fixtures for known-good binary counting, missing edges, missing bits,
  unexercised upper stages, reset transitions, unstable periods, incomplete
  ripple settling, a mid-rail readout level, and the counter-derived frequency
  both below and across the 16-bit wrap — plus no-oscillation and
  missing-gate-waveform cases. Each fixture is checked for both its returned
  status and the process exit code by `tools/ro/test_analyse_ro_count.py`, and
  the two frequency fixtures additionally assert the value to 1 %, and a
  `short_window` fixture pins the two frequency-interval conventions
  (13 fixtures + 4 interval-classifier cases, all behaving as declared; the
  harness's quadratic wave-table lookup was also fixed, so the suite now
  completes in seconds instead of being abandoned as too slow. `freq_wrap` is
  the only fixture that makes the analyzer's synthetic counter wrap, and it is
  what caught the `count_ok` and frequency defects recorded under gate 1).
- [x] Make sweep failures propagate to a nonzero exit status, and forward the
  requested simulation duration: `sweep_ro_count.py` now passes
  `--tstop-cap-ns` through to the free-running deck, sizes that deck from a
  measured period hint, runs the analyzer on both decks, and exits non-zero when
  any case is not accepted.

### Pass criteria

Met: known-bad fixtures fail for the expected reasons, untested behaviour is
reported as untested (`ok_partial_coverage`, `unclassified`), and no row is
accepted solely because its frequency resembles an older dataset — acceptance is
decided per case from the waveforms in that case's own rawfile.

## Gate 2 — Resolve the default matched-canary behavior

### Evidence requiring resolution

`data/safe10/spice/spice_ro.csv` retains revision-2 frequency values for four
cases: matched RO, selections 2 and 3, typical and slow corners. The new
waveforms are flagged as unstable, yet the rows retain `status=ok` and current
build provenance. See the [regeneration record](../data/safe10/count/FOSC-REGEN-STATUS.md).

For slow/matched/selection 3, independent reanalysis of the stored new rawfile
found intervals of 1.32–6.82 ns (mean 3.446 ns), whereas the table retains
14.545 ns / 68.754 MHz. This does not prove a silicon fault; it does mean that
the retained number is not a measurement of that new waveform.

**Status: resolved (2026-09-17), including the wire-RC sensitivity half after
its generator defect was fixed.** The window deck (reset → boot → gate open →
gate close → settle → readout, with the boundaries taken from the RTL) measures
those configurations as **single-valued** at every corner, with the count
decoding exactly against the independently counted ring edges, and reproduces
the f_osc dataset within 0.6 %. Full evidence and the timestep ladder:
[`rtl-freeze-validation.md`](rtl-freeze-validation.md); the invalid
revision-1 wire-capacitance injection and its corrected re-run are described
under Actions below.

### Actions

- [x] Re-extract from the final build with the full counter, toggle feedback,
  reset tree and real output loading. `tools/ro/extract_ro_loop.py --counter`
  re-run against the archived Magic spiceextraction reproduces all eight loop
  subcircuits byte-identically (`runs/freeze-validation/reloops/`). Structural
  control roles, tap-mux reach and loop-node identity are re-checked on every
  deck, and an unknown role is rejected rather than driven to 0 V.
- [x] Model the real sequence: reset asserted, configuration stable, reset
  released, boot gating, RO enabled, measurement window closed, ripple settled,
  then readout. The window deck solves its operating point with reset asserted
  and the gate closed (no arbitrary `.ic`), releases reset with a real edge,
  opens the gate three clock periods later, closes it after 253 periods, and
  runs on for the two-clock readout interval so the stopped count is inside the
  waveform.
- [x] Start with both canaries at `can_sel=3`, `win_sel=0`, all three library
  corners and external clocks of 10 and 50 MHz. The 50 MHz arm covers all six
  configurations with three startups each; the 10 MHz arm covers the three
  configurations that carry the decision (matched canary at the typical and slow
  corners, generic canary at typical) with one startup each — the remaining
  ten-MHz cases are a coverage extension, not an open question, and the deviation
  is recorded in the validation record. The four previously unstable matched
  configurations are covered at `can_sel=3` (both clocks) and `can_sel=2`
  (matrix at 50 MHz).
- [x] Simulate the complete effective gate-open interval, not 20–75 ring edges.
  The interval is derived from the RTL boot/window sequence by
  `tools/ro/probe_ro_window.py` (gate opens at clock cycle 4, closes at cycle
  257 ⇒ 253 periods: 25.3 µs at 10 MHz, 5.06 µs at 50 MHz) and the deck's `en`
  waveform is generated from those numbers.
- [x] Use physically consistent initialization and repeat startup with distinct
  reset/enable timings. Three release phases per primary case; the result is
  that the deck is deterministic and the count is exactly repeatable, which is
  recorded as a property of the model (and of the chip's synchronous gate
  timing), with silicon startup jitter left to the campaign.
- [x] Check timestep convergence and extend the run until the measured count and
  rate are stable. 2/5/10/20/40 ps are compared at fixed 1 µs windows on the
  fastest, slowest, generic and matched canaries; the bulk runs use **10 ps**,
  the coarsest step inside the predeclared 1 % band (−0.20 % … −0.91 % against
  5 ps; 2 ps is +0.06 % … +0.27 % above 5 ps; 20 ps and 40 ps are outside).
- [x] Include extracted wire RC where feasible, and otherwise label the
  limitation. It is measured from the SPEF (399 fF over 119 nets for `ro_gen`,
  549 fF over 231 for `ro_mat`). An injection run was attempted and **failed for
  a generator defect, not for a circuit reason**: `add_wire_caps.py` wrote the
  capacitance in pF without a SPICE scale suffix, and an unsuffixed capacitor
  value is in farads, so every injected capacitor was **10¹² times** too large
  (1 fF became `0.001`, i.e. 1 mF) and the loop stalled. The revision-1 result
  and its "structural, not a magnitude effect" explanation are therefore
  withdrawn. The generator now emits the `p` suffix and
  `tools/ro/test_add_wire_caps.py` round-trips every emitted capacitor to
  farads. **The corrected run is complete**
  (`data/safe10/freeze/wirecap_sensitivity_corrected.json`, 400 ns window,
  5 ps, 8/8 cases accepted, single mode, count exact): the full extracted
  lumped capacitance costs 8.31–10.07 % of ring frequency (`ro_gen` typical
  825.31 → 742.18 MHz, `ro_mat` typical 108.50 → 99.48 MHz, `ro_gen` fast
  1246.57 → 1124.99 MHz, `ro_mat` slow 68.51 → 62.67 MHz), and the
  capacitance-free baselines reproduce the independent f_osc dataset within
  0.4–0.9 %. The omission is therefore bounded by simulation at the lumped
  level and remains a period effect, not a counter effect. A distributed-RC
  deck is still open work and the absolute frequencies remain cell-level
  transient results. The counting conclusion never depended on this — no window
  run was accepted without its own waveform evidence.
- [x] Predeclare a count-repeatability/convergence tolerance before judging the
  reruns. `data/safe10/freeze/PREDECLARED-TOLERANCE.md` was written while the
  sweep was still running: agreement within the larger of 1 % or the derived
  edge-quantization bound, plus the settling/readout rule.

### Pass criteria and decision

Met, with the wire-RC limitation measured rather than argued. Every primary case has a defensible edge-count prediction for its
actual window: the decoded count equals the independently measured ring-edge
count in all accepted cases, startup repeatability is exact (0 % spread), the
timestep and gate-boundary uncertainties are quantified, the stopped readout is
verified settled before the gate closes, and the four configurations under
suspicion are single-valued. No RTL change is indicated by this gate. The
revision-1 sensitivity decks that were used to argue the omission away were
invalid (see the wire-RC action above); the corrected re-run now measures the
effect at 8–10 % of ring frequency with the count still exact, so the remaining
qualification is the lumped (not distributed-RC) nature of the deck, not an
unmeasured omission.

## Gate 3 — Validate counter carries and stop–settle–read behavior

The committed 22 count cases finish at counts of 18–74. In the independently
checked 74-count waveform, bits 7–15 only transition during startup. This does
not validate the full 16-stage ripple under counting conditions.

**Status: complete, including the full-width wrap and stop-phase coverage.** Evidence:
`data/safe10/freeze/carry.json`, `control.json`, `matrix_windows.csv`,
`coverage.csv`, `wrap_result.json`, `stop_phase_coverage.json`,
`stop_phase_sweep.json` and the settle fields of `primary_windows.csv`
(`docs/rtl-freeze-validation.md`).

### Actions

- [x] Check case completeness against the declared matrix. The 24-case
  (3 corners × 2 canaries × 4 `can_sel`) matrix is now measured at 50 MHz in
  `matrix_windows.csv`, together with the `can_sel=3` window runs.
- [x] Observe post-reset carries through every stage. A targeted extended-gate
  run at the fast corner with the shortest ring (`ro_gen`, `can_sel=0`) offers
  34 524 ring edges and the counter decodes 34 524 with **zero** error; every
  stage's toggle count equals its binary-carry rate (bit 15 toggles exactly
  once), so the `0x7FFF → 0x8000` carry is covered. It is labelled a carry test,
  not a window test.
- [x] Cross the full `0xFFFF → 0x0000` wrap in SPICE. The same configuration
  was run with the gate open for 55.2 µs (20 ps step, 3.1 h wall) so that the
  offered edge count exceeds 65536 (`data/safe10/freeze/wrap_result.json`):
  **65 715 offered edges, decoded `counter_final = 179` (0xb3), one wrap
  inferred, reconstructed edges 179 + 65536 = 65 715, circular error 0.** Every
  one of the 16 stages is exercised and at its binary-carry rate (bit 15
  toggles twice), the ripple settles before the decode point, all bits are at a
  rail, and the ring is single-mode at 1190.476 MHz with a 0.840 ns period — so
  the wrap is now measured, not inferred from the sub-wrap run. Note that this
  run is what exposed the `count_ok` and frequency defects recorded under gate
  1: the pre-fix analyzer reported this correct run as `mismatch` with a
  frequency inflated by the wrap count (3.2×10¹² MHz), and the archived record
  was regenerated with the fixed tool rather than re-simulated.
- [x] Exercise the extracted first stage at the fastest supported ring rate
  (1.19 GHz in that run, the fastest configuration in the design); the slow
  corner is covered by the slow-corner window runs, where the measured
  per-stage ripple delay is largest.
- [x] Close the RO enable at multiple phases of its oscillation, and keep
  counting final qualified pulses until the loop has physically stopped. The
  analysis counts every rising edge of the counter's clock net after the window
  opens, including the loop's stop transient. The phase half is now
  **measured**, not argued, in two steps:
  * *What the archived runs already cover.* `tools/ro/measure_stop_phase.py`
    reads the ring waveform and the `en` waveform out of every archived window
    rawfile and reports the phase at gate close
    (`((t_en_fall − t_last_edge) mod period)/period`). Across all 42 archived
    window cases (`data/safe10/freeze/stop_phase_coverage.json`) the stop phase
    takes **30 distinct values spanning 0.091–0.983, a spread of 0.892 of a
    period**. The docs' original reasoning is confirmed exactly: within a
    configuration the three "startup phases" close the gate at the *same* ring
    phase (spread 0.0000 in every three-startup group, because `en` rise→fall is
    a fixed number of ring periods and the ring is gated off between them), so
    the phase spread comes from the host clock period and the `can_sel` tap, not
    from `release_phase`.
  * *What the stop transient does.* `tools/ro/classify_stop_transient.py`
    classifies every excursion above a 15 % floor of the rail by its measured
    peak (full ≥ 85 %, runt 15–85 %, below the floor excluded by design, since a
    level below 15 % cannot switch an input whose threshold is near mid-rail).
    **The floor matters:** the first revision reused the analyzer's 30 %→70 %
    hysteresis detector, which raises no crossing for a pulse peaking below
    70 %, so a genuinely marginal pulse was invisible to the classification —
    the second review pass caught this and it is fixed (see gate 1). Across
    **73 343 excursions in those 42 cases there are 0 runt pulses and 0
    sub-threshold glitches**, and 0 crossings after the gate closes: the gated
    loop stops cleanly at every phase tested, so the "marginal-width clock
    pulse as `en` falls" that this gate named is not merely uncounted, it does
    not occur. The last pulse before the gate closes is a full-amplitude pulse
    in every case (peaks 1.01–1.05× the rail from the loop's own overshoot), and
    in no case does a pulse begin after the close (18 of the 42 do straddle it,
    which is the ring still running as the gate shuts, not an extra edge).
  * *Targeted sweep.* `tools/ro/sweep_stop_phase.py` places `en` fall at
    `periods + phase` ring periods after `en` rise, so the stop phase is swept
    directly rather than through the host clock (which can only reach the
    phases the clock period happens to give). **12 phases, 0.069–0.986, all
    accepted** (`data/safe10/freeze/stop_phase_sweep.json`): every case decodes
    its exact ring-edge count (20–21 edges over a 40-period slow-corner window),
    settles, and holds valid levels, with 0 crossings after the gate closes.
  The ±1-edge gate-boundary ambiguity still covers *which* edges are inside the
  window; the amplitude classification covers runt-pulse capture.
- [x] Measure the time until all counter bits settle and compare it with the
  protocol's readout interval. In every completed window case the last counter
  bit transition happens **before** the gate closes (settle = −0.17 to −0.21 ns);
  the measured per-stage ripple delay is 0.135–0.139 ns, i.e. a 15-stage ripple
  needs ≈ 2.1 ns, an order of magnitude inside the 40 ns (50 MHz) and 200 ns
  (10 MHz) two-clock readout intervals. The count is verified unchanged at the
  decode point (all 16 bits settled, none unsettled).
- [x] Cover reset, FORCE_CAN and freeze/resume during an unfinished window. With
  `FORCE_CAN` raised mid-window the loop stalls and the counter holds the 574
  edges offered before the stall; with `FREEZE` the gate closes, the counter
  holds, and counting resumes (892 edges = 892 count); with reset asserted
  mid-window the counter is cleared and restarts (the analysis opens the counting
  window at the *last* reset release, 1047 edges = 1047 count). The host FREEZE
  contract is unchanged.

### Pass criteria

Met for every claim on this gate, with no restriction left. All claimed stages have explicit post-reset or targeted carry
coverage; the settled count matches the independently observed accepted ring
edges exactly (0 error in the carry run, 0 error in every window case, 0 error
in all 12 stop-phase sweep cases); the ±1-edge gate-boundary ambiguity is derived
per case (`edge_ambiguity_edges`) rather than used as a blanket tolerance; and
ripple settling fits the readout contract by more than an order of magnitude.
The stop phase is now measured rather than assumed: 30 distinct phases are
already covered by the archived waveforms and 12 more were swept directly, and
in all 54 of those cases the stop transient contains **no** marginal-width
pulse (73 343 crossings classified, 0 runts, 0 sub-threshold glitches, 0
crossings after the gate closes). What the gate still does **not** establish is
behaviour beyond the phases tested and beyond the cell-level deck — the stop
transient is shown clean at every phase measured, not proved clean for all
phases analytically.

## Gate 4 — Complete experiment-STA launch coverage

`tools/sta/experiment_sta.tcl` currently discovers 10 launch pins by retained
net names although the pattern generator contains 18 state flops. Renamed LFSR
outputs are omitted. Current seg3333/PRBS restricted versus unrestricted
case-analyzed slack differs by 0.03/0.06/0.09 ns at fast/typical/slow corners.

**Status: complete (2026-09-17).** The launch set is now resolved structurally
inside OpenSTA (32 preserved full-adder operand nets → backward fan-in cone →
sequential cells, minus the two case-analyzed `cfg[8]/cfg[9]` registers = 18
pins), with abort-on-failure assertions for the count, uniqueness, cell type,
shift-chain/counter structure, feedback taps and name agreement. Evidence:
`data/safe10/experiment_sta_launch_pins.json`, the regenerated
`data/safe10/sta_report_*.txt` / `experiment_sta.csv` / `predict/`, the
independent re-checker `tools/sta/verify_launch_coverage.py` (all checks pass)
and `docs/experiment-sta-launch-coverage.md`.

### Actions

- [x] Identify all 16 LFSR and two index flops through synthesis source mapping
  and connectivity, not only `*u_pat.lfsr*` / `*u_pat.idx*` net names. Ten pins
  keep synthesis names; the eight renamed ones (LFSR bits 0, 5, 6, 7, 10, 11,
  13, 15) are recovered by the structural walk.
- [x] Assert the expected launch-register count and uniqueness; retain the
  existing check for 17 capture endpoints. The resolved pin list is written to
  `data/safe10/experiment_sta_launch_pins.json` with the netlist/SPEF/Tcl
  hashes it was resolved against.
- [x] Rerun the full 96-case extracted STA matrix against the final
  netlist/SPEF. Every previously worse unrestricted capture path is classified:
  72 runtime state (`_1380_` lfsr13 on PRBS, `_1383_` idx0 on WORST/ALT),
  24 control (`_1334_` `capture_pending` on the hold rows, which have no runtime
  path), 0 static configuration. After the fix no case has an unrestricted path
  worse than the runtime path.
- [x] Check changed critical paths against sensitizing transitions. Each row
  records the previous and current operand vectors, the operation index and the
  exercised carry chain; 72/72 runtime rows are verified against an operand
  transition whose changed bits intersect the launch flop's operand fan-out.
  SDF limitations are retained explicitly (IOPATH only, no interconnect, timing
  checks stripped, RO loops masked; STA stays conservative by +1.06/+1.10/+2.98 ns).
- [x] Regenerate affected predictions and verify formulas/units against the raw
  reports. 72 of 288 prediction rows changed (the 24 PRBS cases × 3 predictors,
  0.08–1.40 MHz earlier). Oracle/control margin stays positive in all 96 cases
  (`control_slack_ns` ≥ 5.740 ns). No signoff exception was altered.

### Pass criteria

Met: all runtime pattern-state sources are included, the omitted-path
discrepancy is resolved (seg3333/PRBS restricted-versus-unrestricted slack gap
−0.030/−0.060/−0.090 ns → 0.000 at fast/typical/slow), and every prediction
change is traceable to the regenerated raw reports and build hashes.

## Gate 5 — Reconcile the package and declare freeze

- [x] Update the counter and frequency validation records to distinguish
  oscillation, stable edge-rate prediction, lower-stage counting, full carry
  coverage and stop/readout validation. `docs/ro-counter-spice-validation.md`
  now carries that table and marks its revision-1 free-running dataset as
  superseded for window behaviour; `docs/data-dictionary.md` describes both the
  revision-1 dataset and the new `data/safe10/freeze/` archive; case counts and
  the stale "blocked" f_osc statement are replaced with the gate 1–4 results.
- [x] Correct datasheet terminology: `docs/info.md` now states that RO telemetry
  is one-shot per reset and gives the effective gate-open interval
  (`window cycles − 3` clock periods), and the byte map says that completed
  comparisons are `max(ops_cnt − 1, 0)` before saturation;
  `docs/post-silicon-protocol.md` repeats the one-shot/window-duration facts and
  the overflow restriction.
- [x] Retain the host FREEZE timing contract and record board clock, voltage and
  thermal qualification as campaign obligations (they are unchanged and are not
  evidence of an RTL failure).
- [x] If RTL, cell wrappers, constraints, source lists or floorplan changed,
  perform fresh hardening. **They did not change**: `git diff 0a7cd5e..HEAD --
  src info.yaml` is empty, so the archived `0a7cd5e` physical evidence and CI run
  `35034979531` still describe this design. Only tools, docs and datasets changed.
- [x] If only analysis/docs changed, verify the design inputs still match the
  archived build. Hashes of `src/*.v`, `src/config.json`, `src/pnr.sdc`,
  `info.yaml`, the archived netlist and the archived SPEF are recorded in
  `data/safe10/freeze/manifest.json` under `build_inputs`.
- [x] Record netlist, GDS, SPEF, extracted SPICE, libraries, models, decks and
  analysis-script hashes. `manifest.json` records the archived datasets, the
  analysis tools (including `tools/verify_freeze.sh`) and the decks each case was
  run from; the raw waveforms stay under `runs/freeze-validation/` (ignored) and
  are reproducible from those decks — that size limit is stated rather than
  hidden.
- [x] Inspect regression XML, not only make exit status. RTL: 14/14 pass
  (`test/results.xml`, re-run 2026-09-17). Functional gate-level on the archived
  netlist: 10 pass / 4 explained skips. The pad-hand-off test
  (`test_uio_oe_handoff`) passes in both. Physical checks are the archived
  build's (DRC/LVS/antenna/power-grid clean, setup/hold clean at all three
  corners). FPGA validation remains explicitly unrun.
- [x] Record the final decision below.
- [x] Correct the record after the 2026-09-17 reviewer pass: the analysis work
  the freeze record described as uncommitted is committed, two validation-tool
  defects found in that pass are fixed and covered by fixtures (capacitor units
  in `add_wire_caps.py`; readout-level validity in `analyse_ro_count.py`), the
  invalidated wire-RC injection is re-run and measured, and the freeze record is
  corrected in place.
- [x] Close the stop-phase item with measurement instead of documentation:
  `tools/ro/measure_stop_phase.py` and `tools/ro/classify_stop_transient.py`
  derive the phase at gate close and the stop-transient amplitude from every
  archived waveform (42 cases, 30 distinct phases, 73 343 crossings, 0 runts,
  0 crossings after close), and the new targeted
  `tools/ro/sweep_stop_phase.py` sweeps 12 further phases directly
  (`data/safe10/freeze/stop_phase_coverage.json`,
  `data/safe10/freeze/stop_phase_sweep.json`). Two further analyzer defects that
  the full-width wrap test exposed — `count_ok` not wrap-aware, and the
  counter-derived frequency's inverted scale and use of the raw wrapped value —
  are fixed with `freq_units` and `freq_wrap` fixtures. The full `0xFFFF` wrap in
  SPICE is then measured on the same configuration (65 715 edges, decoded 179).

### Freeze record

| Field | Value |
| --- | --- |
| Frozen RTL/build commit and canonical CI run | RTL, constraints and source lists at `0a7cd5e` (`src/` and `info.yaml` unchanged through `dd9d848` and this correction); canonical CI run `35034979531` (gds + precheck + gl_test + viewer green), archived as `artifacts/run-35034979531/` |
| Analysis commit and dataset versions | analysis committed on top of `dbe8844` in `f4ff5f5` (analyzer + fixtures, gate 1), `cd16f58` (window decks, gates 2–3), `b83dc35` (freeze dataset), `41f7e44` (gate 4 launch coverage), `247dc28` (gate 5 reconciliation) and `dd9d848` (manifest tool keys); the 2026-09-17 reviewer corrections (tool fixes, fixtures, rechecks, docs) are the commit that carries this record. Datasets: window-deck revision 1 (`data/safe10/freeze/`), analyzer fixtures (12, including the mid-rail and the two wrap/frequency cases) + `data/safe10/freeze/analyzer_recheck.json` (64 archived waveform records re-checked) + `data/safe10/freeze/wirecap_generation_fixture.json` + `data/safe10/freeze/stop_phase_coverage.json` (42 cases) + `data/safe10/freeze/stop_phase_sweep.json` (12 phases), experiment-STA launch pins + regenerated `data/safe10/experiment_sta.*` and `data/safe10/predict/*`; f_osc dataset revision 3 unchanged |
| Gates 1–4 evidence links and verdicts | G1 **pass** (`data/safe10/count/analyzer_fixtures.json`, now including the mid-rail readout fixture and the wrap/frequency regressions); G2 **pass**, including the corrected lumped wire-capacitance sensitivity run (`data/safe10/freeze/wirecap_sensitivity_corrected.json`, `docs/rtl-freeze-validation.md`); G3 **pass for stages 0–15, `0x7FFF→0x8000` and the full `0xFFFF` wrap (65 715 edges, decoded 179, 0 circular error), with stop-phase coverage measured (30 archived phases + a 12-phase targeted sweep, 0 runt pulses)** (`data/safe10/freeze/carry.json`, `wrap_result.json`, `control.json`, `matrix_windows.csv`, `stop_phase_coverage.json`, `stop_phase_sweep.json`); G4 **pass** (`data/safe10/experiment_sta_launch_pins.json`, `tools/sta/verify_launch_coverage.py`) |
| Operating envelope and accepted limitations | Envelope: 10–50 MHz host clock, 1.08/1.20/1.32 V, −40/25/125 °C simulation corners, `can_sel` 0–3, `win_sel=0`. Accepted limitations: (1) transient decks are cell-level — the corrected lumped-capacitance run measures the omission at 8–10 % of ring frequency (extracted 399 fF/549 fF per ring; revision-1 injection was invalid because of the capacitor-unit bug), while a distributed-RC deck is still open work, so the absolute frequencies remain cell-level transient results; (2) the bulk timestep is 10 ps, inside the predeclared 1 % band but 0.9–1.2 % from the 2–5 ps references; (3) the counter aliases above 65535 with no on-chip flag (audit F3) and the RO window is one-shot per reset (F4) — both documented in `docs/info.md`; (4) silicon startup jitter, board clock/voltage/thermal qualification and the FREEZE host contract remain campaign obligations; (5) FPGA validation unrun; (6) stop-transient cleanliness is demonstrated at 42 measured phases (plus the 12-phase sweep) rather than proved analytically for all phases; (7) the wrap run uses the 20 ps step of the original carry test, so its exact edge count carries that step's few-percent rate offset — the wrap verdict rests on the count decoding, not on the frequency |
| Manifest and durable raw-data location | `data/safe10/freeze/manifest.json` (archived datasets, decks, tools, build inputs, sha256). Raw waveforms: `runs/freeze-validation/**/*.raw` (git-ignored, large; reproducible from the archived decks plus `tools/ro/sweep_ro_count.py`/`run_ro_carry_test.py`); the level re-check is reproducible with `tools/ro/recheck_archived_counts.py`, the stop-phase evidence with `tools/ro/archive_stop_phase.py`, the targeted sweep with `tools/ro/sweep_stop_phase.py`, and the corrected sensitivity run with `tools/ro/run_wirecap_sensitivity.py --jobs 8` |
| Reviewer/date and final decision | 2026-09-17, coding-agent review session (extended in the same session for the wrap/stop-phase work). **Decision: the current RTL is the approved freeze candidate — no RTL defect was demonstrated and no RTL change is required.** The two review passes found seven validation-tool defects (capacitor units; mid-rail readout levels; `count_ok` not wrap-aware; `f_count_from_counter_mhz` inverted scale; `f_count_from_counter_mhz` using the raw wrapped counter; the stop-transient classifier's 70 % detection floor; the frequency fields' unstated interval convention) instead of RTL defects; all are fixed, fixture-covered and re-checked against every archived waveform (64/64 records, 0 verdict changes), the corrected wire-capacitance sensitivity run is complete (8–10 % period effect, count exact), the stop phase is measured from the archived waveforms and swept directly (0 runt pulses in 73 343 crossings), the full `0xFFFF` wrap is measured in SPICE (65 715 edges, decoded 179, one inferred wrap, 0 circular error), and the documentation that overstated completion is corrected in place. **Not claimed by this decision:** distributed-RC signoff and any silicon behaviour — those are listed as coverage/campaign restrictions above, not as established results. Keep the settled contracts (third-edge configuration capture, fourth-edge `uio` hand-off, one-shot falling-edge DUT capture, 19-cycle frame, host-synchronous FREEZE) unchanged. |

The record is complete as of the commit that carries it: keep the current RTL
as the frozen candidate and make only changes justified by new validation
evidence. Passing these gates required no RTL changes.
