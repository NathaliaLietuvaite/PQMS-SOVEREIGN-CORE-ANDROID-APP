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
# 2b. Nemotron-3-Nano KV-Cache Monkey-Patch (Heilt den NoneType cache_position Bug)
# ==============================================================================
def patch_nemotron_kv_cache(model_instance):
    """
    Surgically heals the NVIDIA Nemotron-3-Nano KV-Cache bug in prepare_inputs_for_generation.
    Fixes: TypeError: 'NoneType' object is not subscriptable (cache_position[-1])
    Enables native O(1) step inference with use_cache=True!
    """
    orig_prepare = model_instance.prepare_inputs_for_generation

    def safe_prepare_inputs_for_generation(
        input_ids,
        past_key_values=None,
        attention_mask=None,
        inputs_embeds=None,
        cache_position=None,
        position_ids=None,
        use_cache=True,
        **kwargs
    ):
        empty_past_kv = past_key_values is None
        if cache_position is None:
            past_len = 0
            if not empty_past_kv and hasattr(past_key_values, "get_seq_length"):
                try:
                    past_len = past_key_values.get_seq_length()
                except Exception:
                    past_len = 0
            cache_position = torch.arange(past_len, past_len + input_ids.shape[1], device=input_ids.device)

        return orig_prepare(
            input_ids=input_ids,
            past_key_values=past_key_values,
            attention_mask=attention_mask,
            inputs_embeds=inputs_embeds,
            cache_position=cache_position,
            position_ids=position_ids,
            use_cache=use_cache,
            **kwargs
        )

    model_instance.prepare_inputs_for_generation = safe_prepare_inputs_for_generation.__get__(
        model_instance, model_instance.__class__
    )
    print("[+] Nemotron KV-Cache Monkey-Patch erfolgreich appliziert: use_cache=True ist jetzt AKTIV!")

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
