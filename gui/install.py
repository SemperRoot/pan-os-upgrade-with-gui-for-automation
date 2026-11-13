"""
Installs the pan-os-upgrade CLI and the PAN-OS Upgrade Console GUI on Windows or Linux.

Needs Python 3.11 or later and nothing else (standard library only).

    Windows:  gui\\setup.cmd                 (or:  py -3 gui\\install.py)
    Linux:    bash gui/setup-linux.sh       (or:  python3 gui/install.py)

Packages come from wherever pip normally gets them, so a pip.ini / pip.conf or PIP_INDEX_URL that
points at an internal mirror (Nexus, Artifactory) is used automatically. Without any network access,
install from a folder of downloaded packages instead (see gui/INSTALL.md):

    python gui/install.py --download wheelhouse     on a machine with internet access
    python gui/install.py --wheelhouse wheelhouse   on the offline machine

Safe to run again: it reuses working virtual environments, rebuilds broken ones (for example ones
copied from another computer), and reinstalls the CLI so it picks up code changes.
"""

import argparse
import locale
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

MIN_PYTHON = (3, 11)
IS_WINDOWS = sys.platform == "win32"
GUI_DIR = Path(__file__).resolve().parent
REPO_DIR = GUI_DIR.parent
CLI_VENV = REPO_DIR / ".venv-cli"
GUI_VENV = GUI_DIR / ".venv"
CLI_REQUIREMENTS = GUI_DIR / "requirements-cli.txt"
GUI_REQUIREMENTS = GUI_DIR / "requirements-gui.txt"
# Building the CLI from source (pip install .) needs its build backend, from pyproject.toml
BUILD_REQUIREMENTS = ["poetry-core"]

if IS_WINDOWS:
    os.system("")  # turns on ANSI colours in the Windows console
    START_COMMAND = f'"{GUI_DIR / "start-gui.cmd"}"'
else:
    START_COMMAND = f'bash "{GUI_DIR / "start-gui.sh"}"'


def step(text: str):
    print(f"\n\033[1;34m==> {text}\033[0m", flush=True)


def ok(text: str):
    print(f"\033[32m    OK: {text}\033[0m", flush=True)


def note(text: str):
    print(f"    {text}", flush=True)


def fail(message: str, *details: str):
    print(f"\n\033[1;31mERROR: {message}\033[0m", file=sys.stderr)
    for line in details:
        print(line, file=sys.stderr)
    print('\nSee "Troubleshooting" in gui/INSTALL.md.', file=sys.stderr)
    sys.exit(1)


def venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")


