"""截图提取图形 / 截取识别解析：在原图上拖拽框选，截取或识别。"""
from __future__ import annotations

import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from PIL import Image, ImageTk

from habit_checkin.ui.common import center_window, setup_styles
from habit_checkin.ui.animate import fade_in
from habit_checkin.ui.theme import PALETTE


class CropTool(tk.Toplevel):
    def __init__(self, master, db, source_path, on_crop, ocr_mode=False,
                 on_ocr_text=None, keep_marks=False, on_close=None,
                 title_override=None, hint_override=None):
        super().__init__(master)
        self.db = db
        self.source = source_path
        self.on_crop = on_crop
        self.ocr_mode = ocr_mode
        self.on_ocr_text = on_ocr_text
        self.keep_marks = keep_marks
        self._on_close_cb = on_close
        self._n = 0
        self.title(title_override or ("截取识别解析" if ocr_mode else "截图提取图形（拖拽框选；Esc 退出）"))
        self._hint_override = hint_override
        self.transient(master)
        setup_styles(self)
        self.configure(bg=PALETTE["bg"])
        self._build_ui()
        self._load_image()
        center_window(self)
        self.grab_set()
        fade_in(self)

    def _build_ui(self):
        P = PALETTE
        top = tk.Frame(self, bg=P["bg"], padx=12)
        top.pack(fill="x", pady=(10, 6))
        hint = "在原图上按住左键拖拽框选，松开即把框内区域截取为独立图片（用于题目图形/选项图形）。"
        if self.ocr_mode:
            hint = "框选解析区域，松开即自动识别该区域文字并加入「解析」栏；可连续框选多个区域。"
        if self._hint_override:
            hint = self._hint_override
        tk.Label(top, text=hint, bg=P["bg"], fg=P["text"],
                 font=("Microsoft YaHei UI", 13)).pack(anchor="w")
        self.status = tk.Label(top, text="", bg=P["bg"], fg=P["accent"],
                               font=("Microsoft YaHei UI", 13, "bold"))
        self.status.pack(anchor="w", pady=(2, 0))
        self.done_count = tk.Label(top, text="已提取 0 张", bg=P["bg"], fg=P["muted"])
        self.done_count.pack(anchor="w")

        wrap = tk.Frame(self, bg=P["card"], highlightbackground=P["border"], highlightthickness=1)
        wrap.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self.canvas = tk.Canvas(wrap, bg=P["card"], highlightthickness=0)
        hsb = ttk.Scrollbar(wrap, orient="horizontal", command=self.canvas.xview)
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=hsb.set, yscrollcommand=vsb.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Escape>", lambda e: self.destroy())

        bottom = tk.Frame(self, bg=P["bg"], padx=12, pady=8)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="完成", command=self.destroy).pack(side="right")
        if self.ocr_mode:
            ttk.Button(bottom, text="撤销上一张", command=self._undo).pack(side="right", padx=8)

    def _load_image(self):
        self.img = Image.open(self.source)
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        max_w, max_h = sw - 140, sh - 220
        scale = min(1.0, max_w / self.img.width, max_h / self.img.height)
        self.scale = scale
        disp = self.img.resize((int(self.img.width * scale), int(self.img.height * scale)), Image.LANCZOS)
        self.tk_img = ImageTk.PhotoImage(disp)
        self.canvas.create_image(0, 0, image=self.tk_img, anchor="nw")
        self.canvas.configure(scrollregion=(0, 0, disp.width, disp.height))
        # 窗口自适应完整展示整张图，随后居中
        win_w = min(disp.width + 40, sw - 40)
        win_h = min(disp.height + 160, sh - 60)
        self.geometry("{}x{}+0+0".format(max(win_w, 480), max(win_h, 360)))

    def _on_press(self, e):
        self._x0 = self.canvas.canvasx(e.x)
        self._y0 = self.canvas.canvasy(e.y)
        self._rect = None

    def _on_drag(self, e):
        if self._rect:
            self.canvas.delete(self._rect)
        x1 = self.canvas.canvasx(e.x)
        y1 = self.canvas.canvasy(e.y)
        self._rect = self.canvas.create_rectangle(
            self._x0, self._y0, x1, y1, outline=PALETTE["danger"], width=2, dash=(4, 3)
        )

    def _on_release(self, e):
        if self._rect:
            self.canvas.delete(self._rect)
            self._rect = None
        x0, x1 = sorted((self._x0, self.canvas.canvasx(e.x)))
        y0, y1 = sorted((self._y0, self.canvas.canvasy(e.y)))
        ix0, iy0 = int(x0 / self.scale), int(y0 / self.scale)
        ix1, iy1 = int(x1 / self.scale), int(y1 / self.scale)
        if ix1 - ix0 < 8 or iy1 - iy0 < 8:
            self.status.configure(text="框选区域太小，请重新拖拽", fg=PALETTE["danger"])
            return
        self._last_w, self._last_h = ix1 - ix0, iy1 - iy0
        crop = self.img.crop((ix0, iy0, ix1, iy1))
        tmp = Path(tempfile.gettempdir()) / "habit_crop.png"
        crop.save(tmp, "PNG")
        rel = self.db.store_image_from_path(str(tmp))
        self._n += 1
        self.done_count.configure(text="已提取 {} 张".format(self._n))
        abs_path = self.db.abs_path(rel)
        self.on_crop(abs_path)
        if self.ocr_mode:
            self.status.configure(text="识别解析中…", fg=PALETTE["accent"])

            def work():
                from habit_checkin.services.ocr import ocr_image_lines
                lines = ocr_image_lines(abs_path, keep_marks=self.keep_marks)
                text = "\n".join(lines) if lines else ""
                self.after(0, lambda: self._ocr_done(abs_path, text))

            threading.Thread(target=work, daemon=True).start()
        else:
            # 单次截取模式：截取成功后自动关闭窗口
            self.canvas.unbind("<ButtonPress-1>")
            self.canvas.unbind("<B1-Motion>")
            self.canvas.unbind("<ButtonRelease-1>")
            self.status.configure(text="已截取，窗口即将自动关闭", fg=PALETTE["accent"])

            def _auto_close():
                try:
                    if self.winfo_exists():
                        self.destroy()
                except tk.TclError:
                    pass
            self.after(300, _auto_close)

    def _ocr_done(self, abs_path, text):
        if text:
            if self.on_ocr_text:
                self.on_ocr_text(text)
            self.status.configure(text="已识别并加入解析栏（{}×{}）".format(self._last_w, self._last_h),
                                  fg=PALETTE["accent"])
        else:
            self.status.configure(text="该区域未识别到文字，可重新框选", fg=PALETTE["danger"])

    def _undo(self):
        self.on_crop(None)
        self._n = max(0, self._n - 1)
        self.done_count.configure(text="已提取 {} 张".format(self._n))
        self.status.configure(text="已撤销上一张")

    def destroy(self):
        if self._on_close_cb:
            self._on_close_cb()
        super().destroy()
