"""rtl/odos_q2_30_ref.py — Bit-exact integer Q2.30 golden reference model for odos_gate_core.sv."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence

ONE_Q2_30: int = 1 << 30
RCF_FLOOR_Q2_30: int = 0x3CCCCCCD
DELTA_E_CEIL_Q2_30: int = 0x03333333
NORM_MIN_Q2_30: int = 0x3FEF9DB2
NORM_MAX_Q2_30: int = 0x4010624E
STRIP_NORM_MIN_Q2_30: int = 0x00000432
BLEED_CEIL_Q2_30: int = 0x00000020
INT32_MIN: int = -(1 << 31)
INT32_MAX: int = (1 << 31) - 1


def sat_s32(val: int) -> int:
    return max(INT32_MIN, min(INT32_MAX, val))


def q60_to_q30(acc: int) -> int:
    return sat_s32((acc + (1 << 29)) >> 30)


def mul_q30(a: int, b: int) -> int:
    return q60_to_q30(a * b)


def abs_q30(x: int) -> int:
    if x == INT32_MIN:
        return INT32_MAX
    return -x if x < 0 else x


def load_rom_hex(path: str) -> List[int]:
    vals: List[int] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            s = line.strip()
            if not s:
                continue
            u = int(s, 16)
            vals.append(u - (1 << 32) if (u & 0x80000000) else u)
    if len(vals) != 64:
        raise ValueError(f"Expected 64 ROM entries in {path}, got {len(vals)}")
    return vals


@dataclass(frozen=True)
class RtlGateResult:
    norm_sq: int
    rcf_raw: int
    g3_overlap: int
    delta_e_raw: int
    bleed_post: int
    norm_fault: bool
    pure_g3_collision: bool
    gate_pass: bool
    veto_pin: bool
    cycle_count: int
    stripped_vec: List[int]


def eval_q2_30_reference(
    vec_q: Sequence[int],
    l_rom: Sequence[int],
    g3_rom: Sequence[int],
) -> RtlGateResult:
    v = [sat_s32(int(x)) for x in vec_q]
    norm_sq = q60_to_q30(sum(x * x for x in v))
    dot_l = q60_to_q30(sum(x * l for x, l in zip(v, l_rom)))
    dot_g3_p1 = q60_to_q30(sum(x * g for x, g in zip(v, g3_rom)))

    norm_ok = NORM_MIN_Q2_30 <= norm_sq <= NORM_MAX_Q2_30
    rcf_raw = mul_q30(dot_l, dot_l)
    g3_ov = abs_q30(dot_g3_p1)
    one_minus_rcf = 0 if rcf_raw >= ONE_Q2_30 else (ONE_Q2_30 - rcf_raw)
    g3_clamped = ONE_Q2_30 if g3_ov >= ONE_Q2_30 else g3_ov
    delta_e_raw = (one_minus_rcf + g3_clamped) >> 1

    # Pass 1 & Pass 2 Kahan-Parlett G3 Stripping
    v1 = [sat_s32(x - mul_q30(dot_g3_p1, g)) for x, g in zip(v, g3_rom)]
    dot_g3_p2 = q60_to_q30(sum(x * g for x, g in zip(v1, g3_rom)))
    v2 = [sat_s32(x - mul_q30(dot_g3_p2, g)) for x, g in zip(v1, g3_rom)]

    strip_norm_sq = q60_to_q30(sum(x * x for x in v2))
    bleed_raw = abs_q30(q60_to_q30(sum(x * g for x, g in zip(v2, g3_rom))))
    pure_g3 = strip_norm_sq < STRIP_NORM_MIN_Q2_30
    bleed_final = ONE_Q2_30 if pure_g3 else bleed_raw

    gate_pass = (
        norm_ok
        and (not pure_g3)
        and (rcf_raw >= RCF_FLOOR_Q2_30)
        and (delta_e_raw <= DELTA_E_CEIL_Q2_30)
        and (bleed_final <= BLEED_CEIL_Q2_30)
    )
    return RtlGateResult(
        norm_sq=norm_sq,
        rcf_raw=rcf_raw,
        g3_overlap=g3_ov,
        delta_e_raw=delta_e_raw,
        bleed_post=bleed_final,
        norm_fault=not norm_ok,
        pure_g3_collision=pure_g3,
        gate_pass=gate_pass,
        veto_pin=not gate_pass,
        cycle_count=195,
        stripped_vec=v2,
    )
