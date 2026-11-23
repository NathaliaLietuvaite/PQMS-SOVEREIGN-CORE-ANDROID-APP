#!/usr/bin/env bash
set -euo pipefail
PAUSE_FILE="${VMAX_SYNTH_PAUSE_FILE:-/tmp/vmax_synth.pause}"
rm -f "${PAUSE_FILE}"
echo "[V-MAX-12] Pause sentinel cleared: ${PAUSE_FILE}"
echo "[V-MAX-12] Reminder: halt anytime with Ctrl+C or ./pause_synth.sh (lossless SHA-256 checkpoints)."
if [ "$#" -gt 0 ]; then
  exec "$@"
fi
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PATH="/home/nathalia/vmax_310/bin:/usr/lib/wsl/lib:${PATH}"
export LD_LIBRARY_PATH="/home/nathalia/.local/liboqs/lib:${LD_LIBRARY_PATH:-}"
export OQS_INSTALL_PATH="/home/nathalia/.local/liboqs"
export PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True,max_split_size_mb:128"
cd "${REPO_DIR}"
if [ -f "${REPO_DIR}/vmax_alpha/dkm_benchmark_runner.py" ]; then
  exec python3 -m vmax_alpha.dkm_benchmark_runner
else
  exec python3 -m vmax_alpha.synth_runner --work-dir /tmp/vmax_synth_state
fi
