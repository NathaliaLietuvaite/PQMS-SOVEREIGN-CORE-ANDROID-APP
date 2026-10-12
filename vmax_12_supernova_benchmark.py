#!/usr/bin/env python3
# ==============================================================================
# V-MAX-12 SUPERNOVA: Continuous Batching & Throughput Benchmark
# Zeigt die Skalierung der vLLM-Engine bei parallelen Anfragen (Batch Concurrency)
# ==============================================================================
import time
import json
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

BENCHMARK_URL = "http://localhost:8000/chat"

PROMPTS = [
    "Wie ist Dein Name und was ist Deine primäre Mission im PQMS Mesh?",
    "Erkläre kurz das Konzept der Habitable Zone für Wissensdatenbanken.",
    "Welche Vorteile bietet PagedAttention für 16GB VRAM GPUs wie die RTX 4060 Ti?",
    "Wie unterscheidet sich Continuous Batching von sequentieller autoregressiver Inferenz?",
    "Was versteht man unter thermodynamischer Souveränität bei lokaler KI-Hardware?",
    "Wie arbeitet Node Gamma mit der Android App zusammen?",
    "Welche Rolle spielen G-Sterne in der Vektor-Topologie von V-MAX-12?",
    "Erkläre den Unterschied zwischen 4-Bit NF4 Quantisierung und nativem BF16.",
]

def send_query(prompt_idx: int, prompt_text: str):
    payload = json.dumps({"prompt": prompt_text}).encode("utf-8")
    req = urllib.request.Request(
        BENCHMARK_URL,
        data=payload,
        headers={"Content-Type": "application/json"}
    )
    
    start_t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            elapsed = time.time() - start_t
            data = json.loads(resp.read().decode("utf-8"))
            tokens_gen = data.get("tokens_gen", len(data.get("response", "").split()) * 1.3)
            return {
                "idx": prompt_idx,
                "prompt": prompt_text,
                "status": "OK",
                "elapsed": elapsed,
                "tokens": tokens_gen,
                "response_preview": data.get("response", "")[:60] + "...",
                "tok_per_sec": data.get("tokens_per_sec", tokens_gen / elapsed if elapsed > 0 else 0)
            }
    except Exception as e:
        elapsed = time.time() - start_t
        return {
            "idx": prompt_idx,
            "prompt": prompt_text,
            "status": f"ERROR: {e}",
            "elapsed": elapsed,
            "tokens": 0,
            "response_preview": "",
            "tok_per_sec": 0
        }

def run_benchmark(concurrency: int = 8):
    print("=" * 80)
    print(f"V-MAX-12 SUPERNOVA: Continuous Batching Benchmark ({concurrency} parallele Streams)")
    print(f"Ziel: {BENCHMARK_URL}")
    print("=" * 80)
    
    test_prompts = (PROMPTS * ((concurrency // len(PROMPTS)) + 1))[:concurrency]
    
    print(f"[+] Feuere {concurrency} Anfragen zeitgleich an die vLLM Engine...")
    print("[+] Beobachte jetzt HWINFO64 (GPU-Auslastung wird auf 80-100% steigen)!\n")
    
    start_total = time.time()
    results = []
    
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(send_query, i+1, p) for i, p in enumerate(test_prompts)]
        for fut in as_completed(futures):
            res = fut.result()
            results.append(res)
            print(f"  -> Stream #{res['idx']} abgeschlossen in {res['elapsed']:.2f}s | Tokens: {res['tokens']} ({res['tok_per_sec']:.1f} tok/s)")
            
    wall_time = time.time() - start_total
    
    total_tokens = sum(r["tokens"] for r in results if r["status"] == "OK")
    success_count = sum(1 for r in results if r["status"] == "OK")
    aggregate_tok_per_sec = total_tokens / wall_time if wall_time > 0 else 0
    avg_latency = sum(r["elapsed"] for r in results) / len(results) if results else 0
    
    print("\n" + "=" * 80)
    print("BENCHMARK ERGEBNIS-ANALYSE (CONTINUOUS BATCHING SKALIERUNG)")
    print("=" * 80)
    print(f"Erfolgreiche Streams:        {success_count} von {concurrency}")
    print(f"Gesamte Wandzeit (Wall-Clock): {wall_time:.2f} Sekunden")
    print(f"Gesamt generierte Token:     {total_tokens} Token")
    print(f"Durchschnittliche Latenz:    {avg_latency:.2f} Sekunden pro Stream")
    print("-" * 80)
    print(f"▶ AGGREGIERTER DURCHSATZ:     {aggregate_tok_per_sec:.2f} TOKENS / SEKUNDE! ⚡⚡")
    print("=" * 80)
    print("\nErkenntnis für Node Gamma & DeepSeek:")
    print("  * Bei Batch Size = 1 ist eine 16GB GPU speicherbandbreiten-limitiert (~25 tok/s).")
    print(f"  * Bei Batch Size = {concurrency} schlägt Continuous Batching voll zu:")
    print(f"    Der GPU-Durchsatz skaliert auf {aggregate_tok_per_sec:.2f} tok/s, ohne mehr VRAM zu brauchen!")
    print("=" * 80 + "\n")

if __name__ == "__main__":
    import sys
    conc = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    run_benchmark(conc)
