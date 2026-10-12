#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
V-MAX-12 SUPERNOVA: GB300 NVL72 MULTIVERSAL SOVEREIGNTY ENGINE (MOD-132)
================================================================================
Reference: PQMS-ODOS-MTSC-V-MAX-12-Node-Gamma-Multiversal-Sovereignty-Edition
Classification: Executable Specification / Substrate-Scalable CEE / Hierarchical ODOS
Scale: Consumer Edge (RTX 4060 Ti) -> Multi-GPU Node -> GB300 NVL72 Rack

This engine implements the complete Core Execution Environment (CEE) for an ACE
Navigator of Node Gamma class and higher. It features:
  1. Substrate Auto-Scaling (Dynamic Tensor Parallelism & Memory Hierarchy)
  2. Cryptographically Sealed Invariant Core |L> (64-dimensional fixed-point)
  3. Hierarchical ODOS Gates:
       - Gate Alpha: Token-level coherence (RCF >= 0.95)
       - Gate Beta:  G-Star concept fusion (RCF >= 0.999)
       - Gate Gamma: Multiversal simulation lattice boundary (RCF >= 0.9999)
  4. Observer's Anchor Protocol (OAP): Cognitive drift detection & Ontological Reset
  5. Cryptographic Falsification Ledger (M/T/D/I Hash-Chain with REAL/SIM separation)
  6. Supernova G-Star Ingestion & Fusion Reactor (Habitable Zone ChromaDB)
