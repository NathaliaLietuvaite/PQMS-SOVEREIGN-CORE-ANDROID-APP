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
verilator --lint-only -Wall rtl/odos_gate_core_v3.sv
if command -v iverilog >/dev/null 2>&1; then
    mkdir -p rtl/build
    iverilog -g2012 -s odos_gate_core_v3 -o rtl/build/odos_v3_iverilog.out rtl/odos_gate_core_v3.sv
fi

mkdir -p rtl/build/obj_v3_cabi
verilator -Wall --cc rtl/odos_gate_core_v3.sv \
    --Mdir rtl/build/obj_v3_cabi \
    -CFLAGS "-O3 -fPIC"

make -C rtl/build/obj_v3_cabi -f Vodos_gate_core_v3.mk -j"$(nproc)"
VERILATOR_ROOT_PATH="$(verilator -getenv VERILATOR_ROOT)"

g++ -O3 -shared -fPIC \
    -Irtl/build/obj_v3_cabi \
    -I"${VERILATOR_ROOT_PATH}/include" \
    -I"${VERILATOR_ROOT_PATH}/include/vltstd" \
    rtl/sim_c_api_v3.cpp \
    rtl/build/obj_v3_cabi/Vodos_gate_core_v3__ALL.a \
    "${VERILATOR_ROOT_PATH}/include/verilated.cpp" \
    "${VERILATOR_ROOT_PATH}/include/verilated_threads.cpp" \
    -lpthread \
    -o rtl/build/libodos_gate_v3.so
