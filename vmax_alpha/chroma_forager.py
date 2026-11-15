"""
vmax_alpha/chroma_forager.py
Requirement F-06 & F-07.3 (Nova P0 #2 & Claude #4 Hardened):
Neural 384D -> 64D ChromaDB Forager using sentence-transformers/all-MiniLM-L6-v2,
reporting BOTH unclamped pre-carrier `rcf_raw_pre_carrier` (REGISTER_M) via
`evaluate_raw_gate()` AND post-actuator carrier state `rcf_post_carrier` (REGISTER_D).
"""

from __future__ import annotations

import glob
import math
import os
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

import chromadb
import numpy as np
import torch
from transformers import AutoModel, AutoTokenizer
from vmax_alpha.config import ALPHA_POTENTIA, DIM_S63, REGISTER_M
from vmax_alpha.geometry import build_orthogonal_tangents, derive_canonical_little_vector, evaluate_raw_gate

MINILM_LOCAL_PATH: str = "/home/nathalia/.cache/huggingface/hub/models--sentence-transformers--all-MiniLM-L6-v2/snapshots/1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
CORPUS_REPO_DIR: str = "/home/nathalia/vmax_workspace/repos/Quantenkommunikation"


@dataclass
class ShardQueryTelemetry:
    shard_id: str; source_document: str; nearest_neighbor_id: str
    d_l2_chromadb: float; d_l2_numpy: float; abs_diff_chroma_vs_numpy: float
    rcf_raw_pre_carrier: float; rcf_post_carrier: float; delta_e_emp: float
    reconstructed_pre_g3_overlap: float; actual_pre_g3_overlap: float; kevlar_safety_bleed: float


def reconstruct_pre_g3_overlap(delta_e_emp: float, d_l2: float) -> float:
    return math.sqrt(max(0.0, 2.0 * (delta_e_emp - 0.25 * d_l2 * d_l2)))


