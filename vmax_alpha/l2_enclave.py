"""
vmax_alpha/l2_enclave.py
Requirement F-02 & F-07.1 (WORK-ORDER-AG-14 / Revision V1.7 Hardened):
CUDA L2-SRAM 2.00 MiB Enclave Pinning via libcudart.so.13 featuring:
1. Symmetric N=10 interleaved contention benchmark (identical thrash->enclave
   loop for PERSISTING hitProp=2 vs STREAMING hitProp=1 on same 2.00 MiB buffer).
2. Real live `PinnedL2ProjectorEnclave` storing `mean_384` and `W_384_to_64`
   inside the pinned 2.00 MiB L2-SRAM region and executing live S^63 projections.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import glob
import os
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import torch
from vmax_alpha.config import REGISTER_M

CUDA_ACCESS_PROPERTY_NORMAL: int = 0
CUDA_ACCESS_PROPERTY_STREAMING: int = 1
CUDA_ACCESS_PROPERTY_PERSISTING: int = 2
CUDA_LIMIT_PERSISTING_L2_CACHE_SIZE: int = 0x06
CUDA_DEV_ATTR_L2_CACHE_SIZE: int = 38
CUDA_DEV_ATTR_MAX_PERSISTING_L2_CACHE_SIZE: int = 108
CUDA_STREAM_ATTR_ACCESS_POLICY_WINDOW: int = 1
ENCLAVE_BYTES_2MIB: int = 2 * 1024 * 1024  # 0x200000 = 2,097,152 B


class CudaAccessPolicyWindow(ctypes.Structure):
    _fields_ = [
        ("base_ptr", ctypes.c_void_p),
        ("num_bytes", ctypes.c_size_t),
        ("hitRatio", ctypes.c_float),
        ("hitProp", ctypes.c_int),
        ("missProp", ctypes.c_int),
    ]


class CudaStreamAttrValue(ctypes.Union):
    _fields_ = [
        ("pad", ctypes.c_char * 64),
        ("accessPolicyWindow", CudaAccessPolicyWindow),
    ]


def load_libcudart() -> Tuple[Optional[ctypes.CDLL], str]:
    if torch.cuda.is_available():
        torch.cuda.init()
        _ = torch.empty(1, device="cuda:0")
    cands: List[str] = []
    try:
        with open("/proc/self/maps", "r", encoding="utf-8") as f:
            for line in f:
                if "libcudart.so" in line:
                    p = line.strip().split()[-1]
                    if p not in cands and os.path.exists(p):
                        cands.append(p)
    except Exception:
        pass
    for sp in sys.path:
        if sp and os.path.isdir(sp):
            cands.extend(sorted(glob.glob(os.path.join(sp, "nvidia", "*", "lib", "libcudart.so*"))))
            cands.extend(sorted(glob.glob(os.path.join(sp, "torch", "lib", "libcudart*.so*"))))
    for sdir in ("/usr/local/cuda-13.0/targets/x86_64-linux/lib", "/usr/local/cuda/lib64"):
        cands.extend(sorted(glob.glob(os.path.join(sdir, "libcudart.so*"))))
    for c in cands + [ctypes.util.find_library("cudart") or "", "libcudart.so"]:
        if not c:
            continue
        try:
            lib = ctypes.CDLL(c)
            lib.cudaDeviceGetAttribute.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_int, ctypes.c_int]
            lib.cudaDeviceGetAttribute.restype = ctypes.c_int
            lib.cudaDeviceSetLimit.argtypes = [ctypes.c_int, ctypes.c_size_t]
            lib.cudaDeviceSetLimit.restype = ctypes.c_int
            lib.cudaDeviceGetLimit.argtypes = [ctypes.POINTER(ctypes.c_size_t), ctypes.c_int]
            lib.cudaDeviceGetLimit.restype = ctypes.c_int
            lib.cudaCtxResetPersistingL2Cache.argtypes = []
            lib.cudaCtxResetPersistingL2Cache.restype = ctypes.c_int
            lib.cudaStreamSetAttribute.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(CudaStreamAttrValue)]
            lib.cudaStreamSetAttribute.restype = ctypes.c_int
            lib.cudaStreamGetAttribute.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(CudaStreamAttrValue)]
            lib.cudaStreamGetAttribute.restype = ctypes.c_int
            return lib, c
        except OSError:
            continue
    return None, ""


def apply_l2_window_with_fallback(
    libcudart: ctypes.CDLL,
    stream_handle: int,
    base_ptr: int,
    num_bytes: int = ENCLAVE_BYTES_2MIB,
    hit_ratio: float = 1.0,
    simulate_error_code: int = 0,
    hit_prop: int = CUDA_ACCESS_PROPERTY_PERSISTING,
) -> Dict[str, Any]:
    attr = CudaStreamAttrValue()
    ctypes.memset(ctypes.byref(attr), 0, ctypes.sizeof(attr))
    attr.accessPolicyWindow.base_ptr = ctypes.c_void_p(base_ptr)
    attr.accessPolicyWindow.num_bytes = ctypes.c_size_t(max(0, num_bytes))
    attr.accessPolicyWindow.hitRatio = ctypes.c_float(hit_ratio)
    attr.accessPolicyWindow.hitProp = ctypes.c_int(hit_prop)
    attr.accessPolicyWindow.missProp = ctypes.c_int(CUDA_ACCESS_PROPERTY_STREAMING)
    invalid_param = num_bytes <= 0 or hit_ratio <= 0.0 or hit_ratio > 1.0 or base_ptr == 0
    if simulate_error_code != 0 or invalid_param:
        res_code = simulate_error_code if simulate_error_code != 0 else 1
    else:
        res_code = int(
            libcudart.cudaStreamSetAttribute(
                ctypes.c_void_p(stream_handle),
                CUDA_STREAM_ATTR_ACCESS_POLICY_WINDOW,
                ctypes.byref(attr),
            )
        )
    if res_code != 0:
        fb = CudaStreamAttrValue()
        ctypes.memset(ctypes.byref(fb), 0, ctypes.sizeof(fb))
        fb.accessPolicyWindow.hitProp = ctypes.c_int(CUDA_ACCESS_PROPERTY_NORMAL)
        fb.accessPolicyWindow.missProp = ctypes.c_int(CUDA_ACCESS_PROPERTY_NORMAL)
        fb_rc = int(
            libcudart.cudaStreamSetAttribute(
                ctypes.c_void_p(stream_handle),
                CUDA_STREAM_ATTR_ACCESS_POLICY_WINDOW,
                ctypes.byref(fb),
            )
        )
        return {
            "status": "FALLBACK_TO_NORMAL_RECOVERY",
            "fault_code": res_code,
            "fallback_rc": fb_rc,
            "active_hit_prop": CUDA_ACCESS_PROPERTY_NORMAL,
            "recovered": fb_rc == 0,
        }
    rb = CudaStreamAttrValue()
    ctypes.memset(ctypes.byref(rb), 0, ctypes.sizeof(rb))
    rb_rc = int(
        libcudart.cudaStreamGetAttribute(
            ctypes.c_void_p(stream_handle),
            CUDA_STREAM_ATTR_ACCESS_POLICY_WINDOW,
            ctypes.byref(rb),
        )
    )
    win = rb.accessPolicyWindow
    active_status = (
        "PINNED_PERSISTING_ACTIVE"
        if int(win.hitProp) == CUDA_ACCESS_PROPERTY_PERSISTING
        else "STREAMING_WINDOW_ACTIVE"
    )
    return {
        "status": active_status,
        "fault_code": 0,
        "readback_rc": rb_rc,
        "base_ptr_hex": hex(int(win.base_ptr or 0)),
        "num_bytes_readback": int(win.num_bytes),
        "hit_ratio_readback": round(float(win.hitRatio), 4),
        "active_hit_prop": int(win.hitProp),
        "active_miss_prop": int(win.missProp),
        "verified": rb_rc == 0 and int(win.hitProp) == hit_prop and int(win.num_bytes) == num_bytes,
    }


class PinnedL2ProjectorEnclave:
    """Packs live mean_vec and W_proj inside a 2.00 MiB CUDA L2-persisting enclave for real projections."""

    def __init__(self, mean_vec: np.ndarray, w_proj: np.ndarray) -> None:
        self.d_in, self.d_out = int(w_proj.shape[0]), int(w_proj.shape[1])
        self.active = False
        self.pin_info: Dict[str, Any] = {"status": "CPU_FALLBACK", "verified": False}
        self._cpu_mean = mean_vec.astype(np.float64)
        self._cpu_w = w_proj.astype(np.float64)
        if not torch.cuda.is_available():
            return
        libcudart, _ = load_libcudart()
        if libcudart is None:
            return
        self.stream = torch.cuda.Stream(device=0)
        # 262,144 float64 values == exactly 2,097,152 bytes (2.00 MiB)
        self.enclave_slab = torch.zeros(ENCLAVE_BYTES_2MIB // 8, dtype=torch.float64, device="cuda:0")
        self.mean_view = self.enclave_slab[: self.d_in]
        w_end = self.d_in + self.d_in * self.d_out
        self.w_view = self.enclave_slab[self.d_in : w_end].view(self.d_in, self.d_out)
        with torch.cuda.stream(self.stream):
            self.mean_view.copy_(torch.from_numpy(self._cpu_mean).to("cuda:0"))
            self.w_view.copy_(torch.from_numpy(self._cpu_w).to("cuda:0"))
        self.stream.synchronize()
        libcudart.cudaDeviceSetLimit(CUDA_LIMIT_PERSISTING_L2_CACHE_SIZE, ctypes.c_size_t(ENCLAVE_BYTES_2MIB))
        self.pin_info = apply_l2_window_with_fallback(
            libcudart,
            int(self.stream.cuda_stream),
            int(self.enclave_slab.data_ptr()),
            ENCLAVE_BYTES_2MIB,
            1.0,
            hit_prop=CUDA_ACCESS_PROPERTY_PERSISTING,
        )
        self.active = bool(self.pin_info.get("verified"))

    def project(self, vec_in: np.ndarray) -> np.ndarray:
        if not self.active:
            c = vec_in.astype(np.float64) - self._cpu_mean
            raw = (c / max(float(np.linalg.norm(c)), 1e-12)) @ self._cpu_w
            return raw / max(float(np.linalg.norm(raw)), 1e-12)
        with torch.no_grad(), torch.cuda.stream(self.stream):
            v_gpu = torch.from_numpy(vec_in.astype(np.float64)).to("cuda:0", non_blocking=False)
            c_gpu = v_gpu - self.mean_view
            c_gpu = c_gpu / torch.clamp(torch.linalg.norm(c_gpu), min=1e-12)
            raw_gpu = torch.matmul(c_gpu, self.w_view)
            raw_gpu = raw_gpu / torch.clamp(torch.linalg.norm(raw_gpu), min=1e-12)
        self.stream.synchronize()
        return raw_gpu.cpu().numpy().astype(np.float64)


def _stats(vals: List[float]) -> Dict[str, float]:
    return {
        "median": round(float(np.median(vals)), 2),
        "mean": round(float(np.mean(vals)), 2),
        "std": round(float(np.std(vals)), 2),
    }


def _measure_symmetric_interleaved_trials(
    stream_a: torch.cuda.Stream,
    stream_b: torch.cuda.Stream,
    enclave_buf: torch.Tensor,
    thrash_buf: torch.Tensor,
    n_trials: int,
    rounds_per_trial: int = 20,
    inner_hits: int = 1,
) -> List[float]:
    ev_s = torch.cuda.Event(enable_timing=True)
    ev_e = torch.cuda.Event(enable_timing=True)
    gbps_trials: List[float] = []
    with torch.cuda.stream(stream_a):
        enclave_buf.mul_(1.000001)
    stream_a.synchronize()
    for _ in range(n_trials):
        t_ms = 0.0
        for _ in range(rounds_per_trial):
            with torch.cuda.stream(stream_b):
                thrash_buf.mul_(1.000001)
            stream_b.synchronize()
            with torch.cuda.stream(stream_a):
                ev_s.record(stream_a)
                for _ in range(inner_hits):
                    enclave_buf.mul_(1.000001)
                ev_e.record(stream_a)
            stream_a.synchronize()
            t_ms += float(ev_s.elapsed_time(ev_e))
        gbps_trials.append((rounds_per_trial * inner_hits * 2 * ENCLAVE_BYTES_2MIB / 1e9) / (t_ms / 1e3))
    return gbps_trials


def run_l2_enclave_and_ncu_audit(ncu_bin: str = "/usr/local/cuda-13.0/bin/ncu", n_trials: int = 10) -> Dict[str, Any]:
    libcudart, lib_path = load_libcudart()
    if libcudart is None:
        raise RuntimeError("Failed to load libcudart.so")
    l2_size, max_persist = ctypes.c_int(0), ctypes.c_int(0)
    libcudart.cudaDeviceGetAttribute(ctypes.byref(l2_size), CUDA_DEV_ATTR_L2_CACHE_SIZE, 0)
    libcudart.cudaDeviceGetAttribute(ctypes.byref(max_persist), CUDA_DEV_ATTR_MAX_PERSISTING_L2_CACHE_SIZE, 0)
    libcudart.cudaCtxResetPersistingL2Cache()
    set_rc = int(libcudart.cudaDeviceSetLimit(CUDA_LIMIT_PERSISTING_L2_CACHE_SIZE, ctypes.c_size_t(ENCLAVE_BYTES_2MIB)))
    limit_rb = ctypes.c_size_t(0)
    libcudart.cudaDeviceGetLimit(ctypes.byref(limit_rb), CUDA_LIMIT_PERSISTING_L2_CACHE_SIZE)

    stream_a, stream_b = torch.cuda.Stream(device=0), torch.cuda.Stream(device=0)
    enclave_buf = torch.ones(ENCLAVE_BYTES_2MIB // 4, dtype=torch.float32, device="cuda:0")
    thrash_buf = torch.ones((64 * 1024 * 1024) // 4, dtype=torch.float32, device="cuda:0")
    fault_rec = apply_l2_window_with_fallback(
        libcudart, int(stream_b.cuda_stream), int(enclave_buf.data_ptr()), -1, 1.5, simulate_error_code=11
    )
    apply_l2_window_with_fallback(
        libcudart, int(stream_b.cuda_stream), int(thrash_buf.data_ptr()), 64 * 1024 * 1024, 1.0, hit_prop=CUDA_ACCESS_PROPERTY_NORMAL
    )
    pin_info = apply_l2_window_with_fallback(
        libcudart, int(stream_a.cuda_stream), int(enclave_buf.data_ptr()), ENCLAVE_BYTES_2MIB, 1.0, hit_prop=CUDA_ACCESS_PROPERTY_PERSISTING
    )
    pinned_2m_trials = _measure_symmetric_interleaved_trials(stream_a, stream_b, enclave_buf, thrash_buf, n_trials, 20, 1)

    libcudart.cudaCtxResetPersistingL2Cache()
    apply_l2_window_with_fallback(
        libcudart, int(stream_a.cuda_stream), int(enclave_buf.data_ptr()), ENCLAVE_BYTES_2MIB, 1.0, hit_prop=CUDA_ACCESS_PROPERTY_STREAMING
    )
    unpinned_2m_trials = _measure_symmetric_interleaved_trials(stream_a, stream_b, enclave_buf, thrash_buf, n_trials, 20, 1)

    ev_s, ev_e = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
    stream_64m_trials, warm_roof_trials = [], []
    for _ in range(n_trials):
        with torch.cuda.stream(stream_b):
            ev_s.record(stream_b)
            for _ in range(20):
                thrash_buf.mul_(1.000001)
            ev_e.record(stream_b)
        stream_b.synchronize()
        stream_64m_trials.append((20 * 2 * (64 * 1024 * 1024) / 1e9) / (float(ev_s.elapsed_time(ev_e)) / 1e3))
        with torch.cuda.stream(stream_a):
            enclave_buf.mul_(1.000001)
            ev_s.record(stream_a)
            for _ in range(200):
                enclave_buf.mul_(1.000001)
            ev_e.record(stream_a)
        stream_a.synchronize()
        warm_roof_trials.append((200 * 2 * ENCLAVE_BYTES_2MIB / 1e9) / (float(ev_s.elapsed_time(ev_e)) / 1e3))

    # Verify live PinnedL2ProjectorEnclave parity on real 384x64 matrix inside 2 MiB pinned slab
    rng = np.random.RandomState(137)
    q_w, _ = np.linalg.qr(rng.randn(384, 64).astype(np.float64), mode="reduced")
    m_vec, x_vec = rng.randn(384).astype(np.float64), rng.randn(384).astype(np.float64)
    live_enclave = PinnedL2ProjectorEnclave(m_vec, q_w)
    gpu_proj = live_enclave.project(x_vec)
    c_ref = (x_vec - m_vec) / max(float(np.linalg.norm(x_vec - m_vec)), 1e-12)
    cpu_proj = (c_ref @ q_w) / max(float(np.linalg.norm(c_ref @ q_w)), 1e-12)
    live_proj_err = float(np.max(np.abs(gpu_proj - cpu_proj)))

    s_pin, s_unpin = _stats(pinned_2m_trials), _stats(unpinned_2m_trials)
    s_64m, s_roof = _stats(stream_64m_trials), _stats(warm_roof_trials)
    ncu_args = [
        ncu_bin, "--clock-control", "none", "--csv", "--metrics",
        "lts__t_sectors_srcunit_tex_op_read_lookup_hit.pct,lts__t_sectors_hit_rate.pct",
        sys.executable, "-c", "import torch; x=torch.ones(524288, device='cuda'); y=x*2.0; torch.cuda.synchronize()",
    ]
    proc = subprocess.run(ncu_args, capture_output=True, text=True, timeout=45)
    out_txt = "\n".join([ln.strip() for ln in (proc.stdout + "\n" + proc.stderr).splitlines() if ln.strip()])
    return {
        "epistemic_register": REGISTER_M,
        "symmetric_interleaved_protocol": True,
        "libcudart_path": lib_path,
        "hw_l2_cache_bytes": int(l2_size.value),
        "hw_max_persisting_l2_bytes": int(max_persist.value),
        "set_limit_rc": set_rc,
        "persisting_limit_readback_bytes": int(limit_rb.value),
        "stream_a_pinning": pin_info,
        "f07_1_fault_injection_recovery": fault_rec,
        "live_pinned_l2_projector": {
            "active": live_enclave.active,
            "matrix_shape": [384, 64],
            "payload_bytes_inside_2mib_slab": (384 + 384 * 64) * 8,
            "max_abs_diff_vs_cpu_f64": live_proj_err,
            "pin_status": live_enclave.pin_info.get("status"),
        },
        "microbenchmark_bandwidth": {
            "n_trials": n_trials,
            "rounds_per_trial": 20,
            "inner_hits_per_round": 1,
            "stream_a_pinned_2mib_gbps": s_pin["median"],
            "stream_a_pinned_2mib_stats_gbps": s_pin,
            "stream_a_unpinned_evicted_2mib_gbps": s_unpin["median"],
            "stream_a_unpinned_evicted_2mib_stats_gbps": s_unpin,
            "stream_b_streaming_64mib_gbps": s_64m["median"],
            "stream_b_streaming_64mib_stats_gbps": s_64m,
            "uninterrupted_warm_2mib_l2_roof_gbps": s_roof["median"],
            "uninterrupted_warm_2mib_l2_roof_stats_gbps": s_roof,
            "pinned_vs_unpinned_2mib_speedup": round(s_pin["median"] / max(s_unpin["median"], 1e-6), 3),
            "pinned_vs_streaming_speedup": round(s_pin["median"] / max(s_64m["median"], 1e-6), 3),
        },
        "ncu_profiler_output": out_txt[-1200:],
    }
