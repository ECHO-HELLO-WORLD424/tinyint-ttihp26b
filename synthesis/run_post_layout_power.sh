#!/bin/sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
: "${PDK_ROOT:?Set PDK_ROOT to the ihp-sg13g2 PDK version directory}"
output_dir="$repo_root/test/sim_build/power"
image_name="ghcr.io/librelane/librelane:3.0.0.dev44"
mkdir -p "$output_dir"

iverilog -g2012 -DFUNCTIONAL -DSIM \
  -o "$output_dir/power_activity.vvp" \
  "$PDK_ROOT/ihp-sg13g2/libs.ref/sg13g2_stdcell/verilog/sg13g2_stdcell.v" \
  "$repo_root/runs/wokwi/final/nl/tt_um_echo_hello_world424_tinyint.nl.v" \
  "$repo_root/test/power_activity_tb.v"

for mode in 0 1 2 3; do
  vcd="$output_dir/mode${mode}.vcd"
  report="$output_dir/mode${mode}.power.rpt"
  vvp "$output_dir/power_activity.vvp" "+MODE=$mode" "+VCD=$vcd"
  docker run --rm \
    -v "$repo_root:$repo_root" \
    -v "$PDK_ROOT:$PDK_ROOT" \
    -w "$repo_root" \
    -e "REPO_ROOT=$repo_root" \
    -e "PDK_ROOT=$PDK_ROOT" \
    -e "ACTIVITY_VCD=$vcd" \
    -e "POWER_REPORT=$report" \
    "$image_name" sta -no_splash -exit synthesis/post_layout_power.tcl \
    > "$output_dir/mode${mode}.sta.log"
  grep -Eq '^Annotated [1-9][0-9]* pin activities\.$' "$output_dir/mode${mode}.sta.log"
  grep -Eq '^unannotated +0$' "$output_dir/mode${mode}.sta.log"
done

python3 "$repo_root/synthesis/analyze_activity.py" \
  "$output_dir/mode0.vcd" "$output_dir/mode1.vcd" \
  "$output_dir/mode2.vcd" "$output_dir/mode3.vcd"

python3 "$repo_root/synthesis/analyze_power.py" \
  "$output_dir/mode0.power.rpt" "$output_dir/mode1.power.rpt" \
  "$output_dir/mode2.power.rpt" "$output_dir/mode3.power.rpt"

for log in "$output_dir"/*.sta.log; do
  grep -E '^Annotated |^unannotated ' "$log"
done
