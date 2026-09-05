puts "==CASE seg3333-pat1"
es_case_net 1 {cfg[0]}
es_case_net 1 {cfg[1]}
es_case_net 1 {cfg[2]}
es_case_net 1 {cfg[3]}
es_case_net 1 {cfg[4]}
es_case_net 1 {cfg[5]}
es_case_net 1 {cfg[6]}
es_case_net 1 {cfg[7]}
es_case_net 1 {cfg[8]}
es_case_net 0 {cfg[9]}
es_case_net 0 {can_sel[0]}
es_case_net 0 {can_sel[1]}
es_case_net 0 {cfg[12]}
es_case_net 0 {cfg[13]}
es_case_net 0 {cfg[14]}
es_case_net 0 {cfg[15]}
puts "ES-R2R"
report_checks -from $spins -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-GLOBAL"
report_checks -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-END"
puts "CONTROL-MAX"
report_checks -to $control_epins -path_delay max -group_path_count 1 -format full_clock_expanded -corner nom
puts "CONTROL-END"
