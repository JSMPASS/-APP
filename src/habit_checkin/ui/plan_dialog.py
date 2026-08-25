"""制定计划对话框：选择日期 -> 勾选知识点 -> 设置每项提醒时间。"""
from __future__ import annotations

import tkinter as tk
from datetime import date
from tkinter import messagebox, ttk

from habit_checkin.db import validate_date, validate_time
from habit_checkin.services.clipboard_utils import bind_entry_undo, bind_text_paste
from habit_checkin.ui.calendar import attach_calendar_on_click
from habit_checkin.ui.common import ScrollableFrame, TimePicker, setup_styles
from habit_checkin.ui.animate import fade_in
from habit_checkin.ui.theme import PALETTE, dialog_header
from habit_checkin.ui.topic_tree import TopicTreeMixin

TIME_HINT = "HH:MM，留空不提醒"


class PlanDialog(TopicTreeMixin, tk.Toplevel):
    def __init__(self, master, db, date_str):
        super().__init__(master)
        self.db = db
        self.date_str = date_str
        self.selected = {}  # topic_id -> reminder_time ("" or "HH:MM")
        self.existing = {}  # topic_id -> item dict（编辑已有计划时）
        self.plan = db.get_plan(date_str)
        if self.plan:
            for it in db.get_plan_items(self.plan["id"]):
                self.existing[it["topic_id"]] = it
                self.selected[it["topic_id"]] = it["reminder_time"] or ""
        self.title("制定计划" if not self.plan else "编辑计划（{}）".format(date_str))
        self.geometry("1120x850")
        self.minsize(1000, 740)
        self.transient(master)
        self._center()
        setup_styles(self)
        self.configure(bg=PALETTE["bg"])
        self._build_ui()
        self._populate_tree()
        self._rebuild_selected()
        self.grab_set()
        self.focus_set()
        fade_in(self)

    # ---------- 界面 ----------
    def _center(self):
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        x = max((self.winfo_screenwidth() - w) // 2, 0)
        y = max((self.winfo_screenheight() - h) // 2, 0)
        self.geometry("+{}+{}".format(x, y))

    def _build_ui(self):
        dialog_header(self, self.title(), "选择知识点 · 设置提醒时间")
        top = ttk.Frame(self, padding=(12, 10))
        top.pack(fill="x")
        ttk.Label(top, text="日期：").pack(side="left")
        self.date_entry = ttk.Entry(top, width=12)
        bind_text_paste(self.date_entry)
        self.date_entry.insert(0, self.date_str)
        bind_entry_undo(self.date_entry)
        self.date_entry.pack(side="left", padx=(0, 6))
        attach_calendar_on_click(self.date_entry, lambda ds: self._set_date(ds))
        ttk.Button(top, text="今天", command=lambda: self._set_date(date.today().isoformat())).pack(
            side="left", padx=2
        )
        ttk.Button(top, text="+1 天", command=lambda: self._shift_date(1)).pack(side="left", padx=2)
        ttk.Button(top, text="-1 天", command=lambda: self._shift_date(-1)).pack(side="left", padx=2)
        ttk.Label(top, text="（格式 YYYY-MM-DD）", style="Hint.TLabel").pack(side="left", padx=6)

        bottom = ttk.Frame(self, padding=12)
        bottom.pack(side="bottom", fill="x")
        self.count_label = ttk.Label(bottom, text="已选 0 项")
        self.count_label.pack(side="left")
        ttk.Button(bottom, text="取消", command=self.destroy).pack(side="right")
        ttk.Button(bottom, text="保存", style="Accent.TButton", command=self._save).pack(side="right", padx=8)

        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=12, pady=(0, 6))

        # 左侧：科目树
        left = ttk.LabelFrame(body, text="选择知识点（点击分类展开/勾选；长按拖动调整顺序/层级；右键增删改）", padding=6)
        body.add(left, weight=2)
        self.tree = ttk.Treeview(left, columns=("check",), show="tree", selectmode="none")
        self.tree.heading("#0", text="知识点")
        self.tree.column("#0", width=290, anchor="w")
        self.tree.pack(side="left", fill="both", expand=True)
        lvsb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=lvsb.set)
        lvsb.pack(side="right", fill="y")
        self.tree.tag_configure("drag_target", background=PALETTE["primary_light"])
        self._drag_item = None
        self._drag_active = False
        self._drag_press_time = 0.0
        self._drag_target = None
        self.tree.bind("<ButtonPress-1>", self._on_drag_press)
        self.tree.bind("<B1-Motion>", self._on_drag_motion)
        self.tree.bind("<ButtonRelease-1>", self._on_drag_release)
        self.tree.bind("<Button-3>", self._on_right_click)

        # 右侧：已选列表 + 时间
        right = ttk.LabelFrame(body, text="已选打卡项（勾选「提醒」后设置时/分）", padding=6)
        body.add(right, weight=3)
        self.sel_scroll = ScrollableFrame(right)
        self.sel_scroll.pack(fill="both", expand=True)
        self.sel_inner = self.sel_scroll.inner



    # ---------- 科目树 ----------
    def _populate_tree(self):
        self.tree.delete(*self.tree.get_children())
        topics = self.db.list_topics(include_disabled=False)
        children = {}
        for t in topics:
            children.setdefault(t["parent_id"], []).append(t)
        roots = children.get(None, [])

        def add_node(parent_iid, t):
            iid = "t{}".format(t["id"])
            kids = children.get(t["id"], [])
            has_kids = bool(kids)
            mark = "☑ " if t["id"] in self.selected else ("☐ " if not has_kids else "")
            self.tree.insert(
                parent_iid, "end", iid=iid, text="{}{}".format(mark, t["name"]),
                open=True,
            )
            for kid in kids:
                add_node(iid, kid)
            return iid

        for r in roots:
            add_node("", r)

    def _refresh_tree(self):
        self._populate_tree()

    def _on_tree_click(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        topic_id = int(iid[1:])
        kids = self.tree.get_children(iid)
        if kids:
            if self.tree.item(iid, "open"):
                self.tree.item(iid, open=False)
            else:
                self.tree.item(iid, open=True)
        else:
            self._toggle_topic(topic_id)

    def _toggle_topic(self, topic_id):
        if topic_id in self.selected:
            del self.selected[topic_id]
        else:
            self.selected[topic_id] = ""
        self._sync_tree_mark(topic_id)
        self._rebuild_selected()

    def _sync_tree_mark(self, topic_id):
        iid = "t{}".format(topic_id)
        if not self.tree.exists(iid):
            return
        name = self.tree.item(iid, "text")
        name = name[2:] if name[:2] in ("☑ ", "☐ ") else name
        mark = "☑ " if topic_id in self.selected else "☐ "
        self.tree.item(iid, text=mark + name)

    def _after_topic_changed(self, topic_id):
        self.selected.pop(topic_id, None)
        self._rebuild_selected()

    def _on_tree_order_error(self):
        self._reload_for_date()

    # ---------- 已选列表 ----------
    def _rebuild_selected(self):
        for w in self.sel_inner.winfo_children():
            w.destroy()
        self._sel_pickers = {}
        for idx, (topic_id, tm) in enumerate(sorted(self.selected.items())):
            row = ttk.Frame(self.sel_inner, padding=(4, 3))
            row.pack(fill="x")
            ttk.Label(row, text=self.db.topic_path(topic_id), width=20, anchor="w", style="Card.TLabel").pack(side="left")
            picker = TimePicker(row, initial=tm or None)
            picker.pack(side="left", padx=6)
            self._sel_pickers[topic_id] = picker
            ttk.Button(row, text="✕", width=3, command=lambda tid=topic_id: self._toggle_topic(tid)).pack(
                side="left"
            )
        self.count_label.configure(text="已选 {} 项".format(len(self.selected)))

    # ---------- 日期 ----------
    def _set_date(self, d):
        self.date_entry.delete(0, "end")
        self.date_entry.insert(0, d)
        self._reload_for_date()

    def _shift_date(self, delta):
        try:
            d = validate_date(self.date_entry.get())
        except ValueError:
            d = self.date_str
        from datetime import timedelta
        self._set_date((date.fromisoformat(d) + timedelta(days=delta)).isoformat())

    def _reload_for_date(self):
        """按当前输入日期重新加载已有计划的选择状态（用于切换日期后）。"""
        try:
            day = validate_date(self.date_entry.get())
        except ValueError:
            return
        self.plan = self.db.get_plan(day)
        self.existing = {}
        self.selected = {}
        if self.plan:
            for it in self.db.get_plan_items(self.plan["id"]):
                self.existing[it["topic_id"]] = it
                self.selected[it["topic_id"]] = it["reminder_time"] or ""
        self.tree.delete(*self.tree.get_children())
        self._populate_tree()
        self._rebuild_selected()

    def _collect_times(self):
        """从右侧时间选择器收集提醒时间。"""
        result = {}
        for tid, picker in self._sel_pickers.items():
            try:
                result[tid] = validate_time(picker.get() or "")
            except ValueError as exc:
                raise ValueError("「{}」{}".format(self.db.topic_path(tid), exc))
        return result

    def _save(self):
        try:
            day = validate_date(self.date_entry.get())
        except ValueError as exc:
            messagebox.showwarning("日期错误", str(exc), parent=self)
            return
        if not self.selected:
            messagebox.showwarning("未选择打卡项", "请至少勾选一个知识点。", parent=self)
            return
        try:
            times = self._collect_times()
        except ValueError as exc:
            messagebox.showwarning("提醒时间错误", str(exc), parent=self)
            return

        plan = self.db.get_plan(day)
        if not plan:
            plan_id = self.db.create_plan(day, title="")
        else:
            plan_id = plan["id"]
        existing = {it["topic_id"]: it for it in self.db.get_plan_items(plan_id)}

        # 待删除项（勾选被移除且已存在）
        removed = [existing[tid] for tid in existing if tid not in self.selected]
        removed_with_data = [it for it in removed if it["done"] or (it["note"] or "").strip() or it["images"]]
        if removed_with_data:
            names = "\n".join("· {}".format(it["topic_path"]) for it in removed_with_data)
            ok = messagebox.askyesno(
                "删除确认",
                "以下打卡项已被取消勾选，且已有打卡内容，删除后不可恢复：\n{}\n\n"
                "题库题目将保留为未分类，来源标记失效。是否删除？".format(names),
                parent=self,
            )
            if not ok:
                return

        for tid, tm in times.items():
            if tid not in existing:
                self.db.add_plan_item(plan_id, tid, tm)
            else:
                if existing[tid]["reminder_time"] != tm:
                    self.db.set_item_reminder(existing[tid]["id"], tm)
        for it in removed:
            self.db.delete_plan_item(it["id"])
        self.destroy()
