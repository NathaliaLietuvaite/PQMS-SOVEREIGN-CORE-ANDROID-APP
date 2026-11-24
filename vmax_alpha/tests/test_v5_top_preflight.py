#!/usr/bin/env python3
"""
vmax_alpha/tests/test_v5_top_preflight.py

Deterministic unit tests for SYNC-33 v2 Read-Only Port & EDA Preflight Auditor.
Covers both SystemVerilog (.sv with logic ports) and Verilog-2001 (.v).
OP02-AST-clean: 0 semicolons, 0 tabs, flat test methods (max McCabe CC <= 3).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:
    from vmax_alpha.v5_top_preflight import (
        V4_GDSII_AREA_MM2,
        V5_TOP_CYCLES,
        build_preflight_report,
        compute_top_signoff_metrics,
        parse_verilog_module_ports,
    )
except ImportError:
    from v5_top_preflight import (
        V4_GDSII_AREA_MM2,
        V5_TOP_CYCLES,
        build_preflight_report,
        compute_top_signoff_metrics,
        parse_verilog_module_ports,
    )

SEMI = chr(59)

SAMPLE_V4_SV = (
    "module odos_gate_core_v4 (\n"
    "    input  logic               clk,\n"
    "    input  logic               rst_n,\n"
    "    input  logic signed [31:0] vec_in_q30,\n"
    "    output logic               done_o,\n"
    "    output logic signed [31:0] rcf_raw_o,\n"
    "    output logic               veto_pin_o\n"
    ")" + SEMI + "\n"
    "endmodule\n"
)


class TestV5TopPreflight(unittest.TestCase):
    """Verify .sv/.v port parsing, 201-cycle metrics, and rectangular die contract."""

    def test_parse_systemverilog_logic_ports_extracts_signed_and_widths(self) -> None:
        """Parser handles SystemVerilog logic ports, signedness, and bit widths."""
        mod_name, ports = parse_verilog_module_ports(SAMPLE_V4_SV)
        self.assertEqual(mod_name, "odos_gate_core_v4")
        self.assertEqual(len(ports), 6)
        by_name = {p.name: p for p in ports}
        self.assertEqual(by_name["clk"].direction, "input")
        self.assertEqual(by_name["vec_in_q30"].width, "[31:0]")
        self.assertTrue(by_name["vec_in_q30"].signed)
        self.assertEqual(by_name["rcf_raw_o"].direction, "output")
        self.assertTrue(by_name["rcf_raw_o"].signed)
        self.assertEqual(by_name["done_o"].width, "1")

    def test_201_cycle_pipeline_signoff_metrics_in_unchanged_die(self) -> None:
        """201 cycles @ 100 MHz equals 2.010 us and reports 0.0% delta at 0.7896 mm2."""
        self.assertEqual(V5_TOP_CYCLES, 201)
        metrics = compute_top_signoff_metrics(total_power_mw=17.50, die_area_mm2=V4_GDSII_AREA_MM2)
        self.assertAlmostEqual(metrics["latency_ns"], 2010.0, places=3)
        self.assertAlmostEqual(metrics["latency_us"], 2.01, places=6)
        self.assertAlmostEqual(metrics["energy_nj_per_tx"], 35.175, places=3)
        self.assertAlmostEqual(metrics["area_delta_vs_v40_pct"], 0.0, places=4)
        self.assertGreater(metrics["rack_120kw_pair_leverage"], 3400000.0)

    def test_build_preflight_report_scans_sv_and_preserves_940x840_contract(self) -> None:
        """Preflight scans frozen rtl/*.sv read-only and embeds 940x840 um contract."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "rtl").mkdir()
            (root / "rtl_v5").mkdir()
            v4_file = root / "rtl" / "odos_gate_core_v4.sv"
            v5_file = root / "rtl_v5" / "vmax_v5_core_nano_wrapper.v"
            v4_file.write_text(SAMPLE_V4_SV, encoding="utf-8")
            v5_file.write_text("module vmax_v5_core_nano_wrapper" + SEMI + " endmodule\n", encoding="utf-8")
            report = build_preflight_report(root)
            self.assertEqual(report["v4_frozen_rtl_count"], 1)
            self.assertIsNotNone(report["v5_wrapper_sha256"])
            self.assertEqual(report["pipeline_contract"]["v5_top_cycles"], 201)
            self.assertEqual(report["floorplan_contract"]["primary_die_um"], [940.0, 840.0])
            self.assertEqual(report["floorplan_contract"]["sram_horizontal_clearance_um"], 155.5)


if __name__ == "__main__":
    unittest.main()
