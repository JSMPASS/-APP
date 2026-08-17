# -*- coding: utf-8 -*-
"""生成今日打卡报告：选择导出格式（Word / PDF / 图片）。"""
from __future__ import annotations

import tkinter as tk

from habit_checkin.ui.animate import fade_in, slide_in
from habit_checkin.ui.common import center_window, setup_styles
from habit_checkin.ui.theme import PALETTE, dialog_header


class ExportFormatDialog(tk.Toplevel):
    """三个精美选项按钮，点击后回调 on_choose(fmt)。"""

    OPTIONS = [
        ("docx", "Word 文档", "适合打印与再次编辑", "＊", PALETTE["primary"]),
        ("pdf", "PDF 文档", "版式固定，跨设备查看", "Ｐ", PALETTE["accent"]),
        ("png", "图片（PNG）", "一张长图，方便分享", "图", PALETTE["warning"]),
    ]

    def __init__(self, master, on_choose):
        super().__init__(master)
        self.on_choose = on_choose
        self.title("生成今日打卡报告")
        self.resizable(False, False)
        self.transient(master)
        setup_styles(self)
        self.configure(bg=PALETTE["bg"])
        dialog_header(self, "生成今日打卡报告", "选择导出格式")

        body = tk.Frame(self, bg=PALETTE["bg"], padx=20, pady=18)
        body.pack(fill="both", expand=True)
        tk.Label(body, text="请选择报告导出格式：", bg=PALETTE["bg"], fg=PALETTE["text"],
                 font=("Microsoft YaHei UI", 15, "bold")).pack(anchor="w", pady=(0, 10))

        for fmt, label, desc, mark, color in self.OPTIONS:
            self._option_row(body, fmt, label, desc, mark, color)

        center_window(self)
        fade_in(self)
        slide_in(self)
        self.grab_set()

    def _option_row(self, parent, fmt, label, desc, mark, color):
        row = tk.Frame(parent, bg=PALETTE["surface"], padx=14, pady=10,
                       highlightbackground=PALETTE["border"], highlightthickness=1,
                       cursor="hand2")
        row.pack(fill="x", pady=5)
        icon = tk.Label(row, text=mark, bg=PALETTE["surface"], fg=color,
                        font=("Microsoft YaHei UI", 13, "bold"), width=2)
        icon.pack(side="left")
        txt = tk.Frame(row, bg=PALETTE["surface"])
        txt.pack(side="left", padx=(6, 0))
        tk.Label(txt, text=label, bg=PALETTE["surface"], fg=PALETTE["text"],
                 font=("Microsoft YaHei UI", 15, "bold"), anchor="w").pack(anchor="w")
        tk.Label(txt, text=desc, bg=PALETTE["surface"], fg=PALETTE["muted"],
                 font=("Microsoft YaHei UI", 11), anchor="w").pack(anchor="w", pady=(2, 0))
        arrow = tk.Label(row, text="›", bg=PALETTE["surface"], fg=PALETTE["faint"],
                         font=("Microsoft YaHei UI", 17, "bold"))
        arrow.pack(side="right")
        self._bind_click(row, lambda e, f=fmt: self._pick(f))
        row.bind("<Enter>", lambda e: row.configure(bg=PALETTE["surface_hover"],
                                                    highlightbackground=PALETTE["primary"]))
        row.bind("<Leave>", lambda e: row.configure(bg=PALETTE["surface"],
                                                    highlightbackground=PALETTE["border"]))

    def _bind_click(self, widget, handler):
        """递归绑定点击事件到自身及所有子组件。"""
        widget.bind("<Button-1>", handler)
        for child in widget.winfo_children():
            self._bind_click(child, handler)

    def _pick(self, fmt):
        cb = self.on_choose
        self.destroy()
        if cb:
            cb(fmt)
