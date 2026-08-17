"""数据层单元测试（v3 目录/迁移/题库/指标）。"""
from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from habit_checkin.db import Database, validate_date, validate_time


class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = Database(self.root / "app.db", self.root / "images", self.root)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def _leaf(self, name):
        return [t for t in self.db.list_topics() if t["name"] == name][0]

    def test_seed_topics_v3(self):
        topics = self.db.list_topics()
        names = [t["name"] for t in topics]
        for expected in [
            "行测", "申论",
            "政治理论", "常识判断", "言语理解与表达",
            "逻辑填空（选词填空）", "片段阅读", "语句表达",
            "数量关系", "数字推理", "数学运算",
            "判断推理", "图形推理", "定义判断", "类比推理", "逻辑判断",
            "资料分析", "单一指标", "和差型指标", "分数型指标", "乘积型指标",
            "概括题", "综合分析题", "公文写作题", "提出对策题", "大作文",
        ]:
            self.assertIn(expected, names)
        self.assertEqual([t["name"] for t in self.db.root_topics()], ["行测", "申论"])
        hangce = self._leaf("行测")
        kids = sorted([t for t in topics if t["parent_id"] == hangce["id"]], key=lambda x: x["sort_order"])
        self.assertEqual([k["name"] for k in kids],
                         ["政治理论", "常识判断", "言语理解与表达", "数量关系", "判断推理", "资料分析"])
        zl = self._leaf("资料分析")
        zkids = sorted([t for t in topics if t["parent_id"] == zl["id"]], key=lambda x: x["sort_order"])
        self.assertEqual([k["name"] for k in zkids], ["单一指标", "和差型指标", "分数型指标", "乘积型指标"])

    def test_seed_migration_keeps_custom(self):
        self.db.add_topic("自定义科目")
        self.db.set_setting("seed_version", "1")
        self.db._seed_topics()
        names = [t["name"] for t in self.db.list_topics()]
        self.assertIn("自定义科目", names)
        self.assertIn("言语理解与表达", names)
        self.assertIn("逻辑填空（选词填空）", names)

    def test_topic_kind_defaults_and_switching(self):
        topics = self.db.list_topics()
        self.assertTrue(all(t["kind"] == "category" for t in topics))
        tid = self.db.ensure_topic_by_path(("行测", "全模块小测"))
        row = self.db.conn.execute("SELECT kind FROM topics WHERE id=?", (tid,)).fetchone()
        self.assertEqual(row["kind"], "method")
        self.db.set_topic_kind(tid, "category")
        self.assertEqual(
            self.db.conn.execute("SELECT kind FROM topics WHERE id=?", (tid,)).fetchone()["kind"],
            "category",
        )
        self.db.set_topic_kind(tid, "method")
        self.assertEqual(
            self.db.conn.execute("SELECT kind FROM topics WHERE id=?", (tid,)).fetchone()["kind"],
            "method",
        )
        with self.assertRaises(ValueError):
            self.db.set_topic_kind(tid, "other")

    def test_migrate_topic_kinds_marks_known_methods(self):
        tid = self.db.add_topic("自由补弱", kind="category")
        self.db._migrate_topic_kinds()
        row = self.db.conn.execute("SELECT kind FROM topics WHERE id=?", (tid,)).fetchone()
        self.assertEqual(row["kind"], "method")

    def test_category_subtopic_paths_skips_methods(self):
        root = self.db.add_topic("分类科目")
        cat = self.db.add_topic("单一指标", parent_id=root)
        leaf = self.db.add_topic("具体细分", parent_id=cat)
        method = self.db.add_topic("自由补弱", parent_id=root)
        self.db.add_topic("子做法", parent_id=method)
        self.assertEqual(
            self.db.category_subtopic_paths(root),
            [("单一指标", cat), ("单一指标 / 具体细分", leaf)],
        )

    def test_category_paths_skips_method_roots(self):
        cat_root = self.db.add_topic("行测分类")
        child = self.db.add_topic("单一指标", parent_id=cat_root)
        method_root = self.db.add_topic("自由补弱")
        self.db.add_topic("子做法", parent_id=method_root)
        paths = dict(self.db.category_paths())
        self.assertEqual(paths["行测分类 / 单一指标"], child)
        self.assertNotIn("自由补弱", paths)
        self.assertNotIn("自由补弱 / 子做法", paths)

    def test_plan_and_checkin(self):
        day = "2026-08-11"
        pid = self.db.create_plan(day, "今日计划")
        iid = self.db.add_plan_item(pid, self._leaf("逻辑填空（选词填空）")["id"], "19:30")
        self.db.update_checkin(iid, "完成 30 道逻辑填空", done=True)
        item = self.db.get_plan_item(iid)
        self.assertEqual(item["done"], 1)
        self.assertEqual(item["note"], "完成 30 道逻辑填空")
        self.assertEqual(item["topic_path"], "行测 / 言语理解与表达 / 逻辑填空（选词填空）")
        rows = self.db.query_items("2026-08-01", "2026-08-31")
        self.assertEqual(len(rows), 1)

    def test_update_checkin_can_override_checked_time(self):
        pid = self.db.create_plan("2026-08-12")
        iid = self.db.add_plan_item(pid, self._leaf("大作文")["id"])
        self.db.update_checkin(iid, "ok", done=True, checked_at="2026-08-12 09:00:00")
        self.assertEqual(self.db.get_plan_item(iid)["checked_at"], "2026-08-12 09:00:00")
        self.db.update_checkin(
            iid, "修改错误数据", done=True,
            checked_at="2026-08-12 21:30:00", preserve_time=False,
        )
        self.assertEqual(self.db.get_plan_item(iid)["checked_at"], "2026-08-12 21:30:00")
        self.assertEqual(self.db.get_plan_item(iid)["note"], "修改错误数据")
        self.db.update_checkin(iid, "ok", done=True, checked_at="2026-08-12 22:00:00")
        self.assertEqual(self.db.get_plan_item(iid)["checked_at"], "2026-08-12 21:30:00")
        self.db.delete_plan_item(iid)
        self.assertIsNone(self.db.get_plan_item(iid))

    def test_clear_checkin_time_keeps_done_and_note(self):
        pid = self.db.create_plan("2026-08-13")
        iid = self.db.add_plan_item(pid, self._leaf("单一指标")["id"])
        self.db.update_checkin(iid, "完成资料分析", done=True, checked_at="2026-08-13 10:20:00")
        self.db.set_elapsed(iid, 1800)
        self.db.clear_checked_at(iid)
        item = self.db.get_plan_item(iid)
        self.assertEqual(item["done"], 1)
        self.assertEqual(item["note"], "完成资料分析")
        self.assertIsNone(item["checked_at"])
        self.assertEqual(item["elapsed_seconds"], 1800)

    def test_reset_plan_item_restores_unchecked_state(self):
        from PIL import Image
        img_path = self.root / "reset.png"
        Image.new("RGB", (30, 30)).save(img_path)
        rel = self.db.store_image_from_path(str(img_path))
        pid = self.db.create_plan("2026-08-13")
        iid = self.db.add_plan_item(pid, self._leaf("大作文")["id"])
        self.db.update_checkin(iid, "需要修正", done=True, checked_at="2026-08-13 21:00:00")
        self.db.set_elapsed(iid, 3600)
        self.db.add_image(iid, rel)
        self.db.reset_plan_item(iid)
        item = self.db.get_plan_item(iid)
        self.assertEqual(item["done"], 0)
        self.assertEqual(item["note"], "")
        self.assertIsNone(item["checked_at"])
        self.assertEqual(item["elapsed_seconds"], 0)
        self.assertEqual(item["images"], [])
        self.assertFalse(Path(self.db.abs_path(rel)).exists())

    def test_topic_paths_batch(self):
        root_id = self.db.add_topic("BatchRoot")
        child_id = self.db.add_topic("BatchChild", parent_id=root_id)
        leaf_id = self.db.add_topic("BatchLeaf", parent_id=child_id)
        paths = self.db.topic_paths([leaf_id, root_id])
        self.assertEqual(paths[leaf_id], "BatchRoot / BatchChild / BatchLeaf")
        self.assertEqual(paths[root_id], "BatchRoot")
        self.assertEqual(paths[leaf_id], self.db.topic_path(leaf_id))

    def test_add_plan_items_batch(self):
        pid = self.db.create_plan("2026-08-14")
        tid = self._leaf("大作文")["id"]
        n = self.db.add_plan_items(pid, [(tid, "09:30", "main"), (tid, "10:00", "aux")])
        self.assertEqual(n, 2)
        items = self.db.get_plan_items(pid)
        self.assertEqual([it["reminder_time"] for it in items], ["09:30", "10:00"])
        self.assertEqual({it["task_type"] for it in items}, {"main", "aux"})

    def test_copy_plan(self):
        src, dst = "2026-08-10", "2026-08-11"
        pid = self.db.create_plan(src, "")
        self.db.add_plan_item(pid, self._leaf("政治理论")["id"], "20:00")
        n = self.db.copy_plan(src, dst)
        self.assertEqual(n, 1)
        items = self.db.get_plan_items(self.db.get_plan(dst)["id"])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["reminder_time"], "20:00")
        self.assertEqual(items[0]["done"], 0)

    def test_image_storage(self):
        from PIL import Image
        img_path = self.root / "src.png"
        Image.new("RGB", (50, 40), (255, 0, 0)).save(img_path)
        rel = self.db.store_image_from_path(str(img_path))
        self.assertTrue((self.root / rel).is_file())
        pid = self.db.create_plan("2026-08-11")
        iid = self.db.add_plan_item(pid, self._leaf("大作文")["id"])
        self.db.add_image(iid, rel, sort_order=0)
        self.assertEqual(len(self.db.get_images(iid)), 1)

    def test_delete_topic_cascade(self):
        tid = self.db.add_topic("自定义科目")
        cid = self.db.add_topic("自定义知识点", parent_id=tid)
        from PIL import Image
        img_path = self.root / "src2.png"
        Image.new("RGB", (30, 30)).save(img_path)
        rel = self.db.store_image_from_path(str(img_path))
        pid = self.db.create_plan("2026-08-12")
        iid = self.db.add_plan_item(pid, cid)
        self.db.add_image(iid, rel)
        self.db.delete_topic_cascade(tid)
        self.assertIsNone(self.db.get_plan_item(iid))
        self.assertFalse(Path(self.db.abs_path(rel)).exists())
        self.assertEqual(len(self.db.list_topics(include_disabled=True)), 26)

    def test_settings(self):
        self.assertTrue(self.db.get_bool_setting("sound_enabled", True))
        self.db.set_setting("sound_enabled", "0")
        self.assertFalse(self.db.get_bool_setting("sound_enabled", True))

    def test_validation(self):
        self.assertEqual(validate_time(""), None)
        self.assertEqual(validate_time("19:30"), "19:30")
        with self.assertRaises(ValueError):
            validate_time("25:00")
        with self.assertRaises(ValueError):
            validate_date("2026-13-01")
        self.assertEqual(validate_date("2026-08-11"), "2026-08-11")

    def test_sync_checkin_images(self):
        from PIL import Image
        pid = self.db.create_plan("2026-08-11")
        iid = self.db.add_plan_item(pid, self._leaf("大作文")["id"])
        img1 = self.root / "k1.png"
        img2 = self.root / "k2.jpg"
        Image.new("RGB", (40, 40)).save(img1)
        Image.new("RGB", (50, 50)).save(img2)
        rel1 = self.db.store_image_from_path(str(img1))
        self.db.add_image(iid, rel1, sort_order=0)
        imgs = self.db.sync_checkin_images(iid, [rel1], [str(img2)])
        self.assertEqual(len(imgs), 2)
        imgs = self.db.sync_checkin_images(iid, [], [])
        self.assertEqual(imgs, [])
        self.assertFalse(Path(self.db.abs_path(rel1)).exists())

    def test_move_topic_and_tree(self):
        t1 = self.db.add_topic("甲")
        t2 = self.db.add_topic("乙", parent_id=t1)
        t3 = self.db.add_topic("丙", parent_id=t2)
        # 不能把甲移入自己的子孙（丙）
        with self.assertRaises(ValueError):
            self.db.move_topic(t1, t3, 0)
        with self.assertRaises(ValueError):
            self.db.update_topic_tree([(t1, t3, 0)])
        # 合法移动：乙移到根级
        self.db.move_topic(t2, None, 0)
        row = self.db.conn.execute("SELECT parent_id FROM topics WHERE id=?", (t2,)).fetchone()
        self.assertIsNone(row["parent_id"])
        # 此时丙不再属于甲的子孙，可把丙挂到甲下
        self.db.update_topic_tree([(t3, t1, 5)])
        row3 = self.db.conn.execute("SELECT parent_id, sort_order FROM topics WHERE id=?", (t3,)).fetchone()
        self.assertEqual(row3["parent_id"], t1)
        self.assertEqual(row3["sort_order"], 5)

    def test_questions_crud(self):
        zl = self._leaf("单一指标")
        qid = self.db.add_question(topic_id=zl["id"], question_text="题目A", analysis="解析A",
                                   result="wrong", result_reason="计算粗心")
        qid2 = self.db.add_question(question_text="题目B", result="correct", result_reason="完全理解")
        self.assertEqual(self.db.get_question(qid)["code"], "Q0001")
        self.assertEqual(self.db.get_question(qid2)["code"], "Q0002")
        self.assertEqual(len(self.db.list_questions(result="wrong")), 1)
        self.assertEqual(len(self.db.list_questions(topic_id=zl["id"])), 1)
        self.assertEqual(len(self.db.list_questions(search="题目B")), 1)
        today = date.today().isoformat()
        self.assertEqual(len(self.db.list_questions(start_date=today, end_date=today)), 2)
        self.db.update_question(qid, self_analysis="思路1", correct_analysis="思路2", reflection="教训")
        q = self.db.get_question(qid)
        self.assertEqual(q["self_analysis"], "思路1")
        self.assertEqual(q["reflection"], "教训")
        self.assertEqual(len(self.db.wrong_questions(today, today)), 1)
        self.db.delete_question(qid2)
        self.assertIsNone(self.db.get_question(qid2))
        qid3 = self.db.add_question(question_text="题目C")
        self.assertEqual(self.db.get_question(qid3)["code"], "Q0003")

    def test_question_images_sync(self):
        from PIL import Image
        qid = self.db.add_question(question_text="X")
        img = self.root / "qi.png"
        Image.new("RGB", (40, 40)).save(img)
        imgs = self.db.sync_question_images(qid, [], [str(img)])
        self.assertEqual(len(imgs), 1)
        self.assertTrue(Path(self.db.abs_path(imgs[0]["file_path"])).exists())
        imgs = self.db.sync_question_images(qid, [], [])
        self.assertEqual(imgs, [])

    def test_metrics(self):
        values = self.db.metric_values()
        keys = [m["builtin_key"] for m in values]
        for k in ("checkin_count", "checkin_days", "question_count", "wrong_count",
                  "mock_exam_count", "essay_count"):
            self.assertIn(k, keys)
        self.assertEqual(values[0]["current"], 0)
        mid = self.db.add_custom_metric("刷题页数", "页", 30)
        self.db.set_metric_value(mid, 12)
        m = [x for x in self.db.metric_values() if x["id"] == mid][0]
        self.assertEqual(m["current"], 12)
        self.assertEqual(m["target"], 30)
        self.db.set_metric_target(mid, None)
        self.assertIsNone([x for x in self.db.list_metrics() if x["id"] == mid][0]["target"])
        self.db.set_metric_enabled(mid, False)
        self.assertEqual([x for x in self.db.list_metrics() if x["id"] == mid][0]["enabled"], 0)
        self.db.delete_metric(mid)
        self.assertFalse(any(x["kind"] == "custom" for x in self.db.list_metrics()))
        # 计算值联动
        pid = self.db.create_plan("2026-08-11")
        iid = self.db.add_plan_item(pid, self._leaf("大作文")["id"])
        self.db.update_checkin(iid, "ok", done=True)
        self.assertEqual(self.db.metric_computed_value("checkin_count"), 1)
        self.assertEqual(self.db.metric_computed_value("checkin_days"), 1)

    def test_overall_stats(self):
        self.assertEqual(self.db.overall_stats(), {"total": 0, "done": 0, "rate": 0})
        pid = self.db.create_plan("2026-08-11")
        self.db.add_plan_item(pid, self._leaf("大作文")["id"])
        iid2 = self.db.add_plan_item(pid, self._leaf("政治理论")["id"])
        self.db.update_checkin(iid2, "ok", done=True)
        stats = self.db.overall_stats()
        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["done"], 1)
        self.assertEqual(stats["rate"], 50.0)


    def test_collected_checkin_texts(self):
        pid = self.db.create_plan("2026-08-11")
        iid = self.db.add_plan_item(pid, self._leaf("大作文")["id"])
        self.assertEqual(self.db.collected_checkin_texts(iid), set())
        self.db.add_question(topic_id=None, question_text="第一题", source="checkin", source_item_id=iid)
        self.db.add_question(topic_id=None, question_text="第二题", source="checkin", source_item_id=iid)
        self.db.add_question(topic_id=None, question_text="无关题", source="manual", source_item_id=iid)
        self.assertEqual(self.db.collected_checkin_texts(iid), {"第一题", "第二题"})


    def test_map_auto_created_for_root_topic(self):
        before = len(self.db.list_question_maps())
        tid = self.db.add_topic("MapAutoRoot")
        maps = self.db.list_question_maps()
        self.assertEqual(len(maps), before + 1)
        m = next(x for x in maps if x["topic_id"] == tid)
        self.assertEqual(m["subject_name"], "MapAutoRoot")
        roots = [n for n in self.db.question_types_by_map(m["id"]) if n["parent_id"] is None]
        self.assertEqual(len(roots), 1)
        self.assertEqual(roots[0]["name"], "MapAutoRoot")
        self.assertEqual(roots[0]["node_type"], "subject")

    def test_rename_root_topic_syncs_map(self):
        tid = self.db.add_topic("RenameMapRoot")
        self.db.rename_topic(tid, "RenameMapRoot2")
        m = next(x for x in self.db.list_question_maps() if x["topic_id"] == tid)
        self.assertEqual(m["subject_name"], "RenameMapRoot2")
        roots = [n for n in self.db.question_types_by_map(m["id"]) if n["parent_id"] is None]
        self.assertEqual(roots[0]["name"], "RenameMapRoot2")

    def test_delete_root_topic_removes_map(self):
        tid = self.db.add_topic("DeleteMapRoot")
        m = next(x for x in self.db.list_question_maps() if x["topic_id"] == tid)
        self.db.add_question_type_full("Child", parent_id=None, map_id=m["id"])
        self.db.delete_topic_cascade(tid)
        self.assertFalse(any(x["id"] == m["id"] for x in self.db.list_question_maps()))
        self.assertEqual(self.db.question_types_by_map(m["id"]), [])

    def test_seed_question_types_idempotent(self):
        before = len(self.db.list_question_maps())
        self.db._seed_question_types()
        self.assertEqual(len(self.db.list_question_maps()), before)
        for r in self.db.root_topics():
            m = next((x for x in self.db.list_question_maps() if x["topic_id"] == r["id"]), None)
            self.assertIsNotNone(m)

    def test_question_type_parent_cycle_rejected(self):
        tid = self.db.add_topic("CycleMapRoot")
        m = next(x for x in self.db.list_question_maps() if x["topic_id"] == tid)
        root = [n for n in self.db.question_types_by_map(m["id"]) if n["parent_id"] is None][0]
        a = self.db.add_question_type_full("A", parent_id=root["id"], map_id=m["id"])
        b = self.db.add_question_type_full("B", parent_id=a, map_id=m["id"])
        c = self.db.add_question_type_full("C", parent_id=b, map_id=m["id"])
        with self.assertRaises(ValueError):
            self.db.update_question_type_full(a, parent_id=c)
        with self.assertRaises(ValueError):
            self.db.update_question_type_full(root["id"], parent_id=a)

    def test_question_type_node_width(self):
        tid = self.db.add_topic("WidthMapRoot")
        m = next(x for x in self.db.list_question_maps() if x["topic_id"] == tid)
        root = [n for n in self.db.question_types_by_map(m["id"]) if n["parent_id"] is None][0]
        nid = self.db.add_question_type_full("长节点", parent_id=root["id"], map_id=m["id"],
                                             node_width=260.0)
        node = self.db.get_question_type(nid)
        self.assertEqual(node["node_width"], 260.0)
        self.db.update_question_type_full(nid, node_width=320.0)
        self.assertEqual(self.db.get_question_type(nid)["node_width"], 320.0)

    def test_import_preset_skips_method_topics(self):
        root = self.db.add_topic("ImportMethodRoot")
        m = next(x for x in self.db.list_question_maps() if x["topic_id"] == root)
        category = self.db.add_topic("分类节点", parent_id=root)
        method = self.db.add_topic("自由补弱", parent_id=root)
        self.db.add_topic("子做法", parent_id=method)
        self.db.import_preset_question_types(m["id"])
        nodes = self.db.question_types_by_map(m["id"])
        names = [n["name"] for n in nodes]
        self.assertIn("分类节点", names)
        self.assertNotIn("自由补弱", names)
        self.assertNotIn("子做法", names)
        self.assertEqual(
            self.db.conn.execute(
                "SELECT COUNT(*) AS n FROM question_types WHERE topic_id=?", (category,)
            ).fetchone()["n"],
            1,
        )

    def test_set_question_types_collapsed_batch(self):
        tid = self.db.add_topic("CollapseMapRoot")
        m = next(x for x in self.db.list_question_maps() if x["topic_id"] == tid)
        root = [n for n in self.db.question_types_by_map(m["id"]) if n["parent_id"] is None][0]
        self.db.add_question_type_full("Child", parent_id=root["id"], map_id=m["id"])
        self.db.set_question_types_collapsed(m["id"], 1)
        self.assertTrue(all(n["collapsed"] for n in self.db.question_types_by_map(m["id"])))
        self.db.set_question_types_collapsed(m["id"], 0)
        self.assertTrue(all(not n["collapsed"] for n in self.db.question_types_by_map(m["id"])))


if __name__ == "__main__":
    unittest.main()
