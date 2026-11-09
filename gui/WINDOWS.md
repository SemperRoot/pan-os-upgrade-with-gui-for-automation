# Installing the PAN-OS Upgrade Console on Windows

A step-by-step guide for people who haven't used a command window before. It takes 15 to 30
minutes, most of it waiting for downloads.

When you're done, you'll open the GUI in a browser on the same machine at `http://localhost:8080`.
Everything runs directly on Windows: Windows 10, Windows 11, Windows Server 2019 and Windows
Server 2022. It also works on networks without internet access.

After installing, read [WORKFLOW.md](WORKFLOW.md) for how to run upgrades and [README.md](README.md)
for how HA pairs are upgraded. [INSTALL.md](INSTALL.md) is a shorter reference covering Windows and
Linux.

> **How this guide was tested.** The installer, self-check and start script were run on Windows
> Server 2022 with Python 3.12.1 installed in `C:\Program Files\Python312`, both with internet access
> and fully offline from a downloaded package folder. They're also tested automatically on Windows
> Server 2022 with Python 3.11 to 3.13 every time the project changes. If a step doesn't match what
> you see, note the exact message and check [Troubleshooting](#troubleshooting).

## Contents

- [Before you start](#before-you-start)
- [Command Prompt basics: read this first](#command-prompt-basics-read-this-first)
- [Part 1: Install Python](#part-1-install-python)
- [Part 2: Get the project](#part-2-get-the-project)
- [Part 3: Run the setup](#part-3-run-the-setup)
- [Part 4: Check the installation](#part-4-check-the-installation)
- [Part 5: Start the GUI](#part-5-start-the-gui)
- [Every day after that](#every-day-after-that)
- [Updating to a newer version](#updating-to-a-newer-version)
- [Where your files are](#where-your-files-are)
- [Troubleshooting](#troubleshooting)
- [What gets installed](#what-gets-installed)

## Before you start

| You need | Notes |
|----------|-------|
| Windows 10 or 11, or Windows Server 2019 or 2022 | Press **Windows key + R**, type `winver`, press **Enter** to check. |
| Python 3.11, 3.12 or 3.13 | Part 1 explains how to install it. If it's already installed, Part 1 shows how to check. |
| A source for Python packages | One of: internet access, your organization's internal PyPI mirror (for example Nexus or Artifactory), or a package folder downloaded on another machine. See [Part 3](#part-3-run-the-setup). |
| The project files | As a ZIP from GitHub or your internal Git server (Part 2). The GitHub repository `SemperRoot/pan-os-upgrade-with-gui-for-automation` is private: ask its owner to invite your GitHub account, then accept the email invitation. |
| A web browser on the same machine | Edge, Chrome or Firefox. The GUI only accepts connections from the machine it runs on. |
| HTTPS access to the firewalls and Panorama | From this machine to each device's management address (port 443). |
| About 500 MB of free disk space | |

Administrator rights are only needed if Python isn't installed yet and you install it for all
users. The project itself installs into its own folder and changes nothing else on the machine.

**Don't copy a project folder that was already set up on another computer.** Start from a fresh ZIP
(Part 2). The setup can repair a copied folder, but it's the most common source of problems.

## Command Prompt basics: read this first

All commands in this guide go into **Command Prompt**, Windows' standard command window. Don't use
PowerShell for them.

**Opening Command Prompt in the project folder** (the easiest way, used throughout this guide):

1. Open the project folder in **File Explorer**, for example `C:\pan-os-upgrade`.
2. Click in the **address bar** at the top, where the folder path is shown.
3. Type `cmd` and press **Enter**.

A black window opens, with a line ending in `>` that shows the folder, for example:

```
C:\pan-os-upgrade>
```

How to work in Command Prompt:

- **Run one command at a time.** Copy a command from this guide, paste it into the window, press
  **Enter**, and wait until the line ending in `>` comes back before running the next one.
- **Pasting:** press **Ctrl + V**, or right-click in the window.
- **Copying text from the window:** select it with the mouse, then press **Enter** or right-click.
- **Ctrl + C does not copy here.** It stops whatever is running.
- **Copy commands exactly**, including spaces and backslashes (`\`).

## Part 1: Install Python

### 1.1 Check whether Python is already installed

Open Command Prompt (Start menu → type `cmd` → **Command Prompt**) and run:

```bat
py --version
```

- If it shows **Python 3.11**, **3.12** or **3.13**, Python is ready. Go to [Part 2](#part-2-get-the-project).
- If it shows an older version, such as **Python 3.10**, or says `'py' is not recognized`, continue
  with 1.2.

### 1.2 Download the installer

On a machine with internet access, go to **<https://www.python.org/downloads/windows/>** and download
the **Windows installer (64-bit)** for the latest **Python 3.12** release. Python 3.11 and 3.13 work
too.

On an offline network, copy the installer file (for example `python-3.12.10-amd64.exe`) to the
machine on a USB drive or through your usual file transfer process. Your IT team may also already
provide Python through software distribution.

### 1.3 Run the installer

1. Double-click the installer.
2. At the bottom of the first screen, tick **Add python.exe to PATH**.
3. Choose one:
   - **Install Now** installs for your user only and needs no administrator rights.
   - **Customize installation** → **Next** → tick **Install Python for all users** → **Install**
     installs to `C:\Program Files\Python312` for everyone. This needs administrator rights.
4. When it says **Setup was successful**, click **Close**.

### 1.4 Check it

Open a **new** Command Prompt window (a window opened before the install doesn't see Python yet) and
run:

```bat
py --version
```

**You should see** `Python 3.12.x` (or the version you installed).

## Part 2: Get the project

### 2.1 Download the ZIP

1. In a browser, sign in to GitHub and open
   **<https://github.com/SemperRoot/pan-os-upgrade-with-gui-for-automation>**, or open the project on
   your internal Git server.
2. Click the green **Code** button, then **Download ZIP**.

On an offline network, download the ZIP on a connected machine and transfer it the same way as the
Python installer.

### 2.2 Unblock and extract it

1. In File Explorer, right-click the ZIP file and choose **Properties**. If there's an **Unblock**
   checkbox at the bottom, tick it and click **OK**. This stops Windows from showing security
   warnings for every file inside.
2. Right-click the ZIP again, choose **Extract All...**, type `C:\` as the destination, and click
   **Extract**.
3. In File Explorer, go to `C:\`. Rename the new folder (named like
   `pan-os-upgrade-with-gui-for-automation-main`) to **`pan-os-upgrade`**.

A short path such as `C:\pan-os-upgrade` avoids problems with Windows' path length limit. Any folder
you can write to works, but avoid very long paths and folders synced by OneDrive or Google Drive.

### 2.3 Check the folder

Open `C:\pan-os-upgrade` in File Explorer. **You should see** these items, among others:

```
gui    pan_os_upgrade    LICENSE    pyproject.toml    README.md
```

If you see a single folder instead, the project is one level too deep: see
[Problems in Part 2](#problems-in-part-2).

## Part 3: Run the setup

The setup creates two private Python environments inside the project folder, installs the right
package versions into them, and checks that everything starts. It never changes your system Python.

1. Open Command Prompt in `C:\pan-os-upgrade`. Type `cmd` in File Explorer's address bar, as
   described in [Command Prompt basics](#command-prompt-basics-read-this-first).
2. Run **one** of the commands below, depending on where Python packages come from on your network.

**Internet access, or pip is already set up for your organization's mirror:**

```bat
gui\setup.cmd
```

**Your organization's PyPI mirror (Nexus, Artifactory):** ask IT for the mirror's PyPI proxy address
(it usually ends in `/simple`) and use it in place of the example:

```bat
gui\setup.cmd --index-url https://nexus.example.local/repository/pypi-proxy/simple
```

**No network at all:** use a package folder made on another machine, as described in
[Installing without any network](#installing-without-any-network) below:

```bat
gui\setup.cmd --wheelhouse wheelhouse
```

What to expect:

- It takes **3 to 10 minutes**. Lines starting with `==>` are the steps; `OK:` means a step worked.
- Don't close the window while it runs.

**When it works, the end looks like this:**

```
==> Installing the CLI into .venv-cli (takes a few minutes)
    OK: pan-os-upgrade installed: C:\pan-os-upgrade\.venv-cli

==> Installing the GUI into gui/.venv
    OK: GUI installed: C:\pan-os-upgrade\gui\.venv

==> Setup complete
    Start the GUI with:

        "C:\pan-os-upgrade\gui\start-gui.cmd"

    Then open http://localhost:8080 in your web browser.
```

If it stops with a red **ERROR** line, read the message under it; it says what to do. Then see
[Problems in Part 3](#problems-in-part-3). You can run the setup again as often as needed.

**Don't run `pip install -r requirements.txt` yourself.** The setup creates the separate
environments the CLI and the GUI need, with the right versions.

### Installing without any network

This needs a second Windows machine **with internet access** and the **same Python minor version**
(for example 3.12 on both).

1. On the connected machine, extract the project ZIP and open Command Prompt in its folder, as in
   Parts 2 and 3.
2. Run:

   ```bat
   py -3 gui\install.py --download wheelhouse
   ```

   It creates a folder named `wheelhouse` inside the project, with about 80 files (about 40 MB).
3. Copy the **whole project folder**, including `wheelhouse`, to the offline machine, for example
   to `C:\pan-os-upgrade`.
4. On the offline machine, run `gui\setup.cmd --wheelhouse wheelhouse` as shown above.

With `--wheelhouse`, the setup doesn't try to contact any server.

### Choosing a specific Python

The setup uses the newest Python found by the `py` command. To use a particular installation
instead, set `PAN_OS_PYTHON` in the same window before running the setup, for example:

```bat
set PAN_OS_PYTHON="C:\Program Files\Python312\python.exe"
gui\setup.cmd
```

## Part 4: Check the installation

This runs a few quick checks without contacting any real firewall. In the same Command Prompt
window, run:

```bat
gui\.venv\Scripts\python.exe gui\smoke_test.py
```

**You should see** six lines starting with `PASS`, ending with:

```
6 of 6 checks passed.
```

One check briefly tries to reach `192.0.2.1`. That address is reserved for documentation and never
answers. The check uses it to confirm that a password typed in the GUI reaches the upgrade tool. If
any line says `FAIL`, see [Problems in Part 4](#problems-in-part-4).

## Part 5: Start the GUI

In the same Command Prompt window, run:

```bat
gui\start-gui.cmd
```

You can also double-click `start-gui.cmd` in the `C:\pan-os-upgrade\gui` folder.

**You should see:**

```
  PAN-OS Upgrade Console
  Open http://localhost:8080 in your web browser.
  Keep this window open while you use the GUI. Press Ctrl+C here to stop it.
```

Your browser usually opens by itself. If it doesn't:

1. Open Edge, Chrome or Firefox on the same machine.
2. Go to **<http://localhost:8080>**.

At the bottom of the left-hand menu, under **Environment**, check that it says **CLI available**.

**Keep the Command Prompt window open** while you use the GUI. Closing it stops the GUI. To stop the
GUI on purpose, click the window and press **Ctrl + C**, then answer `Y` if asked
`Terminate batch job (Y/N)?`. Don't do this during an upgrade; see
[WORKFLOW.md](WORKFLOW.md#stopping-a-run).

You're done. Continue with [WORKFLOW.md](WORKFLOW.md).

## Every day after that

Double-click `C:\pan-os-upgrade\gui\start-gui.cmd`, then open **<http://localhost:8080>** if the
browser doesn't open by itself.

**Optional shortcut:** right-click `start-gui.cmd` → **Show more options** (Windows 11 only) →
**Send to** → **Desktop (create shortcut)**. You can then start the GUI from the desktop.

## Updating to a newer version

Your settings, inventory, run history, reports and backups are all in `gui\workspace` and are kept.

1. Download and unblock the new ZIP as in [Part 2](#part-2-get-the-project).
2. Rename the current folder `C:\pan-os-upgrade` to `C:\pan-os-upgrade-old`.
3. Extract the new ZIP to `C:\` and rename the new folder to `pan-os-upgrade`.
4. Move the `workspace` folder from `C:\pan-os-upgrade-old\gui` into `C:\pan-os-upgrade\gui`.
5. Run the setup again ([Part 3](#part-3-run-the-setup)) with the same command as before. For an
   offline install, make a new `wheelhouse` folder for the new version first.

Once the new version works, you can delete `C:\pan-os-upgrade-old`.

## Where your files are

Everything the GUI creates is in `C:\pan-os-upgrade\gui\workspace`: reports (including PDFs), logs,
configuration backups, settings and the inventory. Open that folder in File Explorer as usual.
[WORKFLOW.md](WORKFLOW.md#where-the-gui-keeps-things) lists which file is where.

## Troubleshooting

### Problems in Part 1

| What you see | What to do |
|--------------|------------|
| `'py' is not recognized as an internal or external command` | Python isn't installed, or was installed without the `py` launcher. Install it as in Part 1.3, then open a **new** Command Prompt window. |
| `py --version` shows Python 3.10 or older | Install Python 3.12 (Part 1). Older versions can stay installed; `py` uses the newest one. |
| The installer says you need administrator rights | Choose **Install Now** (for your user only), or ask IT to install Python for all users. |
| Python opens the Microsoft Store | That's a Windows shortcut, not real Python. Install Python from python.org as in Part 1, or use `py` instead of `python`. |

### Problems in Part 2

| What you see | What to do |
|--------------|------------|
| GitHub shows **404 This is not the web page you are looking for** | Your GitHub account doesn't have access, or you aren't signed in. Ask the owner for an invitation, accept it from the email, and sign in. |
| `C:\pan-os-upgrade` contains a single folder instead of `gui`, `README.md` and so on | The project ended up one level too deep. Open that inner folder, select everything inside (**Ctrl + A**), cut it (**Ctrl + X**), go back up to `C:\pan-os-upgrade`, paste (**Ctrl + V**), then delete the now-empty inner folder. |
| Windows shows a security warning every time you open a file from the project | The ZIP wasn't unblocked before extracting. Delete the folder, unblock the ZIP (Part 2.2), and extract it again. |
| `Path too long` or `destination path too long` while extracting | Extract to `C:\` as described, not into a deep folder. |

### Problems in Part 3

| What you see | What to do |
|--------------|------------|
| `'gui\setup.cmd' is not recognized` | Command Prompt isn't open in the project folder. Run `cd /d C:\pan-os-upgrade` and try again. |
| `ERROR: Python wasn't found` | See Problems in Part 1. To use a specific installation, set `PAN_OS_PYTHON` as described in [Choosing a specific Python](#choosing-a-specific-python). |
| `ERROR: Python 3.x is too old` | `py` found an old Python. Install Python 3.12, or set `PAN_OS_PYTHON` to a newer one. |
| `pip couldn't download a package`, `No matching distribution found`, or downloads time out | pip can't reach a package source. Check the `--index-url` address with IT, or use the offline method. To see pip's current settings, run `py -3 -m pip config list`. |
| `SSL: CERTIFICATE_VERIFY_FAILED` | Your mirror or proxy uses a certificate that Python doesn't trust. Get the certificate file (`.pem`) from IT and run `py -3 -m pip config set global.cert C:\path\to\certificate.pem`, then run the setup again. |
| Downloads fail with `proxy` errors | Your network needs a proxy. Ask IT for its address and set it in the same window before running the setup, for example `set HTTPS_PROXY=http://proxy.example.local:8080`. |
| `A package is missing from ...wheelhouse` | The `wheelhouse` folder was made with a different Python version or on a different operating system. Make it again on a Windows machine with the same Python minor version. |
| No module named `imp` while installing **pathtools** | You ran `pip install -r requirements.txt` from an old copy of the project. Get a current copy and use `gui\setup.cmd`. |
| `The CLI's packages conflict` | Delete the `.venv-cli` folder inside the project and run the setup again. |
| `Running scripts is disabled on this system` | You ran the setup from PowerShell. Use **Command Prompt** instead; the setup doesn't use PowerShell scripts. |

### Problems in Part 4

| What you see | What to do |
|--------------|------------|
| `The system cannot find the path specified` | The setup didn't finish. Run it again (Part 3) and check that it ends with **Setup complete**. |
| `FAIL  CLI is installed` or `FAIL  CLI starts` | Run the setup again. If it still fails, copy the lines under the `FAIL` line and send them to the project owner. |
| `FAIL  GUI web server starts` | Another program may be using the port. Close other copies of the GUI and run the check again. |
| Any other `FAIL` | Copy the whole output and send it to the project owner. |

### Problems in Part 5

| What you see | What to do |
|--------------|------------|
| `ERROR: The GUI isn't installed` or `The CLI isn't installed` | Run the setup (Part 3) first, and check that it ends with **Setup complete**. |
| The menu says **CLI not found** | The CLI isn't in `C:\pan-os-upgrade\.venv-cli`. Run the setup again. If you installed the CLI somewhere else, set `PAN_OS_UPGRADE_PYTHON` to that environment's `Scripts\python.exe` before starting the GUI. |
| `http://localhost:8080` doesn't load | Check that the Command Prompt window is still open and shows the GUI's messages. Try **<http://127.0.0.1:8080>**. Use a browser on the same machine; the GUI doesn't accept connections from other computers. |
| `error while attempting to bind on address` or `address already in use` | The GUI is already running in another window, or another program uses port 8080. Close the other window, or use another port: run `set PAN_OS_GUI_PORT=8081`, then `gui\start-gui.cmd`, and open `http://localhost:8081`. |
| The GUI works, but firewalls or Panorama can't be reached | Test from Command Prompt with `curl.exe -k https://FIREWALL-ADDRESS`. An HTML reply means the device is reachable. If it times out, check routing and firewall rules between this machine and the devices' management addresses. |
| Windows Defender Firewall asks whether to allow Python | Click **Cancel** or allow it for **Private networks** only. The GUI only listens on this machine and doesn't need network access from others. Outgoing connections to firewalls work either way. |

## What gets installed

| Where | What |
|-------|------|
| `C:\pan-os-upgrade\.venv-cli` | The `pan-os-upgrade` CLI with the 32 packages pinned in [`requirements-cli.txt`](requirements-cli.txt), including `pan-os-python`, `panos-upgrade-assurance`, `typer` 0.9.4 and `click` 8.1.8. |
| `C:\pan-os-upgrade\gui\.venv` | The GUI's packages from [`requirements-gui.txt`](requirements-gui.txt): `nicegui` 3.18.0 and `PyYAML` 6.0.3, plus their own dependencies. |
| `C:\pan-os-upgrade\gui\workspace` | Created on first use: your settings, inventory, logs, reports and backups. |

The CLI and the GUI use separate environments, and nothing is installed into the system Python or
anywhere else on the machine. To uninstall, delete the project folder (keep `gui\workspace` first if
you want your reports and backups).

**Using the CLI directly.** The CLI is installed too, if you prefer the command line:

```bat
.venv-cli\Scripts\pan-os-upgrade.exe --help
```

**Installing by hand** (only if you can't use the setup), in Command Prompt in the project folder:

```bat
py -3 -m venv .venv-cli
.venv-cli\Scripts\python.exe -m pip install -r gui\requirements-cli.txt
.venv-cli\Scripts\python.exe -m pip install --no-deps .
py -3 -m venv gui\.venv
gui\.venv\Scripts\python.exe -m pip install -r gui\requirements-gui.txt
```

Install the CLI from `requirements-cli.txt`. A plain `pip install .` pulls a newer `click` that
breaks every CLI command.
