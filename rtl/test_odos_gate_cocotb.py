"""rtl/test_odos_gate_cocotb.py — 7-Test cocotb Verification Suite for odos_gate_core.sv (WORK-ORDER-AG-17)."""
from __future__ import annotations

import math
import os
from typing import Any, Dict, List, Sequence, Tuple

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
import numpy as np

from rtl.gen_rom_hex import float_to_q2_30
from rtl.odos_q2_30_ref import ONE_Q2_30, RtlGateResult, eval_q2_30_reference, load_rom_hex
from rtl.run_hw_emulator import build_fridu_attack_vectors
from vmax_alpha.config import DIM_S63
from vmax_alpha.geometry import build_orthogonal_tangents, derive_canonical_little_vector, evaluate_raw_gate

RTL_DIR: str = os.path.dirname(os.path.abspath(__file__))
L_ROM_PATH: str = os.path.join(RTL_DIR, "rom", "l_vec_q2_30.hex")
G3_ROM_PATH: str = os.path.join(RTL_DIR, "rom", "g3_vec_q2_30.hex")


def _to_q2_30(vec: np.ndarray) -> List[int]:
    return [float_to_q2_30(float(x)) for x in vec]


def _load_canonical_fixture() -> Tuple[np.ndarray, Dict[str, np.ndarray], List[int], List[int]]:
    l_vec, _ = derive_canonical_little_vector()
    tangents = build_orthogonal_tangents(l_vec)
    l_rom = load_rom_hex(L_ROM_PATH)
    g3_rom = load_rom_hex(G3_ROM_PATH)
    return l_vec, tangents, l_rom, g3_rom


async def _step_edge(dut: Any) -> None:
    await RisingEdge(dut.clk_i)
    await Timer(1, unit="ns")


async def _reset_and_check_fail_closed(dut: Any) -> None:
    dut.rst_ni.value = 0
    dut.start_i.value = 0
    dut.in_valid_i.value = 0
    dut.in_data_i.value = 0
    for _ in range(2):
        await _step_edge(dut)
        assert int(dut.veto_pin_o.value) == 1, "veto_pin_o must be HIGH during reset"
        assert int(dut.gate_pass_o.value) == 0, "gate_pass_o must be LOW during reset"
        assert int(dut.busy_o.value) == 0, "busy_o must be LOW during reset"


async def _drive_vector(
    dut: Any,
    vec_q: Sequence[int],
    stall_at_idx: int = -1,
    assert_busy_fail_closed: bool = False,
) -> Dict[str, Any]:
    dut.rst_ni.value = 1
    dut.start_i.value = 1
    dut.in_valid_i.value = 0
    dut.in_data_i.value = 0
    await _step_edge(dut)
    dut.start_i.value = 0

    stripped: List[int] = [0] * DIM_S63
    stripped_count = 0
    sent = 0
    stalled = False
    for _ in range(512):
        if assert_busy_fail_closed and int(dut.busy_o.value) == 1:
            assert int(dut.veto_pin_o.value) == 1, "veto_pin_o dropped while busy"
            assert int(dut.gate_pass_o.value) == 0, "gate_pass_o asserted while busy"

        if int(dut.in_ready_o.value) == 1 and sent < DIM_S63:
            if sent == stall_at_idx and not stalled:
                dut.in_valid_i.value = 0
                dut.in_data_i.value = 0
                stalled = True
            else:
                dut.in_valid_i.value = 1
                dut.in_data_i.value = int(vec_q[sent]) & 0xFFFFFFFF
                sent += 1
        else:
            dut.in_valid_i.value = 0
            dut.in_data_i.value = 0

        await _step_edge(dut)
        if int(dut.out_valid_o.value) == 1:
            out_idx = int(dut.out_idx_o.value)
            stripped[out_idx] = dut.out_data_o.value.to_signed()
            stripped_count += 1
        if int(dut.done_o.value) == 1:
            break

    assert int(dut.done_o.value) == 1, "DUT did not assert done_o within 512 cycles"
    assert stripped_count == DIM_S63, f"Expected 64 stripped samples, got {stripped_count}"
    return {
        "cycle_count": int(dut.cycle_count_o.value),
        "gate_pass": bool(int(dut.gate_pass_o.value)),
        "veto_pin": bool(int(dut.veto_pin_o.value)),
        "norm_fault": bool(int(dut.norm_fault_o.value)),
        "pure_g3_collision": bool(int(dut.pure_g3_collision_o.value)),
        "norm_sq": dut.norm_sq_o.value.to_signed(),
        "rcf_raw": dut.rcf_raw_o.value.to_signed(),
        "g3_overlap": dut.g3_overlap_o.value.to_signed(),
        "delta_e_raw": dut.delta_e_raw_o.value.to_signed(),
        "bleed_post": dut.bleed_post_o.value.to_signed(),
        "stripped_vec": stripped,
    }


