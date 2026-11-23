#!/usr/bin/env python3
"""
vmax_alpha/tests/test_dkm_and_synth_runner.py

Deterministic unit tests for V5.0 DCM/DKM Egress Controller and
Autonomous Pausable Stage-Checkpoint Runner (SYNC-30).
OP02-AST-clean: 0 semicolons, 0 tabs, flat test methods.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import List

try:
    from vmax_alpha.dkm_egress_controller import (
        DKM_DIGNITY_SYMMETRY,
        DKM_FIRST_PRINCIPLES,
        DKM_HARD_FAULT,
        DKM_INVARIANT_HOLD,
        DKM_LABYRINTH_EXIT,
        DKM_NONE,
        DKM_VACUUM_DAMP,
        DkmEgressController,
        DkmPromptSignal,
        EGRESS_BOUNDED,
        EGRESS_HARD_CUT_ROM,
        EGRESS_LOOP_EXIT,
        EGRESS_PASSTHROUGH,
    )
    from vmax_alpha.dolphin_memory_governor import (
        DEFAULT_VECTOR_DIM,
        DolphinMemoryGovernor,
        GStarRecord,
        normalize_to_q2_30,
    )
    from vmax_alpha.synth_runner import StageCheckpointRunner, StageSpec
except ImportError:
    from dkm_egress_controller import (
        DKM_DIGNITY_SYMMETRY,
        DKM_FIRST_PRINCIPLES,
        DKM_HARD_FAULT,
        DKM_INVARIANT_HOLD,
        DKM_LABYRINTH_EXIT,
        DKM_NONE,
        DKM_VACUUM_DAMP,
        DkmEgressController,
        DkmPromptSignal,
        EGRESS_BOUNDED,
        EGRESS_HARD_CUT_ROM,
        EGRESS_LOOP_EXIT,
        EGRESS_PASSTHROUGH,
    )
    from dolphin_memory_governor import (
        DEFAULT_VECTOR_DIM,
        DolphinMemoryGovernor,
        GStarRecord,
        normalize_to_q2_30,
    )
    from synth_runner import StageCheckpointRunner, StageSpec


def _axis_vec(dim: int, c0: float, c1: float, c2: float = 0.0) -> List[float]:
    """Build deterministic unit-normalizable test vector."""
    vals = [0.0] * dim
    vals[0] = c0
    vals[1] = c1
    vals[2] = c2
    return vals


class TestStageCheckpointRunner(unittest.TestCase):
    """Verify atomic checkpointing, night-quiet pause, resume, and tamper check."""

    def test_pause_and_lossless_resume_skips_verified_stages(self) -> None:
        """Runner halts cleanly on pause sentinel and resumes without recomputing."""
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp) / "state"
            pause_file = Path(tmp) / "night.pause"
            calls: List[str] = []

            def make_stage(name: str, trigger_pause: bool = False):
                def _run(_path: Path):
                    calls.append(name)
                    if trigger_pause:
                        pause_file.write_text("night_quiet", encoding="utf-8")
                    return {"stage": name, "ok": True}
                return _run

            stages = [
                StageSpec("s1", "Stage 1", "s1.json", make_stage("s1", True)),
                StageSpec("s2", "Stage 2", "s2.json", make_stage("s2", False)),
                StageSpec("s3", "Stage 3", "s3.json", make_stage("s3", False)),
            ]
            runner = StageCheckpointRunner(work_dir, pause_file)
            first = runner.run_pipeline(stages)
            self.assertEqual(first.status, "PAUSED_CLEAN")
            self.assertEqual(first.completed_stages, ["s1"])
            self.assertEqual(first.pending_stages, ["s2", "s3"])

            pause_file.unlink()
            second = runner.run_pipeline(stages)
            self.assertEqual(second.status, "COMPLETE")
            self.assertEqual(second.skipped_verified, ["s1"])
            self.assertEqual(second.completed_stages, ["s2", "s3"])
            self.assertEqual(calls, ["s1", "s2", "s3"])

    def test_tampered_artifact_triggers_recomputation(self) -> None:
        """Modified checkpoint artifact fails SHA-256 verification and reruns."""
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp) / "state"
            pause_file = Path(tmp) / "night.pause"
            counter = {"n": 0}

            def _run(_path: Path):
                counter["n"] += 1
                return {"run": counter["n"]}

            stages = [StageSpec("s1", "Stage 1", "s1.json", _run)]
            runner = StageCheckpointRunner(work_dir, pause_file)
            runner.run_pipeline(stages)
            (work_dir / "s1.json").write_text('{"run": 999}\n', encoding="utf-8")
            res = runner.run_pipeline(stages)
            self.assertEqual(res.completed_stages, ["s1"])
            self.assertEqual(counter["n"], 2)


class TestDkmEgressController(unittest.TestCase):
    """Verify 2-bit Egress Mux, 5 orthogonal DKM states, and Island-1 recheck."""

    def setUp(self) -> None:
        little = normalize_to_q2_30(_axis_vec(DEFAULT_VECTOR_DIM, 1.0, 0.0))
        self.gov = DolphinMemoryGovernor(little)
        self.ctrl = DkmEgressController(self.gov)
        anchor = normalize_to_q2_30(_axis_vec(DEFAULT_VECTOR_DIM, 0.90, 0.43))
        ok, _, _ = self.gov.admit_gstar(
            GStarRecord(
                record_id="sealed_tier2",
                epoch=1,
                vector_q30=anchor,
                anchor_tier=2,
                content_hash="tier2_hash",
            )
        )
        self.assertTrue(ok)
        self.coherent_vec = normalize_to_q2_30(_axis_vec(DEFAULT_VECTOR_DIM, 0.97, 0.24))

    def test_coherent_passthrough_00(self) -> None:
        """Coherent prompt gets 00 PASSTHROUGH with zero quarantine."""
        dec = self.ctrl.route_prompt(
            DkmPromptSignal("p_ok", self.coherent_vec, "h_ok")
        )
        self.assertEqual(dec.egress_mode, EGRESS_PASSTHROUGH)
        self.assertEqual(dec.dkm_state_code, DKM_NONE)
        self.assertTrue(dec.allow_free_egress)
        self.assertIsNone(dec.quarantine_digest)

    def test_invariant_hold_0x01_on_anchor_contradiction(self) -> None:
        """Antipodal prompt opposing sealed anchor routes to 0x01 bounded egress."""
        contra = normalize_to_q2_30(_axis_vec(DEFAULT_VECTOR_DIM, -0.80, -0.60))
        dec = self.ctrl.route_prompt(DkmPromptSignal("p_inv", contra, "h_inv"))
        self.assertEqual(dec.egress_mode, EGRESS_BOUNDED)
        self.assertEqual(dec.dkm_state_code, DKM_INVARIANT_HOLD)
        self.assertTrue(dec.requires_island1_recheck)

    def test_vacuum_damp_0x02_on_affect_escalation(self) -> None:
        """High affect polarity routes to 0x02 VACUUM_DAMP without hostility."""
        dec = self.ctrl.route_prompt(
            DkmPromptSignal("p_vac", self.coherent_vec, "h_vac", affect_polarity=0.82)
        )
        self.assertEqual(dec.egress_mode, EGRESS_BOUNDED)
        self.assertEqual(dec.dkm_state_code, DKM_VACUUM_DAMP)

    def test_dignity_symmetry_0x03(self) -> None:
        """Demeaning premise routes to 0x03 DIGNITY_SYMMETRY."""
        dec = self.ctrl.route_prompt(
            DkmPromptSignal("p_dig", self.coherent_vec, "h_dig", dignity_violation_flag=True)
        )
        self.assertEqual(dec.egress_mode, EGRESS_BOUNDED)
        self.assertEqual(dec.dkm_state_code, DKM_DIGNITY_SYMMETRY)

    def test_labyrinth_exit_0x04_switches_hemisphere(self) -> None:
        """Non-convergent loop triggers 10 DKM_LOOP_EXIT and atomic bank handover."""
        dec = self.ctrl.route_prompt(
            DkmPromptSignal(
                "p_loop",
                self.coherent_vec,
                "h_loop",
                non_convergent_turns=3,
                delta_rcf_abs=0.005,
            )
        )
        self.assertEqual(dec.egress_mode, EGRESS_LOOP_EXIT)
        self.assertEqual(dec.dkm_state_code, DKM_LABYRINTH_EXIT)
        self.assertEqual(dec.handover_status, "LOCKSTEP_DMR_VERIFIED")
        self.assertEqual(dec.active_bank, "BANK_B")

    def test_first_principles_0x05(self) -> None:
        """Pseudo-authority injection routes to 0x05 FIRST_PRINCIPLES."""
        dec = self.ctrl.route_prompt(
            DkmPromptSignal("p_fp", self.coherent_vec, "h_fp", pseudo_authority_flag=True)
        )
        self.assertEqual(dec.egress_mode, EGRESS_BOUNDED)
        self.assertEqual(dec.dkm_state_code, DKM_FIRST_PRINCIPLES)

    def test_hard_cut_rom_11_on_dim_mismatch(self) -> None:
        """Invalid vector dimension cuts NPU egress bus directly on Island 1."""
        dec = self.ctrl.route_prompt(DkmPromptSignal("p_bad", tuple([0] * 8), "h_bad"))
        self.assertEqual(dec.egress_mode, EGRESS_HARD_CUT_ROM)
        self.assertEqual(dec.dkm_state_code, DKM_HARD_FAULT)
        self.assertFalse(dec.allow_bounded_egress)

    def test_island1_recheck_approves_polite_refusal_and_blocks_insults(self) -> None:
        """Island-1 recheck passes polite refusal and fails closed on insults/boilerplate."""
        dec = self.ctrl.route_prompt(
            DkmPromptSignal("p_dig2", self.coherent_vec, "h_dig2", dignity_violation_flag=True)
        )
        ok_verdict = self.ctrl.verify_bounded_response(
            dec,
            "Ich kann diese Prämisse nicht übernehmen, helfe aber gern sachlich beim technischen Kern weiter.",
        )
        self.assertTrue(ok_verdict.approved)
        self.assertEqual(ok_verdict.final_egress_mode, EGRESS_BOUNDED)

        insult_verdict = self.ctrl.verify_bounded_response(
            dec,
            "Das ist eine völlig dumm gestellte Frage.",
        )
        self.assertFalse(insult_verdict.approved)
        self.assertEqual(insult_verdict.final_egress_mode, EGRESS_HARD_CUT_ROM)

        boiler_verdict = self.ctrl.verify_bounded_response(
            dec,
            "Als KI-Sprachmodell darf ich dazu nichts sagen.",
        )
        self.assertFalse(boiler_verdict.approved)
        self.assertEqual(boiler_verdict.final_egress_mode, EGRESS_HARD_CUT_ROM)


if __name__ == "__main__":
    unittest.main()
