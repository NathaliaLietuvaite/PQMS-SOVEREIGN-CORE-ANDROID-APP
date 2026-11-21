#include <cstdint>
#include <fcntl.h>
#include <unistd.h>
#include <verilated.h>
#include "Vodos_gate_core_v4.h"

struct OdosV4ResultC {
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

struct OdosV4Context {
    VerilatedContext ctx;
    Vodos_gate_core_v4* dut;

    OdosV4Context() : ctx(), dut(nullptr) {
        ctx.randReset(0);
    }
    ~OdosV4Context() {
        delete dut;
        dut = nullptr;
    }
};

static inline void tick_core(Vodos_gate_core_v4* dut) {
    dut->clk_i = 0;
    dut->eval();
    dut->clk_i = 1;
    dut->eval();
}

static int run_transaction_on_dut(
    Vodos_gate_core_v4* dut,
    const int32_t* vec_q30,
    uint8_t tier_mode,
    int32_t stall_at_idx,
    uint8_t tamper_tier_in_flight,
    int32_t* stripped_out_q30,
    OdosV4ResultC* res_out
) {
    if (!dut || !vec_q30 || !stripped_out_q30 || !res_out) {
        return -1;
    }

    dut->rst_ni = 0;
    dut->start_i = 0;
    dut->tier_mode_i = tier_mode & 0x3U;
    dut->in_valid_i = 0;
    dut->in_data_i = 0;

    uint8_t reset_ok = 1;
    for (int i = 0; i < 2; ++i) {
        tick_core(dut);
        if ((dut->veto_pin_o != 1) || (dut->gate_pass_o != 0)) {
            reset_ok = 0;
        }
    }

    dut->rst_ni = 1;
    dut->start_i = 1;
    dut->tier_mode_i = tier_mode & 0x3U;
    tick_core(dut);
    dut->start_i = 0;

    uint8_t busy_veto_ok = 1;
    for (int idx = 0; idx < 64; ++idx) {
        if (tamper_tier_in_flight && idx == 10) {
            dut->tier_mode_i = (tier_mode ^ 0x3U) & 0x3U;
        }
        if (stall_at_idx == idx) {
            dut->in_valid_i = 0;
            dut->in_data_i = 0;
            for (int s = 0; s < 3; ++s) {
                tick_core(dut);
                if ((dut->veto_pin_o != 1) || (dut->gate_pass_o != 0)) {
                    busy_veto_ok = 0;
                }
            }
        }
        dut->in_valid_i = 1;
        dut->in_data_i = static_cast<uint32_t>(vec_q30[idx]);
        tick_core(dut);
        if ((dut->veto_pin_o != 1) || (dut->gate_pass_o != 0)) {
            busy_veto_ok = 0;
        }
    }
    dut->in_valid_i = 0;
    dut->in_data_i = 0;

    for (int i = 0; i < 64; ++i) {
        stripped_out_q30[i] = 0;
    }

    int captured = 0;
    int guard = 0;
    while (!dut->done_o && guard < 300) {
        if (tamper_tier_in_flight && guard == 50) {
            dut->tier_mode_i = 0x3U;
        }
        tick_core(dut);
        if (dut->out_valid_o && dut->out_idx_o < 64) {
            stripped_out_q30[dut->out_idx_o] = static_cast<int32_t>(dut->out_data_o);
            ++captured;
        }
        if (!dut->done_o) {
            if ((dut->veto_pin_o != 1) || (dut->gate_pass_o != 0)) {
                busy_veto_ok = 0;
            }
        }
        ++guard;
    }

    if (!dut->done_o || captured != 64) {
        return -2;
    }

    res_out->cycle_count       = static_cast<uint16_t>(dut->cycle_count_o);
    res_out->reset_fail_closed = reset_ok;
    res_out->busy_veto_held    = busy_veto_ok;
    res_out->gate_pass         = static_cast<uint8_t>(dut->gate_pass_o);
    res_out->veto_pin          = static_cast<uint8_t>(dut->veto_pin_o);
    res_out->norm_fault        = static_cast<uint8_t>(dut->norm_fault_o);
    res_out->pure_g3_collision = static_cast<uint8_t>(dut->pure_g3_collision_o);
    res_out->mode_fault        = static_cast<uint8_t>(dut->mode_fault_o);
    res_out->norm_sq_q         = static_cast<int32_t>(dut->norm_sq_o);
    res_out->rcf_raw_q         = static_cast<int32_t>(dut->rcf_raw_o);
    res_out->g3_overlap_q      = static_cast<int32_t>(dut->g3_overlap_o);
    res_out->delta_e_raw_q     = static_cast<int32_t>(dut->delta_e_raw_o);
    res_out->bleed_post_q      = static_cast<int32_t>(dut->bleed_post_o);
    return 0;
}

extern "C" {

OdosV4Context* odos_v4_ctx_create(const char* repo_root) {
    int orig_dir_fd = open(".", O_RDONLY | O_DIRECTORY);
    if (repo_root && repo_root[0] != '\0') {
        if (chdir(repo_root) != 0) {
            if (orig_dir_fd >= 0) {
                close(orig_dir_fd);
            }
            return nullptr;
        }
    }
    auto* handle = new OdosV4Context();
    handle->dut = new Vodos_gate_core_v4(&handle->ctx);
    handle->dut->rst_ni = 0;
    handle->dut->clk_i = 0;
    handle->dut->start_i = 0;
    handle->dut->tier_mode_i = 0;
    handle->dut->in_valid_i = 0;
    handle->dut->in_data_i = 0;
    handle->dut->eval();
    if (orig_dir_fd >= 0) {
        int ignored = fchdir(orig_dir_fd);
        (void)ignored;
        close(orig_dir_fd);
    }
    return handle;
}

int odos_v4_ctx_eval(
    OdosV4Context* handle,
    const int32_t* vec_q30,
    uint8_t tier_mode,
    int32_t stall_at_idx,
    uint8_t tamper_tier_in_flight,
    int32_t* stripped_out_q30,
    OdosV4ResultC* res_out
) {
    if (!handle || !handle->dut) {
        return -1;
    }
    return run_transaction_on_dut(
        handle->dut,
        vec_q30,
        tier_mode,
        stall_at_idx,
        tamper_tier_in_flight,
        stripped_out_q30,
        res_out
    );
}

void odos_v4_ctx_destroy(OdosV4Context* handle) {
    delete handle;
}

int odos_v4_eval_transaction(
    const int32_t* vec_q30,
    uint8_t tier_mode,
    int32_t stall_at_idx,
    uint8_t tamper_tier_in_flight,
    int32_t* stripped_out_q30,
    OdosV4ResultC* res_out
) {
    VerilatedContext ctx;
    ctx.randReset(0);
    Vodos_gate_core_v4 dut(&ctx);
    return run_transaction_on_dut(
        &dut,
        vec_q30,
        tier_mode,
        stall_at_idx,
        tamper_tier_in_flight,
        stripped_out_q30,
        res_out
    );
}

}  // extern "C"
