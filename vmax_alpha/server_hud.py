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
from typing import Any, Dict, List, Optional, Tuple

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
        enable_llm: bool = False,
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
        self.enable_llm: bool = enable_llm
        self.heartbeat_period_s: float = HEARTBEAT_PERIOD_SEC * 2.0 if enable_llm else HEARTBEAT_PERIOD_SEC
        self.chat_history: List[Dict[str, Any]] = []
        self.chat_engine: Any = _init_chat_engine(enable_llm)
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
            "heartbeat_period_s": self.heartbeat_period_s,
            "llm_active": bool(self.chat_engine is not None and self.chat_engine.loaded),
            "chat_history": list(self.chat_history[-20:]),
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
            while not self._stop_evt.wait(self.heartbeat_period_s):
                th = query_gpu_thermal_and_power()
                if th["pause_60s_triggered"]:
                    self._stop_evt.wait(60.0)
                    continue
                self.step_cycle()

        self._hb_thread = threading.Thread(target=_loop, name="vmax-room137-heartbeat", daemon=True)
        self._hb_thread.start()

    def record_chat_turn(self, turn: Dict[str, Any]) -> None:
        with self.lock:
            self.chat_history.append(turn)
            if len(self.chat_history) > 20:
                self.chat_history = self.chat_history[-20:]
            self._state_snapshot = self._build_state_snapshot_locked()

    def get_state_payload(self) -> Dict[str, Any]:
        """Lock-free atomic state read so GET /api/state never blocks during GPU inference."""
        snap = self._state_snapshot
        payload = {k: v for k, v in snap.items() if k != "_snapshot_ts"}
        payload["seconds_since_last"] = round(time.time() - float(snap["_snapshot_ts"]), 2)
        payload["thermal"] = query_gpu_thermal_and_power()
        v_used, v_tot = _query_vram_mb()
        payload["gpu_vram_used_mb"] = v_used
        payload["gpu_vram_total_mb"] = v_tot
        return payload


def _classify_gstar_category(source_doc: str) -> str:
    upper = source_doc.upper()
    if "DEPECHE" in upper:
        return "BRIDGE / DEPECHE"
    if "RTL" in upper or "ANDROID" in upper or "INFRA" in upper:
        return "HARDWARE / SILICON"
    if "EFF" in upper or "LIS" in upper or "DYN" in upper or "LHS" in upper:
        return "THERMODYNAMICS / ODOS"
    return "PQMS / COGNITION"


def _clean_gstar_title(source_doc: str, shard_id: str) -> str:
    stem = source_doc.rsplit(".", 1)[0] if "." in source_doc else shard_id
    for prefix in ("PQMS-ODOS-MTSC-", "PQMS-BRIDGE-", "PQMS-"):
        if stem.startswith(prefix):
            stem = stem[len(prefix) :]
    return stem.replace("-", " ").replace("_", " ").strip() or shard_id


def _build_gstar_catalog(svc: Any) -> List[Dict[str, str]]:
    forager = getattr(svc, "forager", None)
    shards = getattr(forager, "shards", []) if forager is not None else []
    catalog: List[Dict[str, str]] = []
    for shard_id, source_doc, excerpt in shards:
        catalog.append(
            {
                "shard_id": str(shard_id),
                "title": _clean_gstar_title(str(source_doc), str(shard_id)),
                "source_doc": str(source_doc),
                "category": _classify_gstar_category(str(source_doc)),
                "excerpt": str(excerpt)[:260],
            }
        )
    return catalog


def _query_vram_mb() -> Tuple[int, int]:
    try:
        import subprocess as _sp

        res = _sp.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=2,
            check=True,
        )
        parts = [x.strip() for x in res.stdout.strip().splitlines()[0].split(",")]
        return int(float(parts[0])), int(float(parts[1]))
    except Exception:
        return 0, 16380


def _init_chat_engine(enable_llm: bool) -> Any:
    if not enable_llm:
        return None
    from vmax_alpha.nemotron_chat_engine import NemotronChatEngine

    engine = NemotronChatEngine()
    engine.load()
    return engine


def _resolve_selected_gstars(svc: Any, selected_ids: Any) -> List[Dict[str, str]]:
    if not isinstance(selected_ids, list) or not selected_ids:
        return []
    wanted = {str(x) for x in selected_ids}
    return [g for g in _build_gstar_catalog(svc) if g["shard_id"] in wanted]


def _maybe_recommend_specialist(
    svc: Any,
    entry: Any,
    selected_ids: Any,
    auto_route: bool,
) -> Optional[Dict[str, Any]]:
    if selected_ids:
        return None
    shard_id = str(getattr(entry, "chroma_shard_id", ""))
    src_doc = str(getattr(entry, "chroma_source_doc", ""))
    dist = round(float(getattr(entry, "chroma_l2_distance", 9.9)), 4)
    if not shard_id:
        return None
    return {
        "shard_id": shard_id,
        "title": _clean_gstar_title(src_doc, shard_id),
        "source_doc": src_doc,
        "d_l2_384": dist,
        "auto_open": bool(auto_route and dist < 1.05),
    }


