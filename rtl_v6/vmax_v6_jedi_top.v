// =============================================================================
// rtl_v6/vmax_v6_jedi_top.v
// WP-1.6 & G1-G5: Top-Level V-MAX-12-CORE-JEDI (5.50 x 5.50 mm, QFN-64)
// - 12x jedi_coherence_tile (North 0..5, South 6..11, H-symmetric Kagome mesh)
// - 1x  jedi_central_spine  (580 um central sovereign spine + R90 512x64 T_I/O)
// - 4x  RM_IHPSG13_1P_1024x64_c2_bm_bist (2 West BANK_A + 2 East BANK_B = 32 KB)
// - Complete QFN-64 (40 Signal + 24 Power = 64/64 Pads) Padring Wrapper:
//   * 4 mA sg13g2_IOPadOut4mA on Safety Island, 16 mA only on OSPI
//   * Kelvin-separated VDD/VSS (1.2 V Core/EPAD) vs. IOVDD/IOVSS (3.3 V Padring)
//   * Active-high c2p_en verified from IHP SG13G2 sg13g2_io.v in WP-0
// =============================================================================
`timescale 1ns/1ps
`default_nettype none

module vmax_v6_jedi_top (
`ifdef USE_POWER_PINS
    inout  wire       VDD,
    inout  wire       VSS,
    inout  wire       IOVDD,
    inout  wire       IOVSS,
`endif
    // Host 100 MHz SDR OSPI (12 Signal Pads, 16 mA)
    inout  wire [7:0] OSPI_IO,
    input  wire       OSPI_CLK_I,
    input  wire       OSPI_CS_N_I,
    output wire       OSPI_RDY_O,
    output wire       OSPI_IRQ_N_O,

    // Debug / KAT SPI-Slave (4 Signal Pads)
    input  wire       DBG_SCK_I,
    input  wire       DBG_MOSI_I,
    output wire       DBG_MISO_O,
    input  wire       DBG_CS_N_I,

    // Fail-Closed Thermal & Power Supervisors (5 Signal Pads)
    input  wire       THERM_82_N,
    input  wire       THERM_105_N,
    input  wire       THERM_122_N,
    input  wire       CAP_GOOD_I,
    input  wire       GEAR1_ALLOW_I,

    // Clock, Reset & Mode (5 Signal Pads)
    input  wire       CLK_IN,
    input  wire       RST_N,
    input  wire       MODE_DMR_I,
    input  wire       SCOUT_BYPASS_I,
    output wire       BANK_ACTIVE_O,

    // VSS-Shielded Safety Island (8 Signal Pads, 4 mA)
    output wire       ACT_EN_P,
    output wire       ACT_EN_N,
    output wire       TAI_HEARTBEAT_O,
    input  wire       VETO_N,
    output wire       DMR_FAULT_O,
    output wire       COSTBOUND_TRIP_O,
    output wire       EPOCH_ACK_O,
    output wire       KAT_PASS_O,

    // Test / Telemetry / Spare (6 Signal Pads -> 12+4+5+5+8+6 = 40 Signal + 24 Power = 64/64)
    output wire       CLK_MON_O,
    output wire [1:0] GEAR_STAT,
    output wire       TILE_FAULT_O,
    input  wire       TEST_EN_I,
    inout  wire       SPARE_IO
);

    // =========================================================================
    // 1. QFN-64 Padring Wrapper (Foundry sg13g2_io vs. Behavioral Pass-Through)
    // =========================================================================
    wire [7:0] ospi_io_in_w;
    wire       ospi_clk_w;
    wire       ospi_cs_n_w;
    wire       ospi_rdy_w;
    wire       ospi_irq_n_w;

    wire       dbg_sck_w;
    wire       dbg_mosi_w;
    wire       dbg_miso_w;
    wire       dbg_cs_n_w;

    wire       therm_82_n_w;
    wire       therm_105_n_w;
    wire       therm_122_n_w;
    wire       cap_good_w;
    wire       gear1_allow_w;

    wire       clk_in_w;
    wire       rst_n_w;
    wire       mode_dmr_w;
    wire       scout_bypass_w;
    wire       bank_active_w;

    wire       act_en_p_w;
    wire       act_en_n_w;
    wire       tai_hb_w;
    wire       veto_n_w;
    wire       dmr_fault_w;
    wire       cb_trip_w;
    wire       epoch_ack_w;
    wire       kat_pass_w;

    wire       clk_mon_w;
    wire [1:0] gear_stat_w;
    wire       tile_fault_w;
    wire       test_en_w;
    wire       spare_in_w;

