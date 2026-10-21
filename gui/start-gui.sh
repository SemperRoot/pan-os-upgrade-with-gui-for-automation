#!/usr/bin/env bash
# Starts the PAN-OS Upgrade Console. Run setup-wsl.sh once first.
#
#     bash ~/pan-os-upgrade/gui/start-gui.sh
#
# Then open http://localhost:8080 in your web browser. Press Ctrl+C in this window to stop it.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GUI_PYTHON="$REPO_DIR/gui/.venv/bin/python"
export PAN_OS_UPGRADE_BIN="${PAN_OS_UPGRADE_BIN:-$REPO_DIR/.venv-cli/bin/pan-os-upgrade}"
PORT="${PAN_OS_GUI_PORT:-8080}"

fail() { printf '\033[1;31mERROR: %s\033[0m\n' "$1" >&2; exit 1; }

[[ -x "$GUI_PYTHON" ]] || fail "The GUI isn't installed. Run first:  bash $REPO_DIR/gui/setup-wsl.sh"
[[ -x "$PAN_OS_UPGRADE_BIN" ]] || fail "The CLI isn't installed at $PAN_OS_UPGRADE_BIN. Run first:  bash $REPO_DIR/gui/setup-wsl.sh"

printf '\n  PAN-OS Upgrade Console\n'
printf '  Open \033[1mhttp://localhost:%s\033[0m in your web browser.\n' "$PORT"
printf '  Keep this window open while you use the GUI. Press Ctrl+C here to stop it.\n'
printf '  (A message about not being able to open a browser is normal on WSL.)\n\n'

cd "$REPO_DIR"
exec "$GUI_PYTHON" "$REPO_DIR/gui/gui.py"
