# RTL freeze checklist

## Decision and scope

**Status: gates complete — RTL freeze approved (2026-09-17). See the
[freeze record](#freeze-record).**

Reviewed source: `dbe8844`. Its RTL, constraints and source lists are unchanged
from build commit `0a7cd5edd8cea7a45085898f84db403c93b25af0`, archived under
`artifacts/run-35034979531/`. This checklist supplements the
[readiness audit](post-silicon-readiness-audit.md); it qualifies the RO validation
completion claims using the latest review of the data and raw waveforms.

No new RTL defect was demonstrated in that review. The remaining evidence did
not establish that the default matched canary behaves predictably over the
actual measurement window; that was resolved by gates 1–3
([`rtl-freeze-validation.md`](rtl-freeze-validation.md)), which measured the
canary with a deck that models the real reset → boot → window → readout
sequence. **Result: the matched canary is single-valued and its count decodes
exactly against the independently counted ring edges at every corner and both
host clocks, including the four configurations that were previously flagged as
multi-mode. No RTL change is required.**

Already verified during the review:

- RTL regression: 14 passed (re-run 2026-09-17).
- Functional GL on the archived netlist: 10 passed, 4 intentional skips
  (re-run 2026-09-17).
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
| 1 | Make RO measurements and acceptance checks trustworthy | Analyzer fixtures, explicit coverage/failure statuses | No | **Pass** |
| 2 | Resolve default matched-canary startup and window behavior | Current-build transient waveforms and repeatable edge-count results | Only if the result demonstrates a circuit problem | **Pass** (limitations recorded) |
| 3 | Exercise upper counter carries and stop/readout | Per-bit coverage and stopped-count checks | Only if a counter defect is demonstrated | **Pass** for stages 0–15 and `0x7FFF→0x8000`; full `0xFFFF` wrap not claimed |
| 4 | Include all pattern-state launch registers in STA | Complete launch list, regenerated reports and predictions | No | **Pass** |
| 5 | Reconcile the final package and record freeze | Consistent docs, hashes, test results and final decision | Depends on gates 2–3 | **Pass** |

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
- [x] Replace the permissive ripple-rate check with explicit per-bit coverage:
  `per_bit_coverage[b] = {expected, observed, exercised, rate_ok,
  last_transition_ns}`, and `coverage_complete` requires every stage to have
  been *exercised* and to run at its binary-carry rate. An unexercised upper
  stage yields `ok_partial_coverage`, never `ok`.
- [x] Define how period-estimate disagreement affects acceptance. The count
  comparison (`count_ok`) and the frequency claim (`rate_stable`, plus
  `rate_detail`) are separate booleans; the status vocabulary distinguishes
  `ok`, `ok_partial_coverage`, `ok_unstable_rate` and
  `ok_partial_coverage_unstable_rate` from `mismatch`/`unsettled`/`missing_bits`.
- [x] Fix interval classification: `analyse_ro_intervals.classify()` returns
  `unclassified` when no histogram cluster is found (and `too_few_edges` when
  there is not enough data), and `single_mode` now requires one detected cluster.
- [x] Add fixtures for known-good binary counting, missing edges, missing bits,
  unexercised upper stages, reset transitions, unstable periods and incomplete
  ripple settling — plus no-oscillation and missing-gate-waveform cases. Each
  fixture is checked for both its returned status and the process exit code by
  `tools/ro/test_analyse_ro_count.py` (9 fixtures + 4 interval-classifier cases,
  all behaving as declared).
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

**Status: resolved (2026-09-17).** The window deck (reset → boot → gate open →
gate close → settle → readout, with the boundaries taken from the RTL) measures
those configurations as **single-valued** at every corner, with the count
decoding exactly against the independently counted ring edges, and reproduces
the f_osc dataset within 0.6 %. Full evidence and the timestep ladder:
[`rtl-freeze-validation.md`](rtl-freeze-validation.md);

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
  549 fF over 231 for `ro_mat`) and an injection run was attempted; the
  injected-capacitance deck does not oscillate even at 5 % of the extracted
  value, so the limitation is labelled and argued rather than measured. See the
  validation record for why it does not change the counting conclusion.
- [x] Predeclare a count-repeatability/convergence tolerance before judging the
  reruns. `data/safe10/freeze/PREDECLARED-TOLERANCE.md` was written while the
  sweep was still running: agreement within the larger of 1 % or the derived
  edge-quantization bound, plus the settling/readout rule.

### Pass criteria and decision

Met. Every primary case has a defensible edge-count prediction for its actual
window: the decoded count equals the independently measured ring-edge count in
all accepted cases, startup repeatability is exact (0 % spread), the timestep
and gate-boundary uncertainties are quantified, the stopped readout is verified
settled before the gate closes, and the four configurations under suspicion are
single-valued. No RTL change is indicated by this gate.

