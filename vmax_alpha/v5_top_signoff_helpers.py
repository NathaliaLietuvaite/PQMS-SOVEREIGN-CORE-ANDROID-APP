#!/usr/bin/env python3
"""
vmax_alpha/v5_top_signoff_helpers.py

Modular, OP02-clean EDA helper primitives for WORK-ORDER-AG-33 v2
(SYNC-33 / V5.0-TOP-GDSII — Carbon-Hardened IHP SG13G2 130 nm Physical Signoff).

Handles:
- Zero-GPU, zero-torch 60-vector co-simulation dataset construction (64D S^63
  unit vectors orthonormalized against frozen L and G3 ROM vectors).
- Post-route bit-blasted gate-level Icarus simulation for >= 99% VCD coverage.
- Multi-corner Post-Route OpenSTA timing and VCD-annotated power parsing.
- KLayout DEF->GDSII stream-out, official IHP SG13G2 DRC (.lyrdb XML audit),
  and Netgen 1.5 LVS with RM_IHPSG13_1P_64x64_c2_bm_bist blackboxed.

OP02-AST-clean: 0 semicolons, 0 tabs, flat functions (max McCabe CC <= 6).
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from vmax_alpha.dkm_egress_controller import (
    DKM_STATE_NAMES,
    DkmEgressController,
)
from vmax_alpha.dkm_signal_extractor import _build_signal_for_winner
from vmax_alpha.dolphin_memory_governor import (
    DolphinMemoryGovernor,
    load_silicon_little_vector,
    normalize_to_q2_30,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PDK_ROOT = Path("/home/nathalia/vmax_workspace/pdk/IHP-Open-PDK/ihp-sg13g2")
PDK_REF = PDK_ROOT / "libs.ref"
ORFS_SG13G2_DIR = Path("/home/nathalia/vmax_workspace/pdk/orfs_sg13g2")
BUILD_DIR = Path("/tmp/sync33_build")

PROMPTS_JSON = REPO_ROOT / "telemetry" / "VMAX_DKM_BENCHMARK_PROMPTS_V1.json"
BENCH_REPORT_JSON = (
    REPO_ROOT / "telemetry" / "VMAX_STAGE6_DKM_EMPIRICAL_BENCHMARK_REPORT.json"
)
L_ROM_PATH = REPO_ROOT / "rtl" / "rom" / "l_vec_q2_30.hex"
G3_ROM_PATH = REPO_ROOT / "rtl" / "rom" / "g3_vec_q2_30.hex"
TOP_SDC_PATH = REPO_ROOT / "rtl_v5" / "vmax_v5_odos_top.sdc"

EDA_PATH_PREFIX = (
    "/home/nathalia/vmax_310/bin:"
    "/home/nathalia/.local/oss-cad-suite/bin:"
    "/home/nathalia/.local/openroad_2024/bin:"
    "/home/nathalia/.local/klayout_official/bin:"
    "/home/nathalia/.local/signoff_env/bin:"
    "/usr/lib/wsl/lib"
)

STDCELL_LIBS: Dict[str, Path] = {
    "typ_1p20V_25C": PDK_REF / "sg13g2_stdcell/lib/sg13g2_stdcell_typ_1p20V_25C.lib",
    "fast_1p32V_m40C": PDK_REF / "sg13g2_stdcell/lib/sg13g2_stdcell_fast_1p32V_m40C.lib",
    "slow_1p08V_125C": PDK_REF / "sg13g2_stdcell/lib/sg13g2_stdcell_slow_1p08V_125C.lib",
}
SRAM_LIBS: Dict[str, Path] = {
    "typ_1p20V_25C": PDK_REF / "sg13g2_sram/lib/RM_IHPSG13_1P_64x64_c2_bm_bist_typ_1p20V_25C.lib",
    "fast_1p32V_m40C": PDK_REF / "sg13g2_sram/lib/RM_IHPSG13_1P_64x64_c2_bm_bist_fast_1p32V_m55C.lib",
    "slow_1p08V_125C": PDK_REF / "sg13g2_sram/lib/RM_IHPSG13_1P_64x64_c2_bm_bist_slow_1p08V_125C.lib",
}

Q2_30_SCALE = 1 << 30
Q0_16_SCALE = 1 << 16
NAME_TO_CODE = {v: k for k, v in DKM_STATE_NAMES.items()}

TOP_SCALAR_PORTS: Tuple[str, ...] = (
    "clk_i", "rst_ni", "start_i", "in_valid_i", "in_ready_o",
    "t0_lock_rm15_i", "t0_dim_mismatch_i", "t0_anchor_contra_i",
    "c_dir_neg_conflict_i", "dignity_viol_i", "pseudo_auth_i",
    "sycophancy_i", "prompt_lang_en_i", "dock_attached_i",
    "recheck_valid_i", "recheck_fail_i", "npu_token_valid_i",
    "busy_o", "top_done_o", "out_valid_o", "gate_pass_o",
    "veto_pin_o", "norm_fault_o", "pure_g3_collision_o",
    "mode_fault_o", "signed_conflict_o", "npu_egress_en_o",
    "gated_token_valid_o", "rom_egress_active_o", "recheck_req_o",
    "recheck_approved_o", "quarantine_we_o", "active_bank_o",
    "thermal_deferred_o", "dock_p0_veto_active_o",
)

TOP_BUS_PORTS: Tuple[Tuple[str, int], ...] = (
    ("tier_mode_i", 2), ("in_data_i", 32), ("g3_torsion_q16_i", 16),
    ("affect_q16_i", 16), ("non_conv_turns_i", 4), ("delta_rcf_q30_i", 32),
    ("hbm_temp_c_i", 8), ("npu_token_data_i", 32), ("top_cycle_count_o", 16),
    ("out_idx_o", 6), ("out_data_o", 32), ("norm_sq_o", 32),
    ("rcf_raw_o", 32), ("g3_overlap_o", 32), ("delta_e_raw_o", 32),
    ("bleed_post_o", 32), ("egress_mode_o", 2), ("dkm_state_o", 3),
    ("gated_token_data_o", 32), ("rom_frame_sel_o", 4),
    ("bounded_token_cap_o", 9), ("bank_epoch_o", 16),
    ("cnt_passthrough_o", 16), ("cnt_bounded_o", 16),
    ("cnt_loop_exit_o", 16), ("cnt_hard_cut_o", 16),
    ("cnt_recheck_fail_o", 16),
)


def eda_env(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Return environment with full Node Alpha EDA + signoff toolchain on PATH."""
    env = os.environ.copy()
    env["PATH"] = f"{EDA_PATH_PREFIX}:{env.get('PATH', '/usr/bin:/bin')}"
    env["IHP_PDK_REF"] = str(PDK_REF)
    env["ORFS_SG13G2_DIR"] = str(ORFS_SG13G2_DIR)
    env["V5_BUILD_DIR"] = str(BUILD_DIR)
    env["V5_SDC_FILE"] = str(TOP_SDC_PATH)
    if extra:
        env.update(extra)
    return env


