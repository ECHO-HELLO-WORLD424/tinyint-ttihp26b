# Project Guide for Coding Agents

This file applies to the entire repository. Read it together with
[`PRE_SILICON_ACTION_PLAN.md`](PRE_SILICON_ACTION_PLAN.md) before changing RTL,
constraints, tests, or research claims.

## Project goal

This repository implements a 1x1 Tiny Tapeout timing-prediction test vehicle for the
IHP SG13G2 open PDK and the `ttihp26b` shuttle. The chip is intended to support a
pre-silicon/post-silicon research study, not merely to demonstrate a working arithmetic
unit.

The primary research question is:

> How accurately can extracted pre-silicon timing analysis and two low-cost on-chip
> delay proxies predict the workload-dependent first-failure boundary of an arithmetic
> carry path across voltage, temperature, frequency, and configured path length?

The intended contribution is experimental quantification rather than a novel canary
architecture. The final work should compare:

- Case-analyzed, post-route extracted STA predictions.
- A generic inverter ring-oscillator canary.
- A structure-matched ring-oscillator canary.
- Actual DUT error-rate boundaries measured on silicon.
- Uncalibrated prediction versus a predeclared one-point calibration method.

Useful outputs include prediction error, missed-failure probability, false-warning
rate, guardband cost, workload dependence, and an open pre/post-silicon dataset.

## Submission specification

- Process and shuttle: IHP SG13G2, Tiny Tapeout `ttihp26b`.
- Tile size: `1x1`.
- Nominal maximum submitted clock: 50 MHz (`20 ns` period).
- HDL: synthesizable Verilog.
- Top module: `tt_um_echoworld424_tpv`.
- Tiny Tapeout metadata: `info.yaml`.
- LibreLane design configuration: `src/config.json`.
- Generated Tiny Tapeout floorplan configuration: `src/user_config.json`.
- Signoff/P&R constraints: `src/pnr.sdc`.
- Routing maximum layer: `TopMetal1`.
- Supply names: `VPWR` and `VGND`.

Source files declared in `info.yaml` and `test/Makefile` must stay synchronized. A new
synthesizable source file is not part of CI or simulation until it is added to both.

## Implemented architecture

The design contains four coupled measurement components:

1. `tpv_rca16`: a 16-bit ripple-carry DUT split into four 4-bit segments. Configurable
   inverter-pair delay banks are inserted between segments and after the final carry.
2. `tpv_checker`: a short-path, bit-serial 17-bit reference adder used as the oracle.
3. `tpv_ro_gen`: a generic inverter-line ring oscillator with a windowed edge counter.
4. `tpv_ro_match`: a ring oscillator intended to resemble the DUT's delay-bank and
   full-adder structure.

`tpv_pattern_gen` supplies PRBS, worst-case-carry, carry-free alternating, and static
hold patterns. The top module owns configuration capture, frame control, DUT capture,
error/operation counters, canary windows, freeze behavior, and serial status readout.

### Configuration and external protocol

The 16-bit configuration word is `{uio_in, ui_in}` while `rst_n` is low:

| Bits | Meaning |
| --- | --- |
| `[1:0]`, `[3:2]`, `[5:4]`, `[7:6]` | Delay selection for DUT segments 0–3 |
| `[9:8]` | Pattern: PRBS, worst carry, alternating, or hold |
| `[11:10]` | Canary delay selection |
| `[13:12]` | Canary window: 2^8, 2^10, 2^12, or 2^14 clock cycles |
| `[14]` | `FORCE_CAN` test mask |
| `[15]` | `FORCE_ERR` DUT error-injection test bit |

The host must keep configuration pins stable through the first three clocks after
releasing reset. After boot, `uio` changes from input to the status-byte output. During
measurement, `ui_in[7]` is `FREEZE`; keep it low while running and high for quiescent
readout.

The frame counter runs from 0 through 18, so a frame is **19 clock cycles**, not 18.
Documentation, tests, and analysis must use 19 cycles per timed operation.