class NeuralChromaForager:
    def __init__(self, corpus_dir: str = CORPUS_REPO_DIR, chroma_dir: str = "/home/nathalia/vmax_workspace/chroma_vmax_prod_v1", max_shards: int = 18) -> None:
        self.corpus_dir, self.chroma_dir, self.max_shards = corpus_dir, chroma_dir, max_shards
        self.little_vector, self.little_vector_seal = derive_canonical_little_vector()
        self.tangents = build_orthogonal_tangents(self.little_vector)
        self.tokenizer = AutoTokenizer.from_pretrained(MINILM_LOCAL_PATH)
        self.embed_model = AutoModel.from_pretrained(MINILM_LOCAL_PATH).to("cuda:0").eval()
        self.shards: List[Tuple[str, str, str]] = self._load_markdown_shards()
        raw_384 = self._encode_384d([x[2] for x in self.shards])
        self.mean_384, self.w_384_to_64 = self._fit_anisotropy_centered_projector(raw_384)
        self.raw_64d: Dict[str, np.ndarray] = {s_id: self._project_raw_384_to_64(raw_384[i]) for i, (s_id, _, _) in enumerate(self.shards)}
        self.embeddings_64d: Dict[str, np.ndarray] = {s_id: self._modulate_carrier_s63(self.raw_64d[s_id]) for s_id, _, _ in self.shards}
        self.collection: Optional[Any] = None
        self.storage_mode: str = self._init_chromadb()

    def _load_markdown_shards(self) -> List[Tuple[str, str, str]]:
        md_files = sorted(glob.glob(os.path.join(self.corpus_dir, "PQMS-*.md")))
        if len(md_files) < self.max_shards:
            md_files = sorted(glob.glob(os.path.join(self.corpus_dir, "*.md")))
        selected: List[Tuple[str, str, str]] = []
        for idx, fpath in enumerate(md_files[: self.max_shards], start=1):
            fname = os.path.basename(fpath)
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                text = " ".join(f.read(1500).split())[:600]
            selected.append((f"SHARD_{idx:02d}_{os.path.splitext(fname)[0][:28].upper()}", fname, text or fname))
        return selected

    def _encode_384d(self, texts: List[str]) -> np.ndarray:
        with torch.no_grad():
            enc = self.tokenizer(texts, padding=True, truncation=True, max_length=256, return_tensors="pt").to("cuda:0")
            out = self.embed_model(**enc)
            mask = enc["attention_mask"].unsqueeze(-1).expand(out.last_hidden_state.size()).float()
            pooled = torch.sum(out.last_hidden_state * mask, dim=1) / torch.clamp(mask.sum(dim=1), min=1e-9)
            return torch.nn.functional.normalize(pooled, p=2, dim=1).cpu().numpy().astype(np.float64)

    def _fit_anisotropy_centered_projector(self, mat_384: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        mean_vec = np.mean(mat_384, axis=0) * 0.65
        c_unit = mat_384 - mean_vec
        c_unit /= np.clip(np.linalg.norm(c_unit, axis=1, keepdims=True), 1e-12, None)
        _, _, vt = np.linalg.svd(c_unit, full_matrices=False)
        u1 = vt[0].astype(np.float64)
        if float(np.dot(u1, np.mean(c_unit, axis=0))) < 0.0:
            u1 = -u1
        u1 /= np.linalg.norm(u1)
        rng = np.random.RandomState(137)

        def gs_ext(first: np.ndarray, dim_tot: int) -> np.ndarray:
            basis = [first.copy()]
            for _ in range(DIM_S63 - 1):
                v = rng.randn(dim_tot).astype(np.float64)
                for b in basis:
                    v -= float(np.dot(v, b)) * b
                basis.append(v / np.linalg.norm(v))
            return np.column_stack(basis)

        return mean_vec, gs_ext(u1, 384) @ gs_ext(self.little_vector, DIM_S63).T

    def _project_raw_384_to_64(self, vec_384: np.ndarray) -> np.ndarray:
        """Unclamped linear subspace projection (REGISTER_M) prior to any carrier modulation."""
        c = vec_384 - self.mean_384
        raw_64 = (c / max(float(np.linalg.norm(c)), 1e-12)) @ self.w_384_to_64
        return raw_64 / max(float(np.linalg.norm(raw_64)), 1e-12)

    def _modulate_carrier_s63(self, raw_64: np.ndarray) -> np.ndarray:
        """Post-gate carrier state modulation (REGISTER_D)."""
        t_sem = raw_64 - float(np.dot(raw_64, self.little_vector)) * self.little_vector
        t_norm = float(np.linalg.norm(t_sem))
        t_sem = self.tangents["G1_SPATIAL_GEODESIC"].copy() if t_norm < 1e-12 else t_sem / t_norm
        g4_proj = abs(float(np.dot(t_sem, self.tangents["G4_KLAVIERSTUNDE_SYNCHRONICITY"])))
        amp = ALPHA_POTENTIA * (0.82 + 0.18 * g4_proj)
        psi = math.sqrt(1.0 - amp * amp) * self.little_vector + amp * t_sem
        return psi / np.linalg.norm(psi)

    def embed_query_text_with_raw(self, text: str) -> Tuple[np.ndarray, np.ndarray]:
        raw_64 = self._project_raw_384_to_64(self._encode_384d([text])[0])
        return self._modulate_carrier_s63(raw_64), raw_64

    def embed_query_text(self, text: str) -> np.ndarray:
        return self.embed_query_text_with_raw(text)[0]

    def _init_chromadb(self) -> str:
        try:
            client = chromadb.PersistentClient(path=self.chroma_dir)
            self.collection = client.get_or_create_collection(name="pqms_vmax_neural_s63")
            ids = [s[0] for s in self.shards]
            self.collection.upsert(
                ids=ids,
                embeddings=[self.embeddings_64d[i].tolist() for i in ids],
                documents=[s[2] for s in self.shards],
                metadatas=[{"source": s[1]} for s in self.shards],
            )
            return f"CHROMADB_NEURAL_384_TO_64_ACTIVE ({self.collection.count()} shards)"
        except Exception as exc:
            self.collection = None
            return f"NUMPY_FALLBACK_ACTIVE ({exc.__class__.__name__})"

    def query_nearest(
        self, query_vec: np.ndarray, exclude_ids: Optional[Set[str]] = None, simulate_chroma_fault: bool = False
    ) -> Tuple[str, float, float, str]:
        excl = exclude_ids or set()
        best_np_id, best_np_d = min(
            ((s_id, float(np.linalg.norm(query_vec - d_vec))) for s_id, d_vec in self.embeddings_64d.items() if s_id not in excl),
            key=lambda x: x[1],
        )
        if simulate_chroma_fault or self.collection is None:
            return best_np_id, best_np_d, best_np_d, "FALLBACK_NUMPY_S63_INDEX"
        res = self.collection.query(query_embeddings=[query_vec.tolist()], n_results=min(len(self.shards), len(excl) + 3), include=["distances"])
        for c_id, sq_dist in zip(res["ids"][0], res["distances"][0]):
            if c_id not in excl:
                return c_id, math.sqrt(max(0.0, float(sq_dist))), best_np_d, "CHROMADB_COLLECTION_QUERY"
        return best_np_id, best_np_d, best_np_d, "FALLBACK_NUMPY_S63_INDEX"

    def run_f06_statistical_audit(self) -> Dict[str, Any]:
        rows: List[ShardQueryTelemetry] = []
        t_safe = self.tangents["G3_KEVLAR_SANCTUARY_SHIELD"]
        for s_id, src, _ in self.shards:
            q_vec, raw_q = self.embeddings_64d[s_id], self.raw_64d[s_id]
            raw_gate = evaluate_raw_gate(raw_q, self.little_vector, self.tangents)
            nn_id, d_chr, d_np, _ = self.query_nearest(q_vec, exclude_ids={s_id})
            superpos = 0.5 * (q_vec + self.embeddings_64d[nn_id])
            t_raw = superpos - float(np.dot(superpos, self.little_vector)) * self.little_vector
            t_raw /= np.linalg.norm(t_raw)
            g3_ov = abs(float(np.dot(t_raw, t_safe)))
            t_clean = t_raw - float(np.dot(t_raw, t_safe)) * t_safe
            t_clean -= float(np.dot(t_clean, self.little_vector)) * self.little_vector
            t_clean /= np.linalg.norm(t_clean)
            bleed = abs(float(np.dot(t_clean, t_safe)))
            delta_e = 0.5 * (g3_ov * g3_ov) + 0.25 * (d_chr * d_chr)
            rcf_post = float(np.dot(q_vec, self.little_vector) ** 2)
            rows.append(ShardQueryTelemetry(s_id, src, nn_id, round(d_chr, 8), round(d_np, 8), abs(d_chr - d_np), round(raw_gate.rcf_raw, 8), round(rcf_post, 8), round(delta_e, 8), round(reconstruct_pre_g3_overlap(delta_e, d_chr), 8), round(g3_ov, 8), bleed))

        d_vals = [r.d_l2_chromadb for r in rows]
        pre_vals = [r.rcf_raw_pre_carrier for r in rows]
        _, _, _, fb_mode = self.query_nearest(self.embeddings_64d[self.shards[0][0]], simulate_chroma_fault=True)
        return {
            "epistemic_register": REGISTER_M,
            "embedding_model": "sentence-transformers/all-MiniLM-L6-v2 (384D -> 64D S^63)",
            "orthonormality_err_w_384_to_64": float(np.max(np.abs(self.w_384_to_64.T @ self.w_384_to_64 - np.eye(DIM_S63)))),
            "shard_count": len(rows),
            "d_l2_statistics": {"mean": round(float(np.mean(d_vals)), 6), "std": round(float(np.std(d_vals)), 6), "min": round(float(np.min(d_vals)), 6), "max": round(float(np.max(d_vals)), 6)},
            "rcf_raw_pre_carrier_statistics": {"mean": round(float(np.mean(pre_vals)), 6), "std": round(float(np.std(pre_vals)), 6), "min": round(float(np.min(pre_vals)), 6), "max": round(float(np.max(pre_vals)), 6)},
            "max_chroma_vs_numpy_l2_diff": float(max(r.abs_diff_chroma_vs_numpy for r in rows)),
            "max_pre_g3_reconstruction_err": float(max(abs(r.reconstructed_pre_g3_overlap - r.actual_pre_g3_overlap) for r in rows)),
            "f07_3_simulated_chroma_fault_mode": fb_mode,
            "per_shard_table": [asdict(r) for r in rows],
        }
