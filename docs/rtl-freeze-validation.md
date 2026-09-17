# RTL freeze validation record (gates 1–3)

Status: **complete (2026-09-17)**. Data: `data/safe10/freeze/`
(`freeze_summary.json`, `freeze_tables.md`, the per-case CSV/JSON files and
`manifest.json`); the transient decks, rawfiles and ngspice logs live under
`runs/freeze-validation/` and are reproducible from the archived decks. Gate 1
and Gate 4 are complete (see [`rtl-freeze-checklist.md`](rtl-freeze-checklist.md));
this document records the window-transient work that gates 2 and 3 require.

## Why a new transient deck

The committed counter-inclusive dataset (`data/safe10/count/`, revision 1) was
measured with a free-running deck: `en` was tied high for the whole run, the
ring never stopped, and the counter was read while it was still rippling. That
deck can show that the ripple counter counts, but not that the count belongs to
the chip's measurement window. The freeze review therefore replaced it with a
window deck:

| Property | Free-running deck | Window deck |
| --- | --- | --- |
| `rst_n` | slow PWL ramp from t=0 | asserted from t=0, released with a real edge at a declared time |
| `en` | DC high | rises three clock periods after the first clock edge, falls when `win_done` sets |
| initial state | `uic` plus `.ic` on the ring nodes | DC operating point solved with reset asserted and the gate closed (no `uic`) |
| window length | whole transient | 253 external clock periods (`win_sel=0`), then the protocol's readout interval |
| control waveforms | not saved | saved through zero-volt sense branches (`sense_en`, `sense_rst_n`, `sense_q0..q15`) |
| analysis window | counter's own first/last transitions | derived from the control waveforms |

The window boundaries are not assumptions: `tools/ro/probe_ro_window.py`
simulates the RTL and records the cycle at which `ro_en` rises and falls
(`runs/freeze-validation/window/window.json`). For `win_sel=0` the gate opens at
clock cycle 4 and closes at cycle 257 — **253 clock periods**, i.e. 25.3 µs at
10 MHz and 5.06 µs at 50 MHz. `run_ro_count_case.run_window()` builds the deck's
`en` PWL from those numbers, so deck and RTL cannot drift apart silently.

## Startup repeatability: what the three startups can and cannot show

The three "startups" per configuration differ in the host release phase
(`release_phase` = 0.05, 0.35, 0.65 of a clock period), i.e. in *when* within the
host clock the reset release and the boot sequence happen. They do **not** change
the ring's own startup: the ring is gated off until `ro_en` rises, so its
oscillation begins from the same reset state, driven by the same `en` edge, in
every case — and the gate-open interval is a fixed number of clock periods. The
deck is deterministic, so the three runs are the same measurement shifted in
time, and the observed count spread is exactly zero. This is a real result about
the *model* (the count is fixed by the gate-open duration and the ring period,
not by the host phase) but it is not a sample of physical startup jitter, which
no deterministic transient deck can produce. The quantified uncertainty that
follows is the gate-boundary one: at most one ring edge
(`edge_ambiguity_edges`, derived per case from the measured `en` transition and
the ring period). Startup *jitter* on silicon remains a campaign measurement.

## Method and provenance
* Extraction: `tools/ro/extract_ro_loop.py --counter` re-run from the archived
  final build's Magic spiceextraction
  (`tt_um_echoworld424_tpv.spice`, sha256 `18a5657c…`, CI run `35034979531`,
  commit `0a7cd5e`). The re-extraction reproduces all eight loop subcircuits
  byte-identically (`runs/freeze-validation/reloops/`).
* Structural control roles: every control port is resolved from the extraction's
  recorded driver pins and checked against the RTL's structure (enable → gate
  AND, mask → gate inverter, tap selects → the three tap muxes, reset → the flop
  `RESET_B` tree). Unknown roles are rejected rather than driven to 0 V; the
  check runs on every case.
