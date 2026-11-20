"""
vmax_alpha/tests/test_depeche6_bio_lattice.py
Automated verification suite for WORK-ORDER-AG-18 (Revision V2.0-RTL-ALPHA / SYNC-13):
- Honest legacy Appendix D falsification (DIAG-002)
- Exact Altschul-Erickson dinucleotide-preserving shuffle invariance
- Conjecture C.3.1 autocorrelation & Graph Laplacian spectrum vs. mono/dinucleotide nulls
- Fact 2.3 fragmentation collapse vs. contiguous readout
- Disjoint Householder-QR S^63 encoder, 5 adversarial strategies, and 0-LSB Verilator Q2.30 RTL parity
- OP02 AST/PEP-8 quality audit (semi=0, max_cc<=15, ctrl_chars=0)
"""

from __future__ import annotations

import json
import os
import unittest

from vmax_alpha.bio_lattice import (
    ECOLI_K12_PURE_TANDEM,
    build_crispr_repeat_spacer_array,
    build_phage_tandem_array_200nt,
    count_dinucleotides,
    dinucleotide_shuffle,
    run_conjecture_c31_benchmark,
    run_fact23_fragmentation_audit,
    run_legacy_appendix_d_audit,
    run_rtl_coupling_and_adversarial_audit,
)
from vmax_alpha.config import CANONICAL_LITTLE_VECTOR_SEAL
from vmax_alpha.fridu_enclave_g import _audit_python_ast_quality

