# -*- coding: utf-8 -*-
"""应用重启：主题切换等需要重启的场景下，启动新实例并让当前实例随后退出。"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def launch_new_instance():
    """启动一个新的应用实例；成功返回 True，失败返回 False。

    - 打包态：直接再次运行 exe；
    - 开发态：用 pythonw.exe 运行 `python -m habit_checkin`（无黑窗）。
    """
    try:
        if getattr(sys, "frozen", False):
            exe = Path(sys.executable)
            subprocess.Popen([str(exe)], cwd=str(exe.parent),
                             creationflags=0x08000000)  # CREATE_NO_WINDOW
        else:
            root_dir = Path(__file__).resolve().parents[3]  # services -> habit_checkin -> src -> 根目录
            pythonw = Path(sys.executable).with_name("pythonw.exe")
            if not pythonw.is_file():
                pythonw = Path(sys.executable)
            env = os.environ.copy()
            src = str(root_dir / "src")
            env["PYTHONPATH"] = src + (";" + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
            subprocess.Popen(
                [str(pythonw), "-m", "habit_checkin"],
                cwd=str(root_dir), env=env,
                creationflags=0x08000000,  # CREATE_NO_WINDOW
            )
        return True
    except Exception:
        return False
