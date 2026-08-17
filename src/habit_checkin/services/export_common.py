"""报告导出公共工具：时长格式化、题目对错文本、报告数据与图片预处理。"""
from __future__ import annotations

import os
import tempfile
from datetime import date


def fmt_duration(seconds):
    """把秒数格式化为中文时长，如 1小时05分 / 08分32秒 / 45秒。"""
    seconds = max(0, int(seconds or 0))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return "{}小时{:02d}分".format(h, m)
    if m:
        return "{}分{:02d}秒".format(m, s)
    return "{}秒".format(s)


def fmt_clock(seconds):
    """把秒数格式化为 HH:MM:SS（计时器显示用）。"""
    seconds = max(0, int(seconds or 0))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return "{:02d}:{:02d}:{:02d}".format(h, m, s)
    return "{:02d}:{:02d}".format(m, s)


def result_text(q):
    """题目的对错显示文本（含原因）。"""
    mapping = {"correct": "正确", "wrong": "错误"}
    label = mapping.get((q or {}).get("result"), "未判定")
    reason = ((q or {}).get("result_reason") or "").strip()
    if reason:
        label += " · " + reason
    return label


def weekday_cn(day_str):
    """把 YYYY-MM-DD 转成「周X」；解析失败返回空串。"""
    try:
        d = date.fromisoformat(day_str)
    except (ValueError, TypeError):
        return ""
    return "星期" + "一二三四五六日"[d.weekday()]


def report_title(start_date, end_date):
    """生成导出报告标题。"""
    if start_date == end_date:
        return "打卡情况汇总（{}）".format(start_date)
    return "打卡情况汇总（{} 至 {}）".format(start_date, end_date)


def default_filename(start_date, end_date, ext):
    """生成带日期范围的默认导出文件名。"""
    if start_date == end_date:
        return "打卡情况_{}.{}".format(start_date, ext)
    return "打卡情况_{}_{}.{}".format(start_date, end_date, ext)


def prepare_image(src_path, tmpdir, max_side=1600):
    """压缩图片到长边 <= max_side，返回 (临时jpg路径, 宽, 高)。"""
    from PIL import Image
    img = Image.open(src_path)
    w, h = img.size
    if max(w, h) > max_side:
        ratio = max_side / float(max(w, h))
        w, h = int(w * ratio), int(h * ratio)
        img = img.resize((w, h), Image.LANCZOS)
    if img.mode in ("RGBA", "P", "LA"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        bg.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")
    fd, path = tempfile.mkstemp(suffix=".jpg", dir=tmpdir)
    os.close(fd)
    img.save(path, "JPEG", quality=88)
    img.close()
    return path, w, h


def load_report_data(db, start_date, end_date):
    """一次取齐三种导出格式共用的报告数据。"""
    items = db.query_items(start_date, end_date)
    done_items = [it for it in items if it["done"]]
    todo_items = [it for it in items if not it["done"]]
    questions = db.list_questions(start_date=start_date, end_date=end_date)
    images_map = db.query_images_for_items([it["id"] for it in items])
    qimages = {q["id"]: db.get_question_images(q["id"]) for q in questions}
    by_date = {}
    for it in done_items:
        by_date.setdefault(it["plan_date"], []).append(it)
    total = len(items)
    rate = (len(done_items) / total * 100) if total else 0.0
    total_secs = sum(int(it.get("elapsed_seconds") or 0) for it in done_items)
    return {
        "items": items,
        "done_items": done_items,
        "todo_items": todo_items,
        "questions": questions,
        "images_map": images_map,
        "qimages": qimages,
        "by_date": by_date,
        "total": total,
        "rate": rate,
        "total_secs": total_secs,
    }
