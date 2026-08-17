"""小日历弹窗：点击日期相关位置展开，可切换年月、点击日期回填。"""
from __future__ import annotations

import calendar as _cal
import tkinter as tk
from datetime import date

from habit_checkin.ui.theme import PALETTE
from habit_checkin.ui.animate import fade_in

_WEEK = ["一", "二", "三", "四", "五", "六", "日"]


class CalendarPopup(tk.Toplevel):
    """选择日期的弹窗。on_select(date_str) 在点击日期时回调。"""

    def __init__(self, parent, initial_date=None, on_select=None):
        super().__init__(parent)
        self.on_select = on_select
        self.today = date.today()
        init = initial_date or self.today
        self.year = init.year
        self.month = init.month
        self.selected = init
        self.title("选择日期")
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.configure(bg=PALETTE["card"])
        self._build_ui()
        self._render()
        self.transient(parent)
        # 点击日历以外的区域时自动关闭
        self._root = parent.winfo_toplevel()
        self._bind_id = self._root.bind("<Button-1>", self._on_outside_click, add="+")
        fade_in(self)
        self.focus_set()
        try:
            x = parent.winfo_rootx()
            y = parent.winfo_rooty() + parent.winfo_height() + 2
            self.geometry("+%d+%d" % (x, y))
        except tk.TclError:
            pass

    def _build_ui(self):
        P = PALETTE
        box = tk.Frame(self, bg=P["card"], padx=10, pady=10)
        box.pack(fill="both", expand=True)
        nav = tk.Frame(box, bg=P["card"])
        nav.pack(fill="x", pady=(0, 6))
        for text, cmd in (("◀◀", self._prev_year), ("◀", self._prev_month)):
            tk.Button(nav, text=text, command=cmd, bg=P["card"], fg=P["primary"],
                      activebackground=P["primary_light"], relief="flat", bd=0,
                      font=("Microsoft YaHei UI", 11, "bold"), cursor="hand2",
                      padx=6, pady=2).pack(side="left")
        self.title_label = tk.Label(nav, text="", bg=P["card"], fg=P["text"],
                                    font=("Microsoft YaHei UI", 13, "bold"), width=10)
        self.title_label.pack(side="left", expand=True)
        for text, cmd in (("▶", self._next_month), ("▶▶", self._next_year)):
            tk.Button(nav, text=text, command=cmd, bg=P["card"], fg=P["primary"],
                      activebackground=P["primary_light"], relief="flat", bd=0,
                      font=("Microsoft YaHei UI", 11, "bold"), cursor="hand2",
                      padx=6, pady=2).pack(side="left")

        head = tk.Frame(box, bg=P["card"])
        head.pack(fill="x")
        for w in _WEEK:
            tk.Label(head, text=w, width=4, bg=P["primary_light"], fg=P["primary_dark"],
                     font=("Microsoft YaHei UI", 11, "bold")).pack(side="left", padx=1, pady=1)

        self.grid = tk.Frame(box, bg=P["card"])
        self.grid.pack(fill="x")
        tk.Label(box, text="（今日以绿色标注）", bg=P["card"], fg=P["muted"],
                 font=("Microsoft YaHei UI", 11)).pack(pady=(4, 0))

    def _render(self):
        self.title_label.configure(text="{}年 {}月".format(self.year, self.month))
        for w in self.grid.winfo_children():
            w.destroy()
        first = date(self.year, self.month, 1)
        start_wd = first.weekday()
        days = _cal.monthrange(self.year, self.month)[1]
        row = None
        for _ in range(start_wd):
            if row is None or len(row.winfo_children()) % 7 == 0:
                row = tk.Frame(self.grid, bg=PALETTE["card"])
                row.pack(fill="x")
            tk.Label(row, text="", width=4, bg=PALETTE["card"]).pack(side="left", padx=1, pady=1)
        for d in range(1, days + 1):
            if row is None or len(row.winfo_children()) % 7 == 0:
                row = tk.Frame(self.grid, bg=PALETTE["card"])
                row.pack(fill="x")
            day_date = date(self.year, self.month, d)
            if day_date == self.today:
                bg, fg = PALETTE["accent"], "#FFFFFF"
            elif day_date == self.selected:
                bg, fg = PALETTE["primary"], "#FFFFFF"
            else:
                bg, fg = PALETTE["card"], PALETTE["text"]
            btn = tk.Button(row, text=str(d), width=4, bg=bg, fg=fg,
                            activebackground=PALETTE["primary_light"], relief="flat", bd=0,
                            font=("Microsoft YaHei UI", 11), cursor="hand2", pady=2,
                            command=lambda dd=d: self._pick(dd))
            btn.pack(side="left", padx=1, pady=1)
            btn.bind("<Enter>", lambda e, b=btn, bg0=bg: b.configure(bg=PALETTE["primary_light"]) if bg0 == PALETTE["card"] else None)
            btn.bind("<Leave>", lambda e, b=btn, bg0=bg: b.configure(bg=bg0))

    def _pick(self, day):
        day_str = "{:04d}-{:02d}-{:02d}".format(self.year, self.month, day)
        if self.on_select:
            self.on_select(day_str)
        self.destroy()

    def _on_outside_click(self, event):
        """点击日历区域外（主窗口任意位置）时自动关闭日历。"""
        try:
            w = event.widget
            if w is not None and str(w.winfo_toplevel()) == str(self):
                return
        except tk.TclError:
            pass
        self.destroy()

    def destroy(self):
        try:
            if getattr(self, "_bind_id", None) and getattr(self, "_root", None):
                self._root.unbind("<Button-1>", self._bind_id)
        except tk.TclError:
            pass
        super().destroy()

    def _prev_month(self):
        y, m = self.year, self.month - 1
        if m < 1:
            y, m = y - 1, 12
        self.year, self.month = y, m
        self._render()

    def _next_month(self):
        y, m = self.year, self.month + 1
        if m > 12:
            y, m = y + 1, 1
        self.year, self.month = y, m
        self._render()

    def _prev_year(self):
        self.year -= 1
        self._render()

    def _next_year(self):
        self.year += 1
        self._render()


def attach_calendar_on_click(widget, on_select):
    """给控件绑定：点击后在其下方展开日历，选中日期回调 on_select(date_str)。"""
    popup = {"ref": None}

    def open_cal(event=None):
        cur = popup["ref"]
        try:
            if cur is not None and cur.winfo_exists():
                return
        except tk.TclError:
            pass
        popup["ref"] = CalendarPopup(widget, on_select=on_select)

    widget.bind("<Button-1>", open_cal)
    return open_cal
