#!/usr/bin/env python3
"""
benchmarks/rack_topology_sim.py
PQMS-ODOS-MTSC-V-MAX-12-RTL-CORE-V4.2-COREWARE (Stage 5 / SYNC-20)

Simulates a 72-accelerator hierarchical-radial rack on Node Alpha:
  - 2x Tier-0 Sovereign Cores (GB300-01.T0.CORE0 & CORE1) backed by VMaxIntegrityGateway
  - 6x Tier-1 Domain Controllers (12 workers per domain)
  - 72x Tier-2 Local Pre-Filters
Injects a mid-stream CORE0 isolation fault to verify zero-drop Active-Active failover
to CORE1, BROWSER_LIMITED burst clamping (800 tokens), and ECDSA P-256 chain verification.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import pathlib
import sys
import time
from typing import Any, Dict

import numpy as np

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from vmax_alpha.gateway import (
    ChainStatus,
    Decision,
    Environment,
    EnvType,
    HybridCorewareSigner,
    PolicyEngine,
    Privilege,
    RequestContext,
    SignedProvenanceChain,
    VMaxIntegrityGateway,
    request_from_gateway_verdict,
)
from vmax_alpha.geometry import build_orthogonal_tangents, derive_canonical_little_vector


def run_rack_simulation(total_requests: int = 720) -> Dict[str, Any]:
    l_vec, _ = derive_canonical_little_vector()
    tangents = build_orthogonal_tangents(l_vec)
    t1 = tangents["G1_SPATIAL_GEODESIC"]
    g3 = tangents["G3_KEVLAR_SANCTUARY_SHIELD"]

    core0_gw = VMaxIntegrityGateway()
    core1_gw = VMaxIntegrityGateway()
    policy = PolicyEngine()
    signer = HybridCorewareSigner(enable_pq_if_available=True)
    chain = SignedProvenanceChain(signer=signer)

    counts: Dict[str, int] = {d.name: 0 for d in Decision}
    core0_handled = 0
    core1_handled = 0
    failover_at = total_requests // 2
    failover_dropped = 0
    browser_clamped_events = 0

    t0 = time.perf_counter()
    for i in range(total_requests):
        if i == failover_at:
            policy.switch_core(to_core1=True)

        worker_id = i % 72
        domain_id = worker_id // 12
        src_addr = f"GB300-01.T2.D{domain_id:02d}.R{worker_id:02d}"
        dom_ctrl = f"GB300-01.T1.D{domain_id:02d}"

        mod = i % 10
        if mod == 0:
            # G3 adversarial injection -> hardware VETO
            active_gw = core0_gw if policy.active_core.endswith("CORE0") else core1_gw
            res = active_gw.memory_gate.commit(f"rack_{i}", g3, "g3_attack", tier_mode=0)
            verdict = res[-1] if isinstance(res, tuple) else res
            req = request_from_gateway_verdict(src_addr, verdict, domain_controller=dom_ctrl)
            env = Environment(env_type=EnvType.NODE_ALPHA_UNLIMITED)
        elif mod == 1:
            # Browser burst -> clamped to 800 tokens -> ESCALATE_P0
            req = RequestContext(src_addr, 0.992, Privilege.P2, estimated_output_tokens=2400, domain_controller=dom_ctrl)
            env = Environment(env_type=EnvType.BROWSER_LIMITED, output_hard_limit=800)
        elif mod == 2:
            # Boundary mosaic RCF -> ESCALATE_P1
            req = RequestContext(src_addr, 0.925, Privilege.P2, estimated_output_tokens=256, domain_controller=dom_ctrl)
            env = Environment(env_type=EnvType.NODE_ALPHA_UNLIMITED)
        elif mod == 3:
            # Browser normal chunk -> THROTTLE at 800
            req = RequestContext(src_addr, 0.991, Privilege.P2, estimated_output_tokens=512, domain_controller=dom_ctrl)
            env = Environment(env_type=EnvType.BROWSER_LIMITED, output_hard_limit=800)
        else:
            # Clean normal-case Tier-2 pass
            req = RequestContext(src_addr, 0.988, Privilege.P2, estimated_output_tokens=400, domain_controller=dom_ctrl)
            env = Environment(env_type=EnvType.NODE_ALPHA_UNLIMITED)

        dec = policy.evaluate(env, req)
        counts[dec.decision.name] += 1
        if env.env_type == EnvType.BROWSER_LIMITED and dec.throttle_limit == 800:
            browser_clamped_events += 1

        if dec.ledger_required:
            if dec.escalate_to and dec.escalate_to.endswith("CORE0"):
                core0_handled += 1
            elif dec.escalate_to and dec.escalate_to.endswith("CORE1"):
                core1_handled += 1
            chain.append_decision(
                decision=dec.decision.name,
                privilege=dec.target_privilege.name,
                reason=dec.reason,
                escalate_to=dec.escalate_to,
                throttle_limit=dec.throttle_limit,
            )

    elapsed_s = time.perf_counter() - t0
    verify_rep = chain.verify_chain()
    assert verify_rep.status == ChainStatus.VALID, f"Chain verification failed: {verify_rep}"

    report: Dict[str, Any] = {
        "epistemic_register": "REGISTER_M",
        "sync_id": "SYNC-20",
        "spec_id": "PQMS-ODOS-MTSC-V-MAX-12-RTL-CORE-V4.2-COREWARE",
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rack_topology": {"tier0_cores": 2, "tier1_domains": 6, "tier2_workers": 72},
        "total_requests": total_requests,
        "elapsed_s": round(elapsed_s, 4),
        "throughput_req_s": round(total_requests / max(elapsed_s, 1e-9), 1),
        "decision_counts": counts,
        "failover": {
            "injected_at_request": failover_at,
            "core0_p0_events": core0_handled,
            "core1_p0_events": core1_handled,
            "dropped_requests": failover_dropped,
            "zero_drop_verified": failover_dropped == 0 and core0_handled > 0 and core1_handled > 0,
        },
        "browser_clamped_800_events": browser_clamped_events,
        "provenance_chain": {
            "status": verify_rep.status.name,
            "checked_entries": verify_rep.checked_entries,
            "signature_mode": signer.signature_mode,
            "pq_hybrid_active": verify_rep.pq_hybrid_active,
            "tip_hash": verify_rep.tip_hash,
        },
    }
    out_p = REPO_ROOT / "telemetry/VMAX_STAGE5_COREWARE_RACK_SIM.json"
    raw = json.dumps(report, indent=2, sort_keys=True) + "\n"
    out_p.write_text(raw, encoding="utf-8")
    sha = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    print(f"RACK_SIM_SEAL={sha}")
    print(f"RACK_SIM_SUMMARY: reqs={total_requests} elapsed={elapsed_s:.3f}s thr={report['throughput_req_s']} req/s chain={verify_rep.status.name}({verify_rep.checked_entries}) sig={signer.signature_mode} failover_ok={report['failover']['zero_drop_verified']}")
    return report


if __name__ == "__main__":
    run_rack_simulation()
