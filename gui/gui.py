"""
Local web GUI for the pan-os-upgrade CLI.

The GUI never imports or modifies pan_os_upgrade. It runs the existing CLI as a separate
process from its own workspace directory (gui/workspace), so its settings.yaml,
inventory.yaml, logs/ and assurance/ outputs never collide with a CLI run started from
the repository root.

Run with:
    gui/.venv/bin/python gui/gui.py

Environment overrides:
    PAN_OS_UPGRADE_BIN   path to the pan-os-upgrade executable
    PAN_OS_GUI_WORKSPACE working directory for CLI runs launched from the GUI
    PAN_OS_GUI_PORT      port to listen on (localhost only), default 8080
"""

# standard library imports
import ast
import asyncio
import codecs
import os
import re
import shlex
import signal
import subprocess
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

# Paths
GUI_DIR = Path(__file__).resolve().parent

# Keep NiceGUI's persisted form values inside gui/, not the directory the GUI was launched from
os.environ.setdefault("NICEGUI_STORAGE_PATH", str(GUI_DIR / ".nicegui"))

# third party imports
import yaml  # noqa: E402
from nicegui import app, background_tasks, run, ui  # noqa: E402

REPO_DIR = GUI_DIR.parent
CLI_BIN = Path(
    os.environ.get(
        "PAN_OS_UPGRADE_BIN", REPO_DIR / "pan_os_upgrade" / "bin" / "pan-os-upgrade"
    )
)
WORKSPACE = Path(os.environ.get("PAN_OS_GUI_WORKSPACE", GUI_DIR / "workspace"))
SETTINGS_PATH = WORKSPACE / "settings.yaml"
INVENTORY_PATH = WORKSPACE / "inventory.yaml"
CONSOLE_DIR = WORKSPACE / "console"
ASSURANCE_SOURCE = REPO_DIR / "pan_os_upgrade" / "components" / "assurance.py"
GUIDE_PATH = GUI_DIR / "README.md"

# Log files that can be viewed (read-only) from the Logs page
LOG_FILES = {
    "GUI runs (gui/workspace/logs/upgrade.log)": WORKSPACE / "logs" / "upgrade.log",
    "Repo root runs (logs/upgrade.log)": REPO_DIR / "logs" / "upgrade.log",
}

ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
# Noise from getpass when the password prompt is answered over stdin (input is not echoed)
GETPASS_NOISE = ("GetPassWarning: Can not control echo", "passwd = fallback_getpass(", "Warning: Password input may be echoed.")
MAX_CONSOLE_LINES = 20000
# Console capture files are named <YYYY-mm-dd_HH-MM-SS>_<command>.log by Runner.start
CONSOLE_FILE_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})-(\d{2})_(\w+)\.log$")

APP_NAME = "PAN-OS Upgrade Console"

# Visual design
THEME = {
    "primary": "#0B5CAB",
    "secondary": "#475569",
    "accent": "#FA582D",
    "positive": "#2E7D32",
    "negative": "#C62828",
    "warning": "#B26A00",
    "info": "#0277BD",
    "dark": "#0F172A",
}

CSS = """
:root {
  --app-bg: #F4F6F9; --app-surface: #FFFFFF; --app-border: #E2E8F0;
  --app-text: #0F172A; --app-muted: #64748B; --app-subtle: #F8FAFC;
}
body.body--dark {
  --app-bg: #0B1220; --app-surface: #111A2B; --app-border: #1F2B3F;
  --app-text: #E2E8F0; --app-muted: #94A3B8; --app-subtle: #0E1626;
}
body { background: var(--app-bg); color: var(--app-text);
  font-family: Inter, "Segoe UI", system-ui, -apple-system, sans-serif; }
.app-header, .app-footer, .q-drawer { background: var(--app-surface) !important; color: var(--app-text) !important; }
.app-header { border-bottom: 1px solid var(--app-border); }
.app-footer { border-top: 1px solid var(--app-border); }
.q-drawer { border-right: 1px solid var(--app-border) !important; }
.q-tab-panels, .q-tab-panel { background: transparent !important; padding: 0 !important; }
.app-card { background: var(--app-surface); border: 1px solid var(--app-border); border-radius: 8px; box-shadow: none; }
.app-muted { color: var(--app-muted); }
.app-overline { font-size: 11px; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; color: var(--app-muted); }
.app-mono { font-family: "JetBrains Mono", "SF Mono", Menlo, Consolas, monospace; }
.app-nav .q-item { border-radius: 6px; margin: 1px 10px; min-height: 38px; padding: 4px 12px; color: var(--app-text); }
.app-nav .q-item.app-nav-active { background: rgba(11, 92, 171, .10); color: #0B5CAB; font-weight: 600; }
body.body--dark .app-nav .q-item.app-nav-active { background: rgba(96, 165, 250, .15); color: #93C5FD; }
.app-command { font-family: "JetBrains Mono", "SF Mono", Menlo, Consolas, monospace; font-size: 12px;
  background: var(--app-subtle); border: 1px solid var(--app-border); border-radius: 6px;
  padding: 10px 12px; white-space: pre-wrap; word-break: break-all; }
.app-terminal { background: #0B1020 !important; color: #E2E8F0 !important; border: 1px solid #1E293B !important;
  border-radius: 6px; padding: 10px 12px; font-size: 12px;
  font-family: "JetBrains Mono", "SF Mono", Menlo, Consolas, monospace; }
.app-notice { border-radius: 6px; padding: 10px 12px; font-size: 13px; line-height: 1.4; border: 1px solid; }
.app-notice-info { background: rgba(2, 119, 189, .08); border-color: rgba(2, 119, 189, .25); }
.app-notice-negative { background: rgba(198, 40, 40, .08); border-color: rgba(198, 40, 40, .30); }
.app-notice-warning { background: rgba(178, 106, 0, .10); border-color: rgba(178, 106, 0, .30); }
.app-notice-positive { background: rgba(46, 125, 50, .08); border-color: rgba(46, 125, 50, .25); }
.app-prompt { background: rgba(250, 88, 45, .10); border: 1px solid rgba(250, 88, 45, .35); border-radius: 6px; }
.app-kv { display: grid; grid-template-columns: max-content 1fr; gap: 6px 16px; font-size: 13px; }
.app-doc { font-size: 14px; line-height: 1.55; }
.app-doc h2 { font-size: 1.25rem; font-weight: 600; margin: 28px 0 8px; padding-top: 12px; border-top: 1px solid var(--app-border); }
.app-doc h3 { font-size: 1.05rem; font-weight: 600; margin: 20px 0 6px; }
.app-doc p { margin: 6px 0; }
.app-doc ul { list-style: disc; padding-left: 1.4rem; margin: 6px 0; }
.app-doc ol { list-style: decimal; padding-left: 1.4rem; margin: 6px 0; }
.app-doc li { margin: 3px 0; }
.app-doc a { color: #0B5CAB; text-decoration: underline; }
.app-doc table { border-collapse: collapse; margin: 10px 0; font-size: 13px; }
.app-doc th, .app-doc td { border: 1px solid var(--app-border); padding: 6px 10px; text-align: left; vertical-align: top; }
.app-doc th { background: var(--app-subtle); font-weight: 600; }
.app-doc code { font-family: "JetBrains Mono", "SF Mono", Menlo, Consolas, monospace; font-size: 12px;
  background: var(--app-subtle); border: 1px solid var(--app-border); border-radius: 4px; padding: 0 4px; }
.app-doc pre { background: #0B1020; color: #E2E8F0; padding: 10px 12px; border-radius: 6px; overflow-x: auto; margin: 8px 0; }
.app-doc pre code { background: none; border: none; color: inherit; padding: 0; }
.app-doc blockquote { border-left: 3px solid #B26A00; background: rgba(178, 106, 0, .08); margin: 10px 0; padding: 8px 12px; border-radius: 0 6px 6px 0; }
.app-doc-compact { font-size: 13px; }
.app-doc-compact ul { margin: 0; }
"""

