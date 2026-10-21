#!/usr/bin/env bash
# Installs the PAN-OS Upgrade Console and the pan-os-upgrade CLI on Ubuntu (WSL2 or native Linux).
#
# Run it from anywhere:
#     bash ~/pan-os-upgrade/gui/setup-wsl.sh
#
# Safe to run again: it reuses working virtual environments, rebuilds broken ones, and
# reinstalls the CLI so it picks up code changes (run it after every `git pull`).

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI_VENV="$REPO_DIR/.venv-cli"
GUI_VENV="$REPO_DIR/gui/.venv"

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$1"; }
ok() { printf '\033[32m    OK: %s\033[0m\n' "$1"; }
note() { printf '    %s\n' "$1"; }
fail() {
    printf '\n\033[1;31mERROR: %s\033[0m\n' "$1" >&2
    [[ $# -gt 1 ]] && printf '%s\n' "${@:2}" >&2
    printf '\nSee "Troubleshooting" in gui/WINDOWS.md.\n' >&2
    exit 1
}

# A virtual environment is usable only if its Python runs on this machine. One copied from
# another computer (for example a Mac) has a python that points to a path that doesn't exist here.
venv_works() { [[ -x "$1/bin/python" ]] && "$1/bin/python" -c "import sys" >/dev/null 2>&1; }

step "Checking the project folder"
for required in pyproject.toml pan_os_upgrade/main.py gui/gui.py gui/requirements-cli.txt gui/requirements-gui.txt; do
    [[ -f "$REPO_DIR/$required" ]] || fail "$REPO_DIR/$required is missing." \
        "This script must stay inside the project's gui folder, and the project must be complete." \
        "Get a fresh copy with: gh repo clone SemperRoot/pan-os-upgrade-with-gui-for-automation ~/pan-os-upgrade"
done
case "$REPO_DIR" in
    /mnt/*) note "Warning: the project is on the Windows drive ($REPO_DIR). It works, but it is slow."
            note "For better speed, keep it in your Linux home folder, e.g. ~/pan-os-upgrade." ;;
esac
ok "$REPO_DIR"

step "Installing system packages (python3, python3-venv, python3-pip, git)"
if command -v apt-get >/dev/null 2>&1; then
    missing=()
    for package in python3 python3-venv python3-pip git; do
        dpkg -s "$package" >/dev/null 2>&1 || missing+=("$package")
    done
    if [[ ${#missing[@]} -gt 0 ]]; then
        note "Installing: ${missing[*]}"
        note "If asked for a password, type your Ubuntu password. Nothing appears while you type; press Enter when done."
        sudo apt-get update
        sudo apt-get install -y "${missing[@]}"
    fi
    ok "System packages installed"
else
    note "apt-get not found (not Ubuntu/Debian). Skipping; make sure Python 3.11+ with venv is installed."
fi

step "Checking the Python version"
command -v python3 >/dev/null 2>&1 || fail "python3 is not installed."
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
    || fail "Python $(python3 -c 'import platform; print(platform.python_version())') is too old; 3.11 or later is needed." \
        "On WSL, install Ubuntu 24.04 (it has Python 3.12): in PowerShell run  wsl --install -d Ubuntu-24.04"
ok "Python $(python3 -c 'import platform; print(platform.python_version())')"

step "Removing copied virtual-environment files that can't work here"
# A copy of the project made on a Mac contains the Mac's virtual environment inside pan_os_upgrade/.
# Only removed when it can't run on this machine, so a working local setup is never touched.
if [[ -f "$REPO_DIR/pan_os_upgrade/pyvenv.cfg" ]] && ! venv_works "$REPO_DIR/pan_os_upgrade"; then
    rm -rf "$REPO_DIR/pan_os_upgrade/bin" "$REPO_DIR/pan_os_upgrade/lib" "$REPO_DIR/pan_os_upgrade/include"
    rm -f "$REPO_DIR/pan_os_upgrade/pyvenv.cfg"
    if [[ -f "$REPO_DIR/pan_os_upgrade/.gitignore" ]] && grep -q "Created by venv" "$REPO_DIR/pan_os_upgrade/.gitignore"; then
        rm -f "$REPO_DIR/pan_os_upgrade/.gitignore"
    fi
    note "Removed the copied environment from pan_os_upgrade/"
fi
for venv in "$CLI_VENV" "$GUI_VENV"; do
    if [[ -e "$venv" ]] && ! venv_works "$venv"; then
        rm -rf "$venv"
        note "Removed broken environment: $venv"
    fi
done
ok "Done"

step "Installing the CLI into .venv-cli (takes a few minutes)"
venv_works "$CLI_VENV" || python3 -m venv "$CLI_VENV" \
    || fail "Couldn't create $CLI_VENV." "Install the venv module with: sudo apt install python3-venv"
"$CLI_VENV/bin/pip" install --disable-pip-version-check -r "$REPO_DIR/gui/requirements-cli.txt" \
    || fail "Installing the CLI's packages failed." "Check your internet connection or proxy settings, then run this script again."
"$CLI_VENV/bin/pip" install --disable-pip-version-check --no-deps --force-reinstall "$REPO_DIR" \
    || fail "Installing the CLI itself failed."
"$CLI_VENV/bin/pip" check >/dev/null || fail "The CLI's packages conflict:" "$("$CLI_VENV/bin/pip" check)"
# Capture first: piping straight into `grep -q` can end in SIGPIPE, which pipefail reports as failure
cli_help="$("$CLI_VENV/bin/pan-os-upgrade" --help 2>&1 || true)"
[[ "$cli_help" == *firewall* ]] || fail "pan-os-upgrade doesn't start." "$(printf '%s\n' "$cli_help" | tail -5)"
ok "pan-os-upgrade installed: $CLI_VENV/bin/pan-os-upgrade"

step "Installing the GUI into gui/.venv"
venv_works "$GUI_VENV" || python3 -m venv "$GUI_VENV" || fail "Couldn't create $GUI_VENV."
"$GUI_VENV/bin/pip" install --disable-pip-version-check -r "$REPO_DIR/gui/requirements-gui.txt" \
    || fail "Installing the GUI's packages failed." "Check your internet connection or proxy settings, then run this script again."
"$GUI_VENV/bin/python" -c "import nicegui, yaml" || fail "The GUI's packages don't import."
ok "GUI installed: $GUI_VENV"

step "Setup complete"
note "Start the GUI with:"
note ""
note "    bash $REPO_DIR/gui/start-gui.sh"
note ""
note "Then open http://localhost:8080 in your web browser."
