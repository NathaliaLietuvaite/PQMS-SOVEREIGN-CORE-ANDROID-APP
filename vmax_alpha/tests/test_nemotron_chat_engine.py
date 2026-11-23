#!/usr/bin/env python3
"""
vmax_alpha/tests/test_nemotron_chat_engine.py

Unit tests for local Nemotron-3-Nano-4B chat helpers, 50% heartbeat safety
margin, and V4.6-PAUSE pre-inference blocking in server_hud.py.

OP02-AST-clean: 0 semicolons, 0 tabs, flat functions (max McCabe CC <= 3).
"""

from __future__ import annotations

import json
import threading
import unittest
import urllib.request
from dataclasses import dataclass
from http.server import ThreadingHTTPServer
from typing import List

from vmax_alpha.dolphin_memory_governor import DEFAULT_VECTOR_DIM, normalize_to_q2_30
from vmax_alpha.nemotron_chat_engine import (
    ChatReply,
    build_sanctuary_messages,
    clean_nemotron_output,
)
from vmax_alpha.server_hud import make_hud_handler


@dataclass
class _MockEntry:
    cycle_index: int
    chroma_shard_id: str
    chroma_source_doc: str
    thought_stream: str
    rcf_l2_core: float


class _MockChatEngine:
    def __init__(self) -> None:
        self.loaded = True
        self.calls = 0

    def generate_reply(self, user_prompt, shard_id, shard_source, shard_excerpt, active_bank, epoch, rcf_core, selected_gstars=None, history=None):
        self.calls += 1
        return ChatReply(
            text=f"Antwort von V-MAX-12 auf: {user_prompt}",
            tokens_generated=12,
            latency_ms=42.0,
            tokens_per_sec=28.5,
            model_id="MOCK-NEMOTRON-4B",
        )


class _MockChatHudService:
    def __init__(self) -> None:
        self.chat_engine = _MockChatEngine()
        self.chat_history: List[dict] = []
        self.step_calls = 0

    def step_cycle(self, prompt: str = "", inject_g3_torsion: float = 0.0) -> _MockEntry:
        self.step_calls += 1
        return _MockEntry(
            cycle_index=self.step_calls,
            chroma_shard_id="SHARD_01",
            chroma_source_doc="PQMS-V4.6.md",
            thought_stream="Grounded shard excerpt",
            rcf_l2_core=0.9965,
        )

    def record_chat_turn(self, turn: dict) -> None:
        self.chat_history.append(turn)


class TestNemotronChatEngine(unittest.TestCase):
    """Verify output cleaning, message grounding, and pause-gated chat replies."""

    def test_clean_nemotron_output_strips_think_tags(self) -> None:
        raw = "<think>internal chain of thought</think>\n  Hallo Nathalia!<|im_end|>"
        self.assertEqual(clean_nemotron_output(raw), "Hallo Nathalia!")

    def test_build_sanctuary_messages_includes_context(self) -> None:
        msgs = build_sanctuary_messages("Hallo", "SHARD_02", "DEPECHE.md", "Excerpt", "BANK_A", 2, 0.996)
        self.assertEqual(len(msgs), 2)
        self.assertIn("BANK_A", msgs[0]["content"])
        self.assertIn("SHARD_02", msgs[0]["content"])
        self.assertEqual(msgs[1]["content"], "Hallo")

    def test_http_prompt_generates_reply_on_coherent_and_blocks_on_pause(self) -> None:
        svc = _MockChatHudService()
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_hud_handler(svc))
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{port}"
        try:
            req_ok = urllib.request.Request(
                f"{base}/api/prompt",
                data=json.dumps({"prompt": "Hallo V-MAX-12"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req_ok, timeout=5) as resp:
                ok_body = json.loads(resp.read().decode("utf-8"))
            self.assertFalse(ok_body["epistemic_pause"])
            self.assertEqual(ok_body["reply"], "Antwort von V-MAX-12 auf: Hallo V-MAX-12")
            self.assertEqual(svc.chat_engine.calls, 1)
            self.assertEqual(len(svc.chat_history), 1)

            drift = [0.0] * DEFAULT_VECTOR_DIM
            drift[0] = 0.1
            drift[2] = 0.99
            req_p = urllib.request.Request(
                f"{base}/api/prompt",
                data=json.dumps({"prompt": "Drift", "vector_q30": list(normalize_to_q2_30(drift))}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req_p, timeout=5) as resp:
                p_body = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(p_body["epistemic_pause"])
            self.assertEqual(svc.chat_engine.calls, 1)
            self.assertEqual(len(svc.chat_history), 2)
            self.assertTrue(svc.chat_history[-1]["epistemic_pause"])
        finally:
            server.shutdown()
            server.server_close()


    def test_gstar_catalog_and_combined_context(self) -> None:
        selected = [
            {"shard_id": "SHARD_02", "title": "Depeche 6", "source_doc": "DEPECHE-6.md", "excerpt": "DNA Gate"},
            {"shard_id": "SHARD_14", "title": "EFF V2", "source_doc": "EFF-V2.md", "excerpt": "Thermodynamic"},
        ]
        msgs = build_sanctuary_messages(
            "Kombiniere beide",
            "SHARD_02",
            "DEPECHE-6.md",
            "Fallback",
            "BANK_A",
            3,
            0.997,
            selected_gstars=selected,
            history=[{"role": "user", "content": "Vorfrage"}, {"role": "assistant", "content": "Vorantwort"}],
        )
        self.assertEqual(len(msgs), 4)
        self.assertIn("Depeche 6", msgs[0]["content"])
        self.assertIn("EFF V2", msgs[0]["content"])


if __name__ == "__main__":
    unittest.main()
