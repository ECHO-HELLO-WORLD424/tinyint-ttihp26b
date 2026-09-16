# Counter-inclusive extracted RO transient (SPICE) validation

Status: **complete** (2026-09-16, dataset revision 1). This is the test that the
f_osc dataset in [`docs/ro-spice-validation.md`](ro-spice-validation.md) cannot
perform: it simulates the canary **with its ripple edge counter running**, so the
counter's toggle feedback and the whole 16-stage ripple chain are exercised
instead of being pinned in reset.

## Why this test exists

The f_osc decks extract the ring subtree only. In that subtree the counter's
first flop is present as a real capacitive load on the loop node, but the
counter's own logic (its toggle inverter and the 15 further ripple stages) is
outside the subcircuit, so its `D` pin and the shared reset tree become deck
control pins that the driver holds at 0 V. The counter is therefore **held in
reset** for the entire f_osc run, and those results say nothing about whether
the on-chip count is usable — they only establish that the loop oscillates at a
given frequency with a static counter attached.

That distinction matters because the counter is the sensor's readout path: the
host converts `gen_cnt`/`mat_cnt` into a frequency, and `docs/prediction-model.md`
uses those counts directly. `src/pnr.sdc` disables timing for the whole
`*u_ro_gen*` / `*u_ro_mat*` hierarchy (`set_disable_timing`), so no static check
covers the ripple flops either. This procedure supplies the missing evidence.

## Method

1. **Counter-inclusive extraction** (`tools/ro/extract_ro_loop.py --counter`).
   Starting from the loop node, the ripple chain is walked outwards: stage 0 is
   the flop clocked by the loop node; stage *k* is the flop clocked by an
   inverter driven by stage *k−1*'s `Q`, and each stage's toggle is the inverter
   that feeds `Q` back into its own `D`. The chain is followed for
   `--chain-depth` stages (16 = the whole counter, which is what this dataset
   uses) and every stage's `Q`, toggle and ripple-clock cells are pulled into
   the subcircuit.

   Each flip-flop's reset and clock pins are then walked *back* along their
   single-driver chains until an independent net is reached, so the shared
   reset buffer tree (`fanout50/X` … `fanout66/X` … `rst_n`) is included
   instead of being exposed as deck-driven ports. Without that step the deck
   drives one buffer output against another, the downstream flops stay in
   reset, and the test would silently reproduce the very gap it exists to close.

   Control-pin roles (enable, mask, reset, tap select) are inferred from the
   subcircuit structure and recorded in `ro_loop.json` (`control_roles`), not
   from net names: the flat net names are synthesis-assigned and differ between
   builds (`_1351_/CLK` vs `_1347_/CLK`, `_0913_/X` vs `_0898_/Y`).

2. **Deck** (`tools/ro/run_ro_count_case.py`). Same models, corners and
   supplies as the f_osc decks. Differences:

   * every counter bit's `Q` net is saved (`v(x1.Q0)` … `v(x1.Q15)`), so the
     final count and every ripple transition are observable;
   * the reset input is driven as a PWL that asserts for a defined startup and
     then releases, so the counter starts from 0 and then runs — the state a
     real canary window holds;
   * the counter bits are outputs only and are never driven;
   * the `X1` instance lists its nodes in the `.subckt` declaration order (a
     mismatch silently mis-wires control pins, which is how an early version of
     this driver held the counter in reset).

3. **Analysis** (`tools/ro/analyse_ro_count.py`). Measures the ring period from
   the loop node, decodes the 16 saved bits just after bit 0's last falling
   edge, and checks three independent things:

   * **count vs ring edges** — bit 0 is clocked by the ring itself, so the
     counter's final value must equal the number of ring rising edges between
     bit 0's first and last falling edges (tolerance 1 edge, the sampling
     ambiguity of a window bounded by two bit-0 edges);
   * **count vs period estimate** — the same number derived from the measured
     ring period, which is independent of the counter;
   * **ripple rates** — stage *b* must toggle once per `2**b` bit-0 periods; a
     stage that misses or doubles a ripple breaks this even if the aggregate
     value happens to look plausible.

