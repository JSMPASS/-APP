# -*- coding: utf-8 -*-
"""总体进度：汇总概览 + 指标卡片（环形进度 / 数字动画 / 双列网格）。

内置指标自动统计；自定义指标可手动 +1/-1、设目标查看完成度。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from habit_checkin.ui.animate import count_up, fade_in
from habit_checkin.ui.common import center_window, setup_styles
from habit_checkin.ui.field_edit_dialog import ask_fields
from habit_checkin.ui.progress_ring import ProgressRing
from habit_checkin.ui.theme import PALETTE, card, dialog_header


class ProgressWindow(tk.Frame):
    """总体进度页：顶部汇总 + 双列指标卡片。"""

    def __init__(self, master, db):
        super().__init__(master, bg=PALETTE["bg"])
        self.db = db
        setup_styles(self)
        self.configure(bg=PALETTE["bg"])
        self._build_ui()
        self._refresh()

    def refresh(self):
        """侧边栏切换时由 SidebarApp 调用，保证数据始终最新。"""
        self._refresh()

    # ---------- 构建 ----------
    def _build_ui(self):
        P = PALETTE
        header = tk.Frame(self, bg=P["primary"], padx=20, pady=12)
        header.pack(fill="x")
        tk.Label(header, text="总体进度", bg=P["primary"], fg="#FFFFFF",
                 font=("Microsoft YaHei UI", 17, "bold")).pack(side="left")
        tk.Label(header, text="累计统计 · 目标达成", bg=P["primary"], fg=P["header_sub"],
                 font=("Microsoft YaHei UI", 11)).pack(side="left", padx=(10, 0))
        ttk.Button(header, text="管理指标", command=self._manage).pack(side="right")

        self.summary = tk.Frame(self, bg=P["bg"], padx=20)
        self.summary.pack(fill="x", pady=(14, 4))
        self._build_summary()

        self.cards = tk.Frame(self, bg=P["bg"], padx=20)
        self.cards.pack(fill="both", expand=True, pady=(4, 8))
        for i in range(3):
            self.cards.columnconfigure(i, weight=1, uniform="m")
        # self.cards.columnconfigure(1, weight=1, uniform="m")

        tk.Label(self, text="内置指标自动统计；自定义指标可手动 ＋1/－1，并设置目标查看完成度。",
                 bg=P["bg"], fg=P["muted"], font=("Microsoft YaHei UI", 11)
                 ).pack(side="bottom", pady=(0, 8))

    def _build_summary(self):
        for w in self.summary.winfo_children():
            w.destroy()
        P = PALETTE
        for i in range(4):
            self.summary.columnconfigure(i, weight=1, uniform="summary")

        def stat(caption, color, idx):
            f = tk.Frame(self.summary, bg=P["surface"],
                         highlightbackground=P["border"], highlightthickness=1)
            f.grid(row=0, column=idx, sticky="nsew", padx=6, pady=2)
            num = tk.Label(f, text="0", bg=P["surface"], fg=color,
                           font=("Microsoft YaHei UI", 17, "bold"))
            num.pack(pady=(10, 0))
            tk.Label(f, text=caption, bg=P["surface"], fg=P["muted"],
                     font=("Microsoft YaHei UI", 11)).pack(pady=(0, 8))
            return num

        self.sum_enabled = stat("已启用指标", P["primary"], 0)
        self.sum_targets = stat("已设目标", P["warning"], 1)
        self.sum_achieved = stat("已达成目标", P["accent"], 2)
        self.sum_rate = stat("平均完成率", P["primary"], 3)

    # ---------- 刷新 ----------
    def _refresh(self):
        metrics = [m for m in self.db.metric_values() if m["enabled"]]
        # 汇总统计
        enabled = len(metrics)
        with_target = sum(
            1 for m in metrics
            if m.get("target") is not None and int(m["target"]) > 0
        )
        achieved = sum(
            1 for m in metrics
            if m.get("target") is not None and int(m["target"]) > 0
            and m["current"] >= int(m["target"])
        )
        rates = [
            min(100.0, m["current"] / int(m["target"]) * 100)
            for m in metrics
            if m.get("target") is not None and int(m["target"]) > 0
        ]
        avg = (sum(rates) / len(rates)) if rates else 0.0
        count_up(self.sum_enabled, enabled)
        count_up(self.sum_targets, with_target)
        count_up(self.sum_achieved, achieved)
        count_up(self.sum_rate, int(round(avg)), suffix="%")

        # 指标卡片（双列网格）
        for w in self.cards.winfo_children():
            w.destroy()
        if not metrics:
            self._render_empty()
            return
        for row in range((len(metrics) + 2) // 3):
            self.cards.rowconfigure(row, weight=1, uniform="r")
        for idx, m in enumerate(metrics):
            box = card(self.cards, padx=14, pady=12)
            box.grid(row=idx // 3, column=idx % 3, sticky="nsew",
                     padx=6, pady=6)
            self._render_card(box, m)

    def _render_empty(self):
        P = PALETTE
        box = card(self.cards, padx=24, pady=34)
        box.grid(row=0, column=0, columnspan=3, sticky="nsew", pady=10)
        tk.Label(box, text="还没有启用的指标", bg=P["surface"], fg=P["text"],
                 font=("Microsoft YaHei UI", 17, "bold")).pack()
        tk.Label(box, text="点击右上角「管理指标」开启内置指标，或新建自定义指标。",
                 bg=P["surface"], fg=P["muted"], font=("Microsoft YaHei UI", 13)
                 ).pack(pady=(8, 0))
        ttk.Button(box, text="管理指标", style="Accent.TButton",
                   command=self._manage).pack(pady=(14, 0))

    def _render_card(self, box, m):
        P = PALETTE
        top = tk.Frame(box, bg=P["surface"])
        top.pack(fill="x")
        tk.Label(top, text=m["name"], bg=P["surface"], fg=P["text"],
                 font=("Microsoft YaHei UI", 15, "bold")).pack(side="left")
        kind = "内置" if m["kind"] == "builtin" else "自定义"
        badge = tk.Label(top, text=kind, bg=P["primary_light"], fg=P["primary"],
                         font=("Microsoft YaHei UI", 11), padx=6, pady=1)
        badge.pack(side="left", padx=(8, 0))

        unit = m.get("unit") or ""
        target = m.get("target")
        has_target = target is not None and int(target) > 0
        mid = tk.Frame(box, bg=P["surface"])
        mid.pack(fill="x", pady=(12, 0))

        if has_target:
            ring = ProgressRing(mid, size=72, thickness=8, color=P["accent"])
            ring.pack(side="left")
            pct = min(100.0, m["current"] / int(target) * 100)
            ring.set(pct / 100)
            info = tk.Frame(mid, bg=P["surface"])
            info.pack(side="left", padx=(14, 0), fill="x", expand=True)
            val = tk.Label(info, text="0", bg=P["surface"], fg=P["text"],
                           font=("Microsoft YaHei UI", 20, "bold"))
            val.pack(anchor="w")
            tk.Label(info, text="目标 {}{} · 完成 {:.0f}%".format(int(target), unit, pct),
                     bg=P["surface"], fg=P["muted"], font=("Microsoft YaHei UI", 13)
                     ).pack(anchor="w", pady=(2, 0))
            count_up(val, int(m["current"]))
            bar = ttk.Progressbar(box, maximum=100, value=pct)
            bar.pack(fill="x", pady=(10, 0))
        else:
            val = tk.Label(mid, text="0", bg=P["surface"], fg=P["primary"],
                           font=("Microsoft YaHei UI", 28, "bold"))
            val.pack(side="left")
            tk.Label(mid, text=unit, bg=P["surface"], fg=P["muted"],
                     font=("Microsoft YaHei UI", 15)).pack(side="left", padx=(4, 0), pady=(6, 0))
            count_up(val, int(m["current"]))

        if m["kind"] == "custom":
            btns = tk.Frame(box, bg=P["surface"])
            btns.pack(fill="x", pady=(12, 0))
            ttk.Button(btns, text="＋1", width=5,
                       command=lambda mid=m["id"]: self._bump(mid, 1)).pack(side="left")
            ttk.Button(btns, text="－1", width=5,
                       command=lambda mid=m["id"]: self._bump(mid, -1)).pack(side="left", padx=6)
            ttk.Button(btns, text="清零", width=5,
                       command=lambda mid=m["id"]: self._bump(mid, -int(m["current"]))).pack(side="left")
            ttk.Button(btns, text="设目标",
                       command=lambda mid=m["id"]: self._set_target(mid)).pack(side="right")

    # ---------- 操作 ----------
    def _bump(self, mid, delta):
        for m in self.db.metric_values():
            if m["id"] == mid:
                self.db.set_metric_value(mid, max(0, m["current"] + delta))
                break
        self._refresh()

    def _set_target(self, mid):
        m = next((x for x in self.db.metric_values() if x["id"] == mid), None)
        if not m:
            return
        cur = int(m["target"]) if m.get("target") is not None else 0
        values = ask_fields(
            self, "设置目标", [
                {"key": "target", "label": "目标值", "type": "integer",
                 "value": str(max(cur, 0)) if cur > 0 else "", "min": 0,
                 "required": True},
            ],
            subtitle="「{}」目标（{}）；留空表示取消目标".format(
                m["name"], m.get("unit") or "次"),
        )
        if values is not None:
            self.db.set_metric_target(mid, values["target"])
            self._refresh()

    def _manage(self):
        dlg = ManageMetricsDialog(self, self.db)
        self.wait_window(dlg)
        self._refresh()


class ManageMetricsDialog(tk.Toplevel):
    """指标管理：开启/停用、设目标、删除自定义指标、新增自定义指标。"""

    def __init__(self, master, db):
        super().__init__(master, bg=PALETTE["bg"])
        self.db = db
        self.title("管理指标")
        self.geometry("680x540")
        self.transient(master)
        setup_styles(self)
        self.configure(bg=PALETTE["bg"])
        dialog_header(self, "管理指标", "启用/停用 · 目标 · 自定义指标")
        center_window(self)
        fade_in(self)
        self._build_ui()
        self._refresh()

    def _build_ui(self):
        P = PALETTE
        add = tk.Frame(self, bg=P["surface"], padx=12, pady=10,
                       highlightbackground=P["border"], highlightthickness=1)
        add.pack(fill="x", padx=14, pady=(14, 6))
        tk.Label(add, text="新增自定义指标", bg=P["surface"], fg=P["text"],
                 font=("Microsoft YaHei UI", 13, "bold")).pack(anchor="w")
        ttk.Button(add, text="＋ 新增指标", style="Accent.TButton",
                   command=self._add).pack(anchor="w", pady=(6, 0))
        tk.Label(add, text="统一表单填写指标名称、单位与目标值。",
                 bg=P["surface"], fg=P["muted"],
                 font=("Microsoft YaHei UI", 11)).pack(anchor="w", pady=(4, 0))

        self.list_frame = tk.Frame(self, bg=P["bg"], padx=14, pady=6)
        self.list_frame.pack(fill="both", expand=True)

    def _refresh(self):
        for w in self.list_frame.winfo_children():
            w.destroy()
        metrics = self.db.list_metrics()
        if not metrics:
            tk.Label(self.list_frame, text="暂无指标", bg=PALETTE["bg"],
                     fg=PALETTE["muted"]).pack(pady=20)
            return
        for m in metrics:
            self._render_row(m)

    def _render_row(self, m):
        P = PALETTE
        row = tk.Frame(self.list_frame, bg=P["surface"], padx=12, pady=6,
                       highlightbackground=P["border"], highlightthickness=1)
        row.pack(fill="x", pady=3)
        var = tk.BooleanVar(value=bool(m["enabled"]))
        cb = ttk.Checkbutton(row, variable=var, style="Card.TCheckbutton",
                             command=lambda mid=m["id"]: self.db.set_metric_enabled(mid, var.get()))
        cb.pack(side="left")
        kind = "内置" if m["kind"] == "builtin" else "自定义"
        tk.Label(row, text="{}（{}）".format(m["name"], kind), bg=P["surface"], fg=P["text"],
                 font=("Microsoft YaHei UI", 13, "bold")).pack(side="left", padx=6)
        target_text = "目标 {} {}".format(
            int(m["target"]), m.get("unit") or ""
        ) if m["target"] is not None and int(m["target"]) > 0 else "未设目标"
        tk.Label(row, text=target_text, bg=P["surface"], fg=P["muted"]
                 ).pack(side="left", padx=(10, 0))
        ttk.Button(row, text="设目标",
                   command=lambda mid=m["id"]: self._set_target(mid)
                   ).pack(side="left", padx=4)
        if m["kind"] == "custom":
            ttk.Button(row, text="删除",
                       command=lambda mid=m["id"]: self._delete(mid)).pack(side="left", padx=4)

    def _delete(self, mid):
        if messagebox.askyesno("删除指标", "确定删除该自定义指标吗？", parent=self):
            self.db.delete_metric(mid)
            self._refresh()

    def _set_target(self, mid):
        m = next((x for x in self.db.metric_values() if x["id"] == mid), None)
        if not m:
            return
        cur = int(m["target"]) if m.get("target") is not None else 0
        values = ask_fields(
            self, "设置目标", [
                {"key": "target", "label": "目标值", "type": "integer",
                 "value": str(max(cur, 0)) if cur > 0 else "", "min": 0,
                 "required": True},
            ],
            subtitle="「{}」目标（{}）；留空表示取消目标".format(
                m["name"], m.get("unit") or "次"),
        )
        if values is not None:
            self.db.set_metric_target(mid, values["target"])
            self._refresh()

    def _add(self):
        values = ask_fields(
            self, "新增自定义指标", [
                {"key": "name", "label": "指标名称", "required": True,
                 "placeholder": "例如：每日刷题数"},
                {"key": "unit", "label": "单位", "placeholder": "例如：题"},
                {"key": "target", "label": "目标值", "type": "integer",
                 "min": 0},
            ],
            subtitle="新增后出现在总体进度卡片中",
        )
        if not values:
            return
        self.db.add_custom_metric(
            values["name"].strip(), values["unit"].strip(), values["target"]
        )
        self._refresh()
