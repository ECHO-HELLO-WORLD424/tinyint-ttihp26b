if {$::env(ES_RO_MODE) eq "line"} {
  set ro_frm_fmt {u_ro_%s.u_gate.u_a3/X}
  set ro_to_fmt {u_ro_%s.u_gate.u_a2/A}
} else {
  set ro_frm_fmt {u_ro_%s.u_gate.u_a2/A}
  set ro_to_fmt {u_ro_%s.u_gate.u_a3/X}
}
puts "==ROCASE sel=0"
ro_case_net 0 {can_sel[0]}
ro_case_net 0 {can_sel[1]}
puts "RO-GEN"
set_max_delay 1000 -from [get_pins [format $ro_frm_fmt gen]] -to [get_pins [format $ro_to_fmt gen]]
report_checks -from [get_pins [format $ro_frm_fmt gen]] -to [get_pins [format $ro_to_fmt gen]] -path_delay max -group_path_count 1 -fields {slew cap} -format full_clock_expanded -corner nom
puts "RO-MAT"
set_max_delay 1000 -from [get_pins [format $ro_frm_fmt mat]] -to [get_pins [format $ro_to_fmt mat]]
report_checks -from [get_pins [format $ro_frm_fmt mat]] -to [get_pins [format $ro_to_fmt mat]] -path_delay max -group_path_count 1 -fields {slew cap} -format full_clock_expanded -corner nom
puts "RO-END"
puts "==ROCASE sel=1"
ro_case_net 1 {can_sel[0]}
ro_case_net 0 {can_sel[1]}
puts "RO-GEN"
set_max_delay 1000 -from [get_pins [format $ro_frm_fmt gen]] -to [get_pins [format $ro_to_fmt gen]]
report_checks -from [get_pins [format $ro_frm_fmt gen]] -to [get_pins [format $ro_to_fmt gen]] -path_delay max -group_path_count 1 -fields {slew cap} -format full_clock_expanded -corner nom
puts "RO-MAT"
set_max_delay 1000 -from [get_pins [format $ro_frm_fmt mat]] -to [get_pins [format $ro_to_fmt mat]]
report_checks -from [get_pins [format $ro_frm_fmt mat]] -to [get_pins [format $ro_to_fmt mat]] -path_delay max -group_path_count 1 -fields {slew cap} -format full_clock_expanded -corner nom
puts "RO-END"
puts "==ROCASE sel=2"
ro_case_net 0 {can_sel[0]}
ro_case_net 1 {can_sel[1]}
puts "RO-GEN"
set_max_delay 1000 -from [get_pins [format $ro_frm_fmt gen]] -to [get_pins [format $ro_to_fmt gen]]
report_checks -from [get_pins [format $ro_frm_fmt gen]] -to [get_pins [format $ro_to_fmt gen]] -path_delay max -group_path_count 1 -fields {slew cap} -format full_clock_expanded -corner nom
puts "RO-MAT"
set_max_delay 1000 -from [get_pins [format $ro_frm_fmt mat]] -to [get_pins [format $ro_to_fmt mat]]
report_checks -from [get_pins [format $ro_frm_fmt mat]] -to [get_pins [format $ro_to_fmt mat]] -path_delay max -group_path_count 1 -fields {slew cap} -format full_clock_expanded -corner nom
puts "RO-END"
puts "==ROCASE sel=3"
ro_case_net 1 {can_sel[0]}
ro_case_net 1 {can_sel[1]}
puts "RO-GEN"
set_max_delay 1000 -from [get_pins [format $ro_frm_fmt gen]] -to [get_pins [format $ro_to_fmt gen]]
report_checks -from [get_pins [format $ro_frm_fmt gen]] -to [get_pins [format $ro_to_fmt gen]] -path_delay max -group_path_count 1 -fields {slew cap} -format full_clock_expanded -corner nom
puts "RO-MAT"
set_max_delay 1000 -from [get_pins [format $ro_frm_fmt mat]] -to [get_pins [format $ro_to_fmt mat]]
report_checks -from [get_pins [format $ro_frm_fmt mat]] -to [get_pins [format $ro_to_fmt mat]] -path_delay max -group_path_count 1 -fields {slew cap} -format full_clock_expanded -corner nom
puts "RO-END"
