@echo off
setlocal EnableExtensions
rem Lain Brain: double-click me. First time: makes a private Python environment (.venv) here, installs what Lainframe
rem needs, then starts the setup. After setup: starts Lain Brain in the background. Extra words are passed on, e.g.
rem   LainBrain.bat doctor      LainBrain.bat setup --step 8      LainBrain.bat stop
title Lain Brain
cd /d "%~dp0"
set "LAINBRAIN_BAT=1"

set "PY="
for %%V in (3.12 3.13 3.14) do (
  if not defined PY (
    py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V"
  )
)
if not defined PY (
  python -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo.
  echo   Lain Brain needs Python 3.12 or newer, and it isn't installed yet.
  echo.
  echo   1. Open https://www.python.org/downloads/windows/ and download the latest Python 3.12 or 3.13
  echo      "Windows installer (64-bit)".
  echo   2. Run it. On the FIRST screen tick "Add python.exe to PATH", then click "Install Now".
  echo   3. When it's done, double-click LainBrain.bat again.
  echo.
  start "" "https://www.python.org/downloads/windows/"
  goto :fail
)

if not exist ".venv\Scripts\python.exe" (
  echo   Making Lain Brain's Python environment (.venv^) ...
  %PY% -m venv .venv
  if errorlevel 1 (
    echo   Couldn't create .venv with %PY%.
    goto :fail
  )
)

rem install requirements only when requirements.txt changed since the last successful install
fc /b "requirements.txt" ".venv\requirements.installed" >nul 2>&1
if errorlevel 1 (
  echo   Installing Lain Brain's Python packages (first time: a few minutes^) ...
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q --upgrade pip
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
  if errorlevel 1 (
    echo.
    echo   Installing the packages failed. Check the internet connection and run LainBrain.bat again.
    goto :fail
  )
  copy /y "requirements.txt" ".venv\requirements.installed" >nul
)

".venv\Scripts\python.exe" "brain\lain_brain.py" %*
if errorlevel 1 goto :fail
rem Lain Brain started in the background (other commands already waited for Enter): close after a moment
timeout /t 8 >nul
exit /b 0

:fail
echo.
echo   Something went wrong (see above). This window stays open so you can read it.
pause
exit /b 1
