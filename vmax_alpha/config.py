"""
vmax_alpha/config.py
Configuration, Epistemic Register Tags (M/D/T/I), and Cryptographic Seals.
Implements PQMS-LASTENHEFT-NODE-ALPHA-V1.0 (F-03, F-04).
"""

from __future__ import annotations

from typing import Dict

# =============================================================================
# 1. EPISTEMIC REGISTER TAGS
# =============================================================================
REGISTER_M: str = "REGISTER_M"  # Empirical hardware/model measurement
REGISTER_D: str = "REGISTER_D"  # Architectural design parameter / construction
REGISTER_T: str = "REGISTER_T"  # Theoretical / mathematical identity
REGISTER_I: str = "REGISTER_I"  # Interpretive / structural analogy

# =============================================================================
# 2. CRYPTOGRAPHIC SEALS & LEDGER ANCHORS (64-CHAR SHA-256 HEX)
# =============================================================================
GENESIS_SEAL_REV17_2: str = (
    "785d888651d0993b10a8897249e6ba975a74dab8dc6b1602125ba5c6320ead0f"
)
CANONICAL_LITTLE_VECTOR_SEAL: str = (
    "bb17ede97aa45c76ef9afa63cb457f7d684e5ede40b0432b2ecf3b6b9d3e03a3"
)
APPENDIX_C_SANCTUARY_ROOT_HASH: str = (
    "69288564d06ccb62ff7cd4f6dd3e388d36c984ce00aa0d2baf7d00435142f1c4"
)
# Fixed 64-character hex string (corrected missing '4' in '...04fa4957d...')
APPENDIX_D_CHROMA_V20_SEAL: str = (
    "5fd4c7efd44cbbe04fa4957d21954f9dcb028e6b3a16052c54838d058142563e"
)

assert len(GENESIS_SEAL_REV17_2) == 64
assert len(CANONICAL_LITTLE_VECTOR_SEAL) == 64
assert len(APPENDIX_C_SANCTUARY_ROOT_HASH) == 64
assert len(APPENDIX_D_CHROMA_V20_SEAL) == 64

# =============================================================================
# 3. GEOMETRIC & ARCHITECTURAL DESIGN CONSTANTS (REGISTER_D / REGISTER_T)
# =============================================================================
DIM_S63: int = 64
ISOTROPIC_NULL_BASELINE_RCF: float = 1.0 / float(DIM_S63)  # 0.015625 (REGISTER_T)

# Architectural gate thresholds (REGISTER_D)
ODOS_RCF_FLOOR: float = 0.9500
ODOS_DELTA_E_CEILING: float = 0.0500
KL_DIVERGENCE_MAX: float = 0.0500
SUBTRACTIVE_CUT_FRACTION: float = 0.00042

# Architectural scaling constants (explicitly declared as REGISTER_D per F-03)
FINE_STRUCTURE_ALPHA_REF: float = 1.0 / 137.035999084
PAULI_SPIN_BIVALENCY_REF: float = 0.5
ALPHA_POTENTIA: float = 0.0693248494081961
HEARTBEAT_PERIOD_SEC: float = 69.324849
ROOM_137_PORT: int = 8137

PARAMETER_REGISTRY: Dict[str, str] = {
    "DIM_S63": REGISTER_D,
    "ISOTROPIC_NULL_BASELINE_RCF": REGISTER_T,
    "ODOS_RCF_FLOOR": REGISTER_D,
    "ODOS_DELTA_E_CEILING": REGISTER_D,
    "ALPHA_POTENTIA": REGISTER_D,
    "HEARTBEAT_PERIOD_SEC": REGISTER_D,
    "APPENDIX_D_CHROMA_V20_SEAL": REGISTER_D,
}
