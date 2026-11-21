"""
vmax_alpha/gateway/__init__.py
Public exports for Stage 4 V-MAX-12 AI Memory & MTSC-12 Multi-Agent Integrity Middleware.
"""
from __future__ import annotations

from vmax_alpha.gateway.integrity_gateway import (
    ChromaCollectionAdapter,
    GatewayVerdict,
    InMemoryVectorStore,
    MTSC12_CANONICAL_LANES,
    MemoryIntegrityGate,
    MemoryRecord,
    MultiAgentCoherenceGateway,
    QuarantineRecord,
    QuarantineRing,
    VMaxIntegrityGateway,
    normalize_lane_name,
    q2_30_to_float64,
    quantize_state_q2_30,
)

__all__ = [
    "ChromaCollectionAdapter",
    "GatewayVerdict",
    "InMemoryVectorStore",
    "MTSC12_CANONICAL_LANES",
    "MemoryIntegrityGate",
    "MemoryRecord",
    "MultiAgentCoherenceGateway",
    "QuarantineRecord",
    "QuarantineRing",
    "VMaxIntegrityGateway",
    "normalize_lane_name",
    "q2_30_to_float64",
    "quantize_state_q2_30",
]
