"""
Checks that an installation works on this machine, without touching any real firewall.

Run after gui/install.py, with the GUI's Python:

    Windows:  gui\\.venv\\Scripts\\python.exe gui\\smoke_test.py
    Linux:    gui/.venv/bin/python gui/smoke_test.py

It checks that the CLI starts, that a password sent by the GUI reaches the CLI's hidden prompt
(the CLI then tries 192.0.2.1, a reserved documentation address that never answers, and is
stopped), which English locale readiness checks will use, and that the GUI's web server starts.
Prints PASS or FAIL for each check; the exit code is 0 only if everything passed.
"""

import asyncio
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

GUI_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(GUI_DIR))
os.environ.setdefault("PAN_OS_GUI_WORKSPACE", str(GUI_DIR / "workspace-smoke-test"))

import gui  # noqa: E402

# Talks to the local GUI directly, ignoring any HTTP_PROXY / system proxy configured on this machine
LOCAL_HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))
UNREACHABLE = "192.0.2.1"  # TEST-NET-1 (RFC 5737): never routed
PASSWORD = "smoke-test-password"
results = []


def report(name: str, passed: bool, detail: str = ""):
    results.append(passed)
    print(f"{'PASS' if passed else 'FAIL'}  {name}" + (f"\n      {detail}" if detail else ""), flush=True)


def check_cli_starts():
    if not gui.CLI_PYTHON.exists():
        report("CLI is installed", False, f"{gui.CLI_PYTHON} not found. Run the installer first.")
        return False
    result = subprocess.run([str(gui.CLI_PYTHON), str(gui.CLI_LAUNCHER), "--help"], capture_output=True,
                            text=True, errors="replace", env=dict(os.environ, PYTHONUTF8="1"), timeout=120)
    started = "firewall" in result.stdout
    report("CLI starts", started, "" if started else (result.stdout + result.stderr).strip()[-500:])
    return started


def check_locale():
    code = (
        "import locale\n"
        "from pan_os_upgrade.components.assurance import ENGLISH_LOCALES\n"
        "for name in ENGLISH_LOCALES:\n"
        "    try:\n"
        "        locale.setlocale(locale.LC_ALL, name); print(name); break\n"
        "    except locale.Error:\n"
        "        pass\n"
    )
    result = subprocess.run([str(gui.CLI_PYTHON), "-c", code], capture_output=True, text=True, timeout=120)
    chosen = result.stdout.strip()
    report("English locale for readiness checks", result.returncode == 0 and bool(chosen),
           f"uses: {chosen}" if chosen else result.stderr.strip()[-500:])


async def check_password_and_stop():
    gui.background_tasks.create = lambda coroutine, **kwargs: asyncio.ensure_future(coroutine)
    gui.CONSOLE_DIR.mkdir(parents=True, exist_ok=True)
    runner = gui.Runner()
    await runner.start(["firewall", "--hostname", UNREACHABLE, "--username", "admin", "--version", "11.1.0",
                        "--dry-run"], [PASSWORD], "smoke test")
    # The banner is printed only after every prompt, including the hidden password prompt, is answered
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline and runner.running:
        if any("Welcome to the PAN-OS upgrade tool" in line for line in runner.lines):
            break
        await asyncio.sleep(0.5)
    output = "\n".join(runner.lines)
    answered = "Welcome to the PAN-OS upgrade tool" in output
    report("Password from the GUI reaches the CLI's hidden prompt", answered,
           "" if answered else "No banner after the password prompt:\n" + output[-800:])
    report("Password is not shown in the output", PASSWORD not in output)

    started = time.monotonic()
    await runner.stop()
    for _ in range(60):
        if runner.process.returncode is not None:
            break
        await asyncio.sleep(0.5)
    stopped = runner.process.returncode is not None
    report("Stop ends the CLI", stopped, f"took {time.monotonic() - started:.1f}s" if stopped else "still running")
    if not stopped:
        runner.process.kill()


def check_gui_serves():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = dict(os.environ, PAN_OS_GUI_PORT=str(port), PAN_OS_GUI_NO_BROWSER="1", PYTHONUTF8="1")
    server = subprocess.Popen([sys.executable, str(GUI_DIR / "gui.py")], env=env, cwd=GUI_DIR.parent,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
    status, deadline = None, time.monotonic() + 90
    try:
        while time.monotonic() < deadline and server.poll() is None:
            try:
                with LOCAL_HTTP.open(f"http://127.0.0.1:{port}/", timeout=5) as response:
                    status = response.status
                    break
            except OSError:
                time.sleep(1)
    finally:
        server.terminate()
        try:
            output = server.communicate(timeout=20)[0]
        except subprocess.TimeoutExpired:
            server.kill()
            output = server.communicate()[0]
    report("GUI web server starts", status == 200, "" if status == 200 else output.strip()[-800:])


def main():
    print(f"Python {sys.version.split()[0]} on {sys.platform}\nCLI:  {gui.CLI_PYTHON}\n", flush=True)
    if check_cli_starts():
        check_locale()
        asyncio.run(check_password_and_stop())
    check_gui_serves()
    print(f"\n{sum(results)} of {len(results)} checks passed.")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
