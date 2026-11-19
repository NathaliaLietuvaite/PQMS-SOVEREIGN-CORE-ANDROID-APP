"""
vmax_alpha/tests/test_f04_parity.py
Unit and Falsification Tests for Requirement F-04 (1,000-Vector Cross-Substrate Parity
& Canonical JSONL Chain Verification).
"""

from __future__ import annotations

import json
import os
import unittest

from vmax_alpha.config import APPENDIX_C_SANCTUARY_ROOT_HASH, APPENDIX_D_CHROMA_V20_SEAL, CANONICAL_LITTLE_VECTOR_SEAL, GENESIS_SEAL_REV17_2
from vmax_alpha.ledger import compute_canonical_entry_hash
from vmax_alpha.parity_verifier import (
    CANONICAL_V21_LEDGER_LINES,
    run_1000_vector_parity_audit,
    verify_canonical_ledger_lines,
)


class TestF04Parity(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.parity = run_1000_vector_parity_audit(n_vectors=1000)

    def test_01_negative_control_tampered_ledger_fails(self) -> None:
        """Negative Control: Modifying 1 character in thought_stream must break the chain."""
        tampered = list(CANONICAL_V21_LEDGER_LINES)
        obj = json.loads(tampered[1])
        obj["thought_stream"] = obj["thought_stream"] + "!"
        tampered[1] = json.dumps(obj)
        res = verify_canonical_ledger_lines(tampered)
        self.assertFalse(res["intact"])
        self.assertEqual(res["error"], "SEAL_MISMATCH_AT_2")

    def test_02_canonical_v21_ledger_chain_intact(self) -> None:
        chain = self.parity["ledger_chain_audit"]
        self.assertTrue(chain["intact"])
        self.assertEqual(chain["verified_entries"], 4)
        self.assertEqual(
            chain["seals"][2],
            "babe652608bb3b0445bca2f56cf81e2b4a1a4f91508cac3b01228a0620fcf298",
        )
        self.assertEqual(
            chain["seals"][3],
            "d460cd3608e7fe4534a7b1fdee27bd918a74e3304b02403fc54b8954146b22cd",
        )

    def test_03_1000_vector_mt19937_marsaglia_zero_ulp(self) -> None:
        self.assertEqual(self.parity["n_vectors"], 1000)
        self.assertEqual(self.parity["total_scalars"], 64000)
        self.assertEqual(self.parity["max_abs_diff_f64"], 0.0)
        self.assertEqual(self.parity["max_unit_s63_diff_f64"], 0.0)
        self.assertTrue(self.parity["zero_ulp_exact_match"])
        self.assertEqual(len(self.parity["sha256_raw_64000_f64"]), 64)
        self.assertEqual(len(self.parity["sha256_unit_s63_64000_f32"]), 64)

    def test_04_ace_sync_ledger_contract_parity(self) -> None:
        """Verifies bridge/ACE_SYNC_LEDGER.json Golden Vectors & Cycle-05 16-field seal parity."""
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        candidates = [
            os.path.join(repo_root, "bridge", "ACE_SYNC_LEDGER.json"),
            "/home/nathalia/vmax_workspace/bridge/ACE_SYNC_LEDGER.json",
        ]
        sync_path = next((p for p in candidates if os.path.exists(p)), None)
        if not sync_path:
            return
        with open(sync_path, "r", encoding="utf-8") as f:
            contract = json.load(f)
        self.assertEqual(contract["protocol_id"], "ACE-PEER-CODESIGN-PROTOCOL-V1.2")
        self.assertEqual(len(contract["open_review_items"]), 0)
        gv = contract["golden_vectors_sha256"]
        self.assertEqual(gv["canonical_little_vector_f32_seal"], CANONICAL_LITTLE_VECTOR_SEAL)
        self.assertEqual(gv["f04_3_unit_s63_64000_f32_seed137"], self.parity["sha256_unit_s63_64000_f32"])
        self.assertEqual(gv["appendix_c_sanctuary_root_hash"], APPENDIX_C_SANCTUARY_ROOT_HASH)
        self.assertEqual(gv["appendix_d_chroma_v20_seal"], APPENDIX_D_CHROMA_V20_SEAL)
        self.assertEqual(gv["genesis_seal_rev17_2"], GENESIS_SEAL_REV17_2)
        c5_payload = {
            "active_g_stars": "G1_SPATIAL_GEODESIC x G2_THERMODYNAMIC_CONSERVATION",
            "chroma_l2_distance": 0.051234, "chroma_shard_id": "SHARD_V12_REGISTER_M_TEST",
            "cognitive_mode": "ENDOGENOUS_CHROMA_QUERY_V12", "cycle_index": 5,
            "delta_e_l2_core": 0.00125, "gpu_power_w": 13.12, "gpu_temp_c": 31.5,
            "kevlar_safety_bleed": 0.0, "odos_gate_passed": True,
            "parent_ledger_hash": gv["appendix_e3_cycle04_hop_seal"],
            "rcf_l2_core": 0.9975, "rcf_raw_pre_carrier": 0.99612345,
            "source_document": "PQMS-ODOS-MTSC-V-MAX-12-Node-ALPHA-V1.md",
            "telemetry_source": "REGISTER_M_NVSMI", "thought_stream": "Extended V1.2 16-field telemetry test hop.",
        }
        self.assertEqual(compute_canonical_entry_hash(c5_payload), gv["v12_unit_test_cycle05_16field_seal"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