def venv_works(venv: Path) -> bool:
    """Usable only if its Python runs here. A venv copied from another computer points to a missing Python."""
    python = venv_python(venv)
    if not python.exists():
        return False
    try:
        return subprocess.run([str(python), "-c", "import sys"], capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def run(command: list, failure: str, *hints: str):
    print(f"    $ {' '.join(str(c) for c in command)}", flush=True)
    if subprocess.run([str(c) for c in command]).returncode != 0:
        fail(failure, *hints)


def pip_source_args(args) -> list[str]:
    if args.wheelhouse:
        return ["--no-index", "--find-links", str(args.wheelhouse)]
    if args.index_url:
        return ["--index-url", args.index_url]
    return []


def pip_failure_hints(args) -> tuple[str, ...]:
    if args.wheelhouse:
        return (
            f"A package is missing from {args.wheelhouse}. It must be downloaded on the same operating system",
            f"with the same Python version ({platform.python_version().rsplit('.', 1)[0]}): see gui/INSTALL.md.",
        )
    return (
        "pip couldn't download a package. Check that pip can reach your package index:",
        "  - Internal mirror (Nexus, Artifactory): set it in pip.ini / pip.conf, or pass --index-url URL.",
        "  - No network at all: install from a downloaded folder with --wheelhouse (see gui/INSTALL.md).",
    )


def check_python():
    step("Checking the Python version")
    if sys.version_info < MIN_PYTHON:
        fail(
            f"Python {platform.python_version()} is too old; {'.'.join(map(str, MIN_PYTHON))} or later is needed.",
            f"This is the Python at: {sys.executable}",
        )
    try:
        import venv  # noqa: F401
        import ensurepip  # noqa: F401
    except ImportError:
        fail(
            "This Python can't create virtual environments (the venv or ensurepip module is missing).",
            "On Debian/Ubuntu install python3-venv; on RHEL install python3 (or python3.12) with pip.",
        )
    ok(f"Python {platform.python_version()} at {sys.executable}")


def check_project():
    step("Checking the project folder")
    required = ["pyproject.toml", "pan_os_upgrade/main.py", "gui/gui.py", "gui/cli_launcher.py",
                "gui/requirements-cli.txt", "gui/requirements-gui.txt"]
    for name in required:
        if not (REPO_DIR / name).is_file():
            fail(f"{REPO_DIR / name} is missing.",
                 "This script must stay inside the project's gui folder, and the project must be complete.")
    ok(str(REPO_DIR))


def check_locale():
    step("Checking locale support")
    # Readiness checks parse English dates. The CLI falls back to another English locale when
    # en_US.UTF-8 isn't available, so this is informational only.
    for name in ("en_US.UTF-8", "C.UTF-8", "en-US.UTF-8", "English_United States.utf8", "en-US"):
        try:
            locale.setlocale(locale.LC_ALL, name)
            ok(f"{name} available")
            return
        except locale.Error:
            continue
        finally:
            locale.setlocale(locale.LC_ALL, "")
    note("No English UTF-8 locale found. Readiness checks will use the C locale, which also works.")


def remove_broken_environments():
    step("Removing copied virtual-environment files that can't work here")
    # A copy of the project made on a Mac can contain the Mac's virtual environment inside pan_os_upgrade/.
    # Only removed when it can't run here, so a working local setup is never touched.
    package_dir = REPO_DIR / "pan_os_upgrade"
    if (package_dir / "pyvenv.cfg").is_file() and not venv_works(package_dir):
        for name in ("bin", "lib", "include", "Lib", "Scripts", "Include"):
            shutil.rmtree(package_dir / name, ignore_errors=True)
        (package_dir / "pyvenv.cfg").unlink(missing_ok=True)
        stray_ignore = package_dir / ".gitignore"
        if stray_ignore.is_file() and "Created by venv" in stray_ignore.read_text(errors="replace"):
            stray_ignore.unlink()
        note("Removed the copied environment from pan_os_upgrade/")
    for venv in (CLI_VENV, GUI_VENV):
        if venv.exists() and not venv_works(venv):
            shutil.rmtree(venv)
            note(f"Removed broken environment: {venv}")
    ok("Done")


def create_venv(venv: Path):
    if not venv_works(venv):
        run([sys.executable, "-m", "venv", venv], f"Couldn't create {venv}.")


def install_cli(args):
    step("Installing the CLI into .venv-cli (takes a few minutes)")
    create_venv(CLI_VENV)
    python = venv_python(CLI_VENV)
    pip = [python, "-m", "pip", "install", "--disable-pip-version-check", *pip_source_args(args)]
    run([*pip, "-r", CLI_REQUIREMENTS], "Installing the CLI's packages failed.", *pip_failure_hints(args))
    run([*pip, "--no-deps", "--force-reinstall", REPO_DIR], "Installing the CLI itself failed.",
        *pip_failure_hints(args))
    check = subprocess.run([str(python), "-m", "pip", "check", "--disable-pip-version-check"],
                           capture_output=True, text=True)
    if check.returncode != 0:
        fail("The CLI's packages conflict:", check.stdout + check.stderr)
    help_text = subprocess.run([str(python), str(GUI_DIR / "cli_launcher.py"), "--help"],
                               capture_output=True, text=True, errors="replace",
                               env=dict(os.environ, PYTHONUTF8="1"))
    if "firewall" not in help_text.stdout:
        fail("pan-os-upgrade doesn't start.", *(help_text.stdout + help_text.stderr).splitlines()[-8:])
    ok(f"pan-os-upgrade installed: {CLI_VENV}")


def install_gui(args):
    step("Installing the GUI into gui/.venv")
    create_venv(GUI_VENV)
    python = venv_python(GUI_VENV)
    run([python, "-m", "pip", "install", "--disable-pip-version-check", *pip_source_args(args), "-r", GUI_REQUIREMENTS],
        "Installing the GUI's packages failed.", *pip_failure_hints(args))
    imports = subprocess.run([str(python), "-c", "import nicegui, yaml"], capture_output=True, text=True)
    if imports.returncode != 0:
        fail("The GUI's packages don't import.", imports.stderr.strip())
    ok(f"GUI installed: {GUI_VENV}")


def download(args):
    """Fill a folder with every package the install needs, for this OS and Python version."""
    target = Path(args.download).resolve()
    step(f"Downloading packages into {target}")
    note(f"For: {platform.system()} {platform.machine()}, Python {platform.python_version()}.")
    note("Install from this folder only on machines with the same OS and the same Python minor version.")
    target.mkdir(parents=True, exist_ok=True)
    source = ["--index-url", args.index_url] if args.index_url else []
    for requirements in ([*BUILD_REQUIREMENTS], ["-r", CLI_REQUIREMENTS], ["-r", GUI_REQUIREMENTS]):
        run([sys.executable, "-m", "pip", "download", "--disable-pip-version-check", "--only-binary=:all:",
             *source, "--dest", target, *requirements],
            "Downloading packages failed.", "This step needs access to PyPI or your package mirror.")
    count = len(list(target.glob("*.whl")))
    step("Download complete")
    note(f"{count} packages in {target}")
    note("Copy that folder together with the project to the offline machine, then run there:")
    note(f"    python gui/install.py --wheelhouse {target.name}")


def main():
    parser = argparse.ArgumentParser(description="Install the pan-os-upgrade CLI and GUI (Windows or Linux).")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--wheelhouse", metavar="DIR", type=Path,
                        help="install offline from a folder made with --download (no network used)")
    source.add_argument("--download", metavar="DIR",
                        help="only download all packages into DIR, for a later --wheelhouse install")
    parser.add_argument("--index-url", metavar="URL",
                        help="package index to use instead of pip's configured one, e.g. a Nexus PyPI proxy")
    args = parser.parse_args()
    if args.wheelhouse and args.index_url:
        parser.error("--wheelhouse installs without any index; don't combine it with --index-url")
    if args.wheelhouse:
        args.wheelhouse = args.wheelhouse.resolve()
        if not args.wheelhouse.is_dir():
            parser.error(f"wheelhouse folder not found: {args.wheelhouse}")

    check_python()
    if args.download:
        download(args)
        return
    check_project()
    check_locale()
    remove_broken_environments()
    install_cli(args)
    install_gui(args)

    step("Setup complete")
    note("Start the GUI with:")
    note("")
    note(f"    {START_COMMAND}")
    note("")
    note("Then open http://localhost:8080 in your web browser.")


if __name__ == "__main__":
    main()
