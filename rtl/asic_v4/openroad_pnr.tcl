# Full RTL-to-GDSII Place-and-Route & OpenSTA Signoff for odos_gate_core_v4 (IHP SG13G2 130 nm)
set pdk_ref  $::env(IHP_PDK_REF)
set orfs_dir $::env(ORFS_SG13G2_DIR)
set build_dir $::env(V4_BUILD_DIR)
set sdc_file  $::env(V4_SDC_FILE)

# 1. Read Liberty & LEF (IHP SG13G2 typ 1.20 V 25 C + RM_IHPSG13_1P_64x64_c2_bm_bist)
read_liberty "$pdk_ref/sg13g2_stdcell/lib/sg13g2_stdcell_typ_1p20V_25C.lib"
read_liberty "$pdk_ref/sg13g2_sram/lib/RM_IHPSG13_1P_64x64_c2_bm_bist_typ_1p20V_25C.lib"

read_lef "$pdk_ref/sg13g2_stdcell/lef/sg13g2_tech.lef"
read_lef "$pdk_ref/sg13g2_stdcell/lef/sg13g2_stdcell.lef"
read_lef "$pdk_ref/sg13g2_sram/lef/RM_IHPSG13_1P_64x64_c2_bm_bist.lef"

# 2. Load synthesized Liberty netlist & timing constraints
read_verilog "$build_dir/odos_v4_sg13g2_synth.v"
link_design odos_gate_core_v4
read_sdc $sdc_file

set_dont_use {sg13g2_lgcp_1 sg13g2_sighold sg13g2_slgcp_1 sg13g2_dfrbp_2}

# 3. Floorplan: 940.0 x 840.0 um die (core 892.0 x 793.80 um, ~53% util)
initialize_floorplan \
    -die_area  {0 0 940.0 840.0} \
    -core_area {24.0 22.68 916.0 816.48} \
    -site CoreSite

source "$orfs_dir/make_tracks.tcl"

# 4. Place single-port 64x64 foundry SRAM macro cleanly in upper quadrant with halo
set sram_inst [get_full_name [get_cells -hier *u_sram_64x64*]]
puts "V4_INFO: Placing SRAM macro instance: $sram_inst"
set odb_block [ord::get_db_block]
set odb_dbu [$odb_block getDbUnitsPerMicron]
set odb_sram [$odb_block findInst $sram_inst]
$odb_sram setOrient R0
$odb_sram setLocation [expr int(76.80 * $odb_dbu)] [expr int(737.10 * $odb_dbu)]
$odb_sram setPlacementStatus FIRM
cut_rows -halo_width_x 10.0 -halo_width_y 10.0

# 5. Place top-level I/O pins on Metal2 (V) / Metal3 (H)
place_pins -hor_layers Metal3 -ver_layers Metal2

# 6. Power Distribution Network (Stdcell Metal1 rails + TopMetal1/2 rings/stripes + SRAM Metal4 straps)
add_global_connection -net VDD -pin_pattern {^VDD$} -power
add_global_connection -net VDD -pin_pattern {^VDDPE$}
add_global_connection -net VDD -pin_pattern {^VDDCE$}
add_global_connection -net VDD -pin_pattern {^VDD!$} -power
add_global_connection -net VDD -pin_pattern {^VDDARRAY!$} -power
add_global_connection -net VSS -pin_pattern {^VSS$} -ground
add_global_connection -net VSS -pin_pattern {^VSSE$}
add_global_connection -net VSS -pin_pattern {^VSS!$} -ground
global_connect

set_voltage_domain -name CORE -power VDD -ground VSS

define_pdn_grid -name stdcell_grid -voltage_domains CORE
add_pdn_ring -grid stdcell_grid -layers {TopMetal1 TopMetal2} -widths {5.0 5.0} -spacings {2.0 2.0} -core_offsets {4.5 4.5}
add_pdn_stripe -grid stdcell_grid -layer Metal1 -width 0.44 -followpins -extend_to_core_ring
add_pdn_stripe -grid stdcell_grid -layer TopMetal1 -width 2.2 -pitch 75.6 -offset 13.6 -extend_to_core_ring
add_pdn_stripe -grid stdcell_grid -layer TopMetal2 -width 2.2 -pitch 75.6 -offset 13.6 -extend_to_core_ring
add_pdn_connect -grid stdcell_grid -layers {Metal1 TopMetal1}
add_pdn_connect -grid stdcell_grid -layers {TopMetal1 TopMetal2}

