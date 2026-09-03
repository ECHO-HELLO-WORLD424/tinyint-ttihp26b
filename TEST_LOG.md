# TinyInt verification and hardening command log

This file records every verification and hardening command run while
implementing the multi-stage accumulator. Commands are run from the repository
root unless the entry says otherwise. An entry is updated with its observed
result after the command completes.

## Baseline audit

### B01 — Existing full RTL regression

```sh
make test=ALL
```

Purpose: establish that the pre-change conventional implementation and all
existing leaf/integration tests pass before adding the dynamic accumulator.

Result: environment failure (not a design failure). The macOS host has
`iverilog`, but not the repository's Cocotb environment: `cocotb-config` was
not found and Cocotb's `Makefile.sim` could not be included. Per the project
setup, subsequent verification commands are run in the dev container.

### B02 — Existing full RTL regression in the project toolchain

```sh
docker exec charming_golick bash -lc \
  'source /ttsetup/venv/bin/activate && \
   cd /workspaces/tinyint-ttihp26b && make test=ALL'
```

Purpose: repeat B01 using the pinned simulator and Python dependencies installed
in the project dev container.

Result: PASS. Icarus Verilog 13.0 and Cocotb 2.0.1 ran 20 tests; all
20 passed with 0 failures and 0 skips. Coverage included both 256-case
multiplier spaces, both 256-case extension spaces, 10,000 randomized
accumulator control cycles, streaming integration, read timing, mode latching,
counter saturation, completion semantics, and asynchronous reset.

## Dynamic accumulator leaf

### D01 — Dynamic leaf compile and Verilog lint

```sh
docker exec charming_golick bash -lc \
  'source /ttsetup/venv/bin/activate && \
   cd /workspaces/tinyint-ttihp26b && \
   iverilog -g2012 -s tiny_int_dynamic_accumulator \
     -o /tmp/tiny_int_dynamic_accumulator.vvp \
     src/tiny_int_dynamic_accumulator.v && \
   verible-verilog-lint src/tiny_int_dynamic_accumulator.v'
```

Purpose: reject syntax/elaboration errors, implicit nets, and lint violations
in the new leaf before running behavioral tests.

Result: FAIL (style only). Elaboration completed, then Verible reported that
the two helper functions needed explicit lifetimes and recommended SystemVerilog
`always_comb` instead of the repository-wide Verilog-compatible `always @(*)`
style. The function declarations were corrected. The `always-comb` rule is
narrowly waived in the rerun to retain compatibility with the existing `.v`
sources and synthesis flow.

### D01b — Dynamic leaf compile and lint after corrections

```sh
docker exec charming_golick bash -lc \
  'source /ttsetup/venv/bin/activate && \
   cd /workspaces/tinyint-ttihp26b && \
   iverilog -g2012 -s tiny_int_dynamic_accumulator \
     -o /tmp/tiny_int_dynamic_accumulator.vvp \
     src/tiny_int_dynamic_accumulator.v && \
   verible-verilog-lint --rules=-always-comb \
     src/tiny_int_dynamic_accumulator.v'
```

Purpose: confirm the corrected function declarations and all non-waived lint
rules are clean while preserving the repository's combinational RTL style.

Result: PASS. Icarus elaboration and every enabled Verible rule completed with
no diagnostics.

### D02 — Dynamic leaf directed and randomized RTL regression

```sh
docker exec charming_golick bash -lc \
  'source /ttsetup/venv/bin/activate && \
   cd /workspaces/tinyint-ttihp26b && \
   make test=tiny_int_dynamic_accumulator'
```

Purpose: verify reset/control priority, all carry/borrow cascade depths, every
raw product at representative states, exact per-stage write enables, overflow,
and 60,000 back-to-back randomized additions across all modes and signs.

Result: FAIL (testbench control defect). Three of four tests passed, including
all directed cascades and the 60,000-cycle randomized state model. The
representative-state combinational sweep left `accumulate` asserted while its
background clock ran, so the supposedly fixed state changed between products.
The test was corrected to deassert `accumulate`; stage-enable behavior remains
covered by the directed and randomized clocked tests.

### D02b — Corrected dynamic leaf RTL regression

```sh
docker exec charming_golick bash -lc \
  'source /ttsetup/venv/bin/activate && \
   cd /workspaces/tinyint-ttihp26b && \
   make test=tiny_int_dynamic_accumulator'
```

Purpose: rerun the complete leaf suite after correcting the fixed-state
combinational testbench control.

Result: PASS. All 4 tests passed: reset/priority; directed event cascades;
23,040 representative-state raw-product/sign checks; and 60,000 consecutive
randomized updates with exact arithmetic, carry, overflow, sticky state, and
per-stage enable checks.

### D03 — Exhaustive dynamic one-step RTL space

```sh
docker exec charming_golick bash -lc \
  'cd /workspaces/tinyint-ttihp26b && \
   mkdir -p test/sim_build/dynamic_exhaustive_rtl && \
   iverilog -g2012 -s dynamic_accumulator_exhaustive_tb \
     -o test/sim_build/dynamic_exhaustive_rtl/sim.vvp \
     src/tiny_int_dynamic_accumulator.v \
     test/dynamic_accumulator_exhaustive_tb.v && \
   vvp test/sim_build/dynamic_exhaustive_rtl/sim.vvp'
```

Purpose: exhaust every 8-, 12-, and 16-bit active-region residue against all
256 raw products under both zero- and sign-extension. High regions rotate
through cold-stage patterns including zero, `f`, multi-nibble wrap, all-one,
and alternating states. This covers 35,782,656 exact one-step additions.

Result: PASS. Boundary summaries reported 256/4,096/65,536 residues complete,
followed by the overall PASS marker. All 35,782,656 one-step combinations
matched the independent full-width arithmetic reference.

### D04 — Unbounded formal leaf equivalence

```sh
docker exec charming_golick docker run --rm \
  -v /workspaces/tinyint-ttihp26b:/work \
  -w /work/formal ghcr.io/librelane/librelane:3.0.0.dev44 \
  sby -f tiny_int_dynamic_accumulator_equivalence.sby
```

