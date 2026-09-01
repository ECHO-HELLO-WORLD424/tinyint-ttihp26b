# Sample testbench for a Tiny Tapeout project

This is a sample testbench for a Tiny Tapeout project. It uses [cocotb](https://docs.cocotb.org/en/stable/) to drive the DUT and check the outputs.
See below to get started or for more information, check the [website](https://tinytapeout.com/hdl/testing/).

## Setting up

1. Edit [Makefile](Makefile) and modify `PROJECT_SOURCES` to point to your Verilog files.
2. Edit [tb.v](tb.v) and replace `tt_um_example` with your module name.

## How to run

Test files follow the `test_<module>.py` naming convention and are discovered
automatically by the Makefile. From the repository root, run every module test
with:

```sh
make test=ALL
```

To run one module's test file, omit the `test_` prefix and `.py` suffix. For
example, this runs `test_int4_multiplier.py`:

```sh
make test=int4_multiplier
```

## Interactive simulation

To manually drive the TinyInt pins, advance the clock one cycle at a time, and
inspect the outputs without an FPGA, run this from the repository root:

```sh
make play
```

The `show`, `set ui`, `set uio`, and `step` commands provide raw pin-level
control. Convenience commands such as `clear signed`, `mac -3 4`, `last 2 5`,
and `read acc_lo` exercise the TinyInt protocol. Type `help` in the simulator
for the complete command list. The session also writes `test/tb.fst`, so the
same manual interaction can be inspected afterward in GTKWave or Surfer.

To run gatelevel simulation, first harden your project and copy `../runs/wokwi/results/final/verilog/gl/{your_module_name}.v` to `gate_level_netlist.v`.

Then run:

```sh
make test=ALL GATES=yes
```

If you wish to save the waveform in VCD format instead of FST format, edit tb.v to use `$dumpfile("tb.vcd");` and then run:

```sh
make test=ALL FST=
```

This will generate `tb.vcd` instead of `tb.fst`.

To remove simulator builds, result files, waveforms, and Python test caches,
run this from the repository root:

```sh
make clean
```

## How to view the waveform file

Using GTKWave

```sh
gtkwave tb.fst tb.gtkw
```

Using Surfer

```sh
surfer tb.fst
```
