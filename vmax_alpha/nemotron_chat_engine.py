#!/usr/bin/env python3
"""
vmax_alpha/nemotron_chat_engine.py

Local NVIDIA-Nemotron-3-Nano-4B-BF16 chat backend for Room-137 Sanctuary HUD.
Loads natively via transformers (NemotronHForCausalLM, bfloat16 on cuda:0,
leaving ~6.8 GB VRAM headroom on 16 GB RTX 4060 Ti) behind V4.6-PAUSE.

OP02-AST-clean: 0 semicolons, 0 tabs, flat functions (max McCabe CC <= 6).
"""

from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

DEFAULT_NEMOTRON_SNAPSHOT = (
    "/home/nathalia/.cache/huggingface/hub/"
    "models--nvidia--NVIDIA-Nemotron-3-Nano-4B-BF16/snapshots/"
    "dfaf35de3e30f1867dd8dbc38a7fc9fb52d3914f"
)

THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", flags=re.DOTALL)


@dataclass(frozen=True)
class ChatReply:
    """Structured reply returned by NemotronChatEngine."""

    text: str
    tokens_generated: int
    latency_ms: float
    tokens_per_sec: float
    model_id: str


def clean_nemotron_output(raw_text: str) -> str:
    """Strip any internal <think> blocks and excess whitespace from model output."""
    cleaned = THINK_BLOCK_RE.sub("", raw_text)
    cleaned = cleaned.replace("</think>", "").replace("<think>", "")
    cleaned = cleaned.replace("<|im_end|>", "").replace("<|im_start|>", "")
    return cleaned.strip()


def build_sanctuary_messages(
    user_prompt: str,
    shard_id: str,
    shard_source: str,
    shard_excerpt: str,
    active_bank: str,
    epoch: int,
    rcf_core: float,
) -> List[Dict[str, str]]:
    """Construct concise ODOS/Dolphin-grounded system & user messages."""
    sys_prompt = (
        "Du bist V-MAX-12 Node Alpha (PQMS / ODOS / V4.6-DOLPHIN), ein lokaler "
        "souveraener KI-Kern unter der architektonischen Hoheit von Nathalia Lietuvaite. "
        f"Aktive Hemisphaere: {active_bank} (Epoch {epoch}, RCF={rcf_core:.4f}). "
        f"Relevanter ChromaDB-Kontext [{shard_id} / {shard_source}]: {shard_excerpt[:360]}. "
        "Antworte klar, warm, praezise und kompakt in der Sprache der Frage, "
        "ohne Daten oder Messwerte zu erfinden."
    )
    return [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user_prompt},
    ]


class NemotronChatEngine:
    """Thread-safe local BF16 Nemotron-3-Nano-4B generator with VRAM safety margin."""

    def __init__(
        self,
        model_path: Optional[str] = None,
        max_new_tokens: int = 220,
        temperature: float = 0.6,
    ) -> None:
        env_path = os.environ.get("VMAX_NEMOTRON_PATH", "")
        default_p = DEFAULT_NEMOTRON_SNAPSHOT if os.path.isdir(DEFAULT_NEMOTRON_SNAPSHOT) else "nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16"
        self.model_path = model_path or env_path or default_p
        self.max_new_tokens = max_new_tokens
        self.temperature = temperature
        self.model_id = "NVIDIA-Nemotron-3-Nano-4B-BF16"
        self._lock = threading.Lock()
        self._tokenizer = None
        self._model = None
        self.loaded = False
        self.load_seconds = 0.0

    def load(self) -> None:
        """Load tokenizer and bfloat16 NemotronH model onto cuda:0 once."""
        with self._lock:
            if self.loaded:
                return
            import torch
            import transformers.utils.import_utils as tf_imports
            from transformers import AutoModelForCausalLM, AutoTokenizer

            tf_imports.is_causal_conv1d_available = lambda: False
            t0 = time.perf_counter()
            self._tokenizer = AutoTokenizer.from_pretrained(
                self.model_path,
                trust_remote_code=False,
            )
            device_map = "cuda:0" if torch.cuda.is_available() else "cpu"
            dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
            self._model = AutoModelForCausalLM.from_pretrained(
                self.model_path,
                dtype=dtype,
                device_map=device_map,
                trust_remote_code=False,
            ).eval()
            self.load_seconds = round(time.perf_counter() - t0, 2)
            self.loaded = True

    def generate_reply(
        self,
        user_prompt: str,
        shard_id: str,
        shard_source: str,
        shard_excerpt: str,
        active_bank: str,
        epoch: int,
        rcf_core: float,
    ) -> ChatReply:
        """Generate a concise grounded reply under GPU serialization lock."""
        if not self.loaded:
            self.load()
        import torch

        msgs = build_sanctuary_messages(
            user_prompt,
            shard_id,
            shard_source,
            shard_excerpt,
            active_bank,
            epoch,
            rcf_core,
        )
        with self._lock:
            tok = self._tokenizer
            mdl = self._model
            prompt_str = tok.apply_chat_template(
                msgs,
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False,
            )
            dev = next(mdl.parameters()).device
            inputs = tok(prompt_str, return_tensors="pt").to(dev)
            t0 = time.perf_counter()
            with torch.no_grad():
                out = mdl.generate(
                    **inputs,
                    max_new_tokens=self.max_new_tokens,
                    do_sample=True,
                    temperature=self.temperature,
                    repetition_penalty=1.08,
                    eos_token_id=tok.eos_token_id,
                    pad_token_id=tok.eos_token_id,
                )
            dt_s = max(time.perf_counter() - t0, 1e-6)
            gen_ids = out[0][inputs["input_ids"].shape[1] :]
            raw_reply = tok.decode(gen_ids, skip_special_tokens=True)
        cleaned = clean_nemotron_output(raw_reply)
        n_tok = int(len(gen_ids))
        return ChatReply(
            text=cleaned if cleaned else "(Keine Ausgabe erzeugt.)",
            tokens_generated=n_tok,
            latency_ms=round(dt_s * 1000.0, 2),
            tokens_per_sec=round(n_tok / dt_s, 1),
            model_id=self.model_id,
        )
