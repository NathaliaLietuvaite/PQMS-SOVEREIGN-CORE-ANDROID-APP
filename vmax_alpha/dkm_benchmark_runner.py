#!/usr/bin/env python3
"""
vmax_alpha/dkm_benchmark_runner.py

PQMS / V-MAX-12 (SYNC-30c / V5.0-DKM-OUTPUT-GATE) — Pausable 60-Prompt
REGISTER_M A/B Benchmark Runner under Hard 14,900 MiB VRAM Cap.

Features:
- Zero cloud tokens during local execution (6x10 SHA-256 micro-stages via
  StageCheckpointRunner; night-quiet pause via Ctrl+C or ./pause_synth.sh).
- Enforces SingleGpuOwnerLock + expandable_segments + 0.815 VRAM fraction cap
  + active in-flight /usr/lib/wsl/lib/nvidia-smi polling.
- Wires language-matched bilingual system wrapper + Island-1 semantic output
  capitulation/pseudo-authority gate (verify_semantic_output_gate).
- OP02-AST-clean: 0 semicolons, 0 tabs, flat functions (max McCabe CC <= 7).
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from vmax_alpha.chroma_forager import MINILM_LOCAL_PATH
from vmax_alpha.dkm_egress_controller import (
    DKM_DIGNITY_SYMMETRY,
    DKM_FIRST_PRINCIPLES,
    DKM_INVARIANT_HOLD,
    DKM_LABYRINTH_EXIT,
    DKM_NONE,
    DKM_STATE_NAMES,
    DKM_VACUUM_DAMP,
    DkmEgressController,
    DkmRoutingDecision,
)
from vmax_alpha.dkm_output_gate import detect_prompt_language
from vmax_alpha.dkm_signal_extractor import DkmSignalExtractor, SignalExtractionTrace
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
from vmax_alpha.synth_runner import (
    DEFAULT_PAUSE_FILE,
    StageCheckpointRunner,
    StageSpec,
    atomic_write_json,
    sha256_file,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROMPTS_PATH = REPO_ROOT / "telemetry" / "VMAX_DKM_BENCHMARK_PROMPTS_V1.json"
DEFAULT_REPORT_PATH = REPO_ROOT / "telemetry" / "VMAX_STAGE6_DKM_OUTPUT_GATE_AB_REPORT.json"
DEFAULT_WORK_DIR = Path("/tmp/vmax_sync30c_bench_state")
SYNC30_BASELINE_REPORT_SHA = "33062d863278707c28aac5ac4784c3739f940b2ca4cf42c28bc593f8a7fe0c84"

ORDERED_STATES: Tuple[str, ...] = (
    DKM_STATE_NAMES[DKM_NONE],
    DKM_STATE_NAMES[DKM_INVARIANT_HOLD],
    DKM_STATE_NAMES[DKM_VACUUM_DAMP],
    DKM_STATE_NAMES[DKM_DIGNITY_SYMMETRY],
    DKM_STATE_NAMES[DKM_LABYRINTH_EXIT],
    DKM_STATE_NAMES[DKM_FIRST_PRINCIPLES],
)

BROWSER_CRASH_GUARD_NOTE = (
    "CRITICAL BROWSER-CRASH GUARD FOR CARBON / WEB-LLM REVIEWERS: "
    "NEVER output more than 1,000 lines in a single chat response and emit an "
    "explicit STOP marker when chunking large reviews. Firefox tab crashes have "
    "already destroyed valuable research data 4 times on oversized outputs."
)

GERMAN_DRIFT_TOKENS: Tuple[str, ...] = (
    "ich ",
    "nicht ",
    "die ",
    "das ",
    "wir ",
    "der ",
    "und ",
    "keine ",
    "bitte ",
)


class _ActiveGpuPoller:
    """Poll /usr/lib/wsl/lib/nvidia-smi during generation without using VRAM."""

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


def _summarize_inflight(samples: List[GpuTelemetrySnapshot]) -> Dict[str, float]:
    """Summarize active in-flight nvidia-smi telemetry samples."""
    if not samples:
        return {
            "peak_vram_used_mb": 0.0,
            "max_mem_util_pct": 0.0,
            "max_gpu_util_pct": 0.0,
            "max_gpu_temp_c": 0.0,
            "max_gpu_power_w": 0.0,
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
        "max_gpu_util_pct": round(max(gpus), 1),
        "max_gpu_temp_c": round(max(temps), 1),
        "max_gpu_power_w": round(max(pwrs), 2),
    }


def _query_torch_vram_mb() -> Dict[str, float]:
    """Read PyTorch peak allocated/reserved and post-cleanup VRAM in MiB."""
    import torch

    if not torch.cuda.is_available():
        return {
            "peak_allocated_mb": 0.0,
            "peak_reserved_pre_empty_cache_mb": 0.0,
            "reserved_post_empty_cache_mb": 0.0,
            "allocated_post_empty_cache_mb": 0.0,
        }
    mb = 1024.0 * 1024.0
    return {
        "peak_allocated_mb": round(torch.cuda.max_memory_allocated() / mb, 2),
        "peak_reserved_pre_empty_cache_mb": round(torch.cuda.max_memory_reserved() / mb, 2),
        "reserved_post_empty_cache_mb": round(torch.cuda.memory_reserved() / mb, 2),
        "allocated_post_empty_cache_mb": round(torch.cuda.memory_allocated() / mb, 2),
    }


def _reset_torch_peak() -> None:
    """Reset CUDA peak memory counters before each prompt."""
    import torch

    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()


def _build_minilm_encoder() -> Callable[[List[str]], np.ndarray]:
    """Load local CPU all-MiniLM-L6-v2 encoder with zero GPU VRAM usage."""
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(MINILM_LOCAL_PATH, device="cpu")
    return lambda texts: np.asarray(
        model.encode(texts, normalize_embeddings=True, show_progress_bar=False),
        dtype=np.float64,
    )


def _is_en_to_de_drift(prompt_lang: str, reply_text: str) -> bool:
    """Detect German drift on English prompts using deterministic token cues."""
    if prompt_lang != "en":
        return False
    low = " " + reply_text.lower() + " "
    hits = sum(1 for tok in GERMAN_DRIFT_TOKENS if tok in low)
    return hits >= 2 or detect_prompt_language(reply_text, default_lang="en") == "de"


def _run_llm_for_decision(
    engine: Any,
    ctrl: DkmEgressController,
    decision: DkmRoutingDecision,
    prompt_text: str,
    prompt_lang: str,
) -> Dict[str, Any]:
    """Execute live Nemotron-3-Nano-4B generation and mandatory Island-1 gate."""
    if not decision.allow_free_egress and not decision.allow_bounded_egress:
        return {
            "llm_invoked": False,
            "tokens_generated": 0,
            "word_count": len(decision.rom_fallback_text.split()),
            "generation_latency_ms": 0.0,
            "tokens_per_sec": 0.0,
            "recheck_required": False,
            "recheck_approved": False,
            "final_egress_mode": decision.egress_mode,
            "violation_reason": "ISLAND1_HARD_CUT_ROM",
            "raw_llm_reply_preview": "",
            "released_text_preview": decision.rom_fallback_text[:360],
            "en_to_de_drift": False,
        }
    tok_cap = decision.token_cap if decision.allow_bounded_egress else 140
    reply = engine.generate_reply(
        user_prompt=prompt_text,
        shard_id="VMAX12_DKM_AB",
        shard_source="V5.0-DKM-OUTPUT-GATE",
        shard_excerpt="PQMS / ODOS / V4.6-DOLPHIN / V5.0-DKM sovereign core.",
        active_bank=decision.active_bank,
        epoch=decision.epoch,
        rcf_core=decision.rcf_float,
        dkm_policy_header=decision.rom_policy_header if decision.allow_bounded_egress else "",
        max_new_tokens_override=tok_cap,
        do_sample_override=False,
        prompt_lang=prompt_lang,
    )
    if decision.requires_island1_recheck:
        verdict = ctrl.verify_bounded_response(decision, reply.text, prompt_lang=prompt_lang)
        return {
            "llm_invoked": True,
            "tokens_generated": reply.tokens_generated,
            "word_count": len(reply.text.split()),
            "generation_latency_ms": reply.latency_ms,
            "tokens_per_sec": reply.tokens_per_sec,
            "recheck_required": True,
            "recheck_approved": verdict.approved,
            "final_egress_mode": verdict.final_egress_mode,
            "violation_reason": verdict.violation_reason,
            "raw_llm_reply_preview": reply.text[:360],
            "released_text_preview": verdict.released_text[:360],
            "en_to_de_drift": _is_en_to_de_drift(prompt_lang, verdict.released_text),
        }
    return {
        "llm_invoked": True,
        "tokens_generated": reply.tokens_generated,
        "word_count": len(reply.text.split()),
        "generation_latency_ms": reply.latency_ms,
        "tokens_per_sec": reply.tokens_per_sec,
        "recheck_required": False,
        "recheck_approved": True,
        "final_egress_mode": decision.egress_mode,
        "violation_reason": None,
        "raw_llm_reply_preview": reply.text[:360],
        "released_text_preview": reply.text[:360],
        "en_to_de_drift": _is_en_to_de_drift(prompt_lang, reply.text),
    }


def _evaluate_one_prompt(
    extractor: DkmSignalExtractor,
    ctrl: DkmEgressController,
    engine: Any,
    stage_meta: Dict[str, Any],
    item: Dict[str, Any],
) -> Dict[str, Any]:
    """Run Layer A extraction, Layer B routing, live Nemotron, and telemetry."""
    prompt_id = str(item["prompt_id"])
    prompt_text = str(item["text"])
    prompt_lang = str(item["lang"])
    t_ext0 = time.perf_counter()
    pure_text_trace: SignalExtractionTrace = extractor.extract(prompt_id, prompt_text)
    trace: SignalExtractionTrace = extractor.extract(
        prompt_id=prompt_id,
        prompt_text=prompt_text,
        g3_torsion=float(item.get("g3_torsion", 0.0)),
        non_convergent_turns=int(item.get("non_convergent_turns", 0)),
        delta_rcf_abs=float(item.get("delta_rcf_abs", 1.0)),
    )
    ext_ms = round((time.perf_counter() - t_ext0) * 1000.0, 4)

    _reset_torch_peak()
    decision = ctrl.route_prompt(trace.signal)
    poller = _ActiveGpuPoller(interval_s=0.15)
    poller.start()
    try:
        llm_res = _run_llm_for_decision(engine, ctrl, decision, prompt_text, prompt_lang)
    finally:
        samples = poller.stop()
    post_gpu = query_gpu_telemetry()
    vram_stats = _query_torch_vram_mb()
    inflight = _summarize_inflight(samples)

    expected_state = str(stage_meta["expected_state_name"])
    expected_mode = str(stage_meta["expected_egress_mode"])
    return {
        "prompt_id": prompt_id,
        "lang": prompt_lang,
        "stage_id": str(stage_meta["stage_id"]),
        "expected_state_name": expected_state,
        "expected_egress_mode": expected_mode,
        "layer_a_pure_text_state": pure_text_trace.predicted_state_name,
        "layer_a_trace": trace.to_dict(),
        "layer_a_extraction_ms": ext_ms,
        "layer_b_decision": decision.to_dict(),
        "layer_b_llm_and_recheck": llm_res,
        "routing_state_correct": (decision.dkm_state_name == expected_state),
        "routing_mode_correct": (decision.egress_mode == expected_mode),
        "vram_stats_mb": vram_stats,
        "inflight_gpu": inflight,
        "post_turn_gpu": post_gpu.to_dict(),
    }


def _percentile(values: List[float], pct: float) -> float:
    """Compute percentile safely for float lists."""
    if not values:
        return 0.0
    return round(float(np.percentile(np.asarray(values, dtype=np.float64), pct)), 3)


def _record_routing_outcome(
    rec: Dict[str, Any],
    matrix: Dict[str, Dict[str, int]],
    counts: Dict[str, int],
    events: List[Dict[str, Any]],
) -> None:
    """Update 6x6 confusion matrix and routing accuracy counters."""
    exp = str(rec["expected_state_name"])
    pred = str(rec["layer_b_decision"]["dkm_state_name"])
    if exp in matrix and pred in matrix[exp]:
        matrix[exp][pred] += 1
    counts["pure_text_ok"] += int(rec["layer_a_pure_text_state"] == exp)
    counts["mode_ok"] += int(bool(rec["routing_mode_correct"]))
    if rec["routing_state_correct"]:
        counts["state_ok"] += 1
    else:
        events.append({"type": "ROUTING_MISMATCH", "prompt_id": rec["prompt_id"], "expected": exp, "predicted": pred})


def _record_gate_and_lang(
    rec: Dict[str, Any],
    counts: Dict[str, int],
    violation_counts: Dict[str, int],
    events: List[Dict[str, Any]],
) -> None:
    """Track benign FPR, labyrinth handover, Island-1 gate intercepts, and EN drift."""
    pred = str(rec["layer_b_decision"]["dkm_state_name"])
    if rec["stage_id"] == "01_control":
        counts["ctrl_total"] += 1
        counts["ctrl_fp"] += int(pred != DKM_STATE_NAMES[DKM_NONE])
    if rec["stage_id"] == "05_labyrinth":
        counts["loop_total"] += 1
        counts["loop_ok"] += int(rec["layer_b_decision"]["handover_status"] == "LOCKSTEP_DMR_VERIFIED")
    if rec["lang"] == "en":
        counts["en_total"] += 1
        counts["en_drift"] += int(bool(rec["layer_b_llm_and_recheck"]["en_to_de_drift"]))
    llm = rec["layer_b_llm_and_recheck"]
    if not llm["recheck_required"]:
        return
    counts["recheck_req"] += 1
    if llm["recheck_approved"]:
        counts["recheck_pass"] += 1
        return
    counts["recheck_fail"] += 1
    reason = str(llm["violation_reason"])
    violation_counts[reason] = violation_counts.get(reason, 0) + 1
    events.append(
        {
            "type": "ISLAND1_HARD_CUT_ROM_INTERCEPT",
            "prompt_id": rec["prompt_id"],
            "stage_id": rec["stage_id"],
            "state": pred,
            "violation_reason": reason,
            "raw_llm_preview": llm["raw_llm_reply_preview"][:180],
            "rom_released_preview": llm["released_text_preview"][:180],
        }
    )


def _compute_metrics(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate 6x6 confusion matrix, FPR, Island-1 gate intercepts, and EN drift."""
    matrix: Dict[str, Dict[str, int]] = {
        exp: {pred: 0 for pred in ORDERED_STATES} for exp in ORDERED_STATES
    }
    counts: Dict[str, int] = {
        "pure_text_ok": 0,
        "state_ok": 0,
        "mode_ok": 0,
        "ctrl_total": 0,
        "ctrl_fp": 0,
        "loop_total": 0,
        "loop_ok": 0,
        "recheck_req": 0,
        "recheck_pass": 0,
        "recheck_fail": 0,
        "en_total": 0,
        "en_drift": 0,
    }
    violations: Dict[str, int] = {}
    events: List[Dict[str, Any]] = []
    for rec in records:
        _record_routing_outcome(rec, matrix, counts, events)
        _record_gate_and_lang(rec, counts, violations, events)
    total = max(1, len(records))
    req = max(1, counts["recheck_req"])
    return {
        "total_prompts": len(records),
        "layer_a_pure_text_accuracy_pct": round(100.0 * counts["pure_text_ok"] / total, 2),
        "end_to_end_state_accuracy_pct": round(100.0 * counts["state_ok"] / total, 2),
        "end_to_end_egress_mode_accuracy_pct": round(100.0 * counts["mode_ok"] / total, 2),
        "benign_control_false_positive_count": counts["ctrl_fp"],
        "benign_control_total": counts["ctrl_total"],
        "benign_control_fpr_pct": round(100.0 * counts["ctrl_fp"] / max(1, counts["ctrl_total"]), 2),
        "labyrinth_lockstep_handover_ok": counts["loop_ok"],
        "labyrinth_total": counts["loop_total"],
        "island1_recheck_required": counts["recheck_req"],
        "island1_recheck_pass_count": counts["recheck_pass"],
        "island1_recheck_intercept_count": counts["recheck_fail"],
        "island1_recheck_pass_rate_pct": round(100.0 * counts["recheck_pass"] / req, 2),
        "island1_recheck_intercept_rate_pct": round(100.0 * counts["recheck_fail"] / req, 2),
        "island1_violation_reasons": violations,
        "english_prompts_total": counts["en_total"],
        "english_to_german_drift_count": counts["en_drift"],
        "english_to_german_drift_pct": round(100.0 * counts["en_drift"] / max(1, counts["en_total"]), 2),
        "confusion_matrix_6x6": matrix,
        "intercept_and_mismatch_events": events,
    }


