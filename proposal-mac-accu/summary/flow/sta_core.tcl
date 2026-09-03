set netlist $::env(NETLIST)
set vcd $::env(ACTIVITY_VCD)
set rpt $::env(POWER_REPORT)
define_corners nom
read_liberty /pdk/sg13g2_stdcell_typ.lib
read_verilog $netlist
link_design tiny_int_core
create_clock -name clk -period 20 -waveform {0 10} [get_ports clk]
read_vcd -scope tb_core/dut $vcd
report_activity_annotation
report_power -digits 6 > $rpt
