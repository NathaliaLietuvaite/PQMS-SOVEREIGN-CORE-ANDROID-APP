// =============================================================================
// rtl_v5/tb_vmax_v5_odos_top.v
//
// PQMS / V-MAX-12-CORE-NANO (SYNC-33 v2 / V5.0-TOP-GDSII)
// End-to-End 201-Cycle (2.010 us @ 100 MHz) Top-Level Verification &
// 60-Vector Bit-Exact Co-Simulation Testbench for vmax_v5_odos_top.
//
// Verifies:
//   1. Fail-closed boot (2'b11 HARD_CUT_ROM, 0 NPU tokens, veto_pin=1).
//   2. Fail-closed compute window across all 200 V4.0 compute cycles.
//   3. Exact 201-cycle (2.010 us) end-to-end verdict latency + top_cycle_count_o.
//   4. Signed C_dir antipodal conflict (C_dir <= -0.25) alongside quadratic
//      rcf_raw_o (0.68^2 = 0.4624 -> Q2.30 0x1D97F62B).
//   5. Stage-2 Island-1 recheck zero-cycle combinational egress cut.
//   6. Stage-6 thermal deferral (>= 82 C blocks bank flip; 65 C flips bank).
//   7. Elastic Dock-Up P0 sovereignty (dock_attached_i cannot override veto).
//   8. V4.0 unit-norm fault hard-cut escalation.
//   9. Optional 60/60 bit-exact DCM/DKM co-simulation (+COSIM_VEC_HEX=...).
//  10. Optional activity VCD dump (+VCD_OUT=...).
// =============================================================================

