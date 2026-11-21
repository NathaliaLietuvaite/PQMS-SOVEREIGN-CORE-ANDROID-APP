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

from vmax_alpha.gateway.chain_signer import (
    ChainStatus,
    ChainVerificationReport,
    HybridCorewareSigner,
    MLDSA65Spec,
    SignedChainEntry,
    SignedProvenanceChain,
)
from vmax_alpha.gateway.policy_engine import (
    Decision,
    Environment,
    EnvType,
    PolicyDecision,
    PolicyEngine,
    Privilege,
    RequestContext,
    infer_source_privilege,
    request_from_gateway_verdict,
    resolve_safe_output_limit,
)
from vmax_alpha.gateway.rack_l2_manifold import (
    MAX_L2_WINDOW_BYTES,
    LocalL2Mirror,
    ManifoldEpochSnapshot,
    MirrorReadVerdict,
    SharedL2Manifold,
)
from vmax_alpha.gateway.dual_core_arbiter import (
    ArbiterMode,
    ArbiterOutcome,
    CoreVerdictTuple,
    DualCoreArbiter,
)
from vmax_alpha.gateway.merkle_batcher import (
    MerkleEpochBatcher,
    MerkleInclusionReceipt,
    build_merkle_tree,
    extract_merkle_proof,
)
from vmax_alpha.gateway.electro_ramp import (
    ElectroThermalRampController,
    RampScheduleReport,
)
from vmax_alpha.gateway.thermal_gearbox import (
    ClockGear,
    CoreClockState,
    HeterogeneousPairCapacity,
    ThermalClockGearbox,
    select_core_gear,
)
from vmax_alpha.gateway.thermo_governor import (
    CduExergyCommand,
    ThermoAdmissionResult,
    ThermodynamicGovernor,
    compute_hbm_alpha,
)
