"""服务层单元测试：OCR 空格清理、激励语、打卡图片自动收录。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from habit_checkin.db import Database
from habit_checkin.services.collect import collect_image_questions, collect_question_from_image
from habit_checkin.services.motivation import random_quote
from habit_checkin.services import ocr as ocr_module
from habit_checkin.services.ocr import cleanup_cjk_spaces, format_questions_text, parse_ocr_questions, preprocess_for_ocr, reconstruct_page


class TestOcrCleanup(unittest.TestCase):
    def test_cjk_spaces_removed(self):
        self.assertEqual(cleanup_cjk_spaces("资 料 分 析 增 长 率"), "资料分析增长率")
        self.assertEqual(cleanup_cjk_spaces("行测 数量关系"), "行测数量关系")
        self.assertEqual(cleanup_cjk_spaces("A B C"), "A B C")
        self.assertEqual(cleanup_cjk_spaces("第 1 7 题"), "第17题")
        self.assertEqual(cleanup_cjk_spaces("2023 年"), "2023年")

    def test_empty(self):
        self.assertEqual(cleanup_cjk_spaces(""), "")
        self.assertEqual(cleanup_cjk_spaces(None), "")


class TestOcrPreprocess(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.img = self.root / "pre.png"
        from PIL import Image
        Image.new("RGB", (40, 20), "white").save(self.img)

    def tearDown(self):
        self.tmp.cleanup()

    def test_preprocess_returns_unique_temp_files(self):
        p1 = preprocess_for_ocr(str(self.img))
        p2 = preprocess_for_ocr(str(self.img))
        try:
            self.assertNotEqual(p1, p2)
            self.assertTrue(Path(p1).is_file())
            self.assertTrue(Path(p2).is_file())
        finally:
            Path(p1).unlink(missing_ok=True)
            Path(p2).unlink(missing_ok=True)

    def test_ocr_image_lines_removes_temp_file(self):
        fake = self.root / "fake_pre.png"
        fake.write_bytes(b"x")
        with mock.patch.object(ocr_module, "preprocess_for_ocr", return_value=str(fake)), \
                mock.patch.object(ocr_module, "_run_ocr", return_value=[(0, 0, "hello")]):
            lines = ocr_module.ocr_image_lines(str(self.img))
        self.assertEqual(lines, ["hello"])
        self.assertFalse(fake.exists())


class TestOcrParse(unittest.TestCase):
    def test_split_questions(self):
        lines = [
            "1. 世界上面积最大的国家是",
            "A. 俄罗斯", "B. 加拿大", "C. 中国", "D. 美国",
            "3. 下列属于内陆国家的是",
            "A. 哈萨克斯坦", "B. 印度", "C. 蒙古",
        ]
        qs = parse_ocr_questions(lines)
        self.assertEqual(len(qs), 2)
        self.assertEqual(qs[0]["num"], 1)
        self.assertIn("俄罗斯", qs[0]["options"][0])
        self.assertEqual(qs[1]["num"], 3)
        self.assertEqual(len(qs[1]["options"]), 3)
        fmt = format_questions_text(qs)
        self.assertIn("1. 世界上面积最大的国家是", fmt)
        self.assertIn("A. 俄罗斯", fmt)
        self.assertIn("\n\n", fmt)

    def test_loose_qnum_and_annotation_skip(self):
        lines = ["1世界上面积最大的国家是", "A. 俄罗斯 B. 加拿大",
                 "2，下列属于内陆国家的是", "错题", "A. 哈萨克斯坦"]
        qs = parse_ocr_questions(lines)
        self.assertEqual(len(qs), 2)
        self.assertEqual(qs[0]["num"], 1)
        self.assertEqual(qs[1]["num"], 2)
        self.assertNotIn("错题", qs[1]["stem"])
        # 年份不应被误判为题号
        qs2 = parse_ocr_questions(["2023年辽宁省考行测真题", "A. 正确"])
        self.assertIsNone(qs2[0]["num"])

    def test_split_inline_options(self):
        lines = ["1. 世界上面积最大的国家是", "A. 俄罗斯    B. 加拿大    C. 中国    D. 美国"]
        qs = parse_ocr_questions(lines)
        self.assertEqual(qs[0]["options"],
                         ["A. 俄罗斯", "B. 加拿大", "C. 中国", "D. 美国"])
        fmt = format_questions_text(qs)
        self.assertIn("A. 俄罗斯\nB. 加拿大\nC. 中国\nD. 美国", fmt)

    def test_split_fullwidth_and_stem_continuation(self):
        lines = ["１．尼罗河是世界第一长河", "也是文明发祥地", "Ａ．可发电", "Ｂ．可通航"]
        qs = parse_ocr_questions(lines)
        self.assertEqual(len(qs), 1)
        self.assertEqual(qs[0]["num"], 1)
        self.assertIn("文明发祥地", qs[0]["stem"])
        self.assertEqual(len(qs[0]["options"]), 2)
        self.assertTrue(qs[0]["options"][0].startswith("A. "))


class TestReconstruct(unittest.TestCase):
    def test_reconstruct_page(self):
        lines = [
            "l. 5 · 江苏）本土药材：野生药材：名贵药材",
            "人．沿海高铁：跨省高铁：城际高铁",
            "B. 牛奶产业：传统产业：养殖产业",
            "C. 超限车辆：超载车辆：超重车辆",
            "D. 社区治理：社会治理：水上治理",
            "2．（2024 · 四川）政治家：军事家：曹操",
            "lD ，固体：食品：苹果",
            "B. 直辖市：港深：北京",
        ]
        qs = reconstruct_page(lines)
        self.assertIsNotNone(qs)
        self.assertEqual(len(qs), 2)
        self.assertEqual(qs[0]["num"], 1)
        self.assertEqual(qs[1]["num"], 2)
        self.assertEqual(len(qs[0]["options"]), 4)
        self.assertIn("沿海高铁", qs[0]["options"][0])
        self.assertTrue(qs[0]["options"][0].startswith("A. "))
        self.assertIn("江苏", qs[0]["stem"])
        self.assertIn("固体", qs[1]["options"][0])

    def test_reconstruct_rejects_nonregular(self):
        lines = ["这是一段普通文字", "没有结构"]
        self.assertIsNone(reconstruct_page(lines))


class TestMotivation(unittest.TestCase):
    def test_random_quote(self):
        q = random_quote()
        self.assertIsInstance(q, str)
        self.assertTrue(q)


class TestCollectImageQuestions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = Database(self.root / "app.db", self.root / "images", self.root)
        self.img = self.root / "q.png"
        from PIL import Image
        Image.new("RGB", (10, 10), "white").save(self.img)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_collect_splits_multi_question_lines(self):
        lines = ["1. 第一题", "A. 甲", "2. 第二题", "A. 乙"]
        created = collect_image_questions(
            self.db, str(self.img), lines, topic_id=None, source_item_id=9
        )
        self.assertEqual(len(created), 2)
        qs = self.db.list_questions()
        self.assertEqual(len(qs), 2)
        self.assertEqual([q["source_item_id"] for q in qs], [9, 9])
        self.assertEqual({q["question_text"] for q in qs}, {"1. 第一题\nA. 甲", "2. 第二题\nA. 乙"})


class TestCollectQuestionFromImage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = Database(self.root / "app.db", self.root / "images", self.root)
        self.img = self.root / "q.png"
        from PIL import Image
        Image.new("RGB", (10, 10), "white").save(self.img)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_collect_creates_question_with_image(self):
        code, text = collect_question_from_image(
            self.db, str(self.img), "例题：1+1=？", topic_id=None, source_item_id=7
        )
        self.assertTrue(code.startswith("Q"))
        q = self.db.get_question(self.db.list_questions()[0]["id"])
        self.assertEqual(q["code"], code)
        self.assertEqual(q["question_text"], "例题：1+1=？")
        self.assertEqual(q["source"], "checkin")
        self.assertEqual(q["source_item_id"], 7)
        self.assertEqual(len(q["images"]), 1)
        self.assertTrue(Path(self.db.abs_path(q["images"][0]["file_path"])).is_file())

    def test_collect_empty_text_keeps_image(self):
        code, text = collect_question_from_image(self.db, str(self.img), "  ", source_item_id=1)
        self.assertEqual(text, "")
        q = self.db.get_question(self.db.list_questions()[0]["id"])
        self.assertEqual(q["question_text"], "")
        self.assertEqual(len(q["images"]), 1)


if __name__ == "__main__":
    unittest.main()
