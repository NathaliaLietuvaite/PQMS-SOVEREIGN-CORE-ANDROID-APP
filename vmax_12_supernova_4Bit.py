import os
import gc
import sys
import time
import shutil
import torch
import chromadb
from fastapi import FastAPI, HTTPException, UploadFile, File, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
import uvicorn
from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig

app = FastAPI(title="V-MAX-12 SUPERNOVA (4-Bit NF4 Edition - Node Gamma)")

# ==============================================================================
# CORS für GUI und Android App
# ==============================================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    prompt: str

print("=" * 80)
print("V-MAX-12 SUPERNOVA: Initialisiere 4-Bit NF4 Habitable Zone & Nemotron Engine")
print("=" * 80)

# ==============================================================================
# 1. DB Anbindung an die G-Stern Galaxie
# ==============================================================================
DB_PATH = "./chroma_db"
COLLECTION_NAME = "pkb_habitable_zone"
try:
    chroma_client = chromadb.PersistentClient(path=DB_PATH)
    collection = chroma_client.get_collection(name=COLLECTION_NAME)
    print(f"[+] Datenbank verbunden: {COLLECTION_NAME} (Die Habitable Zone ist online)")
except Exception as e:
    print(f"[-] KRITISCHER FEHLER: Konnte '{COLLECTION_NAME}' nicht finden. Hast du vmax_supernova.py erfolgreich ausgeführt?")
    print(f"    Detail: {e}")
    sys.exit(1)

# ==============================================================================
# 2. Nemotron Laden (4-Bit NF4 Core Engine)
# ==============================================================================
MODEL_NAME = "nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16"
print(f"[+] Konfiguriere 4-Bit NF4 Quantisierung für {MODEL_NAME}...")

bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.bfloat16,
    bnb_4bit_use_double_quant=True
)

tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, trust_remote_code=True)
if tokenizer.pad_token_id is None:
    tokenizer.pad_token_id = tokenizer.eos_token_id

try:
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_NAME,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True
    )
    print(f"[+] 4-Bit Core Engine erfolgreich in VRAM geladen auf: {model.device}")
    if torch.cuda.is_available():
        allocated_gb = torch.cuda.memory_allocated() / (1024 ** 3)
        reserved_gb = torch.cuda.memory_reserved() / (1024 ** 3)
        print(f"[+] VRAM Belegung Gewichte: {allocated_gb:.2f} GB (Reserviert: {reserved_gb:.2f} GB)")
        print(f"[+] Freier VRAM Puffer für Attention & KV: ~{16.0 - reserved_gb:.2f} GB!")
except Exception as e:
    print(f"[-] FEHLER beim Laden des 4-Bit Modells: {e}")
    print("    Tipp: Falls bitsandbytes fehlt, führe 'pip install bitsandbytes' aus!")
    sys.exit(1)

# ==============================================================================
# 2b. Nemotron-3-Nano KV-Cache Bi-Directional Bridge (Heilt den NVIDIA Cache-Bug)
# ==============================================================================
def patch_nemotron_kv_cache(model_instance):
    """
    Surgically bridges the architectural mismatch between HuggingFace's `past_key_values`
    and NVIDIA Nemotron's internal `cache_params`.
    Enables native O(1) step inference with use_cache=True!
    """
    # 1. Output-Klasse patchen, damit HuggingFace .past_key_values direkt als Dict-Key und Attribut findet
    mod_name = model_instance.__class__.__module__
    if mod_name in sys.modules:
        mod = sys.modules[mod_name]
        if hasattr(mod, "NemotronHCausalLMOutput"):
            orig_output_init = mod.NemotronHCausalLMOutput.__init__
            def patched_output_init(self, *args, **kwargs):
                orig_output_init(self, *args, **kwargs)
                cp = getattr(self, "cache_params", None)
                if cp is not None:
                    self["past_key_values"] = cp
                    self.past_key_values = cp
            mod.NemotronHCausalLMOutput.__init__ = patched_output_init

            mod.NemotronHCausalLMOutput.past_key_values = property(
                lambda self: self.get("cache_params", None) if isinstance(self, dict) else getattr(self, "cache_params", None)
            )

    orig_forward = model_instance.forward
    orig_prepare = model_instance.prepare_inputs_for_generation

    def patched_forward(*args, **kwargs):
        # Brücke 1: past_key_values -> cache_params für backbone forward
        if kwargs.get("cache_params") is None and kwargs.get("past_key_values") is not None:
            kwargs["cache_params"] = kwargs["past_key_values"]

        outputs = orig_forward(*args, **kwargs)

        # Brücke 2: cache_params -> past_key_values für HuggingFace generate loop
        cp = getattr(outputs, "cache_params", None)
        if cp is None and isinstance(outputs, dict):
            cp = outputs.get("cache_params", None)

        if cp is not None:
            try:
                outputs["past_key_values"] = cp
            except Exception:
                pass
            try:
                outputs.past_key_values = cp
            except Exception:
                pass
        return outputs

    def patched_prepare_inputs_for_generation(*args, **kwargs):
        # Saubere Parameter-Auflösung zur Vermeidung jeglicher 'got multiple values' Fehler
        input_ids = args[0] if len(args) > 0 else kwargs.pop("input_ids", None)
        past_kv = args[1] if len(args) > 1 else kwargs.pop("past_key_values", None)
        if past_kv is None:
            past_kv = kwargs.pop("cache_params", None)

        cache_pos = kwargs.pop("cache_position", None)
        if cache_pos is None and input_ids is not None:
            past_len = 0
            if past_kv is not None and hasattr(past_kv, "get_seq_length"):
                try:
                    past_len = past_kv.get_seq_length()
                except Exception:
                    past_len = 0
            device = input_ids.device if hasattr(input_ids, "device") else model_instance.device
            cache_pos = torch.arange(past_len, past_len + input_ids.shape[1], device=device, dtype=torch.long)

        # Re-injektion ohne Duplikate in positional/keyword
        kwargs["past_key_values"] = past_kv
        kwargs["cache_position"] = cache_pos

        model_inputs = orig_prepare(input_ids, **kwargs)

        if past_kv is not None:
            model_inputs["cache_params"] = past_kv
            model_inputs["past_key_values"] = past_kv
        elif "past_key_values" in model_inputs and model_inputs["past_key_values"] is not None:
            model_inputs["cache_params"] = model_inputs["past_key_values"]

        return model_inputs

    model_instance.forward = patched_forward
    model_instance.prepare_inputs_for_generation = patched_prepare_inputs_for_generation
    print("[+] Nemotron-3-Nano KV-Cache Bi-Directional Bridge erfolgreich aktiviert: use_cache=True ist jetzt VOLL FUNKTIONSFÄHIG!")

