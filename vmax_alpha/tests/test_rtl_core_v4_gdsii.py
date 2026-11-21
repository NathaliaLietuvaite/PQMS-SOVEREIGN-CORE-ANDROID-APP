"""
vmax_alpha/tests/test_rtl_core_v4_gdsii.py
Stage 3 IHP SG13G2 (130 nm) RTL-to-GDSII verification suite (WORK-ORDER-AG-22 / SYNC-17):
  test_01_v4_gdsii_report_manuscript_and_dieshot_integrity
  test_02_v4_python_ast_quality_and_frozen_v31_guard
  test_03_v4_cabi_200_cycles_zero_lsb_stage1_parity
  test_04_v4_multi_tier_44_vector_matrix
  test_05_server_hud_exposes_v4_gdsii_signoff_for_path_b
"""
from __future__ import annotations

import ast
import hashlib
import io
import json
import os
import tempfile
import tokenize
import unittest
from pathlib import Path

import numpy as np

from rtl.run_v3_verification import _build_depeche6_vectors
from vmax_alpha.geometry import build_orthogonal_tangents, derive_canonical_little_vector
from vmax_alpha.hw_gate_bridge import OdosGateV3Bridge, float_vec_to_q2_30
from vmax_alpha.hw_gate_v4_bridge import DEFAULT_V4_SO_PATH, OdosGateV4Bridge, evaluate_v4_integer_ref
from vmax_alpha.server_hud import SanctuaryNodeAlphaService

REPO_ROOT = Path(__file__).resolve().parents[2]
FROZEN_V31_SHA256 = "334b3f1cc0c72410acf04c330da212f3d98953f9ad3c75139be669f5d97e5091"


def _audit_py(path: Path) -> tuple[int, int]:
    src = path.read_text(encoding="utf-8")
    semi = sum(1 for t in tokenize.generate_tokens(io.StringIO(src).readline) if t.type == tokenize.OP and t.string == ";")
    tree = ast.parse(src)
    worst = 1
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            cc = 1
            for sub in ast.walk(node):
                if isinstance(sub, (ast.If, ast.For, ast.While, ast.ExceptHandler, ast.With, ast.Assert, ast.IfExp)):
                    cc += 1
                elif isinstance(sub, ast.BoolOp):
                    cc += len(sub.values) - 1
            worst = max(worst, cc)
    return semi, worst


