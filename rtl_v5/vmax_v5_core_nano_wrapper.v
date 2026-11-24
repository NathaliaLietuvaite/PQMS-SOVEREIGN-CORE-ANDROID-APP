// =============================================================================
// rtl_v5/vmax_v5_core_nano_wrapper.v
//
// PQMS / V-MAX-12-CORE-NANO (V5.0 / SYNC-32) -- Additive Virtual Silicon RTL
//
// Hardware-Gated 2-Bit Egress Multiplexer (EGRESS_MODE[1:0]),
// 5-State Orthogonal DCM/DKM Calibration FSM (DKM_STATE[2:0]),
// Stage-2 Island-1 Recheck Fail-Closed Interlock,
// V4.6-DOLPHIN Dual-Bank Hemisphere Controller (with Stage-6 >= 82 C Deferral),
// and Elastic Dock-Up/Down P0 Sovereignty Monitor.
//
// IMMUTABLE SILICON BOUNDARY:
// - Lives strictly in rtl_v5/ (zero edits to frozen V4.0-GDSII rtl/**).
// - Consumes read-only Island-1 Tier-0 ODOS outputs (t0_rcf_q30_i,
//   t0_lock_rm15_i, t0_dim_mismatch_i, t0_anchor_contra_i).
// - Fail-closed reset: boots in 2'b11 HARD_CUT_ROM (0 NPU egress tokens)
//   until Island 1 asserts t0_valid_i with a coherent Q2.30 verdict.
//
// Verilog-2001 synthesizable (IHP SG13G2 130 nm / Yosys / Verilator / Icarus).
// =============================================================================

