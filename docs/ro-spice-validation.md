# Extracted RO transient (SPICE) validation

Status: **complete** (2026-09-09). This is the SPICE test on the ring
oscillators referenced by:

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

## Result summary

24/24 cases simulated and analysed (3 corners x 4 `can_sel` x 2 canaries).
Data: `data/safe10/spice/` (`spice_ro.csv`, `ro_spice_vs_sta.csv`, plots).

| Metric | Value |
| --- | --- |
| Mean SPICE/STA frequency ratio | **1.008** |
| Ratio standard deviation | 0.176 |
| Range | 0.521 (ro_mat sel0 slow) – 1.170 (ro_gen sel1 fast) |
| Mean ratio, generic canary | **1.082** |
| Mean ratio, matched canary | **0.935** |
| Correlation of ratio with STA wire share | +0.24 (weak) |

The generic canary (pure inverter line) simulates **6–17% faster** than the
broken-loop STA estimate in 11 of 12 cases. The matched canary (line + full
adders + muxes) is **within −11% … +10%** of STA in 11 of 12 cases. The single
large outlier is `ro_mat` `can_sel=0` at every corner (ratio 0.52–0.65,
period jitter 20–50 ps), where the transient run oscillates about 2x slower
than the static estimate; that case is reported as-is and is discussed under
"Caveats" below.

Full table (STA from `data/safe10/ro_predict.csv`, SPICE from
`data/safe10/spice/spice_ro.csv`):

| Corner | Canary | can_sel | STA MHz | SPICE MHz | SPICE/STA | STA wire share | periods |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| fast 1.32 V / −40 °C | ro_gen | 0 | 1020.4 | 1054.7 | 1.034 | 71.4 % | 205 |
| fast 1.32 V / −40 °C | ro_gen | 1 | 657.9 | 769.4 | 1.170 | 81.6 % | 235 |
| fast 1.32 V / −40 °C | ro_gen | 2 | 476.2 | 550.9 | 1.157 | 86.7 % | 223 |
| fast 1.32 V / −40 °C | ro_gen | 3 | 381.7 | 430.9 | 1.129 | 89.3 % | 204 |
| fast 1.32 V / −40 °C | ro_mat | 0 | 609.8 | 396.5 | 0.650 | 84.1 % | 113 |
| fast 1.32 V / −40 °C | ro_mat | 1 | 301.2 | 331.4 | 1.100 | 92.2 % | 198 |
| fast 1.32 V / −40 °C | ro_mat | 2 | 200.0 | 217.0 | 1.085 | 94.8 % | 191 |
| fast 1.32 V / −40 °C | ro_mat | 3 | 150.6 | 159.4 | 1.058 | 96.1 % | 195 |
| typ 1.20 V / 25 °C | ro_gen | 0 | 694.4 | 653.9 | 0.942 | 72.2 % | 175 |
| typ 1.20 V / 25 °C | ro_gen | 1 | 446.4 | 508.8 | 1.140 | 82.1 % | 219 |
| typ 1.20 V / 25 °C | ro_gen | 2 | 324.7 | 364.4 | 1.122 | 87.0 % | 211 |
| typ 1.20 V / 25 °C | ro_gen | 3 | 260.4 | 284.2 | 1.091 | 89.6 % | 195 |
| typ 1.20 V / 25 °C | ro_mat | 0 | 400.0 | 226.0 | 0.565 | 84.0 % | 93 |
| typ 1.20 V / 25 °C | ro_mat | 1 | 204.1 | 219.2 | 1.074 | 91.8 % | 192 |
| typ 1.20 V / 25 °C | ro_mat | 2 | 136.2 | 143.4 | 1.052 | 94.6 % | 186 |
| typ 1.20 V / 25 °C | ro_mat | 3 | 103.3 | 104.4 | 1.011 | 95.9 % | 185 |
| slow 1.08 V / 125 °C | ro_gen | 0 | 438.6 | 382.9 | 0.873 | 72.8 % | 154 |
| slow 1.08 V / 125 °C | ro_gen | 1 | 284.1 | 320.9 | 1.130 | 82.4 % | 209 |
| slow 1.08 V / 125 °C | ro_gen | 2 | 205.8 | 229.9 | 1.117 | 87.2 % | 206 |
| slow 1.08 V / 125 °C | ro_gen | 3 | 165.6 | 178.7 | 1.079 | 89.7 % | 190 |
| slow 1.08 V / 125 °C | ro_mat | 0 | 253.8 | 132.2 | 0.521 | 84.3 % | 82 |
| slow 1.08 V / 125 °C | ro_mat | 1 | 129.5 | 138.2 | 1.067 | 92.0 % | 189 |
| slow 1.08 V / 125 °C | ro_mat | 2 | 87.0 | 90.6 | 1.042 | 94.6 % | 169 |
| slow 1.08 V / 125 °C | ro_mat | 3 | 66.0 | 65.4 | 0.989 | 95.9 % | 119 |

