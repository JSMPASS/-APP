# -*- coding: utf-8 -*-
"""从系统剪贴板读取图片/文本，供各输入框通过 Ctrl+V 直接粘贴使用。"""
from __future__ import annotations

import os
import re
import tempfile
import tkinter as tk
from pathlib import Path

_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff")
_TEMP_PREFIX = "habit_clipboard_"
_IMAGE_ATTR_RE = re.compile(r"""image\s*=\s*['"]([^'"]+)['"]""", re.I)
_IMG_SRC_RE = re.compile(r"""<img\s+[^>]*src\s*=\s*['"]([^'"]+)['"]""", re.I)


def _new_temp_png():
    fd, path = tempfile.mkstemp(prefix=_TEMP_PREFIX, suffix=".png")
    os.close(fd)
    return path


def is_image_path(path):
    p = Path(os.fspath(path))
    return p.is_file() and p.suffix.lower() in _IMAGE_EXTS


def extract_content_image_paths(html):
    """从轻量 HTML 正文提取图片相对路径列表（供数据层清理孤儿文件）。"""
    out = [m.group(1) for m in _IMAGE_ATTR_RE.finditer(html or "")]
    out.extend(m.group(1) for m in _IMG_SRC_RE.finditer(html or ""))
    return out


def paste_clipboard_images():
    """读取剪贴板图片，返回 (图片路径列表, 本次创建的临时文件路径列表)。"""
    try:
        from PIL import ImageGrab
        data = ImageGrab.grabclipboard()
    except Exception:
        return [], []
    if data is None:
        return [], []
    if isinstance(data, list):
        return [os.fspath(p) for p in data if is_image_path(p)], []
    if isinstance(data, (str, os.PathLike)):
        p = os.fspath(data)
        return ([p] if is_image_path(p) else []), []
    if hasattr(data, "save"):
        path = _new_temp_png()
        try:
            data.save(path, "PNG")
            return [path], [path]
        except Exception:
            cleanup_temp_files([path])
            return [], []
    return [], []


def get_clipboard_image_object():
    """读取系统剪贴板图片，返回 PIL Image 对象；无图片时返回 None。"""
    try:
        from PIL import Image, ImageGrab
        data = ImageGrab.grabclipboard()
    except Exception:
        return None
    if data is None:
        return None
    if isinstance(data, list):
        for p in data:
            if is_image_path(p):
                try:
                    return Image.open(os.fspath(p))
                except Exception:
                    continue
        return None
    if isinstance(data, (str, os.PathLike)):
        p = os.fspath(data)
        if is_image_path(p):
            try:
                return Image.open(p)
            except Exception:
                return None
        return None
    if hasattr(data, "save"):
        try:
            return data
        except Exception:
            return None
    return None


def paste_clipboard_text(widget=None):
    """读取系统剪贴板文本；剪贴板没有文本时返回空字符串。"""
    try:
        if widget is not None:
            return widget.clipboard_get()
        root = tk._default_root
        if root is None:
            return ""
        return root.clipboard_get()
    except Exception:
        return ""


def bind_text_paste(widget):
    """给文本输入框绑定 Ctrl+V：有文本时粘贴到光标处，无文本时交还默认/图片逻辑。

    返回处理函数，便于测试或按需解绑。
    """
    def _on_paste(event=None):
        text = paste_clipboard_text(widget)
        if not text:
            return None
        try:
            widget.delete("sel.first", "sel.last")
        except tk.TclError:
            pass
        widget.insert("insert", text)
        return "break"

    widget.bind("<Control-v>", _on_paste)
    return _on_paste


class _EntryUndo:
    """单行输入框的撤销历史：记录每次内容变化，Ctrl+Z 逐次回退。"""

    __slots__ = ("widget", "stack", "max_depth")

    def __init__(self, widget, max_depth=100):
        self.widget = widget
        self.stack = [widget.get()]
        self.max_depth = max(1, int(max_depth))

    def record(self, event=None):
        current = self.widget.get()
        if not self.stack or self.stack[-1] != current:
            self.stack.append(current)
            if len(self.stack) > self.max_depth + 1:
                del self.stack[:len(self.stack) - self.max_depth - 1]
        return None

    def undo(self, event=None):
        if len(self.stack) > 1:
            self.stack.pop()
            self.widget.delete(0, "end")
            self.widget.insert(0, self.stack[-1])
        return "break"

    def reset(self):
        """覆盖内容后重置撤销栈，避免 Ctrl+Z 回到旧内容或占位文本。"""
        self.stack.clear()
        self.stack.append(self.widget.get())


def bind_entry_undo(widget, max_depth=100):
    """给单行输入框增加 Ctrl+Z 撤回（键盘键入/粘贴后逐次回退）。

    无内置 undo 的 Entry 使用内容快照。绑定对象保存在 widget._habit_undo，
    需要时可通过 reset() 在程序化改值后重建初始快照。
    """
    undo = _EntryUndo(widget, max_depth=max_depth)
    widget._habit_undo = undo
    widget.bind("<KeyRelease>", undo.record, add="+")
    widget.bind("<<Paste>>", lambda e: widget.after_idle(undo.record), add="+")
    widget.bind("<<Cut>>", lambda e: widget.after_idle(undo.record), add="+")
    widget.bind("<<Delete>>", lambda e: widget.after_idle(undo.record), add="+")
    widget.bind("<Control-z>", undo.undo, add="+")
    return undo


def cleanup_temp_files(paths):
    """只清理本模块创建的剪贴板临时图片，避免误删用户文件。"""
    tmp_dir = Path(tempfile.gettempdir()).resolve()
    for p in paths or []:
        try:
            path = Path(p).resolve()
        except OSError:
            continue
        if path.name.startswith(_TEMP_PREFIX) and path.parent == tmp_dir:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
