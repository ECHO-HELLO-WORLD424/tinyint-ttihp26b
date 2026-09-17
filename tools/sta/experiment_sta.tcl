# Experiment-specific case-analyzed STA for the timing-prediction test vehicle.
#
# This is NOT the tapeout signoff STA (that is LibreLane/OpenROAD-STAPostPNR with
# the full pnr.sdc). This flow answers the research question: for a given static
# measurement configuration (cfg word case-analyzed), what is the delay of the
# runtime-sensitizable path from the pattern-generator registers (lfsr/idx,
# which change at every frame boundary) to the one-shot DUT capture registers
# (result_reg, falling-edge capture gated by capture_pending)?
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
# Experiment-only clock waveform override; signoff constraints are unchanged.
if {[info exists ::env(ES_PERIOD_NS)]} {
  set t $::env(ES_PERIOD_NS)
  create_clock -name clk -period $t -waveform [list 0 [expr {$t * $::env(ES_DUTY)}]] [get_ports clk]
}

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
if {[llength $epins] != 17} { error "Expected 17 DUT capture endpoints" }
# Keep every other register endpoint in the oracle/control safety check.
set control_epins {}
foreach p [all_registers -data_pins] {
  if {[lsearch -exact $epins $p] < 0} { lappend control_epins $p }
}

# -------------------------------------------------------------- startpoints --
# Runtime pattern-state launch pins, resolved STRUCTURALLY (net names are only
# used as a cross-check, never as the discovery mechanism).
#
# Post-route synthesis flattens tpv_pattern_gen and renames the Q nets of
# eight of its sixteen LFSR flops to auto-generated names, so a name-based
# search (`*u_pat.lfsr*` / `*u_pat.idx*`) finds only 10 of the 18 state flops
# and silently drops the rest. The definition used here instead is functional:
#
#   a launch pin is a flip-flop whose Q can reach an operand input of the DUT
#   full-adder wrappers (the preserved tpv_fa .a/.b input nets) and which the
#   static measurement configuration does not case-analyze to a constant.
#
# Step 1: seed nets (preserved cell-wrapper port nets, tpv_rca16 instantiates
# 4 segments x 4 full adders, each with an `a` and a `b` operand).
set es_seeds {}
foreach pat {{*u_dut*g_fa*u_fa.a} {*u_dut*g_fa*u_fa.b}} {
  foreach n [get_nets -quiet $pat] { lappend es_seeds $n }
}
puts "ES operand seed nets: [llength $es_seeds]"
if {[llength $es_seeds] != 32} {
  error "Expected 32 DUT operand nets (16 bits x 2 operands); found [llength $es_seeds]"
}
set need_operand_nets 32

proc es_fname {obj type} {
  return [get_property -object_type $type $obj full_name]
}

# Every sequential cell of the linked design, keyed by instance name.
set es_reg_cells [dict create]
foreach c [all_registers -cells] { dict set es_reg_cells [es_fname $c cell] $c }
puts "ES sequential cells: [dict size $es_reg_cells]"

# Backward fan-in cone through combinational cells only, collecting the
# sequential cells that drive the cone (their Q is a cone input).
proc es_fanin_regs {seeds reg_cells} {
  set seen [dict create]
  set found [dict create]
  set frontier $seeds
  while {[llength $frontier] > 0} {
    set next {}
    foreach n $frontier {
      set key [es_fname $n net]
      if {[dict exists $seen $key]} { continue }
      dict set seen $key 1
      foreach p [get_pins -quiet -of_objects $n] {
        if {[get_property -object_type pin $p direction] ne "output"} { continue }
        set cs [get_cells -quiet -of_objects $p]
        if {[llength $cs] == 0} { continue }
        set c [lindex $cs 0]
        set ckey [es_fname $c cell]
        if {[dict exists $reg_cells $ckey]} { dict set found $ckey $c ; continue }
        foreach ip [get_pins -quiet -of_objects $c] {
          if {[get_property -object_type pin $ip direction] ne "input"} { continue }
          set ins [get_nets -quiet -of_objects $ip]
          if {[llength $ins] == 0} { continue }
          set in [lindex $ins 0]
          if {[es_fname $in net] eq $key} { continue }
          lappend next $in
        }
      }
    }
    set frontier $next
  }
  return $found
}

