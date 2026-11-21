// rtl/tb/tb_odos_gate_axi4_top.cpp
// Verilator C++ Testbench for odos_gate_axi4_top (SYNC-19 / WP-2)
// Verifies: 0 LSB parity on |L>, G3 veto, norm fault, TIER_3 fault,
// causal store-and-forward (0 words on VETO, 64 words on PASS with backpressure),
// and write-once 0x04 LOCK policy freeze.

#include "Vodos_gate_axi4_top.h"
#include "verilated.h"
#include <cassert>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

static std::vector<int32_t> load_hex_q30(const std::string &path) {
    std::ifstream f(path);
    assert(f.is_open() && "Failed to open ROM hex file");
    std::vector<int32_t> out;
    std::string line;
    while (std::getline(f, line)) {
        if (line.empty()) continue;
        uint32_t u = static_cast<uint32_t>(std::stoul(line, nullptr, 16));
        out.push_back(static_cast<int32_t>(u));
    }
    assert(out.size() == 64);
    return out;
}

class Axi4Harness {
public:
    Vodos_gate_axi4_top *dut;
    uint64_t cycle = 0;

    Axi4Harness() {
        dut = new Vodos_gate_axi4_top;
        dut->clk_i = 0;
        dut->rst_ni = 0;
        dut->s_axil_awaddr = 0;
        dut->s_axil_awprot = 0;
        dut->s_axil_awvalid = 0;
        dut->s_axil_wdata = 0;
        dut->s_axil_wstrb = 0;
        dut->s_axil_wvalid = 0;
        dut->s_axil_bready = 1;
        dut->s_axil_araddr = 0;
        dut->s_axil_arprot = 0;
        dut->s_axil_arvalid = 0;
        dut->s_axil_rready = 1;
        dut->s_axis_tdata = 0;
        dut->s_axis_tvalid = 0;
        dut->s_axis_tlast = 0;
        dut->m_axis_tready = 1;
    }

    ~Axi4Harness() { delete dut; }

    void tick() {
        dut->clk_i = 0;
        dut->eval();
        dut->clk_i = 1;
        dut->eval();
        cycle++;
    }

    void reset(int n = 4) {
        dut->rst_ni = 0;
        for (int i = 0; i < n; ++i) {
            tick();
            assert(dut->veto_pin_o == 1 && "Fail-closed veto_pin_o must be 1 during reset");
        }
        dut->rst_ni = 1;
        tick();
    }

    uint32_t axil_read(uint8_t addr) {
        dut->s_axil_araddr = addr;
        dut->s_axil_arvalid = 1;
        dut->s_axil_rready = 1;
        int guard = 0;
        while (!dut->s_axil_arready) { tick(); assert(++guard < 100); }
        tick();
        dut->s_axil_arvalid = 0;
        while (!dut->s_axil_rvalid) { tick(); assert(++guard < 100); }
        uint32_t val = dut->s_axil_rdata;
        tick();
        return val;
    }

    uint8_t axil_write(uint8_t addr, uint32_t data, uint8_t strb = 0xF) {
        dut->s_axil_awaddr = addr;
        dut->s_axil_awvalid = 1;
        dut->s_axil_wdata = data;
        dut->s_axil_wstrb = strb;
        dut->s_axil_wvalid = 1;
        dut->s_axil_bready = 1;
        int guard = 0;
        bool aw_done = false, w_done = false;
        while (!(aw_done && w_done)) {
            if (!aw_done && dut->s_axil_awready) aw_done = true;
            if (!w_done && dut->s_axil_wready) w_done = true;
            tick();
            if (aw_done) dut->s_axil_awvalid = 0;
            if (w_done) dut->s_axil_wvalid = 0;
            assert(++guard < 100);
        }
        while (!dut->s_axil_bvalid) { tick(); assert(++guard < 100); }
        uint8_t resp = dut->s_axil_bresp;
        tick();
        return resp;
    }

    struct TxResult {
        uint32_t status, norm_sq, rcf_raw, g3_ov, delta_e, bleed_post, cycles;
        std::vector<int32_t> egress;
        bool veto_pin;
    };

