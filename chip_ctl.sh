#!/usr/bin/env bash
# =============================================================================
# chip_ctl.sh — Einfaches Start / Pause / Restart Steuerungsmodul
#               fuer die V-MAX-12 Chip-Herstellung (IHP SG13G2 130 nm)
# =============================================================================
set -euo pipefail

SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
REPO_DIR="$(cd "$(dirname "${SCRIPT_PATH}")" && pwd)"
PY_BIN="/home/nathalia/vmax_310/bin/python3"
if [ ! -x "${PY_BIN}" ]; then
  PY_BIN="python3"
fi

run_ctl() {
  (cd "${REPO_DIR}" && "${PY_BIN}" -m vmax_alpha.chip_fab_controller "$@")
}

if [ "$#" -gt 0 ]; then
  run_ctl "$@"
  exit 0
fi

# Interaktives Minimal-Menue bei Aufruf ohne Argumente
while true; do
  echo ""
  echo "=============================================="
  echo "  V-MAX-12 Chip-Herstellung — Steuerung"
  echo "=============================================="
  run_ctl status
  echo "----------------------------------------------"
  echo "  [1] Start / Fortsetzen"
  echo "  [2] Pause (verlustfrei nach aktiver Stage)"
  echo "  [3] Sofort-Pause (0% CPU einfrieren)"
  echo "  [4] Restart (ab letztem Checkpoint)"
  echo "  [5] Restart --fresh (ab Stage 00 + Backup)"
  echo "  [s] Status aktualisieren"
  echo "  [q] Beenden"
  echo "----------------------------------------------"
  read -r -p "Auswahl [1/2/3/4/5/s/q]: " choice
  case "${choice}" in
    1) run_ctl start ;;
    2) run_ctl pause ;;
    3) run_ctl pause --freeze ;;
    4) run_ctl restart ;;
    5) run_ctl restart --fresh ;;
    s|S) ;;
    q|Q) break ;;
    *) echo "Unbekannte Eingabe: ${choice}" ;;
  esac
done
