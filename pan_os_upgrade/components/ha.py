# Modified from pan-os-upgrade 1.3.11 (https://github.com/cdot65/pan-os-upgrade, Apache License 2.0): HA members this run suspends are made functional again after their upgrade (or when it stops); an active member is only suspended once its peer is passive and can take over; a missing peer version or state defers the device to round 2 instead of crashing; round 2 stops with a clear error instead of deferring again; failed suspensions stop the upgrade; dry runs never suspend.
import logging
import sys
import time
from threading import Lock
from typing import Optional, Tuple, Union
from panos.firewall import Firewall
from panos.panorama import Panorama

from dynaconf import LazySettings
from pathlib import Path
from pan_os_upgrade.components.device import get_ha_status
from pan_os_upgrade.components.utilities import (
    compare_versions,
    flatten_xml_to_dict,
    get_emoji,
)
from pan_os_upgrade.components.assurance import (
    perform_readiness_checks,
    get_checks_list,
)


# HA states in which a peer can take over traffic when this member is suspended
PEER_READY_STATES = ("passive", "active-secondary")

# Devices whose HA state this run suspended, so the same thread can make them functional again once
# their upgrade ends, whether it succeeded or stopped. Keyed by device_key().
_suspended_by_run: set = set()
_suspended_by_run_lock = Lock()


def device_key(target_device: Union[Firewall, Panorama]) -> str:
    """Identify a device across calls: its serial number, or the address used to reach it."""
    return str(
        getattr(target_device, "serial", None)
        or getattr(target_device, "hostname", None)
        or id(target_device)
    )


def suspended_by_run(target_device: Union[Firewall, Panorama]) -> bool:
    """True if this run suspended the device's HA state and hasn't restored it yet."""
    with _suspended_by_run_lock:
        return device_key(target_device) in _suspended_by_run


def firewall_ha_states(ha_details: Optional[dict]) -> Tuple[Optional[str], ...]:
    """
    Local state, local version, peer state and peer version from a firewall's HA details.

    Values the firewall doesn't report are None. peer-info has no version or state while the peer
    is rebooting or HA1 is down, so the keys can't be read directly.
    """
    group = ((ha_details or {}).get("result") or {}).get("group") or {}
    local = group.get("local-info") or {}
    peer = group.get("peer-info") or {}
    return local.get("state"), local.get("build-rel"), peer.get("state"), peer.get("build-rel")


def panorama_ha_states(ha_details: Optional[dict]) -> Tuple[Optional[str], ...]:
    """Local state, local version, peer state and peer version from a Panorama's HA details."""
    result = (ha_details or {}).get("result") or {}
    local = result.get("local-info") or {}
    peer = result.get("peer-info") or {}
    return local.get("state"), local.get("build-rel"), peer.get("state"), peer.get("build-rel")


def ha_retry_settings(settings_file: LazySettings, settings_file_path: Path) -> Tuple[int, int]:
    """ha_sync.max_tries and ha_sync.retry_interval from settings.yaml, defaulting to 3 and 60 seconds."""
    max_retries, retry_interval = 3, 60
    if settings_file_path is not None and settings_file_path.exists() and settings_file is not None:
        max_retries = settings_file.get("ha_sync.max_tries", max_retries)
        retry_interval = settings_file.get("ha_sync.retry_interval", retry_interval)
    return max(1, int(max_retries)), max(0, int(retry_interval))


def defer_to_round_two(
    hostname: str,
    reason: str,
    target_device: Union[Firewall, Panorama],
    target_devices_to_revisit: list,
    target_devices_to_revisit_lock: Lock,
) -> None:
    """Put a device on the revisit list so the batch command upgrades it after round 1 finishes."""
    with target_devices_to_revisit_lock:
        if target_device not in target_devices_to_revisit:
            target_devices_to_revisit.append(target_device)
    logging.info(
        f"{get_emoji(action='search')} {hostname}: Waiting for round 2 because {reason}. Added target device to revisit list."
    )


