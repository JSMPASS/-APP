"""知识库富文本：轻量 HTML 子集 ↔ tk.Text 双向转换，以及统一编辑/预览弹窗。

段落属性：align（left/center/right）、spacing（single/wide/double）、
indent（首行缩进汉字数，默认 2）、bg（段落背景色）。
图片段落用 <p image='相对路径'> 保存，编辑与预览时以嵌入式图片渲染。
旧数据中的无属性 <p> 仍然兼容。
"""
from __future__ import annotations

import math
import re
import tkinter as tk
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from tkinter import colorchooser, filedialog, font as tkfont, messagebox, ttk

from habit_checkin.services.clipboard_utils import (
    bind_entry_undo,
    bind_text_paste,
    cleanup_temp_files,
    extract_content_image_paths,
    get_clipboard_image_object,
    paste_clipboard_images,
    paste_clipboard_text,
)
from habit_checkin.ui.animate import fade_in
from habit_checkin.ui.common import ScrollableFrame, center_window, setup_styles
from habit_checkin.ui.theme import PALETTE, dialog_header, is_dark

_FONT_FAMILY = "Microsoft YaHei UI"
_SIZE_CHOICES = (10, 12, 14, 16, 18)
_SIZE_TAG_RE = re.compile(r"^(?:bold)?size(\d+)$")
_SPACING_PX = {"single": 4, "wide": 12, "double": 24}
_SPACING_LABELS = {"single": "单倍行距", "wide": "1.5 倍行距", "double": "双倍行距"}
_ALIGN_LABELS = {"left": "左对齐", "center": "居中", "right": "右对齐"}
_BG_TAG_RE = re.compile(r"^bg_(#[0-9a-fA-F]{6})$")
_BG_COLORS = ("#FFF3CD", "#E8F0FE", "#E7F6EC", "#FDEAEA", "#EEF1F5", "#FFFFFF")
_DEFAULT_INDENT = 2
_LIST_NUM_RE = re.compile(r"^\d+\.")
_LIST_PREFIX_RE = re.compile(r"^(?:\d+\.|[①-⑳])")
_LIST_NUM_TAG = "listnum"
_CIRCLED_NUMS = tuple("①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳")
_MAX_EDIT_IMAGE_W = 520
_MAX_EDIT_IMAGE_H = 380
_MAX_VIEW_IMAGE_W = 560
_MAX_VIEW_IMAGE_H = 420
_MAX_PREVIEW_W = 300
_MAX_PREVIEW_H = 190
_IMAGE_TYPES = [
    ("图片", "*.png *.jpg *.jpeg *.webp *.bmp *.gif *.tif *.tiff"),
    ("所有文件", "*.*"),
]
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff")


def _list_style_key(value):
    """把 list 属性规范成内部值：True/1 表示数字序号，circle 表示圈号。"""
    if value == "circle":
        return "circle"
    return True if value else False


def _format_list_prefix(num, style):
    """生成序号前缀文本；圈号超过 20 时回退为数字序号。"""
    if style == "circle" and 1 <= num <= len(_CIRCLED_NUMS):
        return _CIRCLED_NUMS[num - 1]
    return "{}.".format(num)


def _prefix_number(text, style):
    """从序号前缀解析出数字；圈号无法解析时回退为数字序号。"""
    if style == "circle" and text:
        try:
            return _CIRCLED_NUMS.index(text[0]) + 1
        except ValueError:
            pass
    m = _LIST_NUM_RE.match(text)
    return int(m.group(0)[:-1]) if m else None


def plain_to_html(text):
    """把普通文本段落转为轻量 HTML。"""
    out = []
    for line in (text or "").splitlines():
        t = line.strip()
        if t:
            out.append("<p>{}</p>".format(escape(t)))
    return "\n".join(out)


def html_to_plain(html):
    """去掉轻量 HTML 标签并反转义，得到纯文本（用于搜索/摘要）。"""
    if not html:
        return ""
    parts = []
    try:
        blocks = parse_rich_html(html)
    except Exception:
        return re.sub(r"<[^>]+>", "", html).replace("&amp;", "&").replace("&lt;", "<") \
            .replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'")
    for blk in blocks:
        parts.append("[图片]" if blk.get("image") else blk.get("text", ""))
    return "\n".join(parts).strip()


def content_image_paths(html):
    """从轻量 HTML 中提取图片相对路径列表（用于清理/统计）。"""
    return extract_content_image_paths(html)


def looks_like_html(value):
    """判断一段既有内容是否为轻量 HTML（用于旧纯文本数据兼容）。"""
    text = (value or "").lstrip()
    return text.startswith("<p") or text.startswith("<P")


def to_plain(value):
    """把既有内容安全转成纯文本：HTML 去掉标签，纯文本原样返回。"""
    if not value:
        return ""
    return html_to_plain(value) if looks_like_html(value) else str(value)


def _theme_bg(hex_color):
    """把预设背景色映射为当前主题语义色；自定义色原样返回。"""
    if is_dark():
        return {
            "#FFF3CD": "#3A3016",
            "#E8F0FE": "#17273F",
            "#E7F6EC": "#17321F",
            "#FDEAEA": "#3A1B1D",
            "#EEF1F5": "#262E39",
            "#FFFFFF": "#141A22",
        }.get((hex_color or "").upper(), hex_color)
    return {
        "#3A3016": "#FFF3CD",
        "#17273F": "#E8F0FE",
        "#17321F": "#E7F6EC",
        "#3A1B1D": "#FDEAEA",
        "#262E39": "#EEF1F5",
        "#141A22": "#FFFFFF",
    }.get((hex_color or "").upper(), hex_color)


class _HtmlCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.blocks = []
        self._cur = None
        self._buf = []

    def handle_starttag(self, tag, attrs):
        if tag == "p":
            if self._cur is not None:
                self._flush()
            a = dict(attrs)
            self._cur = {
                "b": False, "red": False, "size": None, "text": "",
                "align": (a.get("align") or "center" if a.get("image") else a.get("align") or "left"),
                "spacing": a.get("spacing") or "single",
                "indent": int(a["indent"]) if str(a.get("indent", "")).isdigit() else _DEFAULT_INDENT,
                "bg": a.get("bg") or None,
                "image": a.get("image") or None,
                "list": _list_style_key(a.get("list")),
            }
        elif tag == "img":
            a = dict(attrs)
            src = a.get("src") or a.get("image") or ""
            if self._cur is not None:
                self._cur["image"] = src or self._cur.get("image")
            else:
                self._flush()
                self._cur = {
                    "b": False, "red": False, "size": None, "text": "",
                    "align": "center", "spacing": "single",
                    "indent": 0, "bg": None, "image": src, "list": False,
                }
        elif tag == "b":
            if self._cur is not None:
                self._cur["b"] = True
        elif tag == "red":
            if self._cur is not None:
                self._cur["red"] = True
        elif tag == "size":
            attrs = dict(attrs)
            val = attrs.get("value", "")
            if self._cur is not None:
                self._cur["size"] = int(val) if val.isdigit() else None

    def handle_endtag(self, tag):
        if tag == "p":
            self._flush()

    def handle_data(self, data):
        if self._cur is not None:
            self._cur["text"] += data

    def _flush(self):
        if self._cur is not None:
            self.blocks.append(dict(self._cur))
        self._cur = None

    def close(self):
        super().close()
        self._flush()


def parse_rich_html(html):
    """解析轻量 HTML 为段落块（含段落属性，旧数据自动补默认值）。"""
    parser = _HtmlCollector()
    parser.feed(html or "")
    parser.close()
    return parser.blocks


