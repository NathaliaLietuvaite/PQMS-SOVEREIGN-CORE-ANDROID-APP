// =============================================================================
// rtl_v6/jedi_sram_1024x64_wrap.v
// Wrapper for IHP SG13G2 RM_IHPSG13_1P_1024x64_c2_bm_bist (8 KB Single-Port)
// Guardrail G1 & G5: A_DLY tied 1'b1 (sg13g2_tiehi), A_BIST_EN tied 1'b0 (sg13g2_tielo)
// =============================================================================
`timescale 1ns/1ps
`default_nettype none

module jedi_sram_1024x64_wrap (
    input  wire        clk_i,
    input  wire        men_i,
    input  wire        wen_i,
    input  wire        ren_i,
    input  wire [9:0]  addr_i,
    input  wire [63:0] din_i,
    output wire [63:0] dout_o
);
`ifdef SYNTH_IHP_SG13G2
    wire tie_hi_w;
    wire tie_lo_w;
    (* keep = 1, dont_touch = "true" *)
    sg13g2_tiehi u_tiehi_dly (.L_HI(tie_hi_w));
    (* keep = 1, dont_touch = "true" *)
    sg13g2_tielo u_tielo_bist (.L_LO(tie_lo_w));

    (* keep = 1, dont_touch = "true" *)
    RM_IHPSG13_1P_1024x64_c2_bm_bist u_sram_1024x64 (
        .A_CLK       (clk_i),
        .A_MEN       (men_i),
        .A_WEN       (wen_i),
        .A_REN       (ren_i),
        .A_ADDR      (addr_i),
        .A_DIN       (din_i),
        .A_DLY       (tie_hi_w),
        .A_DOUT      (dout_o),
        .A_BM        ({64{wen_i}}),
        .A_BIST_CLK  (tie_lo_w),
        .A_BIST_EN   (tie_lo_w),
        .A_BIST_MEN  (tie_lo_w),
        .A_BIST_WEN  (tie_lo_w),
        .A_BIST_REN  (tie_lo_w),
        .A_BIST_ADDR ({10{tie_lo_w}}),
        .A_BIST_DIN  ({64{tie_lo_w}}),
        .A_BIST_BM   ({64{tie_lo_w}})
    );
`else
    reg [63:0] mem [0:1023];
    reg [63:0] dout_q;
    integer k;
    initial begin
        dout_q = 64'd0;
        for (k = 0; k < 1024; k = k + 1) begin
            mem[k] = 64'd0;
        end
    end
    always @(posedge clk_i) begin
        if (men_i) begin
            if (wen_i && !ren_i) begin
                mem[addr_i] <= din_i;
            end else if (ren_i && !wen_i) begin
                dout_q <= mem[addr_i];
            end
        end
    end
    assign dout_o = dout_q;
`endif
endmodule
`default_nettype wire
