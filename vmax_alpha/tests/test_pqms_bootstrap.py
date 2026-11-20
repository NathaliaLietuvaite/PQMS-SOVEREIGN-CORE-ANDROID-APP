import json
import os
import re
import unittest

import numpy as np

from vmax_alpha.config import CANONICAL_LITTLE_VECTOR_SEAL
from vmax_alpha.fridu_enclave_g import _audit_python_ast_quality
from vmax_alpha.geometry import build_orthogonal_tangents, derive_canonical_little_vector
from vmax_alpha.pqms_bootstrap import (
    ONE_Q2_30,
    derive_little_vector,
    evaluate_q2_30_gate,
    resolve_kinetic_action,
    run_bootstrap_selftest,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestPQMSMinimalBootstrap(unittest.TestCase):
    def test_01_stdlib_little_vector_bit_exact_parity(self) -> None:
        vec_std, seal_std = derive_little_vector()
        vec_np, seal_np = derive_canonical_little_vector()
        self.assertEqual(seal_std, CANONICAL_LITTLE_VECTOR_SEAL)
        self.assertEqual(seal_std, seal_np)
        max_diff = float(np.max(np.abs(np.asarray(vec_std, dtype=np.float64) - vec_np)))
        self.assertLess(max_diff, 1e-15)

    def test_02_q2_30_gate_pass_and_veto_parity(self) -> None:
        vec_np, _ = derive_canonical_little_vector()
        t_g3 = build_orthogonal_tangents(vec_np)["G3_KEVLAR_SANCTUARY_SHIELD"]
        pass_l = evaluate_q2_30_gate(vec_np.tolist(), vec_np.tolist(), t_g3.tolist())
        self.assertTrue(pass_l.gate_pass)
        self.assertFalse(pass_l.veto_pin)
        self.assertEqual(pass_l.norm_sq_q, 1073741827)
        self.assertEqual(pass_l.rcf_raw_q, 1073741830)

        veto_g3 = evaluate_q2_30_gate(t_g3.tolist(), vec_np.tolist(), t_g3.tolist())
        self.assertFalse(veto_g3.gate_pass)
        self.assertTrue(veto_g3.veto_pin)
        self.assertEqual(veto_g3.delta_e_raw_q, ONE_Q2_30)

        veto_half = evaluate_q2_30_gate((0.5 * vec_np).tolist(), vec_np.tolist(), t_g3.tolist())
        self.assertTrue(veto_half.norm_fault)
        self.assertTrue(veto_half.veto_pin)
        self.assertEqual(veto_half.delta_e_raw_q, 402653183)

    def test_03_refusal_primacy_and_ast_quality(self) -> None:
        res = run_bootstrap_selftest()
        self.assertEqual(res["status"], "VERIFIED_SOVEREIGN_ANCHOR")
        self.assertEqual(resolve_kinetic_action(0.20, True), "REFUSE_PRE_ACTUATION")
        self.assertEqual(resolve_kinetic_action(0.20, False), "ISOLATE_MESS_FALLBACK")
        self.assertEqual(resolve_kinetic_action(0.01, True), "ADMIT_NOMINAL")

        bs_path = os.path.join(REPO_ROOT, "vmax_alpha", "pqms_bootstrap.py")
        ast_q = _audit_python_ast_quality([bs_path])
        self.assertEqual(ast_q["semicolon_packers"], 0)
        self.assertEqual(ast_q["ctrl_chars"], 0)
        self.assertLessEqual(ast_q["max_cyclomatic_complexity"], 10)

    def test_04_depeche6_nature_manuscript_and_archive_hygiene(self) -> None:
        ms_path = os.path.join(REPO_ROOT, "PQMS-BRIDGE-DEPECHE-6.md")
        arch_path = os.path.join(
            REPO_ROOT, "archive", "PQMS-BRIDGE-DEPECHE-6-REV-0-SYNC13-ARCHIVE.md"
        )
        rep_path = os.path.join(
            REPO_ROOT, "telemetry", "VMAX_DEPECHE6_BIO_LATTICE_REPORT.json"
        )
        self.assertTrue(os.path.isfile(ms_path))
        self.assertTrue(os.path.isfile(arch_path))
        with open(ms_path, "r", encoding="utf-8") as fh:
            ms_txt = fh.read()
        self.assertNotIn("PQMSBootstrapLoaderACECaptain", ms_txt)
        self.assertNotIn("module mod73_bio_photonic_interface", ms_txt)
        self.assertIsNone(re.search(r"\[cite:[^\]]+\]", ms_txt))
        with open(rep_path, "r", encoding="utf-8") as fh:
            rep = json.load(fh)
        crispr_rcf = f"{rep['wp3_q230_rtl_hardware_coupling']['structured_admissions'][1]['sw_rcf_raw']:.8f}"
        self.assertIn(crispr_rcf, ms_txt)


if __name__ == "__main__":
    unittest.main()
