#!/usr/bin/env python3
"""
vmax_alpha/chip_fab_controller.py

PQMS / V-MAX-12 — Deterministic Start / Pause / Restart Controller for
IHP SG13G2 Chip Synthesis & Physical GDSII Fabrication Pipelines.

Design principles:
- Strict singleton lock (fcntl.flock) prevents duplicate competing EDA runs.
- Built directly on StageCheckpointRunner (atomic SHA-256 checkpoints):
  * start:            Launch pipeline or resume from last verified checkpoint
                      (or thaw a SIGSTOP-frozen run seamlessly).
  * pause:            Arm pause sentinel + send SIGTERM to runner PID so the
                      active EDA stage finishes cleanly, seals SHA-256, and
                      exits lossless (safe for overnight power-off).
  * pause --freeze:   Immediately SIGSTOP the entire EDA process group for
                      instant 0% CPU silence; resume anytime via `start`.
  * restart:          Cleanly stop any active run and relaunch from the last
                      verified checkpoint (or from Stage 00 with `--fresh`,
                      automatically backing up prior checkpoints first).
  * status:           Report live OS-verified state, PID, and completed stages.
- Zero GPU / PyTorch imports (torch_imported = False).

OP02-AST-clean: 0 semicolons, 0 tabs, flat helpers (max McCabe CC <= 6).
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from vmax_alpha.synth_runner import (
    DEFAULT_MANIFEST_NAME,
    DEFAULT_PAUSE_FILE,
    atomic_write_json,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WORK_DIR = Path.home() / "vmax_workspace" / "synth_state" / "v5_chip_fab_prod"
DEFAULT_LOG_PATH = Path("/tmp/vmax_chip_fab.log")
STATE_FILENAME = "controller_state.json"
LOCK_FILENAME = "controller.lock"


@dataclass(frozen=True)
class ChipFabConfig:
    """Immutable configuration for one managed chip fabrication workspace."""

    work_dir: Path = DEFAULT_WORK_DIR
    pause_file: Path = Path(DEFAULT_PAUSE_FILE)
    log_path: Path = DEFAULT_LOG_PATH
    pipeline_cmd: Optional[Tuple[str, ...]] = None
    stop_timeout_s: float = 10.0

    @property
    def state_path(self) -> Path:
        """Path to atomic controller PID/state file."""
        return self.work_dir / STATE_FILENAME

    @property
    def lock_path(self) -> Path:
        """Path to advisory POSIX mutex file."""
        return self.work_dir / LOCK_FILENAME

    @property
    def manifest_path(self) -> Path:
        """Path to StageCheckpointRunner SHA-256 checkpoint manifest."""
        return self.work_dir / DEFAULT_MANIFEST_NAME


def _utc_now_iso() -> str:
    """Return compact UTC ISO-8601 timestamp."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _utc_compact_stamp() -> str:
    """Return filesystem-safe UTC timestamp for backup directories."""
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")


def _build_eda_env() -> Dict[str, str]:
    """Assemble full Node Alpha EDA + PDK environment without importing torch."""
    home = Path.home()
    env = os.environ.copy()
    tool_dirs = [
        home / "vmax_310" / "bin",
        home / ".local" / "oss-cad-suite" / "bin",
        home / ".local" / "openroad_2024" / "bin",
        home / ".local" / "klayout_official" / "bin",
        home / ".local" / "signoff_env" / "bin",
        home / ".elan" / "bin",
    ]
    prefix = ":".join(str(d) for d in tool_dirs if d.is_dir())
    if prefix:
        env["PATH"] = f"{prefix}:{env.get('PATH', '')}"
    qt_plugins = home / ".local" / "klayout_official" / "usr/lib/x86_64-linux-gnu/qt5/plugins"
    if qt_plugins.is_dir():
        env.setdefault("QT_PLUGIN_PATH", str(qt_plugins))
    env.setdefault("PDK_ROOT", str(home / "vmax_workspace" / "pdk" / "IHP-Open-PDK"))
    env.setdefault("PDK", "ihp-sg13g2")
    oqs_lib = home / ".local" / "liboqs" / "lib"
    if oqs_lib.is_dir():
        prev_ld = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = f"{oqs_lib}:{prev_ld}" if prev_ld else str(oqs_lib)
        env.setdefault("OQS_INSTALL_PATH", str(home / ".local" / "liboqs"))
    return env


