# Upgrading an existing installation to release 2026-11-23

This page is for machines that already run the PAN-OS Upgrade Console (the native Windows or Linux
install made with `gui\setup.cmd` or `gui/setup-linux.sh`). For a new machine, follow
[WINDOWS.md](WINDOWS.md) or [INSTALL.md](INSTALL.md) instead. See [WHATS_NEW.md](WHATS_NEW.md) for
what changed.

**Time needed:** about 15 minutes, plus a dry run.
**Packages:** unchanged since the previous release. Your Nexus mirror setting or existing
`wheelhouse` folder works as-is; there's no need to download new packages.
**Your data:** settings, inventory, run history, reports and backups (`gui\workspace`) are kept.

> **The one step you can't skip:** run the setup again after replacing the files (step 6). The
> setup copies the upgrade tool into `.venv-cli`. If you only replace the files, the GUI starts with
> the new screens but every run still uses the **old** upgrade tool, without any of the fixes. This
> release adds a check for exactly this: a red warning in the GUI and a `FAIL` line in the
> installation check.

The steps use the Windows paths from [WINDOWS.md](WINDOWS.md) (`C:\pan-os-upgrade`). Linux commands
follow each Windows one.

## 1. Before you start

1. **Let any running upgrade finish**, and close the GUI (press **Ctrl+C** in its window, or close
   the window).
2. **Check your HA pairs for members left suspended by the previous version.** That version never
   made members functional again, and this one won't upgrade a member that's suspended. On each
   member you upgraded with the previous version, run:

   ```
   show high-availability state
   ```

   If it reports `suspended`, return it to service from that member's CLI:

   ```
   request high-availability state functional
   ```

## 2. Get the new version

Download the project ZIP for release 2026-11-23 from your internal Git server. On Windows, right-click
the ZIP → **Properties** → tick **Unblock** → **OK** before extracting, as in
[WINDOWS.md Part 2](WINDOWS.md#part-2-get-the-project).

## 3. Keep the old folder as a fallback

Rename the current folder, so you can switch back if needed:

```bat
ren C:\pan-os-upgrade pan-os-upgrade-old
```

```bash
mv ~/pan-os-upgrade ~/pan-os-upgrade-old
```

## 4. Extract the new version in its place

Extract the ZIP and rename the extracted folder so the project is at `C:\pan-os-upgrade` again
(`~/pan-os-upgrade` on Linux). Check that `C:\pan-os-upgrade\gui\setup.cmd` exists.

## 5. Copy your data into the new folder

From `C:\pan-os-upgrade-old`, copy these into the same place in `C:\pan-os-upgrade`:

| Copy | Why |
|------|-----|
| `gui\workspace` (whole folder) | Settings, inventory, run history, reports, logs and backups. |
| `gui\.nicegui` (whole folder, if it exists) | Optional: the values remembered in the GUI's forms (hostnames, usernames, target versions). Passwords are never stored. |
| `wheelhouse` (whole folder, offline installs only) | The package folder the setup installs from. It still matches this release. |
| `settings.yaml`, `inventory.yaml` (only if you run `pan-os-upgrade` directly from the project folder) | The CLI reads them from the folder you run it in. |

In Command Prompt:

```bat
robocopy C:\pan-os-upgrade-old\gui\workspace C:\pan-os-upgrade\gui\workspace /E
robocopy C:\pan-os-upgrade-old\gui\.nicegui C:\pan-os-upgrade\gui\.nicegui /E
robocopy C:\pan-os-upgrade-old\wheelhouse C:\pan-os-upgrade\wheelhouse /E
```

`robocopy` prints an error for a source folder that doesn't exist (for example `wheelhouse` on an
online install, or `.nicegui` if the GUI never saved form values). That's fine. On Linux:

```bash
cp -a ~/pan-os-upgrade-old/gui/workspace ~/pan-os-upgrade/gui/
cp -a ~/pan-os-upgrade-old/gui/.nicegui ~/pan-os-upgrade/gui/ 2>/dev/null
cp -a ~/pan-os-upgrade-old/wheelhouse ~/pan-os-upgrade/ 2>/dev/null
```

Don't copy `.venv-cli` or `gui\.venv`; the setup creates them in the next step.

## 6. Run the setup again (required)

Open Command Prompt in `C:\pan-os-upgrade` and run the **same** setup command as for the first
install, for example:

```bat
gui\setup.cmd --index-url https://nexus.example.local/repository/pypi-proxy/simple
```

or, offline:

```bat
gui\setup.cmd --wheelhouse wheelhouse
```

If you set `PAN_OS_PYTHON` for the first install (for example to
`"C:\Program Files\Python312\python.exe"`), set it again in this window first. On Linux, use
`bash gui/setup-linux.sh` with the same options.

It ends with **Setup complete**.

## 7. Check the installation

```bat
gui\.venv\Scripts\python.exe gui\smoke_test.py
```

```bash
gui/.venv/bin/python gui/smoke_test.py
```

All **7** checks must pass. The new one is:

```
PASS  CLI matches the project files
      version 1.3.11+gui.2026.11.23
```

If it says `FAIL`, step 6 didn't complete. Run it again.

## 8. Start the GUI and confirm the version

Start the GUI with `gui\start-gui.cmd` (`bash gui/start-gui.sh` on Linux) and open
<http://localhost:8080>. At the bottom of the side menu, under **Environment**, both lines must read
`1.3.11+gui.2026.11.23`:

```
Project 1.3.11+gui.2026.11.23
CLI 1.3.11+gui.2026.11.23
```

There must be **no** red *installed CLI is older* warning at the top of the page.

## 9. Review the new settings

Open **Configuration → Settings → Retry policy**. These rows are new:

| Setting | Default | What it does |
|---------|---------|--------------|
| Snapshots: interval / max tries | 60 s / 3 | Snapshot attempts per device. When they run out before the upgrade, the device stops before anything changes. |
| HA sync: interval / max tries | 60 s / 3 | Round 2's wait for the upgraded peer, and the attempts to make a suspended member functional again. |
| Download timeout per try | 3600 s | A download that hasn't finished in this time counts as a failed try. Raise it if images come over a slow link. |

The Download interval and max tries were shown before but ignored by the tool; they're now used.

Click **Save settings** once, even if you change nothing, so the new values are written to
`gui\workspace\settings.yaml`. If you don't, the defaults above apply anyway.

**If you run the CLI directly** with your own `settings.yaml`, you can add the new keys by hand
(all optional):

```yaml
download:
  max_tries: 3
  retry_interval: 60
  timeout: 3600
ha_sync:
  max_tries: 3
  retry_interval: 60
snapshots:
  max_tries: 3
  retry_interval: 60
```

## 10. Dry run before the next production run

Run a **dry run** on a small batch that includes at least one HA pair and one standalone firewall.
You should see:

- the passive member's checks in round 1, and the active member's checks in round 2 (*Revisiting
  firewalls...*), and
- no HA suspension on any member. Dry runs never suspend HA.

Then read [WHATS_NEW.md → Behavior changes](WHATS_NEW.md#behavior-changes-to-know-before-your-first-run).
In particular, **HA is now restored automatically**, so any manual "make functional" step in your
own runbook becomes a check instead.

## Switching back to the previous version

Close the GUI, then swap the folders back:

```bat
ren C:\pan-os-upgrade pan-os-upgrade-new
ren C:\pan-os-upgrade-old pan-os-upgrade
```

The old folder still has its own working installation, so nothing needs reinstalling. Copy back
`gui\workspace` if you want to keep runs made with the new version. Remember that the previous
version doesn't restore HA after a run.

Once the new version works, you can delete `C:\pan-os-upgrade-old`.
