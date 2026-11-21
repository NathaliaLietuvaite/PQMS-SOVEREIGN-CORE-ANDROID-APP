"""
vmax_alpha/gateway/chain_signer.py
PQMS-ODOS-MTSC-V-MAX-12-RTL-CORE-V4.2-COREWARE (Stage 5 / SYNC-20)

Cryptographically hash-chained provenance ledger (`prev_hash` + `entry_hash`)
with real ECDSA P-256 (secp256r1, Android TEE compatible) signatures and
honest optional FIPS 204 ML-DSA-65 (Dilithium3 via `oqs` / `liboqs`) hybrid
signing. Never synthesizes insecure placeholder PQ signatures.
"""
from __future__ import annotations

import base64
from dataclasses import asdict, dataclass
from enum import Enum, auto
import hashlib
import json
import time
from typing import Any, Dict, List, Optional, Tuple

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils

try:
    import oqs as _oqs_lib
except ImportError:
    _oqs_lib = None


class MLDSA65Spec:
    NAME: str = "ML-DSA-65"
    OQS_ALG_NAME: str = "ML-DSA-65"
    SECURITY_CATEGORY: int = 3
    PUBLIC_KEY_SIZE: int = 1952
    SECRET_KEY_SIZE: int = 4032
    SIGNATURE_SIZE: int = 3309


class ChainStatus(Enum):
    VALID = auto()
    EMPTY = auto()
    GENESIS_MISMATCH = auto()
    BROKEN_LINK = auto()
    TAMPERED_HASH = auto()
    INVALID_SIGNATURE = auto()


@dataclass(frozen=True)
class SignedChainEntry:
    index: int
    ts_ns: int
    decision: str
    privilege: str
    reason: str
    escalate_to: Optional[str]
    throttle_limit: Optional[int]
    prev_hash: str
    entry_hash: str
    signature_mode: str
    ecdsa_sig_b64: str
    pq_sig_hex: Optional[str]
    ecdsa_pub_fp: str


@dataclass(frozen=True)
class ChainVerificationReport:
    status: ChainStatus
    checked_entries: int
    pq_hybrid_active: bool
    genesis_hash: Optional[str]
    tip_hash: Optional[str]
    first_error_index: Optional[int] = None
    message: str = ""


def _canonical_json_bytes(payload: Dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _entry_core_payload(entry: SignedChainEntry) -> Dict[str, Any]:
    return {
        "decision": entry.decision,
        "escalate_to": entry.escalate_to,
        "index": entry.index,
        "prev_hash": entry.prev_hash,
        "privilege": entry.privilege,
        "reason": entry.reason,
        "throttle_limit": entry.throttle_limit,
        "ts_ns": entry.ts_ns,
    }


class HybridCorewareSigner:
    """Real ECDSA P-256 signer with optional real liboqs ML-DSA-65 hybrid extension."""

    def __init__(
        self,
        private_key: Optional[ec.EllipticCurvePrivateKey] = None,
        enable_pq_if_available: bool = True,
    ) -> None:
        self.private_key = (
            private_key
            if private_key is not None
            else ec.generate_private_key(ec.SECP256R1(), default_backend())
        )
        self.public_key = self.private_key.public_key()
        self.pq_active: bool = False
        self._oqs_signer: Any = None
        self.pq_public_key: Optional[bytes] = None
        if enable_pq_if_available and _oqs_lib is not None:
            self._init_liboqs()

    def _init_liboqs(self) -> None:
        try:
            alg = MLDSA65Spec.OQS_ALG_NAME
            signer = _oqs_lib.Signature(alg)
            self.pq_public_key = signer.generate_keypair()
            self._oqs_signer = signer
            self.pq_active = True
        except Exception:
            self._oqs_signer = None
            self.pq_public_key = None
            self.pq_active = False

    @property
    def signature_mode(self) -> str:
        if self.pq_active:
            return f"HYBRID_ECDSA_P256_{MLDSA65Spec.NAME}"
        return "CLASSICAL_ECDSA_P256_ONLY"

    def public_fingerprint(self) -> str:
        pub_bytes = self.public_key.public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint,
        )
        return hashlib.sha256(pub_bytes).hexdigest()[:16]

    def sign_bytes(self, message: bytes) -> Tuple[str, Optional[str]]:
        digest = hashlib.sha256(message).digest()
        ec_sig = self.private_key.sign(
            digest, ec.ECDSA(utils.Prehashed(hashes.SHA256()))
        )
        ec_b64 = base64.b64encode(ec_sig).decode("ascii")
        if not self.pq_active or self._oqs_signer is None:
            return ec_b64, None
        pq_sig = self._oqs_signer.sign(message)
        return ec_b64, pq_sig.hex()

    def verify_bytes(
        self, message: bytes, ecdsa_sig_b64: str, pq_sig_hex: Optional[str]
    ) -> bool:
        try:
            digest = hashlib.sha256(message).digest()
            sig_raw = base64.b64decode(ecdsa_sig_b64)
            self.public_key.verify(
                sig_raw, digest, ec.ECDSA(utils.Prehashed(hashes.SHA256()))
            )
        except (InvalidSignature, ValueError):
            return False
        if not self.pq_active:
            return pq_sig_hex is None
        if pq_sig_hex is None or self.pq_public_key is None or _oqs_lib is None:
            return False
        verifier = _oqs_lib.Signature(MLDSA65Spec.OQS_ALG_NAME)
        return bool(verifier.verify(message, bytes.fromhex(pq_sig_hex), self.pq_public_key))


