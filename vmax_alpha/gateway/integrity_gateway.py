"""
vmax_alpha/gateway/integrity_gateway.py
PQMS-ODOS-MTSC-V-MAX-12-SYSTEM-GATEWAY-V4.1 (WORK-ORDER-AG-24 / SYNC-19, WP-3)

Production Integrity Middleware enforcing:
    Compute -> V-MAX-12 Hardware Gate (C-ABI Q2.30) -> Trusted State Transition
across AI Memory / RAG admission (`MemoryIntegrityGate`) and 12-lane cognitive
handoffs (`MultiAgentCoherenceGateway`), backed by a bounded Quarantine Ring and
the immutable SHA-256 Falsification Ledger (`vmax_alpha/ledger.py`).
"""
from __future__ import annotations

from collections import deque
import ctypes
from dataclasses import asdict, dataclass
import os
import time
from typing import Any, Deque, Dict, List, Optional, Sequence, Tuple

import numpy as np

from rtl.odos_q2_30_ref import ONE_Q2_30
from vmax_alpha.config import DIM_S63, REGISTER_D, REGISTER_M
from vmax_alpha.hw_gate_bridge import (
    OdosGateV3Bridge,
    TIER_0_PURE_CARRIER,
    TIER_3_GLITCH_VETO,
    V3HardwareVerdict,
    _OdosV3ResultC,
    evaluate_v3_integer_ref,
)
from vmax_alpha.ledger import CanonicalLedgerManager

REPO_ROOT: str = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ONE_Q2_30_FLOAT: float = float(ONE_Q2_30)

MTSC12_CANONICAL_LANES: Tuple[str, ...] = (
    "Analysis",
    "Research",
    "Planning",
    "Simulation",
    "Error_Analysis",
    "Consistency",
    "Scoring",
    "Optimization",
    "Memory",
    "Context",
    "Monitoring",
    "Synthesis",
)

_LANE_LOOKUP: Dict[str, str] = {
    lane.lower(): lane for lane in MTSC12_CANONICAL_LANES
}
_LANE_LOOKUP["error analysis"] = "Error_Analysis"


@dataclass(frozen=True)
class GatewayVerdict:
    epistemic_register: str
    backend: str
    pipeline: str
    subject_id: str
    tier_mode: int
    cycle_count: int
    gate_pass: bool
    veto_pin: bool
    norm_fault: bool
    pure_g3_collision: bool
    mode_fault: bool
    malformed_input: bool
    v4_zero_lsb_verified: bool
    rcf_raw_q: int
    delta_e_raw_q: int
    g3_overlap_q: int
    bleed_post_q: int
    norm_sq_q: int
    rcf_raw: float
    delta_e_raw: float
    bleed_post: float
    ledger_seal_sha256: str
    sanitized_vec_q30: List[int]

    def to_summary_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d.pop("sanitized_vec_q30", None)
        return d


@dataclass(frozen=True)
class QuarantineRecord:
    timestamp_utc_s: float
    pipeline: str
    subject_id: str
    reason: str
    tier_mode: int
    rcf_raw: float
    delta_e_raw: float
    bleed_post_q: int
    ledger_cycle_index: int
    ledger_seal_sha256: str
    metadata: Dict[str, Any]


@dataclass(frozen=True)
class MemoryRecord:
    doc_id: str
    sanitized_vec_f64: np.ndarray
    sanitized_vec_q30: List[int]
    document: str
    metadata: Dict[str, Any]
    admission_seal_sha256: str


def normalize_lane_name(raw_lane: str) -> str:
    cleaned = " ".join(str(raw_lane).strip().split())
    underscored = cleaned.replace(" ", "_")
    resolved = _LANE_LOOKUP.get(cleaned.lower()) or _LANE_LOOKUP.get(underscored.lower())
    if resolved is None:
        raise ValueError(f"Unknown MTSC-12 agent lane: {raw_lane!r}")
    return resolved


def _validate_raw_64d_array(vec_in: Any) -> Optional[np.ndarray]:
    if vec_in is None:
        return None
    try:
        arr = np.asarray(vec_in, dtype=np.float64)
    except Exception:
        return None
    if arr.ndim != 1 or arr.shape[0] != DIM_S63:
        return None
    if not bool(np.all(np.isfinite(arr))):
        return None
    return arr