class TestRtlCoreV4Gdsii(unittest.TestCase):
    def test_01_v4_gdsii_report_manuscript_and_dieshot_integrity(self) -> None:
        rep_path = REPO_ROOT / "telemetry" / "VMAX_RTL_CORE_V4_GDSII_REPORT.json"
        md_path = REPO_ROOT / "PQMS-ODOS-MTSC-V-MAX-12-RTL-CORE-V4.0-GDSII.md"
        png_path = REPO_ROOT / "assets" / "images" / "V-MAX-12-RTL-V4-SG13G2-DIESHOT.png"

        self.assertTrue(rep_path.is_file())
        self.assertTrue(md_path.is_file())
        self.assertTrue(png_path.is_file())
        self.assertGreater(png_path.stat().st_size, 10000)

        rep = json.loads(rep_path.read_text(encoding="utf-8"))
        md_txt = md_path.read_text(encoding="utf-8")
        self.assertNotIn("{{M_", md_txt)
        self.assertNotIn("DIRECT EXECUTION HEADER", md_txt)
        self.assertNotIn("BEGIN_WORK_ORDER_AG22", md_txt)
        rep_sha = hashlib.sha256(rep_path.read_bytes()).hexdigest()
        self.assertIn(rep_sha, md_txt)

        phys = rep["physical_signoff"]
        gen = rep["generic_yosys"]
        self.assertLess(phys["stdcell_ffs"], 1000)
        self.assertLess(gen["generic_ltp_depth"], 110)
        self.assertGreater(phys["fmax_mhz"], 100.0)
        self.assertGreaterEqual(phys["setup_wns_ns"], 0.0)
        self.assertGreaterEqual(phys["hold_wns_ns"], 0.0)
        self.assertEqual(phys["drt_drc_violations"], 0)
        self.assertEqual(rep["cabi_verification"]["stage1_max_lsb_diff"], 0)
        self.assertEqual(rep["cabi_verification"]["depeche6_max_lsb_diff"], 0)

    def test_02_v4_python_ast_quality_and_frozen_v31_guard(self) -> None:
        for rel in (
            "vmax_alpha/hw_gate_v4_bridge.py",
            "rtl/asic_v4/run_v4_gdsii_flow.py",
            "rtl/asic_v4/gdsii_merge_and_render.py",
        ):
            semi, cc = _audit_py(REPO_ROOT / rel)
            self.assertEqual(semi, 0, f"Semicolon found in {rel}")
            self.assertLessEqual(cc, 9, f"Cyclomatic complexity {cc} > 9 in {rel}")
        v31_sha = hashlib.sha256((REPO_ROOT / "rtl" / "odos_gate_core_v3.sv").read_bytes()).hexdigest()
        self.assertEqual(v31_sha, FROZEN_V31_SHA256)

    @unittest.skipUnless(os.path.isfile(DEFAULT_V4_SO_PATH), "libodos_gate_v4.so not compiled")
    def test_03_v4_cabi_200_cycles_zero_lsb_stage1_parity(self) -> None:
        v3 = OdosGateV3Bridge()
        v4 = OdosGateV4Bridge()
        try:
            self.assertTrue(v4.rtl_active)
            l_vec, _ = derive_canonical_little_vector()
            t_g3 = build_orthogonal_tangents(l_vec)["G3_KEVLAR_SANCTUARY_SHIELD"]
            for idx, vec in enumerate((l_vec, t_g3, 0.5 * l_vec, np.zeros(64, dtype=np.float64))):
                vq = float_vec_to_q2_30(vec)
                r3 = v3.evaluate_q30(vq, tier_mode=0, stall_at_idx=17 if idx == 0 else -1, tamper_tier_in_flight=(idx == 0))
                r4 = v4.evaluate_q30(vq, tier_mode=0, stall_at_idx=17 if idx == 0 else -1, tamper_tier_in_flight=(idx == 0))
                self.assertEqual(r4.cycle_count, 200)
                self.assertTrue(r4.reset_fail_closed)
                self.assertTrue(r4.busy_veto_held)
                self.assertEqual(r4.gate_pass, r3.gate_pass)
                self.assertEqual(r4.veto_pin, r3.veto_pin)
                self.assertEqual(r4.rcf_raw_q, r3.rcf_raw_q)
                self.assertEqual(r4.bleed_post_q, r3.bleed_post_q)
                self.assertEqual(r4.stripped_vec_q, r3.stripped_vec_q)
        finally:
            v3.close()
            v4.close()

    @unittest.skipUnless(os.path.isfile(DEFAULT_V4_SO_PATH), "libodos_gate_v4.so not compiled")
    def test_04_v4_multi_tier_44_vector_matrix(self) -> None:
        v4 = OdosGateV4Bridge()
        try:
            runs = 0
            for _, vec in _build_depeche6_vectors():
                vq = float_vec_to_q2_30(vec)
                for tier in (0, 1, 2, 3):
                    ref = evaluate_v4_integer_ref(vq, v4.l_q30, v4.g3_q30, tier_mode=tier)
                    hw = v4.evaluate_q30(vq, tier_mode=tier)
                    self.assertEqual(hw.cycle_count, 200)
                    self.assertEqual(hw.gate_pass, ref.gate_pass)
                    self.assertEqual(hw.mode_fault, tier == 3)
                    self.assertEqual(hw.stripped_vec_q, ref.stripped_vec_q)
                    runs += 1
            self.assertEqual(runs, 44)
        finally:
            v4.close()

    def test_05_server_hud_exposes_v4_gdsii_signoff_for_path_b(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = SanctuaryNodeAlphaService(
                ledger_file=os.path.join(tmp, "ledger.jsonl"),
                quarantine_file=os.path.join(tmp, "quarantine.jsonl"),
                reset=True,
            )
            try:
                snap = svc.get_state_payload()
                self.assertIn("rtl_v4_gdsii_signoff", snap)
                v4_info = snap["rtl_v4_gdsii_signoff"]
                self.assertTrue(v4_info["available"])
                self.assertEqual(v4_info["process"], "IHP_SG13G2_130NM")
                self.assertGreater(float(v4_info["fmax_mhz"]), 100.0)
                self.assertEqual(v4_info["dieshot_asset_uri"], "assets/images/V-MAX-12-RTL-V4-SG13G2-DIESHOT.png")
            finally:
                svc.rtl_bridge.close()
        f05_raw = (REPO_ROOT / "telemetry" / "VMAX_F05_F06_F07_REPORT.json").read_text(encoding="utf-8")
        self.assertIn("be98d730e99a6bfc24f8f379eeaeec260808586b22f900fbeb7303d11352fd29", f05_raw)


if __name__ == "__main__":
    unittest.main()