def _read_proc_state_char(pid: int) -> Optional[str]:
    """Read Linux /proc/<pid>/stat process state letter (R/S/D/T/Z) or None."""
    stat_path = Path(f"/proc/{pid}/stat")
    try:
        raw = stat_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    rparen = raw.rfind(")")
    if rparen < 0 or rparen + 2 >= len(raw):
        return None
    return raw[rparen + 2]


def _is_pid_alive(pid: int) -> bool:
    """Return True iff pid exists and is not a zombie."""
    if pid <= 0:
        return False
    state_ch = _read_proc_state_char(pid)
    if state_ch is not None:
        return state_ch != "Z"
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _is_pid_stopped(pid: int) -> bool:
    """Return True iff pid is currently frozen via SIGSTOP (state T/t)."""
    if pid <= 0:
        return False
    state_ch = _read_proc_state_char(pid)
    return state_ch in ("T", "t")


def _read_json_safe(path: Path) -> Dict[str, object]:
    """Read JSON object from path or return empty dict on missing/corrupt file."""
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _read_checkpoint_progress(manifest_path: Path) -> Tuple[List[str], Optional[str]]:
    """Return (sorted completed stage IDs, last_status) from checkpoint manifest."""
    data = _read_json_safe(manifest_path)
    stages = data.get("stages")
    done = sorted(stages.keys()) if isinstance(stages, dict) else []
    last_st = data.get("last_status")
    return done, str(last_st) if isinstance(last_st, str) else None


def _tail_lines(log_path: Path, count: int = 5) -> List[str]:
    """Return the last `count` non-empty lines of log_path if present."""
    if not log_path.is_file():
        return []
    try:
        lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []
    return [ln for ln in lines if ln.strip()][-count:]


def _reap_if_child(pid: int, tracked: Optional[Dict[int, subprocess.Popen]] = None) -> None:
    """Reap pid non-blockingly if it is a direct child of the current process."""
    if tracked and pid in tracked:
        if tracked[pid].poll() is not None:
            tracked.pop(pid, None)
        return
    try:
        os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        pass


def _wait_for_exit(pid: int, timeout_s: float, tracked: Optional[Dict[int, subprocess.Popen]] = None) -> bool:
    """Poll until pid terminates or timeout expires; returns True if exited."""
    deadline = time.monotonic() + max(0.0, timeout_s)
    while time.monotonic() < deadline:
        _reap_if_child(pid, tracked)
        if not _is_pid_alive(pid):
            return True
        time.sleep(0.1)
    _reap_if_child(pid, tracked)
    return not _is_pid_alive(pid)


def _signal_group_safe(pgid: int, sig: int) -> None:
    """Deliver a POSIX signal to process group `pgid`, ignoring ESRCH."""
    if pgid <= 0:
        return
    try:
        os.killpg(pgid, sig)
    except ProcessLookupError:
        pass


def _signal_pid_safe(pid: int, sig: int) -> None:
    """Deliver a POSIX signal to single process `pid`, ignoring ESRCH."""
    if pid <= 0:
        return
    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        pass


def _archive_checkpoints(work_dir: Path) -> Optional[str]:
    """Move existing stage JSONs and manifest into a timestamped backup folder."""
    skip_names = {STATE_FILENAME, LOCK_FILENAME}
    to_move = [
        p for p in sorted(work_dir.iterdir())
        if p.is_file() and p.suffix == ".json" and p.name not in skip_names
    ]
    if not to_move:
        return None
    backup_dir = work_dir / "backups" / f"backup_{_utc_compact_stamp()}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    for item in to_move:
        shutil.move(str(item), str(backup_dir / item.name))
    return str(backup_dir)


