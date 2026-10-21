# Installing the PAN-OS Upgrade Console on Windows

A step-by-step guide for people who haven't used Linux or a terminal before. It takes 30 to 45
minutes, most of it waiting for downloads.

When you're done, you'll open the GUI in your normal Windows browser at `http://localhost:8080`.
It runs inside **WSL2** (Windows Subsystem for Linux), a small Ubuntu Linux system built into
Windows. The GUI doesn't run upgrades correctly on Windows directly (see
[Why not directly on Windows](#why-not-directly-on-windows)).

After installing, read [WORKFLOW.md](WORKFLOW.md) for how to run upgrades and [README.md](README.md)
for how HA pairs are upgraded.

> **How this guide was tested.** The setup and start scripts were tested on macOS, including a
> fresh download, a re-run, and a project folder copied from another computer. Ubuntu 24.04's
> package versions were checked against Ubuntu's package archive, and the Windows commands against
> Microsoft's WSL documentation. The guide hasn't been run end to end on a Windows PC yet. If a step
> doesn't match what you see, note the exact message and check [Troubleshooting](#troubleshooting).

## Contents

- [Before you start](#before-you-start)
- [Terminal basics: read this first](#terminal-basics-read-this-first)
- [Part 1: Install WSL and Ubuntu](#part-1-install-wsl-and-ubuntu)
- [Part 2: Get the project into Ubuntu](#part-2-get-the-project-into-ubuntu)
- [Part 3: Run the setup script](#part-3-run-the-setup-script)
- [Part 4: Start the GUI](#part-4-start-the-gui)
- [Every day after that](#every-day-after-that)
- [Updating to a newer version](#updating-to-a-newer-version)
- [Finding your files from Windows](#finding-your-files-from-windows)
- [Troubleshooting](#troubleshooting)
- [What gets installed](#what-gets-installed)
- [Why not directly on Windows](#why-not-directly-on-windows)

## Before you start

| You need | How to check |
|----------|--------------|
| Windows 11, or Windows 10 version 2004 (build 19041) or later | Press **Windows key + R**, type `winver`, press **Enter**. |
| Administrator rights on the PC, once | You can open programs with **Run as administrator**. On a company PC, IT may need to do Part 1 for you. |
| Virtualization turned on | **Ctrl + Shift + Esc** opens Task Manager → **Performance** → **CPU**. It should say **Virtualization: Enabled**. |
| A GitHub account with access to the project | The repository `SemperRoot/pan-os-upgrade-with-gui-for-automation` is private. Ask its owner to invite you (repository **Settings → Collaborators → Add people**), then accept the email invitation. |
| Internet access | To download Ubuntu and the Python packages. |
| About 2 GB of free disk space | |

**Don't copy the project folder from a Mac or another PC.** Always get it from GitHub (Part 2). A
copied folder contains files made for the other computer. The setup script can clean those up,
but it's the most common source of problems.

## Terminal basics: read this first

You'll type commands into two different windows. Each step says which one.

| Window | What it is | How to open it |
|--------|------------|----------------|
| **PowerShell** | Windows' own command window. Only used in Part 1. | Start menu → type `PowerShell`. |
| **Ubuntu** | The Linux command window. Used for everything else. | Start menu → type `Ubuntu` → **Ubuntu 24.04**. |

How to work in these windows:

- **Run one command at a time.** Copy a command from this guide, paste it into the window, press
  **Enter**, and wait until the line ending in `$` comes back before running the next one. In
  Ubuntu that line looks like `jane@DESKTOP-AB12CD:~$`.
- **Pasting:** right-click in the window, or press **Ctrl + Shift + V**. Plain **Ctrl + V** works in
  newer Windows versions; if it types `^V` instead, use right-click.
- **Copying text from the window:** select it with the mouse, then press **Ctrl + Shift + C** or
  right-click.
- **Ctrl + C does not copy in these windows.** It stops whatever is running.
- **Passwords stay invisible.** When Ubuntu asks for your password, nothing appears as you type,
  not even dots. Type it and press **Enter**.
- **`~` means your Linux home folder**, for example `/home/jane`.
- **Capital letters and spaces matter.** Copy commands exactly.

## Part 1: Install WSL and Ubuntu

### 1.1 Open PowerShell as administrator

1. Open the **Start** menu and type `PowerShell`.
2. Right-click **Windows PowerShell** and choose **Run as administrator**.
3. Click **Yes** when Windows asks for permission.

### 1.2 Install WSL with Ubuntu 24.04

**In PowerShell (administrator):**

```powershell
wsl --install -d Ubuntu-24.04
```

It downloads and installs for a few minutes. When it says changes take effect after a reboot,
**restart the PC**.

- If the command only prints help text, WSL is already installed. Run it again exactly as shown,
  with `-d Ubuntu-24.04`.
- If the progress stays at 0.0%, close the window, open PowerShell as administrator again, and run:
  `wsl --install --web-download -d Ubuntu-24.04`

### 1.3 Create your Ubuntu user

After the restart, an Ubuntu window usually opens by itself. If not: **Start** menu → type
`Ubuntu` → **Ubuntu 24.04**.

1. Wait while it says it's installing. This happens only the first time.
2. When asked for a **username**, type a short name in lowercase with no spaces, for example
   `jane`, and press **Enter**.
3. When asked for a **password**, type one and press **Enter**. Nothing appears while you type.
   Type it again to confirm.

**Write this password down.** Ubuntu asks for it when installing software. It doesn't need to match
your Windows password.

**You should now see** a line like:

```
jane@DESKTOP-AB12CD:~$
```

### 1.4 Check that it's WSL version 2

Open a normal **PowerShell** window (not administrator) and run:

```powershell
wsl -l -v
```

**You should see** `Ubuntu-24.04` with `2` in the **VERSION** column. If it shows `1`, run:

```powershell
wsl --set-version Ubuntu-24.04 2
```

## Part 2: Get the project into Ubuntu

The project has to live **inside Ubuntu's own folders**, not just in your Windows Downloads
folder. Pick **one** option. Option A is recommended because updating later is a single command.

### Option A (recommended): download with the GitHub command-line tool

**In Ubuntu**, run these one at a time. The first one asks for your Ubuntu password.

```bash
sudo apt update
```

```bash
sudo apt install -y git gh
```

Log in to GitHub:

```bash
gh auth login
```

It asks a few questions. Use the arrow keys and **Enter** to choose:

| Question about | Choose |
|----------------|--------|
| Which GitHub / account | **GitHub.com** |
| Preferred protocol | **HTTPS** |
| Authenticate Git with your GitHub credentials | **Yes** (press **Enter**) |
| How to authenticate | **Login with a web browser** |

It then shows a **one-time code** like `ABCD-1234`.

1. Write the code down, or select it and press **Ctrl + Shift + C**.
2. Press **Enter**. On WSL the browser often doesn't open by itself. If nothing opens, go to
   **<https://github.com/login/device>** in your Windows browser.
3. Sign in to GitHub if asked, enter the code, and click **Authorize**.

Back in Ubuntu it should say **Logged in as** your GitHub username.

Download the project:

```bash
gh repo clone SemperRoot/pan-os-upgrade-with-gui-for-automation ~/pan-os-upgrade
```

Now go to [Check the download](#check-the-download).

### Option B: download a ZIP file

**In your Windows browser:**

1. Sign in to GitHub and open
   **<https://github.com/SemperRoot/pan-os-upgrade-with-gui-for-automation>**.
2. Click the green **Code** button, then **Download ZIP**. The file
   `pan-os-upgrade-with-gui-for-automation-main.zip` lands in your **Downloads** folder.

**Move the ZIP into Ubuntu.** In **Ubuntu**, run:

```bash
cd ~
```

```bash
explorer.exe .
```

Don't miss the dot at the end. A **File Explorer** window opens showing your Ubuntu home folder.
Drag the ZIP file from your **Downloads** folder into that window.

If a file ending in `:Zone.Identifier` appears next to the ZIP, ignore it. Windows adds it, and
it's harmless.

**Unzip it.** In **Ubuntu**, run these one at a time:

```bash
sudo apt update
```

```bash
sudo apt install -y unzip
```

```bash
unzip -q ~/pan-os-upgrade-with-gui-for-automation-main.zip -d ~
```

```bash
mv ~/pan-os-upgrade-with-gui-for-automation-main ~/pan-os-upgrade
```

If `mv` succeeds, it prints nothing. If a `pan-os-upgrade` folder already existed from an earlier
attempt, see [the project is inside another folder](#the-project-is-inside-another-folder).

### Check the download

**In Ubuntu:**

```bash
ls ~/pan-os-upgrade
```

**You should see** these names, among others:

```
LICENSE  README.md  gui  pan_os_upgrade  pyproject.toml  ...
```

If you see a single folder name instead, or `No such file or directory`, fix it before
continuing: see [Problems in Part 2](#problems-in-part-2).

## Part 3: Run the setup script

### 3.1 Install the US English locale

The upgrade's readiness checks need Ubuntu's US English locale (`en_US.UTF-8`) to read dates in
firewall output. WSL's Ubuntu often doesn't include it, and without it runs stop with
`unsupported locale setting`.

**In Ubuntu**, run these one at a time. The first one may ask for your Ubuntu password.

```bash
sudo apt install -y locales
```

```bash
sudo locale-gen en_US.UTF-8
```

**You should see** `en_US.UTF-8... done` and then `Generation complete.` If the first command says
`Unable to locate package locales`, run `sudo apt update` and try again.

### 3.2 Run the setup script

The script installs everything and checks each step, including the locale from 3.1. It works from
any folder.

**In Ubuntu:**

```bash
bash ~/pan-os-upgrade/gui/setup-wsl.sh
```

- It may ask for your **Ubuntu password**, which stays invisible while you type.
- It takes **3 to 10 minutes**. Lines starting with `==>` are the steps; `OK:` means a step worked.
- Don't close the window while it runs.

**When it works, the end looks like this:**

```
==> Installing the CLI into .venv-cli (takes a few minutes)
    OK: pan-os-upgrade installed: /home/jane/pan-os-upgrade/.venv-cli/bin/pan-os-upgrade

==> Installing the GUI into gui/.venv
    OK: GUI installed: /home/jane/pan-os-upgrade/gui/.venv

==> Setup complete
    Start the GUI with:

        bash /home/jane/pan-os-upgrade/gui/start-gui.sh
```

If it stops with a red **ERROR** line, read the message under it; it says what to do. Then see
[Problems in Part 3](#problems-in-part-3). You can run the script again as often as needed.

## Part 4: Start the GUI

**In Ubuntu:**

```bash
bash ~/pan-os-upgrade/gui/start-gui.sh
```

**You should see:**

```
  PAN-OS Upgrade Console
  Open http://localhost:8080 in your web browser.
  Keep this window open while you use the GUI. Press Ctrl+C here to stop it.
```

A message about not being able to open a browser may follow; that's normal on WSL.

1. Open your normal Windows browser (Edge, Chrome or Firefox).
2. Go to **<http://localhost:8080>**.
3. At the bottom of the left-hand menu, under **Environment**, check that it says **CLI available**.

**Keep the Ubuntu window open** while you use the GUI. Closing it stops the GUI. To stop the GUI on
purpose, click the Ubuntu window and press **Ctrl + C**. Don't do this during an upgrade; see
[WORKFLOW.md](WORKFLOW.md#stopping-a-run).

You're done. Continue with [WORKFLOW.md](WORKFLOW.md).

## Every day after that

1. **Start** menu → **Ubuntu 24.04**.
2. Run:

   ```bash
   bash ~/pan-os-upgrade/gui/start-gui.sh
   ```

3. Open **<http://localhost:8080>**.

**Optional shortcut.** Run this once:

```bash
echo "alias pan-gui='bash ~/pan-os-upgrade/gui/start-gui.sh'" >> ~/.bashrc
```

Close and reopen Ubuntu. From then on, typing `pan-gui` starts the GUI.

## Updating to a newer version

Your settings, inventory, run history and reports in `gui/workspace/` are kept in both options.

**If you used Option A (GitHub tool):**

```bash
cd ~/pan-os-upgrade
```

```bash
git pull
```

```bash
bash ~/pan-os-upgrade/gui/setup-wsl.sh
```

**If you used Option B (ZIP):** download the new ZIP and drag it into your Ubuntu home folder as
before. Then run these one at a time. They set the old folder aside, unpack the new one, and move
your saved data across:

```bash
mv ~/pan-os-upgrade ~/pan-os-upgrade-old
```

```bash
unzip -q ~/pan-os-upgrade-with-gui-for-automation-main.zip -d ~
```

```bash
mv ~/pan-os-upgrade-with-gui-for-automation-main ~/pan-os-upgrade
```

```bash
mv ~/pan-os-upgrade-old/gui/workspace ~/pan-os-upgrade/gui/
```

```bash
bash ~/pan-os-upgrade/gui/setup-wsl.sh
```

Once the new version works, you can delete `~/pan-os-upgrade-old` and the ZIP.

## Finding your files from Windows

Reports (PDFs), logs and configuration backups are inside Ubuntu at
`~/pan-os-upgrade/gui/workspace/`. To open that folder in File Explorer, run in Ubuntu:

```bash
explorer.exe ~/pan-os-upgrade/gui/workspace
```

Or type this in File Explorer's address bar, replacing `jane` with your Ubuntu username:

```
\\wsl.localhost\Ubuntu-24.04\home\jane\pan-os-upgrade\gui\workspace
```

[WORKFLOW.md](WORKFLOW.md#where-the-gui-keeps-things) lists which file is where.

## Troubleshooting

### Problems in Part 1

| What you see | What to do |
|--------------|------------|
| A message about enabling **Virtual Machine Platform** or virtualization in the BIOS, or error `0x80370102` | Virtualization is off. It's turned on in the PC's BIOS/UEFI settings (often called **Intel VT-x**, **Intel Virtualization Technology** or **AMD-V/SVM**). On a company PC, ask IT. |
| `WslRegisterDistribution failed with error: 0x8007019e` | WSL isn't enabled yet. Run `wsl --install -d Ubuntu-24.04` in PowerShell **as administrator**, then restart the PC. |
| `wsl --install` only prints help text | WSL is already installed. Run `wsl --install -d Ubuntu-24.04` exactly as shown. |
| Install stuck at 0.0% | Run `wsl --install --web-download -d Ubuntu-24.04` in PowerShell as administrator. |
| `wsl -l -v` shows VERSION `1` | Run `wsl --set-version Ubuntu-24.04 2`. |
| You forgot your Ubuntu password | In PowerShell, run `wsl -d Ubuntu-24.04 -u root passwd jane`, replacing `jane` with your Ubuntu username, and set a new one. |
| Pasting types `^V` | Right-click to paste, or press **Ctrl + Shift + V**. |

### Problems in Part 2

| What you see | What to do |
|--------------|------------|
| `gh: command not found` | Run `sudo apt update`, then `sudo apt install -y git gh`. |
| `E: Unable to locate package gh` | Run `sudo apt update` first. If it still fails, check you installed **Ubuntu 24.04** (`lsb_release -a`). |
| The browser didn't open during `gh auth login` | Normal on WSL. Open <https://github.com/login/device> in your Windows browser and enter the code. |
| `GraphQL: Could not resolve to a Repository` or `repository not found` | Your GitHub account doesn't have access, or you logged in with a different account. Run `gh auth status` to see which account is logged in, and ask the owner for an invitation (then accept it from the email). |
| `fatal: destination path '/home/jane/pan-os-upgrade' already exists` | An earlier attempt left a folder. Set it aside with `mv ~/pan-os-upgrade ~/pan-os-upgrade-old`, then run the clone command again. |
| `unzip: cannot find or open ...zip` | The ZIP isn't in your Ubuntu home folder, or has a different name. Run `ls ~/*.zip` to see what's there. If it was downloaded twice, Windows may have named it `...-main (1).zip`. |
| `cannot stat` or `No such file or directory` after `mv` | The unzipped folder has a different name. Run `ls ~` and use the name you see. |
| `ls ~/pan-os-upgrade` says `No such file or directory` | The project isn't in the expected place. Run `ls ~` to see what's in your home folder, then redo Option A or B. |

#### The project is inside another folder

If `ls ~/pan-os-upgrade` shows a **single folder name** instead of `README.md`, `gui` and so on, the
project ended up one level too deep. This happens when `pan-os-upgrade` already existed when you ran
`mv`. Fix it by setting the folders aside and moving the inner one into place:

```bash
mv ~/pan-os-upgrade ~/pan-os-upgrade-outer
```

```bash
ls ~/pan-os-upgrade-outer
```

Note the folder name that appears, then run the next command with that name in place of `NAME`:

```bash
mv ~/pan-os-upgrade-outer/NAME ~/pan-os-upgrade
```

Check again with `ls ~/pan-os-upgrade`.

### Problems in Part 3

| What you see | What to do |
|--------------|------------|
| `bash: /home/jane/pan-os-upgrade/gui/setup-wsl.sh: No such file or directory` | The project isn't at `~/pan-os-upgrade`, or it's an old copy from before the setup script existed. Run `ls ~/pan-os-upgrade/gui`. If `setup-wsl.sh` isn't listed, get a fresh copy with Part 2. |
| `ERROR: ... is missing.` | The project folder is incomplete. Get a fresh copy with Part 2. |
| `$'\r': command not found` (or `^M: command not found`), or `set: pipefail` followed by `invalid option name` | The script's line endings were changed to Windows format, usually by opening it in a Windows editor or copying it through Windows. Fix with `sed -i 's/\r$//' ~/pan-os-upgrade/gui/*.sh`, then run the setup again. |
| `Python 3.10 is too old` | You're on an older Ubuntu. Install Ubuntu 24.04 (Part 1.2) and redo the guide inside it. |
| `[sudo] password for jane:` then `Sorry, try again.` | Wrong Ubuntu password. It's the one from Part 1.3, not your Windows password. If forgotten, see Part 1 problems. |
| Package downloads fail with `SSL`, `certificate` or `proxy` errors, or time out | Your network uses a proxy or inspects encrypted traffic, which is common on company networks. Ask IT for the proxy address and set it before running the script, for example `export https_proxy=http://proxy.example.com:8080`. IT may also need to provide a certificate. |
| `error: externally-managed-environment` | You ran `pip install` by hand outside the project's environments. Don't; run the setup script instead. |
| `pan-os-upgrade doesn't start` with `make_metavar` in the message | A wrong `click` version was installed. Run the setup script again; it installs the right one. |
| `ERROR: The en_US.UTF-8 locale isn't available.` | Ubuntu couldn't set up the US English locale that readiness checks need. Run `sudo apt install -y locales`, then `sudo locale-gen en_US.UTF-8`, then run the setup script again. |

### Problems in Part 4

| What you see | What to do |
|--------------|------------|
| `ERROR: The GUI isn't installed` or `The CLI isn't installed` | Run the setup script (Part 3) first, and check that it ends with **Setup complete**. |
| The menu says **CLI not found** | You started `gui.py` directly instead of using `start-gui.sh`. Stop it with **Ctrl + C** and use the start command from Part 4. |
| `http://localhost:8080` doesn't load | Check the Ubuntu window is still open and showing the GUI's messages. Try **<http://127.0.0.1:8080>**. If it still fails, see [Mirrored networking](#mirrored-networking). |
| `address already in use` | The GUI is already running in another Ubuntu window, or another program uses port 8080. Close the other window, or start on another port: `PAN_OS_GUI_PORT=8081 bash ~/pan-os-upgrade/gui/start-gui.sh`, then open `http://localhost:8081`. |
| The GUI works, but firewalls or Panorama can't be reached | Test from Ubuntu: `curl -k https://FIREWALL-ADDRESS` (an HTML reply means it's reachable). Company VPNs sometimes block WSL; [mirrored networking](#mirrored-networking) often fixes this. |
| A message about not being able to open a browser | Normal on WSL. Open the address in your Windows browser yourself. |
| A run stops with `generated an exception: unsupported locale setting` | Ubuntu is missing the US English locale that readiness checks need. Setups made before the setup script handled this are affected. Stop the GUI, run the setup script again (Part 3), and start the GUI again. If it's an HA pair, check both firewalls with `show high-availability state` before re-running, and make any member left `suspended` functional again. |

#### Mirrored networking

Mirrored networking makes Ubuntu share Windows' network connection, which fixes most `localhost`
and VPN problems. It needs Windows 11 version 22H2 or later.

1. In File Explorer, go to your Windows user folder (type `%USERPROFILE%` in the address bar).
2. Create a text file named `.wslconfig` (with the dot, no `.txt` at the end) containing:

   ```
   [wsl2]
   networkingMode=mirrored
   ```

3. In PowerShell, run `wsl --shutdown`.
4. Open Ubuntu again and start the GUI.

## What gets installed

| Where | What |
|-------|------|
| Windows | WSL2 and Ubuntu 24.04 (Part 1). |
| Ubuntu system packages | `python3` (3.12), `python3-venv`, `python3-pip`, `git`; plus `gh` (Option A) or `unzip` (Option B). |
| Ubuntu locale | `en_US.UTF-8`, generated with `locale-gen` if missing. The readiness checks switch to it to read dates in firewall output. |
| `~/pan-os-upgrade/.venv-cli` | The `pan-os-upgrade` CLI with the 32 packages pinned in [`requirements-cli.txt`](requirements-cli.txt), including `pan-os-python`, `panos-upgrade-assurance`, `typer` 0.9.4 and `click` 8.1.8. |
| `~/pan-os-upgrade/gui/.venv` | The GUI's packages from [`requirements-gui.txt`](requirements-gui.txt): `nicegui` 3.18.0 and `PyYAML` 6.0.3, plus their own dependencies. |

The CLI and the GUI use separate environments, and nothing is installed into Ubuntu's system Python.

**Installing by hand** (only if you can't use the script), from inside `~/pan-os-upgrade`:

```bash
sudo apt install -y locales && sudo locale-gen en_US.UTF-8
python3 -m venv .venv-cli
.venv-cli/bin/pip install -r gui/requirements-cli.txt
.venv-cli/bin/pip install --no-deps .
python3 -m venv gui/.venv
gui/.venv/bin/pip install -r gui/requirements-gui.txt
```

Install the CLI from `requirements-cli.txt`. A plain `pip install .` pulls a newer `click` that
breaks every CLI command.

## Why not directly on Windows

The GUI's pages load on Windows itself, but upgrades depend on Linux features:

- **The password prompt hangs.** The GUI hands the password to the CLI through standard input, but
  on Windows Python's hidden password prompt reads from the keyboard instead.
- **Live upgrades can't start.** The confirmation dialog uses the Linux `ps` command, which
  doesn't exist on Windows.
- **The Stop button doesn't work.** It uses process signals that Windows doesn't have.

Use WSL2 as described in this guide.
