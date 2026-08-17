# -*- coding: utf-8 -*-
"""关闭确认对话框：点窗口 X 时选择「最小化到托盘 / 退出 / 取消」。"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from habit_checkin.ui.animate import fade_in
from habit_checkin.ui.common import center_window, setup_styles
from habit_checkin.ui.theme import PALETTE, dialog_header


class CloseChoiceDialog(tk.Toplevel):
    """返回 result：'tray' / 'exit' / 'cancel'。"""

    def __init__(self, master, tray_available=True):
        super().__init__(master)
        self.tray_available = tray_available
        self.result = "cancel"
        self.remember = False
        self.remember_var = tk.BooleanVar(value=False)
        self.title("习惯打卡")
        self.geometry("440x340")
        self.resizable(False, False)
        self.transient(master)
        self.configure(bg=PALETTE["bg"])
        setup_styles(self)
        dialog_header(self, "关闭习惯打卡", "请选择关闭方式")
        self._build_ui()
        center_window(self)
        self.grab_set()
        self.focus_set()
        fade_in(self)

    def _build_ui(self):
        P = PALETTE
        body = tk.Frame(self, bg=P["bg"], padx=20, pady=18)
        body.pack(fill="both", expand=True)

        if self.tray_available:
            tk.Label(
                body,
                text="关闭窗口后 App 仍会在后台运行，可从系统托盘恢复。",
                bg=P["bg"], fg=P["muted"], font=("Microsoft YaHei UI", 11),
                wraplength=380, justify="left",
            ).pack(anchor="w", pady=(0, 14))
        else:
            tk.Label(
                body,
                text="当前未安装 pystray，无法最小化到托盘。",
                bg=P["bg"], fg=P["danger"], font=("Microsoft YaHei UI", 11),
                wraplength=380, justify="left",
            ).pack(anchor="w", pady=(0, 14))

        btns = tk.Frame(body, bg=P["bg"])
        btns.pack(fill="x", pady=(6, 0))
        remember_cb = ttk.Checkbutton(
            body,
            text="记住我的选择，以后关闭时不再询问",
            variable=self.remember_var,
        )
        remember_cb.pack(anchor="w", pady=(0, 8))

        if self.tray_available:
            ttk.Button(
                btns,
                text="最小化到托盘",
                style="Accent.TButton",
                command=lambda: self._choose("tray"),
            ).pack(fill="x", pady=3)
        ttk.Button(
            btns,
            text="退出",
            command=lambda: self._choose("exit"),
        ).pack(fill="x", pady=3)
        ttk.Button(
            btns,
            text="取消",
            command=lambda: self._choose("cancel"),
        ).pack(fill="x", pady=3)

    def _choose(self, result):
        self.result = result
        self.remember = self.remember_var.get()
        self.destroy()
