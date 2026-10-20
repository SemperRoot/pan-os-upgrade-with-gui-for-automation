# Upgrade workflow with the PAN-OS Upgrade Console

How to plan, test, run and verify a PAN-OS upgrade with the GUI, from preparation to the checks
after the upgrade.

- Installing on Windows: [WINDOWS.md](WINDOWS.md)
- How HA pairs are upgraded, in detail: [README.md](README.md), also in the GUI under **Help → HA upgrade guide**

## The workflow at a glance

```
1. Prepare        versions, compatibility, HA state, maintenance window, settings, inventory
      │
2. Dry run        download + snapshot + readiness checks + config backup, no install, no reboot
      │
3. Review         Output panel, Run history, readiness results
      │
4. Live upgrade   install + reboot (HA: passive member first, then active)
      │
5. Monitor        Output panel, answer prompts if asked
      │
6. Verify         HA state (restore suspended members), versions, sync, active member, diff reports
```

## Where the GUI keeps things

Every run started from the GUI works in `gui/workspace/`:

| What | Where |
|------|-------|
| Settings for GUI runs | `gui/workspace/settings.yaml` (edit on the **Settings** page) |
| Batch inventory | `gui/workspace/inventory.yaml` (edit on the **Inventory** page) |
| Full output of each run | `gui/workspace/console/<date>_<time>_<command>.log` (shown on **Run history**) |
| CLI log | `gui/workspace/logs/upgrade.log` (shown on **Logs**) |
| Readiness check results | `gui/workspace/assurance/readiness_checks/<host>/pre/` |
| Snapshots before and after | `gui/workspace/assurance/snapshots/<host>/pre/` and `post/` |
| Snapshot comparison (JSON and PDF) | `gui/workspace/assurance/snapshots/<host>/diff/` |
| Configuration backups | `gui/workspace/assurance/configurations/<host>/pre/` and `post/` |

## Step 1: Prepare

### Check versions and compatibility

