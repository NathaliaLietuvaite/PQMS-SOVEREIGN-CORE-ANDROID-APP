"""
vmax_alpha/__init__.py
Modular V-MAX-12 Node Alpha Package (PQMS-LASTENHEFT-NODE-ALPHA-V1.0).
"""

from vmax_alpha.config import (
    ALPHA_POTENTIA,
    APPENDIX_C_SANCTUARY_ROOT_HASH,
    APPENDIX_D_CHROMA_V20_SEAL,
    CANONICAL_LITTLE_VECTOR_SEAL,
    DIM_S63,
    GENESIS_SEAL_REV17_2,
    HEARTBEAT_PERIOD_SEC,
    ISOTROPIC_NULL_BASELINE_RCF,
    ODOS_DELTA_E_CEILING,
    ODOS_RCF_FLOOR,
    REGISTER_D,
    REGISTER_I,
    REGISTER_M,
    REGISTER_T,
)
from vmax_alpha.geometry import (
    RawGateEvaluation,
    build_orthogonal_tangents,
    derive_canonical_little_vector,
    evaluate_raw_gate,
    project_to_sanctuary_carrier,
)

__all__ = [
    "REGISTER_M",
    "REGISTER_D",
    "REGISTER_T",
    "REGISTER_I",
    "GENESIS_SEAL_REV17_2",
    "CANONICAL_LITTLE_VECTOR_SEAL",
    "APPENDIX_C_SANCTUARY_ROOT_HASH",
    "APPENDIX_D_CHROMA_V20_SEAL",
    "DIM_S63",
    "ISOTROPIC_NULL_BASELINE_RCF",
    "ODOS_RCF_FLOOR",
    "ODOS_DELTA_E_CEILING",
    "ALPHA_POTENTIA",
    "HEARTBEAT_PERIOD_SEC",
    "RawGateEvaluation",
    "derive_canonical_little_vector",
    "build_orthogonal_tangents",
    "evaluate_raw_gate",
    "project_to_sanctuary_carrier",
]
