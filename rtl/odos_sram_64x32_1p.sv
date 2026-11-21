`default_nettype none

module odos_sram_64x32_1p (
    input  wire        clk_i,
    input  wire        men_i,
    input  wire        wen_i,
    input  wire [4:0]  addr_i,
    input  wire [63:0] wdata_i,
    output logic [63:0] rdata_o
);

`ifdef SYNTH_IHP_SG13G2
    RM_IHPSG13_1P_64x64_c2_bm_bist u_sram_64x64 (
        .A_CLK      (clk_i),
        .A_MEN      (men_i),
        .A_WEN      (men_i & wen_i),
        .A_REN      (men_i & (~wen_i)),
        .A_ADDR     ({1'b0, addr_i}),
        .A_DIN      (wdata_i),
        .A_DLY      (1'b1),
        .A_DOUT     (rdata_o),
        .A_BM       (64'hFFFF_FFFF_FFFF_FFFF),
        .A_BIST_CLK (1'b0),
        .A_BIST_EN  (1'b0),
        .A_BIST_MEN (1'b0),
        .A_BIST_WEN (1'b0),
        .A_BIST_REN (1'b0),
        .A_BIST_ADDR(6'd0),
        .A_BIST_DIN (64'd0),
        .A_BIST_BM  (64'd0)
    );
`else
    logic [63:0] mem [0:31];

    always_ff @(posedge clk_i) begin
        if (men_i) begin
            if (wen_i) begin
                mem[addr_i] <= wdata_i;
            end else begin
                rdata_o <= mem[addr_i];
            end
        end
    end
`endif

endmodule
`default_nettype wire
