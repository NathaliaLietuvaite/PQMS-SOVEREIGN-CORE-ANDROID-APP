// =============================================================================
// rtl_v6/jedi_central_spine.v
// WP-1.6: Central Sovereign Spine (580 um H-Channel)
// - Matched Twin Root sg13g2_lgcp_1 ICGs (u_root_icg_core & u_root_icg_dma)
// - 4-Pin Debug/KAT SPI Slave (40-bit MSB-first frame, CDC synchronized)
// - Centered R90 RM_IHPSG13_1P_512x64_c2_bm_bist (4 KB Quarantine T_I/O)
// - Mandatory +2-cycle Flank SRAM Pipeline (sram_flank_pipe_q)
// - OSPI Async DMA + Scout Norm Unit + 768D Kagome Reducer + TMR GNC & TAI
// =============================================================================
`timescale 1ns/1ps
`default_nettype none

module jedi_central_spine #(
    parameter signed [75:0] GOLDEN_DOT76_ROM = 76'sh000_0FE6_1550_BAAA_AB00
) (
    // Raw clock, reset & supervisor inputs
    input  wire        clk_in_raw_i,
    input  wire        rst_n_raw_i,
    input  wire        therm_82_n_raw_i,
    input  wire        therm_105_n_raw_i,
    input  wire        therm_122_n_raw_i,
    input  wire        cap_good_raw_i,
    input  wire        veto_n_raw_i,
    input  wire        gear1_allow_raw_i,
    input  wire        mode_dmr_i,
    input  wire        scout_bypass_i,
    input  wire        test_en_i,

    // External 100 MHz SDR OSPI interface
    input  wire        ospi_clk_i,
    input  wire        ospi_cs_n_i,
    input  wire [7:0]  ospi_io_i,
    output wire        ospi_rdy_o,
    output wire        ospi_irq_n_o,

    // 4-Pin Debug / KAT SPI-Slave interface
    input  wire        dbg_sck_i,
    input  wire        dbg_mosi_i,
    output wire        dbg_miso_o,
    input  wire        dbg_cs_n_i,

    // Exported root gated clocks
    output wire        clk_core_o,
    output wire        clk_dma_o,

    // Flank SRAM Bank A (LO = X [0..1023], HI = W [1024..2047])
    output wire        bank_clk_en_a_o,
    output wire        sram_a_lo_men_o,
    output wire        sram_a_lo_wen_o,
    output wire        sram_a_lo_ren_o,
    output wire [9:0]  sram_a_lo_addr_o,
    output wire [63:0] sram_a_lo_din_o,
    input  wire [63:0] sram_a_lo_dout_i,

    output wire        sram_a_hi_men_o,
    output wire        sram_a_hi_wen_o,
    output wire        sram_a_hi_ren_o,
    output wire [9:0]  sram_a_hi_addr_o,
    output wire [63:0] sram_a_hi_din_o,
    input  wire [63:0] sram_a_hi_dout_i,

    // Flank SRAM Bank B (LO = X [0..1023], HI = W [1024..2047])
    output wire        bank_clk_en_b_o,
    output wire        sram_b_lo_men_o,
    output wire        sram_b_lo_wen_o,
    output wire        sram_b_lo_ren_o,
    output wire [9:0]  sram_b_lo_addr_o,
    output wire [63:0] sram_b_lo_din_o,
    input  wire [63:0] sram_b_lo_dout_i,

    output wire        sram_b_hi_men_o,
    output wire        sram_b_hi_wen_o,
    output wire        sram_b_hi_ren_o,
    output wire [9:0]  sram_b_hi_addr_o,
    output wire [63:0] sram_b_hi_din_o,
    input  wire [63:0] sram_b_hi_dout_i,

    // 12-Tile array interface
    output wire [11:0] tile_clk_en_o,
    output wire [11:0] tile_start_o,
    output wire        tile_clear_sticky_o,
    output wire [11:0] tile_vec_valid_o,
    output wire [383:0] tile_x_words_flat_o,
    output wire [383:0] tile_w_words_flat_o,
    output wire        od_probe_en_o,
    output wire        dock_attached_o,
    output wire        tile3_fault_inj_o,
    output wire        tile11_hang_inj_o,

    input  wire [11:0] tile_busy_vec_i,
    input  wire [11:0] tile_done_sticky_i,
    input  wire [11:0] tile_fault_vec_i,
    input  wire signed [74:0] dot_t00_i,
    input  wire signed [74:0] dot_t01_i,
    input  wire signed [74:0] dot_t02_i,
    input  wire signed [74:0] dot_t03_i,
    input  wire signed [74:0] dot_t04_i,
    input  wire signed [74:0] dot_t05_i,
    input  wire signed [74:0] dot_t06_i,
    input  wire signed [74:0] dot_t07_i,
    input  wire signed [74:0] dot_t08_i,
    input  wire signed [74:0] dot_t09_i,
    input  wire signed [74:0] dot_t10_i,
    input  wire signed [74:0] dot_t11_i,

    // Top-level status & Safety Island outputs
    output wire        bank_active_o,
    output wire        act_en_p_o,
    output wire        act_en_n_o,
    output wire        tai_heartbeat_o,
    output wire        dmr_fault_o,
    output wire        costbound_trip_o,
    output wire        epoch_ack_o,
    output wire        kat_pass_o,
    output wire        clk_mon_o,
    output wire [1:0]  gear_stat_o,
    output wire        tile_fault_o
);

    // G2: Spine boundary input antenna diodes
    jedi_ant_diode u_ant_dmr   (.pin_i(mode_dmr_i));
    jedi_ant_diode u_ant_scout (.pin_i(scout_bypass_i));
    jedi_ant_diode u_ant_tsten (.pin_i(test_en_i));

    // =========================================================================
    // 1. Matched Twin Root sg13g2_lgcp_1 Clock Gates (G4)
    // =========================================================================
    wire gear_en_pulse_w;
    wire clk_core_w;
    wire clk_dma_w;

`ifdef SYNTH_IHP_SG13G2
    wire tie_hi_dma_w;
    (* keep = 1, dont_touch = "true" *)
    sg13g2_tiehi u_tiehi_dma (.L_HI(tie_hi_dma_w));
`else
    wire tie_hi_dma_w = 1'b1;
