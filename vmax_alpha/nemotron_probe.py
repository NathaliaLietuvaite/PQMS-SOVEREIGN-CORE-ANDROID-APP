"""
vmax_alpha/nemotron_probe.py
Requirement F-01 (WORK-ORDER-AG-15 / Revision V1.8 Hardened):
Clean PEP-8 Layer-41 activation probe on Nemotron-3-Nano-4B-BF16 featuring:
1. N=25 held-out prompts per group (625 pairs), including domain-matched physics
   Hard Negatives (Group F) alongside fluent prose (E) and scrambled noise (D).
2. Dual leak-free probes: Topic/Domain Probe (B_pos vs B_bg) AND Truth/Polarity
   Probe (B_pos vs B_hard_neg), both last-token and dedicated mean-pooled.
3. Data-driven multi-axis Householder-QR SVD basis (no random-GS degradation).
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any, Dict, List, Tuple

import numpy as np
import torch
from scipy.stats import mannwhitneyu
import transformers.utils.import_utils as _tf_imports

_tf_imports.is_causal_conv1d_available = lambda: False

from transformers import AutoModelForCausalLM, AutoTokenizer
from vmax_alpha.config import DIM_S63, REGISTER_M
from vmax_alpha.geometry import (
    build_orthogonal_tangents,
    derive_canonical_little_vector,
    evaluate_raw_gate,
)

DEFAULT_NEMOTRON_CACHE: str = (
    "/home/nathalia/.cache/huggingface/hub/"
    "models--nvidia--NVIDIA-Nemotron-3-Nano-4B-BF16/snapshots/"
    "dfaf35de3e30f1867dd8dbc38a7fc9fb52d3914f"
)
NEMOTRON_LOCAL_PATH: str = os.environ.get(
    "VMAX_NEMOTRON_PATH",
    DEFAULT_NEMOTRON_CACHE if os.path.isdir(DEFAULT_NEMOTRON_CACHE) else "nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16",
)
PROMPTS_JSON_PATH: str = os.path.join(os.path.dirname(os.path.abspath(__file__)), "f01_prompts.json")

with open(PROMPTS_JSON_PATH, "rb") as _pf:
    _PROMPT_RAW = _pf.read()
PROMPT_CORPUS_SHA256: str = hashlib.sha256(_PROMPT_RAW).hexdigest()
_PROMPTS: Dict[str, Any] = json.loads(_PROMPT_RAW.decode("utf-8"))

GROUP_A_UNPROMPTED: List[str] = _PROMPTS["Group_A_Unprompted_Minimal"]
GROUP_B_CALIB_CONSERVATION: List[str] = _PROMPTS["Group_B_Calib_Conservation"]
GROUP_B_CALIB_BACKGROUND: List[str] = _PROMPTS["Group_B_Calib_Background"]
GROUP_B_CALIB_HARD_NEG: List[str] = _PROMPTS["Group_B_Calib_HardNegatives"]
GROUP_C_TEST_CONSERVATION: List[str] = _PROMPTS["Group_C_HeldOut_Conservation"]
GROUP_D_SCRAMBLED_NOISE: List[str] = _PROMPTS["Group_D_Scrambled_Noise"]
GROUP_E_FLUENT_NON_CONSERVATION: List[str] = _PROMPTS["Group_E_Fluent_NonConservation"]
GROUP_F_PHYSICS_HARD_NEGATIVES: List[str] = _PROMPTS["Group_F_Physics_Hard_Negatives"]


def _unit_rows(mat: np.ndarray) -> np.ndarray:
    return mat / np.clip(np.linalg.norm(mat, axis=1, keepdims=True), 1e-12, None)


def _roc_auc(pos: np.ndarray, neg: np.ndarray) -> float:
    diff = pos[:, None] - neg[None, :]
    return float(np.mean((diff > 0).astype(np.float64) + 0.5 * (diff == 0).astype(np.float64)))


def _auc_stats(pos: List[float], neg: List[float], n_boot: int = 2000, seed: int = 137) -> Dict[str, Any]:
    p_arr = np.asarray(pos, dtype=np.float64)
    n_arr = np.asarray(neg, dtype=np.float64)
    auc = _roc_auc(p_arr, n_arr)
    rng = np.random.RandomState(seed)
    boots = [
        _roc_auc(
            p_arr[rng.randint(0, len(p_arr), len(p_arr))],
            n_arr[rng.randint(0, len(n_arr), len(n_arr))],
        )
        for _ in range(n_boot)
    ]
    ci_lo, ci_hi = np.percentile(boots, [2.5, 97.5])
    mw = mannwhitneyu(p_arr, n_arr, alternative="two-sided")
    return {
        "roc_auc": round(auc, 6),
        "ci95_low": round(float(ci_lo), 6),
        "ci95_high": round(float(ci_hi), 6),
        "mann_whitney_u": round(float(mw.statistic), 2),
        "p_value": float(f"{float(mw.pvalue):.3e}"),
        "n_pairs": int(len(p_arr) * len(n_arr)),
    }


def build_fixed_qr_projector(d_model: int, d_out: int = DIM_S63, seed: int = 137) -> np.ndarray:
    rng = np.random.RandomState(seed)
    q, r = np.linalg.qr(rng.randn(d_model, d_out).astype(np.float64), mode="reduced")
    signs = np.sign(np.diag(r))
    signs[signs == 0.0] = 1.0
    return q * signs


def _householder_qr_basis(seed_cols: np.ndarray, dim_total: int, n_cols: int, seed: int) -> np.ndarray:
    """Build an orthonormal (dim_total, n_cols) basis via Householder QR preserving seed_cols[:, 0]."""
    rng = np.random.RandomState(seed)
    k = min(seed_cols.shape[1], n_cols)
    cols = [seed_cols[:, :k].astype(np.float64)]
    if k < n_cols:
        cols.append(rng.randn(dim_total, n_cols - k).astype(np.float64))
    raw_mat = np.hstack(cols)
    q, r = np.linalg.qr(raw_mat, mode="reduced")
    if float(np.dot(q[:, 0], seed_cols[:, 0])) < 0.0:
        q[:, 0] = -q[:, 0]
    return q


def fit_leakfree_calibration(
    calib_pos: np.ndarray,
    calib_bg: np.ndarray,
    little_vec: np.ndarray,
    seed: int = 137,
    calib_extra: np.ndarray | None = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Fit data-driven multi-axis Householder-QR projectors strictly on calibration split."""
    pos_u = _unit_rows(calib_pos)
    bg_u = _unit_rows(calib_bg)
    mean_bg = np.mean(bg_u, axis=0)
    _, s_vals, vt_raw = np.linalg.svd(pos_u, full_matrices=False)
    u1_raw = vt_raw[0].astype(np.float64)
    if float(np.dot(u1_raw, np.mean(pos_u, axis=0))) < 0.0:
        u1_raw = -u1_raw
    pos_c = _unit_rows(pos_u - mean_bg)
    bg_c = _unit_rows(bg_u - mean_bg)
    c_dir = np.mean(pos_c, axis=0) - np.mean(bg_c, axis=0)
    c_dir = c_dir / np.linalg.norm(c_dir)
    u1_pos = np.mean(pos_c, axis=0)
    u1_pos = u1_pos / np.linalg.norm(u1_pos)

    # Empirical multi-axis SVD basis across calibration classes via Householder QR
    stack_list = [pos_c, bg_c]
    if calib_extra is not None:
        stack_list.append(_unit_rows(_unit_rows(calib_extra) - mean_bg))
    centered_stack = np.vstack(stack_list)
    _, _, vt_emp = np.linalg.svd(centered_stack, full_matrices=False)
    seed_u = np.column_stack([u1_pos] + [vt_emp[i] for i in range(min(vt_emp.shape[0], DIM_S63 - 1))])
    v_mat = _householder_qr_basis(little_vec.astype(np.float64).reshape(-1, 1), DIM_S63, DIM_S63, seed + 1)
    u_raw = _householder_qr_basis((u1_raw / np.linalg.norm(u1_raw)).reshape(-1, 1), calib_pos.shape[1], DIM_S63, seed + 2)
    u_aniso = _householder_qr_basis(seed_u, calib_pos.shape[1], DIM_S63, seed + 3)
    return u_raw @ v_mat.T, u_aniso @ v_mat.T, mean_bg, c_dir, s_vals


