"""rtl/gen_rom_hex.py — Generates canonical Q2.30 HEX ROMs for odos_gate_core.sv."""
from __future__ import annotations

import hashlib
import json
import os
from typing import Dict, List

import numpy as np

from vmax_alpha.config import CANONICAL_LITTLE_VECTOR_SEAL
from vmax_alpha.geometry import build_orthogonal_tangents, derive_canonical_little_vector

SCALE_Q2_30: int = 1 << 30
INT32_MIN: int = -(1 << 31)
INT32_MAX: int = (1 << 31) - 1


def float_to_q2_30(val: float) -> int:
    q = int(round(float(val) * SCALE_Q2_30))
    return max(INT32_MIN, min(INT32_MAX, q))


def write_q2_30_hex(path: str, vec: np.ndarray) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines: List[str] = [f"{(float_to_q2_30(x) & 0xFFFFFFFF):08x}" for x in vec]
    payload = "\n".join(lines) + "\n"
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(payload)
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def generate_roms(rom_dir: str = "rtl/rom") -> Dict[str, str]:
    l_vec, l_seal = derive_canonical_little_vector()
    if l_seal != CANONICAL_LITTLE_VECTOR_SEAL:
        raise RuntimeError(f"Canonical |L> seal mismatch: {l_seal}")
    tangents = build_orthogonal_tangents(l_vec)
    g3_vec = tangents["G3_KEVLAR_SANCTUARY_SHIELD"]
    l_sha = write_q2_30_hex(os.path.join(rom_dir, "l_vec_q2_30.hex"), l_vec)
    g3_sha = write_q2_30_hex(os.path.join(rom_dir, "g3_vec_q2_30.hex"), g3_vec)
    manifest = {
        "canonical_little_vector_seal": l_seal,
        "format": "signed_Q2_30_hex_64x32bit",
        "l_vec_q2_30_hex_sha256": l_sha,
        "g3_vec_q2_30_hex_sha256": g3_sha,
    }
    with open(
        os.path.join(rom_dir, "rom_manifest.json"),
        "w",
        encoding="utf-8",
        newline="\n",
    ) as fh:
        json.dump(manifest, fh, indent=2)
        fh.write("\n")
    return manifest


if __name__ == "__main__":
    print(json.dumps(generate_roms(), indent=2))
