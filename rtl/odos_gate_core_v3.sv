// =============================================================================
// rtl/odos_gate_core_v3.sv
// PQMS-ODOS-MTSC-V-MAX-12-RTL-CORE-V3.0-ALPHA (WORK-ORDER-AG-20 / SYNC-15)
// Loop-free 3-MAC inter-state folded Q2.30 S^63 coprocessor (9 -> 3 multipliers)
// with transaction-latched 2-bit multi-tier domain strap and 2'b11 glitch trap.
// =============================================================================
`timescale 1ns/1ps
`default_nettype none

module odos_gate_core_v3 #(
    parameter L_ROM_HEX  = "rtl/rom/l_vec_q2_30.hex",
    parameter G3_ROM_HEX = "rtl/rom/g3_vec_q2_30.hex"
) (
    input  wire               clk_i,
    input  wire               rst_ni,
    input  wire               start_i,
    input  wire        [1:0]  tier_mode_i,
    input  wire               in_valid_i,
    output logic              in_ready_o,
    input  wire signed [31:0] in_data_i,

    output logic              busy_o,
    output logic              done_o,
    output logic              gate_pass_o,
    output logic              veto_pin_o,
    output logic              norm_fault_o,
    output logic              pure_g3_collision_o,
    output logic              mode_fault_o,

    output logic              out_valid_o,
    output logic       [5:0]  out_idx_o,
    output logic signed [31:0] out_data_o,

    output logic       [15:0] cycle_count_o,
    output logic signed [31:0] norm_sq_o,
    output logic signed [31:0] rcf_raw_o,
    output logic signed [31:0] g3_overlap_o,
    output logic signed [31:0] delta_e_raw_o,
    output logic signed [31:0] bleed_post_o
);

    localparam logic signed [31:0] ONE_Q2_30            = 32'sh4000_0000; // 1073741824 (1.0)
    localparam logic signed [31:0] RCF_TIER0_Q2_30      = 32'sh3CCC_CCCD; // 1020054733 (0.95)
    localparam logic signed [31:0] RCF_TIER1_Q2_30      = 32'sh3999_999A; //  966367642 (0.90)
    localparam logic signed [31:0] RCF_TIER2_Q2_30      = 32'sh3F5C_28F6; // 1063004406 (0.99)
    localparam logic signed [31:0] DE_TIER01_Q2_30      = 32'sh0333_3333; //   53687091 (0.05)
    localparam logic signed [31:0] DE_TIER2_Q2_30       = 32'sh00A3_D70A; //   10737418 (0.01)
    localparam logic signed [31:0] NORM_MIN_Q2_30       = 32'sh3FEF_9DB2; // 1072668082 (0.999)
    localparam logic signed [31:0] NORM_MAX_Q2_30       = 32'sh4010_624E; // 1074815566 (1.001)
    localparam logic signed [31:0] STRIP_NORM_MIN_Q2_30 = 32'sh0000_0432; //       1074 (~1e-6)
    localparam logic signed [31:0] BLEED_CEIL_Q2_30     = 32'sh0000_0020; //         32 LSB
    localparam logic signed [31:0] INT32_MIN_Q2_30      = 32'sh8000_0000; // -2^31
    localparam logic signed [31:0] INT32_MAX_Q2_30      = 32'sh7FFF_FFFF; //  2^31 - 1

    localparam logic [2:0] S_IDLE     = 3'd0;
    localparam logic [2:0] S_LOAD_DOT = 3'd1;
    localparam logic [2:0] S_EVAL_RAW = 3'd2;
    localparam logic [2:0] S_STRIP_P1 = 3'd3;
    localparam logic [2:0] S_LATCH_P2 = 3'd4;
    localparam logic [2:0] S_STRIP_P2 = 3'd5;
    localparam logic [2:0] S_VERDICT  = 3'd6;

    logic [2:0] state_q;
    logic [5:0] idx_q;
    logic [1:0] tier_latched_q;
    logic       norm_ok_q;

    logic signed [31:0] l_rom  [0:63];
    logic signed [31:0] g3_rom [0:63];
    logic signed [31:0] v_buf  [0:63];

    initial begin
        $readmemh(L_ROM_HEX,  l_rom);
        $readmemh(G3_ROM_HEX, g3_rom);
    end

    logic signed [71:0] acc_norm_sq_q;
    logic signed [71:0] acc_dot_l_q;
    logic signed [71:0] acc_dot_g3_q;
    logic signed [71:0] acc_dot_g3_p2_q;
    logic signed [71:0] acc_strip_norm_sq_q;
    logic signed [71:0] acc_bleed_post_q;
    logic signed [31:0] dot_g3_p1_q;
    logic signed [31:0] dot_g3_p2_q;

    function automatic logic signed [31:0] q60_to_q30(input logic signed [71:0] acc);
        logic signed [71:0] rounded;
        logic signed [71:0] shifted;
        begin
            rounded = acc + 72'sd536870912;
            shifted = rounded >>> 30;
            if (shifted > 72'sd2147483647) begin
                q60_to_q30 = INT32_MAX_Q2_30;
            end else if (shifted < -72'sd2147483648) begin
                q60_to_q30 = INT32_MIN_Q2_30;
            end else begin
                q60_to_q30 = shifted[31:0];
            end
        end
    endfunction

    function automatic logic signed [31:0] sat_sub_q30(
        input logic signed [31:0] a,
        input logic signed [31:0] b
    );
        logic signed [32:0] diff;
        begin
            diff = $signed({a[31], a}) - $signed({b[31], b});
            if (diff > 33'sd2147483647) begin
                sat_sub_q30 = INT32_MAX_Q2_30;
            end else if (diff < -33'sd2147483648) begin
                sat_sub_q30 = INT32_MIN_Q2_30;
            end else begin
                sat_sub_q30 = diff[31:0];
            end
        end
    endfunction

    function automatic logic signed [31:0] abs_sat_q30(input logic signed [31:0] x);
        begin
            if (x == INT32_MIN_Q2_30) begin
                abs_sat_q30 = INT32_MAX_Q2_30;
            end else if (x[31]) begin
                abs_sat_q30 = -x;
            end else begin
                abs_sat_q30 = x;
            end
        end
    endfunction

    function automatic logic signed [31:0] half_sum_q30(
        input logic signed [31:0] a,
        input logic signed [31:0] b
    );
        begin
            half_sum_q30 = (a >>> 1) + (b >>> 1) + $signed({31'd0, (a[0] & b[0])});
        end
    endfunction

    wire signed [31:0] l_rom_w    = l_rom[idx_q];
    wire signed [31:0] g3_rom_w   = g3_rom[idx_q];
    wire signed [31:0] v_buf_w    = v_buf[idx_q];
    wire signed [31:0] dot_l_ev_w = q60_to_q30(acc_dot_l_q);

    // -------------------------------------------------------------------------
    // Acyclic Two-Rank 3-MAC Folding Network (Strictly 3 Signed 32x32 $mul)
    // Rank 1: MUL0 depends ONLY on registered state, primary inputs, and ROM.
    // -------------------------------------------------------------------------
    logic signed [31:0] m0_a;
    logic signed [31:0] m0_b;

    always_comb begin
        m0_a = 32'sd0;
        m0_b = 32'sd0;
        case (state_q)
            S_LOAD_DOT: begin
                m0_a = in_data_i;
                m0_b = in_data_i;
            end
            S_EVAL_RAW: begin
                m0_a = dot_l_ev_w;
                m0_b = dot_l_ev_w;
            end
            S_STRIP_P1: begin
                m0_a = dot_g3_p1_q;
                m0_b = g3_rom_w;
            end
            S_STRIP_P2: begin
                m0_a = dot_g3_p2_q;
                m0_b = g3_rom_w;
            end
            default: begin
                m0_a = 32'sd0;
                m0_b = 32'sd0;
            end
        endcase
    end

    wire signed [63:0] m0_prod_w = $signed({{32{m0_a[31]}}, m0_a}) * $signed({{32{m0_b[31]}}, m0_b});
    wire signed [31:0] m0_q30_w  = q60_to_q30({{8{m0_prod_w[63]}}, m0_prod_w});
    wire signed [31:0] v_step_w  = sat_sub_q30(v_buf_w, m0_q30_w);

    // Rank 2: MUL1 & MUL2 consume registered/ROM operands or downstream v_step_w.
    logic signed [31:0] m1_a;
    logic signed [31:0] m1_b;
    logic signed [31:0] m2_a;
    logic signed [31:0] m2_b;

    always_comb begin
        m1_a = 32'sd0;
        m1_b = 32'sd0;
        m2_a = 32'sd0;
        m2_b = 32'sd0;
        case (state_q)
            S_LOAD_DOT: begin
                m1_a = in_data_i;
                m1_b = l_rom_w;
                m2_a = in_data_i;
                m2_b = g3_rom_w;
            end
            S_STRIP_P1: begin
                m1_a = v_step_w;
                m1_b = g3_rom_w;
            end
            S_STRIP_P2: begin
                m1_a = v_step_w;
                m1_b = v_step_w;
                m2_a = v_step_w;
                m2_b = g3_rom_w;
            end
            default: begin
                m1_a = 32'sd0;
                m1_b = 32'sd0;
                m2_a = 32'sd0;
                m2_b = 32'sd0;
            end
        endcase
    end

    wire signed [63:0] m1_prod_w = $signed({{32{m1_a[31]}}, m1_a}) * $signed({{32{m1_b[31]}}, m1_b});
    wire signed [63:0] m2_prod_w = $signed({{32{m2_a[31]}}, m2_a}) * $signed({{32{m2_b[31]}}, m2_b});

    // Raw evaluation & multi-tier threshold selection
    wire signed [31:0] norm_sq_ev_w    = q60_to_q30(acc_norm_sq_q);
    wire signed [31:0] dot_g3_ev_w     = q60_to_q30(acc_dot_g3_q);
    wire signed [31:0] g3_ov_ev_w      = abs_sat_q30(dot_g3_ev_w);
    wire signed [31:0] t1_ev_w         = (m0_q30_w >= ONE_Q2_30) ? 32'sd0 : (ONE_Q2_30 - m0_q30_w);
    wire signed [31:0] t2_ev_w         = (g3_ov_ev_w > ONE_Q2_30) ? ONE_Q2_30 : g3_ov_ev_w;
    wire signed [31:0] delta_e_ev_w    = half_sum_q30(t1_ev_w, t2_ev_w);
    wire               norm_ok_ev_w    = (norm_sq_ev_w >= NORM_MIN_Q2_30) && (norm_sq_ev_w <= NORM_MAX_Q2_30);

    wire signed [31:0] strip_norm_ev_w = q60_to_q30(acc_strip_norm_sq_q);
    wire               pure_g3_ev_w    = (strip_norm_ev_w < STRIP_NORM_MIN_Q2_30);
    wire signed [31:0] bleed_raw_ev_w  = abs_sat_q30(q60_to_q30(acc_bleed_post_q));
    wire signed [31:0] bleed_fin_ev_w  = pure_g3_ev_w ? ONE_Q2_30 : bleed_raw_ev_w;

    logic signed [31:0] rcf_floor_sel_w;
    logic signed [31:0] de_ceil_sel_w;
    logic               tier_glitch_w;

    always_comb begin
        rcf_floor_sel_w = RCF_TIER0_Q2_30;
        de_ceil_sel_w   = DE_TIER01_Q2_30;
        tier_glitch_w   = 1'b0;
        case (tier_latched_q)
            2'b00: begin
                rcf_floor_sel_w = RCF_TIER0_Q2_30;
                de_ceil_sel_w   = DE_TIER01_Q2_30;
            end
            2'b01: begin
                rcf_floor_sel_w = RCF_TIER1_Q2_30;
                de_ceil_sel_w   = DE_TIER01_Q2_30;
            end
            2'b10: begin
                rcf_floor_sel_w = RCF_TIER2_Q2_30;
                de_ceil_sel_w   = DE_TIER2_Q2_30;
            end
            default: begin
                rcf_floor_sel_w = ONE_Q2_30;
                de_ceil_sel_w   = 32'sd0;
                tier_glitch_w   = 1'b1;
            end
        endcase
    end

    wire pass_verdict_w = (!tier_glitch_w)
                        && norm_ok_q
                        && (!pure_g3_ev_w)
                        && (rcf_raw_o >= rcf_floor_sel_w)
                        && (delta_e_raw_o <= de_ceil_sel_w)
                        && (bleed_fin_ev_w <= BLEED_CEIL_Q2_30);

    assign in_ready_o = (state_q == S_LOAD_DOT);
    assign busy_o     = (state_q != S_IDLE);

    // Un-reset 64x32 working vector buffer (maps cleanly to 2,048 DFFE_PP cells)
    always_ff @(posedge clk_i) begin
        if ((state_q == S_LOAD_DOT) && in_valid_i) begin
            v_buf[idx_q] <= in_data_i;
        end else if (state_q == S_STRIP_P1) begin
            v_buf[idx_q] <= v_step_w;
        end
    end

    // Synchronous Fail-Closed Control & Accumulator FSM
    always_ff @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni) begin
            state_q             <= S_IDLE;
            idx_q               <= 6'd0;
            tier_latched_q      <= 2'b00;
            norm_ok_q           <= 1'b0;
            acc_norm_sq_q       <= 72'sd0;
            acc_dot_l_q         <= 72'sd0;
            acc_dot_g3_q        <= 72'sd0;
            acc_dot_g3_p2_q     <= 72'sd0;
            acc_strip_norm_sq_q <= 72'sd0;
            acc_bleed_post_q    <= 72'sd0;
            dot_g3_p1_q         <= 32'sd0;
            dot_g3_p2_q         <= 32'sd0;
            done_o              <= 1'b0;
            gate_pass_o         <= 1'b0;
            veto_pin_o          <= 1'b1;
            norm_fault_o        <= 1'b0;
            pure_g3_collision_o <= 1'b0;
            mode_fault_o        <= 1'b0;
            out_valid_o         <= 1'b0;
            out_idx_o           <= 6'd0;
            out_data_o          <= 32'sd0;
            cycle_count_o       <= 16'd0;
            norm_sq_o           <= 32'sd0;
            rcf_raw_o           <= 32'sd0;
            g3_overlap_o        <= 32'sd0;
            delta_e_raw_o       <= 32'sd0;
            bleed_post_o        <= 32'sd0;
        end else begin
            case (state_q)
                S_IDLE: begin
                    done_o      <= 1'b0;
                    out_valid_o <= 1'b0;
                    if (start_i) begin
                        state_q             <= S_LOAD_DOT;
                        idx_q               <= 6'd0;
                        tier_latched_q      <= tier_mode_i;
                        norm_ok_q           <= 1'b0;
                        acc_norm_sq_q       <= 72'sd0;
                        acc_dot_l_q         <= 72'sd0;
                        acc_dot_g3_q        <= 72'sd0;
                        acc_dot_g3_p2_q     <= 72'sd0;
                        acc_strip_norm_sq_q <= 72'sd0;
                        acc_bleed_post_q    <= 72'sd0;
                        cycle_count_o       <= 16'd0;
                        gate_pass_o         <= 1'b0;
                        veto_pin_o          <= 1'b1;
                        norm_fault_o        <= 1'b0;
                        pure_g3_collision_o <= 1'b0;
                        mode_fault_o        <= 1'b0;
                    end
                end

                S_LOAD_DOT: begin
                    gate_pass_o <= 1'b0;
                    veto_pin_o  <= 1'b1;
                    if (in_valid_i) begin
                        acc_norm_sq_q <= acc_norm_sq_q + {{8{m0_prod_w[63]}}, m0_prod_w};
                        acc_dot_l_q   <= acc_dot_l_q   + {{8{m1_prod_w[63]}}, m1_prod_w};
                        acc_dot_g3_q  <= acc_dot_g3_q  + {{8{m2_prod_w[63]}}, m2_prod_w};
                        cycle_count_o <= cycle_count_o + 16'd1;
                        if (idx_q == 6'd63) begin
                            idx_q   <= 6'd0;
                            state_q <= S_EVAL_RAW;
                        end else begin
                            idx_q <= idx_q + 6'd1;
                        end
                    end
                end

                S_EVAL_RAW: begin
                    gate_pass_o     <= 1'b0;
                    veto_pin_o      <= 1'b1;
                    norm_sq_o       <= norm_sq_ev_w;
                    rcf_raw_o       <= m0_q30_w;
                    g3_overlap_o    <= g3_ov_ev_w;
                    delta_e_raw_o   <= delta_e_ev_w;
                    dot_g3_p1_q     <= dot_g3_ev_w;
                    norm_ok_q       <= norm_ok_ev_w;
                    acc_dot_g3_p2_q <= 72'sd0;
                    cycle_count_o   <= cycle_count_o + 16'd1;
                    idx_q           <= 6'd0;
                    state_q         <= S_STRIP_P1;
                end

                S_STRIP_P1: begin
                    gate_pass_o     <= 1'b0;
                    veto_pin_o      <= 1'b1;
                    acc_dot_g3_p2_q <= acc_dot_g3_p2_q + {{8{m1_prod_w[63]}}, m1_prod_w};
                    cycle_count_o   <= cycle_count_o + 16'd1;
                    if (idx_q == 6'd63) begin
                        idx_q   <= 6'd0;
                        state_q <= S_LATCH_P2;
                    end else begin
                        idx_q <= idx_q + 6'd1;
                    end
                end

                S_LATCH_P2: begin
                    gate_pass_o         <= 1'b0;
                    veto_pin_o          <= 1'b1;
                    dot_g3_p2_q         <= q60_to_q30(acc_dot_g3_p2_q);
                    acc_strip_norm_sq_q <= 72'sd0;
                    acc_bleed_post_q    <= 72'sd0;
                    cycle_count_o       <= cycle_count_o + 16'd1;
                    idx_q               <= 6'd0;
                    state_q             <= S_STRIP_P2;
                end

                S_STRIP_P2: begin
                    gate_pass_o         <= 1'b0;
                    veto_pin_o          <= 1'b1;
                    out_valid_o         <= 1'b1;
                    out_idx_o           <= idx_q;
                    out_data_o          <= v_step_w;
                    acc_strip_norm_sq_q <= acc_strip_norm_sq_q + {{8{m1_prod_w[63]}}, m1_prod_w};
                    acc_bleed_post_q    <= acc_bleed_post_q    + {{8{m2_prod_w[63]}}, m2_prod_w};
                    cycle_count_o       <= cycle_count_o + 16'd1;
                    if (idx_q == 6'd63) begin
                        idx_q   <= 6'd0;
                        state_q <= S_VERDICT;
                    end else begin
                        idx_q <= idx_q + 6'd1;
                    end
                end

                S_VERDICT: begin
                    out_valid_o         <= 1'b0;
                    cycle_count_o       <= cycle_count_o + 16'd1;
                    bleed_post_o        <= bleed_fin_ev_w;
                    norm_fault_o        <= !norm_ok_q;
                    pure_g3_collision_o <= pure_g3_ev_w;
                    mode_fault_o        <= tier_glitch_w;
                    gate_pass_o         <= pass_verdict_w;
                    veto_pin_o          <= !pass_verdict_w;
                    done_o              <= 1'b1;
                    state_q             <= S_IDLE;
                end

                default: begin
                    state_q     <= S_IDLE;
                    gate_pass_o <= 1'b0;
                    veto_pin_o  <= 1'b1;
                end
            endcase
        end
    end

endmodule
`default_nettype wire
