# -*- coding: utf-8 -*-
"""可视化题型思维导图：每个科目独立导图，Canvas 绘制、可交互增删改、折叠展开。

渲染模型：节点位置（_node_pos）存「世界坐标」并持久化到 pos_x/pos_y；
画布绘制前经 scale + 偏移换算成屏幕坐标。缩放/平移只改视图状态
（view_scale/view_offset_x/view_offset_y），不污染节点数据。
"""
from __future__ import annotations

import math
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from habit_checkin.services.clipboard_utils import bind_entry_undo, bind_text_paste
from habit_checkin.services.mindmap_export import export_mindmap_markdown
from habit_checkin.ui.animate import lerp_color
from habit_checkin.ui.common import EmptyState, ScrollableFrame, center_window, setup_styles
from habit_checkin.ui.field_edit_dialog import FieldEditDialog, ask_fields
from habit_checkin.ui.richtext import (
    AutoHeightRichText,
    html_to_plain,
    to_plain,
)
from habit_checkin.ui.theme import PALETTE, dialog_header
from habit_checkin.ui.theme_menu import ThemeMenu

_NODE_TYPE_LABELS = {
    "root": "总览",
    "subject": "科目",
    "category": "分类",
    "type": "题型",
}

_DEFAULT_LAYOUT = "logic"
_LAYOUT_LABELS = {"logic": "右向逻辑图", "radial": "环形放射", "columns": "两翼对称"}

_NODE_COLORS = {
    "root": "#2D6CDF",
    "subject": "#4A7BE0",
    "category": "#16A34A",
    "type": "#F59E0B",
}

_RESULT_LABELS = {"correct": "正确", "wrong": "错误", None: "未判定"}

_NODE_W = 170.0   # 节点默认宽（世界单位，兼容旧数据/纯布局计算）
_NODE_H = 56.0    # 节点高（世界单位）
_MIN_NODE_W = 120.0
_MIN_GAP = 20.0  # 自动布局时任意两节点边缘之间至少保留的水平/垂直间距
_NODE_TEXT_LEFT = 30.0
_NODE_TEXT_RIGHT = 18.0
_NODE_ICON_R = 6.0
_TOOLBAR_FONT = ("Microsoft YaHei UI", 12)
_TOOLBAR_BTN_PAD = (12, 8)
_TOOLBAR_GAP = 8
_NODE_MEASURE_FONT = None
_NODE_ICON_KINDS = {
    "root": "circle",
    "subject": "diamond",
    "category": "square",
    "type": "dot",
}
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


def branch_curve(p0, p1):
    """圆角分支线：水平进出、中间垂直过渡，交由 Canvas 平滑成圆角。"""
    mid_x = (p0[0] + p1[0]) / 2.0
    return [p0, (mid_x, p0[1]), (mid_x, p1[1]), p1]


def round_rect_points(x, y, w, h, r):
    """圆角矩形多边形点列（create_polygon 用，配合 smooth=True 更圆润）。"""
    r = min(max(r, 0), w / 2, h / 2)
    return [
        x + r, y, x + w - r, y, x + w, y, x + w, y + r,
        x + w, y + h - r, x + w, y + h, x + w - r, y + h,
        x + r, y + h, x, y + h, x, y + h - r, x, y + r, x, y,
    ]


def _node_measure_font():
    """懒创建节点文字的测量字体；无 Tk 根窗口时返回 None 走字符估算。"""
    global _NODE_MEASURE_FONT
    if _NODE_MEASURE_FONT is not None:
        return _NODE_MEASURE_FONT
    try:
        import tkinter as tk
        import tkinter.font as tkfont
        root = tk._default_root
        if root is None:
            return None
        _NODE_MEASURE_FONT = tkfont.Font(
            root=root, family="Microsoft YaHei UI", size=12, weight="bold"
        )
        return _NODE_MEASURE_FONT
    except Exception:
        return None


def estimate_node_width(name, measure=None):
    """按单行文字估算节点宽度（世界单位）；有真实字体时优先测量。"""
    text = (name or "").strip()
    if not text:
        return _NODE_W
    if measure is None:
        measure = _node_measure_font()
    if measure is not None:
        try:
            text_w = measure.measure(text)
            if text_w:
                return max(_MIN_NODE_W, _NODE_TEXT_LEFT + _NODE_TEXT_RIGHT + int(text_w))
        except Exception:
            pass
    width = _NODE_TEXT_LEFT + _NODE_TEXT_RIGHT
    for ch in text:
        width += 14.5 if ord(ch) > 0x2E7F else 7.5
    return max(_MIN_NODE_W, width)


def initial_child_pos(parent_rect, child_width, sibling_rects=(), gap=_MIN_GAP,
                      node_h=_NODE_H):
    """手动布局下新增节点的初始位置：贴近父节点右侧且不压到已有同级节点。

    parent_rect / sibling_rects 均为 (x, y, w, h)；从父节点水平线开始，在
    上下两个方向交替寻找最近且保留 _MIN_GAP 间距的空槽位。
    """
    px, py, pw, ph = parent_rect
    cw = max(float(child_width), _MIN_NODE_W)
    x = px + pw + gap
    offsets = [0]
    for i in range(1, 129):
        offsets.append(i * (ph + gap))
        offsets.append(-i * (ph + gap))
    for offset in offsets:
        y = py + offset
        ok = True
        for rx, ry, rw, rh in sibling_rects:
            h_sep = abs((x + cw / 2.0) - (rx + rw / 2.0))
            v_sep = abs((y + ph / 2.0) - (ry + rh / 2.0))
            if h_sep < (cw + rw) / 2.0 + gap - 1e-6 and \
                    v_sep < (ph + rh) / 2.0 + gap - 1e-6:
                ok = False
                break
        if ok:
            return x, y
    return x, y


def resolve_sync_parent_topic(db, parent_qtype_id, map_id):
    """查找新增节点在科目管理中的父知识点：优先沿用最近关联的父节点。"""
    return db.parent_topic_for_question_type(parent_qtype_id, map_id)


