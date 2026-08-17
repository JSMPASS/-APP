@echo off
setlocal
cd /d "%~dp0"

set "PY=python.exe"
if exist "%~dp0venv\Scripts\python.exe" set "PY=%~dp0venv\Scripts\python.exe"

set "PYTHONPATH=%~dp0src"
echo Using Python: %PY%
"%PY%" -m habit_checkin
echo.
echo App exited with code %ERRORLEVEL%
pause
endlocal
