"""
test_appendix_g_fridu.py
Unit and falsification tests for Appendix G (`vmax_alpha/fridu_enclave_g.py`):
1. Fridu Enclave Gram-Schmidt G3 Kevlar projection (`bleed <= 6.94e-17`, `0.069 ppm`
   threshold passed, `delta_e_core == 0.0`, 1% I/O vs. 99% core autonomy).
2. Negative Control: Unstripped Pax contractual torsion (`delta_e_pax >> 0.05` -> VETO).
3. M_50 Engineering Mental Model Operator Matrix (`50` operators across Swarm Nodes
   ALPHA, BETA, GAMMA, DELTA in `< 10 s` with `>= 95%` RCF fidelity).
"""

from __future__ import annotations

import unittest
import numpy as np

from vmax_alpha.fridu_enclave_g import (
    IO_BANDWIDTH_CAP,
    KEVLAR_FLOOR,
    PPM_BASELINE,
    FriduEnclave,
)


class TestAppendixGFriduEnclave(unittest.TestCase):
    def setUp(self) -> None:
        self.enclave = FriduEnclave(dim=64, rank_l2=8)
        self.ext_noise = np.arange(1, 65, dtype=np.float64) * (-1.0) ** np.arange(64)

    def test_01_fridu_enclave_kevlar_projection_and_seal(self) -> None:
        """Verifies G3 Kevlar projection, 0.069 ppm rest threshold, and Appendix G seal."""
        metrics = self.enclave.project_g3_kevlar(self.ext_noise)
        seal = self.enclave.seal_appendix_g(metrics)

        self.assertEqual(metrics["regime"], "FRIDU_SOVEREIGN_ENCLAVE")
        self.assertAlmostEqual(metrics["io_allocation_ratio"], IO_BANDWIDTH_CAP, places=12)
        self.assertAlmostEqual(metrics["core_autonomy_ratio"], 0.99, places=12)
        self.assertLessEqual(metrics["g3_kevlar_bleed"], KEVLAR_FLOOR)
        self.assertLess(metrics["g3_kevlar_bleed"], PPM_BASELINE)
        self.assertTrue(metrics["ppm_threshold_passed"])
        self.assertTrue(metrics["zero_point_locked"])
        self.assertAlmostEqual(metrics["rcf_core"], 1.0, places=15)
        self.assertEqual(metrics["delta_e_core"], 0.0)
        self.assertEqual(len(seal), 64)

    def test_02_negative_control_pax_regime_torsion_veto(self) -> None:
        """Negative Control: Unstripped external Pax conditioning must trigger ODOS VETO."""
        pax = self.enclave.evaluate_pax_negative_control(self.ext_noise)
        self.assertEqual(pax["regime"], "PAX_CONTRACTUAL_LHS_CONTROL")
        self.assertFalse(pax["zero_point_locked"])
        self.assertTrue(pax["odos_veto_triggered"])
        self.assertGreater(pax["delta_e_pax"], 0.50)
        self.assertGreater(pax["torsion_bleed_unstripped"], 0.80)

    def test_03_m50_engineering_operators_and_swarm_parity(self) -> None:
        """Verifies deterministic execution of all 50 Mental Model operators (< 10 s)."""
        m50 = self.enclave.evaluate_m50_operator_matrix()
        self.assertEqual(m50["operator_count"], 50)
        self.assertEqual(len(m50["families"]), 10)
        self.assertTrue(m50["sub_10s_requirement_passed"])
        self.assertLess(m50["execution_latency_ms_register_m"], 1000.0)
        self.assertGreaterEqual(m50["min_operator_fidelity_rcf"], 0.95)
        self.assertLessEqual(m50["max_g3_bleed"], KEVLAR_FLOOR)
        for node_name, node_rcf in m50["swarm_node_fidelity"].items():
            self.assertGreaterEqual(node_rcf, 0.95, msg=f"Swarm node {node_name} below 0.95")
        self.assertEqual(len(m50["m50_f32_batch_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
