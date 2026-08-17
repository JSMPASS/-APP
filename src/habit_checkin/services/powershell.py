"""PowerShell 临时脚本执行公共层：统一编码、超时与无窗口参数。"""
from __future__ import annotations

import os
import subprocess
import tempfile


def run_powershell_script(script, *args, timeout=20):
    """把 script 写入临时 .ps1 后调用 powershell -File 执行，返回 CompletedProcess 或 None。"""
    fd, ps1 = tempfile.mkstemp(suffix=".ps1")
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig") as f:
            f.write(script)
        cmd = [
            "powershell.exe", "-NoProfile", "-NonInteractive",
            "-ExecutionPolicy", "Bypass", "-File", ps1,
        ]
        cmd.extend(str(a) for a in args)
        try:
            return subprocess.run(
                cmd, capture_output=True, timeout=timeout,
                creationflags=0x08000000,  # CREATE_NO_WINDOW
                text=True, encoding="utf-8", errors="replace",
            )
        except Exception:
            return None
    finally:
        try:
            os.unlink(ps1)
        except OSError:
            pass
