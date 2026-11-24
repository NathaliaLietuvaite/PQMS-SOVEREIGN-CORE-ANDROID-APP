#!/usr/bin/env python3
"""
vmax_alpha/v5_top_preflight.py

PQMS / V-MAX-12-CORE-NANO (SYNC-33 v2 / V5.0-TOP-GDSII) — Read-Only Port & EDA
Preflight Auditor for the Combined V4.0 + V5.0 Top-Level IHP SG13G2 Macro.

Functions:
1. Parses exact SystemVerilog/Verilog (.sv and .v) module & port declarations
   of frozen V4.0 RTL (e.g., rtl/odos_gate_core_v4.sv) strictly read-only so
   rtl_v5/vmax_v5_odos_top.v binds cleanly via 1 fail-closed pipeline stage
   (200 -> 201 cycles = 2.010 us @ 100 MHz).
2. Verifies availability of local P&R and foundry signoff binaries (yosys,
   openroad, sta, klayout, netgen, magic, verilator, iverilog, vvp) without
   loading GPU weights.
3. Encodes the rectangular V4.0 SRAM-aware die contract (940.0 x 840.0 um
   primary / 940.0 x 860.0 um fallback) and computes 201-cycle signoff metrics.

OP02-AST-clean: 0 semicolons, 0 tabs, flat functions (max McCabe CC <= 6).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

V4_FROZEN_CYCLES = 200
PIPELINE_REG_STAGES = 1
V5_TOP_CYCLES = V4_FROZEN_CYCLES + PIPELINE_REG_STAGES
TARGET_CLOCK_MHZ = 100.0
TARGET_CLOCK_NS = 10.0
V4_GDSII_DIE_X_UM = 940.0
V4_GDSII_DIE_Y_UM = 840.0
V4_GDSII_AREA_MM2 = 0.7896
V4_GDSII_CORE_MM2 = 0.708
SRAM_MACRO_X_UM = 784.5
SRAM_MACRO_Y_UM = 64.4
FALLBACK_DIE_Y_UM = 860.0
RACK_POWER_W = 120000.0

REQUIRED_EDA_TOOLS: Tuple[str, ...] = (
    "yosys",
    "openroad",
    "sta",
    "klayout",
    "netgen",
    "verilator",
    "iverilog",
    "vvp",
)

OPTIONAL_EDA_TOOLS: Tuple[str, ...] = (
    "magic",
    "openlane",
    "librelane",
)

PORT_DECL_RE = re.compile(
    r"^\s*(input|output|inout)\s+"
    r"(?:(wire|reg|logic)\s+)?"
    r"(?:(signed)\s+)?"
    r"(?:(\[[^\]]+\])\s+)?"
    r"([A-Za-z_][A-Za-z0-9_]*)"
)


@dataclass(frozen=True)
class VerilogPort:
    """Single parsed Verilog/SystemVerilog port declaration (read-only)."""

    direction: str
    width: str
    signed: bool
    name: str

    def to_dict(self) -> Dict[str, object]:
        """Serialize port specification for preflight JSON report."""
        return {
            "direction": self.direction,
            "width": self.width,
            "signed": self.signed,
            "name": self.name,
        }


def sha256_file(path: Path) -> str:
    """Compute SHA-256 hex digest of an existing file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(65536)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _strip_line_comment(line: str) -> str:
    """Remove trailing // comment from one RTL line."""
    idx = line.find("//")
    return line[:idx] if idx >= 0 else line


def parse_verilog_module_ports(verilog_text: str) -> Tuple[Optional[str], List[VerilogPort]]:
    """Extract top module name and .v/.sv port declarations read-only."""
    mod_match = re.search(r"\bmodule\s+([A-Za-z_][A-Za-z0-9_]*)", verilog_text)
    module_name = mod_match.group(1) if mod_match is not None else None
    ports: List[VerilogPort] = []
    seen: Dict[str, bool] = {}
    for raw_line in verilog_text.splitlines():
        cleaned = _strip_line_comment(raw_line)
        hit = PORT_DECL_RE.match(cleaned)
        if hit is None:
            continue
        name = hit.group(5)
        if name in seen:
            continue
        seen[name] = True
        ports.append(
            VerilogPort(
                direction=hit.group(1),
                width=hit.group(4) if hit.group(4) is not None else "1",
                signed=hit.group(3) is not None,
                name=name,
            )
        )
    return module_name, ports


def probe_eda_toolchain(
    required: Tuple[str, ...] = REQUIRED_EDA_TOOLS,
    optional: Tuple[str, ...] = OPTIONAL_EDA_TOOLS,
) -> Dict[str, Dict[str, Optional[str]]]:
    """Locate required and optional EDA binaries via PATH lookup."""
    req_map = {tool: shutil.which(tool) for tool in required}
    opt_map = {tool: shutil.which(tool) for tool in optional}
    return {"required": req_map, "optional": opt_map}


