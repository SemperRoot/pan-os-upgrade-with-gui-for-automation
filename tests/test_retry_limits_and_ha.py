"""
Unit tests for the fixes from the November 2026 customer feedback:

- snapshot retries stop after snapshots.max_tries, even when the snapshot returns no data
- a failed or stuck download stops after download.max_tries instead of waiting forever
- HA: the active member is only suspended once its peer can take over, round 2 never defers again,
  dry runs never suspend, a missing peer version defers instead of crashing, and members this run
  suspended are made functional again
- one device stopping with sys.exit() doesn't end the batch, so round 2 runs

No devices are contacted: everything a device would answer is mocked.
"""

import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock
from xml.etree import ElementTree

import pytest

from pan_os_upgrade.components import assurance, ha, upgrade
from pan_os_upgrade.models import SnapshotReport

NO_SETTINGS = Path("/nonexistent/settings.yaml")


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    sleeps = []
    for module in (assurance, ha, upgrade):
        monkeypatch.setattr(module.time, "sleep", lambda seconds: sleeps.append(seconds))
    return sleeps


@pytest.fixture(autouse=True)
def clean_suspended():
    ha._suspended_by_run.clear()
    yield
    ha._suspended_by_run.clear()


# ---------------------------------------------------------------- snapshots


def settings_file(tmp_path, text):
    path = tmp_path / "settings.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_snapshot_returning_nothing_stops_after_max_tries(tmp_path, monkeypatch, no_sleep):
    calls = []
    monkeypatch.setattr(assurance, "run_assurance", lambda **kwargs: calls.append(1))
    path = settings_file(tmp_path, "snapshots:\n  max_tries: 4\n  retry_interval: 7\n")

    result = assurance.perform_snapshot(
        actions=["arp_table"],
        file_path=str(tmp_path / "snap.json"),
        firewall=MagicMock(),
        hostname="fw1",
        settings_file_path=path,
    )

    assert result is None
    assert len(calls) == 4
    assert no_sleep == [7, 7, 7]  # no pause after the last attempt


