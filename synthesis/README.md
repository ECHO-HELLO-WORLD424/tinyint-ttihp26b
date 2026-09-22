# Standalone comparison synthesis

The three Yosys scripts use the same source files, top module, flattening, and
synthesis recipe. `composite.ys` preserves the runtime architecture selector.
The standalone scripts constrain that selector after process lowering:

- `conventional_only.ys` fixes `core.conventional_selected` high;
- `dynamic_only.ys` fixes `core.conventional_selected` low.

Constant propagation then removes the unselected accumulator and its selection
mux without maintaining a second copy of the command/control RTL. These builds
are analysis netlists for matched area/register comparisons; the unconstrained
composite remains the tapeout netlist.

All generated files are written below `test/sim_build/variants/` and are not
source artifacts.

## Post-layout activity and power

After hardening, run the four-mode extracted-SPEF comparison from inside the
development container:

```sh
PDK_ROOT=/path/to/ihp-sg13g2/version \
  sh synthesis/run_post_layout_power.sh
```

`power_activity_tb.v` applies the same 8,192 signed MACs in every mode. The
script simulates the routed netlist, annotates each VCD onto the nominal SPEF
with the pinned LibreLane 3.0.0.dev44 OpenSTA image, requires all 3,152 design
pins/nodes to be annotated, checks mapped accumulator-state isolation, and
requires the expected dynamic-8 < dynamic-12 < dynamic-16 < conventional power
ordering. Generated traces, logs, and reports are placed in
`test/sim_build/power/`.

## Post-layout peak power

The average flow above reports one whole-trace average per mode. The peak flow
adds a cycle-average peak by ranking the highest-activity clock windows, slicing
the activity VCD for each candidate window, and measuring each slice through the
same routed netlist and nominal SPEF:

```sh
PDK_ROOT=/path/to/ihp-sg13g2/version \
  sh synthesis/run_peak_power.sh
```

`synthesis/peak_activity.py` parses the gate-level VCD, counts
capacitance-weighted state transitions per 20 ns window using the nominal SPEF,
and emits a self-contained VCD slice for the top `TOP_K` windows (default 32).
`synthesis/peak_power.tcl` reports the power of one slice,
`synthesis/run_peak_power.sh` drives it for all four modes, and
`synthesis/analyze_peak.py` aggregates the per-mode average, peak, and
peak/average ratio and writes `test/sim_build/peak/peak_summary.csv`.

The bundled OpenSTA only implements `read_vcd [-scope]`, so the windowing is done
by slicing the VCD rather than with a time-range option. The peak flow reuses the
whole-trace reports from `run_post_layout_power.sh` as the average baseline.
Results and caveats are in [`docs/peak-power.md`](../docs/peak-power.md).

## Maximum operating frequency (Fmax)

The frequency at which the hardened design stops meeting setup timing is found by
sweeping the clock period through OpenSTA on the routed netlist. This is a timing
analysis, not a functional simulation: zero-delay RTL and functional gate models
pass at any clock period, so only the extracted-delay analysis can locate the
setup failure point.

```sh
PDK_ROOT=/path/to/ihp-sg13g2/version \
  sh synthesis/run_fmax_sweep.sh
```

`synthesis/fmax_sweep.tcl` reads the routed netlist, nominal SPEF, and final SDC
once per corner, then redefines `create_clock clk` at each candidate period and
re-applies the released transition, uncertainty, and propagated-clock settings.
`synthesis/run_fmax_sweep.sh` runs one OpenSTA invocation per PVT corner, drives a
coarse linear scan (`CLK_START=20.0` to `CLK_STOP=5.0`, `CLK_STEP=1.0` ns) that
brackets the pass/fail crossing, then a binary search to `CLK_TOL=0.01` ns. The
first period with negative worst setup slack defines Fmax, and the overall Fmax
is the minimum over corners because slow-corner setup is worst.

Per-corner logs and the full worst path at the failing period are written to
`test/sim_build/fmax/<corner>/`, and the one-row-per-corner summary is written to
`test/sim_build/fmax/fmax_summary.csv`. Hold slack is reported alongside each
point; it does not depend on the clock period for this single-clock design. The
method, the metrics-derived expectation, and the corner/SPEF caveats are in
[`docs/fmax.md`](../docs/fmax.md).
