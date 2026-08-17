"""设置窗口：提醒偏好 + 自定义科目/知识点管理。"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from habit_checkin.services import autostart
from habit_checkin.ui.theme import PALETTE, dialog_header
from habit_checkin.ui.topic_tree import TopicTreeMixin


class SettingsWindow(TopicTreeMixin, tk.Frame):
    def __init__(self, master, db):
        super().__init__(master, bg=PALETTE["bg"])
        self.db = db
        from habit_checkin.ui.common import setup_styles
        setup_styles(self)
        self.configure(bg=PALETTE["bg"])
        dialog_header(self, "设置", "提醒偏好 · 科目管理")
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=10, pady=10)
        self._build_reminder_tab(nb)
        self._build_general_tab(nb)
        self._build_topic_tab(nb)

    # ---------- 提醒设置 ----------
    def _build_reminder_tab(self, nb):
        tab = ttk.Frame(nb, padding=14)
        nb.add(tab, text="提醒设置")
        self.sound_var = tk.BooleanVar(value=self.db.get_bool_setting("sound_enabled", True))
        self.toast_var = tk.BooleanVar(value=self.db.get_bool_setting("toast_enabled", False))
        from habit_checkin.ui.common import TextCheck
        cb1 = TextCheck(
            tab, "启用提示音（到点时播放系统提示音）", variable=self.sound_var,
            command=lambda: self.db.set_setting("sound_enabled", "1" if self.sound_var.get() else "0"),
        )
        cb1.pack(anchor="w", pady=4)
        cb2 = TextCheck(
            tab, "启用 Windows 系统通知（尽力而为，未注册应用时可能不显示）",
            variable=self.toast_var,
            command=lambda: self.db.set_setting("toast_enabled", "1" if self.toast_var.get() else "0"),
        )
        cb2.pack(anchor="w", pady=4)
        focus_row = tk.Frame(tab, bg=PALETTE["bg"])
        focus_row.pack(anchor="w", pady=(12, 0))
        tk.Label(focus_row, text="专注提醒间隔（分钟）：", bg=PALETTE["bg"]).pack(side="left")
        self.focus_var = tk.StringVar(value=self.db.get_setting("focus_minutes", "45"))
        ttk.Spinbox(focus_row, from_=0, to=180, width=5, textvariable=self.focus_var).pack(side="left", padx=(0, 6))
        ttk.Button(focus_row, text="保存", command=self._save_focus).pack(side="left")
        ttk.Label(tab, text="打卡计时达到设定时长后弹休息提醒；设为 0 关闭。",
                  style="Hint.TLabel").pack(anchor="w", pady=(4, 0))
        ttk.Label(
            tab,
            text="提醒仅在 App 运行时生效；到点时未完成的打卡项会弹出置顶提醒。",
            style="Hint.TLabel",
        ).pack(anchor="w", pady=(12, 0))
        ttk.Label(
            tab,
            text="数据目录：{}".format(self.db.base_dir / "data"),
            style="Hint.TLabel",
        ).pack(anchor="w", pady=(4, 0))

    # ---------- 科目管理 ----------
    def _build_topic_tab(self, nb):
        tab = ttk.Frame(nb, padding=10)
        nb.add(tab, text="科目管理")
        self.tree = ttk.Treeview(tab, columns=("type", "state"), show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="科目 / 知识点")
        self.tree.heading("type", text="类型")
        self.tree.heading("state", text="状态")
        self.tree.column("#0", width=300, anchor="w")
        self.tree.column("type", width=70, anchor="center", stretch=False)
        self.tree.column("state", width=70, anchor="center", stretch=False)
        vsb = ttk.Scrollbar(tab, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.tag_configure("drag_target", background=PALETTE["primary_light"])
        self.tree.bind("<ButtonPress-1>", self._on_drag_press)
        self.tree.bind("<B1-Motion>", self._on_drag_motion)
        self.tree.bind("<ButtonRelease-1>", self._on_drag_release)
        self.tree.bind("<Button-3>", self._on_right_click)
        self._drag_item = None
        self._drag_active = False
        self._drag_press_time = 0.0
        self._drag_target = None

        hint = ttk.Frame(tab, padding=(10, 0))
        hint.pack(side="right", fill="y")
        ttk.Label(
            hint,
            text="右键科目标题可增删改；\n右键空白处可新增科目。\n长按拖动可调整顺序或层级\n（拖到分类上成为其子项）。\n预置科目只能停用；\n自定义科目可重命名、删除。\n删除会连带清理相关记录与图片。",
            style="Hint.TLabel",
            justify="left",
        ).pack(fill="x")
        self._refresh_tree()

    def _refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        topics = self.db.list_topics(include_disabled=True)
        children = {}
        for t in topics:
            children.setdefault(t["parent_id"], []).append(t)

        def add(parent_iid, t):
            iid = "t{}".format(t["id"])
            state = "停用" if t["disabled"] else "启用"
            typ = "预置" if t["is_preset"] else "自定义"
            self.tree.insert(parent_iid, "end", iid=iid, text=t["name"], values=(typ, state), open=True)
            for kid in children.get(t["id"], []):
                add(iid, kid)

        for r in children.get(None, []):
            add("", r)

    # ---------- 通用设置（开机自启） ----------
    def _build_general_tab(self, nb):
        tab = ttk.Frame(nb, padding=14)
        nb.add(tab, text="通用设置")
        from habit_checkin.ui.common import TextCheck
        self.autostart_var = tk.BooleanVar(value=autostart.is_enabled())
        cb = TextCheck(
            tab, "开机自动启动（登录 Windows 后自动打开习惯打卡）",
            variable=self.autostart_var,
            command=self._toggle_autostart,
        )
        cb.pack(anchor="w", pady=4)
        ttk.Label(
            tab,
            text="开启后会在系统「启动」文件夹创建快捷方式；\n"
                 "关闭时删除该快捷方式，不影响应用本身。",
            style="Hint.TLabel",
            justify="left",
        ).pack(anchor="w", pady=(12, 0))

        self.dark_var = tk.BooleanVar(value=self.db.get_bool_setting("dark_mode", False))
        dark_cb = TextCheck(
            tab, "深色模式（重启应用后生效）",
            variable=self.dark_var,
            command=self._toggle_dark,
        )
        dark_cb.pack(anchor="w", pady=4)

        ttk.Separator(tab, orient="horizontal").pack(fill="x", pady=(16, 8))
        tk.Label(tab, text="关闭窗口时", bg=PALETTE["bg"], fg=PALETTE["text"],
                 font=("Microsoft YaHei UI", 13, "bold")).pack(anchor="w")
        self.close_action_var = tk.StringVar(value=self.db.get_setting("close_action", "ask"))
        for value, text in (
            ("ask", "每次询问"),
            ("exit", "直接关闭（退出）"),
            ("tray", "最小化到托盘"),
        ):
            rb = ttk.Radiobutton(
                tab,
                text=text,
                value=value,
                variable=self.close_action_var,
                command=self._save_close_action,
            )
            rb.pack(anchor="w", pady=2)
        ttk.Label(
            tab,
            text="选择后立即保存；下次点窗口 X 时会按此方式执行。\n如果选择「最小化到托盘」，需要已安装 pystray。",
            style="Hint.TLabel",
            justify="left",
        ).pack(anchor="w", pady=(4, 0))

        ttk.Separator(tab, orient="horizontal").pack(fill="x", pady=(16, 8))
        tk.Label(tab, text="总体统计", bg=PALETTE["bg"], fg=PALETTE["text"],
                 font=("Microsoft YaHei UI", 13, "bold")).pack(anchor="w")
        ttk.Button(tab, text="清零总体统计（从今天重新计）", command=self._reset_stats).pack(anchor="w", pady=(6, 0))
        ttk.Label(
            tab,
            text="清零后「完成计划总数 / 已完成 / 完成率」只统计今天及之后的打卡项，"
                 "原来的完成数不再计入。\n已打卡记录本身不受影响。",
            style="Hint.TLabel",
            justify="left",
        ).pack(anchor="w", pady=(4, 0))

        ttk.Separator(tab, orient="horizontal").pack(fill="x", pady=(16, 8))
        tk.Label(tab, text="数据备份", bg=PALETTE["bg"], fg=PALETTE["text"],
                 font=("Microsoft YaHei UI", 13, "bold")).pack(anchor="w")
        ttk.Button(tab, text="立即备份数据库", command=self._backup_now).pack(anchor="w", pady=(6, 0))
        ttk.Label(
            tab,
            text="每天打开应用时会自动备份一次（保留最近 14 份），备份目录：data/backups。",
            style="Hint.TLabel",
        ).pack(anchor="w", pady=(4, 0))

    def _save_focus(self):
        try:
            minutes = int(self.focus_var.get().strip())
        except ValueError:
            messagebox.showwarning("专注提醒", "请输入整数分钟数。", parent=self)
            return
        self.db.set_setting("focus_minutes", str(max(0, minutes)))
        messagebox.showinfo("已保存", "专注提醒间隔已更新。", parent=self)

    def _save_close_action(self):
        self.db.set_setting("close_action", self.close_action_var.get())

    def _reset_stats(self):
        from datetime import date
        if not messagebox.askyesno(
            "清零统计",
            "确定从今天（{}）起重新统计吗？\n"
            "「完成计划总数 / 已完成 / 完成率」将只统计今天及之后的打卡项，\n"
            "历史完成数不再计入（打卡记录本身不删除）。".format(date.today().isoformat()),
            parent=self,
        ):
            return
        self.db.set_setting("stats_reset_date", date.today().isoformat())
        messagebox.showinfo("已清零", "总体统计已从今天起重新计算。", parent=self)

    def _backup_now(self):
        from habit_checkin.services.backup import backup_db
        dst = backup_db(self.db.db_path, self.db.base_dir / "data" / "backups")
        if dst:
            messagebox.showinfo("备份成功", "已备份到：\n{}".format(dst), parent=self)
        else:
            messagebox.showwarning("备份失败", "无法创建备份，请检查磁盘空间与权限。", parent=self)

    def _toggle_autostart(self):
        want = self.autostart_var.get()
        ok = autostart.enable() if want else autostart.disable()
        if not ok:
            self.autostart_var.set(not want)
            messagebox.showwarning(
                "开机自启", "设置失败，请确认权限后重试。", parent=self
            )

    def _toggle_dark(self):
        self.db.set_setting("dark_mode", "1" if self.dark_var.get() else "0")
        if messagebox.askyesno(
            "深色模式",
            "主题设置已保存，需要重启应用才能生效。\n是否立即重启？",
            parent=self,
        ):
            from habit_checkin.services.restart import launch_new_instance
            root = self.winfo_toplevel()
            if launch_new_instance():
                root.after(400, root.destroy)
            else:
                messagebox.showwarning("重启失败", "自动重启失败，请手动关闭并重新打开应用。", parent=self)
