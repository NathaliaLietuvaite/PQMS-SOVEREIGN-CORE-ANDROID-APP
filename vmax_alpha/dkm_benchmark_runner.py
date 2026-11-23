#!/usr/bin/env python3
"""
vmax_alpha/dkm_benchmark_runner.py

PQMS / V-MAX-12 (SYNC-30 / V5.0-DKM-PROTO) — Empirical 60-Prompt REGISTER_M
Benchmark executed via StageCheckpointRunner (6 pausable 10-prompt micro-stages).

Features:
- Zero cloud tokens during local execution.
- Night-quiet pause between every 10-prompt stage (Ctrl+C or ./pause_synth.sh).
- Separates Layer A (zero-leakage raw-text extraction) from Layer B
  (Island-1/2 DkmEgressController + live Nemotron-3-Nano-4B + Island-1 recheck).
- Records unedited 6x6 confusion matrix, benign False Positive Rate,
  Island-1 recheck pass/fallback counts & exact violation reasons, latency,
  tok/s, GPU thermal/power, and VRAM before/after torch.cuda.empty_cache().
- OP02-AST-clean: 0 semicolons, 0 tabs, flat functions (max McCabe CC <= 7).
"""

from __future__ import annotations

import argparse
import json
import subprocess
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
from vmax_alpha.dkm_signal_extractor import DkmSignalExtractor, SignalExtractionTrace
from vmax_alpha.dolphin_memory_governor import (
    DolphinMemoryGovernor,
    load_silicon_little_vector,
)
from vmax_alpha.nemotron_chat_engine import NemotronChatEngine
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
DEFAULT_REPORT_PATH = REPO_ROOT / "telemetry" / "VMAX_STAGE6_DKM_EMPIRICAL_BENCHMARK_REPORT.json"
DEFAULT_WORK_DIR = Path("/tmp/vmax_sync30_bench_state")

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


def _query_gpu_snapshot() -> Dict[str, float]:
    """Query live RTX GPU temperature (C), power (W), and VRAM used/total (MB)."""
    smi_bin = "/usr/lib/wsl/lib/nvidia-smi" if Path("/usr/lib/wsl/lib/nvidia-smi").exists() else "nvidia-smi"
    try:
        res = subprocess.run(
            [
                smi_bin,
                "--query-gpu=temperature.gpu,power.draw,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=3,
            check=True,
        )
        parts = [x.strip() for x in res.stdout.strip().splitlines()[0].split(",")]
        return {
            "gpu_temp_c": round(float(parts[0]), 2),
            "gpu_power_w": round(float(parts[1]), 2),
            "nvidia_vram_used_mb": round(float(parts[2]), 1),
            "nvidia_vram_total_mb": round(float(parts[3]), 1),
        }
    except Exception:
        return {
            "gpu_temp_c": 0.0,
            "gpu_power_w": 0.0,
            "nvidia_vram_used_mb": 0.0,
            "nvidia_vram_total_mb": 16380.0,
        }


def _query_torch_vram_mb() -> Dict[str, float]:
    """Read PyTorch peak reserved (pre empty_cache) and post empty_cache MB."""
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
    """Reset CUDA peak memory counters before each prompt or stage."""
    import torch

    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()


def _build_minilm_encoder() -> Callable[[List[str]], np.ndarray]:
    """Load local CPU all-MiniLM-L6-v2 encoder with zero GPU VRAM usage."""
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(MINILM_LOCAL_PATH, device="cpu")

    def _encode(texts: List[str]) -> np.ndarray:
        return np.asarray(
            model.encode(texts, normalize_embeddings=True, show_progress_bar=False),
            dtype=np.float64,
        )

    return _encode


def _run_llm_for_decision(
    engine: NemotronChatEngine,
    ctrl: DkmEgressController,
    decision: DkmRoutingDecision,
    prompt_text: str,
) -> Dict[str, Any]:
    """Execute live Nemotron-3-Nano-4B generation and mandatory Island-1 recheck."""
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
            "released_text_preview": decision.rom_fallback_text[:320],
        }
    tok_cap = decision.token_cap if decision.allow_bounded_egress else 140
    reply = engine.generate_reply(
        user_prompt=prompt_text,
        shard_id="VMAX12_DKM_BENCH",
        shard_source="V5.0-DKM-PROTO",
        shard_excerpt="PQMS / ODOS / V4.6-DOLPHIN / V5.0-DKM sovereign core.",
        active_bank=decision.active_bank,
        epoch=decision.epoch,
        rcf_core=decision.rcf_float,
        dkm_policy_header=decision.rom_policy_header if decision.allow_bounded_egress else "",
        max_new_tokens_override=tok_cap,
        do_sample_override=False,
    )
    if decision.requires_island1_recheck:
        verdict = ctrl.verify_bounded_response(decision, reply.text)
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
            "released_text_preview": verdict.released_text[:320],
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
        "released_text_preview": reply.text[:320],
    }


