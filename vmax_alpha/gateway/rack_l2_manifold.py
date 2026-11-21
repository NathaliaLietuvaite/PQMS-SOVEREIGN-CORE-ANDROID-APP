"""
vmax_alpha/gateway/rack_l2_manifold.py
PQMS-ODOS-MTSC-V-MAX-12-RTL-CORE-V4.2-COREWARE (SYNC-22)

Epoch-Versioned Shared-L2-Manifold for 72-Accelerator Racks:
  - Single-Writer P0 authority (Tier-0 Sovereign Cores) prevents clone entropy.
  - 72 die-local read-only L2-pinned mirrors provide O(1) zero-hop local reads.
  - Atomic Epoch-Broadcast + Stale-Epoch Fail-Closed Veto guarantees every
    autonomous accelerator stays aligned to the shared core and can self-heal
    drift via `request_drift_resync()`.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Dict, Iterable, Optional, Tuple

from vmax_alpha.gateway.chain_signer import HybridCorewareSigner, SignedProvenanceChain
from vmax_alpha.gateway.policy_engine import Privilege, infer_source_privilege

MAX_L2_WINDOW_BYTES: int = 2 * 1024 * 1024


@dataclass(frozen=True)
class ManifoldEpochSnapshot:
    epoch: int
    state_sha256: str
    entry_count: int
    entries: Dict[str, Any]


@dataclass(frozen=True)
class MirrorReadVerdict:
    coherent: bool
    status: str
    local_epoch: int
    authoritative_epoch: int
    value: Optional[Any] = None


def _hash_manifold_state(epoch: int, entries: Dict[str, Any]) -> str:
    payload = {"epoch": epoch, "entries": entries}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class LocalL2Mirror:
    """Die-local read-only L2-pinned mirror for one autonomous accelerator."""

    def __init__(self, worker_address: str) -> None:
        self.worker_address = worker_address
        self.local_epoch: int = 0
        self.local_sha256: str = ""
        self._entries: Dict[str, Any] = {}

    def apply_epoch_snapshot(self, snapshot: ManifoldEpochSnapshot) -> None:
        self.local_epoch = snapshot.epoch
        self.local_sha256 = snapshot.state_sha256
        self._entries = dict(snapshot.entries)

    def is_coherent_with(self, auth_epoch: int, auth_sha256: str) -> bool:
        if self.local_epoch != auth_epoch or self.local_sha256 != auth_sha256:
            return False
        return _hash_manifold_state(self.local_epoch, self._entries) == auth_sha256

    def read_if_coherent(
        self, key: str, auth_epoch: int, auth_sha256: str
    ) -> MirrorReadVerdict:
        if not self.is_coherent_with(auth_epoch, auth_sha256):
            return MirrorReadVerdict(
                coherent=False,
                status="STALE_EPOCH_VETO",
                local_epoch=self.local_epoch,
                authoritative_epoch=auth_epoch,
                value=None,
            )
        return MirrorReadVerdict(
            coherent=True,
            status="LOCAL_L2_COHERENT_PASS",
            local_epoch=self.local_epoch,
            authoritative_epoch=auth_epoch,
            value=self._entries.get(key),
        )

    def request_drift_resync(self, manifold: "SharedL2Manifold") -> ManifoldEpochSnapshot:
        snap = manifold.snapshot()
        self.apply_epoch_snapshot(snap)
        return snap


class SharedL2Manifold:
    """Authoritative Tier-0 P0-gated logical Shared-L2-Manifold."""

    def __init__(
        self,
        signer: Optional[HybridCorewareSigner] = None,
        genesis_anchor: str = "bb17ede97aa45c76ef9afa63cb457f7d684e5ede40b0432b2ecf3b6b9d3e03a3",
    ) -> None:
        self.epoch: int = 1
        self._entries: Dict[str, Any] = {"genesis_anchor": genesis_anchor}
        self.state_sha256: str = _hash_manifold_state(self.epoch, self._entries)
        self.chain = SignedProvenanceChain(signer=signer, genesis_anchor=genesis_anchor)

    def snapshot(self) -> ManifoldEpochSnapshot:
        return ManifoldEpochSnapshot(
            epoch=self.epoch,
            state_sha256=self.state_sha256,
            entry_count=len(self._entries),
            entries=dict(self._entries),
        )

    def commit_p0(
        self, caller_address: str, key: str, value: Any
    ) -> Tuple[bool, str, int]:
        if infer_source_privilege(caller_address) != Privilege.P0:
            self.chain.append_decision(
                decision="VETO",
                privilege="P0",
                reason=f"Non-P0 write attempt to SharedL2Manifold by {caller_address}",
                escalate_to=caller_address,
            )
            return False, "P0_WRITE_PRIVILEGE_REQUIRED", self.epoch

        candidate = dict(self._entries)
        candidate[key] = value
        encoded = json.dumps(candidate, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(encoded) > MAX_L2_WINDOW_BYTES:
            return False, "L2_WINDOW_2MIB_EXCEEDED", self.epoch

        self._entries = candidate
        self.epoch += 1
        self.state_sha256 = _hash_manifold_state(self.epoch, self._entries)
        self.chain.append_decision(
            decision="MANIFOLD_COMMIT",
            privilege="P0",
            reason=f"Epoch {self.epoch} commit key={key} sha256={self.state_sha256[:16]}",
            escalate_to=caller_address,
        )
        return True, self.state_sha256, self.epoch

    def broadcast_to_mirrors(
        self,
        mirrors: Iterable[LocalL2Mirror],
        exclude_addresses: Optional[set] = None,
    ) -> int:
        snap = self.snapshot()
        excluded = exclude_addresses or set()
        updated = 0
        for mirror in mirrors:
            if mirror.worker_address not in excluded:
                mirror.apply_epoch_snapshot(snap)
                updated += 1
        return updated
