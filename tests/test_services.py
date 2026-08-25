"""服务层单元测试：OCR 空格清理、激励语、打卡图片自动收录。"""
from __future__ import annotations

import os
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
from habit_checkin.services.knowledge_split import structured_knowledge_blocks
from habit_checkin.services import plan_docs


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
        with mock.patch.dict(
            "os.environ", {"HABIT_OCR_ENGINE": "winrt"}, clear=False
        ), mock.patch.object(ocr_module, "preprocess_for_ocr", return_value=str(fake)), \
                mock.patch.object(ocr_module, "_run_ocr", return_value=[(0, 0, "hello")]):
            lines = ocr_module.ocr_image_lines(str(self.img))
        self.assertEqual(lines, ["hello"])
        self.assertFalse(fake.exists())

    def test_poly_to_xy(self):
        poly = [(10, 20), (110, 22), (112, 62), (12, 60)]
        self.assertEqual(ocr_module._poly_to_xy(poly, None), (10, 20))
        self.assertEqual(ocr_module._poly_to_xy(None, [5, 7]), (5, 7))
        self.assertEqual(ocr_module._poly_to_xy(None, None), (0, 0))


class TestOcrModelRoot(unittest.TestCase):
    def tearDown(self):
        ocr_module.set_model_root("")

    def test_default_root_points_to_data_models(self):
        root = ocr_module.default_model_root()
        self.assertTrue(root.endswith(str(Path("data") / "models")))

    def test_set_model_root_overrides_resolution(self):
        ocr_module.set_model_root("D:\\ocr_models")
        self.assertEqual(ocr_module._resolve_model_root(), "D:\\ocr_models")
        det, rec, layout = ocr_module._paddle_dirs()[1:]
        self.assertEqual(det, "D:\\ocr_models\\PP-OCRv5_server_det")
        self.assertEqual(rec, "D:\\ocr_models\\PP-OCRv5_server_rec")
        self.assertEqual(layout, "D:\\ocr_models\\PicoDet-S_layout_17cls")

    def test_reset_restores_default(self):
        ocr_module.set_model_root("D:\\ocr_models")
        ocr_module.set_model_root("")
        self.assertEqual(
            ocr_module._resolve_model_root(), ocr_module.default_model_root()
        )

    def test_env_var_fallback(self):
        with mock.patch.dict(
            "os.environ", {"HABIT_OCR_MODEL_ROOT": "E:\\models"}, clear=False
        ):
            self.assertEqual(ocr_module._resolve_model_root(), "E:\\models")


class TestOcrDeviceAndEngine(unittest.TestCase):
    def tearDown(self):
        ocr_module.set_device("cpu")
        ocr_module.set_engine("paddle")

    def test_default_device_is_cpu(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(ocr_module._paddle_device(), "cpu")

    def test_set_device_cuda(self):
        ocr_module.set_device("cuda")
        self.assertEqual(ocr_module._paddle_device(), "gpu")

    def test_set_device_gpu_alias(self):
        ocr_module.set_device("gpu")
        self.assertEqual(ocr_module._paddle_device(), "gpu")

    def test_set_device_cpu_clears_env(self):
        ocr_module.set_device("cuda")
        ocr_module.set_device("cpu")
        self.assertEqual(ocr_module._paddle_device(), "cpu")

    def test_set_engine_winrt(self):
        ocr_module.set_engine("winrt")
        self.assertEqual(os.environ.get("HABIT_OCR_ENGINE"), "winrt")

    def test_set_engine_back_to_paddle(self):
        ocr_module.set_engine("winrt")
        ocr_module.set_engine("paddle")
        self.assertNotIn("HABIT_OCR_ENGINE", os.environ)


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


class TestStructuredKnowledgeBlocks(unittest.TestCase):
    def test_title_text_splits_into_blocks(self):
        records = [
            {"label": "paragraph_title", "content": "一、增长率的定义", "order": 1},
            {"label": "text", "content": "增长率用于衡量数据的增长速度。", "order": 2},
            {"label": "paragraph_title", "content": "二、增长率的计算", "order": 3},
            {"label": "text", "content": "增长率 = 现期量 - 基期量。", "order": 4},
        ]
        blocks = structured_knowledge_blocks(records)
        self.assertEqual([b["title"] for b in blocks],
                         ["一、增长率的定义", "二、增长率的计算"])
        self.assertIn("增长率用于衡量数据的增长速度", blocks[0]["content"])
        self.assertIn("<p>", blocks[0]["content"])
        self.assertNotIn("（页脚）", blocks[0]["content"])

    def test_consecutive_titles_merge_with_bold_heading(self):
        records = [
            {"label": "doc_title", "content": "资料分析考点精讲", "order": 1},
            {"label": "paragraph_title", "content": "同比与环比", "order": 2},
            {"label": "text", "content": "同比是与去年同期比较。", "order": 3},
        ]
        blocks = structured_knowledge_blocks(records)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["title"], "同比与环比")
        self.assertIn("<b>资料分析考点精讲</b>", blocks[0]["content"])
        self.assertIn("同比是与去年同期比较", blocks[0]["content"])

    def test_noise_and_empty_records(self):
        records = [
            {"label": "header", "content": "页眉", "order": 1},
            {"label": "number", "content": "12", "order": 2},
            {"label": "text", "content": "只有一段正文", "order": 3},
        ]
        blocks = structured_knowledge_blocks(records)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["title"], "知识点")
        self.assertNotIn("页眉", blocks[0]["content"])
        self.assertEqual(structured_knowledge_blocks([]), [])


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


