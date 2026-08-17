# -*- coding: utf-8 -*-
"""可视化题型思维导图：每个科目独立导图，Canvas 绘制、可交互增删改、折叠展开。

渲染模型：节点位置（_node_pos）存「世界坐标」并持久化到 pos_x/pos_y；
画布绘制前经 scale + 偏移换算成屏幕坐标。缩放/平移只改视图状态
（view_scale/view_offset_x/view_offset_y），不污染节点数据。
"""
from __future__ import annotations

import math
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk

from habit_checkin.services.mindmap_export import export_mindmap_markdown
from habit_checkin.ui.animate import lerp_color
from habit_checkin.ui.common import center_window, setup_styles
from habit_checkin.ui.theme import PALETTE, dialog_header
from habit_checkin.ui.theme_menu import ThemeMenu

_NODE_TYPE_LABELS = {
    "root": "总览",
    "subject": "科目",
    "category": "分类",
    "type": "题型",
}

_LAYOUT_LABELS = {"radial": "环形放射", "columns": "两翼对称", "logic": "右向逻辑图"}

_NODE_COLORS = {
    "root": "#2D6CDF",
    "subject": "#4A7BE0",
    "category": "#16A34A",
    "type": "#F59E0B",
}

_RESULT_LABELS = {"correct": "正确", "wrong": "错误", None: "未判定"}

_NODE_W = 170.0   # 节点宽（世界单位）
_NODE_H = 56.0    # 节点高（世界单位）
_MIN_SCALE = 0.3
_MAX_SCALE = 3.0
_ZOOM_STEP = 1.15
# 高错率预警：错题数 >= 2 且错题占比 >= 40%
_WARN_MIN_WRONG = 2
_WARN_RATE = 0.4


def world_to_screen(wx, wy, scale, off_x, off_y):
    """世界坐标 -> 屏幕坐标。"""
    return wx * scale + off_x, wy * scale + off_y


def screen_to_world(sx, sy, scale, off_x, off_y):
    """屏幕坐标 -> 世界坐标。"""
    return (sx - off_x) / scale, (sy - off_y) / scale


def bezier_curve(p0, p1, steps=20):
    """三次贝塞尔连线：两端水平切线（思维导图风格 S 曲线），返回点列。

    控制点 C1=(p0.x+dx, p0.y)、C2=(p1.x-dx, p1.y)，dx 取水平距离的一半，
    使曲线在起点水平出、终点水平入；向左展开时 dx 为负自动反向。
    """
    dx = (p1[0] - p0[0]) * 0.5
    c1x, c1y = p0[0] + dx, p0[1]
    c2x, c2y = p1[0] - dx, p1[1]
    pts = []
    for i in range(steps + 1):
        t = i / steps
        mt = 1 - t
        x = mt ** 3 * p0[0] + 3 * mt * mt * t * c1x + 3 * mt * t * t * c2x + t ** 3 * p1[0]
        y = mt ** 3 * p0[1] + 3 * mt * mt * t * c1y + 3 * mt * t * t * c2y + t ** 3 * p1[1]
        pts.append((x, y))
    return pts


def round_rect_points(x, y, w, h, r):
    """圆角矩形多边形点列（create_polygon 用，配合 smooth=True 更圆润）。"""
    r = min(max(r, 0), w / 2, h / 2)
    return [
        x + r, y, x + w - r, y, x + w, y, x + w, y + r,
        x + w, y + h - r, x + w, y + h, x + w - r, y + h,
        x + r, y + h, x, y + h, x, y + h - r, x, y + r, x, y,
    ]


