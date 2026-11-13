"""
Runs the pan-os-upgrade CLI for the GUI, with password prompts read from stdin.

The GUI starts this file with the CLI's Python (.venv-cli), never its own:

    .venv-cli/bin/python gui/cli_launcher.py firewall --hostname ...         (Linux)
    .venv-cli\\Scripts\\python.exe gui\\cli_launcher.py firewall --hostname ...  (Windows)

The CLI asks for passwords with typer.prompt(hide_input=True), which calls getpass.getpass().
On Windows, getpass reads keystrokes straight from the console and ignores stdin, so a password
sent by the GUI is never seen and the run hangs. On Linux it falls back to stdin but prints
warnings. Reading the line from stdin on every platform makes both behave the same.

Uses only the standard library and the CLI's own packages; pan_os_upgrade itself is unchanged.
"""

import getpass
import sys


def _stdin_getpass(prompt: str = "Password: ", stream=None) -> str:
    sys.stdout.write(prompt)
    sys.stdout.flush()
    line = sys.stdin.readline()
    if not line:
        raise EOFError
    return line.rstrip("\r\n")


getpass.getpass = _stdin_getpass

from pan_os_upgrade.main import app  # noqa: E402

if __name__ == "__main__":
    app(prog_name="pan-os-upgrade")