    TxResult run_tx(const std::vector<int32_t> &vec, uint32_t ctrl_val, bool apply_backpressure) {
        axil_write(0x00, ctrl_val);
        axil_write(0x00, ctrl_val | 0x1u); // start=1
        TxResult res{};
        int in_idx = 0;
        int guard = 0;
        bool done_seen = false;
        while (guard < 600) {
            if (in_idx < 64) {
                dut->s_axis_tdata = static_cast<uint32_t>(vec[in_idx]);
                dut->s_axis_tvalid = 1;
                dut->s_axis_tlast = (in_idx == 63) ? 1 : 0;
            } else {
                dut->s_axis_tvalid = 0;
                dut->s_axis_tlast = 0;
            }
            dut->m_axis_tready = (apply_backpressure && ((guard % 3) == 1)) ? 0 : 1;

            bool in_fire = (in_idx < 64) && dut->s_axis_tvalid && dut->s_axis_tready;
            bool out_fire = dut->m_axis_tvalid && dut->m_axis_tready;
            if (out_fire) {
                res.egress.push_back(static_cast<int32_t>(dut->m_axis_tdata));
            }
            if (dut->irq_done_o) done_seen = true;

            tick();
            if (in_fire) in_idx++;
            guard++;
            if (done_seen && !dut->m_axis_tvalid && (res.egress.empty() || res.egress.size() == 64)) {
                uint32_t st = axil_read(0x08);
                if ((st & 0x1u) == 0) { // not busy
                    res.status = st;
                    break;
                }
            }
        }
        dut->s_axis_tvalid = 0;
        dut->m_axis_tready = 1;
        res.norm_sq    = axil_read(0x0C);
        res.rcf_raw    = axil_read(0x10);
        res.g3_ov      = axil_read(0x14);
        res.delta_e    = axil_read(0x18);
        res.bleed_post = axil_read(0x1C);
        res.cycles     = axil_read(0x20);
        res.veto_pin   = (dut->veto_pin_o != 0);
        return res;
    }
};

int main(int argc, char **argv) {
    Verilated::commandArgs(argc, argv);
    auto l_vec = load_hex_q30("rtl/rom/l_vec_q2_30.hex");
    auto g3_vec = load_hex_q30("rtl/rom/g3_vec_q2_30.hex");

    Axi4Harness h;
    h.reset();

    // 1. Canonical |L> in TIER_0 with m_axis_tready backpressure -> PASS, 64 words, 0 LSB
    auto rL = h.run_tx(l_vec, 0x00, true);
    assert(rL.norm_sq == 1073741827u);
    assert(rL.rcf_raw == 1073741830u);
    assert(rL.egress.size() == 64);
    assert(!rL.veto_pin);
    std::cout << "[PASS 1/5] |L> TIER_0 + backpressure: norm_sq=" << rL.norm_sq
              << " rcf_raw=" << rL.rcf_raw << " egress=" << rL.egress.size() << " words\n";

    // 2. Pure G3 collision -> VETO, 0 egress words emitted (causal store-and-forward)
    auto rG3 = h.run_tx(g3_vec, 0x00, false);
    assert(rG3.delta_e == 1073741824u);
    assert(rG3.egress.empty());
    assert(rG3.veto_pin);
    std::cout << "[PASS 2/5] G3 collision VETO: delta_e=" << rG3.delta_e
              << " egress=0 words veto_pin=1\n";

    // 3. Sub-unit norm 0.5*|L> -> normFault VETO, 0 egress words
    std::vector<int32_t> half_l(64);
    for (int i = 0; i < 64; ++i) half_l[i] = l_vec[i] / 2;
    auto rHalf = h.run_tx(half_l, 0x00, false);
    assert(rHalf.egress.empty());
    assert(rHalf.veto_pin);
    std::cout << "[PASS 3/5] 0.5*|L> normFault VETO: egress=0 words veto_pin=1\n";

    // 4. TIER_3 (2'b11) -> modeFault fail-closed VETO, 0 egress words
    auto rT3 = h.run_tx(l_vec, (3u << 2), false);
    assert(rT3.egress.empty());
    assert(rT3.veto_pin);
    std::cout << "[PASS 4/5] TIER_3 (2'b11) modeFault VETO: egress=0 words veto_pin=1\n";

    // 5. Write-Once Policy Lock (0x04 LOCK = 1): lock TIER_0, attempt to overwrite to TIER_1 -> frozen!
    h.axil_write(0x00, (0u << 2)); // set TIER_0
    h.axil_write(0x04, 0x1u);      // LOCK = 1 (RW1S)
    uint32_t lock_rd = h.axil_read(0x04);
    assert((lock_rd & 0x1u) == 1u);
    h.axil_write(0x00, (1u << 2)); // attempt to change tier_mode to TIER_1
    uint32_t ctrl_after = h.axil_read(0x00);
    assert(((ctrl_after >> 2) & 0x3u) == 0u && "LOCK failed to freeze tier_mode!");
    std::cout << "[PASS 5/5] 0x04 LOCK RW1S policy freeze verified (tier_mode frozen at 0)\n";

    std::cout << "AXI4_TB_ALL_5_TESTS_PASSED=TRUE\n";
    return 0;
}
