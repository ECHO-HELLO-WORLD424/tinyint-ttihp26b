puts "==ROCASE sel=0"
ro_case_net 0 {can_sel[0]}
ro_case_net 0 {can_sel[1]}
puts "RO-GEN"
set_max_delay 1000 -from [get_pins {u_ro_gen.u_gate.u_a3/X}] -to [get_pins {u_ro_gen.u_gate.u_a2/A}]
report_checks -from [get_pins {u_ro_gen.u_gate.u_a3/X}] -to [get_pins {u_ro_gen.u_gate.u_a2/A}] -path_delay max -group_path_count 1 -fields {slew cap} -format full_clock_expanded -corner nom
puts "RO-MAT"
set_max_delay 1000 -from [get_pins {u_ro_mat.u_gate.u_a3/X}] -to [get_pins {u_ro_mat.u_gate.u_a2/A}]
report_checks -from [get_pins {u_ro_mat.u_gate.u_a3/X}] -to [get_pins {u_ro_mat.u_gate.u_a2/A}] -path_delay max -group_path_count 1 -fields {slew cap} -format full_clock_expanded -corner nom
puts "RO-END"
puts "==ROCASE sel=1"
ro_case_net 1 {can_sel[0]}
ro_case_net 0 {can_sel[1]}
puts "RO-GEN"
set_max_delay 1000 -from [get_pins {u_ro_gen.u_gate.u_a3/X}] -to [get_pins {u_ro_gen.u_gate.u_a2/A}]
report_checks -from [get_pins {u_ro_gen.u_gate.u_a3/X}] -to [get_pins {u_ro_gen.u_gate.u_a2/A}] -path_delay max -group_path_count 1 -fields {slew cap} -format full_clock_expanded -corner nom
puts "RO-MAT"
set_max_delay 1000 -from [get_pins {u_ro_mat.u_gate.u_a3/X}] -to [get_pins {u_ro_mat.u_gate.u_a2/A}]
report_checks -from [get_pins {u_ro_mat.u_gate.u_a3/X}] -to [get_pins {u_ro_mat.u_gate.u_a2/A}] -path_delay max -group_path_count 1 -fields {slew cap} -format full_clock_expanded -corner nom
puts "RO-END"
puts "==ROCASE sel=2"
ro_case_net 0 {can_sel[0]}
ro_case_net 1 {can_sel[1]}
puts "RO-GEN"
set_max_delay 1000 -from [get_pins {u_ro_gen.u_gate.u_a3/X}] -to [get_pins {u_ro_gen.u_gate.u_a2/A}]
report_checks -from [get_pins {u_ro_gen.u_gate.u_a3/X}] -to [get_pins {u_ro_gen.u_gate.u_a2/A}] -path_delay max -group_path_count 1 -fields {slew cap} -format full_clock_expanded -corner nom
puts "RO-MAT"
set_max_delay 1000 -from [get_pins {u_ro_mat.u_gate.u_a3/X}] -to [get_pins {u_ro_mat.u_gate.u_a2/A}]
report_checks -from [get_pins {u_ro_mat.u_gate.u_a3/X}] -to [get_pins {u_ro_mat.u_gate.u_a2/A}] -path_delay max -group_path_count 1 -fields {slew cap} -format full_clock_expanded -corner nom
puts "RO-END"
puts "==ROCASE sel=3"
ro_case_net 1 {can_sel[0]}
ro_case_net 1 {can_sel[1]}
puts "RO-GEN"
set_max_delay 1000 -from [get_pins {u_ro_gen.u_gate.u_a3/X}] -to [get_pins {u_ro_gen.u_gate.u_a2/A}]
report_checks -from [get_pins {u_ro_gen.u_gate.u_a3/X}] -to [get_pins {u_ro_gen.u_gate.u_a2/A}] -path_delay max -group_path_count 1 -fields {slew cap} -format full_clock_expanded -corner nom
puts "RO-MAT"
set_max_delay 1000 -from [get_pins {u_ro_mat.u_gate.u_a3/X}] -to [get_pins {u_ro_mat.u_gate.u_a2/A}]
report_checks -from [get_pins {u_ro_mat.u_gate.u_a3/X}] -to [get_pins {u_ro_mat.u_gate.u_a2/A}] -path_delay max -group_path_count 1 -fields {slew cap} -format full_clock_expanded -corner nom
puts "RO-END"