def create_synced_topic(db, name, parent_qtype_id, map_id):
    """思维导图新增节点时同步创建「具体分类」，返回新 topic_id。"""
    return db.add_synced_topic(name, parent_qtype_id, map_id)


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
        self._node_stats = {}  # node_id -> (total, wrong)，父节点为子树汇总
        self._selected_id = None
        self._drag_id = None
        self._drag_off = (0, 0)
        self._drag_start = (0, 0)
        self._drag_target = None
        self._drag_subtree = []
        self._drag_orig = {}
        self._drag_anchor = (0, 0)
        self._dirty = False
        self._pan_active = False
        self._pan_start = None
        self._pan_off0 = (0, 0)
        self._scale = 1.0
        self._off_x = 40.0
        self._off_y = 40.0
        self._search_results = []
        self._search_idx = 0
        self._last_search = ""
        self._center_after = None
        self._search_glow_id = None
        self._search_glow_after = None
        self._detail_questions = []
        self._detail_knowledge = []
        self._detail_open = False
        self._detail_anim_id = 0
        self._empty_state = None
        setup_styles(self)
        self.configure(bg=PALETTE["bg"])
        self._build_ui()
        self._load_maps()

    def refresh(self):
        """主窗口切换页面时由 MainWindow 调用。"""
        if self._dirty and self._map:
            self._save_map(show_feedback=False)
        self._load_maps()

    # ---------- UI ----------
    def _build_ui(self):
        P = PALETTE
        dialog_header(self, "题型思维导图", "每科一图 · 可视化 · 可交互")
        top = tk.Frame(self, bg=P["bg"], padx=14, pady=8)
        top.pack(fill="x")

        # 两行工具栏：自动布局固定位于「新增节点」正下方，右侧功能依次后移。
        grid = tk.Frame(top, bg=P["bg"])
        grid.pack(fill="x", pady=(0, 6))
        grid.columnconfigure(0, minsize=150)

        toolbar_style = ttk.Style(self)
        toolbar_style.configure(
            "Toolbar.TButton", font=_TOOLBAR_FONT, padding=_TOOLBAR_BTN_PAD,
        )
        toolbar_style.configure(
            "Toolbar.Accent.TButton", font=_TOOLBAR_FONT, padding=_TOOLBAR_BTN_PAD,
            background=P["primary"], foreground="#FFFFFF", bordercolor=P["primary"],
            lightcolor=P["primary"], darkcolor=P["primary"], focuscolor=P["primary"],
        )
        toolbar_style.map(
            "Toolbar.Accent.TButton",
            background=[("active", P["primary_hover"]), ("pressed", P["primary_active"]),
                        ("disabled", P["primary_disabled"])],
            foreground=[("disabled", P["primary_disabled_fg"])],
        )
        toolbar_style.configure("Toolbar.TCombobox", font=_TOOLBAR_FONT, padding=5)
        toolbar_style.configure("Toolbar.TEntry", font=_TOOLBAR_FONT, padding=5)

        def toolbar_button(text, command, column, row=0, style=None, pady=(0, 0)):
            btn = ttk.Button(
                grid, text=text, command=command,
                style=style or "Toolbar.TButton",
            )
            btn.grid(row=row, column=column, sticky="w", padx=_TOOLBAR_GAP, pady=pady)
            return btn

        subject = tk.Frame(grid, bg=P["bg"])
        subject.grid(row=0, column=0, sticky="w", padx=(0, 10), pady=(0, 10))
        tk.Label(subject, text="科目：", bg=P["bg"], font=_TOOLBAR_FONT).pack(side="left")
        self.map_var = tk.StringVar()
        self.map_box = ttk.Combobox(
            subject, textvariable=self.map_var, state="readonly", width=12,
            style="Toolbar.TCombobox",
        )
        self.map_box.pack(side="left", padx=(2, 0))
        self.map_box.bind("<<ComboboxSelected>>", lambda e: self._load_current_map())
        ttk.Button(subject, text="管理科目", style="Toolbar.TButton",
                   command=self._open_topic_manager).pack(side="left", padx=(4, 0))

        toolbar_button("＋ 新增节点", self._add_node, 1, style="Toolbar.Accent.TButton",
                       pady=(0, 10))
        toolbar_button("编辑", self._edit_node, 2, pady=(0, 10))
        toolbar_button("删除", self._delete_node, 3, pady=(0, 10))
        self.save_btn = toolbar_button("保存", self._save_map, 4, pady=(0, 10))
        toolbar_button("展开全部", self._expand_all, 5, pady=(0, 10))
        toolbar_button("折叠全部", self._collapse_all, 6, pady=(0, 10))

        toolbar_button("自动布局", self._fit_view, 1, row=1)
        tk.Label(grid, text="布局：", bg=P["bg"], font=_TOOLBAR_FONT).grid(
            row=1, column=2, sticky="e")
        self.layout_var = tk.StringVar()
        self.layout_box = ttk.Combobox(
            grid, textvariable=self.layout_var, state="readonly", width=10,
            values=list(_LAYOUT_LABELS.values()), style="Toolbar.TCombobox",
        )
        self.layout_box.grid(row=1, column=3, sticky="w", padx=_TOOLBAR_GAP)
        self.layout_box.bind("<<ComboboxSelected>>", lambda e: self._set_layout())
        toolbar_button("导入节点", self._import_preset, 4, row=1)
        search = tk.Frame(grid, bg=P["bg"])
        search.grid(row=1, column=5, sticky="w", padx=_TOOLBAR_GAP)
        tk.Label(search, text="搜索：", bg=P["bg"], font=_TOOLBAR_FONT).pack(side="left")
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(
            search, textvariable=self.search_var, width=12, style="Toolbar.TEntry",
        )
        bind_text_paste(self.search_entry)
        bind_entry_undo(self.search_entry)
        self.search_entry.pack(side="left", padx=(2, 0))
        self.search_entry.bind("<Return>", self._search_nodes)
        toolbar_button("定位", self._search_nodes, 6, row=1)
        toolbar_button("导出", self._export, 7, row=1)

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
        self.detail_scroll = ScrollableFrame(right)
        self.detail_scroll.pack(fill="both", expand=True)
        content = self.detail_scroll.inner
        self.detail_name = tk.Label(content, text="请选择节点", bg=PALETTE["surface"], fg=PALETTE["text"],
                                    font=("Microsoft YaHei UI", 15, "bold"), anchor="w")
        self.detail_name.pack(fill="x", pady=(0, 2))
        self.detail_type = tk.Label(content, text="", bg=PALETTE["surface"], fg=PALETTE["muted"],
                                    font=("Microsoft YaHei UI", 11), anchor="w")
        self.detail_type.pack(fill="x", pady=(0, 2))
        self.detail_edit_btn = ttk.Button(content, text="编辑节点", command=self._edit_node)
        self.detail_edit_btn.pack(fill="x", pady=(0, 4))

        qf = tk.Frame(content, bg=PALETTE["surface"])
        qf.pack(fill="x", pady=(0, 6))
        qrow = tk.Frame(qf, bg=PALETTE["surface"])
        qrow.pack(fill="x")
        tk.Label(qrow, text="关联题目", bg=PALETTE["surface"], fg=PALETTE["text"],
                 font=("Microsoft YaHei UI", 12, "bold")).pack(side="left")
        ttk.Button(qrow, text="去题库查看", command=self._open_bank).pack(side="right")
        ttk.Button(qrow, text="＋ 新增关联题目", command=self._add_question_for_node).pack(
            side="right", padx=(6, 0)
        )
        self.questions_list = tk.Listbox(qf, height=5, font=("Microsoft YaHei UI", 10),
                                         bg=PALETTE["input"], fg=PALETTE["text"],
                                         relief="flat", highlightthickness=1,
                                         highlightbackground=PALETTE["border"],
                                         activestyle="none")
        self.questions_list.pack(fill="x", pady=(2, 0))
        self.questions_list.bind("<Double-Button-1>", lambda e: self._open_bank())

        kf = tk.Frame(content, bg=PALETTE["surface"])
        kf.pack(fill="x", pady=(0, 6))
        krow = tk.Frame(kf, bg=PALETTE["surface"])
        krow.pack(fill="x")
        tk.Label(krow, text="关联知识", bg=PALETTE["surface"], fg=PALETTE["text"],
                 font=("Microsoft YaHei UI", 12, "bold")).pack(side="left")
        ttk.Button(krow, text="去知识库", command=self._open_knowledge).pack(side="right")
        self.knowledge_list = tk.Listbox(kf, height=4, font=("Microsoft YaHei UI", 10),
                                         bg=PALETTE["input"], fg=PALETTE["text"],
                                         relief="flat", highlightthickness=1,
                                         highlightbackground=PALETTE["border"],
                                         activestyle="none")
        self.knowledge_list.pack(fill="x", pady=(2, 0))
        self.knowledge_list.bind("<Double-Button-1>", lambda e: self._open_knowledge())

        self.detail_texts = {}
        self.detail_editable = {}
        for key, label in (("recognition", "识别题型"), ("method", "解题方法"),
                           ("remark", "备注")):
            f = tk.Frame(content, bg=PALETTE["surface"])
            f.pack(fill="x", pady=(0, 6))
            tk.Label(f, text=label, bg=PALETTE["surface"], fg=PALETTE["text"],
                     font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w")
            box = AutoHeightRichText(
                f, bg=PALETTE["input"], image_resolver=self.db.abs_path,
                image_store=self.db.store_image, always_editable=True,
                on_save=lambda html, k=key: self._on_detail_field_save(k, html))
            box.pack(fill="x", pady=(2, 0))
            self.detail_texts[key] = box
            self.detail_editable[key] = box

        self.detail_scroll.bind_wheel_all()

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

    def _show_detail(self, on_done=None):
        if self._detail_open:
            if on_done:
                on_done()
            return
        self._detail_open = True
        # before=画布帧：让抽屉先占右侧宽度，画布再填充剩余
        self.detail_frame.pack(side="right", fill="y", before=self._canvas_frame)
        self._animate_detail(self._DETAIL_W, on_done=on_done)

    def _hide_detail(self):
        if not self._detail_open:
            return
        self._detail_open = False
        self._animate_detail(0)

    def _animate_detail(self, target, ms=140, steps=8, on_done=None):
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
            if i == steps and on_done:
                on_done()

        _step(0)

    # ---------- 数据加载 ----------
    def _load_maps(self):
        self._maps = self.db.list_question_maps()
        self.map_box.configure(values=[m["subject_name"] for m in self._maps])
        if self._maps:
            self.map_var.set(self._maps[0]["subject_name"])
            self._hide_empty_state()
            self._load_current_map()
        else:
            self._map = None
            self.canvas.delete("all")
            self.summary.configure(text="暂无科目，请先新增科目")
            self._show_empty_state()

    def _open_topic_manager(self):
        from habit_checkin.ui.topic_manager_dialog import TopicManagerDialog
        current = self.map_var.get()
        dlg = TopicManagerDialog(self, self.db)
        self.wait_window(dlg)
        self._maps = self.db.list_question_maps()
        names = [m["subject_name"] for m in self._maps]
        self.map_box.configure(values=names)
        if names:
            self.map_var.set(current if current in names else names[0])
            self._hide_empty_state()
            self._load_current_map()
        else:
            self._map = None
            self.canvas.delete("all")
            self.summary.configure(text="暂无科目，请先新增科目")
            self._show_empty_state()

    def _show_empty_state(self):
        """无科目时在画布区显示统一空状态。"""
        self._hide_empty_state()
        self._empty_state = EmptyState(
            self._canvas_frame,
            title="暂无科目",
            description="请先在科目管理中新增科目，或导入预置分类节点，\n"
                        "然后回到这里绘制题型思维导图。",
            action_text="打开科目管理",
            command=self._open_topic_manager,
        )
        self._empty_state.place_in(self._canvas_frame, rely=0.5)

    def _hide_empty_state(self):
        if self._empty_state is not None:
            try:
                self._empty_state.destroy()
            except tk.TclError:
                pass
            self._empty_state = None

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
        self._hide_empty_state()
        self._map = m
        prev_sel = self._selected_id  # 重载后保留选中节点（折叠/编辑后抽屉不无故关闭）
        self._save_detail_edits()
        self._nodes = {n["id"]: n for n in self.db.question_types_by_map(m["id"])}
        self._children = {}
        for n in self._nodes.values():
            self._children.setdefault(n["parent_id"], []).append(n)
        for lst in self._children.values():
            lst.sort(key=lambda x: (x.get("sort_order") or 0, x["id"]))
        self._stats = self.db.question_stats_by_map(m["id"])
        self._node_stats = self.db.question_subtree_stats_by_map(m["id"])
        self._scale = float(m.get("view_scale") or 1.0)
        self._selected_id = None
        self._search_results = []
        self._search_idx = 0
        self._last_search = ""
        self._search_glow_id = None
        if self._search_glow_after is not None:
            try:
                self.after_cancel(self._search_glow_after)
            except tk.TclError:
                pass
            self._search_glow_after = None
        self._calc_depths()
        self.layout_var.set(_LAYOUT_LABELS.get(
            m.get("layout_type") or _DEFAULT_LAYOUT, _LAYOUT_LABELS[_DEFAULT_LAYOUT]))
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
        self._dirty = False
        if hasattr(self, "save_btn"):
            self.save_btn.configure(text="保存")
        self.canvas.focus_set()

    # ---------- 布局与绘制 ----------
    _V_STEP = _NODE_H + _MIN_GAP    # 叶子行距：节点高 + 最小间距
    _RADIAL_R1 = 260.0              # 放射布局：一级主题基础半径
    _RADIAL_STEP = 230.0            # 放射布局：每层基础半径增量
    _RADIAL_FILL = 0.92             # 放射布局：允许占满整圆的角向比例

    @staticmethod
    def _node_width(node):
        """节点实际宽度：自动宽度按名称实时估算，手动宽度使用已保存值。"""
        if node and node.get("auto_width", 1):
            return estimate_node_width(node.get("name") if node else "")
        stored = node.get("node_width") if node else 0
        if stored:
            return max(float(stored), _MIN_NODE_W)
        return estimate_node_width(node.get("name") if node else "")

    def _h_spacing(self, parent, child):
        """父子水平间距：保证两个节点边缘之间至少 _MIN_GAP。"""
        return self._node_width(parent) / 2 + self._node_width(child) / 2 + _MIN_GAP

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

    def _subtree_bbox_size(self, node):
        """子树静态包围盒估算：宽度含父边距，高度按子子树纵向堆叠。"""
        w = self._node_width(node)
        if node.get("collapsed"):
            return w, _NODE_H
        kids = self._children.get(node["id"], [])
        if not kids:
            return w, _NODE_H
        sizes = [self._subtree_bbox_size(k) for k in kids]
        cw = max(s[0] for s in sizes)
        ch = sum(s[1] for s in sizes) + _MIN_GAP * (len(sizes) - 1)
        return max(w, w + _MIN_GAP + cw), max(_NODE_H, ch)

    def _logic_bbox_height(self, node):
        """平衡右向布局中子树垂直包围盒高度（折叠子树按单节点计）。"""
        if node.get("collapsed"):
            return _NODE_H
        kids = self._children.get(node["id"], [])
        if not kids:
            return _NODE_H
        return sum(self._logic_bbox_height(k) for k in kids) \
            + _MIN_GAP * (len(kids) - 1)

    def _layout_logic_subtree_balanced(self, node, x, center_y, direction):
        """把子树放到 (x, center_y)，父节点中线与子分支组中线对齐。

        返回子树垂直包围盒 (top, bottom)，兄弟子树之间至少保留 _MIN_GAP。
        """
        nw = self._node_width(node)
        self._node_pos[node["id"]] = (x, center_y - _NODE_H / 2.0)
        top = center_y - _NODE_H / 2.0
        bottom = center_y + _NODE_H / 2.0
        if node.get("collapsed"):
            return top, bottom
        kids = self._children.get(node["id"], [])
        if not kids:
            return top, bottom
        total = sum(self._logic_bbox_height(k) for k in kids) \
            + _MIN_GAP * (len(kids) - 1)
        child_top = center_y - total / 2.0
        group_bottom = center_y + total / 2.0
        for k in kids:
            kh = self._logic_bbox_height(k)
            kcenter = child_top + kh / 2.0
            kw = self._node_width(k)
            kx = x + nw + _MIN_GAP if direction > 0 else x - kw - _MIN_GAP
            kbox = self._layout_logic_subtree_balanced(
                k, kx, kcenter, direction)
            child_top = kbox[1] + _MIN_GAP
            top = min(top, kbox[0])
            group_bottom = max(group_bottom, kbox[1])
        return top, group_bottom

    def _layout_logic_subtree(self, node, x, y, direction):
        """把子树放到 (x, y) 并递归展开，返回该子树当前包围盒。

        首个子节点与父节点顶边对齐；兄弟子树按包围盒高度依次向下排布，
        任意同级子树之间的垂直间距至少 _MIN_GAP。两翼对称布局使用。
        """
        nw = self._node_width(node)
        self._node_pos[node["id"]] = (x, y)
        own = (x, y, x + nw, y + _NODE_H)
        if node.get("collapsed"):
            return own
        kids = self._children.get(node["id"], [])
        if not kids:
            return own
        minx, maxx = x, x + nw
        maxy = y + _NODE_H
        cy = y
        for k in kids:
            kw = self._node_width(k)
            kx = x + nw + _MIN_GAP if direction > 0 else x - kw - _MIN_GAP
            kbox = self._layout_logic_subtree(k, kx, cy, direction)
            minx = min(minx, kbox[0])
            maxx = max(maxx, kbox[2])
            maxy = max(maxy, kbox[3])
            cy = max(cy, kbox[3] + _MIN_GAP)
        return minx, y, maxx, maxy

    def _layout_logic_branches(self, kids):
        """右向逻辑图：一级分支组围绕根节点水平中线上下对称展开。"""
        if not kids:
            return
        root = self._children.get(None, [None])[0]
        root_w = self._node_width(root) if root else _NODE_W
        total = sum(self._logic_bbox_height(k) for k in kids) \
            + _MIN_GAP * (len(kids) - 1)
        child_top = _NODE_H / 2.0 - total / 2.0
        for k in kids:
            kh = self._logic_bbox_height(k)
            kcenter = child_top + kh / 2.0
            self._layout_logic_subtree_balanced(k, root_w + _MIN_GAP, kcenter, 1)
            child_top += kh + _MIN_GAP

    def _layout_column(self, kids, direction):
        """一列一级节点：从根顶边开始向下堆叠，子树沿 direction 展开。"""
        root = self._children.get(None, [None])[0]
        root_w = self._node_width(root) if root else _NODE_W
        cy = 0.0
        for k in kids:
            kw = self._node_width(k)
            kx = root_w + _MIN_GAP if direction > 0 else -kw - _MIN_GAP
            kbox = self._layout_logic_subtree(k, kx, cy, direction)
            cy = max(cy, kbox[3] + _MIN_GAP)

    def _center_logic_branches(self):
        """右向逻辑图整体围绕根节点水平中线上下对称。"""
        root = self._children.get(None, [None])[0]
        if root is None:
            return
        free_ids = {n["id"] for n in self._nodes.values() if n.get("free_float")}
        locked = {root["id"]}
        for fid in free_ids:
            stack = [fid]
            while stack:
                cur = stack.pop()
                locked.add(cur)
                stack.extend(c["id"] for c in self._children.get(cur, []))
        ys = [y for nid, (_x, y) in self._node_pos.items() if nid not in locked]
        if not ys:
            return
        delta = -(min(ys) + max(ys)) / 2.0
        for nid, (x, y) in list(self._node_pos.items()):
            if nid not in locked:
                self._node_pos[nid] = (x, y + delta)

    def _radial_layout(self):
        """环形放射布局：按子树角度需求自底向上分配不重叠的楔形扇区。

        每个子树至少占用其自身节点矩形所需的角度宽度，并把子节点所需宽度
        累加进父级扇区；一级半径通过二分找到能让全部子树放下且互不重叠的
        最小值。自由主题保留原位不参与布局。
        """
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
        root_w = self._node_width(root)
        ox, oy = root_w / 2.0, _NODE_H / 2.0
        free_ids = {n["id"] for n in self._nodes.values() if n.get("free_float")}
        for fid in free_ids:
            self._copy_free_subtree(fid)
        active = [k for k in kids if k["id"] not in free_ids]
        if not active:
            return

        def pair_delta(a, b, radius):
            """两个同级节点中心至少需要错开的角度（保证水平/垂直留 20px）。"""
            rx = (self._node_width(a) + self._node_width(b)) / 2.0 + _MIN_GAP
            ry = _NODE_H + _MIN_GAP
            ratio = min(1.0, math.hypot(rx, ry) / (2.0 * radius))
            return 2.0 * math.asin(ratio)

        def step_for(node):
            subs = self._children.get(node["id"], [])
            if not subs:
                return self._RADIAL_STEP
            return max(
                self._RADIAL_STEP,
                max(self._h_spacing(node, k) for k in subs),
                _NODE_H + _MIN_GAP,
            )

        def required_half(node, siblings, radius):
            """子树在指定半径下需要的角向半宽（rad）。"""
            own = 0.0
            if siblings:
                own = max(pair_delta(node, s, radius) for s in siblings) / 2.0
            subs = self._children.get(node["id"], [])
            if node.get("collapsed") or not subs:
                return own
            child_radius = radius + step_for(node)
            child_half = sum(
                required_half(k, subs, child_radius) for k in subs
            )
            return max(own, child_half)

        target_half = math.pi * self._RADIAL_FILL
        lo = hi = max(self._RADIAL_R1, _NODE_H + _MIN_GAP)
        while sum(required_half(k, active, hi) for k in active) > target_half:
            hi *= 2.0
        for _ in range(80):
            mid = (lo + hi) / 2.0
            if sum(required_half(k, active, mid) for k in active) <= target_half:
                hi = mid
            else:
                lo = mid
        r1 = hi

        def place(node, mid_angle, half, radius):
            rad = mid_angle
            nw = self._node_width(node)
            cx = ox + radius * math.cos(rad)
            cy = oy + radius * math.sin(rad)
            self._node_pos[node["id"]] = (cx - nw / 2.0, cy - _NODE_H / 2.0)
            if node.get("collapsed"):
                return
            subs = self._children.get(node["id"], [])
            if not subs:
                return
            step = step_for(node)
            child_radius = radius + step
            child_halfs = [
                required_half(k, subs, child_radius) for k in subs
            ]
            child_total = sum(child_halfs)
            while child_total > half + 1e-9 and step < 1e8:
                step *= 2.0
                child_radius = radius + step
                child_halfs = [
                    required_half(k, subs, child_radius) for k in subs
                ]
                child_total = sum(child_halfs)
            gap = max(0.0, (half - child_total) / max(1, len(subs)))
            start = mid_angle - (
                child_total * 2.0 + gap * (len(subs) - 1)
            ) / 2.0
            for k, child_half in zip(subs, child_halfs):
                place(k, start + child_half, child_half, child_radius)
                start += child_half * 2.0 + gap

        total_half = sum(required_half(k, active, r1) for k in active)
        gap = max(0.0, (target_half - total_half) / max(1, len(active)))
        start = -math.pi / 2.0 - (
            total_half * 2.0 + gap * (len(active) - 1)
        ) / 2.0
        for k in active:
            half = required_half(k, active, r1)
            place(k, start + half, half, r1)
            start += half * 2.0 + gap

    def _visible_rects(self):
        """返回所有可见节点（不含折叠隐藏子树）的矩形（x, y, w, h）。"""
        hidden = self._hidden_ids()
        rects = {}
        for nid, (x, y) in self._node_pos.items():
            if nid in hidden:
                continue
            n = self._nodes.get(nid)
            if not n:
                continue
            rects[nid] = (x, y, self._node_width(n), _NODE_H)
        return rects

    def _is_ancestor(self, ancestor_id, node_id):
        cur = node_id
        while cur is not None:
            if cur == ancestor_id:
                return True
            node = self._nodes.get(cur)
            cur = node.get("parent_id") if node else None
        return False

    def _movable_subtree(self, node_id, free_ids):
        """返回可整体移动的子节点 id（跳过自由主题及其子树）。"""
        out = []
        stack = [node_id]
        while stack:
            cur = stack.pop()
            if cur in free_ids:
                continue
            out.append(cur)
            stack.extend(c["id"] for c in self._children.get(cur, []))
        return out

    def _resolve_collisions(self):
        """碰撞检测与自动扩开：任意两个可见节点矩形之间至少保留 20px。

        只处理在两个方向都间距不足的矩形对，按较小缺口方向把整棵子树
        推离，最多迭代 3 轮；自由主题视为固定障碍。
        """
        free_ids = {n["id"] for n in self._nodes.values() if n.get("free_float")}
        for _ in range(3):
            rects = self._visible_rects()
            ids = list(rects)
            moved = False
            for i, a in enumerate(ids):
                for b in ids[i + 1:]:
                    if self._is_ancestor(a, b) or self._is_ancestor(b, a):
                        continue
                    a_free, b_free = a in free_ids, b in free_ids
                    if a_free and b_free:
                        continue
                    ax, ay, aw, ah = rects[a]
                    bx, by, bw, bh = rects[b]
                    acx, acy = ax + aw / 2.0, ay + ah / 2.0
                    bcx, bcy = bx + bw / 2.0, by + bh / 2.0
                    short_x = max(0.0, (aw + bw) / 2.0 + _MIN_GAP - abs(acx - bcx))
                    short_y = max(0.0, (ah + bh) / 2.0 + _MIN_GAP - abs(acy - bcy))
                    if short_x <= 1e-6 or short_y <= 1e-6:
                        continue
                    use_y = short_y <= short_x
                    if use_y:
                        amount = short_y
                        sign = 1.0 if bcy > acy else -1.0
                        dx, dy = 0.0, sign * amount
                    else:
                        amount = short_x
                        sign = 1.0 if bcx > acx else -1.0
                        dx, dy = sign * amount, 0.0
                    if a_free:
                        for nid in self._movable_subtree(b, free_ids):
                            x, y = self._node_pos[nid]
                            self._node_pos[nid] = (x + dx, y + dy)
                    elif b_free:
                        for nid in self._movable_subtree(a, free_ids):
                            x, y = self._node_pos[nid]
                            self._node_pos[nid] = (x - dx, y - dy)
                    else:
                        for nid in self._movable_subtree(a, free_ids):
                            x, y = self._node_pos[nid]
                            self._node_pos[nid] = (x - dx / 2.0, y - dy / 2.0)
                        for nid in self._movable_subtree(b, free_ids):
                            x, y = self._node_pos[nid]
                            self._node_pos[nid] = (x + dx / 2.0, y + dy / 2.0)
                    moved = True
            if not moved:
                break

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
        layout = (self._map or {}).get("layout_type") or _DEFAULT_LAYOUT
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
            free_ids = {n["id"] for n in self._nodes.values() if n.get("free_float")}
            for fid in free_ids:
                self._copy_free_subtree(fid)
            active = [k for k in kids if k["id"] not in free_ids]
            half = (len(kids) + 1) // 2
            left = [k for k in active if k in kids[:half]]
            right = [k for k in active if k in kids[half:]]
            self._layout_column(left, -1)          # 左列
            self._layout_column(right, 1)          # 右列
            self._resolve_collisions()
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
            free_ids = {n["id"] for n in self._nodes.values() if n.get("free_float")}
            for fid in free_ids:
                self._copy_free_subtree(fid)
            active = [k for k in kids if k["id"] not in free_ids]
            self._layout_logic_branches(active)    # 右向逻辑图：分支统一向右
            self._resolve_collisions()
            self._center_logic_branches()          # 围绕根节点水平中线对称
        else:
            self._radial_layout()
            self._resolve_collisions()

    def _center_view(self):
        """把当前布局整体居中到画布（scale=1）。"""
        if not self._node_pos:
            return
        xs = [p[0] for p in self._node_pos.values()]
        ys = [p[1] for p in self._node_pos.values()]
        max_w = max((self._node_width(n) for n in self._nodes.values()), default=_NODE_W)
        bcx = (min(xs) + max(xs) + max_w) / 2
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
        # 连线（圆角分支线：一级较粗、深层逐层变细/变淡，颜色继承父节点）
        for n in self._nodes.values():
            if n["parent_id"] is None or n["id"] in hidden:
                continue
            parent = self._nodes.get(n["parent_id"])
            if not parent or parent.get("collapsed"):
                continue
            pw = self._node_width(parent)
            nw = self._node_width(n)
            x1, y1 = world_to_screen(*self._node_pos.get(parent["id"], (0, 0)), scale, ox, oy)
            x2, y2 = world_to_screen(*self._node_pos.get(n["id"], (0, 0)), scale, ox, oy)
            y_center = _NODE_H * scale / 2
            if x2 + nw * scale < x1:
                p0 = (x1, y1 + y_center)
                p1 = (x2 + nw * scale, y2 + y_center)
            else:
                p0 = (x1 + pw * scale, y1 + y_center)
                p1 = (x2, y2 + y_center)
            pts = branch_curve(p0, p1)
            width, color = self._line_style(
                self._depth_of.get(n["id"], 1), self._node_color(parent))
            if n["id"] == self._selected_id or parent["id"] == self._selected_id:
                color, width = PALETTE["focus"], width + 1
            self.canvas.create_line(pts, fill=color, width=width, capstyle=tk.ROUND, smooth=True)
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

    def _draw_node_icon(self, kind, cx, cy, r, fill, node_id):
        if kind == "circle":
            item = self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r, fill=fill, outline="")
        elif kind == "diamond":
            item = self.canvas.create_polygon(
                [cx, cy - r, cx + r, cy, cx, cy + r, cx - r, cy],
                fill=fill, outline="")
        elif kind == "square":
            item = self.canvas.create_rectangle(cx - r, cy - r, cx + r, cy + r, fill=fill, outline="")
        else:
            item = self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r, fill=fill, outline="")
        if item is not None:
            self._node_items[item] = node_id

    def _draw_node(self, node, x, y):
        scale, ox, oy = self._scale, self._off_x, self._off_y
        color = self._node_color(node)
        nw = self._node_width(node)
        sw, sh = nw * scale, _NODE_H * scale
        sx, sy = world_to_screen(x, y, scale, ox, oy)
        is_root = node["parent_id"] is None
        selected = node["id"] == self._selected_id
        stat = self._node_stats.get(node["id"])
        warn = bool(stat and stat[0] and stat[1] >= _WARN_MIN_WRONG
                    and stat[1] / stat[0] >= _WARN_RATE)
        outline = PALETTE["focus"] if selected else (
            PALETTE["danger"] if warn else color)
        radius = 8 * scale

        # 轻投影：仅普通节点使用，让卡片在画布上更有层次
        if not is_root:
            shadow = self.canvas.create_polygon(
                round_rect_points(sx + 3 * scale, sy + 4 * scale, sw, sh, radius),
                fill=lerp_color(PALETTE["border"], PALETTE["bg"], 0.55),
                outline="", smooth=True)
            self._node_items[shadow] = node["id"]

        # 选中光晕：浅色外扩层 + 主色描边
        if selected:
            glow = self.canvas.create_polygon(
                round_rect_points(sx - 2 * scale, sy - 2 * scale,
                                  sw + 4 * scale, sh + 4 * scale, radius + 2 * scale),
                fill=PALETTE["primary_faint"], outline="", smooth=True)
            self._node_items[glow] = node["id"]

        if node["id"] == self._search_glow_id:
            glow = self.canvas.create_polygon(
                round_rect_points(sx - 5 * scale, sy - 5 * scale,
                                  sw + 10 * scale, sh + 10 * scale, radius + 5 * scale),
                fill=PALETTE["accent_light"], outline=PALETTE["accent"], smooth=True,
                width=2.5 * scale)
            self._node_items[glow] = node["id"]

        rect = self.canvas.create_polygon(
            round_rect_points(sx, sy, sw, sh, radius),
            fill=color if is_root else PALETTE["surface"],
            outline=outline, smooth=True,
            width=3 if selected else (2.5 if node["id"] == self._search_glow_id else 1.5))
        self._node_items[rect] = node["id"]
        self._node_rect[node["id"]] = rect

        if not is_root:
            strip = self.canvas.create_rectangle(
                sx + 2 * scale, sy + 6 * scale,
                sx + 5 * scale, sy + sh - 6 * scale,
                fill=color, outline="")
            self._node_items[strip] = node["id"]

        icon_kind = _NODE_ICON_KINDS.get(node["node_type"], "dot")
        icon_fill = "#FFFFFF" if is_root else color
        self._draw_node_icon(
            icon_kind, sx + 15 * scale, sy + sh / 2,
            _NODE_ICON_R * scale, icon_fill, node["id"])

        label = " ".join(str(node["name"] or "").split())
        text_y = sy + sh / 2 - (6 * scale if stat else 0)
        text = self.canvas.create_text(
            sx + _NODE_TEXT_LEFT * scale, text_y, text=label, fill=("#FFFFFF" if is_root else PALETTE["text"]),
            font=("Microsoft YaHei UI", 12, "bold"), anchor="w")
        self._node_items[text] = node["id"]

        # 统计信息：节点底部居中
        if stat and stat[0]:
            total, wrong = stat
            badge = "{}题 · {}错".format(total, wrong)
            bfg = PALETTE["danger"] if warn else PALETTE["muted"]
            btext = self.canvas.create_text(
                sx + sw / 2.0, sy + sh - 11 * scale,
                text=badge, fill=bfg, font=("Microsoft YaHei UI", 9), anchor="center")
            self._node_items[btext] = node["id"]

        # 折叠/展开小圆钮：圆形按钮 + 精简加减号
        if self._children.get(node["id"]):
            b = 14 * scale
            bx0, by0 = sx + sw - b - 3 * scale, sy + 3 * scale
            btn = self.canvas.create_oval(
                bx0, by0, bx0 + b, by0 + b,
                fill=PALETTE["surface"], outline=color, width=1.2 * scale)
            bcx, bcy = bx0 + b / 2, by0 + b / 2
            arm = 5 * scale
            if node.get("collapsed"):
                hline = self.canvas.create_line(
                    bcx - arm, bcy, bcx + arm, bcy,
                    fill=color, width=1.2 * scale, capstyle=tk.ROUND)
                vline = self.canvas.create_line(
                    bcx, bcy - arm, bcx, bcy + arm,
                    fill=color, width=1.2 * scale, capstyle=tk.ROUND)
                self._node_items[hline] = node["id"]
                self._node_items[vline] = node["id"]
                self._collapse_buttons[hline] = node["id"]
                self._collapse_buttons[vline] = node["id"]
            else:
                hline = self.canvas.create_line(
                    bcx - arm, bcy, bcx + arm, bcy,
                    fill=color, width=1.2 * scale, capstyle=tk.ROUND)
                self._node_items[hline] = node["id"]
                self._collapse_buttons[hline] = node["id"]
            self._node_items[btn] = node["id"]
            self._collapse_buttons[btn] = node["id"]

    def _find_node_by_event(self, event):
        item = self.canvas.find_withtag("current")
        if not item:
            # 兜底：直接按事件坐标反查节点矩形，兼容非悬停触发的点击/程序化事件
            for nid, (x, y) in self._node_pos.items():
                node = self._nodes.get(nid)
                if not node:
                    continue
                nw = self._node_width(node) * self._scale
                nh = _NODE_H * self._scale
                sx, sy = world_to_screen(x, y, self._scale, self._off_x, self._off_y)
                if sx <= event.x <= sx + nw and sy <= event.y <= sy + nh:
                    return node
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
            self._mark_dirty()
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
        self._mark_dirty()

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
                elif wy > ty + _NODE_H + _MIN_GAP:     # 明显在目标下方 -> 插其后
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
        self._mark_dirty()

    def _draw_drag_highlight(self, node_id):
        """拖拽目标高亮框（虚线 accent 色）。"""
        x, y = self._node_pos.get(node_id, (0, 0))
        sx, sy = world_to_screen(x, y, self._scale, self._off_x, self._off_y)
        sw = self._node_width(self._nodes.get(node_id, {})) * self._scale
        sh = _NODE_H * self._scale
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
        nw = self._node_width(self._nodes.get(node_id, {}))
        cx = self._node_pos[node_id][0] + nw / 2
        cy = self._node_pos[node_id][1] + _NODE_H / 2
        best_x = best_y = None
        dx_best = dy_best = thr
        hidden = self._hidden_ids()
        for nid, (x, y) in self._node_pos.items():
            if nid == node_id or nid in hidden:
                continue
            tx = x + self._node_width(self._nodes.get(nid, {})) / 2
            ty = y + _NODE_H / 2
            dx = abs(tx - cx)
            dy = abs(ty - cy)
            if dx < dx_best:
                dx_best, best_x = dx, tx
            if dy < dy_best:
                dy_best, best_y = dy, ty
        if best_x is not None:
            self._node_pos[node_id] = (best_x - nw / 2, self._node_pos[node_id][1])
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
        entry = getattr(self, "_inline_entry", None)
        if entry is not None and entry.winfo_exists():
            commit = getattr(self, "_inline_commit", None)
            if commit:
                commit()
            return "break"
        node = self._find_node_by_event(event)
        if node:
            self._inline_edit(node)
        else:
            self._fit_view()

    def _inline_edit(self, node):
        """画布内联编辑节点名：Enter / 双击空白 / 失焦保存，Esc 取消。"""
        x, y = self._node_pos.get(node["id"], (0, 0))
        sx, sy = world_to_screen(x, y, self._scale, self._off_x, self._off_y)
        sw = self._node_width(node) * self._scale
        sh = _NODE_H * self._scale
        entry = tk.Entry(self.canvas, font=("Microsoft YaHei UI", 12),
                         justify="center", relief="solid")
        bind_text_paste(entry)
        entry.insert(0, node["name"])
        bind_entry_undo(entry)
        entry.place(x=int(sx), y=int(sy), width=max(int(sw), 40), height=max(int(sh), 24))
        entry.focus_set()
        entry.select_range(0, "end")
        state = {"done": False}

        def finish():
            if state["done"]:
                return
            state["done"] = True
            self._inline_entry = None
            self._inline_commit = None

        def commit(_e=None):
            if state["done"]:
                return "break"
            val = entry.get().strip()
            finish()
            entry.destroy()
            if val and val != node["name"]:
                fields = {"name": val}
                if node.get("auto_width", 1):
                    fields["node_width"] = estimate_node_width(val)
                if node.get("topic_id"):
                    # 节点已关联知识点时，把新名称同步回科目管理
                    try:
                        self.db.rename_question_type_with_sync(node["id"], val)
                    except ValueError as exc:
                        messagebox.showwarning("同步名称失败", str(exc), parent=self)
                        return "break"
                    if node.get("auto_width", 1):
                        self.db.update_question_type_full(
                            node["id"], node_width=fields["node_width"])
                else:
                    self.db.update_question_type_full(node["id"], **fields)
                node["name"] = val
                node["node_width"] = fields.get("node_width", node.get("node_width"))
                self._draw()
                self._select_node(node["id"])
                self._mark_dirty()
            return "break"

        def cancel(_e=None):
            finish()
            entry.destroy()
            return "break"

        self._inline_entry = entry
        self._inline_commit = commit
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
                ("＋ 新增关联题目", lambda: self._add_question_for_node(node)),
                ("关联知识", lambda: self._link_knowledge(node)),
                ("移除选中知识", lambda: self._unlink_knowledge(node)),
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
        self._mark_dirty()

    def _back_to_auto(self):
        """整图回到自动布局（自由主题保留原位）。"""
        if self._map:
            self.db.update_question_map(self._map["id"], layout_mode="auto")
            self._load_current_map()
            self._mark_dirty()

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
        lt = next((k for k, v in _LAYOUT_LABELS.items() if v == label), _DEFAULT_LAYOUT)
        self.db.update_question_map(m["id"], layout_type=lt, layout_mode="auto")
        m["layout_type"] = lt  # 同步内存缓存（_current_map 读取它）
        m["layout_mode"] = "auto"
        self._load_current_map()
        self._mark_dirty()

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
        self._mark_dirty()

    def _mark_dirty(self):
        """标记存在尚未显式保存的布局调整，并给出可见提示。"""
        self._dirty = True
        if hasattr(self, "save_btn"):
            self.save_btn.configure(text="● 保存")

    def _save_map(self, show_feedback=True):
        """把当前节点位置、宽度与视图状态一次性持久化，并显示保存反馈。"""
        if not self._map:
            return
        try:
            for nid, (x, y) in self._node_pos.items():
                node = self._nodes.get(nid)
                if not node:
                    continue
                self.db.update_question_type_full(
                    nid,
                    pos_x=float(x),
                    pos_y=float(y),
                    node_width=float(self._node_width(node)),
                )
            self.db.update_question_map(
                self._map["id"],
                layout_mode=self._map.get("layout_mode") or "auto",
                view_scale=self._scale,
                view_offset_x=self._off_x,
                view_offset_y=self._off_y,
            )
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc), parent=self)
            return
        self._dirty = False
        self.save_btn.configure(text="保存")
        if show_feedback:
            self.summary.configure(text="已保存：节点位置、宽度与视图状态已写入数据库")

    def _import_preset(self):
        """把科目管理的具体分类节点树导入当前科目的思维导图（幂等）。"""
        m = self._current_map()
        if not m:
            return
        n = self.db.import_preset_question_types(m["id"])
        self._load_current_map()
        if n:
            messagebox.showinfo("导入节点", "已导入 {} 个分类节点。".format(n), parent=self)
        else:
            messagebox.showinfo("导入节点", "当前科目没有可导入的分类节点，或内容已存在。", parent=self)

    def _select_node(self, node_id, on_detail_done=None):
        self._save_detail_edits()
        self._selected_id = node_id
        node = self._nodes.get(node_id)
        if not node:
            return
        self.detail_name.configure(text=node["name"])
        self.detail_type.configure(
            text="类型：{}".format(_NODE_TYPE_LABELS.get(node["node_type"], node["node_type"])))
        stat = self._node_stats.get(node["id"])
        if stat and stat[0]:
            self.detail_type.configure(
                text="{} · 关联题目 {} 题 / 错 {} 题".format(
                    _NODE_TYPE_LABELS.get(node["node_type"], node["node_type"]), stat[0], stat[1]))
        for key, txt in self.detail_texts.items():
            txt.set_html(node.get(key) or "")
        self._fill_questions_list(node)
        self._fill_knowledge_list(node)
        self.summary.configure(
            text="当前节点：{}  ·  共 {} 个节点".format(node["name"], len(self._nodes)))
        self._show_detail(on_detail_done)
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
                "end", "{}  {}  {}".format(
                    q["code"], res, to_plain(q.get("question_text") or "")[:16]))
            self._detail_questions.append(q["id"])
        if not items:
            self.questions_list.insert("end", "（该知识点暂无题目）")

    def _clear_detail(self):
        self._save_detail_edits()
        self.detail_name.configure(text="请选择节点")
        self.detail_type.configure(text="")
        self.questions_list.delete(0, "end")
        self.questions_list.insert("end", "（未关联知识点，无题目）")
        self._detail_questions = []
        self.knowledge_list.delete(0, "end")
        self.knowledge_list.insert("end", "（未关联知识）")
        self._detail_knowledge = []
        for txt in self.detail_texts.values():
            txt.set_html("")
        self.summary.configure(text="共 {} 个节点".format(len(self._nodes)))
        self._hide_detail()

    def _save_detail_edits(self):
        """结束详情编辑态：把识别题型/解题方法/备注内容落库。"""
        for box in self.detail_editable.values():
            box.save()

    def _on_detail_field_save(self, key, html):
        node = self._nodes.get(self._selected_id)
        if not node:
            return
        try:
            self.db.update_question_type_full(node["id"], **{key: html})
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc), parent=self)
            return
        node[key] = html
        label = {"recognition": "识别题型", "method": "解题方法",
                 "remark": "备注"}.get(key, key)
        self.summary.configure(text="已保存：{}".format(label))

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

    def _add_question_for_node(self, node=None):
        """打开题目表单，按当前节点预填科目与细分分类。"""
        node = node or self._selected_node()
        if not node:
            return
        topic_id = node.get("topic_id")
        if not topic_id:
            messagebox.showinfo("提示", "请先给该节点关联知识点，再新增题目。", parent=self)
            return
        from habit_checkin.ui.question_form_dialog import QuestionFormDialog
        dlg = QuestionFormDialog(
            self, self.db,
            prefill_topic_id=topic_id,
            prefill_detail_type_id=node.get("id"),
        )
        self.wait_window(dlg)
        if dlg.saved_question:
            self._stats = self.db.question_stats_by_map(self._map["id"])
            self._node_stats = self.db.question_subtree_stats_by_map(self._map["id"])
            self._select_node(node["id"])

    # ---------- 关联知识 ----------
    def _fill_knowledge_list(self, node):
        self.knowledge_list.delete(0, "end")
        self._detail_knowledge = []
        links = self.db.knowledge_links_for_node(node["id"])
        for link in links:
            self.knowledge_list.insert(
                "end", "{} · {}".format(link["doc_title"], link["block_title"]))
            self._detail_knowledge.append(link)
        if not links:
            self.knowledge_list.insert("end", "（未关联知识）")

    def _open_knowledge(self):
        node = self._selected_node()
        if not node:
            return
        links = self.db.knowledge_links_for_node(node["id"])
        if not links:
            messagebox.showinfo("提示", "该节点还没有关联知识块。", parent=self)
            return
        mw = self.master
        if hasattr(mw, "open_knowledge_doc"):
            mw.open_knowledge_doc(links[0]["doc_id"], block_id=links[0]["block_id"])

    def _link_knowledge(self, node):
        """打开知识块选择器，把当前节点与所选知识块建立关联。"""
        picker = KnowledgeBlockPicker(self, self.db)
        self.wait_window(picker)
        if picker.result is None:
            return
        try:
            self.db.link_knowledge_block(picker.result, node["id"], auto_link=False)
        except Exception as exc:
            messagebox.showerror("关联失败", str(exc), parent=self)
            return
        self._fill_knowledge_list(node)
        messagebox.showinfo("关联完成", "知识块已关联到当前节点。", parent=self)

    def _unlink_knowledge(self, node):
        sel = self.knowledge_list.curselection()
        links = getattr(self, "_detail_knowledge", [])
        if not sel or not links or sel[0] >= len(links):
            messagebox.showinfo("提示", "请先在下方的关联知识列表中选择一项。", parent=self)
            return
        link = links[sel[0]]
        if messagebox.askyesno(
            "移除关联", "确定移除「{}」与当前节点的关联吗？".format(link["block_title"]),
            parent=self,
        ):
            self.db.unlink_knowledge_block(link["block_id"], node["id"])
            self._fill_knowledge_list(node)

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
        self._cancel_pending_center()
        self._expand_ancestors(node_id)
        self._search_glow_id = node_id
        if self._search_glow_after is not None:
            try:
                self.after_cancel(self._search_glow_after)
            except tk.TclError:
                pass
        self._search_glow_after = self.after(
            1800, lambda: self._clear_search_glow(node_id))
        # 详情抽屉动画完成后画布尺寸才稳定，此时一次性精确居中
        self._select_node(node_id, on_detail_done=lambda: self._center_on_node(node_id))
        self.summary.configure(text="{} / {}：{}".format(
            self._search_idx + 1, len(self._search_results), self._nodes[node_id]["name"]))

    def _clear_search_glow(self, node_id):
        self._search_glow_after = None
        if self._search_glow_id != node_id:
            return
        self._search_glow_id = None
        self._draw()

    def _center_on_node(self, node_id):
        """把节点中心移到当前画布可视区域正中心。"""
        self._cancel_pending_center()
        try:
            rect = self._node_rect.get(node_id)
            if not rect:
                return
            bbox = self.canvas.bbox(rect)
            if not bbox:
                return
            cx = (bbox[0] + bbox[2]) / 2
            cy = (bbox[1] + bbox[3]) / 2
            self._off_x = self.canvas.winfo_width() / 2 - cx
            self._off_y = self.canvas.winfo_height() / 2 - cy
            self._draw()
        except tk.TclError:
            pass

    def _cancel_pending_center(self):
        if self._center_after is None:
            return
        try:
            self.after_cancel(self._center_after)
        except tk.TclError:
            pass
        self._center_after = None

    def _expand_ancestors(self, node_id):
        node = self._nodes.get(node_id)
        if not node:
            return
        parent_id = node.get("parent_id")
        changed = False
        while parent_id is not None:
            parent = self._nodes.get(parent_id)
            if not parent:
                break
            if parent.get("collapsed"):
                parent["collapsed"] = 0
                self.db.update_question_type_full(parent_id, collapsed=0)
                changed = True
            parent_id = parent.get("parent_id")
        if changed and self._map.get("layout_mode") != "manual":
            self._auto_layout_internal()

    # ---------- 操作 ----------
    def _add_map(self):
        values = ask_fields(
            self, "新增科目", [
                {"key": "name", "label": "科目名称", "required": True,
                 "placeholder": "例如：资料分析"},
            ],
            subtitle="新增后将创建一张思维导图",
        )
        if not values:
            return
        name = values["name"].strip()
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
            msg += (
                "\n该科目会连同知识库对应分支、打卡计划、历史记录和图片一并删除，不可恢复。"
                "\n题库题目将保留为未分类。"
            )
        else:
            msg += "\n题库题目将保留为未分类，不再关联该思维导图的细分题型。"
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
        if dlg.result and dlg.result.get("id"):
            self._place_new_node_near_parent(dlg.result)
            self._load_current_map()
            self._select_node(dlg.result["id"])
        else:
            self._load_current_map()

    def _place_new_node_near_parent(self, data):
        """手动布局下把新节点放在父节点右侧最近且不重叠的位置。"""
        if self._map.get("layout_mode") != "manual":
            return
        node_id = data.get("id")
        parent_id = data.get("parent_id")
        parent = self._nodes.get(parent_id) if parent_id is not None else None
        if node_id is None or parent is None:
            return
        px, py = self._node_pos.get(
            parent["id"],
            (parent.get("pos_x") or 0, parent.get("pos_y") or 0),
        )
        child_width = float(data.get("node_width") or 0)
        if not child_width:
            child_width = estimate_node_width(data.get("name") or "")
        obstacle_rects = []
        for nid, (nx, ny, nw, nh) in self._visible_rects().items():
            if nid == node_id:
                continue
            obstacle_rects.append((nx, ny, nw, nh))
        x, y = initial_child_pos(
            (px, py, self._node_width(parent), _NODE_H),
            child_width,
            obstacle_rects,
        )
        self.db.update_question_type_full(node_id, pos_x=x, pos_y=y)

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
        linked_note = ""
        if node.get("topic_id"):
            linked_note = (
                "\n该节点已关联科目管理，将同步删除知识库对应分支、"
                "科目管理及其打卡记录和图片，不可恢复。"
                "\n题库题目将保留为未分类，不再关联该细分题型。"
            )
        else:
            linked_note = "\n题库题目将保留为未分类，不再关联该细分题型。"
        if messagebox.askyesno(
            "删除节点",
            "确定删除「{}」及其 {} 个子节点吗？{}".format(
                node["name"], count - 1, linked_note),
            parent=self,
        ):
            self.db.delete_question_type_with_sync(node["id"])
            self._load_current_map()

    def _toggle_collapse(self, node=None):
        node = node or self._selected_node()
        if not node:
            return
        self.db.toggle_question_type_collapsed(node["id"])
        node["collapsed"] = 0 if node.get("collapsed") else 1
        if self._map.get("layout_mode") != "manual":
            self._auto_layout_internal()
        self._draw()
        self._mark_dirty()

    def _expand_all(self):
        if not self._map:
            return
        self.db.set_question_types_collapsed(self._map["id"], 0)
        for n in self._nodes.values():
            n["collapsed"] = 0
        if self._map.get("layout_mode") != "manual":
            self._auto_layout_internal()
        self._draw()
        self._mark_dirty()

    def _collapse_all(self):
        if not self._map:
            return
        self.db.set_question_types_collapsed(self._map["id"], 1)
        for n in self._nodes.values():
            n["collapsed"] = 1
        if self._map.get("layout_mode") != "manual":
            self._auto_layout_internal()
        self._draw()
        self._mark_dirty()

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


