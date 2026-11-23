# PAN-OS Upgrade Console: HA upgrade guide

How the PAN-OS Upgrade Console (`gui/gui.py`) upgrades firewalls and Panorama appliances that are
in a High Availability (HA) pair: the order, what happens to each member, and what to check afterwards.

The GUI doesn't make any of these decisions. It runs the `pan-os-upgrade` CLI, and everything
below describes that CLI's behavior, mainly in
[`components/ha.py`](../pan_os_upgrade/components/ha.py),
[`components/upgrade.py`](../pan_os_upgrade/components/upgrade.py) and
[`main.py`](../pan_os_upgrade/main.py).

> **Read [After the upgrade](#after-the-upgrade) before your first live run.** The tool suspends HA
> on each member for its upgrade and makes it functional again afterwards; check the pair yourself
> after every run.

## Running the GUI

Install it once as described in [WINDOWS.md](WINDOWS.md) (step by step) or [INSTALL.md](INSTALL.md)
(Windows or Linux), then:

```bat
gui\start-gui.cmd
```

```bash
bash gui/start-gui.sh
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
  passive member ─ checks ─ suspend HA ─ download ─ snapshot ─ readiness ─ backup ─ install ─ reboot ─ HA functional ─ post snapshot
  active member  ─ checks ─ "same version as peer" ─ deferred to round 2
                                    │
             round 1 finishes only after the passive member is done
                                    │
Round 2
  active member  ─ wait for peer ─ now older than its peer, peer passive ─ suspend HA (traffic fails over
                   to the upgraded member) ─ download ─ snapshot ─ readiness ─ backup ─ install ─ reboot ─ HA functional ─ post snapshot
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
  4. Installs the new version, reboots, and waits for the device to come back.
  5. **Makes its HA state functional again** (*HA state restored to functional*), so it rejoins the
     pair as passive. Suspended HA survives a reboot, so without this step the member would stay
     out of the pair.
  6. Takes a post-upgrade snapshot and writes a pre/post diff report to
     `assurance/snapshots/<host>/diff/`.

If the upgrade stops at any point after HA was suspended (a failed download, snapshot, check or
install), the member's HA is made functional again before it stops.

Round 1 ends when every member in it has finished. **Round 2 always runs**, even if some devices
stopped in round 1: one device's failure no longer ends the run. (Before the November 2026 fixes,
any device stopping, or a dry run finishing, ended the run after round 1 and no active member was
upgraded.) The run's exit code is 1 if any device stopped.

### Round 2

Each deferred active member:

1. **Waits for its peer.** It waits one interval, then checks whether the pair is synchronized or
   the upgraded peer is back as passive, up to `ha_sync.max_tries` tries. The defaults are 3 tries,
   60 seconds apart, so this always takes at least 60 seconds.
2. Compares versions again. Its peer was just upgraded, so this member is now **older**.
   - **Peer still on the same version** (its upgrade failed, or it isn't in the inventory): the
     member stops with *HA peer not upgraded*. Nothing changes on it. In a dry run it continues
     its dry-run checks instead.
   - **Peer not passive** (for example still suspended): the member stops with *HA peer not
     ready* and is **not** suspended, because nothing could take over its traffic.
3. Runs the HA readiness check, then **suspends its own HA state**. Traffic fails over to the
   member that was already upgraded.
4. Goes through the same download, snapshot, readiness, backup, install, reboot, HA functional and
   post-snapshot steps as the passive member did.

An active member that finds its peer's version or state missing in round 1 (the peer is
rebooting, for example) or its peer not yet passive is deferred to round 2 instead of failing.
That makes the order of the inventory irrelevant: standbys don't need to be listed first.

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
  **Help → HA upgrade guide** in the side menu shows this README inside the GUI, and
  **Help → What's new** shows the changes in the installed release.
- **Live upgrade confirmation:** summarizes how HA members are suspended and restored.
- **Header badge and Output panel:** *Running*, *Awaiting input*, *Completed*, *Failed* or *Stopped*,
  plus elapsed time. The Output panel shows the CLI's log for both members together, each line
  prefixed with the device hostname.
- **Monitoring → Upgrade tracker:** one row per device instead of one interleaved log. The GUI
  opens it when a firewall, Panorama, batch or config backup run starts, and you can reopen any
  saved run from the **Run** menu.
  - **Tiles** count devices *In progress*, *Waiting* (queued, or an active member deferred to
    round 2), *Done* and *Needs attention*. Click a tile to filter the table by it.
  - **Filters:** HA role (active, passive, standalone), free-text search over device, stage and
    message, and *Only with warnings or errors*.
  - **Table:** HA role with a *Round 2* badge for deferred active members, a pause icon on members
    this run suspended, status, current stage with a progress bar and time in that stage, the
    latest message, versions, and warning and error counts.
  - **Device details and log:** select a row to see its stages, versions, the reason it stopped,
    its diff reports, and only that device's log lines, optionally just warnings and errors.
  - **HA suspended banner:** lists members the run suspended that haven't been made functional
    again yet. During a run that's normal; after the run, any member still listed needs
    `request high-availability state functional`.
  - **Export results:** downloads one row per device (status, stage, versions, HA role and peer
    state, problem, warning and error counts, reports) as a CSV file that opens in Excel.
  - **Retry devices that need attention:** after a batch run, puts every device that *Failed*,
    was *Not upgraded* or was *Interrupted* into the Batch upgrade form. Fix the cause (disk space,
    HA state, pending changes), then dry-run or upgrade just those devices.
  - The tracker reads the CLI's console output; it doesn't query devices. A member already in
    HA *suspended* state when the run starts fails with *HA state is suspended, so the CLI won't
    upgrade it*.
- **Lines to look for:**
  - *Added target device to revisit list*: the active member was deferred to round 2.
  - *Suspending HA state of passive or active-secondary*: the passive member is starting its upgrade.
  - *Revisiting firewalls that were active in an HA pair*: round 2 has started.
  - *Waiting for HA synchronization to complete*: round 2's sync wait.
  - *Suspending HA state of active or active-primary*: failover to the upgraded member.
  - *HA state restored to functional*: a member rejoined the pair after its upgrade.
  - *HA peer not ready* / *HA peer not upgraded*: round 2 stopped an active member safely, without
    suspending it.
- **Run history** keeps the full output of every GUI run in `gui/workspace/console/`.
- **Environment** (bottom of the side menu): the version of the project files and of the installed
  CLI. If the CLI is older, a red warning at the top of every page says to run the setup again.

A live HA upgrade takes at least two full download-install-reboot cycles, one after the other, plus
the sync wait. Closing the browser tab is safe: the run continues and you can reopen the page. If
you stop `gui.py` itself, the CLI keeps running in the background, but the GUI loses track of it
and you can no longer answer prompts or stop it from the GUI. Its output is still written to
`gui/workspace/console/`.

## Dry run with an HA pair

A dry run is **not** side-effect free (it downloads the image), but it never suspends HA:

- The **passive member** downloads the target image, takes a snapshot, runs readiness checks and
  backs up its configuration, then stops.
- The **active member** is deferred, as in a live run, and runs the same dry-run checks in round 2.

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
| Anything else (e.g. `suspended`, `non-functional`) | **Stops** with *HA state is …, so the CLI won't upgrade it*; nothing changes |

For Panorama, `secondary-suspended` and `secondary-non-functional` members are upgraded in round 1
without being suspended again.

## Batch upgrades

The **Batch upgrade** page connects to firewalls through Panorama and uses the same two rounds. It
runs up to the number of members set in **Settings → Concurrent threads** at once (round 1 and round 2
both use this setting).

- **Both members listed:** works as described above.
- **Only the passive member listed:** the passive member is upgraded. The active member isn't
  touched, which leaves the pair on mismatched versions.
- **Only the active member listed (same version):** it's deferred in round 1 and stops in round 2
  with *HA peer not upgraded*. Nothing changes on it.
- **The order of the list doesn't matter.** Standalones, passives and actives can be mixed.
- **One device stopping doesn't affect the others.** Each device that fails is marked *Failed* in
  the tracker with the reason; every other device, including round 2, carries on. Use **Retry
  devices that need attention** in the tracker to run the failed ones again once fixed.

## After the upgrade

Each member the CLI suspended is made functional again after its reboot (or when its upgrade
stops), retrying `ha_sync.max_tries` times. If that fails, the log says *Failed to restore HA state
to functional* and the tracker's HA suspended banner lists the member. After a live run, check both
members:

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
| HA sync interval / max tries (`ha_sync.*`) | GUI → Settings → Retry policy | Round 2's wait for the peer, and the attempts to make a suspended member functional again. Default: 3 tries × 60 s. |
| Download / Snapshots interval and max tries, download timeout | GUI → Settings → Retry policy | The per-device error limits: a device fails after this many download or snapshot attempts, or when a download hasn't finished within the timeout (default 3600 s per try), instead of retrying forever. |

## Known issues

These are CLI behaviors, not GUI behaviors. They're listed so you can plan around them.

1. **The out-of-sync warning doesn't stop the upgrade.** The pre-upgrade HA sync check only logs a
   warning. Round 2 only requires the upgraded peer to be passive, not synchronized (a pair on two
   different releases may not report synchronized).
2. **Peers on different versions that both need the upgrade** can still be upgraded at the same
   time. See [Peers on different versions](#peers-on-different-versions).
