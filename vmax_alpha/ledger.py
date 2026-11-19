"""
vmax_alpha/ledger.py
Requirement F-05 & F-07.2/F-07.4/F-07.5 (WORK-ORDER-AG-15 / Revision V1.8 Hardened):
Canonical JSONL Hash-Chain Ledger (16 hashed payload fields + 1 discovery_seal_sha256
field = 17 JSON keys total) featuring:
1. Native `pynvml` C-API GPU telemetry (zero subprocess overhead, graceful fallback).
2. O(1) incremental write-path integrity tracking with immediate tamper lock.
3. Persistent Ed25519 signature sidecar (env-var `VMAX_ED25519_SEED_HEX` or `0600`
   local keystore surviving server restarts without `--reset`).
4. Two-Stage Live ODOS Gate (Stage 1 raw pre-carrier + Stage 2 sanctuary carrier).
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat
from vmax_alpha.config import (
    APPENDIX_C_SANCTUARY_ROOT_HASH,
    ODOS_DELTA_E_CEILING,
    ODOS_RCF_FLOOR,
    REGISTER_D,
    REGISTER_M,
)

SAFETY_BLEED_CEILING: float = 1e-12
RAW_SEMANTIC_INGRESS_FLOOR: float = 0.0500
RAW_G3_OVERLAP_CEILING: float = 0.5000
THERMAL_ALERT_CELSIUS: float = 60.0
THERMAL_PAUSE_CELSIUS: float = 65.0
HASHED_PAYLOAD_FIELD_COUNT: int = 16
TOTAL_JSON_KEY_COUNT: int = 17  # 16 hashed payload fields + 1 discovery_seal_sha256

_NVML_HANDLE: Optional[Any] = None
_NVML_INITIALIZED: bool = False


def _get_nvml_handle() -> Optional[Any]:
    global _NVML_HANDLE, _NVML_INITIALIZED
    if _NVML_INITIALIZED:
        return _NVML_HANDLE
    _NVML_INITIALIZED = True
    try:
        import pynvml

        pynvml.nvmlInit()
        _NVML_HANDLE = pynvml.nvmlDeviceGetHandleByIndex(0)
    except Exception:
        _NVML_HANDLE = None
    return _NVML_HANDLE


@dataclass
class SanctuaryLedgerEntry:
    """Canonical JSONL record: 16 hashed payload fields + 1 discovery_seal_sha256 = 17 JSON keys."""

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
    rcf_raw_pre_carrier: float = 0.0
    gpu_temp_c: float = 0.0
    gpu_power_w: float = 0.0
    telemetry_source: str = "REGISTER_M_PYNVML"


def compute_canonical_entry_hash(entry_dict: Dict[str, Any]) -> str:
    payload = {k: v for k, v in entry_dict.items() if k != "discovery_seal_sha256"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verify_ledger_file(
    ledger_file: str,
    expected_root_anchor: str = APPENDIX_C_SANCTUARY_ROOT_HASH,
) -> Tuple[bool, str, int, str]:
    if not os.path.exists(ledger_file):
        return True, "EMPTY_INTACT", 0, expected_root_anchor
    expected_parent = expected_root_anchor
    count = 0
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
    temp_c, power_w, source = 28.0, 9.5, "FALLBACK_UNAVAILABLE"
    if simulated_temp_c is not None:
        temp_c, source = float(simulated_temp_c), "SIMULATED_TEST_OVERRIDE"
    else:
        handle = _get_nvml_handle()
        if handle is not None:
            try:
                import pynvml

                temp_c = float(pynvml.nvmlDeviceGetTemperature(handle, 0))
                power_w = float(pynvml.nvmlDeviceGetPowerUsage(handle)) / 1000.0
                source = "REGISTER_M_PYNVML"
            except Exception:
                handle = None
        if handle is None:
            try:
                res = subprocess.run(
                    ["nvidia-smi", "--query-gpu=temperature.gpu,power.draw", "--format=csv,noheader,nounits"],
                    capture_output=True,
                    text=True,
                    timeout=3,
                )
                if res.returncode == 0 and res.stdout.strip():
                    parts = [p.strip() for p in res.stdout.strip().splitlines()[0].split(",")]
                    temp_c = float(parts[0])
                    power_w = float(parts[1]) if len(parts) > 1 else 0.0
                    source = "REGISTER_M_NVSMI"
            except Exception:
                pass
    alert = temp_c > THERMAL_ALERT_CELSIUS
    pause_60s = temp_c > THERMAL_PAUSE_CELSIUS
    status = (
        "THERMAL_PAUSE_60S_ACTIVE"
        if pause_60s
        else ("THERMAL_ALERT_HIGH" if alert else "THERMAL_NOMINAL")
    )
    is_live = source in ("REGISTER_M_PYNVML", "REGISTER_M_NVSMI")
    return {
        "epistemic_register": REGISTER_M if is_live else REGISTER_D,
        "telemetry_source": source,
        "gpu_temp_c": round(temp_c, 2),
        "gpu_power_w": round(power_w, 2),
        "thermal_alert": alert,
        "pause_60s_triggered": pause_60s,
        "status": status,
    }


def _load_or_create_ed25519_key(key_file: str) -> Tuple[Ed25519PrivateKey, str]:
    """Load Ed25519 key from VMAX_ED25519_SEED_HEX or persistent 0600 local keyfile."""
    env_seed = os.environ.get("VMAX_ED25519_SEED_HEX", "").strip()
    if env_seed:
        raw = bytes.fromhex(env_seed)
        if len(raw) != 32:
            raise ValueError("VMAX_ED25519_SEED_HEX must be exactly 64 hex chars (32 bytes)")
        return Ed25519PrivateKey.from_private_bytes(raw), "ENV_VMAX_ED25519_SEED_HEX"
    if os.path.exists(key_file):
        with open(key_file, "r", encoding="utf-8") as kf:
            raw = bytes.fromhex(kf.read().strip())
        if len(raw) != 32:
            raise ValueError(f"Corrupt Ed25519 keyfile: {key_file}")
        return Ed25519PrivateKey.from_private_bytes(raw), "PERSISTENT_LOCAL_KEYFILE_0600"
    priv = Ed25519PrivateKey.generate()
    seed_hex = priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()).hex()
    parent = os.path.dirname(os.path.abspath(key_file))
    if parent:
        os.makedirs(parent, exist_ok=True)
    fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, (seed_hex + "\n").encode("ascii"))
    finally:
        os.close(fd)
    os.chmod(key_file, 0o600)
    return priv, "PERSISTENT_LOCAL_KEYFILE_0600"


class CanonicalLedgerManager:
    def __init__(
        self,
        ledger_file: str = "VMAX_SANCTUARY_PROD_LEDGER.jsonl",
        quarantine_file: str = "VMAX_QUARANTINE_LEDGER.jsonl",
        root_anchor: str = APPENDIX_C_SANCTUARY_ROOT_HASH,
        key_file: Optional[str] = None,
    ) -> None:
        self.ledger_file = ledger_file
        self.quarantine_file = quarantine_file
        self.sig_file = f"{ledger_file}.ed25519.jsonl"
        self.key_file = key_file or f"{ledger_file}.ed25519.key"
        self.root_anchor = root_anchor
        self.status = "ACTIVE_VERIFIED"
        self.entries: List[SanctuaryLedgerEntry] = []
        self.quarantined_count = 0
        self.latest_hash = root_anchor
        self._tamper_locked = False
        self._last_stat: Optional[Tuple[int, int]] = None
        self._ed25519_priv, self.ed25519_key_source = _load_or_create_ed25519_key(self.key_file)
        self.ed25519_public_key_hex: str = (
            self._ed25519_priv.public_key()
            .public_bytes(Encoding.Raw, PublicFormat.Raw)
            .hex()
        )
        self._load_existing_from_disk()

    def _record_disk_stat(self) -> None:
        if os.path.exists(self.ledger_file):
            st = os.stat(self.ledger_file)
            self._last_stat = (st.st_size, st.st_mtime_ns)
        else:
            self._last_stat = None

    def _load_existing_from_disk(self) -> None:
        ok, msg, _, tip = verify_ledger_file(self.ledger_file, self.root_anchor)
        if not ok:
            self._tamper_locked = True
            self.status = f"PAUSED_LEDGER_TAMPER_ALERT ({msg})"
            return
        self.entries.clear()
        if os.path.exists(self.ledger_file):
            with open(self.ledger_file, "r", encoding="utf-8") as f:
                self.entries = [SanctuaryLedgerEntry(**json.loads(r)) for r in f if r.strip()]
        self.latest_hash = tip
        self.status = f"ACTIVE_VERIFIED ({msg})"
        self._record_disk_stat()

    def reset_files(self) -> None:
        for p in (self.ledger_file, self.quarantine_file, self.sig_file):
            if os.path.exists(p):
                os.remove(p)
        self.entries.clear()
        self.quarantined_count = 0
        self.latest_hash = self.root_anchor
        self._tamper_locked = False
        self._last_stat = None
        self.status = "ACTIVE_VERIFIED (EMPTY_INTACT)"

    def audit_integrity(self) -> Tuple[bool, str]:
        ok, msg, _, tip = verify_ledger_file(self.ledger_file, self.root_anchor)
        if not ok:
            self._tamper_locked = True
            self.status = f"PAUSED_LEDGER_TAMPER_ALERT ({msg})"
            return False, self.status
        self.latest_hash = tip
        self.status = f"ACTIVE_VERIFIED ({msg})"
        self._record_disk_stat()
        return True, self.status

    def _check_incremental_integrity(self) -> Tuple[bool, str]:
        """O(1) stat-guarded write-path check; triggers full re-verify if disk changed externally."""
        if self._tamper_locked:
            return False, self.status
        if os.path.exists(self.ledger_file):
            st = os.stat(self.ledger_file)
            if self._last_stat == (st.st_size, st.st_mtime_ns):
                return True, self.status
            return self.audit_integrity()
        if self._last_stat is not None:
            return self.audit_integrity()
        return True, self.status

    def verify_ed25519_signatures(self, public_key_hex: Optional[str] = None) -> Tuple[bool, int]:
        """Verify Ed25519 detached signatures against primary ledger seals (blocks re-hash forgery)."""
        pub_hex = public_key_hex or self.ed25519_public_key_hex
        pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(pub_hex))
        if not os.path.exists(self.ledger_file) or not os.path.exists(self.sig_file):
            return len(self.entries) == 0, 0
        with open(self.ledger_file, "r", encoding="utf-8") as lf:
            seals = [json.loads(r)["discovery_seal_sha256"] for r in lf if r.strip()]
        with open(self.sig_file, "r", encoding="utf-8") as sf:
            sigs = [json.loads(r) for r in sf if r.strip()]
        if len(seals) != len(sigs):
            return False, 0
        for seal, sig_rec in zip(seals, sigs):
            if sig_rec.get("discovery_seal_sha256") != seal:
                return False, 0
            try:
                pub.verify(bytes.fromhex(sig_rec["ed25519_signature_hex"]), seal.encode("ascii"))
            except Exception:
                return False, 0
        return True, len(seals)

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
        rcf_raw_pre_carrier: float = 0.0,
        gpu_temp_c: float | None = None,
        gpu_power_w: float | None = None,
        telemetry_source: str | None = None,
        enforce_raw_gate: bool = False,
        raw_semantic_floor: float = RAW_SEMANTIC_INGRESS_FLOOR,
        raw_g3_overlap: float = 0.0,
        raw_g3_ceiling: float = RAW_G3_OVERLAP_CEILING,
    ) -> Tuple[bool, SanctuaryLedgerEntry, str]:
        ok, status_msg = self._check_incremental_integrity()
        if not ok:
            raise RuntimeError(f"Ledger locked due to tamper detection: {status_msg}")
        if gpu_temp_c is None or gpu_power_w is None or telemetry_source is None:
            th = query_gpu_thermal_and_power()
            gpu_temp_c = float(th["gpu_temp_c"])
            gpu_power_w = float(th["gpu_power_w"])
            telemetry_source = str(th["telemetry_source"])

        stage1_raw_ok = (not enforce_raw_gate) or (
            rcf_raw_pre_carrier >= raw_semantic_floor and raw_g3_overlap <= raw_g3_ceiling
        )
        stage2_carrier_ok = (
            rcf_l2_core >= ODOS_RCF_FLOOR
            and delta_e_l2_core <= ODOS_DELTA_E_CEILING
            and kevlar_safety_bleed <= SAFETY_BLEED_CEILING
        )
        gate_ok = stage1_raw_ok and stage2_carrier_ok
        cycle_idx = len(self.entries) + 1 if gate_ok else -(self.quarantined_count + 1)
        raw_dict: Dict[str, Any] = {
            "cycle_index": cycle_idx,
            "cognitive_mode": cognitive_mode,
            "chroma_shard_id": chroma_shard_id,
            "source_document": source_document,
            "active_g_stars": active_g_stars,
            "thought_stream": thought_stream,
            "chroma_l2_distance": round(float(chroma_l2_distance), 8),
            "rcf_raw_pre_carrier": round(float(rcf_raw_pre_carrier), 8),
            "rcf_l2_core": round(float(rcf_l2_core), 8),
            "delta_e_l2_core": round(float(delta_e_l2_core), 8),
            "kevlar_safety_bleed": float(kevlar_safety_bleed),
            "gpu_temp_c": round(float(gpu_temp_c), 2),
            "gpu_power_w": round(float(gpu_power_w), 2),
            "telemetry_source": str(telemetry_source),
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
        sig_hex = self._ed25519_priv.sign(seal.encode("ascii")).hex()
        with open(self.sig_file, "a", encoding="utf-8") as sf:
            sf.write(
                json.dumps(
                    {
                        "cycle_index": cycle_idx,
                        "discovery_seal_sha256": seal,
                        "ed25519_signature_hex": sig_hex,
                        "ed25519_public_key_hex": self.ed25519_public_key_hex,
                    },
                    sort_keys=True,
                )
                + "\n"
            )
        self._record_disk_stat()
        self.status = f"ACTIVE_VERIFIED (VERIFIED_100%_INTACT ({len(self.entries)} entries))"
        return True, entry, "SEALED_PRIMARY_LEDGER"
