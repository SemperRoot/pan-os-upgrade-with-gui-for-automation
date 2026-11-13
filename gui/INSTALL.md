# Installing the PAN-OS Upgrade Console (Windows or Linux, online or offline)

The CLI and the GUI run natively on **Windows** (10, 11, Server 2019, Server 2022) and **Linux**.
For a step-by-step Windows walkthrough, see [WINDOWS.md](WINDOWS.md). They also work on air-gapped networks: packages can come from an internal PyPI
mirror (Nexus, Artifactory) or from a folder of files you copy in.

> **Tested on:** Windows Server 2022 with Python 3.11, 3.12.1, 3.12 and 3.13 (online, and offline from
> a wheelhouse with no network), Ubuntu with Python 3.11 to 3.13, and macOS. Every change is tested
> automatically on Windows Server 2022 and Ubuntu by the `Install and smoke test` GitHub workflow.
> Other Windows versions should work the same way but haven't been tested.

After installing, read [WORKFLOW.md](WORKFLOW.md) for how to run upgrades and [README.md](README.md)
for how HA pairs are upgraded.

## Contents

- [What you need](#what-you-need)
- [1. Get the project](#1-get-the-project)
- [2. Install](#2-install)
- [3. Check the installation](#3-check-the-installation)
- [4. Start the GUI](#4-start-the-gui)
- [Updating](#updating)
- [Troubleshooting](#troubleshooting)
- [What gets installed](#what-gets-installed)

## What you need

| | |
|---|---|
| **Python 3.11, 3.12 or 3.13** | Windows: the python.org installer (any install location; the `py` launcher is used if present). Linux: the distribution's `python3.11`/`python3.12` package with `venv` and `pip`. Python 3.12 is the most tested. |
| **One of these package sources** | (a) Internet access to PyPI, (b) an internal PyPI mirror such as Nexus, or (c) a "wheelhouse" folder [downloaded elsewhere](#c-no-network-at-all-wheelhouse-folder). |
| **About 300 MB of disk space** | For the two virtual environments (plus about 40 MB for a wheelhouse, if used). |
| **Network access to the firewalls/Panorama** | HTTPS (443) from this machine to each device's management address. |

No administrator rights are needed once Python is installed. Nothing is installed outside the
project folder.

## 1. Get the project

Download the project as a ZIP from GitHub (**Code → Download ZIP**) or from your internal Git
server, and extract it, for example to `C:\pan-os-upgrade` or `~/pan-os-upgrade`.

Don't reuse a project folder copied from another computer that already has `.venv-cli` or
`gui/.venv` in it. The installer detects and rebuilds environments that can't work here, but a clean
copy is simplest.

## 2. Install

Open **Command Prompt** (Windows) or a terminal (Linux) in the project folder. Then pick the line
for your package source.

> **Don't run `pip install -r requirements.txt` by hand** for the GUI setup. The installer creates
> the two separate environments the CLI and GUI need, with the right versions.

### (a) Internet access, or pip already configured for your mirror

If `pip install` already works on this machine (because of a `pip.ini` / `pip.conf` file or
the `PIP_INDEX_URL` variable pointing at your mirror), the installer uses the same settings.

```bat
gui\setup.cmd
```

```bash
bash gui/setup-linux.sh
```

### (b) Internal PyPI mirror (Nexus, Artifactory)

Pass the mirror's **PyPI proxy URL** (the address ends in `/simple` for most mirrors):

```bat
gui\setup.cmd --index-url https://nexus.example.local/repository/pypi-proxy/simple
```

```bash
bash gui/setup-linux.sh --index-url https://nexus.example.local/repository/pypi-proxy/simple
```

If the mirror uses a certificate from an internal CA that Python doesn't trust, add the CA to pip
once, then run the installer again:

```bat
py -3 -m pip config set global.cert C:\path\to\internal-ca.pem
```

All packages are installed from pre-built wheels for Windows and Linux, so nothing is compiled
and no C compiler is needed. The mirror must allow these packages, and their dependencies:
`nicegui`, `pan-os-python`, `panos-upgrade-assurance`, `pydantic`, `typer`, `reportlab`,
`pillow`, `cryptography`, `poetry-core`. The exact versions are in
[requirements-cli.txt](requirements-cli.txt) and [requirements-gui.txt](requirements-gui.txt).

### (c) No network at all: wheelhouse folder

**On a machine with internet access**, running the **same operating system and the same Python
minor version** as the offline machine (for example Windows with Python 3.12), extract the project
and run:

```bat
py -3 gui\install.py --download wheelhouse
```

This fills a `wheelhouse` folder (about 80 files, 40 MB) inside the project. Copy the whole project
folder, including `wheelhouse`, to the offline machine and run there:

```bat
gui\setup.cmd --wheelhouse wheelhouse
```

```bash
bash gui/setup-linux.sh --wheelhouse wheelhouse
```

With `--wheelhouse`, pip doesn't contact any index at all.

### Choosing the Python version

On Windows the installer uses the `py` launcher (newest Python 3), otherwise `python` from the
PATH. On Linux it picks the newest of `python3.14` … `python3.11`. To choose a specific one, set
`PAN_OS_PYTHON` first:

```bat
set PAN_OS_PYTHON="C:\Program Files\Python312\python.exe"
gui\setup.cmd
```

```bash
PAN_OS_PYTHON=/usr/bin/python3.12 bash gui/setup-linux.sh
```

The installer ends with **Setup complete** when everything worked.

## 3. Check the installation

This runs a few checks without touching any real device. It takes under a minute.

```bat
gui\.venv\Scripts\python.exe gui\smoke_test.py
```

```bash
gui/.venv/bin/python gui/smoke_test.py
```

Every line should start with `PASS`. One check briefly tries to reach `192.0.2.1`, an address
reserved for documentation that never answers, to show that the password typed in the GUI reaches
the CLI.

## 4. Start the GUI

```bat
gui\start-gui.cmd
```

```bash
bash gui/start-gui.sh
```

Open <http://localhost:8080> in a browser on the same machine. Keep the window open while you use
the GUI, and press **Ctrl+C** in it to stop. On Windows you can also double-click
`gui\start-gui.cmd` in File Explorer.

The GUI listens only on `127.0.0.1`, so other machines can't reach it and Windows Firewall doesn't
prompt. To use another port, set `PAN_OS_GUI_PORT` first (`set PAN_OS_GUI_PORT=8081` on Windows,
`PAN_OS_GUI_PORT=8081 bash gui/start-gui.sh` on Linux).

The GUI loads nothing from the internet; all its web assets are included in the installed packages.

### Using the CLI directly

The CLI is installed too, if you prefer the command line:

```bat
.venv-cli\Scripts\pan-os-upgrade.exe --help
```

```bash
.venv-cli/bin/pan-os-upgrade --help
```

## Updating

Replace the project files with the new version (keep `gui/workspace`, which holds your settings,
inventory, logs and backups), then run the same install command again. It reuses the existing
environments and only installs what changed.

## Troubleshooting

| Message | Fix |
|---------|-----|
| `Python wasn't found` | Install Python 3.11 or later, or set `PAN_OS_PYTHON` to the full path of `python.exe` / `python3.12`. |
| `Python 3.x is too old` | The `py` launcher or `python3` points at an old Python. Set `PAN_OS_PYTHON` to a 3.11+ Python. |
| `No module named 'imp'` while installing **pathtools** | You ran `pip install -r requirements.txt` from an old copy of the project. Get the current version and use the installer above. |
| `pip couldn't download a package` / `No matching distribution found` | pip can't reach a package source. Check the `--index-url`, the mirror's allow-list, or use a wheelhouse. Run `py -3 -m pip config list` to see pip's current settings. |
| `SSL: CERTIFICATE_VERIFY_FAILED` | Your mirror's certificate isn't trusted. See the `pip config set global.cert` command under [(b)](#b-internal-pypi-mirror-nexus-artifactory). |
| `A package is missing from …wheelhouse` | The wheelhouse was downloaded on a different OS or Python minor version. Download it again on a matching machine. |
| `The CLI's packages conflict` | Delete the `.venv-cli` folder and run the installer again. |
| The menu in the GUI says **CLI not found** | Run the installer. If the CLI is installed elsewhere, set `PAN_OS_UPGRADE_PYTHON` to that environment's Python. |
| `address already in use` / `error while attempting to bind` | The GUI is already running, or another program uses port 8080. Close it or use another port (see [4](#4-start-the-gui)). |
| `Running scripts is disabled on this system` | That's PowerShell's execution policy. The installer doesn't use PowerShell scripts: run `gui\setup.cmd` from **Command Prompt** instead. |

## What gets installed

Everything stays inside the project folder:

| Folder | Contents |
|--------|----------|
| `.venv-cli` | The `pan-os-upgrade` CLI with the packages pinned in [requirements-cli.txt](requirements-cli.txt). |
| `gui/.venv` | The GUI ([NiceGUI](https://nicegui.io)) with the packages in [requirements-gui.txt](requirements-gui.txt). |
| `gui/workspace` | Created on first use: settings, inventory, logs, reports and backups from GUI runs. |

They're separate so the CLI's pinned older packages (for example `click` 8.1.x, which its `typer` 0.9
needs) never constrain the GUI's web server packages, or the other way round.
To uninstall, delete the project folder.
