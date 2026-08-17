"""题库窗口：题目列表、筛选搜索、增删改查、练习复盘入口。"""
from __future__ import annotations

import tkinter as tk
from datetime import date
from tkinter import messagebox, ttk

from habit_checkin.ui.common import center_window, setup_styles
from habit_checkin.ui.theme import PALETTE, dialog_header
from habit_checkin.ui.question_form_dialog import QuestionFormDialog, RESULT_LABELS
from habit_checkin.ui.reflection_window import ReflectionFormDialog
from habit_checkin.ui.topic_colors import configure_topic_tags, topic_tag

_COLUMNS = ("code", "topic", "result", "source", "day", "reflected")


class QuestionBankWindow(tk.Frame):
    def __init__(self, master, db):
        super().__init__(master, bg=PALETTE["bg"])
        self.db = db
        self._sub_options = []
        setup_styles(self)
        self.configure(bg=PALETTE["bg"])
        self._build_ui()
        self._query()

    def _build_ui(self):
        P = PALETTE
        dialog_header(self, "题库", "题目收录 · 对错分类 · 练习复盘")
        top = tk.Frame(self, bg=P["bg"], padx=14, pady=12)
        top.pack(fill="x")
        ttk.Button(top, text="＋ 新增题目", style="Accent.TButton", command=self._add).pack(side="left")
        ttk.Button(top, text="编辑", command=self._edit).pack(side="left", padx=8)
        ttk.Button(top, text="复盘", style="Accent.TButton", command=self._reflect).pack(side="left", padx=8)
        ttk.Button(top, text="删除", command=self._delete).pack(side="left", padx=8)

        tk.Label(top, text="科目：", bg=P["bg"]).pack(side="left", padx=(16, 0))
        self.filter_var = tk.StringVar(value="全部")
        roots = self.db.root_topics()
        self.filter_box = ttk.Combobox(top, textvariable=self.filter_var, state="readonly", width=10,
                                       values=["全部"] + [r["name"] for r in roots])
        self.filter_box.pack(side="left", padx=(0, 8))
        tk.Label(top, text="细分：", bg=P["bg"]).pack(side="left")
        self.sub_filter_var = tk.StringVar(value="全部细分")
        self.sub_filter_box = ttk.Combobox(
            top, textvariable=self.sub_filter_var, state="readonly", width=16,
            values=["全部细分"],
        )
        self.sub_filter_box.pack(side="left", padx=(0, 8))
        self.filter_box.bind("<<ComboboxSelected>>", self._on_root_change)
        tk.Label(top, text="对错：", bg=P["bg"]).pack(side="left")
        self.result_var = tk.StringVar(value="全部")
        self.result_box = ttk.Combobox(top, textvariable=self.result_var, state="readonly", width=8,
                                       values=["全部", "正确", "错误", "未判定"])
        self.result_box.pack(side="left", padx=(0, 8))
        self.search_entry = ttk.Entry(top, width=14)
        self.search_entry.pack(side="left", padx=(0, 6))
        ttk.Button(top, text="查询", command=self._query).pack(side="left")

        self.summary = tk.Label(self, text="", anchor="w", padx=16, pady=6,
                                bg=P["primary_light"], fg=P["primary_dark"],
                                font=("Microsoft YaHei UI", 13, "bold"))
        self.summary.pack(fill="x")

        list_frame = tk.Frame(self, bg=P["bg"], padx=14, pady=10)
        list_frame.pack(fill="both", expand=True)
        box = tk.Frame(list_frame, bg=P["card"], highlightbackground=P["border"], highlightthickness=1)
        box.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(box, columns=_COLUMNS, show="headings", selectmode="browse")
        headers = [("code", "编号", 80, "center"), ("topic", "分类", 300, "w"),
                   ("result", "对错", 130, "center"), ("source", "来源", 70, "center"),
                   ("day", "日期", 100, "center"), ("reflected", "反思", 80, "center")]
        for col, txt, width, anchor in headers:
            self.tree.heading(col, text=txt)
            self.tree.column(col, width=width, anchor=anchor)
        self.tree.tag_configure("wrong", foreground=P["danger"])
        self.tree.tag_configure("correct", foreground=P["done"])
        self.tree.tag_configure("na", foreground=P["muted"])
        vsb = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda e: self._edit())
    def _on_root_change(self, event=None):
        """科目变化时刷新细分下拉框。"""
        self.sub_filter_var.set("全部细分")
        self._sub_options = []
        root_filter = self.filter_var.get()
        if root_filter == "全部":
            self.sub_filter_box.configure(values=["全部细分"], state="readonly")
            return
        root_id = next(
            (r["id"] for r in self.db.root_topics() if r["name"] == root_filter),
            None,
        )
        if root_id is None:
            self.sub_filter_box.configure(values=["全部细分"], state="readonly")
            return
        self._sub_options = self.db.category_subtopic_paths(root_id)
        self.sub_filter_box.configure(
            values=["全部细分"] + [p for p, _ in self._sub_options],
            state="readonly",
        )

    def _selected_topic_id(self):
        """返回当前筛选的 topic_id；未筛选返回 None。"""
        root_filter = self.filter_var.get()
        if root_filter == "全部":
            return None
        root_id = next(
            (r["id"] for r in self.db.root_topics() if r["name"] == root_filter),
            None,
        )
        if root_id is None:
            return None
        sub_filter = self.sub_filter_var.get()
        if sub_filter == "全部细分":
            return root_id
        for path, tid in getattr(self, "_sub_options", []):
            if path == sub_filter:
                return tid
        return root_id


    def _filters(self):
        topic_id = self._selected_topic_id()
        root_name = self.filter_var.get()
        # if root_name != "全部":
            # for r in self.db.root_topics():
                # if r["name"] == root_name:
                    # topic_id = r["id"]
                    # break
        result = {"正确": "correct", "错误": "wrong"}.get(self.result_var.get())
        search = self.search_entry.get().strip() or None
        return topic_id, result, search

    def _query(self):
        topic_id, result, search = self._filters()
        items = self.db.list_questions(topic_id=topic_id, result=result, search=search)
        self._items = items
        self.tree.delete(*self.tree.get_children())
        configure_topic_tags(self.tree, items)
        wrong_cnt = 0
        for it in items:
            res = RESULT_LABELS.get(it["result"], "未判定")
            reason = it["result_reason"]
            res_text = res + (" · " + reason if reason else "")
            if it["result"] == "wrong":
                tag = "wrong"
                wrong_cnt += 1
            elif it["result"] == "correct":
                tag = "correct"
            else:
                tag = "na"
            source = "打卡" if it["source"] == "checkin" else "手动"
            reflected = "已反思" if ((it["self_analysis"] or "").strip()
                                     or (it["correct_analysis"] or "").strip()
                                     or (it["reflection"] or "").strip()) else "未反思"
            bg_tag = topic_tag(it.get("topic_id"))
            row_tags = (bg_tag, tag) if bg_tag else (tag,)
            self.tree.insert("", "end", iid=str(it["id"]), tags=row_tags,
                             values=(it["code"], it["topic_path"], res_text, source,
                                     (it["created_at"] or "")[:10], reflected))
        self.summary.configure(text="共 {} 题，其中错题 {} 题。双击行可编辑；选中后点「复盘」逐题复盘。".format(
            len(items), wrong_cnt))

    def focus_topic(self, topic_id):
        """导图跳转入口：把筛选定位到指定知识点（含其子知识点）。"""
        if topic_id is None:
            self.filter_var.set("全部")
            self._on_root_change()
            self._query()
            return
        path = self.db.topic_path(topic_id)
        parts = [p.strip() for p in path.split(" / ")] if path else []
        if not parts:
            self.filter_var.set("全部")
            self._on_root_change()
            self._query()
            return
        self.filter_var.set(parts[0])
        self._on_root_change()
        if len(parts) > 1:
            sub = " / ".join(parts[1:])
            values = list(self.sub_filter_box["values"])
            if sub in values:
                self.sub_filter_var.set(sub)
        self._query()

    def _selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("题库", "请先在列表中选择一道题。", parent=self)
            return None
        return self.db.get_question(int(sel[0]))

    def _add(self):
        QuestionFormDialog(self, self.db)
        self._query()

    def _edit(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("题库", "请先选择一道题。", parent=self)
            return
        qid = int(sel[0])
        index = next((i for i, it in enumerate(self._items) if it["id"] == qid), 0)
        QuestionFormDialog(self, self.db, question=self.db.get_question(qid),
                           question_list=self._items, index=index)
        self._query()

    def _delete(self):
        q = self._selected()
        if not q:
            return
        if messagebox.askyesno("删除题目", "确定删除题目「{}」及其图片吗？".format(q["code"]), parent=self):
            self.db.delete_question(q["id"])
            self._query()

    def _reflect(self):
        q = self._selected()
        if not q:
            return
        ReflectionFormDialog(self, self.db, q)
        self._query()
