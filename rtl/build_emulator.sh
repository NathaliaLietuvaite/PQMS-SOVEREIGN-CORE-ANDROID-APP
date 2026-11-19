#!/usr/bin/env bash
set -euo pipefail

if ! command -v verilator >/dev/null 2>&1 && [ -d "${HOME}/.local/oss-cad-suite/bin" ]; then
  export PATH="${PATH}:${HOME}/.local/oss-cad-suite/bin"
  export VERILATOR_ROOT="${HOME}/.local/oss-cad-suite/share/verilator"
fi

PYTHONPATH=. python3 -m rtl.gen_rom_hex
mkdir -p rtl/build
verilator --lint-only -Wall rtl/odos_gate_core.sv
verilator --cc --exe --build --trace -j "$(nproc)" \
  --Mdir rtl/build/obj_dir \
  -o ../odos_gate_emu \
  rtl/odos_gate_core.sv rtl/sim_main.cpp
echo "[OK] Native Hardware Emulator built: rtl/build/odos_gate_emu"
