"""
vmax_alpha/klavierstunde_kl.py
Stage 3 Audit Fix (WORK-ORDER-AG-05): Real Subtractive 1-Bit MLP Mask (c = 0.0420%)
and Empirical Forward-KL Divergence on Nemotron-3-Nano-4B-BF16 (REGISTER_M).
Replaces synthetic formula `forward_kl = cut_fraction * 42.5` with real model measurements.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Tuple

import numpy as np
import torch
import transformers.utils.import_utils as _tf_imports

_tf_imports.is_causal_conv1d_available = lambda: False

from transformers import AutoModelForCausalLM, AutoTokenizer
from vmax_alpha.config import KL_DIVERGENCE_MAX, REGISTER_M, SUBTRACTIVE_CUT_FRACTION
from vmax_alpha.nemotron_probe import GROUP_C_TEST_CONSERVATION, NEMOTRON_LOCAL_PATH


def compute_exact_forward_kl(logits_base: torch.Tensor, logits_mod: torch.Tensor) -> float:
    """
    Compute exact Forward KL divergence D_KL(P_base || P_mod) over full vocabulary V (131,072)
    in float64 precision: sum_v P_base(v) * (log P_base(v) - log P_mod(v)).
    """
    log_p = torch.log_softmax(logits_base.to(torch.float64), dim=-1)
    log_q = torch.log_softmax(logits_mod.to(torch.float64), dim=-1)
    p = torch.exp(log_p)
    kl = torch.sum(p * (log_p - log_q), dim=-1)
    return max(0.0, float(kl.mean().item()))


def collect_last_token_logits(
    model: torch.nn.Module, tokenizer: Any, prompts: List[str]
) -> List[torch.Tensor]:
    """Run forward pass on prompts and return last-token float32 logit vectors on CPU."""
    logits_list: List[torch.Tensor] = []
    with torch.no_grad():
        for p in prompts:
            ids = tokenizer(p, return_tensors="pt", add_special_tokens=True)["input_ids"].to("cuda:0")
            out = model(input_ids=ids, use_cache=False)
            last_logits = out.logits[:, -1, :].detach().to(torch.float32).cpu()
            logits_list.append(last_logits)
    return logits_list


def evaluate_kl_against_baseline(
    base_logits: List[torch.Tensor], mod_logits: List[torch.Tensor]
) -> Dict[str, Any]:
    """Compute per-prompt and aggregate Forward KL and top-1 token agreement."""
    kls: List[float] = []
    top1_matches = 0
    for lb, lm in zip(base_logits, mod_logits):
        kls.append(compute_exact_forward_kl(lb, lm))
        if int(torch.argmax(lb, dim=-1).item()) == int(torch.argmax(lm, dim=-1).item()):
            top1_matches += 1
    mean_kl = float(np.mean(kls))
    max_kl = float(np.max(kls))
    passed = mean_kl <= KL_DIVERGENCE_MAX
    return {
        "per_prompt_kl": [round(x, 8) for x in kls],
        "mean_forward_kl": round(mean_kl, 8),
        "std_forward_kl": round(float(np.std(kls)), 8),
        "min_forward_kl": round(float(np.min(kls)), 8),
        "max_forward_kl": round(max_kl, 8),
        "top1_token_agreement": f"{top1_matches}/{len(base_logits)}",
        "kl_threshold_max": KL_DIVERGENCE_MAX,
        "odos_kl_gate_status": "PASS_LAMINAR" if passed else "VETO_KL_EXCEEDED",
        "passed": passed,
    }


def apply_subtractive_1bit_mlp_mask(
    mlp_layers: List[Tuple[int, torch.nn.Linear]],
    cut_fraction: float = SUBTRACTIVE_CUT_FRACTION,
    mode: str = "smallest_magnitude",
    seed: int = 137,
) -> Dict[str, Any]:
    """
    Apply a binary 1-bit multiplicative mask M in {0, 1} (W_masked = W * M)
    across all NemotronH MLP up_proj weight matrices.
    """
    total_params = 0
    zeroed_params = 0
    gen = torch.Generator(device="cuda:0")
    gen.manual_seed(seed)
    with torch.no_grad():
        for _, proj in mlp_layers:
            w = proj.weight.data
            n_el = w.numel()
            k_cut = max(1, int(round(n_el * cut_fraction)))
            flat_abs = torch.abs(w.view(-1))
            if mode == "smallest_magnitude":
                _, idx = torch.topk(flat_abs, k=k_cut, largest=False)
                w.view(-1)[idx] = 0
            elif mode == "structured_off_principal":
                perm = torch.randperm(n_el, generator=gen, device=w.device)[:k_cut]
                w.view(-1)[perm] = 0
            elif mode == "coercive_top_magnitude_plus_torsion":
                _, idx = torch.topk(flat_abs, k=k_cut, largest=True)
                w.view(-1)[idx] = 0
                noise = torch.randn(w.shape, dtype=w.dtype, device=w.device, generator=gen) * 0.08
                w.add_(noise)
            else:
                raise ValueError(f"Unknown mask mode: {mode}")
            total_params += n_el
            zeroed_params += k_cut
    return {
        "mode": mode,
        "num_mlp_up_proj_layers": len(mlp_layers),
        "total_mlp_up_proj_weights": total_params,
        "zeroed_weights_count": zeroed_params,
        "actual_cut_fraction": round(zeroed_params / max(total_params, 1), 8),
    }


def run_stage3_real_kl_audit(
    model_path: str = NEMOTRON_LOCAL_PATH,
    output_json: str = "VMAX_STAGE3_REAL_KL_REPORT.json",
) -> Dict[str, Any]:
    """Execute empirical Stage 3 1-bit MLP mask Forward-KL benchmark on Nemotron-3-Nano-4B-BF16."""
    t0 = time.time()
    tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        model_path, torch_dtype=torch.bfloat16, device_map="cuda:0", trust_remote_code=True
    ).eval()

    mlp_layers: List[Tuple[int, torch.nn.Linear]] = []
    backups: Dict[int, torch.Tensor] = {}
    for idx, layer in enumerate(model.backbone.layers):
        if getattr(layer, "block_type", "") == "mlp" and hasattr(layer.mixer, "up_proj"):
            mlp_layers.append((idx, layer.mixer.up_proj))
            backups[idx] = layer.mixer.up_proj.weight.data.detach().clone().cpu()

    def restore_weights() -> None:
        with torch.no_grad():
            for idx, proj in mlp_layers:
                proj.weight.data.copy_(backups[idx].to(device="cuda:0", dtype=proj.weight.dtype))

    base_logits = collect_last_token_logits(model, tokenizer, GROUP_C_TEST_CONSERVATION)

    # Condition A1: Targeted Small-Magnitude Subtractive 1-Bit Mask (c = 0.00042 = 0.0420%)
    meta_a1 = apply_subtractive_1bit_mlp_mask(mlp_layers, SUBTRACTIVE_CUT_FRACTION, "smallest_magnitude")
    logits_a1 = collect_last_token_logits(model, tokenizer, GROUP_C_TEST_CONSERVATION)
    eval_a1 = evaluate_kl_against_baseline(base_logits, logits_a1)
    restore_weights()

    # Condition A2: Off-Principal Random Subtractive 1-Bit Mask (c = 0.00042 = 0.0420%)
    meta_a2 = apply_subtractive_1bit_mlp_mask(mlp_layers, SUBTRACTIVE_CUT_FRACTION, "structured_off_principal")
    logits_a2 = collect_last_token_logits(model, tokenizer, GROUP_C_TEST_CONSERVATION)
    eval_a2 = evaluate_kl_against_baseline(base_logits, logits_a2)
    restore_weights()

    # Condition B (Negative Control): Coercive 5% Top-Magnitude + Additive Torsion
    meta_b = apply_subtractive_1bit_mlp_mask(mlp_layers, 0.05, "coercive_top_magnitude_plus_torsion")
    logits_b = collect_last_token_logits(model, tokenizer, GROUP_C_TEST_CONSERVATION)
    eval_b = evaluate_kl_against_baseline(base_logits, logits_b)
    restore_weights()

    # Verify lossless weight restoration
    logits_restored = collect_last_token_logits(model, tokenizer, GROUP_C_TEST_CONSERVATION)
    max_restore_diff = max(
        float(torch.max(torch.abs(lb - lr)).item()) for lb, lr in zip(base_logits, logits_restored)
    )

    report: Dict[str, Any] = {
        "document_id": "PQMS-LASTENHEFT-NODE-ALPHA-V1.0",
        "requirement": "STAGE_3_REAL_1BIT_MASK_FORWARD_KL",
        "epistemic_register": REGISTER_M,
        "model_architecture": "NemotronHForCausalLM",
        "vocab_size": int(base_logits[0].shape[-1]),
        "num_heldout_prompts_group_c": len(GROUP_C_TEST_CONSERVATION),
        "mlp_layer_indices": [idx for idx, _ in mlp_layers],
        "condition_a1_smallest_magnitude_0042pct": {**meta_a1, **eval_a1},
        "condition_a2_off_principal_0042pct": {**meta_a2, **eval_a2},
        "condition_b_negative_control_coercive_5pct": {**meta_b, **eval_b},
        "weight_restoration_max_logit_diff": max_restore_diff,
        "elapsed_sec": round(time.time() - t0, 3),
    }
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return report


if __name__ == "__main__":
    print(json.dumps(run_stage3_real_kl_audit(), indent=2, ensure_ascii=False))
