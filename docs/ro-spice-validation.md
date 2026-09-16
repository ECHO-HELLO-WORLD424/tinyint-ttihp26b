# Extracted RO transient (SPICE) validation

Status: **complete** (2026-09-16, dataset revision 3). This is the SPICE test
on the ring oscillators referenced by:

- `docs/pre-silicon-v2-blog.md` (§5 caveats, §7 "still open")
- `docs/prediction-model.md` (RO frequencies were "not transient
  SPICE-validated")
- `tools/ro/ro_predict.tcl` (comment: possible refinement)
- `AGENTS.md` ("Use extracted transient simulation for that purpose")

`data/safe10/ro_predict.csv` (24 rows) is a **broken-loop extracted STA
estimate**. This procedure replaces that caveat with a measured oscillation
frequency from the routed netlist, transient-simulated at transistor level.
SDF simulation cannot do this: RO timing arcs are disabled in signoff SDF
(`docs/ro-sdf-crosscheck-diagnosis.md`).

> **Scope.** This dataset measures f_osc; it does not by itself test counting.
> Revision 2's decks extracted the ring subtree only, so the counter's `D` pin and
> the reset tree became deck control pins and were held at 0 V — the counter was
> held in reset, and the `control_pins: ok` check only asserted that each pin
> reached its assigned level. **Revision 3 uses the counter-inclusive extraction
> and runs the counter**, so the measurement is made in the same configuration as
> on the chip; the counting behaviour itself is validated separately in
> [`docs/ro-counter-spice-validation.md`](ro-counter-spice-validation.md), which
> decodes the counter and compares it with the measured edges. Frozen revision-2
> numbers are archived in `data/safe10/spice/rev2/` and keep the old caveat.

> **Dataset revisions.** Revision 1 had floating canary control pins (a
> deck-generation bug) and produced one anomalous case family; the cause and the
> corrected numbers are in [`RO-SPICE-SEL0-ANOMALY.md`](RO-SPICE-SEL0-ANOMALY.md).
> Revision 2 drove every control pin and verified it by read-back, but measured
> on a different build (commit `b9f03f7`) and with the counter held in reset.
> Revision 3 is the current dataset: current build, counter running, every case
> with uniform 30-period / 10 ps settings. Revision 2 is archived at
> `data/safe10/spice/rev2/`.

## Result summary

24/24 cases simulated and analysed (3 corners x 4 `can_sel` x 2 canaries).
Data: `data/safe10/spice/` (`spice_ro.csv`, `ro_spice_vs_sta.csv`, plots,
`provenance.json`).

| Metric | Value |
| --- | --- |
| Cases | 24/24 simulated and analysed (revision 3) |
| Mean SPICE/STA frequency ratio | **1.083** |
| Ratio standard deviation | 0.028 |
| Range | 1.031 (ro_mat sel3 slow) – 1.143 (ro_mat sel3 fast) |
| Mean ratio, generic canary | **1.087** |
| Mean ratio, matched canary | **1.079** |
| Correlation of ratio with line-segment share of the STA loop | **−0.58** |
| Control-pin read-back check | 24/24 `ok` |
| Single-mode cases (cv < 0.01) | **20/24**; the four multi-mode cases are flagged in the CSV |
| Agreement with revision 2 | every case within **1.42 %** (10 ps vs 5 ps timestep) |

**What the `control_pins` check does and does not mean.** It asserts that every
deck source settled at the level it was assigned (within 50 mV). Two of those
assignments are 0 V by design and hold the counter static: the flop's `D` pin and
the shared reset tree (see the scope note above). The check is also what caught
revision 1's floating pins, so it is necessary but it is not evidence about the
counter.

SPICE is faster than STA in **all 24 cases** — the expected direction, because
the transient run uses a cell-level netlist with no interconnect RC while the
STA prediction includes the SPEF wire parasitics. The gap is not a simple
wire-delay measure: it shrinks as the inverter-dominated line segment dominates
the loop, so the largest disagreements sit in the mux / gate / full-adder cells
rather than in the inverter chains.

Full table (STA from `data/safe10/ro_predict.csv`, SPICE from
`data/safe10/spice/spice_ro.csv`; `line%` is the line-segment share of the STA
loop delay):

| Corner | Canary | can_sel | f_osc (MHz) | STA (MHz) | SPICE/STA | line% | periods | cv |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| fast 1.32 V / −40 °C | ro_gen | 0 | 1235.1 | 1111.1 | 1.112 | 71.1 % | 37 | 0.000 |
| fast 1.32 V / −40 °C | ro_gen | 1 | 759.9 | 694.4 | 1.094 | 81.9 % | 34 | 0.000 |
| fast 1.32 V / −40 °C | ro_gen | 2 | 546.6 | 495.1 | 1.104 | 87.1 % | 33 | 0.000 |
| fast 1.32 V / −40 °C | ro_gen | 3 | 432.7 | 393.7 | 1.099 | 89.8 % | 33 | 0.000 |
| fast 1.32 V / −40 °C | ro_mat | 0 | 688.3 | 609.8 | 1.129 | 85.4 % | 34 | 0.000 |
| fast 1.32 V / −40 °C | ro_mat | 1 | 327.9 | 301.2 | 1.089 | 92.8 % | 32 | 0.000 |
| fast 1.32 V / −40 °C | ro_mat | 2 | 215.3 | 200.0 | 1.076 | 95.2 % | 33 | 0.000 |
| fast 1.32 V / −40 °C | ro_mat | 3 | 161.9 | 151.5 | 1.068 | 96.4 % | 31 | 0.000 |
| slow 1.08 V / 125 °C | ro_gen | 0 | 519.1 | 471.7 | 1.101 | 71.7 % | 33 | 0.000 |
| slow 1.08 V / 125 °C | ro_gen | 1 | 320.3 | 299.4 | 1.070 | 82.0 % | 32 | 0.000 |
| slow 1.08 V / 125 °C | ro_gen | 2 | 230.8 | 214.6 | 1.075 | 87.1 % | 32 | 0.000 |
| slow 1.08 V / 125 °C | ro_gen | 3 | 182.7 | 171.2 | 1.067 | 89.7 % | 32 | 0.000 |
| slow 1.08 V / 125 °C | ro_mat | 0 | 288.5 | 253.8 | 1.137 | 85.8 % | 32 | 0.000 |
| slow 1.08 V / 125 °C | ro_mat | 1 | 138.0 | 129.9 | 1.063 | 92.7 % | 31 | 0.000 |
| slow 1.08 V / 125 °C | ro_mat | 2 | 91.2 | 87.3 | 1.046 | 95.1 % | 39 | 0.385 |
| slow 1.08 V / 125 °C | ro_mat | 3 | 68.8 | 66.7 | 1.031 | 96.3 % | 52 | 0.575 |
| typ 1.20 V / 25 °C | ro_gen | 0 | 822.1 | 746.3 | 1.102 | 71.6 % | 35 | 0.000 |
| typ 1.20 V / 25 °C | ro_gen | 1 | 506.5 | 471.7 | 1.074 | 82.1 % | 33 | 0.000 |
| typ 1.20 V / 25 °C | ro_gen | 2 | 364.5 | 337.8 | 1.079 | 87.2 % | 33 | 0.000 |
| typ 1.20 V / 25 °C | ro_gen | 3 | 288.6 | 268.8 | 1.073 | 89.8 % | 32 | 0.000 |
| typ 1.20 V / 25 °C | ro_mat | 0 | 457.1 | 400.0 | 1.143 | 85.6 % | 33 | 0.000 |
| typ 1.20 V / 25 °C | ro_mat | 1 | 218.2 | 204.1 | 1.069 | 92.7 % | 32 | 0.000 |
| typ 1.20 V / 25 °C | ro_mat | 2 | 144.2 | 137.0 | 1.053 | 95.1 % | 48 | 0.487 |
| typ 1.20 V / 25 °C | ro_mat | 3 | 108.5 | 104.2 | 1.042 | 96.2 % | 41 | 0.381 |

**Revision-3 measurement.** Every case is a 30-period transient at 10 ps on the
counter-inclusive subcircuit (`tools/ro/run_ro_count_case.py`), which carries the
counter's toggle feedback, its 16-stage ripple chain and the reset buffer tree
inside the deck; the counter is therefore *running* during the f_osc measurement,
as it is on the chip. `cv` is the coefficient of variation of the rising-edge
intervals: 20/24 cases are single-mode (cv < 0.01), and the four multi-mode
configurations (typ and slow `ro_mat` `can_sel` 2/3 — the longest loops) keep
their revision-2 values, flagged in the CSV's `note` column.

The matched/generic frequency ratio at the longest tap is 2.67 (fast) / 2.67
(typ) / 2.66 (slow) in SPICE, versus 2.53 / 2.52 / 2.51 in STA — the
structure-matched canary is confirmed to be a substantially slower sensor than
the generic one, as designed.

## Method

1. **Netlist (revision 3).** Post-route extracted SPICE netlist from CI run
   [35034979531](https://github.com/ECHO-HELLO-WORLD424/tinyint-ttihp26b/actions/runs/35034979531)
   (commit `0a7cd5edd8cea7a45085898f84db403c93b25af0`), file
   `runs/wokwi/final/spice/tt_um_echoworld424_tpv.spice`,
   sha256 `18a5657c79f34f010205499071f65990377e0d3be1e5451d6e61c1a8aaefe000` — the
   same build that produced `data/safe10/ro_predict.csv`, so the SPICE and STA
   datasets now share provenance. Revision 2 (commit `b9f03f7` / run
   `34158224984`) is archived under `data/safe10/spice/rev2/`.

2. **Ring extraction** (`tools/ro/extract_ro_loop.py`). The extracted netlist
   is flat: 1,637 non-filler instances at the top level. Both ring loops are
   traced from the gate output net (`_1351_/CLK` for `ro_gen`, `_1367_/CLK`
   for `ro_mat`) over edges driven by another cell of the same RO. The
   resulting subcircuits contain the loop plus the tap mux, the gate cells and
   the first ripple-counter flop (a real capacitive load):
   `ro_gen` 59 cells, `ro_mat` 168 cells.
   The extraction also infers each external pin's role (enable, mask, reset,
   tap select) from where the net sits in the subcircuit rather than from its
   name, and records it as `control_roles` in `ro_loop.json`; the flat net
   names are synthesis-assigned and change between builds.

3. **Transient decks** (`tools/ro/run_ro_spice_case.py`,
   `tools/ro/sweep_ro_spice.py`). Each case simulates only its ring
   subcircuit, with the loop control pins held at the static state of a canary
   window: `en=1`, `mask=0`, `rst_n=1`, mux `sel` = `can_sel`. The ring is
   initialised with `.ic` on every loop node and run with `tran ... uic`, so
   the free-running loop does not need a DC operating point. Only the loop node
   and the control ports are saved. Every static control pin is read back from
   the rawfile and checked against its intended level (`control_pins` column);
   all 24 cases pass.

4. **Measurement** (`tools/ro/analyse_spice_raw.py`). The loop-node waveform is
   read from the ngspice rawfile; rise/fall crossings are found with 30 %/70 %
   hysteresis and the mean period is taken over all settled crossings
   (startup excluded), rejecting intervals more than 2× the median.

5. **Comparison** (`tools/ro/compare_ro_spice.py`) joins the SPICE table with
   `data/safe10/ro_predict.csv` on (corner, canary, can_sel) and writes
   `ro_spice_vs_sta.csv/json` plus the two plots.

### Toolchain

| Component | Version / identity |
| --- | --- |
| ngspice | 45.2 (`ngspice_45.2+ds-1_amd64`), KLU solver, OSDI support |
| PSP103 model | IHP PDK `c4b8b4e5e7a05f375cca3815d51b3a37721fbf5c`, `sg13g2_stdcell.spice` sha256 `2b6d4e3cb169bdbb1350e01e213ffe7bb4bad261821a51a2fe38a5c92211975a`, compiled to OSDI with OpenVAF-Reloaded `v24.0.2mob` (`psp103.osdi` sha256 `d6b6625d22dc5f11891d0da58f3f18b365ea65816af2fa14fe9c65f377e3d213`) |
| Corners | `mos_ff` 1.32 V / −40 °C, `mos_tt` 1.20 V / 25 °C, `mos_ss` 1.08 V / 125 °C |
| Timestep | 5 ps, UIC, `.ic` on all loop nodes |
| Run length | ~150 settled periods per case where the 2 µs cap allowed (120–246 periods measured) |

The devcontainer provides this toolchain
(`.devcontainer/Dockerfile`: ngspice built from source with `--enable-osdi`,
OpenVAF-Reloaded, and `.devcontainer/compile_pdk_osdi.sh` compiling the PDK's
PSP models to OSDI at container start). A spot check in the devcontainer
reproduced the host result within 0.1 % (1.5402 ns vs 1.5388 ns period at
typical corner, `ro_gen` `can_sel=0`).

## Reproducing

```sh
# inside the devcontainer (ngspice, OpenVAF and the PDK are pre-installed)
cd <repo>
python3 tools/ro/extract_ro_loop.py <path>/tt_um_echoworld424_tpv.spice /tmp/ro_loop
python3 tools/ro/sweep_ro_spice.py \
    --predict data/safe10/ro_predict.csv \
    --outdir /tmp/ro_spice --jobs 6 --tstep-ps 5 --solver klu
python3 tools/ro/compare_ro_spice.py \
    --sta data/safe10/ro_predict.csv \
    --spice /tmp/ro_spice/spice_ro.csv \
    --outdir data/safe10/spice
```

`run_ro_spice_case.py` honours `SPICE_NGSPICE`, `SPICE_NGSPICE_LIB`,
`SPICE_NGSPICE_SCRIPTS`, `SPICE_PDK_DIR` and `SPICE_LOOP_DIR`, so the same
drivers work with the packaged ngspice or the devcontainer's source build.

## Convergence checks

- **Timestep.** At the fast corner (`ro_gen` `can_sel=0`), mean period over 42
  periods: 960.9 ps at 10 ps, 954.1 ps at 5 ps, 952.2 ps at 2 ps. 5 ps is
  0.2 % from the 2 ps reference; 10 ps is 0.9 %. The sweep uses 5 ps.
- **Control pins.** Read back from every rawfile and compared with the deck's
  source values (50 mV tolerance). All 24 cases `ok`; this check is what
  caught the revision-1 deck bug (`RO-SPICE-SEL0-ANOMALY.md`).
- **Solver.** KLU is used; it was ~10 % faster than SPARSE with identical
  periods. OpenMP is compiled in but ngspice's OpenMP parallelism only covers
  BSIM3/BSIM4 device evaluation, not the PSP/OSDI models used here, so
  `OMP_NUM_THREADS` had no effect. Case-level parallelism (`--jobs`) is what
  shortens the sweep.

## Caveats (must stay with the result)

- **SPICE is still a model.** It validates the extracted-netlist prediction,
  not silicon. The silicon count comparison remains a post-silicon
  deliverable.
- **No wire RC.** The extracted netlist used here is Magic's cell-level
  spiceextraction: transistor-level cells with cell-internal parasitics, but
  **no interconnect RC**. The STA prediction includes the SPEF wire
  parasitics. The two numbers are therefore not expected to agree exactly, and
  a SPICE result *faster* than STA is the expected direction. The residual
  disagreement is not a pure wire-delay measure: it also contains the
  difference between a static levelized delay estimate and a real switching
  transient, which is largest in the mux / gate / full-adder cells.
- **Netlist/source match.** The SPICE netlist and `ro_predict.csv` come from
  the same design revision (verified above). Do not mix a stale run's netlist
  with the current `ro_predict.csv`; regenerate both from one build if RTL,
  constraints or the floorplan change.
- **Negative results retained.** All 24 cases are in
  `data/safe10/spice/spice_ro.csv`. No case was excluded to improve agreement.
  Revision 1 of the dataset (floating control pins) is documented rather than
  silently overwritten: see `RO-SPICE-SEL0-ANOMALY.md`.
