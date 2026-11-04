import importlib.util
from pathlib import Path

import pytest

# gui/ isn't a package and its dependencies live in a separate virtual environment;
# tracker.py only uses the standard library, so load it straight from its path
_spec = importlib.util.spec_from_file_location(
    "gui_tracker", Path(__file__).resolve().parent.parent / "gui" / "tracker.py"
)
tracker = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tracker)

# Excerpt of a batch run: an HA pair (fw-a passive, fw-b active) plus a standalone firewall
BATCH_HEADER = """\
🚀 panorama.example.com: Connection to the appliance successful.
✅ panorama.example.com: Connection to Panorama established. Firewall connections will be proxied!
📝 panorama.example.com: Please confirm the selected firewalls:
  - fw-a (10.0.0.1)
  - fw-b (10.0.0.2)
  - fw-c (10.0.0.3)
🔧 panorama.example.com: Using 10 threads.
📝 fw-a: 000000000001 None
📝 fw-b: 000000000002 None
📝 fw-c: 000000000003 None
📝 fw-a: HA mode: passive
📝 fw-b: HA mode: active
📝 fw-c: HA mode: disabled
✅ fw-a: Upgrade required from 11.2.13 to 11.2.16-h1
✅ fw-b: Upgrade required from 11.2.13 to 11.2.16-h1
✅ fw-c: Upgrade required from 11.2.15 to 11.2.16-h1
✅ fw-a: Base image for 11.2.16-h1 is already downloaded
📝 fw-a: Local state: passive, Local version: 11.2.13, Peer version: 11.2.13
📝 fw-b: Local state: active, Local version: 11.2.13, Peer version: 11.2.13
🔍 fw-b: Detected active target device in HA pair running the same version as its peer. Added target device to revisit list.
🚀 fw-a: Performing pre-upgrade HA status check.
🚀 fw-a: Performing readiness checks of target firewall.
📝 fw-a: Suspending HA state of passive or active-secondary
✅ fw-a: Passive target device HA state suspended.
🚀 fw-c: version 11.2.16-h1 is beginning download
Device 000000000003 downloading version: 11.2.16-h1
"""

PASSIVE_UPGRADE = """\
🚀 fw-a: Performing snapshot of network state information.
🚀 fw-a: Performing readiness checks of target firewall.
🟧 fw-a: HA peer state is not in sync. This will be noted, but the script will continue.
🚀 fw-a: Performing upgrade to version 11.2.16-h1.
✅ fw-a: Upgrade completed successfully
🚀 fw-a: Rebooting the target device.
🟧 fw-a: Retry attempt 1 due to error: 000000000001 not connected
📝 fw-a: Current device version: 11.2.16-h1
✅ fw-a: Device rebooted to the target version successfully.
🚀 fw-a: Performing snapshot of network state information.
💾 fw-a: Snapshot comparison PDF report saved to assurance/snapshots/fw-a/diff/report.pdf
"""


def run(text, finish=True, **kwargs):
    t = tracker.DeviceTracker()
    t.feed_text(text)
    if finish:
        t.finish(**kwargs)
    return t


def test_batch_run_in_progress():
    t = run(BATCH_HEADER, finish=False)

    # Panorama only proxies the batch run; it isn't tracked as a device
    assert list(t.devices) == ["fw-a", "fw-b", "fw-c"]
    assert t.controllers == {"panorama.example.com"}

    fw_a, fw_b, fw_c = t.devices["fw-a"], t.devices["fw-b"], t.devices["fw-c"]
    assert (fw_a.ip, fw_a.serial, fw_a.role_group) == ("10.0.0.1", "000000000001", "passive")
    assert fw_a.status == "running" and fw_a.stage == "HA suspend" and fw_a.ha_suspended
    assert fw_b.status == "deferred" and fw_b.role_group == "active"
    # The serial-only pan-os-python line is attributed through the serial number
    assert fw_c.role_group == "standalone" and fw_c.stage == "Download"
    assert fw_c.activity == "Downloading 11.2.16-h1"
    assert t.suspended() == ["fw-a"]


