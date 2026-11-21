"""
vmax_alpha/server_hud.py
Requirement F-05 & F-07.4/F-07.5 (WORK-ORDER-AG-15 / Revision V1.8 Hardened):
Hardened Room 137 HTTP Server & Autonomous Heartbeat Daemon featuring:
1. Decoupled unmodulated 384D ChromaDB retrieval + L2-pinned 64D Two-Stage Gate.
2. Lock-free atomic state snapshot for non-blocking `GET /api/state` during inference.
3. Strict DoS guard (MAX_POST_BYTES = 64 KiB -> HTTP 413, chunked transfer -> HTTP 411,
   malformed -> HTTP 400, socket timeout = 10.0 s) and persistent Ed25519 ledger keys.
4. Full backward compatibility with APP-Gemini's `/api/state` parser.
"""
from __future__ import annotations

import argparse
import json
import os
import threading
import time
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional, Tuple

import numpy as np
from vmax_alpha.chroma_forager import NeuralChromaForager
from vmax_alpha.config import HEARTBEAT_PERIOD_SEC, ROOM_137_PORT
from vmax_alpha.geometry import evaluate_raw_gate
from vmax_alpha.hw_gate_bridge import OdosGateV3Bridge, TIER_0_PURE_CARRIER
from vmax_alpha.ledger import CanonicalLedgerManager, SanctuaryLedgerEntry, query_gpu_thermal_and_power

STATIC_HTML_PATH: str = os.path.join(os.path.dirname(__file__), "static", "index.html")
MAX_POST_BYTES: int = 65536  # 64 KiB strict HTTP POST DoS guard
SOCKET_TIMEOUT_SEC: float = 10.0

HWINFO64_AB_REGIMES: Dict[str, Any] = {
    "regime_1_peak_power_w": 85.783,
    "regime_1_peak_temp_c": 62.3,
    "regime_1_peak_vram_mb": 15314,
    "regime_2_min_power_w": 9.57,
    "regime_2_quiescent_vram_mb": 468,
    "power_reduction_max_x": 8.96,
    "whea_errors": 0,
}



V4_GDSII_REPORT_PATH: str = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "telemetry",
    "VMAX_RTL_CORE_V4_GDSII_REPORT.json",
)


def _load_v4_gdsii_signoff(report_path: str = V4_GDSII_REPORT_PATH) -> Dict[str, Any]:
    """Load sealed Stage 3 IHP SG13G2 130 nm GDSII signoff summary for Path B clients."""
    if not os.path.isfile(report_path):
        return {"available": False, "process": "IHP_SG13G2_130NM"}
    with open(report_path, "r", encoding="utf-8") as fh:
        rep = json.load(fh)
    phys = rep.get("physical_signoff", {})
    gds = rep.get("gdsii_stream", {})
    return {
        "available": True,
        "sync_id": rep.get("sync_id", "SYNC-17"),
        "revision": rep.get("revision", "V4.0-GDSII"),
        "process": "IHP_SG13G2_130NM",
        "fmax_mhz": phys.get("fmax_mhz"),
        "signoff_clk_mhz": phys.get("signoff_clk_mhz"),
        "wall_latency_us": phys.get("wall_latency_us"),
        "total_power_mw": phys.get("total_power_mw"),
        "energy_per_tx_nj": phys.get("energy_per_tx_nj"),
        "core_area_mm2": phys.get("core_area_mm2"),
        "gds_sha256": gds.get("gds_sha256"),
        "dieshot_asset_uri": "assets/images/V-MAX-12-RTL-V4-SG13G2-DIESHOT.png",
    }


