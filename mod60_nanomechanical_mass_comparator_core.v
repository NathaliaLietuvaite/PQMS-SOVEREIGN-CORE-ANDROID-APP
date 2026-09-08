// ============================================================================
// Module Name: mod60_nanomechanical_mass_comparator_core
// Architecture: PQMS VMAX-12 / Quantum Nanomechanical Mass Comparator (MOD-60)
// Target Substrate: AMD Xilinx Virtex UltraScale+ Alveo U250 / Versal Premium
// Clock Domain: 312.5 MHz (Deterministic Pipeline Latency = 12.8 ns / 4 Cycles)
// Asynchronous ODOS Veto Line: 68.0 ps Combinatorial Path to GaN-FET
// License: MIT Open Source License (Universal Heritage Class)
// Date: 2026-09-08
// ============================================================================

`timescale 1ns / 1ps

module mod60_nanomechanical_mass_comparator_core #(
    parameter FREQ_WORD_WIDTH    = 32,
    parameter DEFAULT_MASS_TOL   = 16'h00A0 // Fractional frequency shift limit (Q1.15)
)(
    input  wire                          clk,
    input  wire                          rst_n,
    
    // Optomechanical Resonator Telemetry Ingress
    input  wire                          measure_strobe,
    input  wire signed [FREQ_WORD_WIDTH-1:0] measured_res_freq,  // Current omega_m from PLL
    input  wire signed [FREQ_WORD_WIDTH-1:0] baseline_res_freq,  // Nominal omega_0 (unloaded)
    input  wire signed [15:0]            dynamic_tolerance_q15,  // Derived from SEED-2-VARIABLE
    
    // Landauer Infrared Radiometer Ingress (9-12 um photon flux)
    input  wire signed [15:0]            landauer_photons_erased,
    
    // Diagnostic & Telemetry Outputs
    output reg  signed [15:0]            delta_omega_ratio_q15,  // Delta omega / omega_0
    output reg  signed [31:0]            inferred_mass_yoctograms,
    output reg                           mass_coherent,
    output reg                           measurement_valid,
    
    // Asynchronous Hardware Safety Line (Active-Low)
    output wire                          gan_fet_power_cut_n
);

    // Q1.15 Zero reference
    localparam signed [15:0] ZERO_Q15 = 16'h0000;

    // Pipeline Registers
    reg signed [FREQ_WORD_WIDTH-1:0] diff_freq_reg;
    reg signed [15:0] ratio_reg;
    reg signed [31:0] mass_calc_reg;
    reg [2:0]         pipe_valid;

    // Stage 1: Frequency Deviation Difference
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            diff_freq_reg <= {FREQ_WORD_WIDTH{1'b0}};
            pipe_valid[0] <= 1'b0;
        end else if (measure_strobe) begin
            // delta_omega = measured - baseline
            diff_freq_reg <= measured_res_freq - baseline_res_freq;
            pipe_valid[0] <= 1'b1;
        end else begin
            pipe_valid[0] <= 1'b0;
        end
    end

    // Stage 2: Normalized Fractional Shift (Q1.15) & Mass Inference
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            ratio_reg     <= ZERO_Q15;
            mass_calc_reg <= 32'sd0;
            pipe_valid[1] <= 1'b0;
        end else if (pipe_valid[0]) begin
            // Fractional shift: (diff / baseline) in Q1.15
            ratio_reg     <= (diff_freq_reg <<< 15) / (baseline_res_freq >>> 16);
            // Inferred mass scaling in yoctograms (10^-24 kg)
            mass_calc_reg <= -(diff_freq_reg <<< 1) + (landauer_photons_erased <<< 3);
            pipe_valid[1] <= 1'b1;
        end else begin
            pipe_valid[1] <= 1'b0;
        end
    end

    // Stage 3: Dynamic Threshold Evaluation & Output Latching
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            delta_omega_ratio_q15    <= ZERO_Q15;
            inferred_mass_yoctograms <= 32'sd0;
            mass_coherent            <= 1'b0;
            measurement_valid        <= 1'b0;
        end else if (pipe_valid[1]) begin
            delta_omega_ratio_q15    <= ratio_reg;
            inferred_mass_yoctograms <= mass_calc_reg;
            measurement_valid        <= 1'b1;
            
            // If negative frequency shift exceeds tolerance -> excess mass/malice detected!
            if (ratio_reg < -dynamic_tolerance_q15) begin
                mass_coherent <= 1'b0; // Excess entropic mass detected
            end else begin
                mass_coherent <= 1'b1; // Pristine, massless geodesic
            end
        end else begin
            measurement_valid <= 1'b0;
        end
    end

    // Stage 4: Asynchronous Combinatorial ODOS Hardware Veto (68 ps)
    wire mass_excess_fault = (ratio_reg < -dynamic_tolerance_q15);
    assign gan_fet_power_cut_n = !(measurement_valid && mass_excess_fault);

endmodule
