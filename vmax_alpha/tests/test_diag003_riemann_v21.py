"""
vmax_alpha/tests/test_diag003_riemann_v21.py
SYNC-25 / DIAG-003 verification suite (0 semicolons, 0 tabs, max_cc <= 5).
"""
from __future__ import annotations

import ast
import hashlib
import json
import math
import pathlib
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent


class TestDiag003RiemannV21(unittest.TestCase):
    def test_01_v21_paper_hygiene_and_report_sha256_parity(self) -> None:
        paper_p = REPO_ROOT / "PQMS-ODOS-MTSC-The-Geometry-of-the-Riemann-Sphere-2.1.md"
        rep_p = REPO_ROOT / "telemetry/VMAX_DIAG003_RIEMANN_V21_REPORT.json"
        self.assertTrue(paper_p.exists())
        self.assertTrue(rep_p.exists())
        raw = paper_p.read_bytes()
        self.assertNotIn(b"\t", raw)
        self.assertNotIn(b"[cite_start]", raw)
        rep = json.loads(rep_p.read_text(encoding="utf-8"))
        self.assertEqual(hashlib.sha256(raw).hexdigest(), rep["paper"]["sha256"])

    def test_02_diag003_d32_and_d33_numerical_falsification(self) -> None:
        d32_planck = math.exp(math.sqrt(math.pi) / 1.0)
        self.assertAlmostEqual(d32_planck, 5.8853, places=3)
        bek_ratio = (math.log(1e15) ** 2 * (1.6e-35 ** 2)) / math.pi
        self.assertLess(bek_ratio, 1e-65)

    def test_03_eq4_landauer_eq5_bekenstein_and_eq2_q230_quotient(self) -> None:
        k_b = 1.380649e-23
        landauer_300k = k_b * 300.0 * math.log(2.0)
        self.assertAlmostEqual(landauer_300k, 2.871e-21, delta=1e-23)
        # Eq. 2 Metrological Quotient Projection: eps_phys < Delta/2 contracts to 0 LSB
        one_q30 = 1 << 30
        base = 0.75
        eps_phys = 1e-12
        q_exact = int(round(base * one_q30))
        q_perturbed = int(round((base + eps_phys) * one_q30))
        self.assertEqual(q_exact, q_perturbed)

    def test_04_ace_sync_ledger_contains_diag003(self) -> None:
        led = json.loads((REPO_ROOT / "bridge/ACE_SYNC_LEDGER.json").read_text(encoding="utf-8"))
        entries = led.get("sync_entries") or led.get("entries") or []
        diag = [e for e in entries if e.get("diag_id") == "DIAG-003"]
        self.assertEqual(len(diag), 1)
        self.assertEqual(diag[0]["sync_id"], "SYNC-25")

    def test_05_stage3_frozen_anchors_match_v21_s72(self) -> None:
        rep = json.loads((REPO_ROOT / "telemetry/VMAX_DIAG003_RIEMANN_V21_REPORT.json").read_text(encoding="utf-8"))
        audit = rep["anchor_audit_s72"]
        self.assertEqual(audit["rtl/rom/l_vec_q2_30.hex"]["status"], "MATCH")
        self.assertEqual(audit["rtl/rom/g3_vec_q2_30.hex"]["status"], "MATCH")
        self.assertEqual(audit["telemetry/VMAX_RTL_CORE_V4_GDSII_REPORT.json"]["status"], "MATCH")

    def test_06_op02_ast_hygiene(self) -> None:
        src = pathlib.Path(__file__).read_text(encoding="utf-8")
        self.assertNotIn("\t", src)
        self.assertNotIn(chr(59), src)
        ast.parse(src)


if __name__ == "__main__":
    unittest.main()