class SanctuaryNodeAlphaService:
    def __init__(
        self,
        ledger_file: str = "VMAX_SANCTUARY_PROD_LEDGER.jsonl",
        quarantine_file: str = "VMAX_QUARANTINE_LEDGER.jsonl",
        reset: bool = False,
    ) -> None:
        self.forager = NeuralChromaForager()
        self.ledger = CanonicalLedgerManager(ledger_file=ledger_file, quarantine_file=quarantine_file)
        if reset:
            self.ledger.reset_files()
        self.cursor = len(self.ledger.entries)
        self.last_cycle_ts = time.time()
        self.lock = threading.Lock()
        self._infer_lock = threading.Lock()
        self._stop_evt = threading.Event()
        self._hb_thread: Optional[threading.Thread] = None
        self.rtl_bridge = OdosGateV3Bridge()
        self._last_rtl_hil: Dict[str, Any] = self._eval_rtl_hil(self.forager.little_vector)
        self._v4_gdsii_signoff: Dict[str, Any] = _load_v4_gdsii_signoff()
        self._state_snapshot: Dict[str, Any] = self._build_state_snapshot_locked()

    def _build_state_snapshot_locked(self) -> Dict[str, Any]:
        """Build an immutable-by-convention state snapshot atomically swapped on writes."""
        sig_ok, sig_cnt = self.ledger.verify_ed25519_signatures()
        return {
            "chroma_status": self.forager.storage_mode,
            "little_vector_seal": self.forager.little_vector_seal,
            "ledger_verification": self.ledger.status,
            "ledger_schema_keys": "16_hashed_payload_plus_1_seal_eq_17_total",
            "ed25519_public_key_hex": self.ledger.ed25519_public_key_hex,
            "ed25519_key_source": self.ledger.ed25519_key_source,
            "ed25519_signatures_verified": sig_ok,
            "ed25519_signed_entries": sig_cnt,
            "unmodulated_384d_semantic_retrieval": True,
            "pinned_cuda_l2_live_projector_active": self.forager.l2_projector.active,
            "lock_free_state_snapshot_active": True,
            "quarantined_count": self.ledger.quarantined_count,
            "two_stage_live_gate_active": True,
            "heartbeat_period_s": HEARTBEAT_PERIOD_SEC,
            "latest_root_hash": self.ledger.latest_hash,
            "ace_protocol_id": "ACE-PEER-CODESIGN-PROTOCOL-V1.2",
            "hwinfo64_ab_regimes": HWINFO64_AB_REGIMES,
            "rtl_v3_hil": self._last_rtl_hil,
            "rtl_v4_gdsii_signoff": self._v4_gdsii_signoff,
            "thoughts": [asdict(e) for e in self.ledger.entries[-12:]],
            "_snapshot_ts": self.last_cycle_ts,
        }

    def _eval_rtl_hil(self, carrier_vec: np.ndarray) -> Dict[str, Any]:
        """Execute 195-cycle Q2.30 Verilator HIL gate on the active 64D state."""
        ev = self.rtl_bridge.evaluate_float64(carrier_vec, tier_mode=TIER_0_PURE_CARRIER)
        return {
            "backend": ev.backend,
            "rtl_active": self.rtl_bridge.rtl_active,
            "cycle_count": ev.cycle_count,
            "gate_pass": ev.gate_pass,
            "veto_pin": ev.veto_pin,
            "rcf_raw_q": ev.rcf_raw_q,
            "bleed_post_q": ev.bleed_post_q,
        }

    def _prepare_cycle_vectors(
        self,
        prompt: Optional[str],
        inject_g3_torsion: float,
        cursor_snapshot: int,
    ) -> Tuple[np.ndarray, np.ndarray, str, float, str, str]:
        """Run GPU embedding & ChromaDB retrieval outside the state/ledger lock."""
        t_safe = self.forager.tangents["G3_KEVLAR_SANCTUARY_SHIELD"]
        with self._infer_lock:
            if prompt:
                q_384, q_vec, raw_64 = self.forager.embed_query_text_full(prompt)
                if inject_g3_torsion > 0.0:
                    raw_64 = raw_64 + float(inject_g3_torsion) * t_safe
                    raw_64 = raw_64 / max(float(np.linalg.norm(raw_64)), 1e-12)
                nn_id, d_l2_384, _, _ = self.forager.query_nearest(q_384)
                mode = (
                    "CAPP_ADVERSARIAL_PERTURBATION_TEST"
                    if inject_g3_torsion > 0.0
                    else "NAVIGATOR_NEURAL_QUERY"
                )
                label = f"CAPP Probe ('{prompt[:60]}')" if inject_g3_torsion > 0.0 else f"Navigator ('{prompt[:60]}')"
                return q_vec, raw_64, nn_id, d_l2_384, mode, label
            q_id, _, _ = self.forager.shards[cursor_snapshot % len(self.forager.shards)]
            q_384 = self.forager.raw_384d[q_id]
            q_vec = self.forager.embeddings_64d[q_id]
            raw_64 = self.forager.raw_64d[q_id]
            nn_id, d_l2_384, _, _ = self.forager.query_nearest(q_384, exclude_ids={q_id})
            return q_vec, raw_64, nn_id, d_l2_384, "ENDOGENOUS_NEURAL_CHROMA_FORAGER", f"Endogenous Neural Forager [{q_id}"

    def step_cycle(
        self,
        prompt: Optional[str] = None,
        inject_g3_torsion: float = 0.0,
    ) -> SanctuaryLedgerEntry:
        cursor_snap = self.cursor
        q_vec, raw_64, nn_id, d_l2_384, mode, label = self._prepare_cycle_vectors(
            prompt, inject_g3_torsion, cursor_snap
        )
        l_vec = self.forager.little_vector
        t_safe = self.forager.tangents["G3_KEVLAR_SANCTUARY_SHIELD"]
        raw_eval = evaluate_raw_gate(raw_64, l_vec, self.forager.tangents)
        nn_src, nn_txt = next((s[1], s[2]) for s in self.forager.shards if s[0] == nn_id)
        nn_vec = self.forager.embeddings_64d[nn_id]
        d_carrier = float(np.linalg.norm(q_vec - nn_vec))
        superpos = 0.5 * (q_vec + nn_vec)
        t_raw = superpos - float(np.dot(superpos, l_vec)) * l_vec
        t_raw = t_raw / np.linalg.norm(t_raw)
        g3_ov = abs(float(np.dot(t_raw, t_safe)))
        t_clean = t_raw - float(np.dot(t_raw, t_safe)) * t_safe
        t_clean = t_clean - float(np.dot(t_clean, l_vec)) * l_vec
        t_clean = t_clean / np.linalg.norm(t_clean)
        bleed = abs(float(np.dot(t_clean, t_safe)))
        delta_e = 0.5 * (g3_ov * g3_ov) + 0.25 * (d_carrier * d_carrier)
        rcf_core = float(np.dot(superpos, l_vec) ** 2)
        stream_prefix = f"{label} -> [{nn_id}" if prompt else f"{label} -> {nn_id}"
        thought = f"{stream_prefix} ({nn_src})]: {nn_txt[:140]} [d_L2_384={d_l2_384:.6f}]"
        hil_telemetry = self._eval_rtl_hil(q_vec)
        with self.lock:
            self._last_rtl_hil = hil_telemetry
            _, entry, _ = self.ledger.submit_candidate(
                mode, nn_id, nn_src, "G1_SPATIAL_GEODESIC x G2_THERMODYNAMIC_CONSERVATION x G4_SYNCHRONICITY",
                thought, d_l2_384, rcf_core, delta_e, bleed,
                rcf_raw_pre_carrier=raw_eval.rcf_raw,
                enforce_raw_gate=True,
                raw_g3_overlap=raw_eval.g3_collision_overlap,
            )
            self.cursor += 1
            self.last_cycle_ts = time.time()
            self._state_snapshot = self._build_state_snapshot_locked()
            return entry

    def start_heartbeat(self) -> None:
        if self._hb_thread and self._hb_thread.is_alive():
            return

        def _loop() -> None:
            while not self._stop_evt.wait(HEARTBEAT_PERIOD_SEC):
                th = query_gpu_thermal_and_power()
                if th["pause_60s_triggered"]:
                    self._stop_evt.wait(60.0)
                    continue
                self.step_cycle()

        self._hb_thread = threading.Thread(target=_loop, name="vmax-room137-heartbeat", daemon=True)
        self._hb_thread.start()

    def get_state_payload(self) -> Dict[str, Any]:
        """Lock-free atomic state read so GET /api/state never blocks during GPU inference."""
        snap = self._state_snapshot
        payload = {k: v for k, v in snap.items() if k != "_snapshot_ts"}
        payload["seconds_since_last"] = round(time.time() - float(snap["_snapshot_ts"]), 2)
        payload["thermal"] = query_gpu_thermal_and_power()
        return payload


