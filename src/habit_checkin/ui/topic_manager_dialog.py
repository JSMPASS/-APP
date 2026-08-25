"""科目管理弹窗：在只读科目/分类下拉框旁提供统一的增删改查入口。"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from habit_checkin.ui.common import center_window, setup_styles
from habit_checkin.ui.theme import PALETTE, dialog_header
from habit_checkin.ui.topic_tree import TopicTreeMixin


class TopicManagerDialog(TopicTreeMixin, tk.Toplevel):
    """复用科目树能力的模态弹窗，关闭后通过 on_close 通知调用方刷新。"""

    def __init__(self, master, db, on_close=None):
        super().__init__(master)
        self.db = db
        self._on_close = on_close
        self.title("科目管理")
        self.geometry("620x560")
        self.minsize(520, 440)
        self.transient(master)
        setup_styles(self)
        self.configure(bg=PALETTE["bg"])
        dialog_header(self, "科目管理", "右键增删改 · 长按拖动调整顺序/层级")
        self._build()
        center_window(self)
        self.grab_set()

    def _build(self):
        P = PALETTE
        body = tk.Frame(self, bg=P["bg"], padx=14, pady=10)
        body.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(
            body, columns=("type", "state"), show="tree headings", selectmode="browse",
        )
        self.tree.heading("#0", text="科目 / 知识点")
        self.tree.heading("type", text="类型")
        self.tree.heading("state", text="状态")
        self.tree.column("#0", width=280, anchor="w")
        self.tree.column("type", width=120, anchor="center", stretch=False)
        self.tree.column("state", width=70, anchor="center", stretch=False)
        vsb = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.tag_configure("drag_target", background=PALETTE["primary_light"])
        self.tree.bind("<ButtonPress-1>", self._on_drag_press)
        self.tree.bind("<B1-Motion>", self._on_drag_motion)
        self.tree.bind("<ButtonRelease-1>", self._on_drag_release)
        self.tree.bind("<Button-3>", self._on_right_click)
        self._drag_item = None
        self._drag_active = False
        self._drag_press_time = 0.0
        self._drag_target = None

        side = tk.Frame(self, bg=P["bg"], padx=14, pady=10)
        side.pack(fill="x")
        ttk.Label(
            side,
            text="右键科目/知识点可增删改、切换类型；\n"
                 "右键空白处可新增科目；长按拖动调整顺序/层级。\n"
                 "具体分类会进入思维导图和细分查询；\n"
                 "具体做法仅用于生成计划，不入导图。",
            style="Hint.TLabel",
            justify="left",
        ).pack(side="left")
        ttk.Button(side, text="＋ 新增科目", command=self._add_root).pack(side="right")

        bottom = tk.Frame(self, bg=P["bg"], padx=14, pady=10)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="关闭", style="Accent.TButton", command=self.destroy).pack(side="right")
        self.bind("<Escape>", lambda e: self.destroy())
        self._refresh_tree()

    def _refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        topics = self.db.list_topics(include_disabled=True)
        children = {}
        for t in topics:
            children.setdefault(t["parent_id"], []).append(t)

        def add(parent_iid, t):
            iid = "t{}".format(t["id"])
            state = "停用" if t["disabled"] else "启用"
            kind = "具体做法" if t["kind"] == "method" else "具体分类"
            self.tree.insert(parent_iid, "end", iid=iid, text=t["name"], values=(kind, state), open=True)
            for kid in children.get(t["id"], []):
                add(iid, kid)

        for r in children.get(None, []):
            add("", r)

    def destroy(self):
        cb = self._on_close
        self._on_close = None
        if cb:
            try:
                cb()
            except Exception:
                pass
        super().destroy()