class QuestionTypeMindmapWindow(tk.Frame):
    def __init__(self, master, db):
        super().__init__(master, bg=PALETTE["bg"])
        self.db = db
        self._nodes = {}
        self._children = {}
        self._node_items = {}  # canvas item id -> node id
        self._node_pos = {}    # node id -> (world x, world y)
        self._node_rect = {}
        self._collapse_buttons = {}
        self._stats = {}       # topic_id -> (total, wrong)
        self._selected_id = None
        self._drag_id = None
        self._drag_off = (0, 0)
        self._drag_start = (0, 0)
        self._drag_target = None
        self._drag_subtree = []
        self._drag_orig = {}
        self._drag_anchor = (0, 0)
        self._pan_active = False
        self._pan_start = None
        self._pan_off0 = (0, 0)
        self._scale = 1.0
        self._off_x = 40.0
        self._off_y = 40.0
        self._search_results = []
        self._search_idx = 0
        self._last_search = ""
        self._detail_questions = []
        self._detail_open = False
        self._detail_anim_id = 0
        setup_styles(self)
        self.configure(bg=PALETTE["bg"])
        self._build_ui()
        self._load_maps()

    def refresh(self):
        """主窗口切换页面时由 MainWindow 调用。"""
        self._load_maps()

    # ---------- UI ----------
    def _build_ui(self):
        P = PALETTE
        dialog_header(self, "题型思维导图", "每科一图 · 可视化 · 可交互")
        top = tk.Frame(self, bg=P["bg"], padx=14, pady=8)
        top.pack(fill="x")

        row1 = tk.Frame(top, bg=P["bg"])
        row1.pack(fill="x", pady=(0, 6))
        tk.Label(row1, text="科目：", bg=P["bg"]).pack(side="left")
        self.map_var = tk.StringVar()
        self.map_box = ttk.Combobox(row1, textvariable=self.map_var, state="readonly", width=12)
        self.map_box.pack(side="left", padx=(0, 10))
        self.map_box.bind("<<ComboboxSelected>>", lambda e: self._load_current_map())

        ttk.Button(row1, text="＋ 新增节点", style="Accent.TButton", command=self._add_node).pack(side="left", padx=4)
        ttk.Button(row1, text="编辑", command=self._edit_node).pack(side="left", padx=4)
        ttk.Button(row1, text="删除", command=self._delete_node).pack(side="left", padx=4)
        ttk.Button(row1, text="展开全部", command=self._expand_all).pack(side="left", padx=4)
        ttk.Button(row1, text="折叠全部", command=self._collapse_all).pack(side="left", padx=4)

        row2 = tk.Frame(top, bg=P["bg"])
        row2.pack(fill="x")
        ttk.Button(row2, text="自动布局", command=self._fit_view).pack(side="left", padx=4)
        tk.Label(row2, text="布局：", bg=P["bg"]).pack(side="left", padx=(12, 0))
        self.layout_var = tk.StringVar()
        self.layout_box = ttk.Combobox(row2, textvariable=self.layout_var, state="readonly", width=10,
                                       values=list(_LAYOUT_LABELS.values()))
        self.layout_box.pack(side="left", padx=(0, 8))
        self.layout_box.bind("<<ComboboxSelected>>", lambda e: self._set_layout())
        ttk.Button(row2, text="导入预置", command=self._import_preset).pack(side="left", padx=4)
        tk.Label(row2, text="搜索：", bg=P["bg"]).pack(side="left", padx=(12, 0))
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(row2, textvariable=self.search_var, width=12)
        self.search_entry.pack(side="left", padx=(0, 4))
        self.search_entry.bind("<Return>", self._search_nodes)
        ttk.Button(row2, text="定位", command=self._search_nodes).pack(side="left", padx=(0, 4))
        ttk.Button(row2, text="导出", command=self._export).pack(side="right")

        body = tk.Frame(self, bg=P["bg"])
        body.pack(fill="both", expand=True, padx=10, pady=(0, 8))

        self._canvas_frame = ttk.LabelFrame(
            body, text="思维导图画布（拖空白平移 · Ctrl+滚轮缩放 · 双击空白复位）", padding=4)
        self._canvas_frame.pack(side="left", fill="both", expand=True)
        self.canvas = tk.Canvas(self._canvas_frame, bg=PALETTE["input"], highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Button-1>", self._on_canvas_click)
        self.canvas.bind("<B1-Motion>", self._on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_canvas_release)
        self.canvas.bind("<Double-Button-1>", self._on_double_click)
        self.canvas.bind("<Button-3>", self._on_right_click)
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Control-MouseWheel>", self._on_control_mousewheel)

        # 节点详情抽屉：默认收起，点击节点时从右侧滑出，点击空白处收回
        right = ttk.LabelFrame(body, text="节点详情", padding=8)
        self.detail_frame = right
        right.pack_propagate(False)
        right.configure(width=0)
        self.detail_name = tk.Label(right, text="请选择节点", bg=PALETTE["surface"], fg=PALETTE["text"],
                                    font=("Microsoft YaHei UI", 15, "bold"), anchor="w")
        self.detail_name.pack(fill="x", pady=(0, 2))
        self.detail_type = tk.Label(right, text="", bg=PALETTE["surface"], fg=PALETTE["muted"],
                                    font=("Microsoft YaHei UI", 11), anchor="w")
        self.detail_type.pack(fill="x", pady=(0, 2))
        self.detail_edit_btn = ttk.Button(right, text="编辑节点", command=self._edit_node)
        self.detail_edit_btn.pack(fill="x", pady=(0, 4))

        qf = tk.Frame(right, bg=PALETTE["surface"])
        qf.pack(fill="x", pady=(0, 6))
        qrow = tk.Frame(qf, bg=PALETTE["surface"])
        qrow.pack(fill="x")
        tk.Label(qrow, text="关联题目", bg=PALETTE["surface"], fg=PALETTE["text"],
                 font=("Microsoft YaHei UI", 12, "bold")).pack(side="left")
        ttk.Button(qrow, text="去题库查看", command=self._open_bank).pack(side="right")
        self.questions_list = tk.Listbox(qf, height=5, font=("Microsoft YaHei UI", 10),
                                         bg=PALETTE["input"], fg=PALETTE["text"],
                                         relief="flat", highlightthickness=1,
                                         highlightbackground=PALETTE["border"],
                                         activestyle="none")
        self.questions_list.pack(fill="x", pady=(2, 0))
        self.questions_list.bind("<Double-Button-1>", lambda e: self._open_bank())

        self.detail_texts = {}
        for key, label in (("recognition", "识别方法"), ("approach", "解题思路"),
                           ("method", "解题方法"), ("remark", "备注")):
            f = tk.Frame(right, bg=PALETTE["surface"])
            f.pack(fill="both", expand=True, pady=(0, 6))
            tk.Label(f, text=label, bg=PALETTE["surface"], fg=PALETTE["text"],
                     font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w")
            txt = tk.Text(f, height=3, wrap="word", font=("Microsoft YaHei UI", 11),
                          bg=PALETTE["input"], fg=PALETTE["text"], relief="flat",
                          highlightthickness=1, highlightbackground=PALETTE["border"])
            txt.pack(fill="both", expand=True, pady=(2, 0))
            txt.configure(state="disabled")
            self.detail_texts[key] = txt

        self.summary = tk.Label(self, text="", anchor="w", padx=16, pady=4,
                                bg=PALETTE["primary_light"], fg=PALETTE["primary_dark"],
                                font=("Microsoft YaHei UI", 12, "bold"))
        self.summary.pack(fill="x")

        self._menu = None
        for w in (self, self.canvas):
            w.bind("<F2>", self._on_f2)
            w.bind("<Delete>", lambda e: self._delete_node())
            w.bind("<Control-n>", lambda e: self._add_node())
            w.bind("<Tab>", self._on_key)
            w.bind("<Return>", self._on_key)
            w.bind("<Up>", self._on_key)
            w.bind("<Down>", self._on_key)
            w.bind("<Left>", self._on_key)
            w.bind("<Right>", self._on_key)

    def _on_f2(self, event=None):
        node = self._selected_node()
        if node:
            self._inline_edit(node)
        return "break"

    # ---------- 节点详情抽屉 ----------
    _DETAIL_W = 300

    def _show_detail(self):
        if self._detail_open:
            return
        self._detail_open = True
        # before=画布帧：让抽屉先占右侧宽度，画布再填充剩余
        self.detail_frame.pack(side="right", fill="y", before=self._canvas_frame)
        self._animate_detail(self._DETAIL_W)

    def _hide_detail(self):
        if not self._detail_open:
            return
        self._detail_open = False
        self._animate_detail(0)

    def _animate_detail(self, target, ms=140, steps=8):
        self._detail_anim_id += 1
        anim_id = self._detail_anim_id
        start = self.detail_frame.winfo_width() if self.detail_frame.winfo_ismapped() else 0

        def _step(i):
            if self._detail_anim_id != anim_id:
                return  # 已被新的动画取代
            try:
                self.detail_frame.configure(width=start + (target - start) * i / steps)
            except tk.TclError:
                return
            if i < steps:
                self.after(ms // steps, lambda: _step(i + 1))
            elif target == 0:
                self.detail_frame.pack_forget()

        _step(0)

    # ---------- 数据加载 ----------
    def _load_maps(self):
        self._maps = self.db.list_question_maps()
        self.map_box.configure(values=[m["subject_name"] for m in self._maps])
        if self._maps:
            self.map_var.set(self._maps[0]["subject_name"])
            self._load_current_map()
        else:
            self._map = None
            self.canvas.delete("all")
            self.summary.configure(text="暂无科目，请先新增科目")

    def _current_map(self):
        name = self.map_var.get()
        for m in self._maps:
            if m["subject_name"] == name:
                return m
        return None

    def _calc_depths(self):
        self._depth_of = {}
        for n in self._nodes.values():
            d = 0
            pid = n["parent_id"]
            while pid is not None:
                d += 1
                parent = self._nodes.get(pid)
                pid = parent["parent_id"] if parent else None
            self._depth_of[n["id"]] = d

    def _load_current_map(self):
        m = self._current_map()
        if not m:
            return
        self._map = m
        prev_sel = self._selected_id  # 重载后保留选中节点（折叠/编辑后抽屉不无故关闭）
        self._nodes = {n["id"]: n for n in self.db.question_types_by_map(m["id"])}
        self._children = {}
        for n in self._nodes.values():
            self._children.setdefault(n["parent_id"], []).append(n)
        for lst in self._children.values():
            lst.sort(key=lambda x: (x.get("sort_order") or 0, x["id"]))
        self._stats = self.db.question_stats_by_map(m["id"])
        self._scale = float(m.get("view_scale") or 1.0)
        self._selected_id = None
        self._search_results = []
        self._search_idx = 0
        self._last_search = ""
        self._calc_depths()
        self.layout_var.set(_LAYOUT_LABELS.get(m.get("layout_type") or "radial", "环形放射"))
        if m.get("layout_mode") == "manual":
            self._node_pos = {
                n["id"]: (n.get("pos_x") or 0, n.get("pos_y") or 0) for n in self._nodes.values()
            }
        else:
            self._auto_layout_internal()
        saved_off = m.get("view_offset_x")
        if saved_off is None or float(saved_off) == 0:
            self._center_view()  # 视图从未保存过 -> 自动布局后居中
        else:
            self._off_x = float(saved_off)
            self._off_y = float(m.get("view_offset_y") or 0)
        self._draw()
        if prev_sel in self._nodes:
            self._select_node(prev_sel)
        else:
            self._clear_detail()
        self.canvas.focus_set()

    # ---------- 布局与绘制 ----------
    _H_SPACING = 240.0   # 相邻层级水平间距（世界单位）
    _V_STEP = 64.0       # 每棵叶子子树占用的垂直高度
    _RADIAL_R1 = 260.0   # 放射布局：一级主题半径
    _RADIAL_STEP = 230.0 # 放射布局：每层半径增量

    def _subtree_height(self, node):
        if node.get("collapsed"):
            return 1
        children = self._children.get(node["id"], [])
        if not children:
            return 1
        return sum(self._subtree_height(c) for c in children)

    def _leaf_count(self, node):
        """子树叶子数（折叠子树按 1 计），用于放射布局的弧长权重。"""
        if node.get("collapsed"):
            return 1
        children = self._children.get(node["id"], [])
        if not children:
            return 1
        return sum(self._leaf_count(c) for c in children)

    def _layout_node_at(self, node, x, y, direction):
        """把节点放到 (x, y)，子树沿 direction（±1）方向水平展开、
        子节点从父节点水平线开始依次向下排列（首个子节点与父同水平）。"""
        self._node_pos[node["id"]] = (x, y)
        if node.get("collapsed"):
            return
        kids = self._children.get(node["id"], [])
        if not kids:
            return
        cy = y
        for k in kids:
            self._layout_node_at(k, x + direction * self._H_SPACING, cy, direction)
            cy += self._subtree_height(k) * self._V_STEP

    def _layout_column(self, kids, direction):
        """一列一级节点：垂直堆叠（整体以根水平线为对称中心），子树沿 direction 展开。"""
        total = sum(self._subtree_height(k) for k in kids) * self._V_STEP
        cy = -total / 2
        for k in kids:
            h = self._subtree_height(k) * self._V_STEP
            self._layout_node_at(k, direction * self._H_SPACING, cy + h / 2, direction)
            cy += h

    def _radial_layout(self):
        """环形放射布局（XMind 经典）：根居中，一级主题按叶子数分配弧长环绕 360°，
        子树沿径向逐层外扩。自由主题（free_float）及其子树保留原位不参与布局。"""
        import math
        roots = self._children.get(None, [])
        self._node_pos = {}
        if not roots:
            return
        root = roots[0]
        self._node_pos[root["id"]] = (0.0, 0.0)
        kids = self._children.get(root["id"], [])
        if not kids:
            return
        free_ids = {n["id"] for n in self._nodes.values() if n.get("free_float")}
        for fid in free_ids:
            self._copy_free_subtree(fid)
        active = [k for k in kids if k["id"] not in free_ids]
        if not active:
            return
        total = sum(self._leaf_count(k) for k in active)
        angle = -90.0  # 从正上方顺时针环绕

        def place(node, mid_angle, span, radius):
            rad = math.radians(mid_angle)
            self._node_pos[node["id"]] = (radius * math.cos(rad), radius * math.sin(rad))
            if node.get("collapsed"):
                return
            subs = self._children.get(node["id"], [])
            if not subs:
                return
            stotal = sum(self._leaf_count(k) for k in subs)
            a = mid_angle - span / 2
            for k in subs:
                s = self._leaf_count(k) / stotal * span
                place(k, a + s / 2, s, radius + self._RADIAL_STEP)
                a += s

        for k in active:
            span = self._leaf_count(k) / total * 360.0
            place(k, angle + span / 2, span, self._RADIAL_R1)
            angle += span

    def _copy_free_subtree(self, node_id):
        """自由主题子树整体保留现有位置（缺省放原点）。"""
        stack = [node_id]
        while stack:
            cur = stack.pop()
            if cur not in self._node_pos:
                n = self._nodes.get(cur)
                self._node_pos[cur] = (n.get("pos_x") or 0, n.get("pos_y") or 0) if n else (0.0, 0.0)
            stack.extend(c["id"] for c in self._children.get(cur, []))

    def _auto_layout_internal(self):
        """按当前布局模式（layout_type）重算全部节点位置。"""
        layout = (self._map or {}).get("layout_type") or "radial"
        if layout == "columns":
            roots = self._children.get(None, [])
            self._node_pos = {}
            if not roots:
                return
            root = roots[0]
            self._node_pos[root["id"]] = (0.0, 0.0)
            kids = self._children.get(root["id"], [])
            if not kids:
                return
            half = (len(kids) + 1) // 2
            self._layout_column(kids[:half], -1)   # 左列
            self._layout_column(kids[half:], 1)    # 右列
        elif layout == "logic":
            roots = self._children.get(None, [])
            self._node_pos = {}
            if not roots:
                return
            root = roots[0]
            self._node_pos[root["id"]] = (0.0, 0.0)
            kids = self._children.get(root["id"], [])
            if not kids:
                return
            self._layout_column(kids, 1)           # 全部向右
        else:
            self._radial_layout()

    def _center_view(self):
        """把当前布局整体居中到画布（scale=1）。"""
        if not self._node_pos:
            return
        xs = [p[0] for p in self._node_pos.values()]
        ys = [p[1] for p in self._node_pos.values()]
        bcx = (min(xs) + max(xs) + _NODE_W) / 2
        bcy = (min(ys) + max(ys) + _NODE_H) / 2
        w = max(self.canvas.winfo_width(), 600)
        h = max(self.canvas.winfo_height(), 400)
        self._scale = 1.0
        self._off_x = w / 2 - bcx
        self._off_y = h / 2 - bcy

    def _hidden_ids(self):
        """被折叠节点隐藏掉的子孙节点 id 集合（折叠只隐藏绘制，不动布局）。"""
        hidden = set()
        for lst in self._children.values():
            for n in lst:
                if not n.get("collapsed"):
                    continue
                stack = [c["id"] for c in self._children.get(n["id"], [])]
                while stack:
                    cid = stack.pop()
                    hidden.add(cid)
                    stack.extend(c["id"] for c in self._children.get(cid, []))
        return hidden

    def _draw(self):
        self.canvas.delete("all")
        self._node_items = {}
        self._node_rect = {}
        self._collapse_buttons = {}
        scale, ox, oy = self._scale, self._off_x, self._off_y
        hidden = self._hidden_ids()
        # 连线（分层贝塞尔曲线：越深越细、颜色继承父节点）
        for n in self._nodes.values():
            if n["parent_id"] is None or n["id"] in hidden:
                continue
            parent = self._nodes.get(n["parent_id"])
            if not parent or parent.get("collapsed"):
                continue
            x1, y1 = world_to_screen(*self._node_pos.get(parent["id"], (0, 0)), scale, ox, oy)
            x2, y2 = world_to_screen(*self._node_pos.get(n["id"], (0, 0)), scale, ox, oy)
            p0 = (x1 + _NODE_W * scale, y1 + _NODE_H * scale / 2)
            p1 = (x2, y2 + _NODE_H * scale / 2)
            pts = bezier_curve(p0, p1)
            width, color = self._line_style(
                self._depth_of.get(n["id"], 1), self._node_color(parent))
            if n["id"] == self._selected_id or parent["id"] == self._selected_id:
                color, width = PALETTE["focus"], width + 1
            self.canvas.create_line(pts, fill=color, width=width, capstyle=tk.ROUND, smooth=False)
        # 节点（隐藏折叠子树内的节点）
        for n in self._nodes.values():
            if n["id"] in hidden:
                continue
            x, y = self._node_pos.get(n["id"], (0, 0))
            self._draw_node(n, x, y)

    @staticmethod
    def _node_color(node):
        return node.get("color") or _NODE_COLORS.get(node["node_type"], "#2D6CDF")

    @staticmethod
    def _line_style(depth, color):
        """层级线型：根->一级 3px 主题色；更深逐层变细、颜色向背景混合变浅。"""
        if depth <= 1:
            return 3, color
        if depth == 2:
            return 2, lerp_color(color, PALETTE["bg"], 0.45)
        return 1.5, lerp_color(color, PALETTE["bg"], 0.25)

    def _draw_node(self, node, x, y):
        scale, ox, oy = self._scale, self._off_x, self._off_y
        color = self._node_color(node)
        sw, sh = _NODE_W * scale, _NODE_H * scale
        sx, sy = world_to_screen(x, y, scale, ox, oy)
        is_root = node["parent_id"] is None
        selected = node["id"] == self._selected_id
        fill = color if is_root else PALETTE["card"]
        fg = "#FFFFFF" if is_root else PALETTE["text"]
        outline = PALETTE["focus"] if selected else color
        # 高错率预警：红描边
        stat = self._stats.get(node.get("topic_id")) if node.get("topic_id") else None
        if stat:
            total, wrong = stat
            if total and wrong >= _WARN_MIN_WRONG and wrong / total >= _WARN_RATE:
                outline = PALETTE["danger"]
        rect = self.canvas.create_polygon(
            round_rect_points(sx, sy, sw, sh, 10 * scale),
            fill=fill, outline=outline, smooth=True,
            width=3 if selected else 2)
        text = self.canvas.create_text(sx + sw / 2, sy + sh / 2 - (8 if stat else 0),
                                       text=node["name"], fill=fg,
                                       font=("Microsoft YaHei UI", 12, "bold"),
                                       width=max(40, int(150 * scale)))
        self._node_items[rect] = node["id"]
        self._node_items[text] = node["id"]
        self._node_rect[node["id"]] = rect
        # 统计角标
        if stat:
            total, wrong = stat
            badge = "{}题 · {}错".format(total, wrong)
            bfg = PALETTE["danger"] if wrong and wrong / total >= _WARN_RATE else PALETTE["muted"]
            btext = self.canvas.create_text(sx + sw / 2, sy + sh - 9, text=badge, fill=bfg,
                                            font=("Microsoft YaHei UI", 9))
            self._node_items[btext] = node["id"]
        # 折叠/展开小按钮
        if self._children.get(node["id"]):
            mark = "+" if node.get("collapsed") else "-"
            b = 13 * scale
            btn = self.canvas.create_oval(sx + sw - b - 3, sy + 3, sx + sw - 3, sy + b + 3,
                                          fill=PALETTE["surface"], outline=color)
            lbl = self.canvas.create_text(sx + sw - b / 2 - 3, sy + b / 2 + 3, text=mark, fill=color,
                                          font=("Microsoft YaHei UI", 9, "bold"))
            self._node_items[btn] = node["id"]
            self._node_items[lbl] = node["id"]
            self._collapse_buttons[btn] = node["id"]
            self._collapse_buttons[lbl] = node["id"]

    def _find_node_by_event(self, event):
        item = self.canvas.find_withtag("current")
        if not item:
            return None
        return self._nodes.get(self._node_items.get(item[0]))

    # ---------- 交互 ----------
    def _on_canvas_click(self, event):
        item = self.canvas.find_withtag("current")
        if item and item[0] in self._collapse_buttons:
            node = self._nodes.get(self._collapse_buttons[item[0]])
            if node:
                self._toggle_collapse(node)
            return
        node = self._find_node_by_event(event)
        if node:
            self._select_node(node["id"])
            self._drag_id = node["id"]
            self._drag_start = (event.x, event.y)
            self._drag_target = None
            self._drag_subtree = self._subtree_node_ids(node["id"])
            self._drag_orig = {nid: self._node_pos.get(nid, (0, 0)) for nid in self._drag_subtree}
            self._drag_anchor = self._node_pos.get(node["id"], (0, 0))
            sx, sy = world_to_screen(*self._drag_anchor, self._scale, self._off_x, self._off_y)
            self._drag_off = (event.x - sx, event.y - sy)
        else:
            self._clear_detail()  # 点击空白处：收起详情抽屉
            self._pan_active = True
            self._pan_start = (event.x, event.y)
            self._pan_off0 = (self._off_x, self._off_y)

    def _on_canvas_drag(self, event):
        if self._drag_id is not None:
            wx = (event.x - self._drag_off[0] - self._off_x) / self._scale
            wy = (event.y - self._drag_off[1] - self._off_y) / self._scale
            dx = wx - self._drag_anchor[0]
            dy = wy - self._drag_anchor[1]
            # 子树整体跟随
            for nid in self._drag_subtree:
                ox, oy = self._drag_orig[nid]
                self._node_pos[nid] = (ox + dx, oy + dy)
            vx, vy = self._snap_guides(self._drag_id)  # 自由移动吸附
            # 吸附只改了被拖节点 -> 子树整体补上吸附位移
            nx, ny = self._node_pos[self._drag_id]
            adx = nx - (self._drag_anchor[0] + dx)
            ady = ny - (self._drag_anchor[1] + dy)
            if adx or ady:
                for nid in self._drag_subtree:
                    if nid == self._drag_id:
                        continue
                    ox, oy = self._drag_orig[nid]
                    self._node_pos[nid] = (ox + dx + adx, oy + dy + ady)
            # 结构拖拽目标预览：hover 到有效节点 -> 高亮
            target = self._find_node_by_event(event)
            self._drag_target = None
            if target and target["id"] != self._drag_id and target["id"] not in self._drag_subtree:
                self._drag_target = target["id"]
            self._draw()
            if self._drag_target:
                self._draw_drag_highlight(self._drag_target)
            self._draw_guides(vx, vy)
        elif self._pan_active:
            self._off_x = self._pan_off0[0] + (event.x - self._pan_start[0])
            self._off_y = self._pan_off0[1] + (event.y - self._pan_start[1])
            self._draw()

    def _on_canvas_release(self, event):
        if self._drag_id is not None:
            dx = event.x - self._drag_start[0]
            dy = event.y - self._drag_start[1]
            if math.hypot(dx, dy) >= 5:  # 有实际位移才算拖拽
                if self._drag_target is not None:
                    # release 鼠标的世界坐标（用于同级插入前后判定）
                    wy = (event.y - self._off_y) / self._scale
                    self._apply_struct_drop(self._drag_id, self._drag_target, wy)
                else:
                    self._apply_free_drop(self._drag_id)
            self._drag_id = None
            self._drag_target = None
        elif self._pan_active:
            self.db.update_question_map(
                self._map["id"],
                view_offset_x=self._off_x, view_offset_y=self._off_y,
            )
        self._pan_active = False
        self._pan_start = None

    def _apply_free_drop(self, node_id):
        """自由移动：auto 布局下标记为自由主题（脱离布局保留位置）；manual 直接存位。"""
        node = self._nodes.get(node_id)
        if not node:
            return
        x, y = self._node_pos[node_id]
        if self._map.get("layout_mode") != "manual":
            self.db.update_question_map(self._map["id"], layout_mode="manual")
            self._map["layout_mode"] = "manual"
        self.db.update_question_type_full(node_id, pos_x=x, pos_y=y, free_float=1)
        node["free_float"] = 1

    def _apply_struct_drop(self, drag_id, target_id, wy):
        """结构拖拽：同级时按 release 位置（目标上方/下方边缘=重排，中心=成为子节点）；
        跨级一律成为目标子节点。"""
        drag = self._nodes.get(drag_id)
        target = self._nodes.get(target_id)
        if not drag or not target:
            return
        try:
            same_parent = drag["parent_id"] == target["parent_id"]
            if same_parent:
                siblings = self._children.get(target["parent_id"], [])
                index = next((i for i, s in enumerate(siblings) if s["id"] == target_id), 0)
                ty = self._node_pos[target_id][1]
                if wy < ty - 10:                      # 明显在目标上方 -> 插其前
                    self.db.move_question_type(drag_id, target["parent_id"], index)
                elif wy > ty + _NODE_H + 10:          # 明显在目标下方 -> 插其后
                    self.db.move_question_type(drag_id, target["parent_id"], index + 1)
                else:                                 # 目标中心区域 -> 成为其子节点
                    self.db.move_question_type(drag_id, target_id, None)
            else:
                self.db.move_question_type(drag_id, target_id, None)
        except ValueError as exc:
            messagebox.showwarning("移动失败", str(exc), parent=self)
            return
        # 结构变更后重新布局（保持当前模式），并保持选中
        if self._map.get("layout_mode") == "manual":
            self._load_current_map()
        else:
            self._auto_layout_internal()
            self._draw()
        self._select_node(drag_id)

    def _draw_drag_highlight(self, node_id):
        """拖拽目标高亮框（虚线 accent 色）。"""
        x, y = self._node_pos.get(node_id, (0, 0))
        sx, sy = world_to_screen(x, y, self._scale, self._off_x, self._off_y)
        sw, sh = _NODE_W * self._scale, _NODE_H * self._scale
        self.canvas.create_rectangle(sx - 4, sy - 4, sx + sw + 4, sy + sh + 4,
                                     outline=PALETTE["accent"], width=2, dash=(5, 3))

    def _subtree_node_ids(self, node_id):
        ids = [node_id]
        for c in self._children.get(node_id, []):
            ids.extend(self._subtree_node_ids(c["id"]))
        return ids

    def _snap_guides(self, node_id):
        """拖拽对齐：找与目标节点中心最近的水平/垂直对齐位置并吸附。

        返回吸附后的辅助线世界坐标 (vx, vy)，未对齐的维度为 None。
        阈值按屏幕像素换算成世界单位，缩放后手感一致。
        """
        thr = 8.0 / self._scale
        cx = self._node_pos[node_id][0] + _NODE_W / 2
        cy = self._node_pos[node_id][1] + _NODE_H / 2
        best_x = best_y = None
        dx_best = dy_best = thr
        hidden = self._hidden_ids()
        for nid, (x, y) in self._node_pos.items():
            if nid == node_id or nid in hidden:
                continue
            tx = x + _NODE_W / 2
            ty = y + _NODE_H / 2
            dx = abs(tx - cx)
            dy = abs(ty - cy)
            if dx < dx_best:
                dx_best, best_x = dx, tx
            if dy < dy_best:
                dy_best, best_y = dy, ty
        if best_x is not None:
            self._node_pos[node_id] = (best_x - _NODE_W / 2, self._node_pos[node_id][1])
        if best_y is not None:
            self._node_pos[node_id] = (self._node_pos[node_id][0], best_y - _NODE_H / 2)
        return best_x, best_y

    def _draw_guides(self, vx, vy):
        """画贯穿画布的对齐辅助线（虚线，主题色）。"""
        if vx is None and vy is None:
            return
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        color = PALETTE["accent"]
        if vx is not None:
            sx = vx * self._scale + self._off_x
            self.canvas.create_line(sx, 0, sx, h, fill=color, dash=(4, 3), width=1)
        if vy is not None:
            sy = vy * self._scale + self._off_y
            self.canvas.create_line(0, sy, w, sy, fill=color, dash=(4, 3), width=1)

    def _on_double_click(self, event):
        node = self._find_node_by_event(event)
        if node:
            self._inline_edit(node)
        else:
            self._fit_view()

    def _inline_edit(self, node):
        """画布内联编辑节点名：Enter 保存、Esc 取消、失焦保存。"""
        x, y = self._node_pos.get(node["id"], (0, 0))
        sx, sy = world_to_screen(x, y, self._scale, self._off_x, self._off_y)
        sw, sh = _NODE_W * self._scale, _NODE_H * self._scale
        entry = tk.Entry(self.canvas, font=("Microsoft YaHei UI", 12),
                         justify="center", relief="solid")
        entry.insert(0, node["name"])
        entry.place(x=int(sx), y=int(sy), width=max(int(sw), 40), height=max(int(sh), 24))
        entry.focus_set()
        entry.select_range(0, "end")

        def commit(_e=None):
            val = entry.get().strip()
            entry.destroy()
            if val and val != node["name"]:
                self.db.update_question_type_full(node["id"], name=val)
                node["name"] = val
                self._draw()
                self._select_node(node["id"])
            return "break"

        def cancel(_e=None):
            entry.destroy()
            return "break"

        entry.bind("<Return>", commit)
        entry.bind("<Escape>", cancel)
        entry.bind("<FocusOut>", commit)
        entry.bind("<Tab>", lambda _e: "break")  # 编辑中 Tab 不触发新增节点

    def _on_key(self, event):
        """键盘导航：Tab 子节点 / Enter 同级 / 方向键在父子兄弟间移动。"""
        node = self._selected_node()
        if not node:
            return None
        key = event.keysym
        if key == "Tab":
            self._add_node(parent=node)
            return "break"
        if key == "Return":
            self._add_node(parent=self._nodes.get(node["parent_id"]))
            return "break"
        if key == "Left":
            p = self._nodes.get(node["parent_id"])
            if p:
                self._select_node(p["id"])
            return "break"
        if key == "Right":
            kids = self._children.get(node["id"], [])
            if kids:
                self._select_node(kids[0]["id"])
            return "break"
        if key in ("Up", "Down"):
            siblings = self._children.get(node["parent_id"], [])
            if len(siblings) > 1:
                idx = next((i for i, s in enumerate(siblings) if s["id"] == node["id"]), 0)
                if key == "Up" and idx > 0:
                    self._select_node(siblings[idx - 1]["id"])
                elif key == "Down" and idx < len(siblings) - 1:
                    self._select_node(siblings[idx + 1]["id"])
                return "break"
        return None

    def _on_right_click(self, event):
        node = self._find_node_by_event(event)
        menu = ThemeMenu(self)
        self._menu = menu  # 持有引用，防止菜单被 GC
        if node:
            self._select_node(node["id"])
            menu.show(event.x_root, event.y_root, [
                ("＋ 新增子节点", lambda: self._add_node(parent=node)),
                ("＋ 新增同级节点", lambda: self._add_node(parent=self._nodes.get(node["parent_id"]))),
                ("---",),
                ("✎ 编辑", lambda: self._edit_node_dialog(node)),
                ("✕ 删除", lambda: self._delete_node(node), True),
                ("---",),
                ("设为自由主题" if not node.get("free_float") else "回到布局",
                 lambda: self._toggle_free_float(node)),
                ("折叠 / 展开", lambda: self._toggle_collapse(node)),
            ])
        else:
            menu.show(event.x_root, event.y_root, [
                ("＋ 新增科目", self._add_map),
                ("＋ 新增根节点", lambda: self._add_node(parent=None)),
                ("---",),
                ("✕ 删除科目", self._delete_map, True),
                ("---",),
                ("回到自动布局", self._back_to_auto),
            ])

    def _toggle_free_float(self, node):
        """节点级自由主题开关：自由=脱离布局保留位置；回布局=重排。"""
        if node.get("free_float"):
            self.db.update_question_type_full(node["id"], free_float=0)
            node["free_float"] = 0
        else:
            x, y = self._node_pos.get(node["id"], (0, 0))
            self.db.update_question_type_full(node["id"], free_float=1, pos_x=x, pos_y=y)
            node["free_float"] = 1
        if self._map.get("layout_mode") != "auto":
            self.db.update_question_map(self._map["id"], layout_mode="auto")
            self._map["layout_mode"] = "auto"
        self._load_current_map()
        self._select_node(node["id"])

    def _back_to_auto(self):
        """整图回到自动布局（自由主题保留原位）。"""
        if self._map:
            self.db.update_question_map(self._map["id"], layout_mode="auto")
            self._load_current_map()

    def _on_mousewheel(self, event):
        # 普通滚轮：垂直平移
        self._off_y += (-event.delta / 120) * 60
        self._draw()

    def _on_control_mousewheel(self, event):
        # Ctrl+滚轮：以光标为锚点缩放
        factor = _ZOOM_STEP if event.delta > 0 else 1.0 / _ZOOM_STEP
        self._zoom_at(factor, event.x, event.y)

    def _zoom_at(self, factor, cx, cy):
        old = self._scale
        new = min(_MAX_SCALE, max(_MIN_SCALE, old * factor))
        if abs(new - old) < 1e-9:
            return
        wx, wy = screen_to_world(cx, cy, old, self._off_x, self._off_y)
        self._scale = new
        self._off_x = cx - wx * new
        self._off_y = cy - wy * new
        self.db.update_question_map(
            self._map["id"],
            view_scale=new, view_offset_x=self._off_x, view_offset_y=self._off_y,
        )
        self._draw()

    def _set_layout(self):
        """切换布局模式：改 DB layout_type，切回自动布局并重排居中。"""
        m = self._current_map()
        if not m:
            return
        label = self.layout_var.get()
        lt = next((k for k, v in _LAYOUT_LABELS.items() if v == label), "radial")
        self.db.update_question_map(m["id"], layout_type=lt, layout_mode="auto")
        m["layout_type"] = lt  # 同步内存缓存（_current_map 读取它）
        m["layout_mode"] = "auto"
        self._load_current_map()

    def _fit_view(self):
        if not self._map:
            return
        if self._map.get("layout_mode") != "manual":
            self._auto_layout_internal()  # 按当前布局模式重排
        self._center_view()               # 布局整体居中
        self.db.update_question_map(
            self._map["id"],
            layout_mode="auto", view_scale=1.0,
            view_offset_x=self._off_x, view_offset_y=self._off_y,
        )
        self._map["layout_mode"] = "auto"
        self._draw()

    def _import_preset(self):
        """把科目管理的知识点树导入当前科目的思维导图（幂等）。"""
        m = self._current_map()
        if not m:
            return
        n = self.db.import_preset_question_types(m["id"])
        self._load_current_map()
        if n:
            messagebox.showinfo("导入预置", "已导入 {} 个预置知识点节点。".format(n), parent=self)
        else:
            messagebox.showinfo("导入预置", "当前科目没有可导入的预置内容，或内容已存在。", parent=self)

    def _select_node(self, node_id):
        self._selected_id = node_id
        node = self._nodes.get(node_id)
        if not node:
            return
        self.detail_name.configure(text=node["name"])
        self.detail_type.configure(
            text="类型：{}".format(_NODE_TYPE_LABELS.get(node["node_type"], node["node_type"])))
        stat = self._stats.get(node.get("topic_id")) if node.get("topic_id") else None
        if stat:
            self.detail_type.configure(
                text="{} · 关联题目 {} 题 / 错 {} 题".format(
                    _NODE_TYPE_LABELS.get(node["node_type"], node["node_type"]), stat[0], stat[1]))
        for key, txt in self.detail_texts.items():
            txt.configure(state="normal")
            txt.delete("1.0", "end")
            txt.insert("1.0", node.get(key) or "")
            txt.configure(state="disabled")
        self._fill_questions_list(node)
        self.summary.configure(
            text="当前节点：{}  ·  共 {} 个节点".format(node["name"], len(self._nodes)))
        self._show_detail()
        self._draw()

    def _fill_questions_list(self, node):
        self.questions_list.delete(0, "end")
        self._detail_questions = []
        tid = node.get("topic_id")
        if not tid:
            self.questions_list.insert("end", "（未关联知识点，无题目）")
            return
        items = self.db.list_questions(topic_id=tid)[:50]
        for q in items:
            res = _RESULT_LABELS.get(q["result"], "未判定")
            self.questions_list.insert(
                "end", "{}  {}  {}".format(q["code"], res, q["question_text"][:16]))
            self._detail_questions.append(q["id"])
        if not items:
            self.questions_list.insert("end", "（该知识点暂无题目）")

    def _clear_detail(self):
        self.detail_name.configure(text="请选择节点")
        self.detail_type.configure(text="")
        self.questions_list.delete(0, "end")
        self.questions_list.insert("end", "（未关联知识点，无题目）")
        self._detail_questions = []
        for txt in self.detail_texts.values():
            txt.configure(state="normal")
            txt.delete("1.0", "end")
            txt.configure(state="disabled")
        self.summary.configure(text="共 {} 个节点".format(len(self._nodes)))
        self._hide_detail()

    # ---------- 跳转题库 ----------
    def _open_bank(self):
        node = self._selected_node()
        if not node or not node.get("topic_id"):
            messagebox.showinfo("提示", "该节点未关联知识点，无法跳转题库。", parent=self)
            return
        mw = self.master
        if hasattr(mw, "show_page"):
            mw.show_page("bank")
            page = mw._pages.get("bank")
            if page is not None and hasattr(page, "focus_topic"):
                page.focus_topic(node["topic_id"])

    # ---------- 搜索 ----------
    def _search_nodes(self, event=None):
        kw = self.search_var.get().strip().lower()
        if not kw:
            return
        if not self._search_results or self._last_search != kw:
            self._last_search = kw
            self._search_results = [
                n["id"] for n in self._nodes.values()
                if kw in n["name"].lower()
                or kw in (n.get("recognition") or "").lower()
                or kw in (n.get("approach") or "").lower()
                or kw in (n.get("method") or "").lower()
                or kw in (n.get("remark") or "").lower()
            ]
            self._search_idx = 0
        else:
            self._search_idx = (self._search_idx + 1) % len(self._search_results)
        self._show_search_result()

    def _show_search_result(self):
        if not self._search_results:
            self.summary.configure(text="未找到匹配节点")
            return
        node_id = self._search_results[self._search_idx]
        self._expand_ancestors(node_id)
        self._select_node(node_id)
        rect = self._node_rect.get(node_id)
        if rect:
            bbox = self.canvas.bbox(rect)
            if bbox:
                cx = (bbox[0] + bbox[2]) / 2
                cy = (bbox[1] + bbox[3]) / 2
                self._off_x = self.canvas.winfo_width() / 2 - cx
                self._off_y = self.canvas.winfo_height() / 2 - cy
                self._draw()
        self.summary.configure(text="{} / {}：{}".format(
            self._search_idx + 1, len(self._search_results), self._nodes[node_id]["name"]))

    def _expand_ancestors(self, node_id):
        node = self._nodes.get(node_id)
        if not node:
            return
        parent_id = node.get("parent_id")
        while parent_id is not None:
            parent = self._nodes.get(parent_id)
            if not parent:
                break
            if parent.get("collapsed"):
                parent["collapsed"] = 0
                self.db.update_question_type_full(parent_id, collapsed=0)
            parent_id = parent.get("parent_id")

    # ---------- 操作 ----------
    def _add_map(self):
        name = simpledialog.askstring("新增科目", "科目名称：", parent=self)
        if not name:
            return
        try:
            existing = next((r for r in self.db.root_topics() if r["name"] == name), None)
            if existing:
                self.db.ensure_map_for_topic(existing["id"], name)
            else:
                self.db.add_topic(name)
        except Exception as exc:
            messagebox.showerror("新增失败", str(exc), parent=self)
            return
        self._load_maps()
        self.map_var.set(name)
        self._load_current_map()

    def _delete_map(self):
        m = self._current_map()
        if not m:
            return
        msg = "确定删除「{}」及其整张思维导图吗？".format(m["subject_name"])
        if m.get("topic_id"):
            msg += "\n该科目会连同打卡计划、历史记录和图片一并删除，不可恢复。"
        if messagebox.askyesno("删除科目", msg, parent=self):
            if m.get("topic_id"):
                self.db.delete_topic_cascade(m["topic_id"])
            else:
                self.db.delete_question_map(m["id"])
            self._load_maps()

    def _add_node(self, parent=None):
        m = self._current_map()
        if not m:
            return
        if parent is None:
            parent = self._selected_node()
        parent_id = parent["id"] if parent else None
        dlg = NodeEditDialog(self, self.db, map_id=m["id"], parent_id=parent_id)
        self.wait_window(dlg)
        self._load_current_map()

    def _edit_node(self):
        node = self._selected_node()
        if node:
            self._edit_node_dialog(node)

    def _edit_node_dialog(self, node):
        dlg = NodeEditDialog(self, self.db, node=node)
        self.wait_window(dlg)
        self._load_current_map()

    def _delete_node(self, node=None):
        node = node or self._selected_node()
        if not node:
            messagebox.showinfo("提示", "请先选择节点", parent=self)
            return
        count = self._subtree_size(node["id"])
        if messagebox.askyesno(
            "删除节点",
            "确定删除「{}」及其 {} 个子节点吗？".format(node["name"], count - 1),
            parent=self,
        ):
            self.db.delete_question_type(node["id"])
            self._load_current_map()

    def _toggle_collapse(self, node=None):
        node = node or self._selected_node()
        if not node:
            return
        self.db.toggle_question_type_collapsed(node["id"])
        node["collapsed"] = 0 if node.get("collapsed") else 1  # 仅改折叠态，不重排布局
        self._draw()

    def _expand_all(self):
        if not self._map:
            return
        self.db.set_question_types_collapsed(self._map["id"], 0)
        for n in self._nodes.values():
            n["collapsed"] = 0
        self._draw()

    def _collapse_all(self):
        if not self._map:
            return
        self.db.set_question_types_collapsed(self._map["id"], 1)
        for n in self._nodes.values():
            n["collapsed"] = 1
        self._draw()

    def _subtree_size(self, node_id):
        total = 1
        for child in self._children.get(node_id, []):
            total += self._subtree_size(child["id"])
        return total

    def _selected_node(self):
        return self._nodes.get(self._selected_id)

    def _export(self):
        m = self._current_map()
        if not m:
            return
        path = filedialog.asksaveasfilename(
            parent=self, title="导出思维导图", defaultextension=".md",
            initialfile="{}思维导图.md".format(m["subject_name"]),
            filetypes=[("Markdown", "*.md"), ("文本文件", "*.txt"), ("所有文件", "*.*")],
        )
        if not path:
            return
        try:
            export_mindmap_markdown(self.db, m["id"], path)
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc), parent=self)
            return
        messagebox.showinfo("导出成功", "已导出：\n{}".format(path), parent=self)


class NodeEditDialog(tk.Toplevel):
    def __init__(self, master, db, node=None, map_id=None, parent_id=None):
        super().__init__(master)
        self.db = db
        self.node = node
        self.map_id = map_id or (node.get("map_id") if node else None)
        self.parent_id = parent_id if parent_id is not None else (node.get("parent_id") if node else None)
        self.title("编辑节点" if node else "新增节点")
        self.geometry("640x640")
        self.transient(master)
        setup_styles(self)
        self.configure(bg=PALETTE["bg"])
        dialog_header(self, self.title(), "维护题型节点")
        self._build_ui()
        center_window(self)
        self.grab_set()

    def _build_ui(self):
        P = PALETTE
        body = tk.Frame(self, bg=P["bg"], padx=16, pady=12)
        body.pack(fill="both", expand=True)

        row = tk.Frame(body, bg=P["bg"])
        row.pack(fill="x", pady=3)
        tk.Label(row, text="名称：", bg=P["bg"]).pack(side="left")
        self.name_var = tk.StringVar(value=self.node["name"] if self.node else "")
        ttk.Entry(row, textvariable=self.name_var, width=28).pack(side="left", padx=(0, 10))
        tk.Label(row, text="类型：", bg=P["bg"]).pack(side="left")
        self.type_var = tk.StringVar(value=self.node["node_type"] if self.node else "type")
        ttk.Combobox(row, textvariable=self.type_var, state="readonly", width=8,
                     values=list(_NODE_TYPE_LABELS.keys())).pack(side="left")

        row2 = tk.Frame(body, bg=P["bg"])
        row2.pack(fill="x", pady=3)
        tk.Label(row2, text="颜色：", bg=P["bg"]).pack(side="left")
        self.color_var = tk.StringVar(value=self.node.get("color") if self.node else "")
        self.color_btn = tk.Button(row2, text="选择颜色", command=self._pick_color,
                                   bg=PALETTE["surface"], fg=PALETTE["text"])
        self.color_btn.pack(side="left", padx=(0, 10))
        tk.Label(row2, text="颜色值：", bg=P["bg"]).pack(side="left")
        ttk.Entry(row2, textvariable=self.color_var, width=12).pack(side="left")

        row3 = tk.Frame(body, bg=P["bg"])
        row3.pack(fill="x", pady=3)
        tk.Label(row3, text="关联知识点：", bg=P["bg"]).pack(side="left")
        self.topic_var = tk.StringVar()
        self.topic_box = ttk.Combobox(row3, textvariable=self.topic_var, state="readonly", width=32)
        self.topic_box.pack(side="left", padx=(0, 10))
        tk.Label(row3, text="（关联后节点显示题目统计）", bg=P["bg"],
                 fg=P["muted"], font=("Microsoft YaHei UI", 9)).pack(side="left")
        self._load_topics()

        self.fields = {}
        for key, label, height in (
            ("recognition", "识别方法", 4),
            ("approach", "解题思路", 5),
            ("method", "解题方法", 5),
            ("remark", "备注", 3),
        ):
            f = tk.Frame(body, bg=P["bg"])
            f.pack(fill="both", expand=True, pady=(4, 0))
            tk.Label(f, text=label, bg=P["bg"], fg=P["text"],
                     font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w")
            txt = tk.Text(f, height=height, wrap="word", font=("Microsoft YaHei UI", 11),
                          bg=P["input"], fg=P["text"], relief="flat",
                          highlightthickness=1, highlightbackground=P["border"])
            if self.node:
                txt.insert("1.0", self.node.get(key) or "")
            txt.pack(fill="both", expand=True, pady=(2, 0))
            self.fields[key] = txt

        btns = tk.Frame(self, bg=P["bg"], padx=16, pady=10)
        btns.pack(fill="x")
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="right")
        ttk.Button(btns, text="保存", style="Accent.TButton", command=self._save).pack(side="right", padx=8)

    def _load_topics(self):
        topics = self.db.list_topics()
        paths = self.db.topic_paths([t["id"] for t in topics])
        self._topic_map = {paths[t["id"]]: t["id"] for t in topics}
        current = "（不关联）"
        if self.node and self.node.get("topic_id"):
            current = paths.get(self.node["topic_id"], "（不关联）")
        self.topic_box.configure(values=["（不关联）"] + sorted(paths.values()))
        self.topic_var.set(current)

    def _pick_color(self):
        color = colorchooser.askcolor(color=self.color_var.get() or "#4A7BE0", parent=self)[1]
        if color:
            self.color_var.set(color)

    def _save(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("提示", "名称不能为空", parent=self)
            return
        topic_label = self.topic_var.get()
        data = {
            "name": name,
            "node_type": self.type_var.get(),
            "color": self.color_var.get().strip(),
            "recognition": self.fields["recognition"].get("1.0", "end").strip(),
            "approach": self.fields["approach"].get("1.0", "end").strip(),
            "method": self.fields["method"].get("1.0", "end").strip(),
            "remark": self.fields["remark"].get("1.0", "end").strip(),
            "topic_id": self._topic_map.get(topic_label) if topic_label != "（不关联）" else None,
        }
        if self.node:
            data["parent_id"] = self.node.get("parent_id")
            self.db.update_question_type_full(self.node["id"], **data)
        else:
            data["map_id"] = self.map_id
            data["parent_id"] = self.parent_id
            self.db.add_question_type_full(**data)
        self.destroy()