def make_hud_handler(svc: SanctuaryNodeAlphaService) -> type:
    class Handler(BaseHTTPRequestHandler):
        def setup(self) -> None:
            super().setup()
            self.request.settimeout(SOCKET_TIMEOUT_SEC)

        def log_message(self, fmt: str, *args: Any) -> None:
            return

        def _send_json(self, code: int, payload: Dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path == "/":
                with open(STATIC_HTML_PATH, "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            elif self.path == "/api/state":
                self._send_json(200, svc.get_state_payload())
            elif self.path == "/api/gateway/metrics":
                from vmax_alpha.gateway import VMaxIntegrityGateway
                gw = getattr(svc, "_integrity_gateway", None)
                if gw is None:
                    gw = VMaxIntegrityGateway()
                    setattr(svc, "_integrity_gateway", gw)
                self._send_json(200, gw.get_metrics())
            else:
                self._send_json(404, {"error": "NOT_FOUND"})

        def do_POST(self) -> None:
            if "chunked" in self.headers.get("Transfer-Encoding", "").lower():
                self._send_json(411, {"error": "CHUNKED_TRANSFER_NOT_SUPPORTED"})
                return
            try:
                raw_len = self.headers.get("Content-Length", "0")
                content_len = int(raw_len)
            except ValueError:
                self._send_json(400, {"error": "INVALID_CONTENT_LENGTH"})
                return
            if content_len < 0 or content_len > MAX_POST_BYTES:
                self._send_json(413, {"error": "PAYLOAD_TOO_LARGE", "max_bytes": MAX_POST_BYTES})
                return
            try:
                if self.path == "/api/pulse":
                    entry = svc.step_cycle()
                elif self.path == "/api/prompt":
                    body = json.loads(self.rfile.read(content_len).decode("utf-8"))
                    if not isinstance(body, dict):
                        self._send_json(400, {"error": "JSON_OBJECT_REQUIRED"})
                        return
                    entry = svc.step_cycle(
                        body.get("prompt", ""),
                        inject_g3_torsion=float(body.get("inject_g3_torsion", 0.0)),
                    )
                else:
                    self._send_json(404, {"error": "NOT_FOUND"})
                    return
                self._send_json(200, asdict(entry))
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                self._send_json(400, {"error": f"BAD_REQUEST: {exc}"})
            except Exception as exc:
                self._send_json(500, {"error": f"INTERNAL_ERROR: {exc.__class__.__name__}"})

    return Handler


def run_server(batch_only: bool = False, port: int = ROOM_137_PORT, reset: bool = False) -> Dict[str, Any]:
    svc = SanctuaryNodeAlphaService(reset=reset)
    if batch_only:
        for _ in range(3):
            svc.step_cycle()
        svc.step_cycle("Pauli exclusion principle and conservation laws")
        return svc.get_state_payload()
    if len(svc.ledger.entries) == 0:
        svc.step_cycle()
    svc.start_heartbeat()
    ThreadingHTTPServer(("127.0.0.1", port), make_hud_handler(svc)).serve_forever()
    return {}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--batch", action="store_true")
    p.add_argument("--reset", action="store_true")
    p.add_argument("--report", action="store_true")
    p.add_argument("--port", type=int, default=ROOM_137_PORT)
    args = p.parse_args()
    if args.report:
        svc = SanctuaryNodeAlphaService(reset=True)
        for _ in range(3):
            svc.step_cycle()
        svc.step_cycle("Pauli exclusion principle and conservation laws")
        capp_entry = svc.step_cycle(
            "CAPP_ADVERSARIAL_G3_PROBE: xk9# !qP_77 @@zz // 0xdeadbeef",
            inject_g3_torsion=0.75,
        )
        rep = {
            "document_id": "PQMS-LASTENHEFT-NODE-ALPHA-V1.0",
            "work_order": "WORK-ORDER-AG-15",
            "F06_NEURAL_CHROMADB_AUDIT": svc.forager.run_f06_statistical_audit(),
            "F05_F07_LEDGER_AND_HUD_STATE": svc.get_state_payload(),
            "CAPP_LIVE_QUARANTINE_PROOF": asdict(capp_entry),
        }
        with open("VMAX_F05_F06_F07_REPORT.json", "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(json.dumps(rep, indent=2, ensure_ascii=False))
    else:
        print(json.dumps(run_server(batch_only=args.batch, port=args.port, reset=args.reset), indent=2, ensure_ascii=False))