NAV = [
    ("Operations", [
        ("firewall", "Firewall", "security"),
        ("panorama", "Panorama", "dns"),
        ("batch", "Batch upgrade", "view_list"),
    ]),
    ("Configuration", [
        ("inventory", "Inventory", "inventory_2"),
        ("settings", "Settings", "tune"),
    ]),
    ("Monitoring", [
        ("history", "Run history", "history"),
        ("logs", "Logs", "description"),
    ]),
    ("Help", [
        ("guide", "HA upgrade guide", "menu_book"),
    ]),
]

DRY_RUN_NOTE = (
    "Dry run downloads the target image to the device and runs snapshots, readiness checks and a "
    "configuration backup, then stops before install and reboot."
)
LIVE_NOTE = "Live upgrade installs PAN-OS and reboots the devices. You will be asked to confirm before it starts."


def load_assurance_options() -> tuple[dict, dict]:
    """
    Read READINESS_CHECKS and STATE_SNAPSHOTS from the AssuranceOptions class without
    importing pan_os_upgrade (its dependencies live in a different virtual environment).
    """
    try:
        tree = ast.parse(ASSURANCE_SOURCE.read_text())
    except (OSError, SyntaxError):
        return {}, {}

    options = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "AssuranceOptions":
            for item in node.body:
                if (
                    isinstance(item, ast.Assign)
                    and len(item.targets) == 1
                    and isinstance(item.targets[0], ast.Name)
                    and item.targets[0].id in ("READINESS_CHECKS", "STATE_SNAPSHOTS")
                ):
                    try:
                        options[item.targets[0].id] = ast.literal_eval(item.value)
                    except ValueError:
                        pass
    return options.get("READINESS_CHECKS", {}), options.get("STATE_SNAPSHOTS", {})


READINESS_CHECKS, STATE_SNAPSHOTS = load_assurance_options()


class Runner:
    """Runs a single CLI process at a time and collects its output."""

    def __init__(self):
        self.process: Optional[asyncio.subprocess.Process] = None
        self.run_id = 0
        self.lines: list[str] = []
        self.partial = ""  # trailing output without a newline, usually a prompt
        self.description = ""
        self.console_path: Optional[Path] = None
        self.started: Optional[datetime] = None
        self.finished: Optional[datetime] = None
        self.exit_code: Optional[int] = None
        self.stopping = False

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.returncode is None

    @property
    def awaiting_input(self) -> bool:
        return self.running and bool(self.partial.strip())

    async def start(self, args: list[str], stdin_lines: list[str], description: str):
        self.started = datetime.now()
        self.finished = None
        console_path = CONSOLE_DIR / f"{self.started:%Y-%m-%d_%H-%M-%S}_{args[0]}.log"
        console_path.parent.mkdir(parents=True, exist_ok=True)
        self.console_path = console_path
        self.run_id += 1
        self.lines = [
            f"$ pan-os-upgrade {' '.join(args)}",
            f"  (working directory: {WORKSPACE})",
            f"  (console output saved to: {console_path})",
            "",
        ]
        self.partial = ""
        self.description = description
        self.exit_code = None
        self.stopping = False

        env = dict(os.environ, PYTHONUNBUFFERED="1", NO_COLOR="1", TERM="dumb", COLUMNS="200")

        # Output goes to a file rather than a pipe, so the CLI keeps running safely if the GUI
        # is closed mid-upgrade. A new session detaches it from any terminal, so password prompts
        # read from stdin and the whole process group can be signalled on stop.
        with open(console_path, "wb") as console_file:
            self.process = await asyncio.create_subprocess_exec(
                str(CLI_BIN),
                *args,
                cwd=WORKSPACE,
                stdin=asyncio.subprocess.PIPE,
                stdout=console_file,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
                start_new_session=True,
            )
        for line in stdin_lines:
            self.process.stdin.write(f"{line}\n".encode())
        await self.process.stdin.drain()

        background_tasks.create(self._read_output(self.process, console_path))

    async def _read_output(self, process: asyncio.subprocess.Process, console_path: Path):
        # Incremental decoding, so multi-byte characters (the CLI logs emojis) split across reads stay intact
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        with open(console_path, "rb") as console_file:
            while True:
                chunk = console_file.read(4096)
                if chunk:
                    self._append(decoder.decode(chunk))
                elif process.returncode is not None:
                    break
                else:
                    await asyncio.sleep(0.2)
        self.exit_code = await process.wait()
        self.finished = datetime.now()
        if self.partial:
            self.lines.append(self.partial)
            self.partial = ""
        self.lines.append("")
        self.lines.append(f"Process exited with code {self.exit_code}")

    def _append(self, text: str):
        text = ANSI_ESCAPE.sub("", text).replace("\r\n", "\n").replace("\r", "\n")
        *complete, self.partial = (self.partial + text).split("\n")
        self.lines.extend(line for line in complete if not any(noise in line for noise in GETPASS_NOISE))
        if len(self.lines) > MAX_CONSOLE_LINES:
            del self.lines[: len(self.lines) - MAX_CONSOLE_LINES]

    async def send(self, text: str):
        if not self.running:
            return
        self.lines.append(f"{self.partial}{text}")
        self.partial = ""
        self.process.stdin.write(f"{text}\n".encode())
        await self.process.stdin.drain()

    async def stop(self):
        """
        Interrupt the process group, escalating if it does not exit. SIGINT alone is not enough
        while upgrade threads are running: the CLI's main thread waits for them to finish.
        """
        if not self.running or self.stopping:
            return
        self.stopping = True
        process = self.process
        for sig, grace_seconds in ((signal.SIGINT, 10), (signal.SIGTERM, 5), (signal.SIGKILL, 5)):
            if process.returncode is not None:
                break
            self.lines.append(f"[GUI] Sending {sig.name} to the process...")
            try:
                os.killpg(process.pid, sig)
            except ProcessLookupError:
                break
            try:
                await asyncio.wait_for(process.wait(), timeout=grace_seconds)
            except asyncio.TimeoutError:
                pass

    def status(self) -> tuple[str, str, str]:
        """(label, color, icon) describing the current state, shared by the header and the output dock."""
        if self.running and self.stopping:
            return "Stopping", "warning", "hourglass_top"
        if self.awaiting_input:
            return "Awaiting input", "accent", "keyboard"
        if self.running:
            return "Running", "info", "sync"
        if self.started is None:
            return "Idle", "grey-7", "radio_button_unchecked"
        if self.stopping:
            return "Stopped", "warning", "stop_circle"
        if self.exit_code == 0:
            return "Completed", "positive", "check_circle"
        return f"Failed (exit {self.exit_code})", "negative", "error"

    def elapsed(self) -> str:
        if not self.started:
            return ""
        seconds = int(((self.finished or datetime.now()) - self.started).total_seconds())
        return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


