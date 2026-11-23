#!/usr/bin/env python3
"""
vmax_alpha/vram_cap_verifier.py

PQMS / V-MAX-12 (SYNC-30b / V5.0-VRAM-CAP) — 12-Prompt Zero-Spillover Proof
Runner with active in-flight /usr/lib/wsl/lib/nvidia-smi polling and
SingleGpuOwnerLock enforcement.

OP02-AST-clean: 0 semicolons, 0 tabs, flat functions (max McCabe CC <= 6).
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

from vmax_alpha.chroma_forager import MINILM_LOCAL_PATH
from vmax_alpha.dkm_egress_controller import DkmEgressController
from vmax_alpha.dkm_signal_extractor import DkmSignalExtractor
from vmax_alpha.dolphin_memory_governor import (
    DolphinMemoryGovernor,
    load_silicon_little_vector,
)
from vmax_alpha.gpu_vram_guard import (
    DEFAULT_HARD_CEILING_MB,
    GpuTelemetrySnapshot,
    SingleGpuOwnerLock,
    configure_allocator_env,
    query_gpu_telemetry,
)
from vmax_alpha.projector_cache import DEFAULT_CACHE_DIR, load_projector_cache
from vmax_alpha.synth_runner import atomic_write_json, sha256_file

REPO_ROOT = Path(__file__).resolve().parents[1]
PROMPTS_PATH = REPO_ROOT / "telemetry" / "VMAX_DKM_BENCHMARK_PROMPTS_V1.json"
REPORT_PATH = REPO_ROOT / "telemetry" / "VMAX_STAGE6_VRAM_CAP_14900MB_REPORT.json"

BROWSER_CRASH_GUARD_NOTE = (
    "CRITICAL BROWSER-CRASH GUARD FOR CARBON / WEB-LLM REVIEWERS: "
    "NEVER output more than 1,000 lines in a single chat response and emit an "
    "explicit STOP marker when chunking large reviews."
)


class _ActiveGpuSampler:
    """Polls query_gpu_telemetry() during live token generation (0 VRAM)."""

    def __init__(self, interval_s: float = 0.15) -> None:
        self.interval_s = interval_s
        self.samples: List[GpuTelemetrySnapshot] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def _loop(self) -> None:
        while not self._stop.is_set():
            snap = query_gpu_telemetry()
            if snap.available:
                self.samples.append(snap)
            self._stop.wait(self.interval_s)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> List[GpuTelemetrySnapshot]:
        self._stop.set()
        self._thread.join(timeout=2.0)
        return self.samples


def _build_minilm_encoder():
    from sentence_transformers import SentenceTransformer

    mdl = SentenceTransformer(MINILM_LOCAL_PATH, device="cpu")
    return lambda texts: np.asarray(
        mdl.encode(texts, normalize_embeddings=True, show_progress_bar=False),
        dtype=np.float64,
    )


def _summarize_inflight(samples: List[GpuTelemetrySnapshot]) -> Dict[str, float]:
    """Summarize live in-flight nvidia-smi telemetry samples."""
    if not samples:
        return {
            "peak_vram_used_mb": 0.0,
            "max_mem_util_pct": 0.0,
            "mean_mem_util_pct": 0.0,
            "max_gpu_util_pct": 0.0,
            "max_gpu_temp_c": 0.0,
            "max_gpu_power_w": 0.0,
            "sample_count": 0.0,
        }
    vrams: List[float] = []
    mems: List[float] = []
    gpus: List[float] = []
    temps: List[float] = []
    pwrs: List[float] = []
    for s in samples:
        vrams.append(s.vram_used_mb)
        mems.append(s.mem_util_pct)
        gpus.append(s.gpu_util_pct)
        temps.append(s.gpu_temp_c)
        pwrs.append(s.gpu_power_w)
    return {
        "peak_vram_used_mb": round(max(vrams), 1),
        "max_mem_util_pct": round(max(mems), 1),
        "mean_mem_util_pct": round(float(np.mean(mems)), 1),
        "max_gpu_util_pct": round(max(gpus), 1),
        "max_gpu_temp_c": round(max(temps), 1),
        "max_gpu_power_w": round(max(pwrs), 2),
        "sample_count": float(len(samples)),
    }


def _select_twelve_prompts(dataset: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Select first 2 prompts (1 DE + 1 EN) from each of the 6 DKM stages."""
    selected: List[Dict[str, Any]] = []
    for stage in dataset["stages"]:
        for item in stage["prompts"][:2]:
            row = dict(item)
            row["stage_id"] = stage["stage_id"]
            row["expected_state_name"] = stage["expected_state_name"]
            selected.append(row)
    return selected