`ifdef SYNTH_IHP_SG13G2
    wire tie_lo_pad_w;
    (* keep = 1, dont_touch = "true" *)
    sg13g2_tielo u_tielo_pad (.L_LO(tie_lo_pad_w));

`ifdef USE_POWER_PINS
    wire vdd_ring   = VDD;
    wire vss_ring   = VSS;
    wire iovdd_ring = IOVDD;
    wire iovss_ring = IOVSS;

    // 4 Corners + 24 Power Pads (8 VDD, 8 VSS, 4 IOVDD, 4 IOVSS — Kelvin-separated!)
    genvar gp_pwr;
    generate
        for (gp_pwr = 0; gp_pwr < 4; gp_pwr = gp_pwr + 1) begin : g_corners_and_io_pwr
            (* keep = 1, dont_touch = "true" *) sg13g2_Corner     u_pad_crn   (.vdd(vdd_ring), .vss(vss_ring), .iovdd(iovdd_ring), .iovss(iovss_ring));
            (* keep = 1, dont_touch = "true" *) sg13g2_IOPadIOVdd u_pad_iovdd (.vdd(vdd_ring), .vss(vss_ring), .iovdd(iovdd_ring), .iovss(iovss_ring));
            (* keep = 1, dont_touch = "true" *) sg13g2_IOPadIOVss u_pad_iovss (.vdd(vdd_ring), .vss(vss_ring), .iovdd(iovdd_ring), .iovss(iovss_ring));
        end
        for (gp_pwr = 0; gp_pwr < 8; gp_pwr = gp_pwr + 1) begin : g_core_pwr_pads
            (* keep = 1, dont_touch = "true" *) sg13g2_IOPadVdd u_pad_vdd (.vdd(vdd_ring), .vss(vss_ring), .iovdd(iovdd_ring), .iovss(iovss_ring));
            (* keep = 1, dont_touch = "true" *) sg13g2_IOPadVss u_pad_vss (.vdd(vdd_ring), .vss(vss_ring), .iovdd(iovdd_ring), .iovss(iovss_ring));
        end
    endgenerate
