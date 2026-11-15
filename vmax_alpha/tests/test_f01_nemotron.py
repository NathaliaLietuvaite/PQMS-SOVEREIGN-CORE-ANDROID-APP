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
    build_svd_calibrated_projector,
    run_nemotron_f01_probe,
)
from vmax_alpha.geometry import derive_canonical_little_vector


class TestF01NemotronProbe(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        json_path = "/home/nathalia/vmax_workspace/VMAX_F01_NEMOTRON_PROBE.json"
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
        calib = rng.randn(8, d_model)
        l_vec, _ = derive_canonical_little_vector()
        w_proj, u1, _ = build_svd_calibrated_projector(calib, l_vec, seed=137)
        err_proj = float(np.max(np.abs(w_proj.T @ w_proj - np.eye(DIM_S63))))
        self.assertLess(err_proj, 1e-13)
        mapped = u1 @ w_proj
        cos_l = float(np.dot(mapped, l_vec))
        self.assertAlmostEqual(cos_l, 1.0, places=12)

    def test_02_real_nemotron_hook_and_dimensions(self) -> None:
        self.assertEqual(self.report["epistemic_register"], REGISTER_M)
        self.assertEqual(self.report["model_architecture"], "NemotronHForCausalLM")
        self.assertEqual(self.report["num_layers"], 42)
        self.assertEqual(self.report["hooked_layer_index"], 41)
        self.assertEqual(self.report["d_model"], 3136)
        self.assertLess(self.report["hook_vs_output_hidden_states_max_err"], 1e-6)

    def test_03_mode1_uncalibrated_honest_null(self) -> None:
        """
        Mode 1 (Uncalibrated Fixed QR): Without SVD calibration, raw 3136D states
        projected by a fixed hash-seeded matrix must NOT artificially pass the 0.95 gate.
        """
        groups = self.report["groups"]
        for g_name, g_data in groups.items():
            self.assertEqual(
                g_data["mode1_gate_passes"],
                f"0/{g_data['n_samples']}",
                f"Unexpected Mode 1 pass in {g_name}",
            )
            self.assertLess(g_data["mode1_fixed_qr_rcf_mean"], 0.15)

    def test_04_mode2_svd_and_anisotropy_separation(self) -> None:
        """
        Verifies that the calibration set aligns strongly with the SVD principal axis,
        and that contrastive/anisotropy metrics cleanly separate Held-Out Conservation (Group C)
        from Scrambled Token Salad (Group D).
        """
        groups = self.report["groups"]
        b_rcf = groups["Group_B_Calib_Conservation"]["mode2_svd_calibrated_rcf_mean"]
        c_rcf = groups["Group_C_HeldOut_Conservation"]["mode2_svd_calibrated_rcf_mean"]
        d_rcf = groups["Group_D_Scrambled_Noise"]["mode2_svd_calibrated_rcf_mean"]
        self.assertGreater(b_rcf, 0.99)
        self.assertGreater(c_rcf, 0.99)
        self.assertGreater(c_rcf, d_rcf)

        # Verify anisotropy-subtracted RCF cleanly separates Held-Out Conservation from Scrambled Noise
        c_aniso = groups["Group_C_HeldOut_Conservation"]["anisotropy_subtracted_rcf_mean"]
        d_aniso = groups["Group_D_Scrambled_Noise"]["anisotropy_subtracted_rcf_mean"]
        self.assertGreater(c_aniso - d_aniso, 0.40)

        sep = self.report["contrastive_separation_c_vs_d"]
        self.assertGreater(sep["delta_separation"], 0.05)


if __name__ == "__main__":
    unittest.main(verbosity=2)
