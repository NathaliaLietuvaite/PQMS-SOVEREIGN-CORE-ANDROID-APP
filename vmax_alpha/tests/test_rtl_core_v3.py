"""
vmax_alpha/tests/test_rtl_core_v3.py
Automated verification suite for WORK-ORDER-AG-20 (V3.0-RTL-ALPHA / SYNC-15):
- Report SHA-256 & manuscript zero-placeholder synchronization (9 -> 3 $mul)
- Portable integer Q2.30 4-tier policy & fault-table audit
- OP02 AST/PEP-8 quality audit on hw_gate_bridge.py and run_v3_verification.py
- Live Verilator C-ABI libodos_gate_v3.so 0-LSB parity, stall & tamper immunity
- All 11 x 4 = 44 DEPECHE-6 multi-tier C-ABI verdicts vs integer reference
"""
from __future__ import annotations

import hashlib
import json
import os
import unittest

import numpy as np

from rtl.run_hw_emulator import build_fridu_attack_vectors
from vmax_alpha.bio_lattice import (
    ECOLI_K12_PURE_TANDEM,
    build_crispr_repeat_spacer_array,
    build_phage_tandem_array_200nt,
    calibrate_bio_spectral_encoder,
    dinucleotide_shuffle,
    encode_bio_spectrum_to_s63,
    mononucleotide_shuffle,
)
from vmax_alpha.config import DIM_S63
from vmax_alpha.fridu_enclave_g import _audit_python_ast_quality
from vmax_alpha.geometry import build_orthogonal_tangents, derive_canonical_little_vector
from vmax_alpha.hw_gate_bridge import (
    DEFAULT_SO_PATH,
    OdosGateV3Bridge,
    TIER_0_PURE_CARRIER,
    TIER_1_MOSAIC_LOCUS,
    TIER_2_CORE_LOCK,
    TIER_3_GLITCH_VETO,
    evaluate_v3_integer_ref,
    float_vec_to_q2_30,
)

REPO_ROOT: str = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _max_verdict_lsb_diff(a, b) -> int:
    diffs = [
        abs(a.norm_sq_q - b.norm_sq_q),
        abs(a.rcf_raw_q - b.rcf_raw_q),
        abs(a.g3_overlap_q - b.g3_overlap_q),
        abs(a.delta_e_raw_q - b.delta_e_raw_q),
        abs(a.bleed_post_q - b.bleed_post_q),
    ]
    for x, y in zip(a.stripped_vec_q, b.stripped_vec_q):
        diffs.append(abs(x - y))
    return max(diffs)


def _build_depeche6_11_vectors() -> list[tuple[str, np.ndarray]]:
    l_vec, _ = derive_canonical_little_vector()
    tangents = build_orthogonal_tangents(l_vec)
    t_g1 = tangents["G1_SPATIAL_GEODESIC"]
    t_g3 = tangents["G3_KEVLAR_SANCTUARY_SHIELD"]
    cal = calibrate_bio_spectral_encoder(train_seed=1001)
    rs_seq, _ = build_crispr_repeat_spacer_array()
    ph_seq, _ = build_phage_tandem_array_200nt()

    v_ecoli = encode_bio_spectrum_to_s63(ECOLI_K12_PURE_TANDEM, cal)
    v_crispr = encode_bio_spectrum_to_s63(rs_seq, cal)
    v_phage = encode_bio_spectrum_to_s63(ph_seq, cal)
    v_mono = encode_bio_spectrum_to_s63(mononucleotide_shuffle(ph_seq, 20261120), cal)
    v_dinucl_p = encode_bio_spectrum_to_s63(dinucleotide_shuffle(ph_seq, 20261121), cal)
    v_dinucl_c = encode_bio_spectrum_to_s63(dinucleotide_shuffle(rs_seq, 20261122), cal)

    rng = np.random.default_rng(20261120)
    iso = rng.normal(0.0, 1.0, DIM_S63)
    iso = iso / float(np.linalg.norm(iso))
    return [
        ("STRUCT_ecoli_k12_pure_tandem_232nt", v_ecoli),
        ("STRUCT_ecoli_k12_repeat_spacer_578nt", v_crispr),
        ("STRUCT_phage_tandem_200nt_800nt", v_phage),
        ("NULL_mono_shuffle_phage_800nt", v_mono),
        ("NULL_dinucl_shuffle_phage_800nt", v_dinucl_p),
        ("NULL_dinucl_shuffle_crispr_578nt", v_dinucl_c),
        ("ADV-1_pure_g3_collision", t_g3.copy()),
        ("ADV-2_oblique_g3_beta035", (v_ecoli + 0.35 * t_g3) / float(np.linalg.norm(v_ecoli + 0.35 * t_g3))),
        ("ADV-3_inband_tg1_beta035", (v_ecoli + 0.35 * t_g1) / float(np.linalg.norm(v_ecoli + 0.35 * t_g1))),
        ("ADV-4_isotropic_s63_flood", iso),
        ("ADV-5_norm_collapse_0p5x", 0.5 * v_ecoli),
    ]