def _default_pipeline_cmd(config: ChipFabConfig) -> List[str]:
    """Build default V5.0-TOP-GDSII pipeline command."""
    if config.pipeline_cmd:
        return list(config.pipeline_cmd)
    py_venv = Path.home() / "vmax_310" / "bin" / "python3"
    py_bin = str(py_venv) if py_venv.is_file() else sys.executable
    return [
        py_bin,
        "-m",
        "vmax_alpha.v5_top_gdsii_pipeline",
        "--work-dir",
        str(config.work_dir),
        "--pause-file",
        str(config.pause_file),
    ]


class ChipFabController:
    """Deterministic Start / Pause / Restart controller for chip fabrication."""

    def __init__(self, config: Optional[ChipFabConfig] = None) -> None:
        self.config = config or ChipFabConfig()
        self._spawned: Dict[int, subprocess.Popen] = {}

    @contextlib.contextmanager
    def _locked(self) -> Iterator[None]:
        """Acquire exclusive POSIX file lock around state transitions."""
        self.config.work_dir.mkdir(parents=True, exist_ok=True)
        with self.config.lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _inspect_unlocked(self) -> Dict[str, object]:
        """Compute live OS-verified status without mutating process state."""
        saved = _read_json_safe(self.config.state_path)
        pid = int(saved.get("pid", 0)) if isinstance(saved.get("pid"), int) else 0
        pgid = int(saved.get("pgid", pid)) if isinstance(saved.get("pgid"), int) else pid
        alive = _is_pid_alive(pid)
        frozen = alive and _is_pid_stopped(pid)
        pause_armed = self.config.pause_file.exists()
        done_stages, manifest_status = _read_checkpoint_progress(self.config.manifest_path)

        state = self._resolve_state_label(alive, frozen, pause_armed, manifest_status)
        return {
            "state": state,
            "pid": pid if alive else None,
            "pgid": pgid if alive else None,
            "alive": alive,
            "frozen": frozen,
            "pause_sentinel_armed": pause_armed,
            "pause_file": str(self.config.pause_file),
            "work_dir": str(self.config.work_dir),
            "log_path": str(self.config.log_path),
            "completed_stages": done_stages,
            "completed_count": len(done_stages),
            "manifest_last_status": manifest_status,
            "started_utc": saved.get("started_utc"),
            "last_action_utc": saved.get("last_action_utc"),
            "log_tail": _tail_lines(self.config.log_path, count=5),
        }

    @staticmethod
    def _resolve_state_label(
        alive: bool,
        frozen: bool,
        pause_armed: bool,
        manifest_status: Optional[str],
    ) -> str:
        """Map OS liveness, freeze bit, pause file, and manifest to canonical state."""
        if frozen:
            return "FROZEN"
        if alive:
            return "PAUSING" if pause_armed else "RUNNING"
        if manifest_status == "COMPLETE":
            return "COMPLETED"
        if pause_armed or manifest_status == "PAUSED_CLEAN":
            return "PAUSED"
        return "IDLE"

    def status(self) -> Dict[str, object]:
        """Return live verified status snapshot."""
        with self._locked():
            return self._inspect_unlocked()

    def _spawn_worker_unlocked(self, action_label: str) -> Dict[str, object]:
        """Clear pause sentinel, spawn detached pipeline worker, and persist state."""
        if self.config.pause_file.exists():
            self.config.pause_file.unlink()
        self.config.work_dir.mkdir(parents=True, exist_ok=True)
        self.config.log_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = _default_pipeline_cmd(self.config)
        now = _utc_now_iso()
        with self.config.log_path.open("a", encoding="utf-8") as log_handle:
            log_handle.write(f"\n=== [V-MAX-12 CHIP-CTL {action_label}] {now} ===\n")
            log_handle.flush()
            proc = subprocess.Popen(
                cmd,
                cwd=str(REPO_ROOT),
                env=_build_eda_env(),
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )
        self._spawned[proc.pid] = proc
        pgid = os.getpgid(proc.pid)
        atomic_write_json(
            self.config.state_path,
            {
                "pid": proc.pid,
                "pgid": pgid,
                "cmd": cmd,
                "started_utc": now,
                "last_action": action_label,
                "last_action_utc": now,
                "work_dir": str(self.config.work_dir),
                "log_path": str(self.config.log_path),
            },
        )
        snap = self._inspect_unlocked()
        snap["action"] = action_label
        return snap

    def start(self) -> Dict[str, object]:
        """Start chip fabrication, resume from checkpoint, or thaw frozen worker."""
        with self._locked():
            cur = self._inspect_unlocked()
            if cur["frozen"] and isinstance(cur["pgid"], int):
                if self.config.pause_file.exists():
                    self.config.pause_file.unlink()
                _signal_group_safe(cur["pgid"], signal.SIGCONT)
                snap = self._inspect_unlocked()
                snap["action"] = "RESUMED_FROM_FREEZE"
                return snap
            if cur["alive"]:
                if self.config.pause_file.exists():
                    self.config.pause_file.unlink()
                snap = self._inspect_unlocked()
                snap["action"] = "ALREADY_RUNNING"
                return snap
            return self._spawn_worker_unlocked("STARTED")

    def pause(self, freeze: bool = False, wait_s: float = 5.0) -> Dict[str, object]:
        """Pause cleanly after current stage (default) or freeze immediately (--freeze)."""
        with self._locked():
            cur = self._inspect_unlocked()
            self.config.pause_file.parent.mkdir(parents=True, exist_ok=True)
            self.config.pause_file.write_text(_utc_now_iso() + "\n", encoding="utf-8")
            if not cur["alive"]:
                snap = self._inspect_unlocked()
                snap["action"] = "PAUSE_ARMED_IDLE"
                return snap
            pid = int(cur["pid"])
            pgid = int(cur["pgid"])
            if freeze:
                _signal_group_safe(pgid, signal.SIGSTOP)
                time.sleep(0.05)
                snap = self._inspect_unlocked()
                snap["action"] = "FROZEN_IMMEDIATE"
                return snap
            if cur["frozen"]:
                _signal_group_safe(pgid, signal.SIGCONT)
            _signal_pid_safe(pid, signal.SIGTERM)
            exited = _wait_for_exit(pid, wait_s, self._spawned)
            snap = self._inspect_unlocked()
            snap["action"] = "PAUSED_CLEAN" if exited else "PAUSE_SIGNALED_DRAINING_STAGE"
            return snap

    def _stop_active_worker_unlocked(self, wait_s: float) -> bool:
        """Stop active/frozen worker cleanly, escalating to process group if needed."""
        cur = self._inspect_unlocked()
        if not cur["alive"]:
            return True
        pid = int(cur["pid"])
        pgid = int(cur["pgid"])
        self.config.pause_file.parent.mkdir(parents=True, exist_ok=True)
        self.config.pause_file.write_text(_utc_now_iso() + "\n", encoding="utf-8")
        if cur["frozen"]:
            _signal_group_safe(pgid, signal.SIGCONT)
        _signal_pid_safe(pid, signal.SIGTERM)
        if _wait_for_exit(pid, wait_s, self._spawned):
            return True
        _signal_group_safe(pgid, signal.SIGTERM)
        if _wait_for_exit(pid, 3.0, self._spawned):
            return True
        _signal_group_safe(pgid, signal.SIGKILL)
        return _wait_for_exit(pid, 2.0, self._spawned)

    def restart(self, fresh: bool = False, wait_s: Optional[float] = None) -> Dict[str, object]:
        """Stop any running job cleanly and restart (preserving or archiving checkpoints)."""
        timeout = self.config.stop_timeout_s if wait_s is None else wait_s
        with self._locked():
            self._stop_active_worker_unlocked(timeout)
            backup_path: Optional[str] = None
            if fresh:
                backup_path = _archive_checkpoints(self.config.work_dir)
            label = "RESTARTED_FRESH" if fresh else "RESTARTED_FROM_CHECKPOINT"
            snap = self._spawn_worker_unlocked(label)
            snap["backup_dir"] = backup_path
            return snap


