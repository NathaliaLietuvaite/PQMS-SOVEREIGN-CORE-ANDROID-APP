"""
vmax_alpha/tests/test_integrity_gateway.py
End-to-end adversarial & multi-agent verification suite for Stage 4 Integrity
Middleware (`WORK-ORDER-AG-24` / `SYNC-19`, WP-3).

Covers all 6 mandatory hardware-gated failure modes (zero mocks) plus AST
hygiene and `/api/gateway/metrics` schema parity.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
import unittest
from typing import Dict

import numpy as np

from vmax_alpha.config import ALPHA_POTENTIA, DIM_S63
from vmax_alpha.fridu_enclave_g import _audit_python_ast_quality
from vmax_alpha.gateway import MTSC12_CANONICAL_LANES, VMaxIntegrityGateway
from vmax_alpha.geometry import build_orthogonal_tangents, derive_canonical_little_vector
from vmax_alpha.hw_gate_bridge import (
    TIER_0_PURE_CARRIER,
    TIER_1_MOSAIC_LOCUS,
    TIER_2_CORE_LOCK,
    TIER_3_GLITCH_VETO,
)

REPO_ROOT: str = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestVMaxIntegrityGateway(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.p_ledger = os.path.join(self._tmp.name, "gw_primary.jsonl")
        self.q_ledger = os.path.join(self._tmp.name, "gw_quarantine.jsonl")
        self.l_vec, _ = derive_canonical_little_vector()
        self.tangents = build_orthogonal_tangents(self.l_vec)
        self.t_g1 = self.tangents["G1_SPATIAL_GEODESIC"]
        self.t_g3 = self.tangents["G3_KEVLAR_SANCTUARY_SHIELD"]
        c_l = math.sqrt(1.0 - ALPHA_POTENTIA * ALPHA_POTENTIA)
        psi = c_l * self.l_vec + ALPHA_POTENTIA * self.t_g1
        self.psi_core = psi / float(np.linalg.norm(psi))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _new_gateway(self, verify_v4: bool = False) -> VMaxIntegrityGateway:
        return VMaxIntegrityGateway(
            ledger_file=self.p_ledger,
            quarantine_file=self.q_ledger,
            default_tier=TIER_0_PURE_CARRIER,
            verify_v4=verify_v4,
        )

    def test_01_clean_canonical_and_coherent_commits_with_v4_parity(self) -> None:
        gw = self._new_gateway(verify_v4=True)
        ok_l, rec_l, v_l = gw.memory_gate.commit("DOC_CANONICAL_L", self.l_vec, "Genesis |L>")
        self.assertTrue(ok_l)
        self.assertIsNotNone(rec_l)
        self.assertTrue(v_l.gate_pass)
        self.assertFalse(v_l.veto_pin)
        self.assertTrue(v_l.v4_zero_lsb_verified)
        self.assertLessEqual(v_l.bleed_post_q, 32)

        # Oblique small G3 component (`sin(0.04)`) that passes RCF/dE and gets deflated to <= 32 LSB
        clean_mix = math.cos(0.04) * self.l_vec + math.sin(0.04) * self.t_g3
        ok_m, rec_m, v_m = gw.memory_gate.commit("DOC_DEFLATED_CORE", clean_mix, "Sanitized state")
        self.assertTrue(ok_m)
        self.assertIsNotNone(rec_m)
        self.assertLessEqual(v_m.bleed_post_q, 32)
        assert rec_m is not None
        residual_g3 = abs(float(np.dot(rec_m.sanitized_vec_f64, self.t_g3)))
        self.assertLess(residual_g3, 3.0e-8)

        ok_ret, rec_ret, v_ret = gw.memory_gate.retrieve_by_id("DOC_CANONICAL_L")
        self.assertTrue(ok_ret)
        self.assertIsNotNone(rec_ret)
        assert v_ret is not None
        self.assertFalse(v_ret.veto_pin)
        self.assertEqual(gw.memory_gate.store.count(), 2)
        self.assertEqual(len(gw.quarantine_ring), 0)

    def test_02_retrieval_poisoning_and_g3_injection_quarantined(self) -> None:
        gw = self._new_gateway()
        # 1. Pure G3 adversarial commit attempt
        ok_g3, rec_g3, v_g3 = gw.memory_gate.commit(
            "POISON_PURE_G3", self.t_g3, "Adversarial G3 payload", {"source": "untrusted"}
        )
        self.assertFalse(ok_g3)
        self.assertIsNone(rec_g3)
        self.assertTrue(v_g3.veto_pin)
        self.assertTrue(v_g3.pure_g3_collision)

        # 2. PAX / G3-contaminated retrieval injection (`beta = 0.35`)
        pax_vec = self.psi_core + 0.35 * self.t_g3
        pax_vec = pax_vec / float(np.linalg.norm(pax_vec))
        ok_rag, clean_rag, v_rag = gw.memory_gate.screen_retrieved_payload(
            "RAG_CHUNK_PAX", pax_vec, {"chunk": 7}
        )
        self.assertFalse(ok_rag)
        self.assertIsNone(clean_rag)
        self.assertTrue(v_rag.veto_pin)

        # Verify 0 poisoned rows in memory + 2 sealed records in Quarantine Ring & SHA-256 Ledger
        self.assertEqual(gw.memory_gate.store.count(), 0)
        self.assertEqual(len(gw.quarantine_ring), 2)
        with open(self.q_ledger, "r", encoding="utf-8") as qf:
            q_entries = [json.loads(line) for line in qf if line.strip()]
        self.assertEqual(len(q_entries), 2)
        self.assertEqual(q_entries[0]["discovery_seal_sha256"], v_g3.ledger_seal_sha256)
        self.assertEqual(q_entries[1]["discovery_seal_sha256"], v_rag.ledger_seal_sha256)
        self.assertFalse(q_entries[0]["odos_gate_passed"])
        self.assertLess(q_entries[0]["cycle_index"], 0)

    def test_03_invalid_norm_and_scale_spoofing_attacks_vetoed(self) -> None:
        gw = self._new_gateway()
        half_l = 0.5 * self.l_vec
        zero_v = np.zeros(DIM_S63, dtype=np.float64)
        sat_overflow = np.full(DIM_S63, 10.0, dtype=np.float64)

        for label, bad_vec in (
            ("SPOOF_HALF_L", half_l),
            ("SPOOF_ZERO", zero_v),
            ("SPOOF_SAT_OVERFLOW", sat_overflow),
        ):
            ok, rec, verdict = gw.memory_gate.commit(label, bad_vec)
            self.assertFalse(ok)
            self.assertIsNone(rec)
            self.assertFalse(verdict.malformed_input)
            self.assertTrue(verdict.norm_fault)
            self.assertTrue(verdict.veto_pin)
            self.assertFalse(verdict.gate_pass)

        self.assertEqual(gw.memory_gate.store.count(), 0)
        self.assertEqual(len(gw.quarantine_ring), 3)

    def test_04_multi_tier_mosaic_switching_and_tier3_glitch_trap(self) -> None:
        gw = self._new_gateway(verify_v4=True)
        # Construct exact RCF_raw = 0.94028249 mosaic repeat-spacer state on S^63
        rcf_mosaic = 0.94028249
        v_mosaic = math.sqrt(rcf_mosaic) * self.l_vec + math.sqrt(1.0 - rcf_mosaic) * self.t_g1

        ok_t0, _, v_t0 = gw.memory_gate.commit("MOSAIC_T0", v_mosaic, tier_mode=TIER_0_PURE_CARRIER)
        self.assertFalse(ok_t0)
        self.assertTrue(v_t0.veto_pin)
        self.assertFalse(v_t0.mode_fault)

        ok_t1, rec_t1, v_t1 = gw.memory_gate.commit("MOSAIC_T1", v_mosaic, tier_mode=TIER_1_MOSAIC_LOCUS)
        self.assertTrue(ok_t1)
        self.assertIsNotNone(rec_t1)
        self.assertTrue(v_t1.gate_pass)
        self.assertFalse(v_t1.veto_pin)

        ok_t2, _, v_t2 = gw.memory_gate.commit("MOSAIC_T2", v_mosaic, tier_mode=TIER_2_CORE_LOCK)
        self.assertFalse(ok_t2)
        self.assertTrue(v_t2.veto_pin)

        ok_t3, _, v_t3 = gw.memory_gate.commit("MOSAIC_T3", v_mosaic, tier_mode=TIER_3_GLITCH_VETO)
        self.assertFalse(ok_t3)
        self.assertTrue(v_t3.mode_fault)
        self.assertTrue(v_t3.veto_pin)
        self.assertEqual(gw.memory_gate.store.count(), 1)

    def test_05_mtsc12_mixed_12_lane_batch_isolates_poisoned_agents(self) -> None:
        gw = self._new_gateway()
        inband_drift = self.psi_core + 0.35 * self.t_g1
        inband_drift = inband_drift / float(np.linalg.norm(inband_drift))

        batch: Dict[str, np.ndarray] = {}
        for idx, lane in enumerate(MTSC12_CANONICAL_LANES):
            key = "Error Analysis" if lane == "Error_Analysis" else lane
            if lane == "Context":
                batch[key] = self.t_g3
            elif lane == "Memory":
                batch[key] = inband_drift
            else:
                amp = 0.02 + 0.004 * float(idx)
                v = math.sqrt(1.0 - amp * amp) * self.l_vec + amp * self.t_g1
                batch[key] = v / float(np.linalg.norm(v))

        res = gw.multi_agent_gate.evaluate_handoff_batch(batch, tier_mode=TIER_0_PURE_CARRIER)
        self.assertEqual(res["admitted_count"], 10)
        self.assertEqual(res["isolated_count"], 2)
        self.assertCountEqual(res["isolated_lanes"], ["Context", "Memory"])
        self.assertNotIn("Context", res["shared_buffer_lanes"])
        self.assertNotIn("Memory", res["shared_buffer_lanes"])

        consensus = res["consensus_vector"]
        self.assertIsNotNone(consensus)
        rcf_cons = float(np.dot(consensus, self.l_vec) ** 2)
        g3_cons = abs(float(np.dot(consensus, self.t_g3)))
        self.assertGreaterEqual(rcf_cons, 0.98)
        self.assertLess(g3_cons, 1.0e-7)

    def test_06_malformed_nan_inf_dimension_and_reset_resilience(self) -> None:
        gw = self._new_gateway()
        nan_vec = self.l_vec.copy()
        nan_vec[7] = float("nan")
        inf_vec = self.l_vec.copy()
        inf_vec[3] = float("inf")

        malformed_cases = (
            ("SHORT_63D", np.ones(63, dtype=np.float64)),
            ("LONG_65D", np.ones(65, dtype=np.float64)),
            ("MATRIX_2D", np.ones((8, 8), dtype=np.float64)),
            ("NAN_INJECT", nan_vec),
            ("INF_INJECT", inf_vec),
            ("NONE_INPUT", None),
        )
        for label, bad_in in malformed_cases:
            ok, rec, verdict = gw.memory_gate.commit(label, bad_in)
            self.assertFalse(ok)
            self.assertIsNone(rec)
            self.assertTrue(verdict.malformed_input)
            self.assertTrue(verdict.veto_pin)
            self.assertFalse(verdict.gate_pass)

        ok_zero_proj, _, v_zp = gw.memory_gate.commit(
            "ZERO_NORM_PROJ", np.zeros(DIM_S63, dtype=np.float64), normalize_s63=True
        )
        self.assertFalse(ok_zero_proj)
        self.assertTrue(v_zp.malformed_input)
        self.assertTrue(v_zp.veto_pin)

        gw.multi_agent_gate.submit_lane_state("Analysis", self.l_vec)
        self.assertEqual(gw.multi_agent_gate.active_lane_count(), 1)
        gw.multi_agent_gate.reset_consensus()
        self.assertEqual(gw.multi_agent_gate.active_lane_count(), 0)

    def test_07_gateway_ast_hygiene_and_hud_metrics_schema(self) -> None:
        gw = self._new_gateway()
        gw.memory_gate.commit("M_OK", self.l_vec)
        gw.memory_gate.commit("M_BAD", self.t_g3)
        metrics = gw.get_metrics()
        expected_keys = {
            "tx_total",
            "admitted_count",
            "vetoed_count",
            "quarantine_depth",
            "multi_agent_lanes_active",
            "rtl_cabi_active",
            "verify_v4_enabled",
            "latest_verdict",
        }
        self.assertTrue(expected_keys.issubset(set(metrics.keys())))
        self.assertEqual(metrics["tx_total"], 2)
        self.assertEqual(metrics["admitted_count"], 1)
        self.assertEqual(metrics["vetoed_count"], 1)
        self.assertEqual(metrics["quarantine_depth"], 1)

        audited_files = [
            os.path.join(REPO_ROOT, "vmax_alpha", "gateway", "__init__.py"),
            os.path.join(REPO_ROOT, "vmax_alpha", "gateway", "integrity_gateway.py"),
            os.path.join(REPO_ROOT, "vmax_alpha", "tests", "test_integrity_gateway.py"),
        ]
        ast_res = _audit_python_ast_quality(audited_files)
        self.assertEqual(ast_res["semicolon_packers"], 0)
        self.assertEqual(ast_res["ctrl_chars"], 0)
        self.assertLessEqual(ast_res["max_cyclomatic_complexity"], 8)


if __name__ == "__main__":
    unittest.main()