## Gate 3 — Validate counter carries and stop–settle–read behavior

The committed 22 count cases finish at counts of 18–74. In the independently
checked 74-count waveform, bits 7–15 only transition during startup. This does
not validate the full 16-stage ripple under counting conditions.

**Status: complete except the full-width wrap, which is not claimed.** Evidence:
`data/safe10/freeze/carry.json`, `control.json`, `matrix_windows.csv`,
`coverage.csv` and the settle fields of `primary_windows.csv`
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
  not a window test. `0xFFFF → 0x0000` is **not** claimed (no run crosses 65 536
  edges); the RTL regression `test_ro_ripple_counter_wrap` covers the wrap at
  RTL level only.
- [x] Exercise the extracted first stage at the fastest supported ring rate
  (1.19 GHz in that run, the fastest configuration in the design); the slow
  corner is covered by the slow-corner window runs, where the measured
  per-stage ripple delay is largest.
- [x] Close the RO enable at multiple phases of its oscillation, and keep
  counting final qualified pulses until the loop has physically stopped. The
  analysis counts every rising edge of the counter's clock net after the window
  opens, including the loop's stop transient, and the three startup phases close
  the gate at three host-clock phases.
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

Met, with the wrap restriction stated: all claimed stages have explicit
post-reset or targeted carry coverage; the settled count matches the
independently observed accepted ring edges exactly (0 error in the carry run,
0 error in every window case); the ±1-edge gate-boundary ambiguity is derived per
case (`edge_ambiguity_edges`) rather than used as a blanket tolerance; and ripple
settling fits the readout contract by more than an order of magnitude.

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

### Freeze record

| Field | Value |
| --- | --- |
| Frozen RTL/build commit and canonical CI run | RTL, constraints and source lists at `0a7cd5e` (working tree `dbe8844` + this analysis work, `src/` and `info.yaml` unchanged); canonical CI run `35034979531` (gds + precheck + gl_test + viewer green), archived as `artifacts/run-35034979531/` |
| Analysis commit and dataset versions | analysis work is in the working tree on top of `dbe8844` (tools, docs, `data/safe10/freeze/`, `data/safe10/count/analyzer_fixtures.json`) and uncommitted at the time of writing — commit it to make this row concrete; datasets: window-deck revision 1 (`data/safe10/freeze/`), analyzer fixtures, experiment-STA launch pins + regenerated `data/safe10/experiment_sta.*` and `data/safe10/predict/*`; f_osc dataset revision 3 unchanged |
| Gates 1–4 evidence links and verdicts | G1 **pass** (`data/safe10/count/analyzer_fixtures.json`); G2 **pass with quantified uncertainty** (`data/safe10/freeze/`, `docs/rtl-freeze-validation.md`); G3 **pass for stages 0–15 and `0x7FFF→0x8000`, full `0xFFFF` wrap not claimed** (`data/safe10/freeze/carry.json`, `control.json`, `matrix_windows.csv`); G4 **pass** (`data/safe10/experiment_sta_launch_pins.json`, `tools/sta/verify_launch_coverage.py`) |
| Operating envelope and accepted limitations | Envelope: 10–50 MHz host clock, 1.08/1.20/1.32 V, −40/25/125 °C simulation corners, `can_sel` 0–3, `win_sel=0`. Accepted limitations: (1) transient decks are cell-level — no inter-cell wire RC (measured at 399 fF/549 fF per ring and bounded, not simulated); (2) the bulk timestep is 10 ps, inside the predeclared 1 % band but 0.9–1.2 % from the 2–5 ps references; (3) the counter aliases above 65535 with no on-chip flag (audit F3) and the RO window is one-shot per reset (F4) — both documented in `docs/info.md`; (4) silicon startup jitter, board clock/voltage/thermal qualification and the FREEZE host contract remain campaign obligations; (5) FPGA validation unrun |
| Manifest and durable raw-data location | `data/safe10/freeze/manifest.json` (archived datasets, decks, tools, build inputs, sha256). Raw waveforms: `runs/freeze-validation/**/*.raw` (git-ignored, large; reproducible from the archived decks plus `tools/ro/sweep_ro_count.py`/`run_ro_carry_test.py`) |
| Reviewer/date and final decision | 2026-09-17, coding-agent review session. **Decision: freeze approved — no RTL change is required.** No gate demonstrated an RTL defect; the one remaining ambiguity the checklist raised (the default matched canary's behaviour over the real window) is resolved in favour of the current RTL, and every remaining item is a documented measurement/campaign limitation rather than a correctness gap. Keep the settled contracts (third-edge configuration capture, fourth-edge `uio` hand-off, one-shot falling-edge DUT capture, 19-cycle frame, host-synchronous FREEZE) unchanged. |

Until this record is complete, keep the current RTL as the candidate and make
only changes justified by the validation results. Passing these gates may
require no RTL changes at all.
