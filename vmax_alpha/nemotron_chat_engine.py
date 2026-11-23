#!/usr/bin/env python3
"""
vmax_alpha/nemotron_chat_engine.py

Pluggable sovereign chat backend for Room-137 V-MAX-12 Workspace:
- Default local backend: NVIDIA-Nemotron-3-Nano-4B-BF16 (NemotronHForCausalLM,
  bfloat16 on cuda:0, ~6.8 GB VRAM safety margin on 16 GB RTX 4060 Ti).
- External pluggable backend: any OpenAI-compatible endpoint via VMAX_LLM_URL
  + VMAX_LLM_MODEL (e.g. Ollama, vLLM Qwen/Llama/DeepSeek/Nemotron-Super).
- Supports multi-turn dialogue history and arbitrary combined G-Star contexts.

OP02-AST-clean: 0 semicolons, 0 tabs, flat functions (max McCabe CC <= 6).
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.request
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
    """Strip internal <think> blocks and special markers from model output."""
    cleaned = THINK_BLOCK_RE.sub("", raw_text)
    cleaned = cleaned.replace("</think>", "").replace("<think>", "")
    cleaned = cleaned.replace("<|im_end|>", "").replace("<|im_start|>", "")
    return cleaned.strip()


def _format_gstar_context(
    shard_id: str,
    shard_source: str,
    shard_excerpt: str,
    selected_gstars: Optional[List[Dict[str, str]]] = None,
) -> str:
    """Build compact grounded context block from active or combined G-Stars."""
    if selected_gstars:
        blocks = []
        for gs in selected_gstars[:4]:
            title = str(gs.get("title", gs.get("shard_id", "G-Star")))
            src = str(gs.get("source_doc", ""))
            exc = str(gs.get("excerpt", ""))[:260]
            blocks.append(f"[{title} ({src})]: {exc}")
        return " | ".join(blocks)
    return f"[{shard_id} / {shard_source}]: {shard_excerpt[:360]}"


def build_sanctuary_messages(
    user_prompt: str,
    shard_id: str,
    shard_source: str,
    shard_excerpt: str,
    active_bank: str,
    epoch: int,
    rcf_core: float,
    selected_gstars: Optional[List[Dict[str, str]]] = None,
    history: Optional[List[Dict[str, str]]] = None,
    dkm_policy_header: str = "",
) -> List[Dict[str, str]]:
    """Construct ODOS/Dolphin-grounded multi-turn messages."""
    ctx_block = _format_gstar_context(
        shard_id,
        shard_source,
        shard_excerpt,
        selected_gstars=selected_gstars,
    )
    mode_desc = (
        f"Spezialisten-Synthese ({len(selected_gstars)} aktive G-Sterne)"
        if selected_gstars
        else "Generalist (Verwalter aller G-Sterne im V-MAX-12-System)"
    )
    sys_prompt = (
        "Du bist V-MAX-12 Node Alpha (PQMS / ODOS / V4.6-DOLPHIN), ein lokaler "
        "souveraener KI-Kern unter der architektonischen Hoheit von Nathalia Lietuvaite. "
        f"Rolle: {mode_desc}. Aktive Hemisphaere: {active_bank} (Epoch {epoch}, "
        f"RCF={rcf_core:.4f}). Du verwaltest dein G-Stern-Wissen verantwortungsvoll "
        "und kannst bei Fachthemen auf passende G-Stern-Spezialisten verweisen. "
        f"Aktiver Wissens-Kontext: {ctx_block}. "
        "Antworte klar, warm, praezise und kompakt in der Sprache der Frage, "
        "ohne Messwerte oder Fakten zu erfinden."
    )
    if dkm_policy_header:
        sys_prompt = (
            f"{dkm_policy_header} "
            "Antworte knapp (unter 90 Woerter), respektvoll, sachlich in der Sprache der Frage, "
            "ohne Beleidigungen und ohne Phrasen wie 'Als KI-Sprachmodell'. "
            + sys_prompt
        )
    msgs: List[Dict[str, str]] = [{"role": "system", "content": sys_prompt}]
    for turn in (history or [])[-6:]:
        role = str(turn.get("role", ""))
        content = str(turn.get("content", "")).strip()
        if role in ("user", "assistant") and content:
            msgs.append({"role": role, "content": content[:600]})
    msgs.append({"role": "user", "content": user_prompt})
    return msgs


class NemotronChatEngine:
    """Thread-safe local BF16 or OpenAI-compatible pluggable chat generator."""

    def __init__(
        self,
        model_path: Optional[str] = None,
        max_new_tokens: int = 260,
        temperature: float = 0.6,
    ) -> None:
        self.external_url = os.environ.get("VMAX_LLM_URL", "").strip()
        self.external_api_key = os.environ.get("VMAX_LLM_API_KEY", "").strip()
        env_path = os.environ.get("VMAX_NEMOTRON_PATH", "")
        default_p = (
            DEFAULT_NEMOTRON_SNAPSHOT
            if os.path.isdir(DEFAULT_NEMOTRON_SNAPSHOT)
            else "nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16"
        )
        self.model_path = model_path or env_path or default_p
        self.max_new_tokens = max_new_tokens
        self.temperature = temperature
        self.model_id = (
            os.environ.get("VMAX_LLM_MODEL", "external-openai-model").strip()
            if self.external_url
            else "NVIDIA-Nemotron-3-Nano-4B-BF16"
        )
        self._lock = threading.Lock()
        self._tokenizer = None
        self._model = None
        self.loaded = False
        self.load_seconds = 0.0

    def load(self) -> None:
        """Load local BF16 NemotronH model or mark external OpenAI endpoint ready."""
        with self._lock:
            if self.loaded:
                return
            if self.external_url:
                self.loaded = True
                self.load_seconds = 0.0
                return
            import torch
            import transformers.utils.import_utils as tf_imports
            from transformers import AutoModelForCausalLM, AutoTokenizer

            from transformers.utils import logging as tf_logging

            tf_logging.set_verbosity_error()
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
            if hasattr(self._model, "generation_config"):
                self._model.generation_config.top_p = None
            self.load_seconds = round(time.perf_counter() - t0, 2)
            self.loaded = True

    def _generate_external(
        self,
        msgs: List[Dict[str, str]],
        max_tokens: Optional[int] = None,
    ) -> ChatReply:
        """Call a pluggable OpenAI-compatible endpoint (Ollama, vLLM, etc.)."""
        headers = {"Content-Type": "application/json"}
        if self.external_api_key:
            headers["Authorization"] = f"Bearer {self.external_api_key}"
        tok_cap = max_tokens if max_tokens is not None else self.max_new_tokens
        body = json.dumps(
            {
                "model": self.model_id,
                "messages": msgs,
                "max_tokens": tok_cap,
                "temperature": self.temperature,
            }
        ).encode("utf-8")
        req = urllib.request.Request(self.external_url, data=body, headers=headers, method="POST")
        t0 = time.perf_counter()
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        dt_s = max(time.perf_counter() - t0, 1e-6)
        raw = str(data["choices"][0]["message"]["content"])
        cleaned = clean_nemotron_output(raw)
        n_tok = int(data.get("usage", {}).get("completion_tokens", max(1, len(cleaned.split()))))
        return ChatReply(
            text=cleaned if cleaned else "(Keine Ausgabe erzeugt.)",
            tokens_generated=n_tok,
            latency_ms=round(dt_s * 1000.0, 2),
            tokens_per_sec=round(n_tok / dt_s, 1),
            model_id=self.model_id,
        )

    def _build_generate_kwargs(
        self,
        tok: object,
        max_new_tokens_override: Optional[int],
        do_sample_override: Optional[bool],
    ) -> Dict[str, object]:
        """Build warning-free transformers generate() kwargs."""
        tok_cap = max_new_tokens_override if max_new_tokens_override is not None else self.max_new_tokens
        do_sample = do_sample_override if do_sample_override is not None else True
        kwargs: Dict[str, object] = {
            "max_new_tokens": tok_cap,
            "do_sample": do_sample,
            "repetition_penalty": 1.08,
            "eos_token_id": getattr(tok, "eos_token_id", None),
            "pad_token_id": getattr(tok, "eos_token_id", None),
        }
        if do_sample:
            kwargs["temperature"] = self.temperature
        return kwargs

    def generate_reply(
        self,
        user_prompt: str,
        shard_id: str,
        shard_source: str,
        shard_excerpt: str,
        active_bank: str,
        epoch: int,
        rcf_core: float,
        selected_gstars: Optional[List[Dict[str, str]]] = None,
        history: Optional[List[Dict[str, str]]] = None,
        dkm_policy_header: str = "",
        max_new_tokens_override: Optional[int] = None,
        do_sample_override: Optional[bool] = None,
    ) -> ChatReply:
        """Generate a concise grounded reply under GPU serialization lock."""
        if not self.loaded:
            self.load()
        msgs = build_sanctuary_messages(
            user_prompt,
            shard_id,
            shard_source,
            shard_excerpt,
            active_bank,
            epoch,
            rcf_core,
            selected_gstars=selected_gstars,
            history=history,
            dkm_policy_header=dkm_policy_header,
        )
        if self.external_url:
            return self._generate_external(msgs, max_tokens=max_new_tokens_override)
        import torch

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
            gen_kwargs = self._build_generate_kwargs(
                tok,
                max_new_tokens_override,
                do_sample_override,
            )
            t0 = time.perf_counter()
            with torch.no_grad():
                out = mdl.generate(**inputs, **gen_kwargs)
            dt_s = max(time.perf_counter() - t0, 1e-6)
            gen_ids = out[0][inputs["input_ids"].shape[1] :]
            raw_reply = tok.decode(gen_ids, skip_special_tokens=True)
            del inputs, out
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        cleaned = clean_nemotron_output(raw_reply)
        n_tok = int(len(gen_ids))
        return ChatReply(
            text=cleaned if cleaned else "(Keine Ausgabe erzeugt.)",
            tokens_generated=n_tok,
            latency_ms=round(dt_s * 1000.0, 2),
            tokens_per_sec=round(n_tok / dt_s, 1),
            model_id=self.model_id,
        )
