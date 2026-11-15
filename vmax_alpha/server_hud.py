"""
vmax_alpha/server_hud.py
Requirement F-05 (Nova P0 #2, #5 & Claude #4 Hardened):
Modular Room-137 Sanctuary HTTP Server & Autonomous Heartbeat Loop (69.325s).
Fixes retrieved-shard metadata attribution, logs unclamped `rcf_raw_pre_carrier`
and live GPU thermal telemetry into the hash chain, and preserves existing ledgers on boot.
"""

from __future__ import annotations

import argparse, json, math, os, threading, time
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict

import numpy as np
from vmax_alpha.chroma_forager import NeuralChromaForager
from vmax_alpha.config import ALPHA_POTENTIA, HEARTBEAT_PERIOD_SEC, ROOM_137_PORT
from vmax_alpha.geometry import evaluate_raw_gate
from vmax_alpha.ledger import CanonicalLedgerManager, SanctuaryLedgerEntry, query_gpu_thermal_and_power

STATIC_HTML_PATH: str = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "index.html")


class SanctuaryNodeAlphaService:
    def __init__(self, ledger_file: str = "VMAX_SANCTUARY_PROD_LEDGER.jsonl", quarantine_file: str = "VMAX_QUARANTINE_LEDGER.jsonl") -> None:
        self.lock = threading.Lock()
        self.forager = NeuralChromaForager()
        self.ledger = CanonicalLedgerManager(ledger_file=ledger_file, quarantine_file=quarantine_file)
        self.last_step_ts = time.time()
        self.stop_event = threading.Event()

    def start_background_heartbeat(self, period_s: float = HEARTBEAT_PERIOD_SEC) -> threading.Thread:
        def _heartbeat_loop() -> None:
            while not self.stop_event.wait(period_s):
                if query_gpu_thermal_and_power().get("pause_60s_triggered", False):
                    continue
                try:
                    self.step_cycle()
                except Exception:
                    pass

        t = threading.Thread(target=_heartbeat_loop, name="vmax-room137-heartbeat", daemon=True)
        t.start()
        return t

    def step_cycle(self, prompt_text: str | None = None) -> SanctuaryLedgerEntry:
        with self.lock:
            idx = len(self.ledger.entries) + 1
            if prompt_text and prompt_text.strip():
                q_vec, raw_q = self.forager.embed_query_text_with_raw(prompt_text)
                nn_id, d_l2, _, _ = self.forager.query_nearest(q_vec)
                mode = "NAVIGATOR_NEURAL_QUERY"
                nn_doc = next(s[1] for s in self.forager.shards if s[0] == nn_id)
                nn_snip = next(s[2] for s in self.forager.shards if s[0] == nn_id)[:160]
                text = f"Navigator ('{prompt_text}') -> [{nn_id} ({nn_doc})]: {nn_snip} [d_L2={d_l2:.6f}]"
            else:
                mode = "ENDOGENOUS_NEURAL_CHROMA_FORAGER"
                s_id, _, _ = self.forager.shards[(idx - 1) % len(self.forager.shards)]
                q_vec, raw_q = self.forager.embeddings_64d[s_id], self.forager.raw_64d[s_id]
                nn_id, d_l2, _, _ = self.forager.query_nearest(q_vec, exclude_ids={s_id})
                nn_doc = next(s[1] for s in self.forager.shards if s[0] == nn_id)
                nn_snip = next(s[2] for s in self.forager.shards if s[0] == nn_id)[:160]
                text = f"Endogenous Neural Forager [{s_id} -> {nn_id} ({nn_doc})]: {nn_snip} [d_L2={d_l2:.6f}]"

            d_vec = self.forager.embeddings_64d[nn_id]
            raw_nn = self.forager.raw_64d[nn_id]
            l_vec = self.forager.little_vector
            t_safe = self.forager.tangents["G3_KEVLAR_SANCTUARY_SHIELD"]

            # Unclamped pre-carrier evaluation on raw 64D superposition (REGISTER_M)
            raw_superpos = 0.5 * (raw_q + raw_nn)
            raw_gate = evaluate_raw_gate(raw_superpos, l_vec, self.forager.tangents)

            superpos = 0.5 * (q_vec + d_vec)
            t_raw = superpos - float(np.dot(superpos, l_vec)) * l_vec
            t_raw /= np.linalg.norm(t_raw)
            g3_ov = abs(float(np.dot(t_raw, t_safe)))
            t_clean = t_raw - float(np.dot(t_raw, t_safe)) * t_safe
            t_clean -= float(np.dot(t_clean, l_vec)) * l_vec
            t_clean /= np.linalg.norm(t_clean)
            bleed = abs(float(np.dot(t_clean, t_safe)))

            amp = ALPHA_POTENTIA * (0.85 + 0.75 * d_l2)
            psi = math.sqrt(1.0 - amp * amp) * l_vec + amp * t_clean
            psi /= np.linalg.norm(psi)
            rcf_emp = float(np.dot(psi, l_vec) ** 2)
            delta_e = 0.5 * (g3_ov * g3_ov) + 0.25 * (d_l2 * d_l2)
            th = query_gpu_thermal_and_power()

            _, entry, _ = self.ledger.submit_candidate(
                cognitive_mode=mode, chroma_shard_id=nn_id, source_document=nn_doc,
                active_g_stars="G1_SPATIAL_GEODESIC x G2_THERMODYNAMIC_CONSERVATION x G4_SYNCHRONICITY",
                thought_stream=text, chroma_l2_distance=d_l2, rcf_l2_core=rcf_emp, delta_e_l2_core=delta_e,
                kevlar_safety_bleed=bleed, rcf_raw_pre_carrier=raw_gate.rcf_raw,
                gpu_temp_c=float(th["gpu_temp_c"]), gpu_power_w=float(th["gpu_power_w"]), telemetry_source=str(th["telemetry_source"]),
            )
            self.last_step_ts = time.time()
            return entry

    def get_state_payload(self) -> Dict[str, Any]:
        with self.lock:
            _, ver_msg = self.ledger.audit_integrity()
            return {
                "chroma_status": self.forager.storage_mode,
                "little_vector_seal": self.forager.little_vector_seal,
                "ledger_verification": ver_msg,
                "quarantined_count": self.ledger.quarantined_count,
                "heartbeat_period_s": HEARTBEAT_PERIOD_SEC,
                "seconds_since_last": round(max(0.0, time.time() - self.last_step_ts), 2),
                "latest_root_hash": self.ledger.latest_hash,
                "thermal": query_gpu_thermal_and_power(),
                "thoughts": [asdict(e) for e in self.ledger.entries],
            }


