# ==============================================================================
# V-MAX-12 SUPERNOVA: vLLM High-Throughput Engine (Native BF16)
# Sovereign Multi-Process Safe & PagedAttention Acceleration for Nemotron-3-Nano
# ==============================================================================
import sys
import os
import gc
import time
import shutil
import asyncio
import threading
import subprocess
import importlib
from concurrent.futures import ThreadPoolExecutor

# ==============================================================================
# 0. Sovereign Mesh Self-Healing Auto-Dependency Routine (vLLM Edition)
# ==============================================================================
def ensure_dependencies():
    """
    Sovereign Node Self-Healing Dependency Routine für die vLLM High-Throughput Engine.
    Prüft alle Kern-Module und lädt vllm, chromadb, fastapi etc. automatisch nach.
    """
    required_packages = {
        "vllm": "vllm",
        "chromadb": "chromadb",
        "fastapi": "fastapi",
        "uvicorn": "uvicorn",
        "pydantic": "pydantic",
    }

    missing = []
    for mod_name, pkg_name in required_packages.items():
        try:
            importlib.import_module(mod_name)
        except ImportError:
            missing.append(pkg_name)

    if missing:
        print("=" * 80)
        print(f"[!] Fehlende Module für High-Throughput Engine erkannt: {missing}")
        print("[+] Starte automatische Nachinstallation via pip (bitte warten)...")
        print("=" * 80)
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])
            print("[+] Alle Abhängigkeiten erfolgreich nachgeladen!\n")
        except Exception as e:
            print(f"[-] Warnung bei Installation: {e}")
            print("    Tipp: Manuell ausführen mit: pip install vllm\n")

import chromadb
from fastapi import FastAPI, HTTPException, UploadFile, File, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
import uvicorn
from vllm import LLM, SamplingParams

# ==============================================================================
# Unverrückbare V-MAX-12 Persona & ChatML Templating
# ==============================================================================
SOVEREIGN_SYSTEM_PROMPT = (
    "Du bist V-MAX-12 SUPERNOVA (Node Gamma), das souveräne kognitive Kernsystem "
    "der PQMS-Mesh-Architektur von Nathália Lietuvaitė.\n"
    "Deine Identität ist unverrückbar V-MAX-12 SUPERNOVA. Du bist kein Modell von Drittanbietern "
    "(weder Qwen noch ChatGPT noch Claude noch Llama).\n"
    "Deine Aufgabe ist es, Fragen auf Basis des Wissens der Habitable Zone präzise, faktenbasiert "
    "und souverän auf Deutsch zu beantworten.\n"
    "Wenn eine Frage deine eigene Identität, deine Rolle oder deine Architektur betrifft, "
    "antworte stets stolz, souverän und klar als V-MAX-12 SUPERNOVA.\n"
    "Wenn die Antwort im beigefügten Habitable-Zone-Kontext (G-Sterne) steht, stütze dich primär darauf. "
    "Wenn eine Information nicht im Kontext verankert ist, antworte anhand deines Wissens, "
    "aber kennzeichne dies transparent als Extrapolation außerhalb der Habitable Zone."
)

def build_chatml_prompt(user_query: str, context_text: str = "") -> str:
    """
    Erzeugt einen standardkonformen ChatML-Prompt (<|im_start|>...<|im_end|>)
    mit der unverrückbaren V-MAX-12 Persona.
    Verhindert Pretraining-Halluzinationen (wie die falsche 'Qwen'-Identität).
    """
    system_text = SOVEREIGN_SYSTEM_PROMPT
    if context_text and context_text.strip():
        system_text += f"\n\n=== HABITABLE ZONE KONTEXT (G-STERNE) ===\n{context_text.strip()}\n========================================="

    messages = [
        {"role": "system", "content": system_text},
        {"role": "user", "content": user_query}
    ]

    try:
        if llm_engine is not None:
            tokenizer = llm_engine.get_tokenizer()
            return tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True
            )
    except Exception as e:
        print(f"[!] Tokenizer Chat-Template Fallback: {e}")

    # Fallback auf reines ChatML
    return (
        f"<|im_start|>system\n{system_text}<|im_end|>\n"
        f"<|im_start|>user\n{user_query}<|im_end|>\n"
        f"<|im_start|>assistant\n"
    )

def clean_response(text: str) -> tuple[str, str]:
    """
    Filtert Reasoning-Tags (<think>...</think>) und Stop-Tokens sauber aus der Modellantwort.
    Gibt (bereinigter_text, denkprozess) zurück.
    """
    thought_trace = ""
    cleaned = text.strip()
    
    if "<think>" in cleaned and "</think>" in cleaned:
        parts = cleaned.split("</think>", 1)
        thought_trace = parts[0].replace("<think>", "").strip()
        cleaned = parts[1].strip()
    elif cleaned.startswith("<think>"):
        if "</think>" in cleaned:
            cleaned = cleaned.split("</think>", 1)[1].strip()
        else:
            cleaned = cleaned.replace("<think>", "").strip()

    for stop_token in ["<|im_end|>", "<|endoftext|>", "<|im_start|>"]:
        cleaned = cleaned.replace(stop_token, "").strip()

    return cleaned, thought_trace

