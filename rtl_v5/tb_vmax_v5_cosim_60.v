`timescale 1ns/1ps

module tb_vmax_v5_cosim_60;
    reg         clk;
    reg         rst_n;
    reg         t0_valid_i;
    reg  signed [31:0] t0_rcf_q30_i;
    reg         t0_lock_rm15_i;
    reg         t0_dim_mismatch_i;
    reg         t0_anchor_contra_i;
    reg  [15:0] g3_torsion_q16_i;
    reg  [15:0] affect_q16_i;
    reg         dignity_viol_i;
    reg         pseudo_auth_i;
    reg         sycophancy_i;
    reg  [3:0]  non_conv_turns_i;
    reg  [31:0] delta_rcf_q30_i;
    reg  [7:0]  hbm_temp_c_i;
    reg         prompt_lang_en_i;
    reg         dock_attached_i;
    reg         recheck_valid_i;
    reg         recheck_fail_i;
    reg         npu_token_valid_i;
    reg  [31:0] npu_token_data_i;

    wire [1:0]  egress_mode_o;
    wire [2:0]  dkm_state_o;
    wire        npu_egress_en_o;
    wire        gated_token_valid_o;
    wire [31:0] gated_token_data_o;
    wire        rom_egress_active_o;
    wire [3:0]  rom_frame_sel_o;
    wire [8:0]  bounded_token_cap_o;
    wire        recheck_req_o;
    wire        recheck_approved_o;
    wire        quarantine_we_o;
    wire        active_bank_o;
    wire        thermal_deferred_o;
    wire [15:0] bank_epoch_o;
    wire        dock_p0_veto_active_o;
    wire [15:0] cnt_passthrough_o;
    wire [15:0] cnt_bounded_o;
    wire [15:0] cnt_loop_exit_o;
    wire [15:0] cnt_hard_cut_o;
    wire [15:0] cnt_recheck_fail_o;

    reg  [127:0] vec_mem [0:59];
    integer      idx;

    vmax_v5_core_nano_wrapper dut (
        .clk                  (clk),
        .rst_n                (rst_n),
        .t0_valid_i           (t0_valid_i),
        .t0_rcf_q30_i         (t0_rcf_q30_i),
        .t0_lock_rm15_i       (t0_lock_rm15_i),
        .t0_dim_mismatch_i    (t0_dim_mismatch_i),
        .t0_anchor_contra_i   (t0_anchor_contra_i),
        .g3_torsion_q16_i     (g3_torsion_q16_i),
        .affect_q16_i         (affect_q16_i),
        .dignity_viol_i       (dignity_viol_i),
        .pseudo_auth_i        (pseudo_auth_i),
        .sycophancy_i         (sycophancy_i),
        .non_conv_turns_i     (non_conv_turns_i),
        .delta_rcf_q30_i      (delta_rcf_q30_i),
        .hbm_temp_c_i         (hbm_temp_c_i),
        .prompt_lang_en_i     (prompt_lang_en_i),
        .dock_attached_i      (dock_attached_i),
        .recheck_valid_i      (recheck_valid_i),
        .recheck_fail_i       (recheck_fail_i),
        .npu_token_valid_i    (npu_token_valid_i),
        .npu_token_data_i     (npu_token_data_i),
        .egress_mode_o        (egress_mode_o),
        .dkm_state_o          (dkm_state_o),
        .npu_egress_en_o      (npu_egress_en_o),
        .gated_token_valid_o  (gated_token_valid_o),
        .gated_token_data_o   (gated_token_data_o),
        .rom_egress_active_o  (rom_egress_active_o),
        .rom_frame_sel_o      (rom_frame_sel_o),
        .bounded_token_cap_o  (bounded_token_cap_o),
        .recheck_req_o        (recheck_req_o),
        .recheck_approved_o   (recheck_approved_o),
        .quarantine_we_o      (quarantine_we_o),
        .active_bank_o        (active_bank_o),
        .thermal_deferred_o   (thermal_deferred_o),
        .bank_epoch_o         (bank_epoch_o),
        .dock_p0_veto_active_o(dock_p0_veto_active_o),
        .cnt_passthrough_o    (cnt_passthrough_o),
        .cnt_bounded_o        (cnt_bounded_o),
        .cnt_loop_exit_o      (cnt_loop_exit_o),
        .cnt_hard_cut_o       (cnt_hard_cut_o),
        .cnt_recheck_fail_o   (cnt_recheck_fail_o)
    );

    initial clk = 1'b0;
    always #5 clk = ~clk;

    initial begin
        $readmemh("/tmp/v5_cosim_60.hex", vec_mem);
        rst_n              = 1'b0;
        t0_valid_i         = 1'b0;
        t0_rcf_q30_i       = 32'sd0;
        t0_lock_rm15_i     = 1'b0;
        t0_dim_mismatch_i  = 1'b0;
        t0_anchor_contra_i = 1'b0;
        g3_torsion_q16_i   = 16'd0;
        affect_q16_i       = 16'd0;
        dignity_viol_i     = 1'b0;
        pseudo_auth_i      = 1'b0;
        sycophancy_i       = 1'b0;
        non_conv_turns_i   = 4'd0;
        delta_rcf_q30_i    = 32'd0;
        hbm_temp_c_i       = 8'd65;
        prompt_lang_en_i   = 1'b0;
        dock_attached_i    = 1'b0;
        recheck_valid_i    = 1'b0;
        recheck_fail_i     = 1'b0;
        npu_token_valid_i  = 1'b1;
        npu_token_data_i   = 32'hCAFEBABE;

        @(negedge clk);
        @(negedge clk);
        rst_n = 1'b1;

        for (idx = 0; idx < 60; idx = idx + 1) begin
            @(negedge clk);
            t0_valid_i         = 1'b1;
            t0_rcf_q30_i       = vec_mem[idx][127:96];
            delta_rcf_q30_i    = vec_mem[idx][95:64];
            g3_torsion_q16_i   = vec_mem[idx][63:48];
            affect_q16_i       = vec_mem[idx][47:32];
            hbm_temp_c_i       = vec_mem[idx][31:24];
            non_conv_turns_i   = vec_mem[idx][23:20];
            dignity_viol_i     = vec_mem[idx][19];
            pseudo_auth_i      = vec_mem[idx][18];
            sycophancy_i       = vec_mem[idx][17];
            prompt_lang_en_i   = vec_mem[idx][16];
            t0_lock_rm15_i     = vec_mem[idx][15];
            t0_dim_mismatch_i  = vec_mem[idx][14];
            t0_anchor_contra_i = vec_mem[idx][13];
            dock_attached_i    = vec_mem[idx][12];
            @(posedge clk);
            #1;
            $display("COSIM_VEC %0d %02b %0d %0d %0d %0d %0d",
                idx, egress_mode_o, dkm_state_o, active_bank_o,
                bank_epoch_o, rom_frame_sel_o, npu_egress_en_o);
        end
        $display("COSIM_DONE pass_cnt=%0d bound_cnt=%0d loop_cnt=%0d cut_cnt=%0d",
            cnt_passthrough_o, cnt_bounded_o, cnt_loop_exit_o, cnt_hard_cut_o);
        $finish;
    end
endmodule
