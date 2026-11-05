"""
Standalone configuration backups, taken independently of an upgrade.

The upgrade workflow saves `show config running` output to assurance/configurations/, but only late
in the upgrade and only for devices that get that far. This module takes the backup on its own, with
the XML API export (the same export as Device > Setup > Operations > Export named configuration
snapshot), falling back to the configuration API.

Going through Panorama has two limits, seen on PAN-OS 11.2:
- The running configuration export comes back identical to `show config running`, with local
  administrator password hashes masked as ********. Each backup reports how many values are masked.
- Device state can't be downloaded: the firewall creates device_state_cfg.tgz, but Panorama doesn't
  relay the file. Device state is therefore only exported from firewalls connected directly.

Direct backups (`backup --direct`) connect to each firewall's management interface instead, using
the addresses in the `management_addresses` section of inventory.yaml and one set of credentials
for every firewall.
"""


# standard library imports
import logging
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

# third party imports
import yaml

# Palo Alto Networks imports
from panos.firewall import Firewall
from panos.panorama import Panorama

# project imports
from pan_os_upgrade.components.utilities import ensure_directory_exists, get_emoji

# PAN-OS replaces secrets it won't disclose with this placeholder
MASKED_VALUE = "********"


@dataclass
class BackupResult:
    hostname: str
    success: bool = False
    files: List[str] = field(default_factory=list)
    masked_values: int = 0
    error: str = ""  # the running configuration couldn't be saved
    device_state_error: str = ""  # the running configuration was saved, the requested device state wasn't


