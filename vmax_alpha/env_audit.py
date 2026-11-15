"""
vmax_alpha/env_audit.py
Hardware, CUDA L2 Cache, Package, and Local Model Checkpoint Discovery Probe.
Implements WORK-ORDER-AG-01 Step 1.
"""

from __future__ import annotations

import glob
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
from typing import Any, Dict, List


def get_pkg_version(pkg_name: str) -> str:
    try:
        return importlib.metadata.version(pkg_name)
    except importlib.metadata.PackageNotFoundError:
        return "NOT_INSTALLED"


def probe_cuda_and_gpu() -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "register": "REGISTER_M",
        "torch_version": get_pkg_version("torch"),
        "cuda_available": False,
        "device_name": None,
        "total_vram_bytes": 0,
        "total_vram_gb": 0.0,
        "l2_cache_size_bytes": 0,
        "l2_cache_size_mb": 0.0,
        "compute_capability": None,
        "multi_processor_count": 0,
    }
    try:
        import torch

        info["cuda_available"] = bool(torch.cuda.is_available())
        if info["cuda_available"]:
            props = torch.cuda.get_device_properties(0)
            info["device_name"] = props.name
            info["total_vram_bytes"] = int(props.total_memory)
            info["total_vram_gb"] = round(props.total_memory / (1024**3), 4)
            l2_bytes = int(
                getattr(props, "L2_cache_size", getattr(props, "l2_cache_size", 0))
            )
            info["l2_cache_size_bytes"] = l2_bytes
            info["l2_cache_size_mb"] = round(l2_bytes / (1024**2), 2)
            info["compute_capability"] = f"{props.major}.{props.minor}"
            info["multi_processor_count"] = int(props.multi_processor_count)
    except Exception as exc:
        info["error"] = f"{exc.__class__.__name__}: {exc}"
    return info


def discover_local_models() -> List[Dict[str, Any]]:
    search_roots = [
        "/home/nathalia",
        os.path.expanduser("~/.cache/huggingface/hub"),
    ]
    found_paths: List[Dict[str, Any]] = []
    seen = set()

    for root in search_roots:
        if not os.path.exists(root):
            continue
        try:
            cmd = [
                "find",
                root,
                "-maxdepth",
                "4",
                "(",
                "-iname",
                "*nemotron*",
                "-o",
                "-iname",
                "*models--*",
                "-o",
                "-name",
                "*.safetensors",
                "-o",
                "-name",
                "*.gguf",
                ")",
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            for line in proc.stdout.splitlines():
                path = line.strip()
                if not path or path in seen:
                    continue
                seen.add(path)
                size_mb = 0.0
                try:
                    if os.path.isfile(path):
                        size_mb = round(os.path.getsize(path) / (1024**2), 2)
                except OSError:
                    pass
                found_paths.append({"path": path, "size_mb": size_mb})
        except Exception:
            pass
    return found_paths[:40]


def probe_ncu() -> Dict[str, Any]:
    ncu_path = shutil.which("ncu")
    if not ncu_path:
        candidates = glob.glob("/usr/local/cuda*/bin/ncu") + glob.glob(
            "/opt/nvidia/nsight-compute*/*/ncu"
        )
        if candidates:
            ncu_path = candidates[0]
    version_out = None
    if ncu_path:
        try:
            res = subprocess.run(
                [ncu_path, "--version"], capture_output=True, text=True, timeout=5
            )
            lines = [ln.strip() for ln in res.stdout.splitlines() if ln.strip()]
            version_out = lines[-1] if lines else None
        except Exception:
            pass
    return {
        "ncu_in_path": shutil.which("ncu") is not None,
        "ncu_resolved_path": ncu_path,
        "ncu_version": version_out,
    }


def run_env_audit(output_file: str = "VMAX_ENV_AUDIT.json") -> Dict[str, Any]:
    pauli_kt_matches = glob.glob(
        "/home/nathalia/PQMS-SOVEREIGN-CORE-ANDROID-APP/**/*PauliBaselineEngine*.kt",
        recursive=True,
    )
    report: Dict[str, Any] = {
        "document_id": "PQMS-LASTENHEFT-NODE-ALPHA-V1.0",
        "work_order": "WORK-ORDER-AG-01",
        "epistemic_register": "REGISTER_M",
        "os_kernel": platform.platform(),
        "python_version": platform.python_version(),
        "gpu_telemetry": probe_cuda_and_gpu(),
        "packages": {
            "torch": get_pkg_version("torch"),
            "vllm": get_pkg_version("vllm"),
            "transformers": get_pkg_version("transformers"),
            "chromadb": get_pkg_version("chromadb"),
            "fastapi": get_pkg_version("fastapi"),
            "pytest": get_pkg_version("pytest"),
        },
        "ncu_status": probe_ncu(),
        "local_model_checkpoints": discover_local_models(),
        "pauli_baseline_engine_kt_found": pauli_kt_matches,
    }
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return report


if __name__ == "__main__":
    audit = run_env_audit()
    print(json.dumps(audit, indent=2, ensure_ascii=False))
