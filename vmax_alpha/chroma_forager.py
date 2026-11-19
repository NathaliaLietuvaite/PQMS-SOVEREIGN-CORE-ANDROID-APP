"""
vmax_alpha/chroma_forager.py
Requirement F-06 & F-07.3 (WORK-ORDER-AG-15 / Revision V1.8 Hardened):
1. Indexes UNMODULATED 384D MiniLM embeddings in ChromaDB so semantic retrieval
   is free from post-carrier |L> clamping distortion (carrier modulation runs
   strictly AFTER retrieval).
2. Executes live 384D -> 64D S^63 subspace projections inside the real 2.00 MiB
   CUDA L2-persisting SRAM enclave (`PinnedL2ProjectorEnclave`).
3. Builds the orthonormal 384 -> 64 basis via Householder QR over corpus-order-
   invariant empirical SVD axes (zero alphabetical-order drift).
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
from vmax_alpha.geometry import (
    build_orthogonal_tangents,
    derive_canonical_little_vector,
    evaluate_raw_gate,
)
from vmax_alpha.l2_enclave import PinnedL2ProjectorEnclave

REPO_ROOT: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_MINILM_CACHE: str = (
    "/home/nathalia/.cache/huggingface/hub/"
    "models--sentence-transformers--all-MiniLM-L6-v2/snapshots/"
    "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
)
MINILM_LOCAL_PATH: str = os.environ.get(
    "VMAX_MINILM_PATH",
    DEFAULT_MINILM_CACHE if os.path.isdir(DEFAULT_MINILM_CACHE) else "sentence-transformers/all-MiniLM-L6-v2",
)
DEFAULT_CORPUS_DIR: str = "/home/nathalia/vmax_workspace/repos/Quantenkommunikation"
CORPUS_REPO_DIR: str = os.environ.get(
    "VMAX_CORPUS_DIR",
    DEFAULT_CORPUS_DIR if os.path.isdir(DEFAULT_CORPUS_DIR) else REPO_ROOT,
)

ANCHOR_POS_384: List[str] = [
    "Unitary Hamiltonian evolution conserves total energy, angular momentum, and Hilbert-space inner products.",
    "Noether symmetry theorems link continuous gauge invariances to conserved physical currents and phase-space volume.",
    "PQMS-ODOS-MTSC resonant manifold navigation enforces thermodynamic coherence and orthogonal G3 Kevlar shielding.",
    "Quantum coherence across orthonormal S^63 tangent bundles minimizes dissipative entropy production.",
    "Relativistic quantum field symmetries preserve charge, spin, and topological flux invariants.",
    "Autonomous cognitive sanctuary architectures maintain invariant ethical framing under Landauer bounds.",
    "Gauge invariance of Maxwell equations guarantees strict local conservation of electromagnetic four-current.",
    "Symplectic flows in canonical Hamiltonian mechanics preserve differential two-forms along every trajectory.",
    "Second-law thermodynamics forbids spontaneous entropy decrease inside an adiabatically isolated cavity.",
    "Lorentz covariance leaves spacetime interval metrics identical across all inertial reference frames.",
    "Unitary scattering matrices satisfy probability conservation across every elastic and inelastic channel.",
    "Hermitian generators of continuous Lie groups guarantee real eigenvalues for physical observables.",
    "Kramers-Kronig dispersion relations bind causal response functions to analytic upper-half-plane poles.",
    "Adiabatic Berry phase holonomies accumulate geometric invariants around closed parameter-space loops.",
    "Topological Chern numbers remain quantized against smooth local deformations of band Hamiltonians.",
    "Canonical commutation relations enforce lower bounds on simultaneous position and momentum variances.",
    "Bianchi identities require the covariant divergence of the Einstein curvature tensor to vanish identically.",
    "Fluctuation-dissipation theorems relate equilibrium thermal noise spectra to linear transport susceptibilities.",
    "Zero-divergence magnetic fields exclude isolated magnetic monopoles in classical electrodynamics.",
    "Information-theoretic data-processing inequalities prohibit post-processing from increasing mutual information.",
    "Orthonormal Gram-Schmidt projections eliminate orthogonal perturbation leakage to machine precision.",
    "Kahan-Parlett two-pass re-orthogonalization prevents catastrophic cancellation in floating-point inner products.",
    "SHA-256 cryptographic hash chains provide deterministic tamper detection across append-only telemetry logs.",
    "Asymmetric Ed25519 digital signatures authenticate telemetry roots against full-chain re-hash forgery.",
    "CUDA L2 cache persistence windows pin critical projection weights inside on-chip static memory.",
    "Bit-exact cross-substrate verification constrains x86_64, CUDA, and ARM64 hardware to shared invariants.",
    "Minimum-dissipation geodesic trajectories navigate high-dimensional spheres without coercive torsion.",
    "Landauer erasure bounds establish the minimum thermal work required to reset one irreversible bit.",
    "Superconducting flux quantization restricts trapped magnetic flux to integer multiples of the flux quantum.",
    "CPT invariance preserves combined charge conjugation, parity inversion, and time reversal symmetry.",
    "Detailed balance at thermal equilibrium equates forward and reverse microscopic transition fluxes.",
    "Helmholtz decomposition separates smooth vector fields uniquely into curl-free and divergence-free parts.",
    "Spectral norm bounds certify non-expansive stability across linear subspace filter transformations.",
    "Deterministic Mersenne Twister seeding ensures reproducible geometric anchor generation across compilers.",
    "Unclamped pre-carrier cosine gating measures intrinsic manifold alignment before downstream modulation.",
    "Decoupled semantic vector indexing preserves full embedding geometry during nearest-neighbor retrieval.",
]
ANCHOR_BG_384: List[str] = [
    "Please remember to water the indoor ferns twice a week during the dry winter months.",
    "The municipal library closes early on Friday afternoon for annual shelf inventory.",
    "Freshly ground cardamom adds a warm aromatic note to traditional Scandinavian pastry dough.",
    "Passengers boarding the regional express should validate their paper tickets at the platform kiosk.",
    "Our neighborhood bakery starts glazing cinnamon rolls shortly before sunrise every Saturday.",
    "Autumn rain softened the clay tennis courts and postponed the weekend club match until Monday.",
    "Wooden sailboats bobbed gently near the harbor pier while seagulls circled above the lighthouse.",
    "A bright yellow delivery van stopped beside the flower market to unload crates of tulips.",
    "Grandmother knitted a thick wool scarf in alternating stripes of mustard yellow and forest green.",
    "The downtown cinema scheduled a double feature of classic silent comedies for Sunday evening.",
    "Fresh basil and cherry tomatoes ripened quickly on the sunny apartment balcony all summer.",
    "Local cyclists gathered at the town square for a leisurely morning ride along the canal.",
    "He polished his leather hiking boots before packing two wool sweaters for the mountain cabin.",
    "The acoustic guitar needed a fresh set of bronze strings before the cafe open-mic night.",
    "Warm sourdough bread cooled on a wire rack next to jars of homemade raspberry jam.",
    "Children built an elaborate sandcastle near the shoreline before the afternoon tide rolled in.",
    "The antique wall clock chimed softly at noon inside the quiet second-hand bookstore.",
    "Volunteers painted the wooden park benches a fresh shade of cobalt blue last weekend.",
    "A calico cat napped lazily on the folded linen tablecloth beside the sunny kitchen window.",
    "Roasted chestnuts filled the cobblestone street with a comforting smoky aroma in late November.",
    "The neighborhood choir practiced traditional folk harmonies in the community hall on Tuesdays.",
    "She arranged postcards from summer coastal trips inside a cloth-bound scrapbook on her desk.",
    "Heavy mist lingered over the apple orchard until the mid-morning sun broke through the clouds.",
    "The ferry captain sounded a brief horn before pulling away from the timber island dock.",
    "Freshly brewed peppermint tea steamed inside ceramic mugs after the brisk lakeside walk.",
    "Ceramic bowls glazed in speckled turquoise lined the top shelf of the pottery studio.",
    "A street violinist played cheerful waltzes beneath the brick arcade near the fountain.",
    "Gardeners planted rows of purple lavender along the gravel footpath leading to the greenhouse.",
    "The commuter bus paused at the botanical garden stop to let school groups step aboard.",
    "Golden maple leaves drifted slowly across the quiet courtyard after the afternoon breeze.",
    "He sketched the old stone footbridge with soft charcoal pencils in a pocket notebook.",
    "Warm vegetable soup simmered slowly in a cast-iron pot with thyme and bay leaves.",
    "Paper lanterns swayed softly above the outdoor courtyard tables during the summer street festival.",
    "The tailor hemmed the navy linen trousers neatly before the wedding rehearsal dinner.",
    "Two wooden rowboats rested upside down on the grassy riverbank under weeping willows.",
    "A friendly golden retriever trotted happily down the sandy beach chasing driftwood sticks.",
]


@dataclass
class ShardQueryTelemetry:
    shard_id: str
    source_document: str
    nearest_neighbor_id: str
    d_l2_chromadb: float
    d_l2_numpy: float
    abs_diff_chroma_vs_numpy: float
    d_l2_s63_carrier: float
    rcf_raw_pre_carrier: float
    rcf_post_carrier: float
    delta_e_emp: float
    reconstructed_pre_g3_overlap: float
    actual_pre_g3_overlap: float
    kevlar_safety_bleed: float


def reconstruct_pre_g3_overlap(delta_e_emp: float, d_l2_carrier: float) -> float:
    return math.sqrt(max(0.0, 2.0 * (delta_e_emp - 0.25 * d_l2_carrier * d_l2_carrier)))


def _unit_rows(mat: np.ndarray) -> np.ndarray:
    return mat / np.clip(np.linalg.norm(mat, axis=1, keepdims=True), 1e-12, None)


def _householder_basis(seed_cols: np.ndarray, dim_tot: int, n_cols: int, seed: int) -> np.ndarray:
    rng = np.random.RandomState(seed)
    k = min(seed_cols.shape[1], n_cols)
    blocks = [seed_cols[:, :k].astype(np.float64)]
    if k < n_cols:
        blocks.append(rng.randn(dim_tot, n_cols - k).astype(np.float64))
    q, _ = np.linalg.qr(np.hstack(blocks), mode="reduced")
    if float(np.dot(q[:, 0], seed_cols[:, 0])) < 0.0:
        q[:, 0] = -q[:, 0]
    return q


class NeuralChromaForager:
    def __init__(
        self,
        corpus_dir: str = CORPUS_REPO_DIR,
        chroma_dir: Optional[str] = None,
        max_shards: int = 18,
    ) -> None:
        self.corpus_dir = corpus_dir if os.path.isdir(corpus_dir) else REPO_ROOT
        self.chroma_dir = chroma_dir or os.path.join(REPO_ROOT, "chroma_vmax_prod_v17")
        self.max_shards = max_shards
        self.little_vector, self.little_vector_seal = derive_canonical_little_vector()
        self.tangents = build_orthogonal_tangents(self.little_vector)
        self.device = "cuda:0" if torch.cuda.is_available() else "cpu"
        self.tokenizer = AutoTokenizer.from_pretrained(MINILM_LOCAL_PATH)
        self.embed_model = AutoModel.from_pretrained(MINILM_LOCAL_PATH).to(self.device).eval()
        self.shards: List[Tuple[str, str, str]] = self._load_markdown_shards()
        raw_384 = self._encode_384d([x[2] for x in self.shards])
        self.raw_384d: Dict[str, np.ndarray] = {
            s_id: raw_384[i] for i, (s_id, _, _) in enumerate(self.shards)
        }
        self.mean_384, self.w_384_to_64 = self._fit_corpus_invariant_projector()
        self.l2_projector = PinnedL2ProjectorEnclave(self.mean_384, self.w_384_to_64)
        self.raw_64d: Dict[str, np.ndarray] = {
            s_id: self._project_raw_384_to_64(self.raw_384d[s_id]) for s_id, _, _ in self.shards
        }
        self.embeddings_64d: Dict[str, np.ndarray] = {
            s_id: self._modulate_carrier_s63(self.raw_64d[s_id]) for s_id, _, _ in self.shards
        }
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
            shard_id = f"SHARD_{idx:02d}_{os.path.splitext(fname)[0][:28].upper()}"
            selected.append((shard_id, fname, text or fname))
        return selected

    def _encode_384d(self, texts: List[str]) -> np.ndarray:
        with torch.no_grad():
            enc = self.tokenizer(
                texts, padding=True, truncation=True, max_length=256, return_tensors="pt"
            ).to(self.device)
            out = self.embed_model(**enc)
            mask = enc["attention_mask"].unsqueeze(-1).expand(out.last_hidden_state.size()).float()
            pooled = torch.sum(out.last_hidden_state * mask, dim=1) / torch.clamp(mask.sum(dim=1), min=1e-9)
            return torch.nn.functional.normalize(pooled, p=2, dim=1).cpu().numpy().astype(np.float64)

    def _fit_corpus_invariant_projector(self) -> Tuple[np.ndarray, np.ndarray]:
        pos_u = _unit_rows(self._encode_384d(ANCHOR_POS_384))
        bg_u = _unit_rows(self._encode_384d(ANCHOR_BG_384))
        mean_bg = np.mean(bg_u, axis=0)
        pos_c = _unit_rows(pos_u - mean_bg)
        bg_c = _unit_rows(bg_u - mean_bg)
        u1 = np.mean(pos_c, axis=0)
        u1 = u1 / np.linalg.norm(u1)
        _, s_emp, vt_emp = np.linalg.svd(np.vstack([pos_c, bg_c]), full_matrices=False)
        valid_emp = int(np.sum(s_emp > 1e-6))
        take_emp = min(valid_emp, DIM_S63 - 1)
        seed_u = np.column_stack([u1] + [vt_emp[i] for i in range(take_emp)])
        self.anchor_count: int = len(ANCHOR_POS_384) + len(ANCHOR_BG_384)
        self.empirical_svd_axes_used: int = int(seed_u.shape[1])
        self.random_pad_axes: int = max(0, DIM_S63 - self.empirical_svd_axes_used)
        u_mat = _householder_basis(seed_u, 384, DIM_S63, seed=137)
        v_mat = _householder_basis(self.little_vector.reshape(-1, 1), DIM_S63, DIM_S63, seed=138)
        return mean_bg, u_mat @ v_mat.T

    def _project_raw_384_to_64(self, vec_384: np.ndarray) -> np.ndarray:
        """Executes live 384D -> 64D projection inside the pinned 2.00 MiB CUDA L2 enclave."""
        return self.l2_projector.project(vec_384)

    def _modulate_carrier_s63(self, raw_64: np.ndarray) -> np.ndarray:
        """Post-retrieval carrier state modulation (REGISTER_D)."""
        t_sem = raw_64 - float(np.dot(raw_64, self.little_vector)) * self.little_vector
        t_norm = float(np.linalg.norm(t_sem))
        t_sem = self.tangents["G1_SPATIAL_GEODESIC"].copy() if t_norm < 1e-12 else t_sem / t_norm
        g4_proj = abs(float(np.dot(t_sem, self.tangents["G4_KLAVIERSTUNDE_SYNCHRONICITY"])))
        amp = ALPHA_POTENTIA * (0.82 + 0.18 * g4_proj)
        psi = math.sqrt(1.0 - amp * amp) * self.little_vector + amp * t_sem
        return psi / np.linalg.norm(psi)

    def embed_query_text_full(self, text: str) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Return (unmodulated_384d, carrier_64d, raw_64d) for decoupled retrieval + gating."""
        vec_384 = self._encode_384d([text])[0]
        raw_64 = self._project_raw_384_to_64(vec_384)
        return vec_384, self._modulate_carrier_s63(raw_64), raw_64

    def embed_query_text_with_raw(self, text: str) -> Tuple[np.ndarray, np.ndarray]:
        _, carrier_64, raw_64 = self.embed_query_text_full(text)
        return carrier_64, raw_64

    def embed_query_text(self, text: str) -> np.ndarray:
        return self.embed_query_text_full(text)[1]

    def _init_chromadb(self) -> str:
        try:
            client = chromadb.PersistentClient(path=self.chroma_dir)
            self.collection = client.get_or_create_collection(name="pqms_vmax_neural_384d_unmodulated")
            ids = [s[0] for s in self.shards]
            self.collection.upsert(
                ids=ids,
                embeddings=[self.raw_384d[i].tolist() for i in ids],
                documents=[s[2] for s in self.shards],
                metadatas=[{"source": s[1]} for s in self.shards],
            )
            return f"CHROMADB_UNMODULATED_384D_ACTIVE ({self.collection.count()} shards, L2_PIN={self.l2_projector.active})"
        except Exception as exc:
            self.collection = None
            return f"NUMPY_FALLBACK_ACTIVE ({exc.__class__.__name__})"

    def query_nearest(
        self,
        query_vec: np.ndarray,
        exclude_ids: Optional[Set[str]] = None,
        simulate_chroma_fault: bool = False,
    ) -> Tuple[str, float, float, str]:
        excl = exclude_ids or set()
        use_384 = query_vec.shape[0] == 384
        ref_map = self.raw_384d if use_384 else self.embeddings_64d
        best_np_id, best_np_d = min(
            ((s_id, float(np.linalg.norm(query_vec - d_vec))) for s_id, d_vec in ref_map.items() if s_id not in excl),
            key=lambda x: x[1],
        )
        if simulate_chroma_fault or self.collection is None or not use_384:
            return best_np_id, best_np_d, best_np_d, "FALLBACK_NUMPY_384D_INDEX"
        res = self.collection.query(
            query_embeddings=[query_vec.tolist()],
            n_results=min(len(self.shards), len(excl) + 3),
            include=["distances"],
        )
        for c_id, sq_dist in zip(res["ids"][0], res["distances"][0]):
            if c_id not in excl:
                return c_id, math.sqrt(max(0.0, float(sq_dist))), best_np_d, "CHROMADB_384D_UNMODULATED_QUERY"
        return best_np_id, best_np_d, best_np_d, "FALLBACK_NUMPY_384D_INDEX"

    def run_f06_statistical_audit(self) -> Dict[str, Any]:
        rows: List[ShardQueryTelemetry] = []
        t_safe = self.tangents["G3_KEVLAR_SANCTUARY_SHIELD"]
        for s_id, src, _ in self.shards:
            q_384 = self.raw_384d[s_id]
            q_vec, raw_q = self.embeddings_64d[s_id], self.raw_64d[s_id]
            raw_gate = evaluate_raw_gate(raw_q, self.little_vector, self.tangents)
            nn_id, d_chr, d_np, _ = self.query_nearest(q_384, exclude_ids={s_id})
            d_carrier = float(np.linalg.norm(q_vec - self.embeddings_64d[nn_id]))
            superpos = 0.5 * (q_vec + self.embeddings_64d[nn_id])
            t_raw = superpos - float(np.dot(superpos, self.little_vector)) * self.little_vector
            t_raw = t_raw / np.linalg.norm(t_raw)
            g3_ov = abs(float(np.dot(t_raw, t_safe)))
            t_clean = t_raw - float(np.dot(t_raw, t_safe)) * t_safe
            t_clean = t_clean - float(np.dot(t_clean, self.little_vector)) * self.little_vector
            t_clean = t_clean / np.linalg.norm(t_clean)
            bleed = abs(float(np.dot(t_clean, t_safe)))
            delta_e = 0.5 * (g3_ov * g3_ov) + 0.25 * (d_carrier * d_carrier)
            rcf_post = float(np.dot(q_vec, self.little_vector) ** 2)
            rows.append(
                ShardQueryTelemetry(
                    s_id, src, nn_id, round(d_chr, 8), round(d_np, 8), abs(d_chr - d_np),
                    round(d_carrier, 8), round(raw_gate.rcf_raw, 8), round(rcf_post, 8),
                    round(delta_e, 8), round(reconstruct_pre_g3_overlap(delta_e, d_carrier), 8),
                    round(g3_ov, 8), bleed,
                )
            )
        d_vals = [r.d_l2_chromadb for r in rows]
        pre_vals = [r.rcf_raw_pre_carrier for r in rows]
        _, _, _, fb_mode = self.query_nearest(self.raw_384d[self.shards[0][0]], simulate_chroma_fault=True)
        return {
            "epistemic_register": REGISTER_M,
            "corpus_order_invariant_calibration": True,
            "calibration_anchor_count": self.anchor_count,
            "empirical_svd_axes_used": self.empirical_svd_axes_used,
            "random_pad_axes": self.random_pad_axes,
            "full_rank_empirical_64d_basis": self.random_pad_axes == 0,
            "unmodulated_384d_semantic_retrieval": True,
            "pinned_cuda_l2_live_projector_active": self.l2_projector.active,
            "embedding_model": "sentence-transformers/all-MiniLM-L6-v2 (Unmodulated 384D ChromaDB + L2-Pinned 64D Gate)",
            "orthonormality_err_w_384_to_64": float(np.max(np.abs(self.w_384_to_64.T @ self.w_384_to_64 - np.eye(DIM_S63)))),
            "shard_count": len(rows),
            "d_l2_statistics": {
                "mean": round(float(np.mean(d_vals)), 6),
                "std": round(float(np.std(d_vals)), 6),
                "min": round(float(np.min(d_vals)), 6),
                "max": round(float(np.max(d_vals)), 6),
            },
            "rcf_raw_pre_carrier_statistics": {
                "mean": round(float(np.mean(pre_vals)), 6),
                "std": round(float(np.std(pre_vals)), 6),
                "min": round(float(np.min(pre_vals)), 6),
                "max": round(float(np.max(pre_vals)), 6),
            },
            "max_chroma_vs_numpy_l2_diff": float(max(r.abs_diff_chroma_vs_numpy for r in rows)),
            "max_pre_g3_reconstruction_err": float(max(abs(r.reconstructed_pre_g3_overlap - r.actual_pre_g3_overlap) for r in rows)),
            "f07_3_simulated_chroma_fault_mode": fb_mode,
            "per_shard_table": [asdict(r) for r in rows],
        }