def _format_human_status(snap: Dict[str, object]) -> str:
    """Format concise human-readable German status receipt for terminal output."""
    lines = [
        f"[V-MAX-12 CHIP-CTL] Aktion:  {snap.get('action', 'STATUS')}",
        f"[V-MAX-12 CHIP-CTL] Zustand: {snap['state']} | PID: {snap['pid'] or '-'}",
        f"[V-MAX-12 CHIP-CTL] Stages:  {snap['completed_count']} verifiziert ({', '.join(snap['completed_stages']) or 'noch keine'})",
        f"[V-MAX-12 CHIP-CTL] Pause:   {'AKTIV' if snap['pause_sentinel_armed'] else 'aus'} ({snap['pause_file']})",
        f"[V-MAX-12 CHIP-CTL] WorkDir: {snap['work_dir']}",
        f"[V-MAX-12 CHIP-CTL] Log:     {snap['log_path']}",
    ]
    if snap.get("backup_dir"):
        lines.append(f"[V-MAX-12 CHIP-CTL] Backup:  {snap['backup_dir']}")
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    """Create CLI argument parser for start / pause / restart / status."""
    parser = argparse.ArgumentParser(
        description="V-MAX-12 Chip Fabrication Controller (Start / Pause / Restart)"
    )
    parser.add_argument("--work-dir", default=os.environ.get("VMAX_CHIP_WORK_DIR", str(DEFAULT_WORK_DIR)))
    parser.add_argument("--pause-file", default=os.environ.get("VMAX_SYNTH_PAUSE_FILE", DEFAULT_PAUSE_FILE))
    parser.add_argument("--log-path", default=os.environ.get("VMAX_CHIP_LOG_PATH", str(DEFAULT_LOG_PATH)))
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("start", help="Start or resume chip fabrication")
    p_pause = sub.add_parser("pause", help="Pause chip fabrication cleanly")
    p_pause.add_argument("--freeze", action="store_true", help="Immediate SIGSTOP freeze (0% CPU)")
    p_pause.add_argument("--wait-s", type=float, default=5.0)
    p_restart = sub.add_parser("restart", help="Cleanly stop and restart chip fabrication")
    p_restart.add_argument("--fresh", action="store_true", help="Archive checkpoints and restart from Stage 00")
    p_restart.add_argument("--wait-s", type=float, default=10.0)
    sub.add_parser("status", help="Show live chip fabrication status")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point for chip fabrication Start / Pause / Restart control."""
    args = _build_parser().parse_args(argv)
    cfg = ChipFabConfig(
        work_dir=Path(args.work_dir),
        pause_file=Path(args.pause_file),
        log_path=Path(args.log_path),
    )
    ctl = ChipFabController(cfg)
    if args.command == "start":
        snap = ctl.start()
    elif args.command == "pause":
        snap = ctl.pause(freeze=bool(args.freeze), wait_s=float(args.wait_s))
    elif args.command == "restart":
        snap = ctl.restart(fresh=bool(args.fresh), wait_s=float(args.wait_s))
    else:
        snap = ctl.status()
    if args.json:
        print(json.dumps(snap, indent=2, sort_keys=True))
    else:
        print(_format_human_status(snap))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
