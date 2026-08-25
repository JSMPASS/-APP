"""界面主题：语义化浅色/深色配色 + 全局 ttk 样式 + 常用组件（卡片、横幅、悬停按钮、统计卡）。

- LIGHT_PALETTE / DARK_PALETTE 为两套完整色板；
- 模块级 PALETTE 为「当前生效」色板，set_theme(dark) 在启动时切换（需在构建 UI 前调用，
  运行中切换请重启应用）；
- 所有颜色统一从 PALETTE 取值，避免散落的硬编码十六进制色。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from habit_checkin.ui.animate import lerp_color

# ---------------- 浅色色板 ----------------
LIGHT_PALETTE = {
    # 底色/表面
    "bg": "#EEF2F7",            # 窗口底色
    "card": "#FFFFFF",          # 卡片/面板（兼容别名）
    "surface": "#FFFFFF",       # 卡片/面板
    "surface_hover": "#F2F6FC", # 卡片/行悬停
    "sidebar": "#F6F8FC",       # 侧边栏底色
    "border": "#D8E0EA",        # 描边
    "divider": "#E5EAF2",       # 分隔线
    "input": "#FFFFFF",         # 输入框/表格行底色
    "bar": "#E9EEF5",           # 底部操作栏底色
    # 文字
    "text": "#1F2937",          # 正文
    "muted": "#6B7280",         # 次要
    "faint": "#9AA5B1",         # 弱化
    # 主色（蓝）
    "primary": "#2D6CDF",
    "primary_dark": "#2458B8",
    "primary_hover": "#2458B8",
    "primary_active": "#1E4E9F",
    "primary_light": "#E4EDFB",
    "primary_faint": "#F0F5FD",
    # 成功/完成（绿）
    "accent": "#16A34A",
    "accent_hover": "#12803E",
    "accent_light": "#E7F6EC",
    # 警告/危险
    "warning": "#D97706",
    "danger": "#DC2626",
    "danger_hover": "#B91C1C",
    "danger_active": "#991B1B",
    "danger_light": "#FDEAEA",
    # 头/尾
    "header_fg": "#FFFFFF",
    "header_sub": "#DCE7FB",
    # 列表
    "stripe": "#F5F8FC",
    "done": "#16A34A",
    "todo": "#6B7280",
    # 焦点
    "focus": "#2D6CDF",
    # 控件 chrome（ttk 样式三态）
    "btn_active": "#E9EFF7",
    "btn_pressed": "#DCE4EF",
    "btn_disabled": "#F1F4F8",
    "primary_disabled": "#A8C2EC",
    "primary_disabled_fg": "#EAF1FD",
    "accent_disabled": "#A9D8BE",
    "accent_disabled_fg": "#EDF8F1",
    "heading_bg": "#EFF3F9",
    "heading_hover": "#E4EAF4",
    "progress_trough": "#E4EAF2",
    "scrollbar": "#D4DCE6",
    "scrollbar_hover": "#BFC9D6",
    "tab_bg": "#E3E9F2",
}

# ---------------- 深色色板 ----------------
DARK_PALETTE = {
    "bg": "#12161C",
    "card": "#1A212B",
    "surface": "#1A212B",
    "surface_hover": "#232C38",
    "sidebar": "#161C24",
    "border": "#2A3442",
    "divider": "#232B36",
    "input": "#141A22",
    "bar": "#141A22",
    "text": "#E6EAF0",
    "muted": "#9AA7B4",
    "faint": "#6B7686",
    "primary": "#5B8DEF",
    "primary_dark": "#4A7BE0",
    "primary_hover": "#4A7BE0",
    "primary_active": "#3B68C9",
    "primary_light": "#1E2B44",
    "primary_faint": "#1A2436",
    "accent": "#2FBF71",
    "accent_hover": "#27A763",
    "accent_light": "#17321F",
    "warning": "#E39A3B",
    "danger": "#EF5350",
    "danger_hover": "#C64542",
    "danger_active": "#A63A37",
    "danger_light": "#2E1A1C",
    "header_fg": "#FFFFFF",
    "header_sub": "#B9CDF0",
    "stripe": "#1A212B",
    "done": "#2FBF71",
    "todo": "#9AA7B4",
    "focus": "#5B8DEF",
    "btn_active": "#232C38",
    "btn_pressed": "#2E3A48",
    "btn_disabled": "#1F2732",
    "primary_disabled": "#3A4A66",
    "primary_disabled_fg": "#C7D3E8",
    "accent_disabled": "#2A4A38",
    "accent_disabled_fg": "#CBE8D6",
    "heading_bg": "#1B232E",
    "heading_hover": "#232C38",
    "progress_trough": "#232B36",
    "scrollbar": "#2A3442",
    "scrollbar_hover": "#384457",
    "tab_bg": "#1B232E",
}

# 当前生效色板（默认为浅色）
PALETTE = dict(LIGHT_PALETTE)


def set_theme(dark):
    """切换当前色板。需在构建 UI 前调用；运行中切换请保存设置后重启应用。"""
    PALETTE.clear()
    PALETTE.update(DARK_PALETTE if dark else LIGHT_PALETTE)


def is_dark():
    return PALETTE.get("bg") == DARK_PALETTE["bg"]


FONT = ("Microsoft YaHei UI", 13)
FONT_SMALL = ("Microsoft YaHei UI", 11)
FONT_BOLD = ("Microsoft YaHei UI", 13, "bold")
FONT_TITLE = ("Microsoft YaHei UI", 17, "bold")
FONT_BIG = ("Microsoft YaHei UI", 13, "bold")
FONT_NUM = ("Microsoft YaHei UI", 20, "bold")
FONT_HEADER = ("Microsoft YaHei UI", 15, "bold")

# 全局按钮统一字号与内边距，避免各页面按钮大小/间距参差
BUTTON_FONT = ("Microsoft YaHei UI", 13)
BUTTON_PAD_X = 13
BUTTON_PAD_Y = 8
ACCENT_PAD_X = 15
ACCENT_PAD_Y = 9


def apply_theme(root):
    """应用全局 ttk 样式（clam 主题支持完整自定义）。"""
    P = PALETTE
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure(".", font=FONT)

    # 容器与文字
    style.configure("TFrame", background=P["bg"])
    style.configure("Card.TFrame", background=P["surface"])
    style.configure("TLabel", background=P["bg"], foreground=P["text"])
    style.configure("Card.TLabel", background=P["surface"], foreground=P["text"])
    style.configure("Muted.TLabel", background=P["bg"], foreground=P["muted"], font=FONT_SMALL)
    style.configure("CardMuted.TLabel", background=P["surface"], foreground=P["muted"], font=FONT_SMALL)
    style.configure("Section.TLabel", font=FONT_TITLE, background=P["surface"], foreground=P["text"])
    style.configure("Hint.TLabel", background=P["bg"], foreground=P["faint"], font=FONT_SMALL)

    # 普通按钮（白底浅边，悬停/按下/禁用三态）
    style.configure(
        "TButton",
        background=P["surface"], foreground=P["text"],
        bordercolor=P["border"], lightcolor=P["surface"], darkcolor=P["surface"],
        relief="flat", font=BUTTON_FONT, padding=(BUTTON_PAD_X, BUTTON_PAD_Y),
        focuscolor=P["surface"],
    )
    style.map(
        "TButton",
        background=[("active", P["btn_active"]), ("pressed", P["btn_pressed"]),
                    ("disabled", P["btn_disabled"])],
        foreground=[("disabled", P["faint"])],
        bordercolor=[("active", P["border"])],
    )

    # 主按钮（蓝色填充）
    style.configure(
        "Accent.TButton",
        background=P["primary"], foreground="#FFFFFF",
        bordercolor=P["primary"], lightcolor=P["primary"], darkcolor=P["primary"],
        relief="flat", font=BUTTON_FONT, padding=(ACCENT_PAD_X, ACCENT_PAD_Y),
        focuscolor=P["primary"],
    )
    style.map(
        "Accent.TButton",
        background=[("active", P["primary_hover"]), ("pressed", P["primary_active"]),
                    ("disabled", P["primary_disabled"])],
        foreground=[("disabled", P["primary_disabled_fg"])],
    )

    # 成功按钮（绿色填充）
    style.configure(
        "Success.TButton",
        background=P["accent"], foreground="#FFFFFF",
        bordercolor=P["accent"], lightcolor=P["accent"], darkcolor=P["accent"],
        relief="flat", font=BUTTON_FONT, padding=(ACCENT_PAD_X, ACCENT_PAD_Y),
        focuscolor=P["accent"],
    )
    style.map(
        "Success.TButton",
        background=[("active", P["accent_hover"]), ("pressed", P["accent_hover"]),
                    ("disabled", P["accent_disabled"])],
        foreground=[("disabled", P["accent_disabled_fg"])],
    )

    # 危险按钮（红色填充）
    style.configure(
        "Danger.TButton",
        background=P["danger"], foreground="#FFFFFF",
        bordercolor=P["danger"], lightcolor=P["danger"], darkcolor=P["danger"],
        relief="flat", font=BUTTON_FONT, padding=(BUTTON_PAD_X, BUTTON_PAD_Y),
        focuscolor=P["danger"],
    )
    style.map("Danger.TButton", background=[("active", P["danger_hover"]),
                                            ("pressed", P["danger_active"])])

    # 输入框
    style.configure(
        "TEntry",
        fieldbackground=P["input"], foreground=P["text"],
        bordercolor=P["border"], lightcolor=P["border"], darkcolor=P["border"],
        padding=6,
    )
    style.map("TEntry", bordercolor=[("focus", P["focus"])],
              lightcolor=[("focus", P["focus"])])

    # 下拉框
    style.configure(
        "TCombobox",
        fieldbackground=P["input"], foreground=P["text"], background=P["surface"],
        bordercolor=P["border"], lightcolor=P["border"], darkcolor=P["border"],
        padding=5, arrowcolor=P["text"],
    )
    style.map("TCombobox", bordercolor=[("focus", P["focus"])],
              fieldbackground=[("readonly", P["input"])])

    # 复选框/文本勾选
    style.configure("TCheckbutton", background=P["bg"], foreground=P["text"])
    style.configure("Card.TCheckbutton", background=P["surface"], foreground=P["text"])

    # 表格
    style.configure(
        "Treeview",
        background=P["input"], fieldbackground=P["input"], foreground=P["text"],
        rowheight=34, borderwidth=0, relief="flat",
    )
    style.map(
        "Treeview",
        background=[("selected", P["primary"])],
        foreground=[("selected", "#FFFFFF")],
    )
    style.configure(
        "Treeview.Heading",
        background=P["heading_bg"], foreground=P["text"], font=FONT_BOLD,
        relief="flat", borderwidth=0, padding=(9, 10),
    )
    style.map("Treeview.Heading", background=[("active", P["heading_hover"])])

    # 进度条
    style.configure(
        "Horizontal.TProgressbar",
        troughcolor=P["progress_trough"], background=P["accent"],
        bordercolor=P["progress_trough"], lightcolor=P["accent"], darkcolor=P["accent"],
    )

    # 滚动条
    style.configure(
        "Vertical.TScrollbar", background=P["scrollbar"], troughcolor=P["bg"],
        bordercolor=P["bg"], arrowcolor=P["muted"], relief="flat",
    )
    style.map("Vertical.TScrollbar", background=[("active", P["scrollbar_hover"])])
    style.configure(
        "Horizontal.TScrollbar", background=P["scrollbar"], troughcolor=P["bg"],
        bordercolor=P["bg"], arrowcolor=P["muted"], relief="flat",
    )
    style.map("Horizontal.TScrollbar", background=[("active", P["scrollbar_hover"])])

    # 笔记本
    style.configure("TNotebook", background=P["bg"], borderwidth=0, tabmargins=(8, 8, 8, 0))
    style.configure(
        "TNotebook.Tab", background=P["tab_bg"], foreground=P["text"], padding=(17, 9), font=FONT,
    )
    style.map("TNotebook.Tab", background=[("selected", P["surface"])],
              foreground=[("selected", P["primary"])])

    # 标签页容器
    style.configure(
        "TLabelframe", background=P["surface"], bordercolor=P["border"],
        lightcolor=P["border"], darkcolor=P["border"], relief="solid",
    )
    style.configure(
        "TLabelframe.Label", background=P["surface"], foreground=P["text"], font=FONT_BOLD,
    )


def card(parent, padx=16, pady=14, bg=None, **kw):
    """白色卡片容器（带浅描边）。"""
    f = tk.Frame(parent, bg=bg or PALETTE["surface"],
                 highlightbackground=PALETTE["border"], highlightthickness=1, **kw)
    if padx or pady:
        f.configure(padx=padx, pady=pady)
    return f


def hover_button(parent, text, command, bg=None, fg=None, hover_bg=None,
                 font=FONT, padx=13, pady=6, animate=True, **kw):
    """带悬停过渡效果的扁平按钮（tk.Button）。"""
    P = PALETTE
    bg = bg or P["surface"]
    fg = fg or P["primary"]
    hover_bg = hover_bg or P["primary_light"]
    btn = tk.Button(
        parent, text=text, command=command, bg=bg, fg=fg,
        activebackground=hover_bg, activeforeground=fg,
        relief="flat", bd=0, highlightthickness=0,
        font=font, padx=padx, pady=pady, cursor="hand2", **kw,
    )
    _timer = {"id": None}

    def _to(target):
        def _go(i):
            try:
                btn.configure(bg=lerp_color(bg, target, i / 8))
                if i < 8:
                    _timer["id"] = btn.after(12, lambda: _go(i + 1))
            except tk.TclError:
                pass
        if animate:
            if _timer["id"] is not None:
                try:
                    btn.after_cancel(_timer["id"])
                except tk.TclError:
                    pass
            _go(0)
        else:
            btn.configure(bg=target)

    btn.bind("<Enter>", lambda e: _to(hover_bg))
    btn.bind("<Leave>", lambda e: _to(bg))
    return btn


def dialog_header(parent, title, subtitle="", title_size=12, subtitle_size=8):
    """对话框/页面顶部彩色横幅，视觉统一。"""
    P = PALETTE
    header = tk.Frame(parent, bg=P["primary"], padx=18, pady=12)
    header.pack(fill="x")
    tk.Label(header, text=title, bg=P["primary"], fg=P["header_fg"],
             font=("Microsoft YaHei UI", title_size, "bold")).pack(side="left")
    if subtitle:
        tk.Label(header, text=subtitle, bg=P["primary"], fg=P["header_sub"],
                 font=("Microsoft YaHei UI", subtitle_size)).pack(side="right")
    return header


def stat_card(parent, caption, number_color=None):
    """统计卡片：大数字 + 说明文字，返回 (frame, 数字label)。"""
    P = PALETTE
    f = tk.Frame(
        parent, bg=P["surface"],
        highlightbackground=P["border"], highlightthickness=1,
    )
    f.pack(side="left", fill="x", expand=True, padx=(0, 12))
    num = tk.Label(f, text="0", bg=P["surface"],
                   fg=number_color or P["primary"], font=FONT_NUM)
    num.pack(pady=(10, 0))
    tk.Label(f, text=caption, bg=P["surface"], fg=P["muted"], font=FONT_SMALL).pack(pady=(0, 10))
    return f, num
