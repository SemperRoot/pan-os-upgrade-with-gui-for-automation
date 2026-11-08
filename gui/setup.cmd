@echo off
rem Installs the pan-os-upgrade CLI and the PAN-OS Upgrade Console on Windows. No WSL needed.
rem
rem   gui\setup.cmd                          packages from pip's configured index (e.g. a Nexus mirror)
rem   gui\setup.cmd --index-url URL          packages from this index instead
rem   gui\setup.cmd --wheelhouse wheelhouse  offline, from a folder made with --download
rem   gui\setup.cmd --download wheelhouse    only download the packages (on a machine with internet)
rem
rem Uses the "py" launcher, or "python" on the PATH. To pick a specific Python, set PAN_OS_PYTHON first:
rem   set PAN_OS_PYTHON="C:\Program Files\Python312\python.exe"
rem Safe to run again, for example after updating the project files.
setlocal
set "PYTHON="
if defined PAN_OS_PYTHON set "PYTHON=%PAN_OS_PYTHON%"
if not defined PYTHON (
    where py >nul 2>&1 && set "PYTHON=py -3"
)
if not defined PYTHON (
    where python >nul 2>&1 && set "PYTHON=python"
)
if not defined PYTHON (
    echo.
    echo ERROR: Python wasn't found. Install Python 3.11 or later ^(3.12 recommended^) from python.org,
    echo        or set PAN_OS_PYTHON to the full path of python.exe, then run this again.
    set "RC=1"
    goto :end
)

%PYTHON% "%~dp0install.py" %*
set "RC=%ERRORLEVEL%"

:end
rem Keep the window open when started by double-clicking, so the result can be read
echo %CMDCMDLINE% | find /i "%~f0" >nul && pause
exit /b %RC%