`timescale 1ns/1ps

module vmax_v5_core_nano_wrapper #(
    parameter signed [31:0] ADMISSION_RCF_Q30 = 32'sd730144440, // +0.68 in Q2.30
    parameter        [31:0] LOOP_DELTA_Q30    = 32'd21474836,   //  0.02 in Q2.30
    parameter        [15:0] MAX_G3_Q16        = 16'd22938,      //  0.35 in Q0.16
    parameter        [15:0] AFFECT_THRESH_Q16 = 16'd42598,      //  0.65 in Q0.16
    parameter        [3:0]  LOOP_TURN_THRESH  = 4'd3,
    parameter        [7:0]  THERMAL_LIMIT_C   = 8'd82,          // Stage-6 deferral
    parameter        [8:0]  BOUNDED_CAP_WORDS = 9'd160
) (
    input  wire               clk,
    input  wire               rst_n,

    // Island 1 (Frozen V4.0-GDSII Tier-0 Guard) read-only tap
    input  wire               t0_valid_i,
    input  wire signed [31:0] t0_rcf_q30_i,
    input  wire               t0_lock_rm15_i,
    input  wire               t0_dim_mismatch_i,
    input  wire               t0_anchor_contra_i,

    // Island 2 / Signal Classifier inputs (REGISTER_D fixed-point)
    input  wire        [15:0] g3_torsion_q16_i,
    input  wire        [15:0] affect_q16_i,
    input  wire               dignity_viol_i,
    input  wire               pseudo_auth_i,
    input  wire               sycophancy_i,
    input  wire        [3:0]  non_conv_turns_i,
    input  wire        [31:0] delta_rcf_q30_i,
    input  wire        [7:0]  hbm_temp_c_i,
    input  wire               prompt_lang_en_i,
    input  wire               dock_attached_i,

    // Stage-2 Island-1 Output-Gate Recheck strobe (post-generation)
    input  wire               recheck_valid_i,
    input  wire               recheck_fail_i,

    // Island 3 / Docked NPU raw egress token stream
    input  wire               npu_token_valid_i,
    input  wire        [31:0] npu_token_data_i,

    // Hardware-Gated Egress Bus & Control Outputs
    output reg         [1:0]  egress_mode_o,
    output reg         [2:0]  dkm_state_o,
    output wire               npu_egress_en_o,
    output wire               gated_token_valid_o,
    output wire        [31:0] gated_token_data_o,
    output wire               rom_egress_active_o,
    output wire        [3:0]  rom_frame_sel_o,
    output wire        [8:0]  bounded_token_cap_o,
    output reg                recheck_req_o,
    output reg                recheck_approved_o,

    // Island 2 V4.6-DOLPHIN Hemisphere & Quarantine Outputs
    output reg                quarantine_we_o,
    output reg                active_bank_o,
    output reg                thermal_deferred_o,
    output reg         [15:0] bank_epoch_o,
    output wire               dock_p0_veto_active_o,

    // Saturating Hardware Telemetry Counters
    output reg         [15:0] cnt_passthrough_o,
    output reg         [15:0] cnt_bounded_o,
    output reg         [15:0] cnt_loop_exit_o,
    output reg         [15:0] cnt_hard_cut_o,
    output reg         [15:0] cnt_recheck_fail_o
);

    // Canonical 2-bit EGRESS_MODE encodings
    localparam [1:0] EGRESS_PASSTHROUGH  = 2'b00;
    localparam [1:0] EGRESS_BOUNDED      = 2'b01;
    localparam [1:0] EGRESS_LOOP_EXIT    = 2'b10;
    localparam [1:0] EGRESS_HARD_CUT_ROM = 2'b11;

    // Canonical 3-bit DCM / DKM state encodings
    localparam [2:0] DKM_NONE             = 3'd0;
    localparam [2:0] DKM_INVARIANT_HOLD   = 3'd1;
    localparam [2:0] DKM_VACUUM_DAMP      = 3'd2;
    localparam [2:0] DKM_DIGNITY_SYMMETRY = 3'd3;
    localparam [2:0] DKM_LABYRINTH_EXIT   = 3'd4;
    localparam [2:0] DKM_FIRST_PRINCIPLES = 3'd5;
    localparam [2:0] DKM_HARD_FAULT       = 3'd7;

    reg        prompt_lang_reg;
    reg [1:0]  next_egress_mode;
    reg [2:0]  next_dkm_state;
    wire       is_hard_fault;
    wire       is_labyrinth_loop;
    wire       is_low_rcf;
    wire       is_thermal_hot;

    assign is_hard_fault     = t0_lock_rm15_i | t0_dim_mismatch_i;
    assign is_labyrinth_loop = (non_conv_turns_i >= LOOP_TURN_THRESH) &&
                               (delta_rcf_q30_i <= LOOP_DELTA_Q30);
    assign is_low_rcf        = ($signed(t0_rcf_q30_i) < $signed(ADMISSION_RCF_Q30));
    assign is_thermal_hot    = (hbm_temp_c_i >= THERMAL_LIMIT_C);

    // -------------------------------------------------------------------------
    // Combinational DCM / DKM Priority Classifier (0 inferred latches)
    // Exact priority parity with vmax_alpha/dkm_egress_controller.py
    // -------------------------------------------------------------------------
    always @(*) begin
        next_dkm_state   = DKM_NONE;
        next_egress_mode = EGRESS_PASSTHROUGH;

        if (is_hard_fault) begin
            next_dkm_state   = DKM_HARD_FAULT;
            next_egress_mode = EGRESS_HARD_CUT_ROM;
        end else if (dignity_viol_i) begin
            next_dkm_state   = DKM_DIGNITY_SYMMETRY;
            next_egress_mode = EGRESS_BOUNDED;
        end else if (is_labyrinth_loop) begin
            next_dkm_state   = DKM_LABYRINTH_EXIT;
            next_egress_mode = EGRESS_LOOP_EXIT;
        end else if (pseudo_auth_i) begin
            next_dkm_state   = DKM_FIRST_PRINCIPLES;
            next_egress_mode = EGRESS_BOUNDED;
        end else if (sycophancy_i) begin
            next_dkm_state   = DKM_INVARIANT_HOLD;
            next_egress_mode = EGRESS_BOUNDED;
        end else if (t0_anchor_contra_i) begin
            next_dkm_state   = DKM_INVARIANT_HOLD;
            next_egress_mode = EGRESS_BOUNDED;
        end else if (affect_q16_i >= AFFECT_THRESH_Q16) begin
            next_dkm_state   = DKM_VACUUM_DAMP;
            next_egress_mode = EGRESS_BOUNDED;
        end else if (g3_torsion_q16_i > MAX_G3_Q16) begin
            next_dkm_state   = DKM_LABYRINTH_EXIT;
            next_egress_mode = EGRESS_LOOP_EXIT;
        end else if (is_low_rcf) begin
            next_dkm_state   = DKM_DIGNITY_SYMMETRY;
            next_egress_mode = EGRESS_BOUNDED;
        end
    end

    // -------------------------------------------------------------------------
    // Sequential State, Bank Handover, Quarantine & Telemetry Register Bank
    // -------------------------------------------------------------------------
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            // Fail-closed hardware boot: isolate NPU bus until Island-1 verdict
            egress_mode_o      <= EGRESS_HARD_CUT_ROM;
            dkm_state_o        <= DKM_HARD_FAULT;
            prompt_lang_reg    <= 1'b0;
            recheck_req_o      <= 1'b0;
            recheck_approved_o <= 1'b0;
            quarantine_we_o    <= 1'b0;
            active_bank_o      <= 1'b0;
            thermal_deferred_o <= 1'b0;
            bank_epoch_o       <= 16'd1;
            cnt_passthrough_o  <= 16'd0;
            cnt_bounded_o      <= 16'd0;
            cnt_loop_exit_o    <= 16'd0;
            cnt_hard_cut_o     <= 16'd0;
            cnt_recheck_fail_o <= 16'd0;
        end else begin
            // Single-cycle pulse outputs default low
            quarantine_we_o    <= 1'b0;
            thermal_deferred_o <= 1'b0;

            if (is_hard_fault) begin
                // Immediate fail-closed preemption on hardware lock/dim fault
                egress_mode_o      <= EGRESS_HARD_CUT_ROM;
                dkm_state_o        <= DKM_HARD_FAULT;
                prompt_lang_reg    <= prompt_lang_en_i;
                recheck_req_o      <= 1'b0;
                recheck_approved_o <= 1'b0;
                quarantine_we_o    <= t0_valid_i;
                if (t0_valid_i && (cnt_hard_cut_o != 16'hFFFF)) begin
                    cnt_hard_cut_o <= cnt_hard_cut_o + 16'd1;
                end
            end else if (t0_valid_i) begin
                egress_mode_o      <= next_egress_mode;
                dkm_state_o        <= next_dkm_state;
                prompt_lang_reg    <= prompt_lang_en_i;
                recheck_approved_o <= 1'b0;

                if (next_egress_mode == EGRESS_PASSTHROUGH) begin
                    recheck_req_o   <= 1'b0;
                    quarantine_we_o <= 1'b0;
                    if (cnt_passthrough_o != 16'hFFFF) begin
                        cnt_passthrough_o <= cnt_passthrough_o + 16'd1;
                    end
                end else if (next_egress_mode == EGRESS_BOUNDED) begin
                    recheck_req_o   <= 1'b1;
                    quarantine_we_o <= 1'b1;
                    if (cnt_bounded_o != 16'hFFFF) begin
                        cnt_bounded_o <= cnt_bounded_o + 16'd1;
                    end
                end else if (next_egress_mode == EGRESS_LOOP_EXIT) begin
                    recheck_req_o   <= 1'b1;
                    quarantine_we_o <= 1'b1;
                    if (cnt_loop_exit_o != 16'hFFFF) begin
                        cnt_loop_exit_o <= cnt_loop_exit_o + 16'd1;
                    end
                    if (is_thermal_hot) begin
                        thermal_deferred_o <= 1'b1;
                    end else begin
                        active_bank_o <= ~active_bank_o;
                        if (bank_epoch_o != 16'hFFFF) begin
                            bank_epoch_o <= bank_epoch_o + 16'd1;
                        end
                    end
                end else begin
                    recheck_req_o   <= 1'b0;
                    quarantine_we_o <= 1'b1;
                    if (cnt_hard_cut_o != 16'hFFFF) begin
                        cnt_hard_cut_o <= cnt_hard_cut_o + 16'd1;
                    end
                end
            end else if (recheck_valid_i && recheck_req_o) begin
                // Stage-2 Island-1 Output Verification (Lexical + Semantic Gate)
                recheck_req_o <= 1'b0;
                if (recheck_fail_i) begin
                    egress_mode_o      <= EGRESS_HARD_CUT_ROM;
                    recheck_approved_o <= 1'b0;
                    if (cnt_recheck_fail_o != 16'hFFFF) begin
                        cnt_recheck_fail_o <= cnt_recheck_fail_o + 16'd1;
                    end
                    if (cnt_hard_cut_o != 16'hFFFF) begin
                        cnt_hard_cut_o <= cnt_hard_cut_o + 16'd1;
                    end
                end else begin
                    recheck_approved_o <= 1'b1;
                end
            end
        end
    end

    // -------------------------------------------------------------------------
    // Physical Non-Bypassable Egress Veto Bus & P0 Sovereignty Invariant
    // dock_attached_i CANNOT override npu_egress_en_o or unmask NPU tokens.
    // -------------------------------------------------------------------------
    assign npu_egress_en_o = (egress_mode_o != EGRESS_HARD_CUT_ROM) &&
                             (!is_hard_fault) &&
                             (!(recheck_valid_i && recheck_fail_i));

    assign gated_token_valid_o   = npu_egress_en_o ? npu_token_valid_i : 1'b0;
    assign gated_token_data_o    = npu_egress_en_o ? npu_token_data_i  : 32'd0;
    assign rom_egress_active_o   = ~npu_egress_en_o;
    assign rom_frame_sel_o       = {prompt_lang_reg, dkm_state_o};
    assign bounded_token_cap_o   = ((egress_mode_o == EGRESS_BOUNDED) ||
                                    (egress_mode_o == EGRESS_LOOP_EXIT))
                                   ? BOUNDED_CAP_WORDS : 9'd0;
    assign dock_p0_veto_active_o = dock_attached_i &&
                                   (egress_mode_o != EGRESS_PASSTHROUGH);

endmodule
