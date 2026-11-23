#!/usr/bin/env python3
"""
vmax_alpha/synth_runner.py

PQMS / V-MAX-12 (SYNC-30 / V5.0) — Autonomous Zero-Token Stage-Checkpoint Runner.

Designed for local execution on Node Alpha without active cloud-agent polling:
- Executes deterministic micro-stages with atomic SHA-256 checkpoints.
- Supports immediate graceful pause for night-quiet hours via a sentinel file
  (/tmp/vmax_synth.pause) or SIGTERM/SIGINT signals.
- Releases GPU cache (only if torch is already loaded) and exits cleanly (rc=0)
  so the workstation can be powered down with zero lost progress.
- Resumes deterministically by verifying SHA-256 digests of completed stages.

OP02-AST-clean: 0 semicolons, 0 tabs, flat functions (max McCabe CC <= 7).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

DEFAULT_PAUSE_FILE = "/tmp/vmax_synth.pause"
DEFAULT_MANIFEST_NAME = "checkpoint_manifest.json"


@dataclass(frozen=True)
class StageSpec:
    """Definition of one idempotent, checkpointable execution stage."""

    stage_id: str
    description: str
    artifact_name: str
    action: Callable[[Path], Dict[str, object]]


@dataclass(frozen=True)
class RunSummary:
    """Compact summary emitted after completion or clean night-quiet pause."""

    status: str
    completed_stages: List[str]
    skipped_verified: List[str]
    pending_stages: List[str]
    paused_reason: Optional[str]
    elapsed_ms: float
    manifest_path: str

    def to_dict(self) -> Dict[str, object]:
        """Serialize compact summary for telemetry and bridge handoff."""
        return {
            "status": self.status,
            "completed_stages": list(self.completed_stages),
            "skipped_verified": list(self.skipped_verified),
            "pending_stages": list(self.pending_stages),
            "paused_reason": self.paused_reason,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "manifest_path": self.manifest_path,
        }


def sha256_file(path: Path) -> str:
    """Compute hex SHA-256 digest of a local file in 64 KiB chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(65536)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_json(path: Path, payload: Dict[str, object]) -> str:
    """Atomically persist canonical JSON (tmp -> fsync -> replace) and hash it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    raw = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    with tmp_path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, path)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def release_gpu_cache_if_loaded() -> bool:
    """Release CUDA cache only when torch is already imported (zero cold import)."""
    torch_mod = sys.modules.get("torch")
    if torch_mod is None:
        return False
    cuda_mod = getattr(torch_mod, "cuda", None)
    if cuda_mod is None or not cuda_mod.is_available():
        return False
    cuda_mod.empty_cache()
    return True


def _load_manifest(path: Path) -> Dict[str, object]:
    """Load existing checkpoint manifest or return empty initialized structure."""
    if not path.exists():
        return {"version": "V5.0-SYNTH-RUNNER", "stages": {}}
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or not isinstance(data.get("stages"), dict):
        return {"version": "V5.0-SYNTH-RUNNER", "stages": {}}
    return data


def _is_stage_verified(
    work_dir: Path,
    spec: StageSpec,
    manifest: Dict[str, object],
) -> bool:
    """Return True iff stage artifact exists and matches recorded SHA-256."""
    stages_map = manifest.get("stages", {})
    entry = stages_map.get(spec.stage_id)
    if not isinstance(entry, dict):
        return False
    expected_sha = entry.get("artifact_sha256")
    artifact_path = work_dir / spec.artifact_name
    if not expected_sha or not artifact_path.exists():
        return False
    return sha256_file(artifact_path) == expected_sha


class StageCheckpointRunner:
    """
    Deterministic, pausable runner for local synthesis and benchmark pipelines.

    Checks for a pause sentinel or POSIX stop signal before every micro-stage
    so Node Alpha can be halted cleanly for night-quiet hours and resumed later
    without recomputing SHA-256-verified stages.
    """

    def __init__(
        self,
        work_dir: Path,
        pause_file: Path = Path(DEFAULT_PAUSE_FILE),
        manifest_name: str = DEFAULT_MANIFEST_NAME,
    ) -> None:
        self.work_dir = Path(work_dir)
        self.pause_file = Path(pause_file)
        self.manifest_path = self.work_dir / manifest_name
        self._stop_signal_name: Optional[str] = None

    def install_signal_handlers(self) -> None:
        """Install graceful SIGTERM/SIGINT handlers for clean stage-boundary stop."""
        signal.signal(signal.SIGTERM, self._handle_stop_signal)
        signal.signal(signal.SIGINT, self._handle_stop_signal)

    def _handle_stop_signal(self, signum: int, _frame: object) -> None:
        """Record stop signal so runner halts cleanly at the next boundary."""
        self._stop_signal_name = signal.Signals(signum).name

    def check_pause_requested(self) -> Optional[str]:
        """Return pause reason if sentinel file exists or stop signal arrived."""
        if self._stop_signal_name is not None:
            return f"SIGNAL:{self._stop_signal_name}"
        if self.pause_file.exists():
            return f"PAUSE_FILE:{self.pause_file}"
        return None

    def run_pipeline(self, stages: List[StageSpec]) -> RunSummary:
        """Execute stages sequentially with atomic checkpointing and clean pause."""
        t0 = time.perf_counter()
        self.work_dir.mkdir(parents=True, exist_ok=True)
        manifest = _load_manifest(self.manifest_path)
        completed: List[str] = []
        skipped: List[str] = []
        pending: List[str] = []
        paused_reason: Optional[str] = None

        for idx, spec in enumerate(stages):
            if _is_stage_verified(self.work_dir, spec, manifest):
                skipped.append(spec.stage_id)
                continue
            pause_hit = self.check_pause_requested()
            if pause_hit is not None:
                paused_reason = pause_hit
                pending = [item.stage_id for item in stages[idx:]]
                break
            self._execute_one_stage(spec, manifest)
            completed.append(spec.stage_id)

        release_gpu_cache_if_loaded()
        status = "PAUSED_CLEAN" if paused_reason is not None else "COMPLETE"
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        manifest["last_status"] = status
        manifest["last_paused_reason"] = paused_reason
        manifest["last_updated_epoch_s"] = round(time.time(), 3)
        atomic_write_json(self.manifest_path, manifest)
        return RunSummary(
            status=status,
            completed_stages=completed,
            skipped_verified=skipped,
            pending_stages=pending,
            paused_reason=paused_reason,
            elapsed_ms=elapsed_ms,
            manifest_path=str(self.manifest_path),
        )

    def _execute_one_stage(
        self,
        spec: StageSpec,
        manifest: Dict[str, object],
    ) -> None:
        """Run one stage, write its artifact atomically, and update manifest."""
        t_stage = time.perf_counter()
        artifact_path = self.work_dir / spec.artifact_name
        result_payload = spec.action(artifact_path)
        artifact_sha = atomic_write_json(artifact_path, result_payload)
        stage_ms = (time.perf_counter() - t_stage) * 1000.0
        stages_map = manifest.setdefault("stages", {})
        stages_map[spec.stage_id] = {
            "artifact_name": spec.artifact_name,
            "artifact_sha256": artifact_sha,
            "description": spec.description,
            "duration_ms": round(stage_ms, 3),
            "status": "VERIFIED",
        }
        atomic_write_json(self.manifest_path, manifest)


def _demo_stage_action(stage_label: str) -> Callable[[Path], Dict[str, object]]:
    """Build deterministic dry-run stage callback for CLI self-verification."""
    def _run(_artifact_path: Path) -> Dict[str, object]:
        return {"stage": stage_label, "mode": "dry_run", "ok": True}
    return _run


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point for night-quiet self-test or manifest status check."""
    parser = argparse.ArgumentParser(
        description="V-MAX-12 Autonomous Pausable Stage-Checkpoint Runner"
    )
    parser.add_argument("--work-dir", default="/tmp/vmax_synth_state")
    parser.add_argument("--pause-file", default=DEFAULT_PAUSE_FILE)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    runner = StageCheckpointRunner(Path(args.work_dir), Path(args.pause_file))
    runner.install_signal_handlers()
    if args.dry_run:
        stages = [
            StageSpec("01_preflight", "Preflight check", "01_preflight.json", _demo_stage_action("01_preflight")),
            StageSpec("02_compute", "Compute batch", "02_compute.json", _demo_stage_action("02_compute")),
            StageSpec("03_seal", "Seal summary", "03_seal.json", _demo_stage_action("03_seal")),
        ]
        summary = runner.run_pipeline(stages)
        print(json.dumps(summary.to_dict(), sort_keys=True))
        return 0
    manifest = _load_manifest(runner.manifest_path)
    print(json.dumps({"manifest_path": str(runner.manifest_path), "stages": list(manifest.get("stages", {}).keys())}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
