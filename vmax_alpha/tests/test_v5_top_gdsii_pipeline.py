#!/usr/bin/env python3
"""
vmax_alpha/tests/test_v5_top_gdsii_pipeline.py

Deterministic unit tests for SYNC-33 v2 (V5.0-TOP-GDSII) physical signoff
pipeline orchestration, OpenSTA/Yosys parsers, LVS helper transforms, and
rtl_v5/ source isolation (0 GPU, 0 torch imports).

OP02-AST-clean: 0 semicolons, 0 tabs, flat functions (max McCabe CC <= 5).
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

from vmax_alpha.v5_top_gdsii_pipeline import (
    BROWSER_CRASH_GUARD_NOTE,
    REPO_ROOT,
    V5_TOP_TB,
    V5_TOP_V,
    _parse_yosys_stat,
    build_stage_specs,
)
from vmax_alpha.v5_top_lvs_helper import (
    _expand_verilog_conn_map,
    _strip_via_calls_from_top,
    _split_drc_categories,
)
from vmax_alpha.v5_top_signoff_helpers import (
    parse_opensta_power,
    parse_opensta_slacks,
)


class TestV5TopGdsiiPipeline(unittest.TestCase):
    """Validate SYNC-33 v2 stage ordering, parsers, and RTL hygiene."""

    def test_seven_stage_spec_ordering(self) -> None:
        specs = build_stage_specs(Path("/tmp/sync33_unit_dummy"))
        ids = [s.stage_id for s in specs]
        self.assertEqual(
            ids,
            [
                "00_preflight",
                "01_rtl_lint_cosim",
                "02_yosys_top_synth",
                "03_floorplan_place_cts",
                "04_route_spef",
                "05_postroute_sta_vcd_power",
                "06_drc_lvs_gds_seal",
            ],
        )

    def test_parse_opensta_slacks_and_power(self) -> None:
        sample = (
            "wns 0.0000\n"
            "tns 0.0000\n"
            "worst slack 0.8524\n"
            "worst slack 0.1995\n"
            "Total 1.240983e-02 6.295981e-03 8.149270e-06 1.871396e-02 100.0%\n"
        )
        sl = parse_opensta_slacks(sample)
        self.assertEqual(sl["wns_ns"], 0.0)
        self.assertEqual(sl["tns_ns"], 0.0)
        self.assertAlmostEqual(sl["setup_slack_ns"], 0.8524, places=4)
        self.assertAlmostEqual(sl["hold_slack_ns"], 0.1995, places=4)
        pw = parse_opensta_power(sample)
        self.assertAlmostEqual(pw["total_power_mw"], 18.7140, places=3)
        self.assertAlmostEqual(pw["leakage_power_uw"], 8.1493, places=3)

    def test_parse_yosys_stat_scientific_area(self) -> None:
        sample = (
            "Printing statistics.\n"
            "    30655 3.79E+05 cells\n"
            "        1 5.05E+04   RM_IHPSG13_1P_64x64_c2_bm_bist\n"
            "     1243 6.09E+04   sg13g2_dfrbpq_1\n"
            "   Chip area for module '\\vmax_v5_odos_top': 379185.496600\n"
        )
        st = _parse_yosys_stat(sample)
        self.assertEqual(st["total_cells"], 30655)
        self.assertEqual(st["sequential_ff_cells"], 1243)
        self.assertEqual(st["sram_macros"], 1)
        self.assertEqual(st["inferred_latches"], 0)
        self.assertAlmostEqual(st["chip_area_um2"], 379185.497, places=2)

    def test_lvs_verilog_bus_expander_and_drc_split(self) -> None:
        conns = _expand_verilog_conn_map(r".A_ADDR({n5, n4, n3}), .\VDD! (VDD)")
        self.assertEqual(conns["A_ADDR[2]"], "n5")
        self.assertEqual(conns["A_ADDR[0]"], "n3")
        self.assertEqual(conns["VDD"], "VDD")
        geom, dens = _split_drc_categories({"M2.b": 0, "Ant.b_Metal5": 0, "M2.j": 1})
        self.assertEqual(sum(geom.values()), 0)
        self.assertEqual(dens, {"M2.j": 1})

    def test_lvs_strip_via_and_fill_cell_stubs(self) -> None:
        body = (
            " clk_i rst_n_i\n"
            "X1 a b sg13g2_inv_1\n"
            "X2 vdd vdd VIA_M1_M2\n"
            "X3 n1 TM2_FILL_CELL\n"
            "X4 n2 Met2_M_FILL_CELL\n"
        )
        ports, cleaned = _strip_via_calls_from_top(body)
        self.assertEqual(ports, ["clk_i", "rst_n_i"])
        self.assertIn("sg13g2_inv_1", cleaned)
        self.assertNotIn("VIA_M1_M2", cleaned)
        self.assertNotIn("TM2_FILL_CELL", cleaned)
        self.assertNotIn("Met2_M_FILL_CELL", cleaned)

    def test_rtl_v5_top_hygiene_and_zero_torch(self) -> None:
        top_txt = V5_TOP_V.read_text(encoding="utf-8")
        tb_txt = V5_TOP_TB.read_text(encoding="utf-8")
        self.assertNotIn("\t", top_txt)
        self.assertNotIn("\t", tb_txt)
        self.assertIn("keep_hierarchy = 1", top_txt)
        self.assertIn("32'sh1D97F62B", top_txt)
        self.assertIn("1,000 lines", BROWSER_CRASH_GUARD_NOTE)
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys, vmax_alpha.v5_top_gdsii_pipeline; assert 'torch' not in sys.modules",
            ],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertTrue((REPO_ROOT / "rtl_v5" / "vmax_v5_odos_top.sdc").is_file())


if __name__ == "__main__":
    unittest.main()
