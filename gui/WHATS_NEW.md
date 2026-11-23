# What's new

## Release 2026-11-23 (version `1.3.11+gui.2026.11.23`)

This release fixes the problems found in production batch runs of about 100 firewalls, 20 at a time.
The main changes:

- **HA pairs upgrade reliably in batch runs, in any order.** Members are put back into service
  automatically after their upgrade.
- **One device's problem stays with that device.** Every device has a limit on retries. A device
  that hits it is marked failed with the reason, and the rest of the run carries on.
- **Failed devices can be rerun in one click.** You can also export the results of every run.

To update an existing installation, follow [UPGRADING.md](UPGRADING.md). **You must run the setup
again after copying in the new files.** If you skip that step, the GUI keeps running the old
upgrade tool.

### At a glance

| What you saw | What happens now |
|--------------|------------------|
| *Attempting to capture network state snapshot* repeated thousands of times. Logs of 70,000+ lines, a thread held until the end of the run, and the firewall never upgraded. | Snapshots retry `snapshots.max_tries` times (default 3), 60 s apart, then the device stops with *Snapshot failed* before anything changes on it. The counter now goes 1 of 3, 2 of 3, 3 of 3. |
| A firewall with a full disk kept "downloading" forever, even after space was freed. | The tool watches the download job on the firewall. If the job fails, the device stops at once with the firewall's own reason, for example *Not enough disk space*. A download that hasn't finished within the timeout (default 1 hour) also counts as a failed try. Downloads are retried `download.max_tries` times (default 3). |
| Active HA members stuck at *Waiting for round 2*, failed or halted. | Round 2 now always runs. Before, any device that stopped in round 1 (or a finished dry run) ended the whole run before round 2 started. |
| HA2 stayed down after the upgrade; a firewall had to be rebooted. | Each member the tool suspends is made functional again right after its reboot, and also if its upgrade stops partway. Before, the tool never did this, and suspended HA survives a reboot. |
| It only worked with standbys listed before actives. | The order doesn't matter. The active member is only suspended once its upgraded peer is back as passive and can take over. If the peer isn't ready, the active member waits for round 2. If it still isn't ready, the active member stops with a clear reason and is never suspended. |
| No way to retry a device once the problem was fixed. | **Retry devices that need attention** on the Upgrade tracker puts exactly the failed devices back into the Batch upgrade form. |
| Results were hard to collect for 100 devices. | **Export results** on the Upgrade tracker saves one row per device as a CSV file that opens in Excel. |
| No per-firewall error limit. | The download, snapshot and HA retry limits are the per-firewall error limits. All of them are on the GUI Settings page, and they're stored in `settings.yaml` for CLI use. |

### Fixed

**Batch runs and HA pairs**

- **Round 2 always runs.** Before, one device stopping in round 1 ended the whole run once the other
  round-1 devices finished, so no deferred active member was upgraded. This included a device
  already on the target version, a failed check, a failed download, or a finished dry run. Now each
  device's result affects only that device.
- **HA is restored automatically.** After a member's reboot, the tool runs the equivalent of
  `request high-availability state functional`, retrying up to the HA sync limit. It does the same
  if the upgrade stops after HA was suspended (failed download, snapshot, check or install). The log
  says *HA state restored to functional*.
- **The active member is only suspended when its peer can take over.** The upgraded peer must
  report `passive` (or `active-secondary`). This prevents both members from being suspended at once.
- **No more endless "Waiting for round 2".** In round 2, an active member whose peer was never
  upgraded stops with *HA peer not upgraded*. One whose peer isn't passive stops with *HA peer not
  ready*. In both cases nothing changes on the active member.
- **A peer that's rebooting no longer crashes the check.** If the peer isn't reporting its version
  or state, the active member is deferred to round 2 instead of failing with an error.
- **Dry runs never suspend HA.** Before, a dry run could suspend a member when the two members ran
  different versions.
- **A failed HA suspension stops that member's upgrade** before anything changes. Before, it was
  ignored and the upgrade carried on.
- **A member that's already suspended** (for example, left over from an earlier run) stops with
  *HA state is suspended, so the CLI won't upgrade it*, instead of being skipped silently.
- **Dry runs check both members.** The active member now runs its dry-run checks in round 2.

**Downloads**

- A failed download job (no disk space, image not found, connection problems) stops the try at
  once, and the device's reason appears in the log and in the tracker.
- A download that hasn't finished within `download.timeout` (default 3600 seconds per try) counts as
  a failed try.
- The `download.max_tries` and `download.retry_interval` settings now take effect. They were
  ignored before.
- An image that's already on the firewall is still detected and not downloaded again, so
  pre-staging images still saves time.

**Snapshots**

- Every failed snapshot attempt counts toward `snapshots.max_tries`, including attempts that return
  no data. Before, only attempts that raised an error were counted, so an empty result retried
  forever with no pause.
