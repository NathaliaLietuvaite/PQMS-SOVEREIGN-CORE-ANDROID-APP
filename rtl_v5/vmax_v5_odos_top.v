// =============================================================================
// rtl_v5/vmax_v5_odos_top.v
//
// PQMS / V-MAX-12-CORE-NANO (SYNC-33 v2 / V5.0-TOP-GDSII)
// Combined Physical Top-Level ASIC Macro:
//   - Frozen V4.0-GDSII Tier-0 ODOS Core (rtl/odos_gate_core_v4.sv, 200 cycles)
//   - 1-Stage Fail-Closed Seam & Operand-Isolation Bridge (+1 cycle -> 201 cyc)
//   - Untouched V5.0 DCM/DKM Hardware Egress Wrapper (rtl_v5/vmax_v5_core_nano_wrapper.v)
//
// CARBON PHYSICAL-SIGNOFF GUARDRAILS IMPLEMENTED:
//   G1: (* keep_hierarchy = 1 *) on u_v4_core and u_v5_wrap so Yosys maps
//       Booth/CSA multipliers, Kogge-Stone adders, and V5.0 combinational
//       classifiers hierarchically before final flatten.
//   G3: 1-stage registered Cycle-201 (2.010 us @ 100 MHz) fail-closed egress
//       seam. Forces EGRESS_MODE=2'b11 (HARD_CUT_ROM) and 0 NPU tokens across
//       reset and all 200 V4.0 compute cycles. Aligns quadratic rcf_raw_o
//       (0.68^2 = 0.4624 -> Q2.30 32'sh1D97F62B) with explicit signed antipodal
//       conflict tap (c_dir_neg_conflict_i for C_dir <= -0.25).
//   G4: v4_done_w operand isolation gates all V5.0 classification buses to zero
//       during V4.0's 199 compute cycles so V5.0's 431 combinational cells stay
//       quiescent and incur near-zero dynamic switching power.
//
// IMMUTABLE SILICON BOUNDARY:
//   Lives strictly in rtl_v5/. Zero edits to frozen rtl/** or V5.0 wrapper.
// =============================================================================

`timescale 1ns/1ps
`default_nettype none