runner = Runner()


def other_cli_processes() -> list[str]:
    """List pan-os-upgrade processes not started by this GUI (read-only check)."""
    result = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True)
    own_pid = runner.process.pid if runner.running else None
    found = []
    for line in result.stdout.splitlines():
        pid, _, command = line.strip().partition(" ")
        tokens = command.split()
        is_cli = any(Path(t).name == "pan-os-upgrade" or t == "pan_os_upgrade.main" for t in tokens)
        if not pid.isdigit() or not is_cli or int(pid) == own_pid:
            continue
        # Never display passwords passed on another process's command line
        for i, token in enumerate(tokens[:-1]):
            if token in ("-p", "--password"):
                tokens[i + 1] = "********"
        tokens = [re.sub(r"^(--password=).*", r"\1********", t) for t in tokens]
        found.append(f"PID {pid}: {' '.join(tokens)}")
    return found


def read_settings() -> dict:
    if SETTINGS_PATH.exists():
        with open(SETTINGS_PATH) as f:
            return yaml.safe_load(f) or {}
    return {}


def read_inventory() -> list[str]:
    if INVENTORY_PATH.exists():
        with open(INVENTORY_PATH) as f:
            return (yaml.safe_load(f) or {}).get("firewalls_to_upgrade", []) or []
    return []


def tail(path: Path, lines: int = 500) -> str:
    if not path.exists():
        return f"{path} does not exist yet."
    with open(path, errors="replace") as f:
        return "".join(f.readlines()[-lines:])


def console_runs() -> list[dict]:
    """Saved console captures from previous GUI runs, newest first."""
    rows = []
    for path in CONSOLE_DIR.glob("*.log") if CONSOLE_DIR.exists() else []:
        match = CONSOLE_FILE_NAME.match(path.name)
        if not match:
            continue
        day, hh, mm, ss, command = match.groups()
        size = path.stat().st_size
        rows.append({
            "id": path.name,
            "started": f"{day} {hh}:{mm}:{ss}",
            "command": command,
            "size": f"{size / 1024:.1f} KB" if size >= 1024 else f"{size} B",
        })
    return sorted(rows, key=lambda row: row["started"], reverse=True)


def value(element) -> str:
    return str(element.value or "").strip()


PLACEHOLDER = re.compile(r"<[a-z-]+>")


def arg(element, name: str) -> str:
    """Field value for a CLI argument, or a <name> placeholder for the preview while the field is empty."""
    return value(element) or f"<{name}>"


def command_line(args: list[str]) -> str:
    return "pan-os-upgrade " + " ".join(a if PLACEHOLDER.fullmatch(a) else shlex.quote(a) for a in args)


# ---------------------------------------------------------------------------
# Reusable building blocks
# ---------------------------------------------------------------------------

REQUIRED = {"Required": lambda v: bool(str(v or "").strip())}


def text_field(label: str, *, hint: str = "", password: bool = False, required: bool = False, mark: str = ""):
    """Outlined input. Required fields only show their error after a Run attempt, then clear as they're fixed."""
    element = ui.input(
        label, password=password, password_toggle_button=password, validation=REQUIRED if required else None
    ).props("outlined dense stack-label").classes("w-full")
    if hint:
        element.props(f'hint="{hint}"')
    if required:
        element.without_auto_validation()
        element.on_value_change(lambda _: element.error is not None and element.validate())
    if mark:
        element.mark(mark)
    return element


def validate_required(*elements) -> bool:
    results = [element.validate() for element in elements]
    if not all(results):
        ui.notify("Complete the required fields highlighted in red.", type="negative")
    return all(results)


def remembered(element, key: str):
    """Persist a non-secret form value across page reloads and GUI restarts."""
    app.storage.general.setdefault(key, element.value)
    return element.bind_value(app.storage.general, key)


def host_input(device: str, prefix: str):
    return remembered(
        text_field(f"{device} hostname or IP", required=True, mark=f"{prefix}-hostname"), f"{prefix}.hostname"
    )


def credential_inputs(prefix: str):
    username = remembered(text_field("Username", required=True, mark=f"{prefix}-username"), f"{prefix}.username")
    # Passwords are never persisted
    password = text_field("Password", password=True, required=True, mark=f"{prefix}-password")
    return username, password


@contextmanager
def card(title: str = "", subtitle: str = "", icon: str = "", classes: str = ""):
    with ui.card().props("flat").classes(f"app-card w-full p-0 gap-0 {classes}"):
        if title:
            with ui.row().classes("w-full items-center px-5 pt-4 pb-3 gap-3 no-wrap"):
                if icon:
                    ui.icon(icon).classes("text-xl text-primary")
                with ui.column().classes("gap-0"):
                    ui.label(title).classes("text-base font-semibold")
                    if subtitle:
                        ui.label(subtitle).classes("text-xs app-muted")
            ui.separator()
        with ui.column().classes("w-full p-5 gap-4"):
            yield


def notice(text: str, kind: str = "info", icon: str = "info"):
    with ui.row().classes(f"app-notice app-notice-{kind} w-full items-start gap-2 no-wrap") as row:
        ui.icon(icon, color=kind).classes("text-lg mt-[1px]")
        label = ui.label(text).classes("whitespace-pre-wrap")
    row.text_label = label
    return row


def page_header(group: str, title: str, description: str, icon: str):
    with ui.row().classes("w-full items-center gap-4 no-wrap mb-2"):
        with ui.element("div").classes("rounded-lg p-2 bg-primary/10 flex"):
            ui.icon(icon, color="primary").classes("text-2xl")
        with ui.column().classes("gap-0"):
            ui.label(group).classes("app-overline")
            ui.label(title).classes("text-2xl font-semibold leading-tight")
            ui.label(description).classes("text-sm app-muted")
        actions = ui.row().classes("ml-auto items-center gap-2")
    return actions


def operation_columns():
    """Two-column workspace: form cards on the left, sticky execution summary on the right."""
    grid = ui.element("div").classes("grid grid-cols-1 lg:grid-cols-3 gap-4 w-full items-start")
    with grid:
        form = ui.column().classes("lg:col-span-2 gap-4 w-full")
        side = ui.column().classes("gap-4 w-full lg:sticky lg:top-4")
    return form, side


def execution_card(command: Callable[[bool], list[str]], start: Callable, mark: str = ""):
    """Mode selector, live command preview and the primary action for an operation page."""
    with card("Execution", "Review the command before running it", icon="play_circle"):
        # Never persisted: every page load starts in dry-run mode
        mode = ui.toggle({"dry": "Dry run", "live": "Live upgrade"}, value="dry").props(
            "spread no-caps unelevated toggle-color=primary"
        ).classes("w-full")
        if mark:
            mode.mark(f"{mark}-mode")
        dry_note = notice(DRY_RUN_NOTE, "info", "science")
        live_note = notice(LIVE_NOTE, "negative", "warning")
        ui.label("Command").classes("app-overline")
        preview = ui.label().classes("app-command w-full")
        ui.label(
            "The password is sent on stdin. It never appears on the command line or in saved settings."
        ).classes("text-xs app-muted")
        button = ui.button(on_click=lambda: start(mode.value == "dry")).props("unelevated no-caps").classes(
            "w-full h-11"
        )
        if mark:
            button.mark(f"{mark}-run")

    state = {}

    def refresh():
        dry = mode.value == "dry"
        try:
            text = command_line(command(dry))
        except Exception:  # preview must never break the page
            text = "pan-os-upgrade ..."
        current = (dry, text, runner.running)
        if state.get("last") == current:
            return
        state["last"] = current
        preview.text = text
        dry_note.set_visibility(dry)
        live_note.set_visibility(not dry)
        button.set_text("Start dry run" if dry else "Start live upgrade")
        button.props(f"color={'primary' if dry else 'negative'} icon={'science' if dry else 'rocket_launch'}")
        button.set_enabled(not runner.running)
        if runner.running:
            button.set_text("Another run is in progress")

    ui.timer(0.5, refresh)
    refresh()
    return mode