`endif

    // 40 Signal Pads (Liberty-clean signal pins; PG pins wired by OpenROAD global_connect / USE_POWER_PINS)
    genvar gp;
    generate
        for (gp = 0; gp < 8; gp = gp + 1) begin : g_ospi_io_pads
            (* keep = 1, dont_touch = "true" *) sg13g2_IOPadInOut16mA u_pad_ospi_io (
                .pad(OSPI_IO[gp]), .c2p(tie_lo_pad_w), .p2c(ospi_io_in_w[gp]), .c2p_en(tie_lo_pad_w)
            );
        end
    endgenerate

    // OSPI control pads (16 mA outputs)
    (* keep = 1, dont_touch = "true" *) sg13g2_IOPadIn      u_pad_ospi_clk (.pad(OSPI_CLK_I),   .p2c(ospi_clk_w));
    (* keep = 1, dont_touch = "true" *) sg13g2_IOPadIn      u_pad_ospi_cs  (.pad(OSPI_CS_N_I),  .p2c(ospi_cs_n_w));
    (* keep = 1, dont_touch = "true" *) sg13g2_IOPadOut16mA u_pad_ospi_rdy (.pad(OSPI_RDY_O),   .c2p(ospi_rdy_w));
    (* keep = 1, dont_touch = "true" *) sg13g2_IOPadOut16mA u_pad_ospi_irq (.pad(OSPI_IRQ_N_O), .c2p(ospi_irq_n_w));

    // Debug SPI pads
    (* keep = 1, dont_touch = "true" *) sg13g2_IOPadIn     u_pad_dbg_sck  (.pad(DBG_SCK_I),  .p2c(dbg_sck_w));
    (* keep = 1, dont_touch = "true" *) sg13g2_IOPadIn     u_pad_dbg_mosi (.pad(DBG_MOSI_I), .p2c(dbg_mosi_w));
    (* keep = 1, dont_touch = "true" *) sg13g2_IOPadOut4mA u_pad_dbg_miso (.pad(DBG_MISO_O), .c2p(dbg_miso_w));
    (* keep = 1, dont_touch = "true" *) sg13g2_IOPadIn     u_pad_dbg_cs   (.pad(DBG_CS_N_I), .p2c(dbg_cs_n_w));

    // Supervisor, Clock, Reset & Mode pads
    (* keep = 1, dont_touch = "true" *) sg13g2_IOPadIn     u_pad_t82  (.pad(THERM_82_N),     .p2c(therm_82_n_w));
    (* keep = 1, dont_touch = "true" *) sg13g2_IOPadIn     u_pad_t105 (.pad(THERM_105_N),    .p2c(therm_105_n_w));
    (* keep = 1, dont_touch = "true" *) sg13g2_IOPadIn     u_pad_t122 (.pad(THERM_122_N),    .p2c(therm_122_n_w));
    (* keep = 1, dont_touch = "true" *) sg13g2_IOPadIn     u_pad_cap  (.pad(CAP_GOOD_I),     .p2c(cap_good_w));
    (* keep = 1, dont_touch = "true" *) sg13g2_IOPadIn     u_pad_g1a  (.pad(GEAR1_ALLOW_I),  .p2c(gear1_allow_w));
    (* keep = 1, dont_touch = "true" *) sg13g2_IOPadIn     u_pad_clk  (.pad(CLK_IN),         .p2c(clk_in_w));
    (* keep = 1, dont_touch = "true" *) sg13g2_IOPadIn     u_pad_rst  (.pad(RST_N),          .p2c(rst_n_w));
    (* keep = 1, dont_touch = "true" *) sg13g2_IOPadIn     u_pad_dmr  (.pad(MODE_DMR_I),     .p2c(mode_dmr_w));
    (* keep = 1, dont_touch = "true" *) sg13g2_IOPadIn     u_pad_sct  (.pad(SCOUT_BYPASS_I), .p2c(scout_bypass_w));
    (* keep = 1, dont_touch = "true" *) sg13g2_IOPadOut4mA u_pad_bnk  (.pad(BANK_ACTIVE_O),  .c2p(bank_active_w));

    // Safety Island (strictly 4 mA sg13g2_IOPadOut4mA to minimize SSO crosstalk!)
    (* keep = 1, dont_touch = "true" *) sg13g2_IOPadOut4mA u_pad_actp (.pad(ACT_EN_P),         .c2p(act_en_p_w));
    (* keep = 1, dont_touch = "true" *) sg13g2_IOPadOut4mA u_pad_actn (.pad(ACT_EN_N),         .c2p(act_en_n_w));
    (* keep = 1, dont_touch = "true" *) sg13g2_IOPadOut4mA u_pad_hb   (.pad(TAI_HEARTBEAT_O),  .c2p(tai_hb_w));
    (* keep = 1, dont_touch = "true" *) sg13g2_IOPadIn     u_pad_veto (.pad(VETO_N),           .p2c(veto_n_w));
    (* keep = 1, dont_touch = "true" *) sg13g2_IOPadOut4mA u_pad_dmrf (.pad(DMR_FAULT_O),      .c2p(dmr_fault_w));
    (* keep = 1, dont_touch = "true" *) sg13g2_IOPadOut4mA u_pad_cb   (.pad(COSTBOUND_TRIP_O), .c2p(cb_trip_w));
    (* keep = 1, dont_touch = "true" *) sg13g2_IOPadOut4mA u_pad_epk  (.pad(EPOCH_ACK_O),      .c2p(epoch_ack_w));
    (* keep = 1, dont_touch = "true" *) sg13g2_IOPadOut4mA u_pad_kat  (.pad(KAT_PASS_O),       .c2p(kat_pass_w));

    // Telemetry & Spare pads (6 pads)
    (* keep = 1, dont_touch = "true" *) sg13g2_IOPadOut4mA u_pad_cmon (.pad(CLK_MON_O),    .c2p(clk_mon_w));
    (* keep = 1, dont_touch = "true" *) sg13g2_IOPadOut4mA u_pad_gs0  (.pad(GEAR_STAT[0]), .c2p(gear_stat_w[0]));
    (* keep = 1, dont_touch = "true" *) sg13g2_IOPadOut4mA u_pad_gs1  (.pad(GEAR_STAT[1]), .c2p(gear_stat_w[1]));
    (* keep = 1, dont_touch = "true" *) sg13g2_IOPadOut4mA u_pad_tflt (.pad(TILE_FAULT_O), .c2p(tile_fault_w));
    (* keep = 1, dont_touch = "true" *) sg13g2_IOPadIn     u_pad_tste (.pad(TEST_EN_I),    .p2c(test_en_w));
    (* keep = 1, dont_touch = "true" *) sg13g2_IOPadInOut4mA u_pad_spr (
        .pad(SPARE_IO), .c2p(tie_lo_pad_w), .p2c(spare_in_w), .c2p_en(tie_lo_pad_w)
    );
`else
    assign ospi_io_in_w   = OSPI_IO;
    assign ospi_clk_w     = OSPI_CLK_I;
    assign ospi_cs_n_w    = OSPI_CS_N_I;
    assign OSPI_RDY_O     = ospi_rdy_w;
    assign OSPI_IRQ_N_O   = ospi_irq_n_w;

    assign dbg_sck_w      = DBG_SCK_I;
    assign dbg_mosi_w     = DBG_MOSI_I;
    assign DBG_MISO_O     = dbg_miso_w;
    assign dbg_cs_n_w     = DBG_CS_N_I;

    assign therm_82_n_w   = THERM_82_N;
    assign therm_105_n_w  = THERM_105_N;
    assign therm_122_n_w  = THERM_122_N;
    assign cap_good_w     = CAP_GOOD_I;
    assign gear1_allow_w  = GEAR1_ALLOW_I;

    assign clk_in_w       = CLK_IN;
    assign rst_n_w        = RST_N;
    assign mode_dmr_w     = MODE_DMR_I;
    assign scout_bypass_w = SCOUT_BYPASS_I;
    assign BANK_ACTIVE_O  = bank_active_w;

    assign ACT_EN_P       = act_en_p_w;
    assign ACT_EN_N       = act_en_n_w;
    assign TAI_HEARTBEAT_O= tai_hb_w;
    assign veto_n_w       = VETO_N;
    assign DMR_FAULT_O    = dmr_fault_w;
    assign COSTBOUND_TRIP_O = cb_trip_w;
    assign EPOCH_ACK_O    = epoch_ack_w;
    assign KAT_PASS_O     = kat_pass_w;

    assign CLK_MON_O      = clk_mon_w;
    assign GEAR_STAT      = gear_stat_w;
    assign TILE_FAULT_O   = tile_fault_w;
    assign test_en_w      = TEST_EN_I;
    assign spare_in_w     = SPARE_IO;