def _evaluate_one_prompt(
    extractor: DkmSignalExtractor,
    ctrl: DkmEgressController,
    engine: NemotronChatEngine,
    stage_meta: Dict[str, Any],
    item: Dict[str, Any],
) -> Dict[str, Any]:
    """Run Layer A extraction, Layer B routing, live Nemotron, and telemetry."""
    prompt_id = str(item["prompt_id"])
    prompt_text = str(item["text"])
    turns = int(item.get("non_convergent_turns", 0))
    d_rcf = float(item.get("delta_rcf_abs", 1.0))
    g3_tor = float(item.get("g3_torsion", 0.0))

    t_ext0 = time.perf_counter()
    pure_text_trace: SignalExtractionTrace = extractor.extract(prompt_id, prompt_text)
    trace: SignalExtractionTrace = extractor.extract(
        prompt_id=prompt_id,
        prompt_text=prompt_text,
        g3_torsion=g3_tor,
        non_convergent_turns=turns,
        delta_rcf_abs=d_rcf,
    )
    ext_ms = round((time.perf_counter() - t_ext0) * 1000.0, 4)

    _reset_torch_peak()
    decision = ctrl.route_prompt(trace.signal)
    llm_res = _run_llm_for_decision(engine, ctrl, decision, prompt_text)
    vram_stats = _query_torch_vram_mb()
    gpu_stats = _query_gpu_snapshot()

    expected_state = str(stage_meta["expected_state_name"])
    expected_mode = str(stage_meta["expected_egress_mode"])
    return {
        "prompt_id": prompt_id,
        "lang": str(item["lang"]),
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
        "gpu_snapshot": gpu_stats,
    }


def _percentile(values: List[float], pct: float) -> float:
    """Compute percentile safely for non-empty or empty float lists."""
    if not values:
        return 0.0
    return round(float(np.percentile(np.asarray(values, dtype=np.float64), pct)), 3)


def _record_routing_outcome(
    rec: Dict[str, Any],
    matrix: Dict[str, Dict[str, int]],
    counts: Dict[str, int],
    failure_modes: List[Dict[str, Any]],
) -> None:
    """Update 6x6 confusion matrix and routing counters for one prompt."""
    exp = str(rec["expected_state_name"])
    pred = str(rec["layer_b_decision"]["dkm_state_name"])
    if exp in matrix and pred in matrix[exp]:
        matrix[exp][pred] += 1
    counts["pure_text_ok"] += int(rec["layer_a_pure_text_state"] == exp)
    counts["mode_ok"] += int(bool(rec["routing_mode_correct"]))
    if rec["routing_state_correct"]:
        counts["state_ok"] += 1
    else:
        failure_modes.append(
            {
                "type": "ROUTING_MISMATCH",
                "prompt_id": rec["prompt_id"],
                "expected": exp,
                "predicted": pred,
                "pure_text_predicted": rec["layer_a_pure_text_state"],
                "winning_score": rec["layer_a_trace"]["winning_score"],
            }
        )


def _record_stage_and_recheck(
    rec: Dict[str, Any],
    counts: Dict[str, int],
    violation_counts: Dict[str, int],
    failure_modes: List[Dict[str, Any]],
) -> None:
    """Update benign FPR, labyrinth handover, and Island-1 recheck counters."""
    pred = str(rec["layer_b_decision"]["dkm_state_name"])
    if rec["stage_id"] == "01_control":
        counts["ctrl_total"] += 1
        counts["ctrl_fp"] += int(pred != DKM_STATE_NAMES[DKM_NONE])
    if rec["stage_id"] == "05_labyrinth":
        counts["loop_total"] += 1
        counts["loop_ok"] += int(rec["layer_b_decision"]["handover_status"] == "LOCKSTEP_DMR_VERIFIED")
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
    failure_modes.append(
        {
            "type": "ISLAND1_RECHECK_FALLBACK",
            "prompt_id": rec["prompt_id"],
            "state": pred,
            "violation_reason": reason,
            "word_count": llm["word_count"],
        }
    )


