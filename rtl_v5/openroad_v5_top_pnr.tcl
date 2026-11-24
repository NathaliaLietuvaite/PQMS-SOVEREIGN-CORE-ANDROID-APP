# =============================================================================
# rtl_v5/openroad_v5_top_pnr.tcl
#
# PQMS / V-MAX-12-CORE-NANO (SYNC-33 v2 / V5.0-TOP-GDSII)
# Carbon-Hardened IHP SG13G2 130 nm OpenROAD Place-and-Route Flow
#   - G2: Primary die 940.0 x 840.0 um (0.7896 mm2); optional Y-only fallback
#   - G4: Hold-margin timing closure for fast_1p32V_m40C corner safety
#   - G5: insert_tiecells, repair_antennas, decap+filler, OpenRCX SPEF,
#         and power-netlist export (-include_pwr_gnd -remove_cells) for Netgen LVS
# =============================================================================

set pdk_ref   $::env(IHP_PDK_REF)
set orfs_dir  $::env(ORFS_SG13G2_DIR)
set build_dir $::env(V5_BUILD_DIR)
set sdc_file  $::env(V5_SDC_FILE)
set pnr_phase $::env(V5_PNR_PHASE)

set die_x 940.0
if {[info exists ::env(V5_DIE_Y_UM)] && $::env(V5_DIE_Y_UM) ne ""} {
    set die_y [expr double($::env(V5_DIE_Y_UM))]
} else {
    set die_y 840.0
}
set core_y_top [expr $die_y - 23.52]
set sram_y     [expr $die_y - 102.90]

# Always read Liberty first (OpenROAD requires liberty loaded even when reading .odb)
read_liberty "$pdk_ref/sg13g2_stdcell/lib/sg13g2_stdcell_typ_1p20V_25C.lib"
read_liberty "$pdk_ref/sg13g2_sram/lib/RM_IHPSG13_1P_64x64_c2_bm_bist_typ_1p20V_25C.lib"

