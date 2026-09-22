# Clock-period sweep for the maximum operating frequency (Fmax).
#
# Reads the routed IHP SG13G2 netlist, the nominal extracted SPEF, and the final
# SDC, then repeatedly redefines the clock period and measures the worst setup
# slack. The design is considered to fail below Fmax = 1 / period_fail, where
# period_fail is the first period (to within CLK_TOL) whose setup worst slack is
# negative.
#
# The sweep is done in two passes to bound the number of re-analyses: a coarse
# linear scan finds the pass/fail bracket, then a binary search refines the
# crossing to CLK_TOL. Every point is printed on stdout as an FMAX_POINT line and
# the final answer as a single FMAX_RESULT line, so run_fmax_sweep.sh can parse
# the log without opening the design again per point.
#
# Required environment variables:
#   REPO_ROOT  repository root (contains runs/wokwi/final/...)
#   PDK_ROOT   directory containing ihp-sg13g2/libs.ref and libs.tech
#   CORNER     LibreLane corner name, one of:
#                nom_slow_1p08V_125C nom_typ_1p20V_25C nom_fast_1p32V_m40C
# Optional environment variables:
#   CLK_START  largest clock period tested, in ns (default 20.0)
#   CLK_STOP   smallest clock period tested, in ns (default 5.0)
#   CLK_STEP   coarse scan step, in ns (default 1.0)
#   CLK_TOL    binary-search period resolution, in ns (default 0.01)
#
# All FMAX_RESULT lines have the form:
#   FMAX_RESULT corner=<c> status=<OK|ABOVE_STOP|FAIL_AT_START> \
#               period_fail_ns=<p|none> fmax_mhz=<f> wns_max_ns=<w> wns_min_ns=<h>

set repo_root $::env(REPO_ROOT)
set pdk_root  $::env(PDK_ROOT)
set corner_name $::env(CORNER)
set clk_start [expr {[info exists ::env(CLK_START)] ? double($::env(CLK_START)) : 20.0}]
set clk_stop  [expr {[info exists ::env(CLK_STOP)]  ? double($::env(CLK_STOP))  : 5.0}]
set clk_step  [expr {[info exists ::env(CLK_STEP)]  ? double($::env(CLK_STEP))  : 1.0}]
set clk_tol   [expr {[info exists ::env(CLK_TOL)]   ? double($::env(CLK_TOL))   : 0.01}]

# The LibreLane corner names prefix the PVT string with "nom_"; the liberty file
# omits that prefix.
set pvt [string map {nom_ ""} $corner_name]
set liberty "$pdk_root/ihp-sg13g2/libs.ref/sg13g2_stdcell/lib/sg13g2_stdcell_$pvt.lib"

set design_name tt_um_echo_hello_world424_tinyint
set netlist "$repo_root/runs/wokwi/final/nl/$design_name.nl.v"
set sdc     "$repo_root/runs/wokwi/final/sdc/$design_name.sdc"
set spef    "$repo_root/runs/wokwi/final/spef/nom/$design_name.nom.spef"

puts "FMAX_INFO corner=$corner_name liberty=$liberty"
puts "FMAX_INFO netlist=$netlist"
puts "FMAX_INFO sdc=$sdc"
puts "FMAX_INFO spef=$spef"

define_corners $corner_name
read_liberty -corner $corner_name $liberty
read_verilog $netlist
link_design $design_name
read_sdc $sdc
read_spef -corner $corner_name $spef

# Re-create the clock at a new period. The SDC clock (20 ns) is replaced because
# create_clock redefines a clock already defined on the same pin. The transition,
# uncertainty, and propagated-clock settings are re-applied so each point is
# measured with the same constraints as the released SDC.
proc apply_clock { period } {
  create_clock -name clk -period $period [get_ports clk]
  set_clock_transition 0.1500 [get_clocks clk]
  set_clock_uncertainty 0.2500 [get_clocks clk]
  set_propagated_clock [get_clocks clk]
}

proc measure_point { corner_name period } {
  apply_clock $period
  set wns_max [sta::worst_slack -max]
  set wns_min [sta::worst_slack -min]
  puts [format "FMAX_POINT corner=%s period=%.4f wns_max=%.4f wns_min=%.4f" \
    $corner_name $period $wns_max $wns_min]
  return $wns_max
}

# Pass 1: coarse linear scan from the largest to the smallest period.
set last_pass ""
set first_fail ""
set wns_start ""
set wns_min ""
set period $clk_start
while { $period >= $clk_stop - 1.0e-9 } {
  set wns_max [measure_point $corner_name $period]
  if { $wns_start eq "" } {
    set wns_start $wns_max
    set wns_min [sta::worst_slack -min]
  }
  if { $wns_max < 0.0 } {
    set first_fail $period
    break
  }
  set last_pass $period
  set period [expr {$period - $clk_step}]
}

# Pass 2: refine the first failing period with a binary search.
if { $first_fail eq "" } {
  set fmax_mhz [expr {1000.0 / $clk_stop}]
  puts [format "FMAX_RESULT corner=%s status=ABOVE_STOP period_fail_ns=none fmax_mhz=%.4f wns_max_ns=%.4f wns_min_ns=%.4f" \
    $corner_name $fmax_mhz $wns_start $wns_min]
} elseif { $last_pass eq "" } {
  puts [format "FMAX_RESULT corner=%s status=FAIL_AT_START period_fail_ns=%.4f fmax_mhz=0.0 wns_max_ns=%.4f wns_min_ns=%.4f" \
    $corner_name $first_fail $wns_start $wns_min]
} else {
  set lo $last_pass
  set hi $first_fail
  while { [expr {$lo - $hi}] > $clk_tol } {
    set mid [expr {($lo + $hi) / 2.0}]
    set wns_max [measure_point $corner_name $mid]
    if { $wns_max < 0.0 } {
      set hi $mid
    } else {
      set lo $mid
    }
  }
  set period_fail $hi
  apply_clock $period_fail
  set wns_fail [sta::worst_slack -max]
  set tns_fail [sta::total_negative_slack -max]
  set fmax_mhz [expr {1000.0 / $period_fail}]
  puts [format "FMAX_RESULT corner=%s status=OK period_fail_ns=%.4f fmax_mhz=%.4f wns_max_ns=%.4f wns_min_ns=%.4f" \
    $corner_name $period_fail $fmax_mhz $wns_start $wns_min]
  puts [format "FMAX_FAIL_PATH corner=%s period=%.4f wns_max=%.4f tns_max=%.4f" \
    $corner_name $period_fail $wns_fail $tns_fail]
  puts "FMAX_FAIL_PATH_BEGIN"
  report_checks -path_delay max -format full_clock_expanded -digits 4
  puts "FMAX_FAIL_PATH_END"
}
