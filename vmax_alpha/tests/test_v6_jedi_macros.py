#!/usr/bin/env python3
"""
vmax_alpha/tests/test_v6_jedi_macros.py

PQMS / V-MAX-12-CORE-JEDI (SYNC-37 / WP-3):
Deterministic signoff test verifying `tools/v6_jedi_macro_audit.py` (`all_passed=True`)
and zero-GPU execution (`torch_imported=False`) for hardened `jedi_coherence_tile`
and `jedi_central_spine` macros on IHP SG13G2 130 nm.

OP02-AST-clean: 0 semicolons, 0 tabs, flat helpers (max McCabe CC <= 5).
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


def _repo_root() -> Path:
    """Locate repository root containing rtl_v6/macros."""
    return Path(__file__).resolve().parents[2]


class TestV6JediMacros(unittest.TestCase):
    """Verify SYNC-37 hardened macro LEF, dont_touch, canary, and export completeness."""

    def test_01_macro_audit_passes_all_gates(self) -> None:
        root = _repo_root()
        macro_dir = root / "rtl_v6" / "macros"
        proc = subprocess.run(
            [
                sys.executable,
                "tools/v6_jedi_macro_audit.py",
                "--macro-dir",
                str(macro_dir),
            ],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        rep = json.loads(proc.stdout)
        self.assertTrue(rep["all_passed"])
        self.assertFalse(rep["torch_imported"])
        self.assertTrue(rep["tile_lef_audit"]["top_metals_unobstructed"])
        self.assertTrue(rep["spine_lef_audit"]["top_metals_unobstructed"])
        self.assertTrue(rep["spine_dont_touch_audit"]["passed"])
        self.assertTrue(rep["canary_guardband_audit"]["passed"])
        self.assertTrue(rep["tile_exports"]["all_present"])
        self.assertTrue(rep["spine_exports"]["all_present"])

    def test_02_zero_torch_import(self) -> None:
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys, tools.v6_jedi_macro_audit; assert 'torch' not in sys.modules",
            ],
            cwd=str(_repo_root()),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)


if __name__ == "__main__":
    unittest.main()