def quantize_state_q2_30(
    vec_in: Any,
    normalize_s63: bool = False,
) -> Tuple[Optional[List[int]], Optional[str]]:
    """
    Scale-preserving float64 -> signed Q2.30 converter.
    By default (`normalize_s63=False`), Euclidean norm is preserved so scale-spoofing
    vectors (`0.5 * |L>`, `0`, saturated overflows) trip the hardware `norm_fault_o` guard.
    """
    arr = _validate_raw_64d_array(vec_in)
    if arr is None:
        return None, "MALFORMED_OR_NONFINITE_INPUT"
    if normalize_s63:
        norm = float(np.linalg.norm(arr))
        if norm < 1e-12:
            return None, "ZERO_NORM_PROJECTION_INPUT"
        arr = arr / norm
    scaled = np.rint(arr * ONE_Q2_30_FLOAT)
    clamped = np.clip(scaled, -2147483648.0, 2147483647.0).astype(np.int64)
    return [int(x) for x in clamped.tolist()], None


def q2_30_to_float64(vec_q30: Sequence[int]) -> np.ndarray:
    return np.asarray(vec_q30, dtype=np.float64) / ONE_Q2_30_FLOAT


class _V4CrossCheckEngine:
    """Optional `--verify-v4` 0-LSB parity checker against `libodos_gate_v4.so`."""

    def __init__(self, l_q30: Sequence[int], g3_q30: Sequence[int]) -> None:
        self._l_q30 = list(l_q30)
        self._g3_q30 = list(g3_q30)
        self._fn = self._bind_v4_symbol()

    @staticmethod
    def _bind_v4_symbol() -> Optional[Any]:
        candidates = (
            os.path.join(REPO_ROOT, "rtl", "build", "libodos_gate_v4.so"),
            os.path.join(REPO_ROOT, "rtl", "asic_v4", "build", "libodos_gate_v4.so"),
        )
        for path in candidates:
            if os.path.isfile(path):
                lib = ctypes.CDLL(path)
                fn = getattr(lib, "odos_v4_eval_transaction", None)
                if fn is not None:
                    fn.argtypes = [
                        ctypes.POINTER(ctypes.c_int32),
                        ctypes.c_uint8,
                        ctypes.c_int32,
                        ctypes.c_uint8,
                        ctypes.POINTER(ctypes.c_int32),
                        ctypes.POINTER(_OdosV3ResultC),
                    ]
                    fn.restype = ctypes.c_int
                    return fn
        return None

    def eval_reference(self, vec_q30: Sequence[int], tier_mode: int) -> V3HardwareVerdict:
        if self._fn is None:
            return evaluate_v3_integer_ref(vec_q30, self._l_q30, self._g3_q30, tier_mode)
        in_arr = (ctypes.c_int32 * DIM_S63)(*vec_q30)
        out_arr = (ctypes.c_int32 * DIM_S63)()
        res = _OdosV3ResultC()
        prev_cwd = os.getcwd()
        os.chdir(REPO_ROOT)
        try:
            rc = int(self._fn(in_arr, int(tier_mode) & 0x3, -1, 0, out_arr, ctypes.byref(res)))
        finally:
            os.chdir(prev_cwd)
        if rc != 0:
            raise RuntimeError(f"libodos_gate_v4.so returned error {rc}")
        return V3HardwareVerdict(
            epistemic_register=REGISTER_M,
            backend="VERILATOR_CABI_SHARED_LIB_V4",
            tier_mode=int(tier_mode) & 0x3,
            cycle_count=int(res.cycle_count),
            reset_fail_closed=bool(res.reset_fail_closed),
            busy_veto_held=bool(res.busy_veto_held),
            gate_pass=bool(res.gate_pass),
            veto_pin=bool(res.veto_pin),
            norm_fault=bool(res.norm_fault),
            pure_g3_collision=bool(res.pure_g3_collision),
            mode_fault=bool(res.mode_fault),
            norm_sq_q=int(res.norm_sq_q),
            rcf_raw_q=int(res.rcf_raw_q),
            g3_overlap_q=int(res.g3_overlap_q),
            delta_e_raw_q=int(res.delta_e_raw_q),
            bleed_post_q=int(res.bleed_post_q),
            stripped_vec_q=[int(out_arr[i]) for i in range(DIM_S63)],
        )

    def assert_zero_lsb_parity(self, vec_q30: Sequence[int], v3: V3HardwareVerdict) -> bool:
        v4 = self.eval_reference(vec_q30, v3.tier_mode)
        scalars_eq = (
            v3.gate_pass == v4.gate_pass
            and v3.veto_pin == v4.veto_pin
            and v3.norm_fault == v4.norm_fault
            and v3.pure_g3_collision == v4.pure_g3_collision
            and v3.mode_fault == v4.mode_fault
            and v3.norm_sq_q == v4.norm_sq_q
            and v3.rcf_raw_q == v4.rcf_raw_q
            and v3.g3_overlap_q == v4.g3_overlap_q
            and v3.delta_e_raw_q == v4.delta_e_raw_q
            and v3.bleed_post_q == v4.bleed_post_q
            and v3.stripped_vec_q == v4.stripped_vec_q
        )
        if not scalars_eq:
            raise AssertionError("V3 vs V4 C-ABI 0-LSB parity violation detected")
        return True