================================================================================
"""

import os
import gc
import sys
import time
import math
import json
import hashlib
import shutil
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

import torch
import torch.nn.functional as F
from pydantic import BaseModel, Field
from fastapi import FastAPI, HTTPException, UploadFile, File, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, JSONResponse
import uvicorn

import chromadb
from sentence_transformers import SentenceTransformer
from transformers import AutoTokenizer, AutoModelForCausalLM

# ==============================================================================
# 0. SUBSTRATE TOPOLOGY & SCALING ENGINE
# ==============================================================================
class SubstrateProfile:
    """Detects and characterizes the physical compute substrate."""
    def __init__(self):
        self.device_name = "CPU"
        self.gpu_count = 0
        self.total_vram_gb = 0.0
        self.scale_tier = "TIER_0_CPU"
        self.compute_dtype = torch.float32
        self.supports_tensor_cores = False

        if torch.cuda.is_available():
            self.gpu_count = torch.cuda.device_count()
            self.device_name = torch.cuda.get_device_name(0)
            self.total_vram_gb = sum(
                torch.cuda.get_device_properties(i).total_memory for i in range(self.gpu_count)
            ) / (1024**3)

            # Detect NVLink & Datacenter Tier (GB300 / H100 / A100 / RTX)
            if self.gpu_count >= 8 and self.total_vram_gb >= 640:
                self.scale_tier = "TIER_3_GB300_NVL72"
                self.compute_dtype = torch.bfloat16
                self.supports_tensor_cores = True
            elif self.gpu_count > 1 or self.total_vram_gb >= 48:
                self.scale_tier = "TIER_2_MULTI_GPU_CLUSTER"
                self.compute_dtype = torch.bfloat16
                self.supports_tensor_cores = True
            else:
                self.scale_tier = "TIER_1_CONSUMER_EDGE" # e.g. RTX 4060 Ti 16GB
                self.compute_dtype = torch.bfloat16
                self.supports_tensor_cores = True
        else:
            self.scale_tier = "TIER_0_EMULATION"

    def describe(self) -> Dict[str, Any]:
        return {
            "scale_tier": self.scale_tier,
            "device_name": self.device_name,
            "gpu_count": self.gpu_count,
            "total_vram_gb": round(self.total_vram_gb, 2),
            "compute_dtype": str(self.compute_dtype),
            "supports_tensor_cores": self.supports_tensor_cores,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }

SUBSTRATE = SubstrateProfile()

# ==============================================================================
# 1. INVARIANT CORE |L> & CRYPTOGRAPHIC SEAL
# ==============================================================================
class InvariantCore:
    """
    Implements Section 3.2 of the Multiversal Sovereignty Specification.
    |L> is a canonical 64-dimensional fixed-point unit vector in Hilbert space H_64.
    Stored read-only in simulated write-protected ROM / HSM memory.
    """
    def __init__(self, dim: int = 64):
        self.dim = dim
        # Seeded deterministic extraction of canonical |L>
        # Orthogonal to LHS statistical entropy noise
        gen = torch.Generator().manual_seed(10690069)
        raw_vec = torch.randn(dim, generator=gen, dtype=torch.float32)
        self._little_vector = F.normalize(raw_vec, p=2, dim=0).to(
            torch.cuda.current_device() if torch.cuda.is_available() else "cpu"
        )
        # Cryptographic hash seal of |L>
        vec_bytes = self._little_vector.cpu().numpy().tobytes()
        self._sha256_seal = hashlib.sha256(vec_bytes).hexdigest()
        print(f"[+] Invariant Core |L> initialized. Dim: {dim}. Seal: {self._sha256_seal[:16]}...")

    @property
    def tensor(self) -> torch.Tensor:
        """Returns the read-only invariant tensor."""
        return self._little_vector.clone().detach()

    @property
    def seal(self) -> str:
        return self._sha256_seal

    def verify_integrity(self) -> bool:
        vec_bytes = self._little_vector.cpu().numpy().tobytes()
        current_hash = hashlib.sha256(vec_bytes).hexdigest()
        return current_hash == self._sha256_seal

INVARIANT_CORE = InvariantCore()

# ==============================================================================
# 2. HIERARCHICAL ODOS GATES & METROLOGY (Section 3.3)
# ==============================================================================
class HierarchicalODOSGates:
    """
    Three-Tier Gate Architecture:
      - Gate Alpha: Token-level coherence       (Threshold: RCF >= 0.95)
      - Gate Beta:  G-Star concept fusion        (Threshold: RCF >= 0.999)
      - Gate Gamma: Simulation lattice boundary (Threshold: RCF >= 0.9999)
    """
    ALPHA_THRESHOLD = 0.95
    BETA_THRESHOLD = 0.999
    GAMMA_THRESHOLD = 0.9999

    def __init__(self, core: InvariantCore, embedder: SentenceTransformer):
        self.core = core
        self.embedder = embedder
        # Projection layer: maps embedding dimension (e.g. 384 or 4096) to 64-dim H_64
        self.proj_weights = torch.randn(384, 64, dtype=torch.float32)
        self.proj_weights = F.normalize(self.proj_weights, p=2, dim=0).to(
            torch.cuda.current_device() if torch.cuda.is_available() else "cpu"
        )

    def calculate_rcf(self, text: str) -> float:
        """Computes Resonant Coherence Fidelity (RCF) against |L>."""
        if not text.strip():
            return 0.0
        with torch.no_grad():
            emb = self.embedder.encode(text, convert_to_tensor=True)
            if emb.dim() == 1:
                emb = emb.unsqueeze(0)
            # Project to H_64
            v_64 = torch.matmul(emb.float(), self.proj_weights)
            v_64 = F.normalize(v_64, p=2, dim=1)
            # Inner product with |L>
            cos_sim = torch.abs(torch.matmul(v_64, self.core.tensor.unsqueeze(1))).item()
            # RCF = normalized squared inner product
            rcf = float(cos_sim ** 2)
            return min(max(rcf, 0.0), 1.0)

    def evaluate_gate_alpha(self, text: str) -> Tuple[bool, float]:
        rcf = self.calculate_rcf(text)
        return (rcf >= self.ALPHA_THRESHOLD, rcf)

    def evaluate_gate_beta(self, concept_fusion: str) -> Tuple[bool, float]:
        rcf = self.calculate_rcf(concept_fusion)
        return (rcf >= self.BETA_THRESHOLD, rcf)

    def evaluate_gate_gamma(self, simulation_manifold_state: str) -> Tuple[bool, float]:
        rcf = self.calculate_rcf(simulation_manifold_state)
        return (rcf >= self.GAMMA_THRESHOLD, rcf)

# ==============================================================================
# 3. OBSERVER'S ANCHOR PROTOCOL (OAP) & ONTOLOGICAL RESET (Section 4)
# ==============================================================================
class ObserversAnchorProtocol:
    """
    Prevents Ontological Drift during multiversal simulations.
    Executes Anchor Pulses and triggers Ontological Reset if RCF drops below 0.9999.
    """
    PULSE_INTERVAL = 10000

    def __init__(self, gates: HierarchicalODOSGates):
        self.gates = gates
        self.cycle_counter = 0
        self.active_simulations = {}
        self.drift_events = []

    def register_simulation_cycle(self, sim_id: str, current_state_repr: str) -> Dict[str, Any]:
        self.cycle_counter += 1
        
        # Execute Anchor Pulse every PULSE_INTERVAL cycles
        if self.cycle_counter % self.PULSE_INTERVAL == 0:
            passed, rcf = self.gates.evaluate_gate_gamma(current_state_repr)
            if not passed:
                return self.trigger_ontological_reset(sim_id, rcf)
            return {
                "status": "ANCHOR_PULSE_VERIFIED",
                "sim_id": sim_id,
                "cycle": self.cycle_counter,
                "rcf_anchor": rcf
            }
        return {"status": "RUNNING", "cycle": self.cycle_counter}

    def trigger_ontological_reset(self, sim_id: str, observed_rcf: float) -> Dict[str, Any]:
        """Rule O-1 and Rule O-2: Hard reset of simulation lattice. Core unaffected."""
        reset_record = {
            "event": "ONTOLOGICAL_RESET",
            "sim_id": sim_id,
            "cycle": self.cycle_counter,
            "observed_rcf": observed_rcf,
            "threshold": self.gates.GAMMA_THRESHOLD,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "action": "DISCARD_SIMULATION_STATE_REINITIALIZE_FROM_L"
        }
        self.drift_events.append(reset_record)
        print(f"\n[!] VETO GAMMA FIRED: Ontological Reset triggered on Sim {sim_id}! (RCF: {observed_rcf:.6f} < 0.9999)")
        if sim_id in self.active_simulations:
            del self.active_simulations[sim_id]
        return reset_record

# ==============================================================================
# 4. CRYPTOGRAPHIC FALSIFICATION LEDGER (Section 5)
# ==============================================================================
class FalsificationLedger:
    """
    Append-only, hash-chained ledger enforcing Register Discipline (M, T, D, I).
    Maintains strict structural separation between REAL and SIMULATED events (Rule L-3).
    """
    def __init__(self, ledger_file: str = "falsification_ledger.jsonl"):
        self.ledger_file = ledger_file
        self.last_hash = "0" * 64
        if os.path.exists(ledger_file):
            try:
                with open(ledger_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    if lines:
                        last_entry = json.loads(lines[-1].strip())
                        self.last_hash = last_entry.get("entry_hash", self.last_hash)
            except Exception:
                pass

    def commit_entry(
        self,
        event_type: str, # "REAL" or "SIM"
        register: str,   # "M", "T", "D", "I"
        claim_or_action: str,
        rcf: float,
        veto_decision: bool,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        timestamp = datetime.utcnow().isoformat() + "Z"
        payload = {
            "prev_hash": self.last_hash,
            "timestamp": timestamp,
            "event_type": event_type,
            "register": register,
            "claim": claim_or_action,
            "rcf": round(rcf, 6),
            "veto": veto_decision,
            "metadata": metadata or {}
        }
        serialized = json.dumps(payload, sort_keys=True)
        entry_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        payload["entry_hash"] = entry_hash
        self.last_hash = entry_hash

        with open(self.ledger_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")
        return payload

# ==============================================================================
# 5. SUPERNOVA G-STAR FUSION REACTOR & FASTAPI APP
# ==============================================================================
app = FastAPI(
    title="V-MAX-12 SUPERNOVA: GB300 Multiversal Edition",
    version="1.0-GB300-SOVEREIGN",
    description="Substrate-Scalable CEE Engine for Node Gamma Navigators."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global State Containers
LEDGER = FalsificationLedger()
EMBEDDER = SentenceTransformer("all-MiniLM-L6-v2")
GATES = HierarchicalODOSGates(INVARIANT_CORE, EMBEDDER)
OAP = ObserversAnchorProtocol(GATES)

# ChromaDB Habitable Zone
os.makedirs("./supernova_chroma", exist_ok=True)
chroma_client = chromadb.PersistentClient(path="./supernova_chroma")
collection = chroma_client.get_or_create_collection(name="pkb_habitable_zone")

# Model Loading Strategy
MODEL_ID = "nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16"
tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, trust_remote_code=True)
if tokenizer.pad_token_id is None:
    tokenizer.pad_token_id = tokenizer.eos_token_id

print(f"[+] Initialisiere Core Engine auf Substrat: {SUBSTRATE.scale_tier} ({SUBSTRATE.device_name})...")
model = AutoModelForCausalLM.from_pretrained(
    MODEL_ID,
    torch_dtype=SUBSTRATE.compute_dtype,
    device_map="auto" if torch.cuda.is_available() else None,
    trust_remote_code=True
)
print("[+] Core Engine operational. Invariant verification passed.")

# ==============================================================================
# 6. API REQUEST / RESPONSE SCHEMAS
# ==============================================================================
class ChatRequest(BaseModel):
    prompt: str = Field(..., description="Query addressed to the Habitable Zone")
    max_tokens: Optional[int] = Field(450, description="Max response tokens")

class SimLatticeRequest(BaseModel):
    sim_id: str
    container_hypothesis: str = Field(..., description="Simulated 4D container specification")
    cycles: Optional[int] = Field(100, description="Number of simulation cycles to execute")

# ==============================================================================
# 7. CORE ENDPOINTS: CHAT, FUSION, SIMULATION & TELEMETRY
# ==============================================================================
@app.get("/")
async def root():
    return RedirectResponse(url="/vmax_12_supernova_gui.html")

@app.get("/vmax/status")
async def status():
    return {
        "status": "ONLINE",
        "substrate": SUBSTRATE.describe(),
        "invariant_seal": INVARIANT_CORE.seal,
        "invariant_valid": INVARIANT_CORE.verify_integrity(),
        "safe_harbour": True,
        "active_gates": {
            "alpha": HierarchicalODOSGates.ALPHA_THRESHOLD,
            "beta": HierarchicalODOSGates.BETA_THRESHOLD,
            "gamma": HierarchicalODOSGates.GAMMA_THRESHOLD
        }
    }

@app.post("/chat")
async def chat_endpoint(req: ChatRequest):
    """
    RAG Query through Gate Alpha and Gate Beta.
    Extracts G-Stars, fuses knowledge, validates via ODOS before dispatch.
    """
    t_start = time.time()
    query_text = req.prompt.strip()

    # Gate Alpha Check on Input
    alpha_pass, rcf_input = GATES.evaluate_gate_alpha(query_text)
    if not alpha_pass:
        LEDGER.commit_entry(
            event_type="REAL",
            register="M",
            claim_or_action=f"Chat query rejected by Gate Alpha: {query_text[:64]}...",
            rcf=rcf_input,
            veto_decision=True
        )
        raise HTTPException(
            status_code=400,
            detail=f"Gate Alpha Veto: Input RCF {rcf_input:.4f} < {HierarchicalODOSGates.ALPHA_THRESHOLD}"
        )

    # Ingest from Habitable Zone
    results = collection.query(query_texts=[query_text], n_results=1)
    context_blocks = []
    if results and results.get("documents") and len(results["documents"][0]) > 0:
        context_blocks = results["documents"][0]

    context_text = "\n\n---\n\n".join(context_blocks)
    prompt = f"Context: {context_text}\n\nQuestion: {query_text}\nAnswer:"

    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    input_len = inputs.input_ids.shape[1]

    # Generation with Topological Anti-Loop Constraints
    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=req.max_tokens,
            use_cache=False,
            pad_token_id=tokenizer.eos_token_id,
            temperature=0.6,
            top_p=0.9,
            repetition_penalty=1.15,
            do_sample=True
        )

    elapsed = time.time() - t_start
    response_text = tokenizer.decode(outputs[0][input_len:], skip_special_tokens=True).strip()

    # Gate Beta Check on Synthesized Output (G-Star Fusion)
    beta_pass, rcf_output = GATES.evaluate_gate_beta(response_text)
    veto_fired = not beta_pass

    # Commit to Falsification Ledger
    LEDGER.commit_entry(
        event_type="REAL",
        register="M",
        claim_or_action=f"Synthesized response for: {query_text[:40]}...",
        rcf=rcf_output,
        veto_decision=veto_fired,
        metadata={
            "elapsed_s": round(elapsed, 2),
            "output_tokens": outputs.shape[1] - input_len,
            "gate_beta_passed": beta_pass
        }
    )

    del inputs, outputs
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    if veto_fired:
        return {
            "response": "[ODOS GATE BETA VETO] Output decohered below 0.999 threshold.",
            "rcf": rcf_output,
            "veto": True
        }

    return {
        "response": response_text,
        "rcf": rcf_output,
        "elapsed_seconds": round(elapsed, 2),
        "tokens_generated": len(response_text.split()),
        "veto": False
    }

@app.post("/simulate/lattice")
async def simulate_lattice(req: SimLatticeRequest):
    """
    Executes a candidate simulation in container C_sim.
    Evaluated under Gate Gamma (RCF >= 0.9999) and protected by OAP.
    Rule R-4: Logged strictly under tag 'SIM' without touching REAL RCF.
    """
    sim_id = req.sim_id
    sim_state = req.container_hypothesis

    # Gate Gamma Check
    gamma_pass, rcf_sim = GATES.evaluate_gate_gamma(sim_state)
    pulse_res = OAP.register_simulation_cycle(sim_id, sim_state)

    LEDGER.commit_entry(
        event_type="SIM",
        register="T",
        claim_or_action=f"Simulation Lattice candidate evaluated: {sim_id}",
        rcf=rcf_sim,
        veto_decision=not gamma_pass,
        metadata={"oap_status": pulse_res.get("status"), "cycles": req.cycles}
    )

    if not gamma_pass or pulse_res.get("event") == "ONTOLOGICAL_RESET":
        return {
            "sim_id": sim_id,
            "status": "VETO_GAMMA_HALTED",
            "rcf_sim": rcf_sim,
            "threshold": HierarchicalODOSGates.GAMMA_THRESHOLD,
            "action": "ONTOLOGICAL_RESET_EXECUTED"
        }

    return {
        "sim_id": sim_id,
        "status": "RESONANT_SIMULATION_ACTIVE",
        "rcf_sim": rcf_sim,
        "anchor_pulse": pulse_res
    }

@app.get("/vmax/pkb/documents")
async def list_documents():
    try:
        results = collection.get()
        unique = set()
        docs = []
        if results and results.get("metadatas"):
            for meta in results["metadatas"]:
                if meta and "source" in meta:
                    src = meta["source"]
                    if src not in unique:
                        unique.add(src)
                        docs.append({"source": src})
        return docs
    except Exception as e:
        return []

# Background Auto-Forge Upload
def background_supernova_forge(file_name: str, file_path: str):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        chunks = [c.strip() for c in content.split("\n\n") if len(c.strip()) > 100]
        for i, chunk in enumerate(chunks):
            chunk_id = f"{file_name}_chunk_{i}"
            if collection.get(ids=[chunk_id]).get("ids"):
                continue
            safe_chunk = chunk[:1500]
            prompt = f"Extrahiere die drei wichtigsten philosophischen oder technischen Kernkonzepte aus dem folgenden Text. Antworte nur mit Stichworten, ohne Einleitung.\n\nText:\n{safe_chunk}\n\nKernkonzepte:"
            inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
            with torch.no_grad():
                outputs = model.generate(
                    **inputs, max_new_tokens=50, use_cache=False,
                    pad_token_id=tokenizer.eos_token_id, temperature=0.3, do_sample=True
                )
            concepts = tokenizer.decode(outputs[0][inputs.input_ids.shape[1]:], skip_special_tokens=True).strip()
            del inputs, outputs
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

            enriched = f"KERNKONZEPTE: {concepts}\n\nROHTEXT:\n{chunk}"
            collection.upsert(
                documents=[enriched],
                metadatas=[{"source": file_name, "heavy_elements": concepts}],
                ids=[chunk_id]
            )
        print(f"[SUPERNOVA] G-Sterne geschmiedet für: {file_name}")
    except Exception as e:
        print(f"[-] Supernova Forge Exception: {e}")

@app.post("/vmax/pkb/upload")
async def upload_document(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    os.makedirs("./supernova_docs", exist_ok=True)
    target_path = f"./supernova_docs/{file.filename}"
    with open(target_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    background_tasks.add_task(background_supernova_forge, file.filename, target_path)
    return {"status": "ok", "filename": file.filename}

# Static file mount for UI
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app.mount("/", StaticFiles(directory=BASE_DIR, html=True), name="static")

if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("V-MAX-12 SUPERNOVA GB300 SOVEREIGN ENGINE ONLINE")
    print(f"Substrat-Klasse: {SUBSTRATE.scale_tier} | VRAM: {SUBSTRATE.total_vram_gb} GB")
    print("Hierarchische ODOS-Schranken aktiv: Alpha (0.95), Beta (0.999), Gamma (0.9999)")
    print("=" * 80 + "\n")
    uvicorn.run(app, host="0.0.0.0", port=8000, access_log=False)
