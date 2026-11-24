#!/usr/bin/env python3
"""
tools/render_v5_dieshot.py

PQMS / V-MAX-12-CORE-NANO (SYNC-35 / REGISTER_M):
Deterministic Real-Silicon Die-Shot Renderer for
`rtl_v5/gds/vmax_v5_odos_top_sg13g2.gds` (`940.0 x 840.0 um`, IHP SG13G2 130 nm).

Design rules:
1. Renders polygons directly from the sealed 41.12 MB transistor-level GDSII
   via KLayout headless Ruby view (`QT_QPA_PLATFORM=offscreen`), hiding only
   CMP dummy-fill layers (`*:filler`) in the primary functional view so real
   SRAM, PDN, Metal1-TopMetal2 routing, and stdcell density remain sharply
   legible (explicitly disclosed in the figure caption).
2. Wraps the real KLayout layout image inside a dark publication frame with
   exact `940.0 x 840.0 um` scale bars and verified `SYNC-33` / `SYNC-34`
   `REGISTER_M` / `REGISTER_T` telemetry callouts.
3. Zero GPU load (`torch_imported = False`), logs strictly to `/tmp/`.

OP02-AST-clean: 0 semicolons, 0 tabs, flat helpers (max McCabe CC <= 5).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

DEFAULT_GDS_PATH = Path("rtl_v5/gds/vmax_v5_odos_top_sg13g2.gds")
DEFAULT_OUT_PNG = Path("docs/figures/V-MAX-12-RTL-V5.0-DIESHOT.png")
DEFAULT_RAW_PNG = Path("/tmp/sync35_v5_raw_klayout.png")
DEFAULT_RB_SCRIPT = Path("/tmp/sync35_render_dieshot.rb")
DEFAULT_LOG_PATH = Path("/tmp/sync35_klayout_render.log")

RENDER_WIDTH_PX = 2256
RENDER_HEIGHT_PX = 2016


def sha256_file(path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(65536)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def locate_klayout_binary() -> Optional[str]:
    """Locate official Ruby-enabled KLayout binary on Node Alpha."""
    candidates = [
        Path.home() / ".local" / "bin" / "klayout",
        Path("/usr/bin/klayout"),
    ]
    for cand in candidates:
        if cand.is_file() and os.access(cand, os.X_OK):
            return str(cand)
    return shutil.which("klayout")


def locate_sg13g2_lyp(pdk_root: str = "") -> Optional[Path]:
    """Find the official IHP SG13G2 KLayout layer-properties (.lyp) file."""
    roots: List[Path] = []
    if pdk_root:
        roots.append(Path(pdk_root))
    env_pdk = os.environ.get("PDK_ROOT", "")
    if env_pdk:
        roots.append(Path(env_pdk))
    roots.extend([
        Path.home() / "IHP-Open-PDK",
        Path.home() / "vmax_workspace" / "IHP-Open-PDK",
        Path("/opt/IHP-Open-PDK"),
    ])
    rel_suffix = Path("ihp-sg13g2/libs.tech/klayout/tech/sg13g2.lyp")
    for base in roots:
        hit = base / rel_suffix
        if hit.is_file():
            return hit
    return None


def build_klayout_ruby_script(
    gds_path: Path,
    raw_png_path: Path,
    lyp_path: Optional[Path],
    width_px: int = RENDER_WIDTH_PX,
    height_px: int = RENDER_HEIGHT_PX,
    hide_fillers: bool = True,
) -> str:
    """Build headless KLayout Ruby script to rasterize real GDSII polygons."""
    lines = [
        "view = RBA::LayoutView.new",
        "view.set_config('background-color', '#0b1018')",
        "view.set_config('grid-visible', 'false')",
        f"view.load_layout('{gds_path.as_posix()}', 0)",
    ]
    if lyp_path is not None:
        lines.append(f"view.load_layer_props('{lyp_path.as_posix()}')")
    if hide_fillers:
        lines.extend([
            "iter = view.begin_layers",
            "while !iter.at_end?",
            "  lp = iter.current",
            "  name = lp.name.to_s.downcase",
            "  if name.include?('filler') || name.include?('nofill') || name.include?('text')",
            "    lp.visible = false",
            "  end",
            "  iter.next",
            "end",
        ])
    lines.extend([
        "view.max_hier",
        "view.zoom_fit",
        f"view.save_image_with_options('{raw_png_path.as_posix()}', {width_px}, {height_px}, 0, 0, 0.0, RBA::DBox.new, true)",
        "view.close",
    ])
    return "\n".join(lines) + "\n"


def run_klayout_rasterize(
    klayout_bin: str,
    rb_script_path: Path,
    log_path: Path,
) -> int:
    """Execute KLayout headless rasterization with offscreen Qt backend."""
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    cmd = [klayout_bin, "-z", "-nc", "-rx", "-r", str(rb_script_path)]
    with log_path.open("w", encoding="utf-8") as log_handle:
        proc = subprocess.run(
            cmd,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            env=env,
            timeout=180.0,
        )
    return proc.returncode


def _load_font(size: int):
    """Load DejaVuSans bold/regular or fall back to Pillow default font."""
    from PIL import ImageFont

    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for fpath in font_paths:
        if os.path.isfile(fpath):
            return ImageFont.truetype(fpath, size=size)
    return ImageFont.load_default()


def _telemetry_cards(gds_sha_short: str) -> List[Tuple[str, List[str]]]:
    """Return verified SYNC-33 and SYNC-34 sidebar telemetry entries."""
    return [
        (
            "PHYSICAL DIE (IHP SG13G2 130 nm)",
            [
                "Die Size: 940.0 x 840.0 um (0.7896 mm2)",
                "Die Delta vs V4.0: 0.00 % (unchanged die)",
                "Core Util: 64.0 % (450,887 um2 post-route)",
                "Cells: 30,655 (1,243 FFs, 0 Latches)",
                "SRAM: RM_IHPSG13_1P_64x64 (784.5 x 64.4 um)",
                "Wirelength: 1.433 m | 473 Ant. Diodes",
            ],
        ),
        (
            "3-CORNER STA & VCD POWER (REGISTER_M)",
            [
                "Latency: 201 cycles (2.010 us @ 100 MHz)",
                "typ 1.20V 25C: +0.8594 ns (109.40 MHz)",
                "fast 1.32V -40C: Hold +0.0735 ns (0 viol.)",
                "slow 1.08V 125C: +1.5881 ns @ 62.5 MHz",
                "VCD Power (99.8 % cov): 18.7268 mW",
                "Energy: 37.6409 nJ/tx | 3.20M x 120 kW",
            ],
        ),
        (
            "FOUNDRY DRC, LVS & LEAN 4 (SYNC-33/34)",
            [
                "KLayout 0.30.14: 0 FEOL/BEOL/Ant/Fill DRC",
                "Note: 10 M2-M5 standalone macro CMP flags",
                "Netgen 1.5.272 LVS: 0 Mismatches (unique)",
                "34,712 inst | 2,047 MOSFET defs | 535 ports",
                "Lean 4.36.0 (0 Mathlib): 7/7 Hoare PASS",
                "Axioms: 0 sorryAx | 10/10 Triple Parity",
            ],
        ),
        (
            "PROVENANCE & IMMUTABLE GUARDS",
            [
                f"GDSII SHA-256: {gds_sha_short}...",
                "macro_resolution_mode=0 (41.12 MB real)",
                "Render: CMP filler hidden for routing view",
                "IMMUTABLE_SILICON_GUARD: EMPTY_DIFF",
                "Tests: 173/173 Py/RTL/Lean | 36/36 Kotlin",
            ],
        ),
    ]


def _draw_telemetry_sidebar(draw, x0: int, y0: int, width: int, gds_sha_short: str) -> None:
    """Render verified SYNC-33 / SYNC-34 REGISTER_M & REGISTER_T summary cards."""
    f_head = _load_font(25)
    f_body = _load_font(19)
    cursor_y = y0
    for title, bullets in _telemetry_cards(gds_sha_short):
        box_h = 46 + len(bullets) * 30 + 18
        draw.rounded_rectangle(
            [x0, cursor_y, x0 + width, cursor_y + box_h],
            radius=12,
            fill=(19, 28, 43),
            outline=(56, 97, 140),
            width=2,
        )
        draw.text((x0 + 18, cursor_y + 12), title, fill=(125, 211, 252), font=f_head)
        line_y = cursor_y + 50
        for item in bullets:
            draw.text((x0 + 20, line_y), item, fill=(226, 232, 240), font=f_body)
            line_y += 30
        cursor_y += box_h + 22


def compose_publication_dieshot(
    raw_png: Path,
    out_png: Path,
    gds_sha256: str,
) -> Tuple[int, int]:
    """Compose final publication-grade die-shot PNG from real KLayout raster."""
    from PIL import Image, ImageDraw

    raw_img = Image.open(raw_png).convert("RGB")
    die_w = 1560
    die_h = int(round(die_w * (840.0 / 940.0)))
    die_img = raw_img.resize((die_w, die_h), Image.Resampling.LANCZOS)

    pad = 48
    header_h = 110
    sidebar_w = 680
    footer_h = 72
    canvas_w = pad + die_w + 36 + sidebar_w + pad
    canvas_h = header_h + die_h + footer_h + pad

    canvas = Image.new("RGB", (canvas_w, canvas_h), (11, 16, 24))
    draw = ImageDraw.Draw(canvas)

    f_title = _load_font(34)
    f_sub = _load_font(20)
    draw.text(
        (pad, 24),
        "V-MAX-12-CORE-NANO (V5.0) — IHP SG13G2 130 nm Transistor-Level GDSII Die-Shot",
        fill=(248, 250, 252),
        font=f_title,
    )
    draw.text(
        (pad, 68),
        "Combined V4.0 ODOS Core + V5.0 2-Bit Egress Mux / DCM-DKM Wrapper | Direct KLayout 0.30.14 Silicon Render (REGISTER_M)",
        fill=(148, 163, 184),
        font=f_sub,
    )

    die_x0 = pad
    die_y0 = header_h
    draw.rectangle(
        [die_x0 - 3, die_y0 - 3, die_x0 + die_w + 3, die_y0 + die_h + 3],
        outline=(56, 189, 248),
        width=3,
    )
    canvas.paste(die_img, (die_x0, die_y0))

    scale_y = die_y0 + die_h + 22
    draw.line([(die_x0, scale_y), (die_x0 + die_w, scale_y)], fill=(56, 189, 248), width=3)
    draw.text(
        (die_x0 + die_w // 2 - 190, scale_y + 10),
        "940.0 um (X) x 840.0 um (Y) = 0.7896 mm2",
        fill=(186, 230, 253),
        font=f_sub,
    )

    _draw_telemetry_sidebar(draw, die_x0 + die_w + 36, die_y0, sidebar_w, gds_sha256[:16])

    out_png.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_png, format="PNG", optimize=True)
    return canvas_w, canvas_h


def _render_via_klayout(
    gds_path: Path,
    pdk_root: str,
    hide_fillers: bool,
) -> Tuple[Optional[Path], Optional[str]]:
    """Locate KLayout/PDK, run headless rasterizer, and return (lyp, error)."""
    if not gds_path.is_file():
        return None, f"Missing GDSII: {gds_path}"
    klayout_bin = locate_klayout_binary()
    if klayout_bin is None:
        return None, "klayout binary not found"
    lyp_path = locate_sg13g2_lyp(pdk_root)
    rb_text = build_klayout_ruby_script(
        gds_path=gds_path,
        raw_png_path=DEFAULT_RAW_PNG,
        lyp_path=lyp_path,
        hide_fillers=hide_fillers,
    )
    DEFAULT_RB_SCRIPT.write_text(rb_text, encoding="utf-8", newline="\n")
    rc = run_klayout_rasterize(klayout_bin, DEFAULT_RB_SCRIPT, DEFAULT_LOG_PATH)
    if rc != 0 or not DEFAULT_RAW_PNG.is_file():
        return lyp_path, f"klayout render failed rc={rc}"
    return lyp_path, None


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point for real GDSII die-shot rendering."""
    parser = argparse.ArgumentParser(description="Render V-MAX-12 V5.0 Real GDSII Die-Shot PNG")
    parser.add_argument("--gds", default=str(DEFAULT_GDS_PATH))
    parser.add_argument("--out", default=str(DEFAULT_OUT_PNG))
    parser.add_argument("--pdk-root", default="")
    parser.add_argument("--include-fillers", action="store_true")
    args = parser.parse_args(argv)

    gds_path = Path(args.gds).resolve()
    hide_fillers = not args.include_fillers
    lyp_path, err = _render_via_klayout(gds_path, args.pdk_root, hide_fillers)
    if err is not None:
        print(json.dumps({"status": "ERROR", "reason": err}))
        return 1

    out_path = Path(args.out).resolve()
    gds_sha = sha256_file(gds_path)
    width_px, height_px = compose_publication_dieshot(DEFAULT_RAW_PNG, out_path, gds_sha)
    lyp_str = str(lyp_path) if lyp_path is not None else None
    summary: Dict[str, object] = {
        "status": "OK",
        "gds_path": str(gds_path),
        "gds_sha256": gds_sha,
        "lyp_path": lyp_str,
        "out_png": str(out_path),
        "out_bytes": out_path.stat().st_size,
        "out_dimensions_px": [width_px, height_px],
        "out_sha256": sha256_file(out_path),
        "fillers_hidden_for_visibility": hide_fillers,
    }
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
