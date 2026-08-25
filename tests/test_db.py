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
            "自由补弱", "行测套题", "全模块小测", "申论套题",
        ]:
            self.assertIn(expected, names)
        self.assertEqual([t["name"] for t in self.db.root_topics()], ["行测", "申论"])
        hangce = self._leaf("行测")
        kids = sorted([t for t in topics if t["parent_id"] == hangce["id"]], key=lambda x: x["sort_order"])
        self.assertEqual([k["name"] for k in kids],
                         ["政治理论", "常识判断", "言语理解与表达", "数量关系", "判断推理",
                          "资料分析", "自由补弱", "行测套题", "全模块小测"])
        shenlun = self._leaf("申论")
        skids = sorted([t for t in topics if t["parent_id"] == shenlun["id"]], key=lambda x: x["sort_order"])
        self.assertEqual([k["name"] for k in skids],
                         ["概括题", "综合分析题", "公文写作题", "提出对策题", "大作文", "申论套题"])
        self.assertEqual(
            {k["name"]: k["kind"] for k in kids + skids
             if k["name"] in ("自由补弱", "行测套题", "全模块小测", "申论套题")},
            {"自由补弱": "method", "行测套题": "method", "全模块小测": "method", "申论套题": "method"},
        )
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
        method_names = {"自由补弱", "行测套题", "全模块小测", "申论套题"}
        for t in topics:
            self.assertEqual(t["kind"], "method" if t["name"] in method_names else "category")
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

    def test_ensure_method_topics_idempotent(self):
        def method_rows():
            return self.db.conn.execute(
                "SELECT name, parent_id, kind, sort_order FROM topics "
                "WHERE name IN ('自由补弱', '行测套题', '全模块小测', '申论套题') "
                "ORDER BY sort_order, id"
            ).fetchall()

        before = [tuple(r) for r in method_rows()]
        self.db._migrate_ensure_method_topics()
        after = [tuple(r) for r in method_rows()]
        self.assertEqual(after, before)
        self.assertEqual(len(before), 4)

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
        self.assertEqual(item["plan_date"], day)
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
        qid = self.db.add_question(topic_id=cid, question_text="保留到未分类")
        self.db.delete_topic_cascade(tid)
        self.assertIsNone(self.db.get_plan_item(iid))
        self.assertFalse(Path(self.db.abs_path(rel)).exists())
        q = self.db.get_question(qid)
        self.assertIsNotNone(q)
        self.assertIsNone(q["topic_id"])
        self.assertEqual(q["question_text"], "保留到未分类")
        self.assertEqual(len(self.db.list_topics(include_disabled=True)), 30)

    def test_delete_child_topic_cascades_mindmap_and_knowledge_branch(self):
        root = self.db.add_topic("联动根科目")
        m = next(x for x in self.db.list_question_maps() if x["topic_id"] == root)
        root_node = next(
            n for n in self.db.question_types_by_map(m["id"])
            if n["parent_id"] is None
        )
        child = self.db.add_topic("联动子分类", parent_id=root)
        grand = self.db.add_topic("联动孙级", parent_id=child)
        child_node = self.db.conn.execute(
            "SELECT id FROM question_types WHERE map_id=? AND topic_id=?",
            (m["id"], child),
        ).fetchone()
        self.db.add_question_type_full(
            "导图手子", parent_id=child_node["id"], map_id=m["id"])
        kept_node = self.db.add_question_type_full(
            "留存节点", parent_id=root_node["id"], map_id=m["id"])
        self.assertEqual(len(self.db.list_knowledge_docs(topic_id=child)), 1)
        self.assertEqual(len(self.db.list_knowledge_docs(topic_id=grand)), 1)

        self.db.delete_topic_cascade(child)

        self.assertIsNone(self.db.conn.execute(
            "SELECT 1 FROM topics WHERE id IN (?,?)", (child, grand)
        ).fetchone())
        self.assertEqual(self.db.conn.execute(
            "SELECT COUNT(*) AS n FROM question_types "
            "WHERE map_id=? AND topic_id IN (?,?)",
            (m["id"], child, grand),
        ).fetchone()["n"], 0)
        self.assertIsNone(self.db.conn.execute(
            "SELECT 1 FROM question_types WHERE parent_id=?", (child_node["id"],)
        ).fetchone())
        self.assertEqual(self.db.list_knowledge_docs(topic_id=child), [])
        self.assertEqual(self.db.list_knowledge_docs(topic_id=grand), [])
        self.assertEqual(len(self.db.question_types_by_map(m["id"])), 2)
        self.assertIsNotNone(self.db.get_question_type(root_node["id"]))
        self.assertIsNotNone(self.db.get_question_type(kept_node))

    def test_delete_topic_cascade_clears_detail_type_refs(self):
        root = self.db.add_topic("分类清理根")
        child = self.db.add_topic("分类清理子", parent_id=root)
        m = next(x for x in self.db.list_question_maps() if x["topic_id"] == root)
        node = self.db.conn.execute(
            "SELECT id FROM question_types WHERE map_id=? AND topic_id=?",
            (m["id"], child),
        ).fetchone()
        manual = self.db.add_question_type_full(
            "手工细分", parent_id=node["id"], map_id=m["id"])
        qid = self.db.add_question(
            topic_id=child, question_text="保留题目", detail_type_id=manual)
        mid = self.db.add_question_material(
            topic_id=child, detail_type_id=manual, title="保留材料")

        self.db.delete_topic_cascade(root)

        self.assertIsNone(self.db.get_question(qid)["detail_type_id"])
        self.assertIsNone(self.db.get_question_material(mid)["detail_type_id"])

    def test_rename_question_type_syncs_topic_and_knowledge(self):
        root = self.db.add_topic("重命名根科目")
        child = self.db.add_topic("重命名子分类", parent_id=root)
        m = next(x for x in self.db.list_question_maps() if x["topic_id"] == root)
        node = self.db.conn.execute(
            "SELECT id FROM question_types WHERE map_id=? AND topic_id=?",
            (m["id"], child),
        ).fetchone()

        self.db.rename_question_type_with_sync(node["id"], "新分类名")

        self.assertEqual(self.db.get_topic(child)["name"], "新分类名")
        self.assertEqual(self.db.get_question_type(node["id"])["name"], "新分类名")
        self.assertEqual(
            self.db.list_knowledge_docs(topic_id=child)[0]["title"], "新分类名")

    def test_delete_unlinked_question_type_clears_detail_refs(self):
        root = self.db.add_topic("孤立清理根")
        m = next(x for x in self.db.list_question_maps() if x["topic_id"] == root)
        root_node = next(
            n for n in self.db.question_types_by_map(m["id"])
            if n["parent_id"] is None
        )
        node = self.db.add_question_type_full(
            "孤立节点", parent_id=root_node["id"], map_id=m["id"])
        child = self.db.add_question_type_full(
            "孤立子节点", parent_id=node, map_id=m["id"])
        qid = self.db.add_question(
            topic_id=self._leaf("资料分析")["id"],
            question_text="保留题目", detail_type_id=child,
        )

        self.db.delete_question_type_with_sync(node)

        self.assertIsNone(self.db.get_question_type(child))
        self.assertIsNone(self.db.get_question(qid)["detail_type_id"])

    def test_add_synced_question_type_creates_all_in_one(self):
        root = self.db.add_topic("联动新增根")
        m = next(x for x in self.db.list_question_maps() if x["topic_id"] == root)
        root_node = next(
            n for n in self.db.question_types_by_map(m["id"])
            if n["parent_id"] is None
        )

        qid, tid = self.db.add_synced_question_type(
            "联动新增节点", parent_id=root_node["id"], map_id=m["id"],
            node_type="type",
        )

        topic = self.db.get_topic(tid)
        self.assertEqual(topic["name"], "联动新增节点")
        self.assertEqual(topic["parent_id"], root)
        self.assertEqual(topic["kind"], "category")
        self.assertEqual(len(self.db.list_knowledge_docs(topic_id=tid)), 1)
        node = self.db.get_question_type(qid)
        self.assertEqual(node["topic_id"], tid)
        self.assertEqual(node["parent_id"], root_node["id"])

    def test_delete_root_topic_removes_knowledge_images(self):
        from PIL import Image
        root = self.db.add_topic("知识清理根科目")
        child = self.db.add_topic("知识清理子分类", parent_id=root)
        src = self.root / "knowledge_cascade.png"
        Image.new("RGB", (40, 40), "blue").save(src)
        rel = self.db.store_image_from_path(str(src))
        doc = self.db.list_knowledge_docs(topic_id=child)[0]
        self.db.add_knowledge_block(
            doc["id"], "正文块", "<p image='{}'></p>".format(rel))

        self.db.delete_topic_cascade(root)

        self.assertEqual(self.db.list_knowledge_docs(topic_id=child), [])
        self.assertFalse(Path(self.db.abs_path(rel)).exists())

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

    def test_clear_questions(self):
        from PIL import Image
        zl = self._leaf("单一指标")
        mid = self.db.add_question_material(
            topic_id=zl["id"], kind="passage", title="保留材料", content="正文")
        qid = self.db.add_question(
            topic_id=zl["id"], question_text="待清空", material_id=mid, result="wrong")
        img = self.root / "qi_clear.png"
        Image.new("RGB", (30, 30)).save(img)
        imgs = self.db.sync_question_images(qid, [], [str(img)])
        rel = imgs[0]["file_path"]
        self.assertTrue(Path(self.db.abs_path(rel)).exists())

        self.db.clear_questions()

        self.assertEqual(self.db.list_questions(), [])
        self.assertEqual(self.db.get_question_images(qid), [])
        self.assertFalse(Path(self.db.abs_path(rel)).exists())
        self.assertEqual(self.db.next_question_code(), "Q0001")
        self.assertIsNotNone(self.db.get_question_material(mid))
        self.assertTrue(any(t["name"] == "单一指标" for t in self.db.list_topics()))

    def test_question_subtree_stats_by_map(self):
        root = self.db.add_topic("统计根")
        cat = self.db.add_topic("统计分类", parent_id=root)
        leaf = self.db.add_topic("统计细分", parent_id=cat)
        m = next(x for x in self.db.list_question_maps() if x["topic_id"] == root)
        root_node = next(
            n for n in self.db.question_types_by_map(m["id"]) if n["parent_id"] is None)
        child_a = self.db.add_question_type_full(
            "子节点A", parent_id=root_node["id"], map_id=m["id"], topic_id=cat)
        child_b = self.db.add_question_type_full(
            "子节点B", parent_id=root_node["id"], map_id=m["id"], topic_id=cat)
        grandchild = self.db.add_question_type_full(
            "孙节点", parent_id=child_a, map_id=m["id"], topic_id=leaf)

        self.db.add_question(topic_id=cat, question_text="分类题", result="wrong")
        self.db.add_question(topic_id=leaf, question_text="细分题", result="correct")

        stats = self.db.question_subtree_stats_by_map(m["id"])
        self.assertEqual(stats[root_node["id"]], (2, 1))
        self.assertEqual(stats[child_a], (2, 1))
        self.assertEqual(stats[child_b], (1, 1))
        self.assertEqual(stats[grandchild], (1, 0))

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
                                             node_width=260.0, auto_width=0)
        node = self.db.get_question_type(nid)
        self.assertEqual(node["node_width"], 260.0)
        self.assertEqual(node["auto_width"], 0)
        self.db.update_question_type_full(nid, node_width=320.0, auto_width=1)
        node = self.db.get_question_type(nid)
        self.assertEqual(node["node_width"], 320.0)
        self.assertEqual(node["auto_width"], 1)

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

    def test_question_materials_crud_and_question_link(self):
        from PIL import Image
        zl = self._leaf("资料分析")
        mid = self.db.add_question_material(
            topic_id=zl["id"], kind="passage",
            title="2026 第一篇材料", content="材料正文")
        self.assertEqual([m["id"] for m in self.db.list_question_materials(topic_id=zl["id"])], [mid])
        img_path = self.root / "mat.png"
        Image.new("RGB", (30, 30)).save(img_path)
        self.db.sync_question_material_images(mid, [], [str(img_path)])
        mat = self.db.get_question_material(mid)
        self.assertEqual(len(mat["images"]), 1)
        self.db.update_question_material(mid, title="新标题", kind="table")
        mat = self.db.get_question_material(mid)
        self.assertEqual(mat["title"], "新标题")
        self.assertEqual(mat["kind"], "table")

        qid = self.db.add_question(
            topic_id=self._leaf("单一指标")["id"], question_text="Q",
            material_id=mid, stem="题干", options="A 正确\nB 错误", answer="A",
        )
        q = self.db.get_question(qid)
        self.assertEqual(q["material_title"], "新标题")
        self.assertEqual(q["stem"], "题干")
        qrows = self.db.list_questions(material_id=mid)
        self.assertEqual(len(qrows), 1)
        self.assertEqual(qrows[0]["material_title"], "新标题")

        rel = mat["images"][0]["file_path"]
        self.db.delete_question_material(mid)
        self.assertIsNone(self.db.get_question_material(mid))
        self.assertIsNone(self.db.get_question(qid)["material_id"])
        self.assertFalse(Path(self.db.abs_path(rel)).exists())

    def test_question_detail_type_fields_and_filter(self):
        zl = self._leaf("资料分析")
        paths = dict(self.db.detail_type_paths_for_topic(zl["id"]))
        single = next(
            (qid for path, qid in paths.items() if path.endswith("/ 单一指标")),
            None,
        )
        self.assertIsNotNone(single)
        self.assertTrue(all(p.startswith("行测 / 资料分析 /") for p in paths))
        self.assertNotIn("行测 / 资料分析", paths)
        self.assertEqual(self.db.detail_type_paths_for_topic(self._leaf("自由补弱")["id"]), [])

        qid = self.db.add_question(
            topic_id=self._leaf("单一指标")["id"], question_text="细分题",
            detail_type_id=single, stem="提问", answer="B",
        )
        q = self.db.get_question(qid)
        self.assertEqual(q["detail_type_id"], single)
        self.assertTrue(q["detail_type_name"].endswith("单一指标"))
        qrows = self.db.list_questions(detail_type_id=single)
        self.assertEqual(len(qrows), 1)
        self.assertTrue(qrows[0]["detail_type_name"].endswith("单一指标"))

        extra = self.db.add_question_type_full(
            "细分子类", parent_id=single, map_id=next(
                x for x in self.db.list_question_maps() if x["subject_name"] == "行测"
            )["id"],
        )
        self.assertEqual(
            len(self.db.list_questions(detail_type_id=single)),
            1,
        )
        self.db.delete_question_type(extra)

    def test_sync_checkin_images_with_purpose_and_group(self):
        from PIL import Image
        pid = self.db.create_plan("2026-08-21")
        iid = self.db.add_plan_item(pid, self._leaf("单一指标")["id"])
        mat, know, q = (self.root / "mat.png", self.root / "know.png", self.root / "q.png")
        for p in (mat, know, q):
            Image.new("RGB", (30, 30)).save(p)
        rel_mat = self.db.store_image_from_path(str(mat))
        self.db.add_image(iid, rel_mat, sort_order=0)
        imgs = self.db.sync_checkin_images_with_purpose(iid, [
            (rel_mat, "material", "mat-1"),
            (str(know), "knowledge", ""),
            (str(q), "question", ""),
        ])
        kmap = {im["file_path"]: im for im in imgs}
        self.assertEqual(kmap[rel_mat]["purpose"], "material")
        self.assertEqual(kmap[rel_mat]["group_key"], "mat-1")
        self.assertEqual(
            {im["purpose"] for im in imgs if im["file_path"] != rel_mat},
            {"knowledge", "question"},
        )
        imgs2 = self.db.sync_checkin_images_with_purpose(iid, [
            (rel_mat, "material", "mat-2"),
        ])
        self.assertEqual(imgs2[0]["group_key"], "mat-2")
        self.db.sync_checkin_images_with_purpose(iid, [])
        self.assertFalse(Path(self.db.abs_path(rel_mat)).exists())

    def test_old_schema_migration_adds_new_columns(self):
        import sqlite3
        old_db = self.root / "old.db"
        conn = sqlite3.connect(str(old_db))
        conn.executescript("""
        CREATE TABLE topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            parent_id INTEGER REFERENCES topics(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            is_preset INTEGER NOT NULL DEFAULT 0,
            disabled INTEGER NOT NULL DEFAULT 0,
            sort_order INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE plan_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
            topic_id INTEGER NOT NULL REFERENCES topics(id),
            reminder_time TEXT,
            done INTEGER NOT NULL DEFAULT 0,
            note TEXT NOT NULL DEFAULT '',
            checked_at TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE checkin_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_item_id INTEGER NOT NULL REFERENCES plan_items(id) ON DELETE CASCADE,
            file_path TEXT NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE,
            topic_id INTEGER REFERENCES topics(id),
            source TEXT NOT NULL DEFAULT 'manual',
            source_item_id INTEGER,
            question_text TEXT NOT NULL DEFAULT '',
            analysis TEXT NOT NULL DEFAULT '',
            result TEXT,
            result_reason TEXT NOT NULL DEFAULT '',
            self_analysis TEXT NOT NULL DEFAULT '',
            correct_analysis TEXT NOT NULL DEFAULT '',
            reflection TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        INSERT INTO questions(id, code, question_text, created_at)
        VALUES (1, 'Q0001', '旧题', '2026-01-01 00:00:00');
        """)
        conn.commit()
        conn.close()
        db2 = Database(old_db, self.root / "images2", self.root)
        qcols = {r[1] for r in db2.conn.execute("PRAGMA table_info(questions)").fetchall()}
        icols = {r[1] for r in db2.conn.execute("PRAGMA table_info(checkin_images)").fetchall()}
        for col in ("material_id", "detail_type_id", "stem", "options", "answer"):
            self.assertIn(col, qcols)
        for col in ("purpose", "group_key"):
            self.assertIn(col, icols)
        self.assertIsNone(db2.get_question(1)["detail_type_id"])
        db2.close()

    def test_store_image_pil_and_path(self):
        from PIL import Image
        src = self.root / "src_kb.png"
        Image.new("RGB", (60, 40), (0, 128, 255)).save(src)
        rel = self.db.store_image(str(src))
        self.assertTrue(Path(self.db.abs_path(rel)).is_file())
        pil = Image.new("RGBA", (20, 20), (255, 0, 0, 128))
        rel2 = self.db.store_image(pil)
        self.assertTrue(Path(self.db.abs_path(rel2)).is_file())
        self.assertTrue(rel2.lower().endswith(".png"))

    def test_knowledge_block_image_cleanup(self):
        from PIL import Image
        src1 = self.root / "kb1.png"
        src2 = self.root / "kb2.png"
        Image.new("RGB", (30, 30), "red").save(src1)
        Image.new("RGB", (30, 30), "blue").save(src2)
        rel1 = self.db.store_image_from_path(str(src1))
        rel2 = self.db.store_image_from_path(str(src2))
        doc_id = self.db.add_knowledge_doc("清理文档")
        block1 = self.db.add_knowledge_block(doc_id, "块1", "<p image='{}'></p>".format(rel1))
        block2 = self.db.add_knowledge_block(doc_id, "块2", "<p image='{}'></p>".format(rel2))
        self.assertTrue(Path(self.db.abs_path(rel1)).exists())
        self.assertTrue(Path(self.db.abs_path(rel2)).exists())
        self.db.delete_knowledge_block(block2)
        self.assertFalse(Path(self.db.abs_path(rel2)).exists())
        self.assertTrue(Path(self.db.abs_path(rel1)).exists())
        block3 = self.db.add_knowledge_block(doc_id, "块3", "<p image='{}'></p>".format(rel1))
        self.db.delete_knowledge_block(block3)
        self.assertTrue(Path(self.db.abs_path(rel1)).exists())

    def test_update_and_delete_knowledge_doc_image_cleanup(self):
        from PIL import Image
        src1 = self.root / "upd1.png"
        src2 = self.root / "upd2.png"
        Image.new("RGB", (30, 30), "green").save(src1)
        Image.new("RGB", (30, 30), "black").save(src2)
        rel1 = self.db.store_image_from_path(str(src1))
        rel2 = self.db.store_image_from_path(str(src2))
        doc_id = self.db.add_knowledge_doc("更新文档")
        block_id = self.db.add_knowledge_block(doc_id, "块", "<p image='{}'></p>".format(rel1))
        self.db.update_knowledge_block(block_id, content="<p image='{}'></p>".format(rel2))
        self.assertFalse(Path(self.db.abs_path(rel1)).exists())
        self.assertTrue(Path(self.db.abs_path(rel2)).exists())
        doc2 = self.db.add_knowledge_doc("共享文档")
        self.db.add_knowledge_block(doc2, "共享块", "<p image='{}'></p>".format(rel2))
        self.db.delete_knowledge_doc(doc_id)
        self.assertTrue(Path(self.db.abs_path(rel2)).exists())
        self.db.delete_knowledge_doc(doc2)
        self.assertFalse(Path(self.db.abs_path(rel2)).exists())

    def test_rename_topic_syncs_mindmap_nodes(self):
        tid = self._leaf("单一指标")["id"]
        self.db.rename_topic(tid, "单一指标（新）")
        rows = self.db.conn.execute(
            "SELECT name FROM question_types WHERE topic_id=?", (tid,)
        ).fetchall()
        self.assertTrue(rows)
        for r in rows:
            self.assertEqual(r["name"], "单一指标（新）")
        self.assertEqual(
            self.db.topic_path(tid),
            "行测 / 资料分析 / 单一指标（新）",
        )

    def test_rename_root_topic_syncs_map_and_root_node(self):
        tid = self._leaf("行测")["id"]
        self.db.rename_topic(tid, "行政职业能力测验")
        m = next(x for x in self.db.list_question_maps() if x["topic_id"] == tid)
        self.assertEqual(m["subject_name"], "行政职业能力测验")
        root = self.db.conn.execute(
            "SELECT name FROM question_types WHERE map_id=? AND parent_id IS NULL",
            (m["id"],),
        ).fetchone()
        self.assertEqual(root["name"], "行政职业能力测验")

    def test_add_category_child_syncs_mindmap_and_knowledge(self):
        root = self.db.add_topic("同步根科目")
        m = next(x for x in self.db.list_question_maps() if x["topic_id"] == root)
        root_node = [n for n in self.db.question_types_by_map(m["id"])
                     if n["parent_id"] is None][0]
        child = self.db.add_topic("同步分类子节点", parent_id=root)
        nodes = {n["topic_id"]: n for n in self.db.question_types_by_map(m["id"])
                 if n.get("topic_id") is not None}
        self.assertIn(child, nodes)
        self.assertEqual(nodes[child]["name"], "同步分类子节点")
        self.assertEqual(nodes[child]["parent_id"], root_node["id"])
        docs = self.db.list_knowledge_docs(topic_id=child)
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["title"], "同步分类子节点")

    def test_add_child_promotes_parent_node_type(self):
        root = self.db.add_topic("类型提升根")
        parent = self.db.add_topic("中间分类", parent_id=root)
        m = next(x for x in self.db.list_question_maps() if x["topic_id"] == root)
        parent_node = self.db.conn.execute(
            "SELECT node_type FROM question_types WHERE map_id=? AND topic_id=?",
            (m["id"], parent),
        ).fetchone()
        self.assertEqual(parent_node["node_type"], "type")
        self.db.add_topic("叶子子项", parent_id=parent)
        parent_node = self.db.conn.execute(
            "SELECT node_type FROM question_types WHERE map_id=? AND topic_id=?",
            (m["id"], parent),
        ).fetchone()
        self.assertEqual(parent_node["node_type"], "category")

    def test_add_method_child_does_not_sync_mindmap_or_knowledge(self):
        root = self.db.add_topic("方法根科目")
        method = self.db.add_topic("自由补弱", parent_id=root)
        m = next(x for x in self.db.list_question_maps() if x["topic_id"] == root)
        self.assertFalse(self.db.conn.execute(
            "SELECT 1 FROM question_types WHERE map_id=? AND topic_id=?",
            (m["id"], method),
        ).fetchone())
        self.assertEqual(self.db.list_knowledge_docs(topic_id=method), [])

    def test_rename_topic_syncs_knowledge_doc_title(self):
        root = self.db.add_topic("知识同步根")
        child = self.db.add_topic("旧知识名", parent_id=root)
        self.db.rename_topic(child, "新知识名")
        docs = self.db.list_knowledge_docs(topic_id=child)
        self.assertEqual([d["title"] for d in docs], ["新知识名"])

    def test_set_topic_kind_syncs_switched_category(self):
        root = self.db.add_topic("切换根")
        method = self.db.add_topic("自由补弱", parent_id=root)
        self.db.set_topic_kind(method, "category")
        m = next(x for x in self.db.list_question_maps() if x["topic_id"] == root)
        node = self.db.conn.execute(
            "SELECT id FROM question_types WHERE map_id=? AND topic_id=?",
            (m["id"], method),
        ).fetchone()
        self.assertIsNotNone(node)
        self.assertEqual(len(self.db.list_knowledge_docs(topic_id=method)), 1)

    def test_sync_off_mindmap_flow_keeps_manual_node(self):
        root = self.db.add_topic("手动根")
        m = next(x for x in self.db.list_question_maps() if x["topic_id"] == root)
        child = self.db.add_topic("手动子节点", parent_id=root, sync=False)
        self.assertFalse(self.db.conn.execute(
            "SELECT 1 FROM question_types WHERE topic_id=?", (child,)
        ).fetchone())
        self.db.ensure_topic_knowledge_doc(child)
        self.assertEqual(len(self.db.list_knowledge_docs(topic_id=child)), 1)
        # 导图节点仍由调用方显式创建，避免知识库补建时重复插入
        self.assertEqual(
            self.db.conn.execute(
                "SELECT COUNT(*) AS n FROM question_types WHERE topic_id=?", (child,)
            ).fetchone()["n"],
            0,
        )

    def test_create_synced_topic_uses_map_root(self):
        from habit_checkin.ui.question_type_mindmap_window import create_synced_topic
        m = next(x for x in self.db.list_question_maps() if x["subject_name"] == "行测")
        root = self.db.conn.execute(
            "SELECT id FROM question_types WHERE map_id=? AND parent_id IS NULL",
            (m["id"],),
        ).fetchone()
        tid = create_synced_topic(self.db, "新细分指标", root["id"], m["id"])
        row = self.db.conn.execute(
            "SELECT name, kind, parent_id FROM topics WHERE id=?", (tid,)
        ).fetchone()
        self.assertEqual(row["name"], "新细分指标")
        self.assertEqual(row["kind"], "category")
        self.assertEqual(row["parent_id"], self._leaf("行测")["id"])

    def test_create_synced_topic_uses_linked_parent(self):
        from habit_checkin.ui.question_type_mindmap_window import create_synced_topic
        m = next(x for x in self.db.list_question_maps() if x["subject_name"] == "行测")
        zl = self._leaf("资料分析")
        qt = self.db.conn.execute(
            "SELECT id FROM question_types WHERE topic_id=? AND map_id=? LIMIT 1",
            (zl["id"], m["id"]),
        ).fetchone()
        tid = create_synced_topic(self.db, "深层细分", qt["id"], m["id"])
        parent_id = self.db.conn.execute(
            "SELECT parent_id FROM topics WHERE id=?", (tid,)
        ).fetchone()["parent_id"]
        self.assertEqual(parent_id, zl["id"])

    def test_create_synced_topic_requires_linked_map(self):
        from habit_checkin.ui.question_type_mindmap_window import create_synced_topic
        with self.assertRaises(ValueError):
            create_synced_topic(self.db, "孤立节点", None, 999999)

    def test_create_synced_topic_skips_method_parent(self):
        from habit_checkin.ui.question_type_mindmap_window import create_synced_topic
        m = next(x for x in self.db.list_question_maps() if x["subject_name"] == "行测")
        root = self.db.conn.execute(
            "SELECT id FROM question_types WHERE map_id=? AND parent_id IS NULL",
            (m["id"],),
        ).fetchone()
        method_tid = self._leaf("自由补弱")["id"]
        qt_id = self.db.add_question_type_full(
            "自由补弱", parent_id=root["id"], map_id=m["id"],
            node_type="type", topic_id=method_tid,
        )
        tid = create_synced_topic(self.db, "方法下新节点", qt_id, m["id"])
        parent_id = self.db.conn.execute(
            "SELECT parent_id FROM topics WHERE id=?", (tid,)
        ).fetchone()["parent_id"]
        self.assertEqual(parent_id, self._leaf("行测")["id"])


if __name__ == "__main__":
    unittest.main()
