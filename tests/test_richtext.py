"""知识库富文本图片段落单元测试。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from habit_checkin.ui.richtext import (
    blocks_to_html,
    content_image_paths,
    html_to_plain,
    parse_rich_html,
    plain_to_html,
)


class TestRichTextImages(unittest.TestCase):
    def test_image_block_roundtrip(self):
        html = (
            "<p>题干</p>\n"
            "<p image='images/2026/abc.png'></p>\n"
            "<p indent='2'>正文</p>"
        )
        blocks = parse_rich_html(html)
        self.assertEqual(blocks[1]["image"], "images/2026/abc.png")
        self.assertEqual(blocks[1]["align"], "center")
        canonical = blocks_to_html(blocks)
        self.assertIn("image='images/2026/abc.png'", canonical)
        self.assertEqual(parse_rich_html(canonical)[1]["image"], "images/2026/abc.png")

    def test_content_image_paths_and_placeholder(self):
        html = (
            "<p>知识点</p>\n"
            "<p image='images/a.png'></p>\n"
            "<p><img src='images/b.png'></p>"
        )
        self.assertEqual(content_image_paths(html), ["images/a.png", "images/b.png"])
        plain = html_to_plain(html)
        self.assertEqual(plain.count("[图片]"), 2)
        self.assertNotIn("images/a.png", plain)

    def test_plain_to_html_escapes(self):
        self.assertEqual(plain_to_html("A < B"), "<p>A &lt; B</p>")

    def test_list_block_roundtrip(self):
        html = (
            "<p list='1'>第一条</p>\n"
            "<p list='1'><b>第二条</b></p>\n"
            "<p>普通段落</p>"
        )
        blocks = parse_rich_html(html)
        self.assertTrue(blocks[0]["list"])
        self.assertTrue(blocks[1]["list"])
        self.assertFalse(blocks[2]["list"])
        canonical = blocks_to_html(blocks)
        self.assertIn("list='1'", canonical)
        self.assertEqual(parse_rich_html(canonical)[0]["list"], True)
        self.assertEqual(parse_rich_html(canonical)[2]["list"], False)

    def test_circle_list_block_roundtrip(self):
        html = (
            "<p list='circle'>第一条</p>\n"
            "<p list='1'>第二条</p>\n"
            "<p>普通段落</p>"
        )
        blocks = parse_rich_html(html)
        self.assertEqual(blocks[0]["list"], "circle")
        self.assertTrue(blocks[1]["list"])
        self.assertFalse(blocks[2]["list"])
        canonical = blocks_to_html(blocks)
        self.assertIn("list='circle'", canonical)
        self.assertIn("list='1'", canonical)
        self.assertEqual(parse_rich_html(canonical)[0]["list"], "circle")
        self.assertEqual(parse_rich_html(canonical)[2]["list"], False)


if __name__ == "__main__":
    unittest.main()
