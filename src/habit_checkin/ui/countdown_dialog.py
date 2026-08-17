# -*- coding: utf-8 -*-
"""倒计时设置：双击总体进度右侧倒计时区域打开，设置目标日期与名称。"""
from __future__ import annotations

import tkinter as tk
from datetime import date
from tkinter import messagebox, ttk

from habit_checkin.ui.animate import fade_in, slide_in
from habit_checkin.ui.calendar import CalendarPopup
from habit_checkin.ui.common import center_window, setup_styles
from habit_checkin.ui.theme import PALETTE, dialog_header


class CountdownDialog(tk.Toplevel):
    """精美倒计时设置弹窗：目标名称 + 目标日期（小日历选择）。"""

    def __init__(self, master, db):
        super().__init__(master)
        self.db = db
        self.title("倒计时设置")
        self.resizable(False, False)
        self.transient(master)
        setup_styles(self)
        self.configure(bg=PALETTE["bg"])
        dialog_header(self, "倒计时设置", "目标日期与名称")

        P = PALETTE
        body = tk.Frame(self, bg=P["bg"], padx=24, pady=20)
        body.pack(fill="both", expand=True)
        self._var_title = tk.StringVar(value=self.db.get_setting("countdown_title", "") or "")
        self._var_date = tk.StringVar(value=self.db.get_setting("countdown_date", "") or "")

        # 目标名称
        tk.Label(body, text="目标名称", bg=P["bg"], fg=P["muted"],
                 font=("Microsoft YaHei UI", 13)).pack(anchor="w")
        self.title_entry = ttk.Entry(body, textvariable=self._var_title, width=26)
        self.title_entry.pack(fill="x", pady=(4, 12))

        # 目标日期
        tk.Label(body, text="目标日期", bg=P["bg"], fg=P["muted"],
                 font=("Microsoft YaHei UI", 13)).pack(anchor="w")
        date_row = tk.Frame(body, bg=P["bg"])
        date_row.pack(fill="x", pady=(4, 0))
        self.date_btn = tk.Button(
            date_row, text="", bg=P["surface"], fg=P["primary"],
            activebackground=P["primary_light"], relief="flat", bd=0,
            highlightbackground=P["border"], highlightthickness=1,
            font=("Microsoft YaHei UI", 15, "bold"), padx=14, pady=8,
            cursor="hand2",
        )
        self.date_btn.pack(side="left", fill="x", expand=True)
        ttk.Button(date_row, text="今天", command=self._set_today).pack(side="left", padx=(8, 0))
        self._update_date_btn()
        from habit_checkin.ui.calendar import attach_calendar_on_click
        attach_calendar_on_click(self.date_btn, self._on_calendar_pick)

        tk.Label(body, text="提示：点击日期框可弹出小日历选择年月日。",
                 bg=P["bg"], fg=P["faint"], font=("Microsoft YaHei UI", 11)).pack(anchor="w", pady=(6, 0))

        btns = tk.Frame(body, bg=P["bg"])
        btns.pack(fill="x", pady=(18, 0))
        ttk.Button(btns, text="清空倒计时", command=self._clear).pack(side="left")
        ttk.Button(btns, text="保存", style="Accent.TButton", command=self._save).pack(side="right")

        center_window(self)
        fade_in(self)
        slide_in(self)
        self.grab_set()

    def _update_date_btn(self):
        val = self._var_date.get()
        self.date_btn.configure(text=val if val else "点击选择目标日期")

    def _set_today(self):
        self._var_date.set(date.today().isoformat())
        self._update_date_btn()

    def _on_calendar_pick(self, day_str):
        self._var_date.set(day_str)
        self._update_date_btn()

    def _clear(self):
        self._var_title.set("")
        self._var_date.set("")
        self._update_date_btn()

    def _save(self):
        day = self._var_date.get().strip()
        if not day:
            messagebox.showwarning("倒计时设置", "请先选择目标日期。", parent=self)
            return
        try:
            date.fromisoformat(day)
        except ValueError:
            messagebox.showwarning("倒计时设置", "目标日期格式不正确。", parent=self)
            return
        title = self._var_title.get().strip()
        self.db.set_setting("countdown_date", day)
        self.db.set_setting("countdown_title", title)
        self.destroy()
