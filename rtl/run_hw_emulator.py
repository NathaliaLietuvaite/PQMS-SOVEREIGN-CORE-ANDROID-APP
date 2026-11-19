"""rtl/run_hw_emulator.py — 7-Scenario Hardware Emulator & Yosys Synthesis Verifier (WORK-ORDER-AG-17)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from rtl.gen_rom_hex import float_to_q2_30, generate_roms
from rtl.odos_q2_30_ref import (
    BLEED_CEIL_Q2_30,
    DELTA_E_CEIL_Q2_30,
    NORM_MAX_Q2_30,
    NORM_MIN_Q2_30,
    ONE_Q2_30,
    RCF_FLOOR_Q2_30,
    STRIP_NORM_MIN_Q2_30,
    RtlGateResult,
    eval_q2_30_reference,
    load_rom_hex,
)
from vmax_alpha.config import CANONICAL_LITTLE_VECTOR_SEAL, DIM_S63, REGISTER_D, REGISTER_M, REGISTER_T
from vmax_alpha.fridu_enclave_g import FriduEnclave
from vmax_alpha.geometry import RawGateEvaluation, build_orthogonal_tangents, derive_canonical_little_vector, evaluate_raw_gate

REPO_ROOT: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resolve_eda_env() -> Dict[str, str]:
    """Build subprocess env, appending user-space oss-cad-suite if Verilator/Yosys are not on PATH."""
    env = os.environ.copy()
    oss_root = os.path.expanduser("~/.local/oss-cad-suite")
    oss_bin = os.path.join(oss_root, "bin")
    if os.path.isdir(oss_bin) and oss_bin not in env.get("PATH", "").split(os.pathsep):
        env["PATH"] = f"{env.get('PATH', '')}{os.pathsep}{oss_bin}"
    if "VERILATOR_ROOT" not in env and os.path.isdir(os.path.join(oss_root, "share", "verilator")):
        env["VERILATOR_ROOT"] = os.path.join(oss_root, "share", "verilator")
    return env


def vec_to_q2_30(vec: np.ndarray) -> List[int]:
    return [float_to_q2_30(float(x)) for x in vec]


def q2_30_to_float(val: int) -> float:
    return float(val) / float(ONE_Q2_30)


def invoke_emulator(
    vec_q: Sequence[int],
    emu_path: str,
    cwd: str,
    vcd_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute compiled Verilator binary on one 64D Q2.30 vector and parse JSON telemetry."""
    cmd = [emu_path]
    if vcd_path is not None:
        os.makedirs(os.path.dirname(vcd_path), exist_ok=True)
        cmd.extend(["--vcd", vcd_path])
    payload = " ".join(str(int(x)) for x in vec_q) + "\n"
    proc = subprocess.run(
        cmd,
        input=payload,
        text=True,
        capture_output=True,
        cwd=cwd,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"Emulator exited {proc.returncode}: stderr={proc.stderr.strip()}"
        )
    lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
    if not lines:
        raise RuntimeError("Emulator produced empty stdout")
    return json.loads(lines[-1])


def max_lsb_diff(hw: Dict[str, Any], ref: RtlGateResult) -> int:
    """Compute exact worst-case LSB difference across all 5 scalar registers and 64 stripped outputs."""
    diffs = [
        abs(int(hw["norm_sq_q"]) - ref.norm_sq),
        abs(int(hw["rcf_raw_q"]) - ref.rcf_raw),
        abs(int(hw["g3_overlap_q"]) - ref.g3_overlap),
        abs(int(hw["delta_e_raw_q"]) - ref.delta_e_raw),
        abs(int(hw["bleed_post_q"]) - ref.bleed_post),
    ]
    hw_strip = hw.get("stripped_vec", [])
    if len(hw_strip) != DIM_S63:
        raise RuntimeError(f"Expected 64 stripped outputs, got {len(hw_strip)}")
    for h_val, r_val in zip(hw_strip, ref.stripped_vec):
        diffs.append(abs(int(h_val) - int(r_val)))
    return max(diffs)


