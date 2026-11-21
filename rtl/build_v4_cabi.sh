#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [ -d "${HOME}/.local/oss-cad-suite/bin" ]; then
    export PATH="${PATH}:${HOME}/.local/oss-cad-suite/bin"
fi

PY_BIN="python3"
if [ -x "${HOME}/vmax_310/bin/python" ]; then
    PY_BIN="${HOME}/vmax_310/bin/python"
fi

PYTHONPATH=. "$PY_BIN" -m rtl.gen_rom_hex
verilator --lint-only -Wall --top-module odos_gate_core_v4 rtl/odos_sram_64x32_1p.sv rtl/odos_gate_core_v4.sv
if command -v iverilog >/dev/null 2>&1; then
    mkdir -p rtl/build
    iverilog -g2012 -s odos_gate_core_v4 -o rtl/build/odos_v4_iverilog.out rtl/odos_sram_64x32_1p.sv rtl/odos_gate_core_v4.sv
fi

mkdir -p rtl/build/obj_v4_cabi
verilator -Wall --cc --top-module odos_gate_core_v4 \
    rtl/odos_sram_64x32_1p.sv rtl/odos_gate_core_v4.sv \
    --Mdir rtl/build/obj_v4_cabi \
    -CFLAGS "-O3 -fPIC"

make -C rtl/build/obj_v4_cabi -f Vodos_gate_core_v4.mk -j"$(nproc)"
VERILATOR_ROOT_PATH="$(verilator -getenv VERILATOR_ROOT)"

g++ -O3 -shared -fPIC \
    -Irtl/build/obj_v4_cabi \
    -I"${VERILATOR_ROOT_PATH}/include" \
    -I"${VERILATOR_ROOT_PATH}/include/vltstd" \
    rtl/sim_c_api_v4.cpp \
    rtl/build/obj_v4_cabi/Vodos_gate_core_v4__ALL.a \
    "${VERILATOR_ROOT_PATH}/include/verilated.cpp" \
    "${VERILATOR_ROOT_PATH}/include/verilated_threads.cpp" \
    -lpthread \
    -o rtl/build/libodos_gate_v4.so
