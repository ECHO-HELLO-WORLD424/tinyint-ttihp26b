puts "==CASE seg0000-pat0"
es_case_net 0 {cfg[0]}
es_case_net 0 {cfg[1]}
es_case_net 0 {cfg[2]}
es_case_net 0 {cfg[3]}
es_case_net 0 {cfg[4]}
es_case_net 0 {cfg[5]}
es_case_net 0 {cfg[6]}
es_case_net 0 {cfg[7]}
es_case_net 0 {cfg[8]}
es_case_net 0 {cfg[9]}
es_case_net 0 {cfg[10]}
es_case_net 0 {cfg[11]}
es_case_net 0 {cfg[12]}
es_case_net 0 {cfg[13]}
es_case_net 0 {cfg[14]}
es_case_net 0 {cfg[15]}
puts "ES-R2R"
report_checks -from $spins -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-GLOBAL"
report_checks -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-END"
puts "==CASE seg0000-pat1"
es_case_net 0 {cfg[0]}
es_case_net 0 {cfg[1]}
es_case_net 0 {cfg[2]}
es_case_net 0 {cfg[3]}
es_case_net 0 {cfg[4]}
es_case_net 0 {cfg[5]}
es_case_net 0 {cfg[6]}
es_case_net 0 {cfg[7]}
es_case_net 1 {cfg[8]}
es_case_net 0 {cfg[9]}
es_case_net 0 {cfg[10]}
es_case_net 0 {cfg[11]}
es_case_net 0 {cfg[12]}
es_case_net 0 {cfg[13]}
es_case_net 0 {cfg[14]}
es_case_net 0 {cfg[15]}
puts "ES-R2R"
report_checks -from $spins -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-GLOBAL"
report_checks -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-END"
puts "==CASE seg0000-pat2"
es_case_net 0 {cfg[0]}
es_case_net 0 {cfg[1]}
es_case_net 0 {cfg[2]}
es_case_net 0 {cfg[3]}
es_case_net 0 {cfg[4]}
es_case_net 0 {cfg[5]}
es_case_net 0 {cfg[6]}
es_case_net 0 {cfg[7]}
es_case_net 0 {cfg[8]}
es_case_net 1 {cfg[9]}
es_case_net 0 {cfg[10]}
es_case_net 0 {cfg[11]}
es_case_net 0 {cfg[12]}
es_case_net 0 {cfg[13]}
es_case_net 0 {cfg[14]}
es_case_net 0 {cfg[15]}
puts "ES-R2R"
report_checks -from $spins -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-GLOBAL"
report_checks -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-END"
puts "==CASE seg0000-pat3"
es_case_net 0 {cfg[0]}
es_case_net 0 {cfg[1]}
es_case_net 0 {cfg[2]}
es_case_net 0 {cfg[3]}
es_case_net 0 {cfg[4]}
es_case_net 0 {cfg[5]}
es_case_net 0 {cfg[6]}
es_case_net 0 {cfg[7]}
es_case_net 1 {cfg[8]}
es_case_net 1 {cfg[9]}
es_case_net 0 {cfg[10]}
es_case_net 0 {cfg[11]}
es_case_net 0 {cfg[12]}
es_case_net 0 {cfg[13]}
es_case_net 0 {cfg[14]}
es_case_net 0 {cfg[15]}
puts "ES-R2R"
report_checks -from $spins -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-GLOBAL"
report_checks -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-END"
puts "==CASE seg1111-pat0"
es_case_net 1 {cfg[0]}
es_case_net 0 {cfg[1]}
es_case_net 1 {cfg[2]}
es_case_net 0 {cfg[3]}
es_case_net 1 {cfg[4]}
es_case_net 0 {cfg[5]}
es_case_net 1 {cfg[6]}
es_case_net 0 {cfg[7]}
es_case_net 0 {cfg[8]}
es_case_net 0 {cfg[9]}
es_case_net 0 {cfg[10]}
es_case_net 0 {cfg[11]}
es_case_net 0 {cfg[12]}
es_case_net 0 {cfg[13]}
es_case_net 0 {cfg[14]}
es_case_net 0 {cfg[15]}
puts "ES-R2R"
report_checks -from $spins -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-GLOBAL"
report_checks -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-END"
puts "==CASE seg1111-pat1"
es_case_net 1 {cfg[0]}
es_case_net 0 {cfg[1]}
es_case_net 1 {cfg[2]}
es_case_net 0 {cfg[3]}
es_case_net 1 {cfg[4]}
es_case_net 0 {cfg[5]}
es_case_net 1 {cfg[6]}
es_case_net 0 {cfg[7]}
es_case_net 1 {cfg[8]}
es_case_net 0 {cfg[9]}
es_case_net 0 {cfg[10]}
es_case_net 0 {cfg[11]}
es_case_net 0 {cfg[12]}
es_case_net 0 {cfg[13]}
es_case_net 0 {cfg[14]}
es_case_net 0 {cfg[15]}
puts "ES-R2R"
report_checks -from $spins -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-GLOBAL"
report_checks -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-END"
puts "==CASE seg1111-pat2"
es_case_net 1 {cfg[0]}
es_case_net 0 {cfg[1]}
es_case_net 1 {cfg[2]}
es_case_net 0 {cfg[3]}
es_case_net 1 {cfg[4]}
es_case_net 0 {cfg[5]}
es_case_net 1 {cfg[6]}
es_case_net 0 {cfg[7]}
es_case_net 0 {cfg[8]}
es_case_net 1 {cfg[9]}
es_case_net 0 {cfg[10]}
es_case_net 0 {cfg[11]}
es_case_net 0 {cfg[12]}
es_case_net 0 {cfg[13]}
es_case_net 0 {cfg[14]}
es_case_net 0 {cfg[15]}
puts "ES-R2R"
report_checks -from $spins -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-GLOBAL"
report_checks -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-END"
puts "==CASE seg1111-pat3"
es_case_net 1 {cfg[0]}
es_case_net 0 {cfg[1]}
es_case_net 1 {cfg[2]}
es_case_net 0 {cfg[3]}
es_case_net 1 {cfg[4]}
es_case_net 0 {cfg[5]}
es_case_net 1 {cfg[6]}
es_case_net 0 {cfg[7]}
es_case_net 1 {cfg[8]}
es_case_net 1 {cfg[9]}
es_case_net 0 {cfg[10]}
es_case_net 0 {cfg[11]}
es_case_net 0 {cfg[12]}
es_case_net 0 {cfg[13]}
es_case_net 0 {cfg[14]}
es_case_net 0 {cfg[15]}
puts "ES-R2R"
report_checks -from $spins -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-GLOBAL"
report_checks -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-END"
puts "==CASE seg2222-pat0"
es_case_net 0 {cfg[0]}
es_case_net 1 {cfg[1]}
es_case_net 0 {cfg[2]}
es_case_net 1 {cfg[3]}
es_case_net 0 {cfg[4]}
es_case_net 1 {cfg[5]}
es_case_net 0 {cfg[6]}
es_case_net 1 {cfg[7]}
es_case_net 0 {cfg[8]}
es_case_net 0 {cfg[9]}
es_case_net 0 {cfg[10]}
es_case_net 0 {cfg[11]}
es_case_net 0 {cfg[12]}
es_case_net 0 {cfg[13]}
es_case_net 0 {cfg[14]}
es_case_net 0 {cfg[15]}
puts "ES-R2R"
report_checks -from $spins -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-GLOBAL"
report_checks -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-END"
puts "==CASE seg2222-pat1"
es_case_net 0 {cfg[0]}
es_case_net 1 {cfg[1]}
es_case_net 0 {cfg[2]}
es_case_net 1 {cfg[3]}
es_case_net 0 {cfg[4]}
es_case_net 1 {cfg[5]}
es_case_net 0 {cfg[6]}
es_case_net 1 {cfg[7]}
es_case_net 1 {cfg[8]}
es_case_net 0 {cfg[9]}
es_case_net 0 {cfg[10]}
es_case_net 0 {cfg[11]}
es_case_net 0 {cfg[12]}
es_case_net 0 {cfg[13]}
es_case_net 0 {cfg[14]}
es_case_net 0 {cfg[15]}
puts "ES-R2R"
report_checks -from $spins -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-GLOBAL"
report_checks -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-END"
puts "==CASE seg2222-pat2"
es_case_net 0 {cfg[0]}
es_case_net 1 {cfg[1]}
es_case_net 0 {cfg[2]}
es_case_net 1 {cfg[3]}
es_case_net 0 {cfg[4]}
es_case_net 1 {cfg[5]}
es_case_net 0 {cfg[6]}
es_case_net 1 {cfg[7]}
es_case_net 0 {cfg[8]}
es_case_net 1 {cfg[9]}
es_case_net 0 {cfg[10]}
es_case_net 0 {cfg[11]}
es_case_net 0 {cfg[12]}
es_case_net 0 {cfg[13]}
es_case_net 0 {cfg[14]}
es_case_net 0 {cfg[15]}
puts "ES-R2R"
report_checks -from $spins -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-GLOBAL"
report_checks -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-END"
puts "==CASE seg2222-pat3"
es_case_net 0 {cfg[0]}
es_case_net 1 {cfg[1]}
es_case_net 0 {cfg[2]}
es_case_net 1 {cfg[3]}
es_case_net 0 {cfg[4]}
es_case_net 1 {cfg[5]}
es_case_net 0 {cfg[6]}
es_case_net 1 {cfg[7]}
es_case_net 1 {cfg[8]}
es_case_net 1 {cfg[9]}
es_case_net 0 {cfg[10]}
es_case_net 0 {cfg[11]}
es_case_net 0 {cfg[12]}
es_case_net 0 {cfg[13]}
es_case_net 0 {cfg[14]}
es_case_net 0 {cfg[15]}
puts "ES-R2R"
report_checks -from $spins -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-GLOBAL"
report_checks -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-END"
puts "==CASE seg3333-pat0"
es_case_net 1 {cfg[0]}
es_case_net 1 {cfg[1]}
es_case_net 1 {cfg[2]}
es_case_net 1 {cfg[3]}
es_case_net 1 {cfg[4]}
es_case_net 1 {cfg[5]}
es_case_net 1 {cfg[6]}
es_case_net 1 {cfg[7]}
es_case_net 0 {cfg[8]}
es_case_net 0 {cfg[9]}
es_case_net 0 {cfg[10]}
es_case_net 0 {cfg[11]}
es_case_net 0 {cfg[12]}
es_case_net 0 {cfg[13]}
es_case_net 0 {cfg[14]}
es_case_net 0 {cfg[15]}
puts "ES-R2R"
report_checks -from $spins -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-GLOBAL"
report_checks -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-END"
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
es_case_net 0 {cfg[10]}
es_case_net 0 {cfg[11]}
es_case_net 0 {cfg[12]}
es_case_net 0 {cfg[13]}
es_case_net 0 {cfg[14]}
es_case_net 0 {cfg[15]}
puts "ES-R2R"
report_checks -from $spins -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-GLOBAL"
report_checks -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-END"
puts "==CASE seg3333-pat2"
es_case_net 1 {cfg[0]}
es_case_net 1 {cfg[1]}
es_case_net 1 {cfg[2]}
es_case_net 1 {cfg[3]}
es_case_net 1 {cfg[4]}
es_case_net 1 {cfg[5]}
es_case_net 1 {cfg[6]}
es_case_net 1 {cfg[7]}
es_case_net 0 {cfg[8]}
es_case_net 1 {cfg[9]}
es_case_net 0 {cfg[10]}
es_case_net 0 {cfg[11]}
es_case_net 0 {cfg[12]}
es_case_net 0 {cfg[13]}
es_case_net 0 {cfg[14]}
es_case_net 0 {cfg[15]}
puts "ES-R2R"
report_checks -from $spins -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-GLOBAL"
report_checks -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-END"
puts "==CASE seg3333-pat3"
es_case_net 1 {cfg[0]}
es_case_net 1 {cfg[1]}
es_case_net 1 {cfg[2]}
es_case_net 1 {cfg[3]}
es_case_net 1 {cfg[4]}
es_case_net 1 {cfg[5]}
es_case_net 1 {cfg[6]}
es_case_net 1 {cfg[7]}
es_case_net 1 {cfg[8]}
es_case_net 1 {cfg[9]}
es_case_net 0 {cfg[10]}
es_case_net 0 {cfg[11]}
es_case_net 0 {cfg[12]}
es_case_net 0 {cfg[13]}
es_case_net 0 {cfg[14]}
es_case_net 0 {cfg[15]}
puts "ES-R2R"
report_checks -from $spins -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-GLOBAL"
report_checks -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-END"
puts "==CASE seg3000-pat0"
es_case_net 1 {cfg[0]}
es_case_net 1 {cfg[1]}
es_case_net 0 {cfg[2]}
es_case_net 0 {cfg[3]}
es_case_net 0 {cfg[4]}
es_case_net 0 {cfg[5]}
es_case_net 0 {cfg[6]}
es_case_net 0 {cfg[7]}
es_case_net 0 {cfg[8]}
es_case_net 0 {cfg[9]}
es_case_net 0 {cfg[10]}
es_case_net 0 {cfg[11]}
es_case_net 0 {cfg[12]}
es_case_net 0 {cfg[13]}
es_case_net 0 {cfg[14]}
es_case_net 0 {cfg[15]}
puts "ES-R2R"
report_checks -from $spins -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-GLOBAL"
report_checks -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-END"
puts "==CASE seg3000-pat1"
es_case_net 1 {cfg[0]}
es_case_net 1 {cfg[1]}
es_case_net 0 {cfg[2]}
es_case_net 0 {cfg[3]}
es_case_net 0 {cfg[4]}
es_case_net 0 {cfg[5]}
es_case_net 0 {cfg[6]}
es_case_net 0 {cfg[7]}
es_case_net 1 {cfg[8]}
es_case_net 0 {cfg[9]}
es_case_net 0 {cfg[10]}
es_case_net 0 {cfg[11]}
es_case_net 0 {cfg[12]}
es_case_net 0 {cfg[13]}
es_case_net 0 {cfg[14]}
es_case_net 0 {cfg[15]}
puts "ES-R2R"
report_checks -from $spins -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-GLOBAL"
report_checks -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-END"
puts "==CASE seg3000-pat2"
es_case_net 1 {cfg[0]}
es_case_net 1 {cfg[1]}
es_case_net 0 {cfg[2]}
es_case_net 0 {cfg[3]}
es_case_net 0 {cfg[4]}
es_case_net 0 {cfg[5]}
es_case_net 0 {cfg[6]}
es_case_net 0 {cfg[7]}
es_case_net 0 {cfg[8]}
es_case_net 1 {cfg[9]}
es_case_net 0 {cfg[10]}
es_case_net 0 {cfg[11]}
es_case_net 0 {cfg[12]}
es_case_net 0 {cfg[13]}
es_case_net 0 {cfg[14]}
es_case_net 0 {cfg[15]}
puts "ES-R2R"
report_checks -from $spins -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-GLOBAL"
report_checks -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-END"
puts "==CASE seg3000-pat3"
es_case_net 1 {cfg[0]}
es_case_net 1 {cfg[1]}
es_case_net 0 {cfg[2]}
es_case_net 0 {cfg[3]}
es_case_net 0 {cfg[4]}
es_case_net 0 {cfg[5]}
es_case_net 0 {cfg[6]}
es_case_net 0 {cfg[7]}
es_case_net 1 {cfg[8]}
es_case_net 1 {cfg[9]}
es_case_net 0 {cfg[10]}
es_case_net 0 {cfg[11]}
es_case_net 0 {cfg[12]}
es_case_net 0 {cfg[13]}
es_case_net 0 {cfg[14]}
es_case_net 0 {cfg[15]}
puts "ES-R2R"
report_checks -from $spins -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-GLOBAL"
report_checks -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-END"
puts "==CASE seg0003-pat0"
es_case_net 0 {cfg[0]}
es_case_net 0 {cfg[1]}
es_case_net 0 {cfg[2]}
es_case_net 0 {cfg[3]}
es_case_net 0 {cfg[4]}
es_case_net 0 {cfg[5]}
es_case_net 1 {cfg[6]}
es_case_net 1 {cfg[7]}
es_case_net 0 {cfg[8]}
es_case_net 0 {cfg[9]}
es_case_net 0 {cfg[10]}
es_case_net 0 {cfg[11]}
es_case_net 0 {cfg[12]}
es_case_net 0 {cfg[13]}
es_case_net 0 {cfg[14]}
es_case_net 0 {cfg[15]}
puts "ES-R2R"
report_checks -from $spins -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-GLOBAL"
report_checks -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-END"
puts "==CASE seg0003-pat1"
es_case_net 0 {cfg[0]}
es_case_net 0 {cfg[1]}
es_case_net 0 {cfg[2]}
es_case_net 0 {cfg[3]}
es_case_net 0 {cfg[4]}
es_case_net 0 {cfg[5]}
es_case_net 1 {cfg[6]}
es_case_net 1 {cfg[7]}
es_case_net 1 {cfg[8]}
es_case_net 0 {cfg[9]}
es_case_net 0 {cfg[10]}
es_case_net 0 {cfg[11]}
es_case_net 0 {cfg[12]}
es_case_net 0 {cfg[13]}
es_case_net 0 {cfg[14]}
es_case_net 0 {cfg[15]}
puts "ES-R2R"
report_checks -from $spins -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-GLOBAL"
report_checks -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-END"
puts "==CASE seg0003-pat2"
es_case_net 0 {cfg[0]}
es_case_net 0 {cfg[1]}
es_case_net 0 {cfg[2]}
es_case_net 0 {cfg[3]}
es_case_net 0 {cfg[4]}
es_case_net 0 {cfg[5]}
es_case_net 1 {cfg[6]}
es_case_net 1 {cfg[7]}
es_case_net 0 {cfg[8]}
es_case_net 1 {cfg[9]}
es_case_net 0 {cfg[10]}
es_case_net 0 {cfg[11]}
es_case_net 0 {cfg[12]}
es_case_net 0 {cfg[13]}
es_case_net 0 {cfg[14]}
es_case_net 0 {cfg[15]}
puts "ES-R2R"
report_checks -from $spins -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-GLOBAL"
report_checks -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-END"
puts "==CASE seg0003-pat3"
es_case_net 0 {cfg[0]}
es_case_net 0 {cfg[1]}
es_case_net 0 {cfg[2]}
es_case_net 0 {cfg[3]}
es_case_net 0 {cfg[4]}
es_case_net 0 {cfg[5]}
es_case_net 1 {cfg[6]}
es_case_net 1 {cfg[7]}
es_case_net 1 {cfg[8]}
es_case_net 1 {cfg[9]}
es_case_net 0 {cfg[10]}
es_case_net 0 {cfg[11]}
es_case_net 0 {cfg[12]}
es_case_net 0 {cfg[13]}
es_case_net 0 {cfg[14]}
es_case_net 0 {cfg[15]}
puts "ES-R2R"
report_checks -from $spins -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-GLOBAL"
report_checks -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-END"
puts "==CASE seg2130-pat0"
es_case_net 0 {cfg[0]}
es_case_net 1 {cfg[1]}
es_case_net 1 {cfg[2]}
es_case_net 0 {cfg[3]}
es_case_net 1 {cfg[4]}
es_case_net 1 {cfg[5]}
es_case_net 0 {cfg[6]}
es_case_net 0 {cfg[7]}
es_case_net 0 {cfg[8]}
es_case_net 0 {cfg[9]}
es_case_net 0 {cfg[10]}
es_case_net 0 {cfg[11]}
es_case_net 0 {cfg[12]}
es_case_net 0 {cfg[13]}
es_case_net 0 {cfg[14]}
es_case_net 0 {cfg[15]}
puts "ES-R2R"
report_checks -from $spins -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-GLOBAL"
report_checks -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-END"
puts "==CASE seg2130-pat1"
es_case_net 0 {cfg[0]}
es_case_net 1 {cfg[1]}
es_case_net 1 {cfg[2]}
es_case_net 0 {cfg[3]}
es_case_net 1 {cfg[4]}
es_case_net 1 {cfg[5]}
es_case_net 0 {cfg[6]}
es_case_net 0 {cfg[7]}
es_case_net 1 {cfg[8]}
es_case_net 0 {cfg[9]}
es_case_net 0 {cfg[10]}
es_case_net 0 {cfg[11]}
es_case_net 0 {cfg[12]}
es_case_net 0 {cfg[13]}
es_case_net 0 {cfg[14]}
es_case_net 0 {cfg[15]}
puts "ES-R2R"
report_checks -from $spins -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-GLOBAL"
report_checks -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-END"
puts "==CASE seg2130-pat2"
es_case_net 0 {cfg[0]}
es_case_net 1 {cfg[1]}
es_case_net 1 {cfg[2]}
es_case_net 0 {cfg[3]}
es_case_net 1 {cfg[4]}
es_case_net 1 {cfg[5]}
es_case_net 0 {cfg[6]}
es_case_net 0 {cfg[7]}
es_case_net 0 {cfg[8]}
es_case_net 1 {cfg[9]}
es_case_net 0 {cfg[10]}
es_case_net 0 {cfg[11]}
es_case_net 0 {cfg[12]}
es_case_net 0 {cfg[13]}
es_case_net 0 {cfg[14]}
es_case_net 0 {cfg[15]}
puts "ES-R2R"
report_checks -from $spins -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-GLOBAL"
report_checks -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-END"
puts "==CASE seg2130-pat3"
es_case_net 0 {cfg[0]}
es_case_net 1 {cfg[1]}
es_case_net 1 {cfg[2]}
es_case_net 0 {cfg[3]}
es_case_net 1 {cfg[4]}
es_case_net 1 {cfg[5]}
es_case_net 0 {cfg[6]}
es_case_net 0 {cfg[7]}
es_case_net 1 {cfg[8]}
es_case_net 1 {cfg[9]}
es_case_net 0 {cfg[10]}
es_case_net 0 {cfg[11]}
es_case_net 0 {cfg[12]}
es_case_net 0 {cfg[13]}
es_case_net 0 {cfg[14]}
es_case_net 0 {cfg[15]}
puts "ES-R2R"
report_checks -from $spins -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-GLOBAL"
report_checks -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-END"
puts "==CASE seg1203-pat0"
es_case_net 1 {cfg[0]}
es_case_net 0 {cfg[1]}
es_case_net 0 {cfg[2]}
es_case_net 1 {cfg[3]}
es_case_net 0 {cfg[4]}
es_case_net 0 {cfg[5]}
es_case_net 1 {cfg[6]}
es_case_net 1 {cfg[7]}
es_case_net 0 {cfg[8]}
es_case_net 0 {cfg[9]}
es_case_net 0 {cfg[10]}
es_case_net 0 {cfg[11]}
es_case_net 0 {cfg[12]}
es_case_net 0 {cfg[13]}
es_case_net 0 {cfg[14]}
es_case_net 0 {cfg[15]}
puts "ES-R2R"
report_checks -from $spins -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-GLOBAL"
report_checks -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-END"
puts "==CASE seg1203-pat1"
es_case_net 1 {cfg[0]}
es_case_net 0 {cfg[1]}
es_case_net 0 {cfg[2]}
es_case_net 1 {cfg[3]}
es_case_net 0 {cfg[4]}
es_case_net 0 {cfg[5]}
es_case_net 1 {cfg[6]}
es_case_net 1 {cfg[7]}
es_case_net 1 {cfg[8]}
es_case_net 0 {cfg[9]}
es_case_net 0 {cfg[10]}
es_case_net 0 {cfg[11]}
es_case_net 0 {cfg[12]}
es_case_net 0 {cfg[13]}
es_case_net 0 {cfg[14]}
es_case_net 0 {cfg[15]}
puts "ES-R2R"
report_checks -from $spins -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-GLOBAL"
report_checks -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-END"
puts "==CASE seg1203-pat2"
es_case_net 1 {cfg[0]}
es_case_net 0 {cfg[1]}
es_case_net 0 {cfg[2]}
es_case_net 1 {cfg[3]}
es_case_net 0 {cfg[4]}
es_case_net 0 {cfg[5]}
es_case_net 1 {cfg[6]}
es_case_net 1 {cfg[7]}
es_case_net 0 {cfg[8]}
es_case_net 1 {cfg[9]}
es_case_net 0 {cfg[10]}
es_case_net 0 {cfg[11]}
es_case_net 0 {cfg[12]}
es_case_net 0 {cfg[13]}
es_case_net 0 {cfg[14]}
es_case_net 0 {cfg[15]}
puts "ES-R2R"
report_checks -from $spins -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-GLOBAL"
report_checks -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-END"
puts "==CASE seg1203-pat3"
es_case_net 1 {cfg[0]}
es_case_net 0 {cfg[1]}
es_case_net 0 {cfg[2]}
es_case_net 1 {cfg[3]}
es_case_net 0 {cfg[4]}
es_case_net 0 {cfg[5]}
es_case_net 1 {cfg[6]}
es_case_net 1 {cfg[7]}
es_case_net 1 {cfg[8]}
es_case_net 1 {cfg[9]}
es_case_net 0 {cfg[10]}
es_case_net 0 {cfg[11]}
es_case_net 0 {cfg[12]}
es_case_net 0 {cfg[13]}
es_case_net 0 {cfg[14]}
es_case_net 0 {cfg[15]}
puts "ES-R2R"
report_checks -from $spins -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-GLOBAL"
report_checks -to $epins -path_delay max -group_path_count 1 -endpoint_path_count 1 -fields {slew cap input net fanout} -format full_clock_expanded -corner nom
puts "ES-END"