def blocks_to_html(blocks):
    """把段落块序列转为轻量 HTML 字符串（含段落属性）。"""
    out = []
    for blk in blocks:
        image = blk.get("image")
        if image:
            attrs = ["image='{}'".format(escape(image, quote=True))]
            align = blk.get("align") or "center"
            if align in _ALIGN_LABELS and align != "left":
                attrs.append("align='{}'".format(align))
            if blk.get("list"):
                attrs.append("list='circle'" if blk.get("list") == "circle" else "list='1'")
            out.append("<p{}></p>".format(" " + " ".join(attrs)))
            continue
        text = escape(blk.get("text", ""))
        if blk.get("b"):
            text = "<b>{}</b>".format(text)
        if blk.get("red"):
            text = "<red>{}</red>".format(text)
        if blk.get("size"):
            text = "<size value='{}'>{}</size>".format(blk["size"], text)
        attrs = []
        align = blk.get("align") or "left"
        if align in _ALIGN_LABELS and align != "left":
            attrs.append("align='{}'".format(align))
        spacing = blk.get("spacing") or "single"
        if spacing in _SPACING_PX and spacing != "single":
            attrs.append("spacing='{}'".format(spacing))
        indent = int(blk.get("indent") or 0)
        # 显式写入 0/缩进值，避免“无缩进”被重新解析成默认两字缩进
        attrs.append("indent='{}'".format(indent))
        bg = blk.get("bg")
        if bg:
            attrs.append("bg='{}'".format(bg))
        if blk.get("list"):
            attrs.append("list='circle'" if blk.get("list") == "circle" else "list='1'")
        attr_str = (" " + " ".join(attrs)) if attrs else ""
        out.append("<p{}>{}</p>".format(attr_str, text))
    return "\n".join(out)


def _block_tags(blk):
    """返回段落块对应的 tk.Text tag 列表。"""
    tags = []
    if blk.get("b"):
        size = blk.get("size") or 13
        if size in _SIZE_CHOICES:
            tags.append("boldsize{}".format(size))
        else:
            tags.append("bold")
    elif blk.get("size") in _SIZE_CHOICES:
        tags.append("size{}".format(blk["size"]))
    if blk.get("red"):
        tags.append("red")
    align = blk.get("align") or "left"
    if align in _ALIGN_LABELS and align != "left":
        tags.append("align{}".format(align))
    spacing = blk.get("spacing") or "single"
    if spacing in _SPACING_PX and spacing != "single":
        tags.append("line{}".format(spacing))
    indent = int(blk.get("indent") or 0)
    if indent:
        tags.append("indent{}".format(indent))
    bg = blk.get("bg")
    if bg:
        tags.append("bg_{}".format(bg))
    if blk.get("list"):
        tags.append("list")
        if blk.get("list") == "circle":
            tags.append("listcircle")
    return tags


def _indent_px(chars):
    """把首行缩进的汉字位数换算为像素（按当前正文字号估算）。"""
    return int(13 * 2 * chars)


def _tag_align(tags):
    for name in ("left", "center", "right"):
        if "align{}".format(name) in tags:
            return name
    return "left"


def _tag_spacing(tags):
    for name in ("single", "wide", "double"):
        if "line{}".format(name) in tags:
            return name
    return "single"


def _tag_indent(tags):
    for t in tags:
        m = re.match(r"^indent(\d+)$", t)
        if m:
            return int(m.group(1))
    return 0


def _tag_bg(tags):
    for t in tags:
        m = _BG_TAG_RE.match(t)
        if m:
            return m.group(1)
    return None


def _ensure_bg_tag(text, color):
    """为任意合法的十六进制背景色配置 tk.Text tag。"""
    if not color:
        return
    try:
        text.tag_configure("bg_{}".format(color), background=_theme_bg(color))
    except tk.TclError:
        pass


def _load_photo(path, max_w, max_h):
    """加载图片并缩放到显示上限；文件异常时生成灰色占位图。"""
    from PIL import Image, ImageTk
    try:
        img = Image.open(path)
        img.thumbnail((max_w, max_h), Image.LANCZOS)
    except Exception:
        img = Image.new("RGB", (240, 140), "#C9D3E0")
    return ImageTk.PhotoImage(img)


def _text_required_height(text, photos=None):
    """按 Text 当前宽度计算完整展示内容所需的像素高度（含嵌入式图片）。"""
    counted = text.count("1.0", "end", "displaylines")
    total_lines = int(counted[0]) if counted else 0
    try:
        line_h = tkfont.Font(font=text.cget("font")).metrics("linespace")
    except (tk.TclError, TypeError, ValueError):
        line_h = 0
    if line_h <= 0:
        line_h = 24

    images = photos or getattr(text, "_image_photos", [])
    if not images:
        return max(1, total_lines) * line_h

    # 每个图片占一行显示位，另按图片像素高度展开，避免图片被 Text 裁切
    text_lines = max(0, total_lines - len(images))
    return text_lines * line_h + sum(
        int(getattr(img, "height", lambda: 0)()) + 10 for img in images
    )


class ImageInsertDialog(tk.Toplevel):
    """图片插入窗口：支持选择本地图片或直接粘贴剪贴板图片。"""

    def __init__(self, master, image_store):
        super().__init__(master)
        self._store = image_store
        self.result = None
        self._preview_ref = None
        self._preview_pil = None
        self._preview_source = None
        self._preview_paths = []
        self._clipboard_tmp = []
        self._preview_label = None
        self._info_label = None
        self._insert_btn = None

        self.title("插入图片")
        self.geometry("520x452")
        self.minsize(440, 380)
        self.transient(master)
        setup_styles(self)
        self.configure(bg=PALETTE["bg"])
        dialog_header(self, "插入图片", "图片会复制到本地数据目录再插入正文",
                      title_size=14, subtitle_size=9)
        self._build()
        center_window(self)
        fade_in(self)
        self.grab_set()

    def _build(self):
        P = PALETTE
        body = tk.Frame(self, bg=P["bg"], padx=14, pady=10)
        body.pack(fill="both", expand=True)

        actions = tk.Frame(body, bg=P["bg"])
        actions.pack(fill="x", pady=(0, 8))
        ttk.Button(actions, text="选择图片文件", command=self._pick_file).pack(side="left")
        ttk.Button(actions, text="粘贴剪贴板图片", command=self._paste_clipboard
                   ).pack(side="left", padx=8)

        preview = tk.Frame(body, bg=P["surface"], highlightthickness=1,
                           highlightbackground=P["border"])
        preview.pack(fill="both", expand=True)
        preview.pack_propagate(False)
        self._preview_label = tk.Label(
            preview, text="预览区\n\n选择图片文件，或先复制图片到剪贴板再粘贴",
            bg=P["surface"], fg=P["faint"], font=("Microsoft YaHei UI", 11),
            justify="center",
        )
        self._preview_label.pack(fill="both", expand=True)

        self._info_label = tk.Label(
            body, text="", bg=P["bg"], fg=P["muted"],
            font=("Microsoft YaHei UI", 11), anchor="w",
        )
        self._info_label.pack(fill="x", pady=(8, 0))

        bottom = tk.Frame(self, bg=P["bg"], padx=14, pady=10)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="取消", command=self.destroy).pack(side="right")
        self._insert_btn = ttk.Button(
            bottom, text="插入", style="Accent.TButton",
            command=self._insert, state="disabled",
        )
        self._insert_btn.pack(side="right", padx=8)
        self.bind("<Escape>", lambda e: self.destroy())

    def _pick_file(self):
        paths = filedialog.askopenfilenames(parent=self, filetypes=_IMAGE_TYPES, title="选择图片")
        picked = [p for p in paths if p.lower().endswith(_IMAGE_EXTS)]
        if not picked:
            return
        self._preview_paths = picked
        self._set_preview_image(picked[0], len(picked))

    def _paste_clipboard(self):
        paths, tmp = paste_clipboard_images()
        self._clipboard_tmp.extend(tmp)
        img = get_clipboard_image_object()
        if img is not None:
            self._preview_pil = img
            self._preview_source = None
            self._preview_paths = paths if len(paths) > 1 else []
            self._preview_label.configure(image="", text="")
            self._render_pil(img)
            if len(paths) > 1:
                self._info_label.configure(text="已选 {} 张图片，将依次插入".format(len(paths)))
        elif paths:
            self._preview_paths = paths
            self._set_preview_image(paths[0], len(paths))
        else:
            self._set_no_preview("剪贴板中没有可用的图片。")

    def _set_no_preview(self, message):
        self._preview_pil = None
        self._preview_source = None
        self._preview_paths = []
        self._preview_ref = None
        self._preview_label.configure(text=message, image="",
                                      bg=PALETTE["surface"], fg=PALETTE["faint"])
        self._info_label.configure(text="")
        if self._insert_btn:
            self._insert_btn.configure(state="disabled")

    def _render_pil(self, image):
        from PIL import Image, ImageTk
        working = image.convert("RGB") if image.mode not in ("RGB", "RGBA", "L") else image
        working.thumbnail((460, 250), Image.LANCZOS)
        photo = ImageTk.PhotoImage(working)
        self._preview_ref = photo
        self._preview_label.configure(image=photo, text="", bg=PALETTE["surface"])
        w, h = working.size
        self._info_label.configure(text="已选 1 张图片 · 预览尺寸 {}×{}".format(w, h))
        if self._insert_btn:
            self._insert_btn.configure(state="normal")

    def _set_preview_pil(self, image):
        self._preview_pil = image
        self._preview_source = None
        self._preview_label.configure(image="", text="")
        self._render_pil(image)

    def _set_preview_image(self, path, count):
        try:
            from PIL import Image
            self._preview_pil = None
            self._preview_source = path
            image = Image.open(path)
            self._render_pil(image)
            if count > 1:
                self._info_label.configure(text="已选 {} 张图片，将依次插入".format(count))
        except Exception as exc:
            self._set_no_preview("图片加载失败：{}".format(exc))

    def _insert(self):
        if self._preview_paths:
            try:
                rels = [self._store(p) for p in self._preview_paths]
            except Exception as exc:
                messagebox.showerror("插入失败", "图片保存失败：{}\n请重试。".format(exc), parent=self)
                return
            self.result = {"rels": rels, "count": len(rels)}
        elif self._preview_source:
            try:
                rel = self._store(self._preview_source)
            except Exception as exc:
                messagebox.showerror("插入失败", "图片保存失败：{}\n请重试。".format(exc), parent=self)
                return
            self.result = {"rels": [rel], "count": 1}
        elif self._preview_pil is not None:
            try:
                rel = self._store(self._preview_pil)
            except Exception as exc:
                messagebox.showerror("插入失败", "图片保存失败：{}\n请重试。".format(exc), parent=self)
                return
            self.result = {"rels": [rel], "count": 1}
        else:
            messagebox.showinfo("提示", "请先选择或粘贴一张图片。", parent=self)
            return
        self.destroy()

    def destroy(self):
        cleanup_temp_files(self._clipboard_tmp)
        super().destroy()


