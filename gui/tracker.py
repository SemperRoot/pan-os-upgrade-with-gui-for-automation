"""
Per-device progress tracking for the PAN-OS Upgrade Console.

The CLI upgrades devices in parallel threads, so its console output interleaves every device.
DeviceTracker reads that output line by line and keeps one record per device: HA role, upgrade
round, current stage, versions, whether HA was suspended, warnings and errors, and the device's
own log lines. It only parses text, never talks to devices, and has no third party dependencies,
so it can replay a saved console capture as easily as follow a live run.

Every rule below matches a message the CLI logs (pan_os_upgrade/components/*.py and main.py).
Device lines look like "<emoji> <hostname>: <message>"; at DEBUG level they're prefixed with
"<asctime> - <logger> - <LEVEL> - ".
"""

# standard library imports
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

# Stages in the order a device goes through them. HA suspend is skipped for standalone devices.
STAGES = [
    "Queued",
    "Pre-checks",
    "HA suspend",
    "Download",
    "Snapshot",
    "Readiness",
    "Backup",
    "Install",
    "Reboot",
    "Post-checks",
    "Done",
]

# Stages of a `pan-os-upgrade backup` run
BACKUP_STAGES = ["Queued", "Running config", "Device state", "Done"]

# status key -> (label, Quasar color, icon)
STATUSES = {
    "queued": ("Queued", "grey-7", "schedule"),
    "running": ("In progress", "info", "sync"),
    "deferred": ("Waiting for round 2", "secondary", "hourglass_top"),
    "completed": ("Completed", "positive", "check_circle"),
    "dry_run": ("Dry run complete", "positive", "science"),
    "skipped": ("No upgrade needed", "grey-7", "skip_next"),
    "failed": ("Failed", "negative", "error"),
    "not_upgraded": ("Not upgraded", "warning", "block"),
    "interrupted": ("Interrupted", "warning", "stop_circle"),
}

# Filter groups shown as chips on the tracker page: key -> (label, statuses)
STATUS_GROUPS = {
    "running": ("In progress", {"running"}),
    "waiting": ("Waiting", {"queued", "deferred"}),
    "done": ("Done", {"completed", "dry_run", "skipped"}),
    "attention": ("Needs attention", {"failed", "not_upgraded", "interrupted"}),
}

TERMINAL = {"completed", "dry_run", "skipped", "failed", "not_upgraded", "interrupted"}

DEBUG_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2} [\d:,]+ - \S+ - [A-Z]+ - ")
# "<emoji> <host>: <message>". \S+ is greedy, so an IPv6 host keeps its colons.
DEVICE_LINE = re.compile(r"^([^\x00-\x7F]+)\s+(\S+):\s(.*)$")
# Lines that name the device inside the message instead of as a prefix
HA_SYNC_LINE = re.compile(r"^(?:Waiting for HA synchronization|HA synchronization) .*? on (\S+)\.(?:\s|$)")
# Logged by pan-os-python with the serial number only
SERIAL_LINE = re.compile(r"^Device (\d+) (downloading|installing) version: (\S+)")
# "Please confirm the selected firewalls:" list
SELECTED_LINE = re.compile(r"^\s+- (\S+) \(([^)]*)\)\s*$")
EXCEPTION_LINE = re.compile(r"^(?:Firewall|Panorama) (\S+) generated an exception: (.*)$")

WARNING_EMOJI = "\U0001f7e7"  # 🟧
ERROR_EMOJI = "❌"  # ❌
STOP_EMOJI = "\U0001f6d1"  # 🛑

