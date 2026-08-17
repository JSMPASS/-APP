"""计划设置：自定义总天数、阶段、逐周计划、检查点与每日作息模板。"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from habit_checkin.services.study_plan import get_plan_config, save_plan_config
from habit_checkin.ui.animate import fade_in
from habit_checkin.ui.common import center_window, setup_styles
from habit_checkin.ui.theme import PALETTE, dialog_header


def _stage_line(s):
    return "{} | {} | {} | {} | {} | {}".format(
        s["name"], s["day_start"], s["day_end"],
        s.get("xingce", ""), s.get("shenlun", ""), s.get("exit", ""),
    )


def _parse_stages(text):
    stages = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 3:
            raise ValueError("阶段行格式：名称 | 开始天 | 结束天 | 行测 | 申论 | 退出标准")
        name = parts[0]
        try:
            day_start = int(parts[1])
            day_end = int(parts[2])
        except ValueError:
            raise ValueError("阶段天数必须是数字：{}".format(name))
        if day_start < 1 or day_end < day_start:
            raise ValueError("阶段天数范围不合法：{}".format(name))
        stages.append({
            "name": name,
            "day_start": day_start,
            "day_end": day_end,
            "xingce": parts[3] if len(parts) > 3 else "",
            "shenlun": parts[4] if len(parts) > 4 else "",
            "exit": parts[5] if len(parts) > 5 else "",
        })
    return stages


class PlanSettingsDialog(tk.Toplevel):
    """计划配置编辑：按行编辑，保存后供铺排、展示与模板下载使用。"""

    def __init__(self, master, db):
        super().__init__(master)
        self.db = db
        self.config = get_plan_config(db)
        self.title("计划设置")
        self.geometry("860x640")
        self.transient(master)
        setup_styles(self)
        self.configure(bg=PALETTE["bg"])
        dialog_header(self, "计划设置", "自定义天数 · 阶段 · 逐周计划 · 检查点 · 作息模板")
        self._build_ui()
        center_window(self)
        fade_in(self)
        self.grab_set()

    def _build_ui(self):
        P = PALETTE
        body = tk.Frame(self, bg=P["bg"], padx=14, pady=10)
        body.pack(fill="both", expand=True)
        nb = ttk.Notebook(body)
        nb.pack(fill="both", expand=True)

        basic = ttk.Frame(nb, padding=14)
        nb.add(basic, text="基本设置")
        row = tk.Frame(basic, bg=P["bg"])
        row.pack(fill="x")
        tk.Label(row, text="总天数：", bg=P["bg"], font=("Microsoft YaHei UI", 13)).pack(side="left")
        self.days_var = tk.StringVar(value=str(self.config["total_days"]))
        ttk.Spinbox(row, from_=7, to=365, width=6, textvariable=self.days_var).pack(side="left")
        tk.Label(basic, text="总天数会同步影响逐周计划数量、检查点上限与热力图天数。",
                 bg=P["bg"], fg=P["muted"], font=("Microsoft YaHei UI", 11)).pack(anchor="w", pady=(8, 0))

        stages_tab = ttk.Frame(nb, padding=10)
        nb.add(stages_tab, text="阶段内容")
        tk.Label(stages_tab, text="每行一个阶段（行数即阶段数），格式：名称 | 开始天 | 结束天 | 行测 | 申论 | 退出标准",
                 bg=PALETTE["bg"], fg=PALETTE["muted"]).pack(anchor="w")
        self.stages_text = tk.Text(stages_tab, wrap="none", font=("Microsoft YaHei UI", 11),
                                   bg=PALETTE["input"], fg=PALETTE["text"])
        self.stages_text.pack(fill="both", expand=True, pady=(4, 0))

        weeks_tab = ttk.Frame(nb, padding=10)
        nb.add(weeks_tab, text="逐周计划")
        tk.Label(weeks_tab, text="每行一个周，格式：周序号 | 本周重点（日期范围由开始日期自动计算）",
                 bg=PALETTE["bg"], fg=PALETTE["muted"]).pack(anchor="w")
        self.weeks_text = tk.Text(weeks_tab, wrap="none", font=("Microsoft YaHei UI", 11),
                                  bg=PALETTE["input"], fg=PALETTE["text"])
        self.weeks_text.pack(fill="both", expand=True, pady=(4, 0))

        cp_tab = ttk.Frame(nb, padding=10)
        nb.add(cp_tab, text="检查点")
        tk.Label(cp_tab, text="每行一个检查点，格式：第几天 | 检查内容",
                 bg=PALETTE["bg"], fg=PALETTE["muted"]).pack(anchor="w")
        self.checkpoints_text = tk.Text(cp_tab, wrap="none", font=("Microsoft YaHei UI", 11),
                                        bg=PALETTE["input"], fg=PALETTE["text"])
        self.checkpoints_text.pack(fill="both", expand=True, pady=(4, 0))

        routine_tab = ttk.Frame(nb, padding=10)
        nb.add(routine_tab, text="每日作息模板")
        tk.Label(routine_tab, text="每行一个作息项，格式：HH:MM | 内容",
                 bg=PALETTE["bg"], fg=PALETTE["muted"]).pack(anchor="w")
        self.routine_text = tk.Text(routine_tab, wrap="none", font=("Microsoft YaHei UI", 11),
                                    bg=PALETTE["input"], fg=PALETTE["text"])
        self.routine_text.pack(fill="both", expand=True, pady=(4, 0))

        self._fill()

        bottom = tk.Frame(self, bg=P["bg"], padx=14, pady=10)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="取消", command=self.destroy).pack(side="right")
        ttk.Button(bottom, text="保存", style="Accent.TButton", command=self._save).pack(side="right", padx=8)

    def _fill(self):
        cfg = self.config
        self.stages_text.insert("1.0", "\n".join(_stage_line(s) for s in cfg["stages"]))
        self.weeks_text.insert("1.0", "\n".join("{} | {}".format(wk, focus) for wk, focus in cfg["weeks"]))
        self.checkpoints_text.insert("1.0", "\n".join("{} | {}".format(day, content) for day, content in cfg["checkpoints"]))
        self.routine_text.insert("1.0", "\n".join("{} | {}".format(tm, desc) for tm, desc in cfg["daily_routine"]))

    def _save(self):
        try:
            total_days = max(1, int(self.days_var.get().strip()))
        except ValueError:
            messagebox.showwarning("计划设置", "总天数必须是数字。", parent=self)
            return
        try:
            stages = _parse_stages(self.stages_text.get("1.0", "end"))
        except ValueError as exc:
            messagebox.showwarning("阶段内容", str(exc), parent=self)
            return
        if not stages:
            messagebox.showwarning("阶段内容", "至少需要一个阶段。", parent=self)
            return
        if stages[-1]["day_end"] > total_days:
            stages[-1]["day_end"] = total_days

        try:
            weeks = []
            for raw in self.weeks_text.get("1.0", "end").splitlines():
                line = raw.strip()
                if not line:
                    continue
                parts = [p.strip() for p in line.split("|")]
                if len(parts) < 2:
                    raise ValueError("逐周计划格式：周序号 | 本周重点")
                weeks.append([int(parts[0]), parts[1]])
            week_count = (total_days + 6) // 7
            weeks = [w for w in weeks if w[0] >= 1][:week_count]
            existing = {w[0]: w[1] for w in weeks}
            weeks = [[i, existing.get(i, "")] for i in range(1, week_count + 1)]

            checkpoints = []
            for raw in self.checkpoints_text.get("1.0", "end").splitlines():
                line = raw.strip()
                if not line:
                    continue
                parts = [p.strip() for p in line.split("|")]
                if len(parts) < 2:
                    raise ValueError("检查点格式：第几天 | 检查内容")
                day = int(parts[0])
                if 1 <= day <= total_days:
                    checkpoints.append([day, parts[1]])

            routine = []
            for raw in self.routine_text.get("1.0", "end").splitlines():
                line = raw.strip()
                if not line:
                    continue
                parts = [p.strip() for p in line.split("|")]
                if len(parts) < 2:
                    raise ValueError("作息模板格式：HH:MM | 内容")
                routine.append([parts[0], parts[1]])
        except ValueError as exc:
            messagebox.showwarning("计划设置", str(exc), parent=self)
            return

        config = {
            "total_days": total_days,
            "stages": stages,
            "weeks": weeks,
            "checkpoints": checkpoints,
            "daily_routine": routine,
        }
        save_plan_config(self.db, config)
        self.destroy()
