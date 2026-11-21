"""
vmax_alpha/hw_gate_v4_bridge.py
In-process ctypes C-ABI Hardware-in-the-Loop Bridge for odos_gate_core_v4.sv
(200-cycle MAC-pipelined + paired-word 1P foundry SRAM architecture) with
persistent L1-resident Verilator context, thread-safe lock, and portable fallback.
"""
from __future__ import annotations

import ctypes
from dataclasses import asdict, dataclass
import os
import threading
from typing import Dict, List, Optional, Sequence

import numpy as np

from rtl.odos_q2_30_ref import (
    BLEED_CEIL_Q2_30,
    ONE_Q2_30,
    eval_q2_30_reference,
    load_rom_hex,
)
from vmax_alpha.config import REGISTER_D, REGISTER_M
from vmax_alpha.geometry import build_orthogonal_tangents, derive_canonical_little_vector
from vmax_alpha.hw_gate_bridge import (
    TIER_0_PURE_CARRIER,
    TIER_3_GLITCH_VETO,
    TIER_THRESHOLDS_Q2_30,
    float_vec_to_q2_30,
)

REPO_ROOT: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_V4_SO_PATH: str = os.path.join(REPO_ROOT, "rtl", "build", "libodos_gate_v4.so")


class _OdosV4ResultC(ctypes.Structure):
    _fields_ = [
        ("cycle_count", ctypes.c_uint16),
        ("reset_fail_closed", ctypes.c_uint8),
        ("busy_veto_held", ctypes.c_uint8),
        ("gate_pass", ctypes.c_uint8),
        ("veto_pin", ctypes.c_uint8),
        ("norm_fault", ctypes.c_uint8),
        ("pure_g3_collision", ctypes.c_uint8),
        ("mode_fault", ctypes.c_uint8),
        ("norm_sq_q", ctypes.c_int32),
        ("rcf_raw_q", ctypes.c_int32),
        ("g3_overlap_q", ctypes.c_int32),
        ("delta_e_raw_q", ctypes.c_int32),
        ("bleed_post_q", ctypes.c_int32),
    ]


@dataclass(frozen=True)
class V4HardwareVerdict:
    epistemic_register: str
    backend: str
    tier_mode: int
    cycle_count: int
    reset_fail_closed: bool
    busy_veto_held: bool
    gate_pass: bool
    veto_pin: bool
    norm_fault: bool
    pure_g3_collision: bool
    mode_fault: bool
    norm_sq_q: int
    rcf_raw_q: int
    g3_overlap_q: int
    delta_e_raw_q: int
    bleed_post_q: int
    stripped_vec_q: List[int]

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


def evaluate_v4_integer_ref(
    vec_q30: Sequence[int],
    l_q30: Sequence[int],
    g3_q30: Sequence[int],
    tier_mode: int = TIER_0_PURE_CARRIER,
) -> V4HardwareVerdict:
    """Bit-exact pure-integer Q2.30 reference model for odos_gate_core_v4.sv."""
    base = eval_q2_30_reference(vec_q30, l_q30, g3_q30)
    mode_bits = int(tier_mode) & 0x3
    mode_fault = mode_bits == TIER_3_GLITCH_VETO
    rcf_floor, de_ceil = TIER_THRESHOLDS_Q2_30.get(mode_bits, (ONE_Q2_30, 0))
    passed = (
        (not mode_fault)
        and (not base.norm_fault)
        and (not base.pure_g3_collision)
        and base.rcf_raw >= rcf_floor
        and base.delta_e_raw <= de_ceil
        and base.bleed_post <= BLEED_CEIL_Q2_30
    )
    return V4HardwareVerdict(
        epistemic_register=REGISTER_D,
        backend="INTEGER_Q2_30_REF_V4_FALLBACK",
        tier_mode=mode_bits,
        cycle_count=200,
        reset_fail_closed=True,
        busy_veto_held=True,
        gate_pass=passed,
        veto_pin=not passed,
        norm_fault=base.norm_fault,
        pure_g3_collision=base.pure_g3_collision,
        mode_fault=mode_fault,
        norm_sq_q=base.norm_sq,
        rcf_raw_q=base.rcf_raw,
        g3_overlap_q=base.g3_overlap,
        delta_e_raw_q=base.delta_e_raw,
        bleed_post_q=base.bleed_post,
        stripped_vec_q=list(base.stripped_vec),
    )