async def confirm_real_upgrade(details: list[tuple[str, str]], version: str, console_prompts: bool = False) -> bool:
    with ui.dialog().props("persistent") as dialog, ui.card().props("flat").classes(
        "app-card w-[40rem] max-w-full p-0 gap-0"
    ):
        with ui.row().classes("w-full items-center gap-3 px-5 py-4 no-wrap"):
            ui.icon("warning", color="negative").classes("text-3xl")
            with ui.column().classes("gap-0"):
                ui.label("Confirm live upgrade").classes("text-lg font-semibold")
                ui.label("Dry run is off. This changes production devices.").classes("text-sm app-muted")
        ui.separator()
        with ui.column().classes("w-full p-5 gap-4"):
            with ui.element("div").classes("app-kv w-full"):
                for key, val in details:
                    ui.label(key).classes("app-muted")
                    ui.label(val).classes("app-mono whitespace-pre-wrap")
            notice(
                "Devices will download and install PAN-OS and reboot. "
                + (
                    "Answer the CLI's prompts in the Output panel."
                    if console_prompts
                    else "The CLI runs in non-interactive mode, so there are no further confirmations."
                ),
                "negative",
                "restart_alt",
            )
            notice(
                "HA pairs: HA is suspended on each member and is not restored automatically. After the run, "
                "check show high-availability state and run request high-availability state functional "
                "on any member left suspended.",
                "warning",
                "device_hub",
            )
            external = await run.io_bound(other_cli_processes)
            if external:
                notice("Other pan-os-upgrade processes are already running:\n" + "\n".join(external), "warning")
            ui.label(f"Type the target version {version} to confirm.").classes("text-sm")
            typed = ui.input(placeholder=version).props("outlined dense autofocus").classes("w-full app-mono").mark(
                "confirm-version"
            )
        ui.separator()
        with ui.row().classes("w-full justify-end gap-2 px-5 py-3"):
            ui.button("Cancel", on_click=lambda: dialog.submit(False)).props("flat no-caps")
            confirm = ui.button(
                "Start live upgrade", icon="rocket_launch", color="negative", on_click=lambda: dialog.submit(True)
            ).props("unelevated no-caps").mark("confirm-upgrade")
            confirm.bind_enabled_from(typed, "value", backward=lambda v: (v or "").strip() == version)
    result = await dialog
    dialog.delete()
    return bool(result)


async def launch(args: list[str], stdin_lines: list[str], description: str):
    if runner.running:
        ui.notify("A command is already running. Stop it or wait for it to finish.", type="warning")
        return
    if not CLI_BIN.exists():
        ui.notify(f"CLI not found: {CLI_BIN}", type="negative")
        return
    await runner.start(args, stdin_lines, description)
    ui.notify(f"Started: {description}", type="info")


def ha_guidance(first: str, second: str, navigate: Callable[[str], None], extra: Optional[list[str]] = None):
    """Condensed HA behavior from README.md, shown next to the forms that can upgrade an HA pair."""
    items = [
        f"**Same version on both members:** the {first} member is upgraded first. The {second} member "
        "follows after HA sync, failing over to the upgraded member.",
        "**Different versions:** both members upgrade **at the same time**, so the pair can go fully down. "
        "Align the versions first, or upgrade one member at a time.",
        f"**Dry run** only exercises the {first} member. The other member is skipped.",
        "**HA is not restored automatically.** After a live run, check `show high-availability state` and run "
        "`request high-availability state functional` on any member left suspended.",
        *(extra or []),
    ]
    with card("HA pairs", "How this tool upgrades the members of an HA pair", icon="device_hub"):
        ui.markdown("\n".join(f"- {item}" for item in items)).classes("app-doc app-doc-compact w-full")
        ui.button("Read the full HA upgrade guide", icon="menu_book", on_click=lambda: navigate("guide")).props(
            "flat dense no-caps"
        ).classes("self-start")


def guide_markdown() -> str:
    try:
        text = GUIDE_PATH.read_text()
    except OSError:
        return f"`{GUIDE_PATH}` not found."
    text = re.sub(r"\A# .*\n", "", text)  # the page header already shows the title
    # Links to repository files don't resolve in the browser; keep their text
    return re.sub(r"\[([^\]]+)\]\((?!#|https?:)[^)]+\)", r"\1", text)


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


def firewall_page(navigate: Callable[[str], None]):
    page_header("Operations", "Firewall upgrade", "Upgrade a single firewall, or both members of an HA pair.",
                "security")
    form, side = operation_columns()
    with form:
        with card("Target", "Device and PAN-OS release to install", icon="router"):
            with ui.element("div").classes("grid grid-cols-1 md:grid-cols-2 gap-4 w-full"):
                hostname = host_input("Firewall", "firewall")
                peer = remembered(
                    text_field("HA peer hostname or IP", hint="Optional. Auto-detected from HA state when empty."),
                    "firewall.peer",
                )
                version = remembered(
                    text_field("Target PAN-OS version", hint="For example 10.2.7-h3", required=True,
                               mark="firewall-version"),
                    "firewall.version",
                )
        with card("Credentials", "Passwords are never saved", icon="key"):
            with ui.element("div").classes("grid grid-cols-1 md:grid-cols-2 gap-4 w-full"):
                username, password = credential_inputs("firewall")
        ha_guidance("passive (or active-secondary)", "active (or active-primary)", navigate)

    def command(dry: bool) -> list[str]:
        args = ["firewall", "--hostname", arg(hostname, "hostname"), "--username", arg(username, "username"),
                "--version", arg(version, "version")]
        if value(peer):
            args += ["--peer", value(peer)]
        args.append("--dry-run" if dry else "--non-interactive")
        return args

    async def start(dry: bool):
        if not validate_required(hostname, version, username, password):
            return
        if not dry:
            details = [("Firewall", value(hostname)), ("HA peer", value(peer) or "auto-detect"),
                       ("Target version", value(version))]
            if not await confirm_real_upgrade(details, value(version)):
                return
        await launch(command(dry), [password.value],
                     f"firewall {value(hostname)} -> {value(version)}" + (" (dry run)" if dry else ""))

    with side:
        execution_card(command, start, mark="firewall")


