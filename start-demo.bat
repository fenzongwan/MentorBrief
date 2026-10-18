@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_CMD=python"
where python >nul 2>nul
if not errorlevel 1 goto python_ready

set "PYTHON_CMD=py -3"
where py >nul 2>nul
if not errorlevel 1 goto python_ready

set "PYTHON_CMD="%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe""
if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" goto python_ready

echo Python not found. Install Python 3.10+ and enable "Add Python to PATH".
pause
exit /b 1

:python_ready

set "ROOT_DB=%~dp0data\weflow-assistant.db"
set "LOCAL_DB=%LOCALAPPDATA%\MentorBrief\data\weflow-assistant.db"

if exist "%ROOT_DB%" goto start_app
if exist "%LOCAL_DB%" goto start_app

echo Initializing demo data...
%PYTHON_CMD% seed_demo.py
if errorlevel 1 (
  echo Initialization failed.
  pause
  exit /b 1
)

:start_app
start "" /min powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 1; Start-Process 'http://127.0.0.1:8765'"
%PYTHON_CMD% server.py
pause
