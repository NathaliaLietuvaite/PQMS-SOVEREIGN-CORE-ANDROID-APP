#include <cstdint>
#include <fcntl.h>
#include <unistd.h>
#include <verilated.h>
#include "Vodos_gate_core_v3.h"

struct OdosV3ResultC {
    uint16_t cycle_count;
    uint8_t  reset_fail_closed;
    uint8_t  busy_veto_held;
    uint8_t  gate_pass;
    uint8_t  veto_pin;
    uint8_t  norm_fault;
    uint8_t  pure_g3_collision;
    uint8_t  mode_fault;
    int32_t  norm_sq_q;
    int32_t  rcf_raw_q;
    int32_t  g3_overlap_q;
    int32_t  delta_e_raw_q;
    int32_t  bleed_post_q;
};

struct OdosV3Context {
    VerilatedContext ctx;
    Vodos_gate_core_v3* dut;

    OdosV3Context() : ctx(), dut(nullptr) {
        ctx.randReset(0);
    }
    ~OdosV3Context() {
        delete dut;
        dut = nullptr;
    }
};

static inline void tick_core(Vodos_gate_core_v3* dut) {
    dut->clk_i = 0;
    dut->eval();
    dut->clk_i = 1;
    dut->eval();
}

static int run_transaction_on_dut(
    Vodos_gate_core_v3* dut,
    const int32_t* vec_q30,
    uint8_t tier_mode,
    int32_t stall_at_idx,
    uint8_t tamper_tier_in_flight,
    int32_t* stripped_out_q30,
    OdosV3ResultC* res_out
) {
    if (!dut || !vec_q30 || !stripped_out_q30 || !res_out) {
        return -1;
    }

    dut->rst_ni = 0;
    dut->start_i = 0;
    dut->tier_mode_i = tier_mode & 0x3U;
    dut->in_valid_i = 0;
    dut->in_data_i = 0;
    tick_core(dut);
    tick_core(dut);

    res_out->reset_fail_closed = (dut->veto_pin_o == 1 && dut->gate_pass_o == 0) ? 1 : 0;

    dut->rst_ni = 1;
    dut->start_i = 1;
    dut->tier_mode_i = tier_mode & 0x3U;
    tick_core(dut);
    dut->start_i = 0;

    uint8_t busy_veto_ok = 1;
    int idx = 0;
    bool stalled_once = false;
    while (idx < 64) {
        if (tamper_tier_in_flight) {
            dut->tier_mode_i = (tier_mode ^ 0x3U) & 0x3U;
        }
        if (dut->busy_o && (dut->veto_pin_o != 1 || dut->gate_pass_o != 0)) {
            busy_veto_ok = 0;
        }
        if (idx == stall_at_idx && !stalled_once) {
            dut->in_valid_i = 0;
            dut->in_data_i = 0;
            tick_core(dut);
            stalled_once = true;
            continue;
        }
        dut->in_valid_i = 1;
        dut->in_data_i = vec_q30[idx];
        tick_core(dut);
        idx++;
    }
    dut->in_valid_i = 0;
    dut->in_data_i = 0;

    int guard = 0;
    while (!dut->done_o && guard < 400) {
        if (dut->busy_o && (dut->veto_pin_o != 1 || dut->gate_pass_o != 0)) {
            busy_veto_ok = 0;
        }
        if (dut->out_valid_o && dut->out_idx_o < 64) {
            stripped_out_q30[dut->out_idx_o] = dut->out_data_o;
        }
        tick_core(dut);
        if (dut->out_valid_o && dut->out_idx_o < 64) {
            stripped_out_q30[dut->out_idx_o] = dut->out_data_o;
        }
        guard++;
    }
    if (!dut->done_o) {
        return -2;
    }

    res_out->cycle_count       = dut->cycle_count_o;
    res_out->busy_veto_held    = busy_veto_ok;
    res_out->gate_pass         = dut->gate_pass_o;
    res_out->veto_pin          = dut->veto_pin_o;
    res_out->norm_fault        = dut->norm_fault_o;
    res_out->pure_g3_collision = dut->pure_g3_collision_o;
    res_out->mode_fault        = dut->mode_fault_o;
    res_out->norm_sq_q         = dut->norm_sq_o;
    res_out->rcf_raw_q         = dut->rcf_raw_o;
    res_out->g3_overlap_q      = dut->g3_overlap_o;
    res_out->delta_e_raw_q     = dut->delta_e_raw_o;
    res_out->bleed_post_q      = dut->bleed_post_o;
    return 0;
}

extern "C" OdosV3Context* odos_v3_ctx_create(const char* repo_root) {
    int orig_fd = open(".", O_RDONLY);
    if (repo_root && repo_root[0] != '\0') {
        if (chdir(repo_root) != 0) {
            if (orig_fd >= 0) {
                close(orig_fd);
            }
            return nullptr;
        }
    }
    OdosV3Context* h = new OdosV3Context();
    h->dut = new Vodos_gate_core_v3(&h->ctx);
    if (orig_fd >= 0) {
        int rc_back = fchdir(orig_fd);
        (void)rc_back;
        close(orig_fd);
    }
    return h;
}

extern "C" int odos_v3_ctx_eval(
    OdosV3Context* h,
    const int32_t* vec_q30,
    uint8_t tier_mode,
    int32_t stall_at_idx,
    uint8_t tamper_tier_in_flight,
    int32_t* stripped_out_q30,
    OdosV3ResultC* res_out
) {
    if (!h || !h->dut) {
        return -1;
    }
    return run_transaction_on_dut(
        h->dut, vec_q30, tier_mode, stall_at_idx, tamper_tier_in_flight, stripped_out_q30, res_out
    );
}

extern "C" void odos_v3_ctx_destroy(OdosV3Context* h) {
    delete h;
}

extern "C" int odos_v3_eval_transaction(
    const int32_t* vec_q30,
    uint8_t tier_mode,
    int32_t stall_at_idx,
    uint8_t tamper_tier_in_flight,
    int32_t* stripped_out_q30,
    OdosV3ResultC* res_out
) {
    VerilatedContext ctx;
    ctx.randReset(0);
    Vodos_gate_core_v3 dut(&ctx);
    return run_transaction_on_dut(
        &dut, vec_q30, tier_mode, stall_at_idx, tamper_tier_in_flight, stripped_out_q30, res_out
    );
}