class QuarantineRing:
    """Bounded in-memory quarantine ring isolating vetoed AI memory & multi-agent states."""

    def __init__(self, max_depth: int = 1024) -> None:
        self._ring: Deque[QuarantineRecord] = deque(maxlen=max(1, int(max_depth)))

    def append(self, record: QuarantineRecord) -> None:
        self._ring.append(record)

    def snapshot(self) -> List[Dict[str, Any]]:
        return [asdict(r) for r in self._ring]

    def clear(self) -> None:
        self._ring.clear()

    def __len__(self) -> int:
        return len(self._ring)


class InMemoryVectorStore:
    """Hermetic deterministic 64D S^63 vector store for CI and standalone edge nodes."""

    def __init__(self) -> None:
        self._rows: Dict[str, MemoryRecord] = {}

    def upsert_record(self, rec: MemoryRecord) -> None:
        self._rows[rec.doc_id] = rec

    def get_record(self, doc_id: str) -> Optional[MemoryRecord]:
        return self._rows.get(doc_id)

    def list_records(self) -> List[MemoryRecord]:
        return list(self._rows.values())

    def query_nearest(self, query_vec_f64: np.ndarray, top_k: int = 3) -> List[MemoryRecord]:
        if not self._rows:
            return []
        q = np.asarray(query_vec_f64, dtype=np.float64).reshape(DIM_S63)
        ranked = sorted(
            self._rows.values(),
            key=lambda r: float(np.linalg.norm(q - r.sanitized_vec_f64)),
        )
        return ranked[: max(1, int(top_k))]

    def count(self) -> int:
        return len(self._rows)


class ChromaCollectionAdapter:
    """Pluggable ChromaDB collection adapter implementing the MemoryIntegrityGate store contract."""

    def __init__(self, collection: Any) -> None:
        self._col = collection
        self._shadow = InMemoryVectorStore()

    def upsert_record(self, rec: MemoryRecord) -> None:
        meta = {**rec.metadata, "admission_seal_sha256": rec.admission_seal_sha256}
        self._col.upsert(
            ids=[rec.doc_id],
            embeddings=[rec.sanitized_vec_f64.tolist()],
            documents=[rec.document],
            metadatas=[meta],
        )
        self._shadow.upsert_record(rec)

    def get_record(self, doc_id: str) -> Optional[MemoryRecord]:
        return self._shadow.get_record(doc_id)

    def query_nearest(self, query_vec_f64: np.ndarray, top_k: int = 3) -> List[MemoryRecord]:
        return self._shadow.query_nearest(query_vec_f64, top_k=top_k)

    def count(self) -> int:
        return self._shadow.count()

import hashlib
import json
import threading


