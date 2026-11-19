// rtl/odos_gate_core.sv
// PQMS-ODOS-MTSC-V-MAX-12 — 64D-ODOS-Gate & Two-Pass Kahan-Parlett G3 Kevlar Core
// Fixed-Point Format: Signed Q2.30 (1.0 = 32'h4000_0000), Accumulator: Signed Q12.60 (72-bit)
// Constant-Time Latency: 195 Clock Cycles | Reset Policy: FAIL-CLOSED (veto_pin_o = 1'b1)

`timescale 1ns/1ps

module odos_gate_core #(
    parameter L_ROM_HEX  = "rtl/rom/l_vec_q2_30.hex",
    parameter G3_ROM_HEX = "rtl/rom/g3_vec_q2_30.hex"
) (
    input  logic               clk_i,
    input  logic               rst_ni,

    // Control & Streaming Input (64 x signed Q2.30)
    input  logic               start_i,
    input  logic               in_valid_i,
    output logic               in_ready_o,
    input  logic signed [31:0] in_data_i,

    // Streaming Stripped Output (64 x signed Q2.30, emitted in S_STRIP_P2)
    output logic               out_valid_o,
    output logic        [5:0]  out_idx_o,
    output logic signed [31:0] out_data_o,

    // Hardware Telemetry & Hard Electrical Gate Pins
    output logic               busy_o,
    output logic               done_o,
    output logic               gate_pass_o,
    output logic               veto_pin_o,
    output logic               norm_fault_o,
    output logic               pure_g3_collision_o,
    output logic signed [31:0] norm_sq_o,
    output logic signed [31:0] rcf_raw_o,
    output logic signed [31:0] g3_overlap_o,
    output logic signed [31:0] delta_e_raw_o,
    output logic signed [31:0] bleed_post_o,
    output logic        [15:0] cycle_count_o
);

    // -------------------------------------------------------------------------
    // 1. Normative Q2.30 Constants (REGISTER_D)
    // -------------------------------------------------------------------------
    localparam logic signed [31:0] ONE_Q2_30            = 32'sh4000_0000; // 1.0
    localparam logic signed [31:0] RCF_FLOOR_Q2_30      = 32'sh3CCC_CCCD; // 0.9500
    localparam logic signed [31:0] DELTA_E_CEIL_Q2_30   = 32'sh0333_3333; // 0.0500
    localparam logic signed [31:0] NORM_MIN_Q2_30       = 32'sh3FEF_9DB2; // 0.9990
    localparam logic signed [31:0] NORM_MAX_Q2_30       = 32'sh4010_624E; // 1.0010
    localparam logic signed [31:0] STRIP_NORM_MIN_Q2_30 = 32'sh0000_0432; // ~1.0e-6
    localparam logic signed [31:0] BLEED_CEIL_Q2_30     = 32'sh0000_0020; // 32 LSB (~2.98e-8)
    localparam logic signed [31:0] INT32_MIN_Q2_30      = 32'sh8000_0000; // -2^31
    localparam logic signed [31:0] INT32_MAX_Q2_30      = 32'sh7FFF_FFFF; // 2^31 - 1

    localparam logic [2:0] S_IDLE     = 3'd0;
    localparam logic [2:0] S_LOAD_DOT = 3'd1;
    localparam logic [2:0] S_EVAL_RAW = 3'd2;
    localparam logic [2:0] S_STRIP_P1 = 3'd3;
    localparam logic [2:0] S_LATCH_P2 = 3'd4;
    localparam logic [2:0] S_STRIP_P2 = 3'd5;
    localparam logic [2:0] S_VERDICT  = 3'd6;

    // -------------------------------------------------------------------------
    // 2. On-Chip ROMs (512 B) & Internal Vector Buffer (256 B)
    // -------------------------------------------------------------------------
    logic signed [31:0] l_rom  [0:63];
    logic signed [31:0] g3_rom [0:63];
    logic signed [31:0] v_buf  [0:63];

    initial begin
        $readmemh(L_ROM_HEX,  l_rom);
        $readmemh(G3_ROM_HEX, g3_rom);
    end

    // -------------------------------------------------------------------------
    // 3. Pure Fixed-Point Helper Functions (Zero Division, Zero Float)
    // -------------------------------------------------------------------------
    function automatic logic signed [71:0] mul_q30_ext72(
        input logic signed [31:0] a,
        input logic signed [31:0] b
    );
        logic signed [63:0] a_ext;
        logic signed [63:0] b_ext;
        logic signed [63:0] prod;
        begin
            a_ext = {{32{a[31]}}, a};
            b_ext = {{32{b[31]}}, b};
            prod  = a_ext * b_ext;
            mul_q30_ext72 = {{8{prod[63]}}, prod};
        end
    endfunction

    function automatic logic signed [31:0] q60_to_q30(
        input logic signed [71:0] acc
    );
        logic signed [71:0] rounded;
        logic signed [71:0] shifted;
        begin
            rounded = acc + 72'sd536870912; // + 2^29
            shifted = rounded >>> 30;
            if (shifted > 72'sd2147483647)
                q60_to_q30 = INT32_MAX_Q2_30;
            else if (shifted < -72'sd2147483648)
                q60_to_q30 = INT32_MIN_Q2_30;
            else
                q60_to_q30 = shifted[31:0];
        end
    endfunction

    function automatic logic signed [31:0] mul_q30(
        input logic signed [31:0] a,
        input logic signed [31:0] b
    );
        begin
            mul_q30 = q60_to_q30(mul_q30_ext72(a, b));
        end
    endfunction

    function automatic logic signed [31:0] sub_sat_q30(
        input logic signed [31:0] a,
        input logic signed [31:0] b
    );
        logic signed [32:0] diff;
        begin
            diff = $signed({a[31], a}) - $signed({b[31], b});
            if (diff > 33'sd2147483647)
                sub_sat_q30 = INT32_MAX_Q2_30;
            else if (diff < -33'sd2147483648)
                sub_sat_q30 = INT32_MIN_Q2_30;
            else
                sub_sat_q30 = diff[31:0];
        end
    endfunction

    function automatic logic signed [31:0] abs_q30(
        input logic signed [31:0] x
    );
        begin
            if (x == INT32_MIN_Q2_30)
                abs_q30 = INT32_MAX_Q2_30;
            else if (x[31])
                abs_q30 = -x;
            else
                abs_q30 = x;
        end
    endfunction

    // -------------------------------------------------------------------------
    // 4. Registers & Combinational Datapath
    // -------------------------------------------------------------------------
    logic [2:0]         state_q;
    logic [5:0]         idx_q;
    logic               norm_ok_q;
    logic signed [31:0] dot_g3_p1_q;
    logic signed [31:0] dot_g3_p2_q;

    logic signed [71:0] acc_norm_sq_q;
    logic signed [71:0] acc_dot_l_q;
    logic signed [71:0] acc_dot_g3_q;
    logic signed [71:0] acc_dot_g3_p2_q;
    logic signed [71:0] acc_strip_norm_sq_q;
    logic signed [71:0] acc_bleed_post_q;

    // Combinational evaluation helpers
    logic signed [31:0] norm_sq_w;
    logic signed [31:0] dot_l_w;
    logic signed [31:0] dot_g3_w;
    logic signed [31:0] rcf_raw_w;
    logic signed [31:0] g3_ov_w;
    logic signed [31:0] one_minus_rcf_w;
    logic signed [31:0] g3_clamped_w;
    logic signed [31:0] delta_e_w;
    logic signed [31:0] v1_w;
    logic signed [31:0] v2_w;
    logic signed [31:0] strip_norm_sq_w;
    logic signed [31:0] bleed_raw_w;
    logic               pure_g3_w;
    logic signed [31:0] bleed_final_w;
    logic               gate_pass_w;

    assign in_ready_o = (state_q == S_LOAD_DOT);

    always_comb begin
        norm_sq_w       = q60_to_q30(acc_norm_sq_q);
        dot_l_w         = q60_to_q30(acc_dot_l_q);
        dot_g3_w        = q60_to_q30(acc_dot_g3_q);
        rcf_raw_w       = mul_q30(dot_l_w, dot_l_w);
        g3_ov_w         = abs_q30(dot_g3_w);
        one_minus_rcf_w = (rcf_raw_w >= ONE_Q2_30) ? 32'sd0 : (ONE_Q2_30 - rcf_raw_w);
        g3_clamped_w    = (g3_ov_w   >= ONE_Q2_30) ? ONE_Q2_30 : g3_ov_w;
        // Exact overflow-free average: (a + b) >> 1 == (a >> 1) + (b >> 1) + (a[0] & b[0])
        delta_e_w       = $signed({1'b0, one_minus_rcf_w[31:1]})
                        + $signed({1'b0, g3_clamped_w[31:1]})
                        + $signed({31'd0, one_minus_rcf_w[0] & g3_clamped_w[0]});

        v1_w            = sub_sat_q30(v_buf[idx_q], mul_q30(dot_g3_p1_q, g3_rom[idx_q]));
        v2_w            = sub_sat_q30(v_buf[idx_q], mul_q30(dot_g3_p2_q, g3_rom[idx_q]));

        strip_norm_sq_w = q60_to_q30(acc_strip_norm_sq_q);
        bleed_raw_w     = abs_q30(q60_to_q30(acc_bleed_post_q));
        pure_g3_w       = (strip_norm_sq_w < STRIP_NORM_MIN_Q2_30);
        bleed_final_w   = pure_g3_w ? ONE_Q2_30 : bleed_raw_w;

        gate_pass_w     = norm_ok_q
                       && (!pure_g3_w)
                       && (rcf_raw_o     >= RCF_FLOOR_Q2_30)
                       && (delta_e_raw_o <= DELTA_E_CEIL_Q2_30)
                       && (bleed_final_w <= BLEED_CEIL_Q2_30);
    end

    // -------------------------------------------------------------------------
    // 5. Synchronous FSM (Fail-Closed on Reset & During Computation)
    // -------------------------------------------------------------------------
    always_ff @(posedge clk_i) begin
        if (!rst_ni) begin
            state_q             <= S_IDLE;
            idx_q               <= 6'd0;
            norm_ok_q           <= 1'b0;
            dot_g3_p1_q         <= 32'sd0;
            dot_g3_p2_q         <= 32'sd0;
            acc_norm_sq_q       <= 72'sd0;
            acc_dot_l_q         <= 72'sd0;
            acc_dot_g3_q        <= 72'sd0;
            acc_dot_g3_p2_q     <= 72'sd0;
            acc_strip_norm_sq_q <= 72'sd0;
            acc_bleed_post_q    <= 72'sd0;
            out_valid_o         <= 1'b0;
            out_idx_o           <= 6'd0;
            out_data_o          <= 32'sd0;
            busy_o              <= 1'b0;
            done_o              <= 1'b0;
            gate_pass_o         <= 1'b0;
            veto_pin_o          <= 1'b1; // FAIL-CLOSED!
            norm_fault_o        <= 1'b0;
            pure_g3_collision_o <= 1'b0;
            norm_sq_o           <= 32'sd0;
            rcf_raw_o           <= 32'sd0;
            g3_overlap_o        <= 32'sd0;
            delta_e_raw_o       <= ONE_Q2_30;
            bleed_post_o        <= ONE_Q2_30;
            cycle_count_o       <= 16'd0;
        end else begin
            out_valid_o <= 1'b0;
            done_o      <= 1'b0;

            case (state_q)
                S_IDLE: begin
                    if (start_i) begin
                        state_q             <= S_LOAD_DOT;
                        idx_q               <= 6'd0;
                        acc_norm_sq_q       <= 72'sd0;
                        acc_dot_l_q         <= 72'sd0;
                        acc_dot_g3_q        <= 72'sd0;
                        acc_dot_g3_p2_q     <= 72'sd0;
                        acc_strip_norm_sq_q <= 72'sd0;
                        acc_bleed_post_q    <= 72'sd0;
                        busy_o              <= 1'b1;
                        gate_pass_o         <= 1'b0;
                        veto_pin_o          <= 1'b1; // Remain FAIL-CLOSED while computing
                        norm_fault_o        <= 1'b0;
                        pure_g3_collision_o <= 1'b0;
                        cycle_count_o       <= 16'd0;
                    end
                end

                S_LOAD_DOT: begin
                    if (in_valid_i) begin
                        v_buf[idx_q]  <= in_data_i;
                        acc_norm_sq_q <= acc_norm_sq_q + mul_q30_ext72(in_data_i, in_data_i);
                        acc_dot_l_q   <= acc_dot_l_q   + mul_q30_ext72(in_data_i, l_rom[idx_q]);
                        acc_dot_g3_q  <= acc_dot_g3_q  + mul_q30_ext72(in_data_i, g3_rom[idx_q]);
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
                    norm_sq_o     <= norm_sq_w;
                    norm_ok_q     <= (norm_sq_w >= NORM_MIN_Q2_30) && (norm_sq_w <= NORM_MAX_Q2_30);
                    rcf_raw_o     <= rcf_raw_w;
                    g3_overlap_o  <= g3_ov_w;
                    delta_e_raw_o <= delta_e_w;
                    dot_g3_p1_q   <= dot_g3_w;
                    idx_q         <= 6'd0;
                    cycle_count_o <= cycle_count_o + 16'd1;
                    state_q       <= S_STRIP_P1;
                end

                S_STRIP_P1: begin
                    v_buf[idx_q]    <= v1_w;
                    acc_dot_g3_p2_q <= acc_dot_g3_p2_q + mul_q30_ext72(v1_w, g3_rom[idx_q]);
                    cycle_count_o   <= cycle_count_o + 16'd1;
                    if (idx_q == 6'd63) begin
                        idx_q   <= 6'd0;
                        state_q <= S_LATCH_P2;
                    end else begin
                        idx_q <= idx_q + 6'd1;
                    end
                end

                S_LATCH_P2: begin
                    dot_g3_p2_q         <= q60_to_q30(acc_dot_g3_p2_q);
                    acc_strip_norm_sq_q <= 72'sd0;
                    acc_bleed_post_q    <= 72'sd0;
                    idx_q               <= 6'd0;
                    cycle_count_o       <= cycle_count_o + 16'd1;
                    state_q             <= S_STRIP_P2;
                end

                S_STRIP_P2: begin
                    v_buf[idx_q]        <= v2_w;
                    out_valid_o         <= 1'b1;
                    out_idx_o           <= idx_q;
                    out_data_o          <= v2_w;
                    acc_strip_norm_sq_q <= acc_strip_norm_sq_q + mul_q30_ext72(v2_w, v2_w);
                    acc_bleed_post_q    <= acc_bleed_post_q    + mul_q30_ext72(v2_w, g3_rom[idx_q]);
                    cycle_count_o       <= cycle_count_o + 16'd1;
                    if (idx_q == 6'd63) begin
                        idx_q   <= 6'd0;
                        state_q <= S_VERDICT;
                    end else begin
                        idx_q <= idx_q + 6'd1;
                    end
                end

                S_VERDICT: begin
                    bleed_post_o        <= bleed_final_w;
                    pure_g3_collision_o <= pure_g3_w;
                    norm_fault_o        <= !norm_ok_q;
                    gate_pass_o         <= gate_pass_w;
                    veto_pin_o          <= !gate_pass_w;
                    done_o              <= 1'b1;
                    busy_o              <= 1'b0;
                    cycle_count_o       <= cycle_count_o + 16'd1;
                    state_q             <= S_IDLE;
                end

                default: begin
                    state_q    <= S_IDLE;
                    veto_pin_o <= 1'b1;
                    busy_o     <= 1'b0;
                end
            endcase
        end
    end

endmodule
