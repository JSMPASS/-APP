"""习惯打卡 —— 桌面打卡应用入口。

启动：双击 start.bat（开发调试用 python -m habit_checkin），或运行打包后的 exe。
数据目录：开发态 = 仓库根 data/；打包态 = exe 同级 data/（随目录版拷贝即可迁移备份）。
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path


def get_base_dir():
    """应用根目录：打包态为 exe 所在目录，开发态为仓库根目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    override = os.environ.get("HABIT_ROOT")
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parent.parent.parent


def resource_path(name):
    """资源文件路径：打包态在 exe 同级 resources/（含 PyInstaller 6 的 _internal 布局），开发态在包内 resources/。"""
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        for sub in ("resources", "_internal", "_internal/resources"):
            p = exe_dir / sub / name
            if p.is_file():
                return p
        return exe_dir / "resources" / name
    return Path(__file__).resolve().parent / "resources" / name


BASE_DIR = get_base_dir()
DATA_DIR = BASE_DIR / "data"
IMAGES_DIR = DATA_DIR / "images"
DB_PATH = DATA_DIR / "app.db"


def _ensure_tcl_library():
    """为缺少自带 Tcl 脚本目录的 Windows Python 补上本地 Tcl/Tk 库路径。"""
    if not sys.platform.startswith("win"):
        return
    candidates = [
        BASE_DIR / "runtime" / "tcl" / "tcl8.6",
        Path(__file__).resolve().parent / "resources" / "tcl" / "tcl8.6",
    ]
    for tcl_dir in candidates:
        if not (tcl_dir / "init.tcl").is_file():
            continue
        os.environ.setdefault("TCL_LIBRARY", str(tcl_dir))
        tk_dir = tcl_dir.parent / "tk8.6"
        if (tk_dir / "tk.tcl").is_file():
            os.environ.setdefault("TK_LIBRARY", str(tk_dir))
        break


_ensure_tcl_library()


def setup_logging():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(DATA_DIR / "app.log"),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
    )


def make_icon_photoimage():
    """回退方案：用 Pillow 生成应用图标（绿色圆角方块 + 白色对勾）。"""
    from PIL import Image, ImageDraw, ImageTk
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((2, 2, 62, 62), radius=14, fill=(46, 125, 50, 255))
    d.line([(16, 33), (28, 46), (48, 20)], fill=(255, 255, 255, 255), width=8, joint="curve")
    return ImageTk.PhotoImage(img)


def _apply_icon(app):
    try:
        ico = resource_path("icon.ico")
        if ico.is_file():
            app.iconbitmap(str(ico))
            return
    except Exception as exc:
        logging.warning("加载图标资源失败：%s", exc)
    try:
        icon = make_icon_photoimage()
        app.iconphoto(True, icon)
    except Exception as exc:
        logging.warning("图标生成失败：%s", exc)


def _excepthook(exc_type, exc, tb):
    logging.critical("未捕获异常", exc_info=(exc_type, exc, tb))



def main():
    from habit_checkin.services.single_instance import acquire
    if not acquire():
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showwarning("习惯打卡", "应用已在运行，请勿重复打开。", parent=root)
            root.destroy()
        except Exception:
            pass
        return 0
    setup_logging()
    sys.excepthook = _excepthook
    logging.info("启动习惯打卡")
    # 打开数据库前先做每日自动备份（此时文件未被本进程锁定）
    try:
        from habit_checkin.services.backup import backup_if_due
        backup_if_due(DB_PATH, DATA_DIR / "backups")
    except Exception as exc:  # noqa: BLE001
        logging.warning("数据库自动备份失败：%s", exc)
    from habit_checkin.db import Database
    db = Database(DB_PATH, IMAGES_DIR, BASE_DIR)

    # 依据设置选择浅色/深色主题（需在构建 UI 前调用）
    from habit_checkin.ui import theme
    theme.set_theme(db.get_bool_setting("dark_mode", False))
    logging.info("主题模式：%s", "深色" if theme.is_dark() else "浅色")

    from habit_checkin.ui.main_window import SidebarApp
    from habit_checkin.ui.common import center_window
    app = SidebarApp(db)
    center_window(app)
    _apply_icon(app)
    try:
        app.mainloop()
    finally:
        logging.info("退出习惯打卡")
        db.close()
        from habit_checkin.services.single_instance import release
        release()
    return 0


if __name__ == "__main__":
    sys.exit(main())
