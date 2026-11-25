// =============================================================================
// rtl_v6/jedi_scout_norm_unit.v
// WP-1.3: Spine-Local 32x32 Squarers (NX_0 & Cached NW_0) + Zero-False-Reject
// Integer Cauchy-Schwarz Early Reject: CEIL(LHS) < FLOOR(RHS) in uint64 Q4.60.
// - U_Q30 = 32'h4000_0040 (Q2.30) / 32'h401C_0000 (Q2.14)
// - tau_cs_TAI = 32'h3F5C_28F5, tau_cs_NPU = 32'h2B85_1EB7
// =============================================================================
`timescale 1ns/1ps
`default_nettype none

module jedi_scout_norm_unit (
    input  wire               clk_i,
    input  wire               rst_n_i,
    input  wire               start_i,
    input  wire               vec_valid_i,
    input  wire               nw0_use_cache_i,
    input  wire               q214_mode_i,
    input  wire               scout_bypass_i,
    input  wire signed [31:0] x0_word_i,
    input  wire signed [31:0] w0_word_i,
    input  wire signed [74:0] dot0_q60_i,
    output wire               scout_reject_npu_o,
    output wire               scout_reject_tai_o,
    output wire        [31:0] rem_x_hi_o,
    output wire        [31:0] rem_w_hi_o
);

    localparam [31:0] U_Q30_PREC  = 32'h4000_0040;
    localparam [31:0] U_Q30_Q214  = 32'h401C_0000;
    localparam signed [45:0] TAU_CS_TAI = 46'sd1063004405; // 32'h3F5C_28F5
    localparam signed [45:0] TAU_CS_NPU = 46'sd730144439;  // 32'h2B85_1EB7
    localparam signed [45:0] MAX_U32    = 46'sd4294967295; // 32'hFFFF_FFFF

    reg        prod_vld_q;
    reg        use_cache_lat_q;
    reg [63:0] sq_x_q;
    reg [63:0] sq_w_q;
    reg [71:0] nx0_acc_q;
    reg [71:0] nw0_acc_q;
    reg [71:0] nw0_cache_q;
    reg        nw0_cache_vld_q;

    wire signed [63:0] sq_x_comb_w = x0_word_i * x0_word_i;
    wire signed [63:0] sq_w_comb_w = w0_word_i * w0_word_i;

    always @(posedge clk_i or negedge rst_n_i) begin
        if (!rst_n_i) begin
            prod_vld_q      <= 1'b0;
            use_cache_lat_q <= 1'b0;
            sq_x_q          <= 64'd0;
            sq_w_q          <= 64'd0;
            nx0_acc_q       <= 72'd0;
            nw0_acc_q       <= 72'd0;
            nw0_cache_q     <= 72'd0;
            nw0_cache_vld_q <= 1'b0;
        end else begin
            if (start_i) begin
                nx0_acc_q       <= 72'd0;
                use_cache_lat_q <= nw0_use_cache_i & nw0_cache_vld_q;
                if (!(nw0_use_cache_i & nw0_cache_vld_q)) begin
                    nw0_acc_q <= 72'd0;
                end
                prod_vld_q <= 1'b0;
            end else begin
                if (prod_vld_q) begin
                    nx0_acc_q <= nx0_acc_q + {8'd0, sq_x_q};
                    if (!use_cache_lat_q) begin
                        nw0_acc_q       <= nw0_acc_q + {8'd0, sq_w_q};
                        nw0_cache_q     <= nw0_acc_q + {8'd0, sq_w_q};
                        nw0_cache_vld_q <= 1'b1;
                    end
                end
                if (vec_valid_i) begin
                    sq_x_q     <= sq_x_comb_w[63:0];
                    sq_w_q     <= sq_w_comb_w[63:0];
                    prod_vld_q <= 1'b1;
                end else begin
                    prod_vld_q <= 1'b0;
                end
            end
        end
    end

    wire [71:0] nw0_eff_w   = use_cache_lat_q ? nw0_cache_q : nw0_acc_q;
    wire [31:0] u_q30_w     = q214_mode_i ? U_Q30_Q214 : U_Q30_PREC;

    wire [31:0] nx0_q30_w   = (|nx0_acc_q[71:62]) ? 32'hFFFF_FFFF : nx0_acc_q[61:30];
    wire [31:0] nw0_q30_w   = (|nw0_eff_w[71:62]) ? 32'hFFFF_FFFF : nw0_eff_w[61:30];

    wire [31:0] rem_x_hi_w  = (nx0_q30_w >= u_q30_w) ? 32'd0 : (u_q30_w - nx0_q30_w);
    wire [31:0] rem_w_hi_w  = (nw0_q30_w >= u_q30_w) ? 32'd0 : (u_q30_w - nw0_q30_w);

    // dot0_ceil = (D_0 >>> 30) + 1 in signed 46-bit precision
    wire signed [44:0] d0_shr30_w  = dot0_q60_i[74:30];
    wire signed [45:0] dot0_ceil_w = {d0_shr30_w[44], d0_shr30_w} + 46'sd1;

    wire signed [45:0] diff_npu_w  = TAU_CS_NPU - dot0_ceil_w;
    wire signed [45:0] diff_tai_w  = TAU_CS_TAI - dot0_ceil_w;

    wire [31:0] gap_npu_w = (dot0_ceil_w >= TAU_CS_NPU) ? 32'd0 :
                            ((diff_npu_w > MAX_U32) ? 32'hFFFF_FFFF : diff_npu_w[31:0]);
    wire [31:0] gap_tai_w = (dot0_ceil_w >= TAU_CS_TAI) ? 32'd0 :
                            ((diff_tai_w > MAX_U32) ? 32'hFFFF_FFFF : diff_tai_w[31:0]);

    wire [63:0] lhs64_w     = {32'd0, rem_x_hi_w} * {32'd0, rem_w_hi_w};
    wire [63:0] rhs_npu64_w = {32'd0, gap_npu_w}  * {32'd0, gap_npu_w};
    wire [63:0] rhs_tai64_w = {32'd0, gap_tai_w}  * {32'd0, gap_tai_w};

    assign rem_x_hi_o         = rem_x_hi_w;
    assign rem_w_hi_o         = rem_w_hi_w;
    assign scout_reject_npu_o = (~scout_bypass_i) & (dot0_ceil_w < TAU_CS_NPU) & (lhs64_w < rhs_npu64_w);
    assign scout_reject_tai_o = (~scout_bypass_i) & (dot0_ceil_w < TAU_CS_TAI) & (lhs64_w < rhs_tai64_w);

    wire _unused_ok = &{1'b0, nx0_acc_q[29:0], nw0_eff_w[29:0], dot0_q60_i[29:0], diff_npu_w[45:32], diff_tai_w[45:32]};
endmodule
`default_nettype wire