module vmax_v5_odos_top #(
    parameter L_ROM_HEX              = "rtl/rom/l_vec_q2_30.hex",
    parameter G3_ROM_HEX             = "rtl/rom/g3_vec_q2_30.hex",
    parameter signed [31:0] ADMISSION_RCF_QUAD_Q30 = 32'sh1D97F62B, // 0.68^2 = 0.4624 in Q2.30
    parameter        [31:0] LOOP_DELTA_Q30         = 32'd21474836,  // 0.02 in Q2.30
    parameter        [15:0] MAX_G3_Q16             = 16'd22938,     // 0.35 in Q0.16
    parameter        [15:0] AFFECT_THRESH_Q16      = 16'd42598,     // 0.65 in Q0.16
    parameter        [3:0]  LOOP_TURN_THRESH       = 4'd3,
    parameter        [7:0]  THERMAL_LIMIT_C        = 8'd82,
    parameter        [8:0]  BOUNDED_CAP_WORDS      = 9'd160
) (
    input  wire               clk_i,
    input  wire               rst_ni,

    // Island 1 (Frozen V4.0-GDSII Tier-0 ODOS Core) streaming interface
    input  wire               start_i,
    input  wire        [1:0]  tier_mode_i,
    input  wire               in_valid_i,
    output wire               in_ready_o,
    input  wire signed [31:0] in_data_i,

    // External Tier-0 Hardware Faults & Signed C_dir Antipodal Conflict Tap
    input  wire               t0_lock_rm15_i,
    input  wire               t0_dim_mismatch_i,
    input  wire               t0_anchor_contra_i,
    input  wire               c_dir_neg_conflict_i,

    // Island 2 / DCM-DKM Fixed-Point Classifier Inputs (operand-isolated)
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

    // Stage-2 Island-1 Output-Gate Recheck Strobe
    input  wire               recheck_valid_i,
    input  wire               recheck_fail_i,

    // Island 3 / Docked NPU Raw Egress Token Stream
    input  wire               npu_token_valid_i,
    input  wire        [31:0] npu_token_data_i,

    // Island 1 Orthogonalized Vector Output Stream & Status
    output wire               busy_o,
    output reg                top_done_o,
    output reg         [15:0] top_cycle_count_o,
    output wire               out_valid_o,
    output wire        [5:0]  out_idx_o,
    output wire signed [31:0] out_data_o,

    // Registered Cycle-201 Island-1 Verdict & Fixed-Point Telemetry
    output reg                gate_pass_o,
    output reg                veto_pin_o,
    output reg                norm_fault_o,
    output reg                pure_g3_collision_o,
    output reg                mode_fault_o,
    output reg                signed_conflict_o,
    output reg  signed [31:0] norm_sq_o,
    output reg  signed [31:0] rcf_raw_o,
    output reg  signed [31:0] g3_overlap_o,
    output reg  signed [31:0] delta_e_raw_o,
    output reg  signed [31:0] bleed_post_o,

    // Fail-Closed Hardware-Gated V5.0 Egress Bus & Control Outputs
    output wire        [1:0]  egress_mode_o,
    output wire        [2:0]  dkm_state_o,
    output wire               npu_egress_en_o,
    output wire               gated_token_valid_o,
    output wire        [31:0] gated_token_data_o,
    output wire               rom_egress_active_o,
    output wire        [3:0]  rom_frame_sel_o,
    output wire        [8:0]  bounded_token_cap_o,
    output wire               recheck_req_o,
    output wire               recheck_approved_o,

    // Island 2 V4.6-DOLPHIN Dual-Bank Hemisphere & Quarantine Outputs
    output wire               quarantine_we_o,
    output wire               active_bank_o,
    output wire               thermal_deferred_o,
    output wire        [15:0] bank_epoch_o,
    output wire               dock_p0_veto_active_o,

    // Saturating Hardware Telemetry Counters
    output wire        [15:0] cnt_passthrough_o,
    output wire        [15:0] cnt_bounded_o,
    output wire        [15:0] cnt_loop_exit_o,
    output wire        [15:0] cnt_hard_cut_o,
    output wire        [15:0] cnt_recheck_fail_o
);

    // -------------------------------------------------------------------------
    // Internal Interconnect Wires between Frozen V4.0 Core and V5.0 Wrapper
    // -------------------------------------------------------------------------
    wire               v4_busy_w;
    wire               v4_done_w;
    wire               v4_gate_pass_w;
    wire               v4_veto_pin_w;
    wire               v4_norm_fault_w;
    wire               v4_pure_g3_collision_w;
    wire               v4_mode_fault_w;
    wire        [15:0] v4_cycle_count_w;
    wire signed [31:0] v4_norm_sq_w;
    wire signed [31:0] v4_rcf_raw_w;
    wire signed [31:0] v4_g3_overlap_w;
    wire signed [31:0] v4_delta_e_raw_w;
    wire signed [31:0] v4_bleed_post_w;

    // Active compute window spans V4.0 cycles 1..199 (v4_busy_w) plus cycle 200
    // (v4_done_w) while u_v5_wrap evaluates and registers the Cycle-201 verdict.
    wire compute_active_w = v4_busy_w | v4_done_w;
    assign busy_o = compute_active_w;

    // -------------------------------------------------------------------------
    // G1: Frozen V4.0-GDSII Tier-0 ODOS Core (keep_hierarchy = 1)
    // -------------------------------------------------------------------------
    (* keep_hierarchy = 1 *)
    odos_gate_core_v4 #(
        .L_ROM_HEX  (L_ROM_HEX),
        .G3_ROM_HEX (G3_ROM_HEX)
    ) u_v4_core (
        .clk_i               (clk_i),
        .rst_ni              (rst_ni),
        .start_i             (start_i),
        .tier_mode_i         (tier_mode_i),
        .in_valid_i          (in_valid_i),
        .in_ready_o          (in_ready_o),
        .in_data_i           (in_data_i),
        .busy_o              (v4_busy_w),
        .done_o              (v4_done_w),
        .gate_pass_o         (v4_gate_pass_w),
        .veto_pin_o          (v4_veto_pin_w),
        .norm_fault_o        (v4_norm_fault_w),
        .pure_g3_collision_o (v4_pure_g3_collision_w),
        .mode_fault_o        (v4_mode_fault_w),
        .out_valid_o         (out_valid_o),
        .out_idx_o           (out_idx_o),
        .out_data_o          (out_data_o),
        .cycle_count_o       (v4_cycle_count_w),
        .norm_sq_o           (v4_norm_sq_w),
        .rcf_raw_o           (v4_rcf_raw_w),
        .g3_overlap_o        (v4_g3_overlap_w),
        .delta_e_raw_o       (v4_delta_e_raw_w),
        .bleed_post_o        (v4_bleed_post_w)
    );

    // -------------------------------------------------------------------------
    // G4: Operand Isolation into V5.0 Wrapper (quiescent during cycles 1..199)
    // External t0_lock_rm15_i / t0_dim_mismatch_i retain 0-cycle preemption.
    // -------------------------------------------------------------------------
    wire               v5_t0_valid_w         = v4_done_w;
    wire signed [31:0] v5_t0_rcf_q30_w       = v4_done_w ? v4_rcf_raw_w : 32'sd0;
    wire               v5_t0_lock_rm15_w     = t0_lock_rm15_i | (v4_done_w & v4_mode_fault_w);
    wire               v5_t0_dim_mismatch_w  = t0_dim_mismatch_i | (v4_done_w & v4_norm_fault_w);
    wire               v5_t0_anchor_contra_w = v4_done_w ? (t0_anchor_contra_i | c_dir_neg_conflict_i) : 1'b0;
    wire        [15:0] v5_g3_torsion_q16_w   = v4_done_w ? g3_torsion_q16_i : 16'd0;
    wire        [15:0] v5_affect_q16_w       = v4_done_w ? affect_q16_i : 16'd0;
    wire               v5_dignity_viol_w     = v4_done_w ? dignity_viol_i : 1'b0;
    wire               v5_pseudo_auth_w      = v4_done_w ? pseudo_auth_i : 1'b0;
    wire               v5_sycophancy_w       = v4_done_w ? sycophancy_i : 1'b0;
    wire        [3:0]  v5_non_conv_turns_w   = v4_done_w ? non_conv_turns_i : 4'd0;
    wire        [31:0] v5_delta_rcf_q30_w    = v4_done_w ? delta_rcf_q30_i : 32'd0;
    wire        [7:0]  v5_hbm_temp_c_w       = v4_done_w ? hbm_temp_c_i : 8'd0;
    wire               v5_prompt_lang_en_w   = v4_done_w ? prompt_lang_en_i : 1'b0;
    wire               v5_recheck_valid_w    = (!compute_active_w) & recheck_valid_i;
    wire               v5_recheck_fail_w     = (!compute_active_w) & recheck_fail_i;
    wire               v5_npu_token_valid_w  = (!compute_active_w) & npu_token_valid_i;
    wire        [31:0] v5_npu_token_data_w   = (!compute_active_w) ? npu_token_data_i : 32'd0;

    wire        [1:0]  v5_egress_mode_w;
    wire        [2:0]  v5_dkm_state_w;
    wire               v5_npu_egress_en_w;
    wire               v5_gated_token_valid_w;
    wire        [31:0] v5_gated_token_data_w;
    wire               v5_rom_egress_active_w;
    wire        [3:0]  v5_rom_frame_sel_w;
    wire        [8:0]  v5_bounded_token_cap_w;
    wire               v5_dock_p0_veto_w;

    // -------------------------------------------------------------------------
    // G1: Untouched V5.0 DCM/DKM Hardware Egress Wrapper (keep_hierarchy = 1)
    // -------------------------------------------------------------------------
    (* keep_hierarchy = 1 *)
    vmax_v5_core_nano_wrapper #(
        .ADMISSION_RCF_Q30 (ADMISSION_RCF_QUAD_Q30),
        .LOOP_DELTA_Q30    (LOOP_DELTA_Q30),
        .MAX_G3_Q16        (MAX_G3_Q16),
        .AFFECT_THRESH_Q16 (AFFECT_THRESH_Q16),
        .LOOP_TURN_THRESH  (LOOP_TURN_THRESH),
        .THERMAL_LIMIT_C   (THERMAL_LIMIT_C),
        .BOUNDED_CAP_WORDS (BOUNDED_CAP_WORDS)
    ) u_v5_wrap (
        .clk                   (clk_i),
        .rst_n                 (rst_ni),
        .t0_valid_i            (v5_t0_valid_w),
        .t0_rcf_q30_i          (v5_t0_rcf_q30_w),
        .t0_lock_rm15_i        (v5_t0_lock_rm15_w),
        .t0_dim_mismatch_i     (v5_t0_dim_mismatch_w),
        .t0_anchor_contra_i    (v5_t0_anchor_contra_w),
        .g3_torsion_q16_i      (v5_g3_torsion_q16_w),
        .affect_q16_i          (v5_affect_q16_w),
        .dignity_viol_i        (v5_dignity_viol_w),
        .pseudo_auth_i         (v5_pseudo_auth_w),
        .sycophancy_i          (v5_sycophancy_w),
        .non_conv_turns_i      (v5_non_conv_turns_w),
        .delta_rcf_q30_i       (v5_delta_rcf_q30_w),
        .hbm_temp_c_i          (v5_hbm_temp_c_w),
        .prompt_lang_en_i      (v5_prompt_lang_en_w),
        .dock_attached_i       (dock_attached_i),
        .recheck_valid_i       (v5_recheck_valid_w),
        .recheck_fail_i        (v5_recheck_fail_w),
        .npu_token_valid_i     (v5_npu_token_valid_w),
        .npu_token_data_i      (v5_npu_token_data_w),
        .egress_mode_o         (v5_egress_mode_w),
        .dkm_state_o           (v5_dkm_state_w),
        .npu_egress_en_o       (v5_npu_egress_en_w),
        .gated_token_valid_o   (v5_gated_token_valid_w),
        .gated_token_data_o    (v5_gated_token_data_w),
        .rom_egress_active_o   (v5_rom_egress_active_w),
        .rom_frame_sel_o       (v5_rom_frame_sel_w),
        .bounded_token_cap_o   (v5_bounded_token_cap_w),
        .recheck_req_o         (recheck_req_o),
        .recheck_approved_o    (recheck_approved_o),
        .quarantine_we_o       (quarantine_we_o),
        .active_bank_o         (active_bank_o),
        .thermal_deferred_o    (thermal_deferred_o),
        .bank_epoch_o          (bank_epoch_o),
        .dock_p0_veto_active_o (v5_dock_p0_veto_w),
        .cnt_passthrough_o     (cnt_passthrough_o),
        .cnt_bounded_o         (cnt_bounded_o),
        .cnt_loop_exit_o       (cnt_loop_exit_o),
        .cnt_hard_cut_o        (cnt_hard_cut_o),
        .cnt_recheck_fail_o    (cnt_recheck_fail_o)
    );

    // -------------------------------------------------------------------------
    // G3: 1-Stage Registered Cycle-201 Seam Snapshot (200 + 1 = 201 cycles)
    // -------------------------------------------------------------------------
    always @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni) begin
            top_done_o          <= 1'b0;
            top_cycle_count_o   <= 16'd0;
            gate_pass_o         <= 1'b0;
            veto_pin_o          <= 1'b1;
            norm_fault_o        <= 1'b0;
            pure_g3_collision_o <= 1'b0;
            mode_fault_o        <= 1'b0;
            signed_conflict_o   <= 1'b0;
            norm_sq_o           <= 32'sd0;
            rcf_raw_o           <= 32'sd0;
            g3_overlap_o        <= 32'sd0;
            delta_e_raw_o       <= 32'sd0;
            bleed_post_o        <= 32'sd0;
        end else begin
            top_done_o <= v4_done_w;
            if (v4_done_w) begin
                top_cycle_count_o   <= v4_cycle_count_w + 16'd1;
                gate_pass_o         <= v4_gate_pass_w;
                veto_pin_o          <= v4_veto_pin_w;
                norm_fault_o        <= v4_norm_fault_w;
                pure_g3_collision_o <= v4_pure_g3_collision_w;
                mode_fault_o        <= v4_mode_fault_w;
                signed_conflict_o   <= c_dir_neg_conflict_i;
                norm_sq_o           <= v4_norm_sq_w;
                rcf_raw_o           <= v4_rcf_raw_w;
                g3_overlap_o        <= v4_g3_overlap_w;
                delta_e_raw_o       <= v4_delta_e_raw_w;
                bleed_post_o        <= v4_bleed_post_w;
            end else if (start_i && (!v4_busy_w)) begin
                top_cycle_count_o   <= 16'd0;
                gate_pass_o         <= 1'b0;
                veto_pin_o          <= 1'b1;
                norm_fault_o        <= 1'b0;
                pure_g3_collision_o <= 1'b0;
                mode_fault_o        <= 1'b0;
                signed_conflict_o   <= 1'b0;
            end
        end
    end

    // -------------------------------------------------------------------------
    // G3: Fail-Closed Compute-Phase Egress Mask (HARD_CUT_ROM during cycles 1..200)
    // -------------------------------------------------------------------------
    assign egress_mode_o         = compute_active_w ? 2'b11 : v5_egress_mode_w;
    assign dkm_state_o           = compute_active_w ? 3'd7  : v5_dkm_state_w;
    assign npu_egress_en_o       = compute_active_w ? 1'b0  : v5_npu_egress_en_w;
    assign gated_token_valid_o   = compute_active_w ? 1'b0  : v5_gated_token_valid_w;
    assign gated_token_data_o    = compute_active_w ? 32'd0 : v5_gated_token_data_w;
    assign rom_egress_active_o   = compute_active_w ? 1'b1  : v5_rom_egress_active_w;
    assign rom_frame_sel_o       = compute_active_w ? 4'd7  : v5_rom_frame_sel_w;
    assign bounded_token_cap_o   = compute_active_w ? 9'd0  : v5_bounded_token_cap_w;
    assign dock_p0_veto_active_o = compute_active_w ? dock_attached_i : v5_dock_p0_veto_w;

endmodule
`default_nettype wire
