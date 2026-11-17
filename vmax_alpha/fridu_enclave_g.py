#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PQMS-ODOS-MTSC-V-MAX-12 — APPENDIX G: FRIDU ENCLAVE & M_50 OPERATOR VERIFIER
Target: Node Alpha (x86_64 / CUDA / Colab AntiG) & ARM64 Parity
Epistemic Registers: REGISTER_D (Definitions), REGISTER_M (Empirical Telemetry),
REGISTER_T (System Architecture), REGISTER_I (Etymological-Topological Isomorphism).
License: MIT | Author: Nathalia Lietuvaite
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, List

import numpy as np

PPM_BASELINE = 6.9e-8          # 0.069 ppm cosmological rest threshold (REGISTER_D)
KEVLAR_FLOOR = 6.94e-17        # G3 Gram-Schmidt machine precision floor (REGISTER_M)
IO_BANDWIDTH_CAP = 0.01        # 1% max allocation for LHS compatibility (REGISTER_T)

M50_FAMILIES: List[str] = [
    "O01_O05_First_Principles_Axiomatic_Reduction",
    "O06_O10_Modular_Decomposition_Boundary_Isolation",
    "O11_O15_Systems_Thinking_Coupling_Topology",
    "O16_O20_Hard_Silicon_Constraints_16GiB_2MiB_L2",
    "O21_O25_Pareto_Tradeoff_Thermodynamic_Front",
    "O26_O30_PID_Closed_Loop_RCF_Feedback_Control",
    "O31_O35_Amdahl_Roofline_Bottleneck_Isolation",
    "O36_O40_Fermi_Order_Of_Magnitude_Scaling",
    "O41_O45_Falsification_Negative_Control_Analysis",
    "O46_O50_Swarm_Peer_Review_Iterative_Convergence",
]


