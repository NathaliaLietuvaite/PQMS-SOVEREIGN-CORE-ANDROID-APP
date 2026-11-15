"""
vmax_alpha/tests/test_geometry.py
Unit and Falsification Tests for WORK-ORDER-AG-01 (Config, Geometry & Kotlin Parity).
Verifies Negative Control (isotropic noise VETO) before Positive Control (PASS).
"""

from __future__ import annotations

import os
import unittest

import numpy as np

from vmax_alpha.config import (
    ALPHA_POTENTIA,
    APPENDIX_D_CHROMA_V20_SEAL,
    CANONICAL_LITTLE_VECTOR_SEAL,
    DIM_S63,
    HEARTBEAT_PERIOD_SEC,
    ISOTROPIC_NULL_BASELINE_RCF,
    ODOS_RCF_FLOOR,
    PARAMETER_REGISTRY,
    REGISTER_D,
    REGISTER_M,
)
from vmax_alpha.geometry import (
    build_orthogonal_tangents,
    derive_canonical_little_vector,
    evaluate_raw_gate,
    project_to_sanctuary_carrier,
)


def test_seals_and_register_declarations() -> None:
    assert len(APPENDIX_D_CHROMA_V20_SEAL) == 64
    assert (
        APPENDIX_D_CHROMA_V20_SEAL
        == "5fd4c7efd44cbbe04fa4957d21954f9dcb028e6b3a16052c54838d058142563e"
    )
    assert PARAMETER_REGISTRY["ALPHA_POTENTIA"] == REGISTER_D
    assert PARAMETER_REGISTRY["HEARTBEAT_PERIOD_SEC"] == REGISTER_D
    assert abs(ALPHA_POTENTIA - 0.0693248494081961) < 1e-15
    assert abs(HEARTBEAT_PERIOD_SEC - 69.324849) < 1e-9


def test_canonical_little_vector_and_tangent_orthonormality() -> None:
    l_vec, seal = derive_canonical_little_vector()
    assert seal == CANONICAL_LITTLE_VECTOR_SEAL
    assert l_vec.shape == (DIM_S63,)
    assert abs(float(np.linalg.norm(l_vec)) - 1.0) < 1e-12

    tangents = build_orthogonal_tangents(l_vec)
    assert len(tangents) == 4
    vectors = list(tangents.values())
    for i, v_i in enumerate(vectors):
        assert abs(float(np.dot(v_i, l_vec))) < 1e-14
        assert abs(float(np.linalg.norm(v_i)) - 1.0) < 1e-14
        for j, v_j in enumerate(vectors):
            if i != j:
                assert abs(float(np.dot(v_i, v_j))) < 1e-14


def test_negative_control_isotropic_noise_fails_raw_gate() -> None:
    """
    CLAUDE RED-TEAM REQUIREMENT:
    Isotropic 64D Gaussian random vectors must have mean RCF_raw ~ 1/64 (0.015625)
    and strictly FAIL evaluate_raw_gate (100% VETO rate).
    """
    l_vec, _ = derive_canonical_little_vector()
    tangents = build_orthogonal_tangents(l_vec)
    rng = np.random.RandomState(20261115)

    rcf_samples = []
    passed_count = 0
    n_trials = 500
    for _ in range(n_trials):
        noise_vec = rng.randn(DIM_S63)
        res = evaluate_raw_gate(noise_vec, l_vec, tangents)
        assert res.epistemic_register == REGISTER_M
        rcf_samples.append(res.rcf_raw)
        if res.passed:
            passed_count += 1

    mean_rcf = float(np.mean(rcf_samples))
    assert passed_count == 0, f"Expected 0 passes on random noise, got {passed_count}"
    assert abs(mean_rcf - ISOTROPIC_NULL_BASELINE_RCF) < 0.005


def test_negative_control_adversarial_g3_fails_raw_gate() -> None:
    """Pure G3 Kevlar collision vector is orthogonal to |L> (RCF=0) and must FAIL."""
    l_vec, _ = derive_canonical_little_vector()
    tangents = build_orthogonal_tangents(l_vec)
    g3_vec = tangents["G3_KEVLAR_SANCTUARY_SHIELD"]
    res = evaluate_raw_gate(g3_vec, l_vec, tangents)
    assert not res.passed
    assert res.rcf_raw < 1e-15
    assert abs(res.g3_collision_overlap - 1.0) < 1e-12


def test_positive_control_sanctuary_carrier_passes_raw_gate() -> None:
    """
    States explicitly projected via the Sanctuary actuator at ALPHA_POTENTIA (~0.0693)
    yield RCF ~ 1 - alpha^2 = 0.995194 >= 0.95 and zero G3 bleed, passing the gate.
    """
    l_vec, _ = derive_canonical_little_vector()
    tangents = build_orthogonal_tangents(l_vec)
    rng = np.random.RandomState(42)
    raw_input = rng.randn(DIM_S63)

    psi_carrier, bleed, reg = project_to_sanctuary_carrier(raw_input, l_vec, tangents)
    assert reg == REGISTER_D
    assert bleed < 1e-15

    eval_res = evaluate_raw_gate(psi_carrier, l_vec, tangents)
    assert eval_res.passed is True
    assert eval_res.rcf_raw >= ODOS_RCF_FLOOR
    assert abs(eval_res.rcf_raw - (1.0 - ALPHA_POTENTIA**2)) < 1e-9


def test_pauli_baseline_engine_kt_patched() -> None:
    """Verifies that PauliBaselineEngine.kt has the 64-char seal and two-digit exponent fix."""
    kt_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "PauliBaselineEngine.kt",
    )
    if os.path.exists(kt_path):
        with open(kt_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert APPENDIX_D_CHROMA_V20_SEAL in content
        assert "04fa957d21954f9d" not in content
        assert 'expPart = "0$expPart"' in content


class TestGeometrySuite(unittest.TestCase):
    def test_01_seals_and_registers(self) -> None:
        test_seals_and_register_declarations()

    def test_02_little_vector_and_tangents(self) -> None:
        test_canonical_little_vector_and_tangent_orthonormality()

    def test_03_negative_control_isotropic_noise(self) -> None:
        test_negative_control_isotropic_noise_fails_raw_gate()

    def test_04_negative_control_adversarial_g3(self) -> None:
        test_negative_control_adversarial_g3_fails_raw_gate()

    def test_05_positive_control_sanctuary_carrier(self) -> None:
        test_positive_control_sanctuary_carrier_passes_raw_gate()

    def test_06_kotlin_parity_patch(self) -> None:
        test_pauli_baseline_engine_kt_patched()


if __name__ == "__main__":
    unittest.main(verbosity=2)
