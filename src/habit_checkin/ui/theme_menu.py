# -*- coding: utf-8 -*-
"""自绘主题右键菜单：卡片式、hover 高亮、危险项红色、点外部 / Esc 关闭。

替代系统 tk.Menu（原生样式无法贴合 APP 主题）。颜色全部取自 PALETTE，
深色/浅色主题切换后自动跟随。
"""
from __future__ import annotations

import tkinter as tk

from habit_checkin.ui.theme import PALETTE

_FONT = ("Microsoft YaHei UI", 12)


class ThemeMenu(tk.Toplevel):
    """一次性使用示例：

        menu = ThemeMenu(self)
        menu.show(event.x_root, event.y_root, [
            ("＋ 新增子节点", handler),
            ("---",),
            ("✕ 删除", handler, True),   # 第三个参数 True = 危险项（红色）
        ])

    菜单在点击任意项、点击外部或按 Esc 后隐藏；再次 show 前需重建项列表。
    """

    def __init__(self, master):
        super().__init__(master)
        self._items = []
        self._menu_ref = self  # 防止局部引用被 GC 后菜单立即消失
        self.withdraw()
        self.overrideredirect(True)
        self.configure(bg=PALETTE["border"])
        self._box = tk.Frame(self, bg=PALETTE["surface"])
        self._box.pack(padx=1, pady=1)
        self.bind("<Escape>", lambda e: self._close())
        self.bind("<FocusOut>", lambda e: self._close())

    def show(self, x, y, items):
        """在屏幕坐标 (x, y) 处弹出菜单。items 元素：
        ("label", command) 普通项 / ("label", command, True) 危险项 / ("---",) 分隔线。
        """
        self._clear()
        for it in items:
            if isinstance(it, tuple) and it and it[0] == "---":
                tk.Frame(self._box, bg=PALETTE["divider"], height=1
                         ).pack(fill="x", padx=8, pady=3)
                continue
            label, cmd = it[0], it[1]
            danger = len(it) > 2 and bool(it[2])
            self._add_item(label, cmd, danger)
        self._position(x, y)
        self.deiconify()
        self.lift()
        self.focus_force()

    def _add_item(self, label, cmd, danger):
        fg = PALETTE["danger"] if danger else PALETTE["text"]
        hover_bg = PALETTE["danger_light"] if danger else PALETTE["primary_light"]
        hover_fg = PALETTE["danger"] if danger else PALETTE["primary_dark"]
        item = tk.Label(self._box, text=label, bg=PALETTE["surface"], fg=fg,
                        font=_FONT, padx=16, pady=6, anchor="w", cursor="hand2")
        item.pack(fill="x")

        def on_enter(_e, it=item):
            it.configure(bg=hover_bg, fg=hover_fg)

        def on_leave(_e, it=item):
            it.configure(bg=PALETTE["surface"], fg=fg)

        def on_click(_e, c=cmd):
            self._close()
            c()

        item.bind("<Enter>", on_enter)
        item.bind("<Leave>", on_leave)
        item.bind("<Button-1>", on_click)
        self._items.append(item)

    def _position(self, x, y):
        self.update_idletasks()
        w = self.winfo_reqwidth()
        h = self.winfo_reqheight()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        if x + w > sw - 8:
            x = sw - w - 8
        if y + h > sh - 8:
            y = sh - h - 8
        self.geometry("+{}+{}".format(int(max(x, 0)), int(max(y, 0))))

    def _clear(self):
        for it in self._items:
            it.destroy()
        self._items = []

    def _close(self, event=None):
        self.withdraw()
