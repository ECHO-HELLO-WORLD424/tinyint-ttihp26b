# RO canary cross-check in SDF simulation: why gen_cnt=6 / mat_cnt=0

Status: diagnosis of the `data/sdfsim.csv` RO cross-check row (slow corner,
`cansel=3`, `winsel=0`, FORCE_CAN off, 30 frames) against the STA prediction in
`data/ro_predict.csv` (run `33839023290`). The SDF-sim tooling itself is owned by
the P1.2 stream; this note only explains the discrepancy and scopes the fix.

## Observed discrepancy

| quantity | STA prediction (`ro_predict.csv`, slow, sel3) | SDF-sim cross-check |
| --- | --- | --- |
| gen edges in the 256-clk window (5120 ns) | `count_win0 = 825` (T_loop 3.10 ns, T_half 6.2 ns) | `gen_cnt = 6` |
| mat edges in the window | `count_win0 = 240` (T_loop 10.64 ns, T_half 21.3 ns) | `mat_cnt = 0` |

## Root cause (confirmed by experiment)

The RO loop cells are annotated with **hard zero IOPATH delays** in the SDF used
for simulation:

1. `src/pnr.sdc` ends with
   `set_disable_timing [get_cells -hierarchical {*u_ro_gen*}]` / `{*u_ro_mat*}`
   (deliberate: free-running loops are not valid STA objects).
2. OpenROAD's `write_sdf` therefore emits explicit `(0.000:0.000:0.000)` IOPATH
   values for every cell inside the disabled trees — verified in the raw corner
   SDF (`artifacts/run-33839023290/sdf/nom_slow_1p08V_125C/...sdf`), e.g.
   `(CELL (CELLTYPE "sg13g2_inv_1") (INSTANCE u_ro_gen\.g_tail\[0\].u_t._cell)
   ... (IOPATH A Y (0.000:0.000:0.000)))`. All 217 `u_ro_*` CELL blocks in
   `data/sdf_path/nom_slow_1p08V_125C.iopath.sdf` carry zero triples (258 IOPATH
   arcs). `tools/sdf/filter_sdf.py` preserves them verbatim (its empty-`()`
   → `0.000` rule is not even needed here; the zeros are already in the source).
3. In simulation the loops therefore run at ~zero cell delay. Only the
   synthesis-inserted fanout buffers on the loop nodes (plain `_NNNN_`/`fanoutNN`
   names, NOT disabled, correctly annotated, ~0.2 ns each way) remain in the loop.
   A diagnostic probe of the loop nodes (`dut.\u_ro_gen_u_line_node_0_`,
   `dut.\u_ro_mat_u_line0_node_0_`) counted **11885 gen / 13449 mat posedges**
   inside the window — posedge gaps 0.43 ns / 0.38 ns, i.e. an effective
   ~2.3 GHz "oscillation" instead of the predicted 161 MHz / 47 MHz.
4. The edge counters themselves are correctly annotated (synchronous DFF banks
   clocked via the annotated fanout buffers), but at a 0.4 ns clock their
   D-logic (annotated, ~1–2 ns) cannot settle between edges, so every edge is
   sampled mid-transition. The final counter values are deterministic race
   garbage: `gen_cnt=6`, `mat_cnt=0`. `mat_dead`/`gen_dead` in the status byte
   (`0xdc`) are consistent with this readback.

### Decisive experiment

Re-running the identical 30-frame cross-check with a patched copy of the
IOPATH-only SDF in which **only** the `u_ro_*` CELL blocks' zero triples were set
to `0.100:0.100:0.100` (258 arcs, done on a scratch copy, tooling untouched):

- gen loop slows to 448 posedges in the window and the readout reports
  `gen_cnt = 448`; mat slows to 168 and reads `mat_cnt = 168`.
- Counter readback now equals the probed node edges **exactly** (448/448,
  168/168): once the loop period is resolvable, the counters and readout are
  functionally correct.

## Hypotheses disconfirmed

- **Instance-name binding failure** (backslash-escaped SDF `INSTANCE` strings
  like `u_ro_gen\_g_tail\_0\_\_u_t\__cell` vs renamed netlist instances
  `\u_ro_gen_g_tail_0__u_t__cell`): disproven. Icarus strips the `\x` SDF name
  escapes and binds correctly — the patch experiment took effect precisely on
  the renamed RO cells, and no SDF warnings appear.
- **Dropped conditional IOPATH variants** (`filter_sdf.py` rule 5): not the
  cause — even the unconditional arcs of the RO cells are written as zeros by
  OpenROAD, and the loops do oscillate (no fixed point).
- **Missing INTERCONNECT annotation**: not the cause of the low counts. It makes
  the loops *faster* (optimistic), and for the DUT capture path it contributes
  only the documented ~1 ns optimism. The loops did not settle at time 0; the
  kick-start via `rst_n`/`en` works (first edges at t≈141 ns, right after
  `ro_en` rises).

## Fix direction (P1.2/P1.3 follow-up, owner: SDF-sim stream)

The RO cell delays must come from a source that is not filtered by the loop
disable, e.g.:

- Generate a supplementary SDF without `set_disable_timing` on the RO trees
  (broken-loop STA with explicit loop breaks instead), and splice those CELL
  blocks over the zero ones; or
- Look up each RO cell's IOPATH delay from the corner Liberty (NLDM at the
  SPEF load/slew) directly in `filter_sdf.py`; or
- Exclude the RO counters from the comparison and treat the SDF cross-check as
  DUT-boundary-only until (a) or (b) lands.

Note also: with real delays restored, expect counts somewhat *below* the STA
prediction in this IOPATH-only setup (no interconnect delay is annotated, so
the bias direction for the loops is fast, not slow).

The current `data/experiment_sta.csv` (run `33839023290`) gives a 24.96 ns
runtime data path and a 25.42 ns predicted failure period (39.34 MHz) at the
slow corner for seg3333/worst.

## Reproduction

The diagnostic testbench and patched SDF are disposable (regenerate as needed):
compile `netlist_sim.v` + `sg13g2_stdcell_sdf.v` with a probe testbench that
counts posedges on `dut.\u_ro_gen_u_line_node_0_` /
`dut.\u_ro_mat_u_line0_node_0_` (same stimulus as `tools/sdf/tb_sdfsim.v`,
`+period=20 +segs=ff +pat=1 +cansel=3 +winsel=0 +forcecan=0 +nframes=30`), run
once with `data/sdf_path/nom_slow_1p08V_125C.iopath.sdf` and once with the
patched copy.