def check_hw_matches_ref(hw: Dict[str, Any], ref: RtlGateResult) -> int:
    """Assert exact cycle count, fail-closed reset, boolean flags, and 0 LSB parity."""
    lsb = max_lsb_diff(hw, ref)
    if not hw["reset_fail_closed"] or not hw["done"]:
        raise AssertionError(f"Reset/done contract violated: {hw}")
    if int(hw["cycle_count"]) != 195:
        raise AssertionError(f"Expected 195 cycles, got {hw['cycle_count']}")
    bool_ok = (
        bool(hw["gate_pass"]) == ref.gate_pass
        and bool(hw["veto_pin"]) == ref.veto_pin
        and bool(hw["norm_fault"]) == ref.norm_fault
        and bool(hw["pure_g3_collision"]) == ref.pure_g3_collision
    )
    if not bool_ok or lsb != 0:
        raise AssertionError(f"RTL/Ref mismatch: lsb={lsb}, hw={hw}, ref={ref}")
    return lsb


def float64_diff(hw: Dict[str, Any], f64: RawGateEvaluation) -> float:
    """Compute max absolute error between Q2.30 hardware registers and float64 geometry.py."""
    return max(
        abs(q2_30_to_float(int(hw["rcf_raw_q"])) - f64.rcf_raw),
        abs(q2_30_to_float(int(hw["g3_overlap_q"])) - f64.g3_collision_overlap),
        abs(q2_30_to_float(int(hw["delta_e_raw_q"])) - f64.delta_e_raw),
        abs(q2_30_to_float(int(hw["bleed_post_q"])) - f64.g3_bleed_post_strip),
    )


def summarize_single(
    vec: np.ndarray,
    l_vec: np.ndarray,
    tangents: Dict[str, np.ndarray],
    l_rom: Sequence[int],
    g3_rom: Sequence[int],
    emu_path: str,
    cwd: str,
    vcd_path: Optional[str] = None,
    compare_f64: bool = True,
) -> Tuple[Dict[str, Any], int, float]:
    """Run one vector through RTL emulator, integer reference, and optionally float64 geometry."""
    vec_q = vec_to_q2_30(vec)
    hw = invoke_emulator(vec_q, emu_path, cwd, vcd_path=vcd_path)
    ref = eval_q2_30_reference(vec_q, l_rom, g3_rom)
    lsb = check_hw_matches_ref(hw, ref)
    f64_err = 0.0
    f64_pass: Optional[bool] = None
    if compare_f64:
        f64 = evaluate_raw_gate(vec, l_vec, tangents)
        f64_pass = f64.passed
        if bool(hw["gate_pass"]) != f64.passed:
            raise AssertionError(
                f"PASS/VETO mismatch vs float64: hw={hw['gate_pass']}, f64={f64.passed}"
            )
        f64_err = float64_diff(hw, f64)
    summary = {
        "reset_fail_closed": bool(hw["reset_fail_closed"]),
        "cycle_count": int(hw["cycle_count"]),
        "gate_pass": bool(hw["gate_pass"]),
        "veto_pin": bool(hw["veto_pin"]),
        "norm_fault": bool(hw["norm_fault"]),
        "pure_g3_collision": bool(hw["pure_g3_collision"]),
        "norm_sq_q": int(hw["norm_sq_q"]),
        "rcf_raw_q": int(hw["rcf_raw_q"]),
        "g3_overlap_q": int(hw["g3_overlap_q"]),
        "delta_e_raw_q": int(hw["delta_e_raw_q"]),
        "bleed_post_q": int(hw["bleed_post_q"]),
        "rcf_raw_float": round(q2_30_to_float(int(hw["rcf_raw_q"])), 9),
        "g3_overlap_float": round(q2_30_to_float(int(hw["g3_overlap_q"])), 9),
        "delta_e_raw_float": round(q2_30_to_float(int(hw["delta_e_raw_q"])), 9),
        "bleed_post_float": round(q2_30_to_float(int(hw["bleed_post_q"])), 12),
        "max_lsb_diff_vs_ref": lsb,
        "float64_parity_checked": compare_f64,
        "float64_gate_pass": f64_pass,
        "max_abs_diff_vs_float64": round(f64_err, 12),
    }
    if vcd_path is not None:
        summary["vcd_file"] = os.path.relpath(vcd_path, cwd).replace("\\", "/")
    return summary, lsb, f64_err


