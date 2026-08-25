@echo off
setlocal
cd /d "%~dp0"

set "PY=python.exe"
if exist "%~dp0venv\Scripts\python.exe" set "PY=%~dp0venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [Error] python.exe not found. Please install Python 3 or create a venv.
  pause
  exit /b 1
)

set "HABIT_PY=%PY%"
set "HABIT_ROOT=%~dp0"
wscript.exe "%~dp0start_hidden.vbs"
endlocal
