# -*- coding: utf-8 -*-
"""系统托盘图标：最小化到托盘 / 从托盘恢复 / 托盘菜单退出。

依赖：
- pystray（系统托盘）
- Pillow（生成/加载托盘图标）

如果 pystray 未安装，本模块会降级为“无托盘模式”，不会影响 App 启动。
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

try:
    import pystray
    from PIL import Image, ImageDraw
except Exception:  # noqa: BLE001
    pystray = None
    Image = None
    ImageDraw = None

APP_NAME = "习惯打卡"


def _find_icon_path():
    """定位 icon.ico：打包态在 exe 同级，开发态在包 resources 下。"""
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        for sub in ("resources", "_internal", "_internal/resources"):
            p = exe_dir / sub / "icon.ico"
            if p.is_file():
                return p
        return exe_dir / "resources" / "icon.ico"
    return Path(__file__).resolve().parent.parent / "resources" / "icon.ico"


class TrayIcon:
    """封装 pystray 托盘图标，动作通过回调交给 Tk 主线程执行。"""

    def __init__(self, app, icon_path=None):
        self.app = app
        self.icon_path = icon_path or _find_icon_path()
        self.icon = None
        self._started = False

    @property
    def available(self) -> bool:
        return pystray is not None

    def _make_image(self):
        path = Path(self.icon_path)
        if path.is_file():
            try:
                return Image.open(path)
            except Exception:  # noqa: BLE001
                pass
        # 回退：生成绿色圆角方块 + 白色对勾
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle((2, 2, 62, 62), radius=14, fill=(46, 125, 50, 255))
        draw.line([(16, 33), (28, 46), (48, 20)], fill=(255, 255, 255, 255), width=8, joint="curve")
        return img

    def start(self) -> bool:
        """启动托盘图标；成功返回 True，失败返回 False。"""
        if pystray is None:
            logging.warning("未安装 pystray，系统托盘功能不可用")
            return False
        try:
            image = self._make_image()
            menu = pystray.Menu(
                pystray.MenuItem("打开主窗口", self._on_show, default=True),
                pystray.MenuItem("退出", self._on_quit),
            )
            self.icon = pystray.Icon(
                "habit_checkin_tray",
                image,
                APP_NAME,
                menu=menu,
            )
            self.icon.run_detached()
            self._started = True
            return True
        except Exception as exc:  # noqa: BLE001
            logging.warning("托盘图标启动失败：%s", exc)
            self.icon = None
            return False

    def stop(self) -> None:
        """停止托盘图标。"""
        if self.icon is not None:
            try:
                self.icon.stop()
            except Exception:  # noqa: BLE001
                pass
            self.icon = None
        self._started = False

    # ---------- 托盘菜单回调 ----------
    def _on_show(self, icon=None, item=None):
        if self.app is not None:
            try:
                self.app.enqueue_tray_action("show")
            except Exception:  # noqa: BLE001
                pass

    def _on_quit(self, icon=None, item=None):
        if self.app is not None:
            try:
                self.app.enqueue_tray_action("quit")
            except Exception:  # noqa: BLE001
                pass