class RichTextArea(tk.Text):
    """带富文本标记的 Text：支持加粗、标红、字号与嵌入式图片，保存为轻量 HTML。"""

    def __init__(self, master, height=10, image_resolver=None, image_store=None, **kw):
        P = PALETTE
        super().__init__(
            master, height=height, wrap="word", undo=True,
            font=(_FONT_FAMILY, 13), bg=P["input"], fg=P["text"],
            relief="flat", highlightthickness=1,
            highlightbackground=P["border"], highlightcolor=P["focus"],
            insertbackground=P["text"], **kw,
        )
        self.configure(background=P["input"], foreground=P["text"])
        self._configure_tags()
        self.image_resolver = image_resolver
        self.image_store = image_store
        self._image_photos = []
        self._image_rel = {}
        self.bind("<Control-v>", self._on_paste)
        self.bind("<Control-z>", self._undo_text)

    def _undo_text(self, event=None):
        """Ctrl+Z：回退一次编辑操作；没有可回退内容时保持原状。"""
        try:
            self.edit_undo()
        except tk.TclError:
            pass
        return "break"

    def _on_paste(self, event=None):
        text = paste_clipboard_text(self)
        if text:
            try:
                self.delete("sel.first", "sel.last")
            except tk.TclError:
                pass
            self.insert("insert", text)
            return "break"
        if self.image_store is not None:
            if self._paste_clipboard_image():
                return "break"
        return None

    def _paste_clipboard_image(self):
        """剪贴板有图片时直接入库并插入到光标处。"""
        img = get_clipboard_image_object()
        if img is None:
            return False
        rel = self.image_store(img)
        if rel:
            self.insert_image(rel)
            return True
        return False

    def _clear_images(self):
        self._image_photos.clear()
        self._image_rel.clear()

    def _image_abs(self, rel):
        for cb in (getattr(self, "image_resolver", None), getattr(self, "image_store", None)):
            if cb is None:
                continue
            try:
                value = cb(rel)
            except Exception:
                continue
            if isinstance(value, (str, Path)):
                return str(value)
        return None

    def _make_image(self, rel):
        abs_path = self._image_abs(rel)
        photo = _load_photo(abs_path or rel, _MAX_EDIT_IMAGE_W, _MAX_EDIT_IMAGE_H)
        self._image_photos.append(photo)
        self._image_rel[str(photo)] = rel
        return photo

    def _configure_tags(self):
        P = PALETTE
        self.tag_configure("bold", font=(_FONT_FAMILY, 13, "bold"))
        self.tag_configure("red", foreground=P["danger"])
        self.tag_configure("listnum", foreground=P["muted"])
        self.tag_configure("alignleft", justify="left")
        self.tag_configure("aligncenter", justify="center")
        self.tag_configure("alignright", justify="right")
        self.tag_configure("linesingle", spacing1=0, spacing3=4)
        self.tag_configure("linewide", spacing1=4, spacing3=12)
        self.tag_configure("linedouble", spacing1=10, spacing3=24)
        self.tag_configure("list", lmargin1=_indent_px(3), lmargin2=_indent_px(1))
        for n in (2, 4):
            self.tag_configure("indent{}".format(n), lmargin1=_indent_px(n), lmargin2=0)
        for hex_color in _BG_COLORS:
            self.tag_configure("bg_{}".format(hex_color), background=_theme_bg(hex_color))
        for size in _SIZE_CHOICES:
            self.tag_configure("size{}".format(size), font=(_FONT_FAMILY, size))
        self.tag_configure("boldsize10", font=(_FONT_FAMILY, 10, "bold"))
        self.tag_configure("boldsize12", font=(_FONT_FAMILY, 12, "bold"))
        self.tag_configure("boldsize14", font=(_FONT_FAMILY, 14, "bold"))
        self.tag_configure("boldsize16", font=(_FONT_FAMILY, 16, "bold"))
        self.tag_configure("boldsize18", font=(_FONT_FAMILY, 18, "bold"))

    def _line_span_for_selection(self):
        """返回选中内容所在整行（段落）的起止索引；无选中时用光标行。"""
        try:
            ranges = self.tag_ranges("sel")
        except tk.TclError:
            ranges = ()
        if ranges:
            start, end = self.index(ranges[0]), self.index(ranges[-1])
        else:
            start = end = self.index("insert")
        line_start = self.index("{}.0".format(start.split(".")[0]))
        next_line = self.index("{}.0".format(int(end.split(".")[0]) + 1))
        line_end = next_line if end == self.index("{}.0".format(end.split(".")[0])) \
            else self.index("{}.0 lineend +1c".format(end.split(".")[0]))
        return line_start, line_end

    def apply_paragraph_format(self, align=None, spacing=None, indent=None, bg=None):
        """把段落格式应用到当前选中行（无选中时应用到光标所在行）。"""
        start, end = self._line_span_for_selection()
        if align in _ALIGN_LABELS:
            for name in _ALIGN_LABELS:
                self.tag_remove("align{}".format(name), start, end)
            self.tag_add("align{}".format(align), start, end)
        if spacing in _SPACING_PX:
            for name in _SPACING_PX:
                self.tag_remove("line{}".format(name), start, end)
            self.tag_add("line{}".format(spacing), start, end)
        if indent is not None:
            for n in (2, 4):
                self.tag_remove("indent{}".format(n), start, end)
            if indent in (2, 4):
                self.tag_add("indent{}".format(indent), start, end)
        if bg is not None:
            self.tag_remove("bg_#FFFFFF", start, end)
            for hex_color in _BG_COLORS:
                self.tag_remove("bg_{}".format(hex_color), start, end)
            if bg:
                _ensure_bg_tag(self, bg)
                self.tag_add("bg_{}".format(bg), start, end)
        self.focus_set()

    def set_html(self, html):
        self.delete("1.0", "end")
        self._clear_images()
        blocks = parse_rich_html(html)
        list_no = 0
        list_style = None
        for blk in blocks:
            if blk.get("image"):
                blk["list"] = False
                if self.index("end-1c") != "1.0":
                    self.insert("end", "\n")
                photo = self._make_image(blk["image"])
                self.image_create("end-1c", image=photo)
                self.insert("end", "\n")
                list_no = 0
                list_style = None
                continue
            text = (blk.get("text") or "").rstrip("\n")
            _ensure_bg_tag(self, blk.get("bg"))
            tags = _block_tags(blk)
            style = _list_style_key(blk.get("list"))
            if style:
                if style != list_style:
                    list_no = 0
                list_no += 1
                list_style = style
                self._insert_list_prefix("end", list_no, style)
            else:
                list_no = 0
                list_style = None
            self.insert("end", text, tags)
            self.insert("end", "\n")
        self.edit_reset()

    def get_html(self):
        return blocks_to_html(self._collect_blocks())

    def _collect_blocks(self):
        """通过 dump 保留嵌入式图片，把内容还原为段落块序列。"""
        items = []  # (kind, value, index)
        for key, value, idx in self.dump("1.0", "end", text=True, image=True):
            if key == "image":
                rel = self._image_rel.get(value, value)
                items.append(("img", rel, idx))
            elif key == "text":
                for offset, ch in enumerate(value):
                    index = idx if offset == 0 else "{} + {}c".format(idx, offset)
                    items.append(("t", ch, index))

        lines = [[]]
        for kind, value, index in items:
            if kind == "t" and value == "\n":
                lines.append([])
            else:
                lines[-1].append((kind, value, index))
        if lines and not lines[-1]:
            lines.pop()

        blocks = []
        for line in lines:
            line = [it for it in line if not (
                it[0] == "t" and _LIST_NUM_TAG in self.tag_names(it[2])
            )]
            fragments = []
            text_parts = []
            text_index = None
            for kind, value, index in line:
                if kind == "img":
                    if text_parts:
                        fragments.append(("t", "".join(text_parts), text_index))
                        text_parts = []
                        text_index = None
                    fragments.append(("img", value, index))
                else:
                    if text_index is None:
                        text_index = index
                    text_parts.append(value)
            if text_parts:
                fragments.append(("t", "".join(text_parts), text_index))

            for kind, value, index in fragments:
                if kind == "img":
                    blocks.append({
                        "b": False, "red": False, "size": None,
                        "text": "", "align": "center", "spacing": "single",
                        "indent": 0, "bg": None, "image": value, "list": False,
                    })
                    continue
                if not value.strip():
                    continue
                tags = self.tag_names(index)
                size = None
                for t in tags:
                    m = _SIZE_TAG_RE.match(t)
                    if m:
                        size = int(m.group(1))
                        break
                blocks.append({
                    "b": any(t.startswith("bold") for t in tags),
                    "red": "red" in tags,
                    "size": size,
                    "text": value,
                    "align": _tag_align(tags),
                    "spacing": _tag_spacing(tags),
                    "indent": _tag_indent(tags),
                    "bg": _tag_bg(tags),
                    "list": "circle" if "listcircle" in tags else ("list" in tags),
                })
        return blocks

    def _selection_line_range(self):
        """返回选中内容实际覆盖的行范围；无选区时返回光标所在行。"""
        try:
            ranges = self.tag_ranges("sel")
        except tk.TclError:
            ranges = ()
        if not ranges:
            line = int(self.index("insert").split(".")[0])
            return line, line
        start = self.index(ranges[0])
        end = self.index(ranges[-1])
        start_line = int(start.split(".")[0])
        end_line = int(end.split(".")[0])
        if end == self.index("{}.0".format(end_line)):
            end_line -= 1
        end_line = max(start_line, end_line)
        return start_line, end_line

    def apply_list(self, enabled, style="decimal"):
        """把当前段（或选中段）切换为自动序号列表项，并让连续段序号保持连续。"""
        start_line, end_line = self._selection_line_range()
        changed = False
        for line_no in range(start_line, end_line + 1):
            ls = "{}.0".format(line_no)
            le = self.index("{}.0 lineend +1c".format(line_no))
            if self._line_has_image(line_no):
                continue
            current = self._line_list_style(line_no)
            if enabled and current is None:
                num = self._list_number_before(line_no, style) + 1
                self._insert_list_prefix(ls, num, style)
                self.tag_add("list", ls, le)
                if style == "circle":
                    self.tag_add("listcircle", ls, le)
                changed = True
            elif not enabled and current is not None:
                self._delete_line_prefix(ls, le)
                le = self.index("{}.0 lineend +1c".format(line_no))
                self.tag_remove("list", ls, le)
                self.tag_remove("listcircle", ls, le)
                changed = True
            elif enabled and current != style:
                self._delete_line_prefix(ls, le)
                le = self.index("{}.0 lineend +1c".format(line_no))
                self.tag_remove("listcircle", ls, le)
                self.tag_add("list", ls, le)
                if style == "circle":
                    self.tag_add("listcircle", ls, le)
                changed = True
        if changed:
            self._renumber_lists_from(start_line)
        self.focus_set()

    def _line_list_style(self, line_no):
        """返回指定行当前的序号样式；不是列表行时返回 None。"""
        ls = "{}.0".format(line_no)
        if "list" not in self.tag_names(ls):
            return None
        return "circle" if "listcircle" in self.tag_names(ls) else "decimal"

    def _insert_list_prefix(self, index, num, style):
        tags = [_LIST_NUM_TAG, "list"]
        if style == "circle":
            tags.append("listcircle")
        self.insert(index, _format_list_prefix(num, style), tuple(tags))

    def _line_has_image(self, line_no):
        """判断某一行是否包含嵌入式图片（图片独立段不参与自动序号）。"""
        start = "{}.0".format(line_no)
        end = self.index("{}.0 lineend +1c".format(line_no))
        for _, _, _ in self.dump(start, end, image=True):
            return True
        return False

    def _delete_line_prefix(self, line_start, line_end):
        """删除行首的序号前缀文本（仅带 listnum tag 的字符）。"""
        line_text = self.get(line_start, line_end)
        m = _LIST_PREFIX_RE.match(line_text)
        if not m:
            return
        prefix_len = len(m.group(0))
        for i in range(prefix_len):
            index = self.index("{} +{}c".format(line_start, i))
            if _LIST_NUM_TAG not in self.tag_names(index):
                return
        self.delete(line_start, "{} +{}c".format(line_start, prefix_len))

    def _list_number_before(self, line_no, style):
        """返回当前行之前连续序号段中的最后一个序号；没有则返回 0。"""
        line_no -= 1
        last = 0
        while line_no >= 1:
            if self._line_list_style(line_no) != style:
                break
            ls = "{}.0".format(line_no)
            text = self.get(ls, "{}.0 lineend +1c".format(line_no))
            num = _prefix_number(text, style)
            if num:
                last = num
            line_no -= 1
        return last

    def _renumber_lists_from(self, line_no):
        """从指定行开始向下把连续序号段重新编号，保证序号连续。"""
        first = line_no
        while first > 1 and self._line_list_style(first - 1) is not None:
            first -= 1
        num = 0
        style = None
        last_line = int(self.index("end-1c").split(".")[0])
        for current in range(first, last_line + 1):
            current_style = self._line_list_style(current)
            if current_style is None:
                num = 0
                style = None
                continue
            if current_style != style:
                style = current_style
                num = 0
            num += 1
            ls = "{}.0".format(current)
            le = self.index("{}.0 lineend +1c".format(current))
            self._delete_line_prefix(ls, le)
            self._insert_list_prefix(ls, num, style)

    def insert_image(self, rel, at_end=False):
        """在光标处或文末插入独立图片段落。"""
        if at_end:
            content = self.get("1.0", "end-1c")
            if content and not content.endswith("\n"):
                self.insert("end", "\n")
            index = "end-1c"
        else:
            index = self.index("insert")
            line_start = self.index(index.split(".")[0] + ".0")
            if index != line_start:
                self.insert(index, "\n")
                index = self.index("insert")
        photo = self._make_image(rel)
        self.image_create(index, image=photo)
        after = self.index("{} +1c".format(index))
        if self.index("end-1c") != after and self.get(after, after + " +1c") != "\n":
            self.insert(after, "\n")
        self.insert("insert", "\n")
        self.mark_set("insert", after)

    def get_plain(self):
        return self.get("1.0", "end").strip()

    def set_plain(self, text):
        self.set_html(plain_to_html(text))

    def append_plain(self, text):
        """在末尾追加纯文本（用于 OCR 结果追加）。"""
        current = self.get_plain()
        if current:
            self.insert("end", "\n")
        self.insert("end", text or "")

    def replace_plain(self, text):
        """整体替换为纯文本（用于 OCR 结果覆盖）。"""
        self.set_plain(text)