def panorama_page(navigate: Callable[[str], None]):
    page_header("Operations", "Panorama upgrade", "Upgrade a Panorama appliance, and its HA peer if it has one.",
                "dns")
    form, side = operation_columns()
    with form:
        with card("Target", "Appliance and PAN-OS release to install", icon="dns"):
            with ui.element("div").classes("grid grid-cols-1 md:grid-cols-2 gap-4 w-full"):
                hostname = host_input("Panorama", "panorama")
                version = remembered(
                    text_field("Target PAN-OS version", hint="For example 11.1.4-h7", required=True,
                               mark="panorama-version"),
                    "panorama.version",
                )
        with card("Credentials", "Passwords are never saved", icon="key"):
            with ui.element("div").classes("grid grid-cols-1 md:grid-cols-2 gap-4 w-full"):
                username, password = credential_inputs("panorama")
        ha_guidance("secondary-passive", "primary-active", navigate)

    def command(dry: bool) -> list[str]:
        args = ["panorama", "--hostname", arg(hostname, "hostname"), "--username", arg(username, "username"),
                "--version", arg(version, "version")]
        if dry:
            args.append("--dry-run")
        return args

    async def start(dry: bool):
        if not validate_required(hostname, version, username, password):
            return
        stdin_lines = [password.value]
        if not dry:
            details = [("Panorama", value(hostname)), ("Target version", value(version))]
            if not await confirm_real_upgrade(details, value(version), console_prompts=True):
                return
            # The panorama command has no --non-interactive flag; answer its "Dry Run?" prompt
            stdin_lines.append("n")
        await launch(command(dry), stdin_lines,
                     f"panorama {value(hostname)} -> {value(version)}" + (" (dry run)" if dry else ""))

    with side:
        execution_card(command, start, mark="panorama")


def batch_page(navigate: Callable[[str], None]):
    page_header("Operations", "Batch upgrade",
                "Upgrade multiple firewalls managed by Panorama, using Panorama as a proxy.", "view_list")
    form, side = operation_columns()
    with form:
        with card("Target", "Panorama proxy and firewall release to install", icon="dns"):
            with ui.element("div").classes("grid grid-cols-1 md:grid-cols-2 gap-4 w-full"):
                hostname = host_input("Panorama", "batch")
                version = remembered(
                    text_field("Firewall target version", hint="For example 10.2.7-h3", required=True,
                               mark="batch-version"),
                    "batch.version",
                )
        with card("Devices", "Which firewalls to upgrade", icon="lan"):
            inventory = remembered(
                text_field(
                    "Firewall hostnames, comma separated",
                    hint="Optional. Include both peers of an HA pair. Names must match the hostnames in Panorama.",
                    mark="batch-inventory",
                ),
                "batch.inventory",
            )
            with ui.row().classes("w-full items-center gap-2 no-wrap"):
                source = notice("", "info", "checklist")
                source.classes("grow")
                ui.button("Edit inventory", icon="edit", on_click=lambda: navigate("inventory")).props(
                    "flat no-caps"
                ).classes("shrink-0")
        with card("Credentials", "Panorama login. Passwords are never saved", icon="key"):
            with ui.element("div").classes("grid grid-cols-1 md:grid-cols-2 gap-4 w-full"):
                username, password = credential_inputs("batch")
        ha_guidance(
            "passive (or active-secondary)", "active (or active-primary)", navigate,
            extra=["**List both members of every pair.** If only the active member of a same-version pair is "
                   "listed, nothing is upgraded. If only the passive member is listed, the pair ends up on "
                   "mismatched versions."],
        )

    def field_targets() -> list[str]:
        return [h.strip() for h in (inventory.value or "").split(",") if h.strip()]

    def update_device_source():
        if field_targets():
            source.text_label.text = f"{len(field_targets())} firewalls from the field above."
        elif read_inventory():
            source.text_label.text = f"{len(read_inventory())} firewalls from the saved inventory."
        else:
            source.text_label.text = "No devices set. You will pick them from a table in the Output panel."

    inventory.on_value_change(update_device_source)
    ui.timer(3, update_device_source)  # the Inventory page can change the file
    update_device_source()

    def command(dry: bool) -> list[str]:
        selected = field_targets()
        targets = selected or read_inventory()
        args = ["batch", "--hostname", arg(hostname, "hostname"), "--username", arg(username, "username"),
                "--version", arg(version, "version")]
        if selected:
            args += ["--inventory", ",".join(selected)]
        if dry:
            args.append("--dry-run")
        elif targets:
            args.append("--non-interactive")
        return args

    async def start(dry: bool):
        if not validate_required(hostname, version, username, password):
            return
        targets = field_targets() or read_inventory()
        stdin_lines = [password.value]
        if dry:
            if targets:
                # With an inventory there is no device-selection prompt, only the dry-run confirmation
                stdin_lines.append("y")
            else:
                ui.notify("Pick devices in the Output panel: enter numbers (e.g. 1,3-4), then click Done.",
                          type="info")
        else:
            devices = "\n".join(targets) if targets else "selected in the Output panel"
            details = [("Panorama", value(hostname)), ("Target version", value(version)),
                       (f"Firewalls ({len(targets)})" if targets else "Firewalls", devices)]
            if not await confirm_real_upgrade(details, value(version), console_prompts=not targets):
                return
            if not targets:
                # Interactive mode: answer the "Dry Run?" prompt; device selection and the final
                # confirmation are answered in the Output panel
                stdin_lines.append("n")
                ui.notify("Pick devices in the Output panel, click Done, then confirm with Yes.", type="info")
        await launch(command(dry), stdin_lines,
                     f"batch via {value(hostname)} -> {value(version)}" + (" (dry run)" if dry else ""))

    with side:
        execution_card(command, start, mark="batch")


def inventory_page():
    page_header("Configuration", "Inventory", "Firewalls targeted by batch upgrades.", "inventory_2")
    with ui.element("div").classes("grid grid-cols-1 lg:grid-cols-2 gap-4 w-full items-start"):
        with card("Upgrade inventory", str(INVENTORY_PATH), icon="list_alt"):
            editor = ui.textarea("One hostname per line", value="\n".join(read_inventory())).props(
                "outlined rows=14"
            ).classes("w-full app-mono")
            with ui.row().classes("w-full items-center gap-2"):
                count = ui.chip("", icon="dns").props("outline dense")
                unsaved = ui.chip("Unsaved changes", icon="edit", color="warning").props("dense text-color=white")
                ui.space()
                ui.button("Revert", icon="undo", on_click=lambda: reload()).props("flat no-caps")
                ui.button("Save", icon="save", on_click=lambda: save()).props("unelevated no-caps")

        with card("Discover from Panorama", "Build the list from devices Panorama manages", icon="travel_explore"):
            ui.label(
                "Runs the CLI inventory command. Pick devices in the Output panel prompt (e.g. 1,3-5). "
                "The list on the left reloads when the file changes."
            ).classes("text-sm app-muted")
            hostname = host_input("Panorama", "inventory")
            username, password = credential_inputs("inventory")

            async def discover():
                if not validate_required(hostname, username, password):
                    return
                args = ["inventory", "--hostname", value(hostname), "--username", value(username)]
                await launch(args, [password.value], f"inventory from {value(hostname)}")

            ui.button("Discover devices", icon="travel_explore", on_click=discover).props(
                "unelevated no-caps"
            ).classes("self-end")

    state = {"saved": read_inventory()}

    def hostnames() -> list[str]:
        return [line.strip() for line in (editor.value or "").splitlines() if line.strip()]

    def save():
        WORKSPACE.mkdir(parents=True, exist_ok=True)
        with open(INVENTORY_PATH, "w") as f:
            yaml.dump({"firewalls_to_upgrade": hostnames()}, f, default_flow_style=False)
        state["saved"] = hostnames()
        ui.notify(f"Saved {len(hostnames())} firewalls to inventory.yaml", type="positive")

    def reload():
        state["saved"] = read_inventory()
        editor.value = "\n".join(state["saved"])

    def refresh():
        on_disk = read_inventory()
        # Pick up external changes (e.g. Discover) when there are no local edits
        if on_disk != state["saved"] and hostnames() == state["saved"]:
            reload()
        count.text = f"{len(hostnames())} firewalls"
        unsaved.set_visibility(hostnames() != state["saved"])

    ui.timer(2, refresh)
    refresh()


