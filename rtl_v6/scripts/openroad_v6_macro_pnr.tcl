# =============================================================================
# rtl_v6/scripts/openroad_v6_macro_pnr.tcl
#
# PQMS / V-MAX-12-CORE-JEDI (SYNC-37 / V6.0-JEDI-MACRO-HARDENING)
# Reusable IHP SG13G2 130 nm Hard-Macro PnR + 3-Corner OpenSTA + Abstract Export
#   - Supports: jedi_coherence_tile (940.0 x 840.0 um, 64x64 SRAM)
#               jedi_central_spine  (3100.0 x 580.0 um, R0 512x64 SRAM)
#   - G2: Signal Metal1-Metal4, Clock Metal2-Metal4, Local PDN Metal5 (M5->M4),
#         TopMetal1 & TopMetal2 100% EMPTY/UNOBSTRUCTED!
#   - G3: Hard dont_touch on TMR voter, pad_safe_en, ASYNC_REG, ICGs, canary.
# =============================================================================

set pdk_ref    $::env(IHP_PDK_REF)
set orfs_dir   $::env(ORFS_SG13G2_DIR)
set build_dir  $::env(V6_BUILD_DIR)
set macro_dir  $::env(V6_MACRO_DIR)
set macro_name $::env(V6_MACRO_NAME)
set sdc_file   $::env(V6_SDC_FILE)
set die_x      [expr double($::env(V6_DIE_X_UM))]
set die_y      [expr double($::env(V6_DIE_Y_UM))]
set sram_type  $::env(V6_SRAM_TYPE)
set sram_x     [expr double($::env(V6_SRAM_X_UM))]
set sram_y     [expr double($::env(V6_SRAM_Y_UM))]
set sram_halo  [expr double($::env(V6_SRAM_HALO_UM))]

set_thread_count 16

read_liberty "$pdk_ref/sg13g2_stdcell/lib/sg13g2_stdcell_typ_1p20V_25C.lib"
read_liberty "$pdk_ref/sg13g2_sram/lib/${sram_type}_typ_1p20V_25C.lib"

read_lef "$pdk_ref/sg13g2_stdcell/lef/sg13g2_tech.lef"
read_lef "$pdk_ref/sg13g2_stdcell/lef/sg13g2_stdcell.lef"
read_lef "$pdk_ref/sg13g2_sram/lef/${sram_type}.lef"

read_verilog "$build_dir/${macro_name}_synth.v"
link_design $macro_name
read_sdc $sdc_file

set_dont_use {sg13g2_sighold sg13g2_slgcp_1 sg13g2_dfrbp_2}

set core_x0 20.0
set core_y0 20.16
set core_x1 [expr $die_x - 20.0]
set core_y1 [expr $die_y - 20.16]

puts "V6_INFO: Floorplan $macro_name die=0 0 $die_x $die_y core=$core_x0 $core_y0 $core_x1 $core_y1"
initialize_floorplan \
    -die_area  [list 0 0 $die_x $die_y] \
    -core_area [list $core_x0 $core_y0 $core_x1 $core_y1] \
    -site CoreSite

source "$orfs_dir/make_tracks.tcl"

# Place internal foundry SRAM macro horizontally in R0 (MANDATORY real-PDK fix!)
set sram_cells [get_cells -hier -filter "ref_name == $sram_type" *]
foreach sc $sram_cells {
    set sram_inst [get_full_name $sc]
    puts "V6_INFO: Placing $sram_type ($sram_inst) at ($sram_x, $sram_y) R0"
    set odb_block [ord::get_db_block]
    set odb_dbu [$odb_block getDbUnitsPerMicron]
    set odb_sram [$odb_block findInst $sram_inst]
    $odb_sram setOrient R0
    $odb_sram setLocation [expr int($sram_x * $odb_dbu)] [expr int($sram_y * $odb_dbu)]
    $odb_sram setPlacementStatus FIRM
}
cut_rows -halo_width_x $sram_halo -halo_width_y $sram_halo

