# PQMS-ODOS-MTSC-V-MAX-12-CORE-NANO (SYNC-33 v2 / V5.0-TOP-GDSII)
# Multi-Corner Signoff Timing Constraints (IHP SG13G2 130 nm)
set clk_name core_clk
set clk_port_name clk_i
if {[info exists ::env(V5_CLK_PERIOD_NS)] && $::env(V5_CLK_PERIOD_NS) ne ""} {
    set clk_period $::env(V5_CLK_PERIOD_NS)
} else {
    set clk_period 10.0
}

set clk_port [get_ports $clk_port_name]
create_clock -name $clk_name -period $clk_period $clk_port

set non_clock_inputs [lsearch -inline -all -not -exact [all_inputs] $clk_port]
set_input_delay  [expr $clk_period * 0.10] -clock $clk_name $non_clock_inputs
set_output_delay [expr $clk_period * 0.10] -clock $clk_name [all_outputs]

set_driving_cell -lib_cell sg13g2_buf_4 -pin X $non_clock_inputs
set_load 0.02 [all_outputs]

set_clock_uncertainty 0.15 [get_clocks $clk_name]
set_max_fanout 24 [current_design]