def settings_page():
    actions = page_header("Configuration", "Settings",
                          f"Saved to {SETTINGS_PATH}. Used only by runs launched from this GUI.", "tune")
    with actions:
        unsaved = ui.chip("Unsaved changes", icon="edit", color="warning").props("dense text-color=white")
        revert_button = ui.button("Revert", icon="undo").props("flat no-caps")
        save_button = ui.button("Save settings", icon="save").props("unelevated no-caps")

    numbers: dict[str, tuple] = {}

    def number(label: str, path: str, default: int, suffix: str = ""):
        element = ui.number(label, min=1, precision=0, suffix=suffix or None).props(
            "outlined dense stack-label"
        ).classes("w-full")
        numbers[path] = (element, default)

    with ui.element("div").classes("grid grid-cols-1 lg:grid-cols-2 gap-4 w-full items-start"):
        with ui.column().classes("gap-4 w-full"):
            with card("Execution", "Parallelism and connectivity", icon="speed"):
                with ui.element("div").classes("grid grid-cols-1 md:grid-cols-3 gap-4 w-full"):
                    number("Concurrent threads", "concurrency.threads", 10)
                    number("Connection timeout", "timeout_settings.connection_timeout", 30, "s")
                    number("Command timeout", "timeout_settings.command_timeout", 120, "s")
            with card("Retry policy", "How long to wait between attempts, and how many attempts", icon="replay"):
                with ui.element("div").classes("grid grid-cols-[8rem_1fr_1fr] gap-x-4 gap-y-3 items-center w-full"):
                    ui.label("")
                    ui.label("Interval").classes("app-overline")
                    ui.label("Max tries").classes("app-overline")
                    for stage, interval, tries in (("Download", 60, 3), ("Install", 60, 3), ("Reboot", 60, 30)):
                        ui.label(stage).classes("text-sm font-medium")
                        number("Seconds", f"{stage.lower()}.retry_interval", interval, "s")
                        number("Attempts", f"{stage.lower()}.max_tries", tries)
            with card("Logging", "CLI log output for GUI runs", icon="article"):
                with ui.element("div").classes("grid grid-cols-1 md:grid-cols-2 gap-4 w-full"):
                    log_level = ui.select(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], label="Logging level").props(
                        "outlined dense stack-label"
                    ).classes("w-full")
                    log_path = ui.input("Log file path").props("outlined dense stack-label").classes("w-full app-mono")
                    number("Max log size", "logging.max_size", 10, "MB")
                    number("Upgrade logs to retain", "logging.upgrade_log_count", 10)

        with ui.column().classes("gap-4 w-full"):
            def option_section(title: str, subtitle: str, icon: str, options: dict, blocking: bool):
                with card(title, subtitle, icon=icon):
                    disabled = ui.switch(f"Disable all {title.lower()}")
                    customize = ui.switch(f"Customize {title.lower()}")
                    customize.bind_visibility_from(disabled, "value", backward=lambda v: not v)
                    defaults = [name for name, info in options.items() if info.get("enabled_by_default")]
                    default_note = ui.label(
                        f"Using defaults: {len(defaults)} of {len(options)} enabled ({', '.join(defaults)})."
                    ).classes("text-xs app-muted")
                    default_note.bind_visibility_from(
                        customize, "value", backward=lambda v: not v and not disabled.value
                    )
                    disabled.on_value_change(lambda e: default_note.set_visibility(not e.value and not customize.value))
                    boxes = {}
                    with ui.column().classes("w-full gap-0") as column:
                        for name, info in options.items():
                            with ui.row().classes("w-full items-center gap-2 no-wrap py-1 border-b border-gray-500/10"):
                                boxes[name] = ui.checkbox().props("dense")
                                with ui.column().classes("gap-0 grow"):
                                    ui.label(info.get("description", name)).classes("text-sm")
                                    ui.label(name).classes("text-xs app-muted app-mono")
                                if blocking and info.get("exit_on_failure"):
                                    ui.chip("Blocks upgrade", color="negative").props("dense outline").tooltip(
                                        "A failure halts the upgrade for that device"
                                    )
                                if info.get("enabled_by_default"):
                                    ui.chip("Default").props("dense outline")
                    column.bind_visibility_from(customize, "value", backward=lambda v: v and not disabled.value)
                    disabled.on_value_change(lambda e: column.set_visibility(customize.value and not e.value))
                return disabled, customize, boxes

            checks_disabled, checks_customize, check_boxes = option_section(
                "Readiness checks", "Run before each upgrade", "fact_check", READINESS_CHECKS, blocking=True
            )
            snaps_disabled, snaps_customize, snapshot_boxes = option_section(
                "Snapshots", "Captured before and after each upgrade for the diff report", "photo_camera",
                STATE_SNAPSHOTS, blocking=False
            )

    watched = (
        [element for element, _ in numbers.values()]
        + [log_level, log_path, checks_disabled, checks_customize, snaps_disabled, snaps_customize]
        + list(check_boxes.values()) + list(snapshot_boxes.values())
    )
    state = {"loaded": []}

    def load():
        current = read_settings()

        def get(path: str, default):
            node = current
            for key in path.split("."):
                if not isinstance(node, dict) or key not in node:
                    return default
                node = node[key]
            return default if node is None else node

        for path, (element, default) in numbers.items():
            element.value = get(path, default)
        log_level.value = str(get("logging.level", "INFO")).upper()
        log_path.value = get("logging.file_path", "logs/upgrade.log")
        for section, items_key, disabled, customize, boxes, options in (
            ("readiness_checks", "checks", checks_disabled, checks_customize, check_boxes, READINESS_CHECKS),
            ("snapshots", "state", snaps_disabled, snaps_customize, snapshot_boxes, STATE_SNAPSHOTS),
        ):
            disabled.value = bool(get(f"{section}.disabled", False))
            customize.value = bool(get(f"{section}.customize", False))
            for name, box in boxes.items():
                box.value = bool(get(f"{section}.{items_key}.{name}", options[name].get("enabled_by_default", False)))
        state["loaded"] = [element.value for element in watched]

    def save():
        config = {}
        for path, (element, _) in numbers.items():
            section, key = path.split(".")
            config.setdefault(section, {})[key] = int(element.value or 1)
        config["logging"]["level"] = log_level.value
        config["logging"]["file_path"] = log_path.value or "logs/upgrade.log"

        no_checks = checks_disabled.value
        config["readiness_checks"] = {
            "disabled": no_checks,
            "customize": False if no_checks else checks_customize.value,
            "checks": {n: b.value for n, b in check_boxes.items()} if checks_customize.value and not no_checks else {},
            "location": None if no_checks else "assurance/readiness_checks/",
        }
        no_snaps = snaps_disabled.value
        config["snapshots"] = {
            "disabled": no_snaps,
            "customize": False if no_snaps else snaps_customize.value,
            "state": {n: b.value for n, b in snapshot_boxes.items()} if snaps_customize.value and not no_snaps else {},
            "location": None if no_snaps else "assurance/snapshots/",
            "retry_interval": None if no_snaps else 60,
            "max_tries": None if no_snaps else 3,
        }

        WORKSPACE.mkdir(parents=True, exist_ok=True)
        with open(SETTINGS_PATH, "w") as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=True)
        state["loaded"] = [element.value for element in watched]
        ui.notify(f"Saved {SETTINGS_PATH}", type="positive")

    def refresh():
        dirty = [element.value for element in watched] != state["loaded"]
        unsaved.set_visibility(dirty)
        revert_button.set_enabled(dirty)

    save_button.on_click(save)
    revert_button.on_click(load)
    load()
    ui.timer(1, refresh)
    refresh()


