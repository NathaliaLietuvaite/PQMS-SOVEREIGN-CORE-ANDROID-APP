"""
vmax_alpha/geometry.py
Falsifiable S^63 Geometry, Canonical |L> Derivation, Tangent Bundle T_{|L>} S^63,
and Unclamped Raw ODOS Gate Evaluation (Nova P0 #1 & Claude #5 Hardened).
"""

from __future__ import annotations

import hashlib
import math
import struct
from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np

from vmax_alpha.config import (
    ALPHA_POTENTIA,
    CANONICAL_LITTLE_VECTOR_SEAL,
    DIM_S63,
    GENESIS_SEAL_REV17_2,
    ODOS_DELTA_E_CEILING,
    ODOS_RCF_FLOOR,
    REGISTER_D,
    REGISTER_M,
)

TANGENT_OPERATOR_NAMES: Tuple[str, str, str, str] = (
    "G1_SPATIAL_GEODESIC",
    "G2_THERMODYNAMIC_CONSERVATION",
    "G3_KEVLAR_SANCTUARY_SHIELD",
    "G4_KLAVIERSTUNDE_SYNCHRONICITY",
)

ODOS_G3_BLEED_CEILING: float = 1e-12


@dataclass(frozen=True)
class RawGateEvaluation:
    """
    Unclamped, falsifiable measurement of an arbitrary 64D state vector prior
    to any carrier mixing. Random isotropic vectors (~1/64 = 0.015625) fail.
    """

    epistemic_register: str
    rcf_raw: float
    delta_e_raw: float
    g3_collision_overlap: float
    g3_bleed_post_strip: float
    orthogonal_residual_norm: float
    passed: bool


def derive_canonical_little_vector(
    seed_hex: str = GENESIS_SEAL_REV17_2,
) -> Tuple[np.ndarray, str]:
    """
    Derives the canonical 64D unit vector |L> in S^63 from the Genesis Seal
    and verifies the little-endian <64f SHA-256 digest.
    """
    seed_bytes = seed_hex.encode("utf-8")
    blocks = [hashlib.sha256(seed_bytes + bytes([i])).digest() for i in range(8)]
    u32 = np.frombuffer(b"".join(blocks), dtype="<u4").astype(np.float64)
    l_f32 = (u32 / np.linalg.norm(u32)).astype("<f4")
    f32_seal = hashlib.sha256(struct.pack("<64f", *l_f32)).hexdigest()
    if seed_hex == GENESIS_SEAL_REV17_2 and f32_seal != CANONICAL_LITTLE_VECTOR_SEAL:
        raise ValueError(
            f"Canonical |L> seal mismatch: got {f32_seal}, expected {CANONICAL_LITTLE_VECTOR_SEAL}"
        )
    v = l_f32.astype(np.float64)
    return v / np.linalg.norm(v), f32_seal


def build_orthogonal_tangents(
    little_vector: np.ndarray, seed: int = 137
) -> Dict[str, np.ndarray]:
    """
    Constructs the 4 orthonormal tangent operators tau_1..tau_4 in T_{|L>} S^63
    via deterministic Gram-Schmidt orthogonalization against |L>.
    """
    rng = np.random.RandomState(seed)
    tangents: Dict[str, np.ndarray] = {}
    basis_list: List[np.ndarray] = []
    l_unit = little_vector / np.linalg.norm(little_vector)

    for name in TANGENT_OPERATOR_NAMES:
        t = rng.randn(DIM_S63).astype(np.float64)
        t -= float(np.dot(t, l_unit)) * l_unit
        for prev in basis_list:
            t -= float(np.dot(t, prev)) * prev
        norm = float(np.linalg.norm(t))
        if norm < 1e-12:
            raise RuntimeError(f"Degenerate tangent vector during Gram-Schmidt for {name}")
        t /= norm
        basis_list.append(t)
        tangents[name] = t
    return tangents