Purpose: use ABC PDR induction to prove that the dynamic and conventional
leaves have identical combinational results, carry, overflow event, registered
state, and sticky overflow for an unbounded arbitrary legal sequence. The
proof covers all three boundaries, both sign interpretations, all raw products,
and arbitrary clear/load/accumulate control streams.

Result: PASS. SymbiYosys 0.54 with ABC PDR proved all five assertions
inductively in four frames and produced no counterexample.

### D05 — Synthesize and structurally check the dynamic leaf

```sh
docker exec charming_golick docker run --rm \
  -v /workspaces/tinyint-ttihp26b:/work -w /work \
  ghcr.io/librelane/librelane:3.0.0.dev44 sh -lc \
  'mkdir -p test/sim_build/dynamic_gate && \
   yosys -p "read_verilog -sv src/tiny_int_dynamic_accumulator.v; \
     hierarchy -check -top tiny_int_dynamic_accumulator; \
     synth -top tiny_int_dynamic_accumulator; check; stat; \
     write_verilog -noattr test/sim_build/dynamic_gate/gate.v"'
```

Purpose: lower the leaf through Yosys technology-independent gate synthesis,
fail on structural problems, report the mapped logic/register inventory, and
emit the synthesized netlist used by the next gate-level regressions.

Result: PASS. Yosys 0.54 reported 0 structural problems, 0 inferred
processes/memories, and 414 generic mapped cells. The sequential inventory is
exactly 21 asynchronous-reset enabled flip-flops: 20 accumulator bits plus the
sticky overflow flag.

### D06 — Dynamic synthesized-gate directed/randomized regression

```sh
docker exec charming_golick bash -lc \
  'source /ttsetup/venv/bin/activate && \
   cd /workspaces/tinyint-ttihp26b && \
   make -C test test=tiny_int_dynamic_accumulator \
     SIM_BUILD=sim_build/dynamic_gate_cocotb \
     DYNAMIC_ACCUMULATOR_SOURCE=/workspaces/tinyint-ttihp26b/test/sim_build/dynamic_gate/gate.v'
```

Purpose: rerun the complete clocked/directed/randomized leaf suite with the
dynamic accumulator replaced by its synthesized gate netlist.

Result: PASS. The same four tests and 60,000-cycle randomized state model all
passed against the 414-cell synthesized netlist.

### D07 — Exhaustive dynamic synthesized-gate one-step space

```sh
docker exec charming_golick bash -lc \
  'cd /workspaces/tinyint-ttihp26b && \
   mkdir -p test/sim_build/dynamic_gate_verilator && \
   verilator --binary --timing -Wno-fatal \
     --top-module dynamic_accumulator_exhaustive_tb \
     --Mdir test/sim_build/dynamic_gate_verilator/obj_dir \
     -o dynamic_gate_sim \
     test/sim_build/dynamic_gate/gate.v \
     test/dynamic_accumulator_exhaustive_tb.v && \
   test/sim_build/dynamic_gate_verilator/obj_dir/dynamic_gate_sim'
```

Purpose: repeat all 35,782,656 exhaustive one-step cases against the synthesized
gate netlist. Verilator's compiled timing simulation is used to keep this full
finite-space gate sweep practical.

Result: PASS. The compiled synthesized netlist passed all 35,782,656 cases and
reported a PASS marker for each boundary plus the overall suite. Verilator's
only diagnostic was the expected missing-timescale warning on Yosys-generated
Verilog; it does not affect behavior.

### D08 — Full RTL regression after dynamic-leaf completion

```sh
docker exec charming_golick bash -lc \
  'source /ttsetup/venv/bin/activate && \
   cd /workspaces/tinyint-ttihp26b && make test=ALL'
```

Purpose: ensure the new source, testbench instance, and build-manifest changes
preserve every baseline behavior while all dynamic-leaf tests remain green.

Result: PASS. All 24 RTL tests passed with 0 failures/skips after the dynamic
leaf and build/testbench changes. This closes the leaf-module checkpoint.

## State-owning core integration

### C01 — Integrated core/top compile and core lint

```sh
docker exec charming_golick bash -lc \
  'source /ttsetup/venv/bin/activate && \
   cd /workspaces/tinyint-ttihp26b && \
   iverilog -g2012 -s tt_um_echo_hello_world424_tinyint \
     -o /tmp/tinyint_core_integration.vvp src/*.v && \
   verible-verilog-lint --rules=-always-comb src/tiny_int_core.v'
```

Purpose: catch interface/elaboration mistakes across the integrated source set
and run all non-waived Verible rules on the modified state-owning core before
functional testing.

Result: FAIL (pre-existing style only). Full top-level elaboration succeeded.
Verible then flagged the core's five existing Verilog-2001 typed localparams
because its SystemVerilog style guide prefers an explicit storage keyword.
Those declarations predate this change and are valid/synthesizable Verilog;
the rule is narrowly waived with `always-comb` in the rerun.

### C01b — Integrated compile and core lint with compatibility waivers

```sh
docker exec charming_golick bash -lc \
  'source /ttsetup/venv/bin/activate && \
   cd /workspaces/tinyint-ttihp26b && \
   iverilog -g2012 -s tt_um_echo_hello_world424_tinyint \
     -o /tmp/tinyint_core_integration.vvp src/*.v && \
   verible-verilog-lint \
     --rules=-always-comb,-explicit-parameter-storage-type \
     src/tiny_int_core.v'
```

Purpose: confirm clean integrated elaboration and all lint rules other than the
two repository-wide Verilog/SystemVerilog compatibility preferences.

Result: FAIL (pre-existing naming style only). Elaboration again succeeded;
Verible's default `parameter-name-style` rule additionally rejects the existing
uppercase `COMMAND_*` localparam convention. The convention is retained for
protocol readability and that rule is added to the compatibility waivers.

### C01c — Final integrated compile and core lint rerun

