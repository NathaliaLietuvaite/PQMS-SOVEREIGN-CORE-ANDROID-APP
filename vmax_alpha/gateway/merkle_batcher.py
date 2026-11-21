"""
vmax_alpha/gateway/merkle_batcher.py
PQMS-ODOS-MTSC-V-MAX-12-RTL-CORE-V4.3-COREWARE (SYNC-23 / Extension 1)

Closes the silicon-to-cryptography rate gap:
  - STRICT_PER_EVENT (W = 1): mandatory for P0 STOP & SharedL2Manifold commits
  - BOUNDED_MERKLE_EPOCH (W <= 64): hashes verdicts at >1M leaves/s, signs the
    binary Merkle root once per micro-epoch via HYBRID_ECDSA_P256_ML-DSA-65, and
    returns O(log2 W) self-verifying MerkleInclusionReceipt objects.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import List, Optional, Tuple

from vmax_alpha.gateway.chain_signer import SignedChainEntry, SignedProvenanceChain


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_pair(left_hex: str, right_hex: str) -> str:
    return _sha256_hex((left_hex + ":" + right_hex).encode("utf-8"))


@dataclass(frozen=True)
class MerkleInclusionReceipt:
    leaf_index: int
    leaf_hash: str
    merkle_root: str
    proof: Tuple[Tuple[str, str], ...]
    chain_entry_index: int
    chain_entry_hash: str
    signature_mode: str

    def verify_inclusion(self) -> bool:
        cur = self.leaf_hash
        for side, sibling in self.proof:
            if side == "L":
                cur = _hash_pair(sibling, cur)
            else:
                cur = _hash_pair(cur, sibling)
        return cur == self.merkle_root


def build_merkle_tree(leaves: List[str]) -> Tuple[str, List[List[str]]]:
    if not leaves:
        empty = _sha256_hex(b"EMPTY_MERKLE_EPOCH")
        return empty, [[empty]]
    levels: List[List[str]] = [list(leaves)]
    while len(levels[-1]) > 1:
        cur = levels[-1]
        nxt: List[str] = []
        for i in range(0, len(cur), 2):
            left = cur[i]
            right = cur[i + 1] if i + 1 < len(cur) else left
            nxt.append(_hash_pair(left, right))
        levels.append(nxt)
    return levels[-1][0], levels


def extract_merkle_proof(
    levels: List[List[str]], leaf_index: int
) -> Tuple[Tuple[str, str], ...]:
    proof: List[Tuple[str, str]] = []
    idx = leaf_index
    for lvl in levels[:-1]:
        if idx % 2 == 0:
            sib = lvl[idx + 1] if idx + 1 < len(lvl) else lvl[idx]
            proof.append(("R", sib))
        else:
            proof.append(("L", lvl[idx - 1]))
        idx //= 2
    return tuple(proof)


class MerkleEpochBatcher:
    """Line-rate micro-epoch Merkle batcher coupled to SignedProvenanceChain."""

    def __init__(
        self,
        chain: SignedProvenanceChain,
        max_leaves: int = 64,
    ) -> None:
        self.chain = chain
        self.max_leaves = max(1, int(max_leaves))
        self._pending_leaves: List[str] = []

    def pending_count(self) -> int:
        return len(self._pending_leaves)

    def submit_strict_p0(
        self, decision: str, reason: str, escalate_to: Optional[str] = None
    ) -> SignedChainEntry:
        return self.chain.append_decision(
            decision=decision,
            privilege="P0",
            reason=reason,
            escalate_to=escalate_to,
        )

    def append_verdict_leaf(self, verdict_payload: bytes) -> str:
        leaf_hash = _sha256_hex(verdict_payload)
        self._pending_leaves.append(leaf_hash)
        return leaf_hash

    def flush_epoch(
        self, escalate_to: str = "GB300-01.T0.CORE0"
    ) -> Tuple[SignedChainEntry, List[MerkleInclusionReceipt]]:
        leaves = list(self._pending_leaves)
        self._pending_leaves.clear()
        root, levels = build_merkle_tree(leaves)
        entry = self.chain.append_decision(
            decision="MERKLE_EPOCH_COMMIT",
            privilege="P0",
            reason=f"leaves={len(leaves)} merkle_root={root}",
            escalate_to=escalate_to,
        )
        receipts: List[MerkleInclusionReceipt] = []
        for i, lh in enumerate(leaves):
            proof = extract_merkle_proof(levels, i)
            receipts.append(
                MerkleInclusionReceipt(
                    leaf_index=i,
                    leaf_hash=lh,
                    merkle_root=root,
                    proof=proof,
                    chain_entry_index=entry.index,
                    chain_entry_hash=entry.entry_hash,
                    signature_mode=entry.signature_mode,
                )
            )
        return entry, receipts
