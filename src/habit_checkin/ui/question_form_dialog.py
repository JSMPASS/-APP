"""题目表单对话框：上传图片、OCR 识别、分类（大/小知识点）、对错关系与原因。"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from habit_checkin.services.ocr import format_questions_text, normalize_ocr_text, ocr_image_lines, parse_ocr_questions, reconstruct_page, split_figure_stems
from habit_checkin.ui.common import ScrollableFrame, TextCheck, center_window, make_thumbnail, setup_styles, show_image_zoom
from habit_checkin.ui.animate import fade_in
from habit_checkin.ui.theme import PALETTE, dialog_header, hover_button

REASONS_CORRECT = ["完全理解", "蒙对"]
REASONS_WRONG = ["读题粗心", "计算粗心", "知识点了解不全"]
RESULT_LABELS = {"correct": "正确", "wrong": "错误", None: "未判定"}
_FILETYPES = [("图片", "*.png *.jpg *.jpeg *.webp *.bmp *.gif *.tif *.tiff"), ("所有文件", "*.*")]


class QuestionFormDialog(tk.Toplevel):
    def __init__(self, master, db, question=None, prefill_images=None,
                 prefill_topic_id=None, source="manual", source_item_id=None,
                 question_list=None, index=0):
        super().__init__(master)
        self.db = db
        self.question = question
        self.images = []  # {rel, abs, tk, label, frame}
        self.saved_question = None
        self._source = source
        self._source_item_id = source_item_id
        self._qlist = question_list if question_list else ([question] if question else [])
        self._index = index
        self._analysis_queue = []
        self.result_var = tk.StringVar(value="未判定")
        self.reason_var = tk.StringVar(value="")
        self.topic_var = tk.StringVar(value="（未分类）")
        self.title("编辑题目" if question else "新增题目")
        self.geometry("760x920")
        self.minsize(700, 800)
        self.transient(master)
        setup_styles(self)
        self.configure(bg=PALETTE["bg"])
        self._build_ui()
        self._load_initial(question, prefill_images, prefill_topic_id)
        center_window(self)
        self.bind("<Delete>", self._on_delete_key)
        self.grab_set()
        self.focus_set()
        fade_in(self)

    # ---------- 界面 ----------
    def _build_ui(self):
        P = PALETTE
        dialog_header(self, self.title(), "图片 OCR · 分类 · 对错关系")
        # 底部操作栏优先打包（side=bottom），保证「保存/取消」始终可见
        bottom = tk.Frame(self, bg=P["bg"], padx=14, pady=10)
        bottom.pack(side="bottom", fill="x")
        self.code_label = tk.Label(bottom, text="", bg=P["bg"], fg=P["muted"], font=("Microsoft YaHei UI", 11))
        self.code_label.pack(side="left")
        ttk.Button(bottom, text="取消", command=self.destroy).pack(side="right")
        ttk.Button(bottom, text="保存", style="Accent.TButton", command=self._save).pack(side="right", padx=8)

        body = tk.Frame(self, bg=P["bg"], padx=14, pady=10)
        body.pack(fill="both", expand=True)

        # 分类与对错
        meta = tk.Frame(body, bg=P["card"], padx=12, pady=10,
                        highlightbackground=P["border"], highlightthickness=1)
        meta.pack(fill="x", pady=(0, 8))
        row1 = tk.Frame(meta, bg=P["card"])
        row1.pack(fill="x")
        tk.Label(row1, text="知识点分类：", bg=P["card"]).pack(side="left")
        self.topic_box = ttk.Combobox(row1, textvariable=self.topic_var, state="readonly", width=34)
        self.topic_box.pack(side="left")
        tk.Label(row1, text="对错：", bg=P["card"]).pack(side="left", padx=(16, 0))
        self.result_box = ttk.Combobox(row1, textvariable=self.result_var, state="readonly",
                                       values=["未判定", "正确", "错误"], width=8)
        self.result_box.pack(side="left")
        tk.Label(row1, text="原因：", bg=P["card"]).pack(side="left", padx=(10, 0))
        self.reason_box = ttk.Combobox(row1, textvariable=self.reason_var, state="readonly", width=14)
        self.reason_box.pack(side="left")
        self.result_box.bind("<<ComboboxSelected>>", lambda e: self._update_reasons())
        if self.question and self._qlist and len(self._qlist) > 1:
            nav = tk.Frame(meta, bg=P["card"])
            nav.pack(fill="x", pady=(8, 0))
            group = tk.Frame(nav, bg=P["card"])
            group.pack(anchor="center")
            hover_button(group, "◀ 上一题", lambda: self._switch_question(-1),
                         padx=14, pady=5).pack(side="left")
            self.nav_label = tk.Label(group, text="", bg=P["card"], fg=P["primary"],
                                      font=("Microsoft YaHei UI", 13, "bold"), padx=16)
            self.nav_label.pack(side="left")
            hover_button(group, "下一题 ▶", lambda: self._switch_question(1),
                         padx=14, pady=5).pack(side="left")

        # 题目内容
        q_frame = tk.Frame(body, bg=P["card"], padx=12, pady=10,
                           highlightbackground=P["border"], highlightthickness=1)
        q_frame.pack(fill="both", expand=True, pady=(0, 8))
        tk.Label(q_frame, text="题目内容（可 OCR 识别后核对修改）：", bg=P["card"], fg=P["text"],
                 font=("Microsoft YaHei UI", 13, "bold")).pack(anchor="w")
        self.question_text = tk.Text(q_frame, height=6, wrap="word", font=("Microsoft YaHei UI", 13),
                                     bg=P["input"], fg=P["text"], relief="flat", highlightthickness=1,
                                     highlightbackground=P["border"], highlightcolor=P["primary"])
        self.question_text.pack(fill="both", expand=True, pady=(4, 0))

        a_frame = tk.Frame(body, bg=P["card"], padx=12, pady=10,
                           highlightbackground=P["border"], highlightthickness=1)
        a_frame.pack(fill="both", expand=True, pady=(0, 8))
        tk.Label(a_frame, text="题目解析：", bg=P["card"], fg=P["text"],
                 font=("Microsoft YaHei UI", 13, "bold")).pack(anchor="w")
        self.analysis_text = tk.Text(a_frame, height=5, wrap="word", font=("Microsoft YaHei UI", 13),
                                     bg=P["input"], fg=P["text"], relief="flat", highlightthickness=1,
                                     highlightbackground=P["border"], highlightcolor=P["primary"])
        self.analysis_text.pack(fill="both", expand=True, pady=(4, 0))

        # 图片 + OCR
        img_frame = tk.Frame(body, bg=P["card"], padx=12, pady=10,
                             highlightbackground=P["border"], highlightthickness=1)
        img_frame.pack(fill="both", expand=True)
        bar = tk.Frame(img_frame, bg=P["card"])
        bar.pack(fill="x")
        ttk.Button(bar, text="添加图片", command=self._add_images).pack(side="left")
        ttk.Button(bar, text="移除选中", command=self._remove_selected).pack(side="left", padx=6)
        ttk.Button(bar, text="识别图中题目", command=lambda: self._ocr("question")).pack(side="left", padx=6)
        ttk.Button(bar, text="补充解析", command=self._ocr_analysis_crop).pack(side="left", padx=6)
        ttk.Button(bar, text="智能整理", command=self._smart_format).pack(side="left", padx=6)
        ttk.Button(bar, text="跨页合并识别", command=self._ocr_merge).pack(side="left", padx=6)
        self.ocr_status = tk.Label(bar, text="共 0 张图片", bg=P["card"], fg=P["muted"],
                                   font=("Microsoft YaHei UI", 11))
        self.ocr_status.pack(side="right")
        opt_row = tk.Frame(img_frame, bg=PALETTE["card"])
        opt_row.pack(fill="x", pady=(4, 0))
        self.keep_marks_var = tk.BooleanVar(value=False)
        TextCheck(
            opt_row, "保留红笔/手写标注（资料分析需识别圈量/笔记时勾选）",
            variable=self.keep_marks_var, bg=PALETTE["card"],
        ).pack(side="left")
        ttk.Button(opt_row, text="再次截取", command=self._open_crop_tool).pack(side="left", padx=12)
        ttk.Button(opt_row, text="提取图形", command=self._open_figure_tool).pack(side="left", padx=12)
        ttk.Button(opt_row, text="图形切题", command=self._figure_split).pack(side="left", padx=12)
        self.img_scroll = ScrollableFrame(img_frame)
        self.img_scroll.pack(fill="both", expand=True, pady=(6, 0))

    def _load_initial(self, question, prefill_images, prefill_topic_id):
        topics = self.db.list_topics(include_disabled=False)
        self.topic_paths = []
        self.topic_id_map = {}
        for t in topics:
            path = self.db.topic_path(t["id"])
            self.topic_paths.append(path)
            self.topic_id_map[path] = t["id"]
        self.topic_box.configure(values=["（未分类）"] + self.topic_paths)

        if question:
            self._apply_question(question)
        else:
            if prefill_topic_id:
                path = self.db.topic_path(prefill_topic_id)
                if path in self.topic_id_map:
                    self.topic_var.set(path)
            for src in (prefill_images or []):
                self.images.append({"rel": None, "abs": src, "tk": None, "label": None, "frame": None})
        self._update_reasons()
        self._render_images()

    def _apply_question(self, q):
        self.question = q
        self.code_label.configure(text="编号：{}".format(q["code"]))
        if q["topic_id"]:
            path = self.db.topic_path(q["topic_id"])
            self.topic_var.set(path if path in self.topic_id_map else "（未分类）")
        else:
            self.topic_var.set("（未分类）")
        self.question_text.delete("1.0", "end")
        self.question_text.insert("1.0", q["question_text"] or "")
        self.analysis_text.delete("1.0", "end")
        self.analysis_text.insert("1.0", q["analysis"] or "")
        if q["result"]:
            self.result_var.set(RESULT_LABELS.get(q["result"], "未判定"))
            self.reason_var.set(q["result_reason"] or "")
        else:
            self.result_var.set("未判定")
            self.reason_var.set("")
        self._update_reasons()
        self._embedded_photos = []
        self.images = []
        for img in q.get("images", []):
            self.images.append({"rel": img["file_path"], "abs": self.db.abs_path(img["file_path"]),
                                "tk": None, "label": None, "frame": None})
        self._render_images()
        self._update_nav_label()

    def _save_current(self):
        if self.question is None:
            return
        topic_id = self.topic_id_map.get(self.topic_var.get())
        result = {"正确": "correct", "错误": "wrong"}.get(self.result_var.get())
        self.db.update_question(
            self.question["id"], topic_id=topic_id,
            question_text=self.question_text.get("1.0", "end").strip(),
            analysis=self.analysis_text.get("1.0", "end").strip(),
            result=result, result_reason=self.reason_var.get().strip(),
        )
        kept = [im["rel"] for im in self.images if im["rel"]]
        new_sources = [im["abs"] for im in self.images if im["rel"] is None]
        self.db.sync_question_images(self.question["id"], kept, new_sources)

    def _switch_question(self, delta):
        if self.question is None or not self._qlist:
            return
        new_index = self._index + delta
        if new_index < 0 or new_index >= len(self._qlist):
            messagebox.showinfo("切换题目", "已经到头了。", parent=self)
            return
        self._save_current()
        self._index = new_index
        q = self.db.get_question(self._qlist[new_index]["id"])
        if q:
            self._apply_question(q)
            self.title("编辑题目：{}".format(q["code"]))

    def _update_nav_label(self):
        if hasattr(self, "nav_label") and self._qlist:
            self.nav_label.configure(text="第 {} / {} 题".format(self._index + 1, len(self._qlist)))

    def _ocr_analysis_crop(self):
        paths = filedialog.askopenfilenames(
            parent=self, filetypes=_FILETYPES, title="选择解析图片（可多选，将逐张截取识别）"
        )
        if not paths:
            return
        self._analysis_queue = list(paths)
        self._open_next_analysis_crop()

    def _open_next_analysis_crop(self):
        if not getattr(self, "_analysis_queue", None):
            self.ocr_status.configure(text="解析截取识别完成")
            return
        p = self._analysis_queue.pop(0)
        self.images.append({"rel": None, "abs": p, "tk": None, "label": None, "frame": None})
        self._render_images()
        from habit_checkin.ui.crop_tool import CropTool
        CropTool(self, self.db, p, self._on_crop_add, ocr_mode=True,
                 on_ocr_text=self._append_analysis_ocr,
                 keep_marks=self.keep_marks_var.get(),
                 on_close=self._open_next_analysis_crop)

    def _append_analysis_ocr(self, text):
        if not text:
            return
        existing = self.analysis_text.get("1.0", "end").strip()
        if existing:
            self.analysis_text.insert("end", "\n" + text)
        else:
            self.analysis_text.insert("1.0", text)
        self.ocr_status.configure(text="已识别一段解析，继续框选或完成后处理下一张")

    def _update_reasons(self):
        res = self.result_var.get()
        if res == "正确":
            self.reason_box.configure(values=[""] + REASONS_CORRECT)
            if self.reason_var.get() not in REASONS_CORRECT:
                self.reason_var.set("")
        elif res == "错误":
            self.reason_box.configure(values=[""] + REASONS_WRONG)
            if self.reason_var.get() not in REASONS_WRONG:
                self.reason_var.set("")
        else:
            self.reason_box.configure(values=[""])
            self.reason_var.set("")

    # ---------- 图片 ----------
    def _render_images(self):
        for w in self.img_scroll.inner.winfo_children():
            w.destroy()
        self.selected_index = None
        if not self.images:
            tk.Label(self.img_scroll.inner, text="（还没有图片）", bg=PALETTE["card"],
                     fg=PALETTE["muted"], font=("Microsoft YaHei UI", 11)).pack(anchor="w", pady=4)
            self.ocr_status.configure(text="共 0 张图片")
            return
        row = tk.Frame(self.img_scroll.inner, bg=PALETTE["card"])
        row.pack(fill="x", pady=2)
        for idx, img in enumerate(self.images):
            if idx % 5 == 0 and idx > 0:
                row = tk.Frame(self.img_scroll.inner, bg=PALETTE["card"])
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
            tk.Label(frame, text=str(idx + 1), font=("Microsoft YaHei UI", 11),
                     bg=PALETTE["card"], fg=PALETTE["muted"]).pack()
            label.bind("<Button-1>", lambda e, i=idx: self._toggle_select(i))
            frame.bind("<Button-1>", lambda e, i=idx: self._toggle_select(i))
            label.bind("<Double-1>", lambda e, i=idx: show_image_zoom(self, self.images[i]["abs"]))
            frame.bind("<Double-1>", lambda e, i=idx: show_image_zoom(self, self.images[i]["abs"]))
            img.update(tk=tk_img, label=label, frame=frame)
        self.ocr_status.configure(text="共 {} 张图片".format(len(self.images)))

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
        paths = filedialog.askopenfilenames(parent=self, filetypes=_FILETYPES, title="选择题目图片（可多选）")
        for p in paths:
            self.images.append({"rel": None, "abs": p, "tk": None, "label": None, "frame": None})
        self._render_images()

    def _remove_selected(self):
        if self.selected_index is None:
            messagebox.showinfo("移除图片", "请先点击选中要移除的图片。", parent=self)
            return
        del self.images[self.selected_index]
        self._render_images()

    # ---------- OCR ----------
    def _image_paths(self):
        return [im["abs"] if im["rel"] is None else self.db.abs_path(im["rel"]) for im in self.images]

    def _ocr(self, target):
        if self.selected_index is not None and 0 <= self.selected_index < len(self.images):
            im = self.images[self.selected_index]
            paths = [im["abs"] if im["rel"] is None else self.db.abs_path(im["rel"])]
            hint = "识别选中图片中…请稍候"
        else:
            paths = self._image_paths()
            hint = "识别中（{} 张）…请稍候".format(len(paths))
        if not paths:
            messagebox.showinfo("OCR 识别", "请先添加题目图片。", parent=self)
            return
        self.ocr_status.configure(text=hint)
        keep = self.keep_marks_var.get()  # 主线程取值，避免线程内访问 Tk 变量

        def work():
            lines = []
            for p in paths:
                plines = ocr_image_lines(p, keep_marks=keep)
                if plines:
                    lines.extend(plines)
            self.after(0, lambda: self._ocr_done(target, lines))

        threading.Thread(target=work, daemon=True).start()

    def _ocr_done(self, target, lines):
        if target == "question":
            clean = [l.strip() for l in lines if l.strip()]
            text = "\n".join(clean)
            if not text:
                self.ocr_status.configure(text="未识别到文字，请手动输入")
                return
            n = len(parse_ocr_questions(clean))
            self._fill(self.question_text, text)
            hint = "已填入识别结果（尽量保留原图版式与换行）"
            if n > 1:
                hint += "；识别到 {} 道题，可点「智能整理」拆题/分行".format(n)
            self.ocr_status.configure(text=hint)
        else:
            text = "\n".join(lines).strip()
            if not text:
                self.ocr_status.configure(text="未识别到文字，请手动输入")
                return
            self._fill(self.analysis_text, text)
            self.ocr_status.configure(text="已填入识别结果，请核对修改")

    def _fill(self, widget, text):
        if widget.get("1.0", "end").strip():
            widget.insert("end", "\n" + text)
        else:
            widget.insert("1.0", text)

    def _ocr_merge(self):
        """跨页合并识别：按顺序 OCR 全部图片，合并重构跨页题目，一次性填充/拆分。"""
        paths = self._image_paths()
        if not paths:
            messagebox.showinfo("跨页合并识别", "请先添加图片：把同一组题跨页的多张照片按顺序全部选入。", parent=self)
            return
        self.ocr_status.configure(text="跨页合并识别中（{} 张）…请稍候".format(len(paths)))
        keep = self.keep_marks_var.get()  # 主线程取值

        def work():
            all_lines = []
            for p in paths:
                plines = ocr_image_lines(p, keep_marks=keep)
                if plines:
                    all_lines.extend(plines)
            self.after(0, lambda: self._merge_done(all_lines))

        threading.Thread(target=work, daemon=True).start()

    def _merge_done(self, lines):
        clean = [l.strip() for l in lines if l.strip()]
        text = "\n".join(clean)
        questions = reconstruct_page(clean)
        if questions:
            if len(questions) > 1:
                ok = messagebox.askyesno(
                    "识别到多道题",
                    "跨页合并后识别到 {} 道题，是否按题拆分为 {} 条题目？\n（选择「否」则合并填入）".format(
                        len(questions), len(questions)
                    ),
                    parent=self,
                )
                if ok:
                    self._split_into_questions(questions)
                    return
            formatted = normalize_ocr_text(format_questions_text(questions))
            self.question_text.delete("1.0", "end")
            self.question_text.insert("1.0", formatted)
            self.ocr_status.configure(text="跨页合并完成（跨页题目已合并，标点已统一），请核对后保存")
        else:
            if not text:
                self.ocr_status.configure(text="未识别到文字，请手动输入")
                return
            self._fill(self.question_text, text)
            self.ocr_status.configure(text="未能结构化（页面排版不规整），已按原版式填入全部文字")

    def _smart_format(self):
        text = self.question_text.get("1.0", "end").strip()
        ana = self.analysis_text.get("1.0", "end").strip()
        if not text and not ana:
            messagebox.showinfo("智能整理", "请先 OCR 识别或输入题目/解析内容。", parent=self)
            return
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        text_qs = (reconstruct_page(lines) or parse_ocr_questions(lines)) if lines else None
        fig_qs = split_figure_stems(lines) if lines else None
        # 有选项/单题 → 文本结构化结果优先；否则（图形页多题干）用题干切分
        if text_qs and (len(text_qs) == 1 or any(q.get("options") for q in text_qs)):
            questions = text_qs
        elif fig_qs:
            questions = fig_qs
        else:
            questions = text_qs
        if not questions:
            # 无法结构化：仍统一标点/空格
            if text:
                self.question_text.delete("1.0", "end")
                self.question_text.insert("1.0", normalize_ocr_text(text))
            if ana:
                self.analysis_text.delete("1.0", "end")
                self.analysis_text.insert("1.0", normalize_ocr_text(ana))
            self.ocr_status.configure(text="未识别出题目结构，已统一标点/空格")
            return
        if questions and len(questions) > 1 and all(not q.get("options") for q in questions):
            ok = messagebox.askyesno(
                "识别到多道图形推理题",
                "识别到 {} 道图形推理题，是否按题干拆分为 {} 条题目？\n（图形部分可再用「图形切题」或截图工具提取）".format(
                    len(questions), len(questions)
                ),
                parent=self,
            )
            if ok:
                self._split_into_questions(questions)
                return
        if len(questions) > 1:
            ok = messagebox.askyesno(
                "识别到多道题",
                "识别到 {} 道题。是否按题拆分为 {} 条题目？\n（选择「否」则合并整理为美观格式）".format(
                    len(questions), len(questions)
                ),
                parent=self,
            )
            if ok:
                self._split_into_questions(questions)
                return
        formatted = normalize_ocr_text(format_questions_text(questions))
        self.question_text.delete("1.0", "end")
        self.question_text.insert("1.0", formatted)
        if ana:
            self.analysis_text.delete("1.0", "end")
            self.analysis_text.insert("1.0", normalize_ocr_text(ana))
        self.ocr_status.configure(text="已整理题目与解析（格式/标点/字体统一）")

    def _open_crop_tool(self):
        src = self._primary_image_path()
        if not src:
            messagebox.showinfo("再次截取", "请先添加题目图片。", parent=self)
            return
        from habit_checkin.ui.crop_tool import CropTool
        CropTool(self, self.db, src, self._on_crop_add)

    def _primary_image_path(self):
        """优先返回选中的图片，否则返回第一张图片。"""
        if self.selected_index is not None and 0 <= self.selected_index < len(self.images):
            im = self.images[self.selected_index]
            return im["abs"] if im["rel"] is None else self.db.abs_path(im["rel"])
        sources = self._image_paths()
        return sources[0] if sources else None

    def _on_delete_key(self, event):
        if self.selected_index is not None:
            self._remove_selected()
            return "break"
        return None

    def _open_figure_tool(self):
        src = self._primary_image_path()
        if not src:
            messagebox.showinfo("提取图形", "请先添加题目图片。", parent=self)
            return
        from habit_checkin.ui.crop_tool import CropTool
        CropTool(
            self, self.db, src, self._on_crop_figure,
            title_override="提取图形（去背景）",
            hint_override="框选「题干图形+选项图形」的整体区域，松开即去除背景后加入题目内容。",
        )

    def _on_crop_figure(self, abs_path):
        if abs_path is None:
            for i in range(len(self.images) - 1, -1, -1):
                if self.images[i]["rel"] is None:
                    del self.images[i]
                    break
            self._render_images()
            return
        from habit_checkin.services.figures import make_transparent_bg
        processed = make_transparent_bg(abs_path)
        self.images.append({"rel": None, "abs": processed, "tk": None, "label": None, "frame": None})
        self._render_images()
        self._embed_image_in_text(processed)

    def _embed_image_in_text(self, path, max_w=300):
        """把图形图片嵌入「题目内容」文本框的文字下方（透明背景显示为白底）。"""
        from PIL import Image, ImageTk
        img = Image.open(path)
        if img.width > max_w:
            img = img.resize((max_w, int(img.height * max_w / img.width)), Image.LANCZOS)
        photo = ImageTk.PhotoImage(img)
        if not hasattr(self, "_embedded_photos"):
            self._embedded_photos = []
        self._embedded_photos.append(photo)
        self.question_text.image_create("end", image=photo)
        self.question_text.insert("end", "\n")

    def _figure_split(self):
        src = self._primary_image_path()
        if not src:
            messagebox.showinfo("图形切题", "请先添加题目图片。", parent=self)
            return
        from habit_checkin.services.figures import split_figure_page
        keep = self.keep_marks_var.get()  # 主线程取值，避免线程内访问 Tk 变量
        self.ocr_status.configure(text="图形切题分析中…请稍候")

        def work():
            parts = split_figure_page(src, keep_marks=keep)
            self.after(0, lambda: self._figure_split_done(parts, src))

        threading.Thread(target=work, daemon=True).start()

    def _figure_split_done(self, parts, src):
        if not parts:
            self.ocr_status.configure(text="未能识别题号/题干，可改用「再次截取」手动处理")
            return
        if len(parts) == 1:
            q = parts[0]
            if q["stem"]:
                self._fill(self.question_text, q["stem"])
            if q["figure_path"]:
                rel = self.db.store_image_from_path(q["figure_path"])
                abs_path = self.db.abs_path(rel)
                self.images.append({"rel": None, "abs": abs_path, "tk": None, "label": None, "frame": None})
                self._render_images()
                self._embed_image_in_text(abs_path)
            self.ocr_status.configure(text="已切题：题干已填入，图形已去背景并嵌入题目下方")
            return
        ok = messagebox.askyesno(
            "识别到多道题", "识别到 {} 道图形推理题，是否按题拆分？".format(len(parts)), parent=self
        )
        if ok:
            topic_id = self.topic_id_map.get(self.topic_var.get())
            img_sources = [im["abs"] if im["rel"] is None else self.db.abs_path(im["rel"]) for im in self.images]
            created = []
            for q in parts:
                text = (q["stem"] or "").strip()
                qid = self.db.add_question(topic_id=topic_id, question_text=text,
                                           source=self._source, source_item_id=self._source_item_id)
                srcs = img_sources[:]
                if q["figure_path"]:
                    srcs.append(q["figure_path"])
                self.db.sync_question_images(qid, [], srcs)
                created.append(qid)
            messagebox.showinfo("拆分完成", "已拆分为 {} 道图形推理题。".format(len(created)), parent=self)
            self.saved_question = self.db.get_question(created[0])
            self.destroy()
        else:
            text = "\n".join((q["stem"] or "").strip() for q in parts if q["stem"])
            if text:
                self._fill(self.question_text, text)
            self.ocr_status.configure(text="已填入题干文本")

    def _on_crop_add(self, abs_path):
        if abs_path is None:
            for i in range(len(self.images) - 1, -1, -1):
                if self.images[i]["rel"] is None:
                    del self.images[i]
                    break
        else:
            self.images.append({"rel": None, "abs": abs_path, "tk": None, "label": None, "frame": None})
        self._render_images()

    def _split_into_questions(self, questions):
        topic_id = self.topic_id_map.get(self.topic_var.get())
        sources = [im["abs"] if im["rel"] is None else self.db.abs_path(im["rel"]) for im in self.images]
        created = []
        for q in questions:
            text = format_questions_text([q])
            qid = self.db.add_question(topic_id=topic_id, question_text=text,
                                       source=self._source, source_item_id=self._source_item_id)
            self.db.sync_question_images(qid, [], sources)
            created.append(qid)
        messagebox.showinfo(
            "拆分完成", "已将识别内容拆分为 {} 道题，可到题库查看。".format(len(created)), parent=self
        )
        self.saved_question = self.db.get_question(created[0])
        self.destroy()

    # ---------- 保存 ----------
    def _save(self):
        topic_id = self.topic_id_map.get(self.topic_var.get())
        result = {"正确": "correct", "错误": "wrong"}.get(self.result_var.get())
        reason = self.reason_var.get().strip()
        fields = {
            "topic_id": topic_id,
            "question_text": self.question_text.get("1.0", "end").strip(),
            "analysis": self.analysis_text.get("1.0", "end").strip(),
            "result": result,
            "result_reason": reason,
        }
        if self.question:
            self.db.update_question(self.question["id"], **fields)
            qid = self.question["id"]
        else:
            qid = self.db.add_question(source=self._source, source_item_id=self._source_item_id, **fields)
        kept = [im["rel"] for im in self.images if im["rel"]]
        new_sources = [im["abs"] for im in self.images if im["rel"] is None]
        self.db.sync_question_images(qid, kept, new_sources)
        self.saved_question = self.db.get_question(qid)
        self.destroy()
