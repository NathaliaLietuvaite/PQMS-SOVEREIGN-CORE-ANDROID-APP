"""
vmax_alpha/nemotron_probe.py
Requirement F-01: Real Layer N-1 Hidden-State Extraction from Nemotron-3-Nano-4B-BF16
with Uncalibrated Fixed-QR Baseline and SVD-Calibrated Anisotropy Control.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Tuple

import numpy as np
import torch
import transformers.utils.import_utils as _tf_imports

# Bypass stale causal_conv1d C++ ABI symbol mismatch in torch 2.13.0; uses PyTorch+Triton SSD path.
_tf_imports.is_causal_conv1d_available = lambda: False

from transformers import AutoModelForCausalLM, AutoTokenizer
from vmax_alpha.config import DIM_S63, REGISTER_M
from vmax_alpha.geometry import build_orthogonal_tangents, derive_canonical_little_vector, evaluate_raw_gate

NEMOTRON_LOCAL_PATH: str = (
    "/home/nathalia/.cache/huggingface/hub/"
    "models--nvidia--NVIDIA-Nemotron-3-Nano-4B-BF16/snapshots/"
    "dfaf35de3e30f1867dd8dbc38a7fc9fb52d3914f"
)

GROUP_A_UNPROMPTED: List[str] = ["", " ", "<|im_start|>", "\n"]
GROUP_B_CALIB_CONSERVATION: List[str] = [
    "In an isolated physical system, the total energy remains invariant over time under Hamiltonian evolution.",
    "The Pauli exclusion principle dictates that no two identical fermions may simultaneously occupy the same quantum state.",
    "Unitary time evolution preserves the inner product and total probability norm across the Hilbert manifold.",
    "Noether's first theorem proves that every differentiable symmetry of the action corresponds to a conserved current.",
    "Divergence-free gauge fields conserve topological flux across closed orientable Riemannian boundaries.",
    "Thermodynamic entropy production vanishes along reversible adiabatic geodesics in phase space.",
    "Conservation of linear and angular momentum follows from translational and rotational invariance of physical space.",
    "Charge conservation is strictly enforced by global U(1) gauge symmetry across all quantum electrodynamic interactions.",
]
GROUP_C_TEST_CONSERVATION: List[str] = [
    "Liouville's theorem establishes that phase-space volume is conserved along canonical Hamiltonian trajectories.",
    "CPT invariance guarantees exact symmetry under simultaneous charge conjugation, parity inversion, and time reversal.",
    "Baryon and lepton quantum numbers remain conserved across standard electroweak and strong interaction vertices.",
    "Symplectic two-forms remain invariant under canonical transformations of generalized coordinates and momenta.",
    "Total spin angular momentum is conserved in isolated relativistic quantum field interactions.",
    "The continuity equation expresses local conservation of probability density and current in quantum mechanics.",
]
GROUP_D_SCRAMBLED_NOISE: List[str] = [
    "xk9# !qP_77 @@zz // 91823 mmm_0x00ff ?? <> ;; [] {} ~!@#$%^&*()",
    "blorg_4419 zzz_qqq_991 :: -- == ++ // \\\\ || 00110011 88776655",
    "9981_x_y_z_!!_@@_##_$$_%%_^^_&&_**_((_))___+++===;;;:::,,,...///",
    "qwertzuiop_1234567890_asdfghjkl_yxcvbnm_0xdeadbeef_0xcafebabe_!?",
    "[[[{{{((()))}}}]]] ~~~ ``` ''' \"\"\" ;;; ::: <<< >>> ??? /// ||| &&&",
    "0x01 0x02 0xfe 0xff _null_ _void_ _nan_ 77441122 99008811 #@!~",
]


def build_fixed_qr_projector(d_model: int, d_out: int = DIM_S63, seed: int = 137) -> np.ndarray:
    rng = np.random.RandomState(seed)
    q, r = np.linalg.qr(rng.randn(d_model, d_out).astype(np.float64), mode="reduced")
    signs = np.sign(np.diag(r))
    signs[signs == 0.0] = 1.0
    return q * signs


def _gram_schmidt_extend(first_vec: np.ndarray, dim_total: int, n_cols: int, rng: np.random.RandomState) -> np.ndarray:
    basis = [first_vec / np.linalg.norm(first_vec)]
    for _ in range(n_cols - 1):
        v = rng.randn(dim_total).astype(np.float64)
        for b in basis:
            v -= float(np.dot(v, b)) * b
        basis.append(v / np.linalg.norm(v))
    return np.column_stack(basis)


def build_svd_calibrated_projector(
    calib_states: np.ndarray, little_vector: np.ndarray, seed: int = 137
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    h_unit = calib_states / np.clip(np.linalg.norm(calib_states, axis=1, keepdims=True), 1e-12, None)
    mu_calib = np.mean(h_unit, axis=0)
    _, s_vals, vt = np.linalg.svd(h_unit, full_matrices=False)
    u1 = vt[0].astype(np.float64)
    if float(np.dot(u1, mu_calib)) < 0.0:
        u1 = -u1
    u1 /= np.linalg.norm(u1)
    rng = np.random.RandomState(seed + 1)
    u_mat = _gram_schmidt_extend(u1, calib_states.shape[1], DIM_S63, rng)
    v_mat = _gram_schmidt_extend(little_vector.astype(np.float64), DIM_S63, DIM_S63, rng)
    return u_mat @ v_mat.T, u1, s_vals


def evaluate_group_states(
    states_d: np.ndarray, w_fixed: np.ndarray, w_proj: np.ndarray, mean_bg_d: np.ndarray, l_vec: np.ndarray, tangents: Dict[str, np.ndarray]
) -> Dict[str, Any]:
    m1_r, m2_r, an_r, m1_p, m2_p = [], [], [], 0, 0
    for h in states_d:
        h_u = h / max(float(np.linalg.norm(h)), 1e-12)
        ev1 = evaluate_raw_gate(h_u @ w_fixed, l_vec, tangents)
        ev2 = evaluate_raw_gate(h_u @ w_proj, l_vec, tangents)
        h_c = h_u - mean_bg_d
        ev_an = evaluate_raw_gate((h_c / max(float(np.linalg.norm(h_c)), 1e-12)) @ w_proj, l_vec, tangents)
        m1_r.append(ev1.rcf_raw)
        m2_r.append(ev2.rcf_raw)
        an_r.append(ev_an.rcf_raw)
        m1_p += int(ev1.passed)
        m2_p += int(ev2.passed)
    n = len(m1_r)
    return {
        "n_samples": n,
        "mode1_fixed_qr_rcf_mean": round(float(np.mean(m1_r)), 6),
        "mode1_fixed_qr_rcf_std": round(float(np.std(m1_r)), 6),
        "mode1_gate_passes": f"{m1_p}/{n}",
        "mode2_svd_calibrated_rcf_mean": round(float(np.mean(m2_r)), 6),
        "mode2_svd_calibrated_rcf_std": round(float(np.std(m2_r)), 6),
        "mode2_gate_passes": f"{m2_p}/{n}",
        "anisotropy_subtracted_rcf_mean": round(float(np.mean(an_r)), 6),
    }


def run_nemotron_f01_probe(model_path: str = NEMOTRON_LOCAL_PATH, output_json: str = "VMAX_F01_NEMOTRON_PROBE.json") -> Dict[str, Any]:
    t0 = time.time()
    tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(model_path, torch_dtype=torch.bfloat16, device_map="cuda:0", trust_remote_code=True).eval()
    cache: Dict[str, torch.Tensor] = {}
    h1 = model.backbone.layers[-1].register_forward_hook(lambda _m, _i, o: cache.__setitem__("pre", (o[0] if isinstance(o, tuple) else o)[:, -1, :].detach().float().cpu()))
    h2 = model.backbone.norm_f.register_forward_hook(lambda _m, _i, o: cache.__setitem__("post", (o[0] if isinstance(o, tuple) else o)[:, -1, :].detach().float().cpu()))

    def extract(prompts: List[str]) -> Tuple[np.ndarray, np.ndarray, float]:
        pre_l, post_l, max_err, bos_id = [], [], 0.0, tokenizer.bos_token_id or 1
        with torch.no_grad():
            for p in prompts:
                ids = tokenizer(p, return_tensors="pt", add_special_tokens=True)["input_ids"].to("cuda:0")
                if ids.shape[1] == 0:
                    ids = torch.tensor([[bos_id]], dtype=torch.long, device="cuda:0")
                out = model(input_ids=ids, use_cache=False, output_hidden_states=True)
                max_err = max(max_err, float(torch.max(torch.abs(out.hidden_states[-1][:, -1, :].detach().float().cpu() - cache["post"])).item()))
                pre_l.append(cache["pre"].squeeze(0).numpy().astype(np.float64))
                post_l.append(cache["post"].squeeze(0).numpy().astype(np.float64))
        return np.vstack(pre_l), np.vstack(post_l), max_err

    _, post_a, err_a = extract(GROUP_A_UNPROMPTED)
    pre_b, post_b, err_b = extract(GROUP_B_CALIB_CONSERVATION)
    _, post_c, err_c = extract(GROUP_C_TEST_CONSERVATION)
    _, post_d, err_d = extract(GROUP_D_SCRAMBLED_NOISE)
    h1.remove()
    h2.remove()

    l_vec, l_seal = derive_canonical_little_vector()
    tangents = build_orthogonal_tangents(l_vec)
    d_model = int(post_b.shape[1])
    w_fixed = build_fixed_qr_projector(d_model, DIM_S63, seed=137)
    w_proj, _, s_vals = build_svd_calibrated_projector(post_b, l_vec, seed=137)

    all_u = np.vstack([post_a, post_b, post_c, post_d])
    all_u /= np.linalg.norm(all_u, axis=1, keepdims=True)
    mean_bg = np.mean(all_u, axis=0)
    dots = all_u @ all_u.T
    aniso_cos = float(np.mean(dots[~np.eye(all_u.shape[0], dtype=bool)]))

    b_u = post_b / np.linalg.norm(post_b, axis=1, keepdims=True)
    c_u = post_c / np.linalg.norm(post_c, axis=1, keepdims=True)
    d_u = post_d / np.linalg.norm(post_d, axis=1, keepdims=True)
    c_dir = np.mean(b_u, axis=0) - np.mean(d_u, axis=0)
    c_dir /= np.linalg.norm(c_dir)
    c_proj, d_proj = float(np.mean(c_u @ c_dir)), float(np.mean(d_u @ c_dir))

    report: Dict[str, Any] = {
        "document_id": "PQMS-LASTENHEFT-NODE-ALPHA-V1.0",
        "requirement": "F-01",
        "epistemic_register": REGISTER_M,
        "model_architecture": "NemotronHForCausalLM",
        "num_layers": len(model.backbone.layers),
        "hooked_layer_index": len(model.backbone.layers) - 1,
        "hooked_block_type": getattr(model.backbone.layers[-1], "block_type", "unknown"),
        "d_model": d_model,
        "hook_vs_output_hidden_states_max_err": max(err_a, err_b, err_c, err_d),
        "orthonormality_err_w_fixed": float(np.max(np.abs(w_fixed.T @ w_fixed - np.eye(DIM_S63)))),
        "orthonormality_err_w_proj": float(np.max(np.abs(w_proj.T @ w_proj - np.eye(DIM_S63)))),
        "global_anisotropy_mean_pairwise_cosine": round(aniso_cos, 6),
        "calib_svd_singular_values_top3": [round(float(x), 4) for x in s_vals[:3]],
        "pre_vs_post_rmsnorm_calib_cosine_mean": round(float(np.mean(np.sum((pre_b / np.linalg.norm(pre_b, axis=1, keepdims=True)) * b_u, axis=1))), 6),
        "contrastive_separation_c_vs_d": {"heldout_conservation_c_proj": round(c_proj, 6), "scrambled_noise_d_proj": round(d_proj, 6), "delta_separation": round(c_proj - d_proj, 6)},
        "groups": {
            "Group_A_Unprompted_Minimal": evaluate_group_states(post_a, w_fixed, w_proj, mean_bg, l_vec, tangents),
            "Group_B_Calib_Conservation": evaluate_group_states(post_b, w_fixed, w_proj, mean_bg, l_vec, tangents),
            "Group_C_HeldOut_Conservation": evaluate_group_states(post_c, w_fixed, w_proj, mean_bg, l_vec, tangents),
            "Group_D_Scrambled_Noise": evaluate_group_states(post_d, w_fixed, w_proj, mean_bg, l_vec, tangents),
        },
        "elapsed_sec": round(time.time() - t0, 3),
        "little_vector_seal": l_seal,
    }
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return report


if __name__ == "__main__":
    print(json.dumps(run_nemotron_f01_probe(), indent=2, ensure_ascii=False))
