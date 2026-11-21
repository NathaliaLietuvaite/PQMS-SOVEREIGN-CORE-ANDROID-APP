`default_nettype none

module odos_gate_core_v4 #(
    parameter L_ROM_HEX  = "rtl/rom/l_vec_q2_30.hex",
    parameter G3_ROM_HEX = "rtl/rom/g3_vec_q2_30.hex"
) (
    input   wire               clk_i,
    input   wire               rst_ni,
    input   wire               start_i,
    input   wire        [1:0]  tier_mode_i,
    input   wire               in_valid_i,
    output logic              in_ready_o,
    input   wire signed [31:0] in_data_i,

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

    localparam signed [31:0] ONE_Q2_30            = 32'sh4000_0000;
    localparam signed [31:0] RCF_TIER0_Q2_30      = 32'sh3CCC_CCCD;
    localparam signed [31:0] RCF_TIER1_Q2_30      = 32'sh3999_999A;
    localparam signed [31:0] RCF_TIER2_Q2_30      = 32'sh3F5C_28F6;
    localparam signed [31:0] DE_TIER01_Q2_30      = 32'sh0333_3333;
    localparam signed [31:0] DE_TIER2_Q2_30       = 32'sh00A3_D70A;
    localparam signed [31:0] NORM_MIN_Q2_30       = 32'sh3FEF_9DB2;
    localparam signed [31:0] NORM_MAX_Q2_30       = 32'sh4010_624E;
    localparam signed [31:0] STRIP_NORM_MIN_Q2_30 = 32'sh0000_0432;
    localparam signed [31:0] BLEED_CEIL_Q2_30     = 32'sh0000_0020;
    // Exact half-ULP rounding bias (2^29) pre-loaded into Q12.60 accumulators
    localparam signed [71:0] ROUND_BIAS_Q60       = 72'sd536870912;

    typedef enum logic [3:0] {
        S_IDLE       = 4'd0,
        S_LOAD_DOT   = 4'd1,
        S_EVAL_ADD   = 4'd2,
        S_EVAL_SQ    = 4'd3,
        S_STRIP_P1   = 4'd4,
        S_DRAIN_P1_A = 4'd5,
        S_DRAIN_P1_B = 4'd6,
        S_LATCH_P2   = 4'd7,
        S_STRIP_P2   = 4'd8,
        S_DRAIN_P2_A = 4'd9,
        S_DRAIN_P2_B = 4'd10,
        S_VERDICT    = 4'd11
    } state_e;

    state_e state_q;
    logic [5:0] idx_q;
    logic [1:0] tier_latched_q;
    logic       norm_ok_q;
    logic       load_prod_valid_q;

    logic signed [31:0] l_rom  [0:63];
    logic signed [31:0] g3_rom [0:63];

    initial begin
        $readmemh(L_ROM_HEX, l_rom);
        $readmemh(G3_ROM_HEX, g3_rom);
    end

    // Pre-fetched ROM registers (completely decouple 64:1 ROM mux from 32x32 MAC paths)
    logic signed [31:0] l_rom_q;
    logic signed [31:0] g3_rom_q;

    // Dedicated 64-bit MAC product pipeline registers
    logic signed [63:0] m0_prod_q;
    logic signed [63:0] m1_prod_q;
    logic signed [63:0] m2_prod_q;

    // Shared SRAM staging & inter-rank registers (disjoint lifetimes across FSM phases)
    logic signed [31:0] even_hold_q;
    logic signed [31:0] v_cur_q;
    logic signed [31:0] v_odd_hold_q;
    logic signed [31:0] g3_d1_q;
    logic signed [31:0] v_pipe_q;
    logic signed [31:0] g3_pipe_q;

    logic signed [31:0] dot_l_q;
    logic signed [31:0] dot_g3_q;

    // Time-shared pre-biased 72-bit Q12.60 accumulators (initialized to ROUND_BIAS_Q60 = 2^29)
    logic signed [71:0] acc0_q;
    logic signed [71:0] acc1_q;
    logic signed [71:0] acc2_q;

    function automatic logic signed [71:0] sext72(input logic signed [63:0] p);
        begin
            sext72 = $signed({{8{p[63]}}, p});
        end
    endfunction

    // 7-level Kogge-Stone parallel-prefix 72-bit adder
    function automatic logic signed [71:0] add72_ks(
        input logic signed [71:0] a,
        input logic signed [71:0] b
    );
        logic [71:0] p0, g, p, c;
        integer i;
        begin
            p0 = a ^ b;
            g  = a & b;
            p  = p0;
            for (i = 71; i >= 1;  i = i - 1) begin g[i] = g[i] | (p[i] & g[i-1]);  p[i] = p[i] & p[i-1];  end
            for (i = 71; i >= 2;  i = i - 1) begin g[i] = g[i] | (p[i] & g[i-2]);  p[i] = p[i] & p[i-2];  end
            for (i = 71; i >= 4;  i = i - 1) begin g[i] = g[i] | (p[i] & g[i-4]);  p[i] = p[i] & p[i-4];  end
            for (i = 71; i >= 8;  i = i - 1) begin g[i] = g[i] | (p[i] & g[i-8]);  p[i] = p[i] & p[i-8];  end
            for (i = 71; i >= 16; i = i - 1) begin g[i] = g[i] | (p[i] & g[i-16]); p[i] = p[i] & p[i-16]; end
            for (i = 71; i >= 32; i = i - 1) begin g[i] = g[i] | (p[i] & g[i-32]); p[i] = p[i] & p[i-32]; end
            for (i = 71; i >= 64; i = i - 1) begin g[i] = g[i] | (p[i] & g[i-64]); end
            c = {g[70:0], 1'b0};
            add72_ks = $signed(p0 ^ c);
        end
    endfunction

    // 6-level Kogge-Stone parallel-prefix 64-bit adder (final CPA for 32x32 CSA multiplier)
    function automatic logic signed [63:0] add64_ks(
        input logic [63:0] a,
        input logic [63:0] b
    );
        logic [63:0] p0, g, p, c;
        integer i;
        begin
            p0 = a ^ b;
            g  = a & b;
            p  = p0;
            for (i = 63; i >= 1;  i = i - 1) begin g[i] = g[i] | (p[i] & g[i-1]);  p[i] = p[i] & p[i-1];  end
            for (i = 63; i >= 2;  i = i - 1) begin g[i] = g[i] | (p[i] & g[i-2]);  p[i] = p[i] & p[i-2];  end
            for (i = 63; i >= 4;  i = i - 1) begin g[i] = g[i] | (p[i] & g[i-4]);  p[i] = p[i] & p[i-4];  end
            for (i = 63; i >= 8;  i = i - 1) begin g[i] = g[i] | (p[i] & g[i-8]);  p[i] = p[i] & p[i-8];  end
            for (i = 63; i >= 16; i = i - 1) begin g[i] = g[i] | (p[i] & g[i-16]); p[i] = p[i] & p[i-16]; end
            for (i = 63; i >= 32; i = i - 1) begin g[i] = g[i] | (p[i] & g[i-32]); end
            c = {g[62:0], 1'b0};
            add64_ks = $signed(p0 ^ c);
        end
    endfunction

    // Exact 32x32->64 signed multiplier: 4x 16x16 Booth sub-multipliers + 2-stage 3:2 CSA + Kogge-Stone 64b CPA
    function automatic logic signed [63:0] mul32x32_ks(
        input logic signed [31:0] a,
        input logic signed [31:0] b
    );
        logic signed [15:0] a_hi, b_hi;
        logic        [15:0] a_lo, b_lo;
        logic        [31:0] p_ll;
        logic signed [32:0] p_hl, p_lh;
        logic signed [31:0] p_hh;
        logic        [63:0] t0, t1, t2, t3;
        logic        [63:0] s1, c1, s2, c2;
        begin
            a_hi = $signed(a[31:16]);
            b_hi = $signed(b[31:16]);
            a_lo = a[15:0];
            b_lo = b[15:0];
            /* verilator lint_off WIDTHEXPAND */
            p_ll = a_lo * b_lo;
            p_hl = a_hi * $signed({1'b0, b_lo});
            p_lh = $signed({1'b0, a_lo}) * b_hi;
            p_hh = a_hi * b_hi;
            /* verilator lint_on WIDTHEXPAND */
            t0 = {32'd0, p_ll};
            t1 = {{15{p_hl[32]}}, p_hl, 16'd0};
            t2 = {{15{p_lh[32]}}, p_lh, 16'd0};
            t3 = {p_hh, 32'd0};
            s1 = t0 ^ t1 ^ t2;
            c1 = {((t0[62:0] & t1[62:0]) | (t1[62:0] & t2[62:0]) | (t0[62:0] & t2[62:0])), 1'b0};
            s2 = s1 ^ c1 ^ t3;
            c2 = {((s1[62:0] & c1[62:0]) | (c1[62:0] & t3[62:0]) | (s1[62:0] & t3[62:0])), 1'b0};
            mul32x32_ks = add64_ks(s2, c2);
        end
    endfunction

    // Zero-adder saturating slice for pre-biased (acc + 2^29)[71:30] Q12.60 accumulators
    function automatic logic signed [31:0] q60_biased_to_q30(input logic signed [41:0] acc_hi);
        logic all_zero, all_one;
        begin
            all_zero = ~(|acc_hi[41:31]);
            all_one  = &acc_hi[41:31];
            if (all_zero || all_one) begin
                q60_biased_to_q30 = $signed(acc_hi[31:0]);
            end else if (!acc_hi[41]) begin
                q60_biased_to_q30 = 32'sd2147483647;
            end else begin
                q60_biased_to_q30 = -32'sd2147483648;
            end
        end
    endfunction

    // 6-level Kogge-Stone parallel-prefix 35-bit incrementer for single 64-bit signed product rounding
    function automatic logic signed [31:0] prod64_to_q30(input logic [34:0] p_hi);
        logic [34:0] x, p, c, rounded;
        logic all_zero, all_one;
        integer i;
        begin
            x = {p_hi[34], p_hi[34:1]};
            p = x;
            for (i = 34; i >= 1;  i = i - 1) p[i] = p[i] & p[i-1];
            for (i = 34; i >= 2;  i = i - 1) p[i] = p[i] & p[i-2];
            for (i = 34; i >= 4;  i = i - 1) p[i] = p[i] & p[i-4];
            for (i = 34; i >= 8;  i = i - 1) p[i] = p[i] & p[i-8];
            for (i = 34; i >= 16; i = i - 1) p[i] = p[i] & p[i-16];
            for (i = 34; i >= 32; i = i - 1) p[i] = p[i] & p[i-32];
            c = {p[33:0] & {34{p_hi[0]}}, p_hi[0]};
            rounded  = x ^ c;
            all_zero = ~(|rounded[34:31]);
            all_one  = &rounded[34:31];
            if (all_zero || all_one) begin
                prod64_to_q30 = $signed(rounded[31:0]);
            end else if (!rounded[34]) begin
                prod64_to_q30 = 32'sd2147483647;
            end else begin
                prod64_to_q30 = -32'sd2147483648;
            end
        end
    endfunction

    // 6-level Kogge-Stone parallel-prefix 33-bit saturating subtractor
    function automatic logic signed [31:0] sat_sub_q30(
        input logic signed [31:0] a,
        input logic signed [31:0] b
    );
        logic [32:0] ax, bx, p0, g, p, c, diff;
        integer i;
        begin
            ax = {a[31], a};
            bx = ~{b[31], b};
            p0 = ax ^ bx;
            g  = ax & bx;
            // Absorb cin = 1'b1 into bit 0: g[0] = g[0] | p0[0]
            g[0] = g[0] | p0[0];
            p  = p0;
            for (i = 32; i >= 1;  i = i - 1) begin g[i] = g[i] | (p[i] & g[i-1]);  p[i] = p[i] & p[i-1];  end
            for (i = 32; i >= 2;  i = i - 1) begin g[i] = g[i] | (p[i] & g[i-2]);  p[i] = p[i] & p[i-2];  end
            for (i = 32; i >= 4;  i = i - 1) begin g[i] = g[i] | (p[i] & g[i-4]);  p[i] = p[i] & p[i-4];  end
            for (i = 32; i >= 8;  i = i - 1) begin g[i] = g[i] | (p[i] & g[i-8]);  p[i] = p[i] & p[i-8];  end
            for (i = 32; i >= 16; i = i - 1) begin g[i] = g[i] | (p[i] & g[i-16]); p[i] = p[i] & p[i-16]; end
            g[32] = g[32] | (p[32] & g[0]);
            c = {g[31:0], 1'b1};
            diff = p0 ^ c;
            if (diff[32] == diff[31]) begin
                sat_sub_q30 = $signed(diff[31:0]);
            end else if (!diff[32]) begin
                sat_sub_q30 = 32'sd2147483647;
            end else begin
                sat_sub_q30 = -32'sd2147483648;
            end
        end
    endfunction

    function automatic logic signed [31:0] abs_sat_q30(input logic signed [31:0] x);
        begin
            if (x == -32'sd2147483648) begin
                abs_sat_q30 = 32'sd2147483647;
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

    wire [5:0]         idx_next_w   = idx_q + 6'd1;
    wire signed [31:0] l_rom_nxt_w  = l_rom[idx_next_w];
    wire signed [31:0] g3_rom_nxt_w = g3_rom[idx_next_w];
    wire signed [31:0] m0_q30_reg_w = prod64_to_q30(m0_prod_q[63:29]);
    wire signed [31:0] v_step_w     = sat_sub_q30(v_cur_q, m0_q30_reg_w);

    // -------------------------------------------------------------------------
    // Collision-Free Paired-Word Single-Port 64x64 SRAM Control
    // -------------------------------------------------------------------------
    logic        sram_men_w;
    logic        sram_wen_w;
    logic [4:0]  sram_addr_w;
    logic [63:0] sram_wdata_w;
    wire  [63:0] sram_rdata_w;

    wire [4:0] next_rd_addr_w = idx_q[5:1] + 5'd1;

    always_comb begin
        sram_men_w   = 1'b0;
        sram_wen_w   = 1'b0;
        sram_addr_w  = 5'd0;
        sram_wdata_w = 64'd0;
        case (state_q)
            S_LOAD_DOT: begin
                if (in_valid_i && idx_q[0]) begin
                    sram_men_w   = 1'b1;
                    sram_wen_w   = 1'b1;
                    sram_addr_w  = idx_q[5:1];
                    sram_wdata_w = {in_data_i, even_hold_q};
                end
            end
            S_EVAL_SQ, S_LATCH_P2: begin
                sram_men_w  = 1'b1;
                sram_wen_w  = 1'b0;
                sram_addr_w = 5'd0;
            end
            S_STRIP_P1: begin
                if (idx_q[0] && (idx_q != 6'd63)) begin
                    sram_men_w  = 1'b1;
                    sram_wen_w  = 1'b0;
                    sram_addr_w = next_rd_addr_w;
                end else if ((!idx_q[0]) && (idx_q != 6'd0)) begin
                    sram_men_w   = 1'b1;
                    sram_wen_w   = 1'b1;
                    sram_addr_w  = idx_q[5:1] - 5'd1;
                    sram_wdata_w = {v_step_w, even_hold_q};
                end
            end
            S_DRAIN_P1_A: begin
                sram_men_w   = 1'b1;
                sram_wen_w   = 1'b1;
                sram_addr_w  = 5'd31;
                sram_wdata_w = {v_step_w, even_hold_q};
            end
            S_STRIP_P2: begin
                if (idx_q[0] && (idx_q != 6'd63)) begin
                    sram_men_w  = 1'b1;
                    sram_wen_w  = 1'b0;
                    sram_addr_w = next_rd_addr_w;
                end
            end
            default: begin
                sram_men_w = 1'b0;
            end
        endcase
    end

    odos_sram_64x32_1p u_vec_sram (
        .clk_i   (clk_i),
        .men_i   (sram_men_w),
        .wen_i   (sram_wen_w),
        .addr_i  (sram_addr_w),
        .wdata_i (sram_wdata_w),
        .rdata_o (sram_rdata_w)
    );

    // -------------------------------------------------------------------------
    // Strictly Isolated 3-MAC Multiplier Stage (FF/Port -> Booth+CSA+KS -> FF)
    // -------------------------------------------------------------------------
    logic signed [31:0] m0_a, m0_b;
    logic signed [31:0] m1_a, m1_b;
    logic signed [31:0] m2_a, m2_b;

    always_comb begin
        m0_a = 32'sd0; m0_b = 32'sd0;
        m1_a = 32'sd0; m1_b = 32'sd0;
        m2_a = 32'sd0; m2_b = 32'sd0;
        case (state_q)
            S_LOAD_DOT: begin
                m0_a = in_data_i; m0_b = in_data_i;
                m1_a = in_data_i; m1_b = l_rom_q;
                m2_a = in_data_i; m2_b = g3_rom_q;
            end
            S_EVAL_SQ: begin
                m0_a = dot_l_q;   m0_b = dot_l_q;
            end
            S_STRIP_P1: begin
                m0_a = dot_g3_q; m0_b = g3_rom_q;
                if (idx_q >= 6'd2) begin
                    m1_a = v_pipe_q; m1_b = g3_pipe_q;
                end
            end
            S_DRAIN_P1_A, S_DRAIN_P1_B: begin
                m1_a = v_pipe_q; m1_b = g3_pipe_q;
            end
            S_STRIP_P2: begin
                m0_a = dot_g3_q; m0_b = g3_rom_q;
                if (idx_q >= 6'd2) begin
                    m1_a = v_pipe_q; m1_b = v_pipe_q;
                    m2_a = v_pipe_q; m2_b = g3_pipe_q;
                end
            end
            S_DRAIN_P2_A, S_DRAIN_P2_B: begin
                m1_a = v_pipe_q; m1_b = v_pipe_q;
                m2_a = v_pipe_q; m2_b = g3_pipe_q;
            end
            default: begin
                m0_a = 32'sd0; m0_b = 32'sd0;
            end
        endcase
    end

    wire signed [63:0] m0_comb_w = mul32x32_ks(m0_a, m0_b);
    wire signed [63:0] m1_comb_w = mul32x32_ks(m1_a, m1_b);
    wire signed [63:0] m2_comb_w = mul32x32_ks(m2_a, m2_b);

    // Shared post-register Kogge-Stone 72-bit adders & zero-adder biased quantizers
    wire signed [71:0] acc0_next_w = add72_ks(acc0_q, sext72(m0_prod_q));
    wire signed [71:0] acc1_next_w = add72_ks(acc1_q, sext72(m1_prod_q));
    wire signed [71:0] acc2_next_w = add72_ks(acc2_q, sext72(m2_prod_q));

    wire signed [31:0] acc0_q30_w  = q60_biased_to_q30($signed(acc0_next_w[71:30]));
    wire signed [31:0] acc1_q30_w  = q60_biased_to_q30($signed(acc1_next_w[71:30]));
    wire signed [31:0] acc2_q30_w  = q60_biased_to_q30($signed(acc2_next_w[71:30]));

    wire signed [31:0] g3_ov_ev_w     = abs_sat_q30(acc2_q30_w);
    wire               norm_ok_ev_w   = (acc0_q30_w >= NORM_MIN_Q2_30) && (acc0_q30_w <= NORM_MAX_Q2_30);

    wire signed [31:0] t1_ev_w        = (m0_q30_reg_w >= ONE_Q2_30) ? 32'sd0 : (ONE_Q2_30 - m0_q30_reg_w);
    wire signed [31:0] t2_ev_w        = (g3_overlap_o > ONE_Q2_30) ? ONE_Q2_30 : g3_overlap_o;
    wire signed [31:0] delta_e_ev_w   = half_sum_q30(t1_ev_w, t2_ev_w);

    wire               pure_g3_ev_w   = (acc1_q30_w < STRIP_NORM_MIN_Q2_30);
    wire signed [31:0] bleed_raw_ev_w = abs_sat_q30(acc2_q30_w);
    wire signed [31:0] bleed_fin_ev_w = pure_g3_ev_w ? ONE_Q2_30 : bleed_raw_ev_w;
    wire               bleed_ok_ev_w  = (!pure_g3_ev_w) && (acc2_q30_w >= -BLEED_CEIL_Q2_30) && (acc2_q30_w <= BLEED_CEIL_Q2_30);

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
                        && (rcf_raw_o >= rcf_floor_sel_w)
                        && (delta_e_raw_o <= de_ceil_sel_w)
                        && bleed_ok_ev_w;

    assign in_ready_o = (state_q == S_LOAD_DOT);
    assign busy_o     = (state_q != S_IDLE);

    always_ff @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni) begin
            state_q             <= S_IDLE;
            idx_q               <= 6'd0;
            tier_latched_q      <= 2'b00;
            norm_ok_q           <= 1'b0;
            load_prod_valid_q   <= 1'b0;
            l_rom_q             <= 32'sd0;
            g3_rom_q            <= 32'sd0;
            m0_prod_q           <= 64'sd0;
            m1_prod_q           <= 64'sd0;
            m2_prod_q           <= 64'sd0;
            even_hold_q         <= 32'sd0;
            v_cur_q             <= 32'sd0;
            v_odd_hold_q        <= 32'sd0;
            g3_d1_q             <= 32'sd0;
            v_pipe_q            <= 32'sd0;
            g3_pipe_q           <= 32'sd0;
            dot_l_q             <= 32'sd0;
            dot_g3_q            <= 32'sd0;
            acc0_q              <= ROUND_BIAS_Q60;
            acc1_q              <= ROUND_BIAS_Q60;
            acc2_q              <= ROUND_BIAS_Q60;
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
                    done_o            <= 1'b0;
                    out_valid_o       <= 1'b0;
                    load_prod_valid_q <= 1'b0;
                    if (start_i) begin
                        state_q             <= S_LOAD_DOT;
                        idx_q               <= 6'd0;
                        l_rom_q             <= l_rom[6'd0];
                        g3_rom_q            <= g3_rom[6'd0];
                        tier_latched_q      <= tier_mode_i;
                        norm_ok_q           <= 1'b0;
                        acc0_q              <= ROUND_BIAS_Q60;
                        acc1_q              <= ROUND_BIAS_Q60;
                        acc2_q              <= ROUND_BIAS_Q60;
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
                    if (load_prod_valid_q) begin
                        acc0_q <= acc0_next_w;
                        acc1_q <= acc1_next_w;
                        acc2_q <= acc2_next_w;
                    end
                    if (in_valid_i) begin
                        m0_prod_q         <= m0_comb_w;
                        m1_prod_q         <= m1_comb_w;
                        m2_prod_q         <= m2_comb_w;
                        load_prod_valid_q <= 1'b1;
                        if (!idx_q[0]) begin
                            even_hold_q <= in_data_i;
                        end
                        cycle_count_o <= cycle_count_o + 16'd1;
                        if (idx_q == 6'd63) begin
                            idx_q   <= 6'd0;
                            state_q <= S_EVAL_ADD;
                        end else begin
                            idx_q    <= idx_next_w;
                            l_rom_q  <= l_rom_nxt_w;
                            g3_rom_q <= g3_rom_nxt_w;
                        end
                    end else begin
                        load_prod_valid_q <= 1'b0;
                    end
                end

                S_EVAL_ADD: begin
                    gate_pass_o       <= 1'b0;
                    veto_pin_o        <= 1'b1;
                    load_prod_valid_q <= 1'b0;
                    norm_sq_o         <= acc0_q30_w;
                    norm_ok_q         <= norm_ok_ev_w;
                    dot_l_q           <= acc1_q30_w;
                    dot_g3_q          <= acc2_q30_w;
                    g3_overlap_o      <= g3_ov_ev_w;
                    cycle_count_o     <= cycle_count_o + 16'd1;
                    state_q           <= S_EVAL_SQ;
                end

                S_EVAL_SQ: begin
                    gate_pass_o   <= 1'b0;
                    veto_pin_o    <= 1'b1;
                    m0_prod_q     <= m0_comb_w;
                    g3_rom_q      <= g3_rom[6'd0];
                    acc1_q        <= ROUND_BIAS_Q60;
                    idx_q         <= 6'd0;
                    cycle_count_o <= cycle_count_o + 16'd1;
                    state_q       <= S_STRIP_P1;
                end

                S_STRIP_P1: begin
                    gate_pass_o <= 1'b0;
                    veto_pin_o  <= 1'b1;
                    m0_prod_q   <= m0_comb_w;
                    g3_d1_q     <= g3_rom_q;
                    if (idx_q == 6'd0) begin
                        rcf_raw_o     <= m0_q30_reg_w;
                        delta_e_raw_o <= delta_e_ev_w;
                        v_cur_q       <= $signed(sram_rdata_w[31:0]);
                        v_odd_hold_q  <= $signed(sram_rdata_w[63:32]);
                    end else begin
                        v_pipe_q  <= v_step_w;
                        g3_pipe_q <= g3_d1_q;
                        if (idx_q[0]) begin
                            even_hold_q <= v_step_w;
                            v_cur_q     <= v_odd_hold_q;
                        end else begin
                            v_cur_q      <= $signed(sram_rdata_w[31:0]);
                            v_odd_hold_q <= $signed(sram_rdata_w[63:32]);
                        end
                    end
                    if (idx_q >= 6'd2) begin
                        m1_prod_q <= m1_comb_w;
                    end
                    if (idx_q >= 6'd3) begin
                        acc1_q <= acc1_next_w;
                    end
                    cycle_count_o <= cycle_count_o + 16'd1;
                    if (idx_q == 6'd63) begin
                        idx_q   <= 6'd0;
                        state_q <= S_DRAIN_P1_A;
                    end else begin
                        idx_q    <= idx_next_w;
                        g3_rom_q <= g3_rom_nxt_w;
                    end
                end

                S_DRAIN_P1_A: begin
                    gate_pass_o   <= 1'b0;
                    veto_pin_o    <= 1'b1;
                    v_pipe_q      <= v_step_w;
                    g3_pipe_q     <= g3_d1_q;
                    m1_prod_q     <= m1_comb_w;
                    acc1_q        <= acc1_next_w;
                    cycle_count_o <= cycle_count_o + 16'd1;
                    state_q       <= S_DRAIN_P1_B;
                end

                S_DRAIN_P1_B: begin
                    gate_pass_o   <= 1'b0;
                    veto_pin_o    <= 1'b1;
                    m1_prod_q     <= m1_comb_w;
                    acc1_q        <= acc1_next_w;
                    cycle_count_o <= cycle_count_o + 16'd1;
                    state_q       <= S_LATCH_P2;
                end

                S_LATCH_P2: begin
                    gate_pass_o   <= 1'b0;
                    veto_pin_o    <= 1'b1;
                    dot_g3_q      <= acc1_q30_w;
                    g3_rom_q      <= g3_rom[6'd0];
                    acc1_q        <= ROUND_BIAS_Q60;
                    acc2_q        <= ROUND_BIAS_Q60;
                    idx_q         <= 6'd0;
                    cycle_count_o <= cycle_count_o + 16'd1;
                    state_q       <= S_STRIP_P2;
                end

                S_STRIP_P2: begin
                    gate_pass_o <= 1'b0;
                    veto_pin_o  <= 1'b1;
                    m0_prod_q   <= m0_comb_w;
                    g3_d1_q     <= g3_rom_q;
                    if (idx_q == 6'd0) begin
                        out_valid_o  <= 1'b0;
                        v_cur_q      <= $signed(sram_rdata_w[31:0]);
                        v_odd_hold_q <= $signed(sram_rdata_w[63:32]);
                    end else begin
                        out_valid_o <= 1'b1;
                        out_idx_o   <= idx_q - 6'd1;
                        out_data_o  <= v_step_w;
                        v_pipe_q    <= v_step_w;
                        g3_pipe_q   <= g3_d1_q;
                        if (idx_q[0]) begin
                            v_cur_q <= v_odd_hold_q;
                        end else begin
                            v_cur_q      <= $signed(sram_rdata_w[31:0]);
                            v_odd_hold_q <= $signed(sram_rdata_w[63:32]);
                        end
                    end
                    if (idx_q >= 6'd2) begin
                        m1_prod_q <= m1_comb_w;
                        m2_prod_q <= m2_comb_w;
                    end
                    if (idx_q >= 6'd3) begin
                        acc1_q <= acc1_next_w;
                        acc2_q <= acc2_next_w;
                    end
                    cycle_count_o <= cycle_count_o + 16'd1;
                    if (idx_q == 6'd63) begin
                        idx_q   <= 6'd0;
                        state_q <= S_DRAIN_P2_A;
                    end else begin
                        idx_q    <= idx_next_w;
                        g3_rom_q <= g3_rom_nxt_w;
                    end
                end

                S_DRAIN_P2_A: begin
                    gate_pass_o   <= 1'b0;
                    veto_pin_o    <= 1'b1;
                    out_valid_o   <= 1'b1;
                    out_idx_o     <= 6'd63;
                    out_data_o    <= v_step_w;
                    v_pipe_q      <= v_step_w;
                    g3_pipe_q     <= g3_d1_q;
                    m1_prod_q     <= m1_comb_w;
                    m2_prod_q     <= m2_comb_w;
                    acc1_q        <= acc1_next_w;
                    acc2_q        <= acc2_next_w;
                    cycle_count_o <= cycle_count_o + 16'd1;
                    state_q       <= S_DRAIN_P2_B;
                end

                S_DRAIN_P2_B: begin
                    gate_pass_o   <= 1'b0;
                    veto_pin_o    <= 1'b1;
                    out_valid_o   <= 1'b0;
                    m1_prod_q     <= m1_comb_w;
                    m2_prod_q     <= m2_comb_w;
                    acc1_q        <= acc1_next_w;
                    acc2_q        <= acc2_next_w;
                    cycle_count_o <= cycle_count_o + 16'd1;
                    state_q       <= S_VERDICT;
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