def test_round_two_and_completion():
    round_two = """\
🚀 panorama.example.com: Revisiting firewalls that were active in an HA pair and had the same version as their peers.
📝 fw-b: Local state: active, Local version: 11.2.13, Peer version: 11.2.16-h1
Waiting for HA synchronization to complete on fw-b. Attempt 1/3
"""
    t = run(BATCH_HEADER + PASSIVE_UPGRADE + round_two, finish=False)

    fw_a, fw_b = t.devices["fw-a"], t.devices["fw-b"]
    assert fw_a.status == "completed" and fw_a.stage == "Done"
    assert fw_a.reports == ["assurance/snapshots/fw-a/diff/report.pdf"]
    # Connection retries during the reboot are expected and not counted
    assert fw_a.warnings == 1
    assert t.round == 2
    assert fw_b.round == 2 and fw_b.status == "running" and fw_b.peer_version == "11.2.16-h1"
    assert fw_b.activity.startswith("Waiting for HA synchronization")


def test_round_one_failure_leaves_active_member_not_upgraded():
    failure = (
        "🛑 fw-a: [FAIL] Pending changes found on device.: Check if there are pending changes on device. "
        "Test has `exit_on_failure` flag set. Halting script.\n"
    )
    t = run(BATCH_HEADER + failure, exit_code=0)

    fw_a, fw_b, fw_c = t.devices["fw-a"], t.devices["fw-b"], t.devices["fw-c"]
    assert fw_a.status == "failed" and fw_a.problem.startswith("[FAIL] Pending changes")
    assert fw_b.status == "not_upgraded" and "Round 2 didn't run" in fw_b.problem
    assert fw_c.status == "interrupted"
    assert t.counts()["failed"] == 1


def test_member_already_suspended_is_reported():
    log = """\
📝 fw-d: HA mode: suspended
📝 fw-d: Local state: suspended, Local version: 11.2.13, Peer version: 11.2.13
📝 fw-d: Version comparison: equal
"""
    device = run(log, finish=False).devices["fw-d"]
    assert device.status == "not_upgraded"
    assert "request high-availability state functional" in device.problem


@pytest.mark.parametrize(
    "line, status",
    [
        ("🟨 fw-a: No upgrade required or downgrade attempt detected.", "skipped"),
        ("✅ fw-a: Dry run complete, exiting.", "dry_run"),
        ("❌ fw-a: Not ready for upgrade to 11.2.16-h1.", "failed"),
        ("❌ fw-a: Device rebooted but not to the target version.", "failed"),
    ],
)
def test_terminal_outcomes(line, status):
    assert run(line + "\n", finish=False).devices["fw-a"].status == status


def test_debug_format_and_fqdn_hosts():
    log = (
        "2026-11-03 15:24:50,123 - root - INFO - 📝 fw1.example.com: HA mode: passive\n"
        "HA synchronization complete on fw1.example.com. Proceeding with upgrade.\n"
    )
    t = run(log, finish=False)
    assert list(t.devices) == ["fw1.example.com"]
    assert t.devices["fw1.example.com"].role == "passive"


def test_backup_run():
    log = """\
🚀 10.0.0.1: Connection to the appliance successful.
📝 10.0.0.1: Backing up 2 devices. Please confirm the selected firewalls:
  - fw-a (10.0.0.1)
  - fw-b (10.0.0.2)
🔧 10.0.0.1: Using 10 threads.
🚀 fw-a: Exporting running configuration.
💾 fw-a: Running configuration saved to assurance/backups/fw-a/ts/running-config.xml (24 KB, export).
🚀 fw-a: Exporting device state.
✅ fw-a: Backup completed.
🚀 fw-b: Exporting running configuration.
❌ fw-b: Configuration backup failed: timed out
📝 10.0.0.1: Backup summary: 1 succeeded, 1 failed.
"""
    t = tracker.DeviceTracker(kind="backup")
    t.feed_text(log)
    t.finish(exit_code=1)

    # The connected host isn't a backup target unless the device list names it
    assert list(t.devices) == ["fw-a", "fw-b"]
    fw_a, fw_b = t.devices["fw-a"], t.devices["fw-b"]
    assert fw_a.status == "completed" and t.progress(fw_a) == 1.0
    assert fw_a.reports == ["assurance/backups/fw-a/ts/running-config.xml"]
    assert fw_b.status == "failed" and fw_b.stage == "Running config"
    assert fw_b.problem == "Configuration backup failed: timed out"