def run_isotropic_batch(
    l_vec: np.ndarray,
    tangents: Dict[str, np.ndarray],
    l_rom: Sequence[int],
    g3_rom: Sequence[int],
    emu_path: str,
    cwd: str,
    n_trials: int = 500,
) -> Tuple[Dict[str, Any], int, float]:
    """Execute N=500 isotropic S^63 noise vectors (seed=20261115) matching T-01."""
    rng = np.random.RandomState(20261115)
    passes = 0
    worst_lsb = 0
    worst_f64 = 0.0
    rcf_vals: List[float] = []
    cycles_ok = True
    for _ in range(n_trials):
        raw = rng.randn(DIM_S63).astype(np.float64)
        unit_v = raw / float(np.linalg.norm(raw))
        vec_q = vec_to_q2_30(unit_v)
        hw = invoke_emulator(vec_q, emu_path, cwd)
        ref = eval_q2_30_reference(vec_q, l_rom, g3_rom)
        lsb = check_hw_matches_ref(hw, ref)
        f64 = evaluate_raw_gate(unit_v, l_vec, tangents)
        if bool(hw["gate_pass"]) != f64.passed:
            raise AssertionError("Isotropic PASS/VETO mismatch vs float64")
        passes += int(bool(hw["gate_pass"]))
        cycles_ok = cycles_ok and (int(hw["cycle_count"]) == 195)
        worst_lsb = max(worst_lsb, lsb)
        worst_f64 = max(worst_f64, float64_diff(hw, f64))
        rcf_vals.append(q2_30_to_float(int(hw["rcf_raw_q"])))
    summary = {
        "n_vectors": n_trials,
        "seed": 20261115,
        "gate_passes": passes,
        "veto_count": n_trials - passes,
        "all_195_cycles": cycles_ok,
        "mean_rcf_raw": round(float(np.mean(rcf_vals)), 9),
        "max_rcf_raw": round(float(np.max(rcf_vals)), 9),
        "max_lsb_diff_vs_ref": worst_lsb,
        "max_abs_diff_vs_float64": round(worst_f64, 12),
    }
    return summary, worst_lsb, worst_f64


def parse_yosys_stat_block(text: str) -> Dict[str, Any]:
    """Parse cell, wire, port, and flip-flop statistics from Yosys `stat` output."""
    stats: Dict[str, Any] = {"cells": {}}
    in_cells = False
    for line in text.splitlines():
        m_top = re.match(r"^\s*(\d+)\s+(wires|wire bits|ports|port bits|cells)\s*$", line)
        if m_top:
            key = m_top.group(2).replace(" ", "_")
            if key == "cells":
                stats["cells_total"] = int(m_top.group(1))
                in_cells = True
            else:
                stats[key] = int(m_top.group(1))
                in_cells = False
            continue
        if in_cells:
            m_cell = re.match(r"^\s*(\d+)\s+(\S+)\s*$", line)
            if m_cell:
                stats["cells"][m_cell.group(2)] = int(m_cell.group(1))
            elif line.strip() == "":
                in_cells = False
    ff_count = sum(
        cnt
        for name, cnt in stats["cells"].items()
        if "DFF" in name.upper()
    )
    stats["flip_flop_count"] = ff_count
    stats["combinational_cell_count"] = sum(stats["cells"].values()) - ff_count
    return stats


