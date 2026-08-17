@echo off
setlocal
cd /d "%~dp0"

set "PY=python.exe"
if exist "%~dp0venv\Scripts\python.exe" set "PY=%~dp0venv\Scripts\python.exe"

echo [1/3] 安装 PyInstaller（需要联网，请稍候）...
"%PY%" -m pip install --upgrade pyinstaller
if errorlevel 1 (
  echo [错误] PyInstaller 安装失败，请检查网络后重试。
  pause
  exit /b 1
)

"%PY%" build.py
if errorlevel 1 (
  echo [错误] 构建失败，请查看上方输出。
  pause
  exit /b 1
)

echo.
echo 构建完成！桌面已生成「习惯打卡」快捷方式。
pause
endlocal