def history_page():
    actions = page_header("Monitoring", "Run history", f"Console output of runs launched from this GUI ({CONSOLE_DIR}).",
                          "history")
    with actions:
        refresh_button = ui.button("Refresh", icon="refresh").props("flat no-caps")

    with ui.element("div").classes("grid grid-cols-1 xl:grid-cols-5 gap-4 w-full items-start"):
        with ui.column().classes("xl:col-span-2 w-full"):
            with card("Runs", "Newest first. Select a run to view its output", icon="list"):
                table = ui.table(
                    rows=console_runs(),
                    columns=[
                        {"name": "started", "label": "Started", "field": "started", "align": "left", "sortable": True},
                        {"name": "command", "label": "Command", "field": "command", "align": "left", "sortable": True},
                        {"name": "size", "label": "Size", "field": "size", "align": "right"},
                    ],
                    row_key="id",
                    selection="single",
                    pagination=12,
                ).props("flat dense").classes("w-full")
        with ui.column().classes("xl:col-span-3 w-full"):
            with card("Selected run", icon="terminal"):
                title = ui.label("No run selected.").classes("text-sm app-muted app-mono")
                with ui.scroll_area().classes("app-terminal w-full h-[50vh]") as scroller:
                    viewer = ui.label().classes("app-mono whitespace-pre-wrap text-xs")

    def show(selection: list[dict]):
        if not selection:
            title.text, viewer.text = "No run selected.", ""
            return
        path = CONSOLE_DIR / selection[0]["id"]
        title.text = str(path)
        viewer.text = ANSI_ESCAPE.sub("", tail(path, 3000))
        scroller.scroll_to(percent=1.0)

    def refresh():
        table.rows = console_runs()
        table.update()

    table.on_select(lambda e: show(e.selection))
    refresh_button.on_click(refresh)


def logs_page():
    page_header("Monitoring", "Logs", "Read-only view of the upgrade log files.", "description")
    with card():
        with ui.row().classes("w-full items-center gap-3"):
            source = ui.select(list(LOG_FILES), value=list(LOG_FILES)[0], label="Log file").props(
                "outlined dense stack-label"
            ).classes("w-96")
            search = ui.input("Filter", placeholder="Show lines containing...").props(
                "outlined dense stack-label clearable"
            ).classes("w-72")
            with search.add_slot("prepend"):
                ui.icon("search")
            ui.space()
            auto = ui.switch("Auto refresh", value=True)
            ui.button("Refresh", icon="refresh", on_click=lambda: refresh(force=True)).props("flat no-caps")
        path_label = ui.label().classes("text-xs app-muted app-mono")
        with ui.scroll_area().classes("app-terminal w-full h-[65vh]") as scroller:
            view = ui.label().classes("app-mono whitespace-pre-wrap text-xs")

    def refresh(force: bool = False):
        path = LOG_FILES[source.value]
        text = tail(path, 2000)
        needle = value(search).lower()
        if needle:
            text = "".join(line for line in text.splitlines(keepends=True) if needle in line.lower())
        path_label.text = str(path)
        if force or text != view.text:
            view.text = text
            scroller.scroll_to(percent=1.0)

    source.on_value_change(lambda: refresh(force=True))
    search.on_value_change(lambda: refresh(force=True))
    ui.timer(5, lambda: auto.value and refresh())
    refresh(force=True)


def guide_page():
    page_header("Help", "HA upgrade guide", f"How the CLI upgrades HA pairs. Source: {GUIDE_PATH}", "menu_book")
    with card():
        ui.markdown(guide_markdown(), extras=["fenced-code-blocks", "tables", "header-ids"]).classes(
            "app-doc w-full max-w-4xl"
        )


# ---------------------------------------------------------------------------
# Shell: header, navigation, output dock
# ---------------------------------------------------------------------------


def output_dock():
    """Collapsible output panel docked at the bottom of every page, like an IDE's terminal."""
    state = {"run_id": None, "seen": 0, "expanded": False, "last_status": None, "prompted": False}

    with ui.footer().classes("app-footer p-0"):
        with ui.column().classes("w-full gap-0"):
            with ui.row().classes("w-full items-center gap-3 px-4 py-2 no-wrap"):
                toggle = ui.button(icon="expand_less", on_click=lambda: set_expanded(not state["expanded"])).props(
                    "flat dense round"
                ).tooltip("Show or hide output")
                ui.label("Output").classes("font-semibold")
                status = ui.chip("Idle", icon="radio_button_unchecked", color="grey-7").props(
                    "dense text-color=white"
                )
                description = ui.label().classes("text-sm truncate min-w-0")
                elapsed = ui.label().classes("text-sm app-muted app-mono shrink-0")
                ui.space()
                copy_path = ui.button(icon="content_copy", on_click=lambda: copy_console_path()).props(
                    "flat dense round"
                ).tooltip("Copy the path of this run's saved output")
                stop_button = ui.button("Stop", icon="stop", color="negative", on_click=lambda: stop()).props(
                    "outline dense no-caps"
                )
            with ui.column().classes("w-full gap-2 px-4 pb-3") as body:
                log = ui.log(max_lines=MAX_CONSOLE_LINES).classes("app-terminal w-full h-72")
                with ui.row().classes("app-prompt w-full items-center gap-2 px-3 py-2 no-wrap") as reply_bar:
                    ui.icon("keyboard", color="accent").classes("text-lg")
                    prompt = ui.label().classes("app-mono text-sm truncate min-w-0 grow")
                    reply = ui.input(placeholder="Reply to prompt").props("dense outlined").classes(
                        "w-80 shrink-0"
                    ).mark("reply")

                    async def send(text: Optional[str] = None):
                        await runner.send(reply.value if text is None else text)
                        reply.value = ""

                    reply.on("keydown.enter", lambda: send())
                    ui.button("Send", icon="send", on_click=lambda: send()).props("unelevated dense no-caps")
                    ui.button("Yes", on_click=lambda: send("y")).props("flat dense no-caps")
                    ui.button("No", on_click=lambda: send("n")).props("flat dense no-caps")
                    ui.button("Done", on_click=lambda: send("done")).props("flat dense no-caps").tooltip(
                        "Finish the device selection prompt"
                    )

    def set_expanded(expanded: bool):
        state["expanded"] = expanded
        body.set_visibility(expanded)
        toggle.props(f"icon={'expand_more' if expanded else 'expand_less'}")

    def copy_console_path():
        if runner.console_path:
            ui.clipboard.write(str(runner.console_path))
            ui.notify("Output file path copied", type="info")

    async def stop():
        with ui.dialog().props("persistent") as dialog, ui.card().props("flat").classes(
            "app-card w-[34rem] max-w-full p-0 gap-0"
        ):
            with ui.row().classes("w-full items-center gap-3 px-5 py-4 no-wrap"):
                ui.icon("stop_circle", color="negative").classes("text-3xl")
                ui.label("Stop the running command?").classes("text-lg font-semibold")
            ui.separator()
            with ui.column().classes("w-full p-5 gap-3"):
                notice(
                    "Interrupting a real upgrade during download, install or reboot can leave devices "
                    "mid-upgrade. A download or install already started on a device keeps running there, "
                    "but the GUI will not reboot it. Check device state afterwards.",
                    "warning",
                    "warning",
                )
                ui.label(
                    "The GUI sends an interrupt, then terminates the process if it has not exited within 10 seconds."
                ).classes("text-sm app-muted")
            ui.separator()
            with ui.row().classes("w-full justify-end gap-2 px-5 py-3"):
                ui.button("Cancel", on_click=lambda: dialog.submit(False)).props("flat no-caps")
                ui.button("Stop", icon="stop", color="negative", on_click=lambda: dialog.submit(True)).props(
                    "unelevated no-caps"
                ).mark("confirm-stop")
        confirmed = await dialog
        dialog.delete()
        if confirmed:
            background_tasks.create(runner.stop())

    def update():
        if state["run_id"] != runner.run_id:
            log.clear()
            state.update(run_id=runner.run_id, seen=0)
            if runner.run_id:
                set_expanded(True)  # open the panel when a new run starts
        # Lines may have been trimmed from the front; re-sync if so
        state["seen"] = min(state["seen"], len(runner.lines))
        for line in runner.lines[state["seen"]:]:
            log.push(line)
        state["seen"] = len(runner.lines)

        label, color, icon = runner.status()
        if state["last_status"] != (label, color, icon):
            state["last_status"] = (label, color, icon)
            status.text = label
            status.props(f"color={color} icon={icon}")
        description.text = runner.description
        elapsed.text = runner.elapsed()
        prompt.text = runner.partial.strip() if runner.awaiting_input else "Waiting for output..."
        reply_bar.set_visibility(runner.running)
        if runner.awaiting_input and not state["prompted"]:
            set_expanded(True)  # never hide a prompt the CLI is blocked on
        state["prompted"] = runner.awaiting_input
        stop_button.set_visibility(runner.running)
        stop_button.set_enabled(not runner.stopping)
        copy_path.set_visibility(runner.console_path is not None)

    set_expanded(False)
    ui.timer(0.5, update)
    update()
    return lambda: set_expanded(True)


