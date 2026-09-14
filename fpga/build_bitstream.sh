#!/bin/sh
# Build the pico2-ice FPGA bitstream for the TT protocol verification harness.
# Requires host yosys, nextpnr-ice40 and icepack.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
BUILD="$ROOT/fpga/build"
mkdir -p "$BUILD"

SOURCES="$ROOT/src/tt_um_echoworld424_tpv.v $ROOT/src/tpv_cells.v $ROOT/src/tpv_delay_line.v $ROOT/src/tpv_rca16.v $ROOT/src/tpv_checker.v $ROOT/src/tpv_pattern_gen.v $ROOT/src/tpv_ro_canary.v"

echo "== yosys synthesis =="
yosys -l "$BUILD/01-synth.log" -DSYNTH -DTPV_GDELAY=1 -p \
  "read_verilog -sv $ROOT/fpga/tt_fpga_pico2ice.v $SOURCES; synth_ice40 -top tt_fpga_pico2ice -json $BUILD/tt_fpga_pico2ice.json"

echo "== nextpnr-ice40 place and route =="
nextpnr-ice40 -l "$BUILD/02-nextpnr.log" --seed 10 --freq 10 --ignore-loops \
  --package sg48 --up5k \
  --asc "$BUILD/tt_fpga_pico2ice.asc" \
  --pcf "$ROOT/fpga/pico2ice.pcf" \
  --json "$BUILD/tt_fpga_pico2ice.json"

echo "== icepack =="
icepack "$BUILD/tt_fpga_pico2ice.asc" "$BUILD/tt_um_echoworld424_tpv.bin"

ls -l "$BUILD/tt_um_echoworld424_tpv.bin"
