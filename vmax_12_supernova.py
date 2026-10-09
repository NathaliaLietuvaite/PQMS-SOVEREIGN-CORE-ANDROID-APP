import os
import gc
import torch
import shutil
import chromadb
from fastapi import FastAPI, HTTPException, UploadFile, File, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn
from transformers import AutoTokenizer, AutoModelForCausalLM

app = FastAPI(title="V-MAX-12 SUPERNOVA (Node Gamma)")

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

print("="*80)
print("V-MAX-12 SUPERNOVA: Initialisiere Habitable Zone & Nemotron")
print("="*80)

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
    exit()

# ==============================================================================
# 2. Nemotron Laden (Core Engine)
# ==============================================================================
MODEL_NAME = "nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16"
print(f"[+] Lade {MODEL_NAME} in bfloat16 natively...")
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, trust_remote_code=True)
if tokenizer.pad_token_id is None:
    tokenizer.pad_token_id = tokenizer.eos_token_id

model = AutoModelForCausalLM.from_pretrained(
    MODEL_NAME, 
    torch_dtype=torch.bfloat16, 
    device_map="auto", 
    trust_remote_code=True
)
print("[+] Core Engine bereit auf:", model.device)

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
            n_results=1 # REDUZIERT AUF 1 G-STERN, um die Cache-lose Attention-Matrix klein zu halten!
        )
        
        # B. Kontext aus den angereicherten Chunks aufbauen
        context_blocks = []
        if results and results['documents'] and len(results['documents'][0]) > 0:
            for doc in results['documents'][0]:
                context_blocks.append(doc)
                
        print(f"[***] {len(context_blocks)} G-Stern(e) aus der Habitable Zone extrahiert.")
        
        context_text = "\n\n---\n\n".join(context_blocks)
        
        # C. Prompt für das Nemotron bauen (Klassisches Format)
        system_prompt = f"Context: {context_text}\n\nQuestion: {req.prompt}\nAnswer:"

        print("[***] Tokenisiere Prompt...")
        inputs = tokenizer(system_prompt, return_tensors="pt").to(model.device)
        input_len = inputs.input_ids.shape[1]
        print(f"[***] Input Token-Länge: {input_len}")
        
        import time
        print("[***] Zünde Inference-Engine (model.generate) ... bitte warten!")
        start_time = time.time()
        
        # D. Generierung (mit Schutz vor VRAM-Lecks)
        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=450, 
                use_cache=False, 
                pad_token_id=tokenizer.eos_token_id,
                temperature=0.6,
                top_p=0.9,               # Schneidet den unlogischen "Schwanz" der Wahrscheinlichkeiten ab
                repetition_penalty=1.15, # STRAFE FÜR ENDLOSSCHLEIFEN! Bricht den Deadlock.
                do_sample=True
            )
            
        end_time = time.time()
        output_len = outputs.shape[1]
        
        print(f"[***] Output Token-Länge gesamt: {output_len} (Generiert: {output_len - input_len})")
        print(f"[***] GENERIERUNGSZEIT: {end_time - start_time:.2f} Sekunden!")
        
        print("[***] Generierung abgeschlossen! Dekodiere Antwort...")
        response_text = tokenizer.decode(outputs[0][input_len:], skip_special_tokens=True).strip()
        print(f"[***] Dekodierter Text: '{response_text}'")
        
        # E. Thermodynamische Reinigung
        del inputs, outputs
        gc.collect()
        torch.cuda.empty_cache()
        
        print("[<<<] ANTWORT GESENDET.")
        return {"response": response_text}
        
    except Exception as e:
        print(f"Fehler bei Generierung: {e}")
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
            if existing and existing['ids']:
                continue
                
            safe_chunk = chunk[:1500]
            prompt = f"Extrahiere die drei wichtigsten philosophischen oder technischen Kernkonzepte aus dem folgenden Text. Antworte nur mit Stichworten, ohne Einleitung.\n\nText:\n{safe_chunk}\n\nKernkonzepte:"
            
            inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
            with torch.no_grad():
                outputs = model.generate(**inputs, max_new_tokens=50, use_cache=False, pad_token_id=tokenizer.eos_token_id, temperature=0.3, do_sample=True)
                
            response = tokenizer.decode(outputs[0][inputs.input_ids.shape[1]:], skip_special_tokens=True).strip()
            del inputs, outputs
            gc.collect()
            torch.cuda.empty_cache()
            
            enriched_document = f"KERNKONZEPTE: {response}\n\nROHTEXT:\n{chunk}"
            collection.upsert(documents=[enriched_document], metadatas=[{"source": file_name, "heavy_elements": response}], ids=[chunk_id])
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
        
    # Zünde die Schmiede im Hintergrund, ohne die GUI zu blockieren!
    background_tasks.add_task(background_supernova_forge, file.filename, file_path)
    return {"status": "ok", "filename": file.filename}

from fastapi.responses import RedirectResponse

@app.get("/")
async def root():
    # Leitet Aufrufe von localhost:8000/ direkt auf die neue GUI um
    return RedirectResponse(url="/vmax_12_supernova_gui.html")

# ==============================================================================
# 4. Webserver (GUI) Hosting
# ==============================================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app.mount("/", StaticFiles(directory=BASE_DIR, html=True), name="static")

if __name__ == "__main__":
    print("\n" + "="*80)
    print("[+] V-MAX-12 SUPERNOVA Server gestartet.")
    print("[+] GUI und Android App können sich jetzt über Port 8000 verbinden!")
    print("="*80 + "\n")
    # access_log=False schaltet den Spam ab! Nur noch echte System-Meldungen.
    uvicorn.run(app, host="0.0.0.0", port=8000, access_log=False)
