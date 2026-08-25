"""知识图片入库确认弹窗：OCR 拆分结果逐图预览、编辑后写入知识库。"""
from __future__ import annotations

import tkinter as tk
from datetime import date
from tkinter import messagebox, ttk

from habit_checkin.services.clipboard_utils import bind_entry_undo, bind_text_paste
from habit_checkin.ui.animate import fade_in
from habit_checkin.ui.common import center_window, make_thumbnail, setup_styles, show_image_zoom
from habit_checkin.ui.richtext import RichTextEditor, RichTextViewer
from habit_checkin.ui.theme import PALETTE, dialog_header


class KnowledgeImportDialog(tk.Toplevel):
    """逐图预览 OCR 拆分结果，确认后按图创建知识文档。"""

    def __init__(self, master, db, items, default_topic_id=None, source_item_id=None):
        """items: [{"image_rels": [rel...], "blocks": [{"title","content"}, ...]}]"""
        super().__init__(master)
        self.db = db
        self.items = items
        self.default_topic_id = default_topic_id
        self.source_item_id = source_item_id
        self.result = None
        self._thumb_refs = []
        self._pages = [{"blocks": [dict(b) for b in item.get("blocks", [])]}
                       for item in items]
        self.title("知识图片整理")
        self.geometry("980x680")
        self.minsize(820, 580)
        self.transient(master)
        setup_styles(self)
        self.configure(bg=PALETTE["bg"])
        dialog_header(self, "知识图片整理", "确认标题与分段后保存到知识库", title_size=14, subtitle_size=9)
        self._build()
        center_window(self)
        fade_in(self)
        self.grab_set()

    def _build(self):
        P = PALETTE
        body = tk.Frame(self, bg=P["bg"], padx=14, pady=10)
        body.pack(fill="both", expand=True)

        top = tk.Frame(body, bg=P["bg"])
        top.pack(fill="x", pady=(0, 8))
        tk.Label(top, text="知识文档标题", bg=P["bg"], fg=P["text"],
                 font=("Microsoft YaHei UI", 12)).pack(side="left")
        self.title_entry = ttk.Entry(top, font=("Microsoft YaHei UI", 12))
        bind_text_paste(self.title_entry)
        self.title_entry.pack(side="left", fill="x", expand=True, padx=(8, 12))
        default_title = "基本知识 · {}".format(date.today().isoformat())
        self.title_entry.insert(0, default_title)
        bind_entry_undo(self.title_entry)

        tk.Label(top, text="所属分类", bg=P["bg"], fg=P["text"],
                 font=("Microsoft YaHei UI", 12)).pack(side="left")
        self._topic_choices, self._topic_map = self._build_topic_choices()
        current = self._default_topic_label()
        self.topic_var = tk.StringVar(value=current)
        self.topic_box = ttk.Combobox(
            top, textvariable=self.topic_var, state="readonly", width=22,
            values=[c for c, _ in self._topic_choices],
        )
        self.topic_box.pack(side="left", padx=(6, 0))
        ttk.Button(top, text="管理科目", command=self._open_topic_manager).pack(side="left", padx=(6, 0))

        self.auto_link_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            top, text="保存后自动关联思维导图",
            variable=self.auto_link_var,
        ).pack(side="left", padx=(14, 0))

        self.notebook = ttk.Notebook(body)
        self.notebook.pack(fill="both", expand=True, pady=(0, 8))
        for idx in range(len(self.items)):
            self.notebook.add(self._build_page(idx), text="图片 {}".format(idx + 1))

        bottom = tk.Frame(self, bg=P["bg"], padx=14, pady=10)
        bottom.pack(fill="x")
        self.hint = tk.Label(
            bottom,
            text="选中知识段后可编辑标题、加粗、标红、调整字号；识别结果仅供参考。",
            bg=P["bg"], fg=P["faint"], font=("Microsoft YaHei UI", 11),
        )
        self.hint.pack(side="left")
        ttk.Button(bottom, text="取消", command=self.destroy).pack(side="right")
        ttk.Button(bottom, text="保存到知识库", style="Success.TButton",
                   command=self._save).pack(side="right", padx=8)
        self.bind("<Escape>", lambda e: self.destroy())

    def _build_topic_choices(self):
        choices = [("未分类", None)] + sorted(self.db.category_paths())
        return choices, {c: tid for c, tid in choices}

    def _default_topic_label(self):
        if not self.default_topic_id:
            return "未分类"
        path = self.db.topic_path(self.default_topic_id)
        return path if path in self._topic_map else "未分类"

    def _open_topic_manager(self):
        from habit_checkin.ui.topic_manager_dialog import TopicManagerDialog
        current = self.topic_var.get()
        dlg = TopicManagerDialog(self, self.db)
        self.wait_window(dlg)
        self._topic_choices, self._topic_map = self._build_topic_choices()
        self.topic_box.configure(values=[c for c, _ in self._topic_choices])
        if current not in self._topic_map:
            self.topic_var.set("未分类")

    def _build_page(self, idx):
        P = PALETTE
        page = ttk.Frame(self.notebook, padding=8)
        item = self.items[idx]

        img_row = tk.Frame(page, bg=P["surface"], height=112)
        img_row.pack(fill="x", pady=(0, 8))
        img_row.pack_propagate(False)
        rels = item.get("image_rels", [])
        for i, rel in enumerate(rels[:6]):
            try:
                tk_img = make_thumbnail(self.db.abs_path(rel), 88)
            except Exception:
                continue
            self._thumb_refs.append(tk_img)
            lbl = tk.Label(img_row, image=tk_img, bg=P["surface"], cursor="hand2")
            lbl.pack(side="left", padx=4, pady=4)
            lbl.bind("<Double-1>", lambda e, p=rel: show_image_zoom(self, self.db.abs_path(p)))
        if not rels:
            tk.Label(img_row, text="（无图片）", bg=P["surface"], fg=P["faint"],
                     font=("Microsoft YaHei UI", 11)).pack(side="left", padx=8)

        mid = tk.Frame(page, bg=P["surface"])
        mid.pack(fill="both", expand=True)
        left = tk.Frame(mid, bg=P["surface"])
        left.pack(side="left", fill="y")
        tk.Label(left, text="识别出的知识段", bg=P["surface"], fg=P["text"],
                 font=("Microsoft YaHei UI", 12, "bold")).pack(fill="x", anchor="center")
        self._pages[idx]["listbox"] = tk.Listbox(
            left, width=30, font=("Microsoft YaHei UI", 11),
            bg=P["input"], fg=P["text"], relief="flat", highlightthickness=1,
            highlightbackground=P["border"], activestyle="none",
        )
        self._pages[idx]["listbox"].pack(fill="both", expand=True, pady=(4, 0))
        self._pages[idx]["listbox"].bind("<<ListboxSelect>>", lambda e, i=idx: self._show_block(i))
        self._pages[idx]["listbox"].bind("<Double-1>", lambda e, i=idx: self._edit_block(i))

        btn_col = tk.Frame(left, bg=P["surface"])
        btn_col.pack(fill="x", pady=(6, 0))
        ttk.Button(btn_col, text="编辑选中段", command=lambda i=idx: self._edit_block(i)
                   ).pack(side="left")
        ttk.Button(btn_col, text="删除选中段", command=lambda i=idx: self._delete_block(i)
                   ).pack(side="left", padx=6)

        right = tk.Frame(mid, bg=P["surface"])
        right.pack(side="left", fill="both", expand=True, padx=(10, 0))
        tk.Label(right, text="内容预览", bg=P["surface"], fg=P["text"],
                 font=("Microsoft YaHei UI", 12, "bold")).pack(fill="x", anchor="center")
        self._pages[idx]["viewer"] = RichTextViewer(
            right, bg=P["surface"], image_resolver=self.db.abs_path)
        self._pages[idx]["viewer"].pack(fill="both", expand=True, pady=(4, 0))

        self._refresh_block_list(idx)
        return page

    def _refresh_block_list(self, idx):
        box = self._pages[idx]["listbox"]
        box.delete(0, "end")
        for blk in self._pages[idx]["blocks"]:
            n = len(blk.get("content") or "")
            box.insert("end", "{} · {} 字".format(blk.get("title") or "未命名", n))

    def _show_block(self, idx, block_idx=None):
        if block_idx is None:
            sel = self._pages[idx]["listbox"].curselection()
            if not sel:
                return
            block_idx = sel[0]
        blocks = self._pages[idx]["blocks"]
        if 0 <= block_idx < len(blocks):
            self._pages[idx]["viewer"].set_html(blocks[block_idx].get("content", ""))

    def _selected_block(self, idx):
        sel = self._pages[idx]["listbox"].curselection()
        if not sel:
            messagebox.showinfo("提示", "请先选中一个知识段。", parent=self)
            return None
        return sel[0]

    def _edit_block(self, idx):
        pos = self._selected_block(idx)
        if pos is None:
            return
        blk = self._pages[idx]["blocks"][pos]
        dlg = RichTextEditor(
            self, title="编辑知识段",
            initial_title=blk.get("title", ""),
            initial_html=blk.get("content", ""),
            subtitle="可加粗、标红、调整字号与段落格式，正文支持插入图片",
            image_resolver=self.db.abs_path,
            image_store=self.db.store_image,
        )
        self.wait_window(dlg)
        if dlg.result:
            self._pages[idx]["blocks"][pos] = dlg.result
            self._refresh_block_list(idx)
            self._show_block(idx, pos)

    def _delete_block(self, idx):
        pos = self._selected_block(idx)
        if pos is None:
            return
        del self._pages[idx]["blocks"][pos]
        self._refresh_block_list(idx)
        self._pages[idx]["viewer"].set_html("")

    def _topic_id(self):
        label = self.topic_var.get()
        return self._topic_map.get(label)

    def _save(self, event=None):
        title = self.title_entry.get().strip()
        if not title:
            messagebox.showerror("标题不能为空", "请填写知识文档标题。", parent=self)
            return
        doc_ids = []
        topic_id = self._topic_id()
        try:
            for idx, item in enumerate(self.items):
                rels = item.get("image_rels", [])
                first_block = next((b for b in self._pages[idx]["blocks"]
                                    if (b.get("title") or "").strip()), None)
                doc_title = title if len(self.items) == 1 else "{} · {}".format(
                    title, idx + 1)
                if first_block and len(self.items) > 1:
                    doc_title = "{} · {}".format(doc_title, first_block["title"][:20])
                doc_id = self.db.add_knowledge_doc(
                    title=doc_title,
                    topic_id=topic_id,
                    source="checkin",
                    source_item_id=self.source_item_id,
                    source_image=rels[0] if rels else "",
                )
                self.db.sync_knowledge_images(
                    doc_id, [self.db.abs_path(rel) for rel in rels])
                for order, blk in enumerate(self._pages[idx]["blocks"]):
                    self.db.add_knowledge_block(
                        doc_id,
                        (blk.get("title") or "未命名知识点").strip(),
                        blk.get("content", ""),
                        sort_order=order,
                    )
                if self.auto_link_var.get():
                    self.db.auto_link_knowledge(doc_id)
                doc_ids.append(doc_id)
        except Exception as exc:
            messagebox.showerror("保存失败", "知识库保存出错：{}\n请重试。".format(exc), parent=self)
            return
        self.result = {"doc_ids": doc_ids}
        self.destroy()
