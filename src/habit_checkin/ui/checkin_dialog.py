"""打卡对话框：按题型模板区分基本知识/材料/题目图片，提交后确认入库。"""
from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from habit_checkin.services.clipboard_utils import cleanup_temp_files, paste_clipboard_images
from habit_checkin.services.knowledge_split import ocr_knowledge_document
from habit_checkin.services.motivation import random_quote
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

TEMPLATES = {
    "text": ("文字题模板", "基本知识 + 文字/选项题目"),
    "figure": ("图形推理模板", "基本知识 + 图形题目（题干/选项含图形）"),
    "data": ("资料分析模板", "资料/图表材料 + 题目 + 细分分类"),
    "shenlun": ("申论资料模板", "长段材料跨图 + 长文题目"),
}


class CheckinDialog(tk.Toplevel):
    def __init__(self, master, db, item, date_str):
        super().__init__(master)
        self.db = db
        self.item = item
        self.item_id = item["id"]
        self.date_str = date_str
        self.template_key = self._detect_template()
        self._material_group_seq = 0
        self.images = []  # {rel, abs, purpose, tk, label, frame}
        self.selected_index = None
        self._clipboard_tmp = []
        self.title("打卡：{}".format(item["topic_path"]))
        self.geometry("1000x700")
        self.minsize(920, 640)
        self.transient(master)
        setup_styles(self)
        self.configure(bg=PALETTE["bg"])
        self._build_ui()
        self._load_images()
        center_window(self)
        self.bind("<Delete>", self._on_delete_key)
        self.bind("<Control-v>", self._on_paste_images)
        self.bind("<Destroy>", self._on_destroy_clipboard_cleanup, add="+")
        self.grab_set()
        self.focus_set()
        fade_in(self)

    def _build_ui(self):
        dialog_header(self, self.item["topic_path"], "{}（{}）".format(self.date_str, self._status_text()))
        P = PALETTE
        template_bar = tk.Frame(self, bg=P["card"], padx=12, pady=6,
                                highlightbackground=P["border"], highlightthickness=1)
        template_bar.pack(fill="x", padx=12, pady=(0, 6))
        template_name, template_desc = TEMPLATES.get(
            self.template_key, TEMPLATES["text"]
        )
        tk.Label(template_bar, text="上传模板：", bg=P["card"], fg=P["muted"],
                 font=("Microsoft YaHei UI", 11)).pack(side="left")
        tk.Label(template_bar, text=template_name, bg=P["card"], fg=P["primary"],
                 font=("Microsoft YaHei UI", 12, "bold")).pack(side="left")
        tk.Label(template_bar, text=template_desc, bg=P["card"], fg=P["muted"],
                 font=("Microsoft YaHei UI", 11)).pack(side="left", padx=(10, 0))

        # 资料分析 / 申论：材料与作答区（富文本，自带工具栏）
        if self.template_key in ("data", "shenlun"):
            extra = tk.Frame(self, bg=PALETTE["bg"], padx=12)
            extra.pack(fill="x", pady=(0, 4))
            if self.template_key == "data":
                mat_frame = ttk.LabelFrame(extra, text="资料/材料（文字或图表说明）", padding=8)
                mat_frame.pack(fill="x")
                self.material_text = FieldTextArea(mat_frame, height=4)
                self.material_text.pack(fill="x")
                if self.item.get("material"):
                    self.material_text.insert("1.0", self.item["material"])
            else:
                mat_frame = ttk.LabelFrame(extra, text="申论材料（长段材料）", padding=8)
                mat_frame.pack(fill="x", pady=(0, 4))
                self.material_text = FieldTextArea(mat_frame, height=4)
                self.material_text.pack(fill="x")
                if self.item.get("material"):
                    self.material_text.insert("1.0", self.item["material"])
                ans_frame = ttk.LabelFrame(extra, text="手写作答/答案", padding=8)
                ans_frame.pack(fill="x")
                self.answer_text = FieldTextArea(ans_frame, height=3)
                self.answer_text.pack(fill="x")
                if self.item.get("answer"):
                    self.answer_text.insert("1.0", self.item["answer"])


        # 底部操作栏优先打包（side=bottom），保证始终可见
        sep = tk.Frame(self, bg=PALETTE["border"], height=1)
        sep.pack(side="bottom", fill="x")
        bottom = tk.Frame(self, bg=PALETTE["bar"], padx=12, pady=10)
        bottom.pack(side="bottom", fill="x")
        tk.Label(bottom, text="点击图片可选中；双击可放大查看", bg=PALETTE["bar"],
                 fg=PALETTE["muted"], font=("Microsoft YaHei UI", 11)).pack(side="left")
        ttk.Button(bottom, text="收录图片到题库", command=self._collect_to_bank).pack(side="left", padx=12)
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

        text_row = tk.Frame(self, bg=PALETTE["bg"], padx=12)
        text_row.pack(fill="both", expand=True, pady=(4, 6))
        text_row.columnconfigure(0, weight=1, uniform="text")
        text_row.columnconfigure(1, weight=1, uniform="text")

        knowledge_title, question_title = self._frame_titles()
        knowledge_frame = ttk.LabelFrame(
            text_row, text=knowledge_title, padding=8)
        knowledge_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.basic_knowledge_text = FieldTextArea(knowledge_frame, height=8)
        self.basic_knowledge_text.pack(fill="both", expand=True)
        if self.item.get("basic_knowledge"):
            self.basic_knowledge_text.insert("1.0", self.item["basic_knowledge"])

        question_frame = ttk.LabelFrame(
            text_row, text=question_title, padding=8)
        question_frame.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self.note_text = FieldTextArea(question_frame, height=8)
        self.note_text.pack(fill="both", expand=True)
        if self.item.get("note"):
            self.note_text.insert("1.0", self.item["note"])

        img_frame = ttk.LabelFrame(
            self, text="图片（按模板区分「知识 / 材料 / 题目」用途）", padding=8)
        img_frame.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        bar = tk.Frame(img_frame, bg=PALETTE["card"])
        bar.pack(fill="x")
        ttk.Button(bar, text="添加图片", command=self._add_images).pack(side="left")
        ttk.Button(bar, text="移除选中", command=self._remove_selected).pack(side="left", padx=6)
        ttk.Button(bar, text="清空图片", command=self._clear_images).pack(side="left")
        self.img_count = tk.Label(
            bar, text="共 0 张", bg=PALETTE["card"], fg=PALETTE["muted"],
            font=("Microsoft YaHei UI", 11))
        self.img_count.pack(side="right")
        self.img_scroll = ScrollableFrame(img_frame)
        self.img_scroll.pack(fill="both", expand=True, pady=(6, 0))

    def _detect_template(self):
        path = self.item.get("topic_path") or ""
        if "资料分析" in path:
            return "data"
        if "图形推理" in path:
            return "figure"
        if "申论" in path:
            return "shenlun"
        return "text"

    def _frame_titles(self):
        if self.template_key == "data":
            return ("资料/材料（文字或图表说明，可配材料图片）",
                    "题目+选项（可按题拆分，选择细分分类）")
        if self.template_key == "shenlun":
            return ("申论材料（长段材料可配多张图片，整组归属同一材料）",
                    "题目/作答（长文，可跨题目拆录）")
        if self.template_key == "figure":
            return ("基本知识（图形规律、识别要点等，可配图片）",
                    "图形题目（题干/选项含图形，可配题目图片）")
        return ("基本知识（公式、结论、要点等，可配图片）",
                "题目（学习内容、心得、完成情况等，可配图片）")

    def _status_text(self):
        return "已完成（{}）".format((self.item.get("checked_at") or "")[11:16]) if self.item["done"] else "未完成"

    def _load_images(self):
        for img in self.item.get("images", []):
            abs_path = self.db.abs_path(img["file_path"])
            raw_purpose = img.get("purpose") or "question"
            if raw_purpose == "knowledge":
                purpose = "knowledge"
            elif raw_purpose == "material":
                purpose = "material"
            else:
                purpose = "question"
            self.images.append({
                "rel": img["file_path"], "abs": abs_path, "purpose": purpose,
                "group_key": img.get("group_key") or "",
                "tk": None, "label": None, "frame": None,
            })
        self._render_images()

    # ---------- 图片列表 ----------
    def _render_images(self):
        for w in self.img_scroll.inner.winfo_children():
            w.destroy()
        self.selected_index = None
        if not self.images:
            tk.Label(
                self.img_scroll.inner, text="（还没有图片，点击「添加图片」）",
                bg=PALETTE["card"], fg=PALETTE["muted"], font=("Microsoft YaHei UI", 11),
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
            if img["purpose"] == "knowledge":
                badge_text, badge_bg, badge_fg = "知", PALETTE["accent_light"], PALETTE["accent"]
            elif img["purpose"] == "material":
                badge_text, badge_bg, badge_fg = "材", PALETTE["card"], PALETTE["warning"]
            else:
                badge_text, badge_bg, badge_fg = "题", PALETTE["primary_light"], PALETTE["primary_dark"]
            badge = tk.Label(
                frame, text=badge_text,
                font=("Microsoft YaHei UI", 10, "bold"), bg=badge_bg, fg=badge_fg,
                width=2, height=1,
            )
            badge.place(x=4, y=2)
            caption = tk.Label(
                frame, text=str(idx + 1), font=("Microsoft YaHei UI", 11),
                bg=PALETTE["card"], fg=PALETTE["muted"])
            caption.pack()
            label.bind("<Button-1>", lambda e, i=idx: self._toggle_select(i))
            frame.bind("<Button-1>", lambda e, i=idx: self._toggle_select(i))
            badge.bind("<Button-1>", lambda e, i=idx: self._toggle_select(i))
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
        picked = [p for p in paths if p.lower().endswith(
            (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"))]
        if not picked:
            return
        self._append_images(picked)

    def _append_images(self, paths):
        purpose = self._ask_purpose()
        if purpose is None:
            return
        group_key = self._new_group_key() if purpose == "material" else ""
        for p in paths:
            self.images.append({
                "rel": None, "abs": p, "purpose": purpose,
                "group_key": group_key,
                "tk": None, "label": None, "frame": None,
            })
        self._render_images()

    def _new_group_key(self):
        self._material_group_seq += 1
        return "mat-{}-{}".format(self.item_id, self._material_group_seq)

    def _on_paste_images(self, event=None):
        paths, tmp = paste_clipboard_images()
        if not paths:
            return
        self._clipboard_tmp.extend(tmp)
        self._append_images(paths)

    def _on_destroy_clipboard_cleanup(self, event):
        if event.widget is self:
            cleanup_temp_files(self._clipboard_tmp)
            self._clipboard_tmp = []

    def _ask_purpose(self):
        P = PALETTE
        top = tk.Toplevel(self)
        top.title("图片用途")
        top.configure(bg=P["bg"])
        top.attributes("-topmost", True)
        top.resizable(False, False)
        result = {"purpose": None}

        def choose(purpose):
            result["purpose"] = purpose
            top.destroy()

        tk.Label(
            top, text="这批图片的用途是？", bg=P["bg"], fg=P["text"],
            font=("Microsoft YaHei UI", 14, "bold"),
        ).pack(padx=22, pady=(16, 4))
        if self.template_key in ("data", "shenlun"):
            tip = "材料图会先整理为资料；题目图会进入题库前由你确认分类。"
        else:
            tip = "基本知识图会进入知识库；题目图会进入题库前由你确认分类。"
        tk.Label(
            top, text=tip, bg=P["bg"], fg=P["muted"], font=("Microsoft YaHei UI", 11),
        ).pack(padx=22, pady=(0, 12))
        btns = tk.Frame(top, bg=P["bg"])
        btns.pack(padx=22, pady=(0, 16))
        ttk.Button(
            btns, text="基本知识图片", command=lambda: choose("knowledge"),
        ).pack(side="left")
        if self.template_key in ("data", "shenlun"):
            ttk.Button(
                btns, text="材料图片", style="Accent.TButton",
                command=lambda: choose("material"),
            ).pack(side="left", padx=10)
            ttk.Button(
                btns, text="题目图片", style="Success.TButton",
                command=lambda: choose("question"),
            ).pack(side="left", padx=10)
        else:
            ttk.Button(
                btns, text="题目图片", style="Success.TButton",
                command=lambda: choose("question"),
            ).pack(side="left", padx=10)
        top.update_idletasks()
        center_window(top)
        top.grab_set()
        self.wait_window(top)
        return result["purpose"]

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
        note = self.note_text.get_html().strip()
        knowledge = self.basic_knowledge_text.get_html().strip()
        material = self.material_text.get_html().strip() if hasattr(self, "material_text") else ""
        answer = self.answer_text.get_html().strip() if hasattr(self, "answer_text") else ""
        if not note and not knowledge and not material and not answer and not self.images:
            ok = messagebox.askyesno(
                "确认打卡", "还没有填写总结或添加图片，确定要提交空打卡吗？", parent=self
            )
            if not ok:
                return
        combined = "\n".join(x for x in (knowledge, material, note, answer) if x)
        img_warn = None
        try:
            entries = []
            for im in self.images:
                entries.append((
                    im["rel"] if im["rel"] else im["abs"],
                    im["purpose"],
                    im.get("group_key") or "",
                ))
            try:
                saved_images = self.db.sync_checkin_images_with_purpose(self.item_id, entries)
                self.images = [
                    {
                        "rel": im["file_path"],
                        "abs": self.db.abs_path(im["file_path"]),
                        "purpose": im.get("purpose") or "question",
                        "group_key": im.get("group_key") or "",
                        "tk": None,
                        "label": None,
                        "frame": None,
                    }
                    for im in saved_images
                ]
            except Exception as exc:
                img_warn = "图片保存失败：{}".format(exc)
            self.db.update_checkin_full(
                self.item_id, note=combined, done=True,
                basic_knowledge=knowledge, material=material, answer=answer,
                content_type=self.template_key)
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
        knowledge_images = [im for im in self.images if im["purpose"] == "knowledge"]
        if knowledge_images:
            self._import_knowledge_images_after_close(knowledge_images)
        self._show_success()
        self._create_materials_from_images()
        if self.auto_collect_var.get() and any(
            im["purpose"] == "question" for im in self.images
        ):
            self._collect_to_bank()
        self.destroy()

    def _import_knowledge_images_after_close(self, knowledge_images):
        """关闭打卡窗口后，在后台 OCR 基本知识图并打开知识库确认弹窗。"""
        master = self.master
        db = self.db
        item_id = self.item_id
        topic_id = self.item.get("topic_id")
        sources = [db.abs_path(im["rel"]) for im in knowledge_images]

        def work():
            results = []
            for p in sources:
                try:
                    results.append(ocr_knowledge_document(p))
                except Exception:
                    results.append((p, None))
            master.after(200, lambda: self._finish_knowledge_import(results, master, db, topic_id, item_id))

        threading.Thread(target=work, daemon=True).start()

    def _finish_knowledge_import(self, results, master, db, topic_id, item_id):
        items = []
        for p, blocks in results:
            if blocks is None:
                continue
            rels = []
            for im in self.images:
                abs_p = Path(db.abs_path(im["rel"])).resolve().as_posix().lower()
                if abs_p == Path(p).resolve().as_posix().lower():
                    rels.append(im["rel"])
            items.append({"image_rels": rels, "blocks": blocks})
        if not items:
            return
        from habit_checkin.ui.knowledge_import_dialog import KnowledgeImportDialog
        dlg = KnowledgeImportDialog(
            master, db, items,
            default_topic_id=topic_id, source_item_id=item_id,
        )
        master.wait_window(dlg)
        if dlg.result:
            messagebox.showinfo(
                "知识库",
                "基本知识已保存到知识库。可打开左侧「知识库」页面查看和编辑。",
                parent=master,
            )

    # ---------- 确认式收录 ----------
    def _create_materials_from_images(self):
        """资料分析/申论：把「材料」图片按组整理成可挂接的材料记录。"""
        material_images = [im for im in self.images if im["purpose"] == "material"]
        if not material_images:
            return
        groups = {}
        for im in material_images:
            groups.setdefault(im.get("group_key") or "mat-{}".format(self.item_id), []).append(im)
        topic_id = self.item.get("topic_id")
        detail_paths = self.db.detail_type_paths_for_topic(topic_id) if topic_id else []
        created = 0
        from habit_checkin.ui.material_form_dialog import MaterialFormDialog
        for group_key in sorted(groups):
            sources = [
                im["abs"] if im["rel"] is None else self.db.abs_path(im["rel"])
                for im in groups[group_key]
            ]
            dlg = MaterialFormDialog(
                self, self.db,
                prefill_topic_id=topic_id,
                source_item_id=self.item_id,
                detail_paths=detail_paths,
                prefill_images=sources,
            )
            self.wait_window(dlg)
            if dlg.saved_material:
                created += 1
        if created:
            messagebox.showinfo(
                "资料整理",
                "已保存 {} 份材料。接下来收录题目时可直接挂接这份材料。".format(created),
                parent=self,
            )

    def _on_delete_key(self, event):
        if self.selected_index is not None:
            self._remove_selected()
            return "break"
        return None

    def _collect_to_bank(self):
        sources = [
            im["abs"] if im["rel"] is None else self.db.abs_path(im["rel"])
            for im in self.images if im["purpose"] == "question"
        ]
        if not sources:
            messagebox.showinfo(
                "收录到题库", "请先添加「题目」用途的图片，再收录其中的题目。",
                parent=self,
            )
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
