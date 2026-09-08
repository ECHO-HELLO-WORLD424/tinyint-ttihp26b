# TPV chip emulator

An interactive, cocotb-driven model of `tt_um_echoworld424_tpv`. You can set
pins, step one clock cycle at a time, run the real datasheet protocol, and — for
the timing experiment — run the **post-route gate-level netlist with a per-corner
SDF annotated**, so voltage and temperature actually change whether the DUT
capture is correct.

```
tools/chip_emulate.py            command-line entry point (re-execs into the devcontainer)
tools/emulator/chip.py           TpvChip: pin-level + protocol-level driver
tools/emulator/pvt.py            PVT corner table (IHP LibreLane corners)
tools/emulator/artifacts.py      locate/prepare the netlist + corner SDF
tools/emulator/session.py        cocotb test module (scenario dispatcher)
tools/emulator/scenarios.py      hello, pins, patterns, dft, pvtsweep, selftest
tools/emulator/repl.py           interactive command loop
tools/emulator/runner.py         build + launch helper (cocotb runner API)
tools/emulator/tb_emulator.v     testbench (no HDL clock; optional SDF/waves)
tools/emulator/examples/         runnable command scripts
```

## Two backends

| | `--backend rtl` (default) | `--backend sdf` |
| --- | --- | --- |
| Model | `src/*.v` RTL, zero delay | post-route netlist + per-corner SDF |
| Truth | functional (protocol, counters, DFT, freeze) | functional **and timing** |
| Clock period | irrelevant to correctness | sets the capture aperture (high time) |
| PVT | no effect | real cell delays per corner |
| Canaries | oscillate (`-DTPV_GDELAY=1`), counts are simulation-only | **masked** (FORCE_CAN=1): counts are 0 and the dead flags are set |

The SDF backend is the PVT experiment: the DUT launches operands on a rising
edge and samples once on the immediately following falling edge, so **clock high
time is the measurement aperture**. Shorten the period (or slow the corner) and
the ripple carry arrives late, the one-shot capture keeps the stale value, and
the independent oracle flags an error.

### What PVT simulation is and is not

* Real: per-cell IOPATH delays from the LibreLane corner SDF (typ / slow /
  fast), so the first-failure boundary moves with V/T the way a gate-level
  timing simulation predicts it. Compare it with case-analyzed STA and with
  silicon; it is not a substitute for either.
* Not annotated: wire (interconnect) delays — Icarus' interconnect annotator
  crashes on this design's SDF, so `tools/sdf/filter_sdf.py` keeps per-cell
  IOPATH arcs only. This is the same limitation as `tools/run_sdfsim.py`.
* Not available: canary RO frequencies (their timing arcs are disabled for P&R)
  and any analog effect (IR drop, self-heating, jitter). Use the extracted
  transient flow for RO frequency prediction.
* Provenance is printed in every run header and recorded in the sweep JSON:
  netlist path + SHA-256, SDF path + SHA-256, corner, simulator and cocotb
  versions.

## Quick start

```sh
# what PVT corners and artifacts exist
python3 tools/chip_emulate.py corners

# build the Icarus-ready netlist + SDF cache (runs/emulator/sdf/)
python3 tools/chip_emulate.py prepare

# interactive session on the RTL model (default 10 MHz)
python3 tools/chip_emulate.py repl

# interactive session on the post-route netlist at the slow corner
python3 tools/chip_emulate.py repl --backend sdf --corner slow

# one decoded measurement
python3 tools/chip_emulate.py run hello --backend sdf --corner typ --period 14

# first-failure clock period at every PVT corner
python3 tools/chip_emulate.py pvtsweep --ops 50

# regression fixture (protocol, counters, DFT, freeze, PVT behaviour)
python3 tools/chip_emulate.py selftest
python3 tools/chip_emulate.py selftest --backend sdf --corner slow
```

Simulation commands run inside the repository devcontainer by default (Icarus
12.0 + cocotb 2.0.1, the versions `test/Makefile` uses). Use
`--toolchain local` to run with the interpreter/simulator you invoked instead.

## Interactive commands