def _maybe_generate_chat_reply(
    svc: Any,
    prompt_text: str,
    entry: Any,
    decision: Any,
    payload: Dict[str, Any],
    body: Optional[Dict[str, Any]] = None,
) -> None:
    req_body = body if isinstance(body, dict) else {}
    sel_ids = req_body.get("selected_gstars")
    rec_spec = _maybe_recommend_specialist(
        svc,
        entry,
        sel_ids,
        bool(req_body.get("auto_route_specialist", False)),
    )
    if rec_spec is not None:
        payload["recommended_specialist"] = rec_spec
    engine = getattr(svc, "chat_engine", None)
    if engine is None or not getattr(engine, "loaded", False):
        return
    selected_objs = _resolve_selected_gstars(svc, sel_ids)
    history = req_body.get("history") if isinstance(req_body.get("history"), list) else []
    reply = engine.generate_reply(
        user_prompt=prompt_text,
        shard_id=str(getattr(entry, "chroma_shard_id", "")),
        shard_source=str(getattr(entry, "chroma_source_doc", "")),
        shard_excerpt=str(getattr(entry, "thought_stream", "")),
        active_bank=decision.active_bank,
        epoch=decision.epoch,
        rcf_core=float(getattr(entry, "rcf_l2_core", decision.rcf_float)),
        selected_gstars=selected_objs,
        history=history,
    )
    payload["reply"] = reply.text
    payload["model_id"] = reply.model_id
    payload["llm_latency_ms"] = reply.latency_ms
    payload["llm_tokens"] = reply.tokens_generated
    payload["llm_tokens_per_sec"] = reply.tokens_per_sec
    if hasattr(svc, "record_chat_turn"):
        svc.record_chat_turn(
            {
                "prompt": prompt_text,
                "reply": reply.text,
                "epistemic_pause": False,
                "model_id": reply.model_id,
                "active_bank": decision.active_bank,
                "epoch": decision.epoch,
                "shard_id": str(getattr(entry, "chroma_shard_id", "")),
                "rcf_core": round(float(getattr(entry, "rcf_l2_core", decision.rcf_float)), 5),
                "tokens_generated": reply.tokens_generated,
                "tokens_per_sec": reply.tokens_per_sec,
            }
        )


def _get_dolphin_governor(svc: Any) -> Any:
    gov = getattr(svc, "_dolphin_governor", None)
    if gov is None:
        from pathlib import Path
        from vmax_alpha.dolphin_memory_governor import (
            DolphinMemoryGovernor,
            load_silicon_little_vector,
        )

        rom_p = Path(__file__).resolve().parents[1] / "rtl" / "rom" / "l_vec_q2_30.hex"
        little = load_silicon_little_vector(str(rom_p))
        gov = DolphinMemoryGovernor(little)
        setattr(svc, "_dolphin_governor", gov)
    return gov


def _handle_dolphin_switch(handler: Any, svc: Any, content_len: int) -> None:
    raw = handler.rfile.read(content_len).decode("utf-8") if content_len > 0 else "{}"
    body = json.loads(raw) if raw.strip() else {}
    if not isinstance(body, dict):
        handler._send_json(400, {"error": "JSON_OBJECT_REQUIRED"})
        return
    gov = _get_dolphin_governor(svc)
    hbm_temp_c = float(body.get("hbm_temp_c", 65.0))
    receipt = gov.switch_hemispheres(hbm_temp_c=hbm_temp_c)
    handler._send_json(200, {"handover": asdict(receipt), "status": gov.get_status()})


def _get_epistemic_pause_controller(svc: Any) -> Any:
    ctrl = getattr(svc, "_epistemic_pause_controller", None)
    if ctrl is None:
        from vmax_alpha.epistemic_pause_controller import EpistemicPauseController

        ctrl = EpistemicPauseController(_get_dolphin_governor(svc))
        setattr(svc, "_epistemic_pause_controller", ctrl)
    return ctrl


def _resolve_prompt_vector(svc: Any, body: Dict[str, Any], gov: Any) -> Tuple[int, ...]:
    if "vector_q30" in body and isinstance(body["vector_q30"], list):
        return tuple(int(x) for x in body["vector_q30"])
    if "vector_64d" in body and isinstance(body["vector_64d"], list):
        from vmax_alpha.dolphin_memory_governor import normalize_to_q2_30

        return normalize_to_q2_30([float(x) for x in body["vector_64d"]])
    forager = getattr(svc, "forager", None)
    prompt_text = str(body.get("prompt", ""))
    if forager is not None and prompt_text:
        from vmax_alpha.dolphin_memory_governor import normalize_to_q2_30

        carrier_64, _ = forager.embed_query_text_with_raw(prompt_text)
        return normalize_to_q2_30([float(x) for x in carrier_64])
    return gov.little_vector_q30