- If the **pre-upgrade** snapshot can't be captured, the device stops with *Snapshot failed* before
  anything changes on it. You can rerun it, or upgrade it with snapshots turned off.
- If the **post-upgrade** snapshot can't be captured, the upgrade is still marked complete. Only the
  comparison report is skipped. Before, the run crashed at the comparison after a successful upgrade.

**Security**

- **Error output no longer shows passwords.** When the tool crashed, its error display printed
  every local variable, including the password typed at the prompt. Error output now shows only
  where the error happened. If an earlier version crashed on your machine, see
  [UPGRADING.md](UPGRADING.md#1-before-you-start) for where that output may have been saved.

**Other fixes**

- A Panorama with no connected firewalls now stops with *Panorama reports no connected firewalls*,
  instead of crashing with `'str' object has no attribute 'get'` (inventory, batch and backup).
- Turning off all readiness checks in Settings no longer crashes every upgrade.
- A firewall whose install fails is marked failed, and its HA is restored. Before, it could end as
  if it had succeeded, with HA still suspended.
- A Panorama whose install fails is no longer rebooted.

### New

- **Retry devices that need attention** (Upgrade tracker, after a batch run): fills the Batch
  upgrade form with every device marked *Failed*, *Not upgraded* or *Interrupted*. Fix the cause,
  then start a dry run or the upgrade for just those devices.
- **Export results** (Upgrade tracker): downloads a CSV file with one row per device. Columns:
  device, IP, serial, HA role, HA peer state, round, status, stage, current, target and peer
  versions, whether HA was left suspended, warning and error counts, the reason it stopped, the
  latest activity, times, and report paths.
- **New Settings fields** (Configuration → Settings → Retry policy):
  - **Snapshots**: interval and max tries.
  - **HA sync**: interval and max tries. This sets round 2's wait for the peer and the attempts to
    restore HA.
  - **Download timeout per try**.

  Saving the Settings page now keeps settings you added to `settings.yaml` by hand.
- **Version check.** The side menu shows the version of the project files and of the installed
  upgrade tool under **Environment**. If the tool is older, a red warning at the top of every page
  says to run the setup again. The installation check (`gui\smoke_test.py`) has a matching new
  check, *CLI matches the project files*.
- **Help → What's new** in the side menu shows this page inside the GUI.
- **`pan-os-upgrade settings`** (CLI) asks for the download timeout.

### Improved

- **Upgrade tracker.** It recognizes the new messages: download and snapshot failures (with the
  reason kept), *HA peer not ready*, *HA peer not upgraded*, and HA restored. It shows each member's
  HA peer state. The HA suspended banner only lists members that are still suspended.
- **Failed devices in batch runs.** The run's log ends with a line naming every device that
  didn't finish.
- **Documentation.** The HA guide (`gui/README.md`), the workflow guide (`gui/WORKFLOW.md`) and the
  install guides now describe the new behavior, the new settings and the update steps.

### Behavior changes to know before your first run

- **You no longer need to restore HA by hand after a run.** Still check `show high-availability
  state` afterwards. If a member couldn't be restored, the log says *Failed to restore HA state to
  functional* and the tracker lists it.
- **A failed pre-upgrade snapshot stops the device.** Before, it was skipped and the upgrade went
  ahead. To upgrade without snapshots, turn them off in Settings.
- **The batch run exits with code 1 if any device stopped**, including a device already on the
  target version. The GUI then shows *Failed (exit 1)* even though the other devices completed.
  Check the Upgrade tracker for the per-device results.
- **Members left suspended by the previous version won't be upgraded.** Make them functional first
  (see [UPGRADING.md](UPGRADING.md)).
- **The inventory order no longer matters.** You don't need to list standbys before actives.

### Not in this release

- **No automatic HA sync.** An HA pair that's out of sync still only produces a warning. The tool
  doesn't sync configuration, and round 2 doesn't wait for *synchronized* (a pair on two different
  releases may never report it). It only waits for the upgraded peer to be passive. Keep using your
  own sync step before the run.
- **No automatic cleanup of old images.** Free disk space beforehand, for example with your existing
  scripts or `delete software version <version>`.
- **Peers on different versions that both still need the upgrade** can be upgraded at the same time.
  Get both members onto the same version first, or upgrade them one at a time (see the HA guide,
  [Peers on different versions](README.md#peers-on-different-versions)).
- **Stopping the whole run** with **Stop** doesn't restore HA on devices that were mid-upgrade.
  Check them afterwards.
- **The export is CSV, not a native `.xlsx` file.** Excel opens it directly. A native `.xlsx` would
  need an extra package in the offline install bundle.

### Packages

No package versions changed in this release (`gui/requirements-cli.txt` and
`gui/requirements-gui.txt` are the same as in the previous release). An existing `wheelhouse`
folder or Nexus setup works as before.