class NodeEditDialog(FieldEditDialog):
    """新增/编辑思维导图节点：统一字段表单 + 保留业务校验。"""

    def __init__(self, master, db, node=None, map_id=None, parent_id=None):
        self.db = db
        self.node = node
        self.map_id = map_id or (node.get("map_id") if node else None)
        self.parent_id = parent_id if parent_id is not None else (
            node.get("parent_id") if node else None
        )
        topics = db.list_topics()
        paths = db.topic_paths([t["id"] for t in topics])
        self._topic_map = {paths[t["id"]]: t["id"] for t in topics}
        current_topic = "（不关联）"
        if node and node.get("topic_id"):
            current_topic = paths.get(node["topic_id"], "（不关联）")
        name = node["name"] if node else ""
        auto_width = bool(node.get("auto_width", 1)) if node else True
        width = (node.get("node_width") if node and not auto_width and node.get("node_width")
                 else int(estimate_node_width(name)))
        map_row = db.get_question_map(self.map_id) if self.map_id else None
        can_sync = bool(map_row and map_row.get("topic_id"))
        fields = [
            {"key": "name", "label": "节点名称", "value": name,
             "required": True, "placeholder": "例如：增长量计算"},
            {"key": "node_type", "label": "节点类型", "type": "choice",
             "required": True, "choices": list(_NODE_TYPE_LABELS.keys()),
             "value": node["node_type"] if node else "type"},
            {"key": "auto_width", "label": "节点宽度", "type": "bool",
             "value": auto_width, "check_text": "自动宽度（文字单行）"},
            {"key": "node_width", "label": "宽度", "type": "integer",
             "value": int(width), "min": int(_MIN_NODE_W), "max": 1200},
            {"key": "color", "label": "节点颜色", "type": "color",
             "value": node.get("color") if node else ""},
            {"key": "topic", "label": "关联知识点", "type": "choice",
             "choices": ["（不关联）"] + sorted(paths.values()),
             "value": current_topic},
        ]
        if not node:
            fields.append({
                "key": "sync_topic", "label": "同步科目", "type": "bool",
                "value": can_sync,
                "disabled": not can_sync,
                "check_text": ("同步新增到科目管理（具体分类）"
                               if can_sync
                               else "同步新增到科目管理（当前导图未关联科目）"),
            })
        fields.extend([
            {"key": "recognition", "label": "识别题型", "type": "multiline",
             "height": 3, "value": node.get("recognition") if node else ""},
            {"key": "method", "label": "解题方法", "type": "multiline",
             "height": 4, "value": node.get("method") if node else ""},
            {"key": "remark", "label": "备注", "type": "multiline",
             "height": 3, "value": node.get("remark") if node else ""},
        ])
        super().__init__(
            master, "编辑节点" if node else "新增节点", fields,
            subtitle=("新增节点可同步到科目管理" if not node
                      else "关联节点的改名将同步到科目管理"),
        )

    def _save(self, event=None):
        values = self._collect_values()
        errors = self._validate_values(values)
        if errors:
            self._show_errors(errors)
            return
        name = values["name"].strip()
        node_width = (int(estimate_node_width(name)) if values["auto_width"]
                      else values["node_width"])
        topic_label = values["topic"]
        data = {
            "name": name,
            "node_type": values["node_type"],
            "color": values["color"],
            "node_width": node_width,
            "auto_width": 1 if values["auto_width"] else 0,
            "recognition": values["recognition"],
            "method": values["method"],
            "remark": values["remark"],
            "topic_id": None,
        }
        if self.node:
            data["parent_id"] = self.node.get("parent_id")
            data["topic_id"] = (self._topic_map.get(topic_label)
                                if topic_label != "（不关联）" else None)
            data["id"] = self.node["id"]
            self.db.update_question_type_full(self.node["id"], **data)
            old_topic_id = self.node.get("topic_id")
            if (old_topic_id and old_topic_id == data["topic_id"]
                    and name != self.node["name"]):
                try:
                    self.db.rename_question_type_with_sync(self.node["id"], name)
                except ValueError as exc:
                    messagebox.showwarning("同步名称失败", str(exc), parent=self)
        else:
            if values.get("sync_topic"):
                try:
                    new_id, new_topic_id = self.db.add_synced_question_type(
                        name,
                        parent_id=self.parent_id,
                        map_id=self.map_id,
                        node_type=values["node_type"],
                        color=values["color"],
                        node_width=node_width,
                        auto_width=1 if values["auto_width"] else 0,
                        recognition=values["recognition"],
                        method=values["method"],
                        remark=values["remark"],
                    )
                    data["id"] = new_id
                    data["topic_id"] = new_topic_id
                except ValueError as exc:
                    messagebox.showwarning("无法同步新增", str(exc), parent=self)
                    return
            else:
                data["map_id"] = self.map_id
                data["parent_id"] = self.parent_id
                new_id = self.db.add_question_type_full(**data)
                data["id"] = new_id
        self.result = data
        self.destroy()


