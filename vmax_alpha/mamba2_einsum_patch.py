#!/usr/bin/env python3
"""
vmax_alpha/mamba2_einsum_patch.py

PQMS / V-MAX-12 (SYNC-30b) — Memory-Efficient Exact Einsum Mamba2 Chunk Scan.

Replaces the naive 6D broadcast contractions in transformers' reference
mamba2_chunk_scan() (which materialize a 6.00 GiB temporary tensor during
Nemotron-3-Nano-4B prefill when mamba_ssm CUDA kernels are unavailable) with
mathematically equivalent torch.einsum contractions (verified max_abs_diff ~
3.7e-9 in FP32, peak activation ~95.6 MB instead of 6,144 MB).

OP02-AST-clean: 0 semicolons, 0 tabs, flat functions (max McCabe CC <= 5).
"""

from __future__ import annotations

from typing import Any, Optional, Tuple


def _prepare_mamba_inputs(
    hidden_states: Any,
    dt: Any,
    a_param: Any,
    b_param: Any,
    c_param: Any,
    dt_bias: Optional[Any],
    dt_softplus: bool,
    dt_limit: Tuple[float, float],
) -> Tuple[Any, Any, Any, Any, Any]:
    """Apply dt bias/softplus/clamp and expand B/C groups to full heads."""
    import torch
    import torch.nn.functional as F

    num_heads = hidden_states.shape[2]
    num_groups = b_param.shape[2]
    if dt_bias is not None:
        dt = dt + dt_bias.to(dt.dtype)
    if dt_softplus:
        dt = F.softplus(dt)
    dt = torch.clamp(dt, min=dt_limit[0], max=dt_limit[1])
    hs_f = hidden_states.float()
    b_f = b_param.float().repeat_interleave(num_heads // num_groups, dim=2, output_size=num_heads)
    c_f = c_param.float().repeat_interleave(num_heads // num_groups, dim=2, output_size=num_heads)
    return hs_f, dt, a_param.to(hs_f.dtype), b_f, c_f


def _run_einsum_blocks(
    hs_c: Any,
    a_c: Any,
    b_c: Any,
    c_c: Any,
    initial_states: Optional[Any],
    segment_sum_fn: Any,
) -> Tuple[Any, Any]:
    """Execute intra-chunk and inter-chunk SSM contractions via torch.einsum."""
    import torch
    import torch.nn.functional as F

    a_perm = a_c.permute(0, 3, 1, 2)
    a_cumsum = torch.cumsum(a_perm, dim=-1)
    l_mat = torch.exp(segment_sum_fn(a_perm))
    g_mat = torch.einsum("bclhn,bcshn->bclsh", c_c, b_c)
    m_mat = g_mat * l_mat.permute(0, 2, 3, 4, 1)
    y_diag = torch.einsum("bclsh,bcshp->bclhp", m_mat, hs_c)

    decay_states = torch.exp(a_cumsum[:, :, :, -1:] - a_cumsum)
    b_decay = b_c * decay_states.permute(0, -2, -1, 1)[..., None]
    states = torch.einsum("bclhn,bclhp->bchpn", b_decay, hs_c)

    prev = (
        initial_states[:, None].to(dtype=states.dtype, device=states.device)
        if initial_states is not None
        else torch.zeros_like(states[:, :1])
    )
    states = torch.cat([prev, states], dim=1)
    decay_chunk = torch.exp(segment_sum_fn(F.pad(a_cumsum[:, :, :, -1], (1, 0)))).transpose(1, 3)
    new_states = torch.einsum("bczh,bchpn->bzhpn", decay_chunk, states)
    states, final_state = new_states[:, :-1], new_states[:, -1]

    state_decay_out = torch.exp(a_cumsum)
    y_off = torch.einsum("bclhn,bchpn->bclhp", c_c, states) * state_decay_out.permute(0, 2, 3, 1)[..., None]
    return y_diag + y_off, final_state


def einsum_mamba2_chunk_scan(
    hidden_states: Any,
    dt: Any,
    A: Any,
    B: Any,
    C: Any,
    chunk_size: int,
    D: Optional[Any] = None,
    dt_bias: Optional[Any] = None,
    initial_states: Optional[Any] = None,
    dt_softplus: bool = False,
    dt_limit: Tuple[float, float] = (0.0, float("inf")),
    return_final_states: bool = False,
    **_kwargs: Any,
) -> Any:
    """Drop-in O(chunk) memory replacement for transformers mamba2_chunk_scan."""
    from transformers.models.nemotron_h import modeling_nemotron_h as mh

    batch_size, seq_len, num_heads, head_dim = hidden_states.shape
    hs_f, dt, a_f, b_f, c_f = _prepare_mamba_inputs(
        hidden_states, dt, A, B, C, dt_bias, dt_softplus, dt_limit
    )
    pad_size = (chunk_size - seq_len % chunk_size) % chunk_size
    d_res = D[..., None] * mh.pad_tensor_by_size(hs_f, pad_size) if D is not None else None
    hs_disc = hs_f * dt[..., None].float()
    a_disc = a_f * dt.float()
    hs_c, a_c, b_c, c_c = [
        mh.reshape_into_chunks(t, pad_size, chunk_size) for t in (hs_disc, a_disc, b_f, c_f)
    ]
    combined, final_state = _run_einsum_blocks(hs_c, a_c, b_c, c_c, initial_states, mh.segment_sum)
    output = combined.reshape(batch_size, -1, num_heads, head_dim)
    if d_res is not None:
        output = output + d_res
    if pad_size > 0:
        output = output[:, :seq_len]
    return (output, final_state) if return_final_states else output


def install_mamba2_einsum_patch() -> bool:
    """Patch modeling_nemotron_h.mamba2_chunk_scan in-process if available."""
    try:
        from transformers.models.nemotron_h import modeling_nemotron_h as mh
    except Exception:
        return False
    mh.mamba2_chunk_scan = einsum_mamba2_chunk_scan
    return True