# Place macro pins on Metal2 (V) / Metal3 (H)
place_pins -hor_layers Metal3 -ver_layers Metal2

# G2: Local Macro PDN strictly on Metal1..Metal5 (TopMetal1 & TopMetal2 100% EMPTY!)
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
add_pdn_ring -grid stdcell_grid -layers {Metal4 Metal5} -widths {3.0 3.0} -spacings {1.5 1.5} -core_offsets {3.0 3.0}
add_pdn_stripe -grid stdcell_grid -layer Metal1 -width 0.44 -followpins -extend_to_core_ring
add_pdn_stripe -grid stdcell_grid -layer Metal4 -width 1.6 -pitch 120.0 -offset 20.0 -extend_to_core_ring
add_pdn_stripe -grid stdcell_grid -layer Metal5 -width 2.0 -pitch 120.0 -offset 20.0 -extend_to_core_ring
add_pdn_connect -grid stdcell_grid -layers {Metal1 Metal4}
add_pdn_connect -grid stdcell_grid -layers {Metal4 Metal5}

define_pdn_grid -macro -default -name sram_grid -voltage_domains CORE -halo {5.0 5.0 5.0 5.0}
add_pdn_connect -grid sram_grid -layers {Metal4 Metal5}

pdngen

# G3: Hard dont_touch on safety-critical cells/nets AFTER global_connect & pdngen
foreach pat {*tmr_rep* *pad_safe_en* *u_canary* *sync_safe* *wgray_sync* *rgray_sync*} {
    catch { set_dont_touch [get_cells -hier $pat] }
    catch { set_dont_touch [get_nets -hier $pat] }
}

source "$orfs_dir/setRC.tcl"

insert_tiecells sg13g2_tiehi/L_HI -prefix TIEHI_
insert_tiecells sg13g2_tielo/L_LO -prefix TIELO_

# G2: Strict Metal1-Metal4 signal routing cap (Clock Metal2-Metal4)
set_routing_layers -signal Metal2-Metal4 -clock Metal2-Metal4
set_global_routing_layer_adjustment Metal2 0.15
set_global_routing_layer_adjustment Metal3 0.10
set_global_routing_layer_adjustment Metal4 0.05

global_placement -density 0.82 -routability_driven -pad_left 1 -pad_right 1
detailed_placement
check_placement -verbose

clock_tree_synthesis \
    -buf_list {sg13g2_buf_4 sg13g2_buf_8 sg13g2_buf_16} \
    -root_buf sg13g2_buf_8 \
    -sink_clustering_enable \
    -sink_clustering_max_diameter 60
detailed_placement
check_placement -verbose
global_connect
foreach pat {*u_root_icg* *u_tile_icg*} {
    catch { set_dont_touch [get_cells -hier $pat] }
}
set_propagated_clock [all_clocks]

global_route -congestion_iterations 100 -allow_congestion -verbose

filler_placement {sg13g2_decap_8 sg13g2_decap_4 sg13g2_fill_8 sg13g2_fill_4 sg13g2_fill_2 sg13g2_fill_1}
global_connect

detailed_route -output_drc "$build_dir/${macro_name}_drt.rpt" -droute_end_iter 15 -verbose 1

set ant_post [check_antennas]
puts "V6_ANTENNA_POST_DRT=$ant_post"

define_process_corner -ext_model_index 0 X
extract_parasitics -ext_model_file "$orfs_dir/IHP_rcx_patterns.rules"
write_spef "$build_dir/${macro_name}.spef"

puts "=== V6_MACRO_AREA ==="
report_design_area

write_db "$build_dir/${macro_name}_routed.odb"
write_def "$build_dir/${macro_name}_routed.def"
write_verilog "$build_dir/${macro_name}_routed.v"
write_verilog -include_pwr_gnd -remove_cells "sg13g2_fill* sg13g2_decap*" "$macro_dir/${macro_name}_pwr.v"
write_abstract_lef "$macro_dir/${macro_name}.lef"

puts "V6_MACRO_PNR_COMPLETE=${macro_name}"
