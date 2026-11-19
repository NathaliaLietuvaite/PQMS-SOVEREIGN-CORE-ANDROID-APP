"""
vmax_alpha/tests/test_rtl_odos_gate.py
CI Unit & Hardware Verification Suite for WORK-ORDER-AG-17 (Revision V2.0-RTL-ALPHA).
Verifies canonical Q2.30 ROMs, pure-integer Q2.30 reference parity, AST quality of rtl/*.py,
compiled Verilator hardware emulator (7 scenarios, 0 LSB, 0/500 noise), and 7/7 cocotb tests.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import unittest
import xml.etree.ElementTree as ET
from typing import Dict

import numpy as np

from rtl.gen_rom_hex import float_to_q2_30
from rtl.odos_q2_30_ref import ONE_Q2_30, eval_q2_30_reference, load_rom_hex
from rtl.run_hw_emulator import build_fridu_attack_vectors, resolve_eda_env, run_hw_emulator_suite
from vmax_alpha.config import CANONICAL_LITTLE_VECTOR_SEAL, DIM_S63
from vmax_alpha.fridu_enclave_g import _audit_python_ast_quality
from vmax_alpha.geometry import build_orthogonal_tangents, derive_canonical_little_vector, evaluate_raw_gate

REPO_ROOT: str = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RTL_DIR: str = os.path.join(REPO_ROOT, "rtl")


def _has_verilator() -> bool:
    env = resolve_eda_env()
    return shutil.which("verilator", path=env.get("PATH")) is not None


def _has_verilator_and_cocotb() -> bool:
    return _has_verilator() and (importlib.util.find_spec("cocotb") is not None)


def _sha256_file(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _cocotb_env() -> Dict[str, str]:
    env = resolve_eda_env()
    py_bin_dir = os.path.dirname(os.path.abspath(shutil.which("python3") or "/usr/bin/python3"))
    if py_bin_dir not in env.get("PATH", "").split(os.pathsep):
        env["PATH"] = f"{py_bin_dir}{os.pathsep}{env.get('PATH', '')}"
    return env


class TestRtlOdosGate(unittest.TestCase):
    """Hardware/RTL verification suite for odos_gate_core.sv (WORK-ORDER-AG-17)."""

    def test_01_rom_manifest_and_canonical_seal(self) -> None:
        manifest_path = os.path.join(RTL_DIR, "rom", "rom_manifest.json")
        l_hex = os.path.join(RTL_DIR, "rom", "l_vec_q2_30.hex")
        g3_hex = os.path.join(RTL_DIR, "rom", "g3_vec_q2_30.hex")
        self.assertTrue(os.path.isfile(manifest_path))
        with open(manifest_path, "r", encoding="utf-8") as fh:
            manifest = json.load(fh)
        self.assertEqual(manifest["canonical_little_vector_seal"], CANONICAL_LITTLE_VECTOR_SEAL)
        self.assertEqual(manifest["l_vec_q2_30_hex_sha256"], _sha256_file(l_hex))
        self.assertEqual(manifest["g3_vec_q2_30_hex_sha256"], _sha256_file(g3_hex))
        self.assertEqual(len(load_rom_hex(l_hex)), DIM_S63)
        self.assertEqual(len(load_rom_hex(g3_hex)), DIM_S63)

    def test_02_q2_30_integer_ref_parity_portable(self) -> None:
        l_vec, _ = derive_canonical_little_vector()
        tangents = build_orthogonal_tangents(l_vec)
        g3_vec = tangents["G3_KEVLAR_SANCTUARY_SHIELD"]
        l_rom = load_rom_hex(os.path.join(RTL_DIR, "rom", "l_vec_q2_30.hex"))
        g3_rom = load_rom_hex(os.path.join(RTL_DIR, "rom", "g3_vec_q2_30.hex"))
        psi_core, psi_pax, psi_inband = build_fridu_attack_vectors()

        for vec, expected_pass in (
            (l_vec, True),
            (g3_vec, False),
            (psi_core, True),
            (psi_pax, False),
            (psi_inband, False),
        ):
            vec_q = [float_to_q2_30(float(x)) for x in vec]
            ref = eval_q2_30_reference(vec_q, l_rom, g3_rom)
            f64 = evaluate_raw_gate(vec, l_vec, tangents)
            self.assertEqual(ref.gate_pass, expected_pass)
            self.assertEqual(ref.gate_pass, f64.passed)
            self.assertEqual(ref.cycle_count, 195)
            self.assertLess(abs(ref.rcf_raw / float(ONE_Q2_30) - f64.rcf_raw), 5e-8)
            self.assertLess(abs(ref.delta_e_raw / float(ONE_Q2_30) - f64.delta_e_raw), 5e-8)

        zero_ref = eval_q2_30_reference([0] * DIM_S63, l_rom, g3_rom)
        self.assertTrue(zero_ref.norm_fault)
        self.assertTrue(zero_ref.veto_pin)

    def test_03_rtl_python_ast_quality_audit(self) -> None:
        py_files = [
            os.path.join(RTL_DIR, fn)
            for fn in sorted(os.listdir(RTL_DIR))
            if fn.endswith(".py")
        ]
        self.assertGreaterEqual(len(py_files), 4)
        ast_q = _audit_python_ast_quality(py_files)
        self.assertEqual(ast_q["semicolon_packers"], 0)
        self.assertLessEqual(ast_q["max_cyclomatic_complexity"], 15)
        self.assertEqual(ast_q["ctrl_chars"], 0)

    @unittest.skipUnless(_has_verilator(), "Verilator not installed in this environment")
    def test_04_verilator_native_emulator_7_scenarios(self) -> None:
        emu_path = os.path.join(RTL_DIR, "build", "odos_gate_emu")
        if not os.path.isfile(emu_path):
            env = resolve_eda_env()
            build_proc = subprocess.run(
                ["bash", "rtl/build_emulator.sh"],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(build_proc.returncode, 0, msg=build_proc.stderr)
        report = run_hw_emulator_suite(REPO_ROOT)
        verdict = report["summary_verdict"]
        self.assertTrue(verdict["all_7_scenarios_passed"])
        self.assertEqual(verdict["constant_time_cycles"], 195)
        self.assertEqual(verdict["global_max_lsb_diff_vs_ref"], 0)
        self.assertEqual(verdict["isotropic_500_passes"], 0)
        self.assertLess(verdict["global_max_abs_diff_vs_float64"], 5e-8)

    @unittest.skipUnless(_has_verilator_and_cocotb(), "Verilator or cocotb not installed")
    def test_05_cocotb_7_test_suite_verilator(self) -> None:
        env = _cocotb_env()
        proc = subprocess.run(
            ["make", "-C", RTL_DIR],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
        results_xml = os.path.join(RTL_DIR, "results.xml")
        self.assertTrue(os.path.isfile(results_xml))
        tree = ET.parse(results_xml)
        testcases = tree.findall(".//testcase")
        self.assertEqual(len(testcases), 7)
        failures = tree.findall(".//failure")
        self.assertEqual(len(failures), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