# (substring, stage) checked in order; the first match sets the device's stage
STAGE_RULES = [
    ("Waiting for the device to become ready for the post upgrade snapshot", "Post-checks"),
    ("Snapshot comparison", "Post-checks"),
    ("Rebooting the target device", "Reboot"),
    ("Retry attempt", None),  # stays in whatever stage it's retrying
    ("Performing upgrade to version", "Install"),
    ("Attempting upgrade to version", "Install"),
    ("Upgrade completed successfully", "Install"),
    ("Performing backup of configuration", "Backup"),
    ("Not a dry run, continue with upgrade", "Backup"),
    ("Checking if HA peer is in sync", "Readiness"),
    ("Performing readiness checks", "Readiness"),
    ("Readiness Check", "Readiness"),
    ("Performing snapshot of network state", "Snapshot"),
    ("network state snapshot", "Snapshot"),
    ("Network snapshot", "Snapshot"),
    ("Performing test to see if", "Download"),
    ("beginning download", "Download"),
    ("Downloading version", "Download"),
    ("downloaded in", "Download"),
    ("has been downloaded", "Download"),
    ("is not on the target device", "Download"),
    ("already on target device", "Download"),
    ("disk space check", "Download"),
    ("Suspending", "HA suspend"),
    ("HA state suspended", "HA suspend"),
]

BACKUP_STAGE_RULES = [
    ("Exporting device state", "Device state"),
    ("Device state saved", "Device state"),
    ("running configuration", "Running config"),
    ("Running configuration", "Running config"),
    ("Configuration export", "Running config"),
]


@dataclass
class Device:
    hostname: str
    ip: str = ""
    serial: str = ""
    role: str = ""  # HA state as reported by the device: active, passive, active-primary, disabled...
    round: int = 1
    status: str = "queued"
    stage: str = "Queued"
    activity: str = ""  # latest message, i.e. what the device is doing right now
    current_version: str = ""
    target_version: str = ""
    peer_version: str = ""
    ha_suspended: bool = False
    rebooted: bool = False
    reached: set = field(default_factory=set)  # stages the device has been through
    warnings: int = 0
    errors: int = 0
    problem: str = ""  # why the device failed or stopped
    reports: list = field(default_factory=list)
    lines: list = field(default_factory=list)
    started: Optional[datetime] = None
    stage_since: Optional[datetime] = None
    updated: Optional[datetime] = None

    @property
    def role_group(self) -> str:
        """active, passive or standalone, for filtering."""
        if not self.role:
            return "unknown"
        if self.role in ("disabled", "standalone"):
            return "standalone"
        return "passive" if "passive" in self.role or self.role == "active-secondary" else "active"


