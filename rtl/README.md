# `rtl/` — Synthesizable 64D-ODOS-Gate & Two-Pass Kahan–Parlett $\mathcal{G}_3$ Kevlar Core (`V2.0-RTL-ALPHA`)

**Document-ID:** `WORK-ORDER-AG-17` (`PQMS-ODOS-MTSC-V-MAX-12-RTL-CORE-V2.0-ALPHA`)  
**Master Hardware Specification:** [`PQMS-ODOS-MTSC-V-MAX-12-RTL-CORE-V2.0-ALPHA.md`](https://github.com/NathaliaLietuvaite/Quantenkommunikation/blob/main/PQMS-ODOS-MTSC-V-MAX-12-RTL-CORE-V2.0-ALPHA.md)

This directory contains the synthesizable IEEE 1800-2017 SystemVerilog hardware realization of `vmax_alpha/geometry.py` (`evaluate_raw_gate()` + Two-Pass Kahan–Parlett $\mathcal{G}_3$ orthogonal boundary stripping), its bit-exact integer `Q2.30` reference model, a native Verilator C++ hardware emulator, a 7-test `cocotb` verification suite, and a Yosys synthesis flow.

## Module Inventory

| File | Responsibility |
| :--- | :--- |
| `odos_gate_core.sv` | Synthesizable SystemVerilog core (`Q2.30` datapath, `Q12.60` 72-bit accumulators, `195`-cycle constant-time fail-closed FSM, zero divisions, zero `sqrt()`, `0` Verilator `-Wall` warnings) |
| `gen_rom_hex.py` | Generates `rom/l_vec_q2_30.hex`, `rom/g3_vec_q2_30.hex`, and `rom/rom_manifest.json` after asserting `CANONICAL_LITTLE_VECTOR_SEAL == bb17ede9...` |
| `odos_q2_30_ref.py` | Pure-integer Python `Q2.30` golden reference model achieving exact `0 LSB` parity against `odos_gate_core.sv` |
| `sim_main.cpp` | Native Verilator C++ emulator harness (`--vcd` waveform tracing + single-line JSON stdout telemetry) |
| `build_emulator.sh` | Generates canonical ROMs, runs `verilator --lint-only -Wall`, and compiles `rtl/build/odos_gate_emu` |
| `run_hw_emulator.py` | Executes the 7-scenario hardware verification matrix (incl. $N=500$ isotropic $S^{63}$ noise + Yosys synthesis stats) and seals `telemetry/VMAX_RTL_GATE_EMULATOR_REPORT.json` |
| `test_odos_gate_cocotb.py` + `Makefile` | `7 / 7` cycle-accurate `cocotb 2.1.0` hardware testbench (`T-RTL-01`–`T-RTL-07`, `100 MHz` Verilator) |
| `synth_check.ys` | 4-line Yosys generic synthesis & cell/flip-flop count script (`626` coarse RTL cells / `9` `$mul`; `89,609` post-`techmap` cells / `2,839` FFs) |

## Quickstart (Verilator + `cocotb` + Yosys)

```bash
# 1. Build native hardware emulator (Verilator >= 5.036, g++, make)
bash rtl/build_emulator.sh

# 2. Run 7-scenario hardware emulator + Yosys synthesis audit (0 LSB diff, 0/500 noise passes)
PYTHONPATH=. python3 -m rtl.run_hw_emulator

# 3. Run 7/7 cycle-accurate cocotb tests
make -C rtl

# 4. Run full CI suite (47/47 tests on Node Alpha; Verilator tests auto-skip cleanly on Colab/CPU)
python3 -m unittest discover -s vmax_alpha/tests -v
```

> **Precision Disclosure (`REGISTER_D`):** In 32-bit signed `Q2.30`, $1\text{ LSB} = 2^{-30} \approx 9.3132 \times 10^{-10}$, so software `binary64`'s `1e-12` bleed bound is physically unrepresentable in 32-bit fixed-point. Two-Pass Kahan–Parlett stripping enforces `BLEED_CEIL_Q2_30 = 32 LSB` ($2.98 \times 10^{-8} < 6.9 \times 10^{-8}$ ppm baseline) and empirically reaches **`0 LSB`** fixed-point bleed ($1.214 \times 10^{-10}$ in external `float64` on $\theta = 0.25$ $\mathcal{G}_3$ mixtures).
