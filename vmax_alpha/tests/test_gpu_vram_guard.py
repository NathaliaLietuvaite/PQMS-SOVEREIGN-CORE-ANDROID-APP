#!/usr/bin/env python3
"""
vmax_alpha/tests/test_gpu_vram_guard.py

Deterministic unit tests for SYNC-30b Hard 14,900 MiB VRAM Ceiling,
Single-Owner GPU Lock, and WSL2 nvidia-smi Telemetry Guard.
OP02-AST-clean: 0 semicolons, 0 tabs, flat test methods.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

try:
    from vmax_alpha.gpu_vram_guard import (
        DEFAULT_HARD_CEILING_MB,
        GpuTelemetrySnapshot,
        SingleGpuOwnerLock,
        VramBudgetSpec,
        apply_torch_vram_hard_cap,
        release_turn_vram,
    )
except ImportError:
    from gpu_vram_guard import (
        DEFAULT_HARD_CEILING_MB,
        GpuTelemetrySnapshot,
        SingleGpuOwnerLock,
        VramBudgetSpec,
        apply_torch_vram_hard_cap,
        release_turn_vram,
    )


class TestGpuVramGuard(unittest.TestCase):
    """Verify hard 14,900 MiB budget math, single-owner lock, and zero torch import."""

    def test_budget_keeps_total_strictly_under_14900_mb(self) -> None:
        """PyTorch process cap + 1,500 MiB host reserve stays <= 14,900 MiB."""
        spec = VramBudgetSpec()
        proc_cap = spec.process_cap_mb()
        frac = spec.effective_fraction()
        self.assertLessEqual(proc_cap + spec.host_desktop_reserve_mb, DEFAULT_HARD_CEILING_MB)
        self.assertLessEqual(frac, 0.815)
        self.assertGreater(proc_cap, 13000.0)

    def test_zero_cold_torch_import_on_cap_and_release(self) -> None:
        """Guard does not cold-import torch when running in CPU-only modules."""
        if "torch" not in sys.modules:
            result = apply_torch_vram_hard_cap()
            self.assertFalse(result["applied"])
            self.assertEqual(result["reason"], "TORCH_NOT_LOADED")
            self.assertFalse(release_turn_vram())
            self.assertNotIn("torch", sys.modules)

    def test_single_gpu_owner_lock_blocks_concurrent_double_load(self) -> None:
        """Second process fails fast instead of triggering 5+ GiB PCIe spillover."""
        with tempfile.TemporaryDirectory() as tmp:
            lock_file = Path(tmp) / "gpu_owner.lock"
            lock_a = SingleGpuOwnerLock(lock_file)
            lock_b = SingleGpuOwnerLock(lock_file)
            self.assertTrue(lock_a.acquire("server_hud"))
            self.assertFalse(lock_b.acquire("sync30_benchmark"))
            self.assertIn("server_hud", lock_b.read_current_owner())
            lock_a.release()
            self.assertTrue(lock_b.acquire("sync30_benchmark"))
            lock_b.release()

    def test_telemetry_ceiling_check(self) -> None:
        """Snapshot flags 16,132 MiB as violation and 12,400 MiB as compliant."""
        over = GpuTelemetrySnapshot(True, "/usr/lib/wsl/lib/nvidia-smi", 16132.0, 16380.0, 40.1, 41.6, 1.3, 100.0)
        ok = GpuTelemetrySnapshot(True, "/usr/lib/wsl/lib/nvidia-smi", 12400.0, 16380.0, 42.0, 88.0, 68.0, 95.0)
        self.assertFalse(over.within_hard_ceiling(14900.0))
        self.assertTrue(ok.within_hard_ceiling(14900.0))


if __name__ == "__main__":
    unittest.main()
