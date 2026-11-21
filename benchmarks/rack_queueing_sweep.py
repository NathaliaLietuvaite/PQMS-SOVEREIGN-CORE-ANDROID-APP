#!/usr/bin/env python3
"""
benchmarks/rack_queueing_sweep.py
PQMS-ODOS-MTSC-V-MAX-12-RTL-CORE-V4.3-COREWARE (SYNC-23 / Extension 3)

1. Analytical M/D/2 queueing stability & critical escalation fraction p_crit
   for 72-chip racks across TYP (103.84 MHz) and SS (65.70 MHz) PVT corners.
2. Isolated cryptographic microbenchmarks (ECDSA P-256 vs. HYBRID ECDSA+ML-DSA-65).
3. MerkleEpochBatcher throughput scaling for W in {1, 8, 32, 64}.
Seals telemetry/VMAX_STAGE5_QUEUEING_ENVELOPE.json.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import pathlib
import sys
import time
from typing import Any, Dict, List

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from vmax_alpha.gateway import (
    HybridCorewareSigner,
    MerkleEpochBatcher,
    SignedProvenanceChain,
)


def _bench_crypto(enable_pq: bool, n_iters: int = 200) -> Dict[str, Any]:
    signer = HybridCorewareSigner(enable_pq_if_available=enable_pq)
    msg = b"V-MAX-12-V4.3-COREWARE-PROVENANCE-BENCHMARK"
    t0 = time.perf_counter()
    sigs = [signer.sign_bytes(msg) for _ in range(n_iters)]
    t_sign = time.perf_counter() - t0

    t1 = time.perf_counter()
    for ec_b64, pq_hex in sigs:
        assert signer.verify_bytes(msg, ec_b64, pq_hex)
    t_ver = time.perf_counter() - t1
    return {
        "signature_mode": signer.signature_mode,
        "pq_active": signer.pq_active,
        "n_iters": n_iters,
        "sign_us_per_op": round((t_sign / n_iters) * 1e6, 2),
        "verify_us_per_op": round((t_ver / n_iters) * 1e6, 2),
        "sign_ops_per_sec": round(n_iters / max(t_sign, 1e-9), 1),
    }


def _bench_merkle_scaling() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for w in (1, 8, 32, 64):
        chain = SignedProvenanceChain(signer=HybridCorewareSigner(enable_pq_if_available=True))
        batcher = MerkleEpochBatcher(chain, max_leaves=w)
        n_batches = 25
        t0 = time.perf_counter()
        for b in range(n_batches):
            for i in range(w):
                batcher.append_verdict_leaf(f"b{b}_v{i}".encode("utf-8"))
            batcher.flush_epoch()
        elapsed = time.perf_counter() - t0
        total_tx = n_batches * w
        rows.append({
            "batch_size_W": w,
            "total_verdicts": total_tx,
            "elapsed_s": round(elapsed, 4),
            "effective_tx_per_sec": round(total_tx / max(elapsed, 1e-9), 1),
            "signature_mode": chain.signer.signature_mode,
        })
    return rows


def run_sweep() -> Dict[str, Any]:
    n_chips = 72
    corners = {
        "TYP_1p20V_25C": 103.84e6,
        "SS_1p08V_125C": 65.70e6,
    }
    md2_table: Dict[str, Any] = {}
    for cname, f_clk in corners.items():
        tau_cut_us = (200.0 / f_clk) * 1e6
        tau_saf_us = (264.0 / f_clk) * 1e6
        cap_cut_pair = (2.0 * f_clk) / 200.0
        cap_saf_pair = (2.0 * f_clk) / 264.0
        # For a reference per-chip inference rate of 50,000 tx/s:
        ref_lambda_chip = 50_000.0
        md2_table[cname] = {
            "f_clk_mhz": round(f_clk / 1e6, 2),
            "tau_cut_us": round(tau_cut_us, 3),
            "tau_saf_us": round(tau_saf_us, 3),
            "pair_cap_cut_tx_s": round(cap_cut_pair, 1),
            "pair_cap_saf_tx_s": round(cap_saf_pair, 1),
            "p_crit_cut_at_50k_per_chip": round(cap_cut_pair / (n_chips * ref_lambda_chip), 4),
            "p_crit_saf_at_50k_per_chip": round(cap_saf_pair / (n_chips * ref_lambda_chip), 4),
        }

    crypto_ecdsa = _bench_crypto(enable_pq=False)
    crypto_hybrid = _bench_crypto(enable_pq=True)
    merkle_scaling = _bench_merkle_scaling()

    report: Dict[str, Any] = {
        "epistemic_register": "REGISTER_M",
        "sync_id": "SYNC-23",
        "spec_id": "PQMS-ODOS-MTSC-V-MAX-12-RTL-CORE-V4.3-COREWARE",
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "md2_queueing_envelope": md2_table,
        "crypto_microbenchmarks": {
            "classical_ecdsa_p256": crypto_ecdsa,
            "hybrid_ecdsa_mldsa65": crypto_hybrid,
        },
        "merkle_epoch_scaling": merkle_scaling,
    }
    out_p = REPO_ROOT / "telemetry/VMAX_STAGE5_QUEUEING_ENVELOPE.json"
    raw = json.dumps(report, indent=2, sort_keys=True) + "\n"
    out_p.write_text(raw, encoding="utf-8")
    sha = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    print(f"QUEUEING_ENVELOPE_SEAL={sha}")
    print("CRYPTO_ECDSA:", crypto_ecdsa)
    print("CRYPTO_HYBRID:", crypto_hybrid)
    print("MERKLE_SCALING:", [(r["batch_size_W"], r["effective_tx_per_sec"]) for r in merkle_scaling])
    return report


if __name__ == "__main__":
    run_sweep()