define_pdn_grid -macro -default -name sram_grid -voltage_domains CORE -halo {5.0 5.0 5.0 5.0}
add_pdn_connect -grid sram_grid -layers {Metal4 TopMetal1}

pdngen

# 7. Load official IHP SG13G2 metal/via RC parasitics
source "$orfs_dir/setRC.tcl"

# 8. Timing-driven Global & Detailed Placement
set_routing_layers -signal Metal2-Metal5 -clock Metal2-Metal5
set_global_routing_layer_adjustment Metal2-Metal5 0.05

global_placement -density 0.65 -timing_driven -routability_driven -pad_left 1 -pad_right 1
estimate_parasitics -placement
repair_design -slew_margin 10 -cap_margin 10
repair_tie_fanout -separation 0 sg13g2_tiehi/L_HI
repair_tie_fanout -separation 0 sg13g2_tielo/L_LO
detailed_placement
check_placement -verbose

# 9. Clock Tree Synthesis (TritonCTS) + Post-CTS Timing Closure
clock_tree_synthesis \
    -buf_list {sg13g2_buf_4 sg13g2_buf_8 sg13g2_buf_16} \
    -root_buf sg13g2_buf_8 \
    -sink_clustering_enable \
    -sink_clustering_max_diameter 60
repair_clock_nets
detailed_placement

set_propagated_clock [all_clocks]
estimate_parasitics -placement
repair_timing -setup -hold -setup_margin 0.50 -hold_margin 0.25
detailed_placement
check_placement -verbose

# 10. Global & Detailed Routing (Metal2-Metal5)
global_route -congestion_iterations 60 -allow_congestion

# Insert decap & standard-cell fillers before final detailed route
filler_placement {sg13g2_decap_8 sg13g2_decap_4 sg13g2_fill_8 sg13g2_fill_4 sg13g2_fill_2 sg13g2_fill_1}
detailed_route \
    -output_drc "$build_dir/odos_v4_drt.rpt" \
    -droute_end_iter 20 \
    -verbose 1

# 11. Post-Route Parasitic Extraction & Multi-Metric OpenSTA Signoff
if {[file exists "$orfs_dir/IHP_rcx_patterns.rules"]} {
    if {[catch {
        define_process_corner -ext_model_index 0 X
        extract_parasitics -ext_model_file "$orfs_dir/IHP_rcx_patterns.rules"
        write_spef "$build_dir/odos_v4_routed.spef"
        read_spef "$build_dir/odos_v4_routed.spef"
        puts "V4_PARASITICS_SOURCE=OPENRCX_DETAILED_SPEF"
    } err]} {
        puts "V4_OPENRCX_FALLBACK_REASON: $err"
        estimate_parasitics -global_routing
        puts "V4_PARASITICS_SOURCE=GLOBAL_ROUTING_RC"
    }
} else {
    estimate_parasitics -global_routing
    puts "V4_PARASITICS_SOURCE=GLOBAL_ROUTING_RC"
}

puts "=== V4_SIGNOFF_DESIGN_AREA ==="
report_design_area

puts "=== V4_SIGNOFF_WNS_TNS ==="
report_wns -digits 4
report_tns -digits 4
report_worst_slack -max -digits 4
report_worst_slack -min -digits 4

puts "=== V4_SIGNOFF_SETUP_PATH ==="
report_checks -path_delay max -fields {slew cap input_pins fanout} -digits 4

puts "=== V4_SIGNOFF_HOLD_PATH ==="
report_checks -path_delay min -fields {slew cap input_pins fanout} -digits 4

puts "=== V4_SIGNOFF_POWER ==="
report_power -digits 6

# Write routed DEF & Verilog netlist
write_def "$build_dir/odos_v4_routed.def"
write_verilog "$build_dir/odos_v4_routed.v"
puts "V4_OPENROAD_PNR_COMPLETE=TRUE"