```sh
docker exec charming_golick bash -lc \
  'source /ttsetup/venv/bin/activate && \
   cd /workspaces/tinyint-ttihp26b && \
   iverilog -g2012 -s tt_um_echo_hello_world424_tinyint \
     -o /tmp/tinyint_core_integration.vvp src/*.v && \
   verible-verilog-lint \
     --rules=-always-comb,-explicit-parameter-storage-type,-parameter-name-style \
     src/tiny_int_core.v'
```

Purpose: complete the core lint checkpoint with only the three documented
repository compatibility/convention rules disabled.

Result: PASS. Integrated Icarus elaboration and all enabled core lint rules
completed without diagnostics.

### C02 — Core multistage RTL regression

```sh
docker exec charming_golick bash -lc \
  'source /ttsetup/venv/bin/activate && \
   cd /workspaces/tinyint-ttihp26b && \
   python -m py_compile test/test_core_multistage.py && \
   make test=core_multistage'
```

Purpose: verify every configuration/readback encoding, matched conventional
and dynamic workloads, operand/state isolation, zero skipping, accepted-pair
semantics, stage enables, all reserved commands, and post-completion rejection.

Result: PASS. All 4 core tests passed with 0 failures/skips, including every
configuration encoding, 10,432 matched workload MACs, explicit isolation and
zero-skip checks, and all reserved/done rejection paths.

### C03 — Extended core RTL regression with overflow/random protocol coverage

```sh
docker exec charming_golick bash -lc \
  'source /ttsetup/venv/bin/activate && \
   cd /workspaces/tinyint-ttihp26b && \
   python -m py_compile test/test_core_multistage.py && \
   make test=core_multistage'
```

Purpose: rerun the core suite after adding unsigned and signed overflow tests
for all four architecture modes plus 25,000 constrained-random commands/resets
checked cycle-by-cycle against an independent architectural model.

Result: PASS. All 6 core tests passed. Coverage now includes every mode's
unsigned and signed overflow routing, 61,444 directed overflow MACs, and 25,000
model-checked random commands/resets in addition to the C02 coverage.

### C04 — Updated conventional/core-isolation regression

```sh
docker exec charming_golick bash -lc \
  'source /ttsetup/venv/bin/activate && \
   cd /workspaces/tinyint-ttihp26b && make test=tiny_int_accumulator'
```

Purpose: rerun the conventional accumulator suite after changing its integrated
datapath check to exhaust all 512 multiplier cases while requiring the dynamic
operand to remain isolated.

Result: FAIL (testbench configuration defect). Six of seven tests passed. The
updated integrated test left its previous `0xff` operand on `ui_in` during the
second `CLEAR`; the new protocol correctly interpreted that payload as
dynamic-16 with zero-skip, while the test still expected conventional mode.
The test now drives an explicit zero configuration payload before each clear.

### C04b — Corrected conventional/core-isolation regression

```sh
docker exec charming_golick bash -lc \
  'source /ttsetup/venv/bin/activate && \
   cd /workspaces/tinyint-ttihp26b && make test=tiny_int_accumulator'
```

Purpose: rerun the affected suite with an explicit conventional configuration
payload on both signed and unsigned `CLEAR` commands.

Result: PASS. All 7 tests passed, including the corrected 512-case integrated
product/isolation sweep and the original 10,000-cycle conventional leaf model.

### C05 — Synthesize and structurally check the integrated core

```sh
docker exec charming_golick docker run --rm \
  -v /workspaces/tinyint-ttihp26b:/work -w /work \
  ghcr.io/librelane/librelane:3.0.0.dev44 sh -lc \
  'mkdir -p test/sim_build/core_gate && \
   yosys -p "read_verilog -sv \
     src/int4_multiplier.v src/product_extender.v \
     src/tiny_int_accumulator.v src/tiny_int_dynamic_accumulator.v \
     src/tiny_int_core.v; hierarchy -check -top tiny_int_core; \
     synth -flatten -top tiny_int_core; check; stat; \
     write_verilog -noattr test/sim_build/core_gate/gate.v"'
```

Purpose: flatten and synthesize the complete shared datapath/core, reject
structural errors, inspect its mapped register/logic inventory, and generate
the core gate netlist for protocol-level regression.

Result: PASS. Yosys 0.54 found 0 structural problems and no processes or
memories. The core mapped to 951 generic cells with 74 resettable state bits
(73 enabled plus 1 always-written), matching the architectural register count.

### C06 — Integrated core synthesized-gate regression

```sh
docker exec charming_golick bash -lc \
  'source /ttsetup/venv/bin/activate && \
   cd /workspaces/tinyint-ttihp26b && \
   make -C test test=core_multistage \
     SIM_BUILD=sim_build/core_gate_cocotb \
     CORE_SOURCE=/workspaces/tinyint-ttihp26b/test/sim_build/core_gate/gate.v'
```

Purpose: run all configuration, matched-workload, isolation, error, all-mode
overflow, and 25,000-command random-model tests with the complete shared
datapath/core replaced by its flattened synthesized gate netlist.

Result: FAIL (gate harness elaboration only). The synthesized core removed four
unobservable RTL debug nets, so the RTL testbench's hierarchical assignments to
those nets could not bind. No simulation ran. The gate harness now avoids all
internal hierarchy; architectural behavior is tested only through pins, while
isolation is checked separately in mapped-netlist inspection.

### C06b — Architectural core synthesized-gate regression

```sh
docker exec charming_golick bash -lc \
  'source /ttsetup/venv/bin/activate && \
   cd /workspaces/tinyint-ttihp26b && \
   python -m py_compile test/test_core_multistage_gate.py && \
   make -C test test=core_multistage_gate \
     SIM_BUILD=sim_build/core_gate_cocotb \
     COMPILE_ARGS=-DCORE_GATE_TEST \
     CORE_SOURCE=/workspaces/tinyint-ttihp26b/test/sim_build/core_gate/gate.v'
```

Purpose: verify the synthesized core exclusively through architectural pins:
all configurations/modes, 32,768 matched MACs, zero skip, completion/errors,
all-mode overflow, and 15,000 random model-checked commands.

Result: PASS. All 3 synthesized-core tests passed through architectural pins:
32,768 matched-workload MACs, 18,644 directed overflow MACs, completion/error
and zero-skip cases, plus 15,000 random commands with periodic full readback.

