// =============================================================================
// rtl_v6/jedi_ospi_async_dma.v
// WP-1.2 & G4: 100 MHz SDR OSPI -> 64-bit Packer -> 4-Entry Gray-Pointer Async FIFO
// -> clk_dma_100 Domain -> 1P-SRAM Ping-Pong Bank Arbiter (with 1-Cycle Quiescent
// Handover A_MEN=0 & THERM_82_N Backpressure) + Q2.14 (<<16) / Q2.30 Unpacker.
// =============================================================================
`timescale 1ns/1ps
`default_nettype none

module jedi_ospi_async_dma (
    // External OSPI clock domain
    input  wire        ospi_clk_i,
    input  wire        ospi_cs_n_i,
    input  wire [7:0]  ospi_io_i,
    output wire        ospi_rdy_o,

    // Matched 100 MHz DMA / Core clock domain (behind twin root sg13g2_lgcp_1)
    input  wire        clk_dma_i,
    input  wire        rst_n_i,
    input  wire        gear_en_pulse_i,
    input  wire        therm_82_n_i,
    input  wire        q214_mode_i,
    input  wire        swap_req_i,
    input  wire        dma_addr_rst_i,
    input  wire        core_idle_i,
    input  wire        core_rd_req_i,
    input  wire [10:0] core_rd_addr_i,

    // Flank SRAM Bank A & Bank B controls (2x 1024x64 = 2048 words per bank -> [10:0] addr)
    output wire        bank_active_o,
    output wire        swap_quiescent_o,
    output wire        swap_deferred_o,
    output wire        bank_clk_en_a_o,
    output wire        bank_clk_en_b_o,
    output wire        sram_a_men_o,
    output wire        sram_a_wen_o,
    output wire        sram_a_ren_o,
    output wire [10:0] sram_a_addr_o,
    output wire [63:0] sram_a_din_o,
    input  wire [63:0] sram_a_dout_i,

    output wire        sram_b_men_o,
    output wire        sram_b_wen_o,
    output wire        sram_b_ren_o,
    output wire [10:0] sram_b_addr_o,
    output wire [63:0] sram_b_din_o,
    input  wire [63:0] sram_b_dout_i,

    // Active-bank read data + lossless Q2.14 / Q2.30 unpacked 32-bit lanes
    output wire [63:0] active_dout_raw_o,
    output wire signed [31:0] unpack_q30_0_o,
    output wire signed [31:0] unpack_q30_1_o,
    output wire signed [31:0] unpack_q30_2_o,
    output wire signed [31:0] unpack_q30_3_o,
    output wire [10:0] dma_wr_count_o
);

    // =========================================================================
    // 1. OSPI_CLK_I Domain: 8-Byte -> 64-Bit Little-Endian Packer & Gray Write Ptr
    // =========================================================================
    reg [2:0]  byte_cnt_q;
    reg [55:0] byte_shift_q;
    reg [63:0] fifo_mem [0:3];
    reg [2:0]  wbin_q;
    reg [2:0]  wgray_q;

    (* ASYNC_REG = "TRUE", keep = 1, dont_touch = "true" *) reg [2:0] rgray_sync1_q;
    (* ASYNC_REG = "TRUE", keep = 1, dont_touch = "true" *) reg [2:0] rgray_sync2_q;
    (* ASYNC_REG = "TRUE", keep = 1, dont_touch = "true" *) reg       stall_sync1_q;
    (* ASYNC_REG = "TRUE", keep = 1, dont_touch = "true" *) reg       stall_sync2_q;

    wire [2:0] wbin_next_w  = wbin_q + 3'd1;
    wire [2:0] wgray_next_w = (wbin_next_w >> 1) ^ wbin_next_w;
    wire       fifo_full_w  = (wgray_q == {~rgray_sync2_q[2:1], rgray_sync2_q[0]});

    // Read-side Gray pointer declared ahead for CDC hookup
    reg [2:0] rbin_q;
    reg [2:0] rgray_q;
    reg       swap_pending_q;

    wire host_stall_clk_w = swap_pending_q & (~therm_82_n_i);

    always @(posedge ospi_clk_i or negedge rst_n_i) begin
        if (!rst_n_i) begin
            byte_cnt_q    <= 3'd0;
            byte_shift_q  <= 56'd0;
            wbin_q        <= 3'd0;
            wgray_q       <= 3'd0;
            rgray_sync1_q <= 3'd0;
            rgray_sync2_q <= 3'd0;
            stall_sync1_q <= 1'b0;
            stall_sync2_q <= 1'b0;
            fifo_mem[0]   <= 64'd0;
            fifo_mem[1]   <= 64'd0;
            fifo_mem[2]   <= 64'd0;
            fifo_mem[3]   <= 64'd0;
        end else begin
            rgray_sync1_q <= rgray_q;
            rgray_sync2_q <= rgray_sync1_q;
            stall_sync1_q <= host_stall_clk_w;
            stall_sync2_q <= stall_sync1_q;

            if (ospi_cs_n_i) begin
                byte_cnt_q <= 3'd0;
            end else if (!fifo_full_w && !stall_sync2_q) begin
                if (byte_cnt_q == 3'd7) begin
                    fifo_mem[wbin_q[1:0]] <= {ospi_io_i, byte_shift_q};
                    wbin_q                <= wbin_next_w;
                    wgray_q               <= wgray_next_w;
                    byte_cnt_q            <= 3'd0;
                end else begin
                    byte_shift_q <= {ospi_io_i, byte_shift_q[55:8]};
                    byte_cnt_q   <= byte_cnt_q + 3'd1;
                end
            end
        end
    end

    // Immediate hardware backpressure when FIFO full or thermal swap lock active
    assign ospi_rdy_o = rst_n_i & (~fifo_full_w) & (~stall_sync2_q) & (~host_stall_clk_w);

    // =========================================================================
    // 2. clk_dma_i Domain: Gray Read Ptr, Shadow-Bank DMA & Quiescent Swap
    // =========================================================================
    (* ASYNC_REG = "TRUE", keep = 1, dont_touch = "true" *) reg [2:0] wgray_sync1_q;
    (* ASYNC_REG = "TRUE", keep = 1, dont_touch = "true" *) reg [2:0] wgray_sync2_q;

    reg        bank_active_q;
    reg        swap_quiescent_q;
    reg [10:0] dma_addr_q;
    reg        dma_wr_vld_q;
    reg [63:0] dma_wr_dat_q;
    reg [10:0] dma_wr_addr_lat_q;

    wire       fifo_empty_w = (rgray_q == wgray_sync2_q);
    wire [2:0] rbin_next_w  = rbin_q + 3'd1;
    wire [2:0] rgray_next_w = (rbin_next_w >> 1) ^ rbin_next_w;

    wire       dma_pop_w    = (~fifo_empty_w) & (~swap_quiescent_q) & (~swap_pending_q);
    wire       dma_idle_w   = fifo_empty_w & (~dma_wr_vld_q);

    always @(posedge clk_dma_i or negedge rst_n_i) begin
        if (!rst_n_i) begin
            wgray_sync1_q     <= 3'd0;
            wgray_sync2_q     <= 3'd0;
            rbin_q            <= 3'd0;
            rgray_q           <= 3'd0;
            bank_active_q     <= 1'b0;
            swap_pending_q    <= 1'b0;
            swap_quiescent_q  <= 1'b0;
            dma_addr_q        <= 11'd0;
            dma_wr_vld_q      <= 1'b0;
            dma_wr_dat_q      <= 64'd0;
            dma_wr_addr_lat_q <= 11'd0;
        end else begin
            wgray_sync1_q <= wgray_q;
            wgray_sync2_q <= wgray_sync1_q;

            if (dma_addr_rst_i) begin
                dma_addr_q <= 11'd0;
            end

            if (swap_req_i) begin
                swap_pending_q <= 1'b1;
            end

            if (dma_pop_w) begin
                dma_wr_vld_q      <= 1'b1;
                dma_wr_dat_q      <= fifo_mem[rbin_q[1:0]];
                dma_wr_addr_lat_q <= dma_addr_q;
                dma_addr_q        <= dma_addr_q + 11'd1;
                rbin_q            <= rbin_next_w;
                rgray_q           <= rgray_next_w;
            end else begin
                dma_wr_vld_q <= 1'b0;
            end

            // Quiescent 1-dead-cycle handover (A_MEN = 0 on both banks for 1 cycle)
            if (swap_quiescent_q) begin
                swap_quiescent_q <= 1'b0;
            end else if (swap_pending_q && therm_82_n_i && dma_idle_w && core_idle_i && gear_en_pulse_i) begin
                bank_active_q    <= ~bank_active_q;
                swap_pending_q   <= 1'b0;
                swap_quiescent_q <= 1'b1;
                dma_addr_q       <= 11'd0;
            end
        end
    end

    assign bank_active_o    = bank_active_q;
    assign swap_quiescent_o = swap_quiescent_q;
    assign swap_deferred_o  = swap_pending_q & (~therm_82_n_i);
    assign dma_wr_count_o   = dma_addr_q;

    // Strict 1P-SRAM mutual exclusion:
    // bank_active_q == 0 -> BANK_A = Core Active (Read-Only), BANK_B = Shadow DMA (Write-Only)
    // bank_active_q == 1 -> BANK_B = Core Active (Read-Only), BANK_A = Shadow DMA (Write-Only)
    // swap_quiescent_q == 1 -> BOTH banks A_MEN = 0!
    wire core_rd_en_w = core_rd_req_i & gear_en_pulse_i & (~swap_quiescent_q);
    wire dma_wr_en_w  = dma_wr_vld_q & (~swap_quiescent_q);

    assign bank_clk_en_a_o = bank_active_q ? dma_wr_en_w : core_rd_en_w;
    assign bank_clk_en_b_o = bank_active_q ? core_rd_en_w : dma_wr_en_w;

    assign sram_a_men_o  = (~swap_quiescent_q) & (bank_active_q ? dma_wr_en_w : core_rd_en_w);
    assign sram_a_wen_o  = (~swap_quiescent_q) & (bank_active_q ? dma_wr_en_w : 1'b0);
    assign sram_a_ren_o  = (~swap_quiescent_q) & (bank_active_q ? 1'b0        : core_rd_en_w);
    assign sram_a_addr_o = bank_active_q ? dma_wr_addr_lat_q : core_rd_addr_i;
    assign sram_a_din_o  = bank_active_q ? dma_wr_dat_q      : 64'd0;

    assign sram_b_men_o  = (~swap_quiescent_q) & (bank_active_q ? core_rd_en_w : dma_wr_en_w);
    assign sram_b_wen_o  = (~swap_quiescent_q) & (bank_active_q ? 1'b0        : dma_wr_en_w);
    assign sram_b_ren_o  = (~swap_quiescent_q) & (bank_active_q ? core_rd_en_w : 1'b0);
    assign sram_b_addr_o = bank_active_q ? core_rd_addr_i    : dma_wr_addr_lat_q;
    assign sram_b_din_o  = bank_active_q ? 64'd0             : dma_wr_dat_q;

    // Active bank read mux + lossless Q2.14 (<<16) / Q2.30 unpacker
    wire [63:0] act_raw_w   = bank_active_q ? sram_b_dout_i : sram_a_dout_i;
    assign active_dout_raw_o = act_raw_w;

    assign unpack_q30_0_o = q214_mode_i ? $signed({act_raw_w[15:0],  16'h0000}) : $signed(act_raw_w[31:0]);
    assign unpack_q30_1_o = q214_mode_i ? $signed({act_raw_w[31:16], 16'h0000}) : $signed(act_raw_w[63:32]);
    assign unpack_q30_2_o = q214_mode_i ? $signed({act_raw_w[47:32], 16'h0000}) : 32'sd0;
    assign unpack_q30_3_o = q214_mode_i ? $signed({act_raw_w[63:48], 16'h0000}) : 32'sd0;
endmodule
`default_nettype wire