`endif

    (* keep = 1, dont_touch = "true" *)
    jedi_icg_cell u_root_icg_core (
        .clk_i  (clk_in_raw_i),
        .en_i   (gear_en_pulse_w),
        .gclk_o (clk_core_w)
    );

    (* keep = 1, dont_touch = "true" *)
    jedi_icg_cell u_root_icg_dma (
        .clk_i  (clk_in_raw_i),
        .en_i   (tie_hi_dma_w),
        .gclk_o (clk_dma_w)
    );

    assign clk_core_o = clk_core_w;
    assign clk_dma_o  = clk_dma_w;
    assign clk_mon_o  = clk_core_w;

    // =========================================================================
    // 2. 4-Pin Debug / KAT SPI Slave (40-bit frame: {rw, addr[6:0], data[31:0]})
    // =========================================================================
    localparam [255:0] DEFAULT_SPEC_HASH = 256'h564D4158_4A454449_56363030_5349474E_4F46465F_43415242_4F4E335F_32303236;

    reg [5:0]  spi_bit_cnt_q;
    reg [39:0] spi_rx_sh_q;
    reg [31:0] spi_tx_sh_q;
    reg        spi_cmd_tog_q;
    reg [6:0]  spi_wr_addr_q;
    reg [31:0] spi_wr_data_q;

    // Status wires declared ahead for SPI readback mux
    wire        gear1_lockout_sticky_w;
    wire        boot_kat_trial_w;
    wire        scout_aborted_w;
    wire        watchdog_trip_w;
    wire        dmr_divergence_w;
    wire        upper_guard_ok_w;
    wire        born_valid_w;
    wire        tai_tier_ok_w;
    wire        npu_tier_ok_w;
    wire        npu_egress_en_w;
    wire [1:0]  egress_mode_w;
    wire [31:0] rcf_quad_q30_w;
    wire [31:0] born_fidelity_q30_w;
    wire signed [75:0] dot76_w;
    reg  [3:0]  max_clken_pop_q;
    reg  [3:0]  max_start_pop_q;
    reg  [11:0] ever_clken_q;
    reg         quiescent_seen_q;
    wire        swap_deferred_w;

    wire [31:0] status0_w = {
        4'd0,
        quiescent_seen_q,
        swap_deferred_w,
        gear1_lockout_sticky_w,
        boot_kat_trial_w,
        scout_aborted_w,
        watchdog_trip_w,
        dmr_divergence_w,
        upper_guard_ok_w,
        born_valid_w,
        tai_tier_ok_w,
        npu_tier_ok_w,
        npu_egress_en_w,
        egress_mode_w,
        gear_stat_o,
        ever_clken_q
    };

    wire [31:0] status_pop_w = {
        4'd0, max_clken_pop_q,
        4'd0, max_start_pop_q,
        4'd0, ever_clken_q
    };

    wire [6:0] spi_early_addr_w = {spi_rx_sh_q[5:0], dbg_mosi_i};
    reg [31:0] spi_rd_mux_w;
    always @(*) begin
        case (spi_early_addr_w)
            7'h10:   spi_rd_mux_w = status0_w;
            7'h11:   spi_rd_mux_w = rcf_quad_q30_w;
            7'h12:   spi_rd_mux_w = born_fidelity_q30_w;
            7'h13:   spi_rd_mux_w = dot76_w[31:0];
            7'h14:   spi_rd_mux_w = dot76_w[63:32];
            7'h15:   spi_rd_mux_w = {{20{dot76_w[75]}}, dot76_w[75:64]};
            7'h16:   spi_rd_mux_w = status_pop_w;
            default: spi_rd_mux_w = status0_w;
        endcase
    end

    always @(posedge dbg_sck_i or negedge rst_n_raw_i) begin
        if (!rst_n_raw_i) begin
            spi_bit_cnt_q <= 6'd0;
            spi_tx_sh_q   <= 32'd0;
            spi_rx_sh_q   <= 40'd0;
            spi_cmd_tog_q <= 1'b0;
            spi_wr_addr_q <= 7'd0;
            spi_wr_data_q <= 32'd0;
        end else if (!dbg_cs_n_i) begin
            spi_rx_sh_q <= {spi_rx_sh_q[38:0], dbg_mosi_i};
            if (spi_bit_cnt_q == 6'd7) begin
                spi_tx_sh_q   <= spi_rd_mux_w;
                spi_bit_cnt_q <= spi_bit_cnt_q + 6'd1;
            end else if (spi_bit_cnt_q == 6'd39) begin
                spi_bit_cnt_q <= 6'd0;
                if (spi_rx_sh_q[38]) begin
                    spi_wr_addr_q <= spi_rx_sh_q[37:31];
                    spi_wr_data_q <= {spi_rx_sh_q[30:0], dbg_mosi_i};
                    spi_cmd_tog_q <= ~spi_cmd_tog_q;
                end
            end else begin
                spi_bit_cnt_q <= spi_bit_cnt_q + 6'd1;
                if (spi_bit_cnt_q > 6'd7) begin
                    spi_tx_sh_q <= {spi_tx_sh_q[30:0], 1'b0};
                end
            end
        end else begin
            spi_bit_cnt_q <= 6'd0;
        end
    end

    reg dbg_miso_q;
    always @(negedge dbg_sck_i or negedge rst_n_raw_i) begin
        if (!rst_n_raw_i) begin
            dbg_miso_q <= 1'b0;
        end else if (dbg_cs_n_i) begin
            dbg_miso_q <= 1'b0;
        end else begin
            dbg_miso_q <= spi_tx_sh_q[31];
        end
    end
    assign dbg_miso_o = dbg_miso_q;

    // Synchronize SPI write toggle into clk_dma_w (100 MHz) domain
    (* ASYNC_REG = "TRUE", keep = 1, dont_touch = "true" *) reg [2:0] spi_tog_sync_q;

    reg        cmd_eval_trig_q;
    reg        cmd_swap_req_q;
    reg        cmd_epoch_rst_q;
    reg        cmd_kat_req_q;
    reg        cmd_eval_clr_q;
    reg        cmd_dma_rst_q;

    reg [5:0]  reg_mode_q;
    reg [31:0] reg_delta_e_q;
    reg [31:0] reg_max_cycles_q;
    reg [31:0] reg_max_tokens_q;
    reg [31:0] reg_max_pulses_q;
    reg [31:0] reg_max_energy_q;
    reg [31:0] reg_spec_lo_q;
    reg [7:0]  reg_test_inj_q;

    wire spi_wr_pulse_w = spi_tog_sync_q[2] ^ spi_tog_sync_q[1];

    always @(posedge clk_dma_w or negedge rst_n_raw_i) begin
        if (!rst_n_raw_i) begin
            spi_tog_sync_q   <= 3'b000;
            cmd_eval_trig_q  <= 1'b0;
            cmd_swap_req_q   <= 1'b0;
            cmd_epoch_rst_q  <= 1'b0;
            cmd_kat_req_q    <= 1'b0;
            cmd_eval_clr_q   <= 1'b0;
            cmd_dma_rst_q    <= 1'b0;
            reg_mode_q       <= 6'd0;
            reg_delta_e_q    <= 32'h0010_0000;
            reg_max_cycles_q <= 32'h00FF_FFFF;
            reg_max_tokens_q <= 32'h00FF_FFFF;
            reg_max_pulses_q <= 32'h00FF_FFFF;
            reg_max_energy_q <= 32'h00FF_FFFF;
            reg_spec_lo_q    <= DEFAULT_SPEC_HASH[31:0];
            reg_test_inj_q   <= 8'd0;
        end else begin
            spi_tog_sync_q <= {spi_tog_sync_q[1:0], spi_cmd_tog_q};
            // Hold command strobes across 4 DMA clocks so Gear /4 core sees them cleanly
            if (gear_en_pulse_w) begin
                cmd_eval_trig_q <= 1'b0;
                cmd_epoch_rst_q <= 1'b0;
                cmd_kat_req_q   <= 1'b0;
                cmd_eval_clr_q  <= 1'b0;
            end
            cmd_swap_req_q <= 1'b0;
            cmd_dma_rst_q  <= 1'b0;

            if (spi_wr_pulse_w) begin
                case (spi_wr_addr_q)
                    7'h01: begin
                        cmd_eval_trig_q <= spi_wr_data_q[0];
                        cmd_swap_req_q  <= spi_wr_data_q[1];
                        cmd_epoch_rst_q <= spi_wr_data_q[2];
                        cmd_kat_req_q   <= spi_wr_data_q[3];
                        cmd_eval_clr_q  <= spi_wr_data_q[4];
                        cmd_dma_rst_q   <= spi_wr_data_q[5];
                    end
                    7'h02: reg_mode_q       <= spi_wr_data_q[5:0];
                    7'h03: reg_delta_e_q    <= spi_wr_data_q;
                    7'h04: reg_max_cycles_q <= spi_wr_data_q;
                    7'h05: reg_max_tokens_q <= spi_wr_data_q;
                    7'h06: reg_max_pulses_q <= spi_wr_data_q;
                    7'h07: reg_max_energy_q <= spi_wr_data_q;
                    7'h08: reg_spec_lo_q    <= spi_wr_data_q;
                    7'h09: reg_test_inj_q   <= spi_wr_data_q[7:0];
                    default: ;
                endcase
            end
        end
    end

    wire       q214_mode_w      = reg_mode_q[0];
    wire       born_mode_w      = reg_mode_q[1];
    wire       born_pass_w      = reg_mode_q[2];
    wire       nw0_use_cache_w  = reg_mode_q[3];
    assign     od_probe_en_o    = reg_mode_q[4];
    assign     dock_attached_o  = reg_mode_q[5];

    // Fault-injection hooks strictly gated with TEST_EN_I pad!
    wire [7:0] eff_test_inj_w   = test_en_i ? reg_test_inj_q : 8'd0;
    wire [2:0] tmr_fault_inj_w  = eff_test_inj_w[2:0];
    wire       dmr_seu_inj_w    = eff_test_inj_w[3];
    wire       canary_inj_w     = eff_test_inj_w[4];
    wire       kat_100m_inj_w   = eff_test_inj_w[5];
    assign     tile11_hang_inj_o = eff_test_inj_w[6];
    assign     tile3_fault_inj_o = eff_test_inj_w[7];

    wire [255:0] active_spec_hash_w = {DEFAULT_SPEC_HASH[255:32], reg_spec_lo_q};

    // =========================================================================
    // 3. OSPI Async DMA + Flank SRAM Ping-Pong Arbiter + +2-Cycle Flank Pipe
    // =========================================================================
    wire        core_idle_w;
    wire        core_rd_req_w;
    wire [9:0]  core_sub_addr_w;
    wire        swap_quiescent_w;
    wire [10:0] dma_wr_count_w;

    wire        dma_a_men_w;
    wire        dma_a_wen_w;
    wire        dma_a_ren_w;
    wire [10:0] dma_a_addr_w;
    wire [63:0] dma_a_din_w;

    wire        dma_b_men_w;
    wire        dma_b_wen_w;
    wire        dma_b_ren_w;
    wire [10:0] dma_b_addr_w;
    wire [63:0] dma_b_din_w;

    wire [63:0] unused_act_dout_w;
    wire signed [31:0] unused_unp0_w, unused_unp1_w, unused_unp2_w, unused_unp3_w;

    jedi_ospi_async_dma u_ospi_dma (
        .ospi_clk_i       (ospi_clk_i),
        .ospi_cs_n_i      (ospi_cs_n_i),
        .ospi_io_i        (ospi_io_i),
        .ospi_rdy_o       (ospi_rdy_o),
        .clk_dma_i        (clk_dma_w),
        .rst_n_i          (rst_n_raw_i),
        .gear_en_pulse_i  (gear_en_pulse_w),
        .therm_82_n_i     (therm_82_n_raw_i),
        .q214_mode_i      (q214_mode_w),
        .swap_req_i       (cmd_swap_req_q),
        .dma_addr_rst_i   (cmd_dma_rst_q),
        .core_idle_i      (core_idle_w),
        .core_rd_req_i    (core_rd_req_w),
        .core_rd_addr_i   ({1'b0, core_sub_addr_w}),
        .bank_active_o    (bank_active_o),
        .swap_quiescent_o (swap_quiescent_w),
        .swap_deferred_o  (swap_deferred_w),
        .bank_clk_en_a_o  (bank_clk_en_a_o),
        .bank_clk_en_b_o  (bank_clk_en_b_o),
        .sram_a_men_o     (dma_a_men_w),
        .sram_a_wen_o     (dma_a_wen_w),
        .sram_a_ren_o     (dma_a_ren_w),
        .sram_a_addr_o    (dma_a_addr_w),
        .sram_a_din_o     (dma_a_din_w),
        .sram_a_dout_i    (sram_a_lo_dout_i),
        .sram_b_men_o     (dma_b_men_w),
        .sram_b_wen_o     (dma_b_wen_w),
        .sram_b_ren_o     (dma_b_ren_w),
        .sram_b_addr_o    (dma_b_addr_w),
        .sram_b_din_o     (dma_b_din_w),
        .sram_b_dout_i    (sram_b_lo_dout_i),
        .active_dout_raw_o(unused_act_dout_w),
        .unpack_q30_0_o   (unused_unp0_w),
        .unpack_q30_1_o   (unused_unp1_w),
        .unpack_q30_2_o   (unused_unp2_w),
        .unpack_q30_3_o   (unused_unp3_w),
        .dma_wr_count_o   (dma_wr_count_w)
    );

    // Track quiescent handover proof in hardware telemetry
    always @(posedge clk_dma_w or negedge rst_n_raw_i) begin
        if (!rst_n_raw_i) begin
            quiescent_seen_q <= 1'b0;
        end else if (cmd_eval_clr_q) begin
            quiescent_seen_q <= 1'b0;
        end else if (swap_quiescent_w && !sram_a_lo_men_o && !sram_b_lo_men_o) begin
            quiescent_seen_q <= 1'b1;
        end
    end

    // Mandatory Flank Pipeline Stage 1 (outgoing addr/cmd) & Stage 2 (incoming 128-bit dout)
    // When bank acts as Shadow DMA: addr[10]==0 writes LO, addr[10]==1 writes HI.
    // When bank acts as Active Core: BOTH LO (X) and HI (W) read simultaneously at core_sub_addr!
    reg        pipe_rd_vld_d1_q;
    reg        pipe_rd_vld_d2_q;
    reg [2:0]  pipe_grp_d1_q;
    reg [2:0]  pipe_grp_d2_q;
    reg        pipe_scout_only_d1_q;
    reg        pipe_scout_only_d2_q;
    reg        pipe_scout_skip0_d1_q;
    reg        pipe_scout_skip0_d2_q;
    reg [63:0] sram_flank_pipe_lo_q;
    reg [63:0] sram_flank_pipe_hi_q;

    assign sram_a_lo_men_o  = bank_active_o ? (dma_a_men_w & (~dma_a_addr_w[10])) : dma_a_men_w;
    assign sram_a_lo_wen_o  = bank_active_o ? (dma_a_wen_w & (~dma_a_addr_w[10])) : 1'b0;
    assign sram_a_lo_ren_o  = bank_active_o ? 1'b0                                : dma_a_ren_w;
    assign sram_a_lo_addr_o = dma_a_addr_w[9:0];
    assign sram_a_lo_din_o  = dma_a_din_w;

    assign sram_a_hi_men_o  = bank_active_o ? (dma_a_men_w & dma_a_addr_w[10])    : dma_a_men_w;
    assign sram_a_hi_wen_o  = bank_active_o ? (dma_a_wen_w & dma_a_addr_w[10])    : 1'b0;
    assign sram_a_hi_ren_o  = bank_active_o ? 1'b0                                : dma_a_ren_w;
    assign sram_a_hi_addr_o = dma_a_addr_w[9:0];
    assign sram_a_hi_din_o  = dma_a_din_w;

    assign sram_b_lo_men_o  = bank_active_o ? dma_b_men_w : (dma_b_men_w & (~dma_b_addr_w[10]));
    assign sram_b_lo_wen_o  = bank_active_o ? 1'b0        : (dma_b_wen_w & (~dma_b_addr_w[10]));
    assign sram_b_lo_ren_o  = bank_active_o ? dma_b_ren_w : 1'b0;
    assign sram_b_lo_addr_o = dma_b_addr_w[9:0];
    assign sram_b_lo_din_o  = dma_b_din_w;

    assign sram_b_hi_men_o  = bank_active_o ? dma_b_men_w : (dma_b_men_w & dma_b_addr_w[10]);
    assign sram_b_hi_wen_o  = bank_active_o ? 1'b0        : (dma_b_wen_w & dma_b_addr_w[10]);
    assign sram_b_hi_ren_o  = bank_active_o ? dma_b_ren_w : 1'b0;
    assign sram_b_hi_addr_o = dma_b_addr_w[9:0];
    assign sram_b_hi_din_o  = dma_b_din_w;

    wire [63:0] act_lo_dout_w = bank_active_o ? sram_b_lo_dout_i : sram_a_lo_dout_i;
    wire [63:0] act_hi_dout_w = bank_active_o ? sram_b_hi_dout_i : sram_a_hi_dout_i;

    // =========================================================================
    // 4. Core Stream Sequencer (Feeds 12 Tiles via +2-Cycle Flank Pipe or KAT ROM)
    // =========================================================================
    localparam [2:0] FS_IDLE       = 3'd0;
    localparam [2:0] FS_WAIT_WAVES = 3'd1;
    localparam [2:0] FS_SCOUT_FEED = 3'd2;
    localparam [2:0] FS_SCOUT_HOLD = 3'd3;
    localparam [2:0] FS_ARRAY_FEED = 3'd4;
    localparam [2:0] FS_KAT_FEED   = 3'd5;
    localparam [2:0] FS_DRAIN_WAIT = 3'd6;

    localparam signed [31:0] KAT_POS_VAL =  32'sh024D_5555;
    localparam signed [31:0] KAT_NEG_VAL = -32'sh024D_5555;

    reg [2:0] fs_state_q;
    reg [2:0] fs_grp_q;
    reg [5:0] fs_elem_q;
    reg [2:0] fs_wait_cnt_q;
    reg       fs_from_scout_q;
    reg       kat_done_pulse_q;
    reg       kat_was_active_q;
    reg       commit_cost_pulse_q;
    reg       reducer_done_d1_q;

    wire [11:0] gnc_tile_clk_en_w;
    wire [11:0] gnc_tile_start_w;
    wire [11:0] gnc_active_mask_w;
    wire        gnc_eval_arm_w;
    wire        reducer_eval_en_w;

    wire start_any_eval_w = cmd_eval_trig_q | (boot_kat_trial_w & (~kat_was_active_q));

    always @(posedge clk_core_w or negedge rst_n_raw_i) begin
        if (!rst_n_raw_i) begin
            fs_state_q            <= FS_IDLE;
            fs_grp_q              <= 3'd0;
            fs_elem_q             <= 6'd0;
            fs_wait_cnt_q         <= 3'd0;
            fs_from_scout_q       <= 1'b0;
            kat_done_pulse_q      <= 1'b0;
            kat_was_active_q      <= 1'b0;
            commit_cost_pulse_q   <= 1'b0;
            reducer_done_d1_q     <= 1'b0;
            pipe_rd_vld_d1_q      <= 1'b0;
            pipe_rd_vld_d2_q      <= 1'b0;
            pipe_grp_d1_q         <= 3'd0;
            pipe_grp_d2_q         <= 3'd0;
            pipe_scout_only_d1_q  <= 1'b0;
            pipe_scout_only_d2_q  <= 1'b0;
            pipe_scout_skip0_d1_q <= 1'b0;
            pipe_scout_skip0_d2_q <= 1'b0;
            sram_flank_pipe_lo_q  <= 64'd0;
            sram_flank_pipe_hi_q  <= 64'd0;
        end else begin
            kat_done_pulse_q    <= 1'b0;
            commit_cost_pulse_q <= 1'b0;
            reducer_done_d1_q   <= reducer_eval_en_w;

            // Advance +2-cycle flank read pipeline
            pipe_rd_vld_d1_q      <= core_rd_req_w;
            pipe_rd_vld_d2_q      <= pipe_rd_vld_d1_q;
            pipe_grp_d1_q         <= fs_grp_q;
            pipe_grp_d2_q         <= pipe_grp_d1_q;
            pipe_scout_only_d1_q  <= (fs_state_q == FS_SCOUT_FEED);
            pipe_scout_only_d2_q  <= pipe_scout_only_d1_q;
            pipe_scout_skip0_d1_q <= (fs_state_q == FS_ARRAY_FEED) & fs_from_scout_q & (fs_grp_q == 3'd0);
            pipe_scout_skip0_d2_q <= pipe_scout_skip0_d1_q;
            sram_flank_pipe_lo_q  <= act_lo_dout_w;
            sram_flank_pipe_hi_q  <= act_hi_dout_w;

            if (!boot_kat_trial_w) begin
                kat_was_active_q <= 1'b0;
            end

            if (cmd_eval_clr_q) begin
                fs_state_q <= FS_IDLE;
            end else begin
                case (fs_state_q)
                    FS_IDLE: begin
                        fs_grp_q        <= 3'd0;
                        fs_elem_q       <= 6'd0;
                        fs_from_scout_q <= 1'b0;
                        if (boot_kat_trial_w && !kat_was_active_q) begin
                            kat_was_active_q <= 1'b1;
                            fs_wait_cnt_q    <= 3'd4;
                            fs_state_q       <= FS_WAIT_WAVES;
                        end else if (cmd_eval_trig_q) begin
                            if (!mode_dmr_i && !scout_bypass_i && !born_mode_w) begin
                                fs_wait_cnt_q <= 3'd1;
                                fs_state_q    <= FS_WAIT_WAVES;
                            end else begin
                                fs_wait_cnt_q <= 3'd4;
                                fs_state_q    <= FS_WAIT_WAVES;
                            end
                        end
                    end

                    FS_WAIT_WAVES: begin
                        if (fs_wait_cnt_q == 3'd0) begin
                            fs_grp_q  <= 3'd0;
                            fs_elem_q <= 6'd0;
                            if (boot_kat_trial_w) begin
                                fs_state_q <= FS_KAT_FEED;
                            end else if (!mode_dmr_i && !scout_bypass_i && !born_mode_w && !fs_from_scout_q) begin
                                fs_state_q <= FS_SCOUT_FEED;
                            end else begin
                                fs_state_q <= FS_ARRAY_FEED;
                            end
                        end else begin
                            fs_wait_cnt_q <= fs_wait_cnt_q - 3'd1;
                        end
                    end

                    FS_SCOUT_FEED: begin
                        if (fs_elem_q == 6'd63) begin
                            fs_elem_q  <= 6'd0;
                            fs_state_q <= FS_SCOUT_HOLD;
                        end else begin
                            fs_elem_q <= fs_elem_q + 6'd1;
                        end
                    end

                    FS_SCOUT_HOLD: begin
                        if (scout_aborted_w) begin
                            commit_cost_pulse_q <= 1'b1;
                            fs_state_q          <= FS_IDLE;
                        end else if (gnc_tile_clk_en_w[1]) begin
                            // Scout passed -> wait 3 cycles for +4/+4/+3 start waves, then feed tiles 1..11
                            fs_from_scout_q <= 1'b1;
                            fs_wait_cnt_q   <= 3'd3;
                            fs_state_q      <= FS_WAIT_WAVES;
                        end
                    end

                    FS_ARRAY_FEED: begin
                        if (fs_elem_q == 6'd63) begin
                            fs_elem_q <= 6'd0;
                            if ((q214_mode_w && (fs_grp_q == 3'd2)) || (!q214_mode_w && (fs_grp_q == 3'd5))) begin
                                fs_grp_q   <= 3'd0;
                                fs_state_q <= FS_DRAIN_WAIT;
                            end else begin
                                fs_grp_q <= fs_grp_q + 3'd1;
                            end
                        end else begin
                            fs_elem_q <= fs_elem_q + 6'd1;
                        end
                    end

                    FS_KAT_FEED: begin
                        if (fs_elem_q == 6'd63) begin
                            fs_elem_q  <= 6'd0;
                            fs_state_q <= FS_DRAIN_WAIT;
                        end else begin
                            fs_elem_q <= fs_elem_q + 6'd1;
                        end
                    end

                    FS_DRAIN_WAIT: begin
                        if (reducer_eval_en_w && !reducer_done_d1_q) begin
                            if (boot_kat_trial_w) begin
                                kat_done_pulse_q <= 1'b1;
                                // Allow re-trigger if Gear /1 KAT failed and falls back to Gear /2!
                                kat_was_active_q <= 1'b0;
                            end else begin
                                commit_cost_pulse_q <= 1'b1;
                            end
                            fs_state_q <= FS_IDLE;
                        end else if (watchdog_trip_w) begin
                            kat_was_active_q <= 1'b0;
                            fs_state_q       <= FS_IDLE;
                        end
                    end

                    default: begin
                        fs_state_q <= FS_IDLE;
                    end
                endcase
            end
        end
    end

    assign core_rd_req_w   = (fs_state_q == FS_SCOUT_FEED) || (fs_state_q == FS_ARRAY_FEED);
    assign core_sub_addr_w = {1'b0, fs_grp_q, fs_elem_q};
    assign core_idle_w     = (fs_state_q == FS_IDLE) & (~(|tile_busy_vec_i));

    // Unpack +2-cycle pipelined 64-bit SRAM words into per-tile 32-bit Q2.30 lanes
    wire signed [31:0] x_q30_a_w = q214_mode_w ? $signed({sram_flank_pipe_lo_q[15:0],  16'h0000}) : $signed(sram_flank_pipe_lo_q[31:0]);
    wire signed [31:0] x_q30_b_w = q214_mode_w ? $signed({sram_flank_pipe_lo_q[31:16], 16'h0000}) : $signed(sram_flank_pipe_lo_q[63:32]);
    wire signed [31:0] x_q30_c_w = q214_mode_w ? $signed({sram_flank_pipe_lo_q[47:32], 16'h0000}) : x_q30_a_w;
    wire signed [31:0] x_q30_d_w = q214_mode_w ? $signed({sram_flank_pipe_lo_q[63:48], 16'h0000}) : x_q30_b_w;

    wire signed [31:0] w_q30_a_w = q214_mode_w ? $signed({sram_flank_pipe_hi_q[15:0],  16'h0000}) : $signed(sram_flank_pipe_hi_q[31:0]);
    wire signed [31:0] w_q30_b_w = q214_mode_w ? $signed({sram_flank_pipe_hi_q[31:16], 16'h0000}) : $signed(sram_flank_pipe_hi_q[63:32]);
    wire signed [31:0] w_q30_c_w = q214_mode_w ? $signed({sram_flank_pipe_hi_q[47:32], 16'h0000}) : w_q30_a_w;
    wire signed [31:0] w_q30_d_w = q214_mode_w ? $signed({sram_flank_pipe_hi_q[63:48], 16'h0000}) : w_q30_b_w;

    // Alternating carry-ripple KAT vector when in FS_KAT_FEED
    wire signed [31:0] kat_word_w = fs_elem_q[0] ? KAT_NEG_VAL : KAT_POS_VAL;

    reg [11:0] tile_vld_comb_w;
    always @(*) begin
        tile_vld_comb_w = 12'h000;
        if (fs_state_q == FS_KAT_FEED) begin
            tile_vld_comb_w = 12'hFFF;
        end else if (pipe_rd_vld_d2_q) begin
            if (pipe_scout_only_d2_q) begin
                tile_vld_comb_w = 12'h001;
            end else if (q214_mode_w) begin
                case (pipe_grp_d2_q)
                    3'd0:    tile_vld_comb_w = pipe_scout_skip0_d2_q ? 12'h00E : 12'h00F;
                    3'd1:    tile_vld_comb_w = 12'h0F0;
                    3'd2:    tile_vld_comb_w = 12'hF00;
                    default: tile_vld_comb_w = 12'h000;
                endcase
            end else begin
                case (pipe_grp_d2_q)
                    3'd0:    tile_vld_comb_w = pipe_scout_skip0_d2_q ? 12'h002 : 12'h003;
                    3'd1:    tile_vld_comb_w = 12'h00C;
                    3'd2:    tile_vld_comb_w = 12'h030;
                    3'd3:    tile_vld_comb_w = 12'h0C0;
                    3'd4:    tile_vld_comb_w = 12'h300;
                    3'd5:    tile_vld_comb_w = 12'hC00;
                    default: tile_vld_comb_w = 12'h000;
                endcase
            end
        end
    end

    assign tile_vec_valid_o    = tile_vld_comb_w;
    assign tile_clear_sticky_o = cmd_eval_clr_q | start_any_eval_w;

    // In 6xDMR mode, odd tile (2p+1) receives identical word as even tile (2p) for lockstep DMR!
    wire signed [31:0] pair_odd_x_w = mode_dmr_i ? x_q30_a_w : x_q30_b_w;
    wire signed [31:0] pair_odd_w_w = mode_dmr_i ? w_q30_a_w : w_q30_b_w;
    wire signed [31:0] quad2_x_w    = x_q30_c_w;
    wire signed [31:0] quad2_w_w    = w_q30_c_w;
    wire signed [31:0] quad3_x_w    = mode_dmr_i ? x_q30_c_w : x_q30_d_w;
    wire signed [31:0] quad3_w_w    = mode_dmr_i ? w_q30_c_w : w_q30_d_w;

    wire [127:0] grp_x4_w = (fs_state_q == FS_KAT_FEED)
        ? {4{kat_word_w}}
        : (q214_mode_w ? {quad3_x_w, quad2_x_w, pair_odd_x_w, x_q30_a_w}
                       : {pair_odd_x_w, x_q30_a_w, pair_odd_x_w, x_q30_a_w});

    wire [127:0] grp_w4_w = (fs_state_q == FS_KAT_FEED)
        ? {4{kat_word_w}}
        : (q214_mode_w ? {quad3_w_w, quad2_w_w, pair_odd_w_w, w_q30_a_w}
                       : {pair_odd_w_w, w_q30_a_w, pair_odd_w_w, w_q30_a_w});

    assign tile_x_words_flat_o = {3{grp_x4_w}};
    assign tile_w_words_flat_o = {3{grp_w4_w}};

    // Arm the 240-cycle post-stream compute/barrier watchdog right as feed finishes
    wire stream_finishing_w = ((fs_state_q == FS_ARRAY_FEED) && (fs_elem_q == 6'd63) &&
                               ((q214_mode_w && (fs_grp_q == 3'd2)) || (!q214_mode_w && (fs_grp_q == 3'd5))))
                            | ((fs_state_q == FS_KAT_FEED) && (fs_elem_q == 6'd63));

    // =========================================================================
    // 5. Canary, Scout Norm Unit, 768D Reducer, TMR GNC & Quarantine T_I/O SRAM
    // =========================================================================
    wire canary_trip_w;
    jedi_canary_delay_line u_canary (
        .clk_i           (clk_in_raw_i),
        .rst_n_i         (rst_n_raw_i),
        .enable_i        (gear_stat_o == 2'b00),
        .test_trip_inj_i (canary_inj_w),
        .canary_trip_o   (canary_trip_w)
    );

    wire        scout_reject_npu_w;
    wire        scout_reject_tai_w;
    wire [31:0] rem_x_hi_w;
    wire [31:0] rem_w_hi_w;

    jedi_scout_norm_unit u_scout_norm (
        .clk_i              (clk_core_w),
        .rst_n_i            (rst_n_raw_i),
        .start_i            (gnc_tile_start_w[0]),
        .vec_valid_i        (tile_vld_comb_w[0]),
        .nw0_use_cache_i    (nw0_use_cache_w),
        .q214_mode_i        (q214_mode_w),
        .scout_bypass_i     (scout_bypass_i | mode_dmr_i | born_mode_w | boot_kat_trial_w),
        .x0_word_i          (grp_x4_w[31:0]),
        .w0_word_i          (grp_w4_w[31:0]),
        .dot0_q60_i         (dot_t00_i),
        .scout_reject_npu_o (scout_reject_npu_w),
        .scout_reject_tai_o (scout_reject_tai_w),
        .rem_x_hi_o         (rem_x_hi_w),
        .rem_w_hi_o         (rem_w_hi_w)
    );

    wire               any_tile_fault_w;
    wire signed [74:0] tree_even_w;
    wire signed [74:0] tree_odd_w;

    jedi_kagome_reducer_768d u_reducer (
        .clk_i               (clk_core_w),
        .rst_n_i             (rst_n_raw_i),
        .eval_arm_i          (stream_finishing_w),
        .eval_clear_i        (cmd_eval_clr_q | start_any_eval_w),
        .mode_dmr_i          (mode_dmr_i & (~boot_kat_trial_w)),
        .q214_mode_i         (q214_mode_w & (~boot_kat_trial_w)),
        .born_mode_i         (born_mode_w & (~boot_kat_trial_w)),
        .born_pass_i         (born_pass_w),
        .dmr_seu_inj_i       (dmr_seu_inj_w),
        .active_tile_mask_i  (gnc_active_mask_w),
        .tile_done_sticky_i  (tile_done_sticky_i),
        .tile_fault_vec_i    (tile_fault_vec_i),
        .delta_e_q30_i       (reg_delta_e_q),
        .dot_t00_i           (dot_t00_i),
        .dot_t01_i           (dot_t01_i),
        .dot_t02_i           (dot_t02_i),
        .dot_t03_i           (dot_t03_i),
        .dot_t04_i           (dot_t04_i),
        .dot_t05_i           (dot_t05_i),
        .dot_t06_i           (dot_t06_i),
        .dot_t07_i           (dot_t07_i),
        .dot_t08_i           (dot_t08_i),
        .dot_t09_i           (dot_t09_i),
        .dot_t10_i           (dot_t10_i),
        .dot_t11_i           (dot_t11_i),
        .reducer_eval_en_o   (reducer_eval_en_w),
        .watchdog_trip_o     (watchdog_trip_w),
        .any_tile_fault_o    (any_tile_fault_w),
        .dmr_divergence_o    (dmr_divergence_w),
        .upper_guard_ok_o    (upper_guard_ok_w),
        .tree_even_o         (tree_even_w),
        .tree_odd_o          (tree_odd_w),
        .dot76_o             (dot76_w),
        .rcf_quad_q30_o      (rcf_quad_q30_w),
        .npu_tier_ok_o       (npu_tier_ok_w),
        .tai_tier_ok_o       (tai_tier_ok_w),
        .born_valid_o        (born_valid_w),
        .born_fidelity_q30_o (born_fidelity_q30_w)
    );

    jedi_gnc_tmr_tai #(
        .GOLDEN_DOT76_ROM (GOLDEN_DOT76_ROM)
    ) u_gnc_tmr (
        .clk_in_raw_i           (clk_in_raw_i),
        .rst_n_raw_i            (rst_n_raw_i),
        .therm_82_n_raw_i       (therm_82_n_raw_i),
        .therm_105_n_raw_i      (therm_105_n_raw_i),
        .therm_122_n_raw_i      (therm_122_n_raw_i),
        .cap_good_raw_i         (cap_good_raw_i),
        .veto_n_raw_i           (veto_n_raw_i),
        .gear1_allow_raw_i      (gear1_allow_raw_i),
        .clk_core_i             (clk_core_w),
        .gear_en_pulse_o        (gear_en_pulse_w),
        .gear_stat_o            (gear_stat_o),
        .boot_kat_trial_o       (boot_kat_trial_w),
        .gear1_lockout_sticky_o (gear1_lockout_sticky_w),
        .kat_pass_o             (kat_pass_o),
        .eval_req_i             (start_any_eval_w),
        .eval_clear_i           (cmd_eval_clr_q),
        .mode_dmr_i             (mode_dmr_i & (~boot_kat_trial_w)),
        .scout_bypass_i         (scout_bypass_i | boot_kat_trial_w),
        .born_mode_i            (born_mode_w & (~boot_kat_trial_w)),
        .canary_trip_i          (canary_trip_w),
        .kat_run_req_i          (cmd_kat_req_q),
        .kat_done_i             (kat_done_pulse_q),
        .kat_dot76_i            (dot76_w),
        .kat_100m_fail_inj_i    (kat_100m_inj_w),
        .tile0_done_i           (tile_done_sticky_i[0]),
        .scout_reject_npu_i     (scout_reject_npu_w),
        .reducer_eval_en_i      (reducer_eval_en_w),
        .watchdog_trip_i        (watchdog_trip_w),
        .any_tile_fault_i       (any_tile_fault_w),
        .dmr_divergence_i       (dmr_divergence_w),
        .npu_tier_ok_i          (npu_tier_ok_w),
        .tai_tier_ok_i          (tai_tier_ok_w),
        .epoch_reset_i          (cmd_epoch_rst_q),
        .max_cycles_i           (reg_max_cycles_q),
        .max_tokens_i           (reg_max_tokens_q),
        .max_pulses_i           (reg_max_pulses_q),
        .max_energy_uj_i        (reg_max_energy_q),
        .inc_cycles_i           (32'd208),
        .inc_tokens_i           (32'd1),
        .inc_energy_uj_i        (32'd1),
        .commit_cost_i          (commit_cost_pulse_q),
        .active_spec_hash_i     (active_spec_hash_w),
        .expected_spec_hash_i   (DEFAULT_SPEC_HASH),
        .tmr_fault_inj_i        (tmr_fault_inj_w),
        .tile_clk_en_o          (gnc_tile_clk_en_w),
        .tile_start_o           (gnc_tile_start_w),
        .active_tile_mask_o     (gnc_active_mask_w),
        .eval_arm_reducer_o     (gnc_eval_arm_w),
        .scout_aborted_o        (scout_aborted_w),
        .egress_mode_o          (egress_mode_w),
        .npu_egress_en_o        (npu_egress_en_w),
        .costbound_trip_o       (costbound_trip_o),
        .epoch_ack_o            (epoch_ack_o),
        .act_en_p_o             (act_en_p_o),
        .act_en_n_o             (act_en_n_o),
        .tai_heartbeat_o        (tai_heartbeat_o)
    );

    assign tile_clk_en_o = gnc_tile_clk_en_w;
    assign tile_start_o  = gnc_tile_start_w;
    assign dmr_fault_o   = dmr_divergence_w;
    assign tile_fault_o  = any_tile_fault_w | watchdog_trip_w;
    assign ospi_irq_n_o  = ~(reducer_eval_en_w | scout_aborted_w | watchdog_trip_w);

    // Centered R90 512x64 Quarantine Ring Buffer T_I/O (logs vetoed/aborted digests)
    reg [8:0]  tio_wr_ptr_q;
    wire       tio_log_en_w = (reducer_eval_en_w & (~reducer_done_d1_q) & (~npu_tier_ok_w)) | scout_aborted_w | dmr_divergence_w;
    wire [63:0] tio_dout_unused_w;

    always @(posedge clk_core_w or negedge rst_n_raw_i) begin
        if (!rst_n_raw_i) begin
            tio_wr_ptr_q <= 9'd0;
        end else if (tio_log_en_w) begin
            tio_wr_ptr_q <= tio_wr_ptr_q + 9'd1;
        end
    end

    jedi_sram_512x64_wrap u_quarantine_tio_sram (
        .clk_i  (clk_core_w),
        .men_i  (tio_log_en_w),
        .wen_i  (tio_log_en_w),
        .ren_i  (1'b0),
        .addr_i (tio_wr_ptr_q),
        .din_i  ({status0_w, rcf_quad_q30_w}),
        .dout_o (tio_dout_unused_w)
    );

    // Hardware dI/dt Stagger Popcount Monitor (verifies popcount <= 4 on every clock edge)
    reg [11:0] prev_clken_q;
    wire [11:0] clken_rise_w = gnc_tile_clk_en_w & (~prev_clken_q);

    function [3:0] popcount12;
        input [11:0] v;
        integer idx;
        begin
            popcount12 = 4'd0;
            for (idx = 0; idx < 12; idx = idx + 1) begin
                popcount12 = popcount12 + {3'd0, v[idx]};
            end
        end
    endfunction

    wire [3:0] cur_clken_pop_w = popcount12(clken_rise_w);
    wire [3:0] cur_start_pop_w = popcount12(gnc_tile_start_w);

    always @(posedge clk_core_w or negedge rst_n_raw_i) begin
        if (!rst_n_raw_i) begin
            prev_clken_q    <= 12'h000;
            max_clken_pop_q <= 4'd0;
            max_start_pop_q <= 4'd0;
            ever_clken_q    <= 12'h000;
        end else begin
            prev_clken_q <= gnc_tile_clk_en_w;
            if (cmd_eval_clr_q || start_any_eval_w) begin
                max_clken_pop_q <= cur_clken_pop_w;
                max_start_pop_q <= cur_start_pop_w;
                ever_clken_q    <= gnc_tile_clk_en_w;
            end else begin
                if (cur_clken_pop_w > max_clken_pop_q) begin
                    max_clken_pop_q <= cur_clken_pop_w;
                end
                if (cur_start_pop_w > max_start_pop_q) begin
                    max_start_pop_q <= cur_start_pop_w;
                end
                ever_clken_q <= ever_clken_q | gnc_tile_clk_en_w;
            end
        end
    end

    wire _unused_ok = &{
        1'b0, spi_rx_sh_q[39], unused_act_dout_w,
        unused_unp0_w, unused_unp1_w, unused_unp2_w, unused_unp3_w,
        dma_wr_count_w, scout_reject_tai_w, rem_x_hi_w, rem_w_hi_w,
        tree_even_w, tree_odd_w, gnc_eval_arm_w, tio_dout_unused_w
    };
endmodule
`default_nettype wire
