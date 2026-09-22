#!/bin/sh
# Find the maximum operating frequency (Fmax) of the hardened TinyInt design.
#
# This drives synthesis/fmax_sweep.tcl through the pinned LibreLane OpenSTA image
# for each PVT corner. The Tcl reads the routed netlist, nominal extracted SPEF,
# and final SDC once, then sweeps the clock period to find the smallest period
# whose worst setup slack goes negative. Fmax is the reciprocal of that period,
# so the overall Fmax is the minimum over corners (setup is worst at the slow
# corner).
#
# Prerequisites:
#   * PDK_ROOT points at the ihp-sg13g2 version directory, as for the post-layout
#     power flows.
#   * Docker can run the pinned LibreLane image (override with LIBRELANE_IMAGE).
#   * runs/wokwi/final/{nl,sdc,spef} contain the hardened design.
#
# Environment overrides:
#   CORNERS          space-separated corner list, default all three PVT corners
#   CLK_START        largest period tested in ns (20.0)
#   CLK_STOP         smallest period tested in ns (5.0)
#   CLK_STEP         coarse scan step in ns (1.0)
#   CLK_TOL          binary-search resolution in ns (0.01)
#   LIBRELANE_IMAGE  pinned LibreLane image
#
# Outputs:
#   test/sim_build/fmax/<corner>/fmax_<corner>.log   full OpenSTA log per corner
#   test/sim_build/fmax/fmax_summary.csv             one row per corner
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
: "${PDK_ROOT:?Set PDK_ROOT to the ihp-sg13g2 PDK version directory}"

image_name="${LIBRELANE_IMAGE:-ghcr.io/librelane/librelane:3.0.0.dev44}"
corners="${CORNERS:-nom_slow_1p08V_125C nom_typ_1p20V_25C nom_fast_1p32V_m40C}"
clk_start="${CLK_START:-20.0}"
clk_stop="${CLK_STOP:-5.0}"
clk_step="${CLK_STEP:-1.0}"
clk_tol="${CLK_TOL:-0.01}"

out_dir="$repo_root/test/sim_build/fmax"
mkdir -p "$out_dir"

summary="$out_dir/fmax_summary.csv"
printf 'corner,status,period_fail_ns,fmax_mhz,wns_max_ns,wns_min_ns\n' > "$summary"

overall_fmax=""
overall_corner=""

for corner in $corners; do
  corner_dir="$out_dir/$corner"
  mkdir -p "$corner_dir"
  log="$corner_dir/fmax_$corner.log"

  printf '== %s: sweeping period %s ns -> %s ns (tol %s ns) ==\n' \
    "$corner" "$clk_start" "$clk_stop" "$clk_tol"
  docker run --rm \
    -v "$repo_root:$repo_root" \
    -v "$PDK_ROOT:$PDK_ROOT" \
    -w "$repo_root" \
    -e "REPO_ROOT=$repo_root" \
    -e "PDK_ROOT=$PDK_ROOT" \
    -e "CORNER=$corner" \
    -e "CLK_START=$clk_start" \
    -e "CLK_STOP=$clk_stop" \
    -e "CLK_STEP=$clk_step" \
    -e "CLK_TOL=$clk_tol" \
    "$image_name" sta -no_splash -exit "$repo_root/synthesis/fmax_sweep.tcl" \
    > "$log" 2>&1

  result=$(grep '^FMAX_RESULT' "$log" | tail -n 1 || true)
  if [ -z "$result" ]; then
    echo "ERROR: no FMAX_RESULT for $corner; see $log" >&2
    printf '%s,ERROR,none,0,0,0\n' "$corner" >> "$summary"
    continue
  fi

  status=none
  period_fail=none
  fmax_mhz=0
  for kv in $result; do
    case "$kv" in
      status=*) status=${kv#status=} ;;
      period_fail_ns=*) period_fail=${kv#period_fail_ns=} ;;
      fmax_mhz=*) fmax_mhz=${kv#fmax_mhz=} ;;
    esac
  done

  wns_max=$(grep -m 1 '^FMAX_POINT' "$log" | sed -n 's/.*wns_max=\([-0-9.]*\).*/\1/p' || true)
  wns_min=$(grep '^FMAX_POINT' "$log" | tail -n 1 | sed -n 's/.*wns_min=\([-0-9.]*\).*/\1/p' || true)
  [ -n "$wns_max" ] || wns_max=0
  [ -n "$wns_min" ] || wns_min=0

  printf '%s,%s,%s,%s,%s,%s\n' \
    "$corner" "$status" "$period_fail" "$fmax_mhz" "$wns_max" "$wns_min" >> "$summary"

  case "$status" in
    OK|ABOVE_STOP)
      if [ -z "$overall_fmax" ] || \
         python3 -c "import sys; sys.exit(0 if $fmax_mhz < $overall_fmax else 1)"; then
        overall_fmax=$fmax_mhz
        overall_corner=$corner
      fi
      ;;
  esac
done

echo
echo "== Fmax summary =="
cat "$summary"

if [ -n "$overall_fmax" ]; then
  echo
  echo "Overall setup Fmax = $overall_fmax MHz (worst corner: $overall_corner)"
  echo "Note: ABOVE_STOP rows are lower bounds (design still passes at $clk_stop ns)."
fi
