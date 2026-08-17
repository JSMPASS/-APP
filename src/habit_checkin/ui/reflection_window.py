# -*- coding: utf-8 -*-
"""练习后复盘：列出所选日期范围内做过的全部题目（对 + 错），逐题从三个维度复盘。"""
from __future__ import annotations

import tkinter as tk
from datetime import date
from tkinter import messagebox, ttk

from habit_checkin.db import validate_date
from habit_checkin.services.export_common import result_text
from habit_checkin.ui.calendar import attach_calendar_on_click
from habit_checkin.ui.common import center_window, setup_styles
from habit_checkin.ui.theme import PALETTE, dialog_header
from habit_checkin.ui.animate import fade_in
from habit_checkin.ui.topic_colors import configure_topic_tags, topic_tag

_COLUMNS = ("code", "topic", "result", "reflected")

def reflected_of(q):
    return bool((q.get("self_analysis") or "").strip()
                or (q.get("correct_analysis") or "").strip()
                or (q.get("reflection") or "").strip())


class ReflectionWindow(tk.Frame):
    """练习后复盘页：按日期范围列出做过的全部题目，逐题填写复盘。"""

    def __init__(self, master, db):
        super().__init__(master, bg=PALETTE["bg"])
        self.db = db
        self._sub_options = []
        setup_styles(self)
        self.configure(bg=PALETTE["bg"])
        self._build_ui()
        self._query()

    def refresh(self):
        self._query()

    def _build_ui(self):
        P = PALETTE
        dialog_header(self, "练习后复盘", "我的思路 · 正确思路 · 复盘心得")
        top = tk.Frame(self, bg=P["bg"], padx=14, pady=12)
        top.pack(fill="x")
        tk.Label(top, text="开始日期：", bg=P["bg"]).pack(side="left")
        self.start_entry = ttk.Entry(top, width=11)
        self.start_entry.insert(0, date.today().isoformat())
        self.start_entry.pack(side="left", padx=(0, 8))
        attach_calendar_on_click(self.start_entry, lambda ds: self._set_entry(self.start_entry, ds))
        tk.Label(top, text="结束日期：", bg=P["bg"]).pack(side="left")
        self.end_entry = ttk.Entry(top, width=11)
        self.end_entry.insert(0, date.today().isoformat())
        self.end_entry.pack(side="left", padx=(0, 8))
        attach_calendar_on_click(self.end_entry, lambda ds: self._set_entry(self.end_entry, ds))
        tk.Label(top, text="科目：", bg=P["bg"]).pack(side="left")
        roots = self.db.root_topics()
        self.filter_var = tk.StringVar(value="全部")
        self.filter_box = ttk.Combobox(
            top, textvariable=self.filter_var, state="readonly", width=12,
            values=["全部"] + [r["name"] for r in roots],
        )
        self.filter_box.pack(side="left", padx=(0, 8))
        tk.Label(top, text="细分：", bg=P["bg"]).pack(side="left")
        self.sub_filter_var = tk.StringVar(value="全部细分")
        self.sub_filter_box = ttk.Combobox(
            top, textvariable=self.sub_filter_var, state="readonly", width=18,
            values=["全部细分"],
        )
        self.sub_filter_box.pack(side="left", padx=(0, 8))
        self.filter_box.bind("<<ComboboxSelected>>", self._on_root_change)
        ttk.Button(top, text="查询", command=self._query).pack(side="left")
        ttk.Button(top, text="开始复盘", style="Accent.TButton",
                   command=self._reflect).pack(side="right")

        self.summary = tk.Label(self, text="", anchor="w", padx=16, pady=6,
                                bg=P["primary_light"], fg=P["primary_dark"],
                                font=("Microsoft YaHei UI", 13, "bold"))
        self.summary.pack(fill="x")

        list_frame = tk.Frame(self, bg=P["bg"], padx=14, pady=10)
        list_frame.pack(fill="both", expand=True)
        box = tk.Frame(list_frame, bg=P["card"], highlightbackground=P["border"], highlightthickness=1)
        box.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(box, columns=_COLUMNS, show="headings", selectmode="browse")
        for col, txt, width, anchor in (
            ("code", "编号", 90, "center"),
            ("topic", "分类", 330, "w"),
            ("result", "对错（原因）", 200, "center"),
            ("reflected", "复盘状态", 100, "center"),
        ):
            self.tree.heading(col, text=txt)
            self.tree.column(col, width=width, anchor=anchor)
        self.tree.tag_configure("done", foreground=PALETTE["done"])
        self.tree.tag_configure("todo", foreground=PALETTE["text"])
        vsb = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda e: self._reflect())

    @staticmethod
    def _set_entry(entry, ds):
        entry.delete(0, "end")
        entry.insert(0, ds)

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
        topics = self.db.list_topics()
        children = {}
        for t in topics:
            children.setdefault(t["parent_id"], []).append(t)

        def walk(parent_id, prefix):
            for t in children.get(parent_id, []):
                rel = (prefix + " / " + t["name"]).strip(" / ")
                self._sub_options.append((rel, t["id"]))
                walk(t["id"], rel)

        walk(root_id, "")
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

    def _query(self):
        try:
            start = validate_date(self.start_entry.get())
            end = validate_date(self.end_entry.get())
        except ValueError as exc:
            messagebox.showwarning("日期错误", str(exc), parent=self)
            return
        root_filter = self.filter_var.get()
        # root_topic_id = None
        # if root_filter != "全部":
            # for r in self.db.root_topics():
                # if r["name"] == root_filter:
                    # root_topic_id = r["id"]
                    # break
        topic_id = self._selected_topic_id()
        items = self.db.list_questions(topic_id=topic_id, start_date=start, end_date=end)
        # if root_topic_id is not None:
            # ids = set(self.db.subtree_ids(root_topic_id))
            # items = [it for it in items if it["topic_id"] in ids]
        self._items = items
        self.tree.delete(*self.tree.get_children())
        configure_topic_tags(self.tree, items)
        done_cnt = 0
        for it in items:
            reflected = reflected_of(it)
            if reflected:
                tag, st = "done", "已复盘"
                done_cnt += 1
            else:
                tag, st = "todo", "未复盘"
            bg_tag = topic_tag(it.get("topic_id"))
            row_tags = (bg_tag, tag) if bg_tag else (tag,)
            self.tree.insert("", "end", iid=str(it["id"]), tags=row_tags,
                             values=(it["code"], it["topic_path"], result_text(it), st))
        correct = sum(1 for it in items if it["result"] == "correct")
        wrong = sum(1 for it in items if it["result"] == "wrong")
        und = len(items) - correct - wrong
        self.summary.configure(
            text="{} 至 {}：共 {} 题（正确 {} · 错误 {} · 未判定 {}），已复盘 {} 题。"
                 "双击或点「开始复盘」逐题复盘。".format(start, end, len(items), correct, wrong, und, done_cnt))

    def _reflect(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("练习复盘", "请先选择一道题目。", parent=self)
            return
        q = self.db.get_question(int(sel[0]))
        if not q:
            return
        ReflectionFormDialog(self, self.db, q)
        self._query()


class ReflectionFormDialog(tk.Toplevel):
    """练习复盘表单：我的做题思路 / 正确（最优）做题思路 / 复盘心得。"""

    def __init__(self, master, db, question):
        super().__init__(master, bg=PALETTE["bg"])
        self.db = db
        self.question = question
        self.title("练习复盘：{}".format(question["code"]))
        self.geometry("680x640")
        self.transient(master)
        setup_styles(self)
        self.configure(bg=PALETTE["bg"])
        P = PALETTE
        dialog_header(self, "练习复盘：{}".format(question["code"]), "对做过的题逐题复盘")
        center_window(self)
        fade_in(self)
        self.grab_set()
        body = tk.Frame(self, bg=P["bg"], padx=14, pady=10)
        body.pack(fill="both", expand=True)
        head = tk.Frame(body, bg=P["card"], padx=12, pady=10,
                        highlightbackground=P["border"], highlightthickness=1)
        head.pack(fill="x", pady=(0, 8))
        tk.Label(head, text="{} · {}".format(question["code"], question["topic_path"]),
                 bg=P["card"], fg=P["text"], font=("Microsoft YaHei UI", 15, "bold")).pack(anchor="w")
        res_color = P["done"] if question["result"] == "correct" else (
            P["danger"] if question["result"] == "wrong" else P["muted"])
        tk.Label(head, text="对错：{}".format(result_text(question)),
                 bg=P["card"], fg=res_color, font=("Microsoft YaHei UI", 13, "bold")
                 ).pack(anchor="w", pady=(2, 0))
        if question["question_text"]:
            tk.Label(head, text="题目：" + question["question_text"][:160],
                     bg=P["card"], fg=P["muted"], font=("Microsoft YaHei UI", 11),
                     wraplength=620, justify="left").pack(anchor="w", pady=(2, 0))

        self.fields = {}
        for key, label, height in (
            ("self_analysis", "我的做题思路（当时是怎么想的、关键判断是什么）", 6),
            ("correct_analysis", "正确（最优）做题思路（关键步骤、如何快速切入）", 6),
            ("reflection", "复盘心得（收获、易错点、下次如何避免或提速）", 4),
        ):
            frame = tk.Frame(body, bg=P["card"], padx=12, pady=8,
                             highlightbackground=P["border"], highlightthickness=1)
            frame.pack(fill="both", expand=True, pady=(0, 8))
            tk.Label(frame, text=label, bg=P["card"], fg=P["text"],
                     font=("Microsoft YaHei UI", 13, "bold")).pack(anchor="w")
            txt = tk.Text(frame, height=height, wrap="word", font=("Microsoft YaHei UI", 13),
                          bg=P["input"], fg=P["text"], relief="flat", highlightthickness=1,
                          highlightbackground=P["border"], highlightcolor=P["primary"])
            txt.insert("1.0", question.get(key) or "")
            txt.pack(fill="both", expand=True, pady=(4, 0))
            self.fields[key] = txt

        bottom = tk.Frame(self, bg=P["bg"], padx=14, pady=10)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="取消", command=self.destroy).pack(side="right")
        ttk.Button(bottom, text="保存复盘", style="Accent.TButton",
                   command=self._save).pack(side="right", padx=8)

    def _save(self):
        data = {k: v.get("1.0", "end").strip() for k, v in self.fields.items()}
        if not any(data.values()):
            messagebox.showwarning("保存复盘", "请至少填写一个维度的内容。", parent=self)
            return
        self.db.update_question(self.question["id"], **data)
        self.destroy()
