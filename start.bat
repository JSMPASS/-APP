@echo off
setlocal
cd /d "%~dp0"

set "PY=python.exe"
if exist "%~dp0venv\Scripts\python.exe" set "PY=%~dp0venv\Scripts\python.exe"
set "HABIT_PY=%PY%"
set "HABIT_ROOT=%~dp0"
wscript.exe "%~dp0start_hidden.vbs"
endlocal
