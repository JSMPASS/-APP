# -*- coding: utf-8 -*-
"""每周复盘对话框：展示本周完成率/错题统计，填写复盘心得与下周重点。"""
from __future__ import annotations

import tkinter as tk
from datetime import timedelta
from tkinter import messagebox, ttk

from habit_checkin.ui.animate import fade_in
from habit_checkin.ui.common import center_window, setup_styles
from habit_checkin.ui.field_edit_dialog import FieldTextArea
from habit_checkin.ui.theme import PALETTE, dialog_header


class WeeklyReviewDialog(tk.Toplevel):
    """周复盘（第 N 周）：完成率/错题自动统计 + 复盘心得 + 下周重点。"""

    def __init__(self, master, db, week_num, week_start):
        super().__init__(master)
        self.db = db
        self.week_num = week_num
        self.week_start = week_start
        self.week_start_str = week_start.isoformat()
        self.week_end_str = (week_start + timedelta(days=6)).isoformat()
        self.title("周复盘 · 第 {} 周".format(week_num))
        self.geometry("640x600")
        self.transient(master)
        setup_styles(self)
        self.configure(bg=PALETTE["bg"])
        dialog_header(self, "周复盘 · 第 {} 周".format(week_num),
                      "{} ~ {}".format(self.week_start_str, self.week_end_str))
        self._build_ui()
        self._load()
        center_window(self)
        fade_in(self)
        self.grab_set()

    def _build_ui(self):
        P = PALETTE
        # 统计条
        stats = tk.Frame(self, bg=P["surface"], padx=14, pady=10,
                         highlightbackground=P["border"], highlightthickness=1)
        stats.pack(fill="x", padx=14, pady=(12, 6))
        self.stat_label = tk.Label(stats, text="", bg=P["surface"], fg=P["text"],
                                   font=("Microsoft YaHei UI", 13, "bold"),
                                   justify="left")
        self.stat_label.pack(anchor="w")

        body = tk.Frame(self, bg=P["bg"], padx=14, pady=8)
        body.pack(fill="both", expand=True)

        for key, label, height in (
            ("review_text", "复盘心得（本周完成情况、遇到的困难、方法调整）", 8),
            ("next_focus", "下周重点（要强化的模块、要补的弱项）", 4),
        ):
            box = tk.Frame(body, bg=P["surface"], padx=12, pady=8,
                           highlightbackground=P["border"], highlightthickness=1)
            box.pack(fill="both", expand=True, pady=(0, 8))
            tk.Label(box, text=label, bg=P["surface"], fg=P["text"],
                     font=("Microsoft YaHei UI", 13, "bold")).pack(anchor="w")
            txt = FieldTextArea(box, height=height)
            txt.pack(fill="both", expand=True, pady=(4, 0))
            setattr(self, key, txt)

        bottom = tk.Frame(self, bg=P["bg"], padx=14, pady=10)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="取消", command=self.destroy).pack(side="right")
        ttk.Button(bottom, text="保存复盘", style="Accent.TButton",
                   command=self._save).pack(side="right", padx=8)

    def _load(self):
        items = self.db.query_items(self.week_start_str, self.week_end_str)
        total = len(items)
        done = sum(1 for it in items if it["done"])
        rate = (done / total * 100) if total else 0
        wrong = len(self.db.wrong_questions(self.week_start_str, self.week_end_str))
        self.stat_label.configure(
            text="本周共 {} 项，完成 {} 项（{:.0f}%）· 新增错题 {} 题".format(total, done, rate, wrong)
        )
        review = self.db.get_weekly_review(self.week_start_str)
        if review:
            self.review_text.insert("1.0", review.get("review_text") or "")
            self.next_focus.insert("1.0", review.get("next_focus") or "")

    def _save(self):
        review = self.review_text.get_html().strip()
        focus = self.next_focus.get_html().strip()
        if not review and not focus:
            messagebox.showwarning("保存复盘", "请至少填写一项内容。", parent=self)
            return
        self.db.save_weekly_review(self.week_start_str, review, focus)
        self.destroy()