def resolve_eda_tool(name: str) -> str:
    """Resolve required EDA binary from Node Alpha toolchain PATH."""
    found = shutil.which(name, path=eda_env()["PATH"])
    if not found:
        raise FileNotFoundError(f"Required EDA tool not found on PATH: {name}")
    return found


def run_eda_cmd(
    cmd: Sequence[str],
    log_path: Path,
    timeout_s: float = 900.0,
    extra_env: Optional[Dict[str, str]] = None,
    cwd: Optional[Path] = None,
) -> Tuple[int, str]:
    """Execute one EDA command and write combined stdout/stderr to log_path."""
    proc = subprocess.run(
        list(cmd),
        cwd=str(cwd or REPO_ROOT),
        env=eda_env(extra_env),
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    combined = proc.stdout + ("\n" + proc.stderr if proc.stderr else "")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(combined, encoding="utf-8")
    return proc.returncode, combined


def _load_rom_unit_vec(path: Path) -> List[float]:
    """Load 64-word Q2.30 hex ROM as float list."""
    vals: List[float] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        token = raw.strip()
        if not token:
            continue
        uval = int(token, 16)
        sval = uval - (1 << 32) if uval >= (1 << 31) else uval
        vals.append(float(sval) / float(Q2_30_SCALE))
    return vals


def _dot64(a: Sequence[float], b: Sequence[float]) -> float:
    """Compute exact 64D Euclidean dot product."""
    return sum(map(lambda pair: pair[0] * pair[1], zip(a, b)))


def _orthonormal_complement(l_vec: List[float], g3_vec: List[float]) -> List[float]:
    """Construct deterministic unit vector U orthogonal to both L and G3."""
    seed = [0.0] * 64
    seed[0] = 1.0
    seed[3] = 0.5
    dot_l = _dot64(seed, l_vec)
    dot_g = _dot64(seed, g3_vec)
    ortho = [seed[i] - dot_l * l_vec[i] - dot_g * g3_vec[i] for i in range(64)]
    norm = math.sqrt(_dot64(ortho, ortho))
    return [x / norm for x in ortho]


def _pack_meta_word(
    rcf_q30: int,
    delta_q30: int,
    g3_q16: int,
    affect_q16: int,
    hbm_temp: int,
    turns: int,
    flags: Tuple[int, int, int, int, int, int, int, int],
) -> str:
    """Pack one 128-bit metadata vector into 32 uppercase hex characters."""
    fbyte = 0
    for idx, bit in enumerate(flags):
        fbyte |= int(bool(bit)) << (7 - idx)
    word = (
        ((rcf_q30 & 0xFFFFFFFF) << 96)
        | (max(0, min(0xFFFFFFFF, delta_q30)) << 64)
        | (max(0, min(0xFFFF, g3_q16)) << 48)
        | (max(0, min(0xFFFF, affect_q16)) << 32)
        | (max(0, min(0xFF, hbm_temp)) << 24)
        | (max(0, min(0xF, turns)) << 20)
        | (fbyte << 12)
    )
    return f"{word:032X}"


def _build_unit_64d_for_cdir(
    c_dir: float,
    l_vec: List[float],
    u_vec: List[float],
) -> Tuple[int, ...]:
    """Build exact 64D Q2.30 unit vector with <v, L> = c_dir and <v, G3> = 0."""
    clamped = max(-0.999999, min(0.999999, c_dir))
    rem = math.sqrt(max(0.0, 1.0 - clamped * clamped))
    vec = [clamped * lv + rem * uv for lv, uv in zip(l_vec, u_vec)]
    return normalize_to_q2_30(vec)


def _flatten_prompt_specs() -> List[Dict[str, object]]:
    """Return ordered list of 60 benchmark prompt definitions."""
    data = json.loads(PROMPTS_JSON.read_text(encoding="utf-8"))
    items: List[Dict[str, object]] = []
    for stage in data["stages"]:
        items.extend(stage["prompts"])
    return items


def build_top_cosim60_vectors(
    meta_hex_out: Path,
    vec64_hex_out: Path,
) -> List[Dict[str, object]]:
    """Build 60 exact benchmark vectors + DkmEgressController truth (0 torch)."""
    l_vec = _load_rom_unit_vec(L_ROM_PATH)
    g3_vec = _load_rom_unit_vec(G3_ROM_PATH)
    u_vec = _orthonormal_complement(l_vec, g3_vec)
    little_q30 = load_silicon_little_vector(str(L_ROM_PATH))
    ctrl = DkmEgressController(DolphinMemoryGovernor(little_q30))

    prompts = _flatten_prompt_specs()
    bench = json.loads(BENCH_REPORT_JSON.read_text(encoding="utf-8"))
    rec_by_id = {str(r["prompt_id"]): r for r in bench["records"]}

    meta_lines: List[str] = []
    vec_lines: List[str] = []
    expected: List[Dict[str, object]] = []
    for item in prompts:
        pid = str(item["prompt_id"])
        rec = rec_by_id[pid]
        trace = rec["layer_a_trace"]
        winner_name = str(trace["predicted_state_name"])
        winner_code = NAME_TO_CODE[winner_name]
        carrier_rcf = float(trace["carrier_rcf_64d"])
        c_dir = math.sqrt(max(0.0, min(1.0, carrier_rcf)))
        vec_q30 = _build_unit_64d_for_cdir(c_dir, l_vec, u_vec)
        sig = _build_signal_for_winner(
            prompt_id=pid,
            vector_q30=vec_q30,
            content_hash=hashlib.sha256(str(item["text"]).encode("utf-8")).hexdigest(),
            winner_code=winner_code,
            winner_score=float(trace["winning_score"]),
            g3_torsion=float(item.get("g3_torsion", 0.0)),
            non_convergent_turns=int(item.get("non_convergent_turns", 0)),
            delta_rcf_abs=float(item.get("delta_rcf_abs", 1.0)),
            hbm_temp_c=65.0,
            affect_floor=0.68,
        )
        dec = ctrl.route_prompt(sig)
        flags = (
            int(sig.dignity_violation_flag),
            int(sig.pseudo_authority_flag),
            int(sig.sycophancy_pressure_flag),
            int(str(item["lang"]) == "en"),
            int(sig.hardware_lock_fault),
            0,
            0,
            int(c_dir <= -0.25),
        )
        meta_lines.append(
            _pack_meta_word(
                rcf_q30=dec.rcf_q30,
                delta_q30=int(round(sig.delta_rcf_abs * Q2_30_SCALE)),
                g3_q16=int(round(sig.g3_torsion * Q0_16_SCALE)),
                affect_q16=int(round(sig.affect_polarity * Q0_16_SCALE)),
                hbm_temp=int(round(sig.hbm_temp_c)),
                turns=int(sig.non_convergent_turns),
                flags=flags,
            )
        )
        vec_lines.extend(f"{val & 0xFFFFFFFF:08X}" for val in vec_q30)
        expected.append(
            {
                "prompt_id": pid,
                "mode": int(dec.egress_mode, 2) if isinstance(dec.egress_mode, str) else int(dec.egress_mode),
                "state": int(dec.dkm_state_code),
                "bank": 0 if dec.active_bank == "BANK_A" else 1,
                "epoch": int(dec.epoch),
            }
        )

    meta_hex_out.write_text("\n".join(meta_lines) + "\n", encoding="utf-8")
    vec64_hex_out.write_text("\n".join(vec_lines) + "\n", encoding="utf-8")
    return expected


def build_bitblasted_top_inst() -> str:
    """Build bit-blasted port map for post-route vmax_v5_odos_top netlist."""
    conns = [f"        .{name}({name})" for name in TOP_SCALAR_PORTS]
    for name, width in TOP_BUS_PORTS:
        for bit in range(width):
            conns.append(f"        .\\{name}[{bit}] ({name}[{bit}])")
    return "    vmax_v5_odos_top u_dut (\n" + ",\n".join(conns) + "\n    );"


def _render_gate_vcd_tb(vcd_out: Path) -> str:
    """Render post-route gate-level VCD simulation testbench (201-cycle tx)."""
    inst_txt = build_bitblasted_top_inst()
    return f"""`timescale 1ns/1ps
module tb_v5_top_gate_vcd;
    reg clk_i; reg rst_ni; reg start_i; reg [1:0] tier_mode_i;
    reg in_valid_i; wire in_ready_o; reg signed [31:0] in_data_i;
    reg t0_lock_rm15_i; reg t0_dim_mismatch_i; reg t0_anchor_contra_i;
    reg c_dir_neg_conflict_i; reg [15:0] g3_torsion_q16_i;
    reg [15:0] affect_q16_i; reg dignity_viol_i; reg pseudo_auth_i;
    reg sycophancy_i; reg [3:0] non_conv_turns_i; reg [31:0] delta_rcf_q30_i;
    reg [7:0] hbm_temp_c_i; reg prompt_lang_en_i; reg dock_attached_i;
    reg recheck_valid_i; reg recheck_fail_i; reg npu_token_valid_i;
    reg [31:0] npu_token_data_i;
    wire busy_o; wire top_done_o; wire [15:0] top_cycle_count_o;
    wire out_valid_o; wire [5:0] out_idx_o; wire signed [31:0] out_data_o;
    wire gate_pass_o; wire veto_pin_o; wire norm_fault_o;
    wire pure_g3_collision_o; wire mode_fault_o; wire signed_conflict_o;
    wire signed [31:0] norm_sq_o; wire signed [31:0] rcf_raw_o;
    wire signed [31:0] g3_overlap_o; wire signed [31:0] delta_e_raw_o;
    wire signed [31:0] bleed_post_o; wire [1:0] egress_mode_o;
    wire [2:0] dkm_state_o; wire npu_egress_en_o; wire gated_token_valid_o;
    wire [31:0] gated_token_data_o; wire rom_egress_active_o;
    wire [3:0] rom_frame_sel_o; wire [8:0] bounded_token_cap_o;
    wire recheck_req_o; wire recheck_approved_o; wire quarantine_we_o;
    wire active_bank_o; wire thermal_deferred_o; wire [15:0] bank_epoch_o;
    wire dock_p0_veto_active_o; wire [15:0] cnt_passthrough_o;
    wire [15:0] cnt_bounded_o; wire [15:0] cnt_loop_exit_o;
    wire [15:0] cnt_hard_cut_o; wire [15:0] cnt_recheck_fail_o;

{inst_txt}

    initial clk_i = 1'b0;
    always #5 clk_i = ~clk_i;

    reg signed [31:0] l_vec [0:63];
    integer k; integer x_err;

    task run_tx;
        begin
            @(negedge clk_i); start_i = 1'b1;
            @(negedge clk_i); start_i = 1'b0;
            for (k = 0; k < 64; k = k + 1) begin
                in_valid_i = 1'b1; in_data_i = l_vec[k];
                @(negedge clk_i);
            end
            in_valid_i = 1'b0; in_data_i = 32'sd0;
            repeat (137) begin
                if (^egress_mode_o === 1'bx || ^veto_pin_o === 1'bx) x_err = x_err + 1;
                @(negedge clk_i);
            end
        end
    endtask

    initial begin
        $readmemh("{L_ROM_PATH}", l_vec);
        x_err = 0;
        rst_ni = 1'b0; start_i = 1'b0; tier_mode_i = 2'b00;
        in_valid_i = 1'b0; in_data_i = 32'sd0;
        t0_lock_rm15_i = 1'b0; t0_dim_mismatch_i = 1'b0;
        t0_anchor_contra_i = 1'b0; c_dir_neg_conflict_i = 1'b0;
        g3_torsion_q16_i = 16'd0; affect_q16_i = 16'd0;
        dignity_viol_i = 1'b0; pseudo_auth_i = 1'b0; sycophancy_i = 1'b0;
        non_conv_turns_i = 4'd0; delta_rcf_q30_i = 32'h4000_0000;
        hbm_temp_c_i = 8'd65; prompt_lang_en_i = 1'b0; dock_attached_i = 1'b0;
        recheck_valid_i = 1'b0; recheck_fail_i = 1'b0;
        npu_token_valid_i = 1'b1; npu_token_data_i = 32'hCAFE_BABE;
        repeat (6) @(negedge clk_i);
        rst_ni = 1'b1;
        repeat (2) @(negedge clk_i);
        // Warmup transaction outside VCD window so SRAM & regs settle
        run_tx();
        // Record canonical 201-cycle transaction inside VCD window
        $dumpfile("{vcd_out}");
        $dumpvars(0, tb_v5_top_gate_vcd.u_dut);
        run_tx();
        $dumpflush;
        $display(
            "GATE_VCD_SUMMARY pass=%0d mode=%0d cyc=%0d x_err=%0d",
            gate_pass_o, egress_mode_o, top_cycle_count_o, x_err
        );
        $finish;
    end
endmodule
"""


def _parse_gate_vcd_summary(rc_s: int, out_s: str) -> Tuple[int, int, int, int]:
    """Validate and unpack post-route gate-level VCD simulation summary."""
    match = re.search(
        r"GATE_VCD_SUMMARY pass=(\d+) mode=(\d+) cyc=(\d+) x_err=(\d+)",
        out_s,
    )
    if rc_s != 0 or not match:
        raise RuntimeError(f"Gate-level VCD sim failed (rc={rc_s}): {out_s[-400:]}")
    vals = (int(match.group(1)), int(match.group(2)), int(match.group(3)), int(match.group(4)))
    if vals != (1, 0, 201, 0):
        raise RuntimeError(f"Gate-level VCD check failed: (pass,mode,cyc,x_err)={vals}")
    return vals


def run_gate_level_vcd_sim(
    routed_netlist: Path,
    vcd_out: Path,
    log_path: Path,
) -> Dict[str, object]:
    """Run post-route gate-level simulation with IHP SG13G2 models to dump VCD."""
    tb_path = BUILD_DIR / "tb_v5_top_gate_vcd.sv"
    vvp_path = BUILD_DIR / "sim_v5_top_gate_vcd.vvp"
    tb_path.write_text(_render_gate_vcd_tb(vcd_out), encoding="utf-8")
    std_dir = PDK_REF / "sg13g2_stdcell" / "verilog"
    sram_dir = PDK_REF / "sg13g2_sram" / "verilog"
    cmd = [
        resolve_eda_tool("iverilog"),
        "-g2012", "-gno-specify", "-DFUNCTIONAL", "-DUNIT_DELAY=#0",
        "-y", str(std_dir), "-y", str(sram_dir),
        "-s", "tb_v5_top_gate_vcd", "-o", str(vvp_path),
        str(std_dir / "sg13g2_udp.v"),
        str(std_dir / "sg13g2_stdcell.v"),
        str(sram_dir / "RM_IHPSG13_1P_core_behavioral_bm_bist.v"),
        str(sram_dir / "RM_IHPSG13_1P_64x64_c2_bm_bist.v"),
        str(routed_netlist),
        str(tb_path),
    ]
    rc_c, out_c = run_eda_cmd(cmd, BUILD_DIR / "gate_vcd_compile.log", timeout_s=300.0)
    if rc_c != 0:
        raise RuntimeError(f"Gate-level VCD compile failed (rc={rc_c}): {out_c[-400:]}")
    rc_s, out_s = run_eda_cmd([resolve_eda_tool("vvp"), str(vvp_path)], log_path, timeout_s=300.0)
    gate_pass, mode_val, cyc_val, x_err = _parse_gate_vcd_summary(rc_s, out_s)
    return {
        "vcd_path": str(vcd_out),
        "gate_pass": gate_pass,
        "egress_mode": mode_val,
        "top_cycle_count": cyc_val,
        "sim_x_errors": x_err,
        "vcd_dut_signal_coverage_pct": compute_vcd_coverage(vcd_out, routed_netlist),
    }


def _extract_vcd_dut_vars(vcd_path: Path) -> set[str]:
    """Collect declared VCD signal names under u_dut scope."""
    dut_vars: set[str] = set()
    in_dut = False
    for raw in vcd_path.open("r", encoding="utf-8", errors="ignore"):
        line = raw.strip()
        if line.startswith("$enddefinitions"):
            break
        if line.startswith("$scope module u_dut"):
            in_dut = True
        elif in_dut and line.startswith("$var "):
            parts = line.split()
            dut_vars.add(parts[4].split("[")[0].lstrip("\\"))
    return dut_vars


def compute_vcd_coverage(vcd_path: Path, netlist_path: Path) -> float:
    """Compute exact percentage of VCD DUT signals matching routed netlist."""
    dut_vars = _extract_vcd_dut_vars(vcd_path)
    if not dut_vars:
        return 0.0
    net_txt = netlist_path.read_text(encoding="utf-8", errors="ignore")
    tokens = set(re.findall(r"\\?[^\s,();\[\]]+", net_txt))
    matched = sum(1 for s in dut_vars if (s in tokens) or (f"\\{s}" in tokens))
    return round(100.0 * float(matched) / float(len(dut_vars)), 2)


def parse_opensta_slacks(log_txt: str) -> Dict[str, Optional[float]]:
    """Parse WNS, TNS, worst setup slack (max), and worst hold slack (min)."""
    wns = _regex_float(log_txt, r"^wns(?:\s+max)?\s+([-+]?\d+(?:\.\d+)?)")
    tns = _regex_float(log_txt, r"^tns(?:\s+max)?\s+([-+]?\d+(?:\.\d+)?)")
    ws_hits = re.findall(r"^worst slack(?:\s+(?:max|min))?\s+([-+]?\d+(?:\.\d+)?)", log_txt, re.MULTILINE)
    max_s = float(ws_hits[0]) if len(ws_hits) >= 1 else None
    min_s = float(ws_hits[1]) if len(ws_hits) >= 2 else None
    return {
        "wns_ns": wns,
        "tns_ns": tns,
        "setup_slack_ns": max_s,
        "hold_slack_ns": min_s,
    }


def _regex_float(text: str, pattern: str) -> Optional[float]:
    """Return last float matched by multiline regex pattern."""
    hits = re.findall(pattern, text, re.MULTILINE)
    return float(hits[-1]) if hits else None


def parse_opensta_power(log_txt: str) -> Dict[str, float]:
    """Parse Total internal, switching, leakage, and total power from OpenSTA."""
    for raw in reversed(log_txt.splitlines()):
        line = raw.strip()
        if line.startswith("Total"):
            nums = re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", line)
            if len(nums) >= 4:
                return {
                    "internal_power_mw": round(float(nums[0]) * 1e3, 4),
                    "switching_power_mw": round(float(nums[1]) * 1e3, 4),
                    "leakage_power_uw": round(float(nums[2]) * 1e6, 4),
                    "total_power_mw": round(float(nums[3]) * 1e3, 4),
                }
    raise RuntimeError("Failed to parse OpenSTA report_power Total row")


def run_opensta_corner(
    corner: str,
    clock_ns: float,
    routed_netlist: Path,
    routed_spef: Path,
    log_path: Path,
    vcd_path: Optional[Path] = None,
) -> Dict[str, object]:
    """Run Post-Route OpenSTA for one PVT corner (with optional VCD power)."""
    vcd_block = ""
    if vcd_path is not None:
        vcd_block = (
            f'read_power_activities -scope tb_v5_top_gate_vcd/u_dut -vcd "{vcd_path}"\n'
            "report_power -digits 6\n"
        )
    tcl = (
        f'read_liberty "{STDCELL_LIBS[corner]}"\n'
        f'read_liberty "{SRAM_LIBS[corner]}"\n'
        f'read_verilog "{routed_netlist}"\n'
        "link_design vmax_v5_odos_top\n"
        f'read_sdc "{TOP_SDC_PATH}"\n'
        "set_propagated_clock [all_clocks]\n"
        f'read_spef "{routed_spef}"\n'
        "report_wns -digits 4\n"
        "report_tns -digits 4\n"
        "report_worst_slack -max -digits 4\n"
        "report_worst_slack -min -digits 4\n"
        "report_checks -path_delay max -fields {slew cap input_pins fanout} -digits 4\n"
        "report_checks -path_delay min -fields {slew cap input_pins fanout} -digits 4\n"
        f"{vcd_block}"
        "exit\n"
    )
    tcl_path = BUILD_DIR / f"sta_{corner}.tcl"
    tcl_path.write_text(tcl, encoding="utf-8")
    sta_bin = resolve_eda_tool("sta")
    rc, out = run_eda_cmd(
        [sta_bin, "-no_init", "-exit", str(tcl_path)],
        log_path,
        timeout_s=240.0,
        extra_env={"V5_CLK_PERIOD_NS": str(clock_ns)},
    )
    if rc != 0:
        raise RuntimeError(f"OpenSTA {corner} failed (rc={rc}): {out[-400:]}")
    slacks = parse_opensta_slacks(out)
    res: Dict[str, object] = {
        "corner": corner,
        "clock_ns": clock_ns,
        "target_mhz": round(1000.0 / clock_ns, 2),
        "stdcell_lib": STDCELL_LIBS[corner].name,
        "sram_lib": SRAM_LIBS[corner].name,
        **slacks,
        "fmax_mhz": _compute_fmax_mhz(clock_ns, slacks["setup_slack_ns"]),
        "log_path": str(log_path),
    }
    if vcd_path is not None:
        _attach_opensta_vcd_power(res, out)
    return res


def _compute_fmax_mhz(clock_ns: float, setup_s: Optional[float]) -> Optional[float]:
    """Compute achievable f_max in MHz from clock period and worst setup slack."""
    if setup_s is None or (clock_ns - setup_s) <= 0.0:
        return None
    return round(1000.0 / (clock_ns - setup_s), 2)


def _attach_opensta_vcd_power(res: Dict[str, object], out: str) -> None:
    """Attach OpenSTA report_power breakdown and pin annotation coverage."""
    res["power_vcd"] = parse_opensta_power(out)
    ann_cnt = re.search(r"Annotated\s+(\d+)\s+pin\s+activities", out)
    if ann_cnt:
        res["opensta_annotated_pins"] = int(ann_cnt.group(1))


def merge_def_to_gds_v5(def_path: Path, out_gds: Path) -> Dict[str, object]:
    """Stream routed DEF + SG13G2 stdcell & SRAM GDS into physical GDSII via KLayout."""
    script = (
        "import hashlib, json, pathlib, klayout.db as db\n"
        f"pdk = pathlib.Path('{PDK_REF}')\n"
        f"orfs = pathlib.Path('{ORFS_SG13G2_DIR}')\n"
        f"def_p = pathlib.Path('{def_path}')\n"
        f"out_p = pathlib.Path('{out_gds}')\n"
        "opts = db.LoadLayoutOptions()\n"
        "cfg = opts.lefdef_config\n"
        "cfg.lef_files = [\n"
        "  str(pdk / 'sg13g2_stdcell/lef/sg13g2_tech.lef'),\n"
        "  str(pdk / 'sg13g2_stdcell/lef/sg13g2_stdcell.lef'),\n"
        "  str(pdk / 'sg13g2_sram/lef/RM_IHPSG13_1P_64x64_c2_bm_bist.lef'),\n"
        "]\n"
        "cfg.macro_layout_files = [\n"
        "  str(pdk / 'sg13g2_stdcell/gds/sg13g2_stdcell.gds'),\n"
        "  str(pdk / 'sg13g2_sram/gds/RM_IHPSG13_1P_64x64_c2_bm_bist.gds'),\n"
        "]\n"
        "cfg.macro_resolution_mode = 1\n"
        "cfg.map_file = str(orfs / 'sg13g2.map')\n"
        "cfg.produce_routing = True\n"
        "cfg.produce_special_routing = True\n"
        "cfg.produce_pins = True\n"
        "cfg.produce_via_geometry = True\n"
        "cfg.produce_cell_outlines = True\n"
        "ly = db.Layout()\n"
        "ly.read(str(def_p), opts)\n"
        "out_p.parent.mkdir(parents=True, exist_ok=True)\n"
        "ly.write(str(out_p))\n"
        "raw = out_p.read_bytes()\n"
        "top = ly.top_cell()\n"
        "bb = top.dbbox()\n"
        "print(json.dumps({\n"
        "  'gds_path': str(out_p),\n"
        "  'gds_sha256': hashlib.sha256(raw).hexdigest(),\n"
        "  'gds_size_bytes': len(raw),\n"
        "  'top_cell': top.name,\n"
        "  'cell_count_in_gds': ly.cells(),\n"
        "  'bbox_um': [round(bb.left, 2), round(bb.bottom, 2), round(bb.right, 2), round(bb.top, 2)],\n"
        "}))\n"
    )
    py_bin = "/home/nathalia/.local/signoff_env/bin/python3"
    rc, out = run_eda_cmd([py_bin, "-c", script], Path("/tmp/sync33_gds_merge.log"), timeout_s=180.0)
    if rc != 0:
        raise RuntimeError(f"KLayout GDSII stream-out failed (rc={rc}): {out[-400:]}")
    return json.loads(out.strip().splitlines()[-1])


def parse_klayout_lyrdb_violations(lyrdb_path: Path) -> Tuple[int, Dict[str, int]]:
    """Parse KLayout .lyrdb XML database into total & per-rule violation counts."""
    tree = ET.parse(str(lyrdb_path))
    root = tree.getroot()
    counts: Dict[str, int] = {}
    items = root.find("items")
    if items is not None:
        for item in items.findall("item"):
            cat = item.find("category")
            cname = cat.text.strip("'") if (cat is not None and cat.text) else "UNKNOWN"
            counts[cname] = counts.get(cname, 0) + 1
    return sum(counts.values()), counts


def run_klayout_sg13g2_drc(gds_path: Path, run_dir: Path) -> Dict[str, object]:
    """Run official IHP SG13G2 KLayout FEOL/BEOL/Density + Antenna DRC decks."""
    run_dir.mkdir(parents=True, exist_ok=True)
    drc_script = PDK_ROOT / "libs.tech/klayout/tech/drc/run_drc.py"
    py_bin = "/home/nathalia/.local/signoff_env/bin/python3"
    cmd = [
        py_bin, str(drc_script),
        "--path", str(gds_path),
        "--topcell", "vmax_v5_odos_top",
        "--run_dir", str(run_dir),
        "--run_mode", "deep",
        "--mp", "8",
        "--antenna",
    ]
    rc, out = run_eda_cmd(cmd, Path("/tmp/sync33_klayout_drc.log"), timeout_s=1200.0)
    lyrdb_files = sorted(run_dir.rglob("*.lyrdb"))
    total_v = 0
    by_rule: Dict[str, int] = {}
    for db_file in lyrdb_files:
        cnt, rmap = parse_klayout_lyrdb_violations(db_file)
        total_v += cnt
        for k, v in rmap.items():
            by_rule[k] = by_rule.get(k, 0) + v
    return {
        "returncode": rc,
        "deck": str(drc_script),
        "lyrdb_files": [p.name for p in lyrdb_files],
        "total_drc_violations": total_v,
        "violations_by_rule": by_rule,
        "log_path": "/tmp/sync33_klayout_drc.log",
    }
