# RO canary loop-delay prediction (PRE_SILICON_ACTION_PLAN P1.3).
#
# The ring-oscillator loops are intentionally excluded from synchronous STA in
# src/pnr.sdc (free-running loops are not valid STA objects and P&R must not
# restructure them). Digital STA therefore yields no canary-frequency
# prediction. This flow fills that gap with an extracted, parasitic-annotated
# delay measurement of each loop:
#
#   1. Read the post-route netlist + SPEF.
#   2. Break each loop at exactly one arc (the gate's return AND input), so
#      the graph is acyclic without disturbing any cell.
#   3. set_max_delay across the broken path, then report_checks -from the
#      gate output -to the gate return input: the data-path arrival is the
#      full loop delay T_loop (cell delays + wire parasitics) for the
#      case-analyzed can_sel tap.
#   4. f_osc = 1 / (2 * T_loop); counter count = window_cycles * T_clk / (2 * T_loop).
#
# Note on accuracy: this is a static, levelized delay estimate (like a
# first-order RO model): it neglects dynamic effects (input slew dependence
# beyond NLDM, supply bounce). Measured silicon RO counts vs this prediction
# is itself part of the research comparison. A transient SPICE check of the
# extracted loops is a possible refinement (no SPICE engine is available in
# the pinned tool image; documented in tools/README.md).
#
# Inputs (env): ES_LIBS, ES_NETLIST, ES_SPEF, ES_CASES_TCL (loop cases).

define_corners nom

foreach lib $::env(ES_LIBS) {
  read_liberty $lib
}
read_verilog $::env(ES_NETLIST)
link_design tt_um_echoworld424_tpv
read_spef $::env(ES_SPEF)

# Case analysis: only the canary-relevant static state.
proc ro_case_net {val netname} {
  set nets [get_nets -quiet $netname]
  if {[llength $nets] == 0} {
    puts "RO WARNING: case net not found: $netname"
    return
  }
  foreach net $nets {
    foreach p [get_pins -of_objects $net] {
      if {[get_property -object_type pin $p direction] eq "output"} {
        set_case_analysis $val $p
      }
    }
  }
}
ro_case_net 1 {boot[1]}
ro_case_net 1 {boot[0]}
ro_case_net 0 {cfg[14]}  ;# force_can low: loops enabled
ro_case_net 1 {started}

# Break each loop at exactly one arc (the u_a2 AND input fed by `close`),
# turning the two rings into a DAG. This mirrors what the delay really is:
# the propagation around the ring from the gate output back to the gate.
set_disable_timing [get_cells -hierarchical {*u_ro_gen.u_gate.u_a2*}] -from A
set_disable_timing [get_cells -hierarchical {*u_ro_mat.u_gate.u_a2*}] -from A

set gen_from [get_pins {u_ro_gen.u_gate.u_a3/X}]
set gen_to   [get_pins {u_ro_gen.u_gate.u_a2/A}]
set mat_from [get_pins {u_ro_mat.u_gate.u_a3/X}]
set mat_to   [get_pins {u_ro_mat.u_gate.u_a2/A}]

# The cases tcl loops over can_sel values; each iteration reports both loops.
source $::env(ES_CASES_TCL)