See `docs/info.md` for the complete pin and byte-readout protocol. If RTL behavior and
documentation disagree, investigate and fix the disagreement; do not silently choose
one as authoritative.

## Scientific and design invariants

Preserve these properties unless the task explicitly changes the experiment:

- The DUT measurement register must capture exactly once per operation and hold the
  captured value until comparison. A failed timing sample must not be overwritten by a
  later settled value.
- The checker must remain comfortably faster than the deliberately slow DUT across the
  claimed measurement range.
- Operands must remain stable during the measured capture interval and checker run.
- DUT delay cells and both RO loops are intentional structures. Do not let synthesis
  optimize inverter pairs into buffers or remove the loops.
- Ring oscillators are asynchronous and deliberately circular. Ordinary synchronous
  STA through the loops is meaningless; their timing arcs are disabled in `pnr.sdc`.
- Disabling RO timing for P&R does not provide a canary-frequency prediction. Use
  extracted transient simulation for that purpose.
- `FORCE_ERR` and `FORCE_CAN` are DFT features and must remain testable.
- Freeze must stop measurement state without corrupting readout or configuration.
- Error and operation counters saturate; do not allow silent wraparound.
- Keep the normal Tiny Tapeout top-level interface and pin directions intact.

Do not describe the globally worst STA path as the experimental timing boundary unless
it starts at runtime-changing state, ends at the one-shot DUT capture register, is
analyzed with static configuration case analysis, and has a confirmed sensitizing
sequence. The current audited global slow-corner violations start at static `cfg[8]` and
therefore do not yet meet this standard.

## Current blocking work

As of audited commit `206715252bb569430b0d8569393f12997b2a552b`, the project has two
research-blocking issues:

1. `result_reg` is enabled by `update_en` on every clock. It must become a one-shot DUT
   capture, likely using `chk_start`, and hold until comparison.
2. A separate experiment-specific STA analysis must case-analyze static configuration
   and report runtime-sensitizable operand/pattern-state-to-result paths.

The prioritized fixes, required prediction artifacts, accepted baseline, risks, and
definition of pre-silicon completion are in `PRE_SILICON_ACTION_PLAN.md`. Update that
document when a checklist item is genuinely completed.

## Repository map

| Path | Purpose |
| --- | --- |
| `src/tt_um_echoworld424_tpv.v` | Tiny Tapeout top level and measurement control |
| `src/tpv_rca16.v` | Deliberately slow arithmetic DUT |
| `src/tpv_delay_line.v` | Selectable DUT delay banks |
| `src/tpv_cells.v` | Preserved SG13G2/simulation cell wrappers |
| `src/tpv_checker.v` | Bit-serial oracle |
| `src/tpv_pattern_gen.v` | Workload/pattern generation |
| `src/tpv_ro_canary.v` | Generic and matched RO canaries/counters |
| `src/config.json` | Project-specific LibreLane overrides |
| `src/pnr.sdc` | Clock, IO, uncertainty, and RO-loop timing constraints |
| `info.yaml` | Tiny Tapeout submission metadata and source list |
| `docs/info.md` | User-facing datasheet and operating protocol |
| `docs/research-proposal.md` | Research framing and experiment plan |
| `test/test.py` | Cocotb RTL and functional gate-level regression |
| `test/tb.v` | Simulation wrapper and waveform setup |
| `test/Makefile` | Icarus/cocotb RTL and GL build rules |
| `test/strip_ro_cells.py` | Removes RO combinational loops for zero-delay GL tests |
| `.github/workflows/` | RTL, GDS, docs, and optional FPGA CI |
| `.devcontainer/` | Reproducible development-tool environment |

Generated hardening output under `runs/`, the copied `tt/` support-tools checkout,
waveforms, cocotb results, and `test/gate_level_netlist.v` are intentionally ignored.
Do not assume a clean checkout contains them.

## Development environment

Use the repository devcontainer for HDL and physical-design work. Do not install or
silently substitute host tool versions when the devcontainer is available.

The devcontainer provides or configures:

- Icarus Verilog, Verilator, GTKWave, and Verible.
- Python virtual environment `/ttsetup/venv` with cocotb/test dependencies.
- LibreLane and the IHP PDK environment (`PDK=ihp-sg13g2`).
- Docker-in-Docker for tools that require containers.
- A working copy of Tiny Tapeout support tools at `tt/`, populated at container start.

The shell activates `/ttsetup/venv` through `.bashrc`. If a noninteractive command does
not have the environment activated, explicitly source `/ttsetup/venv/bin/activate`.

Tool provenance matters:

- `.devcontainer/Dockerfile` currently installs LibreLane `3.0.0.dev44`.
- The audited GitHub GDS artifact reported LibreLane `3.0.5`.
- `TT_SUPPORT_TOOLS_BRANCH` defaults to mutable `main`, and the base image tag is also
  mutable.

Record exact versions, PDK revision, Git commit, and artifact hashes for any result used
in the report. Do not combine local and CI metrics without labeling their provenance.

## Local verification

Run commands from inside the devcontainer unless only inspecting text.

### RTL regression

```sh
cd test
make clean
make
```

The expected audited baseline is 9 passing cocotb tests. Inspect `test/results.xml`; CI
also checks it explicitly because the simulator make rules may return success even when
a cocotb test fails.

To inspect a waveform:

```sh
cd test
gtkwave tb.fst tb.gtkw
```

### Functional gate-level regression

Place the hardened synthesized gate-level netlist at
`test/gate_level_netlist.v`, then run:

```sh
cd test
make clean
make GATES=yes
```

The audited baseline is 8 passes and 1 intentional skip. This is a **zero-delay
functional** GL test:

- Specify blocks are patched out.
- SDF is not annotated.
- RO combinational loop cells are stripped, and their counters remain zero.

It validates synthesized configuration, control, counters, and readout. It does not
predict DUT failure frequency or ring-oscillator frequency. Maintain a separate flow
for SDF timing tests and extracted RO/path simulation.

### Formatting and lint

Use Verible from the devcontainer for Verilog formatting. Keep code compatible with
the Verilog flow already used by Icarus, Yosys, and Tiny Tapeout CI. Treat newly
introduced width, latch, undriven, multidriver, or unconnected warnings as regressions.
PDK black-box `TIMESCALEMOD` warnings may be documented separately.

## Hardening and signoff

GitHub Actions is the canonical Tiny Tapeout hardening path:
`.github/workflows/gds.yaml` invokes `TinyTapeout/tt-gds-action@ttihp26b` with the
`ihp-sg13g2` PDK. It also runs precheck, functional GL tests, and the layout viewer.

Use the support tools copied to `tt/` for local hardening. Before assuming a command-line
interface, inspect the installed version:

```sh
python tt/tt_tool.py --help
```

Local hardening writes generated data under ignored directories such as `runs/`. Keep
those products out of source commits unless adding a deliberate, small manifest or
research dataset.

For any RTL, cell-wrapper, constraint, source-list, clock, or floorplan change, require
a fresh hardening run. At minimum inspect:

- Tiny Tapeout precheck.
- Synthesis/linter warnings.
- Setup and hold by corner, including startpoint and endpoint.
- Max fanout, slew, and capacitance checks.
- DRC, Magic DRC, LVS, antenna, and power-grid checks.
- Utilization, congestion, routing, and final cell counts.
- Preservation and physical connectivity of both RO loops and DUT delay banks.
- Functional gate-level regression from the newly generated netlist.

Do not weaken signoff constraints merely to make CI green or hide the deliberate slow
path. Keep conservative tapeout signoff separate from experiment-specific case-analyzed
STA.

## Inspecting CI with GitHub CLI

The repository is `ECHO-HELLO-WORLD424/tinyint-ttihp26b`. Use `gh` to inspect the exact
commit's workflows and artifacts rather than relying only on badges or copied metrics.

List recent GDS runs:

```sh
gh run list \
  --repo ECHO-HELLO-WORLD424/tinyint-ttihp26b \
  --workflow gds.yaml \
  --branch proposal-canary \
  --limit 10
```

