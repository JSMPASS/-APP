# -*- coding: utf-8 -*-
"""备考进度页：90 天计划的阶段/周/检查点导航 + 一键铺排 + 周复盘 + 打卡热力图。"""
from __future__ import annotations

import tkinter as tk
from datetime import date, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from habit_checkin.services.study_plan import (
    DEFAULT_START, day_number, get_plan_config, plan_week_of, remaining_days, stage_for,
)
from habit_checkin.services import plan_docs
from habit_checkin.ui.common import ScrollableFrame, setup_styles
from habit_checkin.ui.heatmap import CalendarHeatmap
from habit_checkin.ui.theme import PALETTE, card, dialog_header


class StudyProgressPage(tk.Frame):
    """备考进度页（Frame，嵌入主窗口内容区）。"""

    def __init__(self, master, db):
        super().__init__(master, bg=PALETTE["bg"])
        self.db = db
        setup_styles(self)
        self.configure(bg=PALETTE["bg"])
        self._build_ui()
        self.refresh()

    # ---------- 构建 ----------
    def _build_ui(self):
        P = PALETTE
        dialog_header(self, "备考进度", "可自定义计划 · 阶段 / 周 / 检查点导航",
                      title_size=15, subtitle_size=11)

        top = tk.Frame(self, bg=P["bg"], padx=18, pady=10)
        top.pack(fill="x")
        ttk.Button(top, text="⏱ 一键铺排计划", style="Accent.TButton",
                   command=self._open_generate).pack(side="left")
        ttk.Button(top, text="计划设置", command=self._open_plan_settings).pack(side="left", padx=8)
        ttk.Button(top, text="✓ 去打卡（今日）", style="Success.TButton",
                   command=self._go_checkin).pack(side="left", padx=8)
        ttk.Button(top, text="本周复盘", command=self._open_weekly_review).pack(side="left", padx=8)
        ttk.Button(top, text="重新加载", command=self.refresh).pack(side="left")
        ttk.Button(top, text="模板下载", command=self._download_template).pack(side="left", padx=8)
        ttk.Button(top, text="导入计划", command=self._import_plan).pack(side="left", padx=8)
        self.top_hint = tk.Label(top, text="", bg=P["bg"], fg=P["muted"],
                                 font=("Microsoft YaHei UI", 13))
        self.top_hint.pack(side="left", padx=12)

        self.scroll = ScrollableFrame(self, bg=P["bg"])
        self.scroll.pack(fill="both", expand=True, padx=18, pady=(0, 10))
        self.body = self.scroll.inner
        self._container = tk.Frame(self.body, bg=P["bg"])
        self._container.pack(fill="both", expand=True)

    # ---------- 刷新 ----------
    def refresh(self):
        for w in self._container.winfo_children():
            w.destroy()
        cfg = get_plan_config(self.db)
        total_days = cfg["total_days"]
        start = self._start_date()
        today = date.today()
        day = day_number(start, today)
        if day < 1 or day > total_days:
            self._render_not_started(start, day)
        else:
            daily = self.db.daily_completion(
                start.isoformat(),
                (start + timedelta(days=total_days - 1)).isoformat(),
            )
            self._render_overview(start, today, day, daily, cfg)
            self._render_stages(start, day, daily, cfg["stages"])
            self._render_weeks(start, day, cfg["weeks"], total_days)
            self._render_checkpoints(day, cfg["checkpoints"])
            bottom = tk.Frame(self._container, bg=PALETTE["bg"])
            bottom.pack(fill="x", pady=(6, 0))
            bottom.columnconfigure(0, weight=3, uniform="bottom")
            bottom.columnconfigure(1, weight=3, uniform="bottom")
            self._render_heatmap(bottom)
            self._render_routine(bottom, cfg["daily_routine"])
        # 内容构建完成后，把滚轮绑定到全部子孙控件，支持任意位置滚动
        self.scroll.bind_wheel_all()

    def _start_date(self):
        saved = self.db.get_setting("plan_start_date", "")
        try:
            return date.fromisoformat(saved)
        except (ValueError, TypeError):
            return DEFAULT_START

    def _render_not_started(self, start, day):
        P = PALETTE
        box = card(self._container, padx=24, pady=30)
        box.pack(fill="x", pady=12)
        tk.Label(box, text="还没有开始备考计划", bg=P["surface"], fg=P["text"],
                 font=("Microsoft YaHei UI", 28, "bold")).pack()
        tk.Label(box, text="默认开始日期：{}（第 1 天）。点击「一键铺排计划」生成每日任务后，"
                           "本页将展示阶段 / 周 / 检查点导航。".format(start.isoformat()),
                 bg=P["surface"], fg=P["muted"], font=("Microsoft YaHei UI", 15),
                 wraplength=1400, justify="left").pack(pady=(8, 0), anchor="w")
        ttk.Button(box, text="一键铺排计划", style="Accent.TButton",
                   command=self._open_generate).pack(anchor="w", pady=(14, 0))

    # ---------- 总览 ----------
    def _render_overview(self, start, today, day, daily, cfg):
        P = PALETTE
        total_days = cfg["total_days"]
        box = card(self._container, padx=18, pady=14)
        box.pack(fill="x", pady=(0, 10))
        streak = self.db.streak_stats()
        week_num, _ = plan_week_of(start, today, total_days, cfg["weeks"])
        stage = stage_for(day, cfg["stages"])
        tk.Label(box, text="备考总览", bg=P["surface"], fg=P["text"],
                 font=("Microsoft YaHei UI", 24, "bold")).pack(anchor="w")
        stats = [
            ("第 {} 天 / {} 天".format(day, total_days), P["primary"]),
            ("剩余 {} 天".format(remaining_days(start, today, total_days)), P["warning"]),
            ("阶段：{}".format(stage["name"] if stage else "—"), P["accent"]),
            ("第 {} 周".format(week_num), P["primary_dark"]),
            ("连续打卡 {} 天".format(streak["current"]), P["accent"]),
            ("累计打卡 {} 天".format(streak["days"]), P["muted"]),
        ]
        stats_holder = tk.Frame(box, bg=P["surface"])
        stats_holder.pack(fill="x", pady=(10, 0))
        for i in range(0, len(stats), 3):
            row = tk.Frame(stats_holder, bg=P["surface"])
            row.pack(fill="x", pady=(2, 0))
            for text, color in stats[i:i + 3]:
                f = tk.Frame(row, bg=P["surface"])
                f.pack(side="left", padx=(0, 40))
                num = tk.Label(f, text=text, bg=P["surface"], fg=color,
                               font=("Microsoft YaHei UI", 28, "bold"))
                num.pack(anchor="w")
        # 进度条
        total = sum(v["total"] for v in daily.values())
        done = sum(v["done"] for v in daily.values())
        self._progress_bar(box, "{} 天总进度".format(total_days), done, total)

    # ---------- 三阶段 ----------
    def _render_stages(self, start, day, daily, stages):
        P = PALETTE
        tk.Label(self._container, text="{} 个阶段".format(len(stages)), bg=P["bg"], fg=P["text"],
                 font=("Microsoft YaHei UI", 20, "bold")).pack(anchor="w", pady=(0, 4))
        for s in stages:
            s_start = (start + timedelta(days=s["day_start"] - 1)).isoformat()
            s_end = (start + timedelta(days=s["day_end"] - 1)).isoformat()
            total = sum(v["total"] for d, v in daily.items() if s_start <= d <= s_end)
            done = sum(v["done"] for d, v in daily.items() if s_start <= d <= s_end)
            active = s["day_start"] <= day <= s["day_end"]
            box = card(self._container, padx=14, pady=10)
            box.pack(fill="x", pady=(0, 6))
            head = tk.Frame(box, bg=P["surface"])
            head.pack(fill="x")
            name_color = P["primary"] if active else P["text"]
            tk.Label(head, text="{}  {} ~ {}{}".format(
                s["name"], s_start[5:], s_end[5:],
                "（当前阶段）" if active else ""),
                bg=P["surface"], fg=name_color,
                font=("Microsoft YaHei UI", 17, "bold")).pack(side="left")
            tk.Label(head, text="完成 {} / {}（{:.0f}%）".format(
                done, total, (done / total * 100) if total else 0),
                bg=P["surface"], fg=P["muted"],
                font=("Microsoft YaHei UI", 13)).pack(side="right")
            self._progress_bar(box, "", done, total)
            tk.Label(box, text="行测：{}".format(s["xingce"]),
                     bg=P["surface"], fg=P["muted"], font=("Microsoft YaHei UI", 13),
                     wraplength=1400, justify="left").pack(anchor="w", pady=(6, 0))
            tk.Label(box, text="申论：{}".format(s["shenlun"]),
                     bg=P["surface"], fg=P["muted"], font=("Microsoft YaHei UI", 13),
                     wraplength=1400, justify="left").pack(anchor="w")

    # ---------- 13 周 ----------
    def _render_weeks(self, start, day, weeks, total_days):
        P = PALETTE
        cur_week_no = ((day - 1) // 7) + 1
        tk.Label(self._container, text="{} 周逐周计划".format(len(weeks)), bg=P["bg"], fg=P["text"],
                 font=("Microsoft YaHei UI", 20, "bold")).pack(anchor="w", pady=(6, 4))
        box = card(self._container, padx=12, pady=10)
        box.pack(fill="x", pady=(0, 6))
        for wk, focus in weeks:
            wk_start = start + timedelta(days=(wk - 1) * 7)
            wk_end = min(wk_start + timedelta(days=6), start + timedelta(days=total_days - 1))
            rng = "{} ~ {}".format(wk_start.isoformat()[5:], wk_end.isoformat()[5:])
            is_cur = cur_week_no == wk
            row = tk.Frame(box, bg=P["primary_light"] if is_cur else P["surface"])
            row.pack(fill="x", pady=1)
            tag = "W{}".format(wk) + ("（当前）" if is_cur else "")
            tk.Label(row, text=tag, bg=row["bg"], fg=P["primary"] if is_cur else P["text"],
                     font=("Microsoft YaHei UI", 15, "bold"), width=10, anchor="w").pack(side="left", padx=6)
            tk.Label(row, text=rng, bg=row["bg"], fg=P["muted"],
                     font=("Microsoft YaHei UI", 13), width=16, anchor="w").pack(side="left")
            tk.Label(row, text=focus, bg=row["bg"], fg=P["text"],
                     font=("Microsoft YaHei UI", 13), anchor="w", wraplength=900, justify="left").pack(
                side="left", fill="x", expand=True)

    # ---------- 检查点 ----------
    def _render_checkpoints(self, day, checkpoints):
        P = PALETTE
        tk.Label(self._container, text="检查点", bg=P["bg"], fg=P["text"],
                 font=("Microsoft YaHei UI", 20, "bold")).pack(anchor="w", pady=(6, 4))
        box = card(self._container, padx=12, pady=10)
        box.pack(fill="x", pady=(0, 6))
        next_cp = None
        for cp_day, _ in checkpoints:
            if cp_day >= day:
                next_cp = cp_day
                break
        for cp_day, content in checkpoints:
            passed = cp_day < day
            is_next = cp_day == next_cp
            row = tk.Frame(box, bg=P["accent_light"] if is_next else P["surface"])
            row.pack(fill="x", pady=1)
            mark = "✓ 已过" if passed else ("● 即将" if is_next else "○ 未到")
            color = P["muted"] if passed else (P["accent"] if is_next else P["faint"])
            tk.Label(row, text="第 {} 天  {}".format(cp_day, mark), bg=row["bg"], fg=color,
                     font=("Microsoft YaHei UI", 13, "bold"), width=14, anchor="w").pack(side="left", padx=6)
            tk.Label(row, text=content, bg=row["bg"], fg=P["text"],
                     font=("Microsoft YaHei UI", 13), anchor="w").pack(side="left", fill="x", expand=True)

    # ---------- 热力图 ----------
    def _render_heatmap(self, parent=None):
        P = PALETTE
        parent = parent or self._container
        today = date.today()
        prev_month = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
        next_month = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
        next_end = (next_month.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        daily = self.db.daily_completion(prev_month.isoformat(), next_end.isoformat())
        tk.Label(parent, text="近三个月打卡热力图", bg=P["bg"], fg=P["text"],
                 font=("Microsoft YaHei UI", 18, "bold"), anchor="center").grid(
            row=0, column=0, sticky="ew", pady=(0, 4))
        box = card(parent, padx=14, pady=10)
        box.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        hm = CalendarHeatmap(box, daily, bg=P["surface"])
        hm.pack(anchor="center", pady=(6, 0))
        hover = tk.Label(box, text="点击某天可跳转到该天的计划打卡", bg=P["surface"], fg=P["primary_dark"],
                         font=("Microsoft YaHei UI", 13), anchor="center")
        hover.pack(anchor="center", pady=(4, 0))
        hm.set_hover_label(hover)
        hm.set_click_handler(self._open_day)

    # ---------- 作息模板 ----------
    def _render_routine(self, parent=None, routine=None):
        P = PALETTE
        parent = parent or self._container
        routine = routine or []
        tk.Label(parent, text="每日作息模板", bg=P["bg"], fg=P["text"],
                 font=("Microsoft YaHei UI", 18, "bold")).grid(row=0, column=1, sticky="w", pady=(0, 4))
        box = card(parent, padx=12, pady=10)
        box.grid(row=1, column=1, sticky="nsew", padx=(6, 0))
        box.columnconfigure(1, weight=1)
        for i, (tm, desc) in enumerate(routine):
            row = tk.Frame(box, bg=P["surface"])
            row.pack(fill="x", pady=1)
            tk.Label(row, text=tm, bg=P["surface"], fg=P["primary"],
                     font=("Microsoft YaHei UI", 15, "bold"), width=8, anchor="w").pack(side="left")
            tk.Label(row, text=desc, bg=P["surface"], fg=P["text"],
                     font=("Microsoft YaHei UI", 13), anchor="w", justify="left",
                     wraplength=480).pack(side="left", fill="x", expand=True)

    # ---------- 工具 ----------
    def _progress_bar(self, parent, caption, done, total):
        P = PALETTE
        row = tk.Frame(parent, bg=P["surface"])
        row.pack(fill="x", pady=(6, 0))
        if caption:
            tk.Label(row, text=caption, bg=P["surface"], fg=P["muted"],
                     font=("Microsoft YaHei UI", 13)).pack(side="left", padx=(0, 8))
        bar = ttk.Progressbar(row, maximum=max(total, 1), value=done)
        bar.pack(side="left", fill="x", expand=True)
        tk.Label(row, text="{} / {}".format(done, total), bg=P["surface"], fg=P["muted"],
                 font=("Microsoft YaHei UI", 13)).pack(side="left", padx=(8, 0))

    # ---------- 操作 ----------
    def _open_plan_settings(self):
        from habit_checkin.ui.plan_settings_dialog import PlanSettingsDialog
        PlanSettingsDialog(self.master, self.db)
        self.refresh()

    def _open_generate(self):
        from habit_checkin.ui.plan_90_dialog import Plan90Dialog
        Plan90Dialog(self.master, self.db, on_done=self._after_generate)

    def _download_template(self):
        """下载空白计划模板（md/docx/pdf）。"""
        from tkinter import filedialog as fd
        path = fd.asksaveasfilename(
            parent=self,
            title="保存计划模板",
            defaultextension=".md",
            initialfile="学习计划模板.md",
            filetypes=[
                ("Markdown", "*.md"),
                ("Word", "*.docx"),
                ("PDF", "*.pdf"),
                ("所有文件", "*.*"),
            ],
        )
        if not path:
            return
        fmt = Path(path).suffix.lower().lstrip(".")
        try:
            plan_docs.export_template(path, fmt, config=get_plan_config(self.db))
        except Exception as exc:
            messagebox.showerror("模板下载失败", str(exc), parent=self)
            return
        messagebox.showinfo("模板已下载", "已生成模板：\n{}".format(path), parent=self)

    def _import_plan(self):
        """上传模板文档并同步到备考进度/每日计划。"""
        from tkinter import filedialog as fd
        path = fd.askopenfilename(
            parent=self,
            title="选择计划文档",
            filetypes=[
                ("计划文档", "*.md *.txt *.docx *.pdf"),
                ("Markdown", "*.md *.txt"),
                ("Word", "*.docx"),
                ("PDF", "*.pdf"),
                ("所有文件", "*.*"),
            ],
        )
        if not path:
            return
        try:
            result = plan_docs.import_plan_document(self.db, path, overwrite=True)
        except Exception as exc:
            messagebox.showerror("导入失败", str(exc), parent=self)
            return
        self.refresh()
        messagebox.showinfo(
            "导入完成",
            "开始日期：{}\n同步天数：{}\n同步任务数：{}\n{}".format(
                result["start"],
                result.get("days", 0),
                result.get("items", 0),
                "仅更新了开始日期" if result.get("updated_start_only") else "每日计划已同步",
            ),
            parent=self,
        )


    def _after_generate(self):
        """铺排完成后刷新本页，并直接跳转到「今日」页进入打卡。"""
        self.refresh()
        self._go_checkin()

    def _go_checkin(self):
        """跳转到「今日」页（定位到今天），供使用者立即打卡。"""
        master = self.master
        if hasattr(master, "open_day"):
            master.open_day()
        elif hasattr(master, "show_page"):
            master.show_page("today")

    def _open_day(self, day_str):
        """点击热力图某天 → 跳转到该天的计划进行查看/打卡。"""
        master = self.master
        if hasattr(master, "open_day"):
            master.open_day(day_str)

    def _open_weekly_review(self):
        from habit_checkin.ui.weekly_review_dialog import WeeklyReviewDialog
        cfg = get_plan_config(self.db)
        start = self._start_date()
        week_num, week_start = plan_week_of(start, date.today(), cfg["total_days"], cfg["weeks"])
        WeeklyReviewDialog(self.master, self.db, week_num, week_start)