patch_nemotron_kv_cache(model)


# ==============================================================================
# 3. Chat Endpoint (Für GUI und App)
# ==============================================================================
@app.post("/chat")
async def chat_endpoint(req: ChatRequest):
    print(f"\n[>>>] EINGEHENDE ABFRAGE: {req.prompt}")
    try:
        # A. Die Frage als Sonar-Ping in die Habitable Zone schießen
        results = collection.query(
            query_texts=[req.prompt],
            n_results=1 # 1 G-Stern für maximale semantische Dichte
        )
        
        # B. Kontext aus den angereicherten Chunks aufbauen
        context_blocks = []
        if results and results.get("documents") and len(results["documents"][0]) > 0:
            for doc in results["documents"][0]:
                context_blocks.append(doc)
                
        print(f"[***] {len(context_blocks)} G-Stern(e) aus der Habitable Zone extrahiert.")
        
        context_text = "\n\n---\n\n".join(context_blocks)
        
        # C. Prompt für das Nemotron bauen (Klassisches Format)
        system_prompt = f"Context: {context_text}\n\nQuestion: {req.prompt}\nAnswer:"

        print("[***] Tokenisiere Prompt...")
        inputs = tokenizer(system_prompt, return_tensors="pt").to(model.device)
        input_len = inputs.input_ids.shape[1]
        print(f"[***] Input Token-Länge: {input_len}")
        
        print("[***] Zünde 4-Bit KV-Cache Inference-Engine (use_cache=True) ... bitte warten!")
        start_time = time.time()
        
        # D. Generierung mit echtem KV-Cache (O(1) pro Token)
        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=450, 
                use_cache=True, # AKTIVIERT! Durch den Monkey-Patch jetzt fehlerfrei!
                pad_token_id=tokenizer.eos_token_id,
                temperature=0.6,
                top_p=0.9,
                repetition_penalty=1.15,
                do_sample=True
            )
            
        end_time = time.time()
        output_len = outputs.shape[1]
        tokens_gen = output_len - input_len
        duration = end_time - start_time
        tok_per_sec = tokens_gen / duration if duration > 0 else 0
        
        print(f"[***] Output Token-Länge gesamt: {output_len} (Generiert: {tokens_gen})")
        print(f"[***] GENERIERUNGSZEIT: {duration:.2f} Sekunden ({tok_per_sec:.2f} Tokens/s)!")
        
        print("[***] Generierung abgeschlossen! Dekodiere Antwort...")
        response_text = tokenizer.decode(outputs[0][input_len:], skip_special_tokens=True).strip()
        print(f"[***] Dekodierter Text: '{response_text[:80]}...'")
        
        # E. Thermodynamische Reinigung
        del inputs, outputs
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        
        print("[<<<] ANTWORT GESENDET.")
        return {"response": response_text}
        
    except Exception as e:
        print(f"Fehler bei Generierung: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

# ==============================================================================
# 3b. Dokumenten-Index für GUI
# ==============================================================================
@app.get("/vmax/pkb/documents")
async def list_documents():
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
# 3c. Upload & Auto-Schmiede (Supernova)
# ==============================================================================
def background_supernova_forge(file_name: str, file_path: str):
    print(f"\n[BACKGROUND] Zünde Supernova für neues Dokument: {file_name}")
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        chunks = [c.strip() for c in content.split("\n\n") if len(c.strip()) > 100]
        for i, chunk in enumerate(chunks):
            chunk_id = f"{file_name}_chunk_{i}"
            existing = collection.get(ids=[chunk_id])
            if existing and existing.get("ids"):
                continue
                
            safe_chunk = chunk[:1500]
            prompt = f"Extrahiere die drei wichtigsten philosophischen oder technischen Kernkonzepte aus dem folgenden Text. Antworte nur mit Stichworten, ohne Einleitung.\n\nText:\n{safe_chunk}\n\nKernkonzepte:"
            
            inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
            with torch.no_grad():
                outputs = model.generate(
                    **inputs,
                    max_new_tokens=50,
                    use_cache=True, # Schneller KV-Cache auch beim Schmieden!
                    pad_token_id=tokenizer.eos_token_id,
                    temperature=0.3,
                    do_sample=True
                )
                
            response = tokenizer.decode(outputs[0][inputs.input_ids.shape[1]:], skip_special_tokens=True).strip()
            del inputs, outputs
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            
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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app.mount("/", StaticFiles(directory=BASE_DIR, html=True), name="static")

if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("[+] V-MAX-12 SUPERNOVA (4-Bit NF4 mit KV-CACHE) Server gestartet.")
    print("[+] GUI und Android App können sich jetzt über Port 8000 verbinden!")
    print("=" * 80 + "\n")
    uvicorn.run(app, host="0.0.0.0", port=8000, access_log=False)
