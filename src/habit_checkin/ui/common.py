"""UI 公共工具：样式、缩略图、可滚动容器。"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from habit_checkin.ui.theme import PALETTE, FONT, FONT_SMALL, FONT_TITLE, FONT_BIG, apply_theme

# 兼容旧引用
FONT = FONT
FONT_SMALL = FONT_SMALL
FONT_TITLE = FONT_TITLE
FONT_BIG = FONT_BIG


def setup_styles(root):
    """应用全局主题（兼容旧调用）。"""
    apply_theme(root)


def center_window(win):
    """把窗口居中到屏幕正中央（保留原尺寸；无尺寸时按请求尺寸）。"""
    win.update_idletasks()
    w = h = None
    try:
        size = win.geometry().split("+")[0]
        w, h = (int(x) for x in size.split("x"))
        if w <= 1 or h <= 1:
            w = h = None
    except Exception:
        w = h = None
    if not w or not h:
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
    x = max((win.winfo_screenwidth() - w) // 2, 0)
    y = max((win.winfo_screenheight() - h) // 2, 0)
    win.geometry("{}x{}+{}+{}".format(w, h, x, y))


def make_thumbnail(path, size=96):
    """生成缩略图 PhotoImage（调用方需持有引用）。"""
    from PIL import Image, ImageTk
    img = Image.open(path)
    img.thumbnail((size, size))
    return ImageTk.PhotoImage(img)


class ScrollableFrame(tk.Frame):
    """带竖向滚动条和鼠标滚轮支持的容器。"""

    def __init__(self, master, bg=None, **kw):
        bg = bg or PALETTE["card"]
        super().__init__(master, bg=bg, **kw)
        self.canvas = tk.Canvas(self, highlightthickness=0, bg=bg)
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.vsb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas.bind(
            "<Configure>",
            lambda e: self.canvas.itemconfigure(self._win, width=e.width),
        )
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.inner.bind("<MouseWheel>", self._on_wheel)

    def _on_wheel(self, event):
        self.canvas.yview_scroll(int(-event.delta / 120), "units")
        return "break"

    def bind_wheel_all(self):
        """把鼠标滚轮递归绑定到内容区所有子孙控件，使其在任意位置都能滚动。

        需在内容构建完成后调用（内容重建时再次调用）。
        """
        def _bind(widget):
            widget.bind("<MouseWheel>", self._on_wheel)
            for child in widget.winfo_children():
                _bind(child)
        _bind(self.inner)


class EmptyState(tk.Frame):
    """统一空状态：图示 + 标题 + 说明 + 可选入口按钮。

    用 place_in(parent) 居中浮在目标容器上，不改变原有布局；不需要时 destroy()。
    """

    def __init__(self, master, title, description="", action_text=None, command=None,
                 bg=None, max_width=560):
        bg = bg or PALETTE["surface"]
        super().__init__(master, bg=bg)
        P = PALETTE
        inner = tk.Frame(self, bg=bg)
        inner.pack(padx=30, pady=26)
        self._icon = tk.Canvas(inner, width=76, height=62, bg=bg, highlightthickness=0)
        self._icon.pack()
        self._draw_icon()
        tk.Label(
            inner, text=title, bg=bg, fg=P["text"],
            font=("Microsoft YaHei UI", 18, "bold"),
        ).pack(pady=(14, 0))
        if description:
            tk.Label(
                inner, text=description, bg=bg, fg=P["muted"],
                font=("Microsoft YaHei UI", 13), wraplength=max_width,
                justify="left",
            ).pack(pady=(8, 0))
        if action_text and command:
            ttk.Button(
                inner, text=action_text, style="Accent.TButton", command=command,
            ).pack(pady=(16, 0))

    def _draw_icon(self):
        P = PALETTE
        c = self._icon
        color = P["primary"]
        soft = P["primary_light"]
        # 收纳/文档示意：开口容器 + 内容线，不使用 emoji，避免字体渲染差异
        c.create_rectangle(12, 10, 64, 54, outline=color, width=2,
                           fill=soft, tags="empty_icon")
        c.create_line(12, 10, 26, 28, 64, 10, fill=color, width=2)
        c.create_line(19, 40, 57, 40, fill=color, width=2)
        c.create_line(19, 48, 48, 48, fill=color, width=2)

    def place_in(self, parent, rely=0.45):
        """把空状态居中显示在 parent 上。"""
        self.place(relx=0.5, rely=rely, anchor="center")
        return self


def show_image_zoom(master, path):
    """双击图片放大查看：新窗口居中显示，Esc / 按钮关闭。"""
    from PIL import Image, ImageTk
    try:
        img = Image.open(path)
    except Exception:
        return None
    top = tk.Toplevel(master)
    top.title("图片查看")
    top.configure(bg=PALETTE["bg"])
    max_w = min(900, top.winfo_screenwidth() - 120)
    max_h = min(700, top.winfo_screenheight() - 160)
    img.thumbnail((max_w, max_h))
    tk_img = ImageTk.PhotoImage(img)
    lbl = tk.Label(top, image=tk_img, bg=PALETTE["bg"])
    lbl.image = tk_img
    lbl.pack(padx=12, pady=(12, 4))
    tk.Label(top, text="按 Esc 关闭", bg=PALETTE["bg"], fg=PALETTE["muted"],
             font=("Microsoft YaHei UI", 11)).pack()
    ttk.Button(top, text="关闭", command=top.destroy).pack(pady=(6, 12))
    top.bind("<Escape>", lambda e: top.destroy())
    top.resizable(False, False)
    center_window(top)
    return top


class TextCheck(tk.Frame):
    """文本式勾选：☐ 未选 / √ 已选，点击文字或符号切换（避免主题把勾渲染成 ×）。"""

    def __init__(self, master, text, variable=None, command=None, bg=None, font=None):
        bg = bg or PALETTE["card"]
        super().__init__(master, bg=bg)
        self.var = variable if variable is not None else tk.BooleanVar()
        self.command = command
        self._ind = tk.Label(self, text="☐", bg=bg, fg=PALETTE["muted"],
                             font=("Microsoft YaHei UI", 15, "bold"), cursor="hand2")
        self._ind.pack(side="left")
        self._lbl = tk.Label(self, text=text, bg=bg, fg=PALETTE["text"],
                             font=font or ("Microsoft YaHei UI", 13), cursor="hand2")
        self._lbl.pack(side="left", padx=(2, 0))
        self._ind.bind("<Button-1>", lambda e: self._toggle())
        self._lbl.bind("<Button-1>", lambda e: self._toggle())
        self._sync()

    def _toggle(self):
        self.var.set(not self.var.get())
        self._sync()
        if self.command:
            self.command()

    def _sync(self):
        if self.var.get():
            self._ind.configure(text="√", fg=PALETTE["accent"])
        else:
            self._ind.configure(text="☐", fg=PALETTE["muted"])

    def get(self):
        return self.var.get()

    def set(self, value):
        self.var.set(value)
        self._sync()


class TimePicker(tk.Frame):
    """时间选择：☐/√ 提醒 + 时/分 微调框（到分钟）。get() 返回 HH:MM 或 None。"""

    def __init__(self, master, initial=None, bg=None):
        bg = bg or PALETTE["card"]
        super().__init__(master, bg=bg)
        enabled = bool(initial)
        if not enabled:
            initial = "08:00"
        self.enabled_var = tk.BooleanVar(value=enabled)
        self.cb = TextCheck(self, "提醒", variable=self.enabled_var,
                            command=self._sync, bg=bg)
        self.cb.pack(side="left")
        self.hour = ttk.Spinbox(self, from_=0, to=23, width=3, format="%02.0f", wrap=True)
        self.hour.set(initial[:2])
        self.hour.pack(side="left", padx=(4, 0))
        ttk.Label(self, text=":", background=bg).pack(side="left")
        self.minute = ttk.Spinbox(self, from_=0, to=59, width=3, format="%02.0f", wrap=True)
        self.minute.set(initial[3:5])
        self.minute.pack(side="left")
        self._sync()

    def _sync(self):
        state = "normal" if self.enabled_var.get() else "disabled"
        self.hour.configure(state=state)
        self.minute.configure(state=state)

    def get(self):
        """返回 HH:MM；未启用提醒返回 None；值非法时抛 ValueError。"""
        if not self.enabled_var.get():
            return None
        try:
            h = int(self.hour.get())
            m = int(self.minute.get())
        except (ValueError, TypeError):
            raise ValueError("提醒时间格式应为 HH:MM")
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError("提醒时间格式应为 HH:MM")
        return "{:02d}:{:02d}".format(h, m)

    def set(self, value):
        if value:
            self.enabled_var.set(True)
            self.hour.set(value[:2])
            self.minute.set(value[3:5])
        else:
            self.enabled_var.set(False)
        self._sync()