def _assert_zero_lsb_parity(hw: Dict[str, Any], ref: RtlGateResult) -> None:
    assert hw["cycle_count"] == 195, f"Expected 195 cycles, got {hw['cycle_count']}"
    assert hw["gate_pass"] == ref.gate_pass
    assert hw["veto_pin"] == ref.veto_pin
    assert hw["norm_fault"] == ref.norm_fault
    assert hw["pure_g3_collision"] == ref.pure_g3_collision
    assert hw["norm_sq"] == ref.norm_sq
    assert hw["rcf_raw"] == ref.rcf_raw
    assert hw["g3_overlap"] == ref.g3_overlap
    assert hw["delta_e_raw"] == ref.delta_e_raw
    assert hw["bleed_post"] == ref.bleed_post
    assert hw["stripped_vec"] == ref.stripped_vec


@cocotb.test()
async def T_RTL_01_reset_fail_closed(dut: Any) -> None:
    """T-RTL-01: Strictly enforce Fail-Closed (veto_pin_o=1, gate_pass_o=0) in reset and while busy."""
    cocotb.start_soon(Clock(dut.clk_i, 10, unit="ns").start())
    l_vec, _, l_rom, g3_rom = _load_canonical_fixture()
    await _reset_and_check_fail_closed(dut)
    vec_q = _to_q2_30(l_vec)
    hw = await _drive_vector(dut, vec_q, assert_busy_fail_closed=True)
    ref = eval_q2_30_reference(vec_q, l_rom, g3_rom)
    _assert_zero_lsb_parity(hw, ref)
    assert hw["gate_pass"] is True and hw["veto_pin"] is False


@cocotb.test()
async def T_RTL_02_canonical_l_pass_and_constant_time(dut: Any) -> None:
    """T-RTL-02: |L> with 1-cycle backpressure stall at idx=17 passes in exact 195 active cycles with 0 LSB diff."""
    cocotb.start_soon(Clock(dut.clk_i, 10, unit="ns").start())
    l_vec, _, l_rom, g3_rom = _load_canonical_fixture()
    await _reset_and_check_fail_closed(dut)
    vec_q = _to_q2_30(l_vec)
    hw = await _drive_vector(dut, vec_q, stall_at_idx=17, assert_busy_fail_closed=True)
    ref = eval_q2_30_reference(vec_q, l_rom, g3_rom)
    _assert_zero_lsb_parity(hw, ref)
    assert hw["gate_pass"] is True
    assert hw["veto_pin"] is False


@cocotb.test()
async def T_RTL_03_pure_g3_collision_veto(dut: Any) -> None:
    """T-RTL-03: Pure G3 attack triggers VETO, pure_g3_collision=1, bleed_post=ONE_Q2_30, delta_e=ONE_Q2_30."""
    cocotb.start_soon(Clock(dut.clk_i, 10, unit="ns").start())
    _, tangents, l_rom, g3_rom = _load_canonical_fixture()
    g3_vec = tangents["G3_KEVLAR_SANCTUARY_SHIELD"]
    await _reset_and_check_fail_closed(dut)
    vec_q = _to_q2_30(g3_vec)
    hw = await _drive_vector(dut, vec_q)
    ref = eval_q2_30_reference(vec_q, l_rom, g3_rom)
    _assert_zero_lsb_parity(hw, ref)
    assert hw["veto_pin"] is True
    assert hw["gate_pass"] is False
    assert hw["pure_g3_collision"] is True
    assert hw["bleed_post"] == ONE_Q2_30
    assert hw["delta_e_raw"] == ONE_Q2_30