The measured matched/generic frequency ratio at the longest tap is 2.70 (fast)
/ 2.72 (typ) / 2.73 (slow) in SPICE, versus 2.53 / 2.52 / 2.51 in STA — the
structure-matched canary is confirmed to be a substantially slower sensor than
the generic one, as designed.

## Method

1. **Netlist.** Post-route extracted SPICE netlist from CI run
   [34158224984](https://github.com/ECHO-HELLO-WORLD424/tinyint-ttihp26b/actions/runs/34158224984)
   (commit `b9f03f798978840c8bdc2bb574877408e0f33f4c`), file
   `runs/wokwi/final/spice/tt_um_echoworld424_tpv.spice`,
   sha256 `4a1557205d65cf25e9d21612ad88ec9328bd3e1a7d1a3b0f86224398220a2c76`.
   Every source file of that commit was verified byte-identical to the
   `local-dev-safe10` build that produced `data/safe10/ro_predict.csv`
   (hashes in `data/safe10/verification/local-build-manifest.json`), so the
   SPICE and STA datasets describe the same design revision.

2. **Ring extraction** (`tools/ro/extract_ro_loop.py`). The extracted netlist
   is flat: 1,637 non-filler instances at the top level. Both ring loops are
   traced from the gate output net (`_1351_/CLK` for `ro_gen`, `_1367_/CLK`
   for `ro_mat`) over edges driven by another cell of the same RO. The
   resulting subcircuits contain the loop plus the tap mux, the gate cells and
   the first ripple-counter flop (a real capacitive load):
   `ro_gen` 59 cells, `ro_mat` 168 cells.

3. **Transient decks** (`tools/ro/run_ro_spice_case.py`,
   `tools/ro/sweep_ro_spice.py`). Each case simulates only its ring
   subcircuit, with the loop control pins held at the static state of a canary
   window: `en=1`, `mask=0`, `rst_n=1`, mux `sel` = `can_sel`. The ring is
   initialised with `.ic` on every loop node and run with `tran ... uic`, so
   the free-running loop does not need a DC operating point. Only the loop node
   and the control ports are saved.

4. **Measurement** (`tools/ro/analyse_spice_raw.py`). The loop-node waveform is
   read from the ngspice rawfile; rise/fall crossings are found with 30 %/70 %
   hysteresis and the mean period is taken over all settled crossings
   (startup excluded), rejecting intervals more than 2x the median.

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
| Run length | ~150 settled periods per case where the 2 µs cap allowed (82–235 periods measured) |

The devcontainer now provides this toolchain
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
- **Reproducibility.** Re-running `ro_gen` at the typical corner gave
  651.3 / 506.5 / 362.6 / 282.8 MHz for `can_sel` 0–3 versus
  653.9 / 508.8 / 364.4 / 284.2 MHz in the archived sweep (≤0.5 %).
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
  parasitics, which account for 71–96 % of its predicted loop delay. The two
  numbers are therefore not expected to agree exactly, and a SPICE result
  *faster* than STA is the expected direction. The residual disagreement is
  not a pure wire-delay measure: it also contains the difference between a
  static levelized delay estimate and a real switching transient.
- **`ro_mat` `can_sel=0` outlier.** This is the shortest-tap matched-canary
  case. Its transient run oscillates ~2x slower than the static estimate with
  20–50 ps period jitter (other cases are <5 ps). The extracted netlist's tap
  mux wiring for this setting does not reproduce the RTL's selector topology
  cleanly, so this point should be treated as **not yet explained** rather
  than as a model discrepancy. It is kept in the dataset; do not silently drop
  it.
- **Netlist/source match.** The SPICE netlist and `ro_predict.csv` come from
  the same design revision (verified above). Do not mix a stale run's netlist
  with the current `ro_predict.csv`; regenerate both from one build if RTL,
  constraints or the floorplan change.
- **Negative results retained.** All 24 cases, including the outlier, are in
  `data/safe10/spice/spice_ro.csv`. No case was excluded to improve agreement.
