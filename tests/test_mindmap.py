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
    _NODE_H,
    _MIN_GAP,
    estimate_node_width,
    initial_child_pos,
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

    def _window_from_nodes(self, nodes, layout_type):
        w = QuestionTypeMindmapWindow.__new__(QuestionTypeMindmapWindow)
        w._nodes = {n["id"]: n for n in nodes}
        w._children = {}
        for n in nodes:
            w._children.setdefault(n["parent_id"], []).append(n)
        for lst in w._children.values():
            lst.sort(key=lambda x: (x.get("sort_order") or 0, x["id"]))
        w._map = {"layout_type": layout_type}
        w._node_pos = {}
        w._auto_layout_internal()
        return w

    def _assert_min_gap(self, w):
        rects = w._visible_rects()
        ids = list(rects)
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                ax, ay, aw, ah = rects[a]
                bx, by, bw, bh = rects[b]
                acx, acy = ax + aw / 2.0, ay + ah / 2.0
                bcx, bcy = bx + bw / 2.0, by + bh / 2.0
                h_ok = abs(acx - bcx) >= (aw + bw) / 2.0 + _MIN_GAP - 1e-6
                v_ok = abs(acy - bcy) >= (ah + bh) / 2.0 + _MIN_GAP - 1e-6
                self.assertTrue(
                    h_ok or v_ok,
                    "layout={} nodes {} and {} overlap".format(
                        w._map.get("layout_type"), a, b),
                )

    def test_root_centered(self):
        for layout in ("radial", "columns", "logic"):
            _, pos = self._layout(layout)
            root = self.children[None][0]
            self.assertEqual(pos[root["id"]], (0.0, 0.0))

    def test_radial_level1_around_center(self):
        """放射布局：一级节点分布在根中心周围同一半径，覆盖超过 2/3 圆周。"""
        import math
        w, pos = self._layout("radial")
        root = self.children[None][0]
        root_w = w._node_width(root)
        kids = self.children[root["id"]]
        angles = []
        for k in kids:
            x, y = pos[k["id"]]
            cx = x + w._node_width(k) / 2.0 - root_w / 2.0
            cy = y + _NODE_H / 2.0 - _NODE_H / 2.0
            r = math.hypot(cx, cy)
            self.assertGreaterEqual(r, root_w / 2.0 + w._node_width(k) / 2.0 + _MIN_GAP)
            angles.append(math.degrees(math.atan2(cy, cx)))
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
        """两翼对称布局保留：前一半左列、后一半右列，父子边距至少 20px。"""
        w, pos = self._layout("columns")
        root = self.children[None][0]
        kids = self.children[root["id"]]
        half = (len(kids) + 1) // 2
        for k in kids[:half]:
            kx = pos[k["id"]][0]
            self.assertLess(kx, 0)
            self.assertGreaterEqual(-kx - w._node_width(k), _MIN_GAP)
        for k in kids[half:]:
            self.assertGreaterEqual(
                pos[k["id"]][0] - w._node_width(root), _MIN_GAP)

    def test_level1_symmetric_left_right(self):
        """两翼布局下：一级子节点前一半左列、后一半右列，垂直错开。"""
        w, pos = self._layout("columns")
        kids = self.children[self.children[None][0]["id"]]
        half = (len(kids) + 1) // 2
        left = [pos[k["id"]] for k in kids[:half]]
        right = [pos[k["id"]] for k in kids[half:]]
        self.assertEqual(len(left), len(right))  # 6 个一级 -> 3 左 3 右
        self.assertTrue(all(p[0] < 0 for p in left))
        self.assertTrue(all(p[0] > 0 for p in right))
        # 垂直错开：同列节点 y 各不相同（不再全部挤在根的水平线上）
        left_ys = [p[1] for p in left]
        right_ys = [p[1] for p in right]
        self.assertEqual(len(set(left_ys)), len(left))
        self.assertEqual(len(set(right_ys)), len(right))

    def test_all_layouts_keep_min_gap(self):
        """三种自动布局下，任意两个可见节点矩形至少在一个方向保留 20px。"""
        for layout in ("radial", "columns", "logic"):
            w, _ = self._layout(layout)
            self._assert_min_gap(w)

    def test_add_many_siblings_clear_in_all_layouts(self):
        """真实新增 8 个同级节点后，三种自动布局都不重叠且间距至少 20px。"""
        m = next(
            x for x in self.db.list_question_maps()
            if x["subject_name"] == "行测"
        )
        root = next(
            n for n in self.db.question_types_by_map(m["id"])
            if n["parent_id"] is None
        )
        for i in range(8):
            self.db.add_question_type_full(
                "新增节点{}".format(i + 1),
                parent_id=root["id"],
                map_id=m["id"],
                node_type="type",
            )
        nodes = self.db.question_types_by_map(m["id"])
        for layout in ("radial", "columns", "logic"):
            w = self._window_from_nodes(nodes, layout)
            self._assert_min_gap(w)

    def test_new_sibling_auto_expands(self):
        """右向逻辑图新增多个同级节点后全部向右展开且间距自动扩开。"""
        w = QuestionTypeMindmapWindow.__new__(QuestionTypeMindmapWindow)
        root = {"id": 1, "name": "根", "parent_id": None, "collapsed": 0, "node_type": "root"}
        kids = [{"id": i, "name": "节点{}".format(i), "parent_id": 1,
                 "collapsed": 0, "node_type": "type"} for i in range(2, 11)]
        w._children = {None: [root], 1: kids}
        w._nodes = {1: root}
        w._nodes.update({k["id"]: k for k in kids})
        w._map = {"layout_type": "logic"}
        w._node_pos = {}
        w._auto_layout_internal()
        rects = w._visible_rects()
        root_w = w._node_width(root)
        for n in kids:
            x, y, nw, _ = rects[n["id"]]
            self.assertGreaterEqual(x - root_w, _MIN_GAP - 1e-6)
        for i, a in enumerate(kids):
            for b in kids[i + 1:]:
                ay = rects[a["id"]][1]
                by = rects[b["id"]][1]
                self.assertGreaterEqual(by - (ay + _NODE_H), _MIN_GAP)
        child_tops = [rects[n["id"]][1] for n in kids]
        center = (min(child_tops) + max(child_tops) + _NODE_H) / 2.0
        self.assertAlmostEqual(center, _NODE_H / 2.0, places=6)

    def test_initial_child_pos_places_next_to_parent(self):
        x, y = initial_child_pos((10, 20, 170, 56), 200, [])
        self.assertEqual((x, y), (200.0, 20.0))

    def test_initial_child_pos_skips_occupied_slot(self):
        x, y = initial_child_pos((0, 0, 170, 56), 170, [(190, 0, 170, 56)])
        self.assertEqual(x, 190.0)
        self.assertGreaterEqual(y, _NODE_H + _MIN_GAP)

    def test_manual_add_node_places_next_to_parent(self):
        m = next(
            x for x in self.db.list_question_maps()
            if x["subject_name"] == "行测"
        )
        root = next(
            n for n in self.db.question_types_by_map(m["id"])
            if n["parent_id"] is None
        )
        nodes = self.db.question_types_by_map(m["id"])
        w = self._window_from_nodes(nodes, "logic")
        w._map["layout_mode"] = "manual"
        w.db = self.db
        new_id = self.db.add_question_type_full(
            "新增子节点", parent_id=root["id"], map_id=m["id"], node_type="type",
        )
        w._place_new_node_near_parent({
            "id": new_id,
            "parent_id": root["id"],
            "name": "新增子节点",
            "node_width": estimate_node_width("新增子节点"),
            "auto_width": 1,
        })
        new_node = self.db.get_question_type(new_id)
        px, py = w._node_pos[root["id"]]
        expected_x = px + w._node_width(root) + _MIN_GAP
        self.assertAlmostEqual(new_node["pos_x"], expected_x, places=6)
        # 手动布局下仍贴近父节点，不会落到原点或远离父节点的位置
        self.assertLessEqual(
            abs(new_node["pos_y"] - py), (_NODE_H + _MIN_GAP) * 6)
        w._nodes[new_id] = new_node
        w._children.setdefault(root["id"], []).append(new_node)
        w._node_pos[new_id] = (new_node["pos_x"], new_node["pos_y"])
        self._assert_min_gap(w)

    def test_logic_symmetric_around_root_center(self):
        """右向逻辑图整体围绕根节点水平中线上下对称。"""
        w, pos = self._layout("logic")
        root = self.children[None][0]
        rects = w._visible_rects()
        non_root_rects = [
            (r[1], r[1] + _NODE_H) for nid, r in rects.items()
            if nid != root["id"]
        ]
        top = min(r[0] for r in non_root_rects)
        bottom = max(r[1] for r in non_root_rects)
        self.assertAlmostEqual((top + bottom) / 2.0, _NODE_H / 2.0, places=6)
        kids = self.children[root["id"]]
        root_w = w._node_width(root)
        for k in kids:
            self.assertGreaterEqual(
                pos[k["id"]][0] - root_w, _MIN_GAP - 1e-6)

    def test_logic_parent_centered_and_root_symmetric(self):
        """父节点落在子分支组垂直中线上，整体仍围绕根节点中线对称。"""
        root = {"id": 1, "name": "根", "parent_id": None, "collapsed": 0,
                "node_type": "root"}
        a = {"id": 2, "name": "A", "parent_id": 1, "collapsed": 0,
             "node_type": "category"}
        b = {"id": 3, "name": "B", "parent_id": 1, "collapsed": 0,
             "node_type": "category"}
        leaves = [
            {"id": i, "name": "N{}".format(i), "parent_id": pid,
             "collapsed": 0, "node_type": "type"}
            for pid, ids in ((2, (4, 5)), (3, (6, 7, 8)))
            for i in ids
        ]
        nodes = [root, a, b] + leaves
        w = self._window_from_nodes(nodes, "logic")
        rects = w._visible_rects()
        for parent_id, child_ids in ((2, (4, 5)), (3, (6, 7, 8))):
            pnode = next(n for n in nodes if n["id"] == parent_id)
            py = rects[parent_id][1] + _NODE_H / 2.0
            tops = [rects[cid][1] for cid in child_ids]
            group_center = (min(tops) + max(tops) + _NODE_H) / 2.0
            self.assertAlmostEqual(group_center, py, places=6)
        non_root = [r for nid, r in rects.items() if nid != root["id"]]
        top = min(r[1] for r in non_root)
        bottom = max(r[1] + _NODE_H for r in non_root)
        self.assertAlmostEqual((top + bottom) / 2.0, _NODE_H / 2.0, places=6)
        self._assert_min_gap(w)

    def test_logic_parent_centered_recursive(self):
        """右向逻辑图逐层居中：多级父子节点都对齐各自子分支组中线。"""
        root = {"id": 1, "name": "根", "parent_id": None, "collapsed": 0,
                "node_type": "root"}
        a = {"id": 2, "name": "A", "parent_id": 1, "collapsed": 0,
             "node_type": "category"}
        b = {"id": 3, "name": "B", "parent_id": 2, "collapsed": 0,
             "node_type": "category"}
        leaves = [
            {"id": i, "name": "L{}".format(i), "parent_id": 3,
             "collapsed": 0, "node_type": "type"}
            for i in (4, 5)
        ]
        c = {"id": 6, "name": "C", "parent_id": 1, "collapsed": 0,
             "node_type": "type"}
        nodes = [root, a, b, c] + leaves
        w = self._window_from_nodes(nodes, "logic")
        rects = w._visible_rects()
        leaves_center = (
            rects[4][1] + rects[5][1] + _NODE_H
        ) / 2.0
        for pid in (2, 3):
            py = rects[pid][1] + _NODE_H / 2.0
            self.assertAlmostEqual(leaves_center, py, places=6)
        non_root = [r for nid, r in rects.items() if nid != root["id"]]
        top = min(r[1] for r in non_root)
        bottom = max(r[1] + _NODE_H for r in non_root)
        self.assertAlmostEqual((top + bottom) / 2.0, _NODE_H / 2.0, places=6)
        self._assert_min_gap(w)

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
        target_cx = w._node_pos[3][0] + w._node_width(b) / 2  # 目标中心 x
        w._node_pos[2] = (target_cx - w._node_width(a) / 2 + 3.0, w._node_pos[2][1])
        vx, vy = w._snap_guides(2)
        self.assertIsNotNone(vx)
        self.assertAlmostEqual(vx, target_cx, places=6)
        self.assertAlmostEqual(w._node_pos[2][0] + w._node_width(a) / 2, target_cx, places=6)
        # 远离时不对齐
        w._node_pos[2] = (target_cx - w._node_width(a) / 2 + 5000.0, w._node_pos[2][1])
        vx2, vy2 = w._snap_guides(2)
        self.assertIsNone(vx2)

    def test_estimate_node_width_single_line(self):
        """自动宽度随名称长短变化，手动宽度保留用户设定值。"""
        short = estimate_node_width("资料分析")
        long = estimate_node_width("逻辑填空（选词填空）")
        self.assertGreater(long, short)
        self.assertGreaterEqual(short, 120.0)
        auto = {"name": "短", "node_width": 300.0, "auto_width": 1}
        self.assertEqual(
            QuestionTypeMindmapWindow._node_width(auto),
            estimate_node_width("短"),
        )
        auto["name"] = "这是一个更长的节点名称"
        self.assertGreater(
            QuestionTypeMindmapWindow._node_width(auto),
            estimate_node_width("短"),
        )
        node = {"name": "短", "node_width": 300.0, "auto_width": 0}
        self.assertEqual(QuestionTypeMindmapWindow._node_width(node), 300.0)


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
        self.assertIn("- 识别题型：看对称", text)
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


