"""打卡图片自动收录：把图片（含 OCR 行文本）拆成题目加入题库。"""
from __future__ import annotations

from habit_checkin.services.split import split_question_lines


def collect_question_from_image(db, source_path, text, topic_id=None, source_item_id=None, analysis=""):
    """把一张图片收录为一道题（OCR 文字由调用方提供）。

    返回 (题目编号, 题目文字)。即使 OCR 未识别到文字也会入库（保留图片，
    便于后续在题库中补充题目内容）。
    """
    text = (text or "").strip()
    qid = db.add_question(
        topic_id=topic_id,
        question_text=text,
        analysis=analysis or "",
        source="checkin",
        source_item_id=source_item_id,
    )
    db.sync_question_images(qid, [], [source_path])
    q = db.get_question(qid)
    return q["code"], text


def collect_image_questions(db, source_path, lines, topic_id=None, source_item_id=None):
    """把一张图（按行 OCR 结果）拆成多道题并分别收录。

    返回 [(题目编号, 题目文字), ...]。
    """
    created = []
    for chunk in split_question_lines(lines or []):
        code, _ = collect_question_from_image(
            db, source_path, chunk["text"],
            topic_id=topic_id, source_item_id=source_item_id,
            analysis=chunk.get("analysis", ""),
        )
        created.append((code, chunk["text"]))
    return created
