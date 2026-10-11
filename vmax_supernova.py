import os
import chromadb
from transformers import AutoTokenizer, AutoModelForCausalLM
import torch

# ==============================================================================
# V-MAX-12 SUPERNOVA (NUCLEOSYNTHESIS INGESTION PIPELINE)
# ==============================================================================
# Dieses Skript nimmt rohe Markdown-Dateien (Population III Wasserstoff),
# lässt das Nemotron-Modell "schwere Elemente" (Konzepte, Resonanz) brüten
# und speichert das angereicherte Material (Pop I G-Sterne) in der ChromaDB.
# ==============================================================================

# 1. Konfiguration
DB_PATH = "./chroma_db"
NEW_COLLECTION_NAME = "pkb_habitable_zone"
DOCS_DIR = "./supernova_docs" # Packe hier nur die Dateien rein, die du testen willst!
os.makedirs(DOCS_DIR, exist_ok=True)
MODEL_NAME = "nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16"

print("="*80)
print("V-MAX-12 SUPERNOVA: Zündung der Primordialen Schmiede")
print("="*80)

# 2. ChromaDB initialisieren (Neue Collection für die G-Sterne)
client = chromadb.PersistentClient(path=DB_PATH)
try:
    collection = client.get_or_create_collection(name=NEW_COLLECTION_NAME)
    print(f"[+] ChromaDB Collection '{NEW_COLLECTION_NAME}' bereit für angereicherte Materie.")
except Exception as e:
    print(f"[-] Fehler beim Zugriff auf ChromaDB: {e}")
    exit()

# 3. Nemotron Modell laden (Die Supernova-Engine)
print("[+] Lade Nemotron-3-Nano (Das kann einen Moment dauern)...")
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, trust_remote_code=True)
if tokenizer.pad_token_id is None:
    tokenizer.pad_token_id = tokenizer.eos_token_id

model = AutoModelForCausalLM.from_pretrained(
    MODEL_NAME, 
    torch_dtype=torch.bfloat16, 
    device_map="auto", 
    trust_remote_code=True
)
print("[+] Nemotron-Engine läuft auf:", model.device)

# 4. Supernova-Funktion (Extraktion schwerer Elemente)
def forge_heavy_elements(raw_chunk: str) -> str:
    """
    Zwingt das Modell, die tiefen Konzepte des Chunks zu extrahieren.
    Sicheres VRAM-Management durch GC und Chunk-Limitierung.
    """
    import gc
    
    # Kappe den Text für das Modell auf max. 1500 Zeichen, um eine 
    # O(N^2) Explosion der Attention-Matrix (ohne Cache) zu verhindern.
    safe_chunk = raw_chunk[:1500] 
    
    prompt = f"""Extrahiere die drei wichtigsten philosophischen oder technischen Kernkonzepte aus dem folgenden Text. Antworte nur mit Stichworten, ohne Einleitung.
    
Text:
{safe_chunk}

Kernkonzepte:"""
    
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    
    with torch.no_grad():
        # Generierung (use_cache=False wegen des bekannten Bugs!)
        outputs = model.generate(
            **inputs, 
            max_new_tokens=50, 
            use_cache=False, 
            pad_token_id=tokenizer.eos_token_id,
            temperature=0.3,
            do_sample=True
        )
    
    response = tokenizer.decode(outputs[0][inputs.input_ids.shape[1]:], skip_special_tokens=True).strip()
    
    # ---------------------------------------------------------
    # THERMODYNAMISCHE REINIGUNG (VRAM sofort freigeben!)
    # ---------------------------------------------------------
    del inputs
    del outputs
    gc.collect()
    torch.cuda.empty_cache()
    
    return response

# 5. Dokumenten-Verarbeitung (Die Sternenentstehung)
md_files = [f for f in os.listdir(DOCS_DIR) if f.endswith('.md')]

for file_name in md_files:
    file_path = os.path.join(DOCS_DIR, file_name)
    print(f"\n[*] Analysiere Wasserstoff-Wolke: {file_name}")
    
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
        
    # Simples Chunking (Trennung nach Absätzen für den Start)
    chunks = [c.strip() for c in content.split("\n\n") if len(c.strip()) > 100]
    
    for i, chunk in enumerate(chunks):
        chunk_id = f"{file_name}_chunk_{i}"
        
        # 5.0 Prüfen, ob der Stern schon existiert (Resume-Funktion)
        existing = collection.get(ids=[chunk_id])
        if existing and existing['ids']:
            print(f"       [SKIP] G-Stern '{chunk_id}' existiert bereits. Überspringe...")
            continue
            
        print(f"    -> Zünde Supernova für Chunk {i+1}/{len(chunks)}...")
        
        # 5.1 Schwere Elemente schmieden (LLM Call)
        heavy_elements = forge_heavy_elements(chunk)
        
        # 5.2 Den G-Stern formen (Konzept + Rohtext)
        enriched_document = f"KERNKONZEPTE: {heavy_elements}\n\nROHTEXT:\n{chunk}"
        
        # 5.3 In der habitablen Zone (ChromaDB) ablegen
        collection.upsert(
            documents=[enriched_document],
            metadatas=[{"source": file_name, "heavy_elements": heavy_elements}],
            ids=[chunk_id]
        )
        print(f"       [OK] G-Stern '{chunk_id}' stabil im Latent Space verankert.")

print("\n" + "="*80)
print("SUPERNOVA ABGESCHLOSSEN. DIE HABITABLE ZONE IST BEREIT.")
print("="*80)