@ui.page("/")
def index(page: Optional[str] = None):
    ui.page_title(APP_NAME)
    ui.colors(**THEME)
    ui.add_css(CSS)
    dark = ui.dark_mode(app.storage.general.get("ui.dark", False))

    nav_items = {}
    pages = [key for _, items in NAV for key, _, _ in items]
    # ?page=<name> deep links to a page; otherwise reopen the last page used
    initial = page or app.storage.general.get("ui.page", "firewall")
    if initial not in pages:
        initial = "firewall"

    def navigate(key: str):
        panels.value = key
        app.storage.general["ui.page"] = key
        ui.navigate.history.replace(f"/?page={key}")
        for name, item in nav_items.items():
            item.classes(add="app-nav-active") if name == key else item.classes(remove="app-nav-active")

    def toggle_dark():
        dark.value = not dark.value
        app.storage.general["ui.dark"] = dark.value
        dark_button.props(f"icon={'light_mode' if dark.value else 'dark_mode'}")

    # value=None: open on wide screens, collapsed behind the menu button on narrow ones
    with ui.left_drawer(value=None).props("width=248 breakpoint=1024").classes("p-0") as drawer:
        with ui.column().classes("w-full h-full gap-0 no-wrap"):
            with ui.list().classes("app-nav w-full pt-2"):
                for group, items in NAV:
                    ui.item_label(group).classes("app-overline px-6 pt-4 pb-1")
                    for key, label, icon in items:
                        with ui.item(on_click=lambda k=key: navigate(k)).mark(f"nav-{key}") as item:
                            with ui.item_section().props("avatar").classes("min-w-0 pr-3"):
                                ui.icon(icon).classes("text-xl")
                            with ui.item_section():
                                ui.label(label).classes("text-sm")
                        nav_items[key] = item
            ui.space()
            with ui.column().classes("w-full gap-1 px-6 py-4 border-t border-gray-500/20"):
                ui.label("Environment").classes("app-overline")
                with ui.row().classes("items-center gap-1 no-wrap"):
                    found = CLI_BIN.exists()
                    ui.icon("check_circle" if found else "error", color="positive" if found else "negative").classes(
                        "text-base"
                    )
                    ui.label("CLI available" if found else "CLI not found").classes("text-xs")
                ui.label(str(CLI_BIN)).classes("text-[11px] app-muted app-mono break-all")
                ui.label("Workspace").classes("text-xs mt-2")
                ui.label(str(WORKSPACE)).classes("text-[11px] app-muted app-mono break-all")

    with ui.header().classes("app-header items-center px-3 py-2 gap-3 no-wrap"):
        ui.button(icon="menu", on_click=drawer.toggle).props("flat round dense").tooltip("Toggle navigation")
        with ui.element("div").classes("rounded-md bg-accent p-1.5 flex"):
            ui.icon("system_update_alt", color="white").classes("text-xl")
        with ui.column().classes("gap-0"):
            ui.label(APP_NAME).classes("text-base font-semibold leading-tight")
            ui.label("Firewall and Panorama upgrade orchestration").classes("text-xs app-muted leading-tight")
        ui.space()
        header_status = ui.chip("Idle", icon="radio_button_unchecked", color="grey-7").props(
            "dense clickable text-color=white"
        ).tooltip("Show output")
        dark_button = ui.button(
            icon="light_mode" if dark.value else "dark_mode", on_click=toggle_dark
        ).props("flat round dense").tooltip("Toggle dark mode")

    with ui.column().classes("w-full max-w-screen-2xl mx-auto px-6 py-6 gap-4"):
        external = notice("", "warning", "warning")

        async def check_external():
            found = await run.io_bound(other_cli_processes)
            external.text_label.text = (
                "pan-os-upgrade processes running outside this GUI:\n" + "\n".join(found) if found else ""
            )
            external.set_visibility(bool(found))

        external.set_visibility(False)
        ui.timer(10, check_external)
        background_tasks.create(check_external())

        with ui.tab_panels(value=initial, animated=False).classes("w-full") as panels:
            with ui.tab_panel("firewall"):
                firewall_page(navigate)
            with ui.tab_panel("panorama"):
                panorama_page(navigate)
            with ui.tab_panel("batch"):
                batch_page(navigate)
            with ui.tab_panel("inventory"):
                inventory_page()
            with ui.tab_panel("settings"):
                settings_page()
            with ui.tab_panel("history"):
                history_page()
            with ui.tab_panel("logs"):
                logs_page()
            with ui.tab_panel("guide"):
                guide_page()

    show_output = output_dock()
    header_status.on("click", show_output)

    def update_header_status():
        label, color, icon = runner.status()
        header_status.text = label
        header_status.props(f"color={color} icon={icon}")

    ui.timer(1, update_header_status)
    update_header_status()
    navigate(initial)


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(
        title=APP_NAME,
        host="127.0.0.1",
        port=int(os.environ.get("PAN_OS_GUI_PORT", 8080)),
        reload=False,
        show=True,
    )