def _pack_v4_verdict(
    res: _OdosV4ResultC,
    out_arr: Sequence[int],
    tier_mode: int,
    backend: str,
) -> V4HardwareVerdict:
    return V4HardwareVerdict(
        epistemic_register=REGISTER_M,
        backend=backend,
        tier_mode=int(tier_mode) & 0x3,
        cycle_count=int(res.cycle_count),
        reset_fail_closed=bool(res.reset_fail_closed),
        busy_veto_held=bool(res.busy_veto_held),
        gate_pass=bool(res.gate_pass),
        veto_pin=bool(res.veto_pin),
        norm_fault=bool(res.norm_fault),
        pure_g3_collision=bool(res.pure_g3_collision),
        mode_fault=bool(res.mode_fault),
        norm_sq_q=int(res.norm_sq_q),
        rcf_raw_q=int(res.rcf_raw_q),
        g3_overlap_q=int(res.g3_overlap_q),
        delta_e_raw_q=int(res.delta_e_raw_q),
        bleed_post_q=int(res.bleed_post_q),
        stripped_vec_q=[int(out_arr[i]) for i in range(64)],
    )


def _load_rom_pair() -> tuple[List[int], List[int]]:
    l_hex = os.path.join(REPO_ROOT, "rtl", "rom", "l_vec_q2_30.hex")
    g3_hex = os.path.join(REPO_ROOT, "rtl", "rom", "g3_vec_q2_30.hex")
    if os.path.isfile(l_hex) and os.path.isfile(g3_hex):
        return load_rom_hex(l_hex), load_rom_hex(g3_hex)
    l_vec, _ = derive_canonical_little_vector()
    t_g3 = build_orthogonal_tangents(l_vec)["G3_KEVLAR_SANCTUARY_SHIELD"]
    return float_vec_to_q2_30(l_vec), float_vec_to_q2_30(t_g3)


class OdosGateV4Bridge:
    """Thread-safe persistent C-ABI bridge to Verilated odos_gate_core_v4.sv."""

    def __init__(self, so_path: str = DEFAULT_V4_SO_PATH) -> None:
        self.so_path: str = so_path
        self.l_q30, self.g3_q30 = _load_rom_pair()
        self._lock = threading.Lock()
        self._lib: Optional[ctypes.CDLL] = self._try_load(so_path)
        self._ctx: Optional[int] = None
        if self._lib is not None:
            raw_ptr = self._lib.odos_v4_ctx_create(REPO_ROOT.encode("utf-8"))
            self._ctx = int(raw_ptr) if raw_ptr else None
        self.rtl_active: bool = (self._lib is not None) and (self._ctx is not None)

    @staticmethod
    def _try_load(so_path: str) -> Optional[ctypes.CDLL]:
        if not os.path.isfile(so_path):
            return None
        lib = ctypes.CDLL(so_path)
        lib.odos_v4_ctx_create.argtypes = [ctypes.c_char_p]
        lib.odos_v4_ctx_create.restype = ctypes.c_void_p
        lib.odos_v4_ctx_eval.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_int32),
            ctypes.c_uint8,
            ctypes.c_int32,
            ctypes.c_uint8,
            ctypes.POINTER(ctypes.c_int32),
            ctypes.POINTER(_OdosV4ResultC),
        ]
        lib.odos_v4_ctx_eval.restype = ctypes.c_int
        lib.odos_v4_ctx_destroy.argtypes = [ctypes.c_void_p]
        lib.odos_v4_ctx_destroy.restype = None
        return lib

    def close(self) -> None:
        with self._lock:
            if self._lib is not None and self._ctx is not None:
                self._lib.odos_v4_ctx_destroy(ctypes.c_void_p(self._ctx))
                self._ctx = None
                self.rtl_active = False

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def evaluate_q30(
        self,
        vec_q30: Sequence[int],
        tier_mode: int = TIER_0_PURE_CARRIER,
        stall_at_idx: int = -1,
        tamper_tier_in_flight: bool = False,
    ) -> V4HardwareVerdict:
        if not self.rtl_active or self._lib is None or self._ctx is None:
            return evaluate_v4_integer_ref(vec_q30, self.l_q30, self.g3_q30, tier_mode)
        in_arr = (ctypes.c_int32 * 64)(*vec_q30)
        out_arr = (ctypes.c_int32 * 64)()
        res = _OdosV4ResultC()
        with self._lock:
            rc = int(
                self._lib.odos_v4_ctx_eval(
                    ctypes.c_void_p(self._ctx),
                    in_arr,
                    int(tier_mode) & 0x3,
                    int(stall_at_idx),
                    1 if tamper_tier_in_flight else 0,
                    out_arr,
                    ctypes.byref(res),
                )
            )
        if rc != 0:
            raise RuntimeError(f"odos_v4_ctx_eval returned error {rc}")
        return _pack_v4_verdict(res, out_arr, tier_mode, "VERILATOR_CABI_PERSISTENT_V40")

    def evaluate_float64(
        self,
        vec_64d: np.ndarray,
        tier_mode: int = TIER_0_PURE_CARRIER,
        stall_at_idx: int = -1,
        tamper_tier_in_flight: bool = False,
    ) -> V4HardwareVerdict:
        q_vec = float_vec_to_q2_30(np.asarray(vec_64d, dtype=np.float64).reshape(64))
        return self.evaluate_q30(q_vec, tier_mode, stall_at_idx, tamper_tier_in_flight)
