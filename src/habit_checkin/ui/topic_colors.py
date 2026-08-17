# -*- coding: utf-8 -*-
"""按细分题型给题库/复盘列表行分配稳定的浅色背景。"""
from __future__ import annotations

# 一组低饱和浅色背景，保证深色/浅色主题下文字仍可读
TOPIC_BG_COLORS = [
    "#E8F0FE",  # 蓝
    "#E6F4EA",  # 绿
    "#FEF7E0",  # 黄
    "#FDE8E8",  # 红
    "#F3E8FD",  # 紫
    "#E0F7FA",  # 青
    "#FFF3E0",  # 橙
    "#E8F5E9",  # 浅绿
    "#FCE4EC",  # 粉
    "#E8EAF6",  # 靛
    "#F1F8E9",  # 草绿
    "#FFF8E1",  # 淡黄
    "#EDE7F6",  # 淡紫
    "#E0F2F1",  # 浅青
    "#FBE9E7",  # 浅橙
    "#EFEBE9",  # 棕灰
]


def topic_tag(topic_id):
    """返回 Treeview 行 tag 名；未分类返回 None。"""
    if topic_id is None:
        return None
    return "bg_t{}".format(int(topic_id))


def topic_bg_color(topic_id):
    """根据 topic_id 稳定返回一个浅色背景。"""
    if topic_id is None:
        return "#FFFFFF"
    return TOPIC_BG_COLORS[int(topic_id) % len(TOPIC_BG_COLORS)]


def configure_topic_tags(tree, items):
    """给 Treeview 配置本次结果中出现的细分题型背景 tag。"""
    seen = set()
    for it in items or []:
        tid = it.get("topic_id")
        if tid is None or tid in seen:
            continue
        seen.add(tid)
        tag = topic_tag(tid)
        if tag:
            tree.tag_configure(tag, background=topic_bg_color(tid))