proc es_pin_by_name {cell pname} {
  foreach p [get_pins -quiet -of_objects $cell] {
    if {[get_property -object_type pin $p name] eq $pname} { return $p }
  }
  return ""
}

proc es_net_of_pin {pin} {
  set ns [get_nets -quiet -of_objects $pin]
  if {[llength $ns] == 0} { return "" }
  return [lindex $ns 0]
}

# Step 2: registers in the DUT operand fan-in cone, minus the static
# configuration registers that the case loop drives to constants.
set es_static_nets {}
for {set b 0} {$b < 16} {incr b} {
  if {$b == 10 || $b == 11} {
    lappend es_static_nets "can_sel\[[expr {$b - 10}]\]"
  } else {
    lappend es_static_nets "cfg\[$b\]"
  }
}
foreach n $es_static_nets {
  if {[llength [get_nets -quiet $n]] == 0} {
    error "Static configuration net not found: $n"
  }
}

set es_cone_regs [es_fanin_regs $es_seeds $es_reg_cells]
puts "ES operand-cone registers: [dict size $es_cone_regs]"

set spins {}
set es_static_cone {}
set es_qnet_of [dict create]
foreach k [lsort [dict keys $es_cone_regs]] {
  set c [dict get $es_cone_regs $k]
  set q [es_pin_by_name $c Q]
  if {$q eq ""} { continue }
  set qnet [es_net_of_pin $q]
  if {$qnet eq ""} { continue }
  dict set es_qnet_of $k [es_fname $qnet net]
  if {[lsearch -exact $es_static_nets [es_fname $qnet net]] >= 0} {
    lappend es_static_cone $k
    continue
  }
  lappend spins [lindex [get_pins -quiet "$k/Q"] 0]
}
set es_launch_names [lsort [dict keys $es_qnet_of]]
puts "ES static-config registers in operand cone: [llength $es_static_cone] \
([join $es_static_cone { }])"

# Step 3: assertions - expected launch-register count and uniqueness.
set es_expect_launch 18
puts "ES startpoints ([llength $spins]): [llength $spins] pins"
if {[llength $spins] != $es_expect_launch} {
  error "Expected $es_expect_launch runtime pattern-state launch pins; found \
[llength $spins]. Operand-cone registers: $es_launch_names"
}
set es_pin_names {}
foreach p $spins { lappend es_pin_names [es_fname $p pin] }
if {[llength [lsort -unique $es_pin_names]] != $es_expect_launch} {
  error "Launch pin list is not unique: $es_pin_names"
}
foreach p $spins {
  set c [lindex [get_cells -quiet -of_objects $p] 0]
  if {![dict exists $es_reg_cells [es_fname $c cell]]} {
    error "Launch pin [es_fname $p pin] is not a sequential-cell output"
  }
}
# The 18 state flops are 16 LFSR bits + a 2-bit index counter (see
# src/tpv_pattern_gen.v). Verify that structure without using net names:
# the LFSR is a load-enabled shift chain whose head is fed by four feedback
# taps, and the counter's low bit has no state predecessor.
set es_launch_set [dict create]
foreach p $spins { dict set es_launch_set [es_fname $p pin] 1 }

set es_preds [dict create]
foreach p $spins {
  set pn [es_fname $p pin]
  set cell [lindex [get_cells -quiet -of_objects $p] 0]
  set d [es_pin_by_name $cell D]
  if {$d eq ""} { error "Launch register $pn has no D pin" }
  set dnet [es_net_of_pin $d]
  set flops [es_fanin_regs [list $dnet] $es_reg_cells]
  set preds {}
  foreach k [dict keys $flops] {
    set qp [es_pin_by_name [dict get $es_reg_cells $k] Q]
    if {$qp eq ""} { continue }
    set qpn [es_fname $qp pin]
    if {[dict exists $es_launch_set $qpn] && $qpn ne $pn} { lappend preds $qpn }
  }
  dict set es_preds $pn [lsort -unique $preds]
}

set es_head ""
set es_tail ""
foreach pn [lsort [dict keys $es_preds]] {
  set n [llength [dict get $es_preds $pn]]
  if {$n == 4} {
    if {$es_head ne ""} { error "Two LFSR chain heads found: $es_head $pn" }
    set es_head $pn
  } elseif {$n == 0} {
    if {$es_tail ne ""} { error "Two predecessor-free state flops: $es_tail $pn" }
    set es_tail $pn
  } elseif {$n != 1} {
    error "Launch register $pn has $n state predecessors (expected 0, 1 or 4)"
  }
}
if {$es_head eq ""} { error "No LFSR chain head (4 feedback taps) found" }
if {$es_tail eq ""} { error "No predecessor-free index-counter bit found" }

