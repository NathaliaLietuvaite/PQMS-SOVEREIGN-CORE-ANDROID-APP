"""
vmax_alpha/tests/test_f02_l2_enclave.py
Unit and Falsification Tests for Requirement F-02 & F-07.1 (L2-SRAM Enclave & Fault Recovery).
"""

from __future__ import annotations

import json
import os
import unittest

from vmax_alpha.config import REGISTER_M
from vmax_alpha.l2_enclave import (
    CUDA_ACCESS_PROPERTY_NORMAL,
    CUDA_ACCESS_PROPERTY_PERSISTING,
    ENCLAVE_BYTES_2MIB,
    run_l2_enclave_and_ncu_audit,
)


class TestF02L2Enclave(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.audit = run_l2_enclave_and_ncu_audit()

    def test_01_hardware_l2_capacity_and_limit(self) -> None:
        self.assertEqual(self.audit["epistemic_register"], REGISTER_M)
        self.assertEqual(self.audit["hw_l2_cache_bytes"], 33554432)  # 32.0 MiB on RTX 4060 Ti
        self.assertGreaterEqual(self.audit["hw_max_persisting_l2_bytes"], ENCLAVE_BYTES_2MIB)
        self.assertEqual(self.audit["set_limit_rc"], 0)
        self.assertEqual(self.audit["persisting_limit_readback_bytes"], ENCLAVE_BYTES_2MIB)

    def test_02_stream_attribute_readback_verified(self) -> None:
        pin = self.audit["stream_a_pinning"]
        self.assertTrue(pin["verified"])
        self.assertEqual(pin["num_bytes_readback"], ENCLAVE_BYTES_2MIB)
        self.assertEqual(pin["active_hit_prop"], CUDA_ACCESS_PROPERTY_PERSISTING)
        self.assertAlmostEqual(pin["hit_ratio_readback"], 1.0, places=4)

    def test_03_f07_1_negative_control_fault_injection_recovery(self) -> None:
        """
        Requirement F-07.1 (Negative Control): Simulated CUDA error / invalid window size
        must automatically fall back to cudaAccessPropertyNormal (0) without crashing.
        """
        rec = self.audit["f07_1_fault_injection_recovery"]
        self.assertEqual(rec["status"], "FALLBACK_TO_NORMAL_RECOVERY")
        self.assertEqual(rec["active_hit_prop"], CUDA_ACCESS_PROPERTY_NORMAL)
        self.assertTrue(rec["recovered"])

    def test_04_pinned_vs_streaming_bandwidth(self) -> None:
        self.assertTrue(self.audit["symmetric_interleaved_protocol"])
        bw = self.audit["microbenchmark_bandwidth"]
        self.assertGreater(bw["stream_a_pinned_2mib_gbps"], 350.0)
        self.assertGreater(bw["stream_a_pinned_2mib_gbps"], bw["stream_a_unpinned_evicted_2mib_gbps"])
        self.assertGreater(bw["pinned_vs_unpinned_2mib_speedup"], 1.50)
        self.assertGreater(bw["pinned_vs_streaming_speedup"], 1.50)

    def test_05_live_pinned_l2_projector_enclave_parity(self) -> None:
        """Verifies real 384x64 projection matrix packed & executed inside the 2.00 MiB pinned CUDA L2 slab."""
        lp = self.audit["live_pinned_l2_projector"]
        self.assertTrue(lp["active"])
        self.assertEqual(lp["matrix_shape"], [384, 64])
        self.assertEqual(lp["pin_status"], "PINNED_PERSISTING_ACTIVE")
        self.assertLess(lp["max_abs_diff_vs_cpu_f64"], 1e-13)

    def test_06_post_fallback_cuda_zero_sticky_errors(self) -> None:
        """Regression (WORK-ORDER-AG-16): L2 fallback must drain cudaGetLastError so PyTorch CUDA never inherits sticky errors."""
        import torch
        from vmax_alpha.l2_enclave import apply_l2_window_with_fallback, load_libcudart

        libcudart, _ = load_libcudart()
        self.assertIsNotNone(libcudart)
        stream = torch.cuda.Stream(device=0)
        buf = torch.zeros(1024, dtype=torch.float32, device="cuda:0")
        # Trigger a real driver-level cudaErrorInvalidValue via invalid 1 TiB L2 window
        fb = apply_l2_window_with_fallback(
            libcudart,
            int(stream.cuda_stream),
            int(buf.data_ptr()),
            num_bytes=1 << 40,
            hit_ratio=1.0,
            hit_prop=CUDA_ACCESS_PROPERTY_PERSISTING,
        )
        self.assertEqual(fb["status"], "FALLBACK_TO_NORMAL_RECOVERY")
        self.assertTrue(fb["recovered"])
        self.assertEqual(int(libcudart.cudaGetLastError()), 0)

        # Immediately run real PyTorch CUDA embedding kernel (exact failure site on T4 before AG-16)
        weight = torch.randn(32, 16, device="cuda:0", dtype=torch.float32)
        indices = torch.tensor([0, 5, 13, 31], device="cuda:0", dtype=torch.long)
        out = torch.nn.functional.embedding(indices, weight)
        torch.cuda.synchronize()
        self.assertEqual(tuple(out.shape), (4, 16))
        self.assertEqual(int(libcudart.cudaGetLastError()), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
