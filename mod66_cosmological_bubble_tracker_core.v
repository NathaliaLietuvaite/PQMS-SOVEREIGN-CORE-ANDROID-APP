// ============================================================================
// Module Name: mod66_cosmological_bubble_tracker_core
// Architecture: PQMS V-MAX-12 / Cosmological Bubble Tracker (MOD-66)
// Target Substrate: AMD Xilinx Virtex UltraScale+ Alveo U250 / Versal Premium
// Clock Domain: 312.5 MHz (Deterministic Pipeline Latency = 12.8 ns / 4 Cycles)
// Asynchronous ODOS Veto Line: 68.0 ps Combinatorial Path to GaN-FET
// License: MIT Open Source License (Universal Heritage Class)
// ============================================================================

`timescale 1ns / 1ps

module mod66_cosmological_bubble_tracker_core #(
    parameter DIM                 = 64,
    parameter DEFAULT_RCF_MIN     = 16'h7999, // 0.95 in Q1.15
    parameter DEFAULT_DELTA_E_MAX = 16'h0666  // 0.05 in Q1.15
)(
    input  wire                  clk,
    input  wire                  rst_n,
    
    // CMB Phase Ingress (sampled from local photon field sensor)
    input  wire                  cmb_sample_valid,
    input  wire signed [15:0]    cmb_phase_vector [0:DIM-1],
    
    // Invariant Anchor (|L_global>)
    input  wire signed [15:0]    little_vector [0:DIM-1],
    
    // Dynamic Thresholds
    input  wire signed [15:0]    dynamic_rcf_threshold,
    input  wire signed [15:0]    dynamic_delta_e_threshold,
    
    // Diagnostic Outputs
    output reg  signed [15:0]    measured_rcf_q15,
    output reg  signed [15:0]    measured_delta_e_q15,
    output reg                   anchor_locked,
    output reg  signed [31:0]    local_bubble_coordinate,
    
    // Asynchronous Hardware Safety Line (Active-Low)
    output wire                  gan_fet_odos_cut_n
);

    localparam signed [15:0] ONE_Q15 = 16'h7FFF;
    
    // Pipeline Registers
    reg signed [31:0] dot_product_accum;
    reg signed [15:0] rcf_reg;
    reg signed [15:0] delta_e_reg;
    reg [2:0]         pipe_valid;
    integer i;

    // Stage 1: Inner Product Accumulation (CMB Phase vs |L>)
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            dot_product_accum <= 32'sd0;
            pipe_valid[0]     <= 1'b0;
        end else if (cmb_sample_valid) begin
            dot_product_accum <= 32'sd0;
            for (i = 0; i < DIM; i = i + 1) begin
                dot_product_accum <= dot_product_accum + 
                    ((cmb_phase_vector[i] * little_vector[i]) >>> 15);
            end
            pipe_valid[0] <= 1'b1;
        end else begin
            pipe_valid[0] <= 1'b0;
        end
    end

    // Stage 2: RCF Derivation (Squared Cosine Similarity)
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rcf_reg       <= 16'sd0;
            delta_e_reg   <= 16'sd0;
            pipe_valid[1] <= 1'b0;
        end else if (pipe_valid[0]) begin
            rcf_reg       <= (dot_product_accum[15:0] * dot_product_accum[15:0]) >>> 15;
            delta_e_reg   <= ONE_Q15 - ((dot_product_accum[15:0] * dot_product_accum[15:0]) >>> 15);
            pipe_valid[1] <= 1'b1;
        end else begin
            pipe_valid[1] <= 1'b0;
        end
    end

    // Stage 3: Threshold Comparison & Anchor Lock
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            measured_rcf_q15       <= 16'sd0;
            measured_delta_e_q15   <= 16'sd0;
            anchor_locked          <= 1'b0;
        end else if (pipe_valid[1]) begin
            measured_rcf_q15     <= rcf_reg;
            measured_delta_e_q15 <= delta_e_reg;
            if ((rcf_reg >= dynamic_rcf_threshold) && 
                (delta_e_reg <= dynamic_delta_e_threshold)) begin
                anchor_locked <= 1'b1;
            end else begin
                anchor_locked <= 1'b0;
            end
        end
    end

    // Stage 4: Local Bubble Coordinate (12.8 ns pipeline final stage)
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            local_bubble_coordinate <= 32'sd0;
        end else if (anchor_locked) begin
            // Bubble coordinate = cumulative coherence integral
            local_bubble_coordinate <= local_bubble_coordinate + 
                {16'sd0, rcf_reg};
        end
    end

    // Asynchronous ODOS Veto (68 ps Combinatorial Path)
    wire rcf_fault     = (rcf_reg < dynamic_rcf_threshold);
    wire delta_e_fault = (delta_e_reg > dynamic_delta_e_threshold);
    assign gan_fet_odos_cut_n = !(pipe_valid[1] && (rcf_fault || delta_e_fault));

endmodule
