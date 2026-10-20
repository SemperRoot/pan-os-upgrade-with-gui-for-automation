# Installing the PAN-OS Upgrade Console on Windows

This guide installs the GUI and the `pan-os-upgrade` CLI on a Windows PC. Once it's running, see
[WORKFLOW.md](WORKFLOW.md) for how to run upgrades and [README.md](README.md) for how HA pairs are upgraded.

**Run it inside WSL2** (Windows Subsystem for Linux) and open it in your normal Windows browser.
On native Windows the GUI starts, but upgrade runs don't work (see
[Why not native Windows](#why-not-native-windows)).

> **Tested on macOS, not on Windows.** The install steps below were run on a clean copy of the
> repository on macOS, which uses the same code path as WSL2. Every pinned package was confirmed
> to have prebuilt Linux x86-64 wheels for Python 3.12, the version Ubuntu 24.04 ships.

## Requirements

### Windows

| Requirement | Details |
|-------------|---------|
| Windows version | Windows 11, or Windows 10 version 2004 (build 19041) or later. Check with `winver`. |
| Administrator rights | Needed once, to install WSL2. On a managed PC, IT may need to do this step. |
| Virtualization | Enabled in the BIOS/UEFI. Task Manager → Performance → CPU shows **Virtualization: Enabled**. |
| WSL2 with **Ubuntu 24.04** | Ubuntu 24.04 ships Python 3.12. Older Ubuntu releases ship Python 3.10, which is too old. |
| Web browser | Any current Edge, Chrome or Firefox on Windows. |
| Network access | From the PC to the management interfaces of the firewalls and Panorama on HTTPS (443), plus internet access to download packages during installation. |
| Disk space | About 1 GB for Ubuntu and the Python packages. |

### Inside Ubuntu (WSL2)

| Package | Why |
|---------|-----|
| `python3` (3.11 or later; 3.12 on Ubuntu 24.04) | Runs the GUI and the CLI. |
| `python3-venv` | Creates the two virtual environments. |
| `python3-pip` | Installs the Python packages. |

### Python packages

The GUI and the CLI each get their own virtual environment. The exact versions are pinned in two
files in this folder, copied from the working macOS setup:

| File | Installs into | Contents |
|------|---------------|----------|
| [`requirements-gui.txt`](requirements-gui.txt) | `gui/.venv` | `nicegui==3.18.0`, `PyYAML==6.0.3`. These are the only third-party packages `gui.py` imports. pip adds their own dependencies (FastAPI, uvicorn and others). |
| [`requirements-cli.txt`](requirements-cli.txt) | `.venv-cli` | All 32 packages the CLI needs, pinned. The main ones: `pan-os-python==1.13.1`, `panos-upgrade-assurance==1.5.1`, `pydantic==2.14.1`, `typer==0.9.4`, `click==8.1.8`, `dynaconf==3.3.5`, `reportlab==4.5.1`. |

**Install the CLI from `requirements-cli.txt`, not from `pyproject.toml` alone.** A plain
`pip install .` currently pulls click 8.5.0, which breaks typer 0.9.4: every command crashes
with `TypeError: Parameter.make_metavar() missing 1 required positional argument`. The pinned file
keeps click on 8.1.8.

## Step 1: Install WSL2 and Ubuntu

In PowerShell **as Administrator**:

```powershell
wsl --install -d Ubuntu-24.04
```

Restart when asked. Then open **Ubuntu 24.04** from the Start menu and create a Linux username and
password. This doesn't have to match your Windows account.

## Step 2: Install Python

In the Ubuntu terminal:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
python3 --version    # must show 3.11 or later
```

## Step 3: Copy the project into Ubuntu

Keep the project in your Linux home folder, not under `/mnt/c/`. Files under `/mnt/c/` are slow
to access from WSL. Replace the Windows path with where the folder is on your PC:

```bash
cp -r /mnt/c/Users/<you>/pan-os-upgrade-main ~/pan-os-upgrade
cd ~/pan-os-upgrade
```

**Remove the copied virtual environments.** They were created on macOS and don't work anywhere
else. In this copy, the `pan_os_upgrade/` folder is both the CLI's source code and a virtual
environment, so remove only the virtual-environment parts:

```bash
rm -rf gui/.venv
rm -rf pan_os_upgrade/bin pan_os_upgrade/lib pan_os_upgrade/include
rm -f  pan_os_upgrade/pyvenv.cfg pan_os_upgrade/.gitignore
```

That `.gitignore` was created by Python's venv tool and contains `*`. The source files stay:
`__init__.py`, `main.py`, `components/`, `models/` and `assets/`.

## Step 4: Install the CLI

```bash
cd ~/pan-os-upgrade
python3 -m venv .venv-cli
.venv-cli/bin/pip install -r gui/requirements-cli.txt
.venv-cli/bin/pip install --no-deps .
```

Check the installation:

```bash
.venv-cli/bin/pip check                # expect: No broken requirements found.
.venv-cli/bin/pan-os-upgrade --help    # expect: batch, firewall, inventory, panorama, settings
```

## Step 5: Install the GUI

```bash
python3 -m venv gui/.venv
gui/.venv/bin/pip install -r gui/requirements-gui.txt
```

## Step 6: Tell the GUI where the CLI is

The GUI looks for the CLI at `pan_os_upgrade/bin/pan-os-upgrade` by default, which was removed in
step 3. Point it at the new location, and make the setting permanent:

```bash
echo 'export PAN_OS_UPGRADE_BIN="$HOME/pan-os-upgrade/.venv-cli/bin/pan-os-upgrade"' >> ~/.bashrc
source ~/.bashrc
```

## Step 7: Start the GUI

```bash
cd ~/pan-os-upgrade
gui/.venv/bin/python gui/gui.py
```

Leave this terminal open; closing it stops the GUI. The GUI tries to open a browser inside WSL,
which may print a warning or do nothing. Open **<http://localhost:8080>** in your Windows browser.

Check the **Environment** section at the bottom of the side menu. It should show **CLI available**.
If it shows **CLI not found**, run `echo $PAN_OS_UPGRADE_BIN` in the terminal and check the path.

To stop the GUI, press **Ctrl+C** in the terminal. Don't do this while an upgrade is running; see
[WORKFLOW.md](WORKFLOW.md#stopping-a-run).

## Optional: your saved GUI data

`gui/workspace/` holds the GUI's settings, inventory, logs, run history and upgrade reports. It was
copied in step 3, so your settings come with it. To start clean instead:

```bash
rm -rf ~/pan-os-upgrade/gui/workspace
```

## Updating later

After copying a newer version of the project into `~/pan-os-upgrade`, reinstall the CLI so the
virtual environment picks up the changed code:

```bash
cd ~/pan-os-upgrade
.venv-cli/bin/pip install -r gui/requirements-cli.txt
.venv-cli/bin/pip install --no-deps --force-reinstall .
gui/.venv/bin/pip install -r gui/requirements-gui.txt
```

Changes to `gui/gui.py` take effect the next time you start the GUI.

## Troubleshooting

| Problem | What to try |
|---------|-------------|
| `wsl --install` fails or says virtualization is disabled | Enable virtualization (Intel VT-x or AMD-V) in the BIOS/UEFI, or ask IT. |
| `python3 --version` shows 3.10 | You're on an older Ubuntu. Install Ubuntu 24.04: `wsl --install -d Ubuntu-24.04`. |
| `pan-os-upgrade --help` crashes with `make_metavar` | click was upgraded. Run `.venv-cli/bin/pip install "click==8.1.8"`. |
| **CLI not found** in the side menu | `PAN_OS_UPGRADE_BIN` isn't set in the terminal that started the GUI. Run `source ~/.bashrc` and start the GUI again. |
| `localhost:8080` doesn't load in the Windows browser | Make sure the GUI is still running in the Ubuntu terminal. If it is, turn on mirrored networking: create `C:\Users\<you>\.wslconfig` containing `[wsl2]` and `networkingMode=mirrored` on separate lines, run `wsl --shutdown` in PowerShell, then open Ubuntu again. |
| Firewalls or Panorama are unreachable from the GUI, but reachable from Windows | WSL2 traffic goes through Windows networking, and some corporate VPNs block it. Test from Ubuntu with `curl -k https://<firewall>`. Mirrored networking (above) often fixes VPN problems. |
| `pip install` fails with SSL or proxy errors | Your network needs a proxy. Set it first: `export https_proxy=http://<proxy>:<port>`. |
| Port 8080 is already in use | Start with another port: `PAN_OS_GUI_PORT=8081 gui/.venv/bin/python gui/gui.py`, then open `localhost:8081`. |

## Why not native Windows

The GUI's pages load on native Windows, but upgrade runs depend on macOS/Linux features. These
parts were in the original GUI too; the redesign didn't add them.

| Feature | On native Windows |
|---------|-------------------|
| Password | The GUI passes the password to the CLI through standard input. On Windows, Python's hidden password prompt reads from the keyboard instead, so runs are expected to **wait forever at the password prompt**. |
| Live upgrades | The confirmation dialog runs the `ps` command to look for other running CLI processes. `ps` doesn't exist on Windows, so **the dialog can't finish loading and a live upgrade can't start**. |
| Stop button | Uses process-group signals that don't exist on Windows, so **Stop doesn't work**. |
| CLI location | Windows puts the CLI in `Scripts\pan-os-upgrade.exe`, so `PAN_OS_UPGRADE_BIN` must be set. |
| Log output | The CLI logs emoji. Without `PYTHONUTF8=1`, Python on Windows may drop those log lines. |

Making native Windows work would need changes to both the GUI and how the CLI receives the
password. Until then, use WSL2. On native Windows you can still use the CLI directly in PowerShell,
where you type the password at the prompt. The CLI hasn't been tested on Windows either.
