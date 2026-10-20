# PAN-OS Upgrade Console: HA upgrade guide

How the PAN-OS Upgrade Console (`gui/gui.py`) upgrades firewalls and Panorama appliances that are
in a High Availability (HA) pair: the order, what happens to each member, and what to check afterwards.

The GUI doesn't make any of these decisions. It runs the `pan-os-upgrade` CLI, and everything
below describes that CLI's behavior, mainly in
[`components/ha.py`](../pan_os_upgrade/components/ha.py),
[`components/upgrade.py`](../pan_os_upgrade/components/upgrade.py) and
[`main.py`](../pan_os_upgrade/main.py).

> **Read [After the upgrade](#after-the-upgrade) before your first live run.** The tool suspends HA
> on each member but never sets it back to functional.

## Running the GUI

```bash
gui/.venv/bin/python gui/gui.py
```

Open <http://localhost:8080>. The GUI only listens on your machine. Runs use their own working
folder, `gui/workspace/`, which holds that run's `settings.yaml`, `inventory.yaml`, logs and
assurance reports.

## Summary

When both members run the **same** PAN-OS version, the passive member is upgraded first, then the active one:

| Order | Firewall pair                  | Panorama pair       |
|-------|--------------------------------|---------------------|
| 1st   | `passive` or `active-secondary` | `secondary-passive` |
| 2nd   | `active` or `active-primary`    | `primary-active`    |

When the members run **different** versions, there's no first or second: see
[Peers on different versions](#peers-on-different-versions).

## Which page to use

| Page              | HA peer handling |
|-------------------|------------------|
| **Firewall**      | Enter one member. The peer is found automatically from its HA state (management IP, then management IPv6, then HA1 IP). If that address isn't reachable from your machine, for example because it's behind NAT, enter it under **HA peer hostname or IP**. Both members use the same username and password. |
| **Panorama**      | Enter one appliance. The peer is found automatically from its management IP or IPv6. |
| **Batch upgrade** | Nothing is detected automatically. **List both members of every pair**, in the field or in the saved inventory. With only one member listed, the pair is upgraded partly or not at all (see [Batch upgrades](#batch-upgrades)). |

## The upgrade, step by step (same version on both members)

The CLI processes both members of a pair in **two rounds**.

```
Round 1 (both members start in parallel)
  passive member ─ checks ─ suspend HA ─ download ─ snapshot ─ readiness ─ backup ─ install ─ reboot ─ post snapshot
  active member  ─ checks ─ "same version as peer" ─ deferred to round 2
                                    │
             round 1 finishes only after the passive member is done
                                    │
Round 2
  active member  ─ wait for HA sync ─ now older than its peer ─ suspend HA (traffic fails over
                   to the upgraded member) ─ download ─ snapshot ─ readiness ─ backup ─ install ─ reboot ─ post snapshot
```

### Round 1

Both members start at the same time and run the same opening checks:

1. Connect and read system info and HA state.
2. **Check that an upgrade is possible.**
   - If the member already runs the target version or newer, it stops with *No upgrade required or
     downgrade attempt detected*.
   - Otherwise the target must be available on the device and, for HA pairs, the version jump must
     pass the compatibility rule below. If not, that member stops with *Not ready for upgrade*.
3. Compare the member's version with its peer's.

When the versions match, the members split:

- **Active member:** it's put on a revisit list and skipped for now. The log says
  *Detected active target device in HA pair running the same version as its peer*.
- **Passive member:**
  1. Runs the **HA readiness check**, if `ha` is enabled under readiness checks (it is by default).
     If the check fails, this member's upgrade stops before anything changes.
  2. **Suspends its HA state.**
  3. Downloads the image, takes a pre-upgrade snapshot, runs the other readiness checks, checks HA
     sync, and backs up the configuration to `assurance/configurations/`.
  4. Installs the new version, reboots, waits for the device to come back, then takes a
     post-upgrade snapshot and writes a pre/post diff report to `assurance/snapshots/<host>/diff/`.

Round 1 ends when every member in it has finished.

**Round 2 only starts if no member stopped the run in round 1.** When a member stops early (for
example *Not ready for upgrade*, a failed blocking check, or *No upgrade required*), or reaches the
end of a dry run, the CLI ends the whole run as soon as the other round-1 members finish. For an
HA pair this is protective: if the passive member's upgrade fails, the active member isn't touched.

### Round 2

Each deferred active member:

1. **Waits for HA to sync.** It waits one interval, then checks whether the configuration is
   synchronized, up to the configured number of tries. The defaults are 3 tries, 60 seconds apart,
   so this always takes at least 60 seconds. **If the pair never reports synchronized, the upgrade
   goes ahead anyway.**
2. Compares versions again. Its peer was just upgraded, so this member is now **older**.
3. Runs the HA readiness check, then **suspends its own HA state**. Traffic fails over to the
   member that was already upgraded.
4. Goes through the same download, snapshot, readiness, backup, install, reboot and post-snapshot
   steps as the passive member did.

### Version compatibility rule (HA pairs only)

Before anything changes, the CLI refuses version jumps it considers unsafe for an HA pair:

| Current → target | Result |
|------------------|--------|
| 10.2 or 11.x → any 11.x or later | Allowed |
| One minor step in the same major, e.g. 10.1 → 10.2 | Allowed |
| To the first release of the next major, e.g. 10.1 → 11.0 | Allowed |
| More than one minor step, e.g. 10.0 → 10.2 | **Blocked** |
| Next major beyond its first release, e.g. 10.1 → 11.1 | **Blocked** |
| More than one major, e.g. 9.1 → 11.0 | **Blocked** |

For a blocked jump, upgrade in stages, for example 10.0 → 10.1, then 10.1 → 10.2.

## What you see in the GUI

- **HA pairs box** on the Firewall, Panorama and Batch upgrade pages: a short version of this guide.
  **Help → HA upgrade guide** in the side menu shows this README inside the GUI.
- **Live upgrade confirmation:** includes a reminder that HA isn't restored automatically.
- **Header badge and Output panel:** *Running*, *Awaiting input*, *Completed*, *Failed* or *Stopped*,
  plus elapsed time. The Output panel shows the CLI's log for both members together, each line
  prefixed with the device hostname.
- **Lines to look for:**
  - *Added target device to revisit list*: the active member was deferred to round 2.
  - *Suspending HA state of passive or active-secondary*: the passive member is starting its upgrade.
  - *Revisiting firewalls that were active in an HA pair*: round 2 has started.
  - *Waiting for HA synchronization to complete*: round 2's sync wait.
  - *Suspending HA state of active or active-primary*: failover to the upgraded member.
- **Run history** keeps the full output of every GUI run in `gui/workspace/console/`.

A live HA upgrade takes at least two full download-install-reboot cycles, one after the other, plus
the sync wait. Closing the browser tab is safe: the run continues and you can reopen the page. If
you stop `gui.py` itself, the CLI keeps running in the background, but the GUI loses track of it
and you can no longer answer prompts or stop it from the GUI. Its output is still written to
`gui/workspace/console/`.

## Dry run with an HA pair

A dry run is **not** side-effect free, and for HA pairs it only tests one member:

- The **passive member** downloads the target image, takes a snapshot, runs readiness checks and
  backs up its configuration, then stops. Its HA state is **not** suspended.
- The **active member** is deferred, as in a live run. The passive member's dry run ends the whole
  run, so round 2 never starts. **The active member gets no readiness checks, snapshot or backup
  in a dry run.**

To dry-run the active member on its own, use the **Firewall** page on a standalone test device, or
treat the passive member's results as representative.

## Peers on different versions

If the two members already run different versions, for example after an interrupted upgrade:

- **Neither member is deferred.** Both continue in round 1, **at the same time**.
- The member on the **older** version suspends HA first, but only if it's the active member.
- The member on the **newer** version suspends HA first, but only if it's the passive member.
- A member that is already on the target version, or newer, stops with *No upgrade required*.

**If both members are below the target, both are upgraded and rebooted together, and the pair has
no working member during the reboots.** Before a live run, get both members onto the same version,
or upgrade one member at a time from the **Firewall** page and enter only that member's address.

## Member states that change the flow

| Firewall member state (same version) | What happens |
|--------------------------------------|--------------|
| `active`, `active-primary`           | Deferred to round 2 |
| `passive`, `active-secondary`        | Upgraded in round 1, HA suspended first |
| `initial`                            | Upgraded in round 1, HA **not** suspended (warning logged) |
| Anything else (e.g. `suspended`, `non-functional`) | **Skipped**, nothing is upgraded |

For Panorama, `secondary-suspended` and `secondary-non-functional` members are upgraded in round 1
without being suspended again.

## Batch upgrades

The **Batch upgrade** page connects to firewalls through Panorama and uses the same two rounds. It
runs up to the number of members set in **Settings → Concurrent threads** at once (round 1 and round 2
both use this setting).

- **Both members listed:** works as described above.
- **Only the passive member listed:** the passive member is upgraded. The active member isn't
  touched, which leaves the pair on mismatched versions.
- **Only the active member listed (same version):** it's deferred in round 1 and deferred again in
  round 2, because its peer was never upgraded. **Nothing is upgraded.**
- **One device can cancel round 2 for every pair.** If any device in round 1 stops (already on the
  target version, *Not ready for upgrade*, a failed blocking check), the run ends after round 1 and
  **none of the deferred active members are upgraded**. The passive members of the other pairs are
  still upgraded, leaving those pairs on mismatched versions. Remove devices that are already on
  the target from the list, and dry-run first.

## After the upgrade

**The CLI suspends HA on each member and never sets it back to functional.** It doesn't run
`request high-availability state functional` at any point. After a live run, check both members:

```
show high-availability state
```

If a member reports `suspended`, return it to service from that member's CLI:

```
request high-availability state functional
```

Then confirm that:

- both members run the target version and report `synchronized`,
- the expected member is active (preemption settings decide whether the original active member takes back over),
- the diff reports in `assurance/snapshots/<host>/diff/` show no unexpected changes in routes,
  ARP, sessions, interfaces or IPsec tunnels.

## Settings that affect HA upgrades

| Setting | Where | Effect |
|---------|-------|--------|
| Readiness check `ha` | GUI → Settings → Readiness checks | The HA check that runs just before HA is suspended. A failure stops that member's upgrade. On by default. |
| Concurrent threads | GUI → Settings → Execution | How many members run at once in batch upgrades, and in round 2 for the Firewall page. |
| Reboot interval / max tries | GUI → Settings → Retry policy | How long the CLI waits for a member to come back after reboot. Default: 30 tries × 60 s. |
| `ha_sync.max_tries`, `ha_sync.retry_interval` | **Not shown in the GUI.** Add them by hand to `gui/workspace/settings.yaml`. | Round 2's HA sync wait. Default: 3 tries × 60 s. Saving from the Settings page rewrites the file and drops these keys, so add them again after every save. |

## Known issues

These are CLI behaviors, not GUI behaviors. They're listed so you can plan around them.

1. **A dry run can suspend HA when the versions differ.** In
   [`ha.py`](../pan_os_upgrade/components/ha.py), the "older" and "newer" branches combine `or` and `and`
   without parentheses. As a result, an `active` member (older case) or a `passive` member (newer
   case) is suspended **even during a dry run**. It doesn't happen when both members run the same version.
2. **The out-of-sync warning doesn't stop the upgrade.** The pre-upgrade HA sync check only logs a
   warning, and round 2 goes ahead even if the pair never reports synchronized.
3. **Panorama, newer-version case.** When the `primary-active` appliance is on a newer version than its
   peer, the CLI suspends the `primary-active` appliance, not the `secondary-passive` one.
4. **HA is not restored automatically.** See [After the upgrade](#after-the-upgrade).
