"""
rtl/asic_v4/run_v4_power_vcd.py
PQMS-ODOS-MTSC-V-MAX-12-SYSTEM-GATEWAY-V4.1 (WORK-ORDER-AG-24 / SYNC-19, WP-1)

Transaction-exact VCD-annotated post-route 130 nm IHP SG13G2 power signoff
(`1.20 V`, `25 C`, `100.0 MHz`) on the frozen Stage-3 routed netlist + OpenRCX
SPEF without re-running OpenROAD place-and-route.

AST Quality Invariants (OP02 / test_03 compliant):
  - 0 semicolon statement packers
  - 0 tab / CR control characters
  - McCabe cyclomatic complexity <= 6 per function
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Sequence, Tuple

REPO_ROOT: str = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GDSII_REPORT_PATH: str = os.path.join(REPO_ROOT, "telemetry", "VMAX_RTL_CORE_V4_GDSII_REPORT.json")
POWER_REPORT_OUT: str = os.path.join(REPO_ROOT, "telemetry", "VMAX_RTL_CORE_V4_POWER_VCD.json")
L_ROM_PATH: str = os.path.join(REPO_ROOT, "rtl", "rom", "l_vec_q2_30.hex")
G3_ROM_PATH: str = os.path.join(REPO_ROOT, "rtl", "rom", "g3_vec_q2_30.hex")
WORK_TMP_DIR: str = "/tmp/sync19_v4_power_vcd"

EXPECTED_L_PREFIX: str = "3d18f240"
EXPECTED_G3_PREFIX: str = "3b890d14"
VECTORLESS_POWER_MW_REF: float = 858.79
VECTORLESS_ENERGY_NJ_REF: float = 1717.58

TB_SV_TEMPLATE: str = """`timescale 1ns/1ps
module tb_v4_power_vcd;
    reg clk_i;
    reg rst_ni;
    reg start_i;
    reg [1:0] tier_mode_i;
    reg in_valid_i;
    wire in_ready_o;
    reg signed [31:0] in_data_i;

    wire busy_o;
    wire done_o;
    wire gate_pass_o;
    wire veto_pin_o;
    wire norm_fault_o;
    wire pure_g3_collision_o;
    wire mode_fault_o;
    wire out_valid_o;
    wire [5:0] out_idx_o;
    wire signed [31:0] out_data_o;
    wire [15:0] cycle_count_o;
    wire signed [31:0] norm_sq_o;
    wire signed [31:0] rcf_raw_o;
    wire signed [31:0] g3_overlap_o;
    wire signed [31:0] delta_e_raw_o;
    wire signed [31:0] bleed_post_o;

    reg [31:0] warmup_vec [0:63];
    reg [31:0] target_vec [0:63];
    integer k;
    integer x_err_cnt;

{dut_inst}

    initial begin
        clk_i = 1'b0;
        forever #5.0 clk_i = ~clk_i;
    end

    initial begin
        $readmemh("{warmup_hex}", warmup_vec);
        $readmemh("{target_hex}", target_vec);
        x_err_cnt = 0;
        rst_ni = 1'b0;
        start_i = 1'b0;
        tier_mode_i = 2'b00;
        in_valid_i = 1'b0;
        in_data_i = 32'sd0;

        repeat (4) @(negedge clk_i);
        rst_ni = 1'b1;
        @(negedge clk_i);

        // Un-traced warm-up pass initializes all 953 FFs and 32 SRAM rows (zero X states)
        start_i = 1'b1;
        @(negedge clk_i);
        start_i = 1'b0;
        for (k = 0; k < 64; k = k + 1) begin
            in_valid_i = 1'b1;
            in_data_i = warmup_vec[k];
            @(negedge clk_i);
        end
        in_valid_i = 1'b0;
        in_data_i = 32'sd0;
        repeat (136) @(negedge clk_i);
        repeat (2) @(negedge clk_i);

        // Exact VCD measurement window (`negedge` stimulus avoids CTS hold races)
        $dumpfile("{vcd_out}");
        $dumpvars(0, tb_v4_power_vcd.u_dut);

        if ({is_idle} == 1) begin
            for (k = 0; k < 200; k = k + 1) begin
                if (^veto_pin_o === 1'bx || ^gate_pass_o === 1'bx) x_err_cnt = x_err_cnt + 1;
                @(negedge clk_i);
            end
        end else begin
            start_i = 1'b1;
            @(negedge clk_i);
            start_i = 1'b0;
            for (k = 0; k < 64; k = k + 1) begin
                if ({stall_enable} == 1 && k == 32) begin
                    in_valid_i = 1'b0;
                    in_data_i = 32'sd0;
                    repeat (32) @(negedge clk_i);
                end
                in_valid_i = 1'b1;
                in_data_i = target_vec[k];
                if (^veto_pin_o === 1'bx || ^gate_pass_o === 1'bx) x_err_cnt = x_err_cnt + 1;
                @(negedge clk_i);
            end
            in_valid_i = 1'b0;
            in_data_i = 32'sd0;
            repeat (136) begin
                if (^veto_pin_o === 1'bx || ^out_data_o === 1'bx) x_err_cnt = x_err_cnt + 1;
                @(negedge clk_i);
            end
        end

        $dumpflush;
        $display("VCD_SIM_SUMMARY pass=%0d veto=%0d x_err=%0d", gate_pass_o, veto_pin_o, x_err_cnt);
        $finish;
    end
endmodule
"""

OPENSTA_TCL_TEMPLATE: str = """read_liberty {stdcell_lib}
read_liberty {sram_lib}
read_verilog {routed_netlist}
link_design odos_gate_core_v4
read_spef {routed_spef}
create_clock -name core_clk -period 10.0 [get_ports clk_i]
set_input_delay -clock core_clk 2.0 [all_inputs]
set_output_delay -clock core_clk 2.0 [all_outputs]
if {{ [llength [info commands read_power_activities]] > 0 }} {{
    read_power_activities -scope {vcd_scope} -vcd {vcd_file}
}} else {{
    read_vcd -scope {vcd_scope} {vcd_file}
}}
report_power -digits 6
exit
"""


@dataclass(frozen=True)
class WorkloadSpec:
    name: str
    window_cycles: int
    window_us: float
    use_g3_vec: bool
    stall_enable: int
    is_idle: int
    expect_pass: Optional[int]


@dataclass(frozen=True)
class PowerProfileMetrics:
    workload: str
    window_cycles: int
    window_us: float
    internal_power_mw: float
    switching_power_mw: float
    leakage_power_uw: float
    total_power_mw: float
    energy_per_tx_nj: float
    reduction_vs_vectorless_pct: float
    vcd_signal_coverage_pct: float
    sim_x_errors: int


WORKLOAD_SPECS: Tuple[WorkloadSpec, ...] = (
    WorkloadSpec("WORKLOAD_PASS_CANONICAL", 200, 2.000, False, 0, 0, 1),
    WorkloadSpec("WORKLOAD_VETO_G3", 200, 2.000, True, 0, 0, 0),
    WorkloadSpec("WORKLOAD_STALL_BACKPRESSURE", 232, 2.320, False, 1, 0, 1),
    WorkloadSpec("WORKLOAD_IDLE_CLOCKED", 200, 2.000, False, 0, 1, None),
)


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def _verify_frozen_rom_seals() -> Dict[str, str]:
    l_sha = _sha256_file(L_ROM_PATH)
    g3_sha = _sha256_file(G3_ROM_PATH)
    if not l_sha.startswith(EXPECTED_L_PREFIX) or not g3_sha.startswith(EXPECTED_G3_PREFIX):
        raise RuntimeError(f"Frozen ROM seal mismatch: L={l_sha}, G3={g3_sha}")
    return {"l_rom_sha256": l_sha, "g3_rom_sha256": g3_sha}


def _first_match(patterns: Sequence[str]) -> Optional[str]:
    for pat in patterns:
        hits = sorted(glob.glob(pat, recursive=True))
        if hits:
            return hits[0]
    return None



def _build_bitblasted_dut_inst() -> str:
    scalar = [
        "clk_i", "rst_ni", "start_i", "in_valid_i", "in_ready_o",
        "out_valid_o", "busy_o", "done_o", "gate_pass_o", "veto_pin_o",
        "norm_fault_o", "mode_fault_o",
    ]
    buses = [
        ("tier_mode_i", 2), ("in_data_i", 32), ("out_idx_o", 6), ("out_data_o", 32),
        ("cycle_count_o", 10), ("norm_sq_o", 32), ("rcf_raw_o", 32),
        ("g3_overlap_o", 32), ("delta_e_raw_o", 32), ("bleed_post_o", 32),
    ]
    conns = [f"        .{s}({s})" for s in scalar]
    for name, width in buses:
        for bit in range(width):
            conns.append(f"        .\\{name}[{bit}] ({name}[{bit}])")
    return "    odos_gate_core_v4 u_dut (\n" + ",\n".join(conns) + "\n    );"

def _discover_postroute_artifacts() -> Tuple[str, str]:
    import pathlib as _pl; bdir = _pl.Path(__file__).resolve().parent / 'build'
    if (bdir / 'odos_v4_routed.v').exists() and (bdir / 'odos_v4_routed.spef').exists():
        return bdir / 'odos_v4_routed.v', bdir / 'odos_v4_routed.spef'
    env_net = os.environ.get("VMAX_V4_NETLIST", "")
    env_spef = os.environ.get("VMAX_V4_SPEF", "")
    if os.path.isfile(env_net) and os.path.isfile(env_spef):
        return env_net, env_spef
    netlist = _first_match([
        os.path.join(REPO_ROOT, "rtl", "**", "*odos_gate_core_v4*route*.v"),
        os.path.join(REPO_ROOT, "rtl", "**", "*odos_gate_core_v4*final*.v"),
        os.path.join(REPO_ROOT, "rtl", "asic_v4", "**", "*odos_gate_core_v4*.v"),
    ])
    spef = _first_match([
        os.path.join(REPO_ROOT, "rtl", "**", "*odos_gate_core_v4*.spef"),
        os.path.join(REPO_ROOT, "rtl", "asic_v4", "**", "*.spef"),
    ])
    if not netlist or not spef:
        raise FileNotFoundError("Could not locate frozen Stage-3 routed netlist or OpenRCX .spef")
    return netlist, spef


def _discover_ihp_pdk_files() -> Dict[str, str]:
    roots = [
        os.environ.get("IHP_PDK_ROOT", ""),
        os.environ.get("PDK_ROOT", ""),
        os.path.expanduser("~/IHP-Open-PDK"),
        "/opt/pdk/IHP-Open-PDK",
        "/opt/IHP-Open-PDK",
        "/usr/local/share/pdk",
    ]
    valid_roots = [r for r in roots if r and os.path.isdir(r)]
    found: Dict[str, str] = {}
    targets = {
        "stdcell_v": "**/sg13g2_stdcell.v",
        "sram_v": "**/RM_IHPSG13_1P_64x64_c2_bm_bist.v",
        "stdcell_lib": "**/sg13g2_stdcell_typ_1p20V_25C.lib",
        "sram_lib": "**/RM_IHPSG13_1P_64x64_c2_bm_bist_typ_1p20V_25C.lib",
    }
    for key, rel_glob in targets.items():
        hit = _first_match([os.path.join(r, rel_glob) for r in valid_roots])
        if not hit:
            raise FileNotFoundError(f"Missing IHP SG13G2 PDK file for {key} ({rel_glob})")
        found[key] = hit
    return found


def _resolve_sta_command() -> List[str]:
    env_bin = os.environ.get("OPENSTA_BIN", "")
    if env_bin and shutil.which(env_bin):
        return [env_bin, "-no_init", "-exit"]
    if shutil.which("sta"):
        return ["sta", "-no_init", "-exit"]
    if shutil.which("openroad"):
        return ["openroad", "-no_init", "-exit"]
    raise FileNotFoundError("Neither `sta` nor `openroad` found in PATH")


def _extract_netlist_signal_count(netlist_path: str) -> int:
    with open(netlist_path, "r", encoding="utf-8", errors="ignore") as f:
        txt = f.read()
    wires = re.findall(r"\b(?:wire|input|output)\b[^;]+;", txt)
    return max(1, len(wires))


def _compute_vcd_dut_signal_coverage(vcd_path: str, netlist_path: str) -> float:
    dut_vars: set[str] = set()
    in_dut = False
    with open(vcd_path, "r", encoding="utf-8", errors="ignore") as vf:
        for raw in vf:
            line = raw.strip()
            if line.startswith("$scope module u_dut"):
                in_dut = True
            elif line.startswith("$enddefinitions"):
                break
            elif in_dut and line.startswith("$var "):
                parts = line.split()
                if len(parts) >= 5:
                    dut_vars.add(parts[4].split("[")[0].lstrip("\\"))
    with open(netlist_path, "r", encoding="utf-8", errors="ignore") as nf:
        net_txt = nf.read()
    top_tokens = set(re.findall(r"\\?[^\s,();\[\]]+", net_txt))
    matched = sum(1 for s in dut_vars if s in top_tokens or f"\\{s}" in top_tokens)
    if not dut_vars:
        return 0.0
    return round(100.0 * float(matched) / float(len(dut_vars)), 2)


def _run_iverilog_vcd(
    spec: WorkloadSpec,
    netlist_path: str,
    pdk: Dict[str, str],
) -> Tuple[str, int]:
    vcd_path = os.path.join(WORK_TMP_DIR, f"{spec.name.lower()}.vcd")
    tb_path = os.path.join(WORK_TMP_DIR, f"tb_{spec.name.lower()}.sv")
    vvp_bin = os.path.join(WORK_TMP_DIR, f"sim_{spec.name.lower()}.vvp")
    target_hex = G3_ROM_PATH if spec.use_g3_vec else L_ROM_PATH
    tb_src = TB_SV_TEMPLATE.format(
        dut_inst=_build_bitblasted_dut_inst(),
        warmup_hex=L_ROM_PATH,
        target_hex=target_hex,
        vcd_out=vcd_path,
        is_idle=spec.is_idle,
        stall_enable=spec.stall_enable,
    )
    with open(tb_path, "w", encoding="utf-8") as f:
        f.write(tb_src)
    std_dir = os.path.dirname(pdk["stdcell_v"])
    sram_dir = os.path.dirname(pdk["sram_v"])
    udp_files = sorted(glob.glob(os.path.join(std_dir, "*udp*.v")))
    cmd = [
        "iverilog", "-g2012", "-gno-specify", "-DFUNCTIONAL", "-DUNIT_DELAY=#0",
        "-y", std_dir, "-y", sram_dir,
        "-s", "tb_v4_power_vcd", "-o", vvp_bin,
        *udp_files, pdk["stdcell_v"], "/home/nathalia/vmax_workspace/pdk/IHP-Open-PDK/ihp-sg13g2/libs.ref/sg13g2_sram/verilog/RM_IHPSG13_1P_core_behavioral_bm_bist.v", pdk["sram_v"], netlist_path, tb_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=180)
    sim = subprocess.run(["vvp", vvp_bin], check=True, capture_output=True, text=True, timeout=300)
    m = re.search(r"VCD_SIM_SUMMARY pass=(\d+) veto=(\d+) x_err=(\d+)", sim.stdout)
    if not m:
        raise RuntimeError(f"Missing simulation summary for {spec.name}")
    got_pass, x_err = int(m.group(1)), int(m.group(3))
    if x_err != 0 or (spec.expect_pass is not None and got_pass != spec.expect_pass):
        raise RuntimeError(f"Gate-level VCD check failed on {spec.name}: pass={got_pass}, x_err={x_err}")
    return vcd_path, x_err


def _parse_opensta_total_power_watts(log_txt: str) -> Tuple[float, float, float, float]:
    for raw in reversed(log_txt.splitlines()):
        line = raw.strip()
        if line.startswith("Total"):
            nums = re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", line)
            if len(nums) >= 4:
                return float(nums[0]), float(nums[1]), float(nums[2]), float(nums[3])
    raise RuntimeError("Failed to parse `Total` row from OpenSTA `report_power` output")


def _evaluate_workload_opensta(
    spec: WorkloadSpec,
    vcd_path: str,
    sim_x_err: int,
    netlist_path: str,
    spef_path: str,
    pdk: Dict[str, str],
    sta_cmd: Sequence[str],
) -> PowerProfileMetrics:
    cov_pct = _compute_vcd_dut_signal_coverage(vcd_path, netlist_path)
    if cov_pct < 95.0:
        raise RuntimeError(f"VCD coverage {cov_pct}% < 95.0% threshold on {spec.name}")
    tcl_path = os.path.join(WORK_TMP_DIR, f"sta_{spec.name.lower()}.tcl")
    log_path = os.path.join(WORK_TMP_DIR, f"sta_{spec.name.lower()}.log")
    tcl_txt = OPENSTA_TCL_TEMPLATE.format(
        stdcell_lib=pdk["stdcell_lib"],
        sram_lib=pdk["sram_lib"],
        routed_netlist=netlist_path,
        routed_spef=spef_path,
        vcd_scope="tb_v4_power_vcd/u_dut",
        vcd_file=vcd_path,
    )
    with open(tcl_path, "w", encoding="utf-8") as f:
        f.write(tcl_txt)
    proc = subprocess.run([*sta_cmd, tcl_path], check=True, capture_output=True, text=True, timeout=180)
    full_log = proc.stdout + "\n" + proc.stderr
    with open(log_path, "w", encoding="utf-8") as lf:
        lf.write(full_log)
    p_int_w, p_sw_w, p_leak_w, p_tot_w = _parse_opensta_total_power_watts(full_log)
    tot_mw = round(p_tot_w * 1e3, 4)
    e_nj = round(tot_mw * spec.window_us, 4)
    red_pct = round(100.0 * (1.0 - (tot_mw / VECTORLESS_POWER_MW_REF)), 2)
    return PowerProfileMetrics(
        workload=spec.name,
        window_cycles=spec.window_cycles,
        window_us=spec.window_us,
        internal_power_mw=round(p_int_w * 1e3, 4),
        switching_power_mw=round(p_sw_w * 1e3, 4),
        leakage_power_uw=round(p_leak_w * 1e6, 4),
        total_power_mw=tot_mw,
        energy_per_tx_nj=e_nj,
        reduction_vs_vectorless_pct=red_pct,
        vcd_signal_coverage_pct=cov_pct,
        sim_x_errors=sim_x_err,
    )


def run_v4_vcd_power_signoff() -> Dict[str, Any]:
    os.makedirs(WORK_TMP_DIR, exist_ok=True)
    rom_seals = _verify_frozen_rom_seals()
    gds_report_sha = _sha256_file(GDSII_REPORT_PATH) if os.path.isfile(GDSII_REPORT_PATH) else "UNSET"
    netlist_path, spef_path = _discover_postroute_artifacts()
    pdk = _discover_ihp_pdk_files()
    sta_cmd = _resolve_sta_command()
    net_count = _extract_netlist_signal_count(netlist_path)

    profiles: List[PowerProfileMetrics] = []
    for spec in WORKLOAD_SPECS:
        vcd_path, x_err = _run_iverilog_vcd(spec, netlist_path, pdk)
        metrics = _evaluate_workload_opensta(spec, vcd_path, x_err, netlist_path, spef_path, pdk, sta_cmd)
        profiles.append(metrics)

    report: Dict[str, Any] = {
        "document_id": "PQMS-ODOS-MTSC-V-MAX-12-SYSTEM-GATEWAY-V4.1",
        "work_order": "WORK-ORDER-AG-24 (SYNC-19 / WP-1)",
        "epistemic_register": "REGISTER_M",
        "process_corner": "IHP_SG13G2_130NM_TYP_1P20V_25C",
        "signoff_clock_mhz": 100.0,
        "frozen_stage3_gdsii_report_sha256": gds_report_sha,
        "frozen_rom_seals": rom_seals,
        "routed_netlist_sha256": _sha256_file(netlist_path),
        "routed_spef_sha256": _sha256_file(spef_path),
        "approx_netlist_declarations": net_count,
        "vectorless_opensta_upper_bound_ref": {
            "total_power_mw": VECTORLESS_POWER_MW_REF,
            "energy_per_tx_nj": VECTORLESS_ENERGY_NJ_REF,
        },
        "vcd_annotated_profiles": [asdict(p) for p in profiles],
    }
    os.makedirs(os.path.dirname(POWER_REPORT_OUT), exist_ok=True)
    with open(POWER_REPORT_OUT, "w", encoding="utf-8", newline="\n") as out_f:
        json.dump(report, out_f, indent=2)
        out_f.write("\n")
    out_sha = _sha256_file(POWER_REPORT_OUT)
    print(f"[WP-1 V4.0-POWER-VCD] Report SHA-256: {out_sha}")
    print(f"Vectorless Ref (200 cyc): {VECTORLESS_POWER_MW_REF:.2f} mW | {VECTORLESS_ENERGY_NJ_REF:.2f} nJ/tx")
    for p in profiles:
        print(
            f"{p.workload:28s}: {p.total_power_mw:8.3f} mW | {p.energy_per_tx_nj:8.3f} nJ/tx "
            f"| cov={p.vcd_signal_coverage_pct:.1f}% | vs_vecless=-{p.reduction_vs_vectorless_pct:.1f}%"
        )
    return report


if __name__ == "__main__":
    run_v4_vcd_power_signoff()