class AutoHeightRichText(tk.Frame):
    """自适应高度的富文本：随内容增减自动调整行高。

    展示/编辑共用同一个 RichTextArea，双击进入编辑，外部调用 save()
    后回到只读态并通过 on_save 回调保存。内容中的富文本格式在两种
    状态下保持一致，不会因切换组件而丢失。
    """

    def __init__(self, master, bg=None, on_save=None, min_lines=2, max_lines=None,
                 max_height=None, image_resolver=None, image_store=None,
                 always_editable=False, **kw):
        super().__init__(master, bg=bg or PALETTE["surface"], **kw)
        self._on_save = on_save
        self._min_lines = min_lines
        self._max_lines = max_lines
        self._max_height = max_height
        self._always_editable = bool(always_editable)
        self._editing = False
        self._editing_before = ""
        self._resize_after = None
        self.input = RichTextInput(
            self, height=min_lines, image_resolver=image_resolver,
            image_store=image_store, compact=True,
            toolbar_visible=self._always_editable, bg=bg or PALETTE["surface"],
        )
        # 自适应高度场景下按内容纵向请求尺寸，避免 Text 的 fill/expand
        # 把外层 Frame 的请求高度压成最小值，导致内容无法撑开。
        self.input.pack(fill="x")
        self.text = self.input.text
        if self._always_editable:
            self.text.configure(state="normal", cursor="xterm")
        else:
            self.text.configure(state="disabled", cursor="arrow")
        self.text.bind("<Double-1>", self._start_edit)
        self.text.bind("<KeyRelease>", lambda e: self._schedule_resize())
        self.text.bind("<<Modified>>", lambda e: self._schedule_resize())
        self.text.bind("<Configure>", self._schedule_resize)

    @property
    def is_editing(self):
        return self._editing

    def set_html(self, html):
        """重置内容并退出编辑态；html 为轻量 HTML 字符串。"""
        self.text.configure(state="normal")
        try:
            self.text.set_html(html or "")
        finally:
            if self._always_editable:
                self.input.set_toolbar_visible(True)
                self.text.configure(
                    state="normal", cursor="xterm",
                    highlightbackground=PALETTE["focus"],
                )
                self._editing = True
            else:
                self.input.set_toolbar_visible(False)
                self.text.configure(
                    state="disabled", cursor="arrow",
                    highlightbackground=PALETTE["border"],
                )
                self._editing = False
            self._editing_before = self.text.get_html()
        self._schedule_resize()

    def destroy(self):
        if self._resize_after is not None:
            try:
                self.after_cancel(self._resize_after)
            except tk.TclError:
                pass
            self._resize_after = None
        super().destroy()

    def _start_edit(self, _event=None):
        self.input.set_toolbar_visible(True)
        self.text.configure(
            state="normal", cursor="xterm",
            highlightbackground=PALETTE["focus"],
        )
        if self._always_editable:
            self.text.focus_set()
            self.input._sync_toolbar()
            return None
        if self._editing:
            return None
        self._editing = True
        self._editing_before = self.text.get_html()
        self.text.focus_set()
        self.input._sync_toolbar()
        return None

    def save(self, force=False):
        """结束编辑并把改动交给 on_save；无改动时仍退出编辑态。"""
        if not self._editing and not self._always_editable:
            return False
        self._editing = False
        html = self.text.get_html()
        if self._always_editable:
            self.input.set_toolbar_visible(True)
            self.text.configure(
                state="normal", cursor="xterm",
                highlightbackground=PALETTE["focus"],
            )
        else:
            self.input.set_toolbar_visible(False)
            self.text.configure(
                state="disabled", cursor="arrow",
                highlightbackground=PALETTE["border"],
            )
        self._schedule_resize()
        changed = force or html != self._editing_before
        self._editing_before = html
        if changed and self._on_save is not None:
            self._on_save(html)
        return True

    def _schedule_resize(self, _event=None):
        if self._resize_after is not None:
            try:
                self.after_cancel(self._resize_after)
            except tk.TclError:
                pass
        self._resize_after = self.after_idle(self._resize)

    def _resize(self):
        self._resize_after = None
        try:
            self.update_idletasks()
        except (tk.TclError, TypeError, ValueError):
            return
        try:
            needed = _text_required_height(self.text)
            line_h = tkfont.Font(font=self.text.cget("font")).metrics("linespace")
            if line_h <= 0:
                line_h = 24
            lines = max(self._min_lines, int(math.ceil(needed / line_h)))
            if self._max_lines is not None:
                lines = min(lines, self._max_lines)
            if self._max_height is not None:
                cap = max(
                    self._min_lines,
                    int(math.ceil(self._max_height / line_h)),
                )
                lines = min(lines, cap)
            self.text.configure(height=lines)
        except (tk.TclError, TypeError, ValueError):
            return


