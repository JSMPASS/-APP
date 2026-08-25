"""材料表单对话框：资料分析/申论材料的新增、编辑、图片挂接。"""
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

from habit_checkin.services.clipboard_utils import (
    bind_entry_undo,
    bind_text_paste,
    cleanup_temp_files,
    paste_clipboard_images,
)
from habit_checkin.ui.common import (
    ScrollableFrame,
    center_window,
    make_thumbnail,
    setup_styles,
    show_image_zoom,
)
from habit_checkin.ui.field_edit_dialog import FieldTextArea
from habit_checkin.ui.theme import PALETTE, dialog_header

_FILETYPES = [
    ("图片", "*.png *.jpg *.jpeg *.webp *.bmp *.gif *.tif *.tiff"),
    ("所有文件", "*.*"),
]
KIND_LABELS = [("passage", "材料段落"), ("table", "表格"), ("figure", "图表")]


class MaterialFormDialog(tk.Toplevel):
    def __init__(self, master, db, material=None, prefill_topic_id=None,
                 prefill_detail_type_id=None, source_item_id=None,
                 detail_paths=None, materials=None, prefill_images=None):
        super().__init__(master)
        self.db = db
        self.material = material
        self.prefill_topic_id = prefill_topic_id
        self.prefill_detail_type_id = prefill_detail_type_id
        self.source_item_id = source_item_id
        self.detail_paths = [(path, qid) for path, qid in (detail_paths or [])]
        self.materials = materials or []
        self.prefill_images = list(prefill_images or [])
        self.images = []
        self.saved_material = None
        self._clipboard_tmp = []
        self.title("编辑材料" if material else "新增材料")
        self.geometry("880x780")
        self.minsize(760, 700)
        self.transient(master)
        setup_styles(self)
        self.configure(bg=PALETTE["bg"])
        self._build_ui()
        self._load_initial()
        bind_text_paste(self.title_entry)
        bind_entry_undo(self.title_entry)
        center_window(self)
        self.bind("<Control-v>", self._on_paste_images)
        self.bind("<Destroy>", self._on_destroy_clipboard_cleanup, add="+")
        self.grab_set()
        self.focus_set()

    def _build_ui(self):
        P = PALETTE
        dialog_header(self, self.title(), "资料与题目关联 · 可挂多张图片")
        bottom = tk.Frame(self, bg=PALETTE["bg"], padx=14, pady=10)
        bottom.pack(side="bottom", fill="x")
        ttk.Button(bottom, text="取消", command=self.destroy).pack(side="right")
        ttk.Button(
            bottom, text="保存材料", style="Accent.TButton",
            command=self._save,
        ).pack(side="right", padx=8)

        body = tk.Frame(self, bg=P["bg"], padx=14, pady=10)
        body.pack(fill="both", expand=True)

        meta = tk.Frame(body, bg=P["card"], padx=12, pady=10,
                        highlightbackground=P["border"], highlightthickness=1)
        meta.pack(fill="x", pady=(0, 8))
        row1 = tk.Frame(meta, bg=P["card"])
        row1.pack(fill="x", pady=(0, 6))
        tk.Label(row1, text="材料标题：", bg=P["card"]).pack(side="left")
        self.title_var = tk.StringVar()
        self.title_entry = ttk.Entry(row1, textvariable=self.title_var, width=34)
        self.title_entry.pack(side="left", fill="x", expand=True)

        row2 = tk.Frame(meta, bg=P["card"])
        row2.pack(fill="x", pady=(0, 6))
        tk.Label(row2, text="材料类型：", bg=P["card"]).pack(side="left")
        self.kind_var = tk.StringVar(value="材料段落")
        self.kind_box = ttk.Combobox(
            row2, textvariable=self.kind_var, state="readonly", width=12,
            values=[label for _, label in KIND_LABELS],
        )
        self.kind_box.pack(side="left", padx=(2, 16))
        tk.Label(row2, text="细分分类：", bg=P["card"]).pack(side="left")
        self.detail_var = tk.StringVar(value="（未细分）")
        self.detail_box = ttk.Combobox(
            row2, textvariable=self.detail_var, state="readonly", width=30,
        )
        self.detail_box.pack(side="left", padx=(2, 0))

        content = tk.Frame(body, bg=P["card"], padx=12, pady=10,
                           highlightbackground=P["border"], highlightthickness=1)
        content.pack(fill="both", expand=True, pady=(0, 8))
        tk.Label(content, text="材料正文（资料/申论材料，可 OCR 后核对）：",
                 bg=P["card"], fg=P["text"], font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w")
        self.content_text = FieldTextArea(content, height=8)
        self.content_text.pack(fill="both", expand=True, pady=(4, 0))

        img_frame = tk.Frame(body, bg=P["card"], padx=12, pady=10,
                             highlightbackground=P["border"], highlightthickness=1)
        img_frame.pack(fill="both", expand=True)
        bar = tk.Frame(img_frame, bg=P["card"])
        bar.pack(fill="x")
        ttk.Button(bar, text="添加图片（可多选）", command=self._add_images).pack(side="left")
        ttk.Button(bar, text="移除选中", command=self._remove_selected).pack(side="left", padx=6)
        self.img_count = tk.Label(bar, text="共 0 张", bg=P["card"], fg=P["muted"],
                                  font=("Microsoft YaHei UI", 11))
        self.img_count.pack(side="right")
        self.img_scroll = ScrollableFrame(img_frame)
        self.img_scroll.pack(fill="both", expand=True, pady=(6, 0))

    def _load_initial(self):
        paths = self.detail_paths
        self.detail_id_map = dict(paths)
        values = ["（未细分）"] + [p for p, _ in paths]
        self.detail_box.configure(values=values)
        selected_detail = self.prefill_detail_type_id
        if self.material:
            if self.material.get("kind"):
                label = dict(KIND_LABELS).get(self.material["kind"])
                if label:
                    self.kind_var.set(label)
            self.title_var.set(self.material.get("title") or "")
            detail_id = self.material.get("detail_type_id")
            if detail_id:
                path = self.db.question_type_path(detail_id)
                if path in values:
                    self.detail_var.set(path)
                    selected_detail = detail_id
            self.content_text.insert("1.0", self.material.get("content") or "")
            for img in self.material.get("images", []):
                self.images.append({
                    "rel": img["file_path"], "abs": self.db.abs_path(img["file_path"]),
                    "tk": None, "label": None, "frame": None,
                })
        elif selected_detail:
            path = self.db.question_type_path(selected_detail)
            if path in values:
                self.detail_var.set(path)
        for src in self.prefill_images:
            if Path(src).is_file():
                self.images.append({"rel": None, "abs": str(src), "tk": None, "label": None, "frame": None})
        self._render_images()

    def _add_images(self):
        paths = filedialog.askopenfilenames(
            parent=self, filetypes=_FILETYPES, title="选择材料图片（可多选）"
        )
        picked = [p for p in paths if p.lower().endswith(
            (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"))]
        for p in picked:
            self.images.append({"rel": None, "abs": p, "tk": None, "label": None, "frame": None})
        self._render_images()

    def _on_paste_images(self, event=None):
        paths, tmp = paste_clipboard_images()
        if not paths:
            return
        self._clipboard_tmp.extend(tmp)
        for p in paths:
            self.images.append({"rel": None, "abs": p, "tk": None, "label": None, "frame": None})
        self._render_images()

    def _on_destroy_clipboard_cleanup(self, event):
        if event.widget is self:
            cleanup_temp_files(self._clipboard_tmp)
            self._clipboard_tmp = []

    def _render_images(self):
        for w in self.img_scroll.inner.winfo_children():
            w.destroy()
        self.selected_index = None
        if not self.images:
            tk.Label(
                self.img_scroll.inner, text="（还没有材料图片，可 Ctrl+V 粘贴）",
                bg=PALETTE["card"], fg=PALETTE["muted"],
                font=("Microsoft YaHei UI", 11),
            ).pack(anchor="w", pady=4)
            self.img_count.configure(text="共 0 张")
            return
        row = ttk.Frame(self.img_scroll.inner)
        row.pack(fill="x", pady=2)
        for idx, img in enumerate(self.images):
            if idx % 5 == 0 and idx > 0:
                row = ttk.Frame(self.img_scroll.inner)
                row.pack(fill="x", pady=2)
            try:
                tk_img = make_thumbnail(img["abs"], 100)
            except Exception:
                continue
            frame = tk.Frame(row, width=106, height=124, bg=PALETTE["card"])
            frame.pack_propagate(False)
            frame.pack(side="left", padx=4)
            label = tk.Label(frame, image=tk_img, cursor="hand2", bg=PALETTE["card"])
            label.pack(pady=(2, 0))
            tk.Label(frame, text=str(idx + 1), bg=PALETTE["card"],
                     fg=PALETTE["muted"], font=("Microsoft YaHei UI", 11)).pack()
            label.bind("<Button-1>", lambda e, i=idx: self._toggle_select(i))
            frame.bind("<Button-1>", lambda e, i=idx: self._toggle_select(i))
            label.bind("<Double-1>", lambda e, i=idx: show_image_zoom(self, self.images[i]["abs"]))
            frame.bind("<Double-1>", lambda e, i=idx: show_image_zoom(self, self.images[i]["abs"]))
            img.update(tk=tk_img, label=label, frame=frame)
        self.img_count.configure(text="共 {} 张".format(len(self.images)))

    def _toggle_select(self, idx):
        for im in self.images:
            if im["frame"]:
                im["frame"].configure(highlightthickness=0)
        if self.selected_index == idx:
            self.selected_index = None
            return
        self.selected_index = idx
        self.images[idx]["frame"].configure(
            highlightthickness=2, highlightbackground=PALETTE["primary"])

    def _remove_selected(self):
        if self.selected_index is None:
            messagebox.showinfo("移除图片", "请先点击选中要移除的图片。", parent=self)
            return
        del self.images[self.selected_index]
        self.selected_index = None
        self._render_images()

    def _save(self):
        title = self.title_var.get().strip()
        if not title:
            title = "未命名材料"
        kind = dict((label, key) for key, label in KIND_LABELS).get(self.kind_var.get(), "passage")
        content = self.content_text.get_html().strip()
        detail_id = self.detail_id_map.get(self.detail_var.get())
        kept = [im["rel"] for im in self.images if im["rel"]]
        new_sources = [im["abs"] for im in self.images if im["rel"] is None]
        with self.db.transaction():
            if self.material is None:
                mid = self.db.add_question_material(
                    source_item_id=self.source_item_id,
                    topic_id=self.prefill_topic_id,
                    detail_type_id=detail_id,
                    kind=kind, title=title, content=content,
                )
            else:
                mid = self.material["id"]
                self.db.update_question_material(
                    mid, topic_id=self.prefill_topic_id,
                    detail_type_id=detail_id, kind=kind, title=title, content=content,
                )
            self.db.sync_question_material_images(mid, kept, new_sources)
        self.saved_material = self.db.get_question_material(mid)
        self.destroy()
