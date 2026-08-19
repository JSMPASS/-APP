# -*- coding: utf-8 -*-
"""备考进度页单项编辑弹窗：统一字段编辑组件的兼容封装。"""
from __future__ import annotations

from habit_checkin.ui.field_edit_dialog import FieldEditDialog, ask_fields


def ask_plan_item(master, title, fields):
    """弹出单项编辑框，返回 {key: value}；用户取消时返回 None。"""
    return ask_fields(
        master, title, fields,
        subtitle="修改后将同步到已导入的计划文档",
    )


class PlanItemEditDialog(FieldEditDialog):
    """兼容旧引用：统一字段编辑弹窗。"""

    def __init__(self, master, title, fields):
        super().__init__(
            master, title, fields,
            subtitle="修改后将同步到已导入的计划文档",
        )