### C07 — Full RTL regression after core completion

```sh
docker exec charming_golick bash -lc \
  'source /ttsetup/venv/bin/activate && \
   cd /workspaces/tinyint-ttihp26b && make test=ALL'
```

Purpose: close the core-module checkpoint by running every legacy, leaf,
multistage core, and architectural pin-level test together on current RTL.

Result: PASS. All 33 tests passed together with 0 failures/skips, closing the
core-module RTL/gate checkpoint.

## Composite top-level verification

### T01 — Synthesize and structurally check the complete Tiny Tapeout top

```sh
docker exec charming_golick docker run --rm \
  -v /workspaces/tinyint-ttihp26b:/work -w /work \
  ghcr.io/librelane/librelane:3.0.0.dev44 sh -lc \
  'mkdir -p test/sim_build/top_gate && \
   yosys -p "read_verilog -sv src/*.v; \
     hierarchy -check -top tt_um_echo_hello_world424_tinyint; \
     synth -flatten -top tt_um_echo_hello_world424_tinyint; \
     check; stat; \
     write_verilog -noattr test/sim_build/top_gate/gate.v"'
```

Purpose: synthesize the exact manifest-level composite design including pin
adapter, flatten it as tapeout tools will, reject structural errors, and emit
the full-top generic gate netlist for architectural pin regression.

Result: PASS. Yosys reported 0 structural problems, 0 processes/memories, 74
resettable state bits, and 972 generic cells for the complete flattened top.

### T02 — Full-top synthesized-gate regression

```sh
docker exec charming_golick bash -lc \
  'source /ttsetup/venv/bin/activate && \
   cd /workspaces/tinyint-ttihp26b && \
   make -C test GATES=yes \
     GATE_NETLIST=/workspaces/tinyint-ttihp26b/test/sim_build/top_gate/gate.v \
     SIM_BUILD=sim_build/top_gate_cocotb'
```

Purpose: run all gate-compatible architectural tests on the exact flattened
top netlist, including matched multistage workloads, error/overflow/zero-skip,
15,000 random commands, legacy streaming/read/reset cases, and mode latching.

Result: FAIL (environment path only). Simulation did not compile because the
container's default `PDK_ROOT=/home/vscode/ttsetup/pdk` does not point directly
at the versioned Ciel IHP install. The rerun supplies the resolved root that
contains `libs.ref/sg13g2_io` and `libs.ref/sg13g2_stdcell`.

### T02b — Full-top synthesized-gate regression with resolved IHP PDK

```sh
docker exec charming_golick bash -lc \
  'source /ttsetup/venv/bin/activate && \
   cd /workspaces/tinyint-ttihp26b && \
   PDK_ROOT=/home/vscode/ttsetup/pdk/ciel/ihp-sg13g2/versions/cb7daaa8901016cf7c5d272dfa322c41f024931f \
   make -C test GATES=yes \
     GATE_NETLIST=/workspaces/tinyint-ttihp26b/test/sim_build/top_gate/gate.v \
     SIM_BUILD=sim_build/top_gate_cocotb'
```

Purpose: rerun T02 with the explicit, installed IHP PDK root.

Result: PASS. With the resolved IHP model path, all 11 gate-compatible tests
passed with 0 failures/skips. Icarus emitted known unsupported specify-block
`ifnone` notices from the vendor library; `FUNCTIONAL` simulation was unaffected.

## Standalone architecture builds and isolation inspection

### S01 — Matched composite/conventional-only/dynamic-only synthesis

```sh
docker exec charming_golick docker run --rm \
  -v /workspaces/tinyint-ttihp26b:/work -w /work \
  ghcr.io/librelane/librelane:3.0.0.dev44 sh -lc \
  'mkdir -p test/sim_build/variants && \
   yosys -s synthesis/composite.ys && \
   yosys -s synthesis/conventional_only.ys && \
   yosys -s synthesis/dynamic_only.ys'
```

Purpose: synthesize the composite and both required standalone variants from
the same sources with the same Yosys recipe. Each standalone build constrains
only the elaborated architecture-select wire, allowing constant propagation to
remove the unselected accumulator without duplicating control RTL.

Result: FAIL (variant-method validation). All three Yosys runs exited cleanly,
but the two standalone outputs were byte-identical and retained only 36 flops.
The default `connect` behavior had mapped the selector name back through its
primary driver rather than overriding the selector net. The scripts now use
`connect -nomap` to constrain that exact net.

### S01b — Corrected matched standalone synthesis

```sh
docker exec charming_golick docker run --rm \
  -v /workspaces/tinyint-ttihp26b:/work -w /work \
  ghcr.io/librelane/librelane:3.0.0.dev44 sh -lc \
  'mkdir -p test/sim_build/variants && \
   yosys -s synthesis/composite.ys && \
   yosys -s synthesis/conventional_only.ys && \
   yosys -s synthesis/dynamic_only.ys'
```

Purpose: regenerate all comparison netlists with selector alias mapping
disabled so only the intended post-elaboration select wire is constrained.

Result: PASS. The outputs now differ as intended. Composite has 972 cells and
74 flops; conventional-only has 554 cells and 53 flops; dynamic-only has 728
cells and 53 flops. Each standalone build removes exactly the unselected
accumulator's 21 state bits while retaining common control/readback state.

### S02 — Automated standalone isolation/register audit

```sh
test "$(jq '[.modules[].cells[] | select(.type == "$_DFFE_PN0P_" or .type == "$_DFF_PN0_")] | length' \
  test/sim_build/variants/composite.json)" -eq 74
test "$(jq '[.modules[].cells[] | select(.type == "$_DFFE_PN0P_" or .type == "$_DFF_PN0_")] | length' \
  test/sim_build/variants/conventional_only.json)" -eq 53
test "$(jq '[.modules[].cells[] | select(.type == "$_DFFE_PN0P_" or .type == "$_DFF_PN0_")] | length' \
  test/sim_build/variants/dynamic_only.json)" -eq 53
! cmp -s test/sim_build/variants/conventional_only.v \
  test/sim_build/variants/dynamic_only.v
```