def run_server(batch_only: bool = False, port: int = ROOM_137_PORT, reset: bool = False) -> Dict[str, Any]:
    svc = SanctuaryNodeAlphaService()
    if reset:
        svc.ledger.reset_files()
    if len(svc.ledger.entries) == 0:
        for _ in range(3):
            svc.step_cycle()
    if batch_only:
        return svc.get_state_payload()

    svc.start_background_heartbeat(HEARTBEAT_PERIOD_SEC)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            if self.path == "/api/state":
                raw = json.dumps(svc.get_state_payload(), ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(raw)
                return
            with open(STATIC_HTML_PATH, "rb") as f:
                html = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html)

        def do_POST(self) -> None:
            if self.path == "/api/pulse":
                entry = svc.step_cycle()
            elif self.path == "/api/prompt":
                n = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(n).decode("utf-8"))
                entry = svc.step_cycle(body.get("prompt", ""))
            else:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(asdict(entry), ensure_ascii=False).encode("utf-8"))

    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
    return {}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--batch", action="store_true")
    p.add_argument("--reset", action="store_true")
    p.add_argument("--report", action="store_true")
    p.add_argument("--port", type=int, default=ROOM_137_PORT)
    args = p.parse_args()
    if args.report:
        svc = SanctuaryNodeAlphaService()
        svc.ledger.reset_files()
        for _ in range(3):
            svc.step_cycle()
        svc.step_cycle("Pauli exclusion principle and conservation laws")
        rep = {
            "document_id": "PQMS-LASTENHEFT-NODE-ALPHA-V1.0",
            "work_order": "WORK-ORDER-AG-08",
            "F06_NEURAL_CHROMADB_AUDIT": svc.forager.run_f06_statistical_audit(),
            "F05_F07_LEDGER_AND_HUD_STATE": svc.get_state_payload(),
        }
        with open("VMAX_F05_F06_F07_REPORT.json", "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(json.dumps(rep, indent=2, ensure_ascii=False))
    else:
        print(json.dumps(run_server(batch_only=args.batch, port=args.port, reset=args.reset), indent=2, ensure_ascii=False))
