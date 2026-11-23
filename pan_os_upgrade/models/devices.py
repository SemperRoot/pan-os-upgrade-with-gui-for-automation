# Modified from pan-os-upgrade 1.3.11 (https://github.com/cdot65/pan-os-upgrade, Apache License 2.0): a Panorama with no connected devices returns an empty list instead of crashing.
# models/devices.py

from pydantic import BaseModel
from pan_os_upgrade.models.mixins import FromAPIResponseMixin


class ManagedDevice(BaseModel):
    """Single device from output of `show devices all` on panorama"""

    hostname: str
    serial: str
    connected: bool


class ManagedDevices(BaseModel, FromAPIResponseMixin):
    """Output of `show devices all`"""

    devices: list[ManagedDevice]

    @classmethod
    def from_api_response(cls, response: dict):
        # With no devices, Panorama answers with text ("Total Connected Devices: 0") instead of entries
        devices = (response.get("result") or {}).get("devices")
        entries = devices.get("entry") if isinstance(devices, dict) else None
        if isinstance(entries, dict):
            entries = [entries]
        fixed_dict = {"devices": entries or []}
        return cls(**fixed_dict)