def restore_ha_functional(
    target_device: Union[Firewall, Panorama],
    hostname: str,
    settings_file: LazySettings = None,
    settings_file_path: Path = None,
) -> bool:
    """
    Make a device's HA state functional again if this run suspended it.

    Suspended HA survives a reboot, so without this an upgraded member stays suspended: it never
    rejoins the pair, HA links stay down, and its peer can't fail over to it when its own turn comes.
    Called after the reboot and whenever an upgrade stops after suspending. Does nothing for devices
    this run didn't suspend.

    Retries ha_sync.max_tries times, ha_sync.retry_interval seconds apart, since HA may still be
    starting right after a reboot. Returns True if HA is functional (or was never suspended).
    """
    if not suspended_by_run(target_device):
        return True

    max_retries, retry_interval = ha_retry_settings(settings_file, settings_file_path)
    logging.info(
        f"{get_emoji(action='start')} {hostname}: Restoring HA state to functional (this run suspended it)."
    )

    for attempt in range(1, max_retries + 1):
        result = ""
        try:
            response = target_device.op(
                "<request><high-availability><state><functional/></state></high-availability></request>",
                cmd_xml=False,
            )
            result = str(flatten_xml_to_dict(response).get("result", ""))
        except Exception as error:
            result = f"error: {error}"

        if "functional" in result.lower() and "error" not in result.lower():
            with _suspended_by_run_lock:
                _suspended_by_run.discard(device_key(target_device))
            logging.info(
                f"{get_emoji(action='success')} {hostname}: HA state restored to functional."
            )
            return True

        # The command can fail when HA isn't suspended any more; check before retrying
        try:
            _, ha_details = get_ha_status(hostname=hostname, target_device=target_device)
            group = ((ha_details or {}).get("result") or {})
            local = (group.get("group") or group).get("local-info") or {}
            state = local.get("state")
        except Exception:
            state = None
        if state and "suspended" not in state and state not in ("initial", "unknown"):
            with _suspended_by_run_lock:
                _suspended_by_run.discard(device_key(target_device))
            logging.info(
                f"{get_emoji(action='success')} {hostname}: HA state restored to functional ({state})."
            )
            return True

        if attempt < max_retries:
            logging.warning(
                f"{get_emoji(action='warning')} {hostname}: Couldn't restore HA state to functional yet (attempt {attempt} of {max_retries}: {result or state}). Retrying in {retry_interval} seconds."
            )
            time.sleep(retry_interval)

    logging.error(
        f"{get_emoji(action='error')} {hostname}: Failed to restore HA state to functional after {max_retries} attempts. Run request high-availability state functional on it."
    )
    return False


def ha_sync_check_firewall(
    ha_details: dict,
    hostname: str,
    strict_sync_check: bool = False,
) -> bool:
    """
    Checks the synchronization status between High Availability (HA) peers of a Palo Alto Networks device.

    Ensuring HA peers are synchronized is vital before executing operations that might impact the device's state,
    such as firmware upgrades or configuration changes. This function evaluates the HA synchronization status using
    provided HA details. It offers an option to enforce a strict synchronization check, where failure to sync
    results in script termination, ensuring operations proceed only in a fully synchronized HA environment.

    Parameters
    ----------
    hostname : str
        The hostname or IP address of the target device, used for logging purposes to identify the device under evaluation.
    ha_details : dict
        A dictionary containing HA information for the device, specifically the synchronization status with its HA peer.
    strict_sync_check : bool, optional
        If True (default), the function will exit the script upon detecting unsynchronized HA peers to prevent potential
        disruptions. If False, the script logs a warning but continues execution, suitable for less critical operations.

    Returns
    -------
    bool
        Returns True if the HA peers are confirmed to be synchronized, indicating readiness for sensitive operations.
        Returns False if the HA peers are not synchronized, with subsequent actions dependent on the `strict_sync_check` parameter.

    Raises
    ------
    SystemExit
        Triggered if `strict_sync_check` is True and the HA peers are found to be unsynchronized, halting the script to avoid
        potential issues in an unsynchronized HA environment.

    Example
    -------
    >>> ha_details = {'result': {'group': {'running-sync': 'synchronized'}}}
    >>> ha_sync_check_firewall('firewall1', ha_details)
    True  # Indicates that the HA peers are synchronized

    >>> ha_sync_check_firewall('firewall1', ha_details, strict_sync_check=False)
    False  # HA peers are unsynchronized, but script continues due to lenient check

    Notes
    -----
    - In HA configurations, maintaining synchronization between peers is critical to ensure consistent state and behavior
    across devices.
    - This function is particularly useful in automated workflows and scripts where actions need to be conditional on the
    synchronization state of HA peers to maintain system integrity and prevent split-brain scenarios.
    - The option to override strict synchronization checks allows for flexibility in operations where immediate consistency
    between HA peers may not be as critical.
    """

    logging.info(
        f"{get_emoji(action='start')} {hostname}: Checking if HA peer is in sync."
    )
    if ha_details and ha_details["result"]["group"]["running-sync"] == "synchronized":
        logging.info(
            f"{get_emoji(action='success')} {hostname}: HA peer sync test has been completed."
        )
        return True
    else:
        if strict_sync_check:
            logging.error(
                f"{get_emoji(action='error')} {hostname}: HA peer state is not in sync, please try again."
            )
            logging.error(f"{get_emoji(action='stop')} {hostname}: Halting script.")
            sys.exit(1)
        else:
            logging.warning(
                f"{get_emoji(action='warning')} {hostname}: HA peer state is not in sync. This will be noted, but the script will continue."
            )
            return False