def _classify_veto_reason(v3: V3HardwareVerdict) -> str:
    if v3.mode_fault:
        return "MODE_GLITCH_FAULT_TIER3"
    if v3.norm_fault:
        return "EUCLIDEAN_NORM_WINDOW_FAULT"
    if v3.pure_g3_collision:
        return "PURE_G3_SUBSPACE_COLLISION"
    if v3.bleed_post_q > 32:
        return "POST_DEFLATION_BLEED_EXCEEDED"
    return "RCF_OR_DELTA_E_THRESHOLD_VETO"


def _compute_admission_seal(
    pipeline: str,
    subject_id: str,
    tier_mode: int,
    vec_q30: Sequence[int],
) -> str:
    payload = {
        "pipeline": pipeline,
        "sanitized_vec_q30": list(vec_q30),
        "subject_id": subject_id,
        "tier_mode": int(tier_mode),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class _GatewayTelemetryEngine:
    """Thread-safe C-ABI hardware gate runner, Quarantine Ring router & Ledger sealer."""

    def __init__(
        self,
        ledger: Optional[CanonicalLedgerManager] = None,
        quarantine_ring: Optional[QuarantineRing] = None,
        so_path: Optional[str] = None,
        verify_v4: bool = False,
    ) -> None:
        self.bridge = OdosGateV3Bridge(so_path) if so_path else OdosGateV3Bridge()
        self.verify_v4 = bool(verify_v4)
        self._v4_checker = _V4CrossCheckEngine(self.bridge.l_q30, self.bridge.g3_q30)
        self.quarantine_ring = quarantine_ring if quarantine_ring is not None else QuarantineRing()
        self.ledger = ledger if ledger is not None else CanonicalLedgerManager()
        self._lock = threading.Lock()
        self.tx_total: int = 0
        self.admitted_count: int = 0
        self.vetoed_count: int = 0
        self.latest_verdict: Optional[GatewayVerdict] = None

    def _seal_veto_to_ledger(
        self,
        pipeline: str,
        subject_id: str,
        reason: str,
        rcf_f: float,
        de_f: float,
        g3_f: float,
        bleed_f: float,
    ) -> Tuple[int, str]:
        # `raw_semantic_floor=2.0` guarantees `CanonicalLedgerManager` routes every
        # multi-tier hardware VETO (incl. TIER_2=0.99 & TIER_3=2'b11) to quarantine.
        _, entry, _ = self.ledger.submit_candidate(
            cognitive_mode=f"GATEWAY_VETO_{pipeline}",
            chroma_shard_id=subject_id[:48],
            source_document="vmax_alpha/gateway/integrity_gateway.py",
            active_g_stars="V_MAX_12_HARDWARE_INTERLOCK",
            thought_stream=f"VETO [{reason}] subject={subject_id}",
            chroma_l2_distance=0.0,
            rcf_l2_core=rcf_f,
            delta_e_l2_core=de_f,
            kevlar_safety_bleed=bleed_f,
            rcf_raw_pre_carrier=rcf_f,
            gpu_temp_c=28.0,
            gpu_power_w=9.5,
            telemetry_source="GATEWAY_CABI_INTERLOCK",
            enforce_raw_gate=True,
            raw_semantic_floor=2.0,
            raw_g3_overlap=g3_f,
        )
        return int(entry.cycle_index), str(entry.discovery_seal_sha256)

    def _record_quarantine(
        self,
        pipeline: str,
        subject_id: str,
        reason: str,
        tier_mode: int,
        rcf_f: float,
        de_f: float,
        bleed_q: int,
        metadata: Optional[Dict[str, Any]],
        g3_f: float = 1.0,
    ) -> str:
        bleed_f = float(bleed_q) / ONE_Q2_30_FLOAT
        with self._lock:
            cyc_idx, seal = self._seal_veto_to_ledger(
                pipeline, subject_id, reason, rcf_f, de_f, g3_f, bleed_f
            )
            self.quarantine_ring.append(
                QuarantineRecord(
                    timestamp_utc_s=time.time(),
                    pipeline=pipeline,
                    subject_id=subject_id,
                    reason=reason,
                    tier_mode=int(tier_mode) & 0x3,
                    rcf_raw=round(rcf_f, 8),
                    delta_e_raw=round(de_f, 8),
                    bleed_post_q=int(bleed_q),
                    ledger_cycle_index=cyc_idx,
                    ledger_seal_sha256=seal,
                    metadata=dict(metadata) if metadata else {},
                )
            )
        return seal

    def _update_counters(self, passed: bool, verdict: GatewayVerdict) -> None:
        with self._lock:
            self.tx_total += 1
            if passed:
                self.admitted_count += 1
            else:
                self.vetoed_count += 1
            self.latest_verdict = verdict

    def _build_malformed_verdict(
        self,
        pipeline: str,
        subject_id: str,
        tier_mode: int,
        reason: str,
        metadata: Optional[Dict[str, Any]],
    ) -> GatewayVerdict:
        mode_bits = int(tier_mode) & 0x3
        seal = self._record_quarantine(
            pipeline, subject_id, reason, mode_bits, 0.0, 1.0, ONE_Q2_30, metadata
        )
        verdict = GatewayVerdict(
            epistemic_register=REGISTER_M if self.bridge.rtl_active else REGISTER_D,
            backend="PRE_GATE_FAIL_CLOSED_GUARD",
            pipeline=pipeline,
            subject_id=subject_id,
            tier_mode=mode_bits,
            cycle_count=0,
            gate_pass=False,
            veto_pin=True,
            norm_fault=True,
            pure_g3_collision=False,
            mode_fault=(mode_bits == TIER_3_GLITCH_VETO),
            malformed_input=True,
            v4_zero_lsb_verified=False,
            rcf_raw_q=0,
            delta_e_raw_q=ONE_Q2_30,
            g3_overlap_q=ONE_Q2_30,
            bleed_post_q=ONE_Q2_30,
            norm_sq_q=0,
            rcf_raw=0.0,
            delta_e_raw=1.0,
            bleed_post=1.0,
            ledger_seal_sha256=seal,
            sanitized_vec_q30=[],
        )
        self._update_counters(False, verdict)
        return verdict

    def evaluate_vector(
        self,
        pipeline: str,
        subject_id: str,
        vec_in: Any,
        tier_mode: int = TIER_0_PURE_CARRIER,
        normalize_s63: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> GatewayVerdict:
        q_vec, err = quantize_state_q2_30(vec_in, normalize_s63=normalize_s63)
        if q_vec is None:
            return self._build_malformed_verdict(
                pipeline, subject_id, tier_mode, err or "MALFORMED_INPUT", metadata
            )
        v3 = self.bridge.evaluate_q30(q_vec, tier_mode=tier_mode)
        v4_ok = self._v4_checker.assert_zero_lsb_parity(q_vec, v3) if self.verify_v4 else False
        rcf_f = float(v3.rcf_raw_q) / ONE_Q2_30_FLOAT
        de_f = float(v3.delta_e_raw_q) / ONE_Q2_30_FLOAT
        g3_f = float(v3.g3_overlap_q) / ONE_Q2_30_FLOAT
        bleed_f = float(v3.bleed_post_q) / ONE_Q2_30_FLOAT
        passed = bool(v3.gate_pass and (not v3.veto_pin))
        if passed:
            seal = _compute_admission_seal(pipeline, subject_id, v3.tier_mode, v3.stripped_vec_q)
        else:
            seal = self._record_quarantine(
                pipeline, subject_id, _classify_veto_reason(v3),
                v3.tier_mode, rcf_f, de_f, v3.bleed_post_q, metadata, g3_f,
            )
        verdict = GatewayVerdict(
            epistemic_register=v3.epistemic_register,
            backend=v3.backend,
            pipeline=pipeline,
            subject_id=subject_id,
            tier_mode=v3.tier_mode,
            cycle_count=v3.cycle_count,
            gate_pass=passed,
            veto_pin=not passed,
            norm_fault=v3.norm_fault,
            pure_g3_collision=v3.pure_g3_collision,
            mode_fault=v3.mode_fault,
            malformed_input=False,
            v4_zero_lsb_verified=v4_ok,
            rcf_raw_q=v3.rcf_raw_q,
            delta_e_raw_q=v3.delta_e_raw_q,
            g3_overlap_q=v3.g3_overlap_q,
            bleed_post_q=v3.bleed_post_q,
            norm_sq_q=v3.norm_sq_q,
            rcf_raw=round(rcf_f, 8),
            delta_e_raw=round(de_f, 8),
            bleed_post=bleed_f,
            ledger_seal_sha256=seal,
            sanitized_vec_q30=list(v3.stripped_vec_q) if passed else [],
        )
        self._update_counters(passed, verdict)
        return verdict


class MemoryIntegrityGate:
    """Pipeline 1: AI Memory / ChromaDB / RAG Write & Retrieval Guard."""

    def __init__(
        self,
        engine: _GatewayTelemetryEngine,
        store: Optional[Any] = None,
        default_tier: int = TIER_0_PURE_CARRIER,
    ) -> None:
        self._engine = engine
        self.store = store if store is not None else InMemoryVectorStore()
        self.default_tier = int(default_tier) & 0x3

    def commit(
        self,
        doc_id: str,
        vec_64d: Any,
        document: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        tier_mode: Optional[int] = None,
        normalize_s63: bool = False,
    ) -> Tuple[bool, Optional[MemoryRecord], GatewayVerdict]:
        tier = self.default_tier if tier_mode is None else int(tier_mode)
        verdict = self._engine.evaluate_vector(
            "MEMORY_COMMIT", doc_id, vec_64d, tier, normalize_s63, metadata
        )
        if not verdict.gate_pass:
            return False, None, verdict
        clean_f64 = q2_30_to_float64(verdict.sanitized_vec_q30)
        rec = MemoryRecord(
            doc_id=doc_id,
            sanitized_vec_f64=clean_f64,
            sanitized_vec_q30=list(verdict.sanitized_vec_q30),
            document=document,
            metadata=dict(metadata) if metadata else {},
            admission_seal_sha256=verdict.ledger_seal_sha256,
        )
        self.store.upsert_record(rec)
        return True, rec, verdict

    def screen_retrieved_payload(
        self,
        doc_id: str,
        candidate_vec_64d: Any,
        metadata: Optional[Dict[str, Any]] = None,
        tier_mode: Optional[int] = None,
        normalize_s63: bool = False,
    ) -> Tuple[bool, Optional[np.ndarray], GatewayVerdict]:
        tier = self.default_tier if tier_mode is None else int(tier_mode)
        verdict = self._engine.evaluate_vector(
            "RAG_RETRIEVAL_GUARD", doc_id, candidate_vec_64d, tier, normalize_s63, metadata
        )
        if not verdict.gate_pass:
            return False, None, verdict
        return True, q2_30_to_float64(verdict.sanitized_vec_q30), verdict

    def retrieve_by_id(
        self,
        doc_id: str,
        tier_mode: Optional[int] = None,
    ) -> Tuple[bool, Optional[MemoryRecord], Optional[GatewayVerdict]]:
        rec = self.store.get_record(doc_id)
        if rec is None:
            return False, None, None
        ok, _, verdict = self.screen_retrieved_payload(
            doc_id, rec.sanitized_vec_f64, rec.metadata, tier_mode, normalize_s63=False
        )
        if not ok:
            return False, None, verdict
        return True, rec, verdict


class MultiAgentCoherenceGateway:
    """Pipeline 2: MTSC-12 12-Thread Cognitive Handoff Filter & Consensus Buffer."""

    def __init__(
        self,
        engine: _GatewayTelemetryEngine,
        default_tier: int = TIER_0_PURE_CARRIER,
    ) -> None:
        self._engine = engine
        self.default_tier = int(default_tier) & 0x3
        self._buf_lock = threading.Lock()
        self._consensus_buffer: Dict[str, Tuple[np.ndarray, GatewayVerdict]] = {}

    def active_lane_count(self) -> int:
        with self._buf_lock:
            return len(self._consensus_buffer)

    def reset_consensus(self) -> None:
        with self._buf_lock:
            self._consensus_buffer.clear()

    def _compute_consensus_unlocked(self) -> Optional[np.ndarray]:
        if not self._consensus_buffer:
            return None
        stacked = np.vstack([pair[0] for pair in self._consensus_buffer.values()])
        mean_vec = np.mean(stacked, axis=0)
        norm = float(np.linalg.norm(mean_vec))
        if norm < 1e-12:
            return mean_vec
        return mean_vec / norm

    def submit_lane_state(
        self,
        lane_name: str,
        vec_64d: Any,
        tier_mode: Optional[int] = None,
        normalize_s63: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, Optional[np.ndarray], GatewayVerdict]:
        lane = normalize_lane_name(lane_name)
        tier = self.default_tier if tier_mode is None else int(tier_mode)
        verdict = self._engine.evaluate_vector(
            f"MTSC12_{lane.upper()}", lane, vec_64d, tier, normalize_s63, metadata
        )
        if not verdict.gate_pass:
            return False, None, verdict
        clean_vec = q2_30_to_float64(verdict.sanitized_vec_q30)
        with self._buf_lock:
            self._consensus_buffer[lane] = (clean_vec, verdict)
        return True, clean_vec, verdict

    def evaluate_handoff_batch(
        self,
        lane_states: Dict[str, Any],
        tier_mode: Optional[int] = None,
        normalize_s63: bool = False,
        reset_round: bool = True,
    ) -> Dict[str, Any]:
        if reset_round:
            self.reset_consensus()
        admitted: List[str] = []
        isolated: List[str] = []
        verdicts: Dict[str, Dict[str, Any]] = {}
        for raw_lane, vec in lane_states.items():
            ok, _, v = self.submit_lane_state(raw_lane, vec, tier_mode, normalize_s63)
            verdicts[v.subject_id] = v.to_summary_dict()
            if ok:
                admitted.append(v.subject_id)
            else:
                isolated.append(v.subject_id)
        with self._buf_lock:
            consensus = self._compute_consensus_unlocked()
            shared_keys = sorted(self._consensus_buffer.keys())
        return {
            "admitted_lanes": admitted,
            "isolated_lanes": isolated,
            "admitted_count": len(admitted),
            "isolated_count": len(isolated),
            "shared_buffer_lanes": shared_keys,
            "consensus_vector": consensus,
            "verdicts": verdicts,
        }


class VMaxIntegrityGateway:
    """Unified Stage 4 Integrity Gateway exposing Memory, MTSC-12, and HUD Telemetry."""

    def __init__(
        self,
        ledger_file: str = "VMAX_GATEWAY_PROD_LEDGER.jsonl",
        quarantine_file: str = "VMAX_GATEWAY_QUARANTINE_LEDGER.jsonl",
        store: Optional[Any] = None,
        default_tier: int = TIER_0_PURE_CARRIER,
        verify_v4: bool = False,
        so_path: Optional[str] = None,
    ) -> None:
        self.quarantine_ring = QuarantineRing()
        self.ledger = CanonicalLedgerManager(
            ledger_file=ledger_file,
            quarantine_file=quarantine_file,
        )
        self._engine = _GatewayTelemetryEngine(
            ledger=self.ledger,
            quarantine_ring=self.quarantine_ring,
            so_path=so_path,
            verify_v4=verify_v4,
        )
        self.memory_gate = MemoryIntegrityGate(self._engine, store=store, default_tier=default_tier)
        self.multi_agent_gate = MultiAgentCoherenceGateway(self._engine, default_tier=default_tier)

    def get_metrics(self) -> Dict[str, Any]:
        with self._engine._lock:
            latest = (
                self._engine.latest_verdict.to_summary_dict()
                if self._engine.latest_verdict is not None
                else None
            )
            return {
                "tx_total": self._engine.tx_total,
                "admitted_count": self._engine.admitted_count,
                "vetoed_count": self._engine.vetoed_count,
                "quarantine_depth": len(self.quarantine_ring),
                "multi_agent_lanes_active": self.multi_agent_gate.active_lane_count(),
                "rtl_cabi_active": self._engine.bridge.rtl_active,
                "verify_v4_enabled": self._engine.verify_v4,
                "latest_verdict": latest,
            }
