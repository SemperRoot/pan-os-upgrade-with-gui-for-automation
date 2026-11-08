#!/usr/bin/env bash
# Kept so existing instructions keep working. WSL is no longer needed on Windows: use gui\setup.cmd.
# On Linux or WSL this is the same as gui/setup-linux.sh.
exec bash "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/setup-linux.sh" "$@"