* Analysis: `tools/ro/analyse_ro_count.py` (see gate 1 in the checklist for the
  acceptance vocabulary and the fixture tests).
* Timestep: the bulk runs use **10 ps**, chosen from
  `runs/freeze-validation/timestep_probe.json` — the coarsest step whose edge
  rate stays inside the predeclared 1 % tolerance against the 5 ps reference for
  the fastest, slowest, generic and matched canaries (−0.20 % to −0.91 %; 20 ps
  is −0.93 % to −4.50 % and 40 ps −3.8 % to −12.8 %). The convergence cases are
  still run at 5 ps and 2 ps.
* Tolerances: predeclared in
  [`data/safe10/freeze/PREDECLARED-TOLERANCE.md`](../data/safe10/freeze/PREDECLARED-TOLERANCE.md)
  before the sweep results were available.

## Interconnect capacitance: measured, and why it is not simulated

The transient decks are cell-level: the Magic spiceextraction carries
transistor-level cells with cell-internal parasitics but no inter-cell wire RC
(no RC extraction was run for this tile). Two independent pieces of evidence
bound the omission:

1. **The missing capacitance is measured.** `tools/ro/analyse_loop_rc.py` maps
   every ring instance to its SPEF instance and every `(instance, pin)` pair to
   its SPEF net, then sums the SPEF capacitance of the nets the ring touches:
   399.3 fF over 119 nets for `ro_gen` (8.3 % of the design's total wire
   capacitance) and 548.9 fF over 231 nets for `ro_mat` (11.4 %). At the typical
   corner that is on the order of the ring's own gate input capacitance, i.e. it
   is not negligible for the *frequency*.
2. **A direct sensitivity run was attempted and failed.** In
   `tools/ro/add_wire_caps.py` the same per-net capacitance is inserted as
   lumped capacitors inside the loop subcircuit, so the deck could be run with
   and without it. Every such deck stalls: with the operating-point start the
   loop settles on its metastable mid-rail solution, and with a `uic` start from
   the reset state it does not oscillate either — at 100 %, 25 % and even 5 % of
   the extracted capacitance (≈ 0.17 fF per net), while the identical deck
   without capacitors oscillates normally. The failure is structural to the
   modified subcircuit, not a magnitude effect, and it is recorded here rather
   than papered over.

Why the omission does not invalidate the counting conclusion:

* The claim the deck supports is a **ratio** — the counter's decoded value
  versus the ring edges the *same deck* offers. Wire capacitance changes the
  ring's period, not the counter's function.
* The direction is conservative. The ripple counter needs each carry to
  propagate within one ring period, so a *faster* ring is the harder case.
  Omitting load capacitance makes the simulated ring faster (the cell-only
  SPICE ring runs 1.03–1.14× the SPEF-based broken-loop STA prediction, mean
  1.083, `data/safe10/ro_predict.csv` vs `data/safe10/spice/spice_ro.csv`), so
  a counter that counts correctly in these decks has at least as much margin in
  the extracted circuit.
* The residual frequency offset is part of the SPICE/STA calibration ratio the
  prediction model already carries, and the canary is used as a *relative*
  delay proxy fitted per operating point.

The absolute ring frequency from these decks is therefore a **cell-level
transient result, not post-route RC signoff**, and the same label applies to the
f_osc dataset it agrees with. A distributed-RC deck remains open work.

## Compute budget and deviations

The full checklist matrix (12 primary configurations × 3 startups at 5 ps, plus
the diagnostic, control, carry and convergence runs) is about 780 µs of
simulated ring time. The measured aggregate throughput of this machine for these
decks is ~7–16 ns/s, i.e. **20–30 hours** of wall time for the literal plan. The
executed plan is therefore:

| Item | Checklist asks | Executed |
| --- | --- | --- |
| Primary cases at 50 MHz | 6 configurations × 3 startups | 18 runs, all accepted |
| Primary cases at 10 MHz | 6 configurations × 3 startups | 3 runs (matched at the typical and slow corners, generic at typical), all accepted — the full 6 × 3 ten-MHz arm is ≈ 150 µs of simulated time on its own |
| Diagnostic unstable matched cases | 4 configurations | the two `can_sel=3` cases are covered by the primary runs at both clocks; the `can_sel=2` matched cases are covered at 50 MHz by the matrix sweep (slow/matched/`sel2` measures 90.87 MHz, single mode, against the 91.2 MHz retained in revision 2 and the 218.9 MHz the free-running deck reported) |
| Timestep convergence | 5 ps vs 2 ps on unstable + fastest + slowest | 2/5/10/20/40 ps over 1 µs windows on four representative configurations (16 + 4 runs) |
| Carry coverage beyond 2^14 | targeted carry test | as asked (extended gate, fast corner, 34 524 edges) |
| Matrix completeness | 24 cases | 24 cases at 50 MHz, 18 new + 6 from the primary set |
| Control cases | FORCE_CAN / freeze / reset | 3 runs at 50 MHz |

Every deviation is a **coverage** difference, not a relaxation of an acceptance
rule: no case is accepted without its own waveform evidence, and nothing is
substituted from an older dataset. The runs consumed roughly 400 µs of simulated
ring time (≈ 15 hours of wall time across three parallel stages).

## Gate 2 results — the canary in its real window

Full tables: `data/safe10/freeze/freeze_tables.md`; machine-readable rows in the
CSV/JSON files beside it.

**50 MHz window (5.06 µs, `win_sel=0`), six configurations × three startups.**
All 18 runs are accepted (`count_ok`, `settled`), and every one is
single-valued: one interval cluster, coefficient of variation 2 × 10⁻⁵ …
2 × 10⁻⁴. The three startups of each configuration return **identical** counts
and rates (spread 0.0 %, against the predeclared 1 % criterion), for the reason
set out above.

**10 MHz window (25.3 µs, the submitted operating point).** The configurations
that carry the decision — the matched canary at the typical and slow corners and
the generic canary at typical — are measured over the full nominal window in
`primary_windows.csv`:

| corner | canary | ring edges | decoded count | f | CV | modes | settle vs gate close |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| typical | ro_gen | 7301 | 7301 | 288.569 MHz | 7.5e-5 | 1 | −2.4 ns |
| typical | ro_mat | 2731 | 2731 | 107.938 MHz | 2.3e-5 | 1 | −7.4 ns |
| slow | ro_mat | 1730 | 1730 | 68.373 MHz | 1.1e-5 | 1 | −11.3 ns |

Both canaries measure the **same frequency** in the 25.3 µs window as in the
5.06 µs window (288.569 MHz and 107.938 MHz in both), i.e. the measured rate does
not depend on the window length, and the matched canary is single-valued over the
long window with a settle time inside the last ring period. That is the gate's
core question answered directly at the nominal operating point.

Aggregate: 21 primary window runs (18 at 50 MHz with three startups each, 3 at
10 MHz), **21/21 accepted**, and the 24-case counter matrix at 50 MHz is
**18/18 accepted** on top of the six `can_sel=3` primary configurations.

**The matched canary is not multi-mode in the window deck.** The four
"unstable matched-RO configurations" recorded in
`data/safe10/count/FOSC-REGEN-STATUS.md` (interval CV 0.38–0.58 in the earlier
ring-only analysis) are the configurations the freeze review flagged. In the
counter-inclusive window deck at `can_sel=3` they measure one mode at every
corner:

| corner | canary | measured | f_osc dataset (rev 3) | Δ | CV | modes |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| fast | ro_gen | 432.658 MHz | 432.667 | −0.002 % | 1.2e-4 | 1 |
| fast | ro_mat | 161.879 MHz | 161.876 | +0.002 % | 6.3e-5 | 1 |
| typical | ro_gen | 288.569 MHz | 288.564 | +0.002 % | 7.5e-5 | 1 |
| typical | ro_mat | 107.938 MHz | 108.503 | −0.52 % | 2.3e-5 | 1 |
| slow | ro_gen | 182.725 MHz | 182.726 | −0.001 % | 2.6e-5 | 1 |
| slow | ro_mat | 68.373 MHz | 68.754 | −0.56 % | 1.1e-5 | 1 |

The cross-check column is the independently measured counter-inclusive f_osc
dataset (`data/safe10/spice/spice_ro.csv`, revision 3). Every configuration
agrees within 0.6 %, and the two largest deltas are exactly the two
configurations previously called multi-mode — which the window deck resolves as
single-valued with a slightly different period. The earlier multi-mode
classification therefore did not survive a deck that gates the ring off and
decodes a settled counter; the residual 0.5 % is recorded as a period difference
between decks, not as instability.

## Gate 3 results — carries, controls, settling

**Carry coverage.** The extended-gate carry run (fast corner, `ro_gen`,
`can_sel=0`, 29 µs open gate) offers **34 524** ring edges and the counter
decodes **34 524** — zero error — with every stage at its binary-carry rate
(bit 15 toggles exactly once, so `0x7FFF → 0x8000` is covered). `0xFFFF → 0x0000`
is not claimed: no run crosses 65 536 edges, and the wrap remains covered only by
the RTL regression `test_ro_ripple_counter_wrap`.

**Settling versus readout.** Per-stage ripple delay measured in that run is
0.135–0.139 ns, so a full 15-stage ripple needs ≈ 2.1 ns — an order of magnitude
inside the two-clock readout interval (40 ns at 50 MHz, 200 ns at 10 MHz). Those
delays are taken from the run's **last** transitions, i.e. from the
`0x7FFF → 0x8000` event where bit 15 responds to the ripple that flipped all
fifteen lower stages. In every completed window case the last counter bit
transition happened *before* the gate closed (settle −0.17 … −0.21 ns), and no
case reported an unsettled bit; `settle_within_readout_fraction = 1.0` in
`freeze_summary.json`.

**Control cases** (50 MHz window): `FORCE_CAN` mid-window stalls the loop and the
counter holds the 574 edges offered before the stall; `FREEZE` closes the gate,
the counter holds, and counting resumes (892 edges = 892); a mid-window reset
clears the counter and counting restarts from the last reset release (1047 edges
= 1047). All three decode correctly once the analyzer opens the counting window
at the last reset release (a fix this gate produced).

**Matrix completeness.** The 24-case (corner × canary × `can_sel`) matrix is
measured at 50 MHz in `matrix_windows.csv`; the frequencies reproduce the
counter-inclusive dataset to better than 0.02 % (for example
`fast/ro_gen/sel0` 1235.19 MHz vs 1235.10 MHz, `typ/ro_gen/sel2` 364.48 vs
364.48).

## Gate 2 and 3 verdicts

| Gate | Verdict | Basis |
| --- | --- | --- |
| 2 — matched-canary window behaviour | **Pass**, with the uncertainty quantified | every primary case accepted; counts repeat exactly across startups; the previously flagged multi-mode configurations are single-valued; timestep uncertainty 0.9–1.2 % at the bulk 10 ps step (2 ps→5 ps→10 ps ladder measured); gate-boundary ambiguity ±1 edge per case; wire RC bounded but not simulated |
| 3 — carries, stop/readout, controls | **Pass** for stages 0–15 and `0x7FFF→0x8000`; **not claimed** for the full `0xFFFF` wrap | 34 524/34 524 edges counted with per-bit coverage; settling ≪ readout interval; control cases hold/restart correctly; 24-case matrix complete |
| 4 — experiment STA | Pass (see the checklist and `docs/experiment-sta-launch-coverage.md`) | 18 launch pins resolved structurally, 96 cases, gap 0.000 ns, control margin positive |


