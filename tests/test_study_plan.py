"""90 天备考计划功能单元测试：计划数据、一键铺排、主辅任务、streak、周复盘、新指标。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from habit_checkin.db import Database
from habit_checkin.services import study_plan as sp


class TestStudyPlanHelpers(unittest.TestCase):
    def test_day_stage_week(self):
        start = date(2026, 8, 14)
        self.assertEqual(sp.day_number(start, date(2026, 8, 14)), 1)
        self.assertEqual(sp.day_number(start, date(2026, 11, 11)), 90)
        self.assertEqual(sp.remaining_days(start, date(2026, 8, 14)), 90)
        self.assertEqual(sp.stage_for(1)["name"], "基础奠基")
        self.assertEqual(sp.stage_for(45)["name"], "专项强化")
        self.assertEqual(sp.stage_for(61)["name"], "模考冲刺")
        self.assertEqual(sp.week_for(1)[0], 1)
        self.assertEqual(sp.week_for(90)[0], 13)

    def test_build_daily_tasks(self):
        monday = sp.build_daily_tasks(0)
        self.assertEqual(len(monday), 8)  # 3 主 + 5 辅（含数量插空）
        self.assertEqual(sum(1 for t in monday if t[0] == "main"), 3)
        self.assertEqual(sp.build_daily_tasks(1)[3][1], "归纳概括")  # 周二申论（day=1 → 概括期）
        self.assertEqual(sp.build_daily_tasks(6)[3][1], "大作文")   # 周日大作文
        self.assertEqual(len(sp.build_daily_tasks(1)), 7)           # 周二无数量插空
        self.assertEqual(len(sp.build_daily_tasks(6)), 7)           # 周日固定 7 项
        # 固定辅助任务每天都保留
        for tasks in (monday, sp.build_daily_tasks(1), sp.build_daily_tasks(6)):
            self.assertIn(("aux", "新闻联播", "19:00"), tasks)
            self.assertIn(("aux", "创作", "19:30"), tasks)
            self.assertTrue(any(t[0] == "aux" and t[2] == "16:00" for t in tasks))
        # 每日任务按提醒时间升序，保证界面/生成顺序就是一天的执行顺序
        for tasks in (monday, sp.build_daily_tasks(1), sp.build_daily_tasks(6)):
            times = [t[2] for t in tasks]
            self.assertEqual(times, sorted(times))

    def test_checkpoints_exist(self):
        self.assertEqual(sp.CHECKPOINTS[-1][0], 90)
        self.assertEqual(sp.CHECKPOINTS[0][0], 10)


class TestGenerate90Day(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = Database(self.root / "app.db", self.root / "images", self.root)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_generate(self):
        start = date(2026, 8, 14)
        stats = sp.generate_90day_plan(self.db, start)
        self.assertEqual(stats["created_days"], 90)
        self.assertEqual(stats["skipped_days"], 0)
        self.assertGreater(stats["created_items"], 90 * 4)
        self.assertEqual(self.db.get_setting("plan_start_date"), start.isoformat())
        plan = self.db.get_plan(start.isoformat())
        self.assertIn("第 1 天", plan["title"])
        items = self.db.get_plan_items(plan["id"])
        self.assertEqual(len(items), len(sp.build_daily_tasks(start.weekday(), 1)))
        self.assertEqual({it["task_type"] for it in items}, {"main", "aux"})

    def test_generate_skip_existing(self):
        start = date(2026, 8, 14)
        self.db.create_plan(start.isoformat(), "已有")
        stats = sp.generate_90day_plan(self.db, start, overwrite=False)
        self.assertEqual(stats["skipped_days"], 1)
        self.assertEqual(stats["created_days"], 89)
        # 覆盖模式
        stats2 = sp.generate_90day_plan(self.db, start, overwrite=True)
        self.assertEqual(stats2["created_days"], 90)


class TestPlanDbMethods(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = Database(self.root / "app.db", self.root / "images", self.root)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def _leaf(self, name):
        return [t for t in self.db.list_topics() if t["name"] == name][0]

    def test_ensure_topic_by_path_idempotent(self):
        tid = self.db.ensure_topic_by_path(("行测", "全模块小测"))
        self.assertIsNotNone(tid)
        self.assertEqual(self.db.ensure_topic_by_path(("行测", "全模块小测")), tid)

    def test_task_type_and_copy(self):
        pid = self.db.create_plan("2026-08-14")
        iid = self.db.add_plan_item(pid, self._leaf("大作文")["id"], "13:30", task_type="main")
        self.assertEqual(self.db.get_plan_item(iid)["task_type"], "main")
        self.db.copy_plan("2026-08-14", "2026-08-15")
        copied = self.db.get_plan_items(self.db.get_plan("2026-08-15")["id"])
        self.assertEqual(copied[0]["task_type"], "main")

    def test_streak(self):
        today = date.today()
        yesterday = today - timedelta(days=1)
        for d in (yesterday, today):
            pid = self.db.create_plan(d.isoformat())
            self.db.update_checkin(self.db.add_plan_item(pid, self._leaf("大作文")["id"]), "ok", done=True)
        s = self.db.streak_stats()
        self.assertGreaterEqual(s["current"], 2)
        self.assertEqual(s["days"], 2)

    def test_daily_completion_and_weekly_review(self):
        pid = self.db.create_plan("2026-08-14")
        iid = self.db.add_plan_item(pid, self._leaf("大作文")["id"])
        self.db.update_checkin(iid, "ok", done=True)
        self.assertEqual(self.db.daily_completion("2026-08-14", "2026-08-14"),
                         {"2026-08-14": {"total": 1, "done": 1}})
        self.db.save_weekly_review("2026-08-10", "复盘心得", "下周重点")
        r = self.db.get_weekly_review("2026-08-10")
        self.assertEqual(r["review_text"], "复盘心得")
        self.assertEqual(r["next_focus"], "下周重点")

    def test_new_builtin_metrics(self):
        keys = [m["builtin_key"] for m in self.db.list_metrics() if m["kind"] == "builtin"]
        for k in ("mock_exam_count", "essay_count"):
            self.assertIn(k, keys)
        pid = self.db.create_plan("2026-08-14")
        self.db.update_checkin(self.db.add_plan_item(pid, self._leaf("大作文")["id"]), "ok", done=True)
        self.assertEqual(self.db.metric_computed_value("essay_count"), 1)


class TestCustomPlanConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = Database(self.root / "app.db", self.root / "images", self.root)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_save_and_generate_custom_config(self):
        cfg = {
            "total_days": 28,
            "stages": [
                {"name": "基础", "day_start": 1, "day_end": 14,
                 "xingce": "行测基础", "shenlun": "申论基础", "exit": "完成基础"},
                {"name": "冲刺", "day_start": 15, "day_end": 28,
                 "xingce": "套题", "shenlun": "套题", "exit": "完成冲刺"},
            ],
            "weeks": [[i, "第 {} 周重点".format(i)] for i in range(1, 5)],
            "checkpoints": [[7, "一周复盘"], [14, "阶段小结"], [28, "最终复盘"]],
            "daily_routine": [["09:00", "晨读"], ["23:00", "睡觉"]],
        }
        sp.save_plan_config(self.db, cfg)
        loaded = sp.get_plan_config(self.db)
        self.assertEqual(loaded["total_days"], 28)
        self.assertEqual(len(loaded["stages"]), 2)
        start = date(2026, 8, 16)
        stats = sp.generate_90day_plan(self.db, start, config=loaded)
        self.assertEqual(stats["created_days"], 28)
        self.assertEqual(sp.stage_for(10, loaded["stages"])["name"], "基础")
        self.assertEqual(sp.stage_for(20, loaded["stages"])["name"], "冲刺")
        self.assertEqual(sp.checkpoint_for(14, loaded["checkpoints"])[0], 14)
        self.assertEqual(sp.plan_week_of(start, start + timedelta(days=27), 28, loaded["weeks"])[0], 4)

    def test_template_uses_custom_config(self):
        from habit_checkin.services import plan_docs
        cfg = {
            "total_days": 28,
            "stages": [{"name": "基础", "day_start": 1, "day_end": 14,
                        "xingce": "行测", "shenlun": "申论", "exit": "基础完成"}],
            "weeks": [[1, "第一周"]],
            "checkpoints": [[14, "中期检查"]],
            "daily_routine": [["09:00", "晨读"]],
        }
        out = self.root / "plan_template.md"
        plan_docs.export_markdown_template(str(out), config=cfg)
        content = out.read_text(encoding="utf-8")
        self.assertIn("总天数：28", content)
        self.assertIn("## 每周计划", content)
        self.assertIn("## 检查点", content)
        self.assertIn("## 每日作息模板", content)


if __name__ == "__main__":
    unittest.main()