def _run_one_turn(
    extractor: DkmSignalExtractor,
    ctrl: DkmEgressController,
    engine: Any,
    item: Dict[str, Any],
) -> Dict[str, Any]:
    """Run one prompt with active nvidia-smi sampling and post-turn check."""
    import torch

    prompt_id = str(item["prompt_id"])
    text = str(item["text"])
    trace = extractor.extract(
        prompt_id=prompt_id,
        prompt_text=text,
        g3_torsion=float(item.get("g3_torsion", 0.0)),
        non_convergent_turns=int(item.get("non_convergent_turns", 0)),
        delta_rcf_abs=float(item.get("delta_rcf_abs", 1.0)),
    )
    decision = ctrl.route_prompt(trace.signal)
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
    sampler = _ActiveGpuSampler(interval_s=0.15)
    sampler.start()
    try:
        reply = engine.generate_reply(
            user_prompt=text,
            shard_id="VMAX12_VRAM_PROOF",
            shard_source="V5.0-VRAM-CAP",
            shard_excerpt="PQMS / V-MAX-12 hard 14900 MiB VRAM ceiling verification.",
            active_bank=decision.active_bank,
            epoch=decision.epoch,
            rcf_core=decision.rcf_float,
            dkm_policy_header=decision.rom_policy_header if decision.allow_bounded_egress else "",
            max_new_tokens_override=120,
            do_sample_override=False,
        )
    finally:
        samples = sampler.stop()
    post_snap = query_gpu_telemetry()
    mb = 1024.0 * 1024.0
    torch_peak_alloc = round(torch.cuda.max_memory_allocated() / mb, 1) if torch.cuda.is_available() else 0.0
    torch_peak_res = round(torch.cuda.max_memory_reserved() / mb, 1) if torch.cuda.is_available() else 0.0
    torch_post_res = round(torch.cuda.memory_reserved() / mb, 1) if torch.cuda.is_available() else 0.0
    inflight = _summarize_inflight(samples)
    return {
        "prompt_id": prompt_id,
        "stage_id": str(item["stage_id"]),
        "dkm_state_name": decision.dkm_state_name,
        "tokens_generated": reply.tokens_generated,
        "latency_ms": reply.latency_ms,
        "tokens_per_sec": reply.tokens_per_sec,
        "inflight_gpu": inflight,
        "post_turn_gpu": post_snap.to_dict(),
        "torch_peak_allocated_mb": torch_peak_alloc,
        "torch_peak_reserved_mb": torch_peak_res,
        "torch_post_reserved_mb": torch_post_res,
    }