def ha_sync_check_panorama(
    ha_details: dict,
    hostname: str,
    strict_sync_check: bool = False,
) -> bool:
    """
    Checks the synchronization status between High Availability (HA) peers of a Palo Alto Networks device.

    Ensuring HA peers are synchronized is vital before executing operations that might impact the device's state,
    such as firmware upgrades or configuration changes. This function evaluates the HA synchronization status using
    provided HA details. It offers an option to enforce a strict synchronization check, where failure to sync
    results in script termination, ensuring operations proceed only in a fully synchronized HA environment.

    Parameters
    ----------
    hostname : str
        The hostname or IP address of the target device, used for logging purposes to identify the device under evaluation.
    ha_details : dict
        A dictionary containing HA information for the device, specifically the synchronization status with its HA peer.
    strict_sync_check : bool, optional
        If True (default), the function will exit the script upon detecting unsynchronized HA peers to prevent potential
        disruptions. If False, the script logs a warning but continues execution, suitable for less critical operations.

    Returns
    -------
    bool
        Returns True if the HA peers are confirmed to be synchronized, indicating readiness for sensitive operations.
        Returns False if the HA peers are not synchronized, with subsequent actions dependent on the `strict_sync_check` parameter.

    Raises
    ------
    SystemExit
        Triggered if `strict_sync_check` is True and the HA peers are found to be unsynchronized, halting the script to avoid
        potential issues in an unsynchronized HA environment.

    Example
    -------
    >>> ha_details = {'result': {'group': {'running-sync': 'synchronized'}}}
    >>> ha_sync_check_firewall('firewall1', ha_details)
    True  # Indicates that the HA peers are synchronized

    >>> ha_sync_check_firewall('firewall1', ha_details, strict_sync_check=False)
    False  # HA peers are unsynchronized, but script continues due to lenient check

    Notes
    -----
    - In HA configurations, maintaining synchronization between peers is critical to ensure consistent state and behavior
    across devices.
    - This function is particularly useful in automated workflows and scripts where actions need to be conditional on the
    synchronization state of HA peers to maintain system integrity and prevent split-brain scenarios.
    - The option to override strict synchronization checks allows for flexibility in operations where immediate consistency
    between HA peers may not be as critical.
    """

    logging.info(
        f"{get_emoji(action='start')} {hostname}: Checking if HA peer is in sync."
    )
    if ha_details and ha_details["result"]["running-sync"] == "synchronized":
        logging.info(
            f"{get_emoji(action='success')} {hostname}: HA peer sync test has been completed."
        )
        return True
    else:
        if strict_sync_check:
            logging.error(
                f"{get_emoji(action='error')} {hostname}: HA peer state is not in sync, please try again."
            )
            logging.error(f"{get_emoji(action='stop')} {hostname}: Halting script.")
            sys.exit(1)
        else:
            logging.warning(
                f"{get_emoji(action='warning')} {hostname}: HA peer state is not in sync. This will be noted, but the script will continue."
            )
            return False


