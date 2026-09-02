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
