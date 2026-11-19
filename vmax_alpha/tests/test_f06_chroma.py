"""
vmax_alpha/tests/test_f06_chroma.py
Unit and Falsification Tests for Requirement F-06 & F-07.3 (Neural 384D->64D ChromaDB Forager).
"""

from __future__ import annotations

import unittest

from vmax_alpha.chroma_forager import NeuralChromaForager
from vmax_alpha.config import REGISTER_M


class TestF06ChromaForager(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.forager = NeuralChromaForager()
        cls.audit = cls.forager.run_f06_statistical_audit()

    def test_01_neural_384_to_64_orthonormality_and_shard_count(self) -> None:
        self.assertEqual(self.audit["epistemic_register"], REGISTER_M)
        self.assertEqual(self.audit["shard_count"], 18)
        self.assertLess(self.audit["orthonormality_err_w_384_to_64"], 1e-13)

    def test_02_d_l2_statistics_and_pre_g3_reconstruction(self) -> None:
        stats = self.audit["d_l2_statistics"]
        self.assertGreater(stats["mean"], 0.01)
        self.assertLess(stats["mean"], 0.25)
        self.assertGreater(stats["std"], 0.001)
        self.assertLessEqual(stats["min"], stats["mean"])
        self.assertGreaterEqual(stats["max"], stats["mean"])
        self.assertLess(self.audit["max_pre_g3_reconstruction_err"], 1e-7)

    def test_03_chromadb_vs_numpy_nearest_neighbor_parity(self) -> None:
        self.assertLess(self.audit["max_chroma_vs_numpy_l2_diff"], 1e-5)

    def test_04_f07_3_negative_control_chromadb_fault_fallback(self) -> None:
        self.assertEqual(
            self.audit["f07_3_simulated_chroma_fault_mode"],
            "FALLBACK_NUMPY_S63_INDEX",
        )

    def test_05_corpus_invariant_stage1_benign_vs_adversarial(self) -> None:
        """Verifies corpus-order-invariant Stage-1 admission of unseen Pauli physics vs. noise rejection."""
        from vmax_alpha.geometry import evaluate_raw_gate

        self.assertTrue(self.audit["corpus_order_invariant_calibration"])
        _, raw_pauli = self.forager.embed_query_text_with_raw("Pauli exclusion principle and conservation laws")
        _, raw_noise = self.forager.embed_query_text_with_raw("CAPP_ADVERSARIAL_G3_PROBE: xk9# !qP_77 @@zz // 0xdeadbeef")
        ev_pauli = evaluate_raw_gate(raw_pauli, self.forager.little_vector, self.forager.tangents)
        ev_noise = evaluate_raw_gate(raw_noise, self.forager.little_vector, self.forager.tangents)
        self.assertGreaterEqual(ev_pauli.rcf_raw, 0.05)
        self.assertGreater(ev_pauli.rcf_raw, ev_noise.rcf_raw)


if __name__ == "__main__":
    unittest.main(verbosity=2)
