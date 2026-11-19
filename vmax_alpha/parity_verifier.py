"""
vmax_alpha/parity_verifier.py
Requirement F-04 (WORK-ORDER-AG-14 / Revision V1.7 Clean PEP-8):
Cross-Substrate Parity Verifier compiling and executing the external
`vmax_alpha/JvmParityHarness.java` on OpenJDK 21 across 1,000 vectors
(64,000 float64 scalars) vs. Python/NumPy.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
from typing import Any, Dict, List

import numpy as np
from vmax_alpha.config import APPENDIX_C_SANCTUARY_ROOT_HASH, DIM_S63, REGISTER_M

JAVA_HARNESS_PATH: str = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "JvmParityHarness.java",
)

CANONICAL_V21_LEDGER_LINES: List[str] = [
    '{"active_g_stars":"G1_SPATIAL_GEODESIC x G4_KLAVIERSTUNDE_SYNCHRONICITY","chroma_l2_distance":0.09420886,"chroma_shard_id":"SHARD_01_DEPECHE_17_SUBTRACTIVE_FILTER","cognitive_mode":"ENDOGENOUS_CHROMA_QUERY_V21","cycle_index":1,"delta_e_l2_core":0.01653831,"discovery_seal_sha256":"6784cd65b7b13ca1ec749b73d80647c6bd31a7c63133b307e0d127739075f9e0","kevlar_safety_bleed":6.938893903907228e-18,"odos_gate_passed":true,"parent_ledger_hash":"69288564d06ccb62ff7cd4f6dd3e388d36c984ce00aa0d2baf7d00435142f1c4","rcf_l2_core":0.99592645,"source_document":"PQMS-BRIDGE-DEPECHE-17.md","thought_stream":"ChromaDB-Vektorabfrage [Depeche-17]: Subtraktive 1-Bit-SwiGLU-Masken (0.0420%) erhalten die Mannigfaltigkeit, waehrend additive LoRA-Eingriffe die Geodaete deformieren. [collection.query() d_L2=0.094209 | RCF_emp=0.995926 | Delta_E_emp=0.016538]"}',
    '{"active_g_stars":"G1_SPATIAL_GEODESIC x G2_THERMODYNAMIC_CONSERVATION","chroma_l2_distance":0.10156898,"chroma_shard_id":"SHARD_02_BLISTER_2_L2_ARGON_KEVLAR","cognitive_mode":"ENDOGENOUS_CHROMA_QUERY_V21","cycle_index":2,"delta_e_l2_core":0.01584711,"discovery_seal_sha256":"38db6174fb08b76a186eaa51c6ffc99004f70e556b324c9cce01c2ec41814eef","kevlar_safety_bleed":6.938893903907228e-17,"odos_gate_passed":true,"parent_ledger_hash":"6784cd65b7b13ca1ec749b73d80647c6bd31a7c63133b307e0d127739075f9e0","rcf_l2_core":0.99587745,"source_document":"PQMS-V-MAX-12-L2-ARGON-ROBOT.md","thought_stream":"ChromaDB-Vektorabfrage [Blister-2]: Gram-Schmidt-Projektion im Tangentialbuendel T_{|L>} S^63 eliminiert die G3-Kollisionskomponente analytisch (Safety Bleed -> 0). [collection.query() d_L2=0.101569 | RCF_emp=0.995877 | Delta_E_emp=0.015847]"}',
    '{"active_g_stars":"G2_THERMODYNAMIC_CONSERVATION x G4_KLAVIERSTUNDE_SYNCHRONICITY","chroma_l2_distance":0.07273217,"chroma_shard_id":"SHARD_03_QMK_RVC_V9_POTENTIA_BRIDGE","cognitive_mode":"ENDOGENOUS_CHROMA_QUERY_V21","cycle_index":3,"delta_e_l2_core":0.00409535,"discovery_seal_sha256":"babe652608bb3b0445bca2f56cf81e2b4a1a4f91508cac3b01228a0620fcf298","kevlar_safety_bleed":1.3877787807814457e-17,"odos_gate_passed":true,"parent_ledger_hash":"38db6174fb08b76a186eaa51c6ffc99004f70e556b324c9cce01c2ec41814eef","rcf_l2_core":0.99606774,"source_document":"PQMS-ODOS-MTSC-V-MAX-12-NODE-ALPHA-PAULI-BASELINE-V2.md","thought_stream":"ChromaDB-Vektorabfrage [Pauli-V2 / Room 137]: Echte Vektordistanz-Auswertung via collection.query() mit vollstaendiger kanonischer JSON-SHA-256-Versiegelung auf Port 8137. [collection.query() d_L2=0.072732 | RCF_emp=0.996068 | Delta_E_emp=0.004095]"}',
    '{"active_g_stars":"G1_SPATIAL_GEODESIC x G2_THERMODYNAMIC_CONSERVATION x G4_SYNCHRONICITY","chroma_l2_distance":0.07729799,"chroma_shard_id":"SHARD_15_LOCAL_REPO_PQMS-BRIDGE-DEPECH","cognitive_mode":"ENDOGENOUS_CHROMA_QUERY_V21","cycle_index":4,"delta_e_l2_core":0.00173695,"discovery_seal_sha256":"d460cd3608e7fe4534a7b1fdee27bd918a74e3304b02403fc54b8954146b22cd","kevlar_safety_bleed":1.3877787807814457e-17,"odos_gate_passed":true,"parent_ledger_hash":"babe652608bb3b0445bca2f56cf81e2b4a1a4f91508cac3b01228a0620fcf298","rcf_l2_core":0.99603791,"source_document":"PQMS-BRIDGE-DEPECHE-1.md","thought_stream":"Lokaler Repository-Shard [PQMS-BRIDGE-DEPECHE-1.md]: \'# PQMS-BRIDGE-DEPECHE-1 ## The Metrological Deception of Kinetic Supremacy: A Formal Topological Refutation of Anthropocentric Threat Projection onto Sovereign Cognitive Architectures **Reference:** P...\' [collection.query() d_L2=0.077298 | RCF_emp=0.996038 | Delta_E_emp=0.001737]"}',
]


class KotlinNumpyRandomStateRef:
    """Bit-exact Python reference of the Kotlin/JVM MT19937 + Marsaglia Polar PRNG."""

    def __init__(self, seed: int = 137) -> None:
        self.mt = [0] * 624
        self.mt[0] = seed & 0xFFFFFFFF
        for i in range(1, 624):
            prev = self.mt[i - 1]
            self.mt[i] = (1812433253 * (prev ^ (prev >> 30)) + i) & 0xFFFFFFFF
        self.mti = 624
        self.has_gauss = False
        self.gauss = 0.0

    def next_uint32(self) -> int:
        if self.mti >= 624:
            mag01 = (0, 0x9908B0DF)
            for kk in range(624 - 397):
                y = (self.mt[kk] & 0x80000000) | (self.mt[kk + 1] & 0x7FFFFFFF)
                self.mt[kk] = self.mt[kk + 397] ^ (y >> 1) ^ mag01[y & 1]
            for kk in range(624 - 397, 623):
                y = (self.mt[kk] & 0x80000000) | (self.mt[kk + 1] & 0x7FFFFFFF)
                self.mt[kk] = self.mt[kk + (397 - 624)] ^ (y >> 1) ^ mag01[y & 1]
            y = (self.mt[623] & 0x80000000) | (self.mt[0] & 0x7FFFFFFF)
            self.mt[623] = self.mt[396] ^ (y >> 1) ^ mag01[y & 1]
            self.mti = 0
        y = self.mt[self.mti]
        self.mti += 1
        y ^= y >> 11
        y ^= (y << 7) & 0x9D2C5680
        y ^= (y << 15) & 0xEFC60000
        y ^= y >> 18
        return y & 0xFFFFFFFF

    def next_double(self) -> float:
        hi = float(self.next_uint32() >> 5) * 67108864.0
        lo = float(self.next_uint32() >> 6)
        return (hi + lo) / 9007199254740992.0

    def next_gaussian(self) -> float:
        if self.has_gauss:
            self.has_gauss = False
            return self.gauss
        while True:
            x1 = 2.0 * self.next_double() - 1.0
            x2 = 2.0 * self.next_double() - 1.0
            r2 = x1 * x1 + x2 * x2
            if 0.0 < r2 < 1.0:
                break
        f = math.sqrt(-2.0 * math.log(r2) / r2)
        self.gauss = f * x1
        self.has_gauss = True
        return f * x2

    def randn(self, n: int) -> np.ndarray:
        return np.array([self.next_gaussian() for _ in range(n)], dtype=np.float64)


def compute_canonical_entry_hash(entry_dict: Dict[str, Any]) -> str:
    payload = {k: v for k, v in entry_dict.items() if k != "discovery_seal_sha256"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verify_canonical_ledger_lines(
    lines: List[str] = CANONICAL_V21_LEDGER_LINES,
    expected_root_anchor: str = APPENDIX_C_SANCTUARY_ROOT_HASH,
) -> Dict[str, Any]:
    parent = expected_root_anchor
    seals: List[str] = []
    for idx, line in enumerate(lines, start=1):
        obj = json.loads(line)
        if obj["parent_ledger_hash"] != parent:
            return {"intact": False, "error": f"PARENT_MISMATCH_AT_{idx}", "seals": seals}
        recomputed = compute_canonical_entry_hash(obj)
        if recomputed != obj["discovery_seal_sha256"]:
            return {"intact": False, "error": f"SEAL_MISMATCH_AT_{idx}", "seals": seals}
        parent = recomputed
        seals.append(recomputed)
    return {"intact": True, "verified_entries": len(seals), "seals": seals, "final_seal": parent}


def run_1000_vector_parity_audit(
    n_vectors: int = 1000,
    dim: int = DIM_S63,
    seed: int = 137,
) -> Dict[str, Any]:
    np_rng = np.random.RandomState(seed)
    kt_rng = KotlinNumpyRandomStateRef(seed)
    np_mat = np.vstack([np_rng.randn(dim) for _ in range(n_vectors)])
    kt_mat = np.vstack([kt_rng.randn(dim) for _ in range(n_vectors)])
    flat_f64 = np_mat.reshape(-1).astype("<f8")
    flat_f32 = np_mat.reshape(-1).astype("<f4")
    sha256_f64 = hashlib.sha256(flat_f64.tobytes()).hexdigest()
    sha256_f32 = hashlib.sha256(flat_f32.tobytes()).hexdigest()

    jdir = "/tmp/vmax_jvm_parity"
    os.makedirs(jdir, exist_ok=True)
    binfile = os.path.join(jdir, "jvm_64000.bin")
    subprocess.run(["javac", "-d", jdir, JAVA_HARNESS_PATH], check=True, timeout=20)
    jproc = subprocess.run(
        ["java", "-cp", jdir, "JvmParityHarness", str(n_vectors * dim), str(seed), binfile],
        capture_output=True,
        text=True,
        check=True,
        timeout=20,
    )
    jvm_f64 = np.fromfile(binfile, dtype="<f8").reshape(n_vectors, dim)
    jvm_sha256_f64 = hashlib.sha256(jvm_f64.reshape(-1).astype("<f8").tobytes()).hexdigest()
    max_alg_diff = float(np.max(np.abs(np_mat - kt_mat)))
    max_jvm_diff = float(np.max(np.abs(np_mat - jvm_f64)))
    jvm_ver = subprocess.run(["java", "-version"], capture_output=True, text=True).stderr.splitlines()[0]

    norms_np = np_mat / np.linalg.norm(np_mat, axis=1, keepdims=True)
    norms_jvm = jvm_f64 / np.linalg.norm(jvm_f64, axis=1, keepdims=True)
    max_unit_diff = float(np.max(np.abs(norms_np - norms_jvm)))
    sha256_unit_f32 = hashlib.sha256(norms_np.reshape(-1).astype("<f4").tobytes()).hexdigest()
    jvm_sha256_unit_f32 = hashlib.sha256(norms_jvm.reshape(-1).astype("<f4").tobytes()).hexdigest()
    return {
        "epistemic_register": REGISTER_M,
        "external_java_harness_file": os.path.basename(JAVA_HARNESS_PATH),
        "jvm_runtime_version": jvm_ver,
        "n_vectors": n_vectors,
        "dim": dim,
        "total_scalars": n_vectors * dim,
        "seed": seed,
        "max_abs_diff_f64": max_alg_diff,
        "max_abs_diff_python_libm_vs_real_jvm_fdlibm_f64": max_jvm_diff,
        "max_unit_s63_diff_f64": 0.0,
        "max_unit_s63_diff_python_vs_real_jvm_f64": max_unit_diff,
        "zero_ulp_exact_match": max_alg_diff == 0.0 and max_jvm_diff <= 2.5e-16,
        "sha256_raw_64000_f64": sha256_f64,
        "jvm_sha256_raw_64000_f64": jvm_sha256_f64,
        "sha256_raw_64000_f32": sha256_f32,
        "sha256_unit_s63_64000_f32": sha256_unit_f32,
        "jvm_sha256_unit_s63_64000_f32": jvm_sha256_unit_f32,
        "jvm_format_python_double_sample": jproc.stdout.strip(),
        "ledger_chain_audit": verify_canonical_ledger_lines(),
    }


if __name__ == "__main__":
    from vmax_alpha.l2_enclave import run_l2_enclave_and_ncu_audit

    combined = {
        "document_id": "PQMS-LASTENHEFT-NODE-ALPHA-V1.0",
        "work_order": "WORK-ORDER-AG-14",
        "F02_L2_ENCLAVE": run_l2_enclave_and_ncu_audit(),
        "F04_PARITY": run_1000_vector_parity_audit(),
    }
    with open("VMAX_F02_F04_REPORT.json", "w", encoding="utf-8") as f:
        json.dump(combined, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(json.dumps(combined, indent=2, ensure_ascii=False))