def handle_firewall_ha(
    dry_run: bool,
    hostname: str,
    settings_file: LazySettings,
    settings_file_path: Path,
    target_device: Firewall,
    target_devices_to_revisit,
    target_devices_to_revisit_lock,
) -> Tuple[bool, Optional[Firewall]]:
    """
    Determines and handles High Availability (HA) logic for the target device during the upgrade process.

    This function assesses the HA configuration of the specified target device to decide the appropriate course of action for
    the upgrade. It considers the device's role in an HA setup (active, passive, or standalone) and uses the 'dry_run' flag to
    determine whether to simulate or execute the upgrade. Based on the device's HA status and synchronization state with its
    HA peer, the function guides whether to proceed with the upgrade and performs HA-specific preparations if necessary.

    Parameters
    ----------
    target_device: Firewall
        The device being evaluated for upgrade. It must be an instance of Firewall and might be part of
        an HA configuration.
    hostname : str
        The hostname or IP address of the target device for identification and logging purposes.
    dry_run : bool
        A flag indicating whether to simulate the upgrade process (True) without making actual changes or to proceed with
        the upgrade (False).

    Returns
    -------
    Tuple[bool, Optional[Firewall]]
        A tuple where the first element is a boolean indicating whether the upgrade process should continue, and the second
        element is an optional device instance representing the HA peer if relevant and applicable.

    Example
    -------
    >>> firewall = Firewall(hostname='192.168.1.1', api_username='admin', api_password='admin')
    >>> proceed, ha_peer = handle_firewall_ha(firewall, '192.168.1.1', dry_run=False)
    >>> print(proceed)  # Indicates whether the upgrade should continue
    >>> if ha_peer:
    ...     print(ha_peer)  # The HA peer device instance if applicable

    Notes
    -----
    - This function is crucial for managing the upgrade process in HA environments to ensure consistency and minimize
    downtime.
    - It incorporates checks for synchronization states and versions between HA peers, ensuring upgrades are conducted
    safely and effectively.
    - The 'dry_run' option allows administrators to validate the upgrade logic without impacting the actual device
    configuration or operation.
    - Settings such as retry counts and intervals for HA synchronization checks can be customized via the 'settings.yaml'
    file, providing flexibility for different network environments and requirements.
    """

    deploy_info, ha_details = get_ha_status(
        hostname=hostname,
        target_device=target_device,
    )

    # Get selected checks
    selected_checks = get_checks_list(settings_file_path=settings_file_path)

    # If the target device is not part of an HA configuration, proceed with the upgrade
    if not ha_details:
        return True, None

    logging.debug(
        f"{get_emoji(action='report')} {hostname}: Deployment info: {deploy_info}"
    )
    logging.debug(f"{get_emoji(action='report')} {hostname}: HA details: {ha_details}")

    local_state, local_version, peer_state, peer_version = firewall_ha_states(ha_details)

    logging.info(
        f"{get_emoji(action='report')} {hostname}: Local state: {local_state}, Local version: {local_version}, Peer version: {peer_version}"
    )
    logging.info(f"{get_emoji(action='report')} {hostname}: HA peer state: {peer_state}")

    # Check if the firewall is in the revisit list
    with target_devices_to_revisit_lock:
        is_device_to_revisit = target_device in target_devices_to_revisit

    max_retries, retry_interval = ha_retry_settings(settings_file, settings_file_path)

    if is_device_to_revisit:
        for attempt in range(max_retries):
            logging.info(
                f"Waiting for HA synchronization to complete on {hostname}. Attempt {attempt + 1}/{max_retries}"
            )
            # Wait for HA synchronization
            time.sleep(retry_interval)

            # Re-fetch the HA status to get the latest state
            deploy_info, ha_details = get_ha_status(
                hostname=hostname,
                target_device=target_device,
            )
            local_state, local_version, peer_state, peer_version = firewall_ha_states(
                ha_details
            )

            running_sync = (ha_details or {}).get("result", {}).get("group", {}).get("running-sync")
            if running_sync == "synchronized" or (
                peer_state in PEER_READY_STATES and peer_version != local_version
            ):
                logging.info(
                    f"HA synchronization complete on {hostname}. Proceeding with upgrade."
                )
                break
            else:
                logging.info(
                    f"HA synchronization still in progress on {hostname}. Rechecking after wait period."
                )

        logging.info(
            f"{get_emoji(action='report')} {hostname}: Local state: {local_state}, Local version: {local_version}, Peer version: {peer_version}"
        )
        logging.info(f"{get_emoji(action='report')} {hostname}: HA peer state: {peer_state}")

    # The peer is rebooting, down, or HA1 is disconnected, so its version and state are unknown
    if not peer_version or not local_version:
        if is_device_to_revisit:
            logging.error(
                f"{get_emoji(action='error')} {hostname}: HA peer not ready: its version and state still aren't available in round 2. Not upgrading this firewall. Check the HA pair, then run it again."
            )
            sys.exit(1)
        defer_to_round_two(
            hostname=hostname,
            reason="its HA peer isn't reporting a version or state (it may be rebooting)",
            target_device=target_device,
            target_devices_to_revisit=target_devices_to_revisit,
            target_devices_to_revisit_lock=target_devices_to_revisit_lock,
        )
        return False, None

    version_comparison = compare_versions(
        version1=local_version,
        version2=peer_version,
    )
    logging.info(
        f"{get_emoji(action='report')} {hostname}: Version comparison: {version_comparison}"
    )

    # If the firewall and its peer devices are running the same version
    if version_comparison == "equal":

        # if the current device is active or active-primary
        if local_state == "active" or local_state == "active-primary":

            if is_device_to_revisit:
                if dry_run:
                    # The peer's dry run didn't upgrade it, so the versions still match. Finish the
                    # dry run checks on this firewall instead of deferring it forever.
                    logging.info(
                        f"{get_emoji(action='report')} {hostname}: Its HA peer still runs {peer_version} because this is a dry run. In a real run the peer is upgraded first. Continuing the dry run."
                    )
                    return True, None
                logging.error(
                    f"{get_emoji(action='error')} {hostname}: HA peer not upgraded: the peer still runs {peer_version}, so it wasn't upgraded in round 1 (it failed, or it isn't in this run's inventory). Not upgrading this active firewall. Upgrade the peer first, then run this firewall again."
                )
                sys.exit(1)

            # Add the target device to the revisit list and exit the upgrade process
            with target_devices_to_revisit_lock:
                target_devices_to_revisit.append(target_device)

            # log message to console
            logging.info(
                f"{get_emoji(action='search')} {hostname}: Detected active target device in HA pair running the same version as its peer. Added target device to revisit list."
            )

            # Exit the upgrade process for the target device at this time, to be revisited later
            return False, None

        # if the current device is passive or active-secondary
        elif local_state == "passive" or local_state == "active-secondary":

            # suspend HA state of the target device
            if not dry_run:
                if any(
                    check == "ha" or (isinstance(check, dict) and "ha" in check)
                    for check in selected_checks
                ):
                    logging.info(
                        f"{get_emoji(action='start')} {hostname}: Performing pre-upgrade HA status check."
                    )
                    perform_readiness_checks(
                        file_path=f'assurance/readiness_checks/{hostname}/pre/ha_{time.strftime("%Y-%m-%d_%H-%M-%S")}.json',
                        firewall=target_device,
                        hostname=hostname,
                        checks=["ha"],
                    )

                logging.info(
                    f"{get_emoji(action='report')} {hostname}: Suspending HA state of passive or active-secondary"
                )
                if not suspend_ha_passive(
                    target_device,
                    hostname,
                ):
                    logging.error(
                        f"{get_emoji(action='error')} {hostname}: Failed to suspend HA state, so the upgrade stops here before making changes."
                    )
                    sys.exit(1)

            # log message to console
            else:
                logging.info(
                    f"{get_emoji(action='report')} {hostname}: Target device is passive, but we are in dry-run mode. Skipping HA state suspension.",
                )

            # Continue with upgrade process on the passive target device
            return True, None

        elif local_state == "initial":
            # Continue with upgrade process on the initial target device
            logging.info(
                f"{get_emoji(action='warning')} {hostname}: Target device is in initial HA state",
            )
            return True, None

        else:
            # suspended, non-functional, tentative...: the upgrade doesn't know which member should
            # carry traffic, so it leaves the pair alone
            logging.error(
                f"{get_emoji(action='error')} {hostname}: HA state is {local_state}, so the CLI won't upgrade it. If it was left suspended, run request high-availability state functional on it, then run it again."
            )
            sys.exit(1)

    elif version_comparison == "older":
        logging.info(
            f"{get_emoji(action='report')} {hostname}: Target device is on an older version"
        )
        # Suspend HA state of active if the passive is on a later release
        if local_state == "active" or local_state == "active-primary":

            # Suspending the active fails traffic over to the peer, so the peer must be able to take it.
            # A peer that's still suspended from its own upgrade would leave neither member active.
            if peer_state not in PEER_READY_STATES:
                if dry_run:
                    logging.warning(
                        f"{get_emoji(action='warning')} {hostname}: HA peer is {peer_state}. A real run wouldn't suspend this active firewall until the peer is passive. Continuing the dry run."
                    )
                    return True, None
                if is_device_to_revisit:
                    logging.error(
                        f"{get_emoji(action='error')} {hostname}: HA peer not ready: the peer is {peer_state}, so it can't take over traffic. Not suspending this active firewall. Make the peer functional (request high-availability state functional), then run this firewall again."
                    )
                    sys.exit(1)
                defer_to_round_two(
                    hostname=hostname,
                    reason=f"its HA peer is {peer_state} and can't take over traffic yet",
                    target_device=target_device,
                    target_devices_to_revisit=target_devices_to_revisit,
                    target_devices_to_revisit_lock=target_devices_to_revisit_lock,
                )
                return False, None

            if not dry_run:
                if any(
                    check == "ha" or (isinstance(check, dict) and "ha" in check)
                    for check in selected_checks
                ):
                    logging.info(
                        f"{get_emoji(action='start')} {hostname}: Performing pre-upgrade HA status check."
                    )
                    perform_readiness_checks(
                        file_path=f'assurance/readiness_checks/{hostname}/pre/ha_{time.strftime("%Y-%m-%d_%H-%M-%S")}.json',
                        firewall=target_device,
                        hostname=hostname,
                        checks=["ha"],
                    )
                logging.info(
                    f"{get_emoji(action='report')} {hostname}: Suspending HA state of active or active-primary"
                )
                if not suspend_ha_active(
                    target_device,
                    hostname,
                ):
                    logging.error(
                        f"{get_emoji(action='error')} {hostname}: Failed to suspend HA state, so the upgrade stops here before making changes."
                    )
                    sys.exit(1)
            else:
                logging.info(
                    f"{get_emoji(action='report')} {hostname}: Target device is active, but we are in dry-run mode. Skipping HA state suspension.",
                )
        return True, None

    elif version_comparison == "newer":
        logging.info(
            f"{get_emoji(action='report')} {hostname}: Target device is on a newer version"
        )
        # Suspend HA state of passive if the active is on a later release
        if (
            local_state == "passive" or local_state == "active-secondary"
        ) and not dry_run:
            if any(
                check == "ha" or (isinstance(check, dict) and "ha" in check)
                for check in selected_checks
            ):
                logging.info(
                    f"{get_emoji(action='start')} {hostname}: Performing pre-upgrade HA status check."
                )
                perform_readiness_checks(
                    file_path=f'assurance/readiness_checks/{hostname}/pre/ha_{time.strftime("%Y-%m-%d_%H-%M-%S")}.json',
                    firewall=target_device,
                    hostname=hostname,
                    checks=["ha"],
                )
            logging.info(
                f"{get_emoji(action='report')} {hostname}: Suspending HA state of passive or active-secondary"
            )
            if not suspend_ha_passive(
                target_device,
                hostname,
            ):
                logging.error(
                    f"{get_emoji(action='error')} {hostname}: Failed to suspend HA state, so the upgrade stops here before making changes."
                )
                sys.exit(1)
        return True, None

    logging.error(
        f"{get_emoji(action='error')} {hostname}: Couldn't compare its version ({local_version}) with its HA peer's ({peer_version}). Not upgrading it."
    )
    sys.exit(1)


