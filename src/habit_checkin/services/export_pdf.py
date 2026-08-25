"""PDF 导出：与 Word 导出内容一致，使用 reportlab + STSong-Light 中文字体（离线可用）。

文档结构：标题 -> 统计表 -> 已完成项详情 -> 题目与解析（含错题反思）-> 未完成项列表。
"""
from __future__ import annotations

import os
import shutil
import tempfile
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from habit_checkin.services.export_common import (
    default_filename as _default_filename,
    fmt_duration,
    load_report_data,
    prepare_image,
    report_title,
    result_text,
    weekday_cn,
)
from habit_checkin.ui.richtext import to_plain

_FONT = "STSong-Light"


def _ensure_font():
    try:
        pdfmetrics.getFont(_FONT)
    except Exception:
        pdfmetrics.registerFont(UnicodeCIDFont(_FONT))


_STYLES = {
    "title": ParagraphStyle("title", fontName=_FONT, fontSize=18, leading=24, alignment=1, spaceAfter=4),
    "subtitle": ParagraphStyle("subtitle", fontName=_FONT, fontSize=9, leading=13, alignment=1,
                               textColor=colors.HexColor("#808080"), spaceAfter=12),
    "h1": ParagraphStyle("h1", fontName=_FONT, fontSize=14, leading=20, spaceBefore=10, spaceAfter=6),
    "h2": ParagraphStyle("h2", fontName=_FONT, fontSize=12, leading=18, spaceBefore=8, spaceAfter=4,
                         textColor=colors.HexColor("#2E74B5")),
    "h3": ParagraphStyle("h3", fontName=_FONT, fontSize=12, leading=17, spaceBefore=6, spaceAfter=3),
    "body": ParagraphStyle("body", fontName=_FONT, fontSize=10.5, leading=16),
    "note": ParagraphStyle("note", fontName=_FONT, fontSize=10.5, leading=16, leftIndent=14),
}


def _esc(text):
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _add_image(story, abs_path, tmpdir):
    if not os.path.isfile(abs_path):
        return
    try:
        p, w, h = _prepare_image(abs_path, tmpdir)
        max_w = 14 * cm
        if w > 0:
            scale = min(max_w / float(w), 1.0)
            w, h = w * scale, h * scale
        story.append(Image(p, width=w, height=h))
    except Exception:
        pass


def export_pdf(db, start_date, end_date, out_path):
    """导出打卡汇总文档（PDF），返回统计 dict。"""
    _ensure_font()
    data = load_report_data(db, start_date, end_date)
    items = data["items"]
    done_items = data["done_items"]
    todo_items = data["todo_items"]
    questions = data["questions"]
    images_map = data["images_map"]
    qimages = data["qimages"]
    by_date = data["by_date"]

    doc = SimpleDocTemplate(
        out_path, pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.8 * cm, bottomMargin=1.8 * cm,
        title="打卡情况汇总", author="习惯打卡",
    )
    story = []
    story.append(Paragraph(_esc(report_title(start_date, end_date)), _STYLES["title"]))
    story.append(Paragraph(_esc("生成时间：{}".format(datetime.now().strftime("%Y-%m-%d %H:%M"))), _STYLES["subtitle"]))

    total = data["total"]
    rate = data["rate"]
    total_secs = data["total_secs"]
    table_data = [
        ["计划项数", "已完成", "完成率", "收录题目", "总学习时长"],
        [str(total), str(len(done_items)), "{:.1f}%".format(rate),
         str(len(questions)), fmt_duration(total_secs)],
    ]
    tbl = Table(table_data, colWidths=[3.0 * cm] * 5)
    tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), _FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 10.5),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EFF3F9")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D8E0EA")),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 10))

    tmpdir = tempfile.mkdtemp(prefix="habit_pdf_")
    try:
        # 一、已完成打卡详情
        if done_items:
            story.append(Paragraph("一、已完成打卡详情", _STYLES["h1"]))
        for day in sorted(by_date):
            story.append(Paragraph(_esc("{}  {}".format(day, weekday_cn(day))), _STYLES["h2"]))
            for it in by_date[day]:
                checked = (it["checked_at"] or "")[11:16]
                elapsed = int(it.get("elapsed_seconds") or 0)
                suffix = " · 学习时长 {}".format(fmt_duration(elapsed)) if elapsed > 0 else ""
                story.append(Paragraph(_esc("{}（打卡时间 {}{}）".format(it["topic_path"], checked, suffix)), _STYLES["h3"]))
                note = to_plain(it.get("note") or "").strip()
                story.append(Paragraph("文字总结：" + _esc(note or "（未填写）"), _STYLES["body"]))
                for img in images_map.get(it["id"], []):
                    _add_image(story, db.abs_path(img["file_path"]), tmpdir)

        # 二、题目与解析
        if questions:
            story.append(Paragraph("二、题目与解析（{} 题）".format(len(questions)), _STYLES["h1"]))
            for q in questions:
                story.append(Paragraph(
                    "【{}】{}（{}）".format(_esc(q["code"]), _esc(q["topic_path"]), _esc(result_text(q))),
                    _STYLES["h3"],
                ))
                story.append(Paragraph(
                    "题目内容：" + _esc(to_plain(q.get("question_text") or "").strip() or "（未填写）"),
                    _STYLES["body"],
                ))
                story.append(Paragraph(
                    "解析：" + _esc(to_plain(q.get("analysis") or "").strip() or "（未填写）"),
                    _STYLES["body"],
                ))
                for img in qimages.get(q["id"], []):
                    _add_image(story, db.abs_path(img["file_path"]), tmpdir)
                filled = bool(
                    to_plain(q.get("self_analysis") or "").strip()
                    or to_plain(q.get("correct_analysis") or "").strip()
                    or to_plain(q.get("reflection") or "").strip()
                )
                if q["result"] == "wrong" or filled:
                    if not filled:
                        story.append(Paragraph("复盘：（未填写）", _STYLES["body"]))
                    else:
                        story.append(Paragraph("复盘：", _STYLES["body"]))
                        for label, key in (
                            ("自己的做题思路", "self_analysis"),
                            ("正确的做题思路", "correct_analysis"),
                            ("复盘心得", "reflection"),
                        ):
                            val = to_plain(q.get(key) or "").strip()
                            story.append(Paragraph(
                                "　{}：{}".format(label, _esc(val or "（未填写）")), _STYLES["note"]
                            ))

        # 三、未完成项
        if todo_items:
            story.append(Paragraph("三、未完成项（{} 项）".format(len(todo_items)), _STYLES["h1"]))
            for it in todo_items:
                story.append(Paragraph(
                    "· {}  {}（未完成）".format(_esc(it["plan_date"]), _esc(it["topic_path"])), _STYLES["body"]
                ))

        doc.build(story)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    return {"total": total, "done": len(done_items), "rate": rate, "questions": len(questions)}


def default_filename_pdf(start_date, end_date):
    return _default_filename(start_date, end_date, "pdf")
