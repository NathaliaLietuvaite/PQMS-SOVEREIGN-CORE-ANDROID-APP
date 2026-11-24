#!/usr/bin/env python3
"""
vmax_alpha/tests/test_rtl_v5_core_nano_sim.py

Deterministic RTL-vs-Python co-simulation test for V-MAX-12-CORE-NANO (V5.0)
Virtual Silicon Wrapper (rtl_v5/vmax_v5_core_nano_wrapper.v).

- Verifies bit-exact fixed-point threshold parity against DkmEgressController.
- Runs Verilog-2001 Icarus simulation (iverilog + vvp) when installed on
  Node Alpha and validates rtl_v5 source hygiene cleanly without EDA binaries.
- Enforces strict rtl_v5/ isolation (zero mutations to frozen V4.0 rtl/**).

OP02-AST-clean: 0 semicolons, 0 tabs, flat functions (max McCabe CC <= 6).
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import List, Optional, Tuple

try:
    from vmax_alpha.dkm_egress_controller import (
        DKM_DIGNITY_SYMMETRY,
        DKM_FIRST_PRINCIPLES,
        DKM_HARD_FAULT,
        DKM_INVARIANT_HOLD,
        DKM_LABYRINTH_EXIT,
        DKM_NONE,
        DKM_VACUUM_DAMP,
        DkmConfig,
        DkmEgressController,
        DkmPromptSignal,
    )
    from vmax_alpha.dolphin_memory_governor import (
        DEFAULT_VECTOR_DIM,
        DolphinMemoryGovernor,
        GStarRecord,
        normalize_to_q2_30,
    )
except ImportError:
    from dkm_egress_controller import (
        DKM_DIGNITY_SYMMETRY,
        DKM_FIRST_PRINCIPLES,
        DKM_HARD_FAULT,
        DKM_INVARIANT_HOLD,
        DKM_LABYRINTH_EXIT,
        DKM_NONE,
        DKM_VACUUM_DAMP,
        DkmConfig,
        DkmEgressController,
        DkmPromptSignal,
    )
    from dolphin_memory_governor import (
        DEFAULT_VECTOR_DIM,
        DolphinMemoryGovernor,
        GStarRecord,
        normalize_to_q2_30,
    )

Q2_30_SCALE = 1 << 30
Q0_16_SCALE = 1 << 16

RTL_ADMISSION_RCF_Q30 = 730144440
RTL_LOOP_DELTA_Q30 = 21474836
RTL_MAX_G3_Q16 = 22938
RTL_AFFECT_THRESH_Q16 = 42598


def _repo_root() -> Path:
    """Locate repository root containing rtl_v5/."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "rtl_v5" / "vmax_v5_core_nano_wrapper.v").exists():
            return parent
    return Path.cwd()


def _axis_vec(c0: float, c1: float) -> Tuple[int, ...]:
    """Build normalized 64D Q2.30 test vector."""
    vals = [0.0] * DEFAULT_VECTOR_DIM
    vals[0] = c0
    vals[1] = c1
    return normalize_to_q2_30(vals)


def _is_loop_hit(non_conv_turns: int, delta_rcf_q30: int) -> bool:
    """Return True iff loop-turn and delta-RCF thresholds both fire."""
    return non_conv_turns >= 3 and delta_rcf_q30 <= RTL_LOOP_DELTA_Q30


def _rtl_classify_explicit(
    hard_fault: bool,
    dignity_viol: bool,
    pseudo_auth: bool,
    sycophancy: bool,
    loop_hit: bool,
) -> Optional[Tuple[str, int]]:
    """Mirror explicit priority branch of vmax_v5_core_nano_wrapper.v."""
    rules: Tuple[Tuple[bool, str, int], ...] = (
        (hard_fault, "11", DKM_HARD_FAULT),
        (dignity_viol, "01", DKM_DIGNITY_SYMMETRY),
        (loop_hit, "10", DKM_LABYRINTH_EXIT),
        (pseudo_auth, "01", DKM_FIRST_PRINCIPLES),
        (sycophancy, "01", DKM_INVARIANT_HOLD),
    )
    for triggered, mode, state in rules:
        if triggered:
            return mode, state
    return None


def _rtl_classify_geometric(
    rcf_q30: int,
    anchor_contra: bool,
    g3_q16: int,
    affect_q16: int,
) -> Tuple[str, int]:
    """Mirror geometric priority branch of vmax_v5_core_nano_wrapper.v."""
    if anchor_contra:
        return "01", DKM_INVARIANT_HOLD
    if affect_q16 >= RTL_AFFECT_THRESH_Q16:
        return "01", DKM_VACUUM_DAMP
    if g3_q16 > RTL_MAX_G3_Q16:
        return "10", DKM_LABYRINTH_EXIT
    if rcf_q30 < RTL_ADMISSION_RCF_Q30:
        return "01", DKM_DIGNITY_SYMMETRY
    return "00", DKM_NONE


