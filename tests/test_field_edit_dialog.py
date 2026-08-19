"""统一字段编辑弹窗的校验逻辑测试（不依赖 Tk 主窗口）。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from habit_checkin.ui.field_edit_dialog import FieldEditDialog


class TestFieldEditValidation(unittest.TestCase):
    """验证 _validate_values 的类型转换、必填与范围校验。"""

    def _dialog(self, fields):
        dlg = FieldEditDialog.__new__(FieldEditDialog)
        dlg.fields = fields
        return dlg

    def _basic_fields(self):
        return [
            {"key": "name", "label": "名称", "required": True},
            {"key": "count", "label": "数量", "type": "integer",
             "min": 1, "max": 10, "required": True},
            {"key": "start", "label": "开始时间", "type": "time"},
            {"key": "day", "label": "日期", "type": "date"},
            {"key": "category", "label": "分类", "type": "choice",
             "choices": ["A", "B"], "required": True},
            {"key": "enabled", "label": "启用", "type": "bool"},
        ]

    def test_valid_values_are_converted(self):
        dlg = self._dialog(self._basic_fields())
        values = {
            "name": "资料分析",
            "count": "9",
            "start": "9:05",
            "day": "2026-08-17",
            "category": "B",
            "enabled": True,
        }
        errors = dlg._validate_values(values)
        self.assertEqual(errors, [])
        self.assertEqual(values["count"], 9)
        self.assertEqual(values["start"], "09:05")
        self.assertEqual(values["day"], "2026-08-17")
        self.assertIs(values["enabled"], True)

    def test_required_fields_reported(self):
        dlg = self._dialog(self._basic_fields())
        values = {
            "name": "",
            "count": "",
            "start": "",
            "day": "",
            "category": "",
            "enabled": False,
        }
        errors = dlg._validate_values(values)
        keys = {key for key, _ in errors}
        self.assertIn("name", keys)
        self.assertIn("count", keys)
        self.assertIn("category", keys)

    def test_empty_optional_integer_becomes_none(self):
        dlg = self._dialog([{"key": "target", "label": "目标", "type": "integer"}])
        values = {"target": ""}
        errors = dlg._validate_values(values)
        self.assertEqual(errors, [])
        self.assertIsNone(values["target"])

    def test_integer_range_and_format(self):
        dlg = self._dialog([
            {"key": "count", "label": "数量", "type": "integer",
             "min": 1, "max": 10, "required": True},
        ])
        errors = dlg._validate_values({"count": "abc"})
        self.assertEqual([k for k, _ in errors], ["count"])
        errors = dlg._validate_values({"count": "0"})
        self.assertEqual([k for k, _ in errors], ["count"])
        errors = dlg._validate_values({"count": "11"})
        self.assertEqual([k for k, _ in errors], ["count"])

    def test_time_and_date_format(self):
        dlg = self._dialog([
            {"key": "start", "label": "时间", "type": "time", "required": True},
            {"key": "day", "label": "日期", "type": "date", "required": True},
        ])
        errors = dlg._validate_values({"start": "25:00", "day": "2026/08/17"})
        self.assertEqual({k for k, _ in errors}, {"start", "day"})

    def test_choice_must_be_in_options(self):
        dlg = self._dialog([
            {"key": "category", "label": "分类", "type": "choice",
             "choices": ["A", "B"], "required": True},
        ])
        errors = dlg._validate_values({"category": "C"})
        self.assertEqual([k for k, _ in errors], ["category"])

    def test_multiline_keeps_text(self):
        dlg = self._dialog([{"key": "note", "label": "总结", "type": "multiline"}])
        values = {"note": "第一行\n第二行"}
        errors = dlg._validate_values(values)
        self.assertEqual(errors, [])
        self.assertEqual(values["note"], "第一行\n第二行")


if __name__ == "__main__":
    unittest.main()