Inspect one run and its jobs:

```sh
gh run view RUN_ID \
  --repo ECHO-HELLO-WORLD424/tinyint-ttihp26b
```

List artifacts before choosing what to download:

```sh
gh api repos/ECHO-HELLO-WORLD424/tinyint-ttihp26b/actions/runs/RUN_ID/artifacts \
  --jq '.artifacts[] | [.name, .size_in_bytes, .expired] | @tsv'
```

Download an artifact to a temporary, explicit directory:

```sh
gh run download RUN_ID \
  --repo ECHO-HELLO-WORLD424/tinyint-ttihp26b \
  --name GDS_logs \
  --dir /tmp/tpv-gds-RUN_ID
```

Use `gh run view RUN_ID --log-failed` for failing logs. For a successful job whose
detailed metrics are needed, resolve its job ID from `gh run view` and use
`gh run view --job JOB_ID --log`. Artifact names can change with action revisions, so
always list them first.

When reporting CI evidence, record the commit SHA, run URL/ID, job result, tool/PDK
version from the artifact, and hashes of the files actually analyzed.

## Change and verification policy

Before editing:

- Read the relevant RTL, test, constraints, and user documentation together.
- Check `git status`; preserve unrelated user changes and generated artifacts.
- Identify whether the change affects functional correctness, experiment validity,
  physical structure, external protocol, or only documentation.

When editing:

- Prefer small, reviewable changes.
- Do not replace structural DUT/RO RTL with behaviorally equivalent code without
  checking synthesized structure; physical structure is part of the experiment.
- Preserve `dont_touch`/cell-wrapper mechanisms unless a fresh netlist and layout prove
  the intended chains and loops survive.
- Keep reset release, three-cycle configuration commit, `uio_oe` transition, freeze,
  frame alignment, first-error capture, and saturating-counter behavior covered by
  tests.
- Update `info.yaml`, `docs/info.md`, `docs/research-proposal.md`, and tests whenever an
  externally visible protocol or scientific claim changes.
- Use consistent units: nanoseconds, megahertz, volts, degrees Celsius, cycles, and
  errors per operation.

Verification should be proportional to impact:

| Change | Minimum verification |
| --- | --- |
| Documentation only | Cross-check RTL/config and render/read Markdown |
| Test-only | Run affected test target |
| Pure control RTL | RTL regression and functional GL after synthesis |
| DUT, checker, RO, cell wrapper, or constraint | RTL, synthesis/GL, fresh hardening/signoff, structural inspection |
| Experimental STA/model script | Reproducible fixture, machine-readable output, sanity check against raw timing report |
| Pin/config/readout protocol | RTL/GL regression plus corresponding docs and host-protocol update |

After editing, summarize changed files, commands run, results, any unrun checks, and
whether generated CI artifacts are from the same commit.

## Research data and reporting

Pre-silicon predictions must be produced before looking at corresponding post-silicon
outcomes. Store machine-readable raw/intermediate data separately from derived plots.
Every dataset should include:

- Git commit and build/artifact identity.
- Tool, PDK, library, and corner identity.
- DUT segment selections, pattern, canary selection, and window.
- Voltage, temperature, clock frequency/period, and relevant uncertainty.
- Timing startpoint/endpoint or physical loop identity.
- Prediction method, calibration state, units, and model version.

Do not silently discard negative results, failed runs, or configurations outside the
measurement range. Document exclusions and distinguish measured facts from inferences.
If only one die is available, describe the study as within-die PVT/workload validation,
not process-distribution characterization.

## Definition of done

A change is complete only when its relevant tests pass and its claims are supported by
artifacts from the same source revision. The overall pre-silicon project is not complete
until every item in the definition-of-complete checklist in
`PRE_SILICON_ACTION_PLAN.md` is satisfied, including one-shot capture, experiment STA,
sensitizing timed simulation, extracted RO prediction, frozen analysis/data protocols,
and an archived final build manifest.

