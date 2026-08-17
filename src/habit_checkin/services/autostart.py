# -*- coding: utf-8 -*-
"""开机自启：通过 Windows「启动」文件夹快捷方式实现（可选功能）。

打包态（exe）快捷方式直接指向 exe；开发态指向 pythonw.exe -m habit_checkin。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from habit_checkin.services.powershell import run_powershell_script

APP_NAME = "习惯打卡"
LNK_NAME = APP_NAME + ".lnk"

_SHORTCUT_SCRIPT = (
    "$ws = New-Object -ComObject WScript.Shell\n"
    "$lnk = $ws.CreateShortcut($args[0])\n"
    "$lnk.TargetPath = $args[1]\n"
    "$lnk.Arguments = $args[2]\n"
    "$lnk.WorkingDirectory = $args[3]\n"
    "$lnk.IconLocation = $args[1] + ', 0'\n"
    "$lnk.Description = 'habit checkin autostart'\n"
    "$lnk.Save()\n"
)

_READ_SCRIPT = (
    "$ws = New-Object -ComObject WScript.Shell\n"
    "$lnk = $ws.CreateShortcut($args[0])\n"
    "Write-Output $lnk.TargetPath\n"
)


def _startup_dir() -> Path:
    base = (
        os.environ.get("APPDATA")
        or os.environ.get("USERPROFILE")
        or str(Path.home())
    )
    return Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def shortcut_path() -> Path:
    return _startup_dir() / LNK_NAME


def _current_target():
    """返回 (目标程序, 参数, 工作目录)。"""
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable)
        return str(exe), "", str(exe.parent)
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    if not pythonw.is_file():
        pythonw = exe
    # src/habit_checkin/services/autostart.py -> 项目根目录
    root = Path(__file__).resolve().parents[3]
    return str(pythonw), "-m habit_checkin", str(root)


def _run_powershell(script, *args):
    """通过临时 .ps1 + -File 传参运行 PowerShell。

    -Command 会把后续参数拼进命令串（中文路径会被误解析），
    因此改用 -File 并借助 $args 传参，与打包脚本保持一致。
    """
    return run_powershell_script(script, *args, timeout=20)


def is_enabled() -> bool:
    """启动快捷方式存在且指向当前运行目标时视为已启用。"""
    p = shortcut_path()
    if not p.is_file():
        return False
    target, _, _ = _current_target()
    proc = _run_powershell(_READ_SCRIPT, p)
    if proc is None:
        # 无法读取时退化为「存在即启用」
        return True
    lines = [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip()]
    if not lines:
        return False
    return lines[-1].lower() == target.lower()


def enable() -> bool:
    """创建（或覆盖）启动文件夹快捷方式。"""
    target, args, workdir = _current_target()
    try:
        _startup_dir().mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    proc = _run_powershell(_SHORTCUT_SCRIPT, shortcut_path(), target, args, workdir)
    return proc is not None and proc.returncode == 0


def disable() -> bool:
    """删除启动文件夹快捷方式。"""
    p = shortcut_path()
    if not p.is_file():
        return True
    try:
        p.unlink()
        return True
    except OSError:
        return False