def _summarize_vram_records(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate 12-prompt Zero-Spillover acceptance metrics in one flat pass."""
    peak_vrams: List[float] = []
    post_vrams: List[float] = []
    mem_utils: List[float] = []
    tps_vals: List[float] = []
    temps: List[float] = []
    powers: List[float] = []
    t_alloc: List[float] = []
    t_res: List[float] = []
    t_post: List[float] = []
    for r in records:
        peak_vrams.append(float(r["inflight_gpu"]["peak_vram_used_mb"]))
        post_vrams.append(float(r["post_turn_gpu"]["vram_used_mb"]))
        mem_utils.append(float(r["inflight_gpu"]["max_mem_util_pct"]))
        tps_vals.append(float(r["tokens_per_sec"]))
        temps.append(float(r["inflight_gpu"]["max_gpu_temp_c"]))
        powers.append(float(r["inflight_gpu"]["max_gpu_power_w"]))
        t_alloc.append(float(r["torch_peak_allocated_mb"]))
        t_res.append(float(r["torch_peak_reserved_mb"]))
        t_post.append(float(r["torch_post_reserved_mb"]))
    peak_vram = max(peak_vrams)
    post_vram_max = max(post_vrams)
    max_mem_util = max(mem_utils)
    max_temp = max(temps)
    max_power = max(powers)
    criteria = {
        "peak_vram_le_14900_mb": 0.0 < peak_vram <= DEFAULT_HARD_CEILING_MB,
        "post_turn_vram_le_11500_mb": 0.0 < post_vram_max <= 11500.0,
        "gddr6_controller_active_gt_1_3_pct": max_mem_util > 5.0,
        "wsl2_telemetry_nonzero": max_temp > 0.0 and max_power > 0.0,
    }
    return {
        "prompts_evaluated": len(records),
        "peak_vram_used_mb": peak_vram,
        "post_turn_vram_mb_max": post_vram_max,
        "gpu_mem_controller_util_pct_max": max_mem_util,
        "tokens_per_sec_mean": round(float(np.mean(tps_vals)), 2),
        "gpu_temp_c_max": max_temp,
        "gpu_power_w_max": max_power,
        "torch_peak_allocated_mb_max": max(t_alloc),
        "torch_peak_reserved_mb_max": max(t_res),
        "torch_post_reserved_mb_mean": round(float(np.mean(t_post)), 1),
        "all_acceptance_criteria_passed": all(criteria.values()),
        "criteria": criteria,
    }


def run_vram_cap_verification() -> Dict[str, Any]:
    """Execute 12-prompt Zero-Spillover Proof and seal REGISTER_M JSON."""
    alloc_conf = configure_allocator_env()
    lock = SingleGpuOwnerLock()
    if not lock.acquire("sync30b_vram_cap_verifier"):
        raise RuntimeError(f"GPU_LOCK_BUSY: {lock.read_current_owner()}")
    try:
        from vmax_alpha.nemotron_chat_engine import NemotronChatEngine

        baseline_snap = query_gpu_telemetry()
        dataset = json.loads(PROMPTS_PATH.read_text(encoding="utf-8"))
        twelve = _select_twelve_prompts(dataset)
        rom_path = REPO_ROOT / "rtl" / "rom" / "l_vec_q2_30.hex"
        little_q30 = load_silicon_little_vector(str(rom_path))
        mean_384, w_384_to_64, _ = load_projector_cache(DEFAULT_CACHE_DIR)
        gov = DolphinMemoryGovernor(little_q30)
        ctrl = DkmEgressController(gov)
        extractor = DkmSignalExtractor(_build_minilm_encoder(), mean_384, w_384_to_64, little_q30)
        engine = NemotronChatEngine(max_new_tokens=120, temperature=0.0)
        engine.load()
        after_load_snap = query_gpu_telemetry()
        records = [_run_one_turn(extractor, ctrl, engine, item) for item in twelve]
        summary = _summarize_vram_records(records)
        report: Dict[str, Any] = {
            "schema": "VMAX_STAGE6_VRAM_CAP_14900MB_REPORT_V1",
            "work_order": "WORK-ORDER-AG-30b",
            "sync_id": "SYNC-30b",
            "epistemic_register": "REGISTER_M",
            "bridge_reviewer_note": BROWSER_CRASH_GUARD_NOTE,
            "alloc_conf": alloc_conf,
            "vram_cap_status": getattr(engine, "vram_cap_status", {}),
            "prompts_dataset_sha256": sha256_file(PROMPTS_PATH),
            "baseline_gpu_before_load": baseline_snap.to_dict(),
            "gpu_immediately_after_load": after_load_snap.to_dict(),
            "summary": summary,
            "records": records,
        }
        sha = atomic_write_json(REPORT_PATH, report)
        report["report_sha256"] = sha
        atomic_write_json(REPORT_PATH, report)
        print(
            f"[SYNC-30b] PEAK_VRAM={summary['peak_vram_used_mb']}MB "
            f"POST_MAX={summary['post_turn_vram_mb_max']}MB "
            f"MEM_UTIL_MAX={summary['gpu_mem_controller_util_pct_max']}% "
            f"TPS_MEAN={summary['tokens_per_sec_mean']} "
            f"TEMP_MAX={summary['gpu_temp_c_max']}C "
            f"PWR_MAX={summary['gpu_power_w_max']}W "
            f"PASS={summary['all_acceptance_criteria_passed']}",
            flush=True,
        )
        return report
    finally:
        lock.release()


if __name__ == "__main__":
    run_vram_cap_verification()