def handle_panorama_ha(
    dry_run: bool,
    hostname: str,
    settings_file: LazySettings,
    settings_file_path: Path,
    target_device: Panorama,
    target_devices_to_revisit: list,
    target_devices_to_revisit_lock: Lock,
) -> Tuple[bool, Optional[Panorama]]:
    """
    Determines and handles High Availability (HA) logic for the Panorama device during the upgrade process.

    This function assesses the HA configuration of the specified Panorama device to decide the appropriate course of action for
    the upgrade. It considers the device's role in an HA setup (primary-active, secondary-passive) and uses the 'dry_run' flag to
    determine whether to simulate or execute the upgrade. Based on the device's HA status and synchronization state with its
    HA peer, the function guides whether to proceed with the upgrade and performs HA-specific preparations if necessary.

    Parameters
    ----------
    target_device: Panorama
        The device being evaluated for upgrade. It must be an instance of Panorama and might be part of
        an HA configuration.
    hostname : str
        The hostname or IP address of the target device for identification and logging purposes.
    dry_run : bool
        A flag indicating whether to simulate the upgrade process (True) without making actual changes or to proceed with
        the upgrade (False).

    Returns
    -------
    Tuple[bool, Optional[Panorama]]
        A tuple where the first element is a boolean indicating whether the upgrade process should continue, and the second
        element is an optional device instance representing the HA peer if relevant and applicable.

    Example
    -------
    >>> panorama = Panorama(hostname='192.168.1.1', api_username='admin', api_password='admin')
    >>> proceed, ha_peer = handle_panorama_ha(firewall, '192.168.1.1', dry_run=False)
    >>> print(proceed)  # Indicates whether the upgrade should continue
    >>> if ha_peer:
    ...     print(ha_peer)  # The HA peer device instance if applicable

    Notes
    -----
    - This function is crucial for managing the upgrade process in HA environments to ensure consistency and minimize
    downtime.
    - It incorporates checks for synchronization states and versions between HA peers, ensuring upgrades are conducted
    safely and effectively.
    - The 'dry_run' option allows administrators to validate the upgrade logic without impacting the actual device
    configuration or operation.
    - Settings such as retry counts and intervals for HA synchronization checks can be customized via the 'settings.yaml'
    file, providing flexibility for different network environments and requirements.
    """

    deploy_info, ha_details = get_ha_status(
        hostname=hostname,
        target_device=target_device,
    )

    # If the target device is not part of an HA configuration, proceed with the upgrade
    if not ha_details:
        return True, None

    logging.debug(
        f"{get_emoji(action='report')} {hostname}: Deployment info: {deploy_info}"
    )
    logging.debug(f"{get_emoji(action='report')} {hostname}: HA details: {ha_details}")

    local_state, local_version, peer_state, peer_version = panorama_ha_states(ha_details)

    logging.info(
        f"{get_emoji(action='report')} {hostname}: Local state: {local_state}, Local version: {local_version}, Peer version: {peer_version}"
    )
    logging.info(f"{get_emoji(action='report')} {hostname}: HA peer state: {peer_state}")

    # Check if the firewall is in the revisit list
    with target_devices_to_revisit_lock:
        is_device_to_revisit = target_device in target_devices_to_revisit

    max_retries, retry_interval = ha_retry_settings(settings_file, settings_file_path)

    if is_device_to_revisit:
        for attempt in range(max_retries):
            logging.info(
                f"Waiting for HA synchronization to complete on {hostname}. Attempt {attempt + 1}/{max_retries}"
            )
            # Wait for HA synchronization
            time.sleep(retry_interval)

            # Re-fetch the HA status to get the latest state
            deploy_info, ha_details = get_ha_status(
                hostname=hostname,
                target_device=target_device,
            )
            local_state, local_version, peer_state, peer_version = panorama_ha_states(
                ha_details
            )

            if peer_version and peer_version != local_version and str(peer_state).endswith("-passive"):
                logging.info(
                    f"HA synchronization complete on {hostname}. Proceeding with upgrade."
                )
                break
            else:
                logging.info(
                    f"HA synchronization still in progress on {hostname}. Rechecking after wait period."
                )

        logging.info(
            f"{get_emoji(action='report')} {hostname}: Local state: {local_state}, Local version: {local_version}, Peer version: {peer_version}"
        )
        logging.info(f"{get_emoji(action='report')} {hostname}: HA peer state: {peer_state}")

    # The peer is rebooting, down, or HA is disconnected, so its version and state are unknown
    if not peer_version or not local_version:
        if is_device_to_revisit:
            logging.error(
                f"{get_emoji(action='error')} {hostname}: HA peer not ready: its version and state still aren't available in round 2. Not upgrading this Panorama. Check the HA pair, then run it again."
            )
            sys.exit(1)
        defer_to_round_two(
            hostname=hostname,
            reason="its HA peer isn't reporting a version or state (it may be rebooting)",
            target_device=target_device,
            target_devices_to_revisit=target_devices_to_revisit,
            target_devices_to_revisit_lock=target_devices_to_revisit_lock,
        )
        return False, None

    version_comparison = compare_versions(
        version1=local_version,
        version2=peer_version,
    )
    logging.info(
        f"{get_emoji(action='report')} {hostname}: Version comparison: {version_comparison}"
    )

    local_active = str(local_state).endswith("-active")
    local_passive = str(local_state).endswith("-passive")
    peer_ready = str(peer_state).endswith("-passive")

    # If the active and passive target devices are running the same version
    if version_comparison == "equal":

        # If the current device is active (primary-active, or secondary-active after a failover)
        if local_active:

            if is_device_to_revisit:
                if dry_run:
                    logging.info(
                        f"{get_emoji(action='report')} {hostname}: Its HA peer still runs {peer_version} because this is a dry run. In a real run the peer is upgraded first. Continuing the dry run."
                    )
                    return True, None
                logging.error(
                    f"{get_emoji(action='error')} {hostname}: HA peer not upgraded: the peer still runs {peer_version}, so it wasn't upgraded in round 1. Not upgrading this active Panorama. Upgrade the peer first, then run this Panorama again."
                )
                sys.exit(1)

            # Add the active target device to the list and exit the upgrade process
            with target_devices_to_revisit_lock:
                target_devices_to_revisit.append(target_device)

            # Log message to console
            logging.info(
                f"{get_emoji(action='search')} {hostname}: Detected {local_state} target device in HA pair running the same version as its peer. Added target device to revisit list."
            )

            # Exit the upgrade process for the target device at this time, to be revisited later
            return False, None

        # if the current device is passive
        elif local_passive:

            # suspend HA state of the target device
            if not dry_run:
                logging.info(
                    f"{get_emoji(action='report')} {hostname}: Suspending HA state of {local_state}"
                )
                if not suspend_ha_passive(
                    target_device,
                    hostname,
                ):
                    logging.error(
                        f"{get_emoji(action='error')} {hostname}: Failed to suspend HA state, so the upgrade stops here before making changes."
                    )
                    sys.exit(1)

            # log message to console
            else:
                logging.info(
                    f"{get_emoji(action='report')} {hostname}: Target device is {local_state}, but we are in dry-run mode. Skipping HA state suspension.",
                )

            # Continue with upgrade process on the passive target device
            return True, None

        elif (
            local_state == "secondary-suspended"
            or local_state == "secondary-non-functional"
        ):

            # Continue with upgrade process on the secondary-suspended or secondary-non-functional target device
            logging.info(
                f"{get_emoji(action='warning')} {hostname}: Target device is {local_state}",
            )

            # Continue with upgrade process on the passive target device
            return True, None

        else:
            logging.error(
                f"{get_emoji(action='error')} {hostname}: HA state is {local_state}, so the CLI won't upgrade it. If it was left suspended, run request high-availability state functional on it, then run it again."
            )
            sys.exit(1)

    elif version_comparison == "older":

        # log message to console
        logging.info(
            f"{get_emoji(action='report')} {hostname}: Target device is on an older version"
        )

        # Suspend HA state of the active if its peer is already on the later release
        if local_active:

            # Suspending the active fails over to the peer, so the peer must be passive
            if not peer_ready:
                if dry_run:
                    logging.warning(
                        f"{get_emoji(action='warning')} {hostname}: HA peer is {peer_state}. A real run wouldn't suspend this active Panorama until the peer is passive. Continuing the dry run."
                    )
                    return True, None
                if is_device_to_revisit:
                    logging.error(
                        f"{get_emoji(action='error')} {hostname}: HA peer not ready: the peer is {peer_state}, so it can't take over. Not suspending this active Panorama. Make the peer functional (request high-availability state functional), then run this Panorama again."
                    )
                    sys.exit(1)
                defer_to_round_two(
                    hostname=hostname,
                    reason=f"its HA peer is {peer_state} and can't take over yet",
                    target_device=target_device,
                    target_devices_to_revisit=target_devices_to_revisit,
                    target_devices_to_revisit_lock=target_devices_to_revisit_lock,
                )
                return False, None

            if not dry_run:
                # log message to console
                logging.info(
                    f"{get_emoji(action='report')} {hostname}: Suspending HA state of {local_state}"
                )

                # Suspend HA state of the active
                if not suspend_ha_active(
                    target_device,
                    hostname,
                ):
                    logging.error(
                        f"{get_emoji(action='error')} {hostname}: Failed to suspend HA state, so the upgrade stops here before making changes."
                    )
                    sys.exit(1)

        return True, None

    elif version_comparison == "newer":

        # log message to console
        logging.info(
            f"{get_emoji(action='report')} {hostname}: Target device is on a newer version"
        )

        # Suspend HA state of the passive if the active is on an earlier release
        if local_passive and not dry_run:

            # log message to console
            logging.info(
                f"{get_emoji(action='report')} {hostname}: Suspending HA state of {local_state}"
            )

            if not suspend_ha_passive(
                target_device,
                hostname,
            ):
                logging.error(
                    f"{get_emoji(action='error')} {hostname}: Failed to suspend HA state, so the upgrade stops here before making changes."
                )
                sys.exit(1)

        return True, None

    logging.error(
        f"{get_emoji(action='error')} {hostname}: Couldn't compare its version ({local_version}) with its HA peer's ({peer_version}). Not upgrading it."
    )
    sys.exit(1)


