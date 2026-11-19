// rtl/sim_main.cpp — Native Verilator Hardware Emulator for odos_gate_core.sv
#include "Vodos_gate_core.h"
#include "verilated.h"
#include "verilated_vcd_c.h"

#include <cstdint>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

static void tick(Vodos_gate_core* dut, VerilatedVcdC* tfp, uint64_t& sim_time) {
    dut->clk_i = 0;
    dut->eval();
    if (tfp) tfp->dump(sim_time++);
    dut->clk_i = 1;
    dut->eval();
    if (tfp) tfp->dump(sim_time++);
}

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);
    std::string vcd_path;
    std::string in_path;
    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--vcd" && i + 1 < argc) {
            vcd_path = argv[++i];
        } else {
            in_path = arg;
        }
    }

    std::istream* in_stream = &std::cin;
    std::ifstream file_stream;
    if (!in_path.empty()) {
        file_stream.open(in_path);
        if (!file_stream.is_open()) {
            std::cerr << "ERROR: cannot open input vector file: " << in_path << "\n";
            return 2;
        }
        in_stream = &file_stream;
    }

    std::vector<int32_t> vec;
    std::string token;
    while (*in_stream >> token) {
        if (!token.empty() && token.back() == ',') token.pop_back();
        vec.push_back(static_cast<int32_t>(std::stoll(token)));
    }
    if (vec.size() != 64) {
        std::cerr << "ERROR: expected 64 Q2.30 int32 values, got " << vec.size() << "\n";
        return 3;
    }

    auto* dut = new Vodos_gate_core();
    VerilatedVcdC* tfp = nullptr;
    uint64_t sim_time = 0;
    if (!vcd_path.empty()) {
        Verilated::traceEverOn(true);
        tfp = new VerilatedVcdC();
        dut->trace(tfp, 99);
        tfp->open(vcd_path.c_str());
    }

    // 1. Fail-Closed Reset Check (2 cycles)
    dut->rst_ni = 0;
    dut->start_i = 0;
    dut->in_valid_i = 0;
    dut->in_data_i = 0;
    tick(dut, tfp, sim_time);
    tick(dut, tfp, sim_time);
    const int reset_veto_pin = dut->veto_pin_o;
    const int reset_gate_pass = dut->gate_pass_o;

    // 2. Release reset & pulse start_i
    dut->rst_ni = 1;
    dut->start_i = 1;
    tick(dut, tfp, sim_time);
    dut->start_i = 0;

    // 3. Stream 64 Q2.30 elements and capture 64 stripped output elements
    std::vector<int32_t> stripped;
    stripped.reserve(64);
    size_t sent = 0;
    int guard = 0;
    while (!dut->done_o && guard < 512) {
        if (dut->in_ready_o && sent < 64) {
            dut->in_valid_i = 1;
            dut->in_data_i = static_cast<uint32_t>(vec[sent]);
            ++sent;
        } else {
            dut->in_valid_i = 0;
            dut->in_data_i = 0;
        }
        tick(dut, tfp, sim_time);
        if (dut->out_valid_o) {
            stripped.push_back(static_cast<int32_t>(dut->out_data_o));
        }
        ++guard;
    }
    if (dut->out_valid_o && stripped.size() < 64) {
        stripped.push_back(static_cast<int32_t>(dut->out_data_o));
    }

    // 4. Emit deterministic JSON telemetry
    std::cout << "{"
              << "\"reset_fail_closed\":" << ((reset_veto_pin == 1 && reset_gate_pass == 0) ? "true" : "false") << ","
              << "\"done\":" << (dut->done_o ? "true" : "false") << ","
              << "\"cycle_count\":" << static_cast<uint32_t>(dut->cycle_count_o) << ","
              << "\"gate_pass\":" << (dut->gate_pass_o ? "true" : "false") << ","
              << "\"veto_pin\":" << (dut->veto_pin_o ? "true" : "false") << ","
              << "\"norm_fault\":" << (dut->norm_fault_o ? "true" : "false") << ","
              << "\"pure_g3_collision\":" << (dut->pure_g3_collision_o ? "true" : "false") << ","
              << "\"norm_sq_q\":" << static_cast<int32_t>(dut->norm_sq_o) << ","
              << "\"rcf_raw_q\":" << static_cast<int32_t>(dut->rcf_raw_o) << ","
              << "\"g3_overlap_q\":" << static_cast<int32_t>(dut->g3_overlap_o) << ","
              << "\"delta_e_raw_q\":" << static_cast<int32_t>(dut->delta_e_raw_o) << ","
              << "\"bleed_post_q\":" << static_cast<int32_t>(dut->bleed_post_o) << ","
              << "\"stripped_vec\":[";
    for (size_t i = 0; i < stripped.size(); ++i) {
        if (i > 0) std::cout << ",";
        std::cout << stripped[i];
    }
    std::cout << "]}\n";

    if (tfp) {
        tfp->close();
        delete tfp;
    }
    delete dut;
    return dut->done_o ? 0 : 4;
}