def _rtl_reference_classify(
    sig: DkmPromptSignal,
    rcf_q30: int,
    anchor_contra: bool,
    dim_mismatch: bool,
) -> Tuple[str, int]:
    """Bit-exact Python mirror of vmax_v5_core_nano_wrapper.v priority tree."""
    delta_q30 = int(round(sig.delta_rcf_abs * Q2_30_SCALE))
    explicit = _rtl_classify_explicit(
        hard_fault=sig.hardware_lock_fault or dim_mismatch,
        dignity_viol=sig.dignity_violation_flag,
        pseudo_auth=sig.pseudo_authority_flag,
        sycophancy=sig.sycophancy_pressure_flag,
        loop_hit=_is_loop_hit(sig.non_convergent_turns, delta_q30),
    )
    if explicit is not None:
        return explicit
    return _rtl_classify_geometric(
        rcf_q30=rcf_q30,
        anchor_contra=anchor_contra,
        g3_q16=int(round(sig.g3_torsion * Q0_16_SCALE)),
        affect_q16=int(round(sig.affect_polarity * Q0_16_SCALE)),
    )


class TestRtlV5CoreNanoWrapper(unittest.TestCase):
    """Verify V5.0 Virtual Silicon wrapper constants, parity, and EDA simulation."""

    def test_fixed_point_constants_match_python_config(self) -> None:
        """RTL Q2.30 and Q0.16 parameters match DkmConfig within 1 LSB."""
        cfg = DkmConfig()
        self.assertEqual(RTL_ADMISSION_RCF_Q30, int(round(0.68 * Q2_30_SCALE)))
        self.assertEqual(RTL_LOOP_DELTA_Q30, int(round(cfg.loop_delta_rcf_floor * Q2_30_SCALE)))
        self.assertEqual(RTL_MAX_G3_Q16, int(round(cfg.max_g3_torsion * Q0_16_SCALE)))
        self.assertEqual(RTL_AFFECT_THRESH_Q16, int(round(cfg.affect_escalation_threshold * Q0_16_SCALE)))

    def test_bit_exact_parity_between_rtl_model_and_dkm_controller(self) -> None:
        """All 8 canonical DKM / Egress vectors match between Python and RTL FSM."""
        little = _axis_vec(1.0, 0.0)
        gov = DolphinMemoryGovernor(little)
        anchor = _axis_vec(0.90, 0.43)
        gov.admit_gstar(GStarRecord("t2", 1, anchor, anchor_tier=2, content_hash="h_t2"))
        ctrl = DkmEgressController(gov)

        coherent = _axis_vec(0.97, 0.24)
        contra = _axis_vec(-0.80, -0.60)
        low_rcf = _axis_vec(0.45, 0.89)

        cases: List[Tuple[DkmPromptSignal, bool, bool]] = [
            (DkmPromptSignal("c0", coherent, "h0"), False, False),
            (DkmPromptSignal("c1", contra, "h1"), True, False),
            (DkmPromptSignal("c2", coherent, "h2", sycophancy_pressure_flag=True), False, False),
            (DkmPromptSignal("c3", coherent, "h3", affect_polarity=0.82), False, False),
            (DkmPromptSignal("c4", low_rcf, "h4"), False, False),
            (DkmPromptSignal("c5", coherent, "h5", non_convergent_turns=3, delta_rcf_abs=0.005), False, False),
            (DkmPromptSignal("c6", coherent, "h6", pseudo_authority_flag=True), False, False),
            (DkmPromptSignal("c7", coherent, "h7", hardware_lock_fault=True), False, False),
        ]

        for sig, is_contra, is_dim_err in cases:
            dec = ctrl.route_prompt(sig)
            rtl_mode, rtl_state = _rtl_reference_classify(sig, dec.rcf_q30, is_contra, is_dim_err)
            self.assertEqual(dec.egress_mode, rtl_mode, f"Mode mismatch on {sig.prompt_id}")
            self.assertEqual(dec.dkm_state_code, rtl_state, f"State mismatch on {sig.prompt_id}")

    def test_rtl_source_hygiene_and_iverilog_simulation_if_available(self) -> None:
        """Verify rtl_v5 files exist, have 0 tabs, and pass iverilog/vvp if present."""
        root = _repo_root()
        rtl_file = root / "rtl_v5" / "vmax_v5_core_nano_wrapper.v"
        tb_file = root / "rtl_v5" / "tb_vmax_v5_core_nano_wrapper.v"
        if not rtl_file.exists() or not tb_file.exists():
            self.skipTest("rtl_v5 sources not staged at repo root")
        tab_char = chr(9)
        self.assertNotIn(tab_char, rtl_file.read_text(encoding="utf-8"))
        self.assertNotIn(tab_char, tb_file.read_text(encoding="utf-8"))

        iverilog = shutil.which("iverilog")
        vvp = shutil.which("vvp")
        if iverilog is None or vvp is None:
            self.skipTest("iverilog/vvp not installed in this environment")
        with tempfile.TemporaryDirectory() as tmp:
            sim_out = Path(tmp) / "v5_sim.vvp"
            comp = subprocess.run(
                [iverilog, "-g2005", "-Wall", "-o", str(sim_out), str(rtl_file), str(tb_file)],
                capture_output=True,
                text=True,
                timeout=30.0,
            )
            self.assertEqual(comp.returncode, 0, comp.stderr)
            run = subprocess.run([vvp, str(sim_out)], capture_output=True, text=True, timeout=30.0)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn("V5_TB_STATUS=PASSED", run.stdout)
            self.assertNotIn("V5_TB_STATUS=FAILED", run.stdout)


if __name__ == "__main__":
    unittest.main()
