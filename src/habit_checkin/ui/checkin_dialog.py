"""打卡对话框：填写文字总结 + 添加/移除图片，提交后标记完成。"""
from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from habit_checkin.services.collect import collect_question_from_image
from habit_checkin.services.motivation import random_quote
from habit_checkin.services.ocr import ocr_image_lines
from habit_checkin.services.split import split_question_lines
from habit_checkin.ui.common import ScrollableFrame, center_window, make_thumbnail, setup_styles, show_image_zoom
from habit_checkin.ui.animate import fade_in, slide_in
from habit_checkin.ui.field_edit_dialog import FieldTextArea
from habit_checkin.ui.theme import PALETTE, dialog_header
from habit_checkin.ui.question_form_dialog import QuestionFormDialog
from habit_checkin.ui.reflection_window import ReflectionFormDialog

_FILETYPES = [
    ("图片", "*.png *.jpg *.jpeg *.webp *.bmp *.gif *.tif *.tiff"),
    ("所有文件", "*.*"),
]


class CheckinDialog(tk.Toplevel):
    def __init__(self, master, db, item, date_str):
        super().__init__(master)
        self.db = db
        self.item = item
        self.item_id = item["id"]
        self.date_str = date_str
        self.images = []  # {rel, abs, tk, label, frame}
        self.selected_index = None
        self.title("打卡：{}".format(item["topic_path"]))
        self.geometry("960x640")
        self.minsize(880, 600)
        self.transient(master)
        setup_styles(self)
        self.configure(bg=PALETTE["bg"])
        self._build_ui()
        self._load_images()
        center_window(self)
        self.bind("<Delete>", self._on_delete_key)
        self.grab_set()
        self.focus_set()
        fade_in(self)

    def _build_ui(self):
        dialog_header(self, self.item["topic_path"], "{}（{}）".format(self.date_str, self._status_text()))

        # 底部操作栏优先打包（side=bottom），保证始终可见
        sep = tk.Frame(self, bg=PALETTE["border"], height=1)
        sep.pack(side="bottom", fill="x")
        bottom = tk.Frame(self, bg=PALETTE["bar"], padx=12, pady=10)
        bottom.pack(side="bottom", fill="x")
        tk.Label(bottom, text="点击图片可选中；双击可放大查看", bg=PALETTE["bar"],
                 fg=PALETTE["muted"], font=("Microsoft YaHei UI", 11)).pack(side="left")
        ttk.Button(bottom, text="📚 收录图片到题库", command=self._collect_to_bank).pack(side="left", padx=12)
        self.auto_collect_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            bottom, text="自动识别图片并收录到题库", variable=self.auto_collect_var
        ).pack(side="left", padx=(12, 0))
        ttk.Button(bottom, text="取消", command=self.destroy).pack(side="right")
        self.btn_submit = ttk.Button(
            bottom,
            text="确认修改" if self.item["done"] else "确认打卡",
            style="Success.TButton",
            command=self._submit,
        )
        self.btn_submit.pack(side="right", padx=8)

        note_frame = ttk.LabelFrame(self, text="文字总结（学习内容、心得、完成情况等）", padding=8)
        note_frame.pack(fill="both", expand=True, padx=12, pady=(4, 8))
        self.note_text = FieldTextArea(note_frame, height=8)
        self.note_text.pack(fill="both", expand=True)
        if self.item.get("note"):
            self.note_text.insert("1.0", self.item["note"])

        img_frame = ttk.LabelFrame(self, text="图片（支持多张：png/jpg/webp/bmp 等）", padding=8)
        img_frame.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        bar = tk.Frame(img_frame, bg=PALETTE["card"])
        bar.pack(fill="x")
        ttk.Button(bar, text="添加图片", command=self._add_images).pack(side="left")
        ttk.Button(bar, text="移除选中", command=self._remove_selected).pack(side="left", padx=6)
        ttk.Button(bar, text="清空图片", command=self._clear_images).pack(side="left")
        self.img_count = tk.Label(bar, text="共 0 张", bg=PALETTE["card"], fg=PALETTE["muted"], font=("Microsoft YaHei UI", 11))
        self.img_count.pack(side="right")
        self.img_scroll = ScrollableFrame(img_frame)
        self.img_scroll.pack(fill="both", expand=True, pady=(6, 0))

    def _status_text(self):
        return "已完成（{}）".format((self.item.get("checked_at") or "")[11:16]) if self.item["done"] else "未完成"

    def _load_images(self):
        for img in self.item.get("images", []):
            abs_path = self.db.abs_path(img["file_path"])
            self.images.append({"rel": img["file_path"], "abs": abs_path, "tk": None, "label": None, "frame": None})
        self._render_images()

    # ---------- 图片列表 ----------
    def _render_images(self):
        for w in self.img_scroll.inner.winfo_children():
            w.destroy()
        self.selected_index = None
        if not self.images:
            tk.Label(self.img_scroll.inner, text="（还没有图片，点击「添加图片」）", bg=PALETTE["card"],
            fg=PALETTE["muted"], font=("Microsoft YaHei UI", 11)).pack(
                anchor="w", pady=4
            )
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
            frame = tk.Frame(row, width=106, height=112, bg=PALETTE["card"])
            frame.pack_propagate(False)
            frame.pack(side="left", padx=4)
            label = tk.Label(frame, image=tk_img, cursor="hand2", bg=PALETTE["card"])
            label.pack(pady=(2, 0))
            caption = tk.Label(frame, text=str(idx + 1), font=("Microsoft YaHei UI", 11),
                               bg=PALETTE["card"], fg=PALETTE["muted"])
            caption.pack()
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
        self.images[idx]["frame"].configure(highlightthickness=2, highlightbackground=PALETTE["primary"])

    def _add_images(self):
        paths = filedialog.askopenfilenames(
            parent=self, filetypes=_FILETYPES, title="选择打卡图片（可多选）"
        )
        for p in paths:
            if p.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff")):
                self.images.append({"rel": None, "abs": p, "tk": None, "label": None, "frame": None})
        self._render_images()

    def _remove_selected(self):
        if self.selected_index is None:
            messagebox.showinfo("移除图片", "请先点击选中要移除的图片。", parent=self)
            return
        del self.images[self.selected_index]
        self._render_images()

    def _clear_images(self):
        if not self.images:
            return
        if not messagebox.askyesno("清空图片", "确定移除全部图片吗？", parent=self):
            return
        self.images.clear()
        self._render_images()

    # ---------- 提交 ----------
    def _submit(self):
        note = self.note_text.get("1.0", "end").strip()
        if not note and not self.images:
            ok = messagebox.askyesno(
                "确认打卡", "还没有填写总结或添加图片，确定要提交空打卡吗？", parent=self
            )
            if not ok:
                return
        img_warn = None
        try:
            kept_rels = [im["rel"] for im in self.images if im["rel"]]
            new_sources = [im["abs"] for im in self.images if im["rel"] is None]
            try:
                self.db.sync_checkin_images(self.item_id, kept_rels, new_sources)
            except Exception as exc:
                img_warn = "图片保存失败：{}".format(exc)
            self.db.update_checkin(self.item_id, note, done=True)
        except Exception as exc:
            messagebox.showerror(
                "保存失败", "打卡保存出错：{}\n请重试。".format(exc), parent=self
            )
            return
        if img_warn:
            messagebox.showwarning(
                "图片保存提示",
                img_warn + "\n文字总结与完成状态已保存，可稍后重新打开该打卡项补传图片。",
                parent=self,
            )
        if self.auto_collect_var.get() and self.images:
            self._auto_collect()
        self._show_success()
        self.destroy()

    # ---------- 自动收录 ----------
    def _auto_collect(self):
        """打卡提交后：后台 OCR 识别该打卡项图片中的题目，自动加入题库（已收录的不重复加）。"""
        sources = [im["abs"] if im["rel"] is None else self.db.abs_path(im["rel"]) for im in self.images]
        if not sources:
            return
        master = self.master
        db = self.db
        item_id = self.item_id
        topic_id = self.item.get("topic_id")

        def work():
            results = []
            for p in sources:
                try:
                    results.append((p, ocr_image_lines(p)))
                except Exception:
                    results.append((p, None))
            master.after(0, lambda: self._finish_auto_collect(results, master, db, item_id, topic_id))

        threading.Thread(target=work, daemon=True).start()

    def _finish_auto_collect(self, results, master, db, item_id, topic_id):
        existing = db.collected_checkin_texts(item_id)
        added, no_text, skipped, failed = [], [], [], []
        for p, lines in results:
            if lines:
                chunks = split_question_lines(lines)
            else:
                chunks = [{"text": "", "analysis": ""}]
            for chunk in chunks:
                txt = (chunk["text"] or "").strip()
                try:
                    if txt in existing:
                        skipped.append(Path(p).name)
                        continue
                    code, _ = collect_question_from_image(
                        db, p, txt, topic_id=topic_id, source_item_id=item_id,
                        analysis=chunk.get("analysis", ""),
                    )
                    added.append(code)
                    if not txt:
                        no_text.append(code)
                except Exception:
                    failed.append(Path(p).name)
        if not added and not failed:
            if skipped:
                messagebox.showinfo(
                    "题库收录", "这些图片中的题目之前已收录过，未重复添加。", parent=master
                )
            return
        parts = []
        if added:
            parts.append("已自动收录 {} 题：{}".format(len(added), "、".join(added)))
        if no_text:
            parts.append("其中 {} 题未识别到文字，图片已入库，可在题库中补充题目内容。".format(len(no_text)))
        if failed:
            parts.append("{} 张图片收录失败，可稍后在题库中手动添加。".format(len(failed)))
        parts.append("识别结果来自离线 OCR，建议在题库中核对修改。")
        msg = "\n".join(parts)
        if messagebox.askyesno("题库收录完成", msg + "\n\n是否打开题库查看？", parent=master):
            from habit_checkin.ui.question_bank_window import QuestionBankWindow
            QuestionBankWindow(master, db)

    def _on_delete_key(self, event):
        if self.selected_index is not None:
            self._remove_selected()
            return "break"
        return None

    def _collect_to_bank(self):
        sources = [im["abs"] if im["rel"] is None else self.db.abs_path(im["rel"]) for im in self.images]
        if not sources:
            messagebox.showinfo("收录到题库", "请先添加图片，再收录其中的题目。", parent=self)
            return
        dialog = QuestionFormDialog(self, self.db, prefill_images=sources,
                                    prefill_topic_id=self.item["topic_id"],
                                    source="checkin", source_item_id=self.item_id)
        self.wait_window(dialog)
        q = dialog.saved_question
        if q and q["result"] == "wrong":
            if messagebox.askyesno("练习复盘", "已收录错题「{}」。是否立即填写复盘？".format(q["code"]), parent=self):
                ReflectionFormDialog(self, self.db, q)

    def _show_success(self):
        quote = random_quote()
        P = PALETTE
        top = tk.Toplevel(self.master)
        top.title("打卡成功")
        top.configure(bg=P["bg"])
        top.attributes("-topmost", True)
        top.resizable(False, False)
        box = tk.Frame(top, bg=P["card"], padx=26, pady=18,
                       highlightbackground=P["border"], highlightthickness=1)
        box.pack(padx=12, pady=12)
        tk.Label(box, text="✓ 打卡成功", bg=P["card"], fg=P["accent"],
                 font=("Microsoft YaHei UI", 20, "bold")).pack()
        tk.Label(box, text="「{}」".format(quote), bg=P["card"], fg=P["text"],
                 font=("Microsoft YaHei UI", 13), wraplength=340, justify="center").pack(pady=(10, 2))
        ttk.Button(box, text="继续加油", style="Success.TButton", command=top.destroy).pack(pady=(8, 0))
        top.update_idletasks()
        center_window(top)

        def close_later():
            try:
                if top.winfo_exists():
                    top.destroy()
            except tk.TclError:
                pass

        top.after(6000, close_later)
        slide_in(top)