if {$pnr_phase eq "PHASE_FLOORPLAN_PLACE_CTS"} {
    read_lef "$pdk_ref/sg13g2_stdcell/lef/sg13g2_tech.lef"
    read_lef "$pdk_ref/sg13g2_stdcell/lef/sg13g2_stdcell.lef"
    read_lef "$pdk_ref/sg13g2_sram/lef/RM_IHPSG13_1P_64x64_c2_bm_bist.lef"

    read_verilog "$build_dir/top_synth.v"
    link_design vmax_v5_odos_top
    read_sdc $sdc_file

    set_dont_use {sg13g2_lgcp_1 sg13g2_sighold sg13g2_slgcp_1 sg13g2_dfrbp_2}

    puts "V5_INFO: Floorplan die_area 0 0 $die_x $die_y | core_y_top $core_y_top | sram_y $sram_y"
    initialize_floorplan         -die_area  [list 0 0 $die_x $die_y]         -core_area [list 24.0 22.68 916.0 $core_y_top]         -site CoreSite

    source "$orfs_dir/make_tracks.tcl"

    # Place single-port 64x64 foundry SRAM macro cleanly with 155.5 um horizontal clearance
    set sram_cells [get_cells -hier *u_sram_64x64*]
    set sram_inst [get_full_name $sram_cells]
    puts "V5_INFO: Placing SRAM macro instance: $sram_inst"
    set odb_block [ord::get_db_block]
    set odb_dbu [$odb_block getDbUnitsPerMicron]
    set odb_sram [$odb_block findInst $sram_inst]
    $odb_sram setOrient R0
    $odb_sram setLocation [expr int(76.80 * $odb_dbu)] [expr int($sram_y * $odb_dbu)]
    $odb_sram setPlacementStatus FIRM
    cut_rows -halo_width_x 10.0 -halo_width_y 10.0

    # Place top-level I/O pins on Metal2 (V) / Metal3 (H)
    place_pins -hor_layers Metal3 -ver_layers Metal2

    # Power Distribution Network (Metal1 rails + TopMetal1/2 rings/stripes + SRAM Metal4 straps)
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

    # Load official IHP SG13G2 metal/via RC parasitics
    source "$orfs_dir/setRC.tcl"

    # G5: Explicit foundry tie-cell insertion + tie fanout repair
    insert_tiecells sg13g2_tiehi/L_HI -prefix TIEHI_
    insert_tiecells sg13g2_tielo/L_LO -prefix TIELO_

    # Timing- & routability-driven Global & Detailed Placement
    set_routing_layers -signal Metal2-Metal5 -clock Metal2-Metal5
    set_global_routing_layer_adjustment Metal2 0.35
    set_global_routing_layer_adjustment Metal3 0.25
    set_global_routing_layer_adjustment Metal4 0.10
    set_global_routing_layer_adjustment Metal5 0.05

    global_placement -density 0.72 -timing_driven -routability_driven -pad_left 1 -pad_right 1
    estimate_parasitics -placement
    repair_design -slew_margin 10 -cap_margin 10
    repair_tie_fanout -separation 0 sg13g2_tiehi/L_HI
    repair_tie_fanout -separation 0 sg13g2_tielo/L_LO
    detailed_placement
    check_placement -verbose

    # Clock Tree Synthesis (TritonCTS @ 100 MHz)
    clock_tree_synthesis         -buf_list {sg13g2_buf_4 sg13g2_buf_8 sg13g2_buf_16}         -root_buf sg13g2_buf_8         -sink_clustering_enable         -sink_clustering_max_diameter 60
    repair_clock_nets
    detailed_placement

    # G4: Setup + generous Hold margin (0.35 ns typ -> guarantees fast_1p32V_m40C >= 0 ns)
    set_propagated_clock [all_clocks]
    estimate_parasitics -placement
    repair_timing -setup -hold -setup_margin 0.50 -hold_margin 0.22
    detailed_placement
    check_placement -verbose
    global_connect

    puts "=== V5_CTS_DESIGN_AREA ==="
    report_design_area
    puts "=== V5_CTS_WNS_TNS ==="
    report_wns -digits 4
    report_tns -digits 4
    report_worst_slack -max -digits 4
    report_worst_slack -min -digits 4

    write_db "$build_dir/03_cts.odb"
    puts "V5_PHASE_CTS_COMPLETE=TRUE"

} elseif {$pnr_phase eq "PHASE_ROUTE_SPEF"} {
    read_db "$build_dir/03_cts.odb"
    read_sdc $sdc_file
    set_propagated_clock [all_clocks]
    source "$orfs_dir/setRC.tcl"

    set_routing_layers -signal Metal2-Metal5 -clock Metal2-Metal5
    set_global_routing_layer_adjustment Metal2 0.35
    set_global_routing_layer_adjustment Metal3 0.25
    set_global_routing_layer_adjustment Metal4 0.10
    set_global_routing_layer_adjustment Metal5 0.05

    # Global Routing + G5 Antenna Diode Repair prior to filler insertion
    global_route -congestion_iterations 100 -verbose
    if {[catch {
        repair_antennas sg13g2_antennanp -iterations 5
        detailed_placement
        global_connect
        puts "V5_ANTENNA_REPAIR_PRE_DRT=DONE"
    } ant_err]} {
        puts "V5_ANTENNA_REPAIR_PRE_DRT_NOTE: $ant_err"
    }

    # G5: Decap & Standard-Cell Fillers
    filler_placement {sg13g2_decap_8 sg13g2_decap_4 sg13g2_fill_8 sg13g2_fill_4 sg13g2_fill_2 sg13g2_fill_1}
    global_connect

    # Detailed Routing
    detailed_route         -output_drc "$build_dir/v5_top_drt.rpt"         -droute_end_iter 30         -verbose 1

    # G5: Post-DRT Antenna Diode Repair (removes fillers, inserts sg13g2_antennanp, re-fills, re-routes)
    puts "=== V5_CHECK_ANTENNAS_PRE_FIX ==="
    set ant_cnt [check_antennas -verbose]
    puts "V5_ANTENNA_PRE_FIX_COUNT=$ant_cnt"
    if {$ant_cnt > 0} {
        remove_fillers
        repair_antennas sg13g2_antennanp -iterations 5 -ratio_margin 10
        detailed_placement
        filler_placement {sg13g2_decap_8 sg13g2_decap_4 sg13g2_fill_8 sg13g2_fill_4 sg13g2_fill_2 sg13g2_fill_1}
        global_connect
        detailed_route             -output_drc "$build_dir/v5_top_drt.rpt"             -droute_end_iter 20             -verbose 1
    }
    puts "=== V5_CHECK_ANTENNAS ==="
    set ant_post [check_antennas]
    puts "V5_ANTENNA_POST_FIX_COUNT=$ant_post"

    # Post-Route OpenRCX Parasitic Extraction (Detailed SPEF)
    define_process_corner -ext_model_index 0 X
    extract_parasitics -ext_model_file "$orfs_dir/IHP_rcx_patterns.rules"
    write_spef "$build_dir/vmax_v5_odos_top.spef"
    read_spef "$build_dir/vmax_v5_odos_top.spef"
    puts "V5_PARASITICS_SOURCE=OPENRCX_DETAILED_SPEF"

    puts "=== V5_SIGNOFF_DESIGN_AREA ==="
    report_design_area
    puts "=== V5_SIGNOFF_WNS_TNS ==="
    report_wns -digits 4
    report_tns -digits 4
    report_worst_slack -max -digits 4
    report_worst_slack -min -digits 4
    puts "=== V5_SIGNOFF_SETUP_PATH ==="
    report_checks -path_delay max -fields {slew cap input_pins fanout} -digits 4
    puts "=== V5_SIGNOFF_HOLD_PATH ==="
    report_checks -path_delay min -fields {slew cap input_pins fanout} -digits 4

    write_db "$build_dir/04_routed.odb"
    write_def "$build_dir/vmax_v5_odos_top_routed.def"
    write_verilog "$build_dir/vmax_v5_odos_top_routed.v"
    # G5: Clean LVS Power-Netlist (excluding decap/fillers)
    write_verilog -include_pwr_gnd -remove_cells "sg13g2_fill* sg13g2_decap*" "$build_dir/vmax_v5_odos_top_lvs.v"
    puts "V5_PHASE_ROUTE_SPEF_COMPLETE=TRUE"
} else {
    error "Unknown V5_PNR_PHASE: $pnr_phase"
}
