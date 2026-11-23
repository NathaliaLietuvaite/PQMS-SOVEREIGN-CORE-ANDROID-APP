#!/usr/bin/env bash
set -euo pipefail
PAUSE_FILE="${VMAX_SYNTH_PAUSE_FILE:-/tmp/vmax_synth.pause}"
date -Iseconds > "${PAUSE_FILE}"
echo "[V-MAX-12] Night-quiet pause armed: ${PAUSE_FILE}"
echo "[V-MAX-12] Active synth_runner will finish its current micro-stage, checkpoint SHA-256, free VRAM, and exit cleanly (rc=0)."
echo "[V-MAX-12] You can also press Ctrl+C directly in the runner console. Resume later with ./resume_synth.sh."