def test_snapshot_exceptions_also_stop(tmp_path, monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("API timeout")

    monkeypatch.setattr(assurance, "run_assurance", boom)
    path = settings_file(tmp_path, "snapshots:\n  max_tries: 2\n  retry_interval: 1\n")
    assert assurance.perform_snapshot(
        actions=["arp_table"], file_path=str(tmp_path / "s.json"), firewall=MagicMock(), hostname="fw1",
        settings_file_path=path,
    ) is None


def test_snapshot_success_after_a_failure(tmp_path, monkeypatch):
    report = SnapshotReport(hostname="fw1")
    results = iter([None, report])
    monkeypatch.setattr(assurance, "run_assurance", lambda **kwargs: next(results))
    path = settings_file(tmp_path, "snapshots:\n  max_tries: 3\n  retry_interval: 1\n")
    out = tmp_path / "snap.json"

    assert assurance.perform_snapshot(
        actions=["arp_table"], file_path=str(out), firewall=MagicMock(), hostname="fw1", settings_file_path=path,
    ) is report
    assert out.exists()


def test_snapshots_disabled(tmp_path):
    assert assurance.snapshots_disabled(settings_file(tmp_path, "snapshots:\n  disabled: true\n"))
    assert not assurance.snapshots_disabled(NO_SETTINGS)


def test_readiness_checks_disabled_returns_empty_list(tmp_path):
    path = settings_file(tmp_path, "readiness_checks:\n  disabled: true\n")
    assert assurance.get_checks_list(settings_file_path=path) == []


# ---------------------------------------------------------------- download


def xml(text):
    return ElementTree.fromstring(text)


def fake_device(downloaded_after_polls=None, job_result=None, job_details=""):
    """A device whose download finishes after N polls, or whose download job ends with job_result."""
    device = MagicMock()
    device.id = "0001"
    state = {"polls": 0}
    device.software.versions = {"11.1.6": {"downloaded": False}}

    def info():
        state["polls"] += 1
        if downloaded_after_polls is not None and state["polls"] >= downloaded_after_polls:
            device.software.versions["11.1.6"]["downloaded"] = True

    device.software.info.side_effect = info

    def op(cmd, *args, **kwargs):
        if cmd.startswith("request system software download"):
            return xml("<response status='success'><result><job>42</job></result></response>")
        if cmd.startswith("show jobs id"):
            if job_result:
                return xml(
                    f"<response><result><job><status>FIN</status><result>{job_result}</result>"
                    f"<details><line>{job_details}</line></details></job></result></response>"
                )
            return xml("<response><result><job><status>ACT</status><result>PEND</result></job></result></response>")
        raise AssertionError(cmd)

    device.op.side_effect = op
    return device


def test_download_succeeds():
    device = fake_device(downloaded_after_polls=3)
    assert upgrade.software_download(device, "fw1", "11.1.6", {}, NO_SETTINGS) is True


def test_failed_download_job_stops_after_max_tries(tmp_path, monkeypatch, no_sleep):
    monkeypatch.setattr(upgrade, "get_checks_list", lambda settings_file_path: [])
    device = fake_device(job_result="FAIL", job_details="Not enough disk space")
    path = settings_file(tmp_path, "download:\n  max_tries: 2\n  retry_interval: 5\n")

    assert upgrade.software_download(device, "fw1", "11.1.6", {}, path) is False
    requests = [c for c in device.op.call_args_list if c.args[0].startswith("request system software download")]
    assert len(requests) == 2
    assert 5 in no_sleep


def test_stuck_download_times_out(tmp_path, monkeypatch):
    monkeypatch.setattr(upgrade, "get_checks_list", lambda settings_file_path: [])
    clock = {"now": 0}
    monkeypatch.setattr(upgrade.time, "time", lambda: clock["now"])
    monkeypatch.setattr(upgrade.time, "sleep", lambda s: clock.__setitem__("now", clock["now"] + s))
    device = fake_device()  # never finishes, job stays active
    path = settings_file(tmp_path, "download:\n  max_tries: 1\n  timeout: 120\n")

    assert upgrade.software_download(device, "fw1", "11.1.6", {}, path) is False
    assert clock["now"] <= 200


def test_download_already_present_skips_request():
    device = fake_device()
    device.software.versions["11.1.6"]["downloaded"] = True
    assert upgrade.software_download(device, "fw1", "11.1.6", {}, NO_SETTINGS) is True
    device.op.assert_not_called()


# ---------------------------------------------------------------- HA


def fw_ha(local_state, local_version, peer_state, peer_version, sync="synchronized"):
    peer = {}
    if peer_state:
        peer["state"] = peer_state
    if peer_version:
        peer["build-rel"] = peer_version
    return {
        "result": {
            "enabled": "yes",
            "group": {
                "local-info": {"state": local_state, "build-rel": local_version},
                "peer-info": peer,
                "running-sync": sync,
            },
        }
    }


@pytest.fixture
def ha_env(monkeypatch):
    """Patch device calls in ha.py; returns the suspend mocks and a setter for the HA details."""
    env = {"details": None}
    monkeypatch.setattr(ha, "get_ha_status", lambda hostname, target_device: ("active", env["details"]))
    monkeypatch.setattr(ha, "get_checks_list", lambda settings_file_path: [])
    monkeypatch.setattr(ha, "perform_readiness_checks", MagicMock())
    env["active"] = MagicMock(return_value=True)
    env["passive"] = MagicMock(return_value=True)
    monkeypatch.setattr(ha, "suspend_ha_active", env["active"])
    monkeypatch.setattr(ha, "suspend_ha_passive", env["passive"])
    return env


def handle(device, revisit, dry_run=False):
    return ha.handle_firewall_ha(
        dry_run=dry_run,
        hostname="fw1",
        settings_file=None,
        settings_file_path=NO_SETTINGS,
        target_device=device,
        target_devices_to_revisit=revisit,
        target_devices_to_revisit_lock=threading.Lock(),
    )


def test_same_version_active_is_deferred(ha_env):
    ha_env["details"] = fw_ha("active", "10.2.10", "passive", "10.2.10")
    device, revisit = MagicMock(), []
    assert handle(device, revisit) == (False, None)
    assert revisit == [device]


def test_round_two_same_version_active_fails_instead_of_deferring_again(ha_env):
    ha_env["details"] = fw_ha("active", "10.2.10", "passive", "10.2.10")
    device = MagicMock()
    revisit = [device]
    with pytest.raises(SystemExit):
        handle(device, revisit)
    assert revisit == [device]
    ha_env["active"].assert_not_called()


def test_round_two_dry_run_continues(ha_env):
    ha_env["details"] = fw_ha("active", "10.2.10", "passive", "10.2.10")
    device = MagicMock()
    assert handle(device, [device], dry_run=True) == (True, None)


def test_active_not_suspended_while_peer_is_suspended_round_one(ha_env):
    ha_env["details"] = fw_ha("active", "10.2.10", "suspended", "11.1.6")
    device, revisit = MagicMock(), []
    assert handle(device, revisit) == (False, None)
    assert revisit == [device]
    ha_env["active"].assert_not_called()


def test_active_not_suspended_while_peer_is_suspended_round_two(ha_env):
    ha_env["details"] = fw_ha("active", "10.2.10", "suspended", "11.1.6", sync="not synchronized")
    device = MagicMock()
    with pytest.raises(SystemExit):
        handle(device, [device])
    ha_env["active"].assert_not_called()


def test_active_suspended_once_peer_is_passive(ha_env):
    ha_env["details"] = fw_ha("active", "10.2.10", "passive", "11.1.6")
    assert handle(MagicMock(), []) == (True, None)
    ha_env["active"].assert_called_once()


def test_dry_run_never_suspends_active_or_passive(ha_env):
    ha_env["details"] = fw_ha("active", "10.2.10", "passive", "11.1.6")
    assert handle(MagicMock(), [], dry_run=True) == (True, None)
    ha_env["details"] = fw_ha("passive", "11.1.6", "active", "10.2.10")
    assert handle(MagicMock(), [], dry_run=True) == (True, None)
    ha_env["active"].assert_not_called()
    ha_env["passive"].assert_not_called()


def test_missing_peer_version_defers_instead_of_crashing(ha_env):
    ha_env["details"] = fw_ha("active", "10.2.10", None, None)
    device, revisit = MagicMock(), []
    assert handle(device, revisit) == (False, None)
    assert revisit == [device]


def test_failed_passive_suspension_stops(ha_env):
    ha_env["details"] = fw_ha("passive", "10.2.10", "active", "10.2.10")
    ha_env["passive"].return_value = False
    with pytest.raises(SystemExit):
        handle(MagicMock(), [])


def test_already_suspended_member_stops_with_reason(ha_env):
    ha_env["details"] = fw_ha("suspended", "10.2.10", "active", "10.2.10")
    with pytest.raises(SystemExit):
        handle(MagicMock(), [])


def suspend_response():
    return xml("<response status='success'><result>Successfully changed HA state to suspended</result></response>")


def test_suspension_is_recorded_and_restored(monkeypatch):
    device = MagicMock()
    device.serial = "0001"
    device.op.return_value = suspend_response()
    assert ha.suspend_ha_passive(device, "fw1")
    assert ha.suspended_by_run(device)

    device.op.return_value = xml(
        "<response status='success'><result>Successfully changed HA state to functional</result></response>"
    )
    assert ha.restore_ha_functional(device, "fw1") is True
    assert not ha.suspended_by_run(device)
    assert "functional" in device.op.call_args.args[0]


def test_restore_does_nothing_for_devices_this_run_did_not_suspend():
    device = MagicMock()
    device.serial = "0002"
    assert ha.restore_ha_functional(device, "fw2") is True
    device.op.assert_not_called()


def test_restore_retries_then_reports_failure(monkeypatch):
    device = MagicMock()
    device.serial = "0003"
    ha._suspended_by_run.add("0003")
    device.op.side_effect = RuntimeError("not connected")
    monkeypatch.setattr(ha, "get_ha_status", lambda hostname, target_device: ("active", None))
    assert ha.restore_ha_functional(device, "fw3") is False
    assert device.op.call_count == 3
    assert ha.suspended_by_run(device)


# ---------------------------------------------------------------- batch rounds


def test_device_exit_does_not_end_the_batch(monkeypatch):
    from pan_os_upgrade import main

    monkeypatch.setattr(main, "stopped_devices", [])

    def work(code):
        if code is not None:
            sys.exit(code)

    with ThreadPoolExecutor(3) as executor:
        futures = {}
        for name, code in (("fw-fail", 1), ("fw-dry", 0), ("fw-ok", None)):
            device = MagicMock()
            device.serial = name
            futures[executor.submit(work, code)] = device
        main.wait_for_upgrades(futures, "panorama", "Firewall")  # must not raise SystemExit

    assert main.stopped_devices == ["fw-fail"]
    with pytest.raises(SystemExit):
        main.exit_if_any_stopped("panorama")


# ---------------------------------------------------------------- Panorama with no firewalls, secrets


def test_panorama_with_no_connected_devices_returns_empty_list():
    from pan_os_upgrade.models import ManagedDevices

    response = {"result": {"devices": "Total Connected Devices: 0\n"}}
    assert ManagedDevices.from_api_response(response).devices == []
    one = {"result": {"devices": {"entry": {"hostname": "fw1", "serial": "1", "connected": "yes"}}}}
    assert [d.hostname for d in ManagedDevices.from_api_response(one).devices] == ["fw1"]


def test_no_connected_firewalls_stops_cleanly():
    from pan_os_upgrade import main

    with pytest.raises(SystemExit):
        main.require_connected_firewalls([], "panorama")
    main.require_connected_firewalls([MagicMock()], "panorama")


def test_error_tracebacks_never_show_local_variables():
    # Typer's default prints every local variable, including the password typed at the prompt
    from pan_os_upgrade import main

    assert main.app.pretty_exceptions_show_locals is False