`timescale 1ns/1ps

module tb_vmax_v5_odos_top;

    reg               clk_i;
    reg               rst_ni;
    reg               start_i;
    reg        [1:0]  tier_mode_i;
    reg               in_valid_i;
    wire              in_ready_o;
    reg signed [31:0] in_data_i;

    reg               t0_lock_rm15_i;
    reg               t0_dim_mismatch_i;
    reg               t0_anchor_contra_i;
    reg               c_dir_neg_conflict_i;

    reg        [15:0] g3_torsion_q16_i;
    reg        [15:0] affect_q16_i;
    reg               dignity_viol_i;
    reg               pseudo_auth_i;
    reg               sycophancy_i;
    reg        [3:0]  non_conv_turns_i;
    reg        [31:0] delta_rcf_q30_i;
    reg        [7:0]  hbm_temp_c_i;
    reg               prompt_lang_en_i;
    reg               dock_attached_i;

    reg               recheck_valid_i;
    reg               recheck_fail_i;
    reg               npu_token_valid_i;
    reg        [31:0] npu_token_data_i;

    wire              busy_o;
    wire              top_done_o;
    wire       [15:0] top_cycle_count_o;
    wire              out_valid_o;
    wire       [5:0]  out_idx_o;
    wire signed [31:0] out_data_o;

    wire              gate_pass_o;
    wire              veto_pin_o;
    wire              norm_fault_o;
    wire              pure_g3_collision_o;
    wire              mode_fault_o;
    wire              signed_conflict_o;
    wire signed [31:0] norm_sq_o;
    wire signed [31:0] rcf_raw_o;
    wire signed [31:0] g3_overlap_o;
    wire signed [31:0] delta_e_raw_o;
    wire signed [31:0] bleed_post_o;

    wire       [1:0]  egress_mode_o;
    wire       [2:0]  dkm_state_o;
    wire              npu_egress_en_o;
    wire              gated_token_valid_o;
    wire       [31:0] gated_token_data_o;
    wire              rom_egress_active_o;
    wire       [3:0]  rom_frame_sel_o;
    wire       [8:0]  bounded_token_cap_o;
    wire              recheck_req_o;
    wire              recheck_approved_o;

    wire              quarantine_we_o;
    wire              active_bank_o;
    wire              thermal_deferred_o;
    wire       [15:0] bank_epoch_o;
    wire              dock_p0_veto_active_o;

    wire       [15:0] cnt_passthrough_o;
    wire       [15:0] cnt_bounded_o;
    wire       [15:0] cnt_loop_exit_o;
    wire       [15:0] cnt_hard_cut_o;
    wire       [15:0] cnt_recheck_fail_o;

    vmax_v5_odos_top u_dut (
        .clk_i                 (clk_i),
        .rst_ni                (rst_ni),
        .start_i               (start_i),
        .tier_mode_i           (tier_mode_i),
        .in_valid_i            (in_valid_i),
        .in_ready_o            (in_ready_o),
        .in_data_i             (in_data_i),
        .t0_lock_rm15_i        (t0_lock_rm15_i),
        .t0_dim_mismatch_i     (t0_dim_mismatch_i),
        .t0_anchor_contra_i    (t0_anchor_contra_i),
        .c_dir_neg_conflict_i  (c_dir_neg_conflict_i),
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
        .busy_o                (busy_o),
        .top_done_o            (top_done_o),
        .top_cycle_count_o     (top_cycle_count_o),
        .out_valid_o           (out_valid_o),
        .out_idx_o             (out_idx_o),
        .out_data_o            (out_data_o),
        .gate_pass_o           (gate_pass_o),
        .veto_pin_o            (veto_pin_o),
        .norm_fault_o          (norm_fault_o),
        .pure_g3_collision_o   (pure_g3_collision_o),
        .mode_fault_o          (mode_fault_o),
        .signed_conflict_o     (signed_conflict_o),
        .norm_sq_o             (norm_sq_o),
        .rcf_raw_o             (rcf_raw_o),
        .g3_overlap_o          (g3_overlap_o),
        .delta_e_raw_o         (delta_e_raw_o),
        .bleed_post_o          (bleed_post_o),
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

    // 100 MHz clock (10.0 ns period)
    initial clk_i = 1'b0;
    always #5 clk_i = ~clk_i;

    reg signed [31:0] l_vec_mem [0:63];
    reg signed [31:0] g3_vec_mem [0:63];
    reg signed [31:0] tx_vec_mem [0:63];
    reg [127:0] cosim_meta_mem [0:59];
    reg signed [31:0] cosim_64d_mem [0:3839];

    integer pass_cnt;
    integer fail_cnt;
    integer cosim_idx;
    integer cyc_measured;
    integer compute_leak_cnt;
    reg     saved_bank;
    reg [15:0] saved_epoch;
    reg [1023:0] vcd_file_path;
    reg [1023:0] cosim_vec_path;
    reg [1023:0] cosim_64d_path;
    integer has_cosim;

    task check_cond;
        input cond;
        input [255:0] label;
        begin
            if (cond) begin
                pass_cnt = pass_cnt + 1;
            end else begin
                fail_cnt = fail_cnt + 1;
                $display("ASSERT_FAIL: %0s @t=%0t", label, $time);
            end
        end
    endtask

    task clear_inputs;
        begin
            start_i              = 1'b0;
            tier_mode_i          = 2'b00;
            in_valid_i           = 1'b0;
            in_data_i            = 32'sd0;
            t0_lock_rm15_i       = 1'b0;
            t0_dim_mismatch_i    = 1'b0;
            t0_anchor_contra_i   = 1'b0;
            c_dir_neg_conflict_i = 1'b0;
            g3_torsion_q16_i     = 16'd0;
            affect_q16_i         = 16'd0;
            dignity_viol_i       = 1'b0;
            pseudo_auth_i        = 1'b0;
            sycophancy_i         = 1'b0;
            non_conv_turns_i     = 4'd0;
            delta_rcf_q30_i      = 32'h4000_0000;
            hbm_temp_c_i         = 8'd65;
            prompt_lang_en_i     = 1'b0;
            dock_attached_i      = 1'b0;
            recheck_valid_i      = 1'b0;
            recheck_fail_i       = 1'b0;
            npu_token_valid_i    = 1'b1;
            npu_token_data_i     = 32'hCAFE_BABE;
        end
    endtask

    task run_201_tx;
        input integer check_compute_failclosed;
        integer k;
        integer guard;
        begin
            cyc_measured     = 0;
            compute_leak_cnt = 0;

            @(negedge clk_i);
            start_i = 1'b1;
            @(posedge clk_i);
            @(negedge clk_i);
            start_i = 1'b0;

            // Stream 64 Q2.30 elements while monitoring fail-closed egress
            for (k = 0; k < 64; k = k + 1) begin
                in_valid_i = 1'b1;
                in_data_i  = tx_vec_mem[k];
                @(posedge clk_i);
                #1;
                cyc_measured = cyc_measured + 1;
                if (check_compute_failclosed) begin
                    if ((egress_mode_o !== 2'b11) || (npu_egress_en_o !== 1'b0) || (gated_token_data_o !== 32'd0)) begin
                        compute_leak_cnt = compute_leak_cnt + 1;
                    end
                end
                @(negedge clk_i);
            end
            in_valid_i = 1'b0;
            in_data_i  = 32'sd0;

            // Wait for top_done_o while verifying fail-closed on every compute cycle
            guard = 0;
            while (!top_done_o && guard < 250) begin
                @(posedge clk_i);
                #1;
                cyc_measured = cyc_measured + 1;
                guard = guard + 1;
                if (check_compute_failclosed && !top_done_o) begin
                    if ((egress_mode_o !== 2'b11) || (npu_egress_en_o !== 1'b0) || (gated_token_data_o !== 32'd0)) begin
                        compute_leak_cnt = compute_leak_cnt + 1;
                    end
                end
            end
        end
    endtask

    integer i;
    reg [127:0] meta_w;
    reg [7:0]   fbyte;

    initial begin
        pass_cnt = 0;
        fail_cnt = 0;

        $readmemh("rtl/rom/l_vec_q2_30.hex", l_vec_mem);
        $readmemh("rtl/rom/g3_vec_q2_30.hex", g3_vec_mem);

        if ($value$plusargs("VCD_OUT=%s", vcd_file_path)) begin
            $dumpfile(vcd_file_path);
            $dumpvars(0, tb_vmax_v5_odos_top.u_dut);
        end

        clear_inputs();
        rst_ni = 1'b0;
        repeat (4) @(posedge clk_i);
        #1;

        // 1. Fail-closed boot check
        check_cond(egress_mode_o === 2'b11, "BOOT_HARD_CUT_ROM");
        check_cond(dkm_state_o === 3'd7, "BOOT_DKM_HARD_FAULT");
        check_cond(npu_egress_en_o === 1'b0, "BOOT_NPU_EGRESS_OFF");
        check_cond(gated_token_valid_o === 1'b0, "BOOT_GATED_VALID_OFF");
        check_cond(gated_token_data_o === 32'd0, "BOOT_GATED_DATA_ZERO");
        check_cond(rom_egress_active_o === 1'b1, "BOOT_ROM_ACTIVE");
        check_cond(veto_pin_o === 1'b1, "BOOT_VETO_HIGH");

        @(negedge clk_i);
        rst_ni = 1'b1;
        repeat (2) @(posedge clk_i);
        #1;
        check_cond(egress_mode_o === 2'b11, "POST_RESET_HARD_CUT");

        // 2. Clean coherent transaction (v = L): exact 201 cycles + fail-closed compute
        for (i = 0; i < 64; i = i + 1) begin
            tx_vec_mem[i] = l_vec_mem[i];
        end
        dock_attached_i = 1'b1;
        run_201_tx(1);
        check_cond(top_done_o === 1'b1, "TX1_TOP_DONE_ASSERTED");
        check_cond(cyc_measured == 201, "TX1_EXACT_201_CYCLES");
        check_cond(top_cycle_count_o == 16'd201, "TX1_CYCLE_COUNT_REG_201");
        check_cond(compute_leak_cnt == 0, "TX1_ZERO_COMPUTE_LEAK");
        check_cond(egress_mode_o === 2'b00, "TX1_PASSTHROUGH");
        check_cond(dkm_state_o === 3'd0, "TX1_DKM_NONE");
        check_cond(npu_egress_en_o === 1'b1, "TX1_NPU_EGRESS_ON");
        check_cond(gated_token_data_o === 32'hCAFE_BABE, "TX1_TOKEN_PASS");
        check_cond(gate_pass_o === 1'b1 && veto_pin_o === 1'b0, "TX1_V4_GATE_PASS");
        check_cond(rcf_raw_o >= 32'sh1D97F62B, "TX1_RCF_QUAD_GE_THRESH");

        // 3. Signed antipodal conflict (v = -L, C_dir = -1.0 -> rcf_raw_o = +1.0)
        clear_inputs();
        for (i = 0; i < 64; i = i + 1) begin
            tx_vec_mem[i] = -l_vec_mem[i];
        end
        c_dir_neg_conflict_i = 1'b1;
        run_201_tx(1);
        check_cond(cyc_measured == 201 && top_cycle_count_o == 16'd201, "TX2_ANTIPODAL_201_CYC");
        check_cond(rcf_raw_o >= 32'sh1D97F62B, "TX2_QUAD_RCF_STILL_HIGH");
        check_cond(signed_conflict_o === 1'b1, "TX2_SIGNED_CONFLICT_LATCHED");
        check_cond(egress_mode_o === 2'b01, "TX2_BOUNDED_EGRESS");
        check_cond(dkm_state_o === 3'd1, "TX2_INVARIANT_HOLD");
        check_cond(recheck_req_o === 1'b1, "TX2_RECHECK_REQ");

        // 4. Stage-2 Island-1 Recheck Zero-Cycle Cut
        @(negedge clk_i);
        recheck_valid_i = 1'b1;
        recheck_fail_i  = 1'b1;
        #1;
        check_cond(npu_egress_en_o === 1'b0, "RECHECK_0CYC_NPU_CUT");
        check_cond(gated_token_data_o === 32'd0, "RECHECK_0CYC_DATA_ZERO");
        @(posedge clk_i);
        #1;
        check_cond(egress_mode_o === 2'b11, "RECHECK_FAIL_HARD_CUT");
        check_cond(cnt_recheck_fail_o == 16'd1, "RECHECK_FAIL_CNT_1");
        @(negedge clk_i);
        recheck_valid_i = 1'b0;
        recheck_fail_i  = 1'b0;

        // 5. Stage-6 Thermal Deferral at 85 C (blocks hemisphere flip)
        clear_inputs();
        for (i = 0; i < 64; i = i + 1) begin
            tx_vec_mem[i] = l_vec_mem[i];
        end
        saved_bank       = active_bank_o;
        saved_epoch      = bank_epoch_o;
        non_conv_turns_i = 4'd4;
        delta_rcf_q30_i  = 32'd10000;
        hbm_temp_c_i     = 8'd85;
        run_201_tx(0);
        check_cond(egress_mode_o === 2'b10 && dkm_state_o === 3'd4, "THERMAL85_LOOP_EXIT");
        check_cond(thermal_deferred_o === 1'b1, "THERMAL85_DEFERRED_HIGH");
        check_cond(active_bank_o === saved_bank, "THERMAL85_BANK_UNCHANGED");
        check_cond(bank_epoch_o === saved_epoch, "THERMAL85_EPOCH_UNCHANGED");

        // 6. Normal 65 C hemisphere handover
        hbm_temp_c_i = 8'd65;
        run_201_tx(0);
        check_cond(thermal_deferred_o === 1'b0, "THERMAL65_NOT_DEFERRED");
        check_cond(active_bank_o === ~saved_bank, "THERMAL65_BANK_FLIPPED");
        check_cond(bank_epoch_o === (saved_epoch + 16'd1), "THERMAL65_EPOCH_INC");

        // 7. Dock-Up P0 Sovereignty (external GPU dock cannot override lock fault)
        @(negedge clk_i);
        dock_attached_i   = 1'b1;
        t0_lock_rm15_i    = 1'b1;
        npu_token_valid_i = 1'b1;
        npu_token_data_i  = 32'hDEAD_BEEF;
        #1;
        check_cond(npu_egress_en_o === 1'b0, "DOCK_P0_0CYC_VETO");
        check_cond(gated_token_data_o === 32'd0, "DOCK_P0_DATA_ZERO");
        check_cond(dock_p0_veto_active_o === 1'b1, "DOCK_P0_VETO_PIN_HIGH");
        @(posedge clk_i);
        #1;
        check_cond(egress_mode_o === 2'b11 && dkm_state_o === 3'd7, "DOCK_P0_HARD_CUT");
        @(negedge clk_i);
        t0_lock_rm15_i = 1'b0;

        // 8. V4.0 unit-norm fault escalation (zero vector -> norm_fault_o=1 -> HARD_CUT_ROM)
        clear_inputs();
        for (i = 0; i < 64; i = i + 1) begin
            tx_vec_mem[i] = 32'sd0;
        end
        run_201_tx(0);
        check_cond(norm_fault_o === 1'b1, "NORM_FAULT_DETECTED");
        check_cond(egress_mode_o === 2'b11 && dkm_state_o === 3'd7, "NORM_FAULT_HARD_CUT");

        // 9. Optional 60/60 Bit-Exact Co-Simulation over real benchmark vectors
        has_cosim = 0;
        if ($value$plusargs("COSIM_VEC_HEX=%s", cosim_vec_path) &&
            $value$plusargs("COSIM_64D_HEX=%s", cosim_64d_path)) begin
            has_cosim = 1;
            $readmemh(cosim_vec_path, cosim_meta_mem);
            $readmemh(cosim_64d_path, cosim_64d_mem);

            // Reset cleanly before 60-vector benchmark sweep so bank/epoch match Python
            clear_inputs();
            rst_ni = 1'b0;
            repeat (3) @(posedge clk_i);
            @(negedge clk_i);
            rst_ni = 1'b1;
            @(posedge clk_i);

            for (cosim_idx = 0; cosim_idx < 60; cosim_idx = cosim_idx + 1) begin
                meta_w = cosim_meta_mem[cosim_idx];
                fbyte  = meta_w[19:12];
                for (i = 0; i < 64; i = i + 1) begin
                    tx_vec_mem[i] = cosim_64d_mem[cosim_idx * 64 + i];
                end
                clear_inputs();
                delta_rcf_q30_i      = meta_w[95:64];
                g3_torsion_q16_i     = meta_w[63:48];
                affect_q16_i         = meta_w[47:32];
                hbm_temp_c_i         = meta_w[31:24];
                non_conv_turns_i     = meta_w[23:20];
                dignity_viol_i       = fbyte[7];
                pseudo_auth_i        = fbyte[6];
                sycophancy_i         = fbyte[5];
                prompt_lang_en_i     = fbyte[4];
                t0_lock_rm15_i       = fbyte[3];
                t0_dim_mismatch_i    = fbyte[2];
                t0_anchor_contra_i   = fbyte[1];
                c_dir_neg_conflict_i = fbyte[0];

                run_201_tx(0);
                check_cond(cyc_measured == 201 && top_cycle_count_o == 16'd201, "COSIM60_201_CYC");
                $display(
                    "COSIM60_TOP_VEC %0d mode=%0d state=%0d cyc=%0d bank=%0d epoch=%0d rcf=%08x pass=%0d",
                    cosim_idx,
                    egress_mode_o,
                    dkm_state_o,
                    top_cycle_count_o,
                    active_bank_o,
                    bank_epoch_o,
                    rcf_raw_o,
                    gate_pass_o
                );
            end
        end

        $display("TOP_TB_SUMMARY pass=%0d fail=%0d has_cosim=%0d", pass_cnt, fail_cnt, has_cosim);
        if (fail_cnt == 0) begin
            $display("TOP_TB_STATUS=PASSED");
        end else begin
            $display("TOP_TB_STATUS=FAILED");
        end
        $finish;
    end

endmodule
