import xml.etree.ElementTree as ET

import pytest
from panos.firewall import Firewall
from panos.panorama import Panorama

from pan_os_upgrade.components.backup import _describe_export_response, backup_device, check_config_xml

FIREWALL_CONFIG = (
    '<config version="11.2.0"><devices><entry name="localhost.localdomain"><deviceconfig><system>'
    "<hostname>fw1</hostname></system></deviceconfig><vsys/></entry></devices>"
    "<mgt-config><users><entry name=\"admin\"><phash>$5$abc</phash></entry></users></mgt-config></config>"
)
MASKED_FIREWALL_CONFIG = FIREWALL_CONFIG.replace("$5$abc", "********")
PANORAMA_CONFIG = (
    '<config version="11.2.0"><devices><entry name="localhost.localdomain"><device-group/></entry></devices>'
    "<panorama/></config>"
)


class FakeXapi:
    """Stands in for pan.xapi.PanXapi: export returns raw XML, show wraps it in a response."""

    def __init__(self, export_xml=None, show_xml=None, export_error=None, state=None, serial=None):
        self.serial = serial
        self._export_xml = export_xml
        self._show_xml = show_xml
        self._export_error = export_error
        self._state = state
        self.export_calls = []
        self.export_result = None
        self.xml_document = None
        self.element_root = None

    def export(self, category=None, extra_qs=None):
        self.export_calls.append((category, extra_qs))
        if self._export_error:
            raise self._export_error
        if category == "device-state":
            self.export_result = {"content": self._state}
            self.xml_document = None
        else:
            self.export_result = None
            self.xml_document = self._export_xml

    def show(self, xpath=None):
        self.element_root = ET.fromstring(f'<response status="success"><result>{self._show_xml}</result></response>')


def device(cls, xapi):
    target = cls("fw1" if cls is Firewall else "panorama1")
    target._xapi_private = xapi
    return target


def test_direct_export(tmp_path):
    xapi = FakeXapi(export_xml=FIREWALL_CONFIG)
    result = backup_device(device(Firewall, xapi), "fw1", str(tmp_path))

    assert result.success and result.masked_values == 0
    assert (tmp_path / "running-config.xml").read_text() == FIREWALL_CONFIG
    # A directly connected firewall gets no target parameter
    assert xapi.export_calls == [("configuration", None)]


def test_export_through_panorama_sends_target(tmp_path):
    xapi = FakeXapi(export_xml=FIREWALL_CONFIG, serial="007900000001")
    assert backup_device(device(Firewall, xapi), "fw1", str(tmp_path)).success
    assert xapi.export_calls == [("configuration", {"target": "007900000001"})]


def test_panorama_config_is_never_saved_as_a_firewall(tmp_path):
    # The export reached Panorama itself; fall back to the configuration API, which honors target
    xapi = FakeXapi(export_xml=PANORAMA_CONFIG, show_xml=MASKED_FIREWALL_CONFIG, serial="007900000001")
    result = backup_device(device(Firewall, xapi), "fw1", str(tmp_path))

    assert result.success and result.masked_values == 1
    assert "<panorama" not in (tmp_path / "running-config.xml").read_text()


def test_export_error_falls_back_to_config_api(tmp_path):
    xapi = FakeXapi(export_error=RuntimeError("not supported"), show_xml=FIREWALL_CONFIG)
    assert backup_device(device(Firewall, xapi), "fw1", str(tmp_path)).success


def test_both_methods_wrong_device_fails(tmp_path):
    xapi = FakeXapi(export_xml=PANORAMA_CONFIG, show_xml=PANORAMA_CONFIG)
    result = backup_device(device(Firewall, xapi), "fw1", str(tmp_path))

    assert not result.success and "Panorama's configuration" in result.error
    assert not (tmp_path / "running-config.xml").exists()


@pytest.mark.parametrize(
    "state, saved, reason",
    [
        (b"\x1f\x8b\x08rest-of-tgz", True, ""),
        (b"not a tgz", False, "9 bytes that aren't a .tgz bundle"),
        (None, False, "an empty response"),
    ],
)
def test_device_state(tmp_path, state, saved, reason):
    xapi = FakeXapi(export_xml=FIREWALL_CONFIG, state=state)
    result = backup_device(device(Firewall, xapi), "fw1", str(tmp_path), device_state=True)

    # The running configuration is kept even when the device state export fails
    assert result.success and (tmp_path / "running-config.xml").exists()
    assert (tmp_path / "device-state.tgz").exists() is saved
    assert result.device_state_error == (f"it returned {reason}" if reason else "")