class SignedProvenanceChain:
    """Append-only hash-linked and digitally signed Coreware audit chain."""

    def __init__(
        self,
        signer: Optional[HybridCorewareSigner] = None,
        genesis_anchor: str = "bb17ede97aa45c76ef9afa63cb457f7d684e5ede40b0432b2ecf3b6b9d3e03a3",
    ) -> None:
        self.signer = signer if signer is not None else HybridCorewareSigner()
        self.genesis_anchor = genesis_anchor
        self.entries: List[SignedChainEntry] = []
        self._append_raw(
            index=0,
            ts_ns=0,
            decision="GENESIS",
            privilege="P0",
            reason=f"Coreware genesis anchored to {genesis_anchor[:16]}",
            escalate_to=None,
            throttle_limit=None,
            prev_hash="0" * 64,
        )

    def _append_raw(
        self,
        index: int,
        ts_ns: int,
        decision: str,
        privilege: str,
        reason: str,
        escalate_to: Optional[str],
        throttle_limit: Optional[int],
        prev_hash: str,
    ) -> SignedChainEntry:
        payload = {
            "decision": decision,
            "escalate_to": escalate_to,
            "index": index,
            "prev_hash": prev_hash,
            "privilege": privilege,
            "reason": reason,
            "throttle_limit": throttle_limit,
            "ts_ns": ts_ns,
        }
        raw = _canonical_json_bytes(payload)
        entry_hash = hashlib.sha256(raw).hexdigest()
        ec_b64, pq_hex = self.signer.sign_bytes(raw)
        entry = SignedChainEntry(
            index=index,
            ts_ns=ts_ns,
            decision=decision,
            privilege=privilege,
            reason=reason,
            escalate_to=escalate_to,
            throttle_limit=throttle_limit,
            prev_hash=prev_hash,
            entry_hash=entry_hash,
            signature_mode=self.signer.signature_mode,
            ecdsa_sig_b64=ec_b64,
            pq_sig_hex=pq_hex,
            ecdsa_pub_fp=self.signer.public_fingerprint(),
        )
        self.entries.append(entry)
        return entry

    def append_decision(
        self,
        decision: str,
        privilege: str,
        reason: str,
        escalate_to: Optional[str] = None,
        throttle_limit: Optional[int] = None,
    ) -> SignedChainEntry:
        tip = self.entries[-1]
        return self._append_raw(
            index=tip.index + 1,
            ts_ns=time.time_ns(),
            decision=decision,
            privilege=privilege,
            reason=reason,
            escalate_to=escalate_to,
            throttle_limit=throttle_limit,
            prev_hash=tip.entry_hash,
        )

    def verify_chain(self) -> ChainVerificationReport:
        if not self.entries:
            return ChainVerificationReport(
                ChainStatus.EMPTY, 0, self.signer.pq_active, None, None, 0, "Empty chain"
            )
        gen = self.entries[0]
        if gen.prev_hash != "0" * 64 or gen.decision != "GENESIS":
            return ChainVerificationReport(
                ChainStatus.GENESIS_MISMATCH, 0, self.signer.pq_active,
                gen.entry_hash, self.entries[-1].entry_hash, 0, "Invalid genesis entry",
            )
        expected_prev = "0" * 64
        for idx, entry in enumerate(self.entries):
            if entry.prev_hash != expected_prev:
                return ChainVerificationReport(
                    ChainStatus.BROKEN_LINK, idx, self.signer.pq_active,
                    gen.entry_hash, self.entries[-1].entry_hash, idx, f"Broken link at {idx}",
                )
            raw = _canonical_json_bytes(_entry_core_payload(entry))
            if hashlib.sha256(raw).hexdigest() != entry.entry_hash:
                return ChainVerificationReport(
                    ChainStatus.TAMPERED_HASH, idx, self.signer.pq_active,
                    gen.entry_hash, self.entries[-1].entry_hash, idx, f"Hash mismatch at {idx}",
                )
            if not self.signer.verify_bytes(raw, entry.ecdsa_sig_b64, entry.pq_sig_hex):
                return ChainVerificationReport(
                    ChainStatus.INVALID_SIGNATURE, idx, self.signer.pq_active,
                    gen.entry_hash, self.entries[-1].entry_hash, idx, f"Bad signature at {idx}",
                )
            expected_prev = entry.entry_hash
        return ChainVerificationReport(
            ChainStatus.VALID, len(self.entries), self.signer.pq_active,
            gen.entry_hash, self.entries[-1].entry_hash, None,
            f"All {len(self.entries)} signed chain entries verified ({self.signer.signature_mode})",
        )

    def export_records(self) -> List[Dict[str, Any]]:
        return [asdict(e) for e in self.entries]