def compute_top_signoff_metrics(
    total_power_mw: float,
    die_area_mm2: float,
    cycles_per_tx: int = V5_TOP_CYCLES,
    clock_ns: float = TARGET_CLOCK_NS,
) -> Dict[str, float]:
    """Compute exact latency (us), energy/tx (nJ), area delta, and 120 kW leverage."""
    latency_ns = float(cycles_per_tx) * float(clock_ns)
    latency_us = latency_ns / 1000.0
    energy_nj_per_tx = float(total_power_mw) * latency_us
    pair_power_w = (2.0 * float(total_power_mw)) / 1000.0
    rack_leverage = RACK_POWER_W / pair_power_w if pair_power_w > 0.0 else 0.0
    area_delta_pct = ((float(die_area_mm2) - V4_GDSII_AREA_MM2) / V4_GDSII_AREA_MM2) * 100.0
    return {
        "cycles_per_tx": float(cycles_per_tx),
        "latency_ns": round(latency_ns, 3),
        "latency_us": round(latency_us, 6),
        "total_power_mw": round(float(total_power_mw), 4),
        "energy_nj_per_tx": round(energy_nj_per_tx, 4),
        "die_area_mm2": round(float(die_area_mm2), 6),
        "area_delta_vs_v40_pct": round(area_delta_pct, 4),
        "rack_120kw_pair_leverage": round(rack_leverage, 1),
    }


def _find_v4_rtl_candidates(repo_root: Path) -> List[Path]:
    """Return sorted .sv and .v source paths under frozen rtl/ (read-only)."""
    rtl_dir = repo_root / "rtl"
    if not rtl_dir.is_dir():
        return []
    found = list(rtl_dir.rglob("*.sv")) + list(rtl_dir.rglob("*.v"))
    return sorted(set(found))


def build_preflight_report(repo_root: Path) -> Dict[str, object]:
    """Generate complete read-only SYNC-33 v2 preflight inventory."""
    root = Path(repo_root)
    v4_files = _find_v4_rtl_candidates(root)
    v4_modules: Dict[str, Dict[str, object]] = {}
    for vpath in v4_files:
        text = vpath.read_text(encoding="utf-8", errors="replace")
        mod_name, ports = parse_verilog_module_ports(text)
        rel = str(vpath.relative_to(root))
        v4_modules[rel] = {
            "module_name": mod_name,
            "sha256": sha256_file(vpath),
            "port_count": len(ports),
            "ports": [port.to_dict() for port in ports],
        }
    v5_wrapper = root / "rtl_v5" / "vmax_v5_core_nano_wrapper.v"
    v5_sha = sha256_file(v5_wrapper) if v5_wrapper.is_file() else None
    tools = probe_eda_toolchain()
    missing_req = [name for name, path in tools["required"].items() if path is None]
    return {
        "schema": "VMAX_V5_TOP_PREFLIGHT_V2",
        "repo_root": str(root),
        "pipeline_contract": {
            "v4_frozen_cycles": V4_FROZEN_CYCLES,
            "pipeline_register_stages": PIPELINE_REG_STAGES,
            "v5_top_cycles": V5_TOP_CYCLES,
            "target_clock_mhz": TARGET_CLOCK_MHZ,
            "latency_us": round((V5_TOP_CYCLES * TARGET_CLOCK_NS) / 1000.0, 6),
        },
        "floorplan_contract": {
            "primary_die_um": [V4_GDSII_DIE_X_UM, V4_GDSII_DIE_Y_UM],
            "primary_die_mm2": V4_GDSII_AREA_MM2,
            "fallback_die_um": [V4_GDSII_DIE_X_UM, FALLBACK_DIE_Y_UM],
            "fallback_die_mm2": round((V4_GDSII_DIE_X_UM * FALLBACK_DIE_Y_UM) / 1e6, 4),
            "sram_macro_um": [SRAM_MACRO_X_UM, SRAM_MACRO_Y_UM],
            "sram_horizontal_clearance_um": round(V4_GDSII_DIE_X_UM - SRAM_MACRO_X_UM, 1),
        },
        "v4_frozen_rtl_count": len(v4_files),
        "v4_frozen_modules": v4_modules,
        "v5_wrapper_sha256": v5_sha,
        "eda_toolchain": tools,
        "missing_required_tools": missing_req,
        "ready_for_pnr": len(missing_req) == 0 and v5_sha is not None and len(v4_files) > 0,
    }


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point for SYNC-33 v2 read-only preflight audit."""
    parser = argparse.ArgumentParser(
        description="V-MAX-12 SYNC-33 v2 Read-Only Port & EDA Preflight Auditor"
    )
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)
    report = build_preflight_report(Path(args.repo_root).resolve())
    serialized = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(serialized, encoding="utf-8", newline="\n")
    summary = {
        "v4_frozen_rtl_count": report["v4_frozen_rtl_count"],
        "v5_wrapper_present": report["v5_wrapper_sha256"] is not None,
        "missing_required_tools": report["missing_required_tools"],
        "ready_for_pnr": report["ready_for_pnr"],
    }
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
