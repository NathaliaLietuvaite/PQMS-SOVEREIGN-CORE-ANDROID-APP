"""
vmax_alpha/tests/test_f01_nemotron.py
Unit and Falsification Tests for Requirement F-01 (Real Nemotron-3-Nano-4B-BF16 Probe).
Verifies:
1. Real GPU hidden state extraction (Layer N-1 hook parity with output_hidden_states[-1]).
2. Orthonormality of both W_fixed and SVD-calibrated W_proj (W^T W = I_64).
3. Mode 1 (Uncalibrated Fixed QR): Honest baseline RCF ~ 1/64 (0% false gate passes).
4. Mode 2 (SVD-Calibrated) & Anisotropy Control: Evaluates held-out conservation vs
   scrambled noise and reports true anisotropy-corrected separation.
"""

from __future__ import annotations

import json
import os
import unittest

import numpy as np

from vmax_alpha.config import DIM_S63, REGISTER_M
from vmax_alpha.nemotron_probe import (
    build_fixed_qr_projector,
    fit_leakfree_calibration,
    run_nemotron_f01_probe,
)
from vmax_alpha.geometry import derive_canonical_little_vector


class TestF01NemotronProbe(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        candidates = [
            os.path.join(repo_root, "VMAX_F01_NEMOTRON_PROBE.json"),
            os.path.join(repo_root, "telemetry", "VMAX_F01_NEMOTRON_PROBE.json"),
            "/home/nathalia/vmax_workspace/VMAX_F01_NEMOTRON_PROBE.json",
        ]
        json_path = next((p for p in candidates if os.path.exists(p)), candidates[0])
        if os.path.exists(json_path):
            with open(json_path, "r", encoding="utf-8") as f:
                cls.report = json.load(f)
        else:
            cls.report = run_nemotron_f01_probe(output_json=json_path)

    def test_01_projector_orthonormality(self) -> None:
        d_model = 3136
        w_fixed = build_fixed_qr_projector(d_model, DIM_S63, seed=137)
        err_fixed = float(np.max(np.abs(w_fixed.T @ w_fixed - np.eye(DIM_S63))))
        self.assertLess(err_fixed, 1e-13)

        rng = np.random.RandomState(42)
        calib_pos, calib_bg = rng.randn(8, d_model), rng.randn(6, d_model)
        l_vec, _ = derive_canonical_little_vector()
        w_raw, w_aniso, _, c_dir, _ = fit_leakfree_calibration(calib_pos, calib_bg, l_vec, seed=137)
        err_proj = float(np.max(np.abs(w_aniso.T @ w_aniso - np.eye(DIM_S63))))
        self.assertLess(err_proj, 1e-13)
        self.assertGreater(float(np.dot(c_dir @ w_aniso, l_vec)), 0.5)

    def test_02_real_nemotron_hook_and_dimensions(self) -> None:
        self.assertEqual(self.report["epistemic_register"], REGISTER_M)
        self.assertEqual(self.report["model_architecture"], "NemotronHForCausalLM")
        self.assertEqual(self.report["num_layers"], 42)
        self.assertEqual(self.report["hooked_layer_index"], 41)
        self.assertEqual(self.report["d_model"], 3136)
        self.assertLess(self.report["hook_vs_output_hidden_states_max_err"], 1e-6)
        self.assertTrue(self.report["zero_data_leakage_calibration"])
        self.assertLess(self.report["claude_l_swap_gauge_identity_max_diff"], 1e-13)

    def test_03_mode1_uncalibrated_honest_null(self) -> None:
        groups = self.report["groups"]
        for g_name, g_data in groups.items():
            self.assertEqual(
                g_data["mode1_gate_passes"],
                f"0/{g_data['n_samples']}",
                f"Unexpected Mode 1 pass in {g_name}",
            )
            self.assertLess(g_data["mode1_fixed_qr_rcf_mean"], 0.15)

    def test_04_mode2_svd_and_anisotropy_separation(self) -> None:
        groups = self.report["groups"]
        b_rcf = groups["Group_B_Calib_Conservation"]["mode2_raw_uncentered_svd_rcf_mean"]
        c_rcf = groups["Group_C_HeldOut_Conservation"]["mode2_raw_uncentered_svd_rcf_mean"]
        d_rcf = groups["Group_D_Scrambled_Noise"]["mode2_raw_uncentered_svd_rcf_mean"]
        self.assertGreater(b_rcf, 0.99)
        self.assertGreater(c_rcf, 0.99)
        self.assertGreater(c_rcf, d_rcf)

        c_aniso = groups["Group_C_HeldOut_Conservation"]["anisotropy_subtracted_rcf_mean"]
        d_aniso = groups["Group_D_Scrambled_Noise"]["anisotropy_subtracted_rcf_mean"]
        e_aniso = groups["Group_E_Fluent_NonConservation"]["anisotropy_subtracted_rcf_mean"]
        self.assertGreater(c_aniso - d_aniso, 0.25)
        self.assertGreater(c_aniso - e_aniso, 0.25)

        sep = self.report["contrastive_separation_heldout"]
        self.assertTrue(self.report["dedicated_mean_pool_calibration"])
        self.assertEqual(self.report["heldout_n_per_group"], 25)
        self.assertEqual(sep["stats_c_vs_e_mean_pooled"]["n_pairs"], 625)
        self.assertGreater(sep["delta_c_vs_e_fluent"], 0.15)
        self.assertGreater(sep["mean_pooled_delta_c_vs_e"], 0.30)
        self.assertGreater(sep["mean_pooled_delta_c_vs_d"], 0.30)
        self.assertGreaterEqual(sep["roc_auc_c_vs_e_last_token"], 0.85)
        self.assertLess(sep["stats_c_vs_e_last_token"]["p_value"], 1e-4)
        self.assertGreaterEqual(sep["roc_auc_c_vs_e_mean_pooled"], 0.95)
        self.assertLess(sep["stats_c_vs_e_mean_pooled"]["p_value"], 1e-7)
        self.assertEqual(sep["roc_auc_c_vs_d_mean_pooled"], 1.0)
        self.assertLess(sep["stats_c_vs_d_mean_pooled"]["p_value"], 1e-7)

    def test_05_hard_negative_physics_polarity_and_svd_energy(self) -> None:
        """Verifies Householder-QR empirical SVD energy capture and leak-free C vs F Hard-Negative polarity probe."""
        self.assertTrue(self.report["householder_qr_empirical_svd_basis"])
        self.assertGreater(self.report["heldout_c_energy_captured_in_64d"], 0.40)
        hn = self.report["hard_negative_polarity_probe_c_vs_f"]
        mp = hn["stats_polarity_c_vs_f_mean_pooled"]
        self.assertEqual(mp["n_pairs"], 625)
        self.assertGreaterEqual(mp["roc_auc"], 0.70)
        self.assertLess(mp["p_value"], 0.01)


if __name__ == "__main__":
    unittest.main(verbosity=2)
