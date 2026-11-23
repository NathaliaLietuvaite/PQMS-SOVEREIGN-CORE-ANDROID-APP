#!/usr/bin/env python3
"""
vmax_alpha/gpu_vram_guard.py

PQMS / V-MAX-12 (SYNC-30b / V5.0) — Hard 14,900 MiB VRAM Ceiling,
Single-Owner GPU Lock, Zero-Spillover Allocator Policy & WSL2 Telemetry Guard.

Prevents Windows WDDM / WSL2 PCIe system-RAM spillover (observed at 5.09 GiB
dynamic D3D memory with 1.29% GDDR6 controller load during SYNC-30) by:
1. Enforcing a strict total-GPU ceiling (<= 14,900 MiB on 16,380 MiB RTX 4060 Ti).
2. Reserving >= 1,500 MiB for Windows DWM / Desktop / Antigravity host processes,
   capping the PyTorch process at fraction <= 0.815 (~13,350 MiB).
3. Providing a non-blocking POSIX flock (/tmp/vmax_gpu_owner.lock) so two
   Nemotron-3-Nano-4B instances can never collide in VRAM simultaneously.
4. Resolving nvidia-smi reliably under WSL2 (/usr/lib/wsl/lib/nvidia-smi).

OP02-AST-clean: 0 semicolons, 0 tabs, flat functions (max McCabe CC <= 6).
"""

from __future__ import annotations

import fcntl
import gc
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, TextIO

DEFAULT_TOTAL_VRAM_MB = 16380.0
DEFAULT_HARD_CEILING_MB = 14900.0
DEFAULT_HOST_RESERVE_MB = 1500.0
DEFAULT_MAX_FRACTION = 0.815
DEFAULT_LOCK_PATH = "/tmp/vmax_gpu_owner.lock"
DEFAULT_ALLOC_CONF = "expandable_segments:True,max_split_size_mb:128"
WSL_NVIDIA_SMI = "/usr/lib/wsl/lib/nvidia-smi"


@dataclass(frozen=True)
class VramBudgetSpec:
    """Deterministic VRAM ceiling parameters (REGISTER_D)."""

    physical_total_mb: float = DEFAULT_TOTAL_VRAM_MB
    system_hard_ceiling_mb: float = DEFAULT_HARD_CEILING_MB
    host_desktop_reserve_mb: float = DEFAULT_HOST_RESERVE_MB
    max_process_fraction: float = DEFAULT_MAX_FRACTION

    def process_cap_mb(self) -> float:
        """Compute maximum allowed VRAM in MiB for the Python/PyTorch process."""
        budget_mb = max(0.0, self.system_hard_ceiling_mb - self.host_desktop_reserve_mb)
        frac_cap_mb = self.physical_total_mb * self.max_process_fraction
        return min(budget_mb, frac_cap_mb)

    def effective_fraction(self) -> float:
        """Return safe PyTorch memory fraction strictly below 14,900 MiB total."""
        if self.physical_total_mb <= 0.0:
            return 0.0
        raw_frac = self.process_cap_mb() / self.physical_total_mb
        return round(min(self.max_process_fraction, max(0.05, raw_frac)), 4)


@dataclass(frozen=True)
class GpuTelemetrySnapshot:
    """Live GPU telemetry queried via nvidia-smi (REGISTER_M)."""

    available: bool
    nvidia_smi_path: Optional[str]
    vram_used_mb: float
    vram_total_mb: float
    gpu_temp_c: float
    gpu_power_w: float
    mem_util_pct: float
    gpu_util_pct: float

    def within_hard_ceiling(self, ceiling_mb: float = DEFAULT_HARD_CEILING_MB) -> bool:
        """Return True iff telemetry is valid and VRAM stays <= ceiling_mb."""
        return self.available and self.vram_used_mb <= ceiling_mb

    def to_dict(self) -> Dict[str, object]:
        """Serialize snapshot for JSON reports and /api/dolphin/status."""
        return {
            "available": self.available,
            "nvidia_smi_path": self.nvidia_smi_path,
            "vram_used_mb": round(self.vram_used_mb, 1),
            "vram_total_mb": round(self.vram_total_mb, 1),
            "gpu_temp_c": round(self.gpu_temp_c, 1),
            "gpu_power_w": round(self.gpu_power_w, 2),
            "mem_util_pct": round(self.mem_util_pct, 1),
            "gpu_util_pct": round(self.gpu_util_pct, 1),
            "within_14900mb_cap": self.within_hard_ceiling(DEFAULT_HARD_CEILING_MB),
        }


def _is_executable(path: str) -> bool:
    """Return True if path exists and is executable."""
    return os.path.isfile(path) and os.access(path, os.X_OK)


def resolve_nvidia_smi_binary() -> Optional[str]:
    """Find nvidia-smi including the WSL2 /usr/lib/wsl/lib fallback path."""
    candidates = (WSL_NVIDIA_SMI, "/usr/bin/nvidia-smi", "/usr/local/bin/nvidia-smi")
    for candidate in candidates:
        if _is_executable(candidate):
            return candidate
    return shutil.which("nvidia-smi")


def _parse_float_safe(token: str) -> float:
    """Parse numeric nvidia-smi field, returning 0.0 on N/A."""
    cleaned = token.strip()
    if not cleaned or cleaned.upper() in ("N/A", "[N/A]", "NONE"):
        return 0.0
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _empty_snapshot(smi: Optional[str]) -> GpuTelemetrySnapshot:
    """Build unavailable telemetry snapshot."""
    return GpuTelemetrySnapshot(False, smi, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)