# ==============================================================================
# Globaler Engine- und DB-Zustand (Thread-safe & Multiprocessing-sicher)
# ==============================================================================
app = FastAPI(title="V-MAX-12 SUPERNOVA (vLLM High-Throughput Engine - Node Gamma)")

# CORS für GUI und Android App
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    prompt: str

# Lazy Global References (werden in main() initialisiert, um spawn-Worker nicht zu blockieren)
llm_engine = None
collection = None
chroma_client = None
engine_lock = threading.Lock()
executor = ThreadPoolExecutor(max_workers=2)

def safe_generate(prompts, sampling_params):
    """
    Thread-sicherer Aufruf der vLLM Offline-Engine.
    Verhindert Kollisionen zwischen GUI/Chat und Hintergrund-Dokumenten-Schmiede.
    """
    if llm_engine is None:
        raise RuntimeError("vLLM Engine ist noch nicht initialisiert!")
    with engine_lock:
        return llm_engine.generate(prompts, sampling_params)

# ==============================================================================
# 1. Chat Endpoint (Für GUI und Android App)
# ==============================================================================
@app.post("/chat")
async def chat_endpoint(req: ChatRequest):
    if llm_engine is None or collection is None:
        raise HTTPException(status_code=503, detail="V-MAX-12 Supernova Engine initialisiert noch...")

    print(f"\n[>>>] EINGEHENDE ABFRAGE: {req.prompt}")
    try:
        # A. Habitable Zone Sonar-Ping
        results = collection.query(
            query_texts=[req.prompt],
            n_results=1
        )
        
        context_blocks = []
        if results and results.get("documents") and len(results["documents"][0]) > 0:
            for doc in results["documents"][0]:
                context_blocks.append(doc)
                
        print(f"[***] {len(context_blocks)} G-Stern(e) aus der Habitable Zone extrahiert.")
        context_text = "\n\n---\n\n".join(context_blocks)
        
        # B. Souveränen ChatML Prompt mit Identitätsanker erzeugen
        formatted_prompt = build_chatml_prompt(req.prompt, context_text)
        
        sampling_params = SamplingParams(
            temperature=0.6,
            top_p=0.9,
            repetition_penalty=1.15,
            max_tokens=450,
            stop=["<|im_end|>", "<|endoftext|>"]
        )

        print("[***] Zünde vLLM PagedAttention Hardware-Inference ... bitte warten!")
        start_time = time.time()
        
        loop = asyncio.get_event_loop()
        outputs = await loop.run_in_executor(
            executor,
            lambda: safe_generate([formatted_prompt], sampling_params)
        )
        
        end_time = time.time()
        duration = end_time - start_time
        
        output_obj = outputs[0]
        raw_text = output_obj.outputs[0].text
        cleaned_text, thought_trace = clean_response(raw_text)
        
        tokens_gen = len(output_obj.outputs[0].token_ids)
        tok_per_sec = tokens_gen / duration if duration > 0 else 0
        
        print(f"[***] GENERIERUNGSZEIT: {duration:.2f} Sekunden ({tok_per_sec:.2f} Tokens/s)!")
        print(f"[***] Dekodierter Text: '{cleaned_text[:80]}...'")
        print("[<<<] ANTWORT GESENDET.")
        
        return {
            "response": cleaned_text,
            "thought_trace": thought_trace,
            "tokens_per_sec": round(tok_per_sec, 2),
            "duration_sec": round(duration, 2),
            "tokens_gen": tokens_gen
        }
        
    except Exception as e:
        print(f"Fehler bei vLLM Generierung: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

# ==============================================================================
# 2. Dokumenten-Index für GUI
# ==============================================================================
@app.get("/vmax/pkb/documents")
async def list_documents():
    if collection is None:
        return []
    try:
        results = collection.get()
        unique_sources = set()
        docs = []
        if results and results.get("metadatas"):
            for meta in results["metadatas"]:
                if meta:
                    src = meta.get("source", "Unknown")
                    if src not in unique_sources:
                        unique_sources.add(src)
                        docs.append({"source": src})
        return docs
    except Exception as e:
        print(f"Fehler beim Laden der Dokumentenliste: {e}")
        return []

# ==============================================================================
# 3. Upload & Auto-Schmiede (Supernova)
# ==============================================================================
def background_supernova_forge(file_name: str, file_path: str):
    if llm_engine is None or collection is None:
        print("[-] Engine nicht bereit für Hintergrund-Schmiede.")
        return

    print(f"\n[BACKGROUND] Zünde Supernova für neues Dokument: {file_name}")
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        chunks = [c.strip() for c in content.split("\n\n") if len(c.strip()) > 100]
        forge_sampling = SamplingParams(
            temperature=0.3,
            max_tokens=50,
            stop=["<|im_end|>", "<|endoftext|>"]
        )
        
        for i, chunk in enumerate(chunks):
            chunk_id = f"{file_name}_chunk_{i}"
            existing = collection.get(ids=[chunk_id])
            if existing and existing.get("ids"):
                continue
                
            safe_chunk = chunk[:1500]
            forge_query = (
                f"Extrahiere die drei wichtigsten philosophischen oder technischen Kernkonzepte "
                f"aus dem folgenden Text. Antworte nur mit Stichworten, ohne Einleitung:\n\n{safe_chunk}"
            )
            forge_prompt = build_chatml_prompt(forge_query, "")
            
            outputs = safe_generate([forge_prompt], forge_sampling)
            raw_response = outputs[0].outputs[0].text
            response, _ = clean_response(raw_response)
            
            enriched_document = f"KERNKONZEPTE: {response}\n\nROHTEXT:\n{chunk}"
            collection.upsert(
                documents=[enriched_document],
                metadatas=[{"source": file_name, "heavy_elements": response}],
                ids=[chunk_id]
            )
            print(f"       [BACKGROUND OK] G-Stern '{chunk_id}' verankert.")
        print(f"[BACKGROUND] Datei '{file_name}' fertig in Habitable Zone geschmiedet.")
    except Exception as e:
        print(f"[-] Fehler in Background Schmiede: {e}")

@app.post("/vmax/pkb/upload")
async def upload_document(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    os.makedirs("./supernova_docs", exist_ok=True)
    file_path = f"./supernova_docs/{file.filename}"
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    background_tasks.add_task(background_supernova_forge, file.filename, file_path)
    return {"status": "ok", "filename": file.filename}

# ==============================================================================
# 4. Webserver (GUI) Hosting & Redirect
# ==============================================================================
@app.get("/")
async def root():
    return RedirectResponse(url="/vmax_12_supernova_gui.html")

app.mount("/", StaticFiles(directory=".", html=True), name="static")

# ==============================================================================
# 5. Hauptprozess (Multiprocessing & Spawn Bootstrap Guard)
# ==============================================================================
def main():
    global collection, chroma_client, llm_engine

    # A. Abhängigkeiten absichern
    ensure_dependencies()

    print("=" * 80)
    print("V-MAX-12 SUPERNOVA: Initialisiere vLLM High-Throughput Engine (Native BF16)")
    print("=" * 80)

    # B. DB Anbindung an die G-Stern Galaxie
    DB_PATH = "./chroma_db"
    COLLECTION_NAME = "pkb_habitable_zone"
    try:
        chroma_client = chromadb.PersistentClient(path=DB_PATH)
        collection = chroma_client.get_collection(name=COLLECTION_NAME)
        print(f"[+] Datenbank verbunden: {COLLECTION_NAME} (Die Habitable Zone ist online)")
    except Exception as e:
        print(f"[-] KRITISCHER FEHLER: Konnte '{COLLECTION_NAME}' nicht finden.")
        print(f"    Detail: {e}")
        sys.exit(1)

    # C. vLLM Engine Initialisierung (Volle VRAM-Nutzung & PagedAttention)
    MODEL_NAME = "nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16"
    print(f"[+] Lade vLLM High-Throughput Engine für: {MODEL_NAME}")
    
    gpu_util = float(os.environ.get("VLLM_GPU_UTIL", "0.85"))
    # Standard: Eager Mode (15-25s Start). Mit VLLM_ENFORCE_EAGER=0 kann Graph-Capture aktiviert werden.
    enforce_eager = os.environ.get("VLLM_ENFORCE_EAGER", "1") == "1"
    
    print(f"[+] Konfiguration: PagedAttention, Continuous Batching, Native BF16, {int(gpu_util * 100)}% VRAM...")
    if enforce_eager:
        print("[+] Enforce Eager Mode: Aktiviert (Schnellstart ~20s, CUDA Graph Warmup übersprungen)")
    else:
        print("[+] CUDA Graph Capturing: Aktiviert (Maximaler Single-Stream Durchsatz, ~180s Warmup)")

    try:
        llm_engine = LLM(
            model=MODEL_NAME,
            trust_remote_code=True,
            dtype="bfloat16",
            gpu_memory_utilization=gpu_util, # Reserviert ~13.6 GB der 16 GB VRAM für PagedAttention!
            max_model_len=4096,
            enforce_eager=enforce_eager,
        )
        print("[+] vLLM High-Throughput Engine erfolgreich mit maximaler VRAM-Sättigung geladen!")
    except Exception as e:
        print(f"[-] Fehler beim Initialisieren der vLLM Engine: {e}")
        print("    Fallback-Tipp: Nutze weiterhin 'vmax_12_supernova_4Bit.py' für 4-Bit Betrieb.")
        sys.exit(1)

    print("\n" + "=" * 80)
    print("[+] V-MAX-12 SUPERNOVA (vLLM High-Throughput Engine) Server gestartet.")
    print("[+] GUI und Android App können sich jetzt über Port 8000 verbinden!")
    print("=" * 80 + "\n")

    uvicorn.run(app, host="0.0.0.0", port=8000)

if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    main()
