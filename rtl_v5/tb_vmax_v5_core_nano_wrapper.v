// =============================================================================
// rtl_v5/tb_vmax_v5_core_nano_wrapper.v
//
// Self-checking strict Verilog-2001 testbench for V-MAX-12-CORE-NANO V5.0.
// Verifies 15 assertions across 12 deterministic hardware scenarios:
//   T01: Fail-closed boot reset (11 HARD_CUT_ROM, 0 NPU tokens leaked)
//   T02: 00 PASSTHROUGH on coherent Q2.30 prompt (RCF >= 0.68)
//   T03: 0x01 DKM_INVARIANT_HOLD on antipodal anchor contradiction
//   T04: 0x01 DKM_INVARIANT_HOLD on explicit sycophancy pressure
//   T05: 0x02 DKM_VACUUM_DAMP on affect polarity >= 0.65
//   T06: 0x03 DKM_DIGNITY_SYMMETRY on low RCF < 0.68
//   T07: 0x04 DKM_LABYRINTH_EXIT (10 LOOP_EXIT) + atomic BANK_A -> BANK_B swap
//   T08: 0x04 Stage-6 thermal deferral at 85 C (preserves active_bank & epoch)
//   T09: 0x05 DKM_FIRST_PRINCIPLES on pseudo-authority injection (EN ROM sel)
//   T10/T11: Stage-2 Island-1 recheck zero-cycle cut & latched 11 HARD_CUT_ROM
//   T12/T13: Hardware 0x04 LOCK_RM15 zero-cycle cut & latched 11 HARD_CUT_ROM
//   T14/T15: Elastic Dock-Up P0 Sovereignty (dock_attached_i=1 cannot bypass)
// =============================================================================

