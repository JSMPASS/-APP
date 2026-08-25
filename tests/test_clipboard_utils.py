"""剪贴板辅助工具单元测试（不依赖 Tk 主窗口）。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from habit_checkin.services.clipboard_utils import bind_entry_undo


class _StubEntry:
    """模拟 Entry 的 get/delete/insert，供撤销历史逻辑测试。"""

    def __init__(self, text=""):
        self._text = text

    def get(self):
        return self._text

    def delete(self, first, last):
        if last == "end":
            last = len(self._text)
        if first == "end":
            first = len(self._text)
        self._text = self._text[:first] + self._text[last:]

    def insert(self, index, chars):
        if index == "end":
            index = len(self._text)
        self._text = self._text[:index] + chars + self._text[index:]

    def bind(self, *args, **kwargs):
        return None

    def after_idle(self, callback, *args):
        return None


class TestEntryUndo(unittest.TestCase):
    def test_undo_restores_previous_states(self):
        entry = _StubEntry("初始")
        undo = bind_entry_undo(entry)
        entry.insert("end", "A")
        undo.record()
        entry.insert("end", "B")
        undo.record()
        self.assertEqual(entry.get(), "初始AB")
        undo.undo()
        self.assertEqual(entry.get(), "初始A")
        undo.undo()
        self.assertEqual(entry.get(), "初始")
        undo.undo()
        self.assertEqual(entry.get(), "初始")

    def test_paste_style_change_recorded(self):
        entry = _StubEntry("")
        undo = bind_entry_undo(entry)
        entry.insert(0, "粘贴内容")
        undo.record()
        self.assertEqual(entry.get(), "粘贴内容")
        undo.undo()
        self.assertEqual(entry.get(), "")

    def test_reset_clears_history(self):
        entry = _StubEntry("旧值")
        undo = bind_entry_undo(entry)
        entry.delete(0, "end")
        entry.insert(0, "新值")
        undo.reset()
        entry.insert("end", "X")
        undo.record()
        undo.undo()
        self.assertEqual(entry.get(), "新值")
        undo.undo()
        self.assertEqual(entry.get(), "新值")

    def test_max_depth_limits_history(self):
        entry = _StubEntry("")
        undo = bind_entry_undo(entry, max_depth=3)
        for i in range(6):
            entry.insert("end", str(i))
            undo.record()
        for _ in range(3):
            undo.undo()
        self.assertNotEqual(entry.get(), "")


if __name__ == "__main__":
    unittest.main()