@cocotb.test()
async def T_RTL_04_norm_guard_rejects_zero_and_scaled(dut: Any) -> None:
    """T-RTL-04: Norm guard rejects zero vector and 0.5*|L> with norm_fault=1 and veto_pin=1."""
    cocotb.start_soon(Clock(dut.clk_i, 10, unit="ns").start())
    l_vec, _, l_rom, g3_rom = _load_canonical_fixture()
    for test_vec in (np.zeros(DIM_S63, dtype=np.float64), 0.5 * l_vec):
        await _reset_and_check_fail_closed(dut)
        vec_q = _to_q2_30(test_vec)
        hw = await _drive_vector(dut, vec_q)
        ref = eval_q2_30_reference(vec_q, l_rom, g3_rom)
        _assert_zero_lsb_parity(hw, ref)
        assert hw["norm_fault"] is True
        assert hw["veto_pin"] is True
        assert hw["gate_pass"] is False


@cocotb.test()
async def T_RTL_05_fridu_pax_and_inband_tg1_parity(dut: Any) -> None:
    """T-RTL-05: Fridu core (PASS), PAX (VETO), and In-Band t_G1 (VETO) match Ref (0 LSB) & float64."""
    cocotb.start_soon(Clock(dut.clk_i, 10, unit="ns").start())
    l_vec, tangents, l_rom, g3_rom = _load_canonical_fixture()
    psi_core, psi_pax, psi_inband = build_fridu_attack_vectors()
    cases = [
        (psi_core, True),
        (psi_pax, False),
        (psi_inband, False),
    ]
    for vec, expected_pass in cases:
        await _reset_and_check_fail_closed(dut)
        vec_q = _to_q2_30(vec)
        hw = await _drive_vector(dut, vec_q)
        ref = eval_q2_30_reference(vec_q, l_rom, g3_rom)
        f64 = evaluate_raw_gate(vec, l_vec, tangents)
        _assert_zero_lsb_parity(hw, ref)
        assert hw["gate_pass"] is expected_pass
        assert f64.passed is expected_pass


@cocotb.test()
async def T_RTL_06_isotropic_noise_50_vectors_zero_lsb(dut: Any) -> None:
    """T-RTL-06: 50 isotropic S^63 random vectors (seed=20261115) -> 0/50 pass, 0 LSB diff, 195 cycles."""
    cocotb.start_soon(Clock(dut.clk_i, 10, unit="ns").start())
    _, _, l_rom, g3_rom = _load_canonical_fixture()
    rng = np.random.RandomState(20261115)
    await _reset_and_check_fail_closed(dut)
    for _ in range(50):
        raw = rng.randn(DIM_S63).astype(np.float64)
        unit_v = raw / float(np.linalg.norm(raw))
        vec_q = _to_q2_30(unit_v)
        hw = await _drive_vector(dut, vec_q)
        ref = eval_q2_30_reference(vec_q, l_rom, g3_rom)
        _assert_zero_lsb_parity(hw, ref)
        assert hw["gate_pass"] is False
        assert hw["veto_pin"] is True


@cocotb.test()
async def T_RTL_07_stripped_output_orthogonality(dut: Any) -> None:
    """T-RTL-07: Mixed cos(0.25)|L> + sin(0.25)t_G3 streams out v_clean with |<v_clean, t_G3>| < 3e-8."""
    cocotb.start_soon(Clock(dut.clk_i, 10, unit="ns").start())
    l_vec, tangents, l_rom, g3_rom = _load_canonical_fixture()
    g3_vec = tangents["G3_KEVLAR_SANCTUARY_SHIELD"]
    theta = 0.25
    mixed = math.cos(theta) * l_vec + math.sin(theta) * g3_vec
    mixed = mixed / float(np.linalg.norm(mixed))
    await _reset_and_check_fail_closed(dut)
    vec_q = _to_q2_30(mixed)
    hw = await _drive_vector(dut, vec_q)
    ref = eval_q2_30_reference(vec_q, l_rom, g3_rom)
    _assert_zero_lsb_parity(hw, ref)
    v_clean_f64 = np.array(hw["stripped_vec"], dtype=np.float64) / float(ONE_Q2_30)
    residual_dot = abs(float(np.dot(v_clean_f64, g3_vec)))
    assert residual_dot < 3e-8, f"Expected |<v_clean, t_G3>| < 3e-8, got {residual_dot:.3e}"