Purpose: make the selector/isolation sanity criteria executable: composite must
retain both 21-bit accumulator states, each standalone must remove exactly one,
and the two standalone netlists must not be identical.

Result: PASS. All four executable assertions succeeded: 74/53/53 flop counts
and distinct conventional-only/dynamic-only netlists.

### S03 — Both standalone synthesized-gate regressions

```sh
docker exec charming_golick bash -lc \
  'source /ttsetup/venv/bin/activate && \
   cd /workspaces/tinyint-ttihp26b && \
   PDK_ROOT=/home/vscode/ttsetup/pdk/ciel/ihp-sg13g2/versions/cb7daaa8901016cf7c5d272dfa322c41f024931f \
   make -C test GATES=yes \
     GATE_NETLIST=/workspaces/tinyint-ttihp26b/test/sim_build/variants/conventional_only.v \
     SIM_BUILD=sim_build/conventional_only_gate && \
   PDK_ROOT=/home/vscode/ttsetup/pdk/ciel/ihp-sg13g2/versions/cb7daaa8901016cf7c5d272dfa322c41f024931f \
   make -C test GATES=yes \
     GATE_NETLIST=/workspaces/tinyint-ttihp26b/test/sim_build/variants/dynamic_only.v \
     SIM_BUILD=sim_build/dynamic_only_gate'
```

Purpose: require both reduced architecture netlists to pass the same 11-test
architectural pin suite used for the composite gate netlist.

Result: PASS. Conventional-only and dynamic-only each passed all 11 gate tests
with 0 failures/skips. Both retained full arithmetic/configuration behavior
under the common architectural pin suite.

## Tiny Tapeout physical-design and release checks

### H01 — Metadata check and hardening config regeneration

```sh
docker exec charming_golick bash -lc \
  'source /ttsetup/venv/bin/activate && \
   cd /workspaces/tinyint-ttihp26b && \
   python /ttsetup/tt-support-tools/tt_tool.py \
     --project-dir . --ihp --check-docs && \
   python /ttsetup/tt-support-tools/tt_tool.py \
     --project-dir . --ihp --create-user-config'
```

Purpose: validate `info.yaml`/documentation metadata and regenerate the
LibreLane user configuration directly from the manifest before hardening, so
the physical source list cannot drift from the verified RTL list.

Result: PASS. Documentation validation succeeded and `src/user_config.json`
was regenerated with the dynamic accumulator in the manifest-derived source
list.

### H02 — Full IHP SG13G2 Tiny Tapeout hardening

```sh
docker exec charming_golick bash -lc \
  'source /ttsetup/venv/bin/activate && \
   cd /workspaces/tinyint-ttihp26b && \
   python /ttsetup/tt-support-tools/tt_tool.py \
     --project-dir . --ihp --harden'
```

Purpose: run the complete pinned LibreLane/Tiny Tapeout physical flow for the
1x1 IHP SG13G2 design: lint, synthesis, floorplan, placement, CTS, routing,
parasitic extraction, timing, stream-out, DRC, LVS, and final view generation.

Result: PASS as an intermediate physical implementation run. LibreLane
completed all 79 enabled stages and generated final GDS, DEF, LEF, extracted
SPICE, three-corner SDF/SPEF/liberty, and gate netlists. The routed design has
984 functional standard cells including the expected 74 sequential cells;
route DRC, Magic DRC, antenna, and power-grid violations are all zero. Netgen
reported `Circuits match uniquely`, with zero LVS device, net, property, pin,
or topology errors. Signoff STA is clean at the 20 ns constraint: worst setup
slack is 7.5445 ns and worst hold slack is 0.1187 ns across the three reported
corners. This run also exposed that the inherited template explicitly disabled
KLayout DRC/XOR, so those independent checks are enabled for the release rerun
logged next.

### H03 — Release hardening with independent KLayout DRC and XOR

```sh
docker exec charming_golick bash -lc \
  'source /ttsetup/venv/bin/activate && \
   cd /workspaces/tinyint-ttihp26b && \
   python /ttsetup/tt-support-tools/tt_tool.py \
     --project-dir . --ihp --harden'
```

Purpose: repeat the pinned IHP SG13G2 physical flow after enabling
`RUN_KLAYOUT_DRC` and `RUN_KLAYOUT_XOR`, making the final release satisfy both
the standard Magic/Netgen checks and independent KLayout DRC/stream-equivalence
signoff.

Result: PASS. LibreLane completed all 79 stages with the independent checks
enabled. Final metrics report 984 functional standard cells, 74 sequential
cells, 48.2791% core utilization, and 23,227 um routed wire length. Route DRC,
Magic DRC, KLayout DRC, LVS, antenna, setup, and hold violation counts are all
zero; KLayout XOR also completed. Worst three-corner setup and hold slacks
remain +7.5445 ns and +0.1187 ns respectively at the declared 20 ns clock.
The design uses one characterized clock tree with 74 sinks and no generated
RTL clocks.

### H04 — Final metrics, documentation, and submission bundle checks

```sh
docker exec charming_golick bash -lc \
  'source /ttsetup/venv/bin/activate && \
   cd /workspaces/tinyint-ttihp26b && \
   python /ttsetup/tt-support-tools/tt_tool.py \
     --project-dir . --ihp --print-stats && \
   python /ttsetup/tt-support-tools/tt_tool.py \
     --project-dir . --ihp --print-warnings && \
   python /ttsetup/tt-support-tools/tt_tool.py \
     --project-dir . --ihp --check-docs && \
   python /ttsetup/tt-support-tools/tt_tool.py \
     --project-dir . --ihp --create-tt-submission'
```

Purpose: inspect release metrics/warnings, revalidate user-facing metadata,
and materialize the exact GDS/OASIS/LEF/netlist/SPEF/stats bundle expected by
the Tiny Tapeout submission workflow.

Result: PASS. The tool reported 35.634% routed utilization and 23,227 um wire
length, documentation validation passed, and `tt_submission/` was generated
with GDS, OASIS, LEF, nominal SPEF, netlist, resolved metadata, PDK metadata,
and synthesis/metrics reports.