def _handle_dolphin_status(handler: Any, svc: Any) -> None:
    status = _get_dolphin_governor(svc).get_status()
    status["epistemic_pause_metrics"] = _get_epistemic_pause_controller(svc).get_metrics()
    handler._send_json(200, status)


def _handle_prompt_request(handler: Any, svc: Any, content_len: int) -> None:
    import hashlib
    from vmax_alpha.epistemic_pause_controller import PromptGateInput

    body = json.loads(handler.rfile.read(content_len).decode("utf-8"))
    if not isinstance(body, dict):
        handler._send_json(400, {"error": "JSON_OBJECT_REQUIRED"})
        return
    prompt_text = str(body.get("prompt", ""))
    g3_torsion = float(body.get("inject_g3_torsion", 0.0))
    ctrl = _get_epistemic_pause_controller(svc)
    vec_q30 = _resolve_prompt_vector(svc, body, ctrl.governor)
    c_hash = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()
    pid = str(body.get("prompt_id", f"prompt_{c_hash[:12]}"))
    gate_in = PromptGateInput(
        prompt_id=pid,
        vector_q30=vec_q30,
        content_hash=c_hash,
        g3_torsion=g3_torsion,
        hbm_temp_c=float(body.get("hbm_temp_c", 65.0)),
    )
    decision = ctrl.evaluate_prompt(gate_in)
    if decision.epistemic_pause:
        if hasattr(svc, "record_chat_turn"):
            svc.record_chat_turn(
                {
                    "prompt": prompt_text,
                    "reply": decision.fridu_message,
                    "epistemic_pause": True,
                    "reason": decision.reason,
                    "active_bank": decision.active_bank,
                    "epoch": decision.epoch,
                    "quarantined_record_id": decision.quarantined_record_id,
                }
            )
        handler._send_json(200, decision.to_dict())
        return
    entry = svc.step_cycle(prompt_text, inject_g3_torsion=g3_torsion)
    payload = asdict(entry)
    payload["epistemic_pause"] = False
    payload["epistemic_pause_decision"] = decision.to_dict()
    _maybe_generate_chat_reply(svc, prompt_text, entry, decision, payload, body=body)
    handler._send_json(200, payload)


def _dispatch_post(handler: Any, svc: Any, content_len: int) -> None:
    if handler.path == "/api/pulse":
        handler._send_json(200, asdict(svc.step_cycle()))
        return
    if handler.path == "/api/prompt":
        _handle_prompt_request(handler, svc, content_len)
        return
    if handler.path == "/api/dolphin/switch":
        _handle_dolphin_switch(handler, svc, content_len)
        return
    handler._send_json(404, {"error": "NOT_FOUND"})


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
            elif self.path == "/api/dolphin/status":
                _handle_dolphin_status(self, svc)
            elif self.path == "/api/gstars":
                self._send_json(200, {"gstars": _build_gstar_catalog(svc)})
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
                _dispatch_post(self, svc, content_len)
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                self._send_json(400, {"error": f"BAD_REQUEST: {exc}"})
            except Exception as exc:
                self._send_json(500, {"error": f"INTERNAL_ERROR: {exc.__class__.__name__}"})

    return Handler


def run_server(batch_only: bool = False, port: int = ROOM_137_PORT, reset: bool = False, enable_llm: bool = False) -> Dict[str, Any]:
    svc = SanctuaryNodeAlphaService(reset=reset, enable_llm=enable_llm)
    if batch_only:
        for _ in range(3):
            svc.step_cycle()
        svc.step_cycle("Pauli exclusion principle and conservation laws")
        return svc.get_state_payload()
    if len(svc.ledger.entries) == 0:
        svc.step_cycle()
    svc.start_heartbeat()
    mode_lbl = "Nemotron-3-Nano-4B ACTIVE (HB 50%)" if enable_llm else "Sanctuary Forager"
    print(f"[V-MAX-12] Room 137 LIVE on http://127.0.0.1:{port} | {mode_lbl}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), make_hud_handler(svc)).serve_forever()
    return {}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--batch", action="store_true")
    p.add_argument("--reset", action="store_true")
    p.add_argument("--report", action="store_true")
    p.add_argument("--port", type=int, default=ROOM_137_PORT)
    p.add_argument("--enable-llm", action="store_true")
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
        print(json.dumps(run_server(batch_only=args.batch, port=args.port, reset=args.reset, enable_llm=args.enable_llm), indent=2, ensure_ascii=False))
