// =============================================================================
// rtl_v6/jedi_kagome_reducer_768d.v
// WP-1.4: Split Tree_Even / Tree_Odd 768D Reducer + 6xDMR 1x-Scaling Fix +
// 0-Cycle SEU Divergence Veto + 12-Bit Sticky Barrier + 240-Cycle Watchdog +
// 19-Hex Upper Guard (76'sh000_1001... / 000_1008...) + Signed Dual-Tier Q2.30
// Gate + 2-Pass Complex Born-Fidelity Telemetry Mode (F = Re^2 + Im^2).
// =============================================================================
`timescale 1ns/1ps
`default_nettype none

module jedi_kagome_reducer_768d (
    input  wire               clk_i,
    input  wire               rst_n_i,
    input  wire               eval_arm_i,
    input  wire               eval_clear_i,
    input  wire               mode_dmr_i,
    input  wire               q214_mode_i,
    input  wire               born_mode_i,
    input  wire               born_pass_i,
    input  wire               dmr_seu_inj_i,
    input  wire        [11:0] active_tile_mask_i,
    input  wire        [11:0] tile_done_sticky_i,
    input  wire        [11:0] tile_fault_vec_i,
    input  wire        [31:0] delta_e_q30_i,

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

    output wire               reducer_eval_en_o,
    output wire               watchdog_trip_o,
    output wire               any_tile_fault_o,
    output wire               dmr_divergence_o,
    output wire               upper_guard_ok_o,
    output wire signed [74:0] tree_even_o,
    output wire signed [74:0] tree_odd_o,
    output wire signed [75:0] dot76_o,
    output wire        [31:0] rcf_quad_q30_o,
    output wire               npu_tier_ok_o,
    output wire               tai_tier_ok_o,
    output wire               born_valid_o,
    output wire        [31:0] born_fidelity_q30_o
);

    localparam signed [75:0] UPPER_GUARD_Q230 = 76'sh000_1001_0000_0000_0000;
    localparam signed [75:0] UPPER_GUARD_Q214 = 76'sh000_1008_0000_0000_0000;
    localparam signed [75:0] ROUND_HALF_Q30   = 76'sd536870912; // 2^29
    localparam        [31:0] RCF_QUAD_NPU_Q30 = 32'h1D97_F62B;  // 0.68^2
    localparam        [31:0] RCF_QUAD_TAI_Q30 = 32'h3EB9_F55A;  // 0.99^2
    localparam        [31:0] DELTA_E_TAI_MAX  = 32'h00A3_D70A;  // 0.01

    // Mask inactive tiles cleanly to zero
    wire signed [74:0] m00 = active_tile_mask_i[0]  ? dot_t00_i : 75'sd0;
    wire signed [74:0] m01 = active_tile_mask_i[1]  ? dot_t01_i : 75'sd0;
    wire signed [74:0] m02 = active_tile_mask_i[2]  ? dot_t02_i : 75'sd0;
    wire signed [74:0] m03 = active_tile_mask_i[3]  ? dot_t03_i : 75'sd0;
    wire signed [74:0] m04 = active_tile_mask_i[4]  ? dot_t04_i : 75'sd0;
    wire signed [74:0] m05 = active_tile_mask_i[5]  ? dot_t05_i : 75'sd0;
    wire signed [74:0] m06 = active_tile_mask_i[6]  ? dot_t06_i : 75'sd0;
    wire signed [74:0] m07 = active_tile_mask_i[7]  ? dot_t07_i : 75'sd0;
    wire signed [74:0] m08 = active_tile_mask_i[8]  ? dot_t08_i : 75'sd0;
    wire signed [74:0] m09 = active_tile_mask_i[9]  ? dot_t09_i : 75'sd0;
    wire signed [74:0] m10 = active_tile_mask_i[10] ? dot_t10_i : 75'sd0;
    wire signed [74:0] m11 = active_tile_mask_i[11] ? dot_t11_i : 75'sd0;

    // Split Tree_Even (0,2,4,6,8,10) and Tree_Odd (1,3,5,7,9,11), with 1-LSB SEU test tap
    wire signed [74:0] tree_even_w = (m00 + m02) + (m04 + m06) + (m08 + m10);
    wire signed [74:0] tree_odd_raw_w = (m01 + m03) + (m05 + m07) + (m09 + m11);
    wire signed [74:0] tree_odd_w  = dmr_seu_inj_i ? (tree_odd_raw_w ^ 75'sd1) : tree_odd_raw_w;

    // Sticky barrier + 240-cycle timeout watchdog
    reg       eval_armed_q;
    reg       eval_complete_q;
    reg [7:0] wd_cnt_q;
    reg       wd_trip_q;

    wire all_active_done_w = (&(tile_done_sticky_i | ~active_tile_mask_i)) & (|active_tile_mask_i);
    wire reducer_eval_en_w = eval_complete_q & (~wd_trip_q);

    always @(posedge clk_i or negedge rst_n_i) begin
        if (!rst_n_i) begin
            eval_armed_q    <= 1'b0;
            eval_complete_q <= 1'b0;
            wd_cnt_q        <= 8'd0;
            wd_trip_q       <= 1'b0;
        end else if (eval_clear_i) begin
            eval_armed_q    <= 1'b0;
            eval_complete_q <= 1'b0;
            wd_cnt_q        <= 8'd0;
            wd_trip_q       <= 1'b0;
        end else if (eval_arm_i) begin
            eval_armed_q    <= 1'b1;
            eval_complete_q <= 1'b0;
            wd_cnt_q        <= 8'd0;
            wd_trip_q       <= 1'b0;
        end else if (eval_armed_q && !all_active_done_w && !wd_trip_q) begin
            if (wd_cnt_q >= 8'd239) begin
                wd_cnt_q  <= 8'd240;
                wd_trip_q <= 1'b1;
            end else begin
                wd_cnt_q <= wd_cnt_q + 8'd1;
            end
        end else if (eval_armed_q && all_active_done_w && !wd_trip_q) begin
            eval_armed_q    <= 1'b0;
            eval_complete_q <= 1'b1;
        end
    end

    // 6xDMR 1x-scaling fix & 0-cycle SEU divergence veto
    wire signed [75:0] dot76_w = mode_dmr_i
        ? {tree_even_w[74], tree_even_w}
        : ({tree_even_w[74], tree_even_w} + {tree_odd_w[74], tree_odd_w});

    wire dmr_div_w        = reducer_eval_en_w & mode_dmr_i & (tree_even_w != tree_odd_w);
    wire any_tile_fault_w = |(tile_fault_vec_i & active_tile_mask_i);

    // 19-hex upper guard & strictly positive real-mode check
    wire signed [75:0] upper_lim_w = q214_mode_i ? UPPER_GUARD_Q214 : UPPER_GUARD_Q230;
    wire               upper_ok_w  = (dot76_w <= upper_lim_w);
    wire               lower_born_ok_w = (dot76_w >= -upper_lim_w);
    wire               pos_ok_w    = (~dot76_w[75]) & (dot76_w != 76'sd0);

    // Rounded Q2.30 inner product magnitude for squaring
    wire signed [75:0] dot76_rnd_w = dot76_w + ROUND_HALF_Q30;
    wire signed [31:0] c_signed_q30_w = dot76_rnd_w[61:30];
    wire        [31:0] c_pos_q30_w = (upper_ok_w && pos_ok_w) ? dot76_rnd_w[61:30] : 32'd0;
    wire        [63:0] rcf_prod_w  = {32'd0, c_pos_q30_w} * {32'd0, c_pos_q30_w};
    wire        [63:0] rcf_rnd_w   = rcf_prod_w + 64'd536870912;
    wire        [31:0] rcf_quad_w  = (|rcf_rnd_w[63:62]) ? 32'h7FFF_FFFF : rcf_rnd_w[61:30];

    // 2-Pass Complex Born-Fidelity (C^384 -> S^767): Pass 0 = Re, Pass 1 = Im -> F = Re^2 + Im^2
    reg signed [31:0] born_re_q30_q;
    reg               born_re_latched_q;
    reg               born_done_d1_q;

    wire signed [63:0] re_sq_w = born_re_q30_q  * born_re_q30_q;
    wire signed [63:0] im_sq_w = c_signed_q30_w * c_signed_q30_w;
    wire        [64:0] born_sum65_w = {1'b0, re_sq_w[63:0]} + {1'b0, im_sq_w[63:0]} + 65'd536870912;
    wire        [31:0] born_fid_w   = (|born_sum65_w[64:62]) ? 32'h7FFF_FFFF : born_sum65_w[61:30];

    always @(posedge clk_i or negedge rst_n_i) begin
        if (!rst_n_i) begin
            born_re_q30_q     <= 32'sd0;
            born_re_latched_q <= 1'b0;
            born_done_d1_q    <= 1'b0;
        end else if (eval_clear_i) begin
            born_done_d1_q <= 1'b0;
            if (!born_mode_i) begin
                born_re_latched_q <= 1'b0;
            end
        end else begin
            born_done_d1_q <= reducer_eval_en_w;
            if (born_mode_i && reducer_eval_en_w && !born_done_d1_q) begin
                if (!born_pass_i && upper_ok_w && lower_born_ok_w) begin
                    born_re_q30_q     <= c_signed_q30_w;
                    born_re_latched_q <= 1'b1;
                end
            end
        end
    end

    wire gate_clean_w = reducer_eval_en_w & (~wd_trip_q) & (~dmr_div_w) & (~any_tile_fault_w) & (~born_mode_i);

    assign reducer_eval_en_o   = reducer_eval_en_w;
    assign watchdog_trip_o     = wd_trip_q;
    assign any_tile_fault_o    = any_tile_fault_w;
    assign dmr_divergence_o    = dmr_div_w;
    assign upper_guard_ok_o    = upper_ok_w;
    assign tree_even_o         = tree_even_w;
    assign tree_odd_o          = tree_odd_w;
    assign dot76_o             = dot76_w;
    assign rcf_quad_q30_o      = rcf_quad_w;
    assign npu_tier_ok_o       = gate_clean_w & upper_ok_w & pos_ok_w & (rcf_quad_w >= RCF_QUAD_NPU_Q30);
    assign tai_tier_ok_o       = gate_clean_w & upper_ok_w & pos_ok_w & (rcf_quad_w >= RCF_QUAD_TAI_Q30) & (delta_e_q30_i <= DELTA_E_TAI_MAX);
    assign born_valid_o        = born_mode_i & born_pass_i & born_re_latched_q & reducer_eval_en_w & upper_ok_w & lower_born_ok_w & (~dmr_div_w) & (~any_tile_fault_w);
    assign born_fidelity_q30_o = born_valid_o ? born_fid_w : 32'd0;

    wire _unused_ok = &{1'b0, dot76_rnd_w[75:62], dot76_rnd_w[29:0], rcf_rnd_w[29:0], born_sum65_w[29:0]};
endmodule
`default_nettype wire