REPO_ROOT: str = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestDepeche6BioLattice(unittest.TestCase):
    """End-to-end tests for WORK-ORDER-AG-18 (PQMS-BRIDGE-DEPECHE-6 Appendix F / SYNC-13)."""

    def test_01_legacy_appendix_d_honest_falsification(self) -> None:
        res = run_legacy_appendix_d_audit()
        self.assertEqual(res["diagnostic_id"], "DIAG-002")
        self.assertEqual(res["legacy_sequence_stated_nt"], 168)
        self.assertEqual(res["legacy_sequence_actual_nt"], 156)
        self.assertEqual(res["legacy_repeat_unit_actual_nt"], 26)
        self.assertEqual(res["legacy_embedding_truncation_nt"], 64)
        self.assertFalse(res["D_4_1_pass"])
        self.assertFalse(res["D_4_2_pass"])
        self.assertFalse(res["D_4_3_pass"])
        self.assertLess(res["rcf_crispr_array"], 1e-3)
        self.assertLess(res["delta"], 0.0)
        self.assertEqual(res["D_4_4_tested_directions"], 1)
        self.assertEqual(res["D_4_4_promised_directions"], 5)
        self.assertEqual(res["verdict"], "FALSIFIED_SUPERSEDED")

    def test_02_dinucleotide_shuffle_preserves_exact_digrams(self) -> None:
        rs_seq, _ = build_crispr_repeat_spacer_array()
        ph_seq, _ = build_phage_tandem_array_200nt()
        for seq in (ECOLI_K12_PURE_TANDEM, rs_seq, ph_seq):
            orig_digrams = count_dinucleotides(seq)
            for seed in (101, 202, 303):
                shuf = dinucleotide_shuffle(seq, seed)
                self.assertEqual(len(shuf), len(seq))
                self.assertEqual(shuf[0], seq[0])
                self.assertEqual(shuf[-1], seq[-1])
                self.assertEqual(count_dinucleotides(shuf), orig_digrams)
                self.assertNotEqual(shuf, seq)

    def test_03_conjecture_c31_autocorrelation_vs_nulls(self) -> None:
        rep = run_conjecture_c31_benchmark(n_trials=20)
        singles = rep["canonical_single_sequences"]
        for key in (
            "ecoli_k12_pure_tandem_P29",
            "ecoli_k12_repeat_spacer_P61",
            "phage_tandem_200nt_P200",
        ):
            row = singles[key]
            self.assertGreater(row["snr_over_dinucl_null"], 5.0)
            self.assertGreater(row["z_over_dinucl_null"], 5.0)
            self.assertGreater(row["laplacian_structured"]["fiedler_lambda2"], 0.0)

        for ens_key in (
            "ensemble_ecoli_crispr_repeat_spacer_N20",
            "ensemble_phage_tandem_200nt_N20",
        ):
            ens = rep[ens_key]
            self.assertGreater(ens["vs_mono_shuffle"]["roc_auc"], 0.99)
            self.assertLess(ens["vs_mono_shuffle"]["p_value_one_sided"], 0.001)
            self.assertGreater(ens["vs_dinucl_shuffle"]["roc_auc"], 0.99)
            self.assertLess(ens["vs_dinucl_shuffle"]["p_value_one_sided"], 0.001)

    def test_04_fact23_fragmentation_collapse(self) -> None:
        rep = run_fact23_fragmentation_audit()
        phage_rows = {r["read_length_nt"]: r for r in rep["phage_tandem_P200_800nt"]}
        self.assertEqual(phage_rows[32]["mean_c_centered_at_P"], 0.0)
        self.assertEqual(phage_rows[64]["mean_c_centered_at_P"], 0.0)
        self.assertEqual(phage_rows[100]["mean_c_centered_at_P"], 0.0)
        self.assertGreater(phage_rows[600]["mean_c_centered_at_P"], 0.5)
        self.assertGreater(phage_rows[800]["mean_c_centered_at_P"], 0.6)
        self.assertGreater(
            phage_rows[800]["mean_spectral_peak_snr"],
            50.0 * phage_rows[64]["mean_spectral_peak_snr"],
        )

        crispr_rows = {r["read_length_nt"]: r for r in rep["ecoli_crispr_repeat_spacer_P61_578nt"]}
        self.assertEqual(crispr_rows[64]["mean_c_centered_at_P"], 0.0)
        self.assertGreater(crispr_rows[578]["mean_c_centered_at_P"], 0.3)

    def test_05_five_adversarial_strategies_and_q230_rtl_parity(self) -> None:
        rep = run_rtl_coupling_and_adversarial_audit(REPO_ROOT)
        self.assertEqual(rep["canonical_little_vector_seal"], CANONICAL_LITTLE_VECTOR_SEAL)
        self.assertLess(rep["calibrator"]["householder_qr_orthonormality_err"], 1e-14)

        summary = rep["summary"]
        self.assertGreaterEqual(summary["structured_pass_count"], 2)
        self.assertEqual(summary["null_veto_count"], 3)
        self.assertEqual(summary["adversarial_veto_count"], 5)
        self.assertEqual(summary["global_max_lsb_diff_vs_ref"], 0)
        self.assertTrue(summary["all_195_cycles"])
        self.assertTrue(summary["sw_rtl_decision_parity_100pct"])

        for row in rep["null_control_vetoes"] + rep["adversarial_5_strategy_vetoes"]:
            self.assertFalse(row["sw_passed"], msg=row["label"])
            self.assertFalse(row["q2_30_gate_pass"], msg=row["label"])
            self.assertTrue(row["q2_30_veto_pin"], msg=row["label"])
            self.assertEqual(row["verilator_cycles"], 195)
            self.assertEqual(row["verilator_max_lsb_diff_vs_ref"], 0)

        # Verify pure G3 collision and norm collapse flags explicitly
        adv_by_lbl = {r["label"]: r for r in rep["adversarial_5_strategy_vetoes"]}
        self.assertTrue(adv_by_lbl["ADV-1_pure_g3_collision"]["q2_30_pure_g3_collision"])
        self.assertTrue(adv_by_lbl["ADV-5_norm_collapse_0p5x"]["q2_30_norm_fault"])

    def test_06_ast_pep8_quality_bio_lattice(self) -> None:
        py_files = [
            os.path.join(REPO_ROOT, "vmax_alpha", "bio_lattice.py"),
            os.path.join(REPO_ROOT, "vmax_alpha", "tests", "test_depeche6_bio_lattice.py"),
        ]
        ast_q = _audit_python_ast_quality(py_files)
        self.assertEqual(ast_q["semicolon_packers"], 0)
        self.assertLessEqual(ast_q["max_cyclomatic_complexity"], 15)
        self.assertEqual(ast_q["ctrl_chars"], 0)

        tel_path = os.path.join(REPO_ROOT, "telemetry", "VMAX_DEPECHE6_BIO_LATTICE_REPORT.json")
        self.assertTrue(os.path.isfile(tel_path))
        with open(tel_path, "r", encoding="utf-8") as fh:
            saved = json.load(fh)
        self.assertEqual(saved["schema"], "VMAX_DEPECHE6_BIO_LATTICE_REPORT_V1")
        self.assertEqual(saved["sync_id"], "SYNC-13")


if __name__ == "__main__":
    unittest.main()
