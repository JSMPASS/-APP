"""轻量动画工具：颜色插值、弹窗淡入、进度平滑、上滑、右上角 toast。"""
from __future__ import annotations

import tkinter as tk


def hex_to_rgb(color):
    color = (color or "#000000").lstrip("#")
    if len(color) == 3:
        color = "".join(c * 2 for c in color)
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def rgb_to_hex(r, g, b):
    return "#{:02X}{:02X}{:02X}".format(
        max(0, min(255, int(r))), max(0, min(255, int(g))), max(0, min(255, int(b)))
    )


def lerp_color(c1, c2, t):
    """两个 #RRGGBB 颜色之间线性插值，t 属于 [0,1]。"""
    r1, g1, b1 = hex_to_rgb(c1)
    r2, g2, b2 = hex_to_rgb(c2)
    return rgb_to_hex(r1 + (r2 - r1) * t, g1 + (g2 - g1) * t, b1 + (b2 - b1) * t)


def fade_in(widget, ms=130, steps=12):
    """让 Toplevel 窗口淡入（alpha 0 -> 1）。"""
    try:
        if not isinstance(widget, tk.Toplevel) or not widget.winfo_exists():
            return
        widget.attributes("-alpha", 0.0)
    except tk.TclError:
        return

    def _step(i):
        try:
            if not widget.winfo_exists():
                return
            widget.attributes("-alpha", i / steps)
            if i < steps:
                widget.after(ms // steps, lambda: _step(i + 1))
        except tk.TclError:
            pass

    _step(1)


def smooth_progress(bar, target, ms=220, steps=16):
    """进度条值平滑滚动到 target。"""
    try:
        cur = float(bar["value"])
        maxv = float(bar["maximum"] or 1)
    except (tk.TclError, ValueError):
        return
    target = float(min(target, maxv))

    def _step(i):
        try:
            bar["value"] = cur + (target - cur) * (i / steps)
            if i < steps:
                bar.after(ms // steps, lambda: _step(i + 1))
        except tk.TclError:
            pass

    _step(1)


def count_up(label, target, suffix="", ms=600, steps=20):
    """让 Label 的数字从当前值平滑滚动到 target（ease-out）。"""
    try:
        cur_text = label.cget("text")
        cur = int("".join(ch for ch in cur_text if ch.isdigit()) or 0)
    except (tk.TclError, ValueError):
        cur = 0
    target = int(target)
    if cur == target:
        label.configure(text="{}{}".format(target, suffix))
        return

    def _step(i):
        try:
            if not label.winfo_exists():
                return
        except tk.TclError:
            return
        t = i / steps
        eased = 1 - (1 - t) ** 3
        val = int(round(cur + (target - cur) * eased))
        label.configure(text="{}{}".format(val, suffix))
        if i < steps:
            label.after(ms // steps, lambda: _step(i + 1))

    _step(0)


def slide_in(toplevel, dy=20, ms=150, steps=10):
    """弹窗轻微上滑 + 淡入（适合成功/提醒类小弹窗）。"""
    try:
        if not isinstance(toplevel, tk.Toplevel) or not toplevel.winfo_exists():
            return
        geo = toplevel.geometry().split("+")
        size = geo[0]
        x, y = int(geo[1]), int(geo[2])
        toplevel.geometry("+{}+{}".format(x, y + dy))
        toplevel.attributes("-alpha", 0.0)
    except (tk.TclError, ValueError, IndexError):
        fade_in(toplevel, ms=ms)
        return

    def _step(i):
        try:
            if not toplevel.winfo_exists():
                return
            toplevel.attributes("-alpha", i / steps)
            toplevel.geometry("+{}+{}".format(x, y + int(dy * (1 - i / steps))))
            if i < steps:
                toplevel.after(ms // steps, lambda: _step(i + 1))
        except tk.TclError:
            pass

    _step(1)


def toast(master, text, ms=2000, bg="#1F2937", fg="#FFFFFF"):
    """主窗口右上角轻量提示，自动淡入淡出消失。"""
    try:
        root = master.winfo_toplevel()
    except tk.TclError:
        return None
    top = tk.Toplevel(root)
    top.overrideredirect(True)
    top.attributes("-topmost", True)
    lbl = tk.Label(top, text=text, bg=bg, fg=fg, font=("Microsoft YaHei UI", 13),
                   padx=16, pady=10)
    lbl.pack()
    top.update_idletasks()
    w = top.winfo_reqwidth()
    h = top.winfo_reqheight()
    x = root.winfo_rootx() + root.winfo_width() - w - 24
    y = root.winfo_rooty() + 18
    top.geometry("+{}+{}".format(max(x, 0), y))
    top.attributes("-alpha", 0.0)

    def _fade(a):
        try:
            if not top.winfo_exists():
                return
            top.attributes("-alpha", a)
            if a < 1:
                top.after(15, lambda: _fade(min(1, a + 0.12)))
        except tk.TclError:
            pass

    def _close():
        try:
            if top.winfo_exists():
                top.destroy()
        except tk.TclError:
            pass

    _fade(0.0)
    top.after(ms, _close)
    return top
