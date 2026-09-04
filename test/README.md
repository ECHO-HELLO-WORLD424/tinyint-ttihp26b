# Verification

The cocotb suite verifies configuration capture, boot timing, the 19-cycle
operation frame, all four pattern classes, selectable DUT delay paths,
one-shot result capture, error accounting, DFT injection, canary windows,
freeze semantics, status readout, and mid-run reset/reconfiguration.

Run HDL tests inside the repository devcontainer, where `/ttsetup/venv` and
the IHP SG13G2 PDK are configured.

## RTL regression

```sh
make clean
make
```

Expected baseline: **10 passing tests**. Inspect `results.xml`; the cocotb
simulator make rules may not propagate every test failure through the process
exit code.

The RTL build defines `TPV_GDELAY=1`, which supplies simulation-only delay to
the intentional RO loops. It has no synthesis effect.

## Functional gate-level regression

Copy the routed/synthesized netlist from the archived final build:

```sh
cp ../artifacts/run-33839023290/nl/tt_um_echoworld424_tpv.nl.v gate_level_netlist.v
make clean
make GATES=yes
```

Expected baseline: **8 passes and 2 intentional skips**.

This target is a zero-delay functional test:

- Specify blocks are removed from the standard-cell models.
- SDF is not annotated.
- `strip_ro_cells.py` removes the asynchronous RO combinational loops.
- The one-shot hierarchical monitor is skipped because the final netlist is
  flattened.

It validates synthesized configuration, control, counters, and readout. It
does not predict DUT failure frequency or RO frequency. The separate timed
flow is `../tools/run_sdfsim.py`; extracted runtime STA and RO estimation are
`../tools/run_experiment_sta.py` and `../tools/run_ro_predict.py`.

## Waveforms

The default dump is `tb.fst`:

```sh
gtkwave tb.fst tb.gtkw
```

To generate VCD instead:

```sh
make clean
make FST=
```