def suspend_ha_active(
    target_device: Union[Firewall, Panorama],
    hostname: str,
) -> bool:
    """
    Temporarily disables High Availability (HA) functionality on an active device within an HA configuration.

    In an HA setup, it may be necessary to suspend HA functionality on the active device to perform system upgrades or maintenance tasks without triggering failover to the passive device. This function sends an operational command to the target device to suspend HA, ensuring that the device remains in an active but non-failover state. It checks the command's success through the device's response and provides appropriate logging for the operation's outcome.

    Parameters
    ----------
    target_device : Union[Firewall, Panorama]
        The device on which HA functionality is to be suspended. This must be an active device in an HA pair and can be either a Firewall or a Panorama appliance.
    hostname : str
        The hostname or IP address of the target device. This is used primarily for identification and logging purposes.

    Returns
    -------
    bool
        True if the command to suspend HA is successfully issued and acknowledged by the target device, indicating that HA functionality has been suspended. False if the command fails or the device response indicates an error.

    Raises
    ------
    Exception
        If the operational command to suspend HA fails or an unexpected response is received from the device, an exception is raised detailing the error encountered.

    Example
    -------
    Suspending HA functionality on an active device in an HA pair:
        >>> firewall = Firewall(hostname='192.168.1.1', api_username='admin', api_password='admin')
        >>> success = suspend_ha_active(firewall, '192.168.1.1')
        >>> if success:
        ...     print("HA suspension successful.")
        ... else:
        ...     print("HA suspension failed.")

    Notes
    -----
    - Suspending HA on the active device is a significant operation that should be performed with caution, particularly in a production environment, to avoid unintended service disruptions.
    - Ensure that the procedure for resuming HA functionality is planned and understood before suspending HA, as this will be necessary to restore full HA operational capabilities.
    """

    try:
        suspension_response = target_device.op(
            "<request><high-availability><state><suspend/></state></high-availability></request>",
            cmd_xml=False,
        )

        response_message = flatten_xml_to_dict(suspension_response)

        if response_message.get("result") == "Successfully changed HA state to suspended":
            logging.info(
                f"{get_emoji(action='success')} {hostname}: Active target device HA state suspended."
            )
            with _suspended_by_run_lock:
                _suspended_by_run.add(device_key(target_device))
            return True
        else:
            logging.error(
                f"{get_emoji(action='error')} {hostname}: Failed to suspend active target device HA state."
            )
            return False
    except Exception as e:
        logging.warning(
            f"{get_emoji(action='warning')} {hostname}: Error received when suspending active target device HA state: {e}"
        )
        return False


