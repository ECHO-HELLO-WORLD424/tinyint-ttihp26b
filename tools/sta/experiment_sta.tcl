# Experiment-specific case-analyzed STA for the timing-prediction test vehicle.
#
# This is NOT the tapeout signoff STA (that is LibreLane/OpenROAD-STAPostPNR with
# the full pnr.sdc). This flow answers the research question: for a given static
# measurement configuration (cfg word case-analyzed), what is the delay of the
# runtime-sensitizable path from the pattern-generator registers (lfsr/idx,
# which change at every frame boundary) to the one-shot DUT capture registers
# (result_reg, clock-enabled by chk_start)?
#
# Inputs (environment):
#   ES_LIB        per-corner merged Liberty (artifacts/run-*/lib/<corner>/*.lib)
#   ES_NETLIST    post-route gate-level netlist (final/nl/*.nl.v)
#   ES_SPEF       extracted parasitics (final/spef/nom/*.spef)
#   ES_SDC        baseline constraints (src/pnr.sdc clock/IO/environment)
#   ES_CASES_TCL  generated Tcl that loops over case-analyzed configurations
#   ES_REPORT     output path for the delimited text report
#
# The RO canary loops are free-running asynchronous structures; their internal
# arcs are disabled exactly as in src/pnr.sdc so P&R/STA legality is preserved.
# The RO loop-delay prediction is a separate flow (tools/ro).

define_corners nom

foreach lib $::env(ES_LIBS) {
  read_liberty $lib
}
read_verilog $::env(ES_NETLIST)
link_design tt_um_echoworld424_tpv
read_spef $::env(ES_SPEF)
read_sdc $::env(ES_SDC)

# RO loops: free-running oscillators, not synchronous STA objects.
set_disable_timing [get_cells -hierarchical {*u_ro_gen*}]
set_disable_timing [get_cells -hierarchical {*u_ro_mat*}]

# Propagated clock tree, matching the CI signoff STA setup.
set_propagated_clock [get_clocks clk]

# ---------------------------------------------------------------- endpoints --
# result_reg[*] FF D pins: the one-shot capture registers.
set epins {}
foreach net [get_nets *result_reg*] {
  foreach p [get_pins -of_objects $net] {
    if {[get_property -object_type pin $p direction] eq "output"} {
      set capcell [get_cells -of_objects $p]
      set capname [get_property -object_type cell $capcell full_name]
      set dpin [get_pins "$capname/D"]
      if {[llength $dpin]} { lappend epins [lindex $dpin 0] }
    }
  }
}
puts "ES endpoints ([llength $epins]): [llength $epins] pins"

# -------------------------------------------------------------- startpoints --
# Pattern-generator runtime registers (lfsr/idx change at every frame load).
set spins {}
foreach netpat {{*u_pat.lfsr*} {*u_pat.idx*}} {
  foreach net [get_nets [lindex $netpat 0]] {
    foreach p [get_pins -of_objects $net] {
      if {[get_property -object_type pin $p direction] eq "output"} {
        lappend spins $p
      }
    }
  }
}
puts "ES startpoints ([llength $spins]): [llength $spins] pins"

# ------------------------------------------------------------- case analysis --
# Static measurement state (see tools/sta/run_experiment_sta.py for values):
#   cfg[15:0] per configuration, rst_n=1, ena=1, freeze=0 (ui_in[7]),
#   boot=3 (config committed), oe_cnt=2 (uio switched to output), started=1.
# frame_cnt/win_cnt/win_done/err_cnt/ops_cnt/ro counts stay dynamic: they are
# runtime state, and none of them lies on the operand->capture path.
proc es_case_net {val netname} {
  set nets [get_nets -quiet $netname]
  if {[llength $nets] == 0} {
    puts "ES WARNING: case net not found: $netname"
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

proc es_case_pins {val pins} {
  foreach p $pins { set_case_analysis $val $p }
}

es_case_pins 1 [get_ports {rst_n}]
es_case_pins 1 [get_ports {ena}]
es_case_pins 0 [get_ports {ui_in[7]}]  ;# freeze low while measuring

# Saturated boot/status registers (constant after the first few cycles).
es_case_net 1 {boot[1]}
es_case_net 1 {boot[0]}
es_case_net 1 {oe_cnt[1]}
es_case_net 0 {oe_cnt[0]}
es_case_net 1 {started}

# ------------------------------------------------------------------ reports --
# The case loop is supplied by ES_CASES_TCL (generated per corner by the
# driver). Each iteration prints a ==CASE header and two reports:
#   ES-R2R   : runtime-sensitizable pattern-register -> result_reg path
#   ES-GLOBAL: worst path to result_reg from any startpoint (cross-check)
source $::env(ES_CASES_TCL)
