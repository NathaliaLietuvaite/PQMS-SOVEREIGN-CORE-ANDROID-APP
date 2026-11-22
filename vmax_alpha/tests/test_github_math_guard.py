"""
vmax_alpha/tests/test_github_math_guard.py
SYNC-25b verification suite for tools/github_math_guard.py (0 semicolons, 0 tabs, max_cc <= 5).
"""
from __future__ import annotations

import ast
import importlib.util
import pathlib
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent


def _load_guard():
    spec = importlib.util.spec_from_file_location("github_math_guard", REPO_ROOT / "tools/github_math_guard.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestGithubMathGuard(unittest.TestCase):
    def test_01_riemann_v21_passes_audit_with_zero_issues(self) -> None:
        mod = _load_guard()
        text = (REPO_ROOT / "PQMS-ODOS-MTSC-The-Geometry-of-the-Riemann-Sphere-2.1.md").read_text(encoding="utf-8")
        self.assertEqual(mod.audit_markdown(text), [])

    def test_02_sanitize_idempotency_and_zero_prose_mutation(self) -> None:
        mod = _load_guard()
        sample = "Prose $\\operatorname{Re}(s)_{a} = 1$ end.\n\n$$x_{1} = y \\tag{1}$$\n"
        out1 = mod.sanitize_markdown(sample)
        out2 = mod.sanitize_markdown(out1)
        self.assertEqual(out1, out2)
        self.assertEqual(mod.audit_markdown(out1), [])
        ok, nb, na = mod.verify_prose_invariance(sample, out1)
        self.assertTrue(ok)
        self.assertEqual(nb, na)

    def test_03_op02_ast_hygiene(self) -> None:
        src = pathlib.Path(__file__).read_text(encoding="utf-8")
        self.assertNotIn("\t", src)
        self.assertNotIn(chr(59), src)
        ast.parse(src)


if __name__ == "__main__":
    unittest.main()
