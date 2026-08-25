"""打卡「基本知识」图片的 OCR 拆分：按标题 / 段落还原为多个知识点。

OCR 结果只作预填，用户在预览弹窗中确认、修改后再写入知识库。
"""
from __future__ import annotations

import re

from habit_checkin.services.ocr import cleanup_cjk_spaces, ocr_image_lines, ocr_structured_blocks

_WS_RE = re.compile(r"\s+")
_CN_NUM_RE = re.compile(r"^[一二三四五六七八九十]+、")
_PAREN_NUM_RE = re.compile(r"^[（(]\s*\d+\s*[）)]")
_DOT_NUM_RE = re.compile(r"^\d+\s*[.．、，]")
_SECTION_RE = re.compile(r"^(第[一二三四五六七八九十\d]+[章节部分]|[一二三四五六七八九十]+[章节部分])")
_KEYWORD_HEAD_RE = re.compile(r"^(公式|技巧|方法|要点|重点|考点|结论|注意|提示|补充|定义|概念|题型|口诀|常见错误|易错点|解题步骤)$")
_SHORT_HEAD_RE = re.compile(r"^.{1,18}[:：]$")
_TITLE_LABELS = frozenset({
    "paragraph_title", "doc_title", "abstract",
    "table_title", "figure_title", "title",
})
_SKIP_LABELS = frozenset({
    "header", "footer", "number", "footnote", "formula_number",
    "image", "figure", "seal", "header_image", "footer_image", "aside_text",
})


def _clean(line):
    return _WS_RE.sub(" ", (line or "").strip()).strip()


def _is_heading(line):
    t = _clean(line)
    if not t:
        return False
    if len(t) <= 30 and (
        _CN_NUM_RE.match(t)
        or _PAREN_NUM_RE.match(t)
        or _DOT_NUM_RE.match(t)
        or _SECTION_RE.match(t)
        or _KEYWORD_HEAD_RE.match(t)
    ):
        return True
    # 独立短标题行（带冒号且不含句号，多为小标题）
    if (_SHORT_HEAD_RE.match(t) and "。" not in t and "，" not in t and "！" not in t
            and "？" not in t and "=" not in t and " " not in t and len(t) <= 24):
        return True
    return False


def _plain_lines_to_html(lines):
    """把纯文本段落转为知识库使用的轻量 HTML（换行分段）。"""
    from html import escape
    paras = []
    for raw in lines or []:
        t = _clean(raw)
        if t:
            paras.append("<p>{}</p>".format(escape(t)))
    return "\n".join(paras)


def _parts_to_html(parts):
    """把结构化正文段落转为轻量 HTML；加粗行用于还原被折叠的页面大标题。"""
    from html import escape
    rows = []
    for part in parts:
        bold = bool(part.get("bold")) if isinstance(part, dict) else False
        text = part.get("text") if isinstance(part, dict) else part
        for raw in (text or "").splitlines():
            line = _clean(raw)
            if not line:
                continue
            t = escape(line)
            rows.append("<p><b>{}</b></p>".format(t) if bold else "<p>{}</p>".format(t))
    return "\n".join(rows)


def structured_knowledge_blocks(records):
    """把 PP-StructureV3 布局记录还原成知识块。

    - paragraph_title/doc_title 等标题开始新块；
    - 连续标题（如页面大标题后接小节标题）合并，前一个标题作为正文加粗行；
    - header/footer/页码/图片等噪声块直接跳过。
    返回 [{"title": str, "content": html}, ...]。
    """
    blocks = []
    cur = None
    for rec in records or []:
        label = (rec.get("label") or "").lower()
        if label in _SKIP_LABELS:
            continue
        content = _clean(cleanup_cjk_spaces(rec.get("content") or ""))
        if not content:
            continue
        if label in _TITLE_LABELS:
            if cur is not None and not cur["parts"]:
                if content == cur["title"]:
                    continue
                cur["parts"].append({"text": cur["title"], "bold": True})
                cur["title"] = content
                continue
            if cur is not None:
                blocks.append(cur)
            cur = {"title": content, "parts": []}
            continue
        if cur is None:
            cur = {"title": "知识点", "parts": []}
        if cur["title"] == content and not cur["parts"]:
            continue
        if cur["parts"] and cur["parts"][-1].get("text") == content:
            continue
        cur["parts"].append({"text": content, "bold": False})
    if cur is not None:
        blocks.append(cur)
    return [
        {"title": b["title"], "content": _parts_to_html(b["parts"])}
        for b in blocks
    ]

def split_knowledge_lines(lines):
    """把 OCR 行列表拆成知识点块，返回 [{"title": str, "content": str}, ...]。

    识别不到标题时退回单个知识点，保证不丢内容。
    """
    cleaned = [_clean(l) for l in (lines or [])]
    cleaned = [l for l in cleaned if l]
    if not cleaned:
        return []

    headings = []
    for i, line in enumerate(cleaned):
        if _is_heading(line):
            headings.append(i)
    if not headings:
        return [{"title": "知识点", "content": _plain_lines_to_html(cleaned)}]

    blocks = []
    intro = cleaned[: headings[0]]
    for k, start in enumerate(headings):
        end = headings[k + 1] if k + 1 < len(headings) else len(cleaned)
        title = cleaned[start].rstrip("：: ")
        body = cleaned[start + 1:end]
        # 开头没有标题的内容并入第一个知识块，避免遗漏
        if k == 0 and intro:
            body = intro + body
        blocks.append({"title": title, "content": _plain_lines_to_html(body)})
    return blocks


def ocr_knowledge_document(path, timeout=25):
    """识别一张知识图片并拆成知识点块；失败返回 (None, None)。

    优先用 PP-StructureV3 按页面布局还原标题/正文结构，失败时回退普通行 OCR。
    """
    try:
        records = ocr_structured_blocks(path)
        if records:
            blocks = structured_knowledge_blocks(records)
            if blocks:
                return path, blocks
    except Exception:
        pass
    lines = ocr_image_lines(path, timeout=timeout, keep_marks=True)
    if not lines:
        return None, None
    return path, split_knowledge_lines(lines)
