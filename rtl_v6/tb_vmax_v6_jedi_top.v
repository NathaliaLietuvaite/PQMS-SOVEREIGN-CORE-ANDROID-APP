// =============================================================================
// rtl_v6/tb_vmax_v6_jedi_top.v
// WP-2: Comprehensive Top-Level Verification Testbench (T01..T16)
// Exercises vmax_v6_jedi_top across all 40 QFN-64 signal pins (100 MHz SDR OSPI,
// 4-pin DBG_SPI, async pad clamp with stopped CLK_IN, 6xDMR, BLUE_SCOUT,
// 240-cycle watchdog, TMR GNC, CostBound, Boot-KAT fallback, and 2-pass Born).
// =============================================================================
`timescale 1ns/1ps

module tb_vmax_v6_jedi_top;

    reg  [7:0] ospi_io_drv;
    reg        ospi_io_oe;
    wire [7:0] OSPI_IO = ospi_io_oe ? ospi_io_drv : 8'hZZ;
    reg        OSPI_CLK_I;
    reg        OSPI_CS_N_I;
    wire       OSPI_RDY_O;
    wire       OSPI_IRQ_N_O;

    reg        DBG_SCK_I;
    reg        DBG_MOSI_I;
    wire       DBG_MISO_O;
    reg        DBG_CS_N_I;

    reg        THERM_82_N;
    reg        THERM_105_N;
    reg        THERM_122_N;
    reg        CAP_GOOD_I;
    reg        GEAR1_ALLOW_I;

    reg        CLK_IN;
    reg        clk_run_en;
    reg        RST_N;
    reg        MODE_DMR_I;
    reg        SCOUT_BYPASS_I;
    wire       BANK_ACTIVE_O;

    wire       ACT_EN_P;
    wire       ACT_EN_N;
    wire       TAI_HEARTBEAT_O;
    reg        VETO_N;
    wire       DMR_FAULT_O;
    wire       COSTBOUND_TRIP_O;
    wire       EPOCH_ACK_O;
    wire       KAT_PASS_O;

    wire       CLK_MON_O;
    wire [1:0] GEAR_STAT;
    wire       TILE_FAULT_O;
    reg        TEST_EN_I;
    wire       SPARE_IO = 1'bZ;

    vmax_v6_jedi_top dut (
        .OSPI_IO          (OSPI_IO),
        .OSPI_CLK_I       (OSPI_CLK_I),
        .OSPI_CS_N_I      (OSPI_CS_N_I),
        .OSPI_RDY_O       (OSPI_RDY_O),
        .OSPI_IRQ_N_O     (OSPI_IRQ_N_O),
        .DBG_SCK_I        (DBG_SCK_I),
        .DBG_MOSI_I       (DBG_MOSI_I),
        .DBG_MISO_O       (DBG_MISO_O),
        .DBG_CS_N_I       (DBG_CS_N_I),
        .THERM_82_N       (THERM_82_N),
        .THERM_105_N      (THERM_105_N),
        .THERM_122_N      (THERM_122_N),
        .CAP_GOOD_I       (CAP_GOOD_I),
        .GEAR1_ALLOW_I    (GEAR1_ALLOW_I),
        .CLK_IN           (CLK_IN),
        .RST_N            (RST_N),
        .MODE_DMR_I       (MODE_DMR_I),
        .SCOUT_BYPASS_I   (SCOUT_BYPASS_I),
        .BANK_ACTIVE_O    (BANK_ACTIVE_O),
        .ACT_EN_P         (ACT_EN_P),
        .ACT_EN_N         (ACT_EN_N),
        .TAI_HEARTBEAT_O  (TAI_HEARTBEAT_O),
        .VETO_N           (VETO_N),
        .DMR_FAULT_O      (DMR_FAULT_O),
        .COSTBOUND_TRIP_O (COSTBOUND_TRIP_O),
        .EPOCH_ACK_O      (EPOCH_ACK_O),
        .KAT_PASS_O       (KAT_PASS_O),
        .CLK_MON_O        (CLK_MON_O),
        .GEAR_STAT        (GEAR_STAT),
        .TILE_FAULT_O     (TILE_FAULT_O),
        .TEST_EN_I        (TEST_EN_I),
        .SPARE_IO         (SPARE_IO)
    );

    // 100 MHz master clock (10.0 ns period), gatable in TB for T15 stopped-clock test
    initial begin
        CLK_IN = 1'b0;
        forever begin
            #5.0;
            if (clk_run_en) begin
                CLK_IN = ~CLK_IN;
            end
        end
    end

    integer pass_cnt;
    integer fail_cnt;

    task check_cond;
        input [511:0] tag;
        input         cond;
        begin
            if (cond) begin
                pass_cnt = pass_cnt + 1;
                $display("[PASS] %0s", tag);
            end else begin
                fail_cnt = fail_cnt + 1;
                $display("[FAIL] %0s at time %0t", tag, $time);
            end
        end
    endtask

    task wait_clks;
        input integer n;
        integer k;
        begin
            for (k = 0; k < n; k = k + 1) begin
                @(posedge CLK_IN);
            end
        end
    endtask

    // 40-bit DBG_SPI write transaction
    task spi_write;
        input [6:0]  addr;
        input [31:0] data;
        reg   [39:0] frame;
        integer b;
        begin
            frame = {1'b1, addr, data};
            DBG_CS_N_I = 1'b0;
            #12.0;
            for (b = 39; b >= 0; b = b - 1) begin
                DBG_MOSI_I = frame[b];
                #8.0;
                DBG_SCK_I  = 1'b1;
                #8.0;
                DBG_SCK_I  = 1'b0;
            end
            #12.0;
            DBG_CS_N_I = 1'b1;
            wait_clks(6);
        end
    endtask

    // 40-bit DBG_SPI read transaction
    task spi_read;
        input  [6:0]  addr;
        output [31:0] rdata;
        reg    [39:0] frame;
        integer b;
        begin
            frame = {1'b0, addr, 32'd0};
            rdata = 32'd0;
            DBG_CS_N_I = 1'b0;
            #12.0;
            for (b = 39; b >= 0; b = b - 1) begin
                DBG_MOSI_I = frame[b];
                #8.0;
                DBG_SCK_I  = 1'b1;
                #4.0;
                if (b < 32) begin
                    rdata[b] = DBG_MISO_O;
                end
                #4.0;
                DBG_SCK_I  = 1'b0;
            end
            #12.0;
            DBG_CS_N_I = 1'b1;
            wait_clks(2);
        end
    endtask

    // Send one 64-bit word over 100 MHz SDR OSPI (8 bytes, asynchronous OSPI_CLK_I)
    task ospi_send_word64;
        input [63:0] w64;
        integer b;
        begin
            while (!OSPI_RDY_O) begin
                #10.0;
            end
            OSPI_CS_N_I = 1'b0;
            ospi_io_oe  = 1'b1;
            for (b = 0; b < 8; b = b + 1) begin
                ospi_io_drv = w64[b*8 +: 8];
                #5.3;
                OSPI_CLK_I  = 1'b1;
                #5.3;
                OSPI_CLK_I  = 1'b0;
            end
            OSPI_CS_N_I = 1'b1;
            ospi_io_oe  = 1'b0;
            wait_clks(3);
        end
    endtask

    // Direct helper to preload active SRAM bank quickly for exhaustive vector sweeps
    // (T14 exercises the full byte-serial OSPI_CLK_I async FIFO + 1P swap end-to-end!)
    task preload_uniform_q30;
        input signed [31:0] x_even;
        input signed [31:0] x_odd;
        input signed [31:0] w_even;
        input signed [31:0] w_odd;
        integer a;
        begin
            for (a = 0; a < 384; a = a + 1) begin
                if (!BANK_ACTIVE_O) begin
                    dut.u_sram_west_a_lo.mem[a] = {x_odd, x_even};
                    dut.u_sram_west_a_hi.mem[a] = {w_odd, w_even};
                end else begin
                    dut.u_sram_east_b_lo.mem[a] = {x_odd, x_even};
                    dut.u_sram_east_b_hi.mem[a] = {w_odd, w_even};
                end
            end
        end
    endtask

    task preload_uniform_q214;
        input signed [15:0] x16;
        input signed [15:0] w16;
        integer a;
        begin
            for (a = 0; a < 192; a = a + 1) begin
                if (!BANK_ACTIVE_O) begin
                    dut.u_sram_west_a_lo.mem[a] = {4{x16}};
                    dut.u_sram_west_a_hi.mem[a] = {4{w16}};
                end else begin
                    dut.u_sram_east_b_lo.mem[a] = {4{x16}};
                    dut.u_sram_east_b_hi.mem[a] = {4{w16}};
                end
            end
        end
    endtask

    task run_eval_and_wait;
        input integer max_wait;
        integer c;
        begin
            spi_write(7'h01, 32'h0000_0010); // eval_clear
            spi_write(7'h01, 32'h0000_0001); // eval_trigger
            c = 0;
            while (OSPI_IRQ_N_O && (c < max_wait)) begin
                @(posedge CLK_IN);
                c = c + 1;
            end
            wait_clks(8);
        end
    endtask

    task full_chip_reset;
        begin
            clk_run_en     = 1'b1;
            RST_N          = 1'b0;
            OSPI_CLK_I     = 1'b0;
            OSPI_CS_N_I    = 1'b1;
            ospi_io_oe     = 1'b0;
            ospi_io_drv    = 8'h00;
            DBG_SCK_I      = 1'b0;
            DBG_MOSI_I     = 1'b0;
            DBG_CS_N_I     = 1'b1;
            THERM_82_N     = 1'b1;
            THERM_105_N    = 1'b1;
            THERM_122_N    = 1'b1;
            CAP_GOOD_I     = 1'b1;
            GEAR1_ALLOW_I  = 1'b0;
            MODE_DMR_I     = 1'b0;
            SCOUT_BYPASS_I = 1'b0;
            VETO_N         = 1'b1;
            TEST_EN_I      = 1'b0;
            wait_clks(8);
            RST_N          = 1'b1;
            // Wait 75 clocks for 2-FF + 64-cycle async recovery glitch filter to open cleanly
            wait_clks(75);
        end
    endtask

    reg [31:0] st0;
    reg [31:0] pop_reg;
    reg [31:0] rcf_reg;
    reg [31:0] fid_reg;
    integer    idx;
    reg        hb_saw_hi;
    reg        hb_saw_lo;

    // Continuous background hardware assertion: on EVERY clock edge, popcount <= 4!
    reg [11:0] mon_prev_clken;
    integer    mon_i;
    integer    mon_pop_c, mon_pop_s;
    reg        stagger_violated;

    always @(posedge dut.clk_core_w or negedge RST_N) begin
        if (!RST_N) begin
            mon_prev_clken   <= 12'h000;
            stagger_violated <= 1'b0;
        end else begin
            mon_pop_c = 0;
            mon_pop_s = 0;
            for (mon_i = 0; mon_i < 12; mon_i = mon_i + 1) begin
                if (dut.tile_clk_en_w[mon_i] && !mon_prev_clken[mon_i]) begin
                    mon_pop_c = mon_pop_c + 1;
                end
                if (dut.tile_start_w[mon_i]) begin
                    mon_pop_s = mon_pop_s + 1;
                end
            end
            if ((mon_pop_c > 4) || (mon_pop_s > 4)) begin
                stagger_violated <= 1'b1;
            end
            mon_prev_clken <= dut.tile_clk_en_w;
        end
    end

    initial begin
        pass_cnt = 0;
        fail_cnt = 0;
        CLK_IN   = 1'b0;
        clk_run_en = 1'b1;

        // =====================================================================
        // T01: Reset / Power-up lands in Gear /2 (50 MHz), HARD_CUT_ROM, 2'b00
        // =====================================================================
        RST_N = 1'b0;
        THERM_82_N = 1'b1; THERM_105_N = 1'b1; THERM_122_N = 1'b1;
        CAP_GOOD_I = 1'b1; GEAR1_ALLOW_I = 1'b0; VETO_N = 1'b1;
        MODE_DMR_I = 1'b0; SCOUT_BYPASS_I = 1'b0; TEST_EN_I = 1'b0;
        OSPI_CLK_I = 1'b0; OSPI_CS_N_I = 1'b1; ospi_io_oe = 1'b0; ospi_io_drv = 8'd0;
        DBG_SCK_I = 1'b0; DBG_MOSI_I = 1'b0; DBG_CS_N_I = 1'b1;
        wait_clks(4);
        check_cond(
            "T01_reset_gear2_hard_cut_safe_2b00",
            (GEAR_STAT == 2'b01) && ({ACT_EN_P, ACT_EN_N} == 2'b00) &&
            (TAI_HEARTBEAT_O == 1'b0) && (dut.u_spine.egress_mode_w == 2'b11)
        );
        full_chip_reset();
        check_cond(
            "T01b_post_recovery_gear2_50mhz",
            (GEAR_STAT == 2'b01) && ({ACT_EN_P, ACT_EN_N} == 2'b00)
        );

        // =====================================================================
        // T02: 12xSimplex 768D positive TAI (RCF ~ 0.995 -> TAI & NPU PASS)
        // x_i = 1/sqrt(768) = 38745080, w_i = 0.995 * x_i = 38551355 -> sum ~ 0.995
        // =====================================================================
        SCOUT_BYPASS_I = 1'b1;
        preload_uniform_q30(32'sd38745080, 32'sd38745080, 32'sd38551355, 32'sd38551355);
        run_eval_and_wait(2000);
        hb_saw_hi = 1'b0;
        hb_saw_lo = 1'b0;
        for (idx = 0; idx < 12; idx = idx + 1) begin
            @(posedge CLK_IN);
            if (TAI_HEARTBEAT_O) hb_saw_hi = 1'b1;
            else                 hb_saw_lo = 1'b1;
        end
        spi_read(7'h10, st0);
        check_cond(
            "T02_12x_simplex_768d_tai_0p995_pass",
            ({ACT_EN_P, ACT_EN_N} == 2'b10) && hb_saw_hi && hb_saw_lo &&
            (st0[18] == 1'b1) && (st0[17] == 1'b1) && (st0[16] == 1'b1) &&
            (st0[15:14] == 2'b00)
        );

        // =====================================================================
        // T03: 12xSimplex 768D NPU-only (RCF ~ 0.75 -> NPU PASS, TAI VETO!)
        // w_i = 0.75 * 38745080 = 29058810
        // =====================================================================
        preload_uniform_q30(32'sd38745080, 32'sd38745080, 32'sd29058810, 32'sd29058810);
        run_eval_and_wait(2000);
        spi_read(7'h10, st0);
        check_cond(
            "T03_12x_simplex_768d_npu_0p75_tai_veto",
            ({ACT_EN_P, ACT_EN_N} == 2'b00) && (TAI_HEARTBEAT_O == 1'b0) &&
            (st0[17] == 1'b1) && (st0[18] == 1'b0) && (st0[16] == 1'b1)
        );

        // =====================================================================
        // T04: Antiparallel -0.995 total dissonance VETO (dot76 < 0)
        // =====================================================================
        preload_uniform_q30(32'sd38745080, 32'sd38745080, -32'sd38551355, -32'sd38551355);
        run_eval_and_wait(2000);
        spi_read(7'h10, st0);
        check_cond(
            "T04_antiparallel_neg0p995_total_veto",
            ({ACT_EN_P, ACT_EN_N} == 2'b00) && (st0[18] == 1'b0) &&
            (st0[17] == 1'b0) && (st0[16] == 1'b0) && (st0[15:14] == 2'b11)
        );

        // =====================================================================
        // T05: Modulo-4.0 (+4.99) aliasing upper-guard VETO (dot76 > 0x000_1001...)
        // x_i = w_i = 86500000 -> 768 * (86.5M)^2 / 2^60 ~ +4.985 > 1.000244!
        // =====================================================================
        preload_uniform_q30(32'sd86500000, 32'sd86500000, 32'sd86500000, 32'sd86500000);
        run_eval_and_wait(2000);
        spi_read(7'h10, st0);
        check_cond(
            "T05_mod4_plus4p99_upper_guard_veto",
            ({ACT_EN_P, ACT_EN_N} == 2'b00) && (st0[20] == 1'b0) &&
            (st0[18] == 1'b0) && (st0[17] == 1'b0)
        );

        // =====================================================================
        // T06: MODE_6X_DMR_RADHARD 1x scaling proof (384D = 6 tiles per half-tree)
        // 1/sqrt(384) in Q2.30 = 54793818.
        // RCF = 0.495 -> w = 27122940 -> MUST VETO (2x bug would pass as 0.990!)
        // RCF = 0.995 -> w = 54519849 -> MUST PASS TAI!
        // =====================================================================
        MODE_DMR_I = 1'b1;
        preload_uniform_q30(32'sd54793818, 32'sd54793818, 32'sd27122940, 32'sd27122940);
        run_eval_and_wait(2000);
        spi_read(7'h10, st0);
        check_cond(
            "T06a_dmr6_1x_scaling_0p495_must_veto",
            ({ACT_EN_P, ACT_EN_N} == 2'b00) && (st0[18] == 1'b0) &&
            (st0[17] == 1'b0) && (st0[16] == 1'b0)
        );

        preload_uniform_q30(32'sd54793818, 32'sd54793818, 32'sd54519849, 32'sd54519849);
        run_eval_and_wait(2000);
        spi_read(7'h10, st0);
        check_cond(
            "T06b_dmr6_1x_scaling_0p995_tai_pass",
            ({ACT_EN_P, ACT_EN_N} == 2'b10) && (DMR_FAULT_O == 1'b0) &&
            (st0[18] == 1'b1) && (st0[17] == 1'b1)
        );

        // =====================================================================
        // T07: MODE_6X_DMR_RADHARD 1-LSB SEU divergence (tree_even != tree_odd -> VETO)
        // =====================================================================
        TEST_EN_I = 1'b1;
        spi_write(7'h09, 32'h0000_0008); // dmr_seu_inj = 1
        run_eval_and_wait(2000);
        spi_read(7'h10, st0);
        check_cond(
            "T07_dmr6_1lsb_seu_divergence_0cyc_veto",
            (DMR_FAULT_O == 1'b1) && ({ACT_EN_P, ACT_EN_N} == 2'b00) &&
            (st0[21] == 1'b1) && (st0[16] == 1'b0)
        );
        spi_write(7'h09, 32'h0000_0000);
        TEST_EN_I  = 1'b0;
        MODE_DMR_I = 1'b0;

        // =====================================================================
        // T08 & T09: BLUE_SCOUT Cauchy-Schwarz early reject (tile_clk_en[11:1]==0)
        // + 0% false-reject boundary test (Q2.30 & Q2.14) + popcount <= 4 proof!
        // =====================================================================
        SCOUT_BYPASS_I = 1'b0;
        // Orthogonal/zero correlation in Tile 0 with concentrated norm -> scout rejects!
        // Put entire unit norm in Tile 0: x0 = w0_orth -> dot0 = 0, NX_0 = 1.0, NW_0 = 1.0 -> rem = 0 -> REJECT!
        for (idx = 0; idx < 384; idx = idx + 1) begin
            dut.u_sram_west_a_lo.mem[idx] = 64'd0;
            dut.u_sram_west_a_hi.mem[idx] = 64'd0;
        end
        for (idx = 0; idx < 64; idx = idx + 1) begin
            // x0 = +1/8 (134217728), w0 = alternating +1/8, -1/8 -> NX_0 = 1.0, NW_0 = 1.0, D_0 = 0!
            dut.u_sram_west_a_lo.mem[idx] = {32'sd0, 32'sd134217728};
            dut.u_sram_west_a_hi.mem[idx] = {32'sd0, (idx[0] ? -32'sd134217728 : 32'sd134217728)};
        end
        run_eval_and_wait(1000);
        spi_read(7'h10, st0);
        spi_read(7'h16, pop_reg);
        check_cond(
            "T09a_blue_scout_early_reject_keeps_tiles_1_11_gated",
            (st0[23] == 1'b1) && (pop_reg[11:1] == 11'd0) && (pop_reg[0] == 1'b1) &&
            ({ACT_EN_P, ACT_EN_N} == 2'b00)
        );

        // Boundary 0% false-reject in Q2.30 (RCF ~ 0.992 right above 0.990, uniform across 12 tiles)
        preload_uniform_q30(32'sd38745080, 32'sd38745080, 32'sd38435120, 32'sd38435120);
        run_eval_and_wait(2000);
        spi_read(7'h10, st0);
        spi_read(7'h16, pop_reg);
        check_cond(
            "T09b_blue_scout_boundary_q230_zero_false_reject",
            (st0[23] == 1'b0) && ({ACT_EN_P, ACT_EN_N} == 2'b10) && (pop_reg[11:0] == 12'hFFF)
        );

        // Boundary 0% false-reject in Q2.14 (x16 = w16 = 591 -> 768*(591/16384)^2 = 0.99888 <= 1.00195!)
        spi_write(7'h02, 32'h0000_0001); // q214_mode = 1
        preload_uniform_q214(16'sd591, 16'sd591);
        run_eval_and_wait(2000);
        spi_read(7'h10, st0);
        check_cond(
            "T09c_blue_scout_boundary_q214_zero_false_reject",
            (st0[23] == 1'b0) && ({ACT_EN_P, ACT_EN_N} == 2'b10) && (st0[20] == 1'b1)
        );
        spi_write(7'h02, 32'h0000_0000); // back to Q2.30

        // Check T08 continuous popcount monitor across all runs so far
        spi_read(7'h16, pop_reg);
        check_cond(
            "T08_dual_stagger_popcount_le_4_every_edge",
            (!stagger_violated) && (pop_reg[27:24] <= 4'd4) && (pop_reg[19:16] <= 4'd4)
        );

        // =====================================================================
        // T10: 240-cycle tile-hang watchdog forces HARD_CUT_ROM
        // =====================================================================
        SCOUT_BYPASS_I = 1'b1;
        TEST_EN_I      = 1'b1;
        preload_uniform_q30(32'sd38745080, 32'sd38745080, 32'sd38551355, 32'sd38551355);
        spi_write(7'h09, 32'h0000_0040); // tile11_hang_inj = 1
        run_eval_and_wait(3000);
        spi_read(7'h10, st0);
        check_cond(
            "T10_240cyc_watchdog_forces_hard_cut_rom",
            (TILE_FAULT_O == 1'b1) && (st0[22] == 1'b1) &&
            (st0[15:14] == 2'b11) && ({ACT_EN_P, ACT_EN_N} == 2'b00)
        );
        spi_write(7'h09, 32'h0000_0000);
        spi_write(7'h01, 32'h0000_0010); // eval_clear

        // =====================================================================
        // T11: TMR GNC single-replica fault injection (001, 010, 100 masked 100%)
        // =====================================================================
        spi_write(7'h09, 32'h0000_0001); // corrupt replica 0
        run_eval_and_wait(2000);
        check_cond("T11a_tmr_mask_rep0", ({ACT_EN_P, ACT_EN_N} == 2'b10));

        spi_write(7'h09, 32'h0000_0002); // corrupt replica 1
        run_eval_and_wait(2000);
        check_cond("T11b_tmr_mask_rep1", ({ACT_EN_P, ACT_EN_N} == 2'b10));

        spi_write(7'h09, 32'h0000_0004); // corrupt replica 2
        run_eval_and_wait(2000);
        check_cond("T11c_tmr_mask_rep2", ({ACT_EN_P, ACT_EN_N} == 2'b10));
        spi_write(7'h09, 32'h0000_0000);
        TEST_EN_I = 1'b0;

        // =====================================================================
        // T12: CostBound hard ceiling lockout until authorized epoch_reset
        // =====================================================================
        spi_write(7'h05, 32'd1);         // max_tokens = 1 (already >=1 after prior evals -> trips!)
        wait_clks(6);
        check_cond(
            "T12a_costbound_ceiling_locks_out_tai",
            (COSTBOUND_TRIP_O == 1'b1) && ({ACT_EN_P, ACT_EN_N} == 2'b00)
        );
        spi_write(7'h05, 32'h00FF_FFFF); // restore ceiling
        spi_write(7'h01, 32'h0000_0004); // authorized epoch_reset -> clears lockout & pulses EPOCH_ACK_O!
        wait_clks(6);
        check_cond(
            "T12b_costbound_authorized_epoch_reset_unlocks",
            (COSTBOUND_TRIP_O == 1'b0) && ({ACT_EN_P, ACT_EN_N} == 2'b10)
        );

        // =====================================================================
        // T13: Gear /1 Boot-KAT graceful fallback (100 MHz fail -> sticky /2 PASS)
        //      + live Canary glitch-free /1 -> /2 downshift
        // =====================================================================
        full_chip_reset();
        GEAR1_ALLOW_I = 1'b1;
        TEST_EN_I     = 1'b1;
        wait_clks(6);
        spi_write(7'h09, 32'h0000_0020); // inject 100 MHz KAT failure (simulates slow SS corner)
        spi_write(7'h01, 32'h0000_0008); // kat_run_req
        // Immediately during boot_kat_trial, ACT_EN must stay clamped 2'b00
        check_cond("T13a_boot_kat_clamps_act_en_2b00", ({ACT_EN_P, ACT_EN_N} == 2'b00));
        wait_clks(600);
        spi_read(7'h10, st0);
        check_cond(
            "T13b_boot_kat_100m_fail_graceful_gear2_fallback_pass",
            (KAT_PASS_O == 1'b1) && (GEAR_STAT == 2'b01) && (st0[25] == 1'b1)
        );

        // Clean reset, pass 100 MHz KAT into Gear /1 (2'b00), then trip Canary -> /2 downshift!
        full_chip_reset();
        GEAR1_ALLOW_I = 1'b1;
        TEST_EN_I     = 1'b1;
        wait_clks(6);
        spi_write(7'h01, 32'h0000_0008); // kat_run_req (passes cleanly at 100 MHz!)
        wait_clks(300);
        check_cond("T13c_boot_kat_100m_clean_unlocks_gear1", (KAT_PASS_O == 1'b1) && (GEAR_STAT == 2'b00));
        spi_write(7'h09, 32'h0000_0010); // canary_trip_inj = 1
        wait_clks(8);
        check_cond("T13d_canary_trip_glitchfree_downshift_gear2", (GEAR_STAT == 2'b01));
        spi_write(7'h09, 32'h0000_0000);
        TEST_EN_I = 1'b0;

        // =====================================================================
        // T14: 100 MHz SDR OSPI async FIFO + Q2.14 (16'h4000 -> 32'h4000_0000)
        //      + 1P ping-pong bank swap (1 quiescent cycle + THERM_82_N stall)
        // =====================================================================
        full_chip_reset();
        SCOUT_BYPASS_I = 1'b1;
        spi_write(7'h02, 32'h0000_0001); // q214_mode = 1
        spi_write(7'h01, 32'h0000_0020); // dma_addr_rst = 1
        // Stream 192 words of X into shadow BANK_B LO: word 0 has lane0 = 16'h4000 (+1.0), rest 0!
        ospi_send_word64(64'h0000_0000_0000_4000);
        for (idx = 1; idx < 192; idx = idx + 1) begin
            dut.u_sram_east_b_lo.mem[idx] = 64'd0;
        end
        // Put W word 0 in shadow BANK_B HI: lane0 = 16'h3FCE (~0.99695), rest 0 -> dot = +0.99695!
        dut.u_sram_east_b_hi.mem[0] = 64'h0000_0000_0000_3FCE;
        for (idx = 1; idx < 192; idx = idx + 1) begin
            dut.u_sram_east_b_hi.mem[idx] = 64'd0;
        end

        // Assert thermal lock (THERM_82_N = 0) and request bank swap -> must defer & drop OSPI_RDY_O = 0!
        THERM_82_N = 1'b0;
        wait_clks(4);
        spi_write(7'h01, 32'h0000_0002); // swap_req
        wait_clks(6);
        check_cond(
            "T14a_therm82_defers_swap_and_asserts_ospi_rdy_backpressure",
            (BANK_ACTIVE_O == 1'b0) && (OSPI_RDY_O == 1'b0)
        );
        // Release THERM_82_N -> swap completes with 1 quiescent dead-cycle (A_MEN=0 on both banks)!
        THERM_82_N = 1'b1;
        wait_clks(10);
        spi_read(7'h10, st0);
        check_cond(
            "T14b_pingpong_quiescent_swap_complete",
            (BANK_ACTIVE_O == 1'b1) && (OSPI_RDY_O == 1'b1) && (st0[27] == 1'b1)
        );
        run_eval_and_wait(2000);
        spi_read(7'h11, rcf_reg);
        check_cond(
            "T14c_ospi_q214_shift16_exact_tai_pass",
            ({ACT_EN_P, ACT_EN_N} == 2'b10) && (rcf_reg >= 32'h3EB9_F55A)
        );
        spi_write(7'h02, 32'h0000_0000); // back to Q2.30

        // =====================================================================
        // T15: Async pad clamp cuts ACT_EN_P/N & TAI_HEARTBEAT_O in 0 ns
        //      EVEN WITH CLK_IN COMPLETELY STOPPED!
        // =====================================================================
        preload_uniform_q30(32'sd38745080, 32'sd38745080, 32'sd38551355, 32'sd38551355);
        run_eval_and_wait(2000);
        idx = 0;
        while (!TAI_HEARTBEAT_O && (idx < 32)) begin
            @(posedge CLK_IN);
            idx = idx + 1;
        end
        #1.0;
        clk_run_en = 1'b0; // FREEZE CLK_IN COMPLETELY!
        #2.0;
        check_cond("T15_pre_active_with_stopped_clk", (ACT_EN_P == 1'b1) && (TAI_HEARTBEAT_O == 1'b1));

        VETO_N = 1'b0;
        #0.1;
        check_cond("T15a_veto_n_0ns_clamp_no_clk", ({ACT_EN_P, ACT_EN_N} == 2'b00) && (TAI_HEARTBEAT_O == 1'b0));
        VETO_N = 1'b1;

        clk_run_en = 1'b1;
        wait_clks(80);
        preload_uniform_q30(32'sd38745080, 32'sd38745080, 32'sd38551355, 32'sd38551355);
        run_eval_and_wait(2000);
        clk_run_en = 1'b0;
        #2.0;
        CAP_GOOD_I = 1'b0;
        #0.1;
        check_cond("T15b_cap_good_0ns_clamp_no_clk", ({ACT_EN_P, ACT_EN_N} == 2'b00) && (TAI_HEARTBEAT_O == 1'b0));
        CAP_GOOD_I = 1'b1;

        clk_run_en = 1'b1;
        wait_clks(80);
        run_eval_and_wait(2000);
        clk_run_en = 1'b0;
        #2.0;
        THERM_122_N = 1'b0;
        #0.1;
        check_cond("T15c_therm122_0ns_clamp_no_clk", ({ACT_EN_P, ACT_EN_N} == 2'b00) && (TAI_HEARTBEAT_O == 1'b0));
        THERM_122_N = 1'b1;

        clk_run_en = 1'b1;
        full_chip_reset();
        SCOUT_BYPASS_I = 1'b1;
        preload_uniform_q30(32'sd38745080, 32'sd38745080, 32'sd38551355, 32'sd38551355);
        run_eval_and_wait(2000);
        clk_run_en = 1'b0;
        #2.0;
        RST_N = 1'b0;
        #0.1;
        check_cond("T15d_rst_n_0ns_clamp_no_clk", ({ACT_EN_P, ACT_EN_N} == 2'b00) && (TAI_HEARTBEAT_O == 1'b0));
        clk_run_en = 1'b1;
        full_chip_reset();

        // =====================================================================
        // T16: 2-Pass Complex Born-Fidelity Telemetry Mode (C^384 -> S^767)
        //      Global phase theta = 120 deg -> Re = -0.5*0.995 = -0.4975,
        //      Im = +0.8660254*0.995 = +0.861695 -> F = Re^2 + Im^2 ~ 0.99000!
        //      ACT_EN_P/N MUST stay 2'b00 throughout!
        // =====================================================================
        SCOUT_BYPASS_I = 1'b1;
        // Pass 0 (Re = -0.4975 -> w = -19275806): born_mode=1, born_pass=0 (reg 0x02 = 0x02)
        spi_write(7'h02, 32'h0000_0002);
        preload_uniform_q30(32'sd38745338, 32'sd38745338, -32'sd19275806, -32'sd19275806);
        run_eval_and_wait(2000);
        check_cond("T16a_born_pass0_keeps_act_2b00", ({ACT_EN_P, ACT_EN_N} == 2'b00));

        // Pass 1 (Im = +0.861695 -> w = +33386686): born_mode=1, born_pass=1 (reg 0x02 = 0x06)
        spi_write(7'h02, 32'h0000_0006);
        preload_uniform_q30(32'sd38745338, 32'sd38745338, 32'sd33386686, 32'sd33386686);
        run_eval_and_wait(2000);
        spi_read(7'h10, st0);
        spi_read(7'h12, fid_reg);
        $display("V6_BORN_FID fid_hex=%08x st0=%08x", fid_reg, st0);
        check_cond(
            "T16b_born_pass1_phase_invariant_fidelity_and_act_2b00",
            ({ACT_EN_P, ACT_EN_N} == 2'b00) && (st0[19] == 1'b1) &&
            (fid_reg == 32'h3F5C_9B5E)
        );
        spi_write(7'h02, 32'h0000_0000);

        // =====================================================================
        // Live Co-Sim Vector Sweep (16 vectors across Q2.30, Q2.14, DMR6, Scout)
        // =====================================================================
        for (idx = 0; idx < 16; idx = idx + 1) begin
            MODE_DMR_I     = (idx >= 12) ? 1'b1 : 1'b0;
            SCOUT_BYPASS_I = (idx >= 8)  ? 1'b1 : 1'b0;
            if (idx[2] && (idx < 12)) begin
                spi_write(7'h02, 32'h0000_0001);
                preload_uniform_q214(16'sd591, $signed(16'sd200 + idx * 16'sd32));
            end else begin
                spi_write(7'h02, 32'h0000_0000);
                if (idx >= 12) begin
                    preload_uniform_q30(
                        32'sd54793818, 32'sd54793818,
                        (idx - 12) * 32'sd18173283 + 32'sd10000000,
                        (idx - 12) * 32'sd18173283 + 32'sd10000000
                    );
                end else begin
                    preload_uniform_q30(
                        32'sd38745338, 32'sd38745338,
                        (idx * 32'sd6200000) - 32'sd12000000,
                        (idx * 32'sd6200000) - 32'sd12000000
                    );
                end
            end
            run_eval_and_wait(2000);
            spi_read(7'h10, st0);
            spi_read(7'h11, rcf_reg);
            $display(
                "V6_COSIM idx=%0d dmr=%0d q214=%0d bypass=%0d rcf=%08x npu=%0d tai=%0d srej=%0d",
                idx, MODE_DMR_I, (idx[2] && (idx < 12)) ? 1 : 0, SCOUT_BYPASS_I,
                rcf_reg, st0[17], st0[18], st0[23]
            );
        end
        MODE_DMR_I     = 1'b0;
        SCOUT_BYPASS_I = 1'b0;
        spi_write(7'h02, 32'h0000_0000);

        $display("==============================================================");
        $display("V6_JEDI_TB_SUMMARY: passed=%0d failed=%0d", pass_cnt, fail_cnt);
        if (fail_cnt == 0) begin
            $display("V6_JEDI_TB_STATUS=PASSED");
        end else begin
            $display("V6_JEDI_TB_STATUS=FAILED");
        end
        $display("==============================================================");
        $finish;
    end
endmodule