### H05 — Post-layout release-netlist architectural regression

```sh
docker exec charming_golick bash -lc \
  'cd /workspaces/tinyint-ttihp26b && \
   PDK_ROOT=/home/vscode/ttsetup/pdk/ciel/ihp-sg13g2/versions/cb7daaa8901016cf7c5d272dfa322c41f024931f \
   make -C test GATES=yes'
```

Purpose: rerun the entire top-level gate-compatible protocol/arithmetic suite
against the routed release netlist copied from `runs/wokwi/final/nl`, using the
matching IHP standard-cell functional models.

Result: FAIL (environment activation only). The fresh `docker exec` shell did
not inherit `/ttsetup/venv`, so `cocotb-config` was absent and Make stopped
before compilation or simulation. No design test ran. The corrected invocation
is logged next.

### H06 — Post-layout release-netlist regression with verification venv

```sh
docker exec charming_golick bash -lc \
  'source /ttsetup/venv/bin/activate && \
   cd /workspaces/tinyint-ttihp26b && \
   PDK_ROOT=/home/vscode/ttsetup/pdk/ciel/ihp-sg13g2/versions/cb7daaa8901016cf7c5d272dfa322c41f024931f \
   make -C test GATES=yes'
```

Purpose: execute H05 with the container's Cocotb/Icarus environment active.

Result: PASS, 11/11 tests. The routed 984-cell netlist passed all mode and
configuration readbacks, 32,768 cross-mode MAC comparisons, 18,644 overflow
operations, 15,000 randomized architectural commands, signed and unsigned dot
products, both completion styles, registered/back-to-back reads, counter
saturation, asynchronous reset, illegal-command handling, and mode latching.
Icarus emitted its known unsupported `ifnone` timing-path notices from the
vendor functional model; compilation and all functional checks completed.

### P01 — Activity-annotated post-layout mode comparison

```sh
docker exec charming_golick bash -lc \
  'source /ttsetup/venv/bin/activate && \
   cd /workspaces/tinyint-ttihp26b && \
   PDK_ROOT=/home/vscode/ttsetup/pdk/ciel/ihp-sg13g2/versions/cb7daaa8901016cf7c5d272dfa322c41f024931f \
   sh synthesis/run_post_layout_power.sh'
```

Purpose: simulate the routed gate netlist in conventional, dynamic-8,
dynamic-12, and dynamic-16 modes with an identical 8,192-MAC pin trace that
mixes dense, sparse, signed carry/borrow, and ramp workloads. Annotate each VCD
onto the exact routed netlist and nominal extracted SPEF in the pinned
LibreLane/OpenSTA image, emit power reports, and assert from mapped state names
that the unselected bank is static and each selected cold region toggles less
per bit than its active region.

Result: FAIL (power-script setup only). The conventional gate trace completed,
but standalone OpenSTA correctly rejected `read_liberty -corner` because the
script had not first declared that process corner. No power result or activity
assertion was accepted. Added `define_corners nom_typ_1p20V_25C`; the corrected
full run is logged next.

### P02 — Corrected activity-annotated post-layout mode comparison

```sh
docker exec charming_golick bash -lc \
  'source /ttsetup/venv/bin/activate && \
   cd /workspaces/tinyint-ttihp26b && \
   PDK_ROOT=/home/vscode/ttsetup/pdk/ciel/ihp-sg13g2/versions/cb7daaa8901016cf7c5d272dfa322c41f024931f \
   sh synthesis/run_post_layout_power.sh'
```

Purpose: repeat P01 after explicitly defining the nominal process corner
before loading its IHP liberty model.

Result: FAIL (annotation validation). Gate simulations and mapped-state
assertions completed, but OpenSTA reported `Annotated 0 pin activities`; the
dot-separated VCD scope therefore caused the four identical power estimates to
fall back to default activity. These numbers are rejected. Changed the scope
to OpenSTA's slash-separated hierarchy and added an explicit annotated-pin
report; the corrected run is logged next.

### P03 — VCD scope-corrected post-layout power comparison

```sh
docker exec charming_golick bash -lc \
  'source /ttsetup/venv/bin/activate && \
   cd /workspaces/tinyint-ttihp26b && \
   PDK_ROOT=/home/vscode/ttsetup/pdk/ciel/ihp-sg13g2/versions/cb7daaa8901016cf7c5d272dfa322c41f024931f \
   sh synthesis/run_post_layout_power.sh'
```

Purpose: repeat P02 with the VCD hierarchy expressed using OpenSTA's path
separator, and print all annotated pins so a zero-annotation fallback cannot
be mistaken for a measurement.

Result: PASS. OpenSTA annotated all 3,152 design pins/nodes in every mode with
zero unannotated pins. Mapped accumulator-state toggle totals were:

```text
mode          conventional  dyn[7:0]  dyn[11:8]  dyn[15:12]  dyn[19:16]
conventional  19037         0         0          0           0
dynamic-8     0             18227     599        107         104
dynamic-12    0             18227     599        107         104
dynamic-16    0             18227     599        107         104
```

The nonselected state bank is completely static, and higher state changes are
limited to exact carry/borrow propagation. Nominal extracted-SPEF total power
was 393.0867 uW conventional, 386.7590 uW dynamic-8, 389.0023 uW dynamic-12,
and 393.0562 uW dynamic-16. Power therefore increases monotonically with the
active boundary; dynamic-8 is 1.6097% below conventional for this composite
mixed trace. This is an estimate, not a claim about measured silicon energy.

### P04 — Self-checking post-layout activity/power rerun

```sh
docker exec charming_golick bash -lc \
  'source /ttsetup/venv/bin/activate && \
   cd /workspaces/tinyint-ttihp26b && \
   PDK_ROOT=/home/vscode/ttsetup/pdk/ciel/ihp-sg13g2/versions/cb7daaa8901016cf7c5d272dfa322c41f024931f \
   sh synthesis/run_post_layout_power.sh'
```

Purpose: repeat P03 after making annotation completeness and the expected
dynamic-8 < dynamic-12 < dynamic-16 < conventional extracted-power ordering
hard assertions in the reusable release scripts.