class RichTextInput(tk.Frame):
    """可复用富文本编辑组件：工具栏 + 内容区，统一各页面文本输入。"""

    def __init__(self, master, height=8, html="", image_resolver=None,
                 image_store=None, compact=False, toolbar_visible=True, **kw):
        bg = kw.pop("bg", PALETTE["bg"])
        super().__init__(master, bg=bg, **kw)
        self.image_store = image_store
        self.image_resolver = image_resolver
        self._compact = compact
        self._toolbar_visible = False
        self._build_toolbar()
        self.text = RichTextArea(
            self, height=height,
            image_resolver=image_resolver, image_store=image_store,
        )
        self.text.pack(fill="both", expand=True, pady=(4, 0))
        self.text.set_html(html)
        self.text.bind("<<Selection>>", lambda e: self._sync_toolbar())
        self.text.bind("<KeyRelease>", lambda e: self._sync_toolbar())
        self.set_toolbar_visible(toolbar_visible)
        self._sync_toolbar()

    def _tool_button(self, parent, text, command, fg=None, font=None, hint=""):
        P = PALETTE
        btn = tk.Button(
            parent, text=text, command=command, width=3,
            bg=P["surface"], fg=fg or P["text"], relief="flat", bd=0,
            font=font or (_FONT_FAMILY, 12),
            activebackground=P["btn_active"], cursor="hand2",
        )
        if hint:
            self._tooltip(btn, hint)
        return btn

    def _tooltip(self, widget, text):
        tip = None

        def show(event):
            nonlocal tip
            if tip is not None:
                return
            try:
                tip = tk.Toplevel(self)
                tip.wm_overrideredirect(True)
                tip.configure(bg=PALETTE["border"])
                label = tk.Label(
                    tip, text=text, bg=PALETTE["surface"], fg=PALETTE["text"],
                    font=("Microsoft YaHei UI", 10), padx=8, pady=4,
                )
                label.pack()
                x = widget.winfo_rootx()
                y = widget.winfo_rooty() + widget.winfo_height() + 4
                tip.wm_geometry("+{}+{}".format(x, y))
            except tk.TclError:
                tip = None

        def hide(event=None):
            nonlocal tip
            if tip is not None:
                try:
                    tip.destroy()
                except tk.TclError:
                    pass
                tip = None

        widget.bind("<Enter>", show)
        widget.bind("<Leave>", hide)

    def _build_toolbar(self):
        P = PALETTE
        self.toolbar = tk.Frame(self, bg=P["bg"])
        self.toolbar.pack(fill="x")
        if self._compact:
            self._build_compact_toolbar(P)
        else:
            self._build_full_toolbar(P)

    def _build_full_toolbar(self, P):
        bar = self.toolbar
        self.bold_btn = self._tool_button(
            bar, "B", self._toggle_bold,
            font=(_FONT_FAMILY, 12, "bold"), hint="加粗选中文字",
        )
        self.bold_btn.pack(side="left")
        self.red_btn = self._tool_button(
            bar, "红", self._toggle_red, fg=P["danger"],
            font=(_FONT_FAMILY, 12, "bold"), hint="标红选中文字",
        )
        self.red_btn.pack(side="left", padx=(4, 0))
        self.list_btn = self._tool_button(
            bar, "1.", self._toggle_list,
            font=(_FONT_FAMILY, 12, "bold"), hint="数字自动序号（1. 2. 3.，作用于当前段或选中段）",
        )
        self.list_btn.pack(side="left", padx=(4, 0))
        self.circle_btn = self._tool_button(
            bar, "①", self._toggle_circle_list,
            font=(_FONT_FAMILY, 12), hint="圈号自动序号（①②③，作用于当前段或选中段）",
        )
        self.circle_btn.pack(side="left", padx=(2, 0))

        tk.Label(bar, text="字号", bg=P["bg"], fg=P["muted"],
                 font=("Microsoft YaHei UI", 11)).pack(side="left", padx=(10, 4))
        self.size_var = tk.StringVar(value="13")
        self.size_box = ttk.Combobox(
            bar, textvariable=self.size_var, state="readonly", width=4,
            values=[str(v) for v in _SIZE_CHOICES],
        )
        self.size_box.pack(side="left")
        self.size_box.bind("<<ComboboxSelected>>", lambda e: self._apply_size())

        tk.Label(bar, text="对齐", bg=P["bg"], fg=P["muted"],
                 font=("Microsoft YaHei UI", 11)).pack(side="left", padx=(10, 4))
        self.align_var = tk.StringVar(value="左对齐")
        self.align_box = ttk.Combobox(
            bar, textvariable=self.align_var, state="readonly", width=7,
            values=list(_ALIGN_LABELS.values()),
        )
        self.align_box.pack(side="left")
        self.align_box.bind("<<ComboboxSelected>>", lambda e: self._apply_align())

        tk.Label(bar, text="行距", bg=P["bg"], fg=P["muted"],
                 font=("Microsoft YaHei UI", 11)).pack(side="left", padx=(10, 4))
        self.spacing_var = tk.StringVar(value="单倍行距")
        self.spacing_box = ttk.Combobox(
            bar, textvariable=self.spacing_var, state="readonly", width=10,
            values=list(_SPACING_LABELS.values()),
        )
        self.spacing_box.pack(side="left")
        self.spacing_box.bind("<<ComboboxSelected>>", lambda e: self._apply_spacing())

        tk.Label(bar, text="缩进", bg=P["bg"], fg=P["muted"],
                 font=("Microsoft YaHei UI", 11)).pack(side="left", padx=(10, 4))
        self.indent_var = tk.StringVar(value="2 个汉字")
        self.indent_box = ttk.Combobox(
            bar, textvariable=self.indent_var, state="readonly", width=8,
            values=["无", "2 个汉字", "4 个汉字"],
        )
        self.indent_box.pack(side="left")
        self.indent_box.bind("<<ComboboxSelected>>", lambda e: self._apply_indent())

        self.bg_btn = self._tool_button(
            bar, "背景", self._pick_bg, hint="段落背景色",
        )
        self.bg_btn.pack(side="left", padx=(10, 0))
        self.image_btn = self._tool_button(
            bar, "图片", self._insert_image, hint="插入图片（也可直接 Ctrl+V 粘贴剪贴板图片）",
        )
        if self.image_store is None:
            self.image_btn.configure(state="disabled")
        self.image_btn.pack(side="left", padx=(10, 0))
        hint_text = "选中文字后可加粗/标红/改字号；段落格式作用于整段"
        if self.image_store is not None:
            hint_text += "；正文中可直接粘贴图片"
        tk.Label(
            bar, text=hint_text,
            bg=P["bg"], fg=P["faint"], font=("Microsoft YaHei UI", 9),
        ).pack(side="right")

    def _build_compact_toolbar(self, P):
        row1 = tk.Frame(self.toolbar, bg=P["bg"])
        row2 = tk.Frame(self.toolbar, bg=P["bg"])
        row1.pack(fill="x")
        row2.pack(fill="x", pady=(2, 0))

        self.bold_btn = self._tool_button(
            row1, "B", self._toggle_bold,
            font=(_FONT_FAMILY, 12, "bold"), hint="加粗选中文字",
        )
        self.bold_btn.pack(side="left")
        self.red_btn = self._tool_button(
            row1, "红", self._toggle_red, fg=P["danger"],
            font=(_FONT_FAMILY, 12, "bold"), hint="标红选中文字",
        )
        self.red_btn.pack(side="left", padx=(4, 0))
        self.list_btn = self._tool_button(
            row1, "1.", self._toggle_list,
            font=(_FONT_FAMILY, 12, "bold"), hint="数字自动序号（1. 2. 3.，作用于当前段或选中段）",
        )
        self.list_btn.pack(side="left", padx=(4, 0))
        self.circle_btn = self._tool_button(
            row1, "①", self._toggle_circle_list,
            font=(_FONT_FAMILY, 12), hint="圈号自动序号（①②③，作用于当前段或选中段）",
        )
        self.circle_btn.pack(side="left", padx=(2, 0))

        tk.Label(row1, text="字号", bg=P["bg"], fg=P["muted"],
                 font=("Microsoft YaHei UI", 10)).pack(side="left", padx=(8, 2))
        self.size_var = tk.StringVar(value="13")
        self.size_box = ttk.Combobox(
            row1, textvariable=self.size_var, state="readonly", width=3,
            values=[str(v) for v in _SIZE_CHOICES],
        )
        self.size_box.pack(side="left")
        self.size_box.bind("<<ComboboxSelected>>", lambda e: self._apply_size())

        tk.Label(row1, text="对齐", bg=P["bg"], fg=P["muted"],
                 font=("Microsoft YaHei UI", 10)).pack(side="left", padx=(8, 2))
        self.align_var = tk.StringVar(value="左对齐")
        self.align_box = ttk.Combobox(
            row1, textvariable=self.align_var, state="readonly", width=5,
            values=list(_ALIGN_LABELS.values()),
        )
        self.align_box.pack(side="left")
        self.align_box.bind("<<ComboboxSelected>>", lambda e: self._apply_align())

        tk.Label(row2, text="行距", bg=P["bg"], fg=P["muted"],
                 font=("Microsoft YaHei UI", 10)).pack(side="left", padx=(0, 2))
        self.spacing_var = tk.StringVar(value="单倍行距")
        self.spacing_box = ttk.Combobox(
            row2, textvariable=self.spacing_var, state="readonly", width=7,
            values=list(_SPACING_LABELS.values()),
        )
        self.spacing_box.pack(side="left")
        self.spacing_box.bind("<<ComboboxSelected>>", lambda e: self._apply_spacing())

        tk.Label(row2, text="缩进", bg=P["bg"], fg=P["muted"],
                 font=("Microsoft YaHei UI", 10)).pack(side="left", padx=(4, 2))
        self.indent_var = tk.StringVar(value="2 个汉字")
        self.indent_box = ttk.Combobox(
            row2, textvariable=self.indent_var, state="readonly", width=5,
            values=["无", "2 个汉字", "4 个汉字"],
        )
        self.indent_box.pack(side="left")
        self.indent_box.bind("<<ComboboxSelected>>", lambda e: self._apply_indent())

        self.bg_btn = self._tool_button(
            row2, "背景", self._pick_bg, hint="段落背景色",
        )
        self.bg_btn.pack(side="left", padx=(3, 0))
        self.image_btn = self._tool_button(
            row2, "图片", self._insert_image, hint="插入图片（也可直接 Ctrl+V 粘贴剪贴板图片）",
        )
        if self.image_store is None:
            self.image_btn.pack_forget()
        else:
            self.image_btn.pack(side="left", padx=(3, 0))

    def set_toolbar_visible(self, visible=True):
        """控制工具栏显隐；节点详情等窄面板在编辑时再展开工具栏。"""
        visible = bool(visible)
        if visible == self._toolbar_visible:
            return
        self._toolbar_visible = visible
        if visible:
            if getattr(self, "text", None) is not None and self.text.winfo_ismapped():
                self.toolbar.pack(fill="x", before=self.text)
            else:
                self.toolbar.pack(fill="x")
        else:
            self.toolbar.pack_forget()

    def _insert_image(self):
        if self.image_store is None:
            return
        dlg = ImageInsertDialog(self, self.image_store)
        self.wait_window(dlg)
        if dlg.result:
            rels = dlg.result.get("rels") or (
                [dlg.result["rel"]] if "rel" in dlg.result else [])
            for rel in rels:
                self.text.insert_image(rel)

    # ---------- 选中与格式 ----------
    def _sel_start(self):
        try:
            ranges = self.text.tag_ranges("sel")
        except tk.TclError:
            return None
        return ranges[0] if ranges else None

    def _toggle_bold(self):
        start = self._sel_start()
        if not start:
            return
        tags = self.text.tag_names(start)
        has = "bold" in tags or any(t.startswith("boldsize") for t in tags)
        ranges = self.text.tag_ranges("sel")
        for i in range(0, len(ranges), 2):
            s, e = ranges[i], ranges[i + 1]
            if has:
                self.text.tag_remove("bold", s, e)
                for size in _SIZE_CHOICES:
                    self.text.tag_remove("boldsize{}".format(size), s, e)
            else:
                size = None
                for t in tags:
                    m = _SIZE_TAG_RE.match(t)
                    if m:
                        size = int(m.group(1))
                        break
                if size:
                    self.text.tag_add("boldsize{}".format(size), s, e)
                else:
                    self.text.tag_add("bold", s, e)
        self._sync_toolbar()

    def _toggle_red(self):
        start = self._sel_start()
        if not start:
            return
        has = "red" in self.text.tag_names(start)
        ranges = self.text.tag_ranges("sel")
        for i in range(0, len(ranges), 2):
            s, e = ranges[i], ranges[i + 1]
            if has:
                self.text.tag_remove("red", s, e)
            else:
                self.text.tag_add("red", s, e)
        self._sync_toolbar()

    def _apply_size(self):
        start = self._sel_start()
        if not start:
            return
        value = int(self.size_var.get())
        ranges = self.text.tag_ranges("sel")
        for i in range(0, len(ranges), 2):
            s, e = ranges[i], ranges[i + 1]
            for size in _SIZE_CHOICES:
                self.text.tag_remove("size{}".format(size), s, e)
                self.text.tag_remove("boldsize{}".format(size), s, e)
            tags = self.text.tag_names(s)
            if "bold" in tags or any(t.startswith("boldsize") for t in tags):
                self.text.tag_remove("bold", s, e)
                self.text.tag_add("boldsize{}".format(value), s, e)
            else:
                self.text.tag_add("size{}".format(value), s, e)
        self._sync_toolbar()

    @staticmethod
    def _label_key(label, mapping):
        for key, lab in mapping.items():
            if lab == label:
                return key
        return None

    def _apply_align(self):
        key = self._label_key(self.align_var.get(), _ALIGN_LABELS)
        if key:
            self.text.apply_paragraph_format(align=key)

    def _apply_spacing(self):
        key = self._label_key(self.spacing_var.get(), _SPACING_LABELS)
        if key:
            self.text.apply_paragraph_format(spacing=key)

    def _apply_indent(self):
        value = self.indent_var.get()
        indent = {"无": 0, "2 个汉字": 2, "4 个汉字": 4}.get(value, 0)
        self.text.apply_paragraph_format(indent=indent)

    def _pick_bg(self):
        P = PALETTE
        menu = tk.Menu(self, tearoff=0, bg=P["surface"], fg=P["text"],
                       activebackground=P["primary_light"], bd=0)
        for label, hex_color in (
            ("无背景", None),
            ("浅黄", "#FFF3CD"),
            ("浅蓝", "#E8F0FE"),
            ("浅绿", "#E7F6EC"),
            ("浅红", "#FDEAEA"),
            ("浅灰", "#EEF1F5"),
            ("白色", "#FFFFFF"),
            ("自定义…", "custom"),
        ):
            menu.add_command(label=label, command=lambda c=hex_color: self._apply_bg(c))
        try:
            menu.tk_popup(
                self.bg_btn.winfo_rootx(),
                self.bg_btn.winfo_rooty() + self.bg_btn.winfo_height(),
            )
        finally:
            menu.grab_release()

    def _apply_bg(self, color):
        if color == "custom":
            chosen = colorchooser.askcolor(parent=self)[1]
            color = chosen.upper() if chosen else None
        self.text.apply_paragraph_format(bg=color)

    def _toggle_list(self):
        self._toggle_list_style("decimal")

    def _toggle_circle_list(self):
        self._toggle_list_style("circle")

    def _toggle_list_style(self, style):
        start = self._sel_start()
        if start:
            tags = self.text.tag_names(start)
        else:
            tags = self.text.tag_names(self.text.index("insert"))
        current = "circle" if "listcircle" in tags else (
            "decimal" if "list" in tags else None)
        self.text.apply_list(current != style, style)
        self._sync_toolbar()

    def _sync_toolbar(self):
        start = self._sel_start()
        P = PALETTE
        if not start:
            return
        tags = self.text.tag_names(start)
        has_bold = "bold" in tags or any(t.startswith("boldsize") for t in tags)
        self.bold_btn.configure(bg=P["primary_light"] if has_bold else P["surface"])
        self.red_btn.configure(bg=P["danger_light"] if "red" in tags else P["surface"])
        if getattr(self, "list_btn", None) is not None:
            self.list_btn.configure(
                bg=P["primary_light"] if "list" in tags and "listcircle" not in tags
                else P["surface"]
            )
        if getattr(self, "circle_btn", None) is not None:
            self.circle_btn.configure(
                bg=P["primary_light"] if "listcircle" in tags else P["surface"]
            )
        for t in tags:
            m = _SIZE_TAG_RE.match(t)
            if m:
                self.size_var.set(str(int(m.group(1))))
        align = _tag_align(tags)
        self.align_var.set(_ALIGN_LABELS[align])
        spacing = _tag_spacing(tags)
        self.spacing_var.set(_SPACING_LABELS[spacing])
        indent = _tag_indent(tags)
        self.indent_var.set("{} 个汉字".format(indent) if indent else "无")

    # ---------- 值读写 ----------
    def set_html(self, html):
        self.text.set_html(html)

    def get_html(self):
        return self.text.get_html()

    def set_plain(self, text):
        self.text.set_plain(text)

    def get_plain(self):
        return self.text.get_plain()

    def get_value(self):
        return self.get_html()


