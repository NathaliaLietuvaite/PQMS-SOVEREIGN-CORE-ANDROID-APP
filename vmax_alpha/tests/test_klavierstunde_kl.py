"""
vmax_alpha/tests/test_klavierstunde_kl.py
Unit tests for Stage 3 Real Subtractive 1-Bit MLP Mask and Empirical Forward-KL (WORK-ORDER-AG-05).
Includes both Positive Control (c = 0.0420%, D_KL <= 0.0500) and Negative Control (Coercive Veto, D_KL > 0.0500).
"""

from __future__ import annotations

import json
import os
import unittest

import torch
from vmax_alpha.config import KL_DIVERGENCE_MAX, SUBTRACTIVE_CUT_FRACTION
from vmax_alpha.klavierstunde_kl import (
    apply_subtractive_1bit_mlp_mask,
    compute_exact_forward_kl,
    evaluate_kl_against_baseline,
)


class TestKlavierstundeKL(unittest.TestCase):
    def test_exact_forward_kl_identities_and_negative_control(self) -> None:
        torch.manual_seed(137)
        base_logits = [torch.randn(1, 4096, dtype=torch.float32) for _ in range(4)]

        # Identical distributions -> KL == 0.0
        kl_zero = compute_exact_forward_kl(base_logits[0], base_logits[0].clone())
        self.assertLessEqual(abs(kl_zero), 1e-14)

        # Tiny perturbation -> passes laminar KL gate (<= 0.0500)
        tiny_mod = [lb + 0.01 * torch.randn_like(lb) for lb in base_logits]
        res_pass = evaluate_kl_against_baseline(base_logits, tiny_mod)
        self.assertTrue(res_pass["passed"])
        self.assertEqual(res_pass["odos_kl_gate_status"], "PASS_LAMINAR")
        self.assertLessEqual(res_pass["mean_forward_kl"], KL_DIVERGENCE_MAX)

        # Negative control: Coercive logit distortion -> triggers VETO_KL_EXCEEDED (> 0.0500)
        corrupt_mod = [lb + 2.5 * torch.randn_like(lb) for lb in base_logits]
        res_veto = evaluate_kl_against_baseline(base_logits, corrupt_mod)
        self.assertFalse(res_veto["passed"])
        self.assertEqual(res_veto["odos_kl_gate_status"], "VETO_KL_EXCEEDED")
        self.assertGreater(res_veto["mean_forward_kl"], KL_DIVERGENCE_MAX)

    def test_subtractive_1bit_mask_exact_zero_fraction(self) -> None:
        torch.manual_seed(137)
        layer = torch.nn.Linear(256, 512, bias=False, device="cuda:0", dtype=torch.bfloat16)
        torch.nn.init.normal_(layer.weight, mean=0.0, std=0.05)
        meta = apply_subtractive_1bit_mlp_mask(
            [(0, layer)], cut_fraction=SUBTRACTIVE_CUT_FRACTION, mode="smallest_magnitude"
        )
        expected_zeros = int(round(256 * 512 * SUBTRACTIVE_CUT_FRACTION))
        actual_zeros = int(torch.sum(layer.weight.data == 0).item())
        self.assertEqual(meta["zeroed_weights_count"], expected_zeros)
        self.assertGreaterEqual(actual_zeros, expected_zeros)

    def test_saved_nemotron_stage3_kl_report_verified(self) -> None:
        report_path = "/home/nathalia/vmax_workspace/VMAX_STAGE3_REAL_KL_REPORT.json"
        if os.path.exists(report_path):
            with open(report_path, "r", encoding="utf-8") as f:
                rep = json.load(f)
            self.assertEqual(rep["epistemic_register"], "REGISTER_M")
            self.assertTrue(rep["condition_a1_smallest_magnitude_0042pct"]["passed"])
            self.assertLessEqual(
                rep["condition_a1_smallest_magnitude_0042pct"]["mean_forward_kl"], KL_DIVERGENCE_MAX
            )
            self.assertTrue(rep["condition_a2_random_subtractive_0042pct"]["passed"])
            self.assertFalse(rep["condition_b1_matched_sparsity_largest_magnitude_0042pct"]["passed"])
            self.assertGreater(
                rep["condition_b1_matched_sparsity_largest_magnitude_0042pct"]["mean_forward_kl"], KL_DIVERGENCE_MAX
            )
            self.assertFalse(rep["condition_b_negative_control_coercive_5pct"]["passed"])
            self.assertGreater(
                rep["condition_b_negative_control_coercive_5pct"]["mean_forward_kl"], KL_DIVERGENCE_MAX
            )
            self.assertEqual(rep["weight_restoration_max_logit_diff"], 0.0)


if __name__ == "__main__":
    unittest.main()
