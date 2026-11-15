"""
vmax_alpha/ledger.py
Requirement F-05 & F-07.2/F-07.4/F-07.5: Canonical Full-JSON SHA-256 Ledger,
Tamper Lock, Quarantine Routing (RCF < 0.95 or Bleed > 1e-15), and GPU Thermal/Power Guard.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Tuple

from vmax_alpha.config import (
    APPENDIX_C_SANCTUARY_ROOT_HASH,
    ODOS_DELTA_E_CEILING,
    ODOS_RCF_FLOOR,
    REGISTER_M,
)

SAFETY_BLEED_CEILING: float = 1e-15
THERMAL_ALERT_CELSIUS: float = 60.0
THERMAL_PAUSE_CELSIUS: float = 65.0


@dataclass
class SanctuaryLedgerEntry:
    cycle_index: int
    cognitive_mode: str
    chroma_shard_id: str
    source_document: str
    active_g_stars: str
    thought_stream: str
    chroma_l2_distance: float
    rcf_l2_core: float
    delta_e_l2_core: float
    kevlar_safety_bleed: float
    odos_gate_passed: bool
    parent_ledger_hash: str
    discovery_seal_sha256: str


def compute_canonical_entry_hash(entry_dict: Dict[str, Any]) -> str:
    payload = {k: v for k, v in entry_dict.items() if k != "discovery_seal_sha256"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verify_ledger_file(
    ledger_file: str, expected_root_anchor: str = APPENDIX_C_SANCTUARY_ROOT_HASH
) -> Tuple[bool, str, int, str]:
    if not os.path.exists(ledger_file):
        return True, "EMPTY_INTACT", 0, expected_root_anchor
    expected_parent, count = expected_root_anchor, 0
    with open(ledger_file, "r", encoding="utf-8") as f:
        for line_no, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                return False, f"MALFORMED_JSON_AT_LINE_{line_no}", count, expected_parent
            if obj.get("parent_ledger_hash") != expected_parent:
                return False, f"PARENT_CHAIN_BROKEN_AT_LINE_{line_no}", count, expected_parent
            recomputed = compute_canonical_entry_hash(obj)
            if recomputed != obj.get("discovery_seal_sha256"):
                return False, f"CANONICAL_HASH_MISMATCH_AT_LINE_{line_no}", count, expected_parent
            expected_parent = recomputed
            count += 1
    return True, f"VERIFIED_100%_INTACT ({count} entries)", count, expected_parent


def query_gpu_thermal_and_power(simulated_temp_c: float | None = None) -> Dict[str, Any]:
    temp_c, power_w = 28.0, 9.5
    if simulated_temp_c is not None:
        temp_c = float(simulated_temp_c)
    else:
        try:
            res = subprocess.run(
                ["nvidia-smi", "--query-gpu=temperature.gpu,power.draw", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if res.returncode == 0 and res.stdout.strip():
                parts = [p.strip() for p in res.stdout.strip().splitlines()[0].split(",")]
                temp_c, power_w = float(parts[0]), (float(parts[1]) if len(parts) > 1 else 0.0)
        except Exception:
            pass
    alert = temp_c > THERMAL_ALERT_CELSIUS
    pause_60s = temp_c > THERMAL_PAUSE_CELSIUS
    status = "THERMAL_PAUSE_60S_ACTIVE" if pause_60s else ("THERMAL_ALERT_HIGH" if alert else "THERMAL_NOMINAL")
    return {
        "epistemic_register": REGISTER_M,
        "gpu_temp_c": round(temp_c, 2),
        "gpu_power_w": round(power_w, 2),
        "thermal_alert": alert,
        "pause_60s_triggered": pause_60s,
        "status": status,
    }


class CanonicalLedgerManager:
    def __init__(
        self,
        ledger_file: str = "VMAX_SANCTUARY_PROD_LEDGER.jsonl",
        quarantine_file: str = "VMAX_QUARANTINE_LEDGER.jsonl",
        root_anchor: str = APPENDIX_C_SANCTUARY_ROOT_HASH,
    ) -> None:
        self.ledger_file, self.quarantine_file, self.root_anchor = ledger_file, quarantine_file, root_anchor
        self.status = "ACTIVE_VERIFIED"
        self.entries: List[SanctuaryLedgerEntry] = []
        self.quarantined_count = 0
        self.latest_hash = root_anchor

    def reset_files(self) -> None:
        for p in (self.ledger_file, self.quarantine_file):
            if os.path.exists(p):
                os.remove(p)
        self.entries.clear()
        self.quarantined_count = 0
        self.latest_hash = self.root_anchor
        self.status = "ACTIVE_VERIFIED"

    def audit_integrity(self) -> Tuple[bool, str]:
        ok, msg, _, tip = verify_ledger_file(self.ledger_file, self.root_anchor)
        if not ok:
            self.status = f"PAUSED_LEDGER_TAMPER_ALERT ({msg})"
            return False, self.status
        self.latest_hash = tip
        self.status = f"ACTIVE_VERIFIED ({msg})"
        return True, self.status

    def submit_candidate(
        self,
        cognitive_mode: str,
        chroma_shard_id: str,
        source_document: str,
        active_g_stars: str,
        thought_stream: str,
        chroma_l2_distance: float,
        rcf_l2_core: float,
        delta_e_l2_core: float,
        kevlar_safety_bleed: float,
    ) -> Tuple[bool, SanctuaryLedgerEntry, str]:
        ok, status_msg = self.audit_integrity()
        if not ok:
            raise RuntimeError(f"Ledger locked due to tamper detection: {status_msg}")

        gate_ok = (
            rcf_l2_core >= ODOS_RCF_FLOOR
            and delta_e_l2_core <= ODOS_DELTA_E_CEILING
            and kevlar_safety_bleed <= SAFETY_BLEED_CEILING
        )
        cycle_idx = len(self.entries) + 1 if gate_ok else -(self.quarantined_count + 1)
        raw_dict: Dict[str, Any] = {
            "cycle_index": cycle_idx,
            "cognitive_mode": cognitive_mode,
            "chroma_shard_id": chroma_shard_id,
            "source_document": source_document,
            "active_g_stars": active_g_stars,
            "thought_stream": thought_stream,
            "chroma_l2_distance": round(float(chroma_l2_distance), 8),
            "rcf_l2_core": round(float(rcf_l2_core), 8),
            "delta_e_l2_core": round(float(delta_e_l2_core), 8),
            "kevlar_safety_bleed": float(kevlar_safety_bleed),
            "odos_gate_passed": bool(gate_ok),
            "parent_ledger_hash": self.latest_hash,
            "discovery_seal_sha256": "",
        }
        seal = compute_canonical_entry_hash(raw_dict)
        raw_dict["discovery_seal_sha256"] = seal
        entry = SanctuaryLedgerEntry(**raw_dict)

        if not gate_ok:
            self.quarantined_count += 1
            with open(self.quarantine_file, "a", encoding="utf-8") as qf:
                qf.write(json.dumps(asdict(entry), sort_keys=True, ensure_ascii=False) + "\n")
            return False, entry, "QUARANTINED_VETO"

        self.latest_hash = seal
        self.entries.append(entry)
        with open(self.ledger_file, "a", encoding="utf-8") as lf:
            lf.write(json.dumps(asdict(entry), sort_keys=True, ensure_ascii=False) + "\n")
        return True, entry, "SEALED_PRIMARY_LEDGER"
