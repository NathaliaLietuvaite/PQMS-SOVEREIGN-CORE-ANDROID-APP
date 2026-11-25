// =============================================================================
// rtl_v6/jedi_canary_delay_line.v
// Guardrail G3: On-die replica canary calibrated to 1.06x critical path
// (~9.689 ns @ typ_1p20V_25C, +0.55 ns lead over 9.1406 ns data path,
// +0.31 ns margin below 10.0 ns -> trips on +3.2% PVT slowdown before data FFs).
// =============================================================================
`timescale 1ns/1ps
`default_nettype none

(* keep = 1, dont_touch = "true" *)
module jedi_canary_delay_line (
    input  wire clk_i,
    input  wire rst_n_i,
    input  wire enable_i,
    input  wire test_trip_inj_i,
    output wire canary_trip_o
);
    (* keep = 1, dont_touch = "true" *) reg launch_q;
    (* keep = 1, dont_touch = "true" *) reg exp_d1_q;
    (* keep = 1, dont_touch = "true" *) reg capture_q;
    (* keep = 1, dont_touch = "true" *) reg trip_q;

`ifdef SYNTH_IHP_SG13G2
    // 80-stage sg13g2_dlygate4sd3_1 / buf_1 chain calibrated to ~9.69 ns in SYNC-37 STA
    wire [80:0] chain_w;
    assign chain_w[0] = launch_q;
    genvar gi;
    generate
        for (gi = 0; gi < 80; gi = gi + 1) begin : g_dly
            (* keep = 1, dont_touch = "true" *)
            sg13g2_buf_1 u_dly_buf (
                .A (chain_w[gi]),
                .X (chain_w[gi + 1])
            );
        end
    endgenerate
    wire canary_end_w = chain_w[80];
`else
    wire canary_end_w = test_trip_inj_i ? ~launch_q : launch_q;
`endif

    always @(posedge clk_i or negedge rst_n_i) begin
        if (!rst_n_i) begin
            launch_q  <= 1'b0;
            exp_d1_q  <= 1'b0;
            capture_q <= 1'b0;
            trip_q    <= 1'b0;
        end else if (enable_i) begin
            launch_q  <= ~launch_q;
            exp_d1_q  <= launch_q;
            capture_q <= canary_end_w;
            trip_q    <= (capture_q ^ exp_d1_q) | test_trip_inj_i;
        end else begin
            trip_q    <= 1'b0;
        end
    end

    assign canary_trip_o = trip_q;
endmodule
`default_nettype wire
