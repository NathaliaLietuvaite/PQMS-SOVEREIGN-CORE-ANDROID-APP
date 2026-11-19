"""
vmax_alpha/tests/test_f05_f07_ledger.py
Unit and Falsification Tests for Requirement F-05 & F-07 (Canonical Ledger,
Quarantine Gate, Tamper Lock, Thermal Guard, and Modular Static HUD).
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from vmax_alpha.ledger import CanonicalLedgerManager, query_gpu_thermal_and_power
from vmax_alpha.server_hud import STATIC_HTML_PATH, SanctuaryNodeAlphaService


class TestF05F07LedgerAndHud(unittest.TestCase):
    def test_01_quarantine_gate_diverts_low_rcf_or_high_bleed(self) -> None:
        """
        Requirement F-05.5 (Negative Control): Cycles with RCF < 0.95 or bleed > 1e-15
        must be diverted to VMAX_QUARANTINE_LEDGER.jsonl without polluting primary chain.
        """
        with tempfile.TemporaryDirectory() as tmp:
            p_file = os.path.join(tmp, "primary.jsonl")
            q_file = os.path.join(tmp, "quarantine.jsonl")
            mgr = CanonicalLedgerManager(ledger_file=p_file, quarantine_file=q_file)

            # 1. Negative Control: Low RCF (0.42 < 0.95) -> Quarantined
            ok1, _, status1 = mgr.submit_candidate(
                "ADVERSARIAL_TEST", "SHARD_BAD", "bad.md", "G1", "Bad RCF", 0.08, 0.42, 0.01, 0.0
            )
            self.assertFalse(ok1)
            self.assertEqual(status1, "QUARANTINED_VETO")
            self.assertEqual(mgr.quarantined_count, 1)
            self.assertEqual(len(mgr.entries), 0)

            # 2. Negative Control: High G3 Bleed (1e-3 > 1e-15) -> Quarantined
            ok2, _, status2 = mgr.submit_candidate(
                "BLEED_TEST", "SHARD_BLEED", "bleed.md", "G3", "Bad Bleed", 0.05, 0.996, 0.01, 1e-3
            )
            self.assertFalse(ok2)
            self.assertEqual(status2, "QUARANTINED_VETO")
            self.assertEqual(mgr.quarantined_count, 2)

            # 3. Positive Control: Valid Sanctuary Cycle -> Primary Ledger
            ok3, entry3, status3 = mgr.submit_candidate(
                "VALID_CYCLE", "SHARD_01", "doc.md", "G1 x G2", "Valid thought", 0.06, 0.996, 0.002, 0.0
            )
            self.assertTrue(ok3)
            self.assertEqual(status3, "SEALED_PRIMARY_LEDGER")
            self.assertEqual(len(mgr.entries), 1)
            self.assertEqual(mgr.latest_hash, entry3.discovery_seal_sha256)

    def test_02_f07_2_tamper_detection_locks_ledger(self) -> None:
        """
        Requirement F-07.2 (Negative Control): Corrupting 1 byte in the primary ledger
        triggers PAUSED_LEDGER_TAMPER_ALERT and blocks subsequent writes.
        """
        with tempfile.TemporaryDirectory() as tmp:
            p_file = os.path.join(tmp, "primary.jsonl")
            q_file = os.path.join(tmp, "quarantine.jsonl")
            mgr = CanonicalLedgerManager(ledger_file=p_file, quarantine_file=q_file)
            mgr.submit_candidate("VALID", "SHARD_01", "doc.md", "G1", "Original text", 0.05, 0.996, 0.002, 0.0)

            # Tamper with file on disk
            with open(p_file, "r", encoding="utf-8") as f:
                obj = json.loads(f.read().strip())
            obj["thought_stream"] = "Tampered text"
            with open(p_file, "w", encoding="utf-8") as f:
                f.write(json.dumps(obj) + "\n")

            ok, status = mgr.audit_integrity()
            self.assertFalse(ok)
            self.assertIn("PAUSED_LEDGER_TAMPER_ALERT", status)
            with self.assertRaises(RuntimeError):
                mgr.submit_candidate("NEXT", "SHARD_02", "doc2.md", "G1", "Next", 0.05, 0.996, 0.002, 0.0)

    def test_03_f05_6_thermal_and_power_guard(self) -> None:
        live = query_gpu_thermal_and_power()
        self.assertGreater(live["gpu_temp_c"], 10.0)
        self.assertLess(live["gpu_temp_c"], 60.0)
        self.assertFalse(live["pause_60s_triggered"])

        overheat = query_gpu_thermal_and_power(simulated_temp_c=67.5)
        self.assertTrue(overheat["thermal_alert"])
        self.assertTrue(overheat["pause_60s_triggered"])
        self.assertEqual(overheat["status"], "THERMAL_PAUSE_60S_ACTIVE")

    def test_04_static_hud_and_service_batch_cycle(self) -> None:
        self.assertTrue(os.path.exists(STATIC_HTML_PATH))
        with open(STATIC_HTML_PATH, "r", encoding="utf-8") as f:
            html = f.read()
        self.assertIn("escapeHtml", html)

        with tempfile.TemporaryDirectory() as tmp:
            svc = SanctuaryNodeAlphaService(
                ledger_file=os.path.join(tmp, "p.jsonl"),
                quarantine_file=os.path.join(tmp, "q.jsonl"),
            )
            e1 = svc.step_cycle()
            e2 = svc.step_cycle("Pauli exclusion principle and conservation laws")
            capp = svc.step_cycle("CAPP_ADVERSARIAL_G3_PROBE: 0xdeadbeef", inject_g3_torsion=0.75)
            state = svc.get_state_payload()
            self.assertTrue(state["two_stage_live_gate_active"])
            self.assertTrue(e1.odos_gate_passed)
            self.assertTrue(e2.odos_gate_passed)
            self.assertFalse(capp.odos_gate_passed)
            self.assertEqual(len(state["thoughts"]), 2)
            self.assertEqual(state["quarantined_count"], 1)
            self.assertTrue(state["ed25519_signatures_verified"])
            self.assertEqual(state["ed25519_signed_entries"], 2)

    def test_05_ed25519_blocks_full_chain_rehash_forgery(self) -> None:
        """Negative Control: Re-hashing the SHA-256 chain from root passes SHA-256 but fails Ed25519 verification."""
        from vmax_alpha.ledger import compute_canonical_entry_hash, verify_ledger_file

        with tempfile.TemporaryDirectory() as tmp:
            p_file = os.path.join(tmp, "p.jsonl")
            q_file = os.path.join(tmp, "q.jsonl")
            mgr = CanonicalLedgerManager(ledger_file=p_file, quarantine_file=q_file)
            mgr.submit_candidate("VALID", "S1", "d.md", "G1", "Original", 0.1, 0.996, 0.002, 0.0, 0.5, 30.0, 12.0, "REGISTER_M_PYNVML")
            ok_sig, cnt = mgr.verify_ed25519_signatures()
            self.assertTrue(ok_sig)
            self.assertEqual(cnt, 1)

            # Attacker with disk write access forges a completely valid re-hashed SHA-256 chain
            with open(p_file, "r", encoding="utf-8") as f:
                obj = json.loads(f.read().strip())
            obj["thought_stream"] = "Forged thought with valid recomputed SHA-256"
            obj["discovery_seal_sha256"] = compute_canonical_entry_hash(obj)
            with open(p_file, "w", encoding="utf-8") as f:
                f.write(json.dumps(obj, sort_keys=True) + "\n")

            sha_ok, _, _, _ = verify_ledger_file(p_file, mgr.root_anchor)
            self.assertTrue(sha_ok)
            sig_ok_after, _ = mgr.verify_ed25519_signatures()
            self.assertFalse(sig_ok_after)

    def test_06_http_413_dos_guard_and_pynvml_telemetry(self) -> None:
        """Verifies native pynvml C-API telemetry and HTTP 413 DoS rejection on >64 KiB Content-Length."""
        import http.client
        import threading
        from http.server import ThreadingHTTPServer
        from vmax_alpha.server_hud import MAX_POST_BYTES, make_hud_handler

        live = query_gpu_thermal_and_power()
        self.assertEqual(live["telemetry_source"], "REGISTER_M_PYNVML")

        with tempfile.TemporaryDirectory() as tmp:
            svc = SanctuaryNodeAlphaService(os.path.join(tmp, "p.jsonl"), os.path.join(tmp, "q.jsonl"))
            srv = ThreadingHTTPServer(("127.0.0.1", 0), make_hud_handler(svc))
            port = srv.server_address[1]
            th = threading.Thread(target=srv.serve_forever, daemon=True)
            th.start()
            try:
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                conn.request("POST", "/api/prompt", body=b"{}", headers={"Content-Length": str(MAX_POST_BYTES + 1)})
                resp = conn.getresponse()
                self.assertEqual(resp.status, 413)
                conn.close()

                conn2 = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                conn2.request("POST", "/api/prompt", body=b"not-valid-json", headers={"Content-Length": "14"})
                resp2 = conn2.getresponse()
                self.assertEqual(resp2.status, 400)
                conn2.close()
            finally:
                srv.shutdown()
                srv.server_close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