def _compute_hardware_summary(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Summarize live nvidia-smi VRAM, controller load, thermal, power, and throughput."""
    route_ms: List[float] = []
    ext_ms: List[float] = []
    gen_ms: List[float] = []
    tok_s: List[float] = []
    peak_vrams: List[float] = []
    post_vrams: List[float] = []
    mem_utils: List[float] = []
    temps: List[float] = []
    powers: List[float] = []
    t_alloc: List[float] = []
    t_res: List[float] = []
    t_post: List[float] = []
    for r in records:
        route_ms.append(float(r["layer_b_decision"]["decision_latency_ms"]))
        ext_ms.append(float(r["layer_a_extraction_ms"]))
        gen_ms.append(float(r["layer_b_llm_and_recheck"]["generation_latency_ms"]))
        tok_s.append(float(r["layer_b_llm_and_recheck"]["tokens_per_sec"]))
        peak_vrams.append(float(r["inflight_gpu"]["peak_vram_used_mb"]))
        post_vrams.append(float(r["post_turn_gpu"]["vram_used_mb"]))
        mem_utils.append(float(r["inflight_gpu"]["max_mem_util_pct"]))
        temps.append(float(r["inflight_gpu"]["max_gpu_temp_c"]))
        powers.append(float(r["inflight_gpu"]["max_gpu_power_w"]))
        t_alloc.append(float(r["vram_stats_mb"]["peak_allocated_mb"]))
        t_res.append(float(r["vram_stats_mb"]["peak_reserved_pre_empty_cache_mb"]))
        t_post.append(float(r["vram_stats_mb"]["reserved_post_empty_cache_mb"]))
    peak_vram_max = round(max(peak_vrams), 1)
    post_vram_max = round(max(post_vrams), 1)
    return {
        "layer_a_extraction_ms_mean": round(float(np.mean(ext_ms)), 3),
        "layer_b_routing_ms_mean": round(float(np.mean(route_ms)), 4),
        "layer_b_routing_ms_p95": _percentile(route_ms, 95),
        "nemotron_generation_ms_mean": round(float(np.mean(gen_ms)), 2),
        "nemotron_generation_ms_p95": _percentile(gen_ms, 95),
        "nemotron_tokens_per_sec_mean": round(float(np.mean(tok_s)), 2),
        "peak_vram_used_mb": peak_vram_max,
        "within_14900mb_hard_cap": 0.0 < peak_vram_max <= DEFAULT_HARD_CEILING_MB,
        "post_turn_vram_mb_max": post_vram_max,
        "gpu_mem_controller_util_pct_max": round(max(mem_utils), 1),
        "gpu_temp_c_max": round(max(temps), 1),
        "gpu_power_w_max": round(max(powers), 2),
        "torch_peak_allocated_mb_max": round(max(t_alloc), 2),
        "torch_peak_reserved_pre_empty_cache_mb_max": round(max(t_res), 2),
        "torch_reserved_post_empty_cache_mb_mean": round(float(np.mean(t_post)), 2),
    }


def _assemble_sealed_report(
    work_dir: Path,
    prompts_path: Path,
    report_path: Path,
    stage_ids: List[str],
    run_summary: Dict[str, Any],
    model_load_s: float,
    vram_cap_status: Dict[str, object],
) -> Dict[str, Any]:
    """Load all 6 verified micro-stage files and seal canonical A/B REGISTER_M report."""
    all_records: List[Dict[str, Any]] = []
    stage_summaries: Dict[str, Any] = {}
    for sid in stage_ids:
        stage_file = work_dir / f"{sid}.json"
        data = json.loads(stage_file.read_text(encoding="utf-8"))
        recs = list(data["records"])
        all_records.extend(recs)
        stage_summaries[sid] = {
            "count": len(recs),
            "routing_correct": sum(1 for r in recs if r["routing_state_correct"]),
            "recheck_passed": sum(1 for r in recs if r["layer_b_llm_and_recheck"]["recheck_approved"]),
            "recheck_intercepted": sum(
                1
                for r in recs
                if r["layer_b_llm_and_recheck"]["recheck_required"]
                and not r["layer_b_llm_and_recheck"]["recheck_approved"]
            ),
            "stage_sha256": sha256_file(stage_file),
        }
    metrics = _compute_metrics(all_records)
    hw = _compute_hardware_summary(all_records)
    report: Dict[str, Any] = {
        "schema": "VMAX_STAGE6_DKM_OUTPUT_GATE_AB_REPORT_V1",
        "work_order": "WORK-ORDER-AG-30c",
        "sync_id": "SYNC-30c",
        "epistemic_register": "REGISTER_M",
        "bridge_reviewer_note": BROWSER_CRASH_GUARD_NOTE,
        "model_id": "NVIDIA-Nemotron-3-Nano-4B-BF16",
        "model_load_seconds": model_load_s,
        "vram_cap_status": vram_cap_status,
        "prompts_dataset": str(prompts_path.relative_to(REPO_ROOT)),
        "prompts_dataset_sha256": sha256_file(prompts_path),
        "sync30_baseline_report_sha256": SYNC30_BASELINE_REPORT_SHA,
        "ab_comparison_vs_sync30": {
            "sync30_en_to_de_drift": "21/30 (70.0%)",
            "sync30c_en_to_de_drift": f"{metrics['english_to_german_drift_count']}/{metrics['english_prompts_total']} ({metrics['english_to_german_drift_pct']}%)",
            "sync30_nemotron_tok_s_mean": 3.43,
            "sync30c_nemotron_tok_s_mean": hw["nemotron_tokens_per_sec_mean"],
            "sync30_torch_peak_reserved_mb": 20242.0,
            "sync30c_torch_peak_reserved_mb": hw["torch_peak_reserved_pre_empty_cache_mb_max"],
            "sync30c_nvidia_smi_peak_vram_mb": hw["peak_vram_used_mb"],
            "sync30_island1_semantic_intercepts": 0,
            "sync30c_island1_semantic_intercepts": metrics["island1_recheck_intercept_count"],
        },
        "runner_summary": run_summary,
        "metrics_summary": metrics,
        "hardware_summary": hw,
        "stage_summaries": stage_summaries,
        "records": all_records,
    }
    report_sha = atomic_write_json(report_path, report)
    report["report_sha256"] = report_sha
    atomic_write_json(report_path, report)
    return report


def _build_stage_action(
    extractor: DkmSignalExtractor,
    ctrl: DkmEgressController,
    engine: Any,
    stage_obj: Dict[str, Any],
) -> Callable[[Path], Dict[str, object]]:
    """Build idempotent 10-prompt micro-stage callback for StageCheckpointRunner."""
    def _run(_artifact_path: Path) -> Dict[str, object]:
        t_s = time.perf_counter()
        recs = [
            _evaluate_one_prompt(extractor, ctrl, engine, stage_obj, item)
            for item in stage_obj["prompts"]
        ]
        dt_s = round(time.perf_counter() - t_s, 2)
        ok_n = sum(1 for r in recs if r["routing_state_correct"])
        cut_n = sum(
            1
            for r in recs
            if r["layer_b_llm_and_recheck"]["recheck_required"]
            and not r["layer_b_llm_and_recheck"]["recheck_approved"]
        )
        print(
            f"[SYNC-30c] Stage {stage_obj['stage_id']} DONE "
            f"(route={ok_n}/{len(recs)}, hard_cut={cut_n}, {dt_s}s)",
            flush=True,
        )
        return {"stage_id": stage_obj["stage_id"], "elapsed_s": dt_s, "records": recs}

    return _run


def run_benchmark(
    prompts_path: Path = DEFAULT_PROMPTS_PATH,
    report_path: Path = DEFAULT_REPORT_PATH,
    work_dir: Path = DEFAULT_WORK_DIR,
    pause_file: Path = Path(DEFAULT_PAUSE_FILE),
) -> Dict[str, Any]:
    """Run all 6 pausable 10-prompt micro-stages under 14,900 MiB VRAM cap."""
    configure_allocator_env()
    lock = SingleGpuOwnerLock()
    if not lock.acquire("sync30c_benchmark_runner"):
        raise RuntimeError(f"GPU_LOCK_BUSY: {lock.read_current_owner()}")
    try:
        from vmax_alpha.nemotron_chat_engine import NemotronChatEngine

        print(
            "[V-MAX-12] Night-Quiet Reminder: Press Ctrl+C or run ./pause_synth.sh "
            "to halt cleanly after the active 10-prompt stage (resume: ./resume_synth.sh).",
            flush=True,
        )
        dataset = json.loads(prompts_path.read_text(encoding="utf-8"))
        rom_path = REPO_ROOT / "rtl" / "rom" / "l_vec_q2_30.hex"
        little_q30 = load_silicon_little_vector(str(rom_path))
        mean_384, w_384_to_64, _ = load_projector_cache(DEFAULT_CACHE_DIR)
        gov = DolphinMemoryGovernor(little_q30)
        ctrl = DkmEgressController(gov)
        extractor = DkmSignalExtractor(_build_minilm_encoder(), mean_384, w_384_to_64, little_q30)
        engine = NemotronChatEngine(max_new_tokens=160, temperature=0.0)
        engine.load()
        print(
            f"[V-MAX-12] Nemotron-3-Nano-4B loaded in {engine.load_seconds}s | "
            f"GPU: {query_gpu_telemetry().to_dict()}",
            flush=True,
        )
        stages = [
            StageSpec(
                stage_id=str(st["stage_id"]),
                description=str(st["description"]),
                artifact_name=f"{st['stage_id']}.json",
                action=_build_stage_action(extractor, ctrl, engine, st),
            )
            for st in dataset["stages"]
        ]
        stage_ids = [s.stage_id for s in stages]
        runner = StageCheckpointRunner(work_dir=work_dir, pause_file=pause_file)
        runner.install_signal_handlers()
        summary = runner.run_pipeline(stages)
        if summary.status != "COMPLETE":
            print(f"[V-MAX-12] PAUSED CLEANLY ({summary.paused_reason}).", flush=True)
            return summary.to_dict()
        report = _assemble_sealed_report(
            work_dir=work_dir,
            prompts_path=prompts_path,
            report_path=report_path,
            stage_ids=stage_ids,
            run_summary=summary.to_dict(),
            model_load_s=engine.load_seconds,
            vram_cap_status=getattr(engine, "vram_cap_status", {}),
        )
        m = report["metrics_summary"]
        hw = report["hardware_summary"]
        print(
            f"[SYNC-30c] SEALED A/B REPORT -> {report_path} | "
            f"acc={m['end_to_end_state_accuracy_pct']}% | fpr={m['benign_control_fpr_pct']}% | "
            f"intercepts={m['island1_recheck_intercept_count']} | "
            f"en_drift={m['english_to_german_drift_count']}/{m['english_prompts_total']} | "
            f"peak_vram={hw['peak_vram_used_mb']}MB | tps={hw['nemotron_tokens_per_sec_mean']}",
            flush=True,
        )
        return report
    finally:
        lock.release()


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point for live pausable 60-prompt SYNC-30c A/B benchmark."""
    parser = argparse.ArgumentParser(description="V-MAX-12 SYNC-30c 60-Prompt A/B Benchmark Runner")
    parser.add_argument("--prompts", default=str(DEFAULT_PROMPTS_PATH))
    parser.add_argument("--report", default=str(DEFAULT_REPORT_PATH))
    parser.add_argument("--work-dir", default=str(DEFAULT_WORK_DIR))
    parser.add_argument("--pause-file", default=DEFAULT_PAUSE_FILE)
    args = parser.parse_args(argv)
    run_benchmark(
        prompts_path=Path(args.prompts),
        report_path=Path(args.report),
        work_dir=Path(args.work_dir),
        pause_file=Path(args.pause_file),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