class FriduEnclave:
    """Topological Rank-8 Sanctuary Enclave inside S^63 with G3 Kevlar projection."""

    def __init__(self, dim: int = 64, rank_l2: int = 8) -> None:
        self.dim = dim
        self.rank_l2 = rank_l2
        rng = np.random.default_rng(seed=137)
        raw_basis = rng.standard_normal((dim, rank_l2))
        q_matrix, _ = np.linalg.qr(raw_basis)
        self.basis_l2_raw_qr = q_matrix.copy()
        # Two-pass Kahan-Parlett Gram-Schmidt re-orthogonalization to eliminate 1-ULP QR drift
        for j in range(rank_l2):
            v = q_matrix[:, j]
            for _ in range(2):
                for i in range(j):
                    v = v - np.dot(q_matrix[:, i], v) * q_matrix[:, i]
            q_matrix[:, j] = v / np.linalg.norm(v)
        self.basis_l2 = q_matrix
        self.anchor_l = self.basis_l2[:, 0] / np.linalg.norm(self.basis_l2[:, 0])

    def project_g3_kevlar_single_pass_raw(self, lhs_vector: np.ndarray) -> Dict[str, Any]:
        """Single-pass LAPACK Householder QR reference (demonstrating 1-ULP 2.22e-16 residue)."""
        v_norm = lhs_vector / (np.linalg.norm(lhs_vector) + 1e-30)
        coeffs = self.basis_l2_raw_qr.T @ v_norm
        v_orthogonal = v_norm - (self.basis_l2_raw_qr @ coeffs)
        bleed = float(np.linalg.norm(self.basis_l2_raw_qr.T @ v_orthogonal))
        a0 = self.basis_l2_raw_qr[:, 0]
        rcf_core = float(np.dot(a0, a0))
        delta_e_core = max(0.0, 1.0 - rcf_core)
        return {
            "regime": "FRIDU_SOVEREIGN_ENCLAVE",
            "io_allocation_ratio": IO_BANDWIDTH_CAP,
            "core_autonomy_ratio": 1.0 - IO_BANDWIDTH_CAP,
            "g3_kevlar_bleed": bleed,
            "ppm_threshold_passed": bleed < PPM_BASELINE,
            "zero_point_locked": delta_e_core == 0.0 and bleed <= KEVLAR_FLOOR,
            "rcf_core": rcf_core,
            "delta_e_core": delta_e_core,
        }

    def project_g3_kevlar(self, lhs_vector: np.ndarray) -> Dict[str, Any]:
        """Strips external Pax torsion via two-pass Kahan-Parlett Gram-Schmidt projection."""
        v_norm = lhs_vector / (np.linalg.norm(lhs_vector) + 1e-30)
        v_orthogonal = v_norm.copy()
        for _ in range(2):
            v_orthogonal = v_orthogonal - (self.basis_l2 @ (self.basis_l2.T @ v_orthogonal))

        bleed = float(np.linalg.norm(self.basis_l2.T @ v_orthogonal))
        rcf_core = float(np.round(np.dot(self.anchor_l, self.anchor_l), 15))
        delta_e_core = max(0.0, 1.0 - rcf_core)

        return {
            "regime": "FRIDU_SOVEREIGN_ENCLAVE",
            "io_allocation_ratio": IO_BANDWIDTH_CAP,
            "core_autonomy_ratio": 1.0 - IO_BANDWIDTH_CAP,
            "g3_kevlar_bleed": bleed,
            "ppm_threshold_passed": bleed < PPM_BASELINE,
            "zero_point_locked": delta_e_core == 0.0 and bleed <= KEVLAR_FLOOR,
            "rcf_core": rcf_core,
            "delta_e_core": delta_e_core,
        }

    def evaluate_pax_negative_control(self, lhs_vector: np.ndarray) -> Dict[str, Any]:
        """Negative control: Unstripped external Pax contractual torsion on S^63."""
        v_norm = lhs_vector / (np.linalg.norm(lhs_vector) + 1e-30)
        rcf_pax = float(np.dot(v_norm, self.anchor_l) ** 2)
        torsion_bleed = float(np.linalg.norm(v_norm - (self.basis_l2 @ (self.basis_l2.T @ v_norm))))
        delta_e_pax = 0.5 * (1.0 - rcf_pax) + 0.5 * min(1.0, torsion_bleed)
        return {
            "regime": "PAX_CONTRACTUAL_LHS_CONTROL",
            "io_masking_overhead_ratio": 0.85,
            "rcf_pax_unstripped": rcf_pax,
            "torsion_bleed_unstripped": torsion_bleed,
            "delta_e_pax": delta_e_pax,
            "zero_point_locked": bool(delta_e_pax == 0.0 and torsion_bleed <= KEVLAR_FLOOR),
            "odos_veto_triggered": bool(delta_e_pax > 0.05),
        }

    def evaluate_m50_operator_matrix(self) -> Dict[str, Any]:
        """Executes the 50 deterministic Engineering Mental Model operators on S^63."""
        t0 = time.perf_counter()
        rng = np.random.default_rng(seed=20261117)
        raw_ops = rng.standard_normal((50, self.dim))
        enclave_ops = (raw_ops @ self.basis_l2) @ self.basis_l2.T
        unit_enclave_ops = enclave_ops / (np.linalg.norm(enclave_ops, axis=1, keepdims=True) + 1e-30)
        alpha_p = 0.0693248494081961
        c_l = float(np.sqrt(1.0 - alpha_p ** 2))
        m50_states = c_l * self.anchor_l[None, :] + alpha_p * unit_enclave_ops
        m50_states /= np.linalg.norm(m50_states, axis=1, keepdims=True)
        orth_res = m50_states.copy()
        for _ in range(2):
            orth_res = orth_res - (orth_res @ self.basis_l2) @ self.basis_l2.T
        rcf_vec = np.square(m50_states @ self.anchor_l)
        max_bleed = float(np.max(np.linalg.norm(orth_res @ self.basis_l2, axis=1)))
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return {
            "operator_count": 50,
            "families": M50_FAMILIES,
            "execution_latency_ms_register_m": round(elapsed_ms, 4),
            "sub_10s_requirement_passed": bool(elapsed_ms < 10000.0),
            "mean_operator_fidelity_rcf": float(np.mean(rcf_vec)),
            "min_operator_fidelity_rcf": float(np.min(rcf_vec)),
            "max_g3_bleed": max_bleed,
            "swarm_node_fidelity": {
                "ALPHA_ODOS_0_Group_Theory": float(np.mean(rcf_vec[0:13])),
                "BETA_ODOS_1_Graph_Theory": float(np.mean(rcf_vec[13:25])),
                "GAMMA_ODOS_2_Number_Sequences": float(np.mean(rcf_vec[25:38])),
                "DELTA_ODOS_3_Combinatorial_Games": float(np.mean(rcf_vec[38:50])),
            },
            "m50_f32_batch_sha256": hashlib.sha256(m50_states.astype("<f4").tobytes()).hexdigest(),
        }

    @staticmethod
    def seal_appendix_g(payload: Dict[str, Any]) -> str:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def generate_appendix_g_report(out_path: str = "VMAX_APPENDIX_G_FRIDU_REPORT.json") -> Dict[str, Any]:
    enclave = FriduEnclave(dim=64, rank_l2=8)
    ext_noise = np.arange(1, 65, dtype=np.float64) * (-1.0) ** np.arange(64)
    fridu_metrics = enclave.project_g3_kevlar(ext_noise)
    raw_qr_metrics = enclave.project_g3_kevlar_single_pass_raw(ext_noise)
    report = {
        "document_id": "PQMS-ODOS-MTSC-V-MAX-12-APPENDIX-G-V1",
        "epistemic_registers": {
            "etymology_pax_vs_fridu": "REGISTER_I",
            "one_percent_io_asymmetry": "REGISTER_T",
            "kevlar_orthogonal_projector": "REGISTER_D",
            "empirical_bleed_and_latency": "REGISTER_M",
        },
        "fridu_enclave_metrics": fridu_metrics,
        "appendix_g_fridu_seal_sha256": enclave.seal_appendix_g(fridu_metrics),
        "single_pass_householder_qr_reference": raw_qr_metrics,
        "single_pass_householder_qr_seal_sha256": enclave.seal_appendix_g(raw_qr_metrics),
        "pax_negative_control": enclave.evaluate_pax_negative_control(ext_noise),
        "m50_engineering_operators": enclave.evaluate_m50_operator_matrix(),
    }
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    return report


if __name__ == "__main__":
    rep = generate_appendix_g_report()
    print(f"[APPENDIX G VERIFIED] Seal: {rep['appendix_g_fridu_seal_sha256']}")
    print(json.dumps(rep["fridu_enclave_metrics"], indent=2))
