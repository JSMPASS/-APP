"""计划设置：结构化列表 + 双击打开统一编辑表单，保存后供铺排与展示使用。"""
from __future__ import annotations

import copy
import tkinter as tk
from tkinter import messagebox, ttk

from habit_checkin.services.study_plan import get_plan_config, save_plan_config
from habit_checkin.ui.animate import fade_in
from habit_checkin.ui.common import center_window, setup_styles
from habit_checkin.ui.field_edit_dialog import ask_fields
from habit_checkin.ui.theme import PALETTE, dialog_header


class PlanSettingsDialog(tk.Toplevel):
    """计划配置编辑：阶段/周/检查点/作息用列表展示，双击单项打开统一表单。"""

    def __init__(self, master, db):
        super().__init__(master)
        self.db = db
        self.config = copy.deepcopy(get_plan_config(db))
        self.title("计划设置")
        self.geometry("860x640")
        self.minsize(760, 560)
        self.transient(master)
        setup_styles(self)
        self.configure(bg=PALETTE["bg"])
        dialog_header(self, "计划设置", "自定义天数 · 阶段 · 逐周计划 · 检查点 · 作息模板")
        self._build_ui()
        self._fill()
        center_window(self)
        fade_in(self)
        self.grab_set()

    # ---------- 构建 ----------
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
        tk.Label(row, text="总天数：", bg=P["bg"], font=("Microsoft YaHei UI", 13)
                 ).pack(side="left")
        self.days_var = tk.StringVar(value=str(self.config["total_days"]))
        ttk.Spinbox(row, from_=7, to=365, width=6,
                    textvariable=self.days_var).pack(side="left")
        tk.Label(basic, text="总天数会同步影响逐周计划数量、检查点上限与热力图天数。",
                 bg=P["bg"], fg=P["muted"], font=("Microsoft YaHei UI", 11)
                 ).pack(anchor="w", pady=(8, 0))

        self.stages_tab, self.stages_tree = self._tree_tab(
            nb, "阶段内容", ("name", "range"), ("阶段名称", "天数范围"),
            "双击阶段行可编辑；右键选中后可删除。",
        )
        self._stage_buttons = tk.Frame(self.stages_tab, bg=PALETTE["bg"])
        self._stage_buttons.pack(fill="x", pady=(4, 0))
        ttk.Button(self._stage_buttons, text="＋ 新增阶段",
                   command=self._add_stage).pack(side="left")
        ttk.Button(self._stage_buttons, text="删除选中",
                   command=self._delete_selected_stage).pack(side="left", padx=6)

        self.weeks_tab, self.weeks_tree = self._tree_tab(
            nb, "逐周计划", ("week", "focus"), ("周次", "本周重点"),
            "双击周行可编辑；周数由总天数自动确定。",
        )

        self.cp_tab, self.cp_tree = self._tree_tab(
            nb, "检查点", ("day", "content"), ("检查天数", "检查内容"),
            "双击检查点行可编辑；右键选中后可删除。",
        )
        self._cp_buttons = tk.Frame(self.cp_tab, bg=PALETTE["bg"])
        self._cp_buttons.pack(fill="x", pady=(4, 0))
        ttk.Button(self._cp_buttons, text="＋ 新增检查点",
                   command=self._add_checkpoint).pack(side="left")
        ttk.Button(self._cp_buttons, text="删除选中",
                   command=self._delete_selected_checkpoint).pack(side="left", padx=6)

        self.routine_tab, self.routine_tree = self._tree_tab(
            nb, "每日作息模板", ("time", "desc"), ("时间", "内容"),
            "双击作息行可编辑；右键选中后可删除。",
        )
        self._routine_buttons = tk.Frame(self.routine_tab, bg=PALETTE["bg"])
        self._routine_buttons.pack(fill="x", pady=(4, 0))
        ttk.Button(self._routine_buttons, text="＋ 新增作息项",
                   command=self._add_routine).pack(side="left")
        ttk.Button(self._routine_buttons, text="删除选中",
                   command=self._delete_selected_routine).pack(side="left", padx=6)

        bottom = tk.Frame(self, bg=P["bg"], padx=14, pady=10)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="取消", command=self.destroy).pack(side="right")
        ttk.Button(bottom, text="保存", style="Accent.TButton",
                   command=self._save).pack(side="right", padx=8)

    def _tree_tab(self, nb, title, cols, headings, hint):
        P = PALETTE
        tab = ttk.Frame(nb, padding=10)
        nb.add(tab, text=title)
        tk.Label(tab, text=hint, bg=P["bg"], fg=P["muted"],
                 font=("Microsoft YaHei UI", 11)).pack(anchor="w")
        tree = ttk.Treeview(tab, columns=cols, show="headings", selectmode="browse")
        for col, head in zip(cols, headings):
            tree.heading(col, text=head)
            tree.column(col, width=120 if col in ("week", "day", "time") else 520,
                        anchor="w")
        vsb = ttk.Scrollbar(tab, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", fill="both", expand=True, pady=(6, 0))
        vsb.pack(side="right", fill="y", pady=(6, 0))
        return tab, tree

    # ---------- 数据填充 ----------
    def _fill(self):
        self._fill_stages()
        self._fill_weeks()
        self._fill_checkpoints()
        self._fill_routine()

    def _fill_stages(self):
        self.stages_tree.delete(*self.stages_tree.get_children())
        self._stage_map = {}
        for idx, s in enumerate(self.config["stages"]):
            iid = self.stages_tree.insert(
                "", "end",
                values=(s["name"], "第 {} ~ {} 天".format(s["day_start"], s["day_end"])),
            )
            self._stage_map[iid] = idx
        self.stages_tree.bind(
            "<Double-1>",
            lambda e: self._edit_stage(
                self._index_at_event(self.stages_tree, self._stage_map, e)))

    def _fill_weeks(self):
        self.weeks_tree.delete(*self.weeks_tree.get_children())
        self._week_map = {}
        for wk, focus in self.config["weeks"]:
            iid = self.weeks_tree.insert("", "end", values=("第 {} 周".format(wk), focus))
            self._week_map[iid] = wk
        self.weeks_tree.bind(
            "<Double-1>",
            lambda e: self._edit_week(
                self._index_at_event(self.weeks_tree, self._week_map, e)))

    def _fill_checkpoints(self):
        self.cp_tree.delete(*self.cp_tree.get_children())
        self._cp_map = {}
        for idx, (day, content) in enumerate(self.config["checkpoints"]):
            iid = self.cp_tree.insert("", "end", values=("第 {} 天".format(day), content))
            self._cp_map[iid] = idx
        self.cp_tree.bind(
            "<Double-1>",
            lambda e: self._edit_checkpoint(
                self._index_at_event(self.cp_tree, self._cp_map, e)))

    def _fill_routine(self):
        self.routine_tree.delete(*self.routine_tree.get_children())
        self._routine_map = {}
        for idx, (tm, desc) in enumerate(self.config["daily_routine"]):
            iid = self.routine_tree.insert("", "end", values=(tm, desc))
            self._routine_map[iid] = idx
        self.routine_tree.bind(
            "<Double-1>",
            lambda e: self._edit_routine(
                self._index_at_event(self.routine_tree, self._routine_map, e)))

    def _selected_index(self, tree, mapping):
        sel = tree.selection()
        if sel:
            return mapping.get(sel[0])
        return None

    def _index_at_event(self, tree, mapping, event):
        iid = tree.identify_row(event.y)
        if iid:
            tree.selection_set(iid)
            return mapping.get(iid)
        return None

    # ---------- 阶段 ----------
    def _edit_stage(self, index):
        if index is None or index >= len(self.config["stages"]):
            return
        s = self.config["stages"][index]
        total = self._current_total_days()
        values = ask_fields(
            self, "编辑阶段", [
                {"key": "name", "label": "阶段名称", "value": s["name"],
                 "required": True},
                {"key": "day_start", "label": "开始天数", "type": "integer",
                 "value": str(s["day_start"]), "min": 1, "required": True},
                {"key": "day_end", "label": "结束天数", "type": "integer",
                 "value": str(s["day_end"]), "min": 1, "max": total,
                 "required": True},
                {"key": "xingce", "label": "行测内容", "type": "multiline",
                 "height": 3, "value": s.get("xingce", "")},
                {"key": "shenlun", "label": "申论内容", "type": "multiline",
                 "height": 3, "value": s.get("shenlun", "")},
                {"key": "exit", "label": "退出标准", "type": "multiline",
                 "height": 3, "value": s.get("exit", "")},
            ],
            subtitle="修改后将同步到已导入的计划文档",
        )
        if not values:
            return
        if values["day_end"] < values["day_start"]:
            messagebox.showwarning("编辑阶段", "结束天数不能小于开始天数。", parent=self)
            return
        self.config["stages"][index] = {
            "name": values["name"].strip() or s["name"],
            "day_start": values["day_start"],
            "day_end": values["day_end"],
            "xingce": values["xingce"],
            "shenlun": values["shenlun"],
            "exit": values["exit"],
        }
        self._fill_stages()

    def _add_stage(self):
        total = self._current_total_days()
        last = self.config["stages"][-1] if self.config["stages"] else None
        start = (last["day_end"] + 1) if last else 1
        end = min(total, start + 6)
        values = ask_fields(
            self, "新增阶段", [
                {"key": "name", "label": "阶段名称", "required": True,
                 "placeholder": "例如：基础阶段"},
                {"key": "day_start", "label": "开始天数", "type": "integer",
                 "value": str(start), "min": 1, "required": True},
                {"key": "day_end", "label": "结束天数", "type": "integer",
                 "value": str(end), "min": 1, "max": total, "required": True},
                {"key": "xingce", "label": "行测内容", "type": "multiline",
                 "height": 3},
                {"key": "shenlun", "label": "申论内容", "type": "multiline",
                 "height": 3},
                {"key": "exit", "label": "退出标准", "type": "multiline", "height": 3},
            ],
            subtitle="新增阶段会按开始/结束天数参与计划铺排",
        )
        if not values:
            return
        if values["day_end"] < values["day_start"]:
            messagebox.showwarning("新增阶段", "结束天数不能小于开始天数。", parent=self)
            return
        self.config["stages"].append({
            "name": values["name"].strip(),
            "day_start": values["day_start"],
            "day_end": values["day_end"],
            "xingce": values["xingce"],
            "shenlun": values["shenlun"],
            "exit": values["exit"],
        })
        self.config["stages"].sort(key=lambda s: s["day_start"])
        self._fill_stages()

    def _delete_selected_stage(self):
        idx = self._selected_index(self.stages_tree, self._stage_map)
        if idx is None:
            return
        if len(self.config["stages"]) <= 1:
            messagebox.showwarning("删除阶段", "至少需要一个阶段。", parent=self)
            return
        s = self.config["stages"][idx]
        if not messagebox.askyesno("删除阶段", "确定删除「{}」吗？".format(s["name"]),
                                   parent=self):
            return
        del self.config["stages"][idx]
        self._fill_stages()

    # ---------- 周计划 ----------
    def _edit_week(self, week_num):
        if week_num is None:
            return
        focus = next((f for wk, f in self.config["weeks"] if wk == week_num), "")
        values = ask_fields(
            self, "编辑第 {} 周".format(week_num), [
                {"key": "focus", "label": "本周重点", "type": "multiline",
                 "height": 4, "value": focus, "required": True},
            ],
            subtitle="日期范围由开始日期自动计算",
        )
        if not values:
            return
        self.config["weeks"] = [
            [wk, values["focus"] if wk == week_num else f]
            for wk, f in self.config["weeks"]
        ]
        self._fill_weeks()

    # ---------- 检查点 ----------
    def _edit_checkpoint(self, index):
        if index is None or index >= len(self.config["checkpoints"]):
            return
        day, content = self.config["checkpoints"][index]
        total = self._current_total_days()
        values = ask_fields(
            self, "编辑检查点 · 第 {} 天".format(day), [
                {"key": "day", "label": "检查天数", "type": "integer",
                 "value": str(day), "min": 1, "max": total, "required": True},
                {"key": "content", "label": "检查内容", "type": "multiline",
                 "height": 4, "value": content, "required": True},
            ],
            subtitle="检查点用于阶段自测与复盘提醒",
        )
        if not values:
            return
        self.config["checkpoints"][index] = [values["day"], values["content"]]
        self._fill_checkpoints()

    def _add_checkpoint(self):
        total = self._current_total_days()
        default_day = (self.config["checkpoints"][-1][0] + 1
                       if self.config["checkpoints"] else 1)
        default_day = min(default_day, total)
        values = ask_fields(
            self, "新增检查点", [
                {"key": "day", "label": "检查天数", "type": "integer",
                 "value": str(default_day), "min": 1, "max": total,
                 "required": True},
                {"key": "content", "label": "检查内容", "type": "multiline",
                 "height": 4, "required": True},
            ],
            subtitle="检查点用于阶段自测与复盘提醒",
        )
        if not values:
            return
        self.config["checkpoints"].append([values["day"], values["content"]])
        self.config["checkpoints"].sort(key=lambda cp: cp[0])
        self._fill_checkpoints()

    def _delete_selected_checkpoint(self):
        idx = self._selected_index(self.cp_tree, self._cp_map)
        if idx is None:
            return
        day, content = self.config["checkpoints"][idx]
        if not messagebox.askyesno(
            "删除检查点", "确定删除「第 {} 天 · {}」吗？".format(day, content[:20]),
            parent=self,
        ):
            return
        del self.config["checkpoints"][idx]
        self._fill_checkpoints()

    # ---------- 作息 ----------
    def _edit_routine(self, index):
        if index is None or index >= len(self.config["daily_routine"]):
            return
        tm, desc = self.config["daily_routine"][index]
        values = ask_fields(
            self, "编辑作息 {}".format(tm), [
                {"key": "time", "label": "时间", "type": "time", "value": tm,
                 "required": True},
                {"key": "desc", "label": "内容", "type": "multiline",
                 "height": 4, "value": desc, "required": True},
            ],
            subtitle="每日作息模板会随计划文档一起保存",
        )
        if not values:
            return
        self.config["daily_routine"][index] = [values["time"], values["desc"]]
        self._fill_routine()

    def _add_routine(self):
        default_time = "08:00"
        if self.config["daily_routine"]:
            last = self.config["daily_routine"][-1][0]
            parts = last.split(":")
            default_time = "{:02d}:00".format((int(parts[0]) + 1) % 24)
        values = ask_fields(
            self, "新增作息项", [
                {"key": "time", "label": "时间", "type": "time",
                 "value": default_time, "required": True},
                {"key": "desc", "label": "内容", "type": "multiline",
                 "height": 4, "required": True},
            ],
            subtitle="每日作息模板会随计划文档一起保存",
        )
        if not values:
            return
        self.config["daily_routine"].append([values["time"], values["desc"]])
        self.config["daily_routine"].sort(key=lambda r: r[0])
        self._fill_routine()

    def _delete_selected_routine(self):
        idx = self._selected_index(self.routine_tree, self._routine_map)
        if idx is None:
            return
        tm, desc = self.config["daily_routine"][idx]
        if not messagebox.askyesno(
            "删除作息项", "确定删除「{} · {}」吗？".format(tm, desc[:20]),
            parent=self,
        ):
            return
        del self.config["daily_routine"][idx]
        self._fill_routine()

    # ---------- 保存 ----------
    def _current_total_days(self):
        try:
            return max(7, int(self.days_var.get().strip()))
        except (ValueError, AttributeError):
            return self.config["total_days"]

    def _save(self):
        try:
            total_days = int(self.days_var.get().strip())
        except ValueError:
            messagebox.showwarning("计划设置", "总天数必须是数字。", parent=self)
            return
        if total_days < 1:
            messagebox.showwarning("计划设置", "总天数至少为 1。", parent=self)
            return
        if not self.config["stages"]:
            messagebox.showwarning("阶段内容", "至少需要一个阶段。", parent=self)
            return
        if self.config["stages"][-1]["day_end"] > total_days:
            self.config["stages"][-1]["day_end"] = total_days
        week_count = (total_days + 6) // 7
        existing = {w[0]: w[1] for w in self.config["weeks"]}
        self.config["weeks"] = [[i, existing.get(i, "")] for i in range(1, week_count + 1)]
        self.config["checkpoints"] = [
            [d, c] for d, c in self.config["checkpoints"] if 1 <= d <= total_days
        ]
        self.config["total_days"] = total_days
        save_plan_config(self.db, self.config)
        self.destroy()
