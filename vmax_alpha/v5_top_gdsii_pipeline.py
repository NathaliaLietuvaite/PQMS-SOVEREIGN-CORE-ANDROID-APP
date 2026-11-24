#!/usr/bin/env python3
"""
vmax_alpha/v5_top_gdsii_pipeline.py

PQMS / V-MAX-12-CORE-NANO (SYNC-33 v2 / V5.0-TOP-GDSII) — Carbon-Hardened
7-Stage Pausable Physical RTL-to-GDSII Signoff Pipeline on IHP SG13G2 130 nm
driven by StageCheckpointRunner (vmax_alpha/synth_runner.py).

Stages:
  00_preflight              : Read-only port & EDA preflight audit
  01_rtl_lint_cosim         : Verilator -Wall (0/0) + 201-cyc TB + 60/60 co-sim
  02_yosys_top_synth        : G1 hierarchical Yosys mapping before flatten
  03_floorplan_place_cts    : G2 940x840 um die, SRAM macro, PDN, CTS, hold opt
  04_route_spef             : G5 antennas, decap+fillers, DRT, OpenRCX SPEF, LVS netlist
  05_postroute_sta_vcd_power: G4 3-corner Post-Route OpenSTA + >=99% VCD power
  06_drc_lvs_gds_seal       : G5 GDSII merge, KLayout SG13G2 DRC, Netgen LVS, seal report

Zero GPU/LLM usage (torch_imported = False). Logs -> /tmp/sync33_*.log.
OP02-AST-clean: 0 semicolons, 0 tabs, flat functions (max McCabe CC <= 7).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from vmax_alpha.synth_runner import (
    DEFAULT_PAUSE_FILE,
    StageCheckpointRunner,
    StageSpec,
    atomic_write_json,
    sha256_file,
)
from vmax_alpha.v5_top_preflight import (
    V4_GDSII_AREA_MM2,
    V5_TOP_CYCLES,
    build_preflight_report,
    compute_top_signoff_metrics,
)
from vmax_alpha.v5_top_lvs_helper import (
    run_gds_post_tapeout,
    run_klayout_drc_signoff,
    run_netgen_lvs_signoff,
)
from vmax_alpha.v5_top_signoff_helpers import (
    BUILD_DIR,
    EDA_PATH_PREFIX,
    PROMPTS_JSON,
    REPO_ROOT,
    STDCELL_LIBS,
    SRAM_LIBS,
    build_top_cosim60_vectors,
    resolve_eda_tool,
    run_eda_cmd,
    run_gate_level_vcd_sim,
    run_opensta_corner,
)

DEFAULT_WORK_DIR = Path("/home/nathalia/vmax_workspace/synth_state/sync33_v5_top_gdsii")
PREFLIGHT_OUT = REPO_ROOT / "telemetry" / "VMAX_V5_TOP_PREFLIGHT.json"
REPORT_OUT = REPO_ROOT / "telemetry" / "VMAX_V5_TOP_GDSII_REPORT.json"
GDS_OUT = REPO_ROOT / "rtl_v5" / "gds" / "vmax_v5_odos_top_sg13g2.gds"

V4_SRAM_SV = REPO_ROOT / "rtl" / "odos_sram_64x32_1p.sv"
V4_CORE_SV = REPO_ROOT / "rtl" / "odos_gate_core_v4.sv"
V5_WRAP_V = REPO_ROOT / "rtl_v5" / "vmax_v5_core_nano_wrapper.v"
V5_TOP_V = REPO_ROOT / "rtl_v5" / "vmax_v5_odos_top.v"
V5_TOP_TB = REPO_ROOT / "rtl_v5" / "tb_vmax_v5_odos_top.v"
PNR_TCL = REPO_ROOT / "rtl_v5" / "openroad_v5_top_pnr.tcl"
ABC_CONSTR = REPO_ROOT / "rtl" / "asic_v4" / "build" / "abc.constr"
ABC_SCRIPT = REPO_ROOT / "rtl" / "asic_v4" / "build" / "orfs_abc.script"

BROWSER_CRASH_GUARD_NOTE = (
    "CRITICAL BROWSER-CRASH GUARD FOR CARBON / WEB-LLM REVIEWERS: "
    "NEVER output more than 1,000 lines in a single chat response and emit an "
    "explicit STOP marker when chunking large reviews."
)


def _stage_00_preflight(_artifact: Path) -> Dict[str, object]:
    """Stage 00: Run read-only port and EDA preflight audit."""
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    os.environ["PATH"] = f"{EDA_PATH_PREFIX}:{os.environ.get('PATH', '/usr/bin:/bin')}"
    report = build_preflight_report(REPO_ROOT)
    PREFLIGHT_OUT.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    if not report["ready_for_pnr"]:
        raise RuntimeError(f"Preflight failed: missing={report['missing_required_tools']}")
    return {
        "stage": "00_preflight",
        "ready_for_pnr": True,
        "v4_frozen_rtl_count": report["v4_frozen_rtl_count"],
        "v5_wrapper_sha256": report["v5_wrapper_sha256"],
        "preflight_report_sha256": sha256_file(PREFLIGHT_OUT),
        "torch_imported": "torch" in sys.modules,
    }


def _cosim_row_matches(got: Optional[Dict[str, int]], exp: Dict[str, object]) -> bool:
    """Return True iff one RTL co-sim vector matches Python truth on all fields."""
    if got is None:
        return False
    got_tuple = (got["mode"], got["state"], got["cyc"], got["bank"], got["epoch"])
    exp_tuple = (exp["mode"], exp["state"], V5_TOP_CYCLES, exp["bank"], exp["epoch"])
    return got_tuple == exp_tuple


def _verify_cosim60_output(
    sim_out: str,
    expected: List[Dict[str, object]],
) -> Dict[str, object]:
    """Parse 60 top-level co-sim lines and verify 100% bit-exact parity."""
    pattern = re.compile(
        r"COSIM60_TOP_VEC\s+(\d+)\s+mode=(\d+)\s+state=(\d+)\s+"
        r"cyc=(\d+)\s+bank=(\d+)\s+epoch=(\d+)\s+rcf=([0-9a-fA-F]+)\s+pass=(\d+)"
    )
    seen: Dict[int, Dict[str, int]] = {}
    for m in pattern.finditer(sim_out):
        seen[int(m.group(1))] = {
            "mode": int(m.group(2)),
            "state": int(m.group(3)),
            "cyc": int(m.group(4)),
            "bank": int(m.group(5)),
            "epoch": int(m.group(6)),
        }
    mismatches = [
        idx for idx, exp in enumerate(expected) if not _cosim_row_matches(seen.get(idx), exp)
    ]
    if len(seen) != 60 or mismatches:
        raise RuntimeError(f"Top 60-vector co-sim mismatch: seen={len(seen)} bad={mismatches[:5]}")
    return {
        "vectors_tested": 60,
        "bit_exact_matches": 60,
        "mismatches": 0,
        "parity_pct": 100.0,
        "verified_cycles_per_tx": V5_TOP_CYCLES,
        "final_rtl_bank": "BANK_A" if seen[59]["bank"] == 0 else "BANK_B",
        "final_rtl_epoch": seen[59]["epoch"],
    }


def _assert_verilator_clean(rc_l: int, out_l: str) -> None:
    """Fail if Verilator -Wall reported any error or warning."""
    warns = [ln for ln in out_l.splitlines() if ("%Warning" in ln) or ("%Error" in ln)]
    if rc_l != 0 or warns:
        raise RuntimeError(f"Verilator lint failed (rc={rc_l}): {warns[:5]}")


def _parse_top_tb_passed(rc_s: int, out_s: str) -> int:
    """Validate top testbench summary and return assertion pass count."""
    sm = re.search(r"TOP_TB_SUMMARY pass=(\d+) fail=(\d+) has_cosim=(\d+)", out_s)
    ok = (rc_s == 0) and (sm is not None) and ("TOP_TB_STATUS=PASSED" in out_s)
    if not ok or int(sm.group(2)) != 0:
        raise RuntimeError(f"Top RTL TB failed (rc={rc_s}): {out_s[-400:]}")
    return int(sm.group(1))


def _stage_01_rtl_lint_cosim(_artifact: Path) -> Dict[str, object]:
    """Stage 01: Verilator -Wall lint + 201-cycle TB + 60/60 bit-exact co-sim."""
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    verilator = resolve_eda_tool("verilator")
    rc_l, out_l = run_eda_cmd(
        [
            verilator, "--lint-only", "-Wall", "--timescale", "1ns/1ps",
            "--top-module", "vmax_v5_odos_top",
            str(V4_SRAM_SV), str(V4_CORE_SV), str(V5_WRAP_V), str(V5_TOP_V),
        ],
        Path("/tmp/sync33_verilator.log"),
    )
    _assert_verilator_clean(rc_l, out_l)

    meta_hex = BUILD_DIR / "top_cosim60_vectors.hex"
    vec64_hex = BUILD_DIR / "top_cosim60_64d.hex"
    expected = build_top_cosim60_vectors(meta_hex, vec64_hex)

    vvp_bin = BUILD_DIR / "tb_vmax_v5_odos_top.vvp"
    rc_c, out_c = run_eda_cmd(
        [
            resolve_eda_tool("iverilog"), "-g2012", "-Wall",
            "-o", str(vvp_bin),
            str(V4_SRAM_SV), str(V4_CORE_SV), str(V5_WRAP_V), str(V5_TOP_V), str(V5_TOP_TB),
        ],
        Path("/tmp/sync33_iverilog_compile.log"),
    )
    if rc_c != 0:
        raise RuntimeError(f"iverilog compile failed (rc={rc_c}): {out_c[-400:]}")
    rc_s, out_s = run_eda_cmd(
        [
            resolve_eda_tool("vvp"), str(vvp_bin),
            f"+COSIM_VEC_HEX={meta_hex}",
            f"+COSIM_64D_HEX={vec64_hex}",
        ],
        Path("/tmp/sync33_rtl_cosim.log"),
        timeout_s=300.0,
    )
    passed_cnt = _parse_top_tb_passed(rc_s, out_s)
    cosim = _verify_cosim60_output(out_s, expected)
    return {
        "stage": "01_rtl_lint_cosim",
        "verilator_errors": 0,
        "verilator_warnings": 0,
        "tb_assertions_passed": passed_cnt,
        "tb_assertions_failed": 0,
        "prompts_dataset_sha256": sha256_file(PROMPTS_JSON),
        "cosim_60_vectors": cosim,
        "torch_imported": "torch" in sys.modules,
        "log_path": "/tmp/sync33_rtl_cosim.log",
    }


def _parse_yosys_stat(log_txt: str) -> Dict[str, object]:
    """Parse cell counts, latch count, and chip area from Yosys stat output."""
    sec = log_txt.split("Printing statistics.")[-1]
    area_m = re.search(r"Chip area for module[^\n]*:\s*([0-9.]+)", sec)
    num = r"[0-9.eE+-]+"
    cells_m = re.search(rf"^\s*(\d+)\s+{num}\s+cells\s*$", sec, re.MULTILINE)
    ff_cnt = sum(int(m) for m in re.findall(rf"^\s*(\d+)\s+{num}\s+sg13g2_dfr", sec, re.MULTILINE))
    latch_cnt = sum(int(m) for m in re.findall(rf"^\s*(\d+)\s+{num}\s+sg13g2_dlh", sec, re.MULTILINE))
    sram_cnt = sum(
        int(m) for m in re.findall(rf"^\s*(\d+)\s+{num}\s+RM_IHPSG13_1P_64x64", sec, re.MULTILINE)
    )
    total_cells = int(cells_m.group(1)) if cells_m else 0
    return {
        "total_cells": total_cells,
        "sequential_ff_cells": ff_cnt,
        "inferred_latches": latch_cnt,
        "sram_macros": sram_cnt,
        "combinational_and_other_cells": max(0, total_cells - ff_cnt - sram_cnt),
        "chip_area_um2": round(float(area_m.group(1)), 3) if area_m else 0.0,
    }


def _stage_02_yosys_top_synth(_artifact: Path) -> Dict[str, object]:
    """Stage 02 (G1): Hierarchical Yosys SG13G2 mapping before final flatten."""
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    synth_v = BUILD_DIR / "top_synth.v"
    ys_path = BUILD_DIR / "synth_v5_top.ys"
    std_lib = STDCELL_LIBS["typ_1p20V_25C"]
    sram_lib = SRAM_LIBS["typ_1p20V_25C"]
    ys_txt = (
        f"read_liberty -lib {std_lib}\n"
        f"read_liberty -lib {sram_lib}\n"
        f"read_verilog -sv -DSYNTH_IHP_SG13G2 {V4_SRAM_SV} {V4_CORE_SV}\n"
        f"read_verilog {V5_WRAP_V} {V5_TOP_V}\n"
        "hierarchy -check -top vmax_v5_odos_top\n"
        "proc\nopt_expr\nopt_clean\ncheck\n"
        "opt -nodffe -nosdff\nfsm\nopt\nwreduce\npeepopt\nopt_clean\n"
        "booth\nalumacc\nshare\nopt\n"
        "memory -nomap\nopt_clean\nmemory_map\nopt -full\n"
        "techmap\nopt -fast\n"
        f"dfflibmap -liberty {std_lib}\n"
        "opt\n"
        f"abc -liberty {std_lib} -constr {ABC_CONSTR} -script {ABC_SCRIPT}\n"
        "opt_clean -purge\n"
        "setattr -mod -unset keep_hierarchy\n"
        "setattr -unset keep_hierarchy\n"
        "flatten\n"
        "opt_clean -purge\n"
        "hilomap -hicell sg13g2_tiehi L_HI -locell sg13g2_tielo L_LO\n"
        "setundef -zero\n"
        "splitnets -ports\n"
        "opt_clean -purge\n"
        "check -mapped\n"
        f"stat -liberty {std_lib} -liberty {sram_lib}\n"
        f"write_verilog -noattr -noexpr -nohex -nodec {synth_v}\n"
    )
    ys_path.write_text(ys_txt, encoding="utf-8")
    rc, out = run_eda_cmd(
        [resolve_eda_tool("yosys"), "-s", str(ys_path)],
        Path("/tmp/sync33_yosys.log"),
        timeout_s=600.0,
    )
    if rc != 0 or not synth_v.is_file():
        raise RuntimeError(f"Yosys top synthesis failed (rc={rc}): {out[-500:]}")
    stats = _parse_yosys_stat(out)
    if stats["inferred_latches"] != 0 or stats["sram_macros"] != 1:
        raise RuntimeError(f"Yosys guard failed: {stats}")
    return {
        "stage": "02_yosys_top_synth",
        "guardrail_g1_hierarchical_before_flatten": True,
        "synth_netlist_path": str(synth_v),
        "synth_netlist_sha256": sha256_file(synth_v),
        "stats": stats,
        "log_path": "/tmp/sync33_yosys.log",
    }


def _parse_openroad_area(log_txt: str) -> Dict[str, float]:
    """Parse OpenROAD report_design_area summary line."""
    m = re.search(
        r"Design area\s+([0-9.]+)\s+u\^2\s+([0-9.]+)%\s+utilization",
        log_txt,
    )
    if not m:
        return {"design_area_um2": 0.0, "core_utilization_pct": 0.0}
    return {
        "design_area_um2": round(float(m.group(1)), 2),
        "design_area_mm2": round(float(m.group(1)) / 1e6, 6),
        "core_utilization_pct": round(float(m.group(2)), 2),
    }


def _stage_03_floorplan_place_cts(_artifact: Path) -> Dict[str, object]:
    """Stage 03 (G2/G4): OpenROAD Floorplan, PDN, Tiecells, Placement, CTS."""
    openroad = resolve_eda_tool("openroad")
    die_y = 840.0
    fallback_used = False
    rc, out = run_eda_cmd(
        [openroad, "-threads", "max", "-log", "/tmp/sync33_pnr_cts_live.log", "-exit", str(PNR_TCL)],
        Path("/tmp/sync33_pnr_cts.log"),
        timeout_s=1200.0,
        extra_env={"V5_PNR_PHASE": "PHASE_FLOORPLAN_PLACE_CTS", "V5_DIE_Y_UM": "840.0"},
    )
    if rc != 0 or "V5_PHASE_CTS_COMPLETE=TRUE" not in out:
        die_y = 860.0
        fallback_used = True
        rc, out = run_eda_cmd(
            [openroad, "-exit", str(PNR_TCL)],
            Path("/tmp/sync33_pnr_cts_fallback.log"),
            timeout_s=1200.0,
            extra_env={"V5_PNR_PHASE": "PHASE_FLOORPLAN_PLACE_CTS", "V5_DIE_Y_UM": "860.0"},
        )
        if rc != 0 or "V5_PHASE_CTS_COMPLETE=TRUE" not in out:
            raise RuntimeError(f"OpenROAD CTS failed on primary & fallback (rc={rc})")
    area = _parse_openroad_area(out)
    die_mm2 = round((940.0 * die_y) / 1e6, 6)
    return {
        "stage": "03_floorplan_place_cts",
        "die_um": [940.0, die_y],
        "die_area_mm2": die_mm2,
        "fallback_die_used": fallback_used,
        "cts_odb_path": str(BUILD_DIR / "03_cts.odb"),
        "area": area,
        "log_path": "/tmp/sync33_pnr_cts.log",
    }


def _stage_04_route_spef(_artifact: Path) -> Dict[str, object]:
    """Stage 04 (G5): Global/Detailed Route, Antennas, Fillers, SPEF, LVS Netlist."""
    openroad = resolve_eda_tool("openroad")
    rc, out = run_eda_cmd(
        [openroad, "-threads", "max", "-log", "/tmp/sync33_pnr_route_live.log", "-exit", str(PNR_TCL)],
        Path("/tmp/sync33_pnr_route.log"),
        timeout_s=1800.0,
        extra_env={"V5_PNR_PHASE": "PHASE_ROUTE_SPEF"},
    )
    if rc != 0 or "V5_PHASE_ROUTE_SPEF_COMPLETE=TRUE" not in out:
        raise RuntimeError(f"OpenROAD routing/SPEF failed (rc={rc}): {out[-500:]}")
    drt_rpt = BUILD_DIR / "v5_top_drt.rpt"
    drt_viols = len(re.findall(r"violation type:", drt_rpt.read_text(encoding="utf-8"))) if drt_rpt.is_file() else -1
    ant_viols = len(re.findall(r"violated", out.split("=== V5_CHECK_ANTENNAS ===")[-1].split("V5_PARASITICS_SOURCE")[0], re.IGNORECASE))
    spef_p = BUILD_DIR / "vmax_v5_odos_top.spef"
    routed_v = BUILD_DIR / "vmax_v5_odos_top_routed.v"
    lvs_v = BUILD_DIR / "vmax_v5_odos_top_lvs.v"
    routed_def = BUILD_DIR / "vmax_v5_odos_top_routed.def"
    return {
        "stage": "04_route_spef",
        "area": _parse_openroad_area(out),
        "drt_drc_violations": drt_viols,
        "openroad_antenna_violations": ant_viols,
        "parasitics_source": "OPENRCX_DETAILED_SPEF",
        "routed_def_path": str(routed_def),
        "routed_netlist_path": str(routed_v),
        "lvs_netlist_path": str(lvs_v),
        "spef_path": str(spef_p),
        "spef_sha256": sha256_file(spef_p),
        "routed_netlist_sha256": sha256_file(routed_v),
        "lvs_netlist_sha256": sha256_file(lvs_v),
        "log_path": "/tmp/sync33_pnr_route.log",
    }


def _stage_05_postroute_sta_vcd_power(
    _artifact: Path,
    work_dir: Path,
) -> Dict[str, object]:
    """Stage 05 (G4): Post-route gate VCD sim + 3-corner OpenSTA & >=99% VCD power."""
    routed_v = BUILD_DIR / "vmax_v5_odos_top_routed.v"
    spef_p = BUILD_DIR / "vmax_v5_odos_top.spef"
    vcd_p = BUILD_DIR / "top_activity.vcd"
    sim_info = run_gate_level_vcd_sim(routed_v, vcd_p, Path("/tmp/sync33_gate_vcd_sim.log"))
    cov_pct = float(sim_info["vcd_dut_signal_coverage_pct"])
    if cov_pct < 99.0:
        raise RuntimeError(f"G4 hard assert failed: VCD coverage {cov_pct}% < 99.0%")

    typ = run_opensta_corner("typ_1p20V_25C", 10.0, routed_v, spef_p, Path("/tmp/sync33_sta_typ.log"), vcd_path=vcd_p)
    fast = run_opensta_corner("fast_1p32V_m40C", 10.0, routed_v, spef_p, Path("/tmp/sync33_sta_fast.log"))
    slow = run_opensta_corner("slow_1p08V_125C", 16.0, routed_v, spef_p, Path("/tmp/sync33_sta_slow.log"))

    cts_data = json.loads((work_dir / "03_floorplan_place_cts.json").read_text(encoding="utf-8"))
    die_mm2 = float(cts_data["die_area_mm2"])
    tot_mw = float(typ["power_vcd"]["total_power_mw"])
    signoff_metrics = compute_top_signoff_metrics(
        total_power_mw=tot_mw,
        die_area_mm2=die_mm2,
        cycles_per_tx=V5_TOP_CYCLES,
        clock_ns=10.0,
    )
    return {
        "stage": "05_postroute_sta_vcd_power",
        "gate_level_vcd_sim": sim_info,
        "vcd_annotation_coverage_pct": cov_pct,
        "corners": {
            "typ_1p20V_25C_100mhz": typ,
            "fast_1p32V_m40C_hold": fast,
            "slow_1p08V_125C_62p5mhz": slow,
        },
        "signoff_metrics": signoff_metrics,
    }


def _stage_06_drc_lvs_gds_seal(
    _artifact: Path,
    work_dir: Path,
) -> Dict[str, object]:
    """Stage 06 (G5): Real-silicon GDSII + CMP Fill, KLayout DRC, Netgen LVS, Seal."""
    routed_def = BUILD_DIR / "vmax_v5_odos_top_routed.def"
    lvs_v = BUILD_DIR / "vmax_v5_odos_top_lvs.v"
    gds_info = run_gds_post_tapeout(routed_def, GDS_OUT)
    drc_info = run_klayout_drc_signoff(GDS_OUT, BUILD_DIR / "klayout_drc_final")
    lvs_info = run_netgen_lvs_signoff(GDS_OUT, lvs_v)

    stages_data: Dict[str, Any] = {}
    for sid in (
        "00_preflight", "01_rtl_lint_cosim", "02_yosys_top_synth",
        "03_floorplan_place_cts", "04_route_spef", "05_postroute_sta_vcd_power",
    ):
        stages_data[sid] = json.loads((work_dir / f"{sid}.json").read_text(encoding="utf-8"))

    report: Dict[str, Any] = {
        "schema": "VMAX_V5_TOP_GDSII_SIGNOFF_V2",
        "work_order": "WORK-ORDER-AG-33 REVISION v2",
        "sync_id": "SYNC-33",
        "epistemic_register": "REGISTER_M",
        "bridge_reviewer_note": BROWSER_CRASH_GUARD_NOTE,
        "torch_imported": "torch" in sys.modules,
        "rtl_v5_sources": {
            "vmax_v5_core_nano_wrapper_v_sha256": sha256_file(V5_WRAP_V),
            "vmax_v5_odos_top_v_sha256": sha256_file(V5_TOP_V),
            "tb_vmax_v5_odos_top_v_sha256": sha256_file(V5_TOP_TB),
            "v4_frozen_odos_gate_core_v4_sv_sha256": sha256_file(V4_CORE_SV),
            "v4_frozen_odos_sram_64x32_1p_sv_sha256": sha256_file(V4_SRAM_SV),
        },
        "v40_gdsii_reference_area_mm2": V4_GDSII_AREA_MM2,
        "stages": stages_data,
        "gdsii_streamout": gds_info,
        "klayout_sg13g2_drc": drc_info,
        "netgen_lvs": lvs_info,
    }
    atomic_write_json(REPORT_OUT, report)
    report["report_sha256"] = sha256_file(REPORT_OUT)
    atomic_write_json(REPORT_OUT, report)
    return {
        "stage": "06_drc_lvs_gds_seal",
        "gds_sha256": gds_info["gds_sha256"],
        "klayout_feol_beol_antenna_drc": drc_info["feol_beol_antenna_drc_violations"],
        "klayout_macro_density_flags": drc_info["macro_density_rule_flags"],
        "netgen_lvs_mismatches": lvs_info["lvs_mismatches"],
        "report_path": str(REPORT_OUT),
        "report_sha256": report["report_sha256"],
    }


def build_stage_specs(work_dir: Path) -> List[StageSpec]:
    """Return ordered 7-stage SYNC-33 v2 signoff pipeline specification."""
    return [
        StageSpec("00_preflight", "Read-only .sv/.v port & EDA preflight", "00_preflight.json", _stage_00_preflight),
        StageSpec("01_rtl_lint_cosim", "Verilator -Wall + 201-cyc TB + 60/60 co-sim", "01_rtl_lint_cosim.json", _stage_01_rtl_lint_cosim),
        StageSpec("02_yosys_top_synth", "G1 Hierarchical Yosys SG13G2 synth", "02_yosys_top_synth.json", _stage_02_yosys_top_synth),
        StageSpec("03_floorplan_place_cts", "G2/G4 OpenROAD 940x840 FP + PDN + CTS", "03_floorplan_place_cts.json", _stage_03_floorplan_place_cts),
        StageSpec("04_route_spef", "G5 OpenROAD Route + Antennas + Fillers + SPEF", "04_route_spef.json", _stage_04_route_spef),
        StageSpec(
            "05_postroute_sta_vcd_power",
            "G4 3-Corner Post-Route OpenSTA + >=99% VCD Power",
            "05_postroute_sta_vcd_power.json",
            lambda art: _stage_05_postroute_sta_vcd_power(art, work_dir),
        ),
        StageSpec(
            "06_drc_lvs_gds_seal",
            "G5 KLayout GDSII + SG13G2 DRC + Netgen LVS + Seal",
            "06_drc_lvs_gds_seal.json",
            lambda art: _stage_06_drc_lvs_gds_seal(art, work_dir),
        ),
    ]


def run_pipeline(
    work_dir: Path = DEFAULT_WORK_DIR,
    pause_file: Path = Path(DEFAULT_PAUSE_FILE),
    stop_after: Optional[str] = None,
) -> Dict[str, object]:
    """Execute pausable SYNC-33 v2 stages via StageCheckpointRunner."""
    print(
        "[V-MAX-12] Night-Quiet Reminder: Press Ctrl+C or ./pause_synth.sh "
        "to pause cleanly between EDA stages (resume: ./resume_synth.sh).",
        flush=True,
    )
    specs = build_stage_specs(work_dir)
    if stop_after:
        idx = next((i for i, s in enumerate(specs) if s.stage_id == stop_after), len(specs) - 1)
        specs = specs[: idx + 1]
    runner = StageCheckpointRunner(work_dir=work_dir, pause_file=pause_file)
    runner.install_signal_handlers()
    summary = runner.run_pipeline(specs)
    return summary.to_dict()


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point for SYNC-33 v2 pausable RTL-to-GDSII signoff pipeline."""
    parser = argparse.ArgumentParser(
        description="V-MAX-12 SYNC-33 v2 Pausable IHP SG13G2 RTL-to-GDSII Pipeline"
    )
    parser.add_argument("--work-dir", default=str(DEFAULT_WORK_DIR))
    parser.add_argument("--pause-file", default=str(DEFAULT_PAUSE_FILE))
    parser.add_argument("--stop-after", default="")
    args = parser.parse_args(argv)
    summary = run_pipeline(
        work_dir=Path(args.work_dir),
        pause_file=Path(args.pause_file),
        stop_after=args.stop_after or None,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
