// =============================================================================
// rtl/odos_gate_axi4_top.sv
// PQMS-ODOS-MTSC-V-MAX-12-SYSTEM-GATEWAY-V4.1 (WORK-ORDER-AG-24 / SYNC-19)
// Causally isolated AMBA AXI4-Lite + AXI4-Stream SoC coprocessor wrapper around
// the frozen 130 nm IHP SG13G2 core `odos_gate_core_v4` (zero extra $mul).
//
// Key Hardware Invariants (REGISTER_T):
//   1. Unconditional Fail-Closed Pin: `veto_pin_o == 1'b1` throughout !rst_ni,
//      active computation, core veto/fault, soft-reset, and egress overrun.
//   2. Causal Store-and-Forward Default (`CTRL[5] cut_through_en = 0`):
//      Stages pre-verdict `out_data_o[0..63]` inside a paired-word 1P 64x64
//      SRAM macro + 8x32 skid ring (< 5% stdcell overhead). Emits 0 words on
//      `m_axis` prior to `S_VERDICT` and 0 words total on VETO (200 cycles);
//      drains 64 sanitized Q2.30 words on PASS (264 cycles @ 0 stalls) with
//      full arbitrary `m_axis_tready` backpressure immunity.
//   3. Speculative Cut-Through DMA Mode (`CTRL[5] cut_through_en = 1`):
//      Streams `out_data_o` live (200 cycles) with `m_axis_tuser = veto_pin_o`.
//   4. Write-Once Hardware Policy Lock (`0x04 LOCK`, RW1S):
//      Once `LOCK[0] == 1'b1`, `tier_mode`, `auto_stream_en`, `cut_through_en`,
//      and `soft_rst` are physically frozen until hard pin `rst_ni == 1'b0`.
// =============================================================================
`default_nettype none

/* verilator lint_off DECLFILENAME */
module odos_axi_egress_sram_1p (
    input  wire        clk_i,
    input  wire        men_i,
    input  wire        wen_i,
    input  wire        ren_i,
    input  wire [5:0]  addr_i,
    input  wire [63:0] wdata_i,
    output logic [63:0] rdata_o
);
`ifdef SYNTH_IHP_SG13G2
    wire [63:0] sram_dout_w;
    RM_IHPSG13_1P_64x64_c2_bm_bist u_egress_sram_macro (
        .A_CLK       (clk_i),
        .A_MEN       (men_i),
        .A_WEN       (wen_i),
        .A_REN       (ren_i),
        .A_ADDR      (addr_i),
        .A_DIN       (wdata_i),
        .A_DLY       (1'b1),
        .A_DOUT      (sram_dout_w),
        .A_BM        ({64{wen_i}}),
        .A_BIST_CLK  (1'b0),
        .A_BIST_EN   (1'b0),
        .A_BIST_MEN  (1'b0),
        .A_BIST_WEN  (1'b0),
        .A_BIST_REN  (1'b0),
        .A_BIST_ADDR (6'd0),
        .A_BIST_DIN  (64'd0),
        .A_BIST_BM   (64'd0)
    );
    assign rdata_o = sram_dout_w;
`else
    logic [63:0] mem_q [0:63];
    always_ff @(posedge clk_i) begin
        if (men_i) begin
            if (wen_i) begin
                mem_q[addr_i] <= wdata_i;
            end else if (ren_i) begin
                rdata_o <= mem_q[addr_i];
            end
        end
    end
`endif
endmodule
/* verilator lint_on DECLFILENAME */

module odos_gate_axi4_top #(
    parameter int AXIL_ADDR_WIDTH = 6
) (
    input  wire                        clk_i,
    input  wire                        rst_ni,

    // AMBA AXI4-Lite Slave Control / Status / Telemetry Interface (32-bit)
    input  wire [AXIL_ADDR_WIDTH-1:0]  s_axil_awaddr,
    input  wire [2:0]                  s_axil_awprot,
    input  wire                        s_axil_awvalid,
    output logic                       s_axil_awready,
    input  wire [31:0]                 s_axil_wdata,
    input  wire [3:0]                  s_axil_wstrb,
    input  wire                        s_axil_wvalid,
    output logic                       s_axil_wready,
    output logic [1:0]                 s_axil_bresp,
    output logic                       s_axil_bvalid,
    input  wire                        s_axil_bready,
    input  wire [AXIL_ADDR_WIDTH-1:0]  s_axil_araddr,
    input  wire [2:0]                  s_axil_arprot,
    input  wire                        s_axil_arvalid,
    output logic                       s_axil_arready,
    output logic [31:0]                s_axil_rdata,
    output logic [1:0]                 s_axil_rresp,
    output logic                       s_axil_rvalid,
    input  wire                        s_axil_rready,

    // AMBA AXI4-Stream Slave Ingress (64 x Q2.30 = 256 B)
    input  wire [31:0]                 s_axis_tdata,
    input  wire                        s_axis_tvalid,
    output logic                       s_axis_tready,
    input  wire                        s_axis_tlast,

    // AMBA AXI4-Stream Master Egress (64 x Sanitized Q2.30 = 256 B)
    output logic [31:0]                m_axis_tdata,
    output logic                       m_axis_tvalid,
    input  wire                        m_axis_tready,
    output logic                       m_axis_tlast,
    output logic                       m_axis_tuser,

    // Out-of-Band Physical Hardware Interlock & Interrupt Pins
    output logic                       veto_pin_o,
    output logic                       irq_done_o,
    output logic                       irq_veto_o
);

    // -------------------------------------------------------------------------
    // Register Offset Map (Word-Aligned: addr[5:2])
    // -------------------------------------------------------------------------
    localparam logic [3:0] ADDR_CTRL        = 4'h0; // 0x00 (RW)
    localparam logic [3:0] ADDR_LOCK        = 4'h1; // 0x04 (RW1S)
    localparam logic [3:0] ADDR_STATUS      = 4'h2; // 0x08 (RO)
    localparam logic [3:0] ADDR_NORM_SQ     = 4'h3; // 0x0C (RO)
    localparam logic [3:0] ADDR_RCF_RAW     = 4'h4; // 0x10 (RO)
    localparam logic [3:0] ADDR_G3_OVERLAP  = 4'h5; // 0x14 (RO)
    localparam logic [3:0] ADDR_DELTA_E_RAW = 4'h6; // 0x18 (RO)
    localparam logic [3:0] ADDR_BLEED_POST  = 4'h7; // 0x1C (RO)
    localparam logic [3:0] ADDR_CYCLE_CNT   = 4'h8; // 0x20 (RO)

    typedef enum logic [1:0] {
        EG_IDLE        = 2'd0,
        EG_CAPTURE     = 2'd1,
        EG_DRAIN       = 2'd2,
        EG_CUT_THROUGH = 2'd3
    } eg_state_e;

    function automatic logic [31:0] apply_wstrb32(
        input logic [31:0] cur_val,
        input logic [31:0] wr_val,
        input logic [3:0]  wstrb
    );
        logic [31:0] res;
        begin
            res[7:0]   = wstrb[0] ? wr_val[7:0]   : cur_val[7:0];
            res[15:8]  = wstrb[1] ? wr_val[15:8]  : cur_val[15:8];
            res[23:16] = wstrb[2] ? wr_val[23:16] : cur_val[23:16];
            res[31:24] = wstrb[3] ? wr_val[31:24] : cur_val[31:24];
            apply_wstrb32 = res;
        end
    endfunction

    // Intentionally unused AXI4-Lite sub-word alignment & protection bits
    wire unused_axil_bits_w = &{
        1'b0,
        s_axil_awaddr[1:0],
        s_axil_araddr[1:0],
        s_axil_awprot,
        s_axil_arprot,
        1'b0
    };
    generate
        if (AXIL_ADDR_WIDTH > 6) begin : gen_unused_hi_addr
            wire unused_axil_hi_w = &{1'b0, s_axil_awaddr[AXIL_ADDR_WIDTH-1:6], s_axil_araddr[AXIL_ADDR_WIDTH-1:6]};
        end
    endgenerate

    // -------------------------------------------------------------------------
    // Policy, Lock, AXI4-Lite Skid & Telemetry Registers
    // -------------------------------------------------------------------------
    logic        locked_q;
    logic [1:0]  tier_mode_q;
    logic        auto_stream_en_q;
    logic        cut_through_en_q;
    logic        soft_rst_q;

    logic        aw_pend_q;
    logic [3:0]  aw_word_addr_q;
    logic        w_pend_q;
    logic [31:0] w_data_q;
    logic [3:0]  w_strb_q;

    eg_state_e   eg_state_q;
    logic [5:0]  ing_beat_cnt_q;
    logic        lat_tlast_err_q;

    logic [31:0] even_word_q;
    logic        sram_preread_req_q;
    logic        sram_rd_inflight_q;
    logic [5:0]  sram_rd_pair_ptr_q;

    logic [31:0] skid_mem_q [0:7];
    logic [2:0]  skid_wr_ptr_q;
    logic [2:0]  skid_rd_ptr_q;
    logic [3:0]  skid_cnt_q;
    logic [5:0]  eg_words_sent_q;
    logic        ct_core_done_seen_q;
    logic        egress_overrun_fault_q;

    logic        done_sticky_q;
    logic        lat_gate_pass_q;
    logic        lat_norm_fault_q;
    logic        lat_pure_g3_q;
    logic        lat_mode_fault_q;
    logic [15:0] tx_counter_q;
    logic [15:0] lat_cycle_count_q;
    logic signed [31:0] lat_norm_sq_q;
    logic signed [31:0] lat_rcf_raw_q;
    logic signed [31:0] lat_g3_overlap_q;
    logic signed [31:0] lat_delta_e_raw_q;
    logic signed [31:0] lat_bleed_post_q;

    // -------------------------------------------------------------------------
    // Frozen Stage-3 Core Signals (`odos_gate_core_v4`)
    // -------------------------------------------------------------------------
    wire               core_rst_ni = rst_ni & (~soft_rst_q);
    logic              core_start_w;
    wire               core_in_valid_w;
    wire               core_in_ready_o;
    wire signed [31:0] core_in_data_w = $signed(s_axis_tdata);

    wire               core_busy_o;
    wire               core_done_o;
    wire               core_gate_pass_o;
    wire               core_veto_pin_o;
    wire               core_norm_fault_o;
    wire               core_pure_g3_o;
    wire               core_mode_fault_o;
    wire               core_out_valid_o;
    wire [5:0]         core_out_idx_o;
    wire signed [31:0] core_out_data_o;
    wire [15:0]        core_cycle_count_o;
    wire signed [31:0] core_norm_sq_o;
    wire signed [31:0] core_rcf_raw_o;
    wire signed [31:0] core_g3_overlap_o;
    wire signed [31:0] core_delta_e_raw_o;
    wire signed [31:0] core_bleed_post_o;

    odos_gate_core_v4 u_core (
        .clk_i               (clk_i),
        .rst_ni              (core_rst_ni),
        .start_i             (core_start_w),
        .tier_mode_i         (tier_mode_q),
        .in_valid_i          (core_in_valid_w),
        .in_ready_o          (core_in_ready_o),
        .in_data_i           (core_in_data_w),
        .busy_o              (core_busy_o),
        .done_o              (core_done_o),
        .gate_pass_o         (core_gate_pass_o),
        .veto_pin_o          (core_veto_pin_o),
        .norm_fault_o        (core_norm_fault_o),
        .pure_g3_collision_o (core_pure_g3_o),
        .mode_fault_o        (core_mode_fault_o),
        .out_valid_o         (core_out_valid_o),
        .out_idx_o           (core_out_idx_o),
        .out_data_o          (core_out_data_o),
        .cycle_count_o       (core_cycle_count_o),
        .norm_sq_o           (core_norm_sq_o),
        .rcf_raw_o           (core_rcf_raw_o),
        .g3_overlap_o        (core_g3_overlap_o),
        .delta_e_raw_o       (core_delta_e_raw_o),
        .bleed_post_o        (core_bleed_post_o)
    );

    // -------------------------------------------------------------------------
    // Paired-Word 1P Egress Staging SRAM (Zero R/W Port Collisions)
    // -------------------------------------------------------------------------
    wire        sram_wr_en_w = (eg_state_q == EG_CAPTURE) && core_out_valid_o && core_out_idx_o[0];
    wire        sram_drain_can_rd_w = (eg_state_q == EG_DRAIN)
                                   && (sram_rd_pair_ptr_q < 6'd32)
                                   && ((skid_cnt_q + (sram_rd_inflight_q ? 4'd2 : 4'd0)) <= 4'd6);
    wire        sram_verdict_rd_w = (eg_state_q == EG_CAPTURE)
                                 && core_done_o
                                 && core_gate_pass_o
                                 && (!core_veto_pin_o);
    wire        sram_rd_en_w = sram_preread_req_q | sram_verdict_rd_w | sram_drain_can_rd_w;
    wire        sram_men_w   = sram_wr_en_w | sram_rd_en_w;

    logic [5:0] sram_addr_w;
    always_comb begin
        if (sram_wr_en_w) begin
            sram_addr_w = {1'b0, core_out_idx_o[5:1]};
        end else if (sram_preread_req_q) begin
            sram_addr_w = 6'd0;
        end else if (sram_verdict_rd_w) begin
            sram_addr_w = 6'd1;
        end else begin
            sram_addr_w = sram_rd_pair_ptr_q;
        end
    end

    wire [63:0] sram_wdata_w = {$unsigned(core_out_data_o), even_word_q};
    wire [63:0] sram_rdata_w;

    odos_axi_egress_sram_1p u_egress_sram (
        .clk_i   (clk_i),
        .men_i   (sram_men_w),
        .wen_i   (sram_wr_en_w),
        .ren_i   (sram_rd_en_w & (~sram_wr_en_w)),
        .addr_i  (sram_addr_w),
        .wdata_i (sram_wdata_w),
        .rdata_o (sram_rdata_w)
    );

    // -------------------------------------------------------------------------
    // AXI4-Lite Handshake & Write/Read Decode
    // -------------------------------------------------------------------------
    wire b_space_w = (!s_axil_bvalid) || s_axil_bready;
    assign s_axil_awready = (!aw_pend_q) && b_space_w;
    assign s_axil_wready  = (!w_pend_q)  && b_space_w;
    assign s_axil_arready = (!s_axil_rvalid) || s_axil_rready;

    wire aw_take_w = s_axil_awvalid && s_axil_awready;
    wire w_take_w  = s_axil_wvalid  && s_axil_wready;
    wire axil_wr_fire_w = (aw_pend_q || aw_take_w) && (w_pend_q || w_take_w) && b_space_w;

    wire [3:0]  wr_word_addr_w = aw_pend_q ? aw_word_addr_q : s_axil_awaddr[5:2];
    wire [31:0] wr_data_eff_w  = w_pend_q  ? w_data_q       : s_axil_wdata;
    wire [3:0]  wr_strb_eff_w  = w_pend_q  ? w_strb_q       : s_axil_wstrb;

    wire [31:0] ctrl_cur_w = {
        26'd0,
        cut_through_en_q,
        auto_stream_en_q,
        tier_mode_q,
        2'b00
    };
    wire [31:0] ctrl_merged_w = apply_wstrb32(ctrl_cur_w, wr_data_eff_w, wr_strb_eff_w);
    wire unused_ctrl_bits_w = &{1'b0, ctrl_merged_w[31:6], ctrl_merged_w[1:0]};

    wire ctrl_wr_w         = axil_wr_fire_w && (wr_word_addr_w == ADDR_CTRL);
    wire lock_wr_w         = axil_wr_fire_w && (wr_word_addr_w == ADDR_LOCK);
    wire axil_start_req_w  = ctrl_wr_w && wr_strb_eff_w[0] && wr_data_eff_w[0];
    wire axil_sreset_req_w = ctrl_wr_w && (!locked_q) && wr_strb_eff_w[0] && wr_data_eff_w[1];
    wire axil_clr_irq_w    = ctrl_wr_w && wr_strb_eff_w[0] && wr_data_eff_w[6];

    wire wrapper_busy_w    = core_busy_o || (eg_state_q != EG_IDLE) || soft_rst_q;
    wire can_launch_w      = (!wrapper_busy_w) && (!core_done_o) && (!axil_sreset_req_w);
    wire stream_autostart_w = auto_stream_en_q && s_axis_tvalid;

    assign core_start_w    = can_launch_w && (axil_start_req_w || stream_autostart_w);
    assign s_axis_tready   = core_in_ready_o
                          && ((eg_state_q == EG_CAPTURE) || (eg_state_q == EG_CUT_THROUGH));
    assign core_in_valid_w = s_axis_tvalid && s_axis_tready;

    // Out-of-band fail-closed pin (purely registered sources; 1'b1 on reset/busy/veto/fault)
    assign veto_pin_o   = core_veto_pin_o | egress_overrun_fault_q | soft_rst_q | unused_axil_bits_w;

    assign m_axis_tvalid = ((eg_state_q == EG_DRAIN) || (eg_state_q == EG_CUT_THROUGH))
                        && (skid_cnt_q != 4'd0);
    assign m_axis_tdata  = skid_mem_q[skid_rd_ptr_q];
    assign m_axis_tlast  = m_axis_tvalid && (eg_words_sent_q == 6'd63);
    assign m_axis_tuser  = veto_pin_o;

    wire axis_pop_w = m_axis_tvalid && m_axis_tready;

    wire [31:0] status_word_w = {
        tx_counter_q,
        6'd0,
        lat_tlast_err_q,
        egress_overrun_fault_q,
        lat_pure_g3_q,
        locked_q,
        lat_mode_fault_q,
        lat_norm_fault_q,
        veto_pin_o,
        lat_gate_pass_q && (!wrapper_busy_w) && (!egress_overrun_fault_q),
        done_sticky_q,
        wrapper_busy_w
    };

    logic [31:0] axil_rd_mux_w;
    always_comb begin
        case (s_axil_araddr[5:2])
            ADDR_CTRL:        axil_rd_mux_w = ctrl_cur_w;
            ADDR_LOCK:        axil_rd_mux_w = {31'd0, locked_q};
            ADDR_STATUS:      axil_rd_mux_w = status_word_w;
            ADDR_NORM_SQ:     axil_rd_mux_w = $unsigned(lat_norm_sq_q);
            ADDR_RCF_RAW:     axil_rd_mux_w = $unsigned(lat_rcf_raw_q);
            ADDR_G3_OVERLAP:  axil_rd_mux_w = $unsigned(lat_g3_overlap_q);
            ADDR_DELTA_E_RAW: axil_rd_mux_w = $unsigned(lat_delta_e_raw_q);
            ADDR_BLEED_POST:  axil_rd_mux_w = $unsigned(lat_bleed_post_q);
            ADDR_CYCLE_CNT:   axil_rd_mux_w = {16'd0, lat_cycle_count_q};
            default:          axil_rd_mux_w = 32'd0;
        endcase
    end

    // -------------------------------------------------------------------------
    // Sequential Control, AXI4-Lite Slave & Egress Skid Ring State Machine
    // -------------------------------------------------------------------------
    always_ff @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni) begin
            locked_q               <= 1'b0;
            tier_mode_q            <= 2'b00;
            auto_stream_en_q       <= 1'b0;
            cut_through_en_q       <= 1'b0;
            soft_rst_q             <= 1'b0;
            aw_pend_q              <= 1'b0;
            aw_word_addr_q         <= 4'd0;
            w_pend_q               <= 1'b0;
            w_data_q               <= 32'd0;
            w_strb_q               <= 4'd0;
            s_axil_bvalid          <= 1'b0;
            s_axil_bresp           <= 2'b00;
            s_axil_rvalid          <= 1'b0;
            s_axil_rresp           <= 2'b00;
            s_axil_rdata           <= 32'd0;
            eg_state_q             <= EG_IDLE;
            ing_beat_cnt_q         <= 6'd0;
            lat_tlast_err_q        <= 1'b0;
            even_word_q            <= 32'd0;
            sram_preread_req_q     <= 1'b0;
            sram_rd_inflight_q     <= 1'b0;
            sram_rd_pair_ptr_q     <= 6'd0;
            for (int k = 0; k < 8; k++) begin
                skid_mem_q[k] <= 32'd0;
            end
            skid_wr_ptr_q          <= 3'd0;
            skid_rd_ptr_q          <= 3'd0;
            skid_cnt_q             <= 4'd0;
            eg_words_sent_q        <= 6'd0;
            ct_core_done_seen_q    <= 1'b0;
            egress_overrun_fault_q <= 1'b0;
            done_sticky_q          <= 1'b0;
            lat_gate_pass_q        <= 1'b0;
            lat_norm_fault_q       <= 1'b0;
            lat_pure_g3_q          <= 1'b0;
            lat_mode_fault_q       <= 1'b0;
            tx_counter_q           <= 16'd0;
            lat_cycle_count_q      <= 16'd0;
            lat_norm_sq_q          <= 32'sd0;
            lat_rcf_raw_q          <= 32'sd0;
            lat_g3_overlap_q       <= 32'sd0;
            lat_delta_e_raw_q      <= 32'sd0;
            lat_bleed_post_q       <= 32'sd0;
            irq_done_o             <= 1'b0;
            irq_veto_o             <= 1'b0;
        end else begin
            irq_done_o <= 1'b0;
            irq_veto_o <= 1'b0;
            soft_rst_q <= axil_sreset_req_w;

            // 1. AXI4-Lite Write Skid & Response Channel
            if (aw_take_w && (!axil_wr_fire_w)) begin
                aw_pend_q      <= 1'b1;
                aw_word_addr_q <= s_axil_awaddr[5:2];
            end else if (axil_wr_fire_w) begin
                aw_pend_q <= 1'b0;
            end

            if (w_take_w && (!axil_wr_fire_w)) begin
                w_pend_q <= 1'b1;
                w_data_q <= s_axil_wdata;
                w_strb_q <= s_axil_wstrb;
            end else if (axil_wr_fire_w) begin
                w_pend_q <= 1'b0;
            end

            if (axil_wr_fire_w) begin
                s_axil_bvalid <= 1'b1;
                s_axil_bresp  <= 2'b00;
            end else if (s_axil_bvalid && s_axil_bready) begin
                s_axil_bvalid <= 1'b0;
            end

            // Hardware Write-Once Lock (RW1S: cleared ONLY by rst_ni == 1'b0)
            if (lock_wr_w && wr_strb_eff_w[0] && wr_data_eff_w[0]) begin
                locked_q <= 1'b1;
            end

            if (ctrl_wr_w && (!locked_q) && (!wrapper_busy_w)) begin
                tier_mode_q      <= ctrl_merged_w[3:2];
                auto_stream_en_q <= ctrl_merged_w[4];
                cut_through_en_q <= ctrl_merged_w[5];
            end

            if (axil_clr_irq_w) begin
                done_sticky_q <= 1'b0;
            end

            // 2. AXI4-Lite Read Channel
            if (s_axil_arvalid && s_axil_arready) begin
                s_axil_rvalid <= 1'b1;
                s_axil_rresp  <= 2'b00;
                s_axil_rdata  <= axil_rd_mux_w;
            end else if (s_axil_rvalid && s_axil_rready) begin
                s_axil_rvalid <= 1'b0;
            end

            // 3. Soft-Reset (only reachable when locked_q == 1'b0)
            if (axil_sreset_req_w) begin
                eg_state_q             <= EG_IDLE;
                ing_beat_cnt_q         <= 6'd0;
                lat_tlast_err_q        <= 1'b0;
                sram_preread_req_q     <= 1'b0;
                sram_rd_inflight_q     <= 1'b0;
                sram_rd_pair_ptr_q     <= 6'd0;
                skid_wr_ptr_q          <= 3'd0;
                skid_rd_ptr_q          <= 3'd0;
                skid_cnt_q             <= 4'd0;
                eg_words_sent_q        <= 6'd0;
                ct_core_done_seen_q    <= 1'b0;
                egress_overrun_fault_q <= 1'b0;
                done_sticky_q          <= 1'b0;
                lat_gate_pass_q        <= 1'b0;
            end else begin
                // Ingress Beat & TLAST Diagnostic Tracking
                if (core_start_w) begin
                    ing_beat_cnt_q         <= 6'd0;
                    lat_tlast_err_q        <= 1'b0;
                    done_sticky_q          <= 1'b0;
                    lat_gate_pass_q        <= 1'b0;
                    egress_overrun_fault_q <= 1'b0;
                end else if (core_in_valid_w) begin
                    if ((ing_beat_cnt_q == 6'd63) != s_axis_tlast) begin
                        lat_tlast_err_q <= 1'b1;
                    end
                    ing_beat_cnt_q <= ing_beat_cnt_q + 6'd1;
                end

                // Core Verdict & Scalar Telemetry Capture (`S_VERDICT` completion)
                if (core_done_o) begin
                    done_sticky_q     <= 1'b1;
                    lat_gate_pass_q   <= core_gate_pass_o && (!core_veto_pin_o);
                    lat_norm_fault_q  <= core_norm_fault_o;
                    lat_pure_g3_q     <= core_pure_g3_o;
                    lat_mode_fault_q  <= core_mode_fault_o;
                    tx_counter_q      <= tx_counter_q + 16'd1;
                    lat_cycle_count_q <= core_cycle_count_o;
                    lat_norm_sq_q     <= core_norm_sq_o;
                    lat_rcf_raw_q     <= core_rcf_raw_o;
                    lat_g3_overlap_q  <= core_g3_overlap_o;
                    lat_delta_e_raw_q <= core_delta_e_raw_o;
                    lat_bleed_post_q  <= core_bleed_post_o;
                    irq_done_o        <= 1'b1;
                    irq_veto_o        <= (!core_gate_pass_o) || core_veto_pin_o || egress_overrun_fault_q;
                end

                // Egress State Machine
                case (eg_state_q)
                    EG_IDLE: begin
                        sram_preread_req_q  <= 1'b0;
                        sram_rd_inflight_q  <= 1'b0;
                        skid_cnt_q          <= 4'd0;
                        skid_wr_ptr_q       <= 3'd0;
                        skid_rd_ptr_q       <= 3'd0;
                        eg_words_sent_q     <= 6'd0;
                        ct_core_done_seen_q <= 1'b0;
                        if (core_start_w) begin
                            eg_state_q <= cut_through_en_q ? EG_CUT_THROUGH : EG_CAPTURE;
                        end
                    end

                    EG_CAPTURE: begin
                        if (core_out_valid_o) begin
                            if (!core_out_idx_o[0]) begin
                                even_word_q <= $unsigned(core_out_data_o);
                            end else if (core_out_idx_o == 6'd63) begin
                                sram_preread_req_q <= 1'b1;
                            end
                        end else if (sram_preread_req_q) begin
                            sram_preread_req_q <= 1'b0;
                        end

                        if (core_done_o) begin
                            if (core_gate_pass_o && (!core_veto_pin_o)) begin
                                // `sram_rdata_w` holds pre-fetched W_0 = {v2[1], v2[0]}
                                skid_mem_q[0]      <= sram_rdata_w[31:0];
                                skid_mem_q[1]      <= sram_rdata_w[63:32];
                                skid_wr_ptr_q      <= 3'd2;
                                skid_rd_ptr_q      <= 3'd0;
                                skid_cnt_q         <= 4'd2;
                                eg_words_sent_q    <= 6'd0;
                                sram_rd_pair_ptr_q <= 6'd2;
                                sram_rd_inflight_q <= 1'b1;
                                eg_state_q         <= EG_DRAIN;
                            end else begin
                                skid_cnt_q         <= 4'd0;
                                sram_rd_inflight_q <= 1'b0;
                                eg_state_q         <= EG_IDLE;
                            end
                        end
                    end

                    EG_DRAIN: begin
                        if (sram_rd_inflight_q) begin
                            skid_mem_q[skid_wr_ptr_q]         <= sram_rdata_w[31:0];
                            skid_mem_q[skid_wr_ptr_q + 3'd1]  <= sram_rdata_w[63:32];
                            skid_wr_ptr_q                     <= skid_wr_ptr_q + 3'd2;
                        end

                        if (sram_drain_can_rd_w) begin
                            sram_rd_inflight_q <= 1'b1;
                            sram_rd_pair_ptr_q <= sram_rd_pair_ptr_q + 6'd1;
                        end else begin
                            sram_rd_inflight_q <= 1'b0;
                        end

                        if (axis_pop_w) begin
                            skid_rd_ptr_q   <= skid_rd_ptr_q + 3'd1;
                            eg_words_sent_q <= eg_words_sent_q + 6'd1;
                        end

                        skid_cnt_q <= skid_cnt_q
                                    + (sram_rd_inflight_q ? 4'd2 : 4'd0)
                                    - (axis_pop_w ? 4'd1 : 4'd0);

                        if (axis_pop_w && (eg_words_sent_q == 6'd63)) begin
                            eg_state_q         <= EG_IDLE;
                            sram_rd_inflight_q <= 1'b0;
                        end
                    end

                    EG_CUT_THROUGH: begin
                        ct_core_done_seen_q <= ct_core_done_seen_q | core_done_o;
                        if (core_out_valid_o && (skid_cnt_q == 4'd8) && (!axis_pop_w)) begin
                            egress_overrun_fault_q <= 1'b1;
                            irq_veto_o             <= 1'b1;
                            skid_cnt_q             <= 4'd0;
                            eg_state_q             <= EG_IDLE;
                        end else begin
                            if (core_out_valid_o) begin
                                skid_mem_q[skid_wr_ptr_q] <= $unsigned(core_out_data_o);
                                skid_wr_ptr_q             <= skid_wr_ptr_q + 3'd1;
                            end
                            if (axis_pop_w) begin
                                skid_rd_ptr_q   <= skid_rd_ptr_q + 3'd1;
                                eg_words_sent_q <= eg_words_sent_q + 6'd1;
                            end
                            skid_cnt_q <= skid_cnt_q
                                        + (core_out_valid_o ? 4'd1 : 4'd0)
                                        - (axis_pop_w ? 4'd1 : 4'd0);

                            if ((ct_core_done_seen_q || core_done_o)
                                && ((axis_pop_w && (eg_words_sent_q == 6'd63))
                                    || ((skid_cnt_q == 4'd0) && (!core_out_valid_o)))) begin
                                eg_state_q <= EG_IDLE;
                            end
                        end
                    end

                    default: begin
                        eg_state_q <= EG_IDLE;
                    end
                endcase
            end
        end
    end

endmodule
`default_nettype wire
