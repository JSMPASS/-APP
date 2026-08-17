# -*- coding: utf-8 -*-
"""思维导图导出：按科目导图导出 Markdown 大纲（含节点备注字段）。"""
from __future__ import annotations

_FIELD_LABELS = (
    ("recognition", "识别方法"),
    ("approach", "解题思路"),
    ("method", "解题方法"),
    ("remark", "备注"),
)


def export_mindmap_markdown(db, map_id, path):
    """把某张思维导图导出为 Markdown 大纲，返回写入路径。"""
    m = db.get_question_map(map_id)
    if not m:
        raise ValueError("思维导图不存在")
    nodes = db.question_types_by_map(map_id)
    children = {}
    for n in nodes:
        children.setdefault(n["parent_id"], []).append(n)

    lines = ["# {} 题型思维导图".format(m["subject_name"]), ""]

    def walk(pid, depth):
        for n in children.get(pid, []):
            lines.append("  " * depth + "- " + n["name"])
            for key, label in _FIELD_LABELS:
                if n.get(key):
                    lines.append("  " * (depth + 1) + "- {}：{}".format(
                        label, str(n[key]).replace("\n", " ")))
            walk(n["id"], depth + 1)

    for r in children.get(None, []):
        walk(r["id"], 0)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path
