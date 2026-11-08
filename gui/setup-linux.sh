#!/usr/bin/env bash
# Installs the pan-os-upgrade CLI and the PAN-OS Upgrade Console on Linux (any distribution, or WSL).
#
#     bash gui/setup-linux.sh                          packages from pip's configured index
#     bash gui/setup-linux.sh --index-url URL          packages from this index (e.g. a Nexus mirror)
#     bash gui/setup-linux.sh --wheelhouse wheelhouse  offline, from a folder made with --download
#     bash gui/setup-linux.sh --download wheelhouse    only download the packages
#
# Finds Python 3.11 or later (newest first), or uses $PAN_OS_PYTHON, then runs gui/install.py,
# which does the actual work. Safe to run again, for example after updating the project files.

set -euo pipefail

GUI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

python_ok() {
    "$1" -c 'import sys, venv, ensurepip; sys.exit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1
}

find_python() {
    local candidate
    for candidate in "${PAN_OS_PYTHON:-}" python3.14 python3.13 python3.12 python3.11 python3; do
        [[ -n "$candidate" ]] && command -v "$candidate" >/dev/null 2>&1 && python_ok "$candidate" \
            && { command -v "$candidate"; return 0; }
    done
    return 1
}

if ! PYTHON="$(find_python)"; then
    # Debian/Ubuntu (including WSL) often lack only the venv module; install it when apt is available
    if command -v apt-get >/dev/null 2>&1 && command -v python3 >/dev/null 2>&1 \
        && python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
        printf '\nInstalling python3-venv and python3-pip. If asked, type your Linux password.\n'
        sudo apt-get install -y python3-venv python3-pip || true
    fi
    PYTHON="$(find_python)" || {
        printf '\n\033[1;31mERROR: Python 3.11 or later with the venv module was not found.\033[0m\n' >&2
        printf '  Debian/Ubuntu:  sudo apt-get install python3 python3-venv python3-pip\n' >&2
        printf '  RHEL/Rocky 8-9: sudo dnf install python3.12 python3.12-pip\n' >&2
        printf '  Or set PAN_OS_PYTHON=/path/to/python3.12 and run this again.\n' >&2
        exit 1
    }
fi

exec "$PYTHON" "$GUI_DIR/install.py" "$@"
