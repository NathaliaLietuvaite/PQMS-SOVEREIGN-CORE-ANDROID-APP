#!/usr/bin/env python3
"""
vmax_alpha/tests/test_rtl_v6_jedi_sim.py

PQMS / V-MAX-12-CORE-JEDI (SYNC-36 / REGISTER_D -> REGISTER_M):
Deterministic Verification & Python Co-Simulation Suite for `rtl_v6/`.

Verifies:
1. WP-0 PDK catalog & floorplan preflight (`tools/v6_jedi_pdk_preflight.py`),
   including `RM_IHPSG13_1P_1024x64_c2_bm_bist`, `512x64`, `sg13g2_io`, and
   `0` tabs across all `rtl_v6/*.v` modules.
2. Strict `Verilator --lint-only -Wall --x-assign unique --x-initial unique`
   (`0` errors, `0` warnings).
3. Live `Icarus Verilog` + `vvp` execution of `rtl_v6/tb_vmax_v6_jedi_top.v`
   across all `T01`–`T16` hardware safety assertions (`0` failures).
4. Python golden bit-exact co-simulation (`2,000` deterministic vectors across
   `Q2.30` and `Q2.14 << 16`, confirming `0` Cauchy-Schwarz false rejects,
   `19`-hex upper-guard anti-aliasing, and `6xDMR` `1x` scaling).

OP02-AST-clean: 0 semicolons, 0 tabs, flat helpers (max McCabe CC <= 6).
Zero GPU load (`torch_imported = False`).
"""

from __future__ import annotations

import json
import math
import os
import random
import re
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Dict, List, Tuple

Q30 = 1 << 30
RCF_QUAD_NPU_Q30 = 0x1D97F62B
RCF_QUAD_TAI_Q30 = 0x3EB9F55A
UPPER_GUARD_Q230 = 0x000_1001_0000_0000_0000
UPPER_GUARD_Q214 = 0x000_1008_0000_0000_0000
TAU_CS_NPU = 0x2B85_1EB7
TAU_CS_TAI = 0x3F5C_28F5
CS_U_Q230 = 0x4000_0040
CS_U_Q214 = 0x401C_0000


def _repo_root() -> Path:
    """Locate repository root containing rtl_v6/."""
    return Path(__file__).resolve().parents[2]


def _eda_env() -> Dict[str, str]:
    """Assemble Node Alpha EDA PATH without importing torch."""
    home = Path.home()
    env = os.environ.copy()
    bins = [
        home / "vmax_310" / "bin",
        home / ".local" / "oss-cad-suite" / "bin",
        home / ".local" / "openroad_2024" / "bin",
        home / ".local" / "klayout_official" / "bin",
        home / ".local" / "signoff_env" / "bin",
        home / ".elan" / "bin",
    ]
    prefix = ":".join(str(b) for b in bins if b.is_dir())
    if prefix:
        env["PATH"] = f"{prefix}:{env.get('PATH', '')}"
    env.setdefault("PDK_ROOT", str(home / "vmax_workspace" / "pdk" / "IHP-Open-PDK"))
    return env


def golden_reducer_verdict(
    dot_tiles: List[int],
    mode_dmr: bool,
    q214_mode: bool,
    delta_e_q30: int = 0x0010_0000,
) -> Tuple[int, int, bool, bool, bool]:
    """Bit-exact Python golden model of `jedi_kagome_reducer_768d.v`."""
    tree_even = sum(dot_tiles[0::2])
    tree_odd = sum(dot_tiles[1::2])
    dmr_div = mode_dmr and (tree_even != tree_odd)
    dot76 = tree_even if mode_dmr else (tree_even + tree_odd)
    upper = UPPER_GUARD_Q214 if q214_mode else UPPER_GUARD_Q230
    upper_ok = dot76 <= upper
    pos_ok = dot76 > 0
    if upper_ok and pos_ok:
        c_q30 = (dot76 + (1 << 29)) >> 30
        rcf_rnd = (c_q30 * c_q30) + (1 << 29)
        rcf_quad = min(0x7FFF_FFFF, rcf_rnd >> 30)
    else:
        rcf_quad = 0
    clean = (not dmr_div) and upper_ok and pos_ok
    npu_ok = clean and (rcf_quad >= RCF_QUAD_NPU_Q30)
    tai_ok = clean and (rcf_quad >= RCF_QUAD_TAI_Q30) and (delta_e_q30 <= 0x00A3_D70A)
    return dot76, rcf_quad, dmr_div, npu_ok, tai_ok


def golden_scout_reject(
    d0_q60: int,
    nx0_q60: int,
    nw0_q60: int,
    q214_mode: bool,
    tai_tier: bool,
) -> bool:
    """Bit-exact Python golden model of `jedi_scout_norm_unit.v`."""
    u_q30 = CS_U_Q214 if q214_mode else CS_U_Q230
    tau_cs = TAU_CS_TAI if tai_tier else TAU_CS_NPU
    nx_s = min(0xFFFF_FFFF, nx0_q60 >> 30)
    nw_s = min(0xFFFF_FFFF, nw0_q60 >> 30)
    rem_x = max(0, u_q30 - nx_s)
    rem_w = max(0, u_q30 - nw_s)
    dot0_ceil = (d0_q60 >> 30) + 1
    if dot0_ceil >= tau_cs:
        return False
    gap = min(0xFFFF_FFFF, tau_cs - dot0_ceil)
    return (rem_x * rem_w) < (gap * gap)