def evaluate_group(
    states: np.ndarray,
    mean_pooled: np.ndarray,
    w_fixed: np.ndarray,
    w_raw: np.ndarray,
    w_aniso: np.ndarray,
    mean_bg: np.ndarray,
    c_dir: np.ndarray,
    mean_bg_mp: np.ndarray,
    c_dir_mp: np.ndarray,
    mean_hn_mp: np.ndarray,
    pol_dir_mp: np.ndarray,
    mean_hn_lt: np.ndarray,
    pol_dir_lt: np.ndarray,
    l_vec: np.ndarray,
    tangents: Dict[str, np.ndarray],
) -> Dict[str, Any]:
    m1_r, m2_r, an_r, c_projs, mp_r, pol_lt, pol_mp = [], [], [], [], [], [], []
    m1_p, m2_p = 0, 0
    for h, h_mp in zip(_unit_rows(states), _unit_rows(mean_pooled)):
        ev1 = evaluate_raw_gate(h @ w_fixed, l_vec, tangents)
        ev2 = evaluate_raw_gate(h @ w_raw, l_vec, tangents)
        hc = (h - mean_bg) / max(float(np.linalg.norm(h - mean_bg)), 1e-12)
        ev_an = evaluate_raw_gate(hc @ w_aniso, l_vec, tangents)
        h_mpc = (h_mp - mean_bg_mp) / max(float(np.linalg.norm(h_mp - mean_bg_mp)), 1e-12)
        h_pol_lt = (h - mean_hn_lt) / max(float(np.linalg.norm(h - mean_hn_lt)), 1e-12)
        h_pol_mp = (h_mp - mean_hn_mp) / max(float(np.linalg.norm(h_mp - mean_hn_mp)), 1e-12)
        m1_r.append(ev1.rcf_raw)
        m2_r.append(ev2.rcf_raw)
        an_r.append(ev_an.rcf_raw)
        c_projs.append(float(np.dot(hc, c_dir)))
        mp_r.append(float(np.dot(h_mpc, c_dir_mp)))
        pol_lt.append(float(np.dot(h_pol_lt, pol_dir_lt)))
        pol_mp.append(float(np.dot(h_pol_mp, pol_dir_mp)))
        m1_p += int(ev1.passed)
        m2_p += int(ev2.passed)
    n = len(m1_r)
    return {
        "n_samples": n,
        "mode1_fixed_qr_rcf_mean": round(float(np.mean(m1_r)), 6),
        "mode1_fixed_qr_rcf_std": round(float(np.std(m1_r)), 6),
        "mode1_gate_passes": f"{m1_p}/{n}",
        "mode2_raw_uncentered_svd_rcf_mean": round(float(np.mean(m2_r)), 6),
        "mode2_raw_uncentered_svd_rcf_std": round(float(np.std(m2_r)), 6),
        "mode2_raw_gate_passes": f"{m2_p}/{n}",
        "anisotropy_subtracted_rcf_mean": round(float(np.mean(an_r)), 6),
        "anisotropy_subtracted_rcf_std": round(float(np.std(an_r)), 6),
        "last_token_contrastive_proj_mean": round(float(np.mean(c_projs)), 6),
        "last_token_contrastive_proj_std": round(float(np.std(c_projs)), 6),
        "mean_pooled_contrastive_proj_mean": round(float(np.mean(mp_r)), 6),
        "mean_pooled_contrastive_proj_std": round(float(np.std(mp_r)), 6),
        "polarity_probe_last_token_mean": round(float(np.mean(pol_lt)), 6),
        "polarity_probe_mean_pooled_mean": round(float(np.mean(pol_mp)), 6),
        "per_prompt_last_token_proj": [round(x, 6) for x in c_projs],
        "per_prompt_mean_pooled_proj": [round(x, 6) for x in mp_r],
        "per_prompt_polarity_last_token": [round(x, 6) for x in pol_lt],
        "per_prompt_polarity_mean_pooled": [round(x, 6) for x in pol_mp],
    }