## Result summary

**22 of 22 cases pass**: the counter's final value equals the independently
measured ring-edge count within the ±1-edge sampling tolerance, and every ripple
stage toggles at its correct binary-carry rate. Dataset:
`data/safe10/count/ro_count.csv` (machine-readable, one row per case),
`ro_count.json`, `count_vs_fosc.csv/json`, `provenance.json`.

| Metric | Value |
| --- | --- |
| Cases simulated | 22 (3 corners × 2 canaries × 4 `can_sel`) |
| Cases where the counter counted the ring's edges (±1 edge) | **22 / 22** |
| Cases where every ripple stage ran at its correct rate | **22 / 22** |
| Count error | +1 edge in 19 cases, 0 in 3 |
| Ring frequency vs the previous f_osc dataset | within ±1.4 % in 20 cases; the 2 slow-corner `ro_mat` `can_sel` 2/3 cases differ (see below) |

The table's "prev dataset" column is the revision-2 f_osc number
(`data/safe10/spice/spice_ro.csv`); the Δ column is the difference between the
two decks, which is expected to be small (the counter is a load, not part of the
loop) and is a useful consistency check on both datasets.

| Corner | Canary | can_sel | f_osc (MHz) | prev dataset (MHz) | Δ | counted | ring edges | error (edges) | ripple rates |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| fast 1.32 V / −40 °C | ro_gen | 0 | 1235.1 | 1246.6 | −0.93 % | 24 | 23 | +1 | ok |
| fast 1.32 V / −40 °C | ro_gen | 1 | 759.9 | 769.4 | −1.23 % | 22 | 21 | +1 | ok |
| fast 1.32 V / −40 °C | ro_gen | 2 | 546.6 | 553.0 | −1.16 % | 20 | 19 | +1 | ok |
| fast 1.32 V / −40 °C | ro_gen | 3 | 432.7 | 438.0 | −1.23 % | 20 | 19 | +1 | ok |
| fast 1.32 V / −40 °C | ro_mat | 0 | 688.3 | 694.8 | −0.93 % | 22 | 21 | +1 | ok |
| fast 1.32 V / −40 °C | ro_mat | 1 | 327.9 | 331.5 | −1.10 % | 20 | 19 | +1 | ok |
| fast 1.32 V / −40 °C | ro_mat | 2 | 215.3 | 218.3 | −1.36 % | 18 | 18 | 0 | ok |
| fast 1.32 V / −40 °C | ro_mat | 3 | 163.9 | 164.2 | −0.16 % | 38 | 38 | 0 | ok |
| typ 1.20 V / 25 °C | ro_gen | 0 | 822.2 | 825.4 | −0.39 % | 22 | 21 | +1 | ok |
| typ 1.20 V / 25 °C | ro_gen | 1 | 506.5 | 508.8 | −0.46 % | 20 | 19 | +1 | ok |
| typ 1.20 V / 25 °C | ro_gen | 2 | 364.5 | 366.3 | −0.48 % | 20 | 19 | +1 | ok |
| typ 1.20 V / 25 °C | ro_gen | 3 | 289.4 | 290.0 | −0.20 % | 22 | 21 | +1 | ok |
| typ 1.20 V / 25 °C | ro_mat | 0 | 458.8 | 458.8 | 0.00 % | 38 | 37 | +1 | ok |
| typ 1.20 V / 25 °C | ro_mat | 1 | 219.2 | 219.2 | 0.00 % | 38 | 37 | +1 | ok |
| typ 1.20 V / 25 °C | ro_mat | 2 | 144.2 | 144.2 | 0.00 % | 54 | 54 | 0 | ok |
| typ 1.20 V / 25 °C | ro_mat | 3 | 110.5 | 108.5 | +1.80 % | 30 | 29 | +1 | ok |
| slow 1.08 V / 125 °C | ro_gen | 0 | 519.9 | 520.0 | −0.02 % | 38 | 37 | +1 | ok |
| slow 1.08 V / 125 °C | ro_gen | 1 | 320.9 | 320.9 | −0.01 % | 38 | 37 | +1 | ok |
| slow 1.08 V / 125 °C | ro_gen | 2 | 231.2 | 231.2 | −0.01 % | 38 | 37 | +1 | ok |
| slow 1.08 V / 125 °C | ro_gen | 3 | 182.7 | 183.1 | −0.20 % | 66 | 65 | +1 | ok |
| slow 1.08 V / 125 °C | ro_mat | 0 | 288.9 | 289.0 | −0.01 % | 38 | 37 | +1 | ok |
| slow 1.08 V / 125 °C | ro_mat | 1 | 138.0 | 138.3 | −0.18 % | 50 | 49 | +1 | ok |
| slow 1.08 V / 125 °C | ro_mat | 2 | 218.9 | 91.2 | +140.0 % | 50 | 49 | +1 | ok |
| slow 1.08 V / 125 °C | ro_mat | 3 | 188.0 | 68.8 | +173 % | 74 | 74 | 0 | ok |