class KnowledgeBlockPicker(tk.Toplevel):
    """选择知识库知识块：按文档树浏览，双击或点「关联」返回 block_id。"""

    def __init__(self, master, db):
        super().__init__(master)
        self.db = db
        self.result = None
        self.title("选择知识块")
        self.geometry("520x580")
        self.minsize(440, 420)
        self.transient(master)
        setup_styles(self)
        self.configure(bg=PALETTE["bg"])
        dialog_header(self, "选择知识块", "按文档浏览并选择要关联的知识点", title_size=14, subtitle_size=9)
        self._build()
        center_window(self)
        self.grab_set()

    def _build(self):
        P = PALETTE
        body = tk.Frame(self, bg=P["bg"], padx=14, pady=10)
        body.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(body, columns=("info",), show="tree headings",
                                 selectmode="browse", height=18)
        self.tree.heading("#0", text="文档 / 知识块")
        self.tree.heading("info", text="说明")
        self.tree.column("info", width=110, anchor="w", stretch=False)
        vsb = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda e: self._choose())
        self._load()

        bottom = tk.Frame(self, bg=P["bg"], padx=14, pady=10)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="取消", command=self.destroy).pack(side="right")
        ttk.Button(bottom, text="关联", style="Accent.TButton",
                   command=self._choose).pack(side="right", padx=8)
        self.bind("<Escape>", lambda e: self.destroy())

    def _load(self):
        self.tree.delete(*self.tree.get_children())
        docs = self.db.list_knowledge_docs()
        for doc in docs:
            d_iid = "d{}".format(doc["id"])
            self.tree.insert(
                "", "end", iid=d_iid, text=doc["title"],
                values=("{} 个知识点".format(doc.get("block_count") or 0),),
                open=False,
            )
            for blk in self.db.list_knowledge_blocks(doc["id"]):
                n = len(html_to_plain(blk.get("content") or ""))
                self.tree.insert(
                    d_iid, "end", iid="b{}".format(blk["id"]),
                    text=blk["title"], values=("{} 字".format(n),),
                )
        if docs:
            first = "d{}".format(docs[0]["id"])
            self.tree.item(first, open=True)

    def _choose(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先选择一条知识块。", parent=self)
            return
        iid = sel[0]
        if iid.startswith("d"):
            messagebox.showinfo("提示", "请选择文档下的具体知识块。", parent=self)
            return
        self.result = int(iid[1:])
        self.destroy()
