"""思维导图模块测试：坐标变换、统计查询、Markdown 导出。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from habit_checkin.db import Database
from habit_checkin.services.mindmap_export import export_mindmap_markdown
from habit_checkin.ui.question_type_mindmap_window import (
    QuestionTypeMindmapWindow,
    _NODE_W,
    bezier_curve,
    round_rect_points,
    screen_to_world,
    world_to_screen,
)


class TestMindmapTransforms(unittest.TestCase):
    """世界坐标 <-> 屏幕坐标变换（缩放/平移的数学核心）。"""

    def test_roundtrip(self):
        scale, ox, oy = 1.0, 0.0, 0.0
        wx, wy = 120.0, 300.0
        sx, sy = world_to_screen(wx, wy, scale, ox, oy)
        self.assertEqual((sx, sy), (120.0, 300.0))
        self.assertEqual(screen_to_world(sx, sy, scale, ox, oy), (wx, wy))

    def test_roundtrip_scaled_and_offset(self):
        scale, ox, oy = 1.5, -200.0, 80.0
        for wx, wy in [(0.0, 0.0), (170.0, 52.0), (-40.0, 1000.0)]:
            sx, sy = world_to_screen(wx, wy, scale, ox, oy)
            back = screen_to_world(sx, sy, scale, ox, oy)
            self.assertAlmostEqual(back[0], wx, places=6)
            self.assertAlmostEqual(back[1], wy, places=6)

    def test_zoom_keeps_anchor_world_point(self):
        """缩放锚点：缩放前后光标下的世界点应保持在同一屏幕位置。"""
        scale, ox, oy = 1.0, 40.0, 40.0
        cx, cy = 300.0, 200.0
        wx, wy = screen_to_world(cx, cy, scale, ox, oy)
        new_scale = 1.5
        new_ox = cx - wx * new_scale
        new_oy = cy - wy * new_scale
        sx, sy = world_to_screen(wx, wy, new_scale, new_ox, new_oy)
        self.assertAlmostEqual(sx, cx, places=6)
        self.assertAlmostEqual(sy, cy, places=6)

    def test_bezier_curve_endpoints_and_direction(self):
        """曲线经过端点；水平方向正确的连线（父在左、子在右）。"""
        p0, p1 = (100.0, 50.0), (400.0, 150.0)
        pts = bezier_curve(p0, p1)
        self.assertEqual(len(pts), 21)
        self.assertAlmostEqual(pts[0][0], p0[0])
        self.assertAlmostEqual(pts[0][1], p0[1])
        self.assertAlmostEqual(pts[-1][0], p1[0])
        self.assertAlmostEqual(pts[-1][1], p1[1])
        # 中间点单调向右（水平展开）
        xs = [p[0] for p in pts]
        self.assertEqual(xs, sorted(xs))

    def test_bezier_curve_backward(self):
        """向左展开（子在父左侧）时曲线仍平滑经过两端点。"""
        pts = bezier_curve((400.0, 100.0), (100.0, 80.0))
        self.assertAlmostEqual(pts[0], (400.0, 100.0))
        self.assertAlmostEqual(pts[-1], (100.0, 80.0))
        xs = [p[0] for p in pts]
        self.assertEqual(xs, sorted(xs, reverse=True))

    def test_round_rect_points(self):
        """圆角矩形点列：坐标对成组、不超出边界、圆角半径受限。"""
        pts = round_rect_points(0, 0, 100, 50, 10)
        self.assertEqual(len(pts) % 2, 0)
        xs = pts[0::2]
        ys = pts[1::2]
        self.assertGreaterEqual(min(xs), 0)
        self.assertLessEqual(max(xs), 100)
        self.assertGreaterEqual(min(ys), 0)
        self.assertLessEqual(max(ys), 50)
        # 圆角半径被限制为宽高较小者的一半
        pts2 = round_rect_points(0, 0, 20, 10, 100)
        self.assertEqual(pts2[0], 5.0)  # r = min(100, 10, 5) = 5


class TestLayout(unittest.TestCase):
    """对称布局与折叠隐藏逻辑（纯逻辑，无需 tkinter 窗口）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = Database(self.root / "app.db", self.root / "images", self.root)
        m = next(x for x in self.db.list_question_maps() if x["subject_name"] == "行测")
        nodes = self.db.question_types_by_map(m["id"])
        self.children = {}
        for n in nodes:
            self.children.setdefault(n["parent_id"], []).append(n)
        for lst in self.children.values():
            lst.sort(key=lambda x: (x.get("sort_order") or 0, x["id"]))

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def _layout(self, layout_type="radial"):
        w = QuestionTypeMindmapWindow.__new__(QuestionTypeMindmapWindow)
        w._children = self.children
        w._nodes = {}
        for pid, kids in self.children.items():
            for k in kids:
                w._nodes[k["id"]] = k
        w._map = {"layout_type": layout_type}
        w._node_pos = {}
        w._auto_layout_internal()
        return w, w._node_pos

    def test_root_centered(self):
        for layout in ("radial", "columns"):
            _, pos = self._layout(layout)
            root = self.children[None][0]
            self.assertEqual(pos[root["id"]], (0.0, 0.0))

    def test_radial_level1_around_center(self):
        """放射布局：一级节点分布在根周围同一半径，覆盖超过 2/3 圆周。"""
        import math
        w, pos = self._layout("radial")
        root = self.children[None][0]
        kids = self.children[root["id"]]
        angles = []
        for k in kids:
            x, y = pos[k["id"]]
            r = math.hypot(x, y)
            self.assertAlmostEqual(r, 260.0, delta=1e-6)
            angles.append(math.degrees(math.atan2(y, x)))
        angles.sort()
        gaps = []
        for i in range(len(angles)):
            nxt = angles[(i + 1) % len(angles)]
            gap = (nxt - angles[i]) % 360
            gaps.append(gap)
        spread = 360 - max(gaps)
        self.assertGreater(spread, 240)

    def test_radial_free_float_skipped(self):
        """自由主题节点及其子树保留原位，不参与放射布局。"""
        w, pos = self._layout("radial")
        root = self.children[None][0]
        kids = self.children[root["id"]]
        a = kids[0]
        w._nodes[a["id"]]["free_float"] = 1
        w._nodes[a["id"]]["pos_x"] = 1234.0   # 模拟 DB 中已摆放的自由位置
        w._nodes[a["id"]]["pos_y"] = -567.0
        w._auto_layout_internal()
        x, y = w._node_pos[a["id"]]
        self.assertEqual((x, y), (1234.0, -567.0))

    def test_columns_layout_kept(self):
        """两翼对称布局保留：前一半左列、后一半右列。"""
        _, pos = self._layout("columns")
        kids = self.children[self.children[None][0]["id"]]
        half = (len(kids) + 1) // 2
        for k in kids[:half]:
            self.assertEqual(pos[k["id"]][0], -240.0)
        for k in kids[half:]:
            self.assertEqual(pos[k["id"]][0], 240.0)

    def test_level1_symmetric_left_right(self):
        """两翼布局下：一级子节点前一半左列、后一半右列，垂直错开。"""
        _, pos = self._layout("columns")
        kids = self.children[self.children[None][0]["id"]]
        half = (len(kids) + 1) // 2
        left = [pos[k["id"]] for k in kids[:half]]
        right = [pos[k["id"]] for k in kids[half:]]
        self.assertEqual(len(left), len(right))  # 6 个一级 -> 3 左 3 右
        for p in left:
            self.assertEqual(p[0], -240.0)
        for p in right:
            self.assertEqual(p[0], 240.0)
        # 垂直错开：同列节点 y 各不相同（不再全部挤在根的水平线上）
        left_ys = [p[1] for p in left]
        right_ys = [p[1] for p in right]
        self.assertEqual(len(set(left_ys)), len(left))
        self.assertEqual(len(set(right_ys)), len(right))

    def test_child_starts_at_parent_level(self):
        """子节点从父节点水平线向下排列：首个子节点与父节点同水平。"""
        _, pos = self._layout("columns")
        kids = self.children[self.children[None][0]["id"]]
        yanyu = next(k for k in kids if k["name"] == "言语理解与表达")
        sub = self.children[yanyu["id"]][0]
        self.assertAlmostEqual(pos[sub["id"]][1], pos[yanyu["id"]][1], places=6)
        # 兄弟子节点依次向下
        sub2 = self.children[yanyu["id"]][1]
        self.assertGreater(pos[sub2["id"]][1], pos[sub["id"]][1])

    def test_hidden_ids_on_collapse(self):
        """折叠隐藏：折叠节点的一整棵子树被隐藏，展开后不再隐藏。"""
        w = QuestionTypeMindmapWindow.__new__(QuestionTypeMindmapWindow)
        w._children = self.children
        by_id = {}
        for pid, kids in self.children.items():
            for k in kids:
                by_id[k["id"]] = k
        # 找到「言语理解与表达」及其子节点
        yanyu = next(k for k in self.children[self.children[None][0]["id"]]
                     if k["name"] == "言语理解与表达")
        luoji = next(k for k in self.children[yanyu["id"]] if k["name"] == "逻辑填空（选词填空）")
        by_id[yanyu["id"]]["collapsed"] = 1
        hidden = w._hidden_ids()
        self.assertIn(luoji["id"], hidden)
        self.assertNotIn(yanyu["id"], hidden)
        by_id[yanyu["id"]]["collapsed"] = 0
        self.assertNotIn(luoji["id"], w._hidden_ids())

    def test_snap_guides_align_and_absorb(self):
        """拖拽对齐：靠近目标中心时吸附，并返回贯穿辅助线位置。"""
        w = QuestionTypeMindmapWindow.__new__(QuestionTypeMindmapWindow)
        root = {"id": 1, "name": "根", "parent_id": None, "collapsed": 0, "node_type": "subject"}
        a = {"id": 2, "name": "A", "parent_id": 1, "collapsed": 0, "node_type": "type"}
        b = {"id": 3, "name": "B", "parent_id": 1, "collapsed": 0, "node_type": "type"}
        w._children = {None: [root], 1: [a, b]}
        w._nodes = {1: root, 2: a, 3: b}
        w._map = {"layout_type": "columns"}
        w._scale = 1.0
        w._node_pos = {}
        w._auto_layout_internal()
        target_cx = w._node_pos[3][0] + _NODE_W / 2  # 目标中心 x
        w._node_pos[2] = (target_cx - _NODE_W / 2 + 3.0, w._node_pos[2][1])
        vx, vy = w._snap_guides(2)
        self.assertIsNotNone(vx)
        self.assertAlmostEqual(vx, target_cx, places=6)
        self.assertAlmostEqual(w._node_pos[2][0] + _NODE_W / 2, target_cx, places=6)
        # 远离时不对齐
        w._node_pos[2] = (target_cx - _NODE_W / 2 + 5000.0, w._node_pos[2][1])
        vx2, vy2 = w._snap_guides(2)
        self.assertIsNone(vx2)