def _run_nvidia_smi_csv(smi: str) -> Optional[str]:
    """Execute nvidia-smi CSV query and return first stdout line or None."""
    cmd = [
        smi,
        "--query-gpu=memory.used,memory.total,temperature.gpu,power.draw,"
        "utilization.memory,utilization.gpu",
        "--format=csv,noheader,nounits",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3.0)
    except (OSError, subprocess.SubprocessError):
        return None
    output = proc.stdout.strip()
    if proc.returncode != 0 or not output:
        return None
    return output.splitlines()[0]


def query_gpu_telemetry(binary_path: Optional[str] = None) -> GpuTelemetrySnapshot:
    """Query live RTX GPU VRAM, temperature, power, and controller load."""
    smi = binary_path if binary_path is not None else resolve_nvidia_smi_binary()
    if smi is None:
        return _empty_snapshot(None)
    line = _run_nvidia_smi_csv(smi)
    if line is None:
        return _empty_snapshot(smi)
    parts = [p.strip() for p in line.split(",")]
    if len(parts) < 6:
        return _empty_snapshot(smi)
    return GpuTelemetrySnapshot(
        available=True,
        nvidia_smi_path=smi,
        vram_used_mb=_parse_float_safe(parts[0]),
        vram_total_mb=_parse_float_safe(parts[1]),
        gpu_temp_c=_parse_float_safe(parts[2]),
        gpu_power_w=_parse_float_safe(parts[3]),
        mem_util_pct=_parse_float_safe(parts[4]),
        gpu_util_pct=_parse_float_safe(parts[5]),
    )


def configure_allocator_env() -> str:
    """Set PYTORCH_CUDA_ALLOC_CONF if unset to eliminate caching fragmentation."""
    current = os.environ.get("PYTORCH_CUDA_ALLOC_CONF", "").strip()
    if not current:
        os.environ["PYTORCH_CUDA_ALLOC_CONF"] = DEFAULT_ALLOC_CONF
        return DEFAULT_ALLOC_CONF
    return current


def apply_torch_vram_hard_cap(
    budget: Optional[VramBudgetSpec] = None,
    device_index: int = 0,
) -> Dict[str, object]:
    """
    Apply PyTorch per-process VRAM fraction cap only if torch is loaded.

    Never cold-imports torch so CPU-only modules retain 0 MB VRAM delta.
    """
    spec = budget if budget is not None else VramBudgetSpec()
    alloc_conf = configure_allocator_env()
    frac = spec.effective_fraction()
    torch_mod = sys.modules.get("torch")
    if torch_mod is None:
        return {
            "applied": False,
            "reason": "TORCH_NOT_LOADED",
            "effective_fraction": frac,
            "process_cap_mb": round(spec.process_cap_mb(), 1),
            "alloc_conf": alloc_conf,
        }
    cuda_mod = getattr(torch_mod, "cuda", None)
    if cuda_mod is None or not cuda_mod.is_available():
        return {
            "applied": False,
            "reason": "CUDA_UNAVAILABLE",
            "effective_fraction": frac,
            "process_cap_mb": round(spec.process_cap_mb(), 1),
            "alloc_conf": alloc_conf,
        }
    cuda_mod.set_per_process_memory_fraction(frac, device_index)
    return {
        "applied": True,
        "reason": "HARD_CAP_ACTIVE",
        "effective_fraction": frac,
        "process_cap_mb": round(spec.process_cap_mb(), 1),
        "alloc_conf": alloc_conf,
    }


def release_turn_vram() -> bool:
    """Run GC and release cached CUDA blocks after each inference turn."""
    gc.collect()
    torch_mod = sys.modules.get("torch")
    if torch_mod is None:
        return False
    cuda_mod = getattr(torch_mod, "cuda", None)
    if cuda_mod is None or not cuda_mod.is_available():
        return False
    cuda_mod.empty_cache()
    if hasattr(cuda_mod, "ipc_collect"):
        cuda_mod.ipc_collect()
    return True


class SingleGpuOwnerLock:
    """
    Non-blocking advisory file lock ensuring only one Nemotron-3-Nano-4B
    process owns the RTX 4060 Ti at any time (prevents 2x 9.7 GB collisions).
    """

    def __init__(self, lock_path: Path = Path(DEFAULT_LOCK_PATH)) -> None:
        self.lock_path = Path(lock_path)
        self._handle: Optional[TextIO] = None

    def acquire(self, owner_tag: str = "vmax_alpha") -> bool:
        """Acquire exclusive lock or return False immediately if busy."""
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.lock_path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            return False
        handle.seek(0)
        handle.truncate()
        handle.write(f"pid={os.getpid()} owner={owner_tag}\n")
        handle.flush()
        self._handle = handle
        return True

    def release(self) -> None:
        """Release exclusive GPU ownership lock cleanly."""
        if self._handle is None:
            return
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()
            self._handle = None

    def read_current_owner(self) -> str:
        """Read current owner description for clear operator diagnostics."""
        if not self.lock_path.exists():
            return "NONE"
        return self.lock_path.read_text(encoding="utf-8").strip() or "UNKNOWN"
