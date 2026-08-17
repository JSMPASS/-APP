# -*- coding: utf-8 -*-
"""图片报告导出：把一段日期范围内的打卡情况渲染为一张长图（PNG）。

布局：渐变标题横幅 -> 统计卡片 -> 已完成打卡详情 -> 题目与解析（含错题反思）-> 未完成项。
"""
from __future__ import annotations

import os
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

from habit_checkin.services.export_common import (
    default_filename as _default_filename,
    fmt_duration,
    load_report_data,
    report_title,
    result_text,
    weekday_cn,
)

W = 1080
PAD = 44

# 配色（与界面主题一致）
C_PRIMARY = "#2D6CDF"
C_PRIMARY_DARK = "#2458B8"
C_PRIMARY_LIGHT = "#E4EDFB"
C_ACCENT = "#16A34A"
C_WARNING = "#D97706"
C_TEXT = "#1F2937"
C_MUTED = "#6B7280"
C_BORDER = "#D8E0EA"
C_BG = "#F5F8FC"
C_WHITE = "#FFFFFF"


def _font_path():
    """返回可用的中文字体文件路径（微软雅黑优先）。"""
    for p in (
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\simsun.ttc",
    ):
        if os.path.isfile(p):
            return p
    return None


_FONT_CACHE = {}


def _font(size, bold=False):
    key = (size, bold)
    if key not in _FONT_CACHE:
        path = _font_path()
        try:
            if path:
                f = ImageFont.truetype(path, size)
            else:
                f = ImageFont.load_default()
        except Exception:
            f = ImageFont.load_default()
        _FONT_CACHE[key] = f
    return _FONT_CACHE[key]


def _wrap(draw, text, font, max_w):
    """按字符宽度换行。"""
    lines = []
    for raw in str(text or "").split("\n"):
        if not raw:
            lines.append("")
            continue
        cur = ""
        for ch in raw:
            if draw.textlength(cur + ch, font=font) <= max_w:
                cur += ch
            else:
                lines.append(cur)
                cur = ch
        lines.append(cur)
    return lines


def _image_size(abs_path, max_w, max_h=1400):
    """返回图片按比例缩放后的 (宽, 高)；失败返回 None。"""
    try:
        with Image.open(abs_path) as im:
            w, h = im.size
    except Exception:
        return None
    if w > max_w:
        h = int(h * max_w / w)
        w = max_w
    if h > max_h:
        w = int(w * max_h / h)
        h = max_h
    return w, h


def _lerp(c1, c2, t):
    def hx(v):
        v = v.lstrip("#")
        return tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))
    a, b = hx(c1), hx(c2)
    rgb = tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))
    return "#{:02X}{:02X}{:02X}".format(*rgb)