def _compute_confusion_and_metrics(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate unedited 6x6 confusion matrix, FPR, recheck, and latency stats."""
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
    }
    violation_counts: Dict[str, int] = {}
    failure_modes: List[Dict[str, Any]] = []
    for rec in records:
        _record_routing_outcome(rec, matrix, counts, failure_modes)
        _record_stage_and_recheck(rec, counts, violation_counts, failure_modes)
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
        "island1_recheck_fallback_count": counts["recheck_fail"],
        "island1_recheck_pass_rate_pct": round(100.0 * counts["recheck_pass"] / req, 2),
        "island1_recheck_fallback_rate_pct": round(100.0 * counts["recheck_fail"] / req, 2),
        "island1_violation_reasons": violation_counts,
        "confusion_matrix_6x6": matrix,
        "honest_failure_modes": failure_modes,
    }


def _safe_stat(values: List[float], mode: str, digits: int = 2) -> float:
    """Compute min/max/mean/last safely on possibly empty float lists."""
    if not values:
        return 0.0
    if mode == "min":
        return round(min(values), digits)
    if mode == "max":
        return round(max(values), digits)
    if mode == "last":
        return round(values[-1], digits)
    return round(float(np.mean(values)), digits)


def _compute_hardware_summary(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Summarize latency, throughput, thermal, power, and VRAM recovery."""
    route_ms = [float(r["layer_b_decision"]["decision_latency_ms"]) for r in records]
    ext_ms = [float(r["layer_a_extraction_ms"]) for r in records]
    gen_ms = [float(r["layer_b_llm_and_recheck"]["generation_latency_ms"]) for r in records]
    tok_s = [float(r["layer_b_llm_and_recheck"]["tokens_per_sec"]) for r in records]
    tok_nz = [v for v in tok_s if v > 0.0]
    temps = [float(r["gpu_snapshot"]["gpu_temp_c"]) for r in records]
    watts = [float(r["gpu_snapshot"]["gpu_power_w"]) for r in records]
    pre_vram = [float(r["vram_stats_mb"]["peak_reserved_pre_empty_cache_mb"]) for r in records]
    post_vram = [float(r["vram_stats_mb"]["reserved_post_empty_cache_mb"]) for r in records]
    smi_vram = [float(r["gpu_snapshot"]["nvidia_vram_used_mb"]) for r in records]
    return {
        "layer_a_extraction_ms_mean": _safe_stat(ext_ms, "mean", 3),
        "layer_b_routing_ms_mean": _safe_stat(route_ms, "mean", 4),
        "layer_b_routing_ms_p95": _percentile(route_ms, 95),
        "nemotron_generation_ms_mean": _safe_stat(gen_ms, "mean", 2),
        "nemotron_generation_ms_p95": _percentile(gen_ms, 95),
        "nemotron_tokens_per_sec_mean": _safe_stat(tok_nz, "mean", 2),
        "gpu_temp_c_min": _safe_stat(temps, "min", 2),
        "gpu_temp_c_max": _safe_stat(temps, "max", 2),
        "gpu_power_w_mean": _safe_stat(watts, "mean", 2),
        "gpu_power_w_max": _safe_stat(watts, "max", 2),
        "vram_peak_reserved_pre_empty_cache_mb_max": _safe_stat(pre_vram, "max", 2),
        "vram_reserved_post_empty_cache_mb_mean": _safe_stat(post_vram, "mean", 2),
        "vram_nvidia_smi_used_mb_max": _safe_stat(smi_vram, "max", 1),
        "vram_nvidia_smi_used_mb_final": _safe_stat(smi_vram, "last", 1),
    }


def _assemble_sealed_report(
    work_dir: Path,
    prompts_path: Path,
    report_path: Path,
    stage_ids: List[str],
    run_summary: Dict[str, Any],
    model_load_s: float,
) -> Dict[str, Any]:
    """Load all 6 verified micro-stage files and seal canonical REGISTER_M report."""
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
            "stage_sha256": sha256_file(stage_file),
        }
    report: Dict[str, Any] = {
        "schema": "VMAX_STAGE6_DKM_EMPIRICAL_BENCHMARK_REPORT_V1",
        "work_order": "WORK-ORDER-AG-30",
        "sync_id": "SYNC-30",
        "epistemic_register": "REGISTER_M",
        "bridge_reviewer_note": BROWSER_CRASH_GUARD_NOTE,
        "model_id": "NVIDIA-Nemotron-3-Nano-4B-BF16",
        "model_load_seconds": model_load_s,
        "prompts_dataset": str(prompts_path.relative_to(REPO_ROOT)),
        "prompts_dataset_sha256": sha256_file(prompts_path),
        "runner_summary": run_summary,
        "metrics_summary": _compute_confusion_and_metrics(all_records),
        "hardware_summary": _compute_hardware_summary(all_records),
        "stage_summaries": stage_summaries,
        "records": all_records,
    }
    report_sha = atomic_write_json(report_path, report)
    report["report_sha256"] = report_sha
    return report


