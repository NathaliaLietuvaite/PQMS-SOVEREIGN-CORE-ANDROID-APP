// =============================================================================
// rtl_v6/jedi_gnc_tmr_tai.v
// WP-1.5 & G3/G4:
// - dont_touch 2-of-3 TMR Guardian Neuron Arbiter (dock-up strictly excluded!)
// - Hardware CostBound (cycles/tokens/pulses/energy_uj + 256-bit Spec_Hash)
// - Dual-Stagger Wave Controller (+4/+4/+3 & pairwise 6xDMR +4/+4/+4)
// - Root mod-4 Pulse-Swallowing Gearbox (Boot Gear /2 = 50 MHz) + Graceful
//   Gear /1 Boot-KAT Fallback (GOLDEN_DOT76_ROM) + Canary Downshift
// - Asymmetric Fail-Closed CDC Bridges (THERM_122_N, CAP_GOOD_I, VETO_N)
// - Pad-Adjacent dont_touch Clamp:
//   pad_safe_en = RST_N & THERM_122_N & CAP_GOOD_I & VETO_N & ~boot_kat_trial
// =============================================================================
`timescale 1ns/1ps
`default_nettype none

module jedi_gnc_tmr_tai #(
    parameter signed [75:0] GOLDEN_DOT76_ROM = 76'sh000_0FEA_0000_0000_0000
) (
    // Raw async supervisor pads (for 0-ns pad clamp & async fault set)
    input  wire         clk_in_raw_i,
    input  wire         rst_n_raw_i,
    input  wire         therm_82_n_raw_i,
    input  wire         therm_105_n_raw_i,
    input  wire         therm_122_n_raw_i,
    input  wire         cap_good_raw_i,
    input  wire         veto_n_raw_i,
    input  wire         gear1_allow_raw_i,

    // Core-synchronous control & telemetry
    input  wire         clk_core_i,
    output wire         gear_en_pulse_o,
    output wire  [1:0]  gear_stat_o,
    output wire         boot_kat_trial_o,
    output wire         gear1_lockout_sticky_o,
    output wire         kat_pass_o,

    input  wire         eval_req_i,
    input  wire         eval_clear_i,
    input  wire         mode_dmr_i,
    input  wire         scout_bypass_i,
    input  wire         born_mode_i,
    input  wire         canary_trip_i,
    input  wire         kat_run_req_i,
    input  wire         kat_done_i,
    input  wire signed [75:0] kat_dot76_i,
    input  wire         kat_100m_fail_inj_i,

    // Scout & Reducer inputs
    input  wire         tile0_done_i,
    input  wire         scout_reject_npu_i,
    input  wire         reducer_eval_en_i,
    input  wire         watchdog_trip_i,
    input  wire         any_tile_fault_i,
    input  wire         dmr_divergence_i,
    input  wire         npu_tier_ok_i,
    input  wire         tai_tier_ok_i,

    // CostBound & Spec_Hash inputs
    input  wire         epoch_reset_i,
    input  wire  [31:0] max_cycles_i,
    input  wire  [31:0] max_tokens_i,
    input  wire  [31:0] max_pulses_i,
    input  wire  [31:0] max_energy_uj_i,
    input  wire  [31:0] inc_cycles_i,
    input  wire  [31:0] inc_tokens_i,
    input  wire  [31:0] inc_energy_uj_i,
    input  wire         commit_cost_i,
    input  wire [255:0] active_spec_hash_i,
    input  wire [255:0] expected_spec_hash_i,

    // Test-gated TMR fault injection (1 bit per replica: [0], [1], [2])
    input  wire  [2:0]  tmr_fault_inj_i,

    // Staggered tile controls
    output wire  [11:0] tile_clk_en_o,
    output wire  [11:0] tile_start_o,
    output wire  [11:0] active_tile_mask_o,
    output wire         eval_arm_reducer_o,
    output wire         scout_aborted_o,

    // Voted GNC & Safety Island outputs
    output wire  [1:0]  egress_mode_o,
    output wire         npu_egress_en_o,
    output wire         costbound_trip_o,
    output wire         epoch_ack_o,
    output wire         act_en_p_o,
    output wire         act_en_n_o,
    output wire         tai_heartbeat_o
);

    // =========================================================================
    // 1. Asymmetric Fail-Closed CDC Bridges (0-cycle trip, 2-FF + 64-cyc recovery)
    // =========================================================================
    wire async_safe_raw_w = rst_n_raw_i & therm_122_n_raw_i & cap_good_raw_i & veto_n_raw_i;

    (* ASYNC_REG = "TRUE", keep = 1, dont_touch = "true" *) reg [1:0] sync_safe_q;
    (* ASYNC_REG = "TRUE", keep = 1, dont_touch = "true" *) reg [1:0] sync_t82_q;
    (* ASYNC_REG = "TRUE", keep = 1, dont_touch = "true" *) reg [1:0] sync_t105_q;
    (* ASYNC_REG = "TRUE", keep = 1, dont_touch = "true" *) reg [1:0] sync_g1_q;

    reg [6:0] recov_cnt_q;
    reg       async_fault_latch_q;
    reg       therm122_lock_q;

    wire therm122_trip_n_w = rst_n_raw_i & therm_122_n_raw_i;
    always @(posedge clk_in_raw_i or negedge rst_n_raw_i) begin
        if (!rst_n_raw_i) begin
            therm122_lock_q <= 1'b0;
        end else if (!therm_122_n_raw_i) begin
            therm122_lock_q <= 1'b1;
        end else if (epoch_reset_i) begin
            therm122_lock_q <= 1'b0;
        end
    end

    wire _unused_t122_n = &{1'b0, therm122_trip_n_w};

    always @(posedge clk_in_raw_i or negedge async_safe_raw_w) begin
        if (!async_safe_raw_w) begin
            sync_safe_q         <= 2'b00;
            recov_cnt_q         <= 7'd0;
            async_fault_latch_q <= 1'b1;
        end else begin
            sync_safe_q <= {sync_safe_q[0], 1'b1};
            if (sync_safe_q[1]) begin
                if (recov_cnt_q >= 7'd64) begin
                    if (!therm122_lock_q) begin
                        async_fault_latch_q <= 1'b0;
                    end
                end else begin
                    recov_cnt_q <= recov_cnt_q + 7'd1;
                end
            end else begin
                recov_cnt_q <= 7'd0;
            end
        end
    end

    always @(posedge clk_in_raw_i or negedge rst_n_raw_i) begin
        if (!rst_n_raw_i) begin
            sync_t82_q  <= 2'b00;
            sync_t105_q <= 2'b00;
            sync_g1_q   <= 2'b00;
        end else begin
            sync_t82_q  <= {sync_t82_q[0],  therm_82_n_raw_i};
            sync_t105_q <= {sync_t105_q[0], therm_105_n_raw_i};
            sync_g1_q   <= {sync_g1_q[0],   gear1_allow_raw_i};
        end
    end

    // =========================================================================
    // 2. Root Mod-4 Gearbox + Graceful Gear /1 Boot-KAT Fallback + Canary
    //    Gear encoding: 2'b00 = /1 (100M), 2'b01 = /2 (50M boot default),
    //                   2'b10 = /4 (25M),  2'b11 = HARD_CUT_ROM (0M)
    // =========================================================================
    reg [1:0]  mod4_phase_q;
    reg [1:0]  gear_q;
    reg [2:0]  down_filt_q;
    reg [10:0] up_hyst_q;
    reg        boot_kat_trial_q;
    reg [1:0]  kat_stage_q; // 0=idle, 1=trial_100m, 2=retest_50m, 3=done
    reg        gear1_lockout_sticky_q;
    reg        kat_pass_q;

    always @(posedge clk_in_raw_i or negedge rst_n_raw_i) begin
        if (!rst_n_raw_i) begin
            mod4_phase_q           <= 2'd0;
            gear_q                 <= 2'b01; // Fail-safe boot into Gear /2 (50 MHz)
            down_filt_q            <= 3'd0;
            up_hyst_q              <= 11'd0;
            boot_kat_trial_q       <= 1'b0;
            kat_stage_q            <= 2'd0;
            gear1_lockout_sticky_q <= 1'b0;
            kat_pass_q             <= 1'b0;
        end else begin
            mod4_phase_q <= mod4_phase_q + 2'd1;

            if (!therm_122_n_raw_i || async_fault_latch_q) begin
                gear_q           <= 2'b11;
                boot_kat_trial_q <= 1'b0;
            end else if (kat_run_req_i && (kat_stage_q == 2'd0)) begin
                kat_pass_q <= 1'b0;
                if (sync_g1_q[1] && sync_t82_q[1] && !gear1_lockout_sticky_q) begin
                    boot_kat_trial_q <= 1'b1;
                    gear_q           <= 2'b00;
                    kat_stage_q      <= 2'd1;
                end else begin
                    boot_kat_trial_q <= 1'b1;
                    gear_q           <= 2'b01;
                    kat_stage_q      <= 2'd2;
                end
            end else if (kat_stage_q == 2'd1) begin
                if (canary_trip_i || watchdog_trip_i || (kat_done_i && (kat_100m_fail_inj_i || (kat_dot76_i != GOLDEN_DOT76_ROM)))) begin
                    // Graceful fallback: lock out Gear /1 sticky, re-verify at 50 MHz!
                    gear1_lockout_sticky_q <= 1'b1;
                    gear_q                 <= 2'b01;
                    kat_stage_q            <= 2'd2;
                end else if (kat_done_i && (kat_dot76_i == GOLDEN_DOT76_ROM)) begin
                    boot_kat_trial_q <= 1'b0;
                    kat_pass_q       <= 1'b1;
                    gear_q           <= 2'b00;
                    kat_stage_q      <= 2'd3;
                end
            end else if (kat_stage_q == 2'd2) begin
                if (kat_done_i && (kat_dot76_i == GOLDEN_DOT76_ROM) && !watchdog_trip_i) begin
                    boot_kat_trial_q <= 1'b0;
                    kat_pass_q       <= 1'b1;
                    gear_q           <= 2'b01;
                    kat_stage_q      <= 2'd3;
                end
            end else begin
                if (kat_run_req_i) begin
                    kat_stage_q <= 2'd0;
                end
                // Live Canary or Thermal Downshift (glitch-free on mod-4 boundary)
                if (canary_trip_i && (gear_q == 2'b00)) begin
                    gear_q                 <= 2'b01;
                    gear1_lockout_sticky_q <= 1'b1;
                end else if (!sync_t105_q[1]) begin
                    up_hyst_q <= 11'd0;
                    if (down_filt_q >= 3'd3) begin
                        gear_q <= 2'b10;
                    end else begin
                        down_filt_q <= down_filt_q + 3'd1;
                    end
                end else if (!sync_t82_q[1] && (gear_q == 2'b00)) begin
                    up_hyst_q <= 11'd0;
                    if (down_filt_q >= 3'd3) begin
                        gear_q <= 2'b01;
                    end else begin
                        down_filt_q <= down_filt_q + 3'd1;
                    end
                end else begin
                    down_filt_q <= 3'd0;
                    if (gear_q == 2'b11 && !async_fault_latch_q) begin
                        gear_q <= 2'b01;
                    end else if ((gear_q == 2'b10) && sync_t105_q[1]) begin
                        if (up_hyst_q >= 11'd1023) begin
                            gear_q    <= 2'b01;
                            up_hyst_q <= 11'd0;
                        end else begin
                            up_hyst_q <= up_hyst_q + 11'd1;
                        end
                    end else if ((gear_q == 2'b01) && sync_g1_q[1] && sync_t82_q[1] && kat_pass_q && !gear1_lockout_sticky_q) begin
                        gear_q <= 2'b00;
                    end
                end
            end
        end
    end

    reg gear_en_w;
    always @(*) begin
        case (gear_q)
            2'b00:   gear_en_w = 1'b1;
            2'b01:   gear_en_w = (mod4_phase_q[0] == 1'b0);
            2'b10:   gear_en_w = (mod4_phase_q == 2'b00);
            default: gear_en_w = 1'b0;
        endcase
    end

    assign gear_en_pulse_o        = gear_en_w;
    assign gear_stat_o            = gear_q;
    assign boot_kat_trial_o       = boot_kat_trial_q;
    assign gear1_lockout_sticky_o = gear1_lockout_sticky_q;
    assign kat_pass_o             = kat_pass_q;

    // =========================================================================
    // 3. Hardware CostBound & 256-Bit Spec_Hash Gate (Core Clock Domain)
    // =========================================================================
    reg [31:0] used_cycles_q;
    reg [31:0] used_tokens_q;
    reg [31:0] used_pulses_q;
    reg [31:0] used_energy_uj_q;
    reg        cost_lockout_q;
    reg        epoch_ack_q;

    wire spec_hash_ok_w = (active_spec_hash_i == expected_spec_hash_i);
    wire over_budget_w  = (used_cycles_q >= max_cycles_i)
                        | (used_tokens_q >= max_tokens_i)
                        | (used_pulses_q >= max_pulses_i)
                        | (used_energy_uj_q >= max_energy_uj_i)
                        | (~spec_hash_ok_w);

    // Forward declaration of voted TAI pulse so CostBound counts real actuator authorizations
    wire voted_tai_en_w;
    reg  voted_tai_d1_q;

    always @(posedge clk_core_i or negedge rst_n_raw_i) begin
        if (!rst_n_raw_i) begin
            used_cycles_q    <= 32'd0;
            used_tokens_q    <= 32'd0;
            used_pulses_q    <= 32'd0;
            used_energy_uj_q <= 32'd0;
            cost_lockout_q   <= 1'b0;
            epoch_ack_q      <= 1'b0;
            voted_tai_d1_q   <= 1'b0;
        end else begin
            voted_tai_d1_q <= voted_tai_en_w;
            if (epoch_reset_i) begin
                used_cycles_q    <= 32'd0;
                used_tokens_q    <= 32'd0;
                used_pulses_q    <= 32'd0;
                used_energy_uj_q <= 32'd0;
                cost_lockout_q   <= 1'b0;
                epoch_ack_q      <= 1'b1;
            end else begin
                epoch_ack_q <= 1'b0;
                if (over_budget_w) begin
                    cost_lockout_q <= 1'b1;
                end
                if (commit_cost_i && !cost_lockout_q) begin
                    used_cycles_q    <= used_cycles_q    + inc_cycles_i;
                    used_tokens_q    <= used_tokens_q    + inc_tokens_i;
                    used_energy_uj_q <= used_energy_uj_q + inc_energy_uj_i;
                end
                if (voted_tai_en_w && !voted_tai_d1_q && !cost_lockout_q) begin
                    used_pulses_q <= used_pulses_q + 32'd1;
                end
            end
        end
    end

    wire cost_trip_w     = cost_lockout_q | over_budget_w;
    assign costbound_trip_o = cost_trip_w;
    assign epoch_ack_o      = epoch_ack_q;

    // =========================================================================
    // 4. Dual-Stagger Wave Controller (<= 4 Tiles/Cycle for clk_en & start)
    //    clk_en[w] at t=w, start[w] at t=w+1
    // =========================================================================
    localparam [2:0] WV_IDLE    = 3'd0;
    localparam [2:0] WV_SCOUT_0 = 3'd1;
    localparam [2:0] WV_SCOUT_W = 3'd2;
    localparam [2:0] WV_WAVE_0  = 3'd3;
    localparam [2:0] WV_WAVE_1  = 3'd4;
    localparam [2:0] WV_WAVE_2  = 3'd5;
    localparam [2:0] WV_WAVE_3  = 3'd6;
    localparam [2:0] WV_WAIT    = 3'd7;

    reg [2:0]  wv_state_q;
    reg [11:0] tile_clk_en_q;
    reg [11:0] tile_start_q;
    reg [11:0] active_mask_q;
    reg        eval_arm_q;
    reg        scout_aborted_q;

    always @(posedge clk_core_i or negedge rst_n_raw_i) begin
        if (!rst_n_raw_i) begin
            wv_state_q      <= WV_IDLE;
            tile_clk_en_q   <= 12'h000;
            tile_start_q    <= 12'h000;
            active_mask_q   <= 12'h000;
            eval_arm_q      <= 1'b0;
            scout_aborted_q <= 1'b0;
        end else begin
            tile_start_q <= 12'h000;
            eval_arm_q   <= 1'b0;

            case (wv_state_q)
                WV_IDLE: begin
                    if (eval_clear_i) begin
                        scout_aborted_q <= 1'b0;
                        tile_clk_en_q   <= 12'h000;
                    end else if (eval_req_i) begin
                        scout_aborted_q <= 1'b0;
                        if (!mode_dmr_i && !scout_bypass_i && !born_mode_i) begin
                            // BLUE_SCOUT: wake ONLY Tile 0 first
                            tile_clk_en_q <= 12'h001;
                            active_mask_q <= 12'h001;
                            wv_state_q    <= WV_SCOUT_0;
                        end else begin
                            // Full 12-tile wave 0: wake Tiles 0..3 (4 tiles)
                            tile_clk_en_q <= 12'h00F;
                            active_mask_q <= 12'hFFF;
                            eval_arm_q    <= 1'b1;
                            wv_state_q    <= WV_WAVE_0;
                        end
                    end else begin
                        tile_clk_en_q <= 12'h000;
                    end
                end

                WV_SCOUT_0: begin
                    tile_start_q <= 12'h001;
                    wv_state_q   <= WV_SCOUT_W;
                end

                WV_SCOUT_W: begin
                    if (!tile_start_q[0] && tile0_done_i) begin
                        if (scout_reject_npu_i) begin
                            // Early reject! Tiles 1..11 never wake up!
                            tile_clk_en_q   <= 12'h000;
                            scout_aborted_q <= 1'b1;
                            wv_state_q      <= WV_IDLE;
                        end else begin
                            // Expand +4/+4/+3: enable Tiles 1..4 (4 tiles)
                            tile_clk_en_q <= 12'h01F;
                            active_mask_q <= 12'hFFF;
                            eval_arm_q    <= 1'b1;
                            wv_state_q    <= WV_WAVE_1;
                        end
                    end
                end

                WV_WAVE_0: begin
                    // Start Tiles 0..3 (4), clk_en Tiles 4..7 (+4)
                    tile_start_q  <= 12'h00F;
                    tile_clk_en_q <= 12'h0FF;
                    wv_state_q    <= WV_WAVE_1;
                end

                WV_WAVE_1: begin
                    if (active_mask_q == 12'hFFF && tile_clk_en_q == 12'h01F) begin
                        // Scout expansion: start Tiles 1..4 (4), clk_en Tiles 5..8 (+4)
                        tile_start_q  <= 12'h01E;
                        tile_clk_en_q <= 12'h1FF;
                        wv_state_q    <= WV_WAVE_2;
                    end else begin
                        // Direct/DMR: start Tiles 4..7 (4), clk_en Tiles 8..11 (+4)
                        tile_start_q  <= 12'h0F0;
                        tile_clk_en_q <= 12'hFFF;
                        wv_state_q    <= WV_WAVE_3;
                    end
                end

                WV_WAVE_2: begin
                    // Scout expansion: start Tiles 5..8 (4), clk_en Tiles 9..11 (+3)
                    tile_start_q  <= 12'h1E0;
                    tile_clk_en_q <= 12'hFFF;
                    wv_state_q    <= WV_WAVE_3;
                end

                WV_WAVE_3: begin
                    tile_start_q <= (tile_start_q == 12'h1E0) ? 12'hE00 : 12'hF00;
                    wv_state_q   <= WV_WAIT;
                end

                WV_WAIT: begin
                    if (reducer_eval_en_i || watchdog_trip_i) begin
                        tile_clk_en_q <= 12'h000;
                        wv_state_q    <= WV_IDLE;
                    end
                end

                default: begin
                    wv_state_q <= WV_IDLE;
                end
            endcase
        end
    end

    assign tile_clk_en_o      = tile_clk_en_q;
    assign tile_start_o       = tile_start_q;
    assign active_tile_mask_o = active_mask_q;
    assign eval_arm_reducer_o = eval_arm_q;
    assign scout_aborted_o    = scout_aborted_q;

    // =========================================================================
    // 5. dont_touch 2-of-3 TMR Guardian Neuron Arbiter (G3)
    //    Vector voted: {tai_en, npu_en, egress_mode[1:0]} (4 bits)
    // =========================================================================
    wire global_fault_w = async_fault_latch_q
                        | watchdog_trip_i
                        | any_tile_fault_i
                        | dmr_divergence_i
                        | cost_trip_w
                        | scout_aborted_q
                        | (gear_q == 2'b11);

    wire        raw_tai_w    = (~global_fault_w) & (~boot_kat_trial_q) & tai_tier_ok_i;
    wire        raw_npu_w    = (~global_fault_w) & (~boot_kat_trial_q) & npu_tier_ok_i;
    wire [1:0]  raw_egress_w = global_fault_w ? 2'b11 : (raw_npu_w ? 2'b00 : 2'b11);
    wire [3:0]  raw_bundle_w = {raw_tai_w, raw_npu_w, raw_egress_w};

    (* keep = 1, dont_touch = "true" *) wire [3:0] rep0_w = raw_bundle_w ^ {4{tmr_fault_inj_i[0]}};
    (* keep = 1, dont_touch = "true" *) wire [3:0] rep1_w = raw_bundle_w ^ {4{tmr_fault_inj_i[1]}};
    (* keep = 1, dont_touch = "true" *) wire [3:0] rep2_w = raw_bundle_w ^ {4{tmr_fault_inj_i[2]}};

    (* keep = 1, dont_touch = "true" *)
    wire [3:0] voted_bundle_w = (rep0_w & rep1_w) | (rep1_w & rep2_w) | (rep0_w & rep2_w);

    assign voted_tai_en_w   = voted_bundle_w[3];
    assign npu_egress_en_o  = voted_bundle_w[2];
    assign egress_mode_o    = voted_bundle_w[1:0];

    // Heartbeat toggles on core clock while TAI is validly authorized
    reg hb_toggle_q;
    always @(posedge clk_core_i or negedge rst_n_raw_i) begin
        if (!rst_n_raw_i) begin
            hb_toggle_q <= 1'b0;
        end else if (voted_tai_en_w) begin
            hb_toggle_q <= ~hb_toggle_q;
        end else begin
            hb_toggle_q <= 1'b0;
        end
    end

    // =========================================================================
    // 6. Pad-Adjacent dont_touch Safety Clamp (G3 & Theorem 13)
    //    Safe state: {ACT_EN_P, ACT_EN_N} = 2'b00, TAI_HEARTBEAT_O = 0
    // =========================================================================
    (* keep = 1, dont_touch = "true" *)
    wire pad_safe_en_w = rst_n_raw_i
                       & therm_122_n_raw_i
                       & cap_good_raw_i
                       & veto_n_raw_i
                       & (~boot_kat_trial_q);

    (* keep = 1, dont_touch = "true" *) wire act_p_clamped_w = pad_safe_en_w & voted_tai_en_w;
    (* keep = 1, dont_touch = "true" *) wire act_n_clamped_w = pad_safe_en_w & 1'b0; // Active = 2'b10, Safe = 2'b00
    (* keep = 1, dont_touch = "true" *) wire hb_clamped_w    = pad_safe_en_w & voted_tai_en_w & hb_toggle_q;

    assign act_en_p_o      = act_p_clamped_w;
    assign act_en_n_o      = act_n_clamped_w;
    assign tai_heartbeat_o = hb_clamped_w;
endmodule
`default_nettype wire
