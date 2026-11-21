"""
vmax_alpha/tests/test_sync23_merkle_and_arbiter.py
SYNC-23 verification suite for MerkleEpochBatcher and DualCoreArbiter (SEU + KAT).
"""
from __future__ import annotations

import ast
from dataclasses import replace
import pathlib
import unittest

from vmax_alpha.gateway import (
    ArbiterMode,
    ChainStatus,
    CoreVerdictTuple,
    DualCoreArbiter,
    HybridCorewareSigner,
    MerkleEpochBatcher,
    SignedProvenanceChain,
)


class TestSync23MerkleAndArbiter(unittest.TestCase):
    def test_01_merkle_batcher_w64_receipts_and_chain_valid(self) -> None:
        chain = SignedProvenanceChain(signer=HybridCorewareSigner(enable_pq_if_available=True))
        batcher = MerkleEpochBatcher(chain, max_leaves=64)
        for i in range(64):
            batcher.append_verdict_leaf(f"verdict_{i}".encode("utf-8"))
        entry, receipts = batcher.flush_epoch()
        self.assertEqual(len(receipts), 64)
        self.assertEqual(batcher.pending_count(), 0)
        for r in receipts:
            self.assertTrue(r.verify_inclusion())
            self.assertEqual(r.chain_entry_hash, entry.entry_hash)
        self.assertEqual(chain.verify_chain().status, ChainStatus.VALID)

    def test_02_merkle_1bit_leaf_tamper_rejected(self) -> None:
        chain = SignedProvenanceChain()
        batcher = MerkleEpochBatcher(chain, max_leaves=8)
        for i in range(8):
            batcher.append_verdict_leaf(f"tx_{i}".encode("utf-8"))
        _, receipts = batcher.flush_epoch()
        tampered = replace(receipts[3], leaf_hash="f" * 64)
        self.assertFalse(tampered.verify_inclusion())

    def test_03_strict_p0_bypasses_batching(self) -> None:
        chain = SignedProvenanceChain()
        batcher = MerkleEpochBatcher(chain, max_leaves=64)
        entry = batcher.submit_strict_p0("STOP", "Immediate P0 hardware stop")
        self.assertEqual(entry.decision, "STOP")
        self.assertEqual(chain.verify_chain().status, ChainStatus.VALID)

    def test_04_dual_core_lockstep_agreement(self) -> None:
        expected = CoreVerdictTuple(1073741827, 1073741830, 0, True, False)
        arb = DualCoreArbiter(lambda v, t: expected, lambda v, t: expected, [1] * 64, expected)
        out = arb.evaluate([1] * 64, 0, ArbiterMode.LOCKSTEP_DMR_CRITICAL)
        self.assertEqual(out.decision, "LOCKSTEP_AGREE")
        self.assertFalse(out.divergence_detected)

    def test_05_seu_bitflip_on_core0_triggers_kat_quarantine_and_core1_failover(self) -> None:
        good = CoreVerdictTuple(1073741827, 1073741830, 0, True, False)
        seu_bad = CoreVerdictTuple(1073741827, 1073741831, 0, True, False)  # 1-LSB SEU!
        arb = DualCoreArbiter(lambda v, t: seu_bad, lambda v, t: good, [1] * 64, good)
        out = arb.evaluate([1] * 64, 0, ArbiterMode.LOCKSTEP_DMR_CRITICAL)
        self.assertTrue(out.divergence_detected)
        self.assertEqual(out.decision, "FAILOVER_TO_CORE1")
        self.assertEqual(out.quarantined_core, "GB300-01.T0.CORE0")
        self.assertFalse(arb.core0_healthy)
        self.assertTrue(arb.core1_healthy)

        # Subsequent traffic continues zero-drop on CORE1
        out2 = arb.evaluate([1] * 64, 0, ArbiterMode.LOCKSTEP_DMR_CRITICAL)
        self.assertEqual(out2.decision, "SINGLE_CORE1_PASS")

    def test_06_both_cores_faulty_triggers_hard_veto(self) -> None:
        good = CoreVerdictTuple(1073741827, 1073741830, 0, True, False)
        bad0 = CoreVerdictTuple(1073741827, 1073741800, 0, True, False)
        bad1 = CoreVerdictTuple(1073741827, 1073741801, 0, True, False)
        arb = DualCoreArbiter(lambda v, t: bad0, lambda v, t: bad1, [1] * 64, good)
        out = arb.evaluate([1] * 64, 0, ArbiterMode.LOCKSTEP_DMR_CRITICAL)
        self.assertEqual(out.decision, "CORE_DIVERGENCE_VETO")
        self.assertIsNone(out.verdict)

    def test_07_active_active_sharded_round_robin(self) -> None:
        good = CoreVerdictTuple(1073741827, 1073741830, 0, True, False)
        arb = DualCoreArbiter(lambda v, t: good, lambda v, t: good, [1] * 64, good)
        o0 = arb.evaluate([1] * 64, 0, ArbiterMode.ACTIVE_ACTIVE_SHARDED)
        o1 = arb.evaluate([1] * 64, 0, ArbiterMode.ACTIVE_ACTIVE_SHARDED)
        self.assertEqual(o0.active_survivor, "GB300-01.T0.CORE0")
        self.assertEqual(o1.active_survivor, "GB300-01.T0.CORE1")

    def test_08_op02_ast_hygiene_sync23(self) -> None:
        root = pathlib.Path(__file__).resolve().parent.parent / "gateway"
        for fn in ("merkle_batcher.py", "dual_core_arbiter.py"):
            src = (root / fn).read_text(encoding="utf-8")
            self.assertNotIn("\t", src)
            self.assertNotIn(";", src)
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    branches = sum(
                        1 for n in ast.walk(node)
                        if isinstance(n, (ast.If, ast.For, ast.While, ast.ExceptHandler, ast.With, ast.IfExp))
                    )
                    self.assertLessEqual(branches + 1, 6, f"{fn}:{node.name} cc={branches + 1}")


if __name__ == "__main__":
    unittest.main()