class _Layout:
    """流式布局：先测量所有块高度，再一次性绘制。"""

    def __init__(self, width=W):
        self.width = width
        self.blocks = []  # (kind, payload)

    def banner(self, title, subtitle):
        self.blocks.append(("banner", (title, subtitle)))

    def spacer(self, h=14):
        self.blocks.append(("spacer", h))

    def stats(self, items):
        # items: [(caption, value, color), ...]
        self.blocks.append(("stats", items))

    def section(self, text):
        self.blocks.append(("section", text))

    def day(self, text):
        self.blocks.append(("day", text))

    def heading(self, text):
        self.blocks.append(("heading", text))

    def line(self, text, size=14, color=C_TEXT, bold=False, space=4):
        self.blocks.append(("line", (text, size, color, bold, space)))

    def image(self, abs_path):
        self.blocks.append(("image", abs_path))

    # ---------- 测量 ----------
    def _measure(self, draw):
        heights = []
        content_w = self.width - PAD * 2
        for kind, payload in self.blocks:
            if kind == "banner":
                heights.append(122)
            elif kind == "spacer":
                heights.append(payload)
            elif kind == "stats":
                heights.append(116)
            elif kind == "section":
                heights.append(44)
            elif kind == "day":
                heights.append(38)
            elif kind == "heading":
                f = _font(16, bold=True)
                n = len(_wrap(draw, payload, f, content_w))
                heights.append(n * 24 + 10)
            elif kind == "line":
                text, size, color, bold, space = payload
                f = _font(size, bold=bold)
                n = len(_wrap(draw, text, f, content_w))
                heights.append(n * (size + 9) + space)
            elif kind == "image":
                size = _image_size(payload, content_w - 24)
                if size is None:
                    heights.append(0)
                else:
                    heights.append(size[1] + 20)
        return heights

    def render(self, out_path):
        # 测量
        tmp_img = Image.new("RGB", (10, 10), C_WHITE)
        tmp_draw = ImageDraw.Draw(tmp_img)
        heights = self._measure(tmp_draw)
        total_h = PAD + sum(heights) + PAD
        img = Image.new("RGB", (self.width, total_h), C_BG)
        draw = ImageDraw.Draw(img)
        y = 0
        content_w = self.width - PAD * 2
        for (kind, payload), h in zip(self.blocks, heights):
            y = self._draw_block(draw, img, kind, payload, h, y, content_w)
        img.save(out_path, "PNG")
        return total_h

    def _draw_block(self, draw, img, kind, payload, h, y, content_w):
        if kind == "banner":
            title, subtitle = payload
            # 渐变横幅
            for i in range(h):
                draw.line(
                    [(0, y + i), (self.width, y + i)],
                    fill=_lerp(C_PRIMARY, C_PRIMARY_DARK, i / max(h - 1, 1)),
                )
            draw.text((PAD, y + 26), title, font=_font(30, bold=True), fill=C_WHITE)
            draw.text((PAD, y + 72), subtitle, font=_font(13), fill="#DCE7FB")
            return y + h
        if kind == "spacer":
            return y + h
        if kind == "stats":
            n = len(payload)
            gap = 14
            bw = (content_w - gap * (n - 1)) // n
            for i, (caption, value, color) in enumerate(payload):
                x = PAD + i * (bw + gap)
                draw.rounded_rectangle(
                    [x, y + 6, x + bw, y + h - 6], radius=12, fill=C_WHITE,
                    outline=C_BORDER, width=1,
                )
                draw.text((x + bw / 2, y + 26), str(value), font=_font(28, bold=True),
                          fill=color, anchor="mm")
                draw.text((x + bw / 2, y + 78), caption, font=_font(12), fill=C_MUTED,
                          anchor="mm")
            return y + h
        if kind == "section":
            draw.rounded_rectangle(
                [PAD, y + 4, PAD + 6, y + 30], radius=3, fill=C_PRIMARY,
            )
            draw.text((PAD + 18, y + 14), payload, font=_font(19, bold=True),
                      fill=C_TEXT, anchor="lm")
            return y + h
        if kind == "day":
            draw.text((PAD, y + 12), payload, font=_font(16, bold=True),
                      fill=C_PRIMARY, anchor="lm")
            return y + h
        if kind == "heading":
            draw.text((PAD, y + 10), payload, font=_font(16, bold=True),
                      fill=C_TEXT, anchor="lm")
            return y + h
        if kind == "line":
            text, size, color, bold, space = payload
            f = _font(size, bold=bold)
            for ln in _wrap(draw, text, f, content_w):
                draw.text((PAD, y + 4), ln, font=f, fill=color)
                y += size + 9
            return y + space
        if kind == "image":
            size = _image_size(payload, content_w - 24)
            if size is not None:
                w, hh = size
                try:
                    with Image.open(payload) as src:
                        overlay = src.convert("RGB").resize((w, hh), Image.LANCZOS)
                    x0 = (self.width - w) // 2
                    draw.rounded_rectangle(
                        [x0 - 4, y + 4, x0 + w + 4, y + hh + 4], radius=8,
                        fill=C_WHITE, outline=C_BORDER, width=1,
                    )
                    img.paste(overlay, (x0, y + 8))
                except Exception:
                    pass
            return y + h
        return y + h