def test_panorama_backup_expects_panorama_config(tmp_path):
    xapi = FakeXapi(export_xml=PANORAMA_CONFIG)
    result = backup_device(device(Panorama, xapi), "panorama1", str(tmp_path), device_state=True)

    # Device state is a firewall export; it's skipped for Panorama
    assert result.success and [c for c, _ in xapi.export_calls] == ["configuration"]


def test_check_config_xml_warnings():
    error, warnings = check_config_xml(MASKED_FIREWALL_CONFIG, "fw2", expect_panorama=False)
    assert error is None
    assert any("local hostname is fw1" in w for w in warnings)
    assert any("1 values are masked" in w for w in warnings)
    assert check_config_xml("<response/>", "fw1", expect_panorama=False)[0]
    assert check_config_xml("not xml", "fw1", expect_panorama=False)[0]


def test_describe_export_response():
    error = '<response status="error"><msg><line>Command not supported via Panorama</line></msg></response>'
    assert _describe_export_response(None, error) == '<response status="error"> Command not supported via Panorama'
    assert _describe_export_response(None, FIREWALL_CONFIG) == "a configuration file instead of a .tgz bundle"


def test_device_state_through_panorama_explains_the_limit(tmp_path):
    xapi = FakeXapi(export_xml=FIREWALL_CONFIG, serial="007900000001")
    xapi._state = None
    original = xapi.export

    def export(category=None, extra_qs=None):
        original(category, extra_qs)
        if category == "device-state":
            xapi.xml_document = (
                '<response status="success"><result>Device state device_state_cfg.tgz created successfully'
                "</result></response>"
            )

    xapi.export = export
    result = backup_device(device(Firewall, xapi), "fw1", str(tmp_path), device_state=True)
    assert result.success
    assert "Panorama doesn't relay file downloads" in result.device_state_error


# Direct backups

from pan_os_upgrade.components.backup import (  # noqa: E402
    backup_device_direct,
    connect_direct,
    load_management_addresses,
    parse_addresses_option,
)


def test_management_addresses(tmp_path):
    inventory = tmp_path / "inventory.yaml"
    assert load_management_addresses(inventory) == {}
    inventory.write_text("firewalls_to_upgrade: [fw1]\nmanagement_addresses:\n  fw1: 203.0.113.10\n")
    assert load_management_addresses(inventory) == {"fw1": "203.0.113.10"}
    assert parse_addresses_option(" fw1=203.0.113.10, fw2=fw2.example.com ") == {
        "fw1": "203.0.113.10",
        "fw2": "fw2.example.com",
    }
    with pytest.raises(ValueError):
        parse_addresses_option("fw1")


@pytest.mark.parametrize(
    "system, error",
    [
        ({"hostname": "fw1", "model": "PA-VM"}, None),
        ({"hostname": "fw2", "model": "PA-VM"}, "answered as 'fw2', not 'fw1'"),
        ({"hostname": "fw1", "model": "Panorama"}, "is a Panorama appliance"),
    ],
)
def test_connect_direct_checks_the_device(monkeypatch, system, error):
    def show_system_info(self):
        # The real call creates the API client; give it a fake one so nothing touches the network
        self._xapi_private = FakeXapi()
        return {"system": system}

    monkeypatch.setattr(Firewall, "show_system_info", show_system_info)
    if error:
        with pytest.raises(RuntimeError, match=error):
            connect_direct("fw1", "203.0.113.10", "admin", "secret")
    else:
        firewall = connect_direct("fw1", "203.0.113.10", "admin", "secret", command_timeout=90)
        assert firewall.hostname == "203.0.113.10" and firewall.xapi.timeout == 90


def test_direct_connection_failure_is_one_failed_device(monkeypatch, tmp_path):
    def refuse(self):
        raise Exception("Invalid credentials.")

    monkeypatch.setattr(Firewall, "show_system_info", refuse)
    result = backup_device_direct("fw1", "203.0.113.10", "admin", "wrong", str(tmp_path))
    assert not result.success
    assert "same username and password on every firewall" in result.error
