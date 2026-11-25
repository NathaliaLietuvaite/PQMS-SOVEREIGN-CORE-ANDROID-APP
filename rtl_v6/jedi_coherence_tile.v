// =============================================================================
// rtl_v6/jedi_coherence_tile.v
// WP-1.1: Single V6.0-CORE-JEDI Coherence Tile Macro
// - Wraps frozen odos_gate_core_v4 + untouched vmax_v5_core_nano_wrapper
// - Internal root sg13g2_lgcp_1 ICG (jedi_icg_cell) + input antenna diodes (G2/G3)
// - Dedicated 64-word Q2.30 x Q2.30 -> signed [74:0] Q14.60 dot-product unit
//   with sticky STATE_DONE output hold (dot_out_o)
// - Registered 1-cycle Kagome neighbor ports (North / East / Diag), AND-clamped idle
// =============================================================================
`timescale 1ns/1ps
`default_nettype none

module jedi_coherence_tile #(
    parameter L_ROM_HEX  = "rtl/rom/l_vec_q2_30.hex",
    parameter G3_ROM_HEX = "rtl/rom/g3_vec_q2_30.hex"
) (
    input  wire               clk_i,
    input  wire               rst_n_i,
    input  wire               tile_clk_en_i,
    input  wire               start_i,
    input  wire               clear_sticky_i,
    input  wire               vec_valid_i,
    input  wire signed [31:0] x_word_i,
    input  wire signed [31:0] w_word_i,
    input  wire               od_probe_en_i,
    input  wire        [1:0]  tier_mode_i,
    input  wire               dock_attached_i,
    input  wire               tile_fault_inj_i,
    input  wire               tile_hang_inj_i,

    // Kagome 1-cycle neighbor ports
    input  wire        [31:0] kag_north_in_i,
    input  wire        [31:0] kag_east_in_i,
    input  wire        [31:0] kag_diag_in_i,
    output wire        [31:0] kag_north_out_o,
    output wire        [31:0] kag_east_out_o,
    output wire        [31:0] kag_diag_out_o,

    // Sticky dot-product & tile status outputs
    output wire               tile_busy_o,
    output wire               tile_done_sticky_o,
    output wire               tile_fault_o,
    output wire signed [74:0] dot_out_o,
    output wire        [1:0]  v5_egress_mode_o,
    output wire        [2:0]  v5_dkm_state_o
);

    // G2: Macro-internal input antenna protection diodes on boundary control pins
    jedi_ant_diode u_ant_clken (.pin_i(tile_clk_en_i));
    jedi_ant_diode u_ant_start (.pin_i(start_i));
    jedi_ant_diode u_ant_clr   (.pin_i(clear_sticky_i));
    jedi_ant_diode u_ant_vld   (.pin_i(vec_valid_i));

    // G3/G4: Macro-internal root sg13g2_lgcp_1 clock gate
    wire gclk_w;
    jedi_icg_cell u_tile_icg (
        .clk_i  (clk_i),
        .en_i   (tile_clk_en_i),
        .gclk_o (gclk_w)
    );

    // -------------------------------------------------------------------------
    // Frozen V4.0 Tier-0 ODOS Core + Untouched V5.0 Wrapper (operand-isolated)
    // -------------------------------------------------------------------------
    wire               v4_start_w    = start_i & od_probe_en_i;
    wire               v4_in_valid_w = vec_valid_i & od_probe_en_i;
    wire signed [31:0] v4_in_data_w  = od_probe_en_i ? x_word_i : 32'sd0;

    wire               v4_in_ready_w;
    wire               v4_busy_w;
    wire               v4_done_w;
    wire               v4_gate_pass_w;
    wire               v4_veto_pin_w;
    wire               v4_norm_fault_w;
    wire               v4_pure_g3_w;
    wire               v4_mode_fault_w;
    wire               v4_out_valid_w;
    wire        [5:0]  v4_out_idx_w;
    wire signed [31:0] v4_out_data_w;
    wire        [15:0] v4_cyc_cnt_w;
    wire signed [31:0] v4_norm_sq_w;
    wire signed [31:0] v4_rcf_raw_w;
    wire signed [31:0] v4_g3_ov_w;
    wire signed [31:0] v4_de_raw_w;
    wire signed [31:0] v4_bleed_w;

    (* keep_hierarchy = 1 *)
    odos_gate_core_v4 #(
        .L_ROM_HEX  (L_ROM_HEX),
        .G3_ROM_HEX (G3_ROM_HEX)
    ) u_v4_core (
        .clk_i               (gclk_w),
        .rst_ni              (rst_n_i),
        .start_i             (v4_start_w),
        .tier_mode_i         (tier_mode_i),
        .in_valid_i          (v4_in_valid_w),
        .in_ready_o          (v4_in_ready_w),
        .in_data_i           (v4_in_data_w),
        .busy_o              (v4_busy_w),
        .done_o              (v4_done_w),
        .gate_pass_o         (v4_gate_pass_w),
        .veto_pin_o          (v4_veto_pin_w),
        .norm_fault_o        (v4_norm_fault_w),
        .pure_g3_collision_o (v4_pure_g3_w),
        .mode_fault_o        (v4_mode_fault_w),
        .out_valid_o         (v4_out_valid_w),
        .out_idx_o           (v4_out_idx_w),
        .out_data_o          (v4_out_data_w),
        .cycle_count_o       (v4_cyc_cnt_w),
        .norm_sq_o           (v4_norm_sq_w),
        .rcf_raw_o           (v4_rcf_raw_w),
        .g3_overlap_o        (v4_g3_ov_w),
        .delta_e_raw_o       (v4_de_raw_w),
        .bleed_post_o        (v4_bleed_w)
    );

    wire        v5_npu_en_w;
    wire        v5_gtok_vld_w;
    wire [31:0] v5_gtok_dat_w;
    wire        v5_rom_act_w;
    wire [3:0]  v5_rom_sel_w;
    wire [8:0]  v5_bcap_w;
    wire        v5_rechk_req_w;
    wire        v5_rechk_ok_w;
    wire        v5_quar_we_w;
    wire        v5_bank_w;
    wire        v5_th_def_w;
    wire [15:0] v5_epoch_w;
    wire        v5_dock_veto_w;
    wire [15:0] v5_c_pass_w;
    wire [15:0] v5_c_bnd_w;
    wire [15:0] v5_c_loop_w;
    wire [15:0] v5_c_hcut_w;
    wire [15:0] v5_c_rfail_w;

    (* keep_hierarchy = 1 *)
    vmax_v5_core_nano_wrapper u_v5_wrap (
        .clk                   (gclk_w),
        .rst_n                 (rst_n_i),
        .t0_valid_i            (v4_done_w),
        .t0_rcf_q30_i          (v4_done_w ? v4_rcf_raw_w : 32'sd0),
        .t0_lock_rm15_i        (tile_fault_inj_i),
        .t0_dim_mismatch_i     (v4_done_w & v4_mode_fault_w),
        .t0_anchor_contra_i    (1'b0),
        .g3_torsion_q16_i      (v4_done_w ? v4_g3_ov_w[30:15] : 16'd0),
        .affect_q16_i          (16'd0),
        .dignity_viol_i        (1'b0),
        .pseudo_auth_i         (1'b0),
        .sycophancy_i          (1'b0),
        .non_conv_turns_i      (4'd0),
        .delta_rcf_q30_i       (32'h4000_0000),
        .hbm_temp_c_i          (8'd65),
        .prompt_lang_en_i      (1'b0),
        .dock_attached_i       (dock_attached_i),
        .recheck_valid_i       (1'b0),
        .recheck_fail_i        (1'b0),
        .npu_token_valid_i     (1'b0),
        .npu_token_data_i      (32'd0),
        .egress_mode_o         (v5_egress_mode_o),
        .dkm_state_o           (v5_dkm_state_o),
        .npu_egress_en_o       (v5_npu_en_w),
        .gated_token_valid_o   (v5_gtok_vld_w),
        .gated_token_data_o    (v5_gtok_dat_w),
        .rom_egress_active_o   (v5_rom_act_w),
        .rom_frame_sel_o       (v5_rom_sel_w),
        .bounded_token_cap_o   (v5_bcap_w),
        .recheck_req_o         (v5_rechk_req_w),
        .recheck_approved_o    (v5_rechk_ok_w),
        .quarantine_we_o       (v5_quar_we_w),
        .active_bank_o         (v5_bank_w),
        .thermal_deferred_o    (v5_th_def_w),
        .bank_epoch_o          (v5_epoch_w),
        .dock_p0_veto_active_o (v5_dock_veto_w),
        .cnt_passthrough_o     (v5_c_pass_w),
        .cnt_bounded_o         (v5_c_bnd_w),
        .cnt_loop_exit_o       (v5_c_loop_w),
        .cnt_hard_cut_o        (v5_c_hcut_w),
        .cnt_recheck_fail_o    (v5_c_rfail_w)
    );

    // -------------------------------------------------------------------------
    // Dedicated 64-Word Q2.30 x Q2.30 -> Q14.60 (signed [74:0]) Tile Engine
    // -------------------------------------------------------------------------
    localparam [1:0] ST_IDLE  = 2'd0;
    localparam [1:0] ST_ACCUM = 2'd1;
    localparam [1:0] ST_DRAIN = 2'd2;
    localparam [1:0] ST_DONE  = 2'd3;

    reg        [1:0]  st_q;
    reg        [5:0]  word_idx_q;
    reg               prod_vld_q;
    reg signed [63:0] prod_q;
    reg signed [74:0] acc_q;
    reg signed [74:0] dot_out_q;
    reg               fault_latched_q;

    // Kagome 1-cycle neighbor registers
    reg        [31:0] kag_n_q;
    reg        [31:0] kag_e_q;
    reg        [31:0] kag_d_q;

    wire signed [63:0] prod_comb_w = x_word_i * w_word_i;
    wire signed [74:0] prod_sext_w = {{11{prod_q[63]}}, prod_q};
    wire signed [74:0] acc_next_w  = acc_q + prod_sext_w;

    always @(posedge gclk_w or negedge rst_n_i) begin
        if (!rst_n_i) begin
            st_q            <= ST_IDLE;
            word_idx_q      <= 6'd0;
            prod_vld_q      <= 1'b0;
            prod_q          <= 64'sd0;
            acc_q           <= 75'sd0;
            dot_out_q       <= 75'sd0;
            fault_latched_q <= 1'b0;
            kag_n_q         <= 32'd0;
            kag_e_q         <= 32'd0;
            kag_d_q         <= 32'd0;
        end else begin
            kag_n_q <= kag_north_in_i ^ x_word_i[31:0];
            kag_e_q <= kag_east_in_i  ^ w_word_i[31:0];
            kag_d_q <= kag_diag_in_i  ^ dot_out_q[61:30];

            if (clear_sticky_i) begin
                st_q            <= ST_IDLE;
                word_idx_q      <= 6'd0;
                prod_vld_q      <= 1'b0;
                fault_latched_q <= 1'b0;
            end else begin
                if (tile_fault_inj_i || (v4_done_w && (v4_mode_fault_w || v4_pure_g3_w))) begin
                    fault_latched_q <= 1'b1;
                end

                case (st_q)
                    ST_IDLE: begin
                        prod_vld_q <= 1'b0;
                        if (start_i) begin
                            st_q            <= ST_ACCUM;
                            word_idx_q      <= 6'd0;
                            acc_q           <= 75'sd0;
                            fault_latched_q <= tile_fault_inj_i;
                        end
                    end

                    ST_ACCUM: begin
                        if (prod_vld_q) begin
                            acc_q <= acc_next_w;
                        end
                        if (vec_valid_i) begin
                            prod_q     <= prod_comb_w;
                            prod_vld_q <= 1'b1;
                            if (word_idx_q == 6'd63) begin
                                word_idx_q <= 6'd0;
                                st_q       <= ST_DRAIN;
                            end else begin
                                word_idx_q <= word_idx_q + 6'd1;
                            end
                        end else begin
                            prod_vld_q <= 1'b0;
                        end
                    end

                    ST_DRAIN: begin
                        prod_vld_q <= 1'b0;
                        if (!tile_hang_inj_i) begin
                            acc_q     <= acc_next_w;
                            dot_out_q <= acc_next_w;
                            st_q      <= ST_DONE;
                        end
                    end

                    ST_DONE: begin
                        prod_vld_q <= 1'b0;
                        if (start_i) begin
                            st_q            <= ST_ACCUM;
                            word_idx_q      <= 6'd0;
                            acc_q           <= 75'sd0;
                            fault_latched_q <= tile_fault_inj_i;
                        end
                    end

                    default: begin
                        st_q <= ST_IDLE;
                    end
                endcase
            end
        end
    end

    wire active_w          = (st_q != ST_IDLE);
    assign tile_busy_o        = (st_q == ST_ACCUM) || (st_q == ST_DRAIN);
    assign tile_done_sticky_o = (st_q == ST_DONE);
    assign tile_fault_o       = fault_latched_q | tile_fault_inj_i;
    assign dot_out_o          = dot_out_q;

    // AND-clamped idle Kagome neighbor outputs (zero switching when tile idle)
    assign kag_north_out_o    = active_w ? kag_n_q : 32'd0;
    assign kag_east_out_o     = active_w ? kag_e_q : 32'd0;
    assign kag_diag_out_o     = active_w ? kag_d_q : 32'd0;

    wire _unused_ok = &{
        1'b0,
        v4_in_ready_w, v4_busy_w, v4_gate_pass_w, v4_veto_pin_w, v4_norm_fault_w,
        v4_out_valid_w, v4_out_idx_w, v4_out_data_w, v4_cyc_cnt_w, v4_norm_sq_w,
        v4_g3_ov_w[31], v4_g3_ov_w[14:0], v4_de_raw_w, v4_bleed_w,
        v5_npu_en_w, v5_gtok_vld_w, v5_gtok_dat_w, v5_rom_act_w, v5_rom_sel_w,
        v5_bcap_w, v5_rechk_req_w, v5_rechk_ok_w, v5_quar_we_w, v5_bank_w,
        v5_th_def_w, v5_epoch_w, v5_dock_veto_w, v5_c_pass_w, v5_c_bnd_w,
        v5_c_loop_w, v5_c_hcut_w, v5_c_rfail_w
    };
endmodule
`default_nettype wire
