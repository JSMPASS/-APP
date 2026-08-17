"""把 OCR 出的多行文本拆分成一道道题目。

公考/行测截图常见"一图多题"：每道题以「（20XX·省份）题干」或「1. 题干」开头，
末尾可能有「答案速览 ABC…」。本模块基于行文本做边界识别，尽量稳健地拆开；
识别不出多题时退回"整图一道题"，保证不丢内容。
"""
from __future__ import annotations

import re

_DIGIT_SPACE_RE = re.compile(r"(\d)\s+(\d)")
_WS_RE = re.compile(r"\s+")

# 年份标记（行首，可带题号前缀/括号），如：
#   （2017·天津）… / 3，（2017·河南）… / 4．2020·浙江）…
#   17·辽宁）… / 019·江苏）… / 5．20]8·吉林）…
_YEAR_MARK_RE = re.compile(
    r"^(?:[（(]\s*)?(?:\d{1,2}\s*[.．、，,)]\s*[（(]?\s*)?"
    r"\d{2,4}\s*[^·\u4e00-\u9fff]{0,4}\s*[·.．]\s*[\u4e00-\u9fff]{1,6}"
)
_NUMBER_RE = re.compile(r"^\d{1,2}\s*[.．、，,):：)]")
_ANSWER_SAME_RE = re.compile(r"^答案(?:速览)?\s*[:：]?\s*([A-Da-d]{1,20})$")
_ANSWER_HEAD_RE = re.compile(r"^答案(?:速览)?\s*[:：]?$")
_ANSWER_LETTERS_RE = re.compile(r"^[A-Da-d]{1,20}$")
_BARE_NUM_RE = re.compile(r"^\d{1,2}\s*[.．、，,):：)]?\s*$")


def _norm(line):
    """边界判断用：折叠空白、去掉数字间空格。"""
    t = _WS_RE.sub(" ", (line or "").strip())
    return _DIGIT_SPACE_RE.sub(r"\1\2", t)


def _is_year_start(line):
    return bool(_YEAR_MARK_RE.match(line))


def _is_number_start(line):
    return bool(_NUMBER_RE.match(line))


def _extract_answer_key(lines):
    """返回 (答案串, 答案起始行号)；没有则为 (None, None)。"""
    n = len(lines)
    for i, l in enumerate(lines):
        m = _ANSWER_SAME_RE.match(l)
        if m:
            return m.group(1).upper(), i
    for i, l in enumerate(lines):
        if _ANSWER_HEAD_RE.match(l) and i + 1 < n:
            m = _ANSWER_LETTERS_RE.match(lines[i + 1])
            if m:
                return m.group(0).upper(), i
    for i in range(n - 1, -1, -1):
        if _ANSWER_LETTERS_RE.match(lines[i]) and len(lines[i].strip()) >= 2:
            return lines[i].strip().upper(), i
    return None, None


def _move_trailing_numbers(groups):
    """把上一组末尾游离的题号行（如 "5，"）挪到下一组开头。"""
    out = [list(g) for g in groups]
    for i in range(len(out) - 1):
        g = out[i]
        if g and _BARE_NUM_RE.match(g[-1]):
            out[i + 1].insert(0, g.pop())
    return [g for g in out if g]


def split_question_lines(lines):
    """把行列表拆成题目列表，返回 [{"text": ..., "analysis": ...}, ...]。

    识别不出多道题时返回整图作为一道题（analysis 可能带答案）。
    """
    cleaned = [_norm(l) for l in (lines or [])]
    cleaned = [l for l in cleaned if l]
    if not cleaned:
        return []

    key, cut = _extract_answer_key(cleaned)
    body = cleaned[:cut] if cut is not None else cleaned

    starts = [i for i, l in enumerate(body) if _is_year_start(l)]
    if not starts:
        starts = [i for i, l in enumerate(body) if _is_number_start(l)]
    if not starts:
        text = "\n".join(body).strip()
        if not text:
            return []
        item = {"text": text, "analysis": ""}
        if key:
            item["analysis"] = ("【答案】" + key if len(key) == 1 else "【答案速览】" + key)
        return [item]

    bounds = starts if starts[0] == 0 else [0] + starts
    groups = []
    for idx, i in enumerate(bounds):
        j = bounds[idx + 1] if idx + 1 < len(bounds) else len(body)
        groups.append(body[i:j])
    groups = _move_trailing_numbers(groups)

    result = []
    for g in groups:
        text = "\n".join(g).strip()
        if text:
            result.append({"text": text, "analysis": ""})
    if not result:
        return []

    if key:
        if len(key) == len(result):
            for idx, it in enumerate(result):
                it["analysis"] = "【答案】" + key[idx]
        else:
            result[-1]["analysis"] = "【答案速览】" + key
    return result
