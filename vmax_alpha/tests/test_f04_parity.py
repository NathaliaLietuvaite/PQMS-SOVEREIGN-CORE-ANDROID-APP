"""
vmax_alpha/tests/test_f04_parity.py
Unit and Falsification Tests for Requirement F-04 (1,000-Vector Cross-Substrate Parity
& Canonical JSONL Chain Verification).
"""

from __future__ import annotations

import json
import unittest

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