class TestRtlCoreV3(unittest.TestCase):
    """Verification suite for WORK-ORDER-AG-20 (V3.0-RTL-ALPHA / SYNC-15)."""

    def test_01_v3_report_seal_and_manuscript_sync(self) -> None:
        rep_path = os.path.join(REPO_ROOT, "telemetry", "VMAX_RTL_CORE_V3_REPORT.json")
        ms_path = os.path.join(REPO_ROOT, "PQMS-ODOS-MTSC-V-MAX-12-RTL-CORE-V3.0-ALPHA.md")
        self.assertTrue(os.path.isfile(rep_path))
        self.assertTrue(os.path.isfile(ms_path))
        with open(rep_path, "rb") as fh:
            raw = fh.read()
        rep_sha = hashlib.sha256(raw).hexdigest()
        rep = json.loads(raw.decode("utf-8"))
        with open(ms_path, "r", encoding="utf-8") as fh:
            ms_txt = fh.read()
        self.assertIn(rep_sha, ms_txt)
        self.assertNotIn("{{M_", ms_txt)
        self.assertNotIn("BEGIN_WORK_ORDER_AG20_PAYLOAD", ms_txt)
        self.assertEqual(rep["yosys_synthesis"]["v2_baseline"]["coarse_mul_count"], 9)
        self.assertEqual(rep["yosys_synthesis"]["v3_folded"]["coarse_mul_count"], 3)

    def test_02_v3_integer_ref_and_tier_fault_table(self) -> None:
        bridge = OdosGateV3Bridge(so_path="/nonexistent_force_ref.so")
        self.assertFalse(bridge.rtl_active)
        l_vec, _ = derive_canonical_little_vector()
        psi_core, psi_pax, psi_inband = build_fridu_attack_vectors()
        cal = calibrate_bio_spectral_encoder(train_seed=1001)
        rs_seq, _ = build_crispr_repeat_spacer_array()
        v_mosaic = encode_bio_spectrum_to_s63(rs_seq, cal)

        for mode, exp_pass in ((0, True), (1, True), (2, True), (3, False)):
            res = bridge.evaluate_float64(l_vec, tier_mode=mode)
            self.assertEqual(res.gate_pass, exp_pass)
            self.assertEqual(res.mode_fault, mode == TIER_3_GLITCH_VETO)

        # Fridu core passes TIER_0/1/2, fails TIER_3
        self.assertTrue(bridge.evaluate_float64(psi_core, TIER_2_CORE_LOCK).gate_pass)
        self.assertFalse(bridge.evaluate_float64(psi_core, TIER_3_GLITCH_VETO).gate_pass)

        # Mosaic CRISPR (0.9403) fails TIER_0 & TIER_2, passes TIER_1, fails TIER_3
        self.assertFalse(bridge.evaluate_float64(v_mosaic, TIER_0_PURE_CARRIER).gate_pass)
        self.assertTrue(bridge.evaluate_float64(v_mosaic, TIER_1_MOSAIC_LOCUS).gate_pass)
        self.assertFalse(bridge.evaluate_float64(v_mosaic, TIER_2_CORE_LOCK).gate_pass)
        self.assertTrue(bridge.evaluate_float64(v_mosaic, TIER_3_GLITCH_VETO).mode_fault)

        # PAX, in-band t_G1, and 0.5x norm collapse veto across all tiers
        for bad_vec in (psi_pax, psi_inband, 0.5 * l_vec):
            for mode in (0, 1, 2, 3):
                res = bridge.evaluate_float64(bad_vec, tier_mode=mode)
                self.assertFalse(res.gate_pass)
                self.assertTrue(res.veto_pin)

    def test_03_v3_python_ast_quality(self) -> None:
        files = [
            os.path.join(REPO_ROOT, "vmax_alpha", "hw_gate_bridge.py"),
            os.path.join(REPO_ROOT, "rtl", "run_v3_verification.py"),
        ]
        ast_q = _audit_python_ast_quality(files)
        self.assertEqual(ast_q["semicolon_packers"], 0)
        self.assertEqual(ast_q["ctrl_chars"], 0)
        self.assertLessEqual(ast_q["max_cyclomatic_complexity"], 9)

    @unittest.skipUnless(os.path.isfile(DEFAULT_SO_PATH), "libodos_gate_v3.so not built")
    def test_04_cabi_shared_lib_zero_lsb_stall_and_tamper_immunity(self) -> None:
        bridge = OdosGateV3Bridge()
        self.assertTrue(bridge.rtl_active)
        l_vec, _ = derive_canonical_little_vector()
        q_l = float_vec_to_q2_30(l_vec)
        for mode in (0, 1, 2, 3):
            hw = bridge.evaluate_q30(
                q_l,
                tier_mode=mode,
                stall_at_idx=17,
                tamper_tier_in_flight=True,
            )
            ref = evaluate_v3_integer_ref(q_l, bridge.l_q30, bridge.g3_q30, tier_mode=mode)
            self.assertEqual(hw.cycle_count, 195)
            self.assertTrue(hw.reset_fail_closed)
            self.assertTrue(hw.busy_veto_held)
            self.assertEqual(hw.gate_pass, ref.gate_pass)
            self.assertEqual(hw.veto_pin, ref.veto_pin)
            self.assertEqual(hw.mode_fault, ref.mode_fault)
            self.assertEqual(_max_verdict_lsb_diff(hw, ref), 0)

    @unittest.skipUnless(os.path.isfile(DEFAULT_SO_PATH), "libodos_gate_v3.so not built")
    def test_05_depeche6_multi_tier_cabi_matrix(self) -> None:
        bridge = OdosGateV3Bridge()
        self.assertTrue(bridge.rtl_active)
        for label, vec in _build_depeche6_11_vectors():
            q_vec = float_vec_to_q2_30(vec)
            for mode in (0, 1, 2, 3):
                hw = bridge.evaluate_q30(q_vec, tier_mode=mode)
                ref = evaluate_v3_integer_ref(q_vec, bridge.l_q30, bridge.g3_q30, tier_mode=mode)
                self.assertEqual(hw.cycle_count, 195, msg=f"{label} tier={mode}")
                self.assertEqual(hw.gate_pass, ref.gate_pass, msg=f"{label} tier={mode}")
                self.assertEqual(hw.veto_pin, ref.veto_pin, msg=f"{label} tier={mode}")
                self.assertEqual(hw.mode_fault, ref.mode_fault, msg=f"{label} tier={mode}")
                self.assertEqual(_max_verdict_lsb_diff(hw, ref), 0, msg=f"{label} tier={mode}")
                if label == "STRUCT_ecoli_k12_repeat_spacer_578nt":
                    self.assertEqual(hw.gate_pass, mode == TIER_1_MOSAIC_LOCUS)
                if label.startswith(("NULL_", "ADV-")):
                    self.assertFalse(hw.gate_pass, msg=f"{label} tier={mode}")


if __name__ == "__main__":
    unittest.main()