- **Both HA members must run the same version.** If they don't, both members upgrade *at the same
  time* and the pair can go fully down. Align them first, or upgrade one member at a time (see
  [Peers on different versions](README.md#peers-on-different-versions)).
- **Check the version jump.** For HA pairs, the CLI refuses jumps it considers unsafe, for example
  10.0 → 10.2 or 10.1 → 11.1. Plan intermediate steps if needed (see
  [Version compatibility rule](README.md#version-compatibility-rule-ha-pairs-only)).
- **Check the HA state on both members** with `show high-availability state`. Each member should
  be `active` or `passive` (`active-primary` or `active-secondary` for active/active), and the
  configuration `synchronized`. A firewall member in another state, such as `suspended`, is
  skipped by the CLI.
- **Plan a maintenance window** for at least two full download-install-reboot cycles, run one
  after the other, plus a few minutes of HA sync wait.

### Review settings

Open **Configuration → Settings**. The defaults suit most upgrades. Look at:

| Setting | Why it matters |
|---------|----------------|
| **Readiness checks** | Run before each upgrade. Checks marked **Blocks upgrade** stop that device if they fail. Turn on **Customize readiness checks** to choose. Keep `ha` on for HA pairs. |
| **Snapshots** | Captured before and after; the comparison is how you verify the upgrade. Consider enabling `ip_sec_tunnels` if the firewalls carry VPNs. |
| **Retry policy → Reboot** | How long the CLI waits for a device to come back. Default: 30 tries × 60 s. Raise it for slow platforms. |
| **Concurrent threads** | How many devices a batch upgrade runs at once. |

Click **Save settings**. The **Unsaved changes** badge disappears once saved.

### Prepare the device list (batch upgrades only)

Open **Configuration → Inventory** and either:

- type one hostname per line and click **Save**, or
- fill in the Panorama details under **Discover from Panorama** and click **Discover devices**.
  Pick devices in the Output panel prompt (for example `1,3-5`), then click **Done**. The list
  reloads when the file changes.

**List both members of every HA pair.** Hostnames must match the names in Panorama.

## Step 2: Dry run

Always start with a dry run. A dry run is **not** free of side effects. On each device it tests,
it:

- downloads the target PAN-OS image to the device,
- takes a pre-upgrade snapshot,
- runs the readiness checks,
- backs up the configuration,

then stops before install and reboot.

**HA pairs:** a dry run only tests the passive member. The active member is skipped. See
[Dry run with an HA pair](README.md#dry-run-with-an-ha-pair).

1. In the side menu, open the page for your target:
   - **Firewall:** one firewall, or one member of an HA pair (the peer is found automatically).
   - **Panorama:** one Panorama appliance and its HA peer.
   - **Batch upgrade:** several firewalls through Panorama.
2. Fill in the **Target** card: hostname and target PAN-OS version (for example `10.2.7-h3`).
   - Firewall page: fill in **HA peer hostname or IP** only if the peer's management address
     isn't reachable from your machine, for example behind NAT.
   - Batch page: enter hostnames in the **Devices** card, or leave it empty to use the saved
     inventory. The box under the field shows which list will be used.
3. Fill in the **Credentials** card. The password is never saved, so you enter it for each run.
4. In the **Execution** panel, leave **Dry run** selected and check the **Command** preview.
5. Click **Start dry run**.

The **Output** panel opens at the bottom. On the Batch page with no device list, a table of
devices appears in the Output panel: type the numbers (for example `1,3-4`) and click **Done**.

## Step 3: Review the dry run

When the status badge shows **Completed**:

- **Read the Output panel** (or the run on **Monitoring → Run history**). Look for errors,
  failed readiness checks and *Not ready for upgrade*.
- **Check the HA lines.** You should see the active member deferred (*Added target device to
  revisit list*) and the passive member go through the checks.
- **Open the readiness results** in `gui/workspace/assurance/readiness_checks/<host>/pre/`.
- **Fix whatever failed** (pending changes, expired licenses, disk space, HA state) and run the
  dry run again until it's clean.

**Completed** means the CLI exited with code 0. It doesn't mean every check passed: checks
without **Blocks upgrade** only log an error, and a device that's already on the target version
also ends the run with code 0. Read the output.

## Step 4: Live upgrade

1. Open the same page with the same details. Enter the password again.
2. In the **Execution** panel, select **Live upgrade**. The panel turns red and the button changes
   to **Start live upgrade**.
3. Click **Start live upgrade**. A confirmation dialog shows the target devices and version, warns
   about reboots, and reminds you that HA isn't restored automatically. If other `pan-os-upgrade`
   processes are running on this machine, it lists them.
4. **Type the target version** in the dialog. **Start live upgrade** is enabled only when it
   matches exactly.
5. Click **Start live upgrade**.

What happens next depends on the page:

| Page | Prompts during the run |
|------|------------------------|
| Firewall | None. The CLI runs non-interactively. |
| Panorama | The GUI answers the CLI's *Dry Run?* prompt for you. Answer any other prompt in the Output panel. |
| Batch, with a device list | None. |
| Batch, without a device list | Pick devices in the Output panel, click **Done**, then confirm with **Yes**. |

For an HA pair with the same version on both members, the order is: the passive member is
suspended and upgraded first; after HA syncs, the active member is suspended, traffic fails over
to the upgraded member, and the original active member is upgraded.

## Step 5: Monitor

- **Status badge** (header and Output panel): *Running*, *Awaiting input*, *Completed*,
  *Failed (exit N)* or *Stopped*, with elapsed time.
- **Awaiting input:** the Output panel opens with the CLI's question in the orange bar. Type a reply
  and press **Enter**, or use **Yes**, **No** or **Done**.
- **Progress lines to look for in HA upgrades:**

  | Log line | Meaning |
  |----------|---------|
  | *Added target device to revisit list* | Active member deferred to round 2 |
  | *Suspending HA state of passive or active-secondary* | Passive member's upgrade started |
  | *Revisiting firewalls that were active in an HA pair* | Round 2 started |
  | *Waiting for HA synchronization to complete* | Round 2 sync wait, at least 60 s |
  | *Suspending HA state of active or active-primary* | Failover to the upgraded member |

- **Copy icon** next to **Stop**: copies the path of this run's saved output file.
- You can close the browser tab; the run continues. Reopen <http://localhost:8080> to check on it.
  Keep the terminal running `gui.py` open.

### Stopping a run

**Stop** sends an interrupt, then forces the CLI to exit if it doesn't stop within 10 seconds.
**Avoid stopping during download, install or reboot.** A download or install already running on
a device keeps going there, but the CLI won't reboot it, and an HA member may be left suspended.
After stopping, check each device's software state and HA state by hand.

## Step 6: Verify

The CLI suspends HA on each member and **never sets it back to functional**. After every live run:

1. **Check HA state on both members:**

   ```
   show high-availability state
   ```

2. **Return any suspended member to service**, from that member's CLI:

   ```
   request high-availability state functional
   ```

3. **Confirm the versions:** both members run the target version (`show system info`).
4. **Confirm sync:** the configuration shows `synchronized`.
5. **Confirm the active member** is the one you expect. Preemption and priority settings decide
   whether the original active member takes over again.
6. **Review the diff reports** in `gui/workspace/assurance/snapshots/<host>/diff/` (JSON and PDF).
   They compare the snapshots taken before and after. Look for unexpected changes in routes, ARP
   entries, sessions, interfaces and IPsec tunnels. The CLI doesn't judge these differences; a
   person has to read them.
7. **Keep the run record.** **Run history** has the full output, and the configuration backups
   are in `gui/workspace/assurance/configurations/<host>/`.

## When something goes wrong

| Symptom | Where to look and what to do |
|---------|------------------------------|
| **Failed (exit 1)** early in the run | Output panel. Usually *Not ready for upgrade*: the version isn't available, the jump is blocked for HA, or a check marked **Blocks upgrade** failed. Fix it and dry-run again. |
| *No upgrade required or downgrade attempt detected* | The device already runs the target version or newer. Nothing was changed on it, but this also **ends the run after round 1** (see next row). |
| Passive members upgraded, active members never started | A device stopped in round 1 (already on target, not ready, failed blocking check), which cancels round 2 for every pair. Check HA state and restore suspended members, fix or remove that device, then run again: each pair's members are now on different versions, so they'll upgrade together (see [Peers on different versions](README.md#peers-on-different-versions)). Consider upgrading each remaining active member on its own from the **Firewall** page. |
| Run stuck on **Awaiting input** | Read the orange prompt bar and reply. |
| A device doesn't come back after reboot | The CLI keeps waiting until **Retry policy → Reboot** runs out. Check the device's console. Raise the reboot limit for slow platforms. |
| Only one HA member was upgraded | Check whether the run was stopped, whether another device stopped round 1 (row above), whether the other member was in an unexpected HA state, or (batch) whether both members were listed. Check `show high-availability state` and restore suspended members. |
| Need more detail | Set **Settings → Logging level** to `DEBUG`, save, and check **Monitoring → Logs** on the next run. |
| A dry run suspended HA | Known CLI issue when the HA members run different versions (see [Known issues](README.md#known-issues)). Restore the member with `request high-availability state functional`. |
