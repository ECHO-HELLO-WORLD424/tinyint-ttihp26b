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

Expected baseline: **14 passing tests** (merged half-cycle design plus
`test_uio_oe_handoff`; the
archived full-cycle build's baseline was 10). Inspect `results.xml`; the
cocotb
simulator make rules may not propagate every test failure through the process
exit code.

The RTL build defines `TPV_GDELAY=1`, which supplies simulation-only delay to
the intentional RO loops. It has no synthesis effect.

## Functional gate-level regression

The netlist under test **must be synthesized from the current RTL**. After the F1
`uio_oe` fix (see `../docs/post-silicon-readiness-audit.md`) no in-tree or archived
netlist matches the sources any more: run a fresh hardening first and use its
`final/nl/` netlist (see `../AGENTS.md`).

```sh
cp <fresh-run>/final/nl/tt_um_echoworld424_tpv.v gate_level_netlist.v
make clean
make GATES=yes
```

A stale netlist announces itself: `test_uio_oe_handoff` runs in GL too and fails on
pre-fix logic (`chip drives uio at rising edge 2 ...`). Measured against the archived
`../artifacts/run-34158224984/submission/tt_submission/` netlist (also the CI artifact
of run `34853386333`, both pre-fix): **9 pass / 1 fail / 4 skip**, the single failure
being `test_uio_oe_handoff`. Those netlists are kept for provenance only.

Expected baseline against a matching netlist: **10 passes and 4 intentional skips**
(14 total) — the previous 9 pass / 4 skip baseline plus `test_uio_oe_handoff`. This is
measured, not assumed: the netlist regenerated after the F1 fix
(`runs/wokwi/final/nl/`, sha256 `e889762e…`) gives exactly 10 pass / 0 fail / 4 skip.
The archived full-cycle build's baseline was 8 passes and 2 skips.

This target is a zero-delay functional test:

- Specify blocks are removed from the standard-cell models.
- SDF is not annotated.
- `strip_ro_cells.py` removes the asynchronous RO combinational loops.
- Four tests run only in RTL (`skip=GL`): one-shot capture hold, counter
  saturation, canary window counts, and RO ripple-counter wrap. They depend
  on the simulation-only RO gate delays (`TPV_GDELAY=1`) and internal RTL
  signals that the zero-delay, RO-stripped netlist does not provide.

It validates synthesized configuration, control, counters, and readout. It
does not predict DUT failure frequency or RO frequency. The separate timed
flow is `../tools/run_sdfsim.py`; extracted runtime STA and RO estimation are
`../tools/run_experiment_sta.py` and `../tools/run_ro_predict.py`.

## Bidirectional pad (uio) hand-off check

`tb_pad_contention.v` models the `uio` pins the way a board does — the host's
drivers and the chip's `uio_oe`/`uio_out` drivers on one net — so a hand-off
error appears as a contended (`x`) pad and a corrupted configuration word. The
cocotb suite cannot do this: `tb.v` wires `uio_in` and `uio_out` as separate
nets, so it can only observe the output-enable *timing*. This instrument is
standalone and is not part of the cocotb build (`Makefile` lists `tb.v`
explicitly).

```sh
iverilog -g2012 -o /tmp/tb_pad -DTPV_GDELAY=1 -I ../src \
  ../src/tt_um_echoworld424_tpv.v ../src/tpv_cells.v ../src/tpv_delay_line.v \
  ../src/tpv_rca16.v ../src/tpv_checker.v ../src/tpv_pattern_gen.v \
  ../src/tpv_ro_canary.v tb_pad_contention.v
vvp /tmp/tb_pad    # PASS -> exit 0; any contention -> $fatal, exit 1
```

It caught the F1 defect recorded in `../docs/post-silicon-readiness-audit.md`
(`uio_oe` asserted from `boot[1]`, one clock before the configuration-commit
edge) and fails on that revision with three violations.

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
