#!/usr/bin/env bash
# Starts the PAN-OS Upgrade Console on Linux. Run gui/setup-linux.sh once first.
#
#     bash gui/start-gui.sh
#
# Then open http://localhost:8080 in your web browser. Press Ctrl+C in this window to stop it.
# To use another port:  PAN_OS_GUI_PORT=8081 bash gui/start-gui.sh

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GUI_PYTHON="$REPO_DIR/gui/.venv/bin/python"
CLI_PYTHON="${PAN_OS_UPGRADE_PYTHON:-$REPO_DIR/.venv-cli/bin/python}"
PORT="${PAN_OS_GUI_PORT:-8080}"

fail() { printf '\033[1;31mERROR: %s\033[0m\n' "$1" >&2; exit 1; }

[[ -x "$GUI_PYTHON" ]] || fail "The GUI isn't installed. Run first:  bash $REPO_DIR/gui/setup-linux.sh"
[[ -x "$CLI_PYTHON" ]] || fail "The CLI isn't installed at $CLI_PYTHON. Run first:  bash $REPO_DIR/gui/setup-linux.sh"

printf '\n  PAN-OS Upgrade Console\n'
printf '  Open \033[1mhttp://localhost:%s\033[0m in your web browser.\n' "$PORT"
printf '  Keep this window open while you use the GUI. Press Ctrl+C here to stop it.\n'
printf '  (A message about not being able to open a browser is normal without a desktop.)\n\n'

cd "$REPO_DIR"
exec "$GUI_PYTHON" "$REPO_DIR/gui/gui.py"