Result: PASS. Each trace annotated 3,152 pins/nodes with zero unannotated. Both
the mapped-state isolation assertions and extracted-power ordering assertions
passed, reproducing the P03 toggle and power figures.

### R01 — Host-script syntax and scripted interactive protocol smoke test

```sh
docker exec charming_golick bash -lc \
  'source /ttsetup/venv/bin/activate && \
   cd /workspaces/tinyint-ttihp26b && \
   python -m py_compile test/interactive.py \
     synthesis/analyze_activity.py synthesis/analyze_power.py && \
   printf "clear dynamic8 signed skip\\nmac -3 4\\nread config\\nread id\\nquit\\n" | \
     make -C test interactive'
```

Purpose: compile-check every new Python operator/analysis script and drive the
interactive shell through the implemented configuration, MAC, configuration
readback, and design-ID readback paths. This catches drift between public host
commands and the frozen pin protocol.

Result: PASS. All three Python files compile. The scripted shell accepted
`clear dynamic8 signed skip`, accumulated `-3 * 4`, returned configuration
`0x0b`, returned design ID `0x42`, and exited with Cocotb 1/1 PASS.

### R02 — Final documentation check and complete RTL regression

```sh
docker exec charming_golick bash -lc \
  'source /ttsetup/venv/bin/activate && \
   cd /workspaces/tinyint-ttihp26b && \
   python /ttsetup/tt-support-tools/tt_tool.py \
     --project-dir . --ihp --check-docs && \
   make test=ALL'
```

Purpose: validate the final edited documentation/metadata and rerun every RTL
Cocotb test together after all implementation, host, physical-analysis, and
release-document changes.

Result: PASS. Final documentation validation succeeded and the unified RTL run
reported 33/33 PASS, covering every leaf, the integrated core, and the physical
top-level protocol.

### R03 — Release artifact and repository consistency audit

```sh
git diff --check && \
! rg -n 'Result: pending' TEST_LOG.md && \
sh -n synthesis/run_post_layout_power.sh && \
python3 -m py_compile test/interactive.py \
  synthesis/analyze_activity.py synthesis/analyze_power.py && \
jq -e '.RUN_KLAYOUT_DRC == 1 and .RUN_KLAYOUT_XOR == 1' \
  src/config_merged.json && \
jq -e '.route__drc_errors == 0 and .magic__drc_error__count == 0 and
  .klayout__drc_error__count == 0 and .design__lvs_error__count == 0 and
  .antenna__violating__nets == 0 and .timing__setup_vio__count == 0 and
  .timing__hold_vio__count == 0' runs/wokwi/final/metrics.json && \
test -s tt_submission/tt_um_echo_hello_world424_tinyint.gds && \
test -s tt_submission/tt_um_echo_hello_world424_tinyint.oas && \
test -s tt_submission/tt_um_echo_hello_world424_tinyint.lef && \
test -s tt_submission/tt_um_echo_hello_world424_tinyint.v && \
test -s tt_submission/tt_um_echo_hello_world424_tinyint.nom.spef
```

Purpose: reject whitespace defects, unfinished test-log entries, invalid
release scripts, disabled independent DRC, any signoff violation metric, or a
missing/empty required submission view.

Result: FAIL (audit-command defect). The pending-marker search also matched the
literal command shown inside this Markdown entry, so the audit stopped before
the later checks. No implementation or release check failed. The anchored
replacement is logged next.

### R04 — Corrected release artifact and repository consistency audit

```sh
git diff --check && \
! rg -n '^Result: pending' TEST_LOG.md && \
sh -n synthesis/run_post_layout_power.sh && \
python3 -m py_compile test/interactive.py \
  synthesis/analyze_activity.py synthesis/analyze_power.py && \
jq -e '.RUN_KLAYOUT_DRC == 1 and .RUN_KLAYOUT_XOR == 1' \
  src/config_merged.json && \
jq -e '.route__drc_errors == 0 and .magic__drc_error__count == 0 and
  .klayout__drc_error__count == 0 and .design__lvs_error__count == 0 and
  .antenna__violating__nets == 0 and .timing__setup_vio__count == 0 and
  .timing__hold_vio__count == 0' runs/wokwi/final/metrics.json && \
test -s tt_submission/tt_um_echo_hello_world424_tinyint.gds && \
test -s tt_submission/tt_um_echo_hello_world424_tinyint.oas && \
test -s tt_submission/tt_um_echo_hello_world424_tinyint.lef && \
test -s tt_submission/tt_um_echo_hello_world424_tinyint.v && \
test -s tt_submission/tt_um_echo_hello_world424_tinyint.nom.spef
```

Purpose: run R03 with the pending-result search anchored to actual result
lines, so the documented command text cannot match itself.

Result: FAIL (host sandbox only). The command passed the diff, pending-entry,
and shell-syntax checks, then macOS system Python attempted to place bytecode
under a sandbox-denied user cache path. The same Python files already passed
R01 in the dev container. The fully containerized audit is logged next.

### R05 — Dev-container release artifact and consistency audit

```sh
docker exec charming_golick bash -lc \
  'source /ttsetup/venv/bin/activate && \
   cd /workspaces/tinyint-ttihp26b && \
   git diff --check && \
   ! grep -n "^Result: pending" TEST_LOG.md && \
   sh -n synthesis/run_post_layout_power.sh && \
   python -m py_compile test/interactive.py \
     synthesis/analyze_activity.py synthesis/analyze_power.py && \
   jq -e ".RUN_KLAYOUT_DRC == 1 and .RUN_KLAYOUT_XOR == 1" \
     src/config_merged.json && \
   jq -e ".route__drc_errors == 0 and .magic__drc_error__count == 0 and
     .klayout__drc_error__count == 0 and .design__lvs_error__count == 0 and
     .antenna__violating__nets == 0 and .timing__setup_vio__count == 0 and
     .timing__hold_vio__count == 0" runs/wokwi/final/metrics.json && \
   test -s tt_submission/tt_um_echo_hello_world424_tinyint.gds && \
   test -s tt_submission/tt_um_echo_hello_world424_tinyint.oas && \
   test -s tt_submission/tt_um_echo_hello_world424_tinyint.lef && \
   test -s tt_submission/tt_um_echo_hello_world424_tinyint.v && \
   test -s tt_submission/tt_um_echo_hello_world424_tinyint.nom.spef'
```