```
pin level
  ui <v>            drive ui_in (0x80, 128, 0b1000_0000)
  uio <v>           drive uio_in (config phase only)
  rst <0|1>         drive rst_n (0 = reset asserted)
  ena <0|1>         drive the Tiny Tapeout enable pin
  clk <0|1>         drive clk level, hold a half period
  tick [n] / step   step n complete clock cycles (default 1)
  pins              show every pin, the readout pointer and sim time
  period <ns>       set the clock period (period 20 -> 50 MHz)
  duty <frac>       set the clock duty cycle (high time is the aperture)

protocol level
  config <word>              reset + commit a raw 16-bit word
  config key=value ...       seg=3333 pat=worst cansel=1 winsel=0 force_err=1
  config show                show the committed word
  run <ops>                  advance ops measured operations (19 cycles each)
  cycles <n>                 advance n raw clock cycles
  freeze <0|1>               drive FREEZE (ui_in[7])
  status                     read + decode the 16 status bytes
  measure [ops]              configure + run + freeze + read

experiments and scripts
  sweep <pmin> <pmax> [steps] [ops]       scan clock periods
  findfail <p_fail> <p_pass> [ops] [tol]  bisect the first-failing period
  script <file>             run a command script
  assert <expr>             assert over the last status (st, chip, sweep)
  info / pvt                show backend, corner, clock, configuration
  quit / exit
```

A session looks like this:

```
$ python3 tools/chip_emulate.py repl --backend sdf --corner slow
...
tpv chip emulator -- type 'help' for commands, 'quit' to exit
tpv> period 40
period = 40 ns -> 25.000 MHz, high 20 ns
tpv> config seg=3333 pat=worst cansel=3
committed 0x4DFF: {'word': 19711, 'seg': (3, 3, 3, 3), 'pattern': 'worst', ...}
tpv> measure 50
PVT nom_slow_1p08V_125C (1.08 V, +125 C) | backend sdf | clk 25.000 MHz ...
  ops              50   (compared 49)
  err_cnt           0   err_rate 0.0000 per compared op
  ...
tpv> period 20
tpv> measure 50
  err_cnt          12   err_rate 0.2449 per compared op
tpv> findfail 16 32 50
    probe  16.0000 ns ( 62.500 MHz) high 8.0000 ns -> err    12 /    49
    ...
```

## Scripted sessions

Every example below is a plain command file, so a run is reproducible:

```sh
python3 tools/chip_emulate.py repl --script tools/emulator/examples/pin_level.txt
python3 tools/chip_emulate.py repl --script tools/emulator/examples/functional_check.txt
python3 tools/chip_emulate.py repl --backend sdf --corner slow \
    --script tools/emulator/examples/timing_boundary.txt
```

* `pin_level.txt` — drive the config word by hand, watch `uo[7]` (frame strobe)
  once per 19 cycles, freeze from the pin level.
* `functional_check.txt` — DUT vs oracle across all four workload classes and
  several delay-bank taps at 10 MHz; DFT `FORCE_ERR` accounting.
* `timing_boundary.txt` — same DUT at a safe and a too-fast period at one
  corner, then bisects the first-failing period.

`assert <python expression>` fails the script (and the run) when false:

```
config seg=0000 pat=prbs force_err=1
run 10
freeze 1
status
assert st.err_cnt == 9
assert st.err_seen
```

## Built-in scenarios

```sh
python3 tools/chip_emulate.py run hello      --ops 20
python3 tools/chip_emulate.py run pins       --ops 6
python3 tools/chip_emulate.py run patterns   --ops 50 --segs 3333
python3 tools/chip_emulate.py run dft        --ops 20
python3 tools/chip_emulate.py run pvtsweep   --ops 50
python3 tools/chip_emulate.py run selftest
```

`patterns` prints an error-rate table over `{0000,1111,3333}` ×
`{prbs,worst,alt,hold}` — on the SDF backend that table *is* the workload
dependence of the first-failure boundary.

## PVT sweep

```sh
python3 tools/chip_emulate.py pvtsweep --ops 50 --steps 9 \
    --segs 3333 --pat worst
```

For each corner it scans the clock period, then bisects between the slowest
failing and the fastest passing point. Measured on the archived full-cycle
post-route build (`artifacts/run-33839023290`, SDF from the same run),
`seg=3333`, `pat=worst`, 50 ops per point:

| corner | supply / temp | last failing | first passing | f_fail |
| --- | --- | --- | --- | --- |
| `nom_fast_1p32V_m40C` | 1.32 V, −40 °C | 10.5000 ns | 10.6406 ns | ≈ 94.0 MHz |
| `nom_typ_1p20V_25C` | 1.20 V, +25 °C | 15.8750 ns | 16.0625 ns | ≈ 62.3 MHz |
| `nom_slow_1p08V_125C` | 1.08 V, +125 °C | 23.6953 ns | 23.8281 ns | ≈ 42.0 MHz |

The error rate above the boundary is ~0.245 errors per compared operation for
this configuration, matching the archived `data/sdfsim.csv` point (49/199 at
14 ns, typ corner) — the emulator resolves the boundary much more finely than
that 2 ns grid.

Results are written to `runs/emulator/results/<timestamp>/`:
`pvtsweep-<corner>.json` per corner plus `pvtsweep-summary.json`, each with the
netlist/SDF identity, corner voltage/temperature, configuration and every
probed point. Use `--results-dir data/<set>` to archive a sweep deliberately.

## Python API

`TpvChip` is usable from any cocotb test module:

```python
from emulator.chip import TpvChip
from emulator.pvt import get_corner

@cocotb.test()
async def my_test(dut):
    chip = TpvChip(dut, pvt=get_corner("slow"), backend="sdf", period_ns=20.0)
    st = await chip.measure(100, seg="3333", pat="worst", cansel=3)
    assert st.err_cnt == 0
    chip.period_ns = 12.0                     # 83 MHz, 6 ns aperture
    st = await chip.measure(100, seg="3333", pat="worst", cansel=3)
    print(st.table(), st.err_rate)
```

Run such a module with the same build/launch plumbing:

```sh
python3 tools/chip_emulate.py run --module emulator.example_custom_test \
    --backend sdf --corner slow
```

Pin-level API: `chip.ui_in/uio_in/rst_n/ena/clk`, `await chip.tick(n)`,
`await chip.half(level)`, `chip.uo_out/uio_out/uio_oe`, `chip.pins()`.
Protocol API: `await chip.configure(...)`, `await chip.run_ops(n)`,
`await chip.set_freeze(True)`, `await chip.read_status()`,
`await chip.measure(ops, ...)`, `await chip.sweep_period(...)`,
`await chip.find_failure_period(p_fail, p_pass, ops=...)`.

## Adding another PVT corner

The SDF backend needs three same-build artifacts: a post-route netlist, a corner
SDF and the timing-safe standard-cell library.

1. Harden the design for the new corner (LibreLane emits
   `.../sdf/<corner>/<top>__<corner>.sdf` and `.../nl/<top>.nl.v`).
2. Either drop them under `artifacts/run-*/` / `src/runs/*/final/`, or point at
   them explicitly:

   ```sh
   python3 tools/chip_emulate.py run hello --backend sdf --period 20 \
       --sdf /path/to/corner.sdf --netlist /path/to/netlist.nl.v
   ```

3. Or add the corner to `tools/common.py` (`CORNERS`) so it appears in
   `corners`, `--corner` and `pvtsweep`. Voltage/temperature labels can also be
   given for a custom SDF.

`prepare` filters raw SDFs to IOPATH-only form and renames escaped netlist
identifiers into the cache under `runs/emulator/sdf/`; it reuses the cache until
a source hash changes.

## Notes and caveats

* The locally available netlist is the archived **full-cycle** build
  `artifacts/run-33839023290`. The merged half-cycle design's netlist is not in
  this checkout (`src/runs/` is git-ignored), so SDF numbers above describe that
  archived build. Drop the current netlist at `test/gate_level_netlist.v`,
  `src/runs/*/final/nl/*.nl.v` or `artifacts/run-*/nl/*.nl.v` and the emulator
  picks it up (pairing prefers a netlist and SDF from the same run).
* In the SDF backend `FORCE_CAN=1` is enforced: the ring oscillators are
  asynchronous zero-annotated loops and would livelock Icarus. Canary counts
  there are 0 by construction, not a measurement.
* Pin changes are applied 1 ps before the next rising edge so a same-timestamp
  pin/clock write cannot race the edge; the clock high time (the aperture) is
  unaffected.
* `read_status()` samples all 16 bytes through the auto-incrementing pointer and
  fails loudly if any pointer is missed, so a truncated readout cannot be
  mistaken for a measurement.
