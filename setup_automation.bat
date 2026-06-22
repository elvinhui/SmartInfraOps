@echo off
setlocal
cd /d "%~dp0"

echo ====================================================
echo Medium Auto Pusher Local Setup
echo ====================================================
echo.

if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
)

echo Installing dependencies...
call .venv\Scripts\activate.bat
pip install -r module_pusher\requirements.txt
playwright install chromium
echo.

if not exist "medium_auth.json" (
    echo Running first-time login...
    python module_pusher\login_medium.py
)

echo.
echo ====================================================
echo Setting up Windows Task Scheduler to run silently
echo every time you log in (on boot)...
echo ====================================================

:: Create a VBS script to run the task completely silently (no console window popping up)
echo Set WshShell = CreateObject("WScript.Shell") > run_silently.vbs
echo WshShell.Run "cmd.exe /c cd /d ""%~dp0"" & call .venv\Scripts\activate.bat & python module_pusher\main.py >> pusher_log.txt 2>&1", 0, False >> run_silently.vbs

:: Add the task to Windows Task Scheduler (runs on user logon)
schtasks /create /tn "SmartInfraOps_Medium_Pusher" /tr "wscript.exe ""%~dp0run_silently.vbs""" /sc onlogon /f

echo.
echo Setup Complete!
echo The pusher will now run silently in the background every time you turn on/log in to your PC.
echo You can check the output in: %~dp0pusher_log.txt
echo.
pause