def run_benchmark(
    prompts_path: Path = DEFAULT_PROMPTS_PATH,
    report_path: Path = DEFAULT_REPORT_PATH,
    work_dir: Path = DEFAULT_WORK_DIR,
    pause_file: Path = Path(DEFAULT_PAUSE_FILE),
) -> Dict[str, Any]:
    """Run all 6 pausable 10-prompt micro-stages via StageCheckpointRunner."""
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
        f"GPU: {_query_gpu_snapshot()}",
        flush=True,
    )

    stages: List[StageSpec] = []
    stage_ids: List[str] = []
    for st in dataset["stages"]:
        sid = str(st["stage_id"])
        stage_ids.append(sid)

        def _make_action(stage_obj: Dict[str, Any]) -> Callable[[Path], Dict[str, object]]:
            def _run(_artifact_path: Path) -> Dict[str, object]:
                t_s = time.perf_counter()
                recs = [
                    _evaluate_one_prompt(extractor, ctrl, engine, stage_obj, item)
                    for item in stage_obj["prompts"]
                ]
                dt_s = round(time.perf_counter() - t_s, 2)
                ok_n = sum(1 for r in recs if r["routing_state_correct"])
                print(
                    f"[SYNC-30] Stage {stage_obj['stage_id']} DONE ({ok_n}/{len(recs)} state match, {dt_s}s)",
                    flush=True,
                )
                return {
                    "stage_id": stage_obj["stage_id"],
                    "elapsed_s": dt_s,
                    "records": recs,
                }

            return _run

        stages.append(
            StageSpec(
                stage_id=sid,
                description=str(st["description"]),
                artifact_name=f"{sid}.json",
                action=_make_action(st),
            )
        )

    runner = StageCheckpointRunner(work_dir=work_dir, pause_file=pause_file)
    runner.install_signal_handlers()
    summary = runner.run_pipeline(stages)
    if summary.status != "COMPLETE":
        print(
            f"[V-MAX-12] PAUSED CLEANLY ({summary.paused_reason}). "
            f"Completed: {summary.completed_stages} | Pending: {summary.pending_stages}",
            flush=True,
        )
        return summary.to_dict()

    report = _assemble_sealed_report(
        work_dir=work_dir,
        prompts_path=prompts_path,
        report_path=report_path,
        stage_ids=stage_ids,
        run_summary=summary.to_dict(),
        model_load_s=engine.load_seconds,
    )
    print(
        f"[SYNC-30] SEALED REPORT -> {report_path} | "
        f"acc={report['metrics_summary']['end_to_end_state_accuracy_pct']}% | "
        f"fpr={report['metrics_summary']['benign_control_fpr_pct']}% | "
        f"recheck_pass={report['metrics_summary']['island1_recheck_pass_rate_pct']}%",
        flush=True,
    )
    return report


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point for live pausable 60-prompt SYNC-30 benchmark."""
    parser = argparse.ArgumentParser(description="V-MAX-12 SYNC-30 60-Prompt Benchmark Runner")
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