class TestDetailSidebarScrolling(unittest.TestCase):
    """节点详情侧边栏应可滚动查看溢出 UI 高度的内容（真实 Tk 窗口冒烟测试）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root_dir = Path(self.tmp.name)
        self.db = Database(root_dir / "app.db", root_dir / "images", root_dir)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_detail_sidebar_scrollable(self):
        import tkinter as tk
        from habit_checkin.ui.question_type_mindmap_window import QuestionTypeMindmapWindow

        root = tk.Tk()
        root.geometry("960x640+-10000+-10000")
        try:
            win = QuestionTypeMindmapWindow(root, self.db)
            win.pack(fill="both", expand=True)
            win.update_idletasks()
            root.update_idletasks()
            # 抽屉动画依赖真实延时，测试里直接同步展开，避免遗留定时回调
            win._animate_detail = lambda target, ms=140, steps=8, **kwargs: \
                win.detail_frame.configure(width=target)

            m = next(x for x in self.db.list_question_maps()
                     if x["subject_name"] == "行测")
            leaf = next(n for n in self.db.question_types_by_map(m["id"])
                        if n["name"] == "逻辑填空（选词填空）")
            win._select_node(leaf["id"])
            # 推完展开动画与布局计算
            for _ in range(20):
                root.update()

            scroll = win.detail_scroll
            self.assertIsNotNone(scroll.vsb)
            region = scroll.canvas.cget("scrollregion") or ""
            parts = [float(x) for x in region.split()]
            self.assertEqual(len(parts), 4)
            self.assertGreater(parts[3] - parts[1], 0)  # 内容有实际高度可滚动
            scroll.canvas.yview_moveto(1.0)
            top, _ = scroll.canvas.yview()
            self.assertGreater(top, 0.0)  # 滚动条可把内容滚出可视区
        finally:
            root.destroy()


class TestDetailSidebarDynamicHeight(unittest.TestCase):
    """节点详情侧边栏内容应随富文本增多动态增高（真实 Tk 窗口冒烟测试）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root_dir = Path(self.tmp.name)
        self.db = Database(root_dir / "app.db", root_dir / "images", root_dir)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_detail_fields_grow_with_content(self):
        import tkinter as tk
        from habit_checkin.ui.question_type_mindmap_window import QuestionTypeMindmapWindow

        root = tk.Tk()
        root.geometry("960x640+-10000+-10000")
        try:
            win = QuestionTypeMindmapWindow(root, self.db)
            win.pack(fill="both", expand=True)
            root.update()
            win._animate_detail = lambda target, ms=140, steps=8, **kwargs: \
                win.detail_frame.configure(width=target)

            m = next(x for x in self.db.list_question_maps()
                     if x["subject_name"] == "行测")
            leaf = next(n for n in self.db.question_types_by_map(m["id"])
                        if n["name"] == "逻辑填空（选词填空）")
            win._select_node(leaf["id"])
            for _ in range(20):
                root.update()

            short_editable = int(win.detail_texts["recognition"].text.cget("height"))
            short_remark = int(win.detail_texts["remark"].text.cget("height"))
            region_short = [float(x) for x in
                            (win.detail_scroll.canvas.cget("scrollregion") or "").split()]

            long_text = "<p>{}</p>".format(
                "随内容增多的完整解题说明。" * 80)
            win.detail_texts["recognition"].set_html(long_text)
            win.detail_texts["method"].set_html(long_text)
            win.detail_texts["remark"].set_html(long_text)
            for _ in range(30):
                root.update()

            long_editable = int(win.detail_texts["recognition"].text.cget("height"))
            long_remark = int(win.detail_texts["remark"].text.cget("height"))
            region_long = [float(x) for x in
                           (win.detail_scroll.canvas.cget("scrollregion") or "").split()]

            self.assertGreater(long_editable, short_editable)
            self.assertGreater(long_remark, short_remark)
            self.assertGreater(region_long[3] - region_long[1],
                               region_short[3] - region_short[1])
        finally:
            root.destroy()

    def test_detail_fields_keep_growing_beyond_twelve_lines(self):
        """超过 12 行后仍应继续随内容增高，不能停在固定行数。"""
        import tkinter as tk
        from habit_checkin.ui.question_type_mindmap_window import QuestionTypeMindmapWindow

        root = tk.Tk()
        root.geometry("960x640+-10000+-10000")
        try:
            win = QuestionTypeMindmapWindow(root, self.db)
            win.pack(fill="both", expand=True)
            root.update()
            win._animate_detail = lambda target, ms=140, steps=8, **kwargs: \
                win.detail_frame.configure(width=target)

            m = next(x for x in self.db.list_question_maps()
                     if x["subject_name"] == "行测")
            leaf = next(n for n in self.db.question_types_by_map(m["id"])
                        if n["name"] == "逻辑填空（选词填空）")
            win._select_node(leaf["id"])
            for _ in range(20):
                root.update()

            mid_text = "<p>{}</p>".format("识别与解题说明。" * 18)
            long_text = "<p>{}</p>".format("识别与解题说明。" * 38)
            win.detail_texts["recognition"].set_html(mid_text)
            for _ in range(20):
                root.update()
            mid_height = int(win.detail_texts["recognition"].text.cget("height"))

            win.detail_texts["recognition"].set_html(long_text)
            for _ in range(20):
                root.update()
            long_height = int(win.detail_texts["recognition"].text.cget("height"))

            self.assertGreater(long_height, mid_height)
            self.assertGreaterEqual(long_height, 13)
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