class TestPlanDocImport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = Database(self.root / "app.db", self.root / "images", self.root)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_import_saves_source_file(self):
        md = self.root / "plan.md"
        md.write_text(
            "# 习惯打卡计划模板\n"
            "- 开始日期：2026-08-01\n"
            "## 每日任务\n"
            "### 2026-08-01\n"
            "- 09:30 | 大作文 | 主 | 写一篇\n",
            encoding="utf-8",
        )
        result = plan_docs.import_plan_document(self.db, str(md))
        self.assertFalse(result["updated_start_only"])
        self.assertEqual(self.db.get_setting("plan_start_date"), "2026-08-01")
        self.assertEqual(self.db.get_setting("plan_source_file"), "plan.md")

    def test_start_only_import_saves_source_file(self):
        md = self.root / "start.md"
        md.write_text("# 习惯打卡计划模板\n- 开始日期：2026-08-10\n", encoding="utf-8")
        result = plan_docs.import_plan_document(self.db, str(md))
        self.assertTrue(result["updated_start_only"])
        self.assertEqual(self.db.get_setting("plan_source_file"), "start.md")

    def test_import_preserves_existing_completed_plan_even_when_overwrite(self):
        md = self.root / "plan.md"
        md.write_text(
            "# 习惯打卡计划模板\n"
            "- 开始日期：2026-08-01\n"
            "## 每日任务\n"
            "### 2026-08-01\n"
            "- 09:30 | 大作文 | 主 | 写一篇\n",
            encoding="utf-8",
        )
        plan_docs.import_plan_document(self.db, str(md), overwrite=True)
        pid = self.db.get_plan("2026-08-01")["id"]
        item = self.db.get_plan_items(pid)[0]
        self.db.update_checkin(item["id"], note="已完成总结", done=True)

        md2 = self.root / "plan2.md"
        md2.write_text(
            "# 习惯打卡计划模板\n"
            "- 开始日期：2026-08-01\n"
            "## 每日任务\n"
            "### 2026-08-01\n"
            "- 10:00 | 资料分析 | 主 | 改时间\n",
            encoding="utf-8",
        )
        result = plan_docs.import_plan_document(self.db, str(md2), overwrite=True)

        self.assertEqual(result["skipped_days"], 1)
        self.assertEqual(result["days"], 0)
        plan = self.db.get_plan("2026-08-01")
        self.assertIsNotNone(plan)
        items = self.db.get_plan_items(plan["id"])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["note"], "已完成总结")

    def test_import_default_skips_existing_plan(self):
        md = self.root / "plan.md"
        md.write_text(
            "# 习惯打卡计划模板\n"
            "- 开始日期：2026-08-02\n"
            "## 每日任务\n"
            "### 2026-08-02\n"
            "- 09:30 | 大作文 | 主 | 写一篇\n",
            encoding="utf-8",
        )
        plan_docs.import_plan_document(self.db, str(md))
        pid = self.db.get_plan("2026-08-02")["id"]

        result = plan_docs.import_plan_document(self.db, str(md))

        self.assertEqual(result["skipped_days"], 1)
        self.assertEqual(self.db.get_plan("2026-08-02")["id"], pid)


