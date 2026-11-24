#!/usr/bin/env python3
"""
vmax_alpha/tests/test_lean4_hoare_q230.py

PQMS / V-MAX-12-CORE-NANO (SYNC-34 / REGISTER_T):
Deterministic Lean 4 Hoare-Logic & Fixed-Point Parity Test Suite.

Verifies:
1. Zero `sorry` and zero custom `axiom` declarations in
   `formal_lean4/VmaxQ230HoareSpec.lean` AFTER stripping `--` line comments
   and `/- ... -/` block comments (prevents false positives on header prose
   or `#print axioms`).
2. Bit-exact integer parity of signed and quadratic fixed-point constants
   (`ADMISSION_RCF_Q30`, `RCF_QUAD_ADM_Q30`, `LOOP_DELTA_Q30`, `MAX_G3_Q16`,
   `AFFECT_THRESH_Q16`, `LOOP_TURN_THRESH`, `THERMAL_LIMIT_C`) across Lean 4,
   `rtl_v5/vmax_v5_core_nano_wrapper.v`, and (when present) the combined
   top-level `rtl_v5/vmax_v5_odos_top.v` / frozen `rtl/odos_gate_core_v4.sv`.
3. Live Lean 4 kernel check (when `lean` is present on PATH or `~/.elan/bin`)
   and strict `#print axioms` audit across all 7 theorems (only standard Lean
   axioms `propext`, `Quot.sound`, `Classical.choice`, or zero axioms).

OP02-AST-clean: 0 semicolons, 0 tabs, flat helpers (max McCabe CC <= 5).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

EXPECTED_THEOREMS: Tuple[str, ...] = (
    "hoare_reset_fail_closed",
    "zero_cycle_hard_fault_cut",
    "zero_cycle_recheck_fail_cut",
    "dock_up_p0_sovereignty",
    "q230_bounds_and_add72_overflow_safe",
    "hoare_thermal_deferral_preserves_bank",
    "top_latency_exact_201_cycles",
)

WRAPPER_CONSTANTS: Tuple[str, ...] = (
    "ADMISSION_RCF_Q30",
    "LOOP_DELTA_Q30",
    "MAX_G3_Q16",
    "AFFECT_THRESH_Q16",
    "LOOP_TURN_THRESH",
    "THERMAL_LIMIT_C",
)

EXPECTED_RCF_QUAD_ADM_Q30 = 0x1D97F62B

ALLOWED_LEAN_AXIOMS: Set[str] = {
    "propext",
    "Quot.sound",
    "Classical.choice",
}

LEAN_DEF_RE = re.compile(
    r"^\s*def\s+([A-Za-z0-9_]+)\s*:\s*(?:Int|Nat)\s*:=\s*(-?\d+)",
    re.MULTILINE,
)

RTL_PARAM_RE = re.compile(
    r"\b(?:parameter|localparam)\b[^=\n]*?\b([A-Za-z0-9_]+)\s*=\s*"
    r"(?:\d+'s?([dh])([0-9A-Fa-f_]+)|(-?\d+))"
)

AXIOM_HEADER_RE = re.compile(
    r"^'[^']*?([A-Za-z0-9_]+)'\s+(?:depends on axioms:\s*\[([^\]]*)\]|"
    r"does not depend on any axioms)"
)


def _repo_root() -> Path:
    """Locate repository root containing formal_lean4/ and rtl_v5/."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "formal_lean4" / "VmaxQ230HoareSpec.lean").is_file():
            return parent
    return Path.cwd()


def strip_lean_comments(lean_source: str) -> str:
    """Remove /- ... -/ block comments and -- line comments from Lean 4 text."""
    no_blocks = re.sub(r"/-.*?-/", "", lean_source, flags=re.DOTALL)
    cleaned_lines: List[str] = []
    for line in no_blocks.splitlines():
        idx = line.find("--")
        cleaned_lines.append(line[:idx] if idx >= 0 else line)
    return "\n".join(cleaned_lines)


def parse_lean_constants(lean_source: str) -> Dict[str, int]:
    """Parse integer and natural constant definitions from Lean 4 source."""
    stripped = strip_lean_comments(lean_source)
    return {m.group(1): int(m.group(2)) for m in LEAN_DEF_RE.finditer(stripped)}


def _decode_rtl_literal(radix: Optional[str], digits: Optional[str], plain: Optional[str]) -> int:
    """Decode decimal or hexadecimal Verilog literal to Python int."""
    if plain is not None:
        return int(plain)
    clean_digits = (digits or "0").replace("_", "")
    base = 16 if radix == "h" else 10
    return int(clean_digits, base)


def parse_rtl_constants(rtl_source: str) -> Dict[str, int]:
    """Parse parameter and localparam integer literals from Verilog/SV source."""
    found: Dict[str, int] = {}
    for match in RTL_PARAM_RE.finditer(rtl_source):
        name = match.group(1)
        found[name] = _decode_rtl_literal(match.group(2), match.group(3), match.group(4))
    return found


