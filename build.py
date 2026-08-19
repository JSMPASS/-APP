"""构建脚本：全新初始化数据 → PyInstaller 打包目录版 exe → 生成桌面快捷方式。

用法：python build.py（或双击 build.bat，会自动安装 PyInstaller）。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
DIST = ROOT / "dist"
NAME = "习惯打卡"
ICON = ROOT / "assets" / "icon.ico"
RES = SRC / "habit_checkin" / "resources"


def fresh_init():
    """全新初始化：清空开发态 data（用户已确认）。"""
    data = ROOT / "data"
    data.mkdir(parents=True, exist_ok=True)
    for name in ("app.db", "app.log"):
        p = data / name
        if p.is_file():
            p.unlink()
    imgs = data / "images"
    if imgs.is_dir():
        shutil.rmtree(imgs)
    imgs.mkdir(parents=True, exist_ok=True)
    print("[1/3] data 已全新初始化")


def close_running_app():
    """打包前关闭正在运行的应用（dist 数据文件被占用会导致打包失败）。"""
    try:
        subprocess.run(
            ["taskkill", "/IM", "习惯打卡.exe", "/F"],
            capture_output=True, timeout=15,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
        import time
        time.sleep(1)
    except Exception:
        pass


def build():
    tcl = ROOT / "runtime" / "tcl" / "tcl8.6"
    tk = ROOT / "runtime" / "tcl" / "tk8.6"
    if (tcl / "init.tcl").is_file():
        os.environ.setdefault("TCL_LIBRARY", str(tcl))
        if (tk / "tk.tcl").is_file():
            os.environ.setdefault("TK_LIBRARY", str(tk))
    close_running_app()
    if DIST.exists():
        shutil.rmtree(DIST)
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--windowed", "--onedir",
        "--name", NAME,
        "--icon", str(ICON),
        "--paths", str(SRC),
        "--add-data", "{};resources".format(RES),
        str(SRC / "habit_checkin" / "__main__.py"),
    ]
    print("[2/3] 运行 PyInstaller ...")
    print("  " + " ".join(str(x) for x in cmd))
    subprocess.run(cmd, check=True)
    exe = DIST / NAME / (NAME + ".exe")
    if not exe.is_file():
        raise SystemExit("未找到打包产物: " + str(exe))
    print("[3/3] 打包完成:", exe)
    create_shortcut(exe)


def create_shortcut(exe):
    """在桌面创建快捷方式。ps1 脚本为纯 ASCII，中文路径通过命令行参数传入（避免编码乱码）。"""
    ps1 = ROOT / "build" / "make_shortcut.ps1"
    ps1.parent.mkdir(parents=True, exist_ok=True)
    script = (
        "$ws = New-Object -ComObject WScript.Shell\n"
        "$lnk = $ws.CreateShortcut($args[2])\n"
        "$lnk.TargetPath = $args[0]\n"
        "$lnk.WorkingDirectory = $args[1]\n"
        "$lnk.IconLocation = $args[0] + ', 0'\n"
        "$lnk.Description = 'habit checkin'\n"
        "$lnk.Save()\n"
    )
    ps1.write_text(script, encoding="ascii")
    import os
    desktop = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"
    lnk = desktop / "习惯打卡.lnk"
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(ps1), str(exe), str(exe.parent), str(lnk)],
        check=False,
        creationflags=0x08000000,  # CREATE_NO_WINDOW
    )
    print("桌面快捷方式已创建：", lnk)


if __name__ == "__main__":
    # 默认保留原有“全新初始化”行为；传 --no-fresh 可跳过清空开发态 data
    if "--no-fresh" not in sys.argv:
        fresh_init()
    build()