class RichTextEditor(tk.Toplevel):
    """富文本编辑弹窗：标题 + 可复用富文本组件，保存后返回 {"title", "content"}。"""

    def __init__(self, master, title="编辑知识点", initial_title="", initial_html="",
                 subtitle="", extra_footer=None, image_resolver=None, image_store=None):
        super().__init__(master)
        self.result = None
        self.image_resolver = image_resolver
        self.image_store = image_store
        self.title(title)
        self.geometry("820x660")
        self.minsize(680, 520)
        self.transient(master)
        setup_styles(self)
        self.configure(bg=PALETTE["bg"])
        dialog_header(self, title, subtitle, title_size=14, subtitle_size=9)
        self._build(initial_title, initial_html, extra_footer or [])
        center_window(self)
        fade_in(self)
        self.grab_set()

    def _build(self, initial_title, initial_html, extra_footer):
        P = PALETTE
        body = tk.Frame(self, bg=P["bg"], padx=14, pady=10)
        body.pack(fill="both", expand=True)

        title_row = tk.Frame(body, bg=P["bg"])
        title_row.pack(fill="x", pady=(0, 6))
        tk.Label(title_row, text="知识点标题", bg=P["bg"], fg=P["text"],
                 font=("Microsoft YaHei UI", 12)).pack(side="left")
        self.title_entry = ttk.Entry(title_row, font=("Microsoft YaHei UI", 12))
        self.title_entry.pack(side="left", fill="x", expand=True, padx=(8, 0))
        bind_text_paste(self.title_entry)
        if initial_title:
            self.title_entry.insert(0, initial_title)
        bind_entry_undo(self.title_entry)

        self.input = RichTextInput(
            body, height=14, html=initial_html,
            image_resolver=self.image_resolver, image_store=self.image_store,
        )
        self.input.pack(fill="both", expand=True, pady=(2, 0))
        self.text = self.input.text

        bottom = tk.Frame(self, bg=P["bg"], padx=14, pady=10)
        bottom.pack(fill="x")
        for text, cmd in extra_footer:
            ttk.Button(bottom, text=text, command=cmd).pack(side="left")
        self.count_label = tk.Label(bottom, text="", bg=P["bg"], fg=P["faint"],
                                    font=("Microsoft YaHei UI", 11))
        self.count_label.pack(side="left", padx=10)
        ttk.Button(bottom, text="取消", command=self.destroy).pack(side="right")
        ttk.Button(bottom, text="保存", style="Accent.TButton",
                   command=self._save).pack(side="right", padx=8)
        self.bind("<Escape>", lambda e: self.destroy())
        self.text.bind("<Control-Return>", lambda e: self._save())
        self._update_count()

    def _update_count(self):
        n = len(self.text.get("1.0", "end-1c"))
        self.count_label.configure(text="{} 字".format(n))
        self.after(400, self._update_count)

    def _save(self, event=None):
        title = self.title_entry.get().strip()
        if not title:
            messagebox.showerror("标题不能为空", "请填写知识点标题。", parent=self)
            return
        self.result = {"title": title, "content": self.text.get_html()}
        self.destroy()


