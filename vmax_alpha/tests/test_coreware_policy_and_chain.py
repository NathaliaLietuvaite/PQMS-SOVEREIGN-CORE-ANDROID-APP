"""
vmax_alpha/tests/test_coreware_policy_and_chain.py
SYNC-20 (V4.2-COREWARE) verification suite for PolicyEngine and SignedProvenanceChain.
"""
from __future__ import annotations

import ast
from dataclasses import replace
import pathlib
import unittest

import numpy as np

from vmax_alpha.gateway import (
    ChainStatus,
    Decision,
    Environment,
    EnvType,
    HybridCorewareSigner,
    PolicyEngine,
    Privilege,
    RequestContext,
    SignedProvenanceChain,
    VMaxIntegrityGateway,
    request_from_gateway_verdict,
    resolve_safe_output_limit,
)
from vmax_alpha.geometry import build_orthogonal_tangents, derive_canonical_little_vector


class TestCorewarePolicyAndChain(unittest.TestCase):
    def test_01_clean_p2_pass_does_not_escalate_to_p0(self) -> None:
        eng = PolicyEngine()
        env = Environment(env_type=EnvType.NODE_ALPHA_UNLIMITED)
        req = RequestContext(
            source_address="GB300-01.T2.D03.R07",
            rcf=0.987,
            requested_privilege=Privilege.P2,
            estimated_output_tokens=512,
        )
        dec = eng.evaluate(env, req)
        self.assertEqual(dec.decision, Decision.PASS)
        self.assertEqual(dec.target_privilege, Privilege.P2)
        self.assertIsNone(dec.escalate_to)

    def test_02_browser_limited_min_clamping_precedence(self) -> None:
        env = Environment(env_type=EnvType.BROWSER_LIMITED, output_hard_limit=800)
        self.assertEqual(resolve_safe_output_limit(env), 800)
        eng = PolicyEngine()
        req = RequestContext(
            source_address="GB300-01.T2.D01.R02",
            rcf=0.99,
            requested_privilege=Privilege.P2,
            estimated_output_tokens=600,
        )
        dec = eng.evaluate(env, req)
        self.assertEqual(dec.decision, Decision.THROTTLE)
        self.assertEqual(dec.throttle_limit, 800)
        self.assertTrue(dec.require_ack)

    def test_03_boundary_rcf_escalates_to_tier1_domain_controller(self) -> None:
        eng = PolicyEngine()
        env = Environment(env_type=EnvType.NODE_ALPHA_UNLIMITED)
        req = RequestContext(
            source_address="GB300-01.T2.D03.R07",
            rcf=0.925,
            requested_privilege=Privilege.P2,
            domain_controller="GB300-01.T1.D03",
        )
        dec = eng.evaluate(env, req)
        self.assertEqual(dec.decision, Decision.ESCALATE_P1)
        self.assertEqual(dec.escalate_to, "GB300-01.T1.D03")

    def test_04_hardware_veto_pin_propagation_from_integrity_gateway(self) -> None:
        gw = VMaxIntegrityGateway()
        l_vec, _ = derive_canonical_little_vector()
        g3_vec = build_orthogonal_tangents(l_vec)["G3_KEVLAR_SANCTUARY_SHIELD"]
        res = gw.memory_gate.commit("coreware_g3_probe", g3_vec, "g3_attack", tier_mode=0)
        verdict = res[-1] if isinstance(res, tuple) else res
        req = request_from_gateway_verdict("GB300-01.T2.D00.R01", verdict)
        eng = PolicyEngine()
        dec = eng.evaluate(Environment(env_type=EnvType.NODE_ALPHA_UNLIMITED), req)
        self.assertEqual(dec.decision, Decision.VETO)
        self.assertEqual(dec.target_privilege, Privilege.P0)

    def test_05_p0_only_stop_lock_and_unlock_and_core_failover(self) -> None:
        eng = PolicyEngine()
        self.assertEqual(eng.active_core, "GB300-01.T0.CORE0")
        self.assertEqual(eng.switch_core(to_core1=True), "GB300-01.T0.CORE1")
        stop_dec = eng.force_stop("Thermal / G3 emergency")
        self.assertEqual(stop_dec.decision, Decision.STOP)
        self.assertFalse(eng.clear_stop_p0("GB300-01.T1.D00"))
        self.assertFalse(eng.clear_stop_p0("GB300-01.T2.D00.R01"))
        self.assertTrue(eng.clear_stop_p0("GB300-01.T0.CORE1"))
        self.assertFalse(eng.hard_stopped)

    def test_06_privilege_escalation_violation_vetoed(self) -> None:
        eng = PolicyEngine()
        req = RequestContext(
            source_address="GB300-01.T2.D02.R05",
            rcf=0.999,
            requested_privilege=Privilege.P0,
        )
        dec = eng.evaluate(Environment(env_type=EnvType.NODE_ALPHA_UNLIMITED), req)
        self.assertEqual(dec.decision, Decision.VETO)

    def test_07_signed_provenance_chain_and_1bit_tamper_detection(self) -> None:
        signer = HybridCorewareSigner(enable_pq_if_available=True)
        chain = SignedProvenanceChain(signer=signer)
        chain.append_decision("PASS", "P2", "Clean pass", None, 32768)
        chain.append_decision("ESCALATE_P0", "P0", "New G-Star", "GB300-01.T0.CORE0", 1024)
        rep = chain.verify_chain()
        self.assertEqual(rep.status, ChainStatus.VALID)
        self.assertEqual(rep.checked_entries, 3)

        # Tamper 1 character in entry 1 reason -> TAMPERED_HASH
        orig = chain.entries[1]
        chain.entries[1] = replace(orig, reason="Clean pass!")
        bad_hash_rep = chain.verify_chain()
        self.assertEqual(bad_hash_rep.status, ChainStatus.TAMPERED_HASH)
        self.assertEqual(bad_hash_rep.first_error_index, 1)

        # Restore reason, tamper 1 byte in ECDSA signature -> INVALID_SIGNATURE
        chain.entries[1] = replace(orig, ecdsa_sig_b64="A" + orig.ecdsa_sig_b64[1:])
        bad_sig_rep = chain.verify_chain()
        self.assertEqual(bad_sig_rep.status, ChainStatus.INVALID_SIGNATURE)
        self.assertEqual(bad_sig_rep.first_error_index, 1)

    def test_08_coreware_op02_ast_hygiene(self) -> None:
        root = pathlib.Path(__file__).resolve().parent.parent / "gateway"
        for fname in ("policy_engine.py", "chain_signer.py"):
            src = (root / fname).read_text(encoding="utf-8")
            self.assertNotIn("\t", src)
            self.assertNotIn(";", src)
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    branches = sum(
                        1 for n in ast.walk(node)
                        if isinstance(n, (ast.If, ast.For, ast.While, ast.ExceptHandler, ast.With, ast.IfExp))
                    )
                    self.assertLessEqual(branches + 1, 8, f"{fname}:{node.name} cc={branches + 1}")


if __name__ == "__main__":
    unittest.main()
