#!/bin/sh
# Cycle-peak power analysis for the TinyInt comparison vehicle.
#
# Extends the whole-trace average flow in run_post_layout_power.sh by measuring
# each of the highest-activity clock windows separately, so the peak cycle
# average power can be reported alongside the trace average.
#
# Prerequisites:
#   * PDK_ROOT points at the ihp-sg13g2 version directory (same as the average
#     power flow).
#   * The whole-trace average flow has been run, so that
#     test/sim_build/power/mode{0..3}.power.rpt exist for the peak/average
#     comparison. This script builds the VCDs itself if they are missing.
#   * Docker can run the pinned LibreLane image (override with LIBRELANE_IMAGE).
#
# Environment overrides:
#   TOP_K            number of highest-activity windows measured per mode (32)
#   LIBRELANE_IMAGE  pinned LibreLane image
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
: "${PDK_ROOT:?Set PDK_ROOT to the ihp-sg13g2 PDK version directory}"
top_k=${TOP_K:-32}
image_name="${LIBRELANE_IMAGE:-ghcr.io/librelane/librelane:3.0.0.dev44}"

design_name=tt_um_echo_hello_world424_tinyint
power_dir="$repo_root/test/sim_build/power"
peak_dir="$repo_root/test/sim_build/peak"
mkdir -p "$power_dir" "$peak_dir"

# 1. Gate-level activity VCDs (identical stimulus in every architecture mode).
if [ ! -f "$power_dir/power_activity.vvp" ]; then
  iverilog -g2012 -DFUNCTIONAL -DSIM \
    -o "$power_dir/power_activity.vvp" \
    "$PDK_ROOT/ihp-sg13g2/libs.ref/sg13g2_stdcell/verilog/sg13g2_stdcell.v" \
    "$repo_root/runs/wokwi/final/nl/$design_name.nl.v" \
    "$repo_root/test/power_activity_tb.v"
fi
for mode in 0 1 2 3; do
  [ -f "$power_dir/mode$mode.vcd" ] || \
    vvp "$power_dir/power_activity.vvp" "+MODE=$mode" "+VCD=$power_dir/mode$mode.vcd"
done

# 2. Rank windows, emit single-window VCD slices, measure each slice through the
#    routed netlist and nominal SPEF, then aggregate the peak.
docker run --rm \
  -v "$repo_root:$repo_root" \
  -v "$PDK_ROOT:$PDK_ROOT" \
  -w "$repo_root" \
  -e "REPO_ROOT=$repo_root" \
  -e "PDK_ROOT=$PDK_ROOT" \
  -e "TOP_K=$top_k" \
  "$image_name" bash -lc '
    set -eu
    spef="$REPO_ROOT/runs/wokwi/final/spef/nom/tt_um_echo_hello_world424_tinyint.nom.spef"
    peak="$REPO_ROOT/test/sim_build/peak"
    for mode in 0 1 2 3; do
      python3 "$REPO_ROOT/synthesis/peak_activity.py" \
        --vcd "$REPO_ROOT/test/sim_build/power/mode$mode.vcd" \
        --spef "$spef" --outdir "$peak" --prefix "mode$mode" \
        --window-ps 20000 --begin-ps 0 --top-k "$TOP_K"
      while IFS=, read -r rank window begin end flips energy slice; do
        [ "$rank" = rank ] && continue
        ACTIVITY_VCD="$peak/$slice" \
        POWER_REPORT="$peak/$slice.rpt" \
          sta -no_splash -exit "$REPO_ROOT/synthesis/peak_power.tcl" \
          > "$peak/$slice.log" 2>&1
      done < "$peak/mode$mode.candidates.csv"
    done
    python3 "$REPO_ROOT/synthesis/analyze_peak.py" \
      --peakdir "$peak" --powerdir "$REPO_ROOT/test/sim_build/power"
  '