class RichTextViewer(tk.Frame):
    """只读富文本视图：渲染轻量 HTML，供知识库正文展示。"""

    def __init__(self, master, bg=None, on_edit=None, image_resolver=None,
                 auto_height=False, min_height=64, max_height=None, **kw):
        bg = bg or PALETTE["surface"]
        super().__init__(master, bg=bg, **kw)
        self._on_edit = on_edit
        self.image_resolver = image_resolver
        self._image_refs = []
        self._auto_height = auto_height
        self._min_height = min_height
        self._max_height = max_height
        self._resize_after = None
        self.text = tk.Text(
            self, wrap="word", font=(_FONT_FAMILY, 13),
            bg=bg, fg=PALETTE["text"], relief="flat", bd=0,
            highlightthickness=0, state="disabled", cursor="arrow",
        )
        self.text.pack(fill="both", expand=True)
        self.text.configure(background=bg, foreground=PALETTE["text"])
        if auto_height:
            self.text.bind("<Configure>", self._schedule_resize)
        if on_edit is not None:
            self.text.bind("<Double-1>", lambda e: self._on_edit())
        self._configure_tags()

    def _schedule_resize(self, _event=None):
        if self._resize_after is not None:
            return
        self._resize_after = self.after_idle(self._resize)

    def _resize(self):
        self._resize_after = None
        try:
            needed = _text_required_height(self.text, self._image_refs)
        except (tk.TclError, TypeError, ValueError):
            return
        if self._max_height is not None:
            needed = min(needed, self._max_height)
        needed = max(self._min_height, needed)
        try:
            line_h = tkfont.Font(font=self.text.cget("font")).metrics("linespace")
        except (tk.TclError, TypeError, ValueError):
            line_h = 0
        if line_h <= 0:
            line_h = 24
        lines = max(1, int(math.ceil(needed / line_h)))
        if self.text.cget("height") != str(lines):
            self.text.configure(height=lines)

    def _configure_tags(self):
        P = PALETTE
        self.text.tag_configure("bold", font=(_FONT_FAMILY, 13, "bold"))
        self.text.tag_configure("red", foreground=P["danger"])
        self.text.tag_configure("alignleft", justify="left")
        self.text.tag_configure("aligncenter", justify="center")
        self.text.tag_configure("alignright", justify="right")
        self.text.tag_configure("linesingle", spacing1=0, spacing3=4)
        self.text.tag_configure("linewide", spacing1=4, spacing3=12)
        self.text.tag_configure("linedouble", spacing1=10, spacing3=24)
        for n in (2, 4):
            self.text.tag_configure("indent{}".format(n), lmargin1=_indent_px(n), lmargin2=0)
        for hex_color in _BG_COLORS:
            self.text.tag_configure("bg_{}".format(hex_color), background=_theme_bg(hex_color))
        for size in _SIZE_CHOICES:
            self.text.tag_configure("size{}".format(size), font=(_FONT_FAMILY, size))
            self.text.tag_configure("boldsize{}".format(size), font=(_FONT_FAMILY, size, "bold"))

    def set_html(self, html):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self._image_refs.clear()
        if self._auto_height:
            self._resize_after = None
        for blk in parse_rich_html(html):
            _ensure_bg_tag(self.text, blk.get("bg"))
            tags = _block_tags(blk)
            if blk.get("image"):
                abs_path = None
                if self.image_resolver is not None:
                    try:
                        abs_path = self.image_resolver(blk["image"])
                    except Exception:
                        abs_path = None
                if not abs_path:
                    self.text.insert("end", "[图片]\n")
                    continue
                photo = _load_photo(str(abs_path), _MAX_VIEW_IMAGE_W, _MAX_VIEW_IMAGE_H)
                self._image_refs.append(photo)
                if self.text.index("end-1c") != "1.0" and \
                        self.text.get("end-2c", "end-1c") != "\n":
                    self.text.insert("end", "\n")
                self.text.image_create("end-1c", image=photo)
                self.text.insert("end", "\n")
                continue
            self.text.insert("end", blk.get("text", "") + "\n", tags or None)
        self.text.configure(state="disabled")
        if self._auto_height:
            self._schedule_resize()

    def set_plain(self, text):
        self.set_html(plain_to_html(text))

    def destroy(self):
        if self._resize_after is not None:
            try:
                self.after_cancel(self._resize_after)
            except tk.TclError:
                pass
            self._resize_after = None
        super().destroy()