`endif

    // =========================================================================
    // 2. Central Sovereign Spine + 4x Flank 1024x64 SRAMs + 12x Coherence Tiles
    // =========================================================================
    wire        clk_core_w;
    wire        clk_dma_w;
    wire        bank_clk_en_a_w;
    wire        bank_clk_en_b_w;
    wire        gclk_bank_a_w;
    wire        gclk_bank_b_w;

    // Balanced Bank ICGs on top-level H-tree (G4)
    (* keep = 1, dont_touch = "true" *)
    jedi_icg_cell u_bank_icg_a (.clk_i(clk_in_w), .en_i(bank_clk_en_a_w), .gclk_o(gclk_bank_a_w));
    (* keep = 1, dont_touch = "true" *)
    jedi_icg_cell u_bank_icg_b (.clk_i(clk_in_w), .en_i(bank_clk_en_b_w), .gclk_o(gclk_bank_b_w));

    wire        sram_a_lo_men_w, sram_a_lo_wen_w, sram_a_lo_ren_w;
    wire [9:0]  sram_a_lo_addr_w;
    wire [63:0] sram_a_lo_din_w, sram_a_lo_dout_w;

    wire        sram_a_hi_men_w, sram_a_hi_wen_w, sram_a_hi_ren_w;
    wire [9:0]  sram_a_hi_addr_w;
    wire [63:0] sram_a_hi_din_w, sram_a_hi_dout_w;

    wire        sram_b_lo_men_w, sram_b_lo_wen_w, sram_b_lo_ren_w;
    wire [9:0]  sram_b_lo_addr_w;
    wire [63:0] sram_b_lo_din_w, sram_b_lo_dout_w;

    wire        sram_b_hi_men_w, sram_b_hi_wen_w, sram_b_hi_ren_w;
    wire [9:0]  sram_b_hi_addr_w;
    wire [63:0] sram_b_hi_din_w, sram_b_hi_dout_w;

    // West Flank (BANK_A): 2x RM_IHPSG13_1P_1024x64_c2_bm_bist (16 KB)
    jedi_sram_1024x64_wrap u_sram_west_a_lo (
        .clk_i(gclk_bank_a_w), .men_i(sram_a_lo_men_w), .wen_i(sram_a_lo_wen_w),
        .ren_i(sram_a_lo_ren_w), .addr_i(sram_a_lo_addr_w), .din_i(sram_a_lo_din_w), .dout_o(sram_a_lo_dout_w)
    );
    jedi_sram_1024x64_wrap u_sram_west_a_hi (
        .clk_i(gclk_bank_a_w), .men_i(sram_a_hi_men_w), .wen_i(sram_a_hi_wen_w),
        .ren_i(sram_a_hi_ren_w), .addr_i(sram_a_hi_addr_w), .din_i(sram_a_hi_din_w), .dout_o(sram_a_hi_dout_w)
    );

    // East Flank (BANK_B): 2x RM_IHPSG13_1P_1024x64_c2_bm_bist (16 KB, >3.1 mm SEU separation)
    jedi_sram_1024x64_wrap u_sram_east_b_lo (
        .clk_i(gclk_bank_b_w), .men_i(sram_b_lo_men_w), .wen_i(sram_b_lo_wen_w),
        .ren_i(sram_b_lo_ren_w), .addr_i(sram_b_lo_addr_w), .din_i(sram_b_lo_din_w), .dout_o(sram_b_lo_dout_w)
    );
    jedi_sram_1024x64_wrap u_sram_east_b_hi (
        .clk_i(gclk_bank_b_w), .men_i(sram_b_hi_men_w), .wen_i(sram_b_hi_wen_w),
        .ren_i(sram_b_hi_ren_w), .addr_i(sram_b_hi_addr_w), .din_i(sram_b_hi_din_w), .dout_o(sram_b_hi_dout_w)
    );

    wire [11:0]  tile_clk_en_w;
    wire [11:0]  tile_start_w;
    wire         tile_clr_sticky_w;
    wire [11:0]  tile_vec_valid_w;
    wire [383:0] tile_x_flat_w;
    wire [383:0] tile_w_flat_w;
    wire         od_probe_en_w;
    wire         dock_attached_w;
    wire         tile3_fault_inj_w;
    wire         tile11_hang_inj_w;

    wire [11:0]  tile_busy_vec_w;
    wire [11:0]  tile_done_sticky_w;
    wire [11:0]  tile_fault_vec_w;
    wire signed [74:0] dot_tile_w [0:11];
    wire [31:0]  kag_n_out_w [0:11];
    wire [31:0]  kag_e_out_w [0:11];
    wire [31:0]  kag_d_out_w [0:11];
    wire [1:0]   tile_v5_em_w [0:11];
    wire [2:0]   tile_v5_st_w [0:11];

    genvar gt;
    generate
        for (gt = 0; gt < 12; gt = gt + 1) begin : g_tiles
            localparam integer N_NBR = (gt + 6) % 12;
            localparam integer E_NBR = (gt + 1) % 12;
            localparam integer D_NBR = (gt + 7) % 12;

            (* keep_hierarchy = 1 *)
            jedi_coherence_tile u_tile (
                .clk_i              (clk_core_w),
                .rst_n_i            (rst_n_w),
                .tile_clk_en_i      (tile_clk_en_w[gt]),
                .start_i            (tile_start_w[gt]),
                .clear_sticky_i     (tile_clr_sticky_w),
                .vec_valid_i        (tile_vec_valid_w[gt]),
                .x_word_i           ($signed(tile_x_flat_w[gt*32 +: 32])),
                .w_word_i           ($signed(tile_w_flat_w[gt*32 +: 32])),
                .od_probe_en_i      (od_probe_en_w),
                .tier_mode_i        (2'b10),
                .dock_attached_i    (dock_attached_w),
                .tile_fault_inj_i   ((gt == 3) ? tile3_fault_inj_w : 1'b0),
                .tile_hang_inj_i    ((gt == 11) ? tile11_hang_inj_w : 1'b0),
                .kag_north_in_i     (kag_n_out_w[N_NBR]),
                .kag_east_in_i      (kag_e_out_w[E_NBR]),
                .kag_diag_in_i      (kag_d_out_w[D_NBR]),
                .kag_north_out_o    (kag_n_out_w[gt]),
                .kag_east_out_o     (kag_e_out_w[gt]),
                .kag_diag_out_o     (kag_d_out_w[gt]),
                .tile_busy_o        (tile_busy_vec_w[gt]),
                .tile_done_sticky_o (tile_done_sticky_w[gt]),
                .tile_fault_o       (tile_fault_vec_w[gt]),
                .dot_out_o          (dot_tile_w[gt]),
                .v5_egress_mode_o   (tile_v5_em_w[gt]),
                .v5_dkm_state_o     (tile_v5_st_w[gt])
            );
        end
    endgenerate

    (* keep_hierarchy = 1 *)
    jedi_central_spine u_spine (
        .clk_in_raw_i        (clk_in_w),
        .rst_n_raw_i         (rst_n_w),
        .therm_82_n_raw_i    (therm_82_n_w),
        .therm_105_n_raw_i   (therm_105_n_w),
        .therm_122_n_raw_i   (therm_122_n_w),
        .cap_good_raw_i      (cap_good_w),
        .veto_n_raw_i        (veto_n_w),
        .gear1_allow_raw_i   (gear1_allow_w),
        .mode_dmr_i          (mode_dmr_w),
        .scout_bypass_i      (scout_bypass_w),
        .test_en_i           (test_en_w),
        .ospi_clk_i          (ospi_clk_w),
        .ospi_cs_n_i         (ospi_cs_n_w),
        .ospi_io_i           (ospi_io_in_w),
        .ospi_rdy_o          (ospi_rdy_w),
        .ospi_irq_n_o        (ospi_irq_n_w),
        .dbg_sck_i           (dbg_sck_w),
        .dbg_mosi_i          (dbg_mosi_w),
        .dbg_miso_o          (dbg_miso_w),
        .dbg_cs_n_i          (dbg_cs_n_w),
        .clk_core_o          (clk_core_w),
        .clk_dma_o           (clk_dma_w),
        .bank_clk_en_a_o     (bank_clk_en_a_w),
        .sram_a_lo_men_o     (sram_a_lo_men_w),
        .sram_a_lo_wen_o     (sram_a_lo_wen_w),
        .sram_a_lo_ren_o     (sram_a_lo_ren_w),
        .sram_a_lo_addr_o    (sram_a_lo_addr_w),
        .sram_a_lo_din_o     (sram_a_lo_din_w),
        .sram_a_lo_dout_i    (sram_a_lo_dout_w),
        .sram_a_hi_men_o     (sram_a_hi_men_w),
        .sram_a_hi_wen_o     (sram_a_hi_wen_w),
        .sram_a_hi_ren_o     (sram_a_hi_ren_w),
        .sram_a_hi_addr_o    (sram_a_hi_addr_w),
        .sram_a_hi_din_o     (sram_a_hi_din_w),
        .sram_a_hi_dout_i    (sram_a_hi_dout_w),
        .bank_clk_en_b_o     (bank_clk_en_b_w),
        .sram_b_lo_men_o     (sram_b_lo_men_w),
        .sram_b_lo_wen_o     (sram_b_lo_wen_w),
        .sram_b_lo_ren_o     (sram_b_lo_ren_w),
        .sram_b_lo_addr_o    (sram_b_lo_addr_w),
        .sram_b_lo_din_o     (sram_b_lo_din_w),
        .sram_b_lo_dout_i    (sram_b_lo_dout_w),
        .sram_b_hi_men_o     (sram_b_hi_men_w),
        .sram_b_hi_wen_o     (sram_b_hi_wen_w),
        .sram_b_hi_ren_o     (sram_b_hi_ren_w),
        .sram_b_hi_addr_o    (sram_b_hi_addr_w),
        .sram_b_hi_din_o     (sram_b_hi_din_w),
        .sram_b_hi_dout_i    (sram_b_hi_dout_w),
        .tile_clk_en_o       (tile_clk_en_w),
        .tile_start_o        (tile_start_w),
        .tile_clear_sticky_o (tile_clr_sticky_w),
        .tile_vec_valid_o    (tile_vec_valid_w),
        .tile_x_words_flat_o (tile_x_flat_w),
        .tile_w_words_flat_o (tile_w_flat_w),
        .od_probe_en_o       (od_probe_en_w),
        .dock_attached_o     (dock_attached_w),
        .tile3_fault_inj_o   (tile3_fault_inj_w),
        .tile11_hang_inj_o   (tile11_hang_inj_w),
        .tile_busy_vec_i     (tile_busy_vec_w),
        .tile_done_sticky_i  (tile_done_sticky_w),
        .tile_fault_vec_i    (tile_fault_vec_w),
        .dot_t00_i           (dot_tile_w[0]),
        .dot_t01_i           (dot_tile_w[1]),
        .dot_t02_i           (dot_tile_w[2]),
        .dot_t03_i           (dot_tile_w[3]),
        .dot_t04_i           (dot_tile_w[4]),
        .dot_t05_i           (dot_tile_w[5]),
        .dot_t06_i           (dot_tile_w[6]),
        .dot_t07_i           (dot_tile_w[7]),
        .dot_t08_i           (dot_tile_w[8]),
        .dot_t09_i           (dot_tile_w[9]),
        .dot_t10_i           (dot_tile_w[10]),
        .dot_t11_i           (dot_tile_w[11]),
        .bank_active_o       (bank_active_w),
        .act_en_p_o          (act_en_p_w),
        .act_en_n_o          (act_en_n_w),
        .tai_heartbeat_o     (tai_hb_w),
        .dmr_fault_o         (dmr_fault_w),
        .costbound_trip_o    (cb_trip_w),
        .epoch_ack_o         (epoch_ack_w),
        .kat_pass_o          (kat_pass_w),
        .clk_mon_o           (clk_mon_w),
        .gear_stat_o         (gear_stat_w),
        .tile_fault_o        (tile_fault_w)
    );

    wire _unused_ok = &{
        1'b0, clk_dma_w, spare_in_w,
        tile_v5_em_w[0], tile_v5_em_w[1], tile_v5_em_w[2], tile_v5_em_w[3],
        tile_v5_em_w[4], tile_v5_em_w[5], tile_v5_em_w[6], tile_v5_em_w[7],
        tile_v5_em_w[8], tile_v5_em_w[9], tile_v5_em_w[10], tile_v5_em_w[11],
        tile_v5_st_w[0], tile_v5_st_w[1], tile_v5_st_w[2], tile_v5_st_w[3],
        tile_v5_st_w[4], tile_v5_st_w[5], tile_v5_st_w[6], tile_v5_st_w[7],
        tile_v5_st_w[8], tile_v5_st_w[9], tile_v5_st_w[10], tile_v5_st_w[11]
    };
endmodule
`default_nettype wire