def check_config_xml(
    xml_text: str,
    hostname: str,
    expect_panorama: bool,
) -> Tuple[Optional[str], List[str]]:
    """
    Check that exported XML is a complete configuration of the expected device type.

    Returns (error, warnings). error is None when the configuration can be saved.

    The export API doesn't pass Panorama's `target` parameter on by itself, so a request meant for
    a managed firewall can silently return Panorama's own configuration. Rejecting a Panorama
    configuration when a firewall was expected keeps that from being saved under the firewall's name.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        return f"Exported data isn't valid XML: {e}", []
    if root.tag != "config":
        return f"Exported data isn't a configuration (root element <{root.tag}>).", []

    is_panorama = root.find("panorama") is not None or root.find("./devices/entry/device-group") is not None
    if is_panorama and not expect_panorama:
        return "The export returned Panorama's configuration instead of the firewall's.", []
    if expect_panorama and not is_panorama:
        return "The export didn't return a Panorama configuration.", []

    warnings = []
    local_hostname = root.findtext("./devices/entry/deviceconfig/system/hostname")
    if local_hostname and local_hostname != hostname:
        # Can be legitimate when a Panorama template overrides the local hostname
        warnings.append(f"The configuration's local hostname is {local_hostname}, not {hostname}.")
    masked = xml_text.count(MASKED_VALUE)
    if masked:
        warnings.append(
            f"{masked} values are masked ({MASKED_VALUE}) in this backup, for example local administrator "
            "password hashes. After restoring it, those values must be re-entered."
        )
    return None, warnings


def _export(target_device: Union[Firewall, Panorama], category: str) -> Tuple[Optional[bytes], str]:
    """
    Run a type=export API request against the device. Returns (content, xml_document).

    Firewalls managed by Panorama are reached through Panorama: their API client carries the
    firewall's serial number, which op and config requests send as `target`, but export requests
    don't, so it's added here.
    """
    xapi = target_device.xapi
    serial = getattr(xapi, "serial", None)
    xapi.export(category=category, extra_qs={"target": serial} if serial else None)
    content = (xapi.export_result or {}).get("content")
    return content, xapi.xml_document or ""


def _describe_export_response(content: Optional[bytes], xml_document: str) -> str:
    """Say what an export returned instead of the expected file, without dumping its contents."""
    if content:
        return f"{len(content)} bytes that aren't a .tgz bundle"
    if not xml_document.strip():
        return "an empty response"
    try:
        root = ET.fromstring(xml_document)
    except ET.ParseError:
        return f"non-XML text: {xml_document.strip()[:150]}"
    if root.tag == "config":
        return "a configuration file instead of a .tgz bundle"
    message = " ".join(" ".join(root.itertext()).split())[:200]
    return f"<{root.tag} status=\"{root.get('status', '')}\"> {message}".rstrip()


def _show_running_config(target_device: Union[Firewall, Panorama]) -> str:
    """Running configuration through the configuration API (type=config&action=show)."""
    xapi = target_device.xapi
    xapi.show(xpath="/config")
    config = xapi.element_root.find("./result/config")
    if config is None:
        raise RuntimeError("the configuration API returned no <config> element")
    return ET.tostring(config, encoding="unicode")


def export_running_config(
    target_device: Union[Firewall, Panorama],
    hostname: str,
) -> Tuple[str, str, List[str]]:
    """
    Get the device's running configuration as checked XML. Returns (xml_text, method, warnings).

    Tries the export API first. If that fails or returns the wrong configuration, for example on a
    PAN-OS version or Panorama proxy path that doesn't support it, falls back to the configuration
    API, which returns the running configuration but may mask secrets.
    """
    expect_panorama = type(target_device) is Panorama
    try:
        content, xml_document = _export(target_device, "configuration")
        xml_text = content.decode("utf-8") if content else xml_document
        error, warnings = check_config_xml(xml_text, hostname, expect_panorama)
        if not error:
            return xml_text, "export", warnings
        logging.warning(f"{get_emoji(action='warning')} {hostname}: {error} Trying the configuration API.")
    except Exception as e:
        logging.warning(
            f"{get_emoji(action='warning')} {hostname}: Configuration export failed ({e}). Trying the configuration API."
        )

    xml_text = _show_running_config(target_device)
    error, warnings = check_config_xml(xml_text, hostname, expect_panorama)
    if error:
        raise RuntimeError(error)
    return xml_text, "config API", warnings


def backup_device(
    target_device: Union[Firewall, Panorama],
    hostname: str,
    directory: str,
    device_state: bool = False,
) -> BackupResult:
    """
    Save the running configuration, and optionally the device state, to `directory`.

    Parameters
    ----------
    target_device : Union[Firewall, Panorama]
        The device to back up. Firewalls managed by Panorama may be reached through Panorama.
    hostname : str
        The device's hostname, used in log messages and to check the exported configuration.
    directory : str
        Folder for this device's backup files, for example assurance/backups/<hostname>/<timestamp>.
    device_state : bool
        Also export the device state bundle: the configuration pushed by Panorama plus the
        certificates. Only for firewalls connected directly, not through Panorama.

    Returns
    -------
    BackupResult
        Whether the backup succeeded, the files written, and any error.
    """
    result = BackupResult(hostname=hostname)
    is_panorama = type(target_device) is Panorama
    if device_state and (is_panorama or getattr(target_device.xapi, "serial", None)):
        raise ValueError("device state is only exported from firewalls connected directly, not through Panorama")

    try:
        logging.info(f"{get_emoji(action='start')} {hostname}: Exporting running configuration.")
        xml_text, method, warnings = export_running_config(target_device, hostname)

        file_path = os.path.join(directory, "running-config.xml")
        ensure_directory_exists(file_path=file_path)
        with open(file_path, "w", encoding="utf-8") as file:
            file.write(xml_text)
        result.files.append(file_path)
        result.masked_values = xml_text.count(MASKED_VALUE)
        logging.info(
            f"{get_emoji(action='save')} {hostname}: Running configuration saved to {file_path} "
            f"({len(xml_text.encode('utf-8')) // 1024} KB, {method})."
        )
        for warning in warnings:
            logging.warning(f"{get_emoji(action='warning')} {hostname}: {warning}")

    except Exception as e:
        result.error = str(e)
        logging.error(f"{get_emoji(action='error')} {hostname}: Configuration backup failed: {e}")
        return result

    result.success = True
    if device_state:
        # A failure here doesn't undo the running configuration backup already saved
        try:
            logging.info(f"{get_emoji(action='start')} {hostname}: Exporting device state.")
            content, xml_document = _export(target_device, "device-state")
            if not content or content[:2] != b"\x1f\x8b":
                raise RuntimeError(f"it returned {_describe_export_response(content, xml_document)}")
            state_path = os.path.join(directory, "device-state.tgz")
            with open(state_path, "wb") as file:
                file.write(content)
            result.files.append(state_path)
            logging.info(
                f"{get_emoji(action='save')} {hostname}: Device state saved to {state_path} ({len(content) // 1024} KB)."
            )
        except Exception as e:
            result.device_state_error = str(e)
            logging.warning(f"{get_emoji(action='warning')} {hostname}: Device state export failed: {e}")

    logging.info(f"{get_emoji(action='success')} {hostname}: Backup completed.")
    return result


def load_management_addresses(inventory_path: Path) -> Dict[str, str]:
    """
    The `management_addresses` section of inventory.yaml: firewall hostname -> address of its
    management interface (IP or DNS name) reachable from where the CLI runs, for example:

        management_addresses:
          fw-a: 203.0.113.10
          fw-b: fw-b-mgmt.example.com
    """
    if not inventory_path.exists():
        return {}
    with open(inventory_path, "r") as file:
        addresses = (yaml.safe_load(file) or {}).get("management_addresses") or {}
    return {str(name): str(address) for name, address in addresses.items()}


def parse_addresses_option(value: str) -> Dict[str, str]:
    """Parse --addresses "fw-a=203.0.113.10,fw-b=203.0.113.11"."""
    addresses = {}
    for item in filter(None, (part.strip() for part in value.split(","))):
        name, separator, address = item.partition("=")
        if not separator or not name.strip() or not address.strip():
            raise ValueError(f"expected hostname=address, got {item!r}")
        addresses[name.strip()] = address.strip()
    return addresses


def connect_direct(
    hostname: str,
    address: str,
    username: str,
    password: str,
    connection_timeout: int = 30,
    command_timeout: int = 120,
) -> Firewall:
    """
    Connect to a firewall's management interface and check it's the firewall named `hostname`.

    Raises instead of exiting like connect_to_host, so one unreachable firewall doesn't stop the
    others. The hostname check keeps a wrong address in inventory.yaml from saving one firewall's
    configuration under another's name.
    """
    firewall = Firewall(hostname=address, api_username=username, api_password=password, timeout=connection_timeout)
    try:
        system = firewall.show_system_info()["system"]
    except Exception as e:
        message = str(e)
        if "credential" in message.lower() or "403" in message:
            message += ". Direct backups use the same username and password on every firewall."
        raise RuntimeError(f"couldn't connect to {address}: {message}") from e

    model = str(system.get("model", ""))
    if model == "Panorama" or model.startswith("M-"):
        raise RuntimeError(f"{address} is a Panorama appliance ({model}), not a firewall")
    if system.get("hostname") != hostname:
        raise RuntimeError(
            f"{address} answered as {system.get('hostname')!r}, not {hostname!r}. "
            "Check management_addresses in inventory.yaml."
        )
    # Exports, device state especially, can take longer than connecting
    firewall.timeout = command_timeout
    firewall.xapi.timeout = command_timeout
    return firewall


def backup_device_direct(
    hostname: str,
    address: str,
    username: str,
    password: str,
    directory: str,
    device_state: bool = False,
    connection_timeout: int = 30,
    command_timeout: int = 120,
) -> BackupResult:
    """Connect to the firewall's management interface at `address`, then run backup_device."""
    logging.info(f"{get_emoji(action='start')} {hostname}: Connecting directly to {address}.")
    try:
        firewall = connect_direct(hostname, address, username, password, connection_timeout, command_timeout)
    except Exception as e:
        logging.error(f"{get_emoji(action='error')} {hostname}: Configuration backup failed: {e}")
        return BackupResult(hostname=hostname, error=str(e))
    return backup_device(firewall, hostname, directory, device_state)
