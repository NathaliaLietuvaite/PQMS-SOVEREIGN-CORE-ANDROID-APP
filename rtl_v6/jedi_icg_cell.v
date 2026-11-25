// =============================================================================
// rtl_v6/jedi_icg_cell.v
// Glitch-free negative-phase latch clock gate wrapping IHP SG13G2 sg13g2_lgcp_1
// Guardrail G3 & G4: (* keep = 1, dont_touch = "true" *)
// =============================================================================
`timescale 1ns/1ps
`default_nettype none

(* keep = 1, dont_touch = "true" *)
module jedi_icg_cell (
    input  wire clk_i,
    input  wire en_i,
    output wire gclk_o
);
`ifdef SYNTH_IHP_SG13G2
    (* keep = 1, dont_touch = "true" *)
    sg13g2_lgcp_1 u_lgcp (
        .GCLK (gclk_o),
        .CLK  (clk_i),
        .GATE (en_i)
    );
`else
    /* verilator lint_off LATCH */
    reg en_latched_q;
    initial begin
        en_latched_q = 1'b0;
    end
    always @(*) begin
        if (!clk_i) begin
            en_latched_q = en_i;
        end
    end
    /* verilator lint_on LATCH */
    assign gclk_o = clk_i & en_latched_q;
`endif
endmodule
`default_nettype wire