def run_yosys_synthesis(repo_root: str) -> Dict[str, Any]:
    """Run Yosys RTL synthesis (`rtl/synth_check.ys` + coarse pre-techmap DSP/mul count)."""
    env = resolve_eda_env()
    yosys_bin = shutil.which("yosys", path=env.get("PATH"))
    if not yosys_bin:
        return {"available": False, "epistemic_register": REGISTER_M}

    ver_proc = subprocess.run([yosys_bin, "-V"], capture_output=True, text=True, env=env, check=False)
    gate_proc = subprocess.run(
        [yosys_bin, "-s", "rtl/synth_check.ys"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    coarse_cmd = (
        "read_verilog -sv rtl/odos_gate_core.sv; "
        "hierarchy -check -top odos_gate_core; "
        "proc; opt; fsm; opt; memory; opt; stat"
    )
    coarse_proc = subprocess.run(
        [yosys_bin, "-p", coarse_cmd],
        cwd=repo_root,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if gate_proc.returncode != 0 or coarse_proc.returncode != 0:
        return {
            "available": True,
            "synthesis_passed": False,
            "stderr": (gate_proc.stderr + "\n" + coarse_proc.stderr).strip(),
        }
    gate_stats = parse_yosys_stat_block(gate_proc.stdout)
    coarse_stats = parse_yosys_stat_block(coarse_proc.stdout)
    return {
        "available": True,
        "synthesis_passed": True,
        "epistemic_register": REGISTER_M,
        "yosys_version": ver_proc.stdout.strip(),
        "script": "rtl/synth_check.ys",
        "post_techmap_gate_level": {
            "ports": gate_stats.get("ports", 0),
            "port_bits": gate_stats.get("port_bits", 0),
            "wires": gate_stats.get("wires", 0),
            "wire_bits": gate_stats.get("wire_bits", 0),
            "total_cells": sum(gate_stats["cells"].values()),
            "flip_flop_count": gate_stats["flip_flop_count"],
            "combinational_gate_count": gate_stats["combinational_cell_count"],
            "cell_breakdown": gate_stats["cells"],
        },
        "pre_techmap_coarse_rtl": {
            "total_cells": sum(coarse_stats["cells"].values()),
            "mul_blocks": coarse_stats["cells"].get("$mul", 0),
            "add_sub_blocks": coarse_stats["cells"].get("$add", 0) + coarse_stats["cells"].get("$sub", 0),
            "mem_blocks": sum(v for k, v in coarse_stats["cells"].items() if "mem" in k),
            "cell_breakdown": coarse_stats["cells"],
        },
    }


def build_fridu_attack_vectors() -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Construct exact Appendix G Fridu base core, PAX contaminated, and in-band t_G1 vectors."""
    enclave = FriduEnclave()
    ext_noise = np.arange(1, 65, dtype=np.float64) * (-1.0) ** np.arange(64)
    v_lhs = ext_noise / (float(np.linalg.norm(ext_noise)) + 1e-30)
    v_ext = v_lhs.copy()
    for _ in range(2):
        v_ext = v_ext - enclave.core_basis @ (enclave.core_basis.T @ v_ext)
    v_ext = v_ext / (float(np.linalg.norm(v_ext)) + 1e-30)
    psi_pax = enclave.psi_core + 0.35 * v_ext
    psi_pax = psi_pax / float(np.linalg.norm(psi_pax))
    psi_inband = enclave.psi_core + 0.35 * enclave.t_g1
    psi_inband = psi_inband / float(np.linalg.norm(psi_inband))
    return enclave.psi_core, psi_pax, psi_inband


def run_hw_emulator_suite(repo_root: str = REPO_ROOT) -> Dict[str, Any]:
    """Execute full 7-scenario hardware emulator verification matrix and write sealed JSON report."""
    t0 = time.perf_counter()
    rom_dir = os.path.join(repo_root, "rtl", "rom")
    manifest = generate_roms(rom_dir)
    l_rom = load_rom_hex(os.path.join(rom_dir, "l_vec_q2_30.hex"))
    g3_rom = load_rom_hex(os.path.join(rom_dir, "g3_vec_q2_30.hex"))
    emu_path = os.path.join(repo_root, "rtl", "build", "odos_gate_emu")
    if not os.path.isfile(emu_path):
        raise FileNotFoundError(
            f"Compiled Verilator emulator not found at {emu_path}; run bash rtl/build_emulator.sh"
        )

    l_vec, l_seal = derive_canonical_little_vector()
    if l_seal != CANONICAL_LITTLE_VECTOR_SEAL:
        raise RuntimeError(f"Canonical |L> seal mismatch: {l_seal}")
    tangents = build_orthogonal_tangents(l_vec)
    g3_vec = tangents["G3_KEVLAR_SANCTUARY_SHIELD"]
    psi_core, psi_pax, psi_inband = build_fridu_attack_vectors()

    vcd_l = os.path.join(repo_root, "rtl", "build", "odos_gate_canonical_l.vcd")
    vcd_g3 = os.path.join(repo_root, "rtl", "build", "odos_gate_g3_veto.vcd")

    s1, l1, e1 = summarize_single(l_vec, l_vec, tangents, l_rom, g3_rom, emu_path, repo_root, vcd_path=vcd_l)
    s2, l2, e2 = summarize_single(g3_vec, l_vec, tangents, l_rom, g3_rom, emu_path, repo_root, vcd_path=vcd_g3)
    s3_zero, l3z, _ = summarize_single(
        np.zeros(DIM_S63, dtype=np.float64), l_vec, tangents, l_rom, g3_rom, emu_path, repo_root, compare_f64=False
    )
    s3_half, l3h, _ = summarize_single(
        0.5 * l_vec, l_vec, tangents, l_rom, g3_rom, emu_path, repo_root, compare_f64=False
    )
    s4, l4, e4 = run_isotropic_batch(l_vec, tangents, l_rom, g3_rom, emu_path, repo_root, n_trials=500)
    s5, l5, e5 = summarize_single(psi_core, l_vec, tangents, l_rom, g3_rom, emu_path, repo_root)
    s6, l6, e6 = summarize_single(psi_pax, l_vec, tangents, l_rom, g3_rom, emu_path, repo_root)
    s7, l7, e7 = summarize_single(psi_inband, l_vec, tangents, l_rom, g3_rom, emu_path, repo_root)

    global_max_lsb = max(l1, l2, l3z, l3h, l4, l5, l6, l7)
    global_max_f64 = max(e1, e2, e4, e5, e6, e7)
    if global_max_lsb != 0:
        raise AssertionError(f"Expected 0 LSB global error, got {global_max_lsb}")
    if s4["gate_passes"] != 0 or global_max_f64 >= 5e-8:
        raise AssertionError(f"Noise/precision bound failed: passes={s4['gate_passes']}, err={global_max_f64}")
    if not (s1["gate_pass"] and s5["gate_pass"] and s2["veto_pin"] and s2["pure_g3_collision"]
            and s3_zero["norm_fault"] and s3_half["norm_fault"] and s6["veto_pin"] and s7["veto_pin"]):
        raise AssertionError("One or more scenario verdicts violated specification")

    env = resolve_eda_env()
    vlt_bin = shutil.which("verilator", path=env.get("PATH"))
    vlt_ver = subprocess.run([vlt_bin, "--version"], capture_output=True, text=True, env=env, check=False).stdout.strip() if vlt_bin else "unknown"
    yosys_stats = run_yosys_synthesis(repo_root)

    scenarios = {
        "1_canonical_l": s1,
        "2_pure_g3_attack": s2,
        "3_zero_and_unnormalized": {"zero_vector": s3_zero, "scaled_half_l_vector": s3_half},
        "4_isotropic_random_500": s4,
        "5_fridu_base_core": s5,
        "6_pax_contaminated": s6,
        "7_in_band_tg1_attack": s7,
    }
    seal_payload = {
        "rom_manifest": manifest,
        "scenarios": scenarios,
        "global_max_lsb_diff_vs_ref": global_max_lsb,
        "global_max_abs_diff_vs_float64": round(global_max_f64, 12),
    }
    report_seal = hashlib.sha256(
        json.dumps(seal_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    report = {
        "document_id": "PQMS-ODOS-MTSC-V-MAX-12-RTL-CORE-V2.0-ALPHA",
        "work_order": "WORK-ORDER-AG-17",
        "epistemic_registers": {
            "q2_30_format_and_thresholds": REGISTER_D,
            "constant_time_195_cycle_fsm": REGISTER_T,
            "verilator_rtl_emulation_and_yosys_synth": REGISTER_M,
        },
        "q2_30_honest_quantization_disclosure": {
            "lsb_resolution": 2.0**-30,
            "bleed_ceil_q2_30_lsb": BLEED_CEIL_Q2_30,
            "bleed_ceil_q2_30_float": BLEED_CEIL_Q2_30 * (2.0**-30),
            "ppm_baseline": 6.9e-8,
            "note": (
                "1 LSB in signed 32-bit Q2.30 is 2^-30 (~9.3132e-10). The float64 1e-12 floor from "
                "vmax_alpha/geometry.py is physically unrepresentable in 32-bit fixed-point; Two-Pass "
                "Kahan-Parlett stripping bounds residual hardware bleed to <= 32 LSB (~2.98e-8 < 6.9e-8 ppm)."
            ),
        },
        "normative_constants_q2_30": {
            "ONE_Q2_30": ONE_Q2_30,
            "RCF_FLOOR_Q2_30": RCF_FLOOR_Q2_30,
            "DELTA_E_CEIL_Q2_30": DELTA_E_CEIL_Q2_30,
            "NORM_MIN_Q2_30": NORM_MIN_Q2_30,
            "NORM_MAX_Q2_30": NORM_MAX_Q2_30,
            "STRIP_NORM_MIN_Q2_30": STRIP_NORM_MIN_Q2_30,
            "BLEED_CEIL_Q2_30": BLEED_CEIL_Q2_30,
        },
        "toolchain": {
            "verilator_version": vlt_ver,
            "emulator_binary": "rtl/build/odos_gate_emu",
        },
        "rom_manifest": manifest,
        "summary_verdict": {
            "all_7_scenarios_passed": True,
            "constant_time_cycles": 195,
            "global_max_lsb_diff_vs_ref": global_max_lsb,
            "isotropic_500_passes": s4["gate_passes"],
            "global_max_abs_diff_vs_float64": round(global_max_f64, 12),
            "execution_walltime_ms": round((time.perf_counter() - t0) * 1000.0, 3),
        },
        "scenarios": scenarios,
        "yosys_synthesis": yosys_stats,
        "rtl_report_seal_sha256": report_seal,
    }

    raw_json = json.dumps(report, indent=2) + "\n"
    for out_rel in (
        "VMAX_RTL_GATE_EMULATOR_REPORT.json",
        os.path.join("telemetry", "VMAX_RTL_GATE_EMULATOR_REPORT.json"),
    ):
        out_abs = os.path.join(repo_root, out_rel)
        os.makedirs(os.path.dirname(out_abs), exist_ok=True)
        with open(out_abs, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(raw_json)
    return report


if __name__ == "__main__":
    rep = run_hw_emulator_suite()
    print(json.dumps(rep["summary_verdict"], indent=2))
    print("RTL_REPORT_SEAL_SHA256:", rep["rtl_report_seal_sha256"])
    if rep["yosys_synthesis"].get("synthesis_passed"):
        print("YOSYS_GATE_LEVEL:", json.dumps(rep["yosys_synthesis"]["post_techmap_gate_level"], indent=2))
        print("YOSYS_COARSE_RTL:", json.dumps(rep["yosys_synthesis"]["pre_techmap_coarse_rtl"], indent=2))