class DeviceTracker:
    """Builds per-device state from the CLI's console output, one line at a time."""

    def __init__(self, kind: str = "upgrade"):
        self.kind = kind  # "upgrade" (firewall, panorama, batch commands) or "backup"
        self.stages = BACKUP_STAGES if kind == "backup" else STAGES
        self.stage_rules = BACKUP_STAGE_RULES if kind == "backup" else STAGE_RULES
        self.devices: dict[str, Device] = {}
        self.controllers: set[str] = set()  # Panorama proxying a batch run; not upgraded itself
        self.serials: dict[str, str] = {}
        self.round = 1
        self.finished = False
        self.version = 0  # bumped on every change, so the UI only redraws when needed

    # ---------------------------------------------------------------- feeding

    def feed(self, line: str, when: Optional[datetime] = None):
        """Process one console line. Pass when for live output; saved captures have no timestamps."""
        text = DEBUG_PREFIX.sub("", line.rstrip())
        if not text.strip():
            return

        selected = SELECTED_LINE.match(text)
        if selected:
            self.controllers.discard(selected.group(1))
            self._device(selected.group(1), when).ip = selected.group(2)
            self.version += 1
            return

        serial = SERIAL_LINE.match(text)
        if serial and serial.group(1) in self.serials:
            device = self.devices.get(self.serials[serial.group(1)])
            if device:
                stage = "Download" if serial.group(2) == "downloading" else "Install"
                self._update(device, stage, f"{serial.group(2).capitalize()} {serial.group(3)}", text, when)
            return

        sync = HA_SYNC_LINE.match(text)
        if sync:
            device = self._device(sync.group(1), when)
            self._update(device, "Pre-checks", text, text, when)
            return

        match = DEVICE_LINE.match(text)
        if not match:
            return
        emoji, host, message = match.groups()
        self._handle(emoji, host, message, text, when)

    def feed_text(self, text: str):
        for line in text.splitlines():
            self.feed(line)

    def finish(self, exit_code: Optional[int] = None, stopped: bool = False):
        """Settle devices the run left mid-way once the process has exited."""
        for device in self.devices.values():
            if device.status in TERMINAL:
                continue
            if device.rebooted and device.current_version == device.target_version:
                device.status, device.stage = "completed", "Done"
            elif device.status == "deferred":
                device.status = "not_upgraded"
                device.problem = device.problem or (
                    "Deferred again in round 2: its HA peer still runs the same version, so the peer wasn't "
                    "upgraded. Check the peer's result." if device.round == 2 else
                    "Round 2 didn't run. A dry run, or another device stopping the run in round 1, "
                    "ends the run before deferred active members are upgraded."
                )
            elif device.status == "queued":
                device.status = "not_upgraded"
                device.problem = device.problem or "The run ended before this device started."
            else:
                device.status = "interrupted"
                device.problem = device.problem or (
                    "The run was stopped during this device's upgrade." if stopped
                    else f"The run ended during {device.stage.lower()}"
                    + (f" (exit code {exit_code})." if exit_code is not None else ".")
                )
        self.finished = True
        self.version += 1

    # ---------------------------------------------------------------- parsing

    def progress(self, device: Device) -> float:
        if device.status in ("completed", "dry_run", "skipped"):
            return 1.0
        return self.stages.index(device.stage) / (len(self.stages) - 1)

    def _device(self, host: str, when: Optional[datetime]) -> Device:
        if host not in self.devices:
            self.devices[host] = Device(hostname=host, started=when, stage_since=when, updated=when)
        return self.devices[host]

    def _handle(self, emoji: str, host: str, message: str, text: str, when: Optional[datetime]):
        if "Firewall connections will be proxied" in message:
            # The batch command's Panorama: run-level messages, not a device being upgraded
            self.controllers.add(host)
            self.devices.pop(host, None)
            self.version += 1
            return
        if self.kind == "backup" and message.startswith("Backing up "):
            # The device list follows. Anything seen before it was connection setup, and the host
            # that logs this line is the one the command connected to, not a backup target
            # unless the list names it.
            self.devices.clear()
            self.controllers.add(host)
            self.version += 1
            return
        if "Revisiting" in message:
            self.round = 2
            for device in self.devices.values():
                if device.status == "deferred":
                    device.round = 2
                    device.activity = "Round 2 started"
            self.version += 1
            return
        exception = EXCEPTION_LINE.match(message)
        if exception:
            device = self._device(exception.group(1), when)
            device.errors += 1
            self._fail(device, f"Exception: {exception.group(2)}")
            self._update(device, None, message, text, when)
            return
        if host in self.controllers:
            return

        device = self._device(host, when)
        if self.round == 2 and device.status in ("deferred", "queued"):
            device.round = 2

        if emoji.startswith(WARNING_EMOJI):
            # Connection retries while the device reboots are expected, not worth flagging
            if not (device.stage == "Reboot" and message.startswith("Retry attempt")):
                device.warnings += 1
        elif emoji.startswith(ERROR_EMOJI) or emoji.startswith(STOP_EMOJI):
            device.errors += 1

        stage = next((s for needle, s in self.stage_rules if needle in message), None)
        if stage == "Readiness" and "Snapshot" not in device.reached:
            # The HA check before suspending, and the disk space check before downloading
            stage = "Download" if "Download" in device.reached else "Pre-checks"
        if stage == "Snapshot" and device.rebooted:
            stage = "Post-checks"
        if stage == "Backup" and device.rebooted:
            stage = "Post-checks"
        if stage is None and device.stage == "Queued":
            stage = self.stages[1]

        self._facts(device, message)
        self._outcome(device, emoji, message)
        self._update(device, stage, message, text, when)

    def _facts(self, device: Device, message: str):
        """Versions, HA role and other details stated in a message."""
        if re.fullmatch(r"\d{6,} .*", message):
            serial = message.split()[0]
            device.serial = serial
            self.serials[serial] = device.hostname
        elif message.startswith("HA mode: "):
            device.role = message.removeprefix("HA mode: ").strip()
        elif message.startswith("Current version: "):
            device.current_version = message.removeprefix("Current version: ").strip()
        elif message.startswith("Current device version: "):
            device.current_version = message.removeprefix("Current device version: ").strip()
        elif message.startswith("Target version: "):
            device.target_version = message.removeprefix("Target version: ").strip()
        elif local := re.match(r"Local state: (\S+), Local version: (\S+), Peer version: (\S+)", message):
            device.role, device.current_version, device.peer_version = local.groups()
        elif upgrade := re.match(r"Upgrade required from (\S+) to (\S+)", message):
            device.current_version, device.target_version = upgrade.groups()
        elif "HA state suspended" in message:
            device.ha_suspended = True
        elif "Device rebooted to the target version successfully" in message:
            device.rebooted = True
        elif "report saved to " in message or (self.kind == "backup" and " saved to " in message):
            # "... saved to <path>" or, for backups, "... saved to <path> (24 KB, export)."
            device.reports.append(message.split(" saved to ", 1)[1].split(" (")[0].strip())

    def _outcome(self, device: Device, emoji: str, message: str):
        """Status changes: deferral, completion and the ways a device stops."""
        if device.role == "suspended" and message.startswith("Version comparison: equal"):
            # handle_firewall_ha has no branch for this state, so the CLI stops here without logging why
            device.status = "not_upgraded"
            device.problem = (
                "HA is already suspended on this device, probably left over from an earlier run, so the CLI "
                "skipped it. Run request high-availability state functional on it, then upgrade it again."
            )
        elif "Added target device to revisit list" in message:
            device.status = "deferred"
            device.stage = "Queued"
        elif "Dry run complete" in message:
            device.status = "dry_run"
        elif "No upgrade required or downgrade attempt detected" in message:
            device.status = "skipped"
            device.problem = "Already on the target version or newer."
        elif message.startswith("Backup completed") or "Snapshot comparison PDF report saved" in message or (
            device.rebooted and "Snapshots are disabled" in message
        ):
            device.status = "completed"
        elif emoji.startswith(STOP_EMOJI) or any(
            needle in message
            for needle in (
                "Not ready for upgrade",
                "Image not downloaded, exiting",
                "Device rebooted but not to the target version",
                "Failed to reboot to the target version",
                "Installation of the target version was not successful",
                "Failed to suspend",
                "Panorama does not have an active license",
                "No IP address found for the peer",
                "Configuration backup failed",
            )
        ):
            # "Halting script." follows the line that explains why; keep the explanation
            if not (message.startswith("Halting script") and device.problem):
                self._fail(device, message)
        elif device.status in ("queued", "deferred") and "revisit" not in message:
            device.status = "running"

    def _fail(self, device: Device, reason: str):
        if device.status in ("completed", "dry_run", "skipped"):
            return
        device.status = "failed"
        device.problem = reason.removesuffix(" Halting script.").strip()

    def _update(self, device: Device, stage: Optional[str], activity: str, text: str, when: Optional[datetime]):
        if device.status in ("queued",) and stage not in (None, "Queued"):
            device.status = "running"
        if stage and device.status not in TERMINAL and stage != device.stage:
            device.stage = stage
            device.stage_since = when
        if stage:
            device.reached.add(stage)
        if device.status == "completed":
            device.stage = "Done"
            device.reached.add("Done")
        device.activity = activity
        device.updated = when
        device.lines.append(text)
        self.version += 1

    # ---------------------------------------------------------------- queries

    def counts(self) -> dict[str, int]:
        counts = {key: 0 for key in STATUSES}
        for device in self.devices.values():
            counts[device.status] += 1
        return counts

    def summary(self) -> str:
        """One line, e.g. "5 devices: 2 in progress, 1 waiting for round 2, 2 completed"."""
        if not self.devices:
            return ""
        parts = [f"{n} {STATUSES[key][0].lower()}" for key, n in self.counts().items() if n]
        return f"{len(self.devices)} devices: " + ", ".join(parts)

    def suspended(self) -> list[str]:
        """Devices this run put into HA suspended state. The CLI never restores them."""
        return [d.hostname for d in self.devices.values() if d.ha_suspended]
