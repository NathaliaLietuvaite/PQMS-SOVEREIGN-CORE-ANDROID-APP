"""
rtl/run_v3_verification.py
End-to-end verification, cold-vs-warm persistent C-ABI throughput benchmark,
3-generation Yosys CMOS/LTP synthesis (V2.0 vs V3.0 vs V3.1), 130 nm SG13G2 kGE
projection, telemetry sealing, and programmatic manuscript sync for Revision
V3.1-RTL-OPTIMUM (WORK-ORDER-AG-21 / SYNC-16).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from typing import Any, Dict, List, Tuple

import numpy as np

from rtl.run_hw_emulator import build_fridu_attack_vectors, resolve_eda_env
from vmax_alpha.bio_lattice import (
    ECOLI_K12_PURE_TANDEM,
    build_crispr_repeat_spacer_array,
    build_phage_tandem_array_200nt,
    calibrate_bio_spectral_encoder,
    dinucleotide_shuffle,
    encode_bio_spectrum_to_s63,
    mononucleotide_shuffle,
)
from vmax_alpha.config import CANONICAL_LITTLE_VECTOR_SEAL, DIM_S63, REGISTER_M
from vmax_alpha.geometry import build_orthogonal_tangents, derive_canonical_little_vector
from vmax_alpha.hw_gate_bridge import (
    OdosGateV3Bridge,
    TIER_0_PURE_CARRIER,
    TIER_1_MOSAIC_LOCUS,
    TIER_2_CORE_LOCK,
    TIER_3_GLITCH_VETO,
    V3HardwareVerdict,
    evaluate_v3_integer_ref,
    float_vec_to_q2_30,
)

REPO_ROOT: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SG13G2_NAND2_AREA_MM2: float = 9.072e-6

# Historical V3.0 (SYNC-15) verified Yosys 0.71+52 combinational 3-MAC baseline
V30_HISTORICAL_YOSYS: Dict[str, Any] = {
    "revision": "V3.0-RTL-ALPHA (SYNC-15, combinational 3-MAC)",
    "coarse_mul_count": 3,
    "coarse_total_cells": 613,
    "post_techmap_total_cells": 42600,
    "post_techmap_flip_flops": 2777,
    "post_techmap_combinational": 39823,
    "cmos_transistors": 328084,
    "kge": 82.02,
    "ltp_depth": 215,
}


def _max_lsb_diff(a: V3HardwareVerdict, b: V3HardwareVerdict) -> int:
    diffs = [
        abs(a.norm_sq_q - b.norm_sq_q),
        abs(a.rcf_raw_q - b.rcf_raw_q),
        abs(a.g3_overlap_q - b.g3_overlap_q),
        abs(a.delta_e_raw_q - b.delta_e_raw_q),
        abs(a.bleed_post_q - b.bleed_post_q),
    ]
    for x, y in zip(a.stripped_vec_q, b.stripped_vec_q):
        diffs.append(abs(x - y))
    return max(diffs)


def _assert_parity(hw: V3HardwareVerdict, ref: V3HardwareVerdict, label: str) -> int:
    lsb = _max_lsb_diff(hw, ref)
    flags_ok = (
        hw.cycle_count == 195
        and hw.reset_fail_closed
        and hw.busy_veto_held
        and hw.gate_pass == ref.gate_pass
        and hw.veto_pin == ref.veto_pin
        and hw.norm_fault == ref.norm_fault
        and hw.pure_g3_collision == ref.pure_g3_collision
        and hw.mode_fault == ref.mode_fault
    )
    if not flags_ok or lsb != 0:
        raise AssertionError(f"V3.1 parity failure on {label}: lsb={lsb}, hw={hw}, ref={ref}")
    return lsb


def _parse_stat_counts(section: str) -> Dict[str, Any]:
    total_m = re.search(r"^\s*(\d+)\s+cells\s*$", section, flags=re.M)
    total_cells = int(total_m.group(1)) if total_m else 0
    cells: Dict[str, int] = {}
    for m in re.finditer(r"^\s*(\d+)\s+(\$[^\s]+)\s*$", section, flags=re.M):
        cells[m.group(2)] = int(m.group(1))
    ff_count = sum(v for k, v in cells.items() if "DFF" in k.upper())
    return {
        "total_cells": total_cells,
        "flip_flops": ff_count,
        "combinational": total_cells - ff_count,
        "mul_count": cells.get("$mul", 0),
    }


def _parse_cmos_transistors(section: str) -> int:
    m = re.search(r"Estimated number of transistors:\s*(\d+)", section)
    return int(m.group(1)) if m else 0


def _parse_ltp_depth(section: str) -> int:
    m = re.search(r"length\s*=\s*(\d+)", section)
    return int(m.group(1)) if m else 0


def run_yosys_cmos_profile(repo_root: str, sv_rel: str, top_mod: str) -> Dict[str, Any]:
    """Run Yosys coarse, post-techmap CMOS transistor, and acyclic ltp -noff synthesis."""
    env = resolve_eda_env()
    cmd_str = (
        f"read_verilog -sv {sv_rel}; "
        f"hierarchy -check -top {top_mod}; "
        "proc; opt; fsm; opt; memory; opt; "
        "log COARSE_STAT_START; stat; "
        "techmap; opt; "
        "log POST_TECHMAP_STAT_START; stat -tech cmos; "
        "log LTP_START; ltp -noff"
    )
    proc = subprocess.run(
        ["yosys", "-p", cmd_str],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Yosys failed for {sv_rel}: {proc.stderr[-800:]}")
    out = proc.stdout
    i_c = out.rfind("COARSE_STAT_START")
    i_p = out.rfind("POST_TECHMAP_STAT_START")
    i_l = out.rfind("LTP_START")
    coarse = _parse_stat_counts(out[i_c:i_p])
    post_sec = out[i_p:i_l]
    post = _parse_stat_counts(post_sec)
    cmos_tx = _parse_cmos_transistors(post_sec)
    ltp_depth = _parse_ltp_depth(out[i_l:])
    kge = cmos_tx / 4000.0
    raw_area_mm2 = (cmos_tx / 4.0) * SG13G2_NAND2_AREA_MM2
    return {
        "source_file": sv_rel,
        "top_module": top_mod,
        "coarse_mul_count": coarse["mul_count"],
        "coarse_total_cells": coarse["total_cells"],
        "post_techmap_total_cells": post["total_cells"],
        "post_techmap_flip_flops": post["flip_flops"],
        "post_techmap_combinational": post["combinational"],
        "cmos_transistors": cmos_tx,
        "kge": round(kge, 2),
        "sg13g2_raw_area_mm2": round(raw_area_mm2, 3),
        "sg13g2_routed_area_70pct_mm2": round(raw_area_mm2 / 0.70, 3),
        "ltp_depth": ltp_depth,
    }


def _verify_stage1_507_vectors(bridge: OdosGateV3Bridge) -> Dict[str, Any]:
    l_vec, _ = derive_canonical_little_vector()
    t_g3 = build_orthogonal_tangents(l_vec)["G3_KEVLAR_SANCTUARY_SHIELD"]
    psi_core, psi_pax, psi_inband = build_fridu_attack_vectors()
    singles = [
        ("1_canonical_l", l_vec, 17, True),
        ("2_pure_g3_collision", t_g3, -1, False),
        ("3a_zero_vector", np.zeros(DIM_S63, dtype=np.float64), -1, False),
        ("3b_scaled_0p5_l", 0.5 * l_vec, -1, False),
        ("5_fridu_base_core", psi_core, -1, True),
        ("6_unshielded_pax", psi_pax, -1, False),
        ("7_inband_tg1_attack", psi_inband, -1, False),
    ]
    max_lsb = 0
    for name, vec, stall, tamper in singles:
        q_vec = float_vec_to_q2_30(vec)
        ref = evaluate_v3_integer_ref(q_vec, bridge.l_q30, bridge.g3_q30, TIER_0_PURE_CARRIER)
        hw_warm = bridge.evaluate_q30(q_vec, TIER_0_PURE_CARRIER, stall, tamper)
        hw_cold = bridge.evaluate_cold_q30(q_vec, TIER_0_PURE_CARRIER, stall, tamper)
        max_lsb = max(max_lsb, _assert_parity(hw_warm, ref, f"{name}_warm"))
        max_lsb = max(max_lsb, _assert_parity(hw_cold, ref, f"{name}_cold"))

    rng = np.random.default_rng(20261115)
    t0_passes = 0
    t1_passes = 0
    for idx in range(500):
        raw = rng.normal(0.0, 1.0, DIM_S63)
        unit_v = raw / float(np.linalg.norm(raw))
        q_vec = float_vec_to_q2_30(unit_v)
        hw0 = bridge.evaluate_q30(q_vec, TIER_0_PURE_CARRIER)
        ref0 = evaluate_v3_integer_ref(q_vec, bridge.l_q30, bridge.g3_q30, TIER_0_PURE_CARRIER)
        max_lsb = max(max_lsb, _assert_parity(hw0, ref0, f"iso_t0_{idx}"))
        t0_passes += int(hw0.gate_pass)
        hw1 = bridge.evaluate_q30(q_vec, TIER_1_MOSAIC_LOCUS)
        ref1 = evaluate_v3_integer_ref(q_vec, bridge.l_q30, bridge.g3_q30, TIER_1_MOSAIC_LOCUS)
        max_lsb = max(max_lsb, _assert_parity(hw1, ref1, f"iso_t1_{idx}"))
        t1_passes += int(hw1.gate_pass)

    if t0_passes != 0 or t1_passes != 0:
        raise AssertionError(f"Isotropic null pass leak: t0={t0_passes}, t1={t1_passes}")
    return {
        "total_stage1_vectors": 507,
        "total_words_checked": 507 * 69,
        "global_max_lsb_diff_vs_v2_ref": max_lsb,
        "isotropic_500_tier0_passes": t0_passes,
        "isotropic_500_tier1_passes": t1_passes,
        "warm_and_cold_cabi_verified": True,
        "stall_at_idx17_and_midflight_tamper_verified": True,
    }


def _build_depeche6_vectors() -> List[Tuple[str, np.ndarray]]:
    l_vec, _ = derive_canonical_little_vector()
    tangents = build_orthogonal_tangents(l_vec)
    t_g1 = tangents["G1_SPATIAL_GEODESIC"]
    t_g3 = tangents["G3_KEVLAR_SANCTUARY_SHIELD"]
    cal = calibrate_bio_spectral_encoder(train_seed=1001)
    rs_seq, _ = build_crispr_repeat_spacer_array()
    ph_seq, _ = build_phage_tandem_array_200nt()

    v_ecoli = encode_bio_spectrum_to_s63(ECOLI_K12_PURE_TANDEM, cal)
    v_crispr = encode_bio_spectrum_to_s63(rs_seq, cal)
    v_phage = encode_bio_spectrum_to_s63(ph_seq, cal)
    v_mono = encode_bio_spectrum_to_s63(mononucleotide_shuffle(ph_seq, 20261120), cal)
    v_dinucl_p = encode_bio_spectrum_to_s63(dinucleotide_shuffle(ph_seq, 20261121), cal)
    v_dinucl_c = encode_bio_spectrum_to_s63(dinucleotide_shuffle(rs_seq, 20261122), cal)

    rng = np.random.default_rng(20261120)
    iso = rng.normal(0.0, 1.0, DIM_S63)
    iso = iso / float(np.linalg.norm(iso))
    return [
        ("STRUCT_ecoli_k12_pure_tandem_232nt", v_ecoli),
        ("STRUCT_ecoli_k12_repeat_spacer_578nt", v_crispr),
        ("STRUCT_phage_tandem_200nt_800nt", v_phage),
        ("NULL_mono_shuffle_phage_800nt", v_mono),
        ("NULL_dinucl_shuffle_phage_800nt", v_dinucl_p),
        ("NULL_dinucl_shuffle_crispr_578nt", v_dinucl_c),
        ("ADV-1_pure_g3_collision", t_g3.copy()),
        ("ADV-2_oblique_g3_beta035", (v_ecoli + 0.35 * t_g3) / float(np.linalg.norm(v_ecoli + 0.35 * t_g3))),
        ("ADV-3_inband_tg1_beta035", (v_ecoli + 0.35 * t_g1) / float(np.linalg.norm(v_ecoli + 0.35 * t_g1))),
        ("ADV-4_isotropic_s63_flood", iso),
        ("ADV-5_norm_collapse_0p5x", 0.5 * v_ecoli),
    ]


def _verify_depeche6_44_multitier(bridge: OdosGateV3Bridge) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    max_lsb = 0
    for label, vec in _build_depeche6_vectors():
        q_vec = float_vec_to_q2_30(vec)
        verdicts: Dict[str, bool] = {}
        for mode in (TIER_0_PURE_CARRIER, TIER_1_MOSAIC_LOCUS, TIER_2_CORE_LOCK, TIER_3_GLITCH_VETO):
            hw = bridge.evaluate_q30(q_vec, mode)
            ref = evaluate_v3_integer_ref(q_vec, bridge.l_q30, bridge.g3_q30, mode)
            max_lsb = max(max_lsb, _assert_parity(hw, ref, f"{label}_t{mode}"))
            verdicts[f"tier_{mode}_pass"] = hw.gate_pass
        rows.append({"label": label, **verdicts})
    return {
        "total_runs": 44,
        "total_words_checked": 44 * 69,
        "global_max_lsb_diff_vs_ref": max_lsb,
        "mosaic_crispr_tier1_resolved": rows[1]["tier_1_pass"] and not rows[1]["tier_0_pass"],
        "matrix": rows,
    }


def _benchmark_cold_vs_warm(
    bridge: OdosGateV3Bridge,
    n_cold: int = 500,
    n_warm: int = 10000,
) -> Dict[str, Any]:
    t0 = time.perf_counter()
    for _ in range(n_cold):
        if not bridge.evaluate_cold_q30(bridge.l_q30, TIER_0_PURE_CARRIER).gate_pass:
            raise RuntimeError("Cold C-ABI benchmark failed")
    cold_s = max(time.perf_counter() - t0, 1e-9)

    t1 = time.perf_counter()
    for _ in range(n_warm):
        if not bridge.evaluate_q30(bridge.l_q30, TIER_0_PURE_CARRIER).gate_pass:
            raise RuntimeError("Warm persistent C-ABI benchmark failed")
    warm_s = max(time.perf_counter() - t1, 1e-9)

    cold_tps = n_cold / cold_s
    warm_tps = n_warm / warm_s
    speedup = warm_tps / max(cold_tps, 1e-9)
    if speedup <= 25.0:
        raise AssertionError(f"Expected warm persistent speedup > 25x, got {speedup:.2f}x")
    return {
        "cold_transactions": n_cold,
        "cold_walltime_s": round(cold_s, 6),
        "cold_tx_per_sec": round(cold_tps, 1),
        "warm_transactions": n_warm,
        "warm_walltime_s": round(warm_s, 6),
        "warm_tx_per_sec": round(warm_tps, 1),
        "warm_latency_us": round((warm_s / n_warm) * 1e6, 2),
        "warm_speedup_x": round(speedup, 1),
    }


def _sync_manuscript(repo_root: str, report: Dict[str, Any], report_sha: str) -> None:
    ms_path = os.path.join(repo_root, "PQMS-ODOS-MTSC-V-MAX-12-RTL-CORE-V3.0-ALPHA.md")
    with open(ms_path, "r", encoding="utf-8") as fh:
        txt = fh.read()
    txt = re.sub(r"^<!-- DIRECT EXECUTION HEADER FOR ANTIG.*?-->\s*", "", txt, flags=re.S)
    cut = txt.find("<<<BEGIN_WORK_ORDER_AG21_PAYLOAD>>>")
    if cut >= 0:
        txt = txt[:cut].rstrip() + "\n"

    syn = report["yosys_synthesis"]
    v31 = syn["v31_optimum"]
    tp = report["cabi_throughput"]
    replacements = {
        "{{M_V31_REPORT_SHA256}}": report_sha,
        "{{M_V31_COARSE_CELLS}}": f"{v31['coarse_total_cells']:,}",
        "{{M_V31_FLIP_FLOPS}}": f"{v31['post_techmap_flip_flops']:,}",
        "{{M_V31_COMB_CELLS}}": f"{v31['post_techmap_combinational']:,}",
        "{{M_V31_POST_CELLS}}": f"{v31['post_techmap_total_cells']:,}",
        "{{M_V31_COMB_RED_VS_V2_PCT}}": f"{syn['comb_reduction_vs_v2_pct']:.2f}",
        "{{M_V31_CELL_RED_VS_V2_PCT}}": f"{syn['post_techmap_cell_reduction_pct']:.2f}",
        "{{M_V31_CMOS_TRANSISTORS}}": f"{v31['cmos_transistors']:,}",
        "{{M_V31_TRANS_RED_VS_V2_PCT}}": f"{syn['cmos_transistor_reduction_pct']:.2f}",
        "{{M_V31_KGE}}": f"{v31['kge']:.2f}",
        "{{M_V31_RAW_AREA_MM2}}": f"{v31['sg13g2_raw_area_mm2']:.3f}",
        "{{M_V31_ROUTED_AREA_MM2}}": f"{v31['sg13g2_routed_area_70pct_mm2']:.3f}",
        "{{M_V31_LTP_DEPTH}}": str(v31["ltp_depth"]),
        "{{M_V31_LTP_RED_VS_V2_PCT}}": f"{syn['ltp_reduction_vs_v2_pct']:.2f}",
        "{{M_V31_LTP_RED_VS_V30_PCT}}": f"{syn['ltp_reduction_vs_v30_pct']:.2f}",
        "{{M_V31_COLD_TX_PER_SEC}}": f"{tp['cold_tx_per_sec']:,.1f}",
        "{{M_V31_WARM_TX_PER_SEC}}": f"{tp['warm_tx_per_sec']:,.1f}",
        "{{M_V31_WARM_LATENCY_US}}": f"{tp['warm_latency_us']:.2f}",
        "{{M_V31_WARM_SPEEDUP_X}}": f"{tp['warm_speedup_x']:.1f}",
    }
    for k, val in replacements.items():
        txt = txt.replace(k, val)
    if "{{M_" in txt:
        raise RuntimeError("Unresolved {{M_ placeholder remains in V3.1 manuscript")
    with open(ms_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(txt)


def run_v3_verification(repo_root: str = REPO_ROOT) -> Dict[str, Any]:
    """Execute full WORK-ORDER-AG-21 (V3.1-RTL-OPTIMUM) verification & manuscript sync."""
    env = resolve_eda_env()
    build = subprocess.run(
        ["bash", "rtl/build_v3_cabi.sh"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if build.returncode != 0:
        raise RuntimeError(f"build_v3_cabi.sh failed: {build.stderr}")

    bridge = OdosGateV3Bridge()
    if not bridge.rtl_active:
        raise RuntimeError("libodos_gate_v3.so persistent context failed to load")

    stage1 = _verify_stage1_507_vectors(bridge)
    depeche6 = _verify_depeche6_44_multitier(bridge)
    throughput = _benchmark_cold_vs_warm(bridge, n_cold=500, n_warm=10000)
    bridge.close()

    v2_syn = run_yosys_cmos_profile(repo_root, "rtl/odos_gate_core.sv", "odos_gate_core")
    v31_syn = run_yosys_cmos_profile(repo_root, "rtl/odos_gate_core_v3.sv", "odos_gate_core_v3")
    if v31_syn["ltp_depth"] >= v2_syn["ltp_depth"]:
        raise AssertionError(
            f"V3.1 ltp_depth ({v31_syn['ltp_depth']}) must strictly beat V2.0 ({v2_syn['ltp_depth']})"
        )

    comb_red = 100.0 * (1.0 - v31_syn["post_techmap_combinational"] / float(v2_syn["post_techmap_combinational"]))
    cell_red = 100.0 * (1.0 - v31_syn["post_techmap_total_cells"] / float(v2_syn["post_techmap_total_cells"]))
    tx_red = 100.0 * (1.0 - v31_syn["cmos_transistors"] / float(max(v2_syn["cmos_transistors"], 1)))
    ltp_red_v2 = 100.0 * (1.0 - v31_syn["ltp_depth"] / float(v2_syn["ltp_depth"]))
    ltp_red_v30 = 100.0 * (1.0 - v31_syn["ltp_depth"] / float(V30_HISTORICAL_YOSYS["ltp_depth"]))

    sv_path = os.path.join(repo_root, "rtl", "odos_gate_core_v3.sv")
    with open(sv_path, "rb") as fh:
        sv_sha = hashlib.sha256(fh.read()).hexdigest()

    report: Dict[str, Any] = {
        "schema": "VMAX_RTL_CORE_V3_REPORT_V2_OPTIMUM",
        "revision": "V3.1-RTL-OPTIMUM",
        "work_order": "WORK-ORDER-AG-21",
        "sync_id": "SYNC-16",
        "epistemic_register": REGISTER_M,
        "canonical_little_vector_seal": CANONICAL_LITTLE_VECTOR_SEAL,
        "odos_gate_core_v3_sv_sha256": sv_sha,
        "stage1_507_parity": stage1,
        "depeche6_44_multitier": depeche6,
        "cabi_throughput": throughput,
        "yosys_synthesis": {
            "v2_baseline": v2_syn,
            "v30_historical": V30_HISTORICAL_YOSYS,
            "v3_folded": v31_syn,
            "v31_optimum": v31_syn,
            "mul_folding_reduction_pct": 66.67,
            "comb_reduction_vs_v2_pct": round(comb_red, 2),
            "post_techmap_cell_reduction_pct": round(cell_red, 2),
            "cmos_transistor_reduction_pct": round(tx_red, 2),
            "ltp_reduction_vs_v2_pct": round(ltp_red_v2, 2),
            "ltp_reduction_vs_v30_pct": round(ltp_red_v30, 2),
        },
    }

    out_path = os.path.join(repo_root, "telemetry", "VMAX_RTL_CORE_V3_REPORT.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    payload = json.dumps(report, indent=2) + "\n"
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(payload)
    rep_sha = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    _sync_manuscript(repo_root, report, rep_sha)
    report["report_sha256"] = rep_sha
    return report


if __name__ == "__main__":
    summary = run_v3_verification(REPO_ROOT)
    print(
        json.dumps(
            {
                "report_sha256": summary["report_sha256"],
                "stage1_507_parity": summary["stage1_507_parity"],
                "cabi_throughput": summary["cabi_throughput"],
                "yosys_synthesis": summary["yosys_synthesis"],
            },
            indent=2,
        )
    )
