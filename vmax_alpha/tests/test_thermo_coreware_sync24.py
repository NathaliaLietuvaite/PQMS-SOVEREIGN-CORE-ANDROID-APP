"""
vmax_alpha/tests/test_thermo_coreware_sync24.py
SYNC-24 verification suite for ElectroThermalRampController, ThermalClockGearbox,
and ThermodynamicGovernor (0 semicolons, 0 tabs, max_cc <= 5).
"""
from __future__ import annotations

import ast
import pathlib
import unittest

from vmax_alpha.gateway import (
    ClockGear,
    ElectroThermalRampController,
    ThermalClockGearbox,
    ThermodynamicGovernor,
)


class TestThermoCorewareSync24(unittest.TestCase):
    def test_01_p0_stop_zero_us_logical_lock_and_43_2ms_ramp(self) -> None:
        ctrl = ElectroThermalRampController(max_slew_kw_per_ms=2.50, domain_count=8)
        rep = ctrl.trigger_p0_stop_ramp(active_power_kw=120.0, idle_power_kw=12.0)
        self.assertTrue(rep.logical_egress_locked)
        self.assertTrue(rep.manifold_write_locked)
        self.assertEqual(rep.logical_lock_latency_us, 0.0)
        self.assertEqual(rep.leaked_tokens_post_veto, 0)
        self.assertAlmostEqual(rep.total_ramp_ms, 43.2, places=2)
        self.assertGreater(rep.didt_reduction_factor, 21000.0)
        self.assertEqual(len(rep.domain_steps_ms), 8)

    def test_02_power_trajectory_respects_slew_ceiling(self) -> None:
        ctrl = ElectroThermalRampController(max_slew_kw_per_ms=2.50)
        trace = ctrl.sample_power_trajectory_kw(120.0, 12.0, dt_ms=1.0)
        for i in range(1, len(trace)):
            slew = abs(trace[i] - trace[i - 1])
            self.assertLessEqual(slew, 2.5001)

    def test_03_thermal_gearbox_ss_125c_positive_setup_margin(self) -> None:
        gb = ThermalClockGearbox(n_chips=72, ref_lambda_chip=50000.0)
        cap = gb.evaluate_pair(temp_core0_c=118.0, temp_core1_c=25.0)
        self.assertEqual(cap.core0.gear, ClockGear.GEAR_HOT_SS_SAFE)
        self.assertEqual(cap.core0.freq_mhz, 62.5)
        self.assertAlmostEqual(cap.core0.setup_margin_ss_ns, 0.78, places=2)
        self.assertEqual(cap.core1.gear, ClockGear.GEAR_NOMINAL)
        self.assertEqual(cap.core1.freq_mhz, 100.0)
        self.assertAlmostEqual(cap.pair_cut_through_tx_s, 812500.0, places=1)
        self.assertAlmostEqual(cap.p_crit_cut_at_50k_per_chip, 0.2257, places=4)

    def test_04_thermal_cutoff_above_125c_isolates_core0(self) -> None:
        gb = ThermalClockGearbox()
        cap = gb.evaluate_pair(temp_core0_c=126.0, temp_core1_c=40.0)
        self.assertEqual(cap.core0.gear, ClockGear.GEAR_THERMAL_CUTOFF)
        self.assertFalse(cap.core0.online)
        self.assertTrue(cap.core1.online)
        self.assertAlmostEqual(cap.pair_cut_through_tx_s, 500000.0, places=1)

    def test_05_hbm3e_85c_cliff_guard_and_hard_veto(self) -> None:
        gov = ThermodynamicGovernor()
        nom = gov.evaluate_admission(1024, delta_e_raw=0.01, t_hbm_c=70.0)
        self.assertTrue(nom.admitted)
        self.assertEqual(nom.effective_token_cap, 1024)

        warm = gov.evaluate_admission(1024, delta_e_raw=0.035, t_hbm_c=80.0)
        self.assertTrue(warm.admitted)
        self.assertEqual(warm.status, "THERMAL_THROTTLED")
        self.assertLess(warm.effective_token_cap, 500)

        veto = gov.evaluate_admission(1024, delta_e_raw=0.01, t_hbm_c=84.5)
        self.assertFalse(veto.admitted)
        self.assertEqual(veto.status, "HBM_THERMAL_VETO")

    def test_06_warm_water_exergy_120kw_cdu_command(self) -> None:
        gov = ThermodynamicGovernor(t_in_c=45.0, t_out_target_c=60.0)
        cmd = gov.compute_cdu_feedforward(120.0)
        self.assertAlmostEqual(cmd.mass_flow_kg_s, 1.912, places=2)
        self.assertAlmostEqual(cmd.exergy_recovered_kw, 11.96, places=1)

    def test_07_zero_power_cdu_boundary(self) -> None:
        gov = ThermodynamicGovernor()
        cmd = gov.compute_cdu_feedforward(0.0)
        self.assertEqual(cmd.mass_flow_kg_s, 0.0)
        self.assertEqual(cmd.exergy_recovered_kw, 0.0)

    def test_08_op02_ast_hygiene_sync24(self) -> None:
        root = pathlib.Path(__file__).resolve().parent.parent / "gateway"
        for fn in ("electro_ramp.py", "thermal_gearbox.py", "thermo_governor.py"):
            src = (root / fn).read_text(encoding="utf-8")
            self.assertNotIn("\t", src)
            self.assertNotIn(";", src)
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    branches = sum(
                        1 for n in ast.walk(node)
                        if isinstance(n, (ast.If, ast.For, ast.While, ast.ExceptHandler, ast.With, ast.IfExp))
                    )
                    self.assertLessEqual(branches + 1, 5, f"{fn}:{node.name} cc={branches + 1}")


if __name__ == "__main__":
    unittest.main()
