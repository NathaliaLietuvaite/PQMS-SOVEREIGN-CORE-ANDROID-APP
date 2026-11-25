#!/usr/bin/env python3
"""
vmax_alpha/tests/test_chip_fab_controller.py

Deterministic lifecycle tests for vmax_alpha/chip_fab_controller.py:
- Start + singleton duplicate-launch rejection (ALREADY_RUNNING)
- Graceful checkpoint Pause (sentinel + SIGTERM) + Resume without data loss
- Immediate SIGSTOP Freeze (`pause --freeze`) + seamless SIGCONT thaw (`start`)
- Clean Restart (checkpoint-preserving) and Fresh Restart (`--fresh` with backup)
- Zero PyTorch import (`torch_imported = False`)

OP02-AST-clean: 0 semicolons, 0 tabs, flat helpers (max McCabe CC <= 3).
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Tuple

from vmax_alpha.chip_fab_controller import (
    ChipFabConfig,
    ChipFabController,
    _is_pid_alive,
)

DUMMY_WORKER_CODE = (
    "import os, pathlib, signal, sys, time\n"
    "work = pathlib.Path(sys.argv[1])\n"
    "pause_p = pathlib.Path(sys.argv[2])\n"
    "stop_flag = [False]\n"
    "def on_sig(_s, _f): stop_flag[0] = True\n"
    "signal.signal(signal.SIGTERM, on_sig)\n"
    "signal.signal(signal.SIGINT, on_sig)\n"
    "(work / 'stage_00.json').write_text('{\"ok\": true}\\n', encoding='utf-8')\n"
    "(work / 'checkpoint_manifest.json').write_text("
    "'{\"stages\": {\"00_preflight\": {\"status\": \"VERIFIED\"}}, \"last_status\": \"RUNNING\"}\\n', encoding='utf-8')\n"
    "for _ in range(200):\n"
    "    if stop_flag[0] or pause_p.exists():\n"
    "        (work / 'checkpoint_manifest.json').write_text("
    "'{\"stages\": {\"00_preflight\": {\"status\": \"VERIFIED\"}}, \"last_status\": \"PAUSED_CLEAN\"}\\n', encoding='utf-8')\n"
    "        sys.exit(0)\n"
    "    time.sleep(0.05)\n"
)


def _make_controller(tmp_dir: Path) -> Tuple[ChipFabController, ChipFabConfig]:
    """Create isolated controller wired to a fast deterministic dummy worker."""
    work_dir = tmp_dir / "work"
    pause_file = tmp_dir / "pause.sentinel"
    log_path = tmp_dir / "chip.log"
    worker_py = tmp_dir / "dummy_worker.py"
    worker_py.write_text(DUMMY_WORKER_CODE, encoding="utf-8")
    cfg = ChipFabConfig(
        work_dir=work_dir,
        pause_file=pause_file,
        log_path=log_path,
        pipeline_cmd=(sys.executable, str(worker_py), str(work_dir), str(pause_file)),
        stop_timeout_s=3.0,
    )
    return ChipFabController(cfg), cfg


class TestChipFabController(unittest.TestCase):
    """Verify Start / Pause / Freeze / Restart / Status invariants."""

    def test_start_idempotent_pause_and_resume(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ctl, cfg = _make_controller(Path(td))
            self.assertEqual(ctl.status()["state"], "IDLE")

            s1 = ctl.start()
            self.assertEqual(s1["action"], "STARTED")
            self.assertEqual(s1["state"], "RUNNING")
            pid1 = int(s1["pid"])
            self.assertTrue(_is_pid_alive(pid1))

            # Duplicate start must NOT launch a second process
            s2 = ctl.start()
            self.assertEqual(s2["action"], "ALREADY_RUNNING")
            self.assertEqual(s2["pid"], pid1)

            # Wait briefly for dummy stage checkpoint, then pause cleanly
            time.sleep(0.25)
            p1 = ctl.pause(freeze=False, wait_s=3.0)
            self.assertEqual(p1["action"], "PAUSED_CLEAN")
            self.assertEqual(p1["state"], "PAUSED")
            self.assertFalse(_is_pid_alive(pid1))
            self.assertIn("00_preflight", p1["completed_stages"])
            self.assertTrue(cfg.pause_file.exists())

            # Resume starts a fresh PID and clears pause sentinel while keeping checkpoint
            s3 = ctl.start()
            self.assertEqual(s3["action"], "STARTED")
            self.assertEqual(s3["state"], "RUNNING")
            self.assertFalse(cfg.pause_file.exists())
            self.assertIn("00_preflight", s3["completed_stages"])
            ctl.pause(freeze=False, wait_s=3.0)

    def test_freeze_and_thaw_via_start(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ctl, _ = _make_controller(Path(td))
            s1 = ctl.start()
            pid1 = int(s1["pid"])

            f1 = ctl.pause(freeze=True)
            self.assertEqual(f1["action"], "FROZEN_IMMEDIATE")
            self.assertEqual(f1["state"], "FROZEN")
            self.assertEqual(f1["pid"], pid1)

            r1 = ctl.start()
            self.assertEqual(r1["action"], "RESUMED_FROM_FREEZE")
            self.assertEqual(r1["state"], "RUNNING")
            self.assertEqual(r1["pid"], pid1)

            ctl.pause(freeze=False, wait_s=3.0)

    def test_restart_checkpoint_and_restart_fresh_with_backup(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ctl, cfg = _make_controller(Path(td))
            s1 = ctl.start()
            pid1 = int(s1["pid"])
            time.sleep(0.25)

            # Normal restart stops pid1, launches pid2, preserves checkpoints
            r1 = ctl.restart(fresh=False, wait_s=3.0)
            self.assertEqual(r1["action"], "RESTARTED_FROM_CHECKPOINT")
            self.assertEqual(r1["state"], "RUNNING")
            self.assertFalse(_is_pid_alive(pid1))
            pid2 = int(r1["pid"])
            self.assertNotEqual(pid2, pid1)
            self.assertIsNone(r1["backup_dir"])
            self.assertIn("00_preflight", r1["completed_stages"])

            # Fresh restart archives prior checkpoints before relaunching
            time.sleep(0.25)
            r2 = ctl.restart(fresh=True, wait_s=3.0)
            self.assertEqual(r2["action"], "RESTARTED_FRESH")
            self.assertEqual(r2["state"], "RUNNING")
            self.assertIsNotNone(r2["backup_dir"])
            backup_dir = Path(str(r2["backup_dir"]))
            self.assertTrue((backup_dir / "checkpoint_manifest.json").is_file())
            self.assertTrue((backup_dir / "stage_00.json").is_file())
            self.assertTrue(cfg.log_path.is_file())

            ctl.pause(freeze=False, wait_s=3.0)

    def test_zero_torch_import_isolation(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys, vmax_alpha.chip_fab_controller; assert 'torch' not in sys.modules",
            ],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)


if __name__ == "__main__":
    unittest.main()