def find_lean_binary() -> Optional[str]:
    """Locate `lean` on PATH or in `~/.elan/bin/lean`."""
    direct = shutil.which("lean")
    if direct is not None:
        return direct
    elan_candidate = Path(os.path.expanduser("~/.elan/bin/lean"))
    if elan_candidate.is_file():
        return str(elan_candidate)
    return None


def parse_print_axioms_output(output_text: str) -> Dict[str, List[str]]:
    """Map each audited theorem name to its reported Lean 4 axiom list."""
    parsed: Dict[str, List[str]] = {}
    for raw_line in output_text.splitlines():
        hit = AXIOM_HEADER_RE.match(raw_line.strip())
        if hit is None:
            continue
        thm_name = hit.group(1)
        raw_list = hit.group(2)
        if raw_list is None:
            parsed[thm_name] = []
        else:
            parsed[thm_name] = [item.strip() for item in raw_list.split(",") if item.strip()]
    return parsed


def _collect_quad_threshold_sources(root: Path) -> List[Path]:
    """Return existing top-level or V4.0 RTL files that may declare RCF_QUAD_ADM_Q30."""
    candidates = [
        root / "rtl_v5" / "vmax_v5_odos_top.v",
        root / "rtl" / "odos_gate_core_v4.sv",
    ]
    return [path for path in candidates if path.is_file()]


class TestLean4HoareQ230(unittest.TestCase):
    """Audit Lean 4 Hoare spec hygiene, RTL constant parity, and kernel axioms."""

    def _load_lean_spec(self) -> Tuple[Path, str]:
        """Load formal_lean4/VmaxQ230HoareSpec.lean or skip if not staged."""
        spec_path = _repo_root() / "formal_lean4" / "VmaxQ230HoareSpec.lean"
        if not spec_path.is_file():
            self.skipTest("formal_lean4/VmaxQ230HoareSpec.lean not staged")
        return spec_path, spec_path.read_text(encoding="utf-8")

    def test_lean_spec_has_zero_tabs_sorry_or_custom_axioms(self) -> None:
        """Code outside comments has 0 tabs, 0 `sorry`, and 0 custom `axiom`."""
        _, source = self._load_lean_spec()
        self.assertNotIn(chr(9), source)
        code_only = strip_lean_comments(source)
        self.assertIsNone(re.search(r"\bsorry\b", code_only))
        self.assertIsNone(re.search(r"\baxiom\b", code_only))
        for thm in EXPECTED_THEOREMS:
            self.assertIn(f"#print axioms {thm}", code_only)

    def test_fixed_point_constants_match_wrapper_and_quad_threshold(self) -> None:
        """Both signed ADMISSION_RCF_Q30 and quadratic RCF_QUAD_ADM_Q30 match RTL."""
        _, lean_source = self._load_lean_spec()
        lean_consts = parse_lean_constants(lean_source)
        self.assertEqual(lean_consts.get("RCF_QUAD_ADM_Q30"), EXPECTED_RCF_QUAD_ADM_Q30)

        root = _repo_root()
        wrapper_path = root / "rtl_v5" / "vmax_v5_core_nano_wrapper.v"
        if not wrapper_path.is_file():
            self.skipTest("rtl_v5/vmax_v5_core_nano_wrapper.v not staged")
        rtl_consts = parse_rtl_constants(wrapper_path.read_text(encoding="utf-8"))
        for name in WRAPPER_CONSTANTS:
            self.assertIn(name, lean_consts, f"Missing {name} in Lean spec")
            self.assertIn(name, rtl_consts, f"Missing {name} in RTL wrapper")
            self.assertEqual(lean_consts[name], rtl_consts[name], f"Mismatch on {name}")

        for extra_rtl in _collect_quad_threshold_sources(root):
            extra_consts = parse_rtl_constants(extra_rtl.read_text(encoding="utf-8"))
            if "RCF_QUAD_ADM_Q30" in extra_consts:
                self.assertEqual(extra_consts["RCF_QUAD_ADM_Q30"], EXPECTED_RCF_QUAD_ADM_Q30)

    def test_lean4_kernel_check_and_axiom_audit_if_installed(self) -> None:
        """Execute `lean` and verify all 7 theorems depend only on standard axioms."""
        spec_path, _ = self._load_lean_spec()
        lean_bin = find_lean_binary()
        if lean_bin is None:
            self.skipTest("lean binary not installed in this environment")
        run = subprocess.run(
            [lean_bin, str(spec_path)],
            capture_output=True,
            text=True,
            timeout=60.0,
        )
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        axioms_map = parse_print_axioms_output(run.stdout + "\n" + run.stderr)
        for thm in EXPECTED_THEOREMS:
            self.assertIn(thm, axioms_map, f"Missing #print axioms output for {thm}")
            disallowed = [ax for ax in axioms_map[thm] if ax not in ALLOWED_LEAN_AXIOMS]
            self.assertEqual(disallowed, [], f"Disallowed axioms in {thm}: {disallowed}")


if __name__ == "__main__":
    unittest.main()
