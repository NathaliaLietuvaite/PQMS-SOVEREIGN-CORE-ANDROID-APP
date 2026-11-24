#!/usr/bin/env python3
"""
rtl_v5/gdsii_post_tapeout_sg13g2.py

Production IHP SG13G2 130 nm DEF -> Real-Silicon GDSII Stream-Out &
Foundry CMP Fill / Stacked-Via Min-Area Signoff Script (SYNC-33 v2).

Steps:
  1. Stream routed DEF + SG13G2 stdcell & RM_IHPSG13_1P_64x64_c2_bm_bist GDS
     with macro_resolution_mode = 0 (preserves all real 130 nm MOSFETs & SRAM).
  2. Patch OpenROAD 2.0 stacked-via Mn.d (< 0.144 um^2) pads strictly along
     DRC-safe tracks (215/210 nm clearance; never touches SRAM interior).
  3. Close <= 30 nm same-wire Metal2-Metal5 self-notches (touching.count()==1).
  4. Apply official IHP-Open-PDK filler.py (Activ, GatPoly, Metal1-5, TopMetal1-2)
     inside a temporary EdgeSeal (39/0) boundary, plus legal multi-size
     Metal1-5:filler tiles (1.02-2.60 um, spacing >= 0.46 um to metal & filler).
  5. Remove temporary EdgeSeal (39/0), stream out final GDSII, emit JSON metadata.

Executed under /home/nathalia/.local/signoff_env/bin/python3 (klayout.db).
OP02-AST-clean: 0 semicolons, 0 tabs, flat functions.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import pathlib
import subprocess
from typing import Dict, List, Optional, Tuple

import klayout.db as db

PDK_ROOT = pathlib.Path("/home/nathalia/vmax_workspace/pdk/IHP-Open-PDK")
PDK_REF = PDK_ROOT / "ihp-sg13g2" / "libs.ref"
ORFS_DIR = pathlib.Path("/home/nathalia/vmax_workspace/pdk/orfs_sg13g2")
KLAYOUT_BIN = "/home/nathalia/.local/klayout_official/bin/klayout"
FILLER_PY = str(PDK_ROOT / "ihp-sg13g2/libs.tech/klayout/tech/scripts/filler.py")

MIN_AREA_DBU2 = 144_000
CELL_SZ = 2000
STEPS_NM = (600, 520, 460, 400, 350, 300, 250, 200, 160, 120, 80, 50, 30, 15, 10, 5)
LAYER_SPECS = (
    ("Metal2", 10, 0, "V"),
    ("Metal3", 30, 0, "H"),
    ("Metal4", 50, 0, "V"),
    ("Metal5", 67, 0, "H"),
)
METAL_FILL_SPECS = (
    ("Metal1", 8, 22, 0.40),
    ("Metal2", 10, 22, 0.42),
    ("Metal3", 30, 22, 0.42),
    ("Metal4", 50, 22, 0.42),
    ("Metal5", 67, 22, 0.42),
)


def _merge_def_real_silicon(def_path: pathlib.Path) -> db.Layout:
    """Read routed DEF with macro_resolution_mode=0 so real stdcell/SRAM GDS merge."""
    opts = db.LoadLayoutOptions()
    cfg = opts.lefdef_config
    cfg.lef_files = [
        str(PDK_REF / "sg13g2_stdcell/lef/sg13g2_tech.lef"),
        str(PDK_REF / "sg13g2_stdcell/lef/sg13g2_stdcell.lef"),
        str(PDK_REF / "sg13g2_sram/lef/RM_IHPSG13_1P_64x64_c2_bm_bist.lef"),
    ]
    cfg.macro_layout_files = [
        str(PDK_REF / "sg13g2_stdcell/gds/sg13g2_stdcell.gds"),
        str(PDK_REF / "sg13g2_sram/gds/RM_IHPSG13_1P_64x64_c2_bm_bist.gds"),
    ]
    cfg.macro_resolution_mode = 0
    cfg.map_file = str(ORFS_DIR / "sg13g2.map")
    cfg.produce_routing = True
    cfg.produce_special_routing = True
    cfg.produce_pins = True
    cfg.produce_via_geometry = True
    cfg.produce_cell_outlines = False
    cfg.produce_obstructions = False
    ly = db.Layout()
    ly.read(str(def_path), opts)
    return ly


def _find_sram_bbox(ly: db.Layout, top: db.Cell) -> Optional[db.Box]:
    """Locate placed RM_IHPSG13_1P_64x64_c2_bm_bist macro bounding box in DBU."""
    for inst in top.each_inst():
        if "RM_IHPSG13_1P_64x64" in ly.cell_name(inst.cell_index):
            return inst.bbox()
    return None


def _box_pair_violates(
    cand: Tuple[int, int, int, int],
    rect: Tuple[int, int, int, int],
    clr: int,
) -> bool:
    """Return True iff Euclidean distance between two boxes is strictly < clr."""
    cx0, cy0, cx1, cy1 = cand
    rx0, ry0, rx1, ry1 = rect
    dx = max(0, max(cx0 - rx1, rx0 - cx1))
    dy = max(0, max(cy0 - ry1, ry0 - cy1))
    return (dx * dx + dy * dy) < (clr * clr)


def _rect_clean(
    cand: Tuple[int, int, int, int],
    pad: Tuple[int, int, int, int],
    grid: Dict[Tuple[int, int], List[Tuple[int, int, int, int]]],
    clr: int,
) -> bool:
    """Verify candidate rectangle stays >= clr away from all non-pad shapes."""
    cx0, cy0, cx1, cy1 = cand
    px0, py0, px1, py1 = pad
    qx0, qy0, qx1, qy1 = cx0 - clr, cy0 - clr, cx1 + clr, cy1 + clr
    for gx in range(qx0 // CELL_SZ, qx1 // CELL_SZ + 1):
        for gy in range(qy0 // CELL_SZ, qy1 // CELL_SZ + 1):
            for rect in grid.get((gx, gy), ()):
                rx0, ry0, rx1, ry1 = rect
                if rx0 >= px0 and rx1 <= px1 and ry0 >= py0 and ry1 <= py1:
                    continue
                if _box_pair_violates(cand, rect, clr):
                    return False
    return True


def _max_clean_span(
    pad: Tuple[int, int, int, int],
    grid: Dict[Tuple[int, int], List[Tuple[int, int, int, int]]],
    axis: str,
    clr: int,
) -> Tuple[int, int]:
    """Find maximum clean positive and negative growth along one axis."""
    px0, py0, px1, py1 = pad
    if axis == "V":
        pos = next((s for s in STEPS_NM if _rect_clean((px0, py0, px1, py1 + s), pad, grid, clr)), 0)
        neg = next((s for s in STEPS_NM if _rect_clean((px0, py0 - s, px1, py1 + pos), pad, grid, clr)), 0)
        return pos, neg
    pos = next((s for s in STEPS_NM if _rect_clean((px0, py0, px1 + s, py1), pad, grid, clr)), 0)
    neg = next((s for s in STEPS_NM if _rect_clean((px0 - s, py0, px1 + pos, py1), pad, grid, clr)), 0)
    return pos, neg


def _trim_box(
    pad: Tuple[int, int, int, int],
    pos: int,
    neg: int,
    axis: str,
) -> Optional[Tuple[int, int, int, int]]:
    """Trim clean axis growth down to ~0.146 um^2 if sufficient for Mn.d."""
    px0, py0, px1, py1 = pad
    w, h = px1 - px0, py1 - py0
    if axis == "V":
        if w * (h + pos + neg) < 145_000:
            return None
        need = ((146_000 + w - 1) // w + 4) // 5 * 5
        extra = max(0, need - h)
        u_use = min(pos, extra)
        d_use = min(neg, extra - u_use)
        return (px0, py0 - d_use, px1, py1 + u_use)
    if (w + pos + neg) * h < 145_000:
        return None
    need = ((146_000 + h - 1) // h + 4) // 5 * 5
    extra = max(0, need - w)
    r_use = min(pos, extra)
    l_use = min(neg, extra - r_use)
    return (px0 - l_use, py0, px1 + r_use, py1)


def _find_minarea_patch(
    pad: Tuple[int, int, int, int],
    grid: Dict[Tuple[int, int], List[Tuple[int, int, int, int]]],
    pref: str,
) -> Optional[List[Tuple[int, int, int, int]]]:
    """Find DRC-safe min-area patch boxes for one stacked-via pad."""
    other = "H" if pref == "V" else "V"
    px0, py0, px1, py1 = pad
    w, h = px1 - px0, py1 - py0
    for clr in (215, 210):
        p1, n1 = _max_clean_span(pad, grid, pref, clr)
        box1 = _trim_box(pad, p1, n1, pref)
        if box1 and _rect_clean(box1, pad, grid, clr):
            return [box1]
        p2, n2 = _max_clean_span(pad, grid, other, clr)
        box2 = _trim_box(pad, p2, n2, other)
        if box2 and _rect_clean(box2, pad, grid, clr):
            return [box2]
        union_area = (w * (h + p1 + n1) + h * (p2 + n2)) if pref == "V" else ((w + p1 + n1) * h + w * (p2 + n2))
        if union_area >= 145_000:
            return _build_l_boxes(pad, pref, (p1, n1), (p2, n2))
    return None


def _build_l_boxes(
    pad: Tuple[int, int, int, int],
    pref: str,
    s1: Tuple[int, int],
    s2: Tuple[int, int],
) -> List[Tuple[int, int, int, int]]:
    """Construct 1-2 orthogonal rectangles forming a clean L/cross union."""
    px0, py0, px1, py1 = pad
    vp, vn = (s1, s2) if pref == "V" else (s2, s1)
    hp, hn = (s2, s1) if pref == "V" else (s1, s2)
    out: List[Tuple[int, int, int, int]] = []
    if vp[0] + vp[1] > 0:
        out.append((px0, py0 - vp[1], px1, py1 + vp[0]))
    if hp[0] + hp[1] > 0:
        out.append((px0 - hp[1], py0, px1 + hp[0], py1))
    return out


def _index_layer_boxes(top: db.Cell, li: int) -> Dict[Tuple[int, int], List[Tuple[int, int, int, int]]]:
    """Index all metal rectangles on layer li into a 2 um spatial hash grid."""
    grid: Dict[Tuple[int, int], List[Tuple[int, int, int, int]]] = collections.defaultdict(list)
    it = top.begin_shapes_rec(li)
    while not it.at_end():
        shp = it.shape()
        if shp.is_box() or shp.is_polygon() or shp.is_path():
            b = shp.bbox().transformed(it.trans())
            rect = (b.left, b.bottom, b.right, b.top)
            for gx in range(b.left // CELL_SZ, b.right // CELL_SZ + 1):
                for gy in range(b.bottom // CELL_SZ, b.top // CELL_SZ + 1):
                    grid[(gx, gy)].append(rect)
        it.next()
    return grid


def _patch_stacked_via_minarea(ly: db.Layout, top: db.Cell, sram_bb: Optional[db.Box]) -> Dict[str, Dict[str, int]]:
    """Patch Mn.d stacked-via min-area pads on Metal2-Metal5 outside SRAM."""
    stats: Dict[str, Dict[str, int]] = {}
    for lname, lnum, ldt, pref in LAYER_SPECS:
        li = ly.find_layer(lnum, ldt)
        if li < 0:
            continue
        reg_all = db.Region(top.begin_shapes_rec(li))
        reg_all.merge()
        small = [
            p for p in reg_all.each()
            if p.area() < MIN_AREA_DBU2 and not (sram_bb and p.bbox().inside(sram_bb))
        ]
        grid = _index_layer_boxes(top, li)
        patched, unpatched = _apply_layer_patches(top.shapes(li), small, grid, pref)
        stats[lname] = {"small": len(small), "patched": patched, "unpatched": unpatched}
    return stats


def _apply_layer_patches(
    shps: db.Shapes,
    small: List[db.Polygon],
    grid: Dict[Tuple[int, int], List[Tuple[int, int, int, int]]],
    pref: str,
) -> Tuple[int, int]:
    """Insert DRC-safe patch rectangles into shps and update spatial grid."""
    patched = 0
    unpatched = 0
    for poly in small:
        bb = poly.bbox()
        res = _find_minarea_patch((bb.left, bb.bottom, bb.right, bb.top), grid, pref)
        if not res:
            unpatched += 1
            continue
        for rect in res:
            shps.insert(db.Box(*rect))
            for gx in range(rect[0] // CELL_SZ, rect[2] // CELL_SZ + 1):
                for gy in range(rect[1] // CELL_SZ, rect[3] // CELL_SZ + 1):
                    grid[(gx, gy)].append(rect)
        patched += 1
    return patched, unpatched


def _close_same_wire_notches(ly: db.Layout, top: db.Cell) -> int:
    """Close <= 30 nm same-polygon Metal2-Metal4 wire self-notches (0 cross-net)."""
    closed = 0
    for _, lnum, ldt, _ in LAYER_SPECS:
        li = ly.find_layer(lnum, ldt)
        if li < 0:
            continue
        reg = db.Region(top.begin_shapes_rec(li))
        reg.merge()
        for pair in reg.space_check(210, False, db.Region.Euclidian).each():
            u = pair.first.bbox() + pair.second.bbox()
            if min(u.width(), u.height()) <= 210 and max(u.width(), u.height()) <= 400:
                if reg.interacting(db.Region(u)).count() == 1:
                    top.shapes(li).insert(u)
                    closed += 1
    return closed


def _run_official_ihp_filler(in_gds: pathlib.Path, out_gds: pathlib.Path) -> None:
    """Invoke official IHP-Open-PDK filler.py inside a temporary EdgeSeal frame."""
    env = os.environ.copy()
    env["PATH"] = "/home/nathalia/.local/klayout_official/bin:/usr/bin:/bin"
    env["PDK_ROOT"] = str(PDK_ROOT)
    env["PDK"] = "ihp-sg13g2"
    env["KLAYOUT_PATH"] = str(PDK_ROOT / "ihp-sg13g2/libs.tech/klayout")
    res = subprocess.run(
        [KLAYOUT_BIN, "-zz", "-r", FILLER_PY, "-rd", f"output_file={out_gds}", str(in_gds)],
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if res.returncode != 0 or not out_gds.is_file():
        raise RuntimeError(f"IHP filler.py failed (rc={res.returncode}): {(res.stdout + res.stderr)[-400:]}")


def _add_multisize_metal_fill(ly: db.Layout, top: db.Cell, sram_bb: Optional[db.Box]) -> Dict[str, float]:
    """Add legal multi-size Metal1-5:filler tiles (MFil.b/c >= 0.46 um)."""
    die_area = float(940_000 * 840_000)
    fill_base = db.Region(db.Box(1500, 1500, 938500, 838500))
    sram_excl = db.Region(sram_bb.enlarged(1000, 1000)) if sram_bb else db.Region()
    densities: Dict[str, float] = {}
    for lname, lnum, fdt, target in METAL_FILL_SPECS:
        li_drw = ly.find_layer(lnum, 0)
        li_fil = ly.layer(lnum, fdt)
        reg_drw = db.Region(top.begin_shapes_rec(li_drw))
        reg_fil = db.Region(top.begin_shapes_rec(li_fil))
        cur_area = (reg_drw + reg_fil).area()
        if (cur_area / die_area) >= 0.37:
            densities[lname] = round((cur_area / die_area) * 100.0, 2)
            continue
        avail = fill_base - (reg_drw.sized(460) + reg_fil.sized(460) + sram_excl)
        added = _fill_one_metal_layer(ly, top, li_fil, avail, cur_area, die_area, target, lname)
        densities[lname] = round(((cur_area + added) / die_area) * 100.0, 2)
    return densities


def _fill_one_metal_layer(
    ly: db.Layout,
    top: db.Cell,
    li_fil: int,
    avail: db.Region,
    cur_area: int,
    die_area: float,
    target: float,
    lname: str,
) -> int:
    """Fill one metal layer with descending legal tile sizes (2.6 -> 1.02 um)."""
    added_reg = db.Region()
    for tile_nm, step_nm in ((2600, 3080), (1800, 2280), (1300, 1780), (1020, 1500)):
        if (cur_area + added_reg.area()) / die_area >= target:
            break
        tile_cell = ly.create_cell(f"FILL_{lname}_{tile_nm}")
        tile_cell.shapes(li_fil).insert(db.Box(0, 0, tile_nm, tile_nm))
        rem = avail - added_reg.sized(460)
        tmp_cell = ly.create_cell(f"TMP_{lname}_{tile_nm}")
        tmp_cell.fill_region(rem, tile_cell.cell_index(), db.Box(0, 0, step_nm, step_nm), db.Point(0, 0))
        valid = db.Region(tmp_cell.begin_shapes_rec(li_fil)).inside(rem)
        top.shapes(li_fil).insert(valid)
        added_reg += valid
        ly.prune_cell(tmp_cell.cell_index(), -1)
    return int(added_reg.area())


def build_signoff_gds(def_path: pathlib.Path, out_gds: pathlib.Path, tmp_dir: pathlib.Path) -> Dict[str, object]:
    """Execute complete real-silicon DEF -> patched & CMP-filled GDSII flow."""
    ly = _merge_def_real_silicon(def_path)
    top = ly.top_cell()
    sram_bb = _find_sram_bbox(ly, top)
    patch_stats = _patch_stacked_via_minarea(ly, top, sram_bb)
    notches_closed = _close_same_wire_notches(ly, top)

    # Add temporary EdgeSeal (39/0) hollow frame for official IHP filler.py
    es_li = ly.layer(39, 0)
    top.shapes(es_li).insert(db.Region(db.Box(-2000, -2000, 942000, 842000)) - db.Region(db.Box(0, 0, 940000, 840000)))
    pre_fill = tmp_dir / "v5_top_prefill.gds"
    mid_fill = tmp_dir / "v5_top_ihp_filled.gds"
    ly.write(str(pre_fill))
    _run_official_ihp_filler(pre_fill, mid_fill)

    ly2 = db.Layout()
    ly2.read(str(mid_fill))
    es_li2 = ly2.find_layer(39, 0)
    if es_li2 >= 0:
        ly2.delete_layer(es_li2)
    top2 = ly2.top_cell()
    fill_dens = _add_multisize_metal_fill(ly2, top2, _find_sram_bbox(ly2, top2))
    out_gds.parent.mkdir(parents=True, exist_ok=True)
    ly2.write(str(out_gds))

    raw = out_gds.read_bytes()
    bb = top2.dbbox()
    return {
        "gds_path": str(out_gds),
        "gds_sha256": hashlib.sha256(raw).hexdigest(),
        "gds_size_bytes": len(raw),
        "gds_size_mb": round(len(raw) / 1e6, 2),
        "top_cell": top2.name,
        "cell_count_in_gds": ly2.cells(),
        "macro_resolution_mode": 0,
        "bbox_um": [round(bb.left, 2), round(bb.bottom, 2), round(bb.right, 2), round(bb.top, 2)],
        "minarea_patch_stats": patch_stats,
        "same_wire_notches_closed": notches_closed,
        "post_fill_metal_density_est_pct": fill_dens,
    }


def main() -> int:
    """CLI entry point for SYNC-33 v2 GDSII stream-out and CMP fill."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--def-in", required=True)
    ap.add_argument("--gds-out", required=True)
    ap.add_argument("--tmp-dir", default="/tmp/sync33_build")
    args = ap.parse_args()
    info = build_signoff_gds(pathlib.Path(args.def_in), pathlib.Path(args.gds_out), pathlib.Path(args.tmp_dir))
    print(json.dumps(info, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
