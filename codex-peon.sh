#!/usr/bin/env bash
set -euo pipefail

PEON_DIR="${CODEX_PEON_DIR:-$HOME/.codex/hooks/codex-peon}"
exec python3 "$PEON_DIR/codex-peon.py" "$@"
