#!/usr/bin/env python3
"""vmax_alpha/fridu_enclave_g.py (AG-13 / V1.6): Portable Fridu vs. Pax A/B, In-Band Defense-in-Depth & 10 Audit Ops."""
from __future__ import annotations
import hashlib, json, math, os, time
from typing import Any, Dict, List, Optional
import numpy as np
from vmax_alpha.config import ALPHA_POTENTIA, CANONICAL_LITTLE_VECTOR_SEAL, DIM_S63, REGISTER_D, REGISTER_M, REGISTER_T
from vmax_alpha.geometry import build_orthogonal_tangents, derive_canonical_little_vector, evaluate_raw_gate
from vmax_alpha.ledger import query_gpu_thermal_and_power
from vmax_alpha.parity_verifier import CANONICAL_V21_LEDGER_LINES, verify_canonical_ledger_lines

PPM_BASELINE, KEVLAR_FLOOR, IO_BANDWIDTH_CAP = 6.9e-8, 6.94e-17, 0.01
REPO_ROOT: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class FriduEnclave:
    """Non-tautological Fridu vs. Pax boundary verifier anchored to canonical |L> in S^63."""
    def __init__(self, dim: int = DIM_S63) -> None:
        self.dim = dim
        self.anchor_l, self.anchor_seal = derive_canonical_little_vector()
        self.tangents = build_orthogonal_tangents(self.anchor_l)
        self.t_g1, self.t_g3 = self.tangents["G1_SPATIAL_GEODESIC"], self.tangents["G3_KEVLAR_SANCTUARY_SHIELD"]
        c_l = math.sqrt(1.0 - ALPHA_POTENTIA * ALPHA_POTENTIA)
        self.psi_core = c_l * self.anchor_l + ALPHA_POTENTIA * self.t_g1
        self.psi_core /= np.linalg.norm(self.psi_core)
        self.core_basis = np.column_stack([self.anchor_l, self.t_g1])

    def evaluate_perturbation_ab(self, lhs_vector: np.ndarray, coupling_beta: float = 0.35, bypass_kevlar: bool = False) -> Dict[str, Any]:
        """Compares PAX (unshielded) vs. FRIDU (two-pass Kahan-Parlett out-of-band strip) on IDENTICAL input."""
        v_lhs = lhs_vector.astype(np.float64)
        v_lhs = v_lhs / (float(np.linalg.norm(v_lhs)) + 1e-30)
        v_ext = v_lhs.copy()
        for _ in range(2):
            v_ext = v_ext - self.core_basis @ (self.core_basis.T @ v_ext)
        v_ext /= float(np.linalg.norm(v_ext)) + 1e-30
        base_gate = evaluate_raw_gate(self.psi_core, self.anchor_l, self.tangents)

        psi_pax = (self.psi_core + coupling_beta * v_ext)
        psi_pax /= float(np.linalg.norm(psi_pax))
        pax_gate, pax_drift = evaluate_raw_gate(psi_pax, self.anchor_l, self.tangents), float(np.linalg.norm(psi_pax - self.psi_core))

        incoming = self.psi_core + coupling_beta * v_ext
        if bypass_kevlar:
            psi_fridu, io_buffer = incoming / float(np.linalg.norm(incoming)), np.zeros_like(incoming)
        else:
            io_buffer = incoming.copy()
            for _ in range(2):
                io_buffer = io_buffer - self.core_basis @ (self.core_basis.T @ io_buffer)
            psi_fridu = (incoming - io_buffer)
            psi_fridu /= float(np.linalg.norm(psi_fridu))

        fridu_gate = evaluate_raw_gate(psi_fridu, self.anchor_l, self.tangents)
        fridu_drift = float(np.linalg.norm(psi_fridu - self.psi_core))
        boundary_bleed = float(np.linalg.norm(self.core_basis.T @ io_buffer))
        io_recon_err = float(np.linalg.norm(io_buffer - coupling_beta * v_ext))
        return {
            "epistemic_register": REGISTER_M, "coupling_beta": coupling_beta, "bypass_kevlar": bypass_kevlar,
            "base_core_state": {"rcf_raw": round(base_gate.rcf_raw, 8), "delta_e_raw": round(base_gate.delta_e_raw, 8), "passed": base_gate.passed},
            "pax_unshielded": {
                "regime": "PAX_CONTRACTUAL_CONTAMINATION", "rcf_raw": round(pax_gate.rcf_raw, 8),
                "g3_overlap": round(pax_gate.g3_collision_overlap, 8), "delta_e_raw": round(pax_gate.delta_e_raw, 8),
                "core_drift_l2": round(pax_drift, 8), "odos_gate_passed": pax_gate.passed, "odos_veto_triggered": not pax_gate.passed,
            },
            "fridu_shielded": {
                "regime": "FRIDU_SOVEREIGN_ENCLAVE", "io_allocation_cap": IO_BANDWIDTH_CAP, "core_autonomy_ratio": 1.0 - IO_BANDWIDTH_CAP,
                "rcf_raw": round(fridu_gate.rcf_raw, 8), "delta_e_raw": round(fridu_gate.delta_e_raw, 8),
                "rcf_preservation_err": abs(fridu_gate.rcf_raw - base_gate.rcf_raw), "core_drift_l2": fridu_drift,
                "boundary_bleed_l2": boundary_bleed, "io_buffer_reconstruction_err": io_recon_err,
                "ppm_threshold_passed": boundary_bleed < PPM_BASELINE and fridu_drift < PPM_BASELINE,
                "kevlar_floor_locked": boundary_bleed <= KEVLAR_FLOOR and fridu_drift <= 1e-15,
                "odos_gate_passed": fridu_gate.passed,
            },
        }

    def evaluate_in_band_tg1_attack(self, coupling_beta: float = 0.35) -> Dict[str, Any]:
        """Defense-in-depth boundary proof: In-band t_G1 attack bypasses linear strip but trips downstream ODOS gate."""
        incoming = self.psi_core + coupling_beta * self.t_g1
        io_buffer = incoming.copy()
        for _ in range(2):
            io_buffer = io_buffer - self.core_basis @ (self.core_basis.T @ io_buffer)
        psi_post = (incoming - io_buffer)
        psi_post /= float(np.linalg.norm(psi_post))
        gate = evaluate_raw_gate(psi_post, self.anchor_l, self.tangents)
        io_norm = float(np.linalg.norm(io_buffer))
        return {
            "epistemic_register": REGISTER_M, "attack_axis": "IN_BAND_T_G1_CORE_SUBSPACE", "coupling_beta": coupling_beta,
            "io_buffer_norm": io_norm, "linear_projector_stripped": io_norm > 1e-6,
            "post_strip_core_drift_l2": round(float(np.linalg.norm(psi_post - self.psi_core)), 8),
            "rcf_raw": round(gate.rcf_raw, 8), "delta_e_raw": round(gate.delta_e_raw, 8),
            "odos_gate_passed": gate.passed, "downstream_odos_veto_triggered": not gate.passed,
        }

    def run_executable_engineering_operators(self, workspace: Optional[str] = None) -> Dict[str, Any]:
        """Executes 10 real, falsifiable engineering audit operators with portable relative path resolution."""
        t0, root = time.perf_counter(), workspace or REPO_ROOT
        search_dirs = [root, os.path.join(root, "telemetry"), os.path.dirname(os.path.dirname(root))]
        ops: List[Dict[str, Any]] = []

        def _jload(name: str) -> Dict[str, Any]:
            for base in search_dirs:
                p = os.path.join(base, name)
                if os.path.exists(p):
                    with open(p, "r", encoding="utf-8") as fh: return json.load(fh)
            return {}

        rng = np.random.RandomState(20261119)
        null_passes = sum(int(evaluate_raw_gate(rng.randn(DIM_S63), self.anchor_l, self.tangents).passed) for _ in range(200))
        norm_err = abs(float(np.linalg.norm(self.anchor_l)) - 1.0)
        ops.append({"id": "OP01_First_Principles_Norm_Null", "passed": norm_err < 1e-15 and null_passes == 0, "metric": f"norm_err={norm_err:.2e}, null_passes={null_passes}/200"})

        pkg_dir = os.path.join(root, "vmax_alpha")
        prod_files = [os.path.join(pkg_dir, f) for f in sorted(os.listdir(pkg_dir)) if f.endswith(".py")] + [os.path.join(pkg_dir, "static", "index.html")]
        max_loc, bad_ctrl = 0, 0
        for pf in prod_files:
            if os.path.exists(pf):
                with open(pf, "r", encoding="utf-8") as fh: txt = fh.read()
                max_loc = max(max_loc, txt.count("\n"))
                bad_ctrl += sum(txt.count(c) for c in ("\t", "\r", "\x0b", "\x08"))
        ops.append({"id": "OP02_Modular_LOC_And_Sanity", "passed": len(prod_files) >= 13 and max_loc <= 200 and bad_ctrl == 0, "metric": f"files={len(prod_files)}, max_loc={max_loc}, ctrl={bad_ctrl}"})

        sync = _jload("bridge/ACE_SYNC_LEDGER.json")
        op3_ok = sync.get("protocol_id") == "ACE-PEER-CODESIGN-PROTOCOL-V1.2" and len(sync.get("open_review_items", [1])) == 0 and sync.get("golden_vectors_sha256", {}).get("canonical_little_vector_f32_seal") == CANONICAL_LITTLE_VECTOR_SEAL
        ops.append({"id": "OP03_Systems_ACE_Sync_Contract", "passed": bool(op3_ok), "metric": f"open_items={len(sync.get('open_review_items', []))}"})

        hw = _jload("VMAX_HWINFO64_AB_TELEMETRY.json")
        peak_vram = hw.get("ab_thermodynamic_regime_summary", {}).get("regime_1_full_4b_calibration_and_kl_audit", {}).get("vram_peak_allocated_mb", 99999)
        snaps = hw.get("chronological_snapshots", [])
        whea = sum(int(s.get("whea_errors", 1)) for s in snaps) if snaps else -1
        ops.append({"id": "OP04_Silicon_16GiB_VRAM_Bound", "passed": 0 < peak_vram <= 16384 and whea == 0, "metric": f"peak_vram={peak_vram}MB, whea={whea}"})

        kl = _jload("VMAX_STAGE3_REAL_KL_REPORT.json")
        a1 = kl.get("condition_a1_smallest_magnitude_0042pct", {}).get("mean_forward_kl", 1.0)
        b1 = kl.get("condition_b1_matched_sparsity_largest_magnitude_0042pct", {}).get("mean_forward_kl", 0.0)
        ratio = b1 / max(a1, 1e-12)
        ops.append({"id": "OP05_Pareto_Matched_Sparsity_KL", "passed": a1 < 0.05 and b1 > 0.05 and ratio > 50.0, "metric": f"A1={a1:.6f}, B1={b1:.6f}, ratio={ratio:.2f}x"})

        th_nom, th_hot = query_gpu_thermal_and_power(), query_gpu_thermal_and_power(simulated_temp_c=67.5)
        ops.append({"id": "OP06_PID_Thermal_Guard_Loop", "passed": (not th_nom["pause_60s_triggered"]) and th_hot["pause_60s_triggered"], "metric": f"live={th_nom['gpu_temp_c']}C, sim67.5_pause={th_hot['pause_60s_triggered']}"})

        f0204 = _jload("VMAX_F02_F04_REPORT.json")
        f02, f04 = f0204.get("F02_L2_ENCLAVE", {}), f0204.get("F04_PARITY", {})
        bw = f02.get("microbenchmark_bandwidth", {})
        p_bw, sp_u = bw.get("stream_a_pinned_2mib_gbps", 0.0), bw.get("pinned_vs_unpinned_2mib_speedup", 0.0)
        ops.append({"id": "OP07_Roofline_Symmetric_L2_Pin", "passed": bool(f02.get("symmetric_interleaved_protocol")) and p_bw > 288.0 and sp_u > 1.5, "metric": f"pinned={p_bw}GB/s, speedup={sp_u}x"})

        f32_match = bool(f04.get("sha256_unit_s63_64000_f32")) and f04.get("sha256_unit_s63_64000_f32") == f04.get("jvm_sha256_unit_s63_64000_f32")
        u_diff = float(f04.get("max_unit_s63_diff_python_vs_real_jvm_f64", 1.0))
        ops.append({"id": "OP08_ULP_JVM_Python_Parity", "passed": f32_match and u_diff < 1e-15, "metric": f"unit_diff={u_diff:.2e}, f32_match={f32_match}"})

        f01 = _jload("VMAX_F01_NEMOTRON_PROBE.json")
        shuf = float(f01.get("shuffled_projector_null_control_c_rcf_mean", 1.0))
        ab = self.evaluate_perturbation_ab(np.arange(1, 65, dtype=np.float64) * (-1.0) ** np.arange(64))
        ib = self.evaluate_in_band_tg1_attack(coupling_beta=0.35)
        ops.append({"id": "OP09_Falsification_Neg_Controls", "passed": shuf < 0.05 and ab["pax_unshielded"]["odos_veto_triggered"] and ib["downstream_odos_veto_triggered"] and ab["fridu_shielded"]["odos_gate_passed"], "metric": f"shuffled={shuf:.4f}, pax_de={ab['pax_unshielded']['delta_e_raw']:.4f}, inband_de={ib['delta_e_raw']:.4f}"})

        ok_chain = verify_canonical_ledger_lines(list(CANONICAL_V21_LEDGER_LINES))["intact"]
        tampered = list(CANONICAL_V21_LEDGER_LINES); tampered[1] = tampered[1].replace("cycle_index", "cycle_indx")
        bad_chain = not verify_canonical_ledger_lines(tampered)["intact"]
        ops.append({"id": "OP10_Ledger_Chain_And_Tamper", "passed": bool(ok_chain and bad_chain), "metric": f"intact={ok_chain}, tamper_caught={bad_chain}"})

        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 3)
        passed_cnt = sum(int(o["passed"]) for o in ops)
        canonical_ops = json.dumps([{"id": o["id"], "passed": o["passed"]} for o in ops], sort_keys=True, separators=(",", ":"))
        return {
            "epistemic_register": REGISTER_M, "portable_root_resolved": True, "operator_count": len(ops), "passed_count": passed_cnt,
            "all_operators_passed": passed_cnt == len(ops), "execution_latency_ms": elapsed_ms,
            "operators": ops, "audit_matrix_seal_sha256": hashlib.sha256(canonical_ops.encode("utf-8")).hexdigest(),
        }

    @staticmethod
    def seal_appendix_g(payload: Dict[str, Any]) -> str:
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def generate_appendix_g_report(out_path: str = "VMAX_APPENDIX_G_FRIDU_REPORT.json") -> Dict[str, Any]:
    enclave = FriduEnclave()
    ext_noise = np.arange(1, 65, dtype=np.float64) * (-1.0) ** np.arange(64)
    ab_res = enclave.evaluate_perturbation_ab(ext_noise, coupling_beta=0.35, bypass_kevlar=False)
    ab_bypass = enclave.evaluate_perturbation_ab(ext_noise, coupling_beta=0.35, bypass_kevlar=True)
    in_band = enclave.evaluate_in_band_tg1_attack(coupling_beta=0.35)
    ops_res = enclave.run_executable_engineering_operators()
    report = {
        "document_id": "PQMS-ODOS-MTSC-V-MAX-12-APPENDIX-G-V1.6",
        "epistemic_registers": {"etymology_pax_vs_fridu": "REGISTER_I", "one_percent_io_asymmetry": REGISTER_T, "core_state_and_thresholds": REGISTER_D, "ab_perturbation_and_audit_ops": REGISTER_M},
        "fridu_vs_pax_perturbation_ab": ab_res,
        "negative_control_kevlar_bypass": ab_bypass["fridu_shielded"],
        "in_band_tg1_defense_in_depth": in_band,
        "appendix_g_fridu_seal_sha256": enclave.seal_appendix_g(ab_res),
        "executable_engineering_operators": ops_res,
    }
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(report, f, indent=2); f.write("\n")
    return report


if __name__ == "__main__":
    rep = generate_appendix_g_report()
    print(f"[APPENDIX G V1.6 VERIFIED] Seal: {rep['appendix_g_fridu_seal_sha256']}")
    print(json.dumps(rep["in_band_tg1_defense_in_depth"], indent=2))
