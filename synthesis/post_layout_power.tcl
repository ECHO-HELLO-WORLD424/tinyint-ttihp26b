# Activity-annotated power report using the routed netlist and extracted SPEF.
# Required environment: REPO_ROOT, PDK_ROOT, ACTIVITY_VCD, POWER_REPORT.
set repo_root $::env(REPO_ROOT)
set pdk_root $::env(PDK_ROOT)
set corner_name nom_typ_1p20V_25C
set design_name tt_um_echo_hello_world424_tinyint

set liberty "$pdk_root/ihp-sg13g2/libs.ref/sg13g2_stdcell/lib/sg13g2_stdcell_typ_1p20V_25C.lib"
set netlist "$repo_root/runs/wokwi/final/nl/$design_name.nl.v"
set sdc "$repo_root/runs/wokwi/final/sdc/$design_name.sdc"
set spef "$repo_root/runs/wokwi/final/spef/nom/$design_name.nom.spef"

define_corners $corner_name
read_liberty -corner $corner_name $liberty
read_verilog $netlist
link_design $design_name
read_sdc $sdc
read_spef -corner $corner_name $spef
read_vcd -scope power_activity_tb/user_project $::env(ACTIVITY_VCD)

set corner [lindex [sta::corners] 0]
report_activity_annotation
report_power -corner $corner -digits 9 > $::env(POWER_REPORT)
puts "POWER_REPORT=$::env(POWER_REPORT)"
