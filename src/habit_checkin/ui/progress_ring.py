# -*- coding: utf-8 -*-
"""环形进度组件：Canvas 绘制圆环 + 中心百分比，带缓动动画。"""
from __future__ import annotations

import tkinter as tk

from habit_checkin.ui.theme import PALETTE


class ProgressRing(tk.Canvas):
    """圆环进度指示器，set() 时从当前值平滑动画到目标值。"""

    def __init__(self, master, size=96, thickness=10, color=None, trough=None,
                 text_color=None, bg=None, **kw):
        bg = bg or PALETTE["surface"]
        super().__init__(master, width=size, height=size, bg=bg,
                         highlightthickness=0, bd=0, **kw)
        self._size = size
        self._thickness = thickness
        self._color = color or PALETTE["primary"]
        self._trough = trough or PALETTE["divider"]
        self._text_color = text_color or PALETTE["text"]
        self._cur = 0.0
        self._target = 0.0
        self._after_id = None
        self._draw(self._cur)

    # ---------- 对外接口 ----------
    def set(self, frac, animate=True, ms=600, steps=24):
        """设置进度（0~1），带 ease-out 缓动动画。"""
        self._target = max(0.0, min(1.0, float(frac)))
        self._cancel()
        if not animate:
            self._cur = self._target
            self._draw(self._cur)
            return
        start = self._cur

        def _step(i):
            try:
                if not self.winfo_exists():
                    return
            except tk.TclError:
                return
            t = i / steps
            eased = 1 - (1 - t) ** 3  # ease-out cubic
            self._cur = start + (self._target - start) * eased
            self._draw(self._cur)
            if i < steps:
                self._after_id = self.after(ms // steps, lambda: _step(i + 1))

        _step(0)

    def set_color(self, color):
        """动态更换圆环颜色并重绘。"""
        self._color = color
        self._draw(self._cur)

    # ---------- 内部 ----------
    def _cancel(self):
        if self._after_id is not None:
            try:
                self.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None

    def _draw(self, frac):
        self.delete("all")
        size = self._size
        th = max(2, self._thickness)
        pad = th // 2 + 2
        bbox = (pad, pad, size - pad, size - pad)
        self.create_arc(bbox, start=90, extent=-359.9, style="arc", width=th,
                        outline=self._trough)
        if frac > 0.001:
            extent = -359.9 * min(frac, 1.0)
            self.create_arc(bbox, start=90, extent=extent, style="arc", width=th,
                            outline=self._color)
        pct = int(round(frac * 100))
        font_size = max(9, int(size // 4.6))
        self.create_text(size / 2, size / 2, text="{}%".format(pct),
                         fill=self._text_color,
                         font=("Microsoft YaHei UI", font_size, "bold"))