class TestPlanDocMarkdownSync(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = Database(self.root / "app.db", self.root / "images", self.root)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_update_sections_keeps_notes_and_daily_tasks(self):
        md = self.root / "plan.md"
        md.write_text(
            "# 习惯打卡计划模板\n"
            "- 开始日期：2026-08-01\n"
            "\n"
            "## 阶段安排\n"
            "\n"
            "- 基础奠基（第 1 - 30 天）：行测基础；退出标准：基础完成\n"
            "> 自定义备注\n"
            "\n"
            "## 每周计划\n"
            "\n"
            "- 第 1 周：基础\n"
            "- 第 2 周：强化\n"
            "\n"
            "## 检查点\n"
            "\n"
            "- 第 10 天：检查基础\n"
            "- 第 20 天：检查强化\n"
            "\n"
            "## 每日作息模板\n"
            "\n"
            "- 09:00 晨读\n"
            "- 23:00 睡觉\n"
            "\n"
            "## 每日任务\n"
            "\n"
            "### 2026-08-01\n"
            "- 09:30 | 大作文 | 主 | 写一篇\n",
            encoding="utf-8",
        )
        cfg = {
            "total_days": 90,
            "stages": [
                {"name": "基础奠基", "day_start": 1, "day_end": 30,
                 "xingce": "行测基础", "shenlun": "申论基础", "exit": "基础完成"},
                {"name": "专项强化", "day_start": 31, "day_end": 60,
                 "xingce": "限时专项", "shenlun": "大作文", "exit": "速度提升"},
            ],
            "weeks": [[1, "第一周修改"], [3, "第三周新增"]],
            "checkpoints": [[10, "检查基础修改"], [45, "检查专项"]],
            "daily_routine": [["09:00", "晨读修改"], ["21:30", "明日计划"]],
        }
        plan_docs.update_markdown_config_sections(str(md), cfg)
        text = md.read_text(encoding="utf-8")
        self.assertIn("- 基础奠基（第 1 - 30 天）：行测基础；申论：申论基础；退出标准：基础完成", text)
        self.assertIn("- 专项强化（第 31 - 60 天）：限时专项；申论：大作文；退出标准：速度提升", text)
        self.assertIn("> 自定义备注", text)
        self.assertIn("- 第 1 周：第一周修改", text)
        self.assertIn("- 第 3 周：第三周新增", text)
        self.assertNotIn("- 第 2 周：强化", text)
        self.assertIn("- 第 10 天：检查基础修改", text)
        self.assertIn("- 第 45 天：检查专项", text)
        self.assertNotIn("- 第 20 天：检查强化", text)
        self.assertIn("- 09:00 晨读修改", text)
        self.assertIn("- 21:30 明日计划", text)
        self.assertNotIn("- 23:00 睡觉", text)
        self.assertIn("### 2026-08-01", text)
        self.assertIn("- 09:30 | 大作文 | 主 | 写一篇", text)

    def test_missing_sections_are_inserted_before_daily_tasks(self):
        md = self.root / "plan.md"
        md.write_text(
            "# 习惯打卡计划模板\n"
            "- 开始日期：2026-08-01\n"
            "\n"
            "## 每日任务\n"
            "\n"
            "### 2026-08-01\n"
            "- 09:00 | 判断 | 主 | 练习\n",
            encoding="utf-8",
        )
        cfg = {
            "total_days": 14,
            "stages": [{"name": "基础", "day_start": 1, "day_end": 14,
                        "xingce": "行测", "shenlun": "申论", "exit": "完成"}],
            "weeks": [[1, "第一周"]],
            "checkpoints": [[7, "中期检查"]],
            "daily_routine": [["09:00", "晨读"]],
        }
        plan_docs.update_markdown_config_sections(str(md), cfg)
        text = md.read_text(encoding="utf-8")
        self.assertIn("## 阶段安排", text)
        self.assertIn("## 每日作息模板", text)
        self.assertLess(text.index("## 每日作息模板"), text.index("## 每日任务"))
        self.assertIn("- 09:00 | 判断 | 主 | 练习", text)


if __name__ == "__main__":
    unittest.main()