def export_image(db, start_date, end_date, out_path):
    """导出打卡汇总长图（PNG），返回统计 dict。"""
    data = load_report_data(db, start_date, end_date)
    items = data["items"]
    done_items = data["done_items"]
    todo_items = data["todo_items"]
    questions = data["questions"]
    images_map = data["images_map"]
    qimages = data["qimages"]
    by_date = data["by_date"]
    total = data["total"]
    rate = data["rate"]
    total_secs = data["total_secs"]

    lay = _Layout()
    lay.banner(report_title(start_date, end_date), "生成时间：{} · 习惯打卡".format(
        datetime.now().strftime("%Y-%m-%d %H:%M")))
    lay.spacer(18)
    lay.stats([
        ("计划项数", str(total), C_TEXT),
        ("已完成", str(len(done_items)), C_ACCENT),
        ("完成率", "{:.0f}%".format(rate), C_PRIMARY),
        ("收录题目", str(len(questions)), C_WARNING),
        ("总学习时长", fmt_duration(total_secs), C_PRIMARY),
    ])
    lay.spacer(22)

    # 一、已完成打卡详情
    if done_items:
        lay.section("一、已完成打卡详情")
    for day in sorted(by_date):
        lay.day("{}  {}".format(day, weekday_cn(day)))
        for it in by_date[day]:
            checked = (it["checked_at"] or "")[11:16]
            elapsed = int(it.get("elapsed_seconds") or 0)
            suffix = " · 学习时长 {}".format(fmt_duration(elapsed)) if elapsed > 0 else ""
            lay.heading("{}（打卡时间 {}{}）".format(it["topic_path"], checked, suffix))
            note = (it["note"] or "").strip()
            lay.line("文字总结：{}".format(note or "（未填写）"), size=14,
                     color=C_TEXT if note else C_MUTED)
            for img in images_map.get(it["id"], []):
                abs_path = db.abs_path(img["file_path"])
                if os.path.isfile(abs_path):
                    lay.image(abs_path)
            lay.spacer(8)

    # 二、题目与解析
    if questions:
        lay.section("二、题目与解析（{} 题）".format(len(questions)))
        for q in questions:
            lay.heading("【{}】{}（{}）".format(q["code"], q["topic_path"], result_text(q)))
            lay.line("题目内容：{}".format(q["question_text"] or "（未填写）"), size=14,
                     color=C_TEXT if q["question_text"] else C_MUTED)
            lay.line("解析：{}".format(q["analysis"] or "（未填写）"), size=14,
                     color=C_TEXT if q["analysis"] else C_MUTED)
            for img in qimages.get(q["id"], []):
                abs_path = db.abs_path(img["file_path"])
                if os.path.isfile(abs_path):
                    lay.image(abs_path)
            filled = bool(
                (q.get("self_analysis") or "").strip()
                or (q.get("correct_analysis") or "").strip()
                or (q.get("reflection") or "").strip()
            )
            if q["result"] == "wrong" or filled:
                if not filled:
                    lay.line("复盘：（未填写）", size=14, color=C_MUTED)
                else:
                    lay.line("复盘：", size=14, color=C_TEXT, bold=True)
                    for label, key in (
                        ("自己的做题思路", "self_analysis"),
                        ("正确的做题思路", "correct_analysis"),
                        ("复盘心得", "reflection"),
                    ):
                        val = (q.get(key) or "").strip()
                        lay.line("　{}：{}".format(label, val or "（未填写）"), size=13,
                                 color=C_TEXT if val else C_MUTED)
            lay.spacer(8)

    # 三、未完成项
    if todo_items:
        lay.section("三、未完成项（{} 项）".format(len(todo_items)))
        for it in todo_items:
            lay.line("· {}  {}（未完成）".format(it["plan_date"], it["topic_path"]),
                     size=14, color=C_TEXT)

    lay.render(out_path)
    return {"total": total, "done": len(done_items), "rate": rate, "questions": len(questions)}


def default_filename_png(start_date, end_date):
    return _default_filename(start_date, end_date, "png")