def suspend_ha_passive(
    target_device: Union[Firewall, Panorama],
    hostname: str,
) -> bool:
    """
    Temporarily disables High Availability (HA) functionality on the passive device within an HA pair.

    In an HA environment, it may become necessary to suspend HA functionality on the passive device to facilitate system upgrades or maintenance, ensuring the device does not unexpectedly become active. This function issues a command to the target device to suspend its HA functionality. The success of this operation is determined by the response from the device, and the outcome is logged for administrative review.

    Parameters
    ----------
    target_device : Union[Firewall, Panorama]
        The device on which HA functionality is to be suspended. This must be a passive device in an HA pair and can be either a Firewall or a Panorama appliance.
    hostname : str
        The hostname or IP address of the device. Used for identification and logging.

    Returns
    -------
    bool
        True if the HA suspension command is successfully executed, indicating that HA functionality on the passive device has been temporarily disabled. False if the command execution fails or if the device response indicates an error.

    Raises
    ------
    Exception
        If the operational command to suspend HA fails or an unexpected response is received, an exception is logged detailing the encountered issue.

    Example
    -------
    Suspending HA on the passive device in an HA configuration:
        >>> panorama = Panorama(hostname='panorama.example.com', api_username='admin', api_password='admin')
        >>> success = suspend_ha_passive(panorama, 'panorama.example.com')
        >>> print("HA suspension successful" if success else "HA suspension failed")

    Notes
    -----
    - Suspending HA on a passive device is a critical operation that should be carefully planned and executed, particularly in live environments, to avoid unintended failovers or service disruptions.
    - Coordination with network management and understanding the process to resume HA functionality are essential to ensure the continuity of services and network redundancy.
    """

    logging.info(
        f"{get_emoji(action='start')} {hostname}: Suspending passive target device HA state."
    )

    try:
        suspension_response = target_device.op(
            "<request><high-availability><state><suspend/></state></high-availability></request>",
            cmd_xml=False,
        )

        response_message = flatten_xml_to_dict(suspension_response)

        if response_message.get("result") == "Successfully changed HA state to suspended":
            logging.info(
                f"{get_emoji(action='success')} {hostname}: Passive target device HA state suspended."
            )
            with _suspended_by_run_lock:
                _suspended_by_run.add(device_key(target_device))
            return True
        else:
            logging.error(
                f"{get_emoji(action='error')} {hostname}: Failed to suspend passive target device HA state."
            )
            return False
    except Exception as e:
        logging.error(
            f"{get_emoji(action='error')} {hostname}: Error suspending passive target device HA state: {e}"
        )
        return False