# second counter bit: exactly one node whose only state predecessor is the
# predecessor-free node
set es_idx1 ""
foreach pn [lsort [dict keys $es_preds]] {
  if {$pn eq $es_head || $pn eq $es_tail} { continue }
  set pr [dict get $es_preds $pn]
  if {[llength $pr] == 1 && [lindex $pr 0] eq $es_tail} {
    if {$es_idx1 ne ""} { error "Two index-counter high bits: $es_idx1 $pn" }
    set es_idx1 $pn
  }
}
if {$es_idx1 eq ""} { error "No second index-counter bit found" }

# chain index = number of single-predecessor steps needed to reach the head
array set es_role {}
set es_role($es_head) lfsr0
set es_role($es_tail) idx0
set es_role($es_idx1) idx1
foreach pn [lsort [dict keys $es_preds]] {
  if {$pn eq $es_head || $pn eq $es_tail || $pn eq $es_idx1} { continue }
  set cur $pn
  set n 0
  while {$cur ne $es_head} {
    set pr [dict get $es_preds $cur]
    if {[llength $pr] != 1} { error "$pn is not on the LFSR shift chain" }
    set cur [lindex $pr 0]
    incr n
    if {$n > 18} { error "LFSR chain walk did not terminate at $pn" }
  }
  set es_role($pn) "lfsr$n"
}
if {[array size es_role] != 18} {
  error "Assigned [array size es_role] structural roles, expected 18"
}

set es_seen_bits [dict create]
foreach pn [array names es_role] {
  set r $es_role($pn)
  if {[string match "lfsr*" $r]} {
    set b [string range $r 4 end]
    if {[dict exists $es_seen_bits $b]} { error "LFSR bit $b assigned twice" }
    dict set es_seen_bits $b 1
  }
}
if {[dict size $es_seen_bits] != 16} {
  error "Expected 16 distinct LFSR bits, found [dict size $es_seen_bits]"
}
set es_taps {}
foreach tp [dict get $es_preds $es_head] { lappend es_taps $es_role($tp) }
set es_taps [lsort $es_taps]
if {$es_taps ne [lsort {lfsr10 lfsr12 lfsr13 lfsr15}]} {
  error "LFSR feedback taps $es_taps do not match x^16+x^14+x^13+x^11+1"
}
# Named anchors (synthesis source mapping) must agree with the structural role.
set es_named 0
foreach k [lsort [dict keys $es_qnet_of]] {
  set pn "$k/Q"
  set qn [dict get $es_qnet_of $k]
  if {[regexp {^u_pat\.lfsr\[(\d+)\]$} $qn -> b]} {
    incr es_named
    if {$es_role($pn) ne "lfsr$b"} {
      error "Named net $qn is structurally $es_role($pn)"
    }
  } elseif {[regexp {^u_pat\.idx\[(\d+)\]$} $qn -> b]} {
    incr es_named
    if {$es_role($pn) ne "idx$b"} {
      error "Named net $qn is structurally $es_role($pn)"
    }
  }
}
puts "ES startpoint roles: [array size es_role] pins, \
[expr {18 - $es_named}] with synthesis-renamed Q nets"
foreach pn [lsort -dictionary [array names es_role]] {
  set cell [string range $pn 0 end-2]
  puts "ES-LAUNCH-PIN $pn $es_role($pn) [dict get $es_qnet_of $cell] \
[llength [dict get $es_preds $pn]]"
}
puts "ES-LAUNCH-PINS-OK $es_expect_launch $es_named [llength $es_static_cone] $need_operand_nets"

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
es_case_net 1 {started}

# ------------------------------------------------------------------ reports --
# The case loop is supplied by ES_CASES_TCL (generated per corner by the
# driver). Each iteration prints a ==CASE header and two reports:
#   ES-R2R   : runtime-sensitizable pattern-register -> result_reg path
#   ES-GLOBAL: worst path to result_reg from any startpoint (cross-check)
source $::env(ES_CASES_TCL)
