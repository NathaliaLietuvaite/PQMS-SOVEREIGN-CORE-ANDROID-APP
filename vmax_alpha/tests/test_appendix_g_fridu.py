"""
test_appendix_g_fridu.py (WORK-ORDER-AG-12 / Revision V1.5)
Non-tautological unit and falsification tests for `vmax_alpha/fridu_enclave_g.py`:
1. Fridu vs. Pax perturbation A/B test on IDENTICAL core state + external torsion.
2. Negative Control: Bypassing the G3 Kevlar shield causes immediate Fridu veto/drift.
3. Executable Engineering Audit Operators: All 10 real workspace/telemetry operators pass.
"""

from __future__ import annotations

import unittest
import numpy as np

from vmax_alpha.fridu_enclave_g import KEVLAR_FLOOR, PPM_BASELINE, FriduEnclave


class TestAppendixGFriduEnclave(unittest.TestCase):
    def setUp(self) -> None:
        self.enclave = FriduEnclave()
        self.ext_noise = np.arange(1, 65, dtype=np.float64) * (-1.0) ** np.arange(64)

    def test_01_fridu_vs_pax_perturbation_ab_no_tautology(self) -> None:
        """Identical core + external torsion: PAX fails gate, FRIDU preserves core & I/O buffer."""
        res = self.enclave.evaluate_perturbation_ab(self.ext_noise, coupling_beta=0.35, bypass_kevlar=False)
        base, pax, fridu = res["base_core_state"], res["pax_unshielded"], res["fridu_shielded"]

        # Core base state is genuinely non-trivial (RCF < 1.0, not dot(L, L) == 1.0)
        self.assertLess(base["rcf_raw"], 0.999)
        self.assertTrue(base["passed"])

        # PAX unshielded: real core drift and ODOS veto
        self.assertFalse(pax["odos_gate_passed"])
        self.assertTrue(pax["odos_veto_triggered"])
        self.assertGreater(pax["core_drift_l2"], 0.25)
        self.assertGreater(pax["delta_e_raw"], 0.05)

        # FRIDU shielded: strips perturbation into 1% I/O buffer without corrupting core
        self.assertTrue(fridu["odos_gate_passed"])
        self.assertTrue(fridu["ppm_threshold_passed"])
        self.assertTrue(fridu["kevlar_floor_locked"])
        self.assertLessEqual(fridu["boundary_bleed_l2"], KEVLAR_FLOOR)
        self.assertLess(fridu["core_drift_l2"], 1e-15)
        self.assertLess(fridu["io_buffer_reconstruction_err"], 1e-15)
        self.assertEqual(len(self.enclave.seal_appendix_g(res)), 64)

    def test_02_negative_control_kevlar_bypass_fails_gate(self) -> None:
        """Negative Control: Disabling Kevlar orthogonal stripping causes Fridu branch to VETO."""
        bypassed = self.enclave.evaluate_perturbation_ab(self.ext_noise, coupling_beta=0.35, bypass_kevlar=True)
        fridu_bad = bypassed["fridu_shielded"]
        self.assertFalse(fridu_bad["odos_gate_passed"])
        self.assertFalse(fridu_bad["kevlar_floor_locked"])
        self.assertGreater(fridu_bad["core_drift_l2"], 0.25)

    def test_03_executable_engineering_audit_operators(self) -> None:
        """Verifies all 10 real engineering audit operators pass on actual workspace artifacts."""
        ops = self.enclave.run_executable_engineering_operators()
        self.assertEqual(ops["operator_count"], 10)
        self.assertLess(ops["execution_latency_ms"], 10000.0)
        failed = [o for o in ops["operators"] if not o["passed"]]
        self.assertEqual(failed, [], msg=f"Failed engineering operators: {failed}")
        self.assertTrue(ops["all_operators_passed"])
        self.assertEqual(len(ops["audit_matrix_seal_sha256"]), 64)

    def test_04_epistemic_register_and_one_percent_io_asymmetry(self) -> None:
        """Verifies 1% peripheral I/O budget cap, 99% core autonomy, and REGISTER_M tag."""
        res = self.enclave.evaluate_perturbation_ab(self.ext_noise, coupling_beta=0.35)
        self.assertEqual(res["epistemic_register"], "REGISTER_M")
        self.assertAlmostEqual(res["fridu_shielded"]["io_allocation_cap"], 0.01, places=12)
        self.assertAlmostEqual(res["fridu_shielded"]["core_autonomy_ratio"], 0.99, places=12)
        self.assertAlmostEqual(
            res["fridu_shielded"]["io_allocation_cap"] + res["fridu_shielded"]["core_autonomy_ratio"],
            1.0,
            places=12,
        )

    def test_05_in_band_tg1_attack_caught_by_downstream_odos_gate(self) -> None:
        """Defense-in-Depth: In-band t_G1 attack bypasses linear strip and is vetoed by downstream ODOS gate."""
        ib = self.enclave.evaluate_in_band_tg1_attack(coupling_beta=0.35)
        self.assertFalse(ib["linear_projector_stripped"])
        self.assertLess(ib["io_buffer_norm"], 1e-15)
        self.assertFalse(ib["odos_gate_passed"])
        self.assertTrue(ib["downstream_odos_veto_triggered"])
        self.assertGreater(ib["delta_e_raw"], 0.05)


if __name__ == "__main__":
    unittest.main(verbosity=2)
