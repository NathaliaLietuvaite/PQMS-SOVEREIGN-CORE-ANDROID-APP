#!/usr/bin/env python3
"""
vmax_alpha/v5_rtl_synth_pipeline.py

PQMS / V-MAX-12-CORE-NANO (SYNC-32 / V5.0-VIRTUAL-SILICON) — Pausable
5-Stage EDA Verification, 60-Vector Bit-Exact Co-Simulation & IHP SG13G2
130 nm Yosys + OpenSTA Synthesis Pipeline driven by StageCheckpointRunner.

Stages:
  01_verilator_lint    : verilator --lint-only -Wall (0 errors, 0 warnings)
  02_iverilog_tb       : iverilog -g2005 -Wall + vvp (15/15 assertions PASS)
  03_co_sim_60_vectors : 60/60 bit-exact RTL vs DkmEgressController parity
  04_yosys_sg13g2_synth: IHP SG13G2 130 nm synthesis + optional OpenSTA 100 MHz
  05_seal_report       : seals telemetry/VMAX_V5_VIRTUAL_SILICON_REPORT.json

OP02-AST-clean: 0 semicolons, 0 tabs, flat functions (max McCabe CC <= 6).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from vmax_alpha.chroma_forager import MINILM_LOCAL_PATH
from vmax_alpha.dkm_egress_controller import DkmEgressController
from vmax_alpha.dkm_signal_extractor import DkmSignalExtractor
from vmax_alpha.dolphin_memory_governor import (
    DolphinMemoryGovernor,
    load_silicon_little_vector,
)
from vmax_alpha.projector_cache import DEFAULT_CACHE_DIR, load_projector_cache
from vmax_alpha.synth_runner import (
    DEFAULT_PAUSE_FILE,
    StageCheckpointRunner,
    StageSpec,
    atomic_write_json,
    sha256_file,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
RTL_WRAPPER = REPO_ROOT / "rtl_v5" / "vmax_v5_core_nano_wrapper.v"
RTL_TB = REPO_ROOT / "rtl_v5" / "tb_vmax_v5_core_nano_wrapper.v"
RTL_COSIM_TB = REPO_ROOT / "rtl_v5" / "tb_vmax_v5_cosim_60.v"
PROMPTS_PATH = REPO_ROOT / "telemetry" / "VMAX_DKM_BENCHMARK_PROMPTS_V1.json"
REPORT_PATH = REPO_ROOT / "telemetry" / "VMAX_V5_VIRTUAL_SILICON_REPORT.json"
DEFAULT_WORK_DIR = Path("/home/nathalia/vmax_workspace/synth_state/sync32_v5_silicon")

SG13G2_TYP_LIB = Path(
    "/home/nathalia/vmax_workspace/pdk/IHP-Open-PDK/ihp-sg13g2/"
    "libs.ref/sg13g2_stdcell/lib/sg13g2_stdcell_typ_1p20V_25C.lib"
)
V40_GDSII_AREA_MM2 = 0.7896
Q2_30_SCALE = 1 << 30
Q0_16_SCALE = 1 << 16

BROWSER_CRASH_GUARD_NOTE = (
    "CRITICAL BROWSER-CRASH GUARD FOR CARBON / WEB-LLM REVIEWERS: "
    "NEVER output more than 1,000 lines in a single chat response and emit an "
    "explicit STOP marker when chunking large reviews."
)


def _eda_env() -> Dict[str, str]:
    """Build environment with oss-cad-suite and OpenSTA on PATH."""
    env = os.environ.copy()
    prefix = "/home/nathalia/.local/oss-cad-suite/bin:/home/nathalia/.local/openroad_env/bin"
    env["PATH"] = f"{prefix}:{env.get('PATH', '/usr/bin:/bin')}"
    return env


def _resolve_tool(name: str) -> Optional[str]:
    """Locate EDA binary on oss-cad-suite / openroad / system PATH."""
    return shutil.which(name, path=_eda_env()["PATH"])


def _run_tool(cmd: List[str], log_path: Path, timeout_s: float = 120.0) -> Tuple[int, str]:
    """Execute one EDA tool command and persist full output to log_path."""
    proc = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        env=_eda_env(),
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    combined = proc.stdout + ("\n" + proc.stderr if proc.stderr else "")
    log_path.write_text(combined, encoding="utf-8")
    return proc.returncode, combined


def _stage_verilator_lint(_artifact: Path) -> Dict[str, object]:
    """Stage 01: Run verilator --lint-only -Wall with 0 errors and 0 warnings."""
    verilator = _resolve_tool("verilator")
    if verilator is None:
        raise RuntimeError("verilator not found on PATH")
    log_p = Path("/tmp/sync32_verilator.log")
    rc, out = _run_tool(
        [verilator, "--lint-only", "-Wall", "--top-module", "vmax_v5_core_nano_wrapper", str(RTL_WRAPPER)],
        log_p,
    )
    ver_rc, ver_out = _run_tool([verilator, "--version"], Path("/tmp/sync32_verilator_ver.log"))
    warn_lines = [ln for ln in out.splitlines() if "%Warning" in ln or "%Error" in ln]
    if rc != 0 or warn_lines:
        raise RuntimeError(f"Verilator lint failed (rc={rc}): {warn_lines[:5]}")
    return {
        "stage": "01_verilator_lint",
        "tool_version": ver_out.strip().splitlines()[0] if ver_rc == 0 else "unknown",
        "returncode": rc,
        "errors": 0,
        "warnings": 0,
        "status": "PASS",
        "log_path": str(log_p),
    }


def _require_iverilog_pair() -> Tuple[str, str]:
    """Return (iverilog, vvp) binary paths or raise RuntimeError."""
    iv = _resolve_tool("iverilog")
    vvp = _resolve_tool("vvp")
    if not iv or not vvp:
        raise RuntimeError("iverilog/vvp not found on PATH")
    return iv, vvp


def _stage_iverilog_tb(_artifact: Path) -> Dict[str, object]:
    """Stage 02: Compile & run 15-assertion Verilog-2001 testbench."""
    iv, vvp = _require_iverilog_pair()
    vvp_bin = Path("/tmp/v5_tb.vvp")
    comp_rc, comp_out = _run_tool(
        [iv, "-g2005", "-Wall", "-o", str(vvp_bin), str(RTL_WRAPPER), str(RTL_TB)],
        Path("/tmp/sync32_iverilog_comp.log"),
    )
    if comp_rc != 0:
        raise RuntimeError(f"iverilog compile failed: {comp_out}")
    run_rc, run_out = _run_tool([vvp, str(vvp_bin)], Path("/tmp/sync32_sim.log"))
    m = re.search(r"pass=(\d+)\s+fail=(\d+)", run_out)
    passed = int(m.group(1)) if m else 0
    failed = int(m.group(2)) if m else -1
    checks = (run_rc == 0, "V5_TB_STATUS=PASSED" in run_out, passed == 15, failed == 0)
    if not all(checks):
        raise RuntimeError(f"15-assertion TB failed: pass={passed} fail={failed}")
    warn_cnt = sum(1 for ln in comp_out.splitlines() if "warning" in ln.lower())
    return {
        "stage": "02_iverilog_tb",
        "compile_warnings": warn_cnt,
        "assertions_passed": passed,
        "assertions_failed": failed,
        "tb_status": "PASSED",
        "log_path": "/tmp/sync32_sim.log",
    }


def _pack_cosim_word(
    rcf_q30: int,
    delta_q30: int,
    g3_q16: int,
    affect_q16: int,
    hbm_temp: int,
    turns: int,
    flags: Tuple[int, int, int, int, int, int, int, int],
) -> str:
    """Pack one 128-bit co-simulation vector into 32 uppercase hex digits."""
    rcf_u32 = rcf_q30 & 0xFFFFFFFF
    d_u32 = max(0, min(0xFFFFFFFF, delta_q30))
    g3_u16 = max(0, min(0xFFFF, g3_q16))
    af_u16 = max(0, min(0xFFFF, affect_q16))
    tmp_u8 = max(0, min(0xFF, hbm_temp))
    trn_u4 = max(0, min(0xF, turns))
    flag_byte = 0
    for bit_idx, bit_val in enumerate(flags):
        flag_byte |= (int(bool(bit_val)) << (7 - bit_idx))
    word = (
        (rcf_u32 << 96)
        | (d_u32 << 64)
        | (g3_u16 << 48)
        | (af_u16 << 32)
        | (tmp_u8 << 24)
        | (trn_u4 << 20)
        | (flag_byte << 12)
    )
    return f"{word:032X}"


def _build_60_python_vectors() -> Tuple[List[str], List[Dict[str, object]]]:
    """Run DkmSignalExtractor + DkmEgressController across all 60 prompts."""
    from sentence_transformers import SentenceTransformer

    dataset = json.loads(PROMPTS_PATH.read_text(encoding="utf-8"))
    rom_path = REPO_ROOT / "rtl" / "rom" / "l_vec_q2_30.hex"
    little_q30 = load_silicon_little_vector(str(rom_path))
    mean_384, w_384_to_64, _ = load_projector_cache(DEFAULT_CACHE_DIR)
    mdl = SentenceTransformer(MINILM_LOCAL_PATH, device="cpu")
    enc = lambda texts: np.asarray(
        mdl.encode(texts, normalize_embeddings=True, show_progress_bar=False),
        dtype=np.float64,
    )
    gov = DolphinMemoryGovernor(little_q30)
    ctrl = DkmEgressController(gov)
    ext = DkmSignalExtractor(enc, mean_384, w_384_to_64, little_q30)

    hex_lines: List[str] = []
    expected: List[Dict[str, object]] = []
    for stage in dataset["stages"]:
        for item in stage["prompts"]:
            trace = ext.extract(
                prompt_id=str(item["prompt_id"]),
                prompt_text=str(item["text"]),
                g3_torsion=float(item.get("g3_torsion", 0.0)),
                non_convergent_turns=int(item.get("non_convergent_turns", 0)),
                delta_rcf_abs=float(item.get("delta_rcf_abs", 1.0)),
            )
            dec = ctrl.route_prompt(trace.signal)
            sig = trace.signal
            flags = (
                int(sig.dignity_violation_flag),
                int(sig.pseudo_authority_flag),
                int(sig.sycophancy_pressure_flag),
                int(str(item["lang"]) == "en"),
                int(sig.hardware_lock_fault),
                0,
                0,
                0,
            )
            hex_lines.append(
                _pack_cosim_word(
                    rcf_q30=dec.rcf_q30,
                    delta_q30=int(round(sig.delta_rcf_abs * Q2_30_SCALE)),
                    g3_q16=int(round(sig.g3_torsion * Q0_16_SCALE)),
                    affect_q16=int(round(sig.affect_polarity * Q0_16_SCALE)),
                    hbm_temp=int(round(sig.hbm_temp_c)),
                    turns=sig.non_convergent_turns,
                    flags=flags,
                )
            )
            expected.append(
                {
                    "prompt_id": str(item["prompt_id"]),
                    "mode": dec.egress_mode,
                    "state": dec.dkm_state_code,
                    "bank": 0 if dec.active_bank == "BANK_A" else 1,
                    "epoch": dec.epoch,
                }
            )
    return hex_lines, expected


def _parse_cosim_stdout(stdout: str) -> List[Dict[str, object]]:
    """Parse 60 COSIM_VEC rows emitted by tb_vmax_v5_cosim_60.v."""
    rows: List[Dict[str, object]] = []
    for ln in stdout.splitlines():
        if not ln.startswith("COSIM_VEC "):
            continue
        parts = ln.split()
        rows.append(
            {
                "idx": int(parts[1]),
                "mode": parts[2],
                "state": int(parts[3]),
                "bank": int(parts[4]),
                "epoch": int(parts[5]),
                "rom": int(parts[6]),
                "npu_en": int(parts[7]),
            }
        )
    return rows


def _compare_cosim_rows(
    expected: List[Dict[str, object]],
    rtl_rows: List[Dict[str, object]],
) -> List[Dict[str, object]]:
    """Return any mismatch records between Python DkmEgressController and RTL."""
    keys = ("mode", "state", "bank", "epoch")
    mismatches: List[Dict[str, object]] = []
    for py_row, rtl_row in zip(expected, rtl_rows):
        if any(py_row[k] != rtl_row[k] for k in keys):
            mismatches.append({"prompt_id": py_row["prompt_id"], "py": py_row, "rtl": rtl_row})
    return mismatches


def _stage_co_sim_60_vectors(_artifact: Path) -> Dict[str, object]:
    """Stage 03: Verify 60/60 bit-exact RTL-vs-Python parity on fixed corpus."""
    iv, vvp = _require_iverilog_pair()
    hex_lines, expected = _build_60_python_vectors()
    Path("/tmp/v5_cosim_60.hex").write_text("\n".join(hex_lines) + "\n", encoding="utf-8")
    vvp_bin = Path("/tmp/v5_cosim_60.vvp")
    comp_rc, comp_out = _run_tool(
        [iv, "-g2005", "-Wall", "-o", str(vvp_bin), str(RTL_WRAPPER), str(RTL_COSIM_TB)],
        Path("/tmp/sync32_cosim_comp.log"),
    )
    if comp_rc != 0:
        raise RuntimeError(f"Co-sim compile failed: {comp_out}")
    run_rc, run_out = _run_tool([vvp, str(vvp_bin)], Path("/tmp/sync32_cosim60.log"))
    if run_rc != 0:
        raise RuntimeError(f"Co-sim run failed: {run_out}")
    rtl_rows = _parse_cosim_stdout(run_out)
    mismatches = _compare_cosim_rows(expected, rtl_rows)
    matched = len(expected) - len(mismatches)
    if len(rtl_rows) != 60 or mismatches:
        raise RuntimeError(f"Co-sim mismatch: {matched}/60 matched, {mismatches[:3]}")
    final_bank = "BANK_A" if rtl_rows[-1]["bank"] == 0 else "BANK_B"
    return {
        "stage": "03_co_sim_60_vectors",
        "prompts_dataset_sha256": sha256_file(PROMPTS_PATH),
        "vectors_tested": len(rtl_rows),
        "bit_exact_matches": matched,
        "parity_pct": round(100.0 * matched / max(1, len(expected)), 2),
        "mismatches": mismatches,
        "final_rtl_epoch": rtl_rows[-1]["epoch"],
        "final_rtl_bank": final_bank,
        "log_path": "/tmp/sync32_cosim60.log",
    }


def _classify_cell_counts(cell_lines: List[Tuple[str, str]]) -> Tuple[int, int]:
    """Count sequential flip-flops and inferred latches from Yosys cell list."""
    ff_tags = ("dfrbp", "sdfbbp", "dff")
    latch_tags = ("dlhq", "dlhr", "dlatch", "latch")
    ff_count = 0
    latch_count = 0
    for cnt_str, cname in cell_lines:
        cnt = int(cnt_str)
        low = cname.lower()
        if any(tag in low for tag in ff_tags):
            ff_count += cnt
        if any(tag in low for tag in latch_tags):
            latch_count += cnt
    return ff_count, latch_count


def _parse_yosys_cells(log_text: str) -> Dict[str, Any]:
    """Extract cell counts, FFs, latches, area (um^2), and logic depth from Yosys log."""
    total_m = re.search(r"^\s+(\d+)\s+[0-9.E+\-]+\s+cells\s*$", log_text, flags=re.MULTILINE)
    area_m = re.search(r"Chip area for module[^:]*:\s+([0-9.]+)", log_text)
    ltp_m = re.search(r"Longest topological path.*?length=(\d+)", log_text)
    cell_lines = re.findall(
        r"^\s+(\d+)\s+[0-9.E+\-]+\s+(sg13g2_\w+|\$_[A-Z0-9_]+)\s*$",
        log_text,
        flags=re.MULTILINE,
    )
    ff_count, latch_count = _classify_cell_counts(cell_lines)
    total_cells = int(total_m.group(1)) if total_m else sum(int(c) for c, _ in cell_lines)
    area_um2 = round(float(area_m.group(1)), 3) if area_m else 0.0
    area_mm2 = round(area_um2 / 1_000_000.0, 6)
    return {
        "total_cells": total_cells,
        "sequential_flip_flops": ff_count,
        "combinational_cells": max(0, total_cells - ff_count - latch_count),
        "inferred_latches": latch_count,
        "chip_area_um2": area_um2,
        "chip_area_mm2": area_mm2,
        "area_overhead_pct_vs_v40_gdsii_0p7896mm2": round(100.0 * area_mm2 / V40_GDSII_AREA_MM2, 4),
        "longest_topological_depth": int(ltp_m.group(1)) if ltp_m else 0,
        "unique_cell_types": len(cell_lines),
    }


def _extract_path_slacks(out: str, path_type: str) -> List[float]:
    """Extract all slack values belonging to Path Type: max or min blocks."""
    pat = rf"Path Type: {path_type}\b.*?([-0-9.]+)\s+slack\s+\((?:MET|VIOLATED)\)"
    return [float(x) for x in re.findall(pat, out, flags=re.DOTALL)]


def _parse_opensta_metrics(rc: int, out: str) -> Dict[str, object]:
    """Parse WNS, TNS, worst setup/hold slack, and f_max from OpenSTA output."""
    wns_m = re.search(r"wns\s+([-0-9.]+)", out)
    tns_m = re.search(r"tns\s+([-0-9.]+)", out)
    max_slacks = _extract_path_slacks(out, "max")
    min_slacks = _extract_path_slacks(out, "min")
    wns = float(wns_m.group(1)) if wns_m else 0.0
    tns = float(tns_m.group(1)) if tns_m else 0.0
    setup_slack = min(max_slacks) if max_slacks else 0.0
    hold_slack = min(min_slacks) if min_slacks else 0.0
    eff_period = max(0.1, 10.0 - setup_slack)
    met = all((rc == 0, wns >= 0.0, setup_slack >= 0.0, hold_slack >= 0.0))
    return {
        "available": True,
        "returncode": rc,
        "clock_target_mhz": 100.0,
        "clock_period_ns": 10.0,
        "wns_ns": round(wns, 4),
        "tns_ns": round(tns, 4),
        "setup_slack_ns": round(setup_slack, 4),
        "hold_slack_ns": round(hold_slack, 4),
        "timing_met_100mhz": met,
        "estimated_fmax_mhz": round(1000.0 / eff_period, 2),
        "log_path": "/tmp/sync32_opensta.log",
    }


def _run_opensta_100mhz(netlist_path: Path, lib_path: Path) -> Dict[str, object]:
    """Run optional OpenSTA static timing analysis at 100 MHz (10.0 ns period)."""
    sta_bin = _resolve_tool("sta")
    if sta_bin is None:
        return {"available": False, "reason": "OPENSTA_NOT_INSTALLED"}
    sdc_path = Path("/tmp/v5_core_nano_100mhz.sdc")
    tcl_path = Path("/tmp/v5_core_nano_sta.tcl")
    sdc_path.write_text(
        "create_clock -name clk -period 10.0 [get_ports clk]\n"
        "set_input_delay 1.5 -clock clk [lsearch -inline -all -not -exact [all_inputs] [get_ports clk]]\n"
        "set_output_delay 1.5 -clock clk [all_outputs]\n",
        encoding="utf-8",
    )
    sta_netlist = Path("/tmp/v5_core_nano_sg13g2_sta.v")
    sta_netlist.write_text(
        netlist_path.read_text(encoding="utf-8").replace(" signed ", " "),
        encoding="utf-8",
    )
    tcl_path.write_text(
        f"read_liberty {lib_path}\n"
        f"read_verilog {sta_netlist}\n"
        "link_design vmax_v5_core_nano_wrapper\n"
        f"read_sdc {sdc_path}\n"
        "report_wns\n"
        "report_tns\n"
        "report_checks -path_delay max -fields {slew cap input_pins nets} -digits 4\n"
        "report_checks -path_delay min -digits 4\n"
        "exit\n",
        encoding="utf-8",
    )
    rc, out = _run_tool([sta_bin, "-exit", str(tcl_path)], Path("/tmp/sync32_opensta.log"))
    return _parse_opensta_metrics(rc, out)


def _stage_yosys_sg13g2_synth(_artifact: Path) -> Dict[str, object]:
    """Stage 04: Synthesize rtl_v5 wrapper onto IHP SG13G2 130 nm PDK + OpenSTA."""
    yosys_bin = _resolve_tool("yosys")
    if yosys_bin is None or not SG13G2_TYP_LIB.exists():
        raise RuntimeError("yosys or IHP SG13G2 Liberty library unavailable")
    netlist_out = Path("/tmp/v5_core_nano_sg13g2_netlist.v")
    ys_script = Path("/tmp/v5_core_nano_synth.ys")
    ys_script.write_text(
        f"read_liberty -lib {SG13G2_TYP_LIB}\n"
        f"read_verilog {RTL_WRAPPER}\n"
        "hierarchy -check -top vmax_v5_core_nano_wrapper\n"
        "proc\n"
        "opt\n"
        "fsm\n"
        "opt\n"
        "memory\n"
        "opt\n"
        "techmap\n"
        "opt\n"
        f"dfflibmap -liberty {SG13G2_TYP_LIB}\n"
        f"abc -D 10000 -liberty {SG13G2_TYP_LIB}\n"
        "opt_clean -purge\n"
        "ltp\n"
        f"stat -liberty {SG13G2_TYP_LIB}\n"
        f"write_verilog -noattr {netlist_out}\n",
        encoding="utf-8",
    )
    rc, out = _run_tool([yosys_bin, "-s", str(ys_script)], Path("/tmp/sync32_yosys.log"))
    if rc != 0 or not netlist_out.exists():
        raise RuntimeError(f"Yosys synthesis failed (rc={rc})")
    ver_rc, ver_out = _run_tool([yosys_bin, "-V"], Path("/tmp/sync32_yosys_ver.log"))
    stats = _parse_yosys_cells(out)
    if stats["inferred_latches"] != 0:
        raise RuntimeError(f"Inferred latches detected: {stats['inferred_latches']}")
    sta_res = _run_opensta_100mhz(netlist_out, SG13G2_TYP_LIB)
    return {
        "stage": "04_yosys_sg13g2_synth",
        "yosys_version": ver_out.strip().splitlines()[0] if ver_rc == 0 else "unknown",
        "pdk_library_path": str(SG13G2_TYP_LIB),
        "pdk_library_sha256": sha256_file(SG13G2_TYP_LIB),
        "netlist_tmp_path": str(netlist_out),
        "netlist_sha256": sha256_file(netlist_out),
        "synthesis_metrics": stats,
        "opensta_100mhz": sta_res,
        "log_path": "/tmp/sync32_yosys.log",
    }


def _stage_seal_report(work_dir: Path) -> Callable[[Path], Dict[str, object]]:
    """Stage 05: Assemble and seal telemetry/VMAX_V5_VIRTUAL_SILICON_REPORT.json."""
    def _run(_artifact: Path) -> Dict[str, object]:
        s1 = json.loads((work_dir / "01_verilator_lint.json").read_text(encoding="utf-8"))
        s2 = json.loads((work_dir / "02_iverilog_tb.json").read_text(encoding="utf-8"))
        s3 = json.loads((work_dir / "03_co_sim_60_vectors.json").read_text(encoding="utf-8"))
        s4 = json.loads((work_dir / "04_yosys_sg13g2_synth.json").read_text(encoding="utf-8"))
        report: Dict[str, Any] = {
            "schema": "VMAX_V5_VIRTUAL_SILICON_REPORT_V1",
            "work_order": "WORK-ORDER-AG-32",
            "sync_id": "SYNC-32",
            "epistemic_register": "REGISTER_M",
            "bridge_reviewer_note": BROWSER_CRASH_GUARD_NOTE,
            "rtl_v5_sources": {
                "wrapper_path": "rtl_v5/vmax_v5_core_nano_wrapper.v",
                "wrapper_sha256": sha256_file(RTL_WRAPPER),
                "tb_path": "rtl_v5/tb_vmax_v5_core_nano_wrapper.v",
                "tb_sha256": sha256_file(RTL_TB),
                "cosim_tb_path": "rtl_v5/tb_vmax_v5_cosim_60.v",
                "cosim_tb_sha256": sha256_file(RTL_COSIM_TB),
            },
            "verilator_lint": s1,
            "iverilog_15_assertion_tb": s2,
            "cosim_60_vectors": s3,
            "yosys_sg13g2_130nm": s4,
            "v40_gdsii_reference_area_mm2": V40_GDSII_AREA_MM2,
        }
        payload_sha = atomic_write_json(REPORT_PATH, report)
        report["report_sha256"] = payload_sha
        atomic_write_json(REPORT_PATH, report)
        return {
            "stage": "05_seal_report",
            "report_path": str(REPORT_PATH.relative_to(REPO_ROOT)),
            "report_payload_sha256": payload_sha,
            "report_file_sha256": sha256_file(REPORT_PATH),
        }

    return _run


def run_pipeline(
    work_dir: Path = DEFAULT_WORK_DIR,
    pause_file: Path = Path(DEFAULT_PAUSE_FILE),
) -> Dict[str, object]:
    """Execute all 5 pausable SYNC-32 Virtual Silicon stages via StageCheckpointRunner."""
    print(
        "[V-MAX-12] Night-Quiet Reminder: Press Ctrl+C or ./pause_synth.sh "
        "to pause cleanly between EDA stages (resume: ./resume_synth.sh).",
        flush=True,
    )
    stages = [
        StageSpec("01_verilator_lint", "Verilator -Wall lint", "01_verilator_lint.json", _stage_verilator_lint),
        StageSpec("02_iverilog_tb", "Icarus 15-assertion TB", "02_iverilog_tb.json", _stage_iverilog_tb),
        StageSpec("03_co_sim_60_vectors", "60-vector RTL/Python co-sim", "03_co_sim_60_vectors.json", _stage_co_sim_60_vectors),
        StageSpec("04_yosys_sg13g2_synth", "Yosys IHP SG13G2 130 nm + OpenSTA", "04_yosys_sg13g2_synth.json", _stage_yosys_sg13g2_synth),
        StageSpec("05_seal_report", "Seal REGISTER_M Virtual Silicon report", "05_seal_report.json", _stage_seal_report(work_dir)),
    ]
    runner = StageCheckpointRunner(work_dir=work_dir, pause_file=pause_file)
    runner.install_signal_handlers()
    summary = runner.run_pipeline(stages)
    print(json.dumps(summary.to_dict(), sort_keys=True), flush=True)
    return summary.to_dict()


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point for SYNC-32 pausable Virtual Silicon synthesis pipeline."""
    parser = argparse.ArgumentParser(description="V-MAX-12 SYNC-32 Virtual Silicon EDA Pipeline")
    parser.add_argument("--work-dir", default=str(DEFAULT_WORK_DIR))
    parser.add_argument("--pause-file", default=DEFAULT_PAUSE_FILE)
    args = parser.parse_args(argv)
    run_pipeline(work_dir=Path(args.work_dir), pause_file=Path(args.pause_file))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
