#!/usr/bin/env bash
set -euo pipefail
export PATH="/home/nathalia/.local/oss-cad-suite/bin:$PATH"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

verilator -Wall --cc --exe --build -j 4 \
  --top-module odos_gate_axi4_top \
  -Mdir /tmp/obj_axi4_tb \
  rtl/odos_sram_64x32_1p.sv rtl/odos_gate_core_v4.sv rtl/odos_gate_axi4_top.sv \
  rtl/tb/tb_odos_gate_axi4_top.cpp

/tmp/obj_axi4_tb/Vodos_gate_axi4_top