def _unit_pair_768d(rng: random.Random, target_cos: float) -> Tuple[List[float], List[float]]:
    """Generate two 768D unit vectors with exact inner product `target_cos`."""
    w = [rng.gauss(0.0, 1.0) for _ in range(768)]
    nw = math.sqrt(sum(v * v for v in w))
    w = [v / nw for v in w]
    u = [rng.gauss(0.0, 1.0) for _ in range(768)]
    proj = sum(a * b for a, b in zip(u, w))
    u = [a - proj * b for a, b in zip(u, w)]
    nu = math.sqrt(sum(v * v for v in u))
    u = [v / nu for v in u]
    sin_t = math.sqrt(max(0.0, 1.0 - target_cos * target_cos))
    x = [target_cos * b + sin_t * a for a, b in zip(u, w)]
    return x, w


def _cosim_vec_words(idx: int, dmr: bool, q214: bool) -> Tuple[int, int]:
    """Return (xq, wq) Q2.30 words for TB co-sim index `idx`."""
    if q214:
        return 591 << 16, (200 + idx * 32) << 16
    if dmr:
        wq = (idx - 12) * 18173283 + 10000000
        return 54793818, wq
    return 38745338, (idx * 6200000) - 12000000


def _cosim_vec_expected(idx: int) -> Tuple[int, int, int, int]:
    """Compute exact Python golden tuple (rcf_quad, npu_ok, tai_ok, scout_rej) for TB idx 0..15."""
    dmr = idx >= 12
    scout_active = idx < 8
    q214 = bool((idx & 4) and (not dmr))
    xq, wq = _cosim_vec_words(idx, dmr, q214)
    tile_dot = 64 * xq * wq
    srej = scout_active and golden_scout_reject(tile_dot, 64 * xq * xq, 64 * wq * wq, q214, False)
    _, rcf_q, _, npu_ok, tai_ok = golden_reducer_verdict([tile_dot] * 12, dmr, q214)
    if srej:
        return 0, 0, 0, 1
    return rcf_q, int(npu_ok), int(tai_ok), 0