def evaluate_raw_gate(
    vec_64d: np.ndarray,
    little_vector: np.ndarray,
    tangents: Dict[str, np.ndarray],
    rcf_floor: float = ODOS_RCF_FLOOR,
    delta_e_ceiling: float = ODOS_DELTA_E_CEILING,
    g3_bleed_ceiling: float = ODOS_G3_BLEED_CEILING,
) -> RawGateEvaluation:
    """
    Normative Unclamped Gate Evaluation (F-01 / F-06 / Nova P0 #1 & Claude #5):
    Evaluates raw input vector `vec_64d` BEFORE any carrier mixing:
      - rcf_raw = |<vec_u | L>|^2
      - g3_collision_overlap = |<vec_u | t_G3>| (pre-strip)
      - delta_e_raw = 0.5 * (1.0 - rcf_raw) + 0.5 * min(1.0, g3_collision_overlap)
      - g3_bleed_post_strip = |<vec_stripped | t_G3>| (or 1.0 if pure G3 collision)
      - passed = (rcf_raw >= rcf_floor) and (delta_e_raw <= delta_e_ceiling) and (g3_bleed_post_strip <= g3_bleed_ceiling)
    """
    arr = np.asarray(vec_64d, dtype=np.float64).reshape(-1)
    if arr.shape[0] != DIM_S63:
        raise ValueError(f"Expected {DIM_S63}D vector, got {arr.shape[0]}D")
    norm = float(np.linalg.norm(arr))
    if norm < 1e-15 or not np.all(np.isfinite(arr)):
        return RawGateEvaluation(REGISTER_M, 0.0, 1.0, 1.0, 1.0, 1.0, False)

    vec_u = arr / norm
    l_u = little_vector / np.linalg.norm(little_vector)

    overlap = float(np.dot(vec_u, l_u))
    rcf_raw = overlap * overlap

    ortho_vec = vec_u - overlap * l_u
    ortho_norm = float(np.linalg.norm(ortho_vec))

    t_g3 = tangents["G3_KEVLAR_SANCTUARY_SHIELD"]
    g3_collision_overlap = abs(float(np.dot(vec_u, t_g3)))

    v_stripped = vec_u - float(np.dot(vec_u, t_g3)) * t_g3
    strip_norm = float(np.linalg.norm(v_stripped))
    if strip_norm < 1e-9:
        g3_bleed_post_strip = 1.0
    else:
        v_stripped /= strip_norm
        g3_bleed_post_strip = abs(float(np.dot(v_stripped, t_g3)))

    delta_e_raw = float(0.5 * (1.0 - rcf_raw) + 0.5 * min(1.0, g3_collision_overlap))
    passed = bool(
        (rcf_raw >= rcf_floor)
        and (delta_e_raw <= delta_e_ceiling)
        and (g3_bleed_post_strip <= g3_bleed_ceiling)
    )

    return RawGateEvaluation(
        epistemic_register=REGISTER_M,
        rcf_raw=rcf_raw,
        delta_e_raw=delta_e_raw,
        g3_collision_overlap=g3_collision_overlap,
        g3_bleed_post_strip=g3_bleed_post_strip,
        orthogonal_residual_norm=ortho_norm,
        passed=passed,
    )


def project_to_sanctuary_carrier(
    vec_64d: np.ndarray,
    little_vector: np.ndarray,
    tangents: Dict[str, np.ndarray],
    alpha_amp: float = ALPHA_POTENTIA,
) -> Tuple[np.ndarray, float, str]:
    """
    State Actuator (REGISTER_D): Strips the G3 collision component in T_{|L>} S^63
    and modulates the carrier state at amplitude `alpha_amp`.
    Separated strictly from `evaluate_raw_gate`.
    """
    arr = np.asarray(vec_64d, dtype=np.float64).reshape(-1)
    l_u = little_vector / np.linalg.norm(little_vector)
    t_raw = arr - float(np.dot(arr, l_u)) * l_u
    raw_norm = float(np.linalg.norm(t_raw))
    t_raw = tangents["G1_SPATIAL_GEODESIC"].copy() if raw_norm < 1e-12 else t_raw / raw_norm

    t_g3 = tangents["G3_KEVLAR_SANCTUARY_SHIELD"]
    t_clean = t_raw - float(np.dot(t_raw, t_g3)) * t_g3
    t_clean -= float(np.dot(t_clean, l_u)) * l_u
    t_clean /= float(np.linalg.norm(t_clean))

    safety_bleed = abs(float(np.dot(t_clean, t_g3)))
    amp = max(0.0, min(float(alpha_amp), 0.999999))
    psi = math.sqrt(1.0 - amp * amp) * l_u + amp * t_clean
    psi /= float(np.linalg.norm(psi))
    return psi, safety_bleed, REGISTER_D