class TestMindmapStats(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = Database(self.root / "app.db", self.root / "images", self.root)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def _map_for(self, name):
        tid = self.db.add_topic(name)
        m = next(x for x in self.db.list_question_maps() if x["topic_id"] == tid)
        return m

    def test_stats_by_map(self):
        m = self._map_for("StatsMap")
        root = [n for n in self.db.question_types_by_map(m["id"]) if n["parent_id"] is None][0]
        leaf = self._leaf("图形推理")
        self.db.add_question_type_full("图推", parent_id=root["id"], map_id=m["id"],
                                       topic_id=leaf["id"])
        self.db.add_question(topic_id=leaf["id"], question_text="一", result="wrong")
        self.db.add_question(topic_id=leaf["id"], question_text="二", result="correct")
        self.db.add_question(topic_id=leaf["id"], question_text="三", result="wrong")
        stats = self.db.question_stats_by_map(m["id"])
        self.assertEqual(stats.get(leaf["id"]), (3, 2))
        # 未关联节点的知识点不计入
        other = self._leaf("大作文")
        self.db.add_question(topic_id=other["id"], question_text="无关", result="wrong")
        self.assertNotIn(other["id"], self.db.question_stats_by_map(m["id"]))

    def test_node_topic_id_roundtrip(self):
        m = self._map_for("TopicIdMap")
        root = [n for n in self.db.question_types_by_map(m["id"]) if n["parent_id"] is None][0]
        leaf = self._leaf("逻辑填空（选词填空）")
        nid = self.db.add_question_type_full("节点", parent_id=root["id"], map_id=m["id"],
                                             topic_id=leaf["id"])
        node = self.db.get_question_type(nid)
        self.assertEqual(node["topic_id"], leaf["id"])
        self.db.update_question_type_full(nid, topic_id=None)
        self.assertIsNone(self.db.get_question_type(nid)["topic_id"])

    def _leaf(self, name):
        return [t for t in self.db.list_topics() if t["name"] == name][0]


class TestMindmapExport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = Database(self.root / "app.db", self.root / "images", self.root)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_export_markdown(self):
        m = next(x for x in self.db.list_question_maps()
                 if x["subject_name"] == "行测")
        root = [n for n in self.db.question_types_by_map(m["id"]) if n["parent_id"] is None][0]
        self.db.add_question_type_full("图推技巧", parent_id=root["id"], map_id=m["id"],
                                       recognition="看对称", approach="先整体后局部")
        out = self.root / "map.md"
        export_mindmap_markdown(self.db, m["id"], str(out))
        text = out.read_text(encoding="utf-8")
        self.assertIn("# 行测 题型思维导图", text)
        self.assertIn("- 图推技巧", text)
        self.assertIn("- 识别方法：看对称", text)
        self.assertIn("- 解题思路：先整体后局部", text)

    def test_export_missing_map(self):
        with self.assertRaises(ValueError):
            export_mindmap_markdown(self.db, 99999, str(self.root / "x.md"))


class TestPresetImport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = Database(self.root / "app.db", self.root / "images", self.root)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def _map(self, name):
        return next(x for x in self.db.list_question_maps() if x["subject_name"] == name)

    def test_auto_imported_once(self):
        """首次初始化后预置科目导图自动包含知识点树，且只执行一次。"""
        m = self._map("行测")
        names = [n["name"] for n in self.db.question_types_by_map(m["id"])]
        self.assertIn("言语理解与表达", names)
        self.assertIn("逻辑填空（选词填空）", names)
        self.assertEqual(self.db.get_setting("mindmap_preset_imported"), "1")
        # 幂等：重复初始化不重复导入
        self.db._seed_question_types()
        self.assertEqual(len(self.db.question_types_by_map(m["id"])), len(names))

    def test_hierarchy_and_topic_link(self):
        """中间层 -> category、叶子 -> type，且均关联 topic_id、父子关系正确。"""
        m = self._map("行测")
        nodes = {n["name"]: n for n in self.db.question_types_by_map(m["id"])}
        yanyu = nodes["言语理解与表达"]
        luoji = nodes["逻辑填空（选词填空）"]
        self.assertEqual(yanyu["node_type"], "category")
        self.assertEqual(luoji["node_type"], "type")
        self.assertIsNotNone(yanyu["topic_id"])
        self.assertIsNotNone(luoji["topic_id"])
        self.assertEqual(luoji["parent_id"], yanyu["id"])

    def test_stats_via_imported_link(self):
        """导入即关联：往预置叶子知识点加题，导图节点统计直接生效。"""
        m = self._map("行测")
        luoji = next(n for n in self.db.question_types_by_map(m["id"])
                     if n["name"] == "逻辑填空（选词填空）")
        self.db.add_question(topic_id=luoji["topic_id"], question_text="一", result="wrong")
        self.db.add_question(topic_id=luoji["topic_id"], question_text="二", result="correct")
        self.assertEqual(self.db.question_stats_by_map(m["id"])[luoji["topic_id"]], (2, 1))

    def test_manual_import_idempotent_and_skip_same_name(self):
        """手动导入幂等；同名分支（含子树）被跳过，其余分支正常导入。"""
        m = self._map("行测")
        root = [n for n in self.db.question_types_by_map(m["id"]) if n["parent_id"] is None][0]
        # 清空子节点，手建一个同名节点
        for n in self.db.question_types_by_map(m["id"]):
            if n["parent_id"] is not None:
                self.db.delete_question_type(n["id"])
        self.db.add_question_type_full("言语理解与表达", parent_id=root["id"], map_id=m["id"])
        n = self.db.import_preset_question_types(m["id"])
        self.assertGreater(n, 0)
        names = [x["name"] for x in self.db.question_types_by_map(m["id"])]
        self.assertEqual(names.count("言语理解与表达"), 1)          # 同名分支跳过
        self.assertNotIn("逻辑填空（选词填空）", names)              # 其子树随之跳过
        self.assertIn("数量关系", names)                             # 其他分支照常导入
        # 再次导入为 0
        self.assertEqual(self.db.import_preset_question_types(m["id"]), 0)

    def test_custom_map_not_affected(self):
        """自定义科目（无预置知识点）导入为 0。"""
        tid = self.db.add_topic("自定义科目")
        m = next(x for x in self.db.list_question_maps() if x["topic_id"] == tid)
        self.assertEqual(self.db.import_preset_question_types(m["id"]), 0)


class TestMoveQuestionType(unittest.TestCase):
    """拖拽改层级 / 同级重排 / 防环（数据层）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = Database(self.root / "app.db", self.root / "images", self.root)
        m = next(x for x in self.db.list_question_maps() if x["subject_name"] == "行测")
        self.m = m
        self.root_node = [n for n in self.db.question_types_by_map(m["id"])
                          if n["parent_id"] is None][0]

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def _add(self, name, parent_id=None):
        return self.db.add_question_type_full(name, parent_id=parent_id, map_id=self.m["id"])

    def _abc(self, parent_id):
        """根下测试节点顺序（忽略预置节点）。"""
        return [n["name"] for n in self.db.question_type_children(parent_id)
                if n["name"] in ("A", "B", "C")]

    def test_move_to_new_parent(self):
        a = self._add("A", parent_id=self.root_node["id"])
        b = self._add("B", parent_id=self.root_node["id"])
        c = self._add("C", parent_id=self.root_node["id"])
        self.db.move_question_type(a, c, None)  # A 成为 C 的子节点
        self.assertEqual(self.db.get_question_type(a)["parent_id"], c)
        self.assertEqual(self._abc(self.root_node["id"]), ["B", "C"])

    def test_same_parent_reorder(self):
        a = self._add("A", parent_id=self.root_node["id"])
        b = self._add("B", parent_id=self.root_node["id"])
        c = self._add("C", parent_id=self.root_node["id"])
        # 拖 A 到 C 之后：按 C 在根下的绝对位置 + 1（与 UI 逻辑一致）
        siblings = self.db.question_type_children(self.root_node["id"])
        c_index = next(i for i, n in enumerate(siblings) if n["id"] == c)
        self.db.move_question_type(a, self.root_node["id"], c_index + 1)
        self.assertEqual(self._abc(self.root_node["id"]), ["B", "C", "A"])
        # 拖 A 到开头
        self.db.move_question_type(a, self.root_node["id"], 0)
        self.assertEqual(self._abc(self.root_node["id"]), ["A", "B", "C"])

    def test_cycle_rejected(self):
        a = self._add("A", parent_id=self.root_node["id"])
        b = self._add("B", parent_id=a)
        c = self._add("C", parent_id=b)
        with self.assertRaises(ValueError):
            self.db.move_question_type(a, c)   # 移到自身后代下
        with self.assertRaises(ValueError):
            self.db.move_question_type(self.root_node["id"], a)  # 科目根不能移动
        with self.assertRaises(ValueError):
            self.db.move_question_type(a, 99999)  # 目标不存在

    def test_free_float_roundtrip(self):
        a = self._add("Float", parent_id=self.root_node["id"])
        self.db.update_question_type_full(a, free_float=1, pos_x=12.0, pos_y=34.0)
        node = self.db.get_question_type(a)
        self.assertEqual(node["free_float"], 1)
        self.assertEqual(node["pos_x"], 12.0)
        self.assertEqual(node["pos_y"], 34.0)
        self.db.update_question_type_full(a, free_float=0)
        self.assertEqual(self.db.get_question_type(a)["free_float"], 0)


if __name__ == "__main__":
    unittest.main()
