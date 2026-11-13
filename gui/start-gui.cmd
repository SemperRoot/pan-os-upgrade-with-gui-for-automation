@echo off
rem Starts the PAN-OS Upgrade Console on Windows. Run gui\setup.cmd once first.
rem Then open http://localhost:8080 in your web browser. Press Ctrl+C in this window to stop it.
rem To use another port:  set PAN_OS_GUI_PORT=8081  before running this.
setlocal
set "GUI_PYTHON=%~dp0.venv\Scripts\python.exe"
set "CLI_PYTHON=%~dp0..\.venv-cli\Scripts\python.exe"
if not defined PAN_OS_GUI_PORT set "PAN_OS_GUI_PORT=8080"

if not exist "%GUI_PYTHON%" (
    echo ERROR: The GUI isn't installed. Run first:  "%~dp0setup.cmd"
    goto :failed
)
if not defined PAN_OS_UPGRADE_PYTHON if not exist "%CLI_PYTHON%" (
    echo ERROR: The CLI isn't installed. Run first:  "%~dp0setup.cmd"
    goto :failed
)

echo.
echo   PAN-OS Upgrade Console
echo   Open http://localhost:%PAN_OS_GUI_PORT% in your web browser.
echo   Keep this window open while you use the GUI. Press Ctrl+C here to stop it.
echo.
cd /d "%~dp0.."
"%GUI_PYTHON%" "%~dp0gui.py"
exit /b %ERRORLEVEL%

:failed
echo %CMDCMDLINE% | find /i "%~f0" >nul && pause
exit /b 1