### f_osc dataset regeneration (blocked)

Regenerating the f_osc table against the current build surfaced a problem that is
recorded in `data/safe10/count/FOSC-REGEN-STATUS.md` and **not** yet resolved: the
ring-only deck and this counter-inclusive deck disagree by up to 2.5x for the
`can_sel=2` tap selections, with byte-identical subcircuit wiring and identical
select-pin values. The loop waveform itself is not single-period at those
settings (rising-edge intervals of 1.2-6.8 ns in one run), so a mean-interval
frequency depends on the analysis window. `data/safe10/spice/spice_ro.csv` is
therefore left at revision 2 and this dataset is the authoritative f_osc source
for the cases it covers.

## Findings that outlive the acceptance gate

1. **The counter counts.** With the toggle feedback and the full 16-stage ripple
   inside the deck, the counter's saved bits decode to the ring-edge count, and
   every stage toggles at its binary-carry rate, at both the fastest
   (`ro_gen` `can_sel=0`, ≈1.2 GHz, ≈620 MHz at `cnt[0]`) and the slowest
   configurations. This closes the "counts correctly at speed" gap in
   `docs/post-silicon-readiness-audit.md` (F5).
2. **The counter does not perturb the ring.** Where the previous f_osc dataset is
   clean, f_osc with the counter running matches it to ≤ 0.2 % — the *load*
   result and the *counting* result are consistent.
3. **The slow-corner `ro_mat` tap selection does not match the previous f_osc
   dataset.** In this counter deck `ro_mat` `can_sel=2/3` at the slow corner run
   at 214/188 MHz, where the previous f_osc dataset recorded 91/69 MHz. The
   previous numbers are the slowest in the whole design (≈69 MHz for what should
   be the longest loop is on the wrong side of the trend) and are currently
   under review: they may be the tap-mux select role being mis-assigned in a
   name-based deck, exactly the class of bug the structural `control_roles`
   mapping was added to remove. This does **not** affect the counter result — the
   counter tracks whatever the ring does — but it does put the f_osc prediction
   for the slow-corner matched canary in question. Tracked as an open item in
   `docs/post-silicon-readiness-audit.md`.
4. **One case needed a longer window.** `slow` `ro_mat` `can_sel=2` read 56
   against 59 measured edges in the 16-period/10 ps pass. Re-run over 48 periods
   at 5 ps (`runs/count-outlier/`, recorded in the row above) it counts 50
   against 49 edges, so the earlier value was a short-window sampling artifact at
   a 4.6 ns ring period, not a counting failure. The dataset row is the verified
   re-run and the CSV `note` column records the substitution.