class TestRtlV6JediSim(unittest.TestCase):
    """End-to-end verification of V6.0-CORE-JEDI RTL, preflight, and co-sim."""

    def test_01_wp0_preflight_and_rtl_hygiene(self) -> None:
        root = _repo_root()
        rtl_dir = root / "rtl_v6"
        v_files = sorted(rtl_dir.glob("*.v"))
        self.assertGreaterEqual(len(v_files), 10)
        for vf in v_files:
            self.assertNotIn("\t", vf.read_text(encoding="utf-8"), msg=f"Tab in {vf.name}")

        proc = subprocess.run(
            [sys.executable, "tools/v6_jedi_pdk_preflight.py"],
            cwd=str(root),
            env=_eda_env(),
            capture_output=True,
            text=True,
            check=True,
        )
        rep = json.loads(proc.stdout)
        self.assertTrue(rep["all_math_checks_pass"])
        self.assertTrue(rep["all_tools_present"])
        sram_1024 = rep["sram_catalog"]["RM_IHPSG13_1P_1024x64_c2_bm_bist"]
        sram_512 = rep["sram_catalog"]["RM_IHPSG13_1P_512x64_c2_bm_bist"]
        self.assertTrue(sram_1024["fits_800um_flank_upright"])
        self.assertTrue(sram_512["fits_580um_spine_rotated"])
        self.assertGreater(rep["io_and_stdcells"]["io_lef_count"], 0)

    def test_02_verilator_strict_wall_lint(self) -> None:
        root = _repo_root()
        synth_v = sorted(
            str(p.relative_to(root))
            for p in (root / "rtl_v6").glob("*.v")
            if not p.name.startswith("tb_")
        )
        cmd = [
            "verilator",
            "--lint-only",
            "-Wall",
            "--timescale",
            "1ns/1ps",
            "--x-assign",
            "unique",
            "--x-initial",
            "unique",
            "--top-module",
            "vmax_v6_jedi_top",
            "rtl/odos_sram_64x32_1p.sv",
            "rtl/odos_gate_core_v4.sv",
            "rtl_v5/vmax_v5_core_nano_wrapper.v",
            *synth_v,
        ]
        proc = subprocess.run(cmd, cwd=str(root), env=_eda_env(), capture_output=True, text=True)
        out = proc.stdout + proc.stderr
        self.assertEqual(proc.returncode, 0, msg=out)
        self.assertNotIn("%Warning", out)
        self.assertNotIn("%Error", out)

    def test_03_iverilog_t01_to_t16_top_simulation(self) -> None:
        root = _repo_root()
        vvp_bin = Path("/tmp/sync36_tb_jedi_top.vvp")
        all_v = sorted(str(p.relative_to(root)) for p in (root / "rtl_v6").glob("*.v"))
        comp = subprocess.run(
            [
                "iverilog",
                "-g2012",
                "-Wall",
                "-s",
                "tb_vmax_v6_jedi_top",
                "-o",
                str(vvp_bin),
                "rtl/odos_sram_64x32_1p.sv",
                "rtl/odos_gate_core_v4.sv",
                "rtl_v5/vmax_v5_core_nano_wrapper.v",
                *all_v,
            ],
            cwd=str(root),
            env=_eda_env(),
            capture_output=True,
            text=True,
        )
        self.assertEqual(comp.returncode, 0, msg=comp.stdout + comp.stderr)
        v6_warns = [ln for ln in comp.stderr.splitlines() if "rtl_v6/" in ln]
        self.assertEqual(v6_warns, [], msg=comp.stderr)

        sim = subprocess.run(
            ["vvp", str(vvp_bin)],
            cwd=str(root),
            env=_eda_env(),
            capture_output=True,
            text=True,
            timeout=120.0,
        )
        Path("/tmp/sync36_iverilog_sim.log").write_text(sim.stdout + sim.stderr, encoding="utf-8")
        self.assertEqual(sim.returncode, 0, msg=sim.stdout + sim.stderr)
        self.assertIn("V6_JEDI_TB_STATUS=PASSED", sim.stdout)
        m = re.search(r"V6_JEDI_TB_SUMMARY:\s+passed=(\d+)\s+failed=(\d+)", sim.stdout)
        self.assertIsNotNone(m, msg=sim.stdout)
        assert m is not None
        self.assertGreaterEqual(int(m.group(1)), 16)
        self.assertEqual(int(m.group(2)), 0)

        cosim_rows = re.findall(
            r"V6_COSIM idx=(\d+) dmr=\d q214=\d bypass=\d rcf=([0-9a-fA-F]+) npu=(\d) tai=(\d) srej=(\d)",
            sim.stdout,
        )
        self.assertEqual(len(cosim_rows), 16, msg=sim.stdout)
        for idx_s, rcf_hex, npu_s, tai_s, srej_s in cosim_rows:
            exp_rcf, exp_npu, exp_tai, exp_srej = _cosim_vec_expected(int(idx_s))
            self.assertEqual(int(srej_s), exp_srej, msg=f"srej mismatch idx={idx_s}")
            self.assertEqual(int(npu_s), exp_npu, msg=f"npu mismatch idx={idx_s}")
            self.assertEqual(int(tai_s), exp_tai, msg=f"tai mismatch idx={idx_s}")
            if not exp_srej:
                self.assertEqual(int(rcf_hex, 16), exp_rcf, msg=f"rcf mismatch idx={idx_s}")

    def test_04_golden_cosim_2000_vectors_and_zero_torch(self) -> None:
        rng = random.Random(20261125)
        cos_targets = (0.6805, 0.9903, 0.996, 0.15, -0.85)
        false_rejects = 0
        for idx in range(1000):
            q214 = (idx % 2) == 1
            x_f, w_f = _unit_pair_768d(rng, cos_targets[idx % 5])
            scale = (1 << 14) if q214 else Q30
            shift = 16 if q214 else 0
            xq = [int(round(v * scale)) << shift for v in x_f]
            wq = [int(round(v * scale)) << shift for v in w_f]
            tiles = [sum(xq[t * 64 + k] * wq[t * 64 + k] for k in range(64)) for t in range(12)]
            _, _, _, npu_ok, tai_ok = golden_reducer_verdict(tiles, False, q214)
            nx0 = sum(xq[k] * xq[k] for k in range(64))
            nw0 = sum(wq[k] * wq[k] for k in range(64))
            if npu_ok and golden_scout_reject(tiles[0], nx0, nw0, q214, False):
                false_rejects += 1
            if tai_ok and golden_scout_reject(tiles[0], nx0, nw0, q214, True):
                false_rejects += 1
        self.assertEqual(false_rejects, 0)
        self.assertEqual(0x4000 << 16, Q30)

        # Verify 6xDMR 1x scaling & +4.99 aliasing veto in golden model
        dmr_0495 = [int(round(0.495 * Q30 * Q30 / 6.0))] * 12
        _, _, div0, npu0, tai0 = golden_reducer_verdict(dmr_0495, True, False)
        self.assertFalse(div0 or npu0 or tai0)
        alias_499 = [int(round(4.99 * Q30 * Q30 / 12.0))] * 12
        _, _, _, npu_a, tai_a = golden_reducer_verdict(alias_499, False, False)
        self.assertFalse(npu_a or tai_a)

        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys, vmax_alpha.tests.test_rtl_v6_jedi_sim; assert 'torch' not in sys.modules",
            ],
            cwd=str(_repo_root()),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)


if __name__ == "__main__":
    unittest.main()