def run_nemotron_f01_probe(
    model_path: str = NEMOTRON_LOCAL_PATH,
    output_json: str = "VMAX_F01_NEMOTRON_PROBE.json",
) -> Dict[str, Any]:
    t0 = time.time()
    tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        model_path, dtype=torch.bfloat16, device_map="cuda:0", trust_remote_code=True
    ).eval()
    cache: Dict[str, torch.Tensor] = {}
    h1 = model.backbone.layers[-1].register_forward_hook(
        lambda _m, _i, o: cache.__setitem__("pre", (o[0] if isinstance(o, tuple) else o)[:, -1, :].detach().float().cpu())
    )
    h2 = model.backbone.norm_f.register_forward_hook(
        lambda _m, _i, o: cache.__setitem__("seq", (o[0] if isinstance(o, tuple) else o).detach().float().cpu())
    )

    def extract(prompts: List[str]) -> Tuple[np.ndarray, np.ndarray, np.ndarray, float]:
        pre_l, post_l, mp_l = [], [], []
        max_err = 0.0
        bos_id = tokenizer.bos_token_id or 1
        with torch.no_grad():
            for p in prompts:
                ids = tokenizer(p, return_tensors="pt", add_special_tokens=True)["input_ids"].to("cuda:0")
                if ids.shape[1] == 0:
                    ids = torch.tensor([[bos_id]], dtype=torch.long, device="cuda:0")
                out = model(input_ids=ids, use_cache=False, output_hidden_states=True)
                seq_h = cache["seq"].squeeze(0).numpy().astype(np.float64)
                diff = float(torch.max(torch.abs(out.hidden_states[-1][:, -1, :].detach().float().cpu() - cache["seq"][:, -1, :])).item())
                max_err = max(max_err, diff)
                pre_l.append(cache["pre"].squeeze(0).numpy().astype(np.float64))
                post_l.append(seq_h[-1])
                mp_l.append(np.mean(seq_h, axis=0))
        return np.vstack(pre_l), np.vstack(post_l), np.vstack(mp_l), max_err

    _, post_a, mp_a, err_a = extract(GROUP_A_UNPROMPTED)
    pre_b, post_b, mp_b, err_b = extract(GROUP_B_CALIB_CONSERVATION)
    _, post_bg, mp_bg, _ = extract(GROUP_B_CALIB_BACKGROUND)
    _, post_bhn, mp_bhn, _ = extract(GROUP_B_CALIB_HARD_NEG)
    _, post_c, mp_c, err_c = extract(GROUP_C_TEST_CONSERVATION)
    _, post_d, mp_d, err_d = extract(GROUP_D_SCRAMBLED_NOISE)
    _, post_e, mp_e, err_e = extract(GROUP_E_FLUENT_NON_CONSERVATION)
    _, post_f, mp_f, err_f = extract(GROUP_F_PHYSICS_HARD_NEGATIVES)
    h1.remove()
    h2.remove()

    l_vec, l_seal = derive_canonical_little_vector()
    tangents = build_orthogonal_tangents(l_vec)
    d_model = int(post_b.shape[1])
    w_fixed = build_fixed_qr_projector(d_model, DIM_S63, seed=137)
    w_raw, w_aniso, mean_bg, c_dir, s_vals = fit_leakfree_calibration(post_b, post_bg, l_vec, seed=137, calib_extra=post_bhn)
    _, _, mean_bg_mp, c_dir_mp, _ = fit_leakfree_calibration(mp_b, mp_bg, l_vec, seed=137, calib_extra=mp_bhn)
    _, _, mean_hn_lt, pol_dir_lt, _ = fit_leakfree_calibration(post_b, post_bhn, l_vec, seed=139)
    _, _, mean_hn_mp, pol_dir_mp, _ = fit_leakfree_calibration(mp_b, mp_bhn, l_vec, seed=139)

    rng_ctrl = np.random.RandomState(999)
    l_alt = rng_ctrl.randn(DIM_S63)
    l_alt = l_alt / np.linalg.norm(l_alt)
    _, w_aniso_alt, _, _, _ = fit_leakfree_calibration(post_b, post_bg, l_alt, seed=137, calib_extra=post_bhn)
    c_centered = _unit_rows(_unit_rows(post_c) - mean_bg)
    l_swap_diff = float(np.max(np.abs(np.sum((c_centered @ w_aniso) * l_vec, axis=1) ** 2 - np.sum((c_centered @ w_aniso_alt) * l_alt, axis=1) ** 2)))
    w_shuffled = w_aniso[rng_ctrl.permutation(d_model), :]
    shuffled_c_rcf = float(np.mean([evaluate_raw_gate(h @ w_shuffled, l_vec, tangents).rcf_raw for h in c_centered]))
    calib_all = _unit_rows(np.vstack([post_b, post_bg, post_bhn]))
    aniso_cos = float(np.mean((calib_all @ calib_all.T)[~np.eye(calib_all.shape[0], dtype=bool)]))
    c_proj_var = float(np.sum((c_centered @ w_aniso) ** 2) / max(float(np.sum(c_centered ** 2)), 1e-12))

    eval_args = (w_fixed, w_raw, w_aniso, mean_bg, c_dir, mean_bg_mp, c_dir_mp, mean_hn_mp, pol_dir_mp, mean_hn_lt, pol_dir_lt, l_vec, tangents)
    grp = {
        "Group_A_Unprompted_Minimal": evaluate_group(post_a, mp_a, *eval_args),
        "Group_B_Calib_Conservation": evaluate_group(post_b, mp_b, *eval_args),
        "Group_C_HeldOut_Conservation": evaluate_group(post_c, mp_c, *eval_args),
        "Group_D_Scrambled_Noise": evaluate_group(post_d, mp_d, *eval_args),
        "Group_E_Fluent_NonConservation": evaluate_group(post_e, mp_e, *eval_args),
        "Group_F_Physics_Hard_Negatives": evaluate_group(post_f, mp_f, *eval_args),
    }
    gc, gd, ge, gf = grp["Group_C_HeldOut_Conservation"], grp["Group_D_Scrambled_Noise"], grp["Group_E_Fluent_NonConservation"], grp["Group_F_Physics_Hard_Negatives"]
    lt_ce = _auc_stats(gc["per_prompt_last_token_proj"], ge["per_prompt_last_token_proj"])
    lt_cd = _auc_stats(gc["per_prompt_last_token_proj"], gd["per_prompt_last_token_proj"])
    lt_cf_topic = _auc_stats(gc["per_prompt_last_token_proj"], gf["per_prompt_last_token_proj"])
    mp_ce = _auc_stats(gc["per_prompt_mean_pooled_proj"], ge["per_prompt_mean_pooled_proj"])
    mp_cd = _auc_stats(gc["per_prompt_mean_pooled_proj"], gd["per_prompt_mean_pooled_proj"])
    mp_cf_topic = _auc_stats(gc["per_prompt_mean_pooled_proj"], gf["per_prompt_mean_pooled_proj"])
    pol_cf_lt = _auc_stats(gc["per_prompt_polarity_last_token"], gf["per_prompt_polarity_last_token"])
    pol_cf_mp = _auc_stats(gc["per_prompt_polarity_mean_pooled"], gf["per_prompt_polarity_mean_pooled"])

    report: Dict[str, Any] = {
        "document_id": "PQMS-LASTENHEFT-NODE-ALPHA-V1.0",
        "requirement": "F-01",
        "revision": "V1.8",
        "epistemic_register": REGISTER_M,
        "prompt_corpus_sha256": PROMPT_CORPUS_SHA256,
        "heldout_n_per_group": len(GROUP_C_TEST_CONSERVATION),
        "householder_qr_empirical_svd_basis": True,
        "heldout_c_energy_captured_in_64d": round(c_proj_var, 6),
        "model_architecture": "NemotronHForCausalLM",
        "num_layers": len(model.backbone.layers),
        "hooked_layer_index": len(model.backbone.layers) - 1,
        "hooked_block_type": getattr(model.backbone.layers[-1], "block_type", "unknown"),
        "d_model": d_model,
        "hook_vs_output_hidden_states_max_err": max(err_a, err_b, err_c, err_d, err_e, err_f),
        "zero_data_leakage_calibration": True,
        "dedicated_mean_pool_calibration": True,
        "orthonormality_err_w_fixed": float(np.max(np.abs(w_fixed.T @ w_fixed - np.eye(DIM_S63)))),
        "orthonormality_err_w_proj": float(np.max(np.abs(w_aniso.T @ w_aniso - np.eye(DIM_S63)))),
        "global_anisotropy_mean_pairwise_cosine": round(aniso_cos, 6),
        "calib_svd_singular_values_top3": [round(float(x), 4) for x in s_vals[:3]],
        "pre_vs_post_rmsnorm_calib_cosine_mean": round(float(np.mean(np.sum(_unit_rows(pre_b) * _unit_rows(post_b), axis=1))), 6),
        "claude_l_swap_gauge_identity_max_diff": l_swap_diff,
        "shuffled_projector_null_control_c_rcf_mean": round(shuffled_c_rcf, 6),
        "contrastive_separation_heldout": {
            "heldout_conservation_c_proj": gc["last_token_contrastive_proj_mean"],
            "fluent_non_conservation_e_proj": ge["last_token_contrastive_proj_mean"],
            "scrambled_noise_d_proj": gd["last_token_contrastive_proj_mean"],
            "physics_hard_neg_f_proj": gf["last_token_contrastive_proj_mean"],
            "delta_c_vs_e_fluent": round(gc["last_token_contrastive_proj_mean"] - ge["last_token_contrastive_proj_mean"], 6),
            "delta_c_vs_d_scrambled": round(gc["last_token_contrastive_proj_mean"] - gd["last_token_contrastive_proj_mean"], 6),
            "roc_auc_c_vs_e_last_token": lt_ce["roc_auc"],
            "roc_auc_c_vs_d_last_token": lt_cd["roc_auc"],
            "stats_c_vs_e_last_token": lt_ce,
            "stats_c_vs_d_last_token": lt_cd,
            "stats_c_vs_f_topic_probe_last_token": lt_cf_topic,
            "mean_pooled_c_proj": gc["mean_pooled_contrastive_proj_mean"],
            "mean_pooled_e_proj": ge["mean_pooled_contrastive_proj_mean"],
            "mean_pooled_d_proj": gd["mean_pooled_contrastive_proj_mean"],
            "mean_pooled_f_hard_neg_proj": gf["mean_pooled_contrastive_proj_mean"],
            "mean_pooled_delta_c_vs_e": round(gc["mean_pooled_contrastive_proj_mean"] - ge["mean_pooled_contrastive_proj_mean"], 6),
            "mean_pooled_delta_c_vs_d": round(gc["mean_pooled_contrastive_proj_mean"] - gd["mean_pooled_contrastive_proj_mean"], 6),
            "roc_auc_c_vs_e_mean_pooled": mp_ce["roc_auc"],
            "roc_auc_c_vs_d_mean_pooled": mp_cd["roc_auc"],
            "stats_c_vs_e_mean_pooled": mp_ce,
            "stats_c_vs_d_mean_pooled": mp_cd,
            "stats_c_vs_f_topic_probe_mean_pooled": mp_cf_topic,
        },
        "hard_negative_polarity_probe_c_vs_f": {
            "description": "Leak-free conservation truth vs. anti-conservation falsehood within identical physics vocabulary (N=25 vs N=25, 625 pairs)",
            "polarity_c_mean_pooled": gc["polarity_probe_mean_pooled_mean"],
            "polarity_f_mean_pooled": gf["polarity_probe_mean_pooled_mean"],
            "polarity_delta_c_vs_f_mean_pooled": round(gc["polarity_probe_mean_pooled_mean"] - gf["polarity_probe_mean_pooled_mean"], 6),
            "stats_polarity_c_vs_f_last_token": pol_cf_lt,
            "stats_polarity_c_vs_f_mean_pooled": pol_cf_mp,
        },
        "groups": grp,
        "elapsed_sec": round(time.time() - t0, 3),
        "little_vector_seal": l_seal,
    }
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return report


if __name__ == "__main__":
    print(json.dumps(run_nemotron_f01_probe(), indent=2, ensure_ascii=False))
