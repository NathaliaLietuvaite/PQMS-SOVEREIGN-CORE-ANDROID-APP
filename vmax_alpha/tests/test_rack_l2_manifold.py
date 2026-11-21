"""
vmax_alpha/tests/test_rack_l2_manifold.py
SYNC-22 verification suite for Epoch-Versioned Shared-L2-Manifold (72 mirrors).
"""
from __future__ import annotations

import ast
import pathlib
import unittest

from vmax_alpha.gateway import (
    ChainStatus,
    LocalL2Mirror,
    SharedL2Manifold,
)


class TestRackL2Manifold(unittest.TestCase):
    def test_01_p0_only_write_enforcement(self) -> None:
        m = SharedL2Manifold()
        ok_p2, reason_p2, ep = m.commit_p0("GB300-01.T2.D00.R01", "gstar_1", {"rcf": 0.99})
        self.assertFalse(ok_p2)
        self.assertEqual(reason_p2, "P0_WRITE_PRIVILEGE_REQUIRED")
        self.assertEqual(ep, 1)

        ok_p0, sha, ep2 = m.commit_p0("GB300-01.T0.CORE0", "gstar_1", {"rcf": 0.995})
        self.assertTrue(ok_p0)
        self.assertEqual(ep2, 2)
        self.assertEqual(len(sha), 64)

    def test_02_72_mirror_atomic_epoch_broadcast_zero_clone_entropy(self) -> None:
        m = SharedL2Manifold()
        mirrors = [LocalL2Mirror(f"GB300-01.T2.D{i // 12:02d}.R{i:02d}") for i in range(72)]
        m.commit_p0("GB300-01.T0.CORE0", "mask_band_0", "0xA5A5")
        updated = m.broadcast_to_mirrors(mirrors)
        self.assertEqual(updated, 72)
        for mir in mirrors:
            v = mir.read_if_coherent("mask_band_0", m.epoch, m.state_sha256)
            self.assertTrue(v.coherent)
            self.assertEqual(v.status, "LOCAL_L2_COHERENT_PASS")
            self.assertEqual(v.value, "0xA5A5")

    def test_03_stale_mirror_fail_closed_veto_and_autonomous_resync(self) -> None:
        m = SharedL2Manifold()
        mirrors = [LocalL2Mirror(f"GB300-01.T2.D{i // 12:02d}.R{i:02d}") for i in range(72)]
        m.broadcast_to_mirrors(mirrors)

        # Partition worker 7 during Epoch 2 commit
        m.commit_p0("GB300-01.T0.CORE1", "gstar_sync", {"theta": 0.01})
        stale_addr = "GB300-01.T2.D00.R07"
        updated = m.broadcast_to_mirrors(mirrors, exclude_addresses={stale_addr})
        self.assertEqual(updated, 71)

        # Stale worker 7 must fail-closed with STALE_EPOCH_VETO
        v_stale = mirrors[7].read_if_coherent("gstar_sync", m.epoch, m.state_sha256)
        self.assertFalse(v_stale.coherent)
        self.assertEqual(v_stale.status, "STALE_EPOCH_VETO")

        # Autonomous drift-correction resync restores coherence
        mirrors[7].request_drift_resync(m)
        v_healed = mirrors[7].read_if_coherent("gstar_sync", m.epoch, m.state_sha256)
        self.assertTrue(v_healed.coherent)
        self.assertEqual(v_healed.value, {"theta": 0.01})

    def test_04_local_tamper_detected_by_sha256_coherence_check(self) -> None:
        m = SharedL2Manifold()
        mir = LocalL2Mirror("GB300-01.T2.D01.R15")
        m.commit_p0("GB300-01.T0.CORE0", "k", 42)
        m.broadcast_to_mirrors([mir])
        mir._entries["k"] = 999  # Simulate silent local memory corruption
        v = mir.read_if_coherent("k", m.epoch, m.state_sha256)
        self.assertFalse(v.coherent)
        self.assertEqual(v.status, "STALE_EPOCH_VETO")

    def test_05_provenance_chain_valid_after_commits(self) -> None:
        m = SharedL2Manifold()
        m.commit_p0("GB300-01.T0.CORE0", "a", 1)
        m.commit_p0("GB300-01.T0.CORE1", "b", 2)
        rep = m.chain.verify_chain()
        self.assertEqual(rep.status, ChainStatus.VALID)
        self.assertEqual(rep.checked_entries, 3)

    def test_06_op02_ast_hygiene(self) -> None:
        p = pathlib.Path(__file__).resolve().parent.parent / "gateway/rack_l2_manifold.py"
        src = p.read_text(encoding="utf-8")
        self.assertNotIn("\t", src)
        self.assertNotIn(";", src)
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                branches = sum(
                    1 for n in ast.walk(node)
                    if isinstance(n, (ast.If, ast.For, ast.While, ast.ExceptHandler, ast.With, ast.IfExp))
                )
                self.assertLessEqual(branches + 1, 6, f"{node.name} cc={branches + 1}")


if __name__ == "__main__":
    unittest.main()