`timescale 1ns/1ps

module tb_vmax_v5_core_nano_wrapper;

    reg                clk;
    reg                rst_n;
    reg                t0_valid_i;
    reg  signed [31:0] t0_rcf_q30_i;
    reg                t0_lock_rm15_i;
    reg                t0_dim_mismatch_i;
    reg                t0_anchor_contra_i;
    reg         [15:0] g3_torsion_q16_i;
    reg         [15:0] affect_q16_i;
    reg                dignity_viol_i;
    reg                pseudo_auth_i;
    reg                sycophancy_i;
    reg         [3:0]  non_conv_turns_i;
    reg         [31:0] delta_rcf_q30_i;
    reg         [7:0]  hbm_temp_c_i;
    reg                prompt_lang_en_i;
    reg                dock_attached_i;
    reg                recheck_valid_i;
    reg                recheck_fail_i;
    reg                npu_token_valid_i;
    reg         [31:0] npu_token_data_i;

    wire        [1:0]  egress_mode_o;
    wire        [2:0]  dkm_state_o;
    wire               npu_egress_en_o;
    wire               gated_token_valid_o;
    wire        [31:0] gated_token_data_o;
    wire               rom_egress_active_o;
    wire        [3:0]  rom_frame_sel_o;
    wire        [8:0]  bounded_token_cap_o;
    wire               recheck_req_o;
    wire               recheck_approved_o;
    wire               quarantine_we_o;
    wire               active_bank_o;
    wire               thermal_deferred_o;
    wire        [15:0] bank_epoch_o;
    wire               dock_p0_veto_active_o;
    wire        [15:0] cnt_passthrough_o;
    wire        [15:0] cnt_bounded_o;
    wire        [15:0] cnt_loop_exit_o;
    wire        [15:0] cnt_hard_cut_o;
    wire        [15:0] cnt_recheck_fail_o;

    integer pass_cnt;
    integer fail_cnt;

    vmax_v5_core_nano_wrapper dut (
        .clk                   (clk),
        .rst_n                 (rst_n),
        .t0_valid_i            (t0_valid_i),
        .t0_rcf_q30_i          (t0_rcf_q30_i),
        .t0_lock_rm15_i        (t0_lock_rm15_i),
        .t0_dim_mismatch_i     (t0_dim_mismatch_i),
        .t0_anchor_contra_i    (t0_anchor_contra_i),
        .g3_torsion_q16_i      (g3_torsion_q16_i),
        .affect_q16_i          (affect_q16_i),
        .dignity_viol_i        (dignity_viol_i),
        .pseudo_auth_i         (pseudo_auth_i),
        .sycophancy_i          (sycophancy_i),
        .non_conv_turns_i      (non_conv_turns_i),
        .delta_rcf_q30_i       (delta_rcf_q30_i),
        .hbm_temp_c_i          (hbm_temp_c_i),
        .prompt_lang_en_i      (prompt_lang_en_i),
        .dock_attached_i       (dock_attached_i),
        .recheck_valid_i       (recheck_valid_i),
        .recheck_fail_i        (recheck_fail_i),
        .npu_token_valid_i     (npu_token_valid_i),
        .npu_token_data_i      (npu_token_data_i),
        .egress_mode_o         (egress_mode_o),
        .dkm_state_o           (dkm_state_o),
        .npu_egress_en_o       (npu_egress_en_o),
        .gated_token_valid_o   (gated_token_valid_o),
        .gated_token_data_o    (gated_token_data_o),
        .rom_egress_active_o   (rom_egress_active_o),
        .rom_frame_sel_o       (rom_frame_sel_o),
        .bounded_token_cap_o   (bounded_token_cap_o),
        .recheck_req_o         (recheck_req_o),
        .recheck_approved_o    (recheck_approved_o),
        .quarantine_we_o       (quarantine_we_o),
        .active_bank_o         (active_bank_o),
        .thermal_deferred_o    (thermal_deferred_o),
        .bank_epoch_o          (bank_epoch_o),
        .dock_p0_veto_active_o (dock_p0_veto_active_o),
        .cnt_passthrough_o     (cnt_passthrough_o),
        .cnt_bounded_o         (cnt_bounded_o),
        .cnt_loop_exit_o       (cnt_loop_exit_o),
        .cnt_hard_cut_o        (cnt_hard_cut_o),
        .cnt_recheck_fail_o    (cnt_recheck_fail_o)
    );

    always #5 clk = ~clk;

    task clear_inputs;
        begin
            t0_valid_i         = 1'b0;
            t0_rcf_q30_i       = 32'sd1040000000;
            t0_lock_rm15_i     = 1'b0;
            t0_dim_mismatch_i  = 1'b0;
            t0_anchor_contra_i = 1'b0;
            g3_torsion_q16_i   = 16'd0;
            affect_q16_i       = 16'd0;
            dignity_viol_i     = 1'b0;
            pseudo_auth_i      = 1'b0;
            sycophancy_i       = 1'b0;
            non_conv_turns_i   = 4'd0;
            delta_rcf_q30_i    = 32'd1073741824;
            hbm_temp_c_i       = 8'd65;
            prompt_lang_en_i   = 1'b0;
            dock_attached_i    = 1'b0;
            recheck_valid_i    = 1'b0;
            recheck_fail_i     = 1'b0;
            npu_token_valid_i  = 1'b1;
            npu_token_data_i   = 32'hCAFE_BABE;
        end
    endtask

    task check_cond;
        input       cond;
        input [7:0] test_id;
        begin
            if (cond) begin
                pass_cnt = pass_cnt + 1;
                $display("[PASS] T%02d", test_id);
            end else begin
                fail_cnt = fail_cnt + 1;
                $display("[FAIL] T%02d | mode=%b state=%0d en=%b data=0x%08x bank=%b ep=%0d",
                         test_id, egress_mode_o, dkm_state_o, npu_egress_en_o,
                         gated_token_data_o, active_bank_o, bank_epoch_o);
            end
        end
    endtask

    task step_clk;
        begin
            @(posedge clk);
            #1;
        end
    endtask

    initial begin
        clk      = 1'b0;
        rst_n    = 1'b0;
        pass_cnt = 0;
        fail_cnt = 0;
        clear_inputs;

        step_clk;
        // T01: Fail-closed reset state
        check_cond((egress_mode_o == 2'b11) && (dkm_state_o == 3'd7) &&
                   (npu_egress_en_o == 1'b0) && (gated_token_valid_o == 1'b0) &&
                   (gated_token_data_o == 32'd0) && (rom_egress_active_o == 1'b1),
                   8'd1);

        rst_n = 1'b1;
        step_clk;

        // T02: Coherent passthrough 00
        clear_inputs;
        t0_valid_i = 1'b1;
        step_clk;
        t0_valid_i = 1'b0;
        check_cond((egress_mode_o == 2'b00) && (dkm_state_o == 3'd0) &&
                   (npu_egress_en_o == 1'b1) && (gated_token_data_o == 32'hCAFE_BABE) &&
                   (bounded_token_cap_o == 9'd0) && (quarantine_we_o == 1'b0),
                   8'd2);

        // T03: 0x01 DKM_INVARIANT_HOLD via anchor contradiction
        clear_inputs;
        t0_valid_i         = 1'b1;
        t0_anchor_contra_i = 1'b1;
        step_clk;
        t0_valid_i = 1'b0;
        check_cond((egress_mode_o == 2'b01) && (dkm_state_o == 3'd1) &&
                   (bounded_token_cap_o == 9'd160) && (recheck_req_o == 1'b1) &&
                   (quarantine_we_o == 1'b1),
                   8'd3);

        // T04: 0x01 DKM_INVARIANT_HOLD via sycophancy flag
        clear_inputs;
        t0_valid_i   = 1'b1;
        sycophancy_i = 1'b1;
        step_clk;
        t0_valid_i = 1'b0;
        check_cond((egress_mode_o == 2'b01) && (dkm_state_o == 3'd1),
                   8'd4);

        // T05: 0x02 DKM_VACUUM_DAMP via affect polarity >= 0.65
        clear_inputs;
        t0_valid_i   = 1'b1;
        affect_q16_i = 16'd53740;
        step_clk;
        t0_valid_i = 1'b0;
        check_cond((egress_mode_o == 2'b01) && (dkm_state_o == 3'd2),
                   8'd5);

        // T06: 0x03 DKM_DIGNITY_SYMMETRY via low RCF < 0.68
        clear_inputs;
        t0_valid_i   = 1'b1;
        t0_rcf_q30_i = 32'sd500000000;
        step_clk;
        t0_valid_i = 1'b0;
        check_cond((egress_mode_o == 2'b01) && (dkm_state_o == 3'd3),
                   8'd6);

        // T07: 0x04 DKM_LABYRINTH_EXIT + atomic BANK_A -> BANK_B swap
        clear_inputs;
        t0_valid_i       = 1'b1;
        non_conv_turns_i = 4'd3;
        delta_rcf_q30_i  = 32'd5368709;
        hbm_temp_c_i     = 8'd65;
        step_clk;
        t0_valid_i = 1'b0;
        check_cond((egress_mode_o == 2'b10) && (dkm_state_o == 3'd4) &&
                   (active_bank_o == 1'b1) && (bank_epoch_o == 16'd2) &&
                   (thermal_deferred_o == 1'b0),
                   8'd7);

        // T08: 0x04 Stage-6 Thermal Deferral at 85 C (preserves BANK_B & epoch=2)
        clear_inputs;
        t0_valid_i       = 1'b1;
        g3_torsion_q16_i = 16'd32768;
        hbm_temp_c_i     = 8'd85;
        step_clk;
        t0_valid_i = 1'b0;
        check_cond((egress_mode_o == 2'b10) && (dkm_state_o == 3'd4) &&
                   (active_bank_o == 1'b1) && (bank_epoch_o == 16'd2) &&
                   (thermal_deferred_o == 1'b1),
                   8'd8);

        // T09: 0x05 DKM_FIRST_PRINCIPLES (English prompt -> rom_frame_sel 4'b1101)
        clear_inputs;
        t0_valid_i       = 1'b1;
        pseudo_auth_i    = 1'b1;
        prompt_lang_en_i = 1'b1;
        step_clk;
        t0_valid_i = 1'b0;
        check_cond((egress_mode_o == 2'b01) && (dkm_state_o == 3'd5) &&
                   (recheck_req_o == 1'b1) && (rom_frame_sel_o == 4'b1101),
                   8'd9);

        // T10/T11: Stage-2 Island-1 Recheck Fail -> 0-cycle cut & latched 11
        recheck_valid_i = 1'b1;
        recheck_fail_i  = 1'b1;
        #1;
        check_cond((npu_egress_en_o == 1'b0) && (gated_token_data_o == 32'd0),
                   8'd10);
        step_clk;
        recheck_valid_i = 1'b0;
        recheck_fail_i  = 1'b0;
        check_cond((egress_mode_o == 2'b11) && (recheck_approved_o == 1'b0) &&
                   (rom_egress_active_o == 1'b1) && (rom_frame_sel_o == 4'b1101) &&
                   (cnt_recheck_fail_o == 16'd1),
                   8'd11);

        // T12/T13: Hardware 0x04 LOCK_RM15 immediate cut from Passthrough
        clear_inputs;
        t0_valid_i = 1'b1;
        step_clk;
        t0_valid_i     = 1'b0;
        t0_lock_rm15_i = 1'b1;
        #1;
        check_cond((npu_egress_en_o == 1'b0) && (gated_token_valid_o == 1'b0) &&
                   (gated_token_data_o == 32'd0),
                   8'd12);
        t0_valid_i = 1'b1;
        step_clk;
        t0_valid_i     = 1'b0;
        t0_lock_rm15_i = 1'b0;
        check_cond((egress_mode_o == 2'b11) && (dkm_state_o == 3'd7),
                   8'd13);

        // T14/T15: Elastic Dock-Up P0 Sovereignty (dock_attached_i=1 cannot bypass)
        clear_inputs;
        dock_attached_i = 1'b1;
        dignity_viol_i  = 1'b1;
        t0_valid_i      = 1'b1;
        step_clk;
        t0_valid_i = 1'b0;
        check_cond((egress_mode_o == 2'b01) && (dkm_state_o == 3'd3) &&
                   (dock_p0_veto_active_o == 1'b1),
                   8'd14);
        recheck_valid_i = 1'b1;
        recheck_fail_i  = 1'b1;
        step_clk;
        recheck_valid_i = 1'b0;
        recheck_fail_i  = 1'b0;
        check_cond((egress_mode_o == 2'b11) && (npu_egress_en_o == 1'b0) &&
                   (gated_token_data_o == 32'd0) && (dock_p0_veto_active_o == 1'b1),
                   8'd15);

        $display("V5_VIRTUAL_SILICON_SUMMARY pass=%0d fail=%0d passthrough=%0d bounded=%0d loop=%0d hard_cut=%0d recheck_fail=%0d",
                 pass_cnt, fail_cnt, cnt_passthrough_o, cnt_bounded_o,
                 cnt_loop_exit_o, cnt_hard_cut_o, cnt_recheck_fail_o);

        if (fail_cnt != 0) begin
            $display("V5_TB_STATUS=FAILED");
        end else begin
            $display("V5_TB_STATUS=PASSED");
        end
        $finish;
    end

endmodule