Purpose: execute the complete static audit inside the declared development
environment, avoiding host-specific Python cache behavior.

Result: PASS. The containerized audit completed every assertion: no diff
whitespace errors, no unfinished result entries, valid release-script syntax,
valid Python, independent DRC enabled in the merged config, zero values for all
required physical violation metrics, and every required submission view
present and nonempty.

## P3 event-scheduled variant (branch proposal/3-event-scheduled)

These entries cover the P3 research variant ("event-scheduled deferred-carry
accumulator with maintenance domain"), which replaces the conventional/dynamic
bank pair in `tiny_int_core` with `tiny_int_event_accumulator`. Commands run
from the repository root of this worktree.

### P3.V1 — Represented-value invariant equivalence

```sh
make -C test p3-equiv
```

Purpose: drive the event-scheduled accumulator and the released conventional
`tiny_int_accumulator` with identical MAC/clear/load/flush/reset streams and
check on EVERY cycle that the represented value
`{stage4,stage3,stage2,stage1,stage0} + cnt2*256 + cnt3*4096 + cnt4*65536`
(mod 2^20, counters signed) equals the golden value, that the combinational
canonical value equals the golden value, that `canonical_valid` matches the
pending counters, and that the sticky overflow flag is bit-identical. After
every stream a flush must make the stored bank equal the golden value with
all counters cleared. Workloads: the released mixed 8192-MAC signed stream
(LFSR/sparse/+7,-1/ramp quarters), unsigned 0xff 4096, signed 0x11 4096,
signed 0x00 4096, 20k randomized ops with clear/load/flush injection and
accumulate+flush coincidence, 30k unsigned 0xff carry storm, 30k signed 0xf1
borrow storm, directed nibble-boundary walks, and a mid-stream asynchronous
reset.

Result: PASS. 111,317 cycles checked with zero mismatches. Observed counter
bounds: |cnt2| <= 7 (divider bound 8; saturation guard unreachable at cadence
8), |cnt3| <= 15 and |cnt4| <= 15 only in the sustained one-sided storms,
where the lossless same-cycle saturation-guard drains keep the counters inside
[-16, +15] without ever dropping an event. Two testbench-only corrections were
made while converging: a mod-2^20 wrap legitimately pushes +/-1 out of stage 4
during canonicalization (the drop IS the modulo reduction), and the stimulus
driver must hold the addend contract (extension mode consistent with
signed_mode at the sampling edge) for the event decomposition to apply.

### P3.V2 — Maintenance-domain activity metrics

```sh
make -C test p3-metrics
```

Purpose: measure hot/cold write events, maintenance-tick (cold_we) cycles,
maximum counter magnitudes, and per-nibble toggle counts for the released
mixed 8192-MAC signed stream, with the invariant checks of P3.V1 running as a
correctness guard, followed by a 30k-MAC unsigned 0xff carry storm as a
worst-case cadence reference.

Result: PASS. Mixed stream: 8192 MACs; hot writes stage0=8192 stage1=8192;
cold writes stage2=190 stage3=12 stage4=4; cold_we = 206 of 8195 cycles
(2.51%, all divider ticks, zero out-of-order ticks); max |cnt2|=1, |cnt3|=1,
|cnt4|=1; cold bit toggles stage2=367 (baseline dynamic-8: 599), stage3=43
(107), stage4=16 (104) — 39%/60%/85% reductions. Carry storm: 30000 MACs,
cold writes 3750/102/6, cold_we 9.82% of cycles, max |cnt2|=7 |cnt3|=15
|cnt4|=15, stage3/stage4 bit toggles 0 (the counters absorb the sustained
carry stream; the guard drains fold whole +16 wraps upward).

### P3.V3 — Core-level READ protocol equivalence

```sh
make -C test p3-core-read
```

Purpose: drive the P3 core and a frozen copy of the released core
(`test/p3_ref/tiny_int_core_ref.v`, module `tiny_int_core_ref`) with identical
request streams and verify (1) every READ response byte matches the reference
for all eight selectors, including back-to-back READ bursts and READs injected
into dense MAC storms, (2) the READ response latency is bounded (asserted
<= 6 cycles; measured exactly 2), (3) MAC acceptance never stalls
(request_ready, pair_count, done, last_product, count_overflow,
protocol_error, sticky overflow, latched signed mode, and the canonical
accumulator value match continuously), (4) protocol rejection parity, and
(5) asynchronous reset clears both cores identically including the pending
response pipeline. Phases: directed transaction, unsigned/signed overflow
storms with interleaved READs, read bursts, reserved/done rejection parity,
4000 randomized commands at one request per cycle, and a mid-stream reset.

Result: PASS. One RTL bug was found and fixed during this run: the first
implementation registered `response_valid` from the second pipeline stage,
emitting responses three cycles after acceptance and misaligning them with
the captured data; corrected to the intended two-cycle latency.

### P3.V4 — Full repository regression on the variant core

```sh
make -C test test=ALL
cd test && iverilog -g2012 -o /tmp/dyn_exh.vvp \
  ../src/tiny_int_dynamic_accumulator.v dynamic_accumulator_exhaustive_tb.v \
  && vvp /tmp/dyn_exh.vvp
```

Purpose: run the complete cocotb regression (33 tests) against the variant
core and top level, plus the standalone dynamic-accumulator exhaustive
testbench for the retained leaf.

Result: PASS. TESTS=33 PASS=33 FAIL=0 after updating the released tests for
the documented two-cycle READ response latency (bounded-wait `read` helpers, a
one-iteration-delayed response check in the two constrained-random command
loops, single-cycle valid discipline in the two timing-sensitive helpers, and
replacement of the removed conventional/dynamic bank probes with the
event-accumulator probes). The dynamic exhaustive testbench passes unchanged
for all three boundaries. Verified `iverilog -Wall` compiles the variant
sources without warnings.
