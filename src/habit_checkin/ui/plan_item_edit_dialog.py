# -*- coding: utf-8 -*-
"""备考进度页单项编辑弹窗：双击阶段/周/检查点/作息行后就地修改。"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from habit_checkin.ui.animate import fade_in
from habit_checkin.ui.common import center_window, setup_styles
from habit_checkin.ui.theme import PALETTE, dialog_header


def ask_plan_item(master, title, fields):
    """弹出单项编辑框，返回 {key: value}；用户取消时返回 None。"""
    dlg = PlanItemEditDialog(master, title, fields)
    dlg.wait_window()
    return dlg.result


class PlanItemEditDialog(tk.Toplevel):
    """按字段列表生成的小型编辑窗口，保存后返回字段值。"""

    def __init__(self, master, title, fields):
        super().__init__(master)
        self.fields = fields
        self.result = None
        self._entries = []
        self._texts = []
        self.title(title)
        self.transient(master)
        setup_styles(self)
        self.configure(bg=PALETTE["bg"])
        dialog_header(self, title, "修改后将同步到已导入的计划文档")
        self._build(fields)
        center_window(self)
        fade_in(self)
        self.grab_set()

    def _build(self, fields):
        P = PALETTE
        body = tk.Frame(self, bg=P["bg"], padx=16, pady=10)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        for i, field in enumerate(fields):
            tk.Label(body, text=field["label"], bg=P["bg"], fg=P["muted"],
                     font=("Microsoft YaHei UI", 12)).grid(
                row=i * 2, column=0, sticky="w", pady=(8, 0))
            if field.get("multiline"):
                text = tk.Text(
                    body, height=field.get("height", 3), wrap="word",
                    font=("Microsoft YaHei UI", 12), bg=P["input"], fg=P["text"],
                    relief="flat", highlightthickness=1,
                    highlightbackground=P["border"], highlightcolor=P["focus"],
                )
                text.insert("1.0", field.get("value", ""))
                text.grid(row=i * 2 + 1, column=0, sticky="ew", pady=(2, 0))
                body.rowconfigure(i * 2 + 1, weight=1)
                self._texts.append(text)
                self._entries.append(None)
            else:
                var = tk.StringVar(value=field.get("value", ""))
                entry = ttk.Entry(body, textvariable=var)
                entry.grid(row=i * 2 + 1, column=0, sticky="ew", pady=(2, 0))
                entry.bind("<Return>", lambda e: self._save())
                self._entries.append(entry)
                self._texts.append(None)

        bottom = tk.Frame(self, bg=P["bg"], padx=16, pady=10)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="取消", command=self.destroy).pack(side="right")
        ttk.Button(bottom, text="保存", style="Accent.TButton",
                   command=self._save).pack(side="right", padx=8)
        self.bind("<Escape>", lambda e: self.destroy())

    def _save(self):
        values = []
        for i, field in enumerate(self.fields):
            if self._texts[i] is not None:
                value = self._texts[i].get("1.0", "end").strip()
            else:
                value = self._entries[i].get().strip()
            values.append(value)
        self.result = dict(zip([f["key"] for f in self.fields], values))
        self.destroy()
