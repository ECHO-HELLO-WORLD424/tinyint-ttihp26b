# RO canary loop-delay prediction (PRE_SILICON_ACTION_PLAN P1.3).
#
# The ring-oscillator loops are intentionally excluded from synchronous STA in
# src/pnr.sdc (free-running loops are not valid STA objects and P&R must not
# restructure them). Digital STA therefore yields no canary-frequency
# prediction. This flow fills that gap with an extracted, parasitic-annotated
# delay measurement of each loop:
#
#   1. Read the post-route netlist + SPEF.
#   2. Break each loop at exactly one arc, so the graph is acyclic without
#      disturbing any cell.
#   3. set_max_delay across the broken path, then report_checks between the
#      break pins: the data-path arrival is the measured segment delay
#      (cell delays + wire parasitics) for the case-analyzed can_sel tap.
#   4. The full loop period is the sum of BOTH segments around the ring:
#        line segment: u_a3/X (nand_out) -> line -> tail -> u_close -> close
#                      -> u_a2/A            (loop broken at u_a2 A->X)
#        gate segment: u_a2/A -> u_a2/X (g2) -> u_a3/B -> u_a3/X (nand_out)
#                      (loop broken at u_close A->Y)
#      f_osc = 1 / (2 * T_loop); counter count = window_cycles * T_clk / (2 * T_loop).
#
# The driver (tools/run_ro_predict.py) runs this flow twice per corner,
# selecting the segment via ES_RO_MODE:
#   ES_RO_MODE=line : break at u_gate.u_a2 A->X; report the line/tail path
#                     from nand_out (u_a3/X) back to the gate input (u_a2/A).
#   ES_RO_MODE=gate : break at u_close A->Y; report the gate-return segment
#                     from u_a2/A through u_a2 A->X and u_a3 B->X to nand_out
#                     (u_a3/X). The two gate cells at the loop break are part
#                     of the physical loop and must be counted (see
#                     PRE_SILICON_ACTION_PLAN P1.3 refinement).
#
# Note on accuracy: this is a static, levelized delay estimate (like a
# first-order RO model): it neglects dynamic effects (input slew dependence
# beyond NLDM, supply bounce). Measured silicon RO counts vs this prediction
# is itself part of the research comparison. A transient SPICE check of the
# extracted loops is a possible refinement (no SPICE engine is available in
# the pinned tool image; documented in docs/prediction-model.md).
#
# Inputs (env): ES_LIBS, ES_NETLIST, ES_SPEF, ES_CASES_TCL (loop cases),
# ES_RO_MODE (line|gate segment, see above).

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

# Break each loop at exactly one arc, turning the rings into DAGs. The break
# arc is always OUTSIDE the segment being measured, so the segment spans the
# physical loop closure (u_close -> close -> u_a2/A -> g2 -> u_a3/B -> nand_out).
if {$::env(ES_RO_MODE) eq "line"} {
  # Break at the gate return AND input: the line/tail path from nand_out
  # ends at u_a2/A and includes u_close and the close net wire.
  set_disable_timing [get_cells -hierarchical {*u_ro_gen.u_gate.u_a2*}] -from A
  set_disable_timing [get_cells -hierarchical {*u_ro_mat.u_gate.u_a2*}] -from A
} elseif {$::env(ES_RO_MODE) eq "gate"} {
  # Break at u_close: the gate-return segment (u_a2/A -> u_a3/X, through
  # u_a2 A->X and u_a3 B->X) is measurable; the line path dead-ends at
  # u_close/A and is measured by the line mode instead.
  set_disable_timing [get_cells -hierarchical {*u_ro_gen.u_close*}]
  set_disable_timing [get_cells -hierarchical {*u_ro_mat.u_close*}]
} else {
  error "ES_RO_MODE must be 'line' or 'gate' (got: $::env(ES_RO_MODE))"
}

# The cases tcl loops over can_sel values; each iteration reports both loops
# with the pins appropriate for the selected ES_RO_MODE.
source $::env(ES_CASES_TCL)
