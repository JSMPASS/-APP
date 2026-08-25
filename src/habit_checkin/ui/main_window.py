"""主窗口：左侧栏单窗口导航 + 今日页。"""
from __future__ import annotations

import threading
import queue
import time
import tkinter as tk
from datetime import date, datetime, timedelta
from tkinter import filedialog, messagebox, ttk

from habit_checkin.db import Database
from habit_checkin.services.reminder import ReminderService
from habit_checkin.services.tray import TrayIcon
from habit_checkin.services import toast
from habit_checkin.services.export_common import fmt_clock
from habit_checkin.ui.animate import count_up, lerp_color, smooth_progress, toast as ui_toast
from habit_checkin.ui.checkin_dialog import CheckinDialog
from habit_checkin.ui.close_dialog import CloseChoiceDialog
from habit_checkin.ui.progress_ring import ProgressRing
from habit_checkin.ui.richtext import to_plain
from habit_checkin.ui.theme import PALETTE, apply_theme, card, dialog_header, hover_button, stat_card
from habit_checkin.ui.theme_menu import ThemeMenu


class SidebarApp(tk.Tk):
    """单窗口应用：左侧栏导航 + 内容区页面切换。"""

    NAV = [
        ("today", "首页"),
        ("study", "备考进度"),
        ("bank", "题库"),
        ("types", "题型思维导图"),
        ("knowledge", "知识库"),
        ("reflection", "练习复盘"),
        ("progress", "总体进度"),
        ("history", "历史记录"),
        ("settings", "设置"),
    ]

    def __init__(self, db):
        super().__init__()
        self.db = db
        from habit_checkin.services.ocr import apply_model_dir_from_setting
        apply_model_dir_from_setting(self.db)
        self.title("习惯打卡")
        self.geometry("1672x1050")
        self.minsize(1320, 820)
        apply_theme(self)
        self.configure(bg=PALETTE["bg"])
        self.protocol("WM_DELETE_WINDOW", self._on_close_choice)
        self._pages = {}
        self._nav_buttons = {}
        self._page_revisions = {}
        self._current = None
        self._build_sidebar()
        self._build_content()
        self._reminder = ReminderService(db.db_path, interval=30)
        self._reminder.start()
        self.after(800, self._poll_reminder)
        self.show_page("today")
        # 页面构建成功后再启动托盘，避免初始化失败留下无主窗口的后台进程
        self._tray_queue = queue.Queue()
        self._tray = TrayIcon(self)
        self._tray_available = self._tray.start()
        self.after(200, self._poll_tray_queue)
        self.after(1200, self._maybe_show_checkpoint)

    # ---------- 侧边栏 ----------
    def _build_sidebar(self):
        P = PALETTE
        self.sidebar = tk.Frame(self, bg=P["sidebar"], width=214)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        title = tk.Frame(self.sidebar, bg=P["sidebar"], padx=18, pady=20)
        title.pack(fill="x")
        tk.Label(title, text="习惯打卡", bg=P["sidebar"], fg=P["primary"],
                 font=("Microsoft YaHei UI", 20, "bold")).pack(anchor="w")
        tk.Label(title, text="每日计划 · 打卡 · 题库", bg=P["sidebar"], fg=P["muted"],
                 font=("Microsoft YaHei UI", 11)).pack(anchor="w", pady=(2, 0))

        nav = tk.Frame(self.sidebar, bg=P["sidebar"], padx=10)
        nav.pack(fill="x", pady=(6, 0))
        for key, label in self.NAV:
            self._nav_buttons[key] = self._make_nav_item(nav, key, label)

        foot = tk.Frame(self.sidebar, bg=P["sidebar"], padx=18, pady=16)
        foot.pack(side="bottom", fill="x")
        tk.Label(foot, text="数据：{}".format(self.db.base_dir / "data"),
                 bg=P["sidebar"], fg=P["faint"], font=("Microsoft YaHei UI", 11),
                 wraplength=180, justify="left").pack(anchor="w")

    def _make_nav_item(self, parent, key, label):
        P = PALETTE
        item = tk.Frame(parent, bg=P["sidebar"], height=42)
        item.pack(fill="x", pady=2)
        item.pack_propagate(False)
        ind = tk.Frame(item, bg=P["sidebar"], width=4)
        ind.pack(side="left", fill="y")
        lbl = tk.Label(item, text=label, bg=P["sidebar"], fg=P["text"],
                       font=("Microsoft YaHei UI", 13), anchor="w", padx=12, cursor="hand2")
        lbl.pack(side="left", fill="both", expand=True)
        for w in (item, lbl):
            w.bind("<Button-1>", lambda e, k=key: self.show_page(k))
            w.bind("<Enter>", lambda e, i=item: i.configure(bg=P["surface_hover"]))
            w.bind("<Leave>", lambda e, i=item: i.configure(
                bg=P["primary_light"] if i is self._nav_buttons.get(self._current) else P["sidebar"]))
        item._ind = ind
        item._lbl = lbl
        return item

    def _update_nav(self, key):
        P = PALETTE
        for k, item in self._nav_buttons.items():
            active = k == key
            bg = P["primary_light"] if active else P["sidebar"]
            item.configure(bg=bg)
            item._ind.configure(bg=P["primary"] if active else P["sidebar"])
            item._lbl.configure(bg=bg, fg=P["primary"] if active else P["text"],
                                font=("Microsoft YaHei UI", 13, "bold" if active else "normal"))

    # ---------- 内容区 ----------
    def _build_content(self):
        self.content = tk.Frame(self, bg=PALETTE["bg"])
        self.content.pack(side="left", fill="both", expand=True)

    def show_page(self, key):
        if self._current == key:
            page = self._pages.get(key)
            if page is not None and hasattr(page, "refresh"):
                page.refresh()
            return
        if self._current is not None and self._current in self._pages:
            self._pages[self._current].pack_forget()
        page = self._pages.get(key)
        if page is None:
            page = self._create_page(key)
            self._pages[key] = page
        # 页面 pack 进内容区容器（而非根窗口），否则内容区只占极小宽度、页面溢出到右侧
        page.pack(in_=self.content, fill="both", expand=True)
        if hasattr(page, "refresh"):
            force = bool(getattr(page, "_force_refresh", False))
            page._force_refresh = False
            last = self._page_revisions.get(key)
            if force or last is None or self.db.revision() != last \
                    or getattr(page, "_dirty", False):
                page.refresh()
                self._page_revisions[key] = self.db.revision()
        self._current = key
        self._update_nav(key)

    def open_day(self, day_str=None):
        """跳转到「今日」页并定位到指定日期（None/空表示今天）。"""
        from datetime import date as _date
        try:
            d = _date.fromisoformat(day_str) if day_str else _date.today()
        except ValueError:
            d = _date.today()
        page = self._pages.get("today")
        if page is None:
            page = self._create_page("today")
            self._pages["today"] = page
        if hasattr(page, "current_date"):
            page.current_date = d
            page._force_refresh = True
        self.show_page("today")

    def _create_page(self, key):
        from habit_checkin.ui.history_window import HistoryWindow
        from habit_checkin.ui.progress_window import ProgressWindow
        from habit_checkin.ui.question_bank_window import QuestionBankWindow
        from habit_checkin.ui.reflection_window import ReflectionWindow
        from habit_checkin.ui.question_type_mindmap_window import QuestionTypeMindmapWindow
        from habit_checkin.ui.settings_window import SettingsWindow
        from habit_checkin.ui.knowledge_bank_window import KnowledgeBankWindow
        if key == "today":
            return TodayPage(self, self.db)
        if key == "study":
            from habit_checkin.ui.study_progress_page import StudyProgressPage
            return StudyProgressPage(self, self.db)
        if key == "bank":
            return QuestionBankWindow(self, self.db)
        if key == "types":
            return QuestionTypeMindmapWindow(self, self.db)
        if key == "knowledge":
            return KnowledgeBankWindow(self, self.db)
        if key == "reflection":
            return ReflectionWindow(self, self.db)
        if key == "progress":
            return ProgressWindow(self, self.db)
        if key == "history":
            return HistoryWindow(self, self.db)
        if key == "settings":
            return SettingsWindow(self, self.db)
        raise KeyError(key)

    def open_knowledge_doc(self, doc_id, block_id=None):
        """思维导图跳转知识库：切到知识库页并定位文档/知识块。"""
        page = self._pages.get("knowledge")
        if page is None:
            page = self._create_page("knowledge")
            self._pages["knowledge"] = page
        self.show_page("knowledge")
        if hasattr(page, "open_doc"):
            page.open_doc(doc_id, block_id=block_id)

    # ---------- 提醒 ----------
    def _poll_reminder(self):
        while True:
            ev = self._reminder.get_event()
            if ev is None:
                break
            self._show_reminder(ev)
        self.after(1000, self._poll_reminder)

    def _show_reminder(self, ev):
        item = self.db.get_plan_item(ev["item_id"])
        if not item or item["done"]:
            return
        P = PALETTE
        top = tk.Toplevel(self)
        top.title("打卡提醒")
        top.configure(bg=P["bg"])
        top.attributes("-topmost", True)
        top.resizable(False, False)
        top.geometry("460x260")
        from habit_checkin.ui.common import center_window
        center_window(top)
        box = card(top, padx=26, pady=20)
        box.pack(fill="both", expand=True, padx=14, pady=14)
        tk.Label(box, text="⏰ 到点打卡啦", bg=P["surface"], fg=P["primary"],
                 font=("Microsoft YaHei UI", 13, "bold")).pack()
        tk.Label(box, text=ev["topic_path"], bg=P["surface"], fg=P["text"],
                 font=("Microsoft YaHei UI", 15, "bold"), wraplength=380,
                 justify="center").pack(pady=(12, 2))
        tk.Label(box, text="{}（{}）".format(ev["plan_date"], ev["reminder_time"]),
                 bg=P["surface"], fg=P["muted"], font=("Microsoft YaHei UI", 13)).pack()
        btns = tk.Frame(box, bg=P["surface"])
        btns.pack(pady=(18, 0))
        item_id = ev["item_id"]

        def go_checkin():
            top.destroy()
            dlg = CheckinDialog(self, self.db, item, ev["plan_date"])
            self.wait_window(dlg)
            page = self._pages.get("today")
            if page is not None and hasattr(page, "refresh"):
                page.refresh()

        def snooze():
            self._reminder.snooze(item_id, 10)
            top.destroy()

        def ignore():
            self._reminder.ignore_today(item_id)
            top.destroy()

        ttk.Button(btns, text="去打卡", style="Success.TButton", command=go_checkin).pack(side="left")
        ttk.Button(btns, text="稍后 10 分钟", command=snooze).pack(side="left", padx=10)
        ttk.Button(btns, text="忽略今天", command=ignore).pack(side="left")
        from habit_checkin.ui.animate import slide_in
        slide_in(top)
        if self.db.get_bool_setting("sound_enabled", True):
            try:
                import winsound
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            except Exception:
                pass
        if self.db.get_bool_setting("toast_enabled", False):
            threading.Thread(
                target=toast.show_toast,
                args=("习惯打卡提醒", ev["topic_path"]),
                daemon=True,
            ).start()

    # ---------- 备考检查点提醒 ----------
    def _maybe_show_checkpoint(self):
        """若今天是计划配置里的检查点，弹一次提醒。"""
        try:
            from habit_checkin.services.study_plan import day_number, checkpoint_for, get_plan_config
            cfg = get_plan_config(self.db)
            start_str = self.db.get_setting("plan_start_date", "")
            try:
                start = date.fromisoformat(start_str)
            except (ValueError, TypeError):
                return
            day = day_number(start, date.today())
            cp = checkpoint_for(day, cfg["checkpoints"])
            if not cp:
                return
            today = date.today().isoformat()
            if self.db.get_setting("checkpoint_notified", "") == today:
                return
            self.db.set_setting("checkpoint_notified", today)
            self._show_checkpoint_dialog(cp)
        except Exception as exc:  # noqa: BLE001
            import logging
            logging.warning("检查点提醒失败：%s", exc)

    def _show_checkpoint_dialog(self, cp):
        day, content = cp
        P = PALETTE
        top = tk.Toplevel(self)
        top.title("备考检查点 · 第 {} 天".format(day))
        top.configure(bg=P["bg"])
        top.attributes("-topmost", True)
        top.resizable(False, False)
        from habit_checkin.ui.common import center_window
        center_window(top)
        box = card(top, padx=26, pady=20)
        box.pack(fill="both", expand=True, padx=14, pady=14)
        tk.Label(box, text="📌 第 {} 天检查点".format(day), bg=P["surface"], fg=P["primary"],
                 font=("Microsoft YaHei UI", 17, "bold")).pack()
        tk.Label(box, text=content, bg=P["surface"], fg=P["text"],
                 font=("Microsoft YaHei UI", 13), wraplength=420,
                 justify="left").pack(pady=(14, 2), anchor="w")
        ttk.Button(box, text="知道了", style="Accent.TButton", command=top.destroy).pack(pady=(16, 0))

    def _on_close_choice(self):
        """点击窗口 X：按已记住的关闭方式执行；未设置时弹出选择。"""
        self._persist_timer()
        action = self.db.get_setting("close_action", "ask")
        if action == "exit":
            self._really_quit()
            return
        if action == "tray" and self._tray_available:
            self._hide_to_tray()
            return
        dlg = CloseChoiceDialog(self, tray_available=self._tray_available)
        self.wait_window(dlg)
        action = dlg.result
        if dlg.remember and action in ("exit", "tray"):
            self.db.set_setting("close_action", action)
        if action == "exit":
            self._really_quit()
        elif action == "tray" and self._tray_available:
            self._hide_to_tray()

    def _persist_timer(self):
        page = self._pages.get("today")
        if page is not None and hasattr(page, "persist_timer"):
            page.persist_timer()

    def _really_quit(self):
        """真正退出：停止提醒、停止托盘、销毁窗口。"""
        self._persist_timer()
        self._reminder.stop()
        if getattr(self, "_tray", None) is not None:
            self._tray.stop()
        self.destroy()

    def _hide_to_tray(self):
        """隐藏主窗口，保留后台提醒与托盘图标。"""
        self.withdraw()
        try:
            toast.show_toast("习惯打卡", "已最小化到系统托盘")
        except Exception:  # noqa: BLE001
            pass

    def iconify(self):
        """重写最小化：托盘可用时最小化到托盘，否则保持普通最小化。"""
        if getattr(self, "_tray_available", False):
            self._hide_to_tray()
        else:
            super().iconify()

    def show_from_tray(self):
        """从托盘恢复主窗口。"""
        try:
            self.deiconify()
            self.state("normal")
            self.lift()
            self.focus_force()
        except tk.TclError:
            pass

    def quit_from_tray(self):
        """托盘菜单退出。"""
        try:
            self.after(0, self._really_quit)
        except Exception:  # noqa: BLE001
            self._really_quit()

    def enqueue_tray_action(self, action):
        """供托盘线程安全调用：把动作放入队列，由主线程处理。"""
        self._tray_queue.put(action)

    def _poll_tray_queue(self):
        """主线程定期消费托盘动作队列。"""
        try:
            while True:
                action = self._tray_queue.get_nowait()
                if action == "show":
                    self.show_from_tray()
                elif action == "quit":
                    self._really_quit()
        except queue.Empty:
            pass
        try:
            if self.winfo_exists():
                self.after(200, self._poll_tray_queue)
        except tk.TclError:
            pass


class TodayPage(tk.Frame):
    """今日页：总体进度 + 今日计划 + 打卡/导出快捷操作。"""

    _COLUMNS = ("status", "topic", "goal", "remind", "timer", "checked")

    def __init__(self, master, db):
        super().__init__(master, bg=PALETTE["bg"])
        self.db = db
        self.current_date = date.today()
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        P = PALETTE
        # 顶栏（日期 + 快捷操作）
        top = tk.Frame(self, bg=P["bg"], padx=18, pady=14)
        top.pack(fill="x")
        self.page_title = tk.Label(top, text="首页", bg=P["bg"], fg=P["text"],
                                   font=("Microsoft YaHei UI", 20, "bold"))
        self.page_title.pack(side="left")
        self.plan_title_label = tk.Label(top, text="", bg=P["bg"], fg=P["muted"],
                                         font=("Microsoft YaHei UI", 13))
        self.plan_title_label.pack(side="left", padx=(8, 0))
        nav = tk.Frame(top, bg=P["bg"])
        nav.pack(side="left", padx=14)
        hover_button(nav, "◀", self._prev_day, padx=9, pady=4).pack(side="left", padx=2)
        self.date_label = tk.Label(nav, text="", bg=P["bg"], fg=P["primary"],
                                   font=("Microsoft YaHei UI", 15, "bold"),
                                   padx=8, cursor="hand2")
        self.date_label.pack(side="left", padx=2)
        self.date_label.bind("<Button-1>", lambda e: self._open_calendar())
        hover_button(nav, "▶", self._next_day, padx=9, pady=4).pack(side="left", padx=2)
        hover_button(nav, "回到今天", self._go_today, padx=10, pady=4).pack(side="left", padx=(8, 0))

        actions = tk.Frame(top, bg=P["bg"])
        actions.pack(side="right")
        ttk.Button(actions, text="＋ 制定计划", style="Accent.TButton",
                   command=self._open_plan).pack(side="left")
        ttk.Button(actions, text="复制昨日", command=self._copy_yesterday).pack(side="left", padx=6)
        self.btn_checkin = ttk.Button(actions, text="✓ 打卡", style="Success.TButton",
                                      command=self._checkin_selected)
        self.btn_checkin.pack(side="left", padx=6)
        ttk.Button(actions, text="生成打卡报告", style="Accent.TButton",
                   command=self._open_export_dialog).pack(side="left", padx=6)

        # 总体进度（环形 + 统计 + 倒计时）
        ov = tk.Frame(self, bg=P["bg"], padx=18)
        ov.pack(fill="x")
        ov.columnconfigure(0, weight=1, uniform="home")
        ov.columnconfigure(1, weight=1, uniform="home")
        ov.columnconfigure(2, weight=1, uniform="home")
        ov.rowconfigure(0, weight=1, minsize=230)
        box = card(ov, padx=18, pady=18)
        box.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        box.columnconfigure(0, weight=1)
        inner = tk.Frame(box, bg=P["surface"])
        inner.grid(row=0, column=0, sticky="ew")
        self.overall_ring = ProgressRing(inner, size=88, thickness=9, color=P["accent"])
        self.overall_ring.pack(side="left", padx=(0, 16))
        right = tk.Frame(inner, bg=P["surface"])
        right.pack(side="left", fill="x", expand=True)
        tk.Label(right, text="总体进度", bg=P["surface"], fg=P["text"],
                 font=("Microsoft YaHei UI", 15, "bold")).pack(anchor="w")
        stats_row = tk.Frame(right, bg=P["surface"])
        stats_row.pack(fill="x", pady=(10, 0))

        def _stat(parent, caption, color):
            f = tk.Frame(parent, bg=P["surface"])
            f.pack(side="left", expand=True, fill="x")
            num = tk.Label(f, text="0", bg=P["surface"], fg=color,
                           font=("Microsoft YaHei UI", 17, "bold"))
            num.pack(anchor="center")
            tk.Label(f, text=caption, bg=P["surface"], fg=P["muted"],
                     font=("Microsoft YaHei UI", 11)).pack(anchor="w", pady=(2, 0))
            return num

        self.overall_done_num = _stat(stats_row, "已完成计划", P["accent"])
        self.overall_total_num = _stat(stats_row, "完成计划总数", P["primary"])
        self.overall_rate_num = _stat(stats_row, "完成率", P["warning"])
        self.streak_num = _stat(stats_row, "连续打卡(天)", P["accent"])
        self.overall_progress = ttk.Progressbar(box, maximum=100)
        self.overall_progress.grid(row=1, column=0, sticky="ew", pady=(12, 0))

        # 倒计时面板（独立卡片行，避免与统计横向拥挤；双击打开设置）
        cd_box = card(ov, padx=18, pady=18)
        cd_box.grid(row=0, column=1, sticky="nsew", padx=5)
        cd = tk.Frame(cd_box, bg=P["surface"], height=176, cursor="hand2")
        cd.pack(fill="both", expand=True)
        cd.pack_propagate(False)
        # 主行：标题（左）与天数（右），与左侧环中心同一水平线
        main = tk.Frame(cd, bg=P["surface"])
        main.place(relx=0.5, rely=0.5, anchor="center")
        self.countdown_ring = ProgressRing(main, size=76, thickness=8, color=P["primary"])
        self.countdown_ring.pack(side="left", padx=(0, 8))
        text_col = tk.Frame(main, bg=P["surface"])
        text_col.pack(side="left", fill="both", expand=True)
        self.countdown_sub = tk.Label(text_col, text="双击设置目标日", bg=P["surface"],
                                      fg=P["primary"], font=("Microsoft YaHei UI", 36, "bold"))
        self.countdown_sub.pack(anchor="center")
        num_row = tk.Frame(text_col, bg=P["surface"])
        num_row.pack(pady=(2, 0))
        self.countdown_days = tk.Label(num_row, text="--", bg=P["surface"], fg=P["primary"],
                                       font=("Microsoft YaHei UI", 30, "bold"))
        self.countdown_days.pack(side="left")
        self.countdown_hours = tk.Label(num_row, text="--", bg=P["surface"], fg=P["primary_dark"],
                                        font=("Microsoft YaHei UI", 20, "bold"))
        self.countdown_hours.pack(side="left", padx=(8, 0))
        tk.Label(num_row, text="小时", bg=P["surface"], fg=P["muted"],
                 font=("Microsoft YaHei UI", 15)).pack(side="left", pady=(5, 0), padx=(0, 8))
        self.countdown_mins = tk.Label(num_row, text="--", bg=P["surface"], fg=P["primary_dark"],
                                       font=("Microsoft YaHei UI", 20, "bold"))
        self.countdown_mins.pack(side="left", padx=(8, 0))
        tk.Label(num_row, text="分", bg=P["surface"], fg=P["muted"],
                 font=("Microsoft YaHei UI", 15)).pack(side="left", pady=(5, 0))
        # 说明：紧贴主行正上方居中
        tk.Label(cd, text="目标倒计时", bg=P["surface"], fg=P["muted"],
                 font=("Microsoft YaHei UI", 10)).place(in_=main, relx=0.5, rely=0.0,
                                                       y=-6, anchor="s")
        # 日期 + 提示：位于主行正下方居中
        bot = tk.Frame(cd, bg=P["surface"])
        bot.place(in_=main, relx=0.5, rely=1.0, y=4, anchor="n")
        self.countdown_date = tk.Label(bot, text="", bg=P["surface"], fg=P["faint"],
                                       font=("Microsoft YaHei UI", 11))
        self.countdown_date.pack(side="left")
        tk.Label(bot, text="  ·  双击修改", bg=P["surface"], fg=P["faint"],
                 font=("Microsoft YaHei UI", 11)).pack(side="left")
        self._bind_double_click(cd, lambda e: self._open_countdown_dialog())
        self._pulse_after = None
        self._pulse_step = 0
        self._tick_after = None

        # 最近 7 天完成率迷你柱状图 + 激励语
        self.insight_box = card(ov, padx=18, pady=18)
        self.insight_box.grid(row=0, column=2, sticky="nsew", padx=(5, 0))
        self.insight_box.columnconfigure(0, weight=1)
        self.insight_box.rowconfigure(1, weight=1)
        tk.Label(self.insight_box, text="最近 7 天完成率", bg=P["surface"], fg=P["text"],
                 font=("Microsoft YaHei UI", 13, "bold")).grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.week_chart = tk.Canvas(self.insight_box, width=280, height=100, bg=P["surface"],
                                    highlightthickness=0)
        self.week_chart.grid(row=1, column=0, sticky="nsew")
        self.insight_box.bind("<Configure>", self._on_insight_resize)










        # 今日列表卡片
        body = tk.Frame(self, bg=P["bg"], padx=18, pady=14)
        body.pack(fill="both", expand=True)
        list_card = card(body, padx=14, pady=12)
        list_card.pack(fill="both", expand=True)
        prog_row = tk.Frame(list_card, bg=P["surface"])
        prog_row.pack(fill="x", pady=(0, 8))
        prog_row.columnconfigure(1, weight=0)
        prog_row.columnconfigure(3, weight=1)
        self.today_ring = ProgressRing(prog_row, size=58, thickness=7, color=P["primary"])
        self.today_ring.grid(row=0, column=0, padx=(0, 12))
        mid = tk.Frame(prog_row, bg=P["surface"])
        mid.grid(row=0, column=1, sticky="w", padx=(0, 40))
        tk.Label(mid, text="今日进度", bg=P["surface"], fg=P["text"],
                 font=("Microsoft YaHei UI", 15, "bold")).pack(anchor="w")
        self.progress_label = tk.Label(mid, text="0 / 0（0%）", bg=P["surface"], fg=P["muted"],
                                       font=("Microsoft YaHei UI", 13))
        self.progress_label.pack(anchor="w", pady=(3, 0))
        self.qualify_label = tk.Label(mid, text="", bg=P["surface"], fg=P["accent"],
                                      font=("Microsoft YaHei UI", 11, "bold"),
                                      wraplength=320, justify="left")
        self.qualify_label.pack(anchor="w", pady=(1, 0))
        self.progress = ttk.Progressbar(prog_row, length=510)
        self.progress.grid(row=0, column=2, padx=(0, 12))

        # 打卡计时控件（独立一行右对齐，避免横向挤占被窗口裁剪）
        timer_row = tk.Frame(list_card, bg=P["surface"])
        self.quote_label = tk.Label(prog_row, text="", bg=P["surface"], fg=P["accent"],
                                    font=("Microsoft YaHei UI", 12, "bold"),
                                    wraplength=320, justify="left")
        self.quote_label.grid(row=0, column=3, sticky="e", padx=(0, 16))
        timer_row.pack(fill="x", pady=(0, 8))
        self.btn_timer_stop = hover_button(timer_row, "⏹ 结束", self._timer_stop)
        self.btn_timer_stop.pack(side="right", padx=2)
        self.btn_timer_stop.configure(state="disabled")
        self.btn_timer_pause = hover_button(timer_row, "⏸ 暂停", self._timer_pause)
        self.btn_timer_pause.pack(side="right", padx=2)
        self.btn_timer_pause.configure(state="disabled")
        self.btn_timer_start = hover_button(timer_row, "▶ 开始", self._timer_start)
        self.btn_timer_start.pack(side="right", padx=2)
        self.timer_label = tk.Label(timer_row, text="⏱ 00:00:00", bg=P["surface"], fg=P["primary"],
                                    font=("Microsoft YaHei UI", 17, "bold"))
        self.timer_label.pack(side="right", padx=(0, 10))
        tk.Label(timer_row, text="打卡计时", bg=P["surface"], fg=P["muted"],
                 font=("Microsoft YaHei UI", 11)).pack(side="right", padx=(0, 6))
        self.day_total_label = tk.Label(timer_row, text="今日累计 00:00:00", bg=P["surface"],
                                        fg=P["muted"], font=("Microsoft YaHei UI", 11))
        self.day_total_label.pack(side="right", padx=(0, 14))
        self._timer_item_id = None
        self._timer_base = 0
        self._timer_started = None
        self._timer_after = None
        self._rest_reminded = False
        self._focus_secs = 0

        tree_wrap = tk.Frame(list_card, bg=P["surface"])
        tree_wrap.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(tree_wrap, columns=self._COLUMNS, show="headings", selectmode="browse")
        self.tree.heading("status", text="状态")
        self.tree.heading("topic", text="打卡项（知识点）")
        self.tree.heading("goal", text="任务目标")
        self.tree.heading("remind", text="提醒时间")
        self.tree.heading("timer", text="计时")
        self.tree.heading("checked", text="打卡时间")
        self.tree.column("status", width=100, anchor="center", stretch=False)
        self.tree.column("topic", width=280, anchor="w")
        self.tree.column("goal", width=330, anchor="w")
        self.tree.column("remind", width=90, anchor="center", stretch=False)
        self.tree.column("timer", width=90, anchor="center", stretch=False)
        self.tree.column("checked", width=140, anchor="center", stretch=False)
        self.tree.tag_configure("done_even", foreground=P["done"], background=P["input"])
        self.tree.tag_configure("done_odd", foreground=P["done"], background=P["stripe"])
        self.tree.tag_configure("todo_even", foreground=P["text"], background=P["input"])
        self.tree.tag_configure("todo_odd", foreground=P["text"], background=P["stripe"])
        vsb = ttk.Scrollbar(tree_wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda e: self._checkin_selected())
        self.tree.bind("<Button-3>", self._on_item_right_click)

        # 底部提示
        bar = tk.Frame(self, bg=P["bar"], padx=18, pady=6)
        bar.pack(fill="x", side="bottom")
        self.hint_label = tk.Label(bar, text="", bg=P["bar"], fg=P["muted"],
                                   font=("Microsoft YaHei UI", 11))
        self.hint_label.pack(side="left")

    def refresh(self):
        day = self.current_date.isoformat()
        self.page_title.configure(text=self._relative_day(self.current_date))
        self.date_label.configure(text="{}  星期{}".format(day, "一二三四五六日"[self.current_date.weekday()]))
        self.tree.delete(*self.tree.get_children())
        plan = self.db.get_plan(day)
        items = self.db.get_plan_items(plan["id"]) if plan else []
        self.plan_title_label.configure(text=(plan or {}).get("title") or "")
        done = sum(1 for it in items if it["done"])
        total = len(items)
        rate = (done / total * 100) if total else 0
        self.progress.configure(maximum=max(total, 1))
        smooth_progress(self.progress, done)
        self.progress_label.configure(text="{} / {}（{:.0f}%）".format(done, total, rate))
        self.today_ring.set(rate / 100 if total else 0)
        # 80% 合格线
        if total:
            if done * 5 >= total * 4:  # 完成率 >= 80%
                self.qualify_label.configure(text="已达合格线（80%）✓", fg=PALETTE["accent"])
            else:
                need = max(0, (total * 4 + 4) // 5 - done)
                self.qualify_label.configure(
                    text="距合格线还差 {} 项 · 完成 80% 就算合格，不补账".format(need),
                    fg=PALETTE["muted"])
        else:
            self.qualify_label.configure(text="")
        running_ids = {self._timer_item_id} if self._timer_item_id is not None else set()
        item_ids = {it["id"] for it in items}
        for idx, it in enumerate(items):
            stripe = "even" if idx % 2 == 0 else "odd"
            tag = ("done_" if it["done"] else "todo_") + stripe
            status = "✓ 已完成" if it["done"] else "○ 未完成"
            remind = it["reminder_time"] or "—"
            checked = (it["checked_at"] or "")[11:16] or "—"
            if it["id"] in running_ids:
                timer_val = fmt_clock(self._timer_current())
            else:
                timer_val = fmt_clock(int(it.get("elapsed_seconds") or 0)) or "00:00"
            task_tag = "〔辅〕" if it.get("task_type") == "aux" else "〔主〕"
            goal = to_plain(it.get("note") or "").strip() or "—"
            self.tree.insert("", "end", iid=str(it["id"]),
                             values=(status, task_tag + it["topic_path"], goal, remind, timer_val, checked),
                             tags=(tag,))
        overall = self.db.overall_stats()
        count_up(self.overall_total_num, overall["total"])
        count_up(self.overall_done_num, overall["done"])
        count_up(self.overall_rate_num, overall["rate"], suffix="%")
        streak = self.db.streak_stats()
        count_up(self.streak_num, streak["current"])
        self.overall_progress.configure(maximum=100)
        smooth_progress(self.overall_progress, overall["rate"])
        self.overall_ring.set(overall["rate"] / 100 if overall["total"] else 0)
        # 计时器仍在当前列表中则保持运行，否则结束并保存
        if self._timer_item_id is not None:
            if self._timer_item_id not in item_ids:
                self._timer_stop()
            else:
                self.timer_label.configure(text="⏱ " + fmt_clock(self._timer_current()))
        # 今日累计学习时长（含正在运行的计时）
        day_total = sum(int(it.get("elapsed_seconds") or 0) for it in items)
        if self._timer_item_id is not None and self._timer_started is not None \
                and self._timer_item_id in item_ids:
            day_total += max(0, int(self._timer_current() - self._timer_base))
        self.day_total_label.configure(text="今日累计 " + fmt_clock(day_total))
        self._update_countdown()
        self._update_week_chart()
        self._update_quote()
        if not plan:
            self.hint_label.configure(text="当天还没有计划，点击左上角「＋ 制定计划」创建。")
            self.btn_checkin.configure(state="disabled")
        elif not items:
            self.hint_label.configure(text="该计划还没有打卡项，点击「＋ 制定计划」添加。")
            self.btn_checkin.configure(state="disabled")
        else:
            self.hint_label.configure(text="双击列表中的打卡项，或选中后点击「✓ 打卡」；选中后可用右侧计时器记录学习时长。")
            self.btn_checkin.configure(state="normal")


    # ---------- 最近 7 天迷你柱状图 / 激励语 ----------
    def _on_insight_resize(self, event=None):
        try:
            w = max(int(self.insight_box.winfo_width()) - 36, 280)
            self.week_chart.configure(width=w)
            self.quote_label.configure(wraplength=w)
        except tk.TclError:
            pass

    def _update_week_chart(self):
        today = date.today()
        start = today - timedelta(days=6)
        daily = self.db.daily_completion(start.isoformat(), today.isoformat())
        self.week_chart.delete("all")
        self.week_chart.update_idletasks()
        w = max(int(self.week_chart.winfo_width()), 280)
        h = int(self.week_chart["height"]) or 100
        n = 7
        gap = 10
        bar_w = max((w - gap * (n + 1)) // n, 8)
        top_pad = 16
        bottom_pad = 2
        date_h = 14
        bar_base = h - bottom_pad - date_h
        for i in range(n):
            d = start + timedelta(days=i)
            info = daily.get(d.isoformat(), {"total": 0, "done": 0})
            rate = (info["done"] / info["total"] * 100) if info["total"] else 0
            x0 = gap + i * (bar_w + gap)
            bh = max(int((bar_base - top_pad) * rate / 100), 2 if rate > 0 else 0)
            y0 = bar_base
            color = PALETTE["accent"] if rate >= 80 else (PALETTE["primary"] if rate > 0 else PALETTE["border"])
            self.week_chart.create_rectangle(x0, y0 - bh, x0 + bar_w, y0, fill=color, outline="")
            self.week_chart.create_text(
                x0 + bar_w / 2, h - bottom_pad - date_h / 2,
                text=str(d.day), fill=PALETTE["muted"], font=("Microsoft YaHei UI", 9),
            )
            if rate > 0:
                self.week_chart.create_text(
                    x0 + bar_w / 2, y0 - bh - 2, text="{:.0f}".format(rate),
                    fill=PALETTE["text"], font=("Microsoft YaHei UI", 9), anchor="s",
                )

    def _update_quote(self):
        try:
            from habit_checkin.services.motivation import random_quote
            self.quote_label.configure(text="💡 " + random_quote())
        except Exception:
            self.quote_label.configure(text="")

    # ---------- 导出格式 ----------
    def _open_export_dialog(self):
        from habit_checkin.ui.export_dialog import ExportFormatDialog
        ExportFormatDialog(self.master, self._export_with_format)

    def _export_with_format(self, fmt):
        self._export_range_fmt(fmt)

    # ---------- 倒计时 ----------
    def _bind_double_click(self, widget, handler):
        widget.bind("<Double-Button-1>", handler)
        for child in widget.winfo_children():
            self._bind_double_click(child, handler)

    def _open_countdown_dialog(self):
        from habit_checkin.ui.countdown_dialog import CountdownDialog
        dlg = CountdownDialog(self.master, self.db)
        self.wait_window(dlg)
        self._update_countdown()

    def _update_countdown(self):
        day_str = self.db.get_setting("countdown_date", "") or ""
        if not day_str:
            self.countdown_days.configure(text="--")
            self.countdown_hours.configure(text="--")
            self.countdown_mins.configure(text="--")
            self.countdown_sub.configure(text="双击设置目标日")
            self.countdown_date.configure(text="")
            self._cancel_pulse()
            self._schedule_tick()
            return
        try:
            target_date = date.fromisoformat(day_str)
        except ValueError:
            self.countdown_days.configure(text="--")
            self.countdown_hours.configure(text="--")
            self.countdown_mins.configure(text="--")
            self.countdown_sub.configure(text="双击设置目标日")
            self.countdown_date.configure(text="")
            self._cancel_pulse()
            self._schedule_tick()
            return
        # 目标视为当天 23:59:59，实时计算 天/小时/分
        target_dt = datetime.combine(target_date, datetime.max.time())
        delta = target_dt - datetime.now()
        if delta.total_seconds() <= 0:
            days, hours, mins, expired = 0, 0, 0, True
        else:
            days, hours, mins = delta.days, delta.seconds // 3600, (delta.seconds % 3600) // 60
            expired = False
        # 倒计时进度环：从备考开始日到目标日的已过时间占比
        try:
            start_str = self.db.get_setting("plan_start_date", "")
            start_date = date.fromisoformat(start_str) if start_str else date.today()
        except ValueError:
            start_date = date.today()
        total_days = max((target_date - start_date).days, 1)
        elapsed_days = max((date.today() - start_date).days, 0)
        self.countdown_ring.set(min(1.0, elapsed_days / total_days))
        self.countdown_days.configure(text="{}天".format(days))
        self.countdown_hours.configure(text=str(hours))
        self.countdown_mins.configure(text=str(mins))
        title = self.db.get_setting("countdown_title", "") or ""
        if title and len(title) > 6:
            title = title[:6] + "…"
        self.countdown_sub.configure(text=title if title else "距离目标日")
        self.countdown_date.configure(text=day_str + ("（已到期）" if expired else ""))
        self._start_pulse()
        self._schedule_tick()

    def _schedule_tick(self):
        """每 30 秒刷新一次小时/分钟倒计时。"""
        if not self.winfo_viewable():
            return
        if getattr(self, "_tick_after", None) is None:
            self._tick_after = self.after(30000, self._countdown_tick)

    def _countdown_tick(self):
        self._tick_after = None
        try:
            if not self.winfo_exists() or not self.winfo_viewable():
                return
        except tk.TclError:
            return
        self._update_countdown()

    def _start_pulse(self):
        if not self.winfo_viewable():
            return
        if self._pulse_after is not None:
            return
        self._pulse_step = 0
        self._countdown_pulse()

    def _countdown_pulse(self):
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        if not self.winfo_viewable():
            self._pulse_after = None
            return
        step = self._pulse_step
        t = abs((step % 40) - 20) / 20.0
        self.countdown_days.configure(
            fg=lerp_color(PALETTE["primary"], PALETTE["accent"], t))
        self._pulse_step = step + 1
        self._pulse_after = self.after(80, self._countdown_pulse)

    def _cancel_pulse(self):
        if self._pulse_after is not None:
            try:
                self.after_cancel(self._pulse_after)
            except tk.TclError:
                pass
            self._pulse_after = None
        try:
            self.countdown_days.configure(fg=PALETTE["primary"])
        except tk.TclError:
            pass

    # ---------- 打卡计时 ----------
    def _timer_selected_item(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("打卡计时", "请先在列表中选中一个打卡项。", parent=self.master)
            return None
        return int(sel[0])

    def _timer_current(self):
        if self._timer_started is not None:
            return self._timer_base + int(time.monotonic() - self._timer_started)
        return self._timer_base

    def _timer_start(self):
        item_id = self._timer_selected_item()
        if item_id is None:
            return
        if self._timer_item_id == item_id and self._timer_started is not None:
            return
        if self._timer_item_id is not None:
            self._persist_timer()
        self._timer_item_id = item_id
        self._timer_base = self.db.get_elapsed(item_id)
        self._timer_started = time.monotonic()
        self._rest_reminded = False
        try:
            self._focus_secs = max(0, int(float(self.db.get_setting("focus_minutes", "45") or 0))) * 60
        except (ValueError, TypeError):
            self._focus_secs = 45 * 60
        self._update_timer_buttons()
        self._timer_tick()
        ui_toast(self.master, "开始计时：{}".format(self._timer_topic_name(item_id)))

    def _timer_topic_name(self, item_id):
        it = self.db.get_plan_item(item_id)
        return it["topic_path"] if it else "打卡项"

    def _timer_pause(self):
        if self._timer_item_id is None or self._timer_started is None:
            return
        self._persist_timer()
        self._timer_started = None
        if self._timer_after is not None:
            try:
                self.after_cancel(self._timer_after)
            except tk.TclError:
                pass
            self._timer_after = None
        self._update_timer_buttons()
        self.timer_label.configure(text="⏱ " + fmt_clock(self._timer_current()))
        if self.tree.exists(str(self._timer_item_id)):
            self.tree.set(str(self._timer_item_id), "timer", fmt_clock(self._timer_current()))
        ui_toast(self.master, "已暂停计时")

    def _timer_stop(self):
        if self._timer_item_id is None:
            return
        self._persist_timer()
        item_id = self._timer_item_id
        self._timer_item_id = None
        self._timer_base = 0
        self._timer_started = None
        if self._timer_after is not None:
            try:
                self.after_cancel(self._timer_after)
            except tk.TclError:
                pass
            self._timer_after = None
        self._update_timer_buttons()
        self.timer_label.configure(text="⏱ 00:00:00")
        self.refresh()
        ui_toast(self.master, "计时已保存")

    def _persist_timer(self):
        if self._timer_item_id is not None:
            secs = self._timer_current()
            self.db.set_elapsed(self._timer_item_id, secs)
            self._timer_base = secs

    def _timer_tick(self):
        if self._timer_item_id is None or self._timer_started is None:
            return
        secs = self._timer_current()
        if self._focus_secs and not self._rest_reminded and secs >= self._focus_secs:
            self._rest_reminded = True
            ui_toast(self.master, "已专注 {} 分钟，建议起身休息 5 分钟～".format(self._focus_secs // 60))
        self.timer_label.configure(text="⏱ " + fmt_clock(secs))
        if self.tree.exists(str(self._timer_item_id)):
            self.tree.set(str(self._timer_item_id), "timer", fmt_clock(secs))
        self._timer_after = self.after(1000, self._timer_tick)

    def _update_timer_buttons(self):
        running = self._timer_started is not None
        has = self._timer_item_id is not None
        self.btn_timer_start.configure(state="normal")
        self.btn_timer_pause.configure(state="normal" if running else "disabled")
        self.btn_timer_stop.configure(state="normal" if has else "disabled")

    def _prev_day(self):
        self.current_date -= timedelta(days=1)
        self.refresh()

    def _next_day(self):
        self.current_date += timedelta(days=1)
        self.refresh()

    def _go_today(self):
        self.current_date = date.today()
        self.refresh()

    def _relative_day(self, d):
        """把日期转成相对今天的人性化描述。"""
        delta = (d - date.today()).days
        if delta == 0:
            return "今日"
        if delta == -1:
            return "昨天"
        if delta == -2:
            return "前天"
        if delta == 1:
            return "明天"
        if delta == 2:
            return "后天"
        if delta < 0:
            return "{}天前".format(-delta)
        return "{}天后".format(delta)

    def _open_calendar(self):
        from habit_checkin.ui.calendar import CalendarPopup
        CalendarPopup(self.date_label, initial_date=self.current_date, on_select=self._on_calendar_pick)

    def _on_calendar_pick(self, day_str):
        try:
            self.current_date = date.fromisoformat(day_str)
        except ValueError:
            return
        self.refresh()

    # ---------- 操作 ----------
    def _open_plan(self):
        from habit_checkin.ui.plan_dialog import PlanDialog
        dlg = PlanDialog(self.master, self.db, self.current_date.isoformat())
        self.wait_window(dlg)
        self.refresh()

    def _copy_yesterday(self):
        src = (self.current_date - timedelta(days=1)).isoformat()
        dst = self.current_date.isoformat()
        if not self.db.get_plan(src):
            messagebox.showinfo("复制昨日计划", "前一天没有计划，无法复制。", parent=self.master)
            return
        if self.db.get_plan(dst):
            ok = messagebox.askyesno(
                "复制昨日计划",
                "当天已有计划，复制会覆盖现有计划（含已有打卡内容）。\n是否继续？",
                parent=self.master,
            )
            if not ok:
                return
        n = self.db.copy_plan(src, dst, replace_existing=True)
        ui_toast(self.master, "已复制 {} 项到 {}".format(n, dst))
        self.refresh()

    def _checkin_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("打卡", "请先选择一个打卡项。", parent=self.master)
            return
        item = self.db.get_plan_item(int(sel[0]))
        if not item:
            return
        dlg = CheckinDialog(self.master, self.db, item, self.current_date.isoformat())
        self.wait_window(dlg)
        self.refresh()

    # ---------- 已完成项右键清理 ----------
    def _on_item_right_click(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        item = self.db.get_plan_item(int(iid))
        if not item or not item["done"]:
            return
        self.tree.selection_set(iid)
        self.tree.focus(iid)
        item_id = int(iid)
        menu = ThemeMenu(self)
        self._menu = menu
        menu.show(event.x_root, event.y_root, [
            ("清除计时数据", lambda: self._clear_timing(item_id)),
            ("清除打卡时间数据", lambda: self._clear_checkin_time(item_id)),
            ("---",),
            ("清除打卡数据（复原为未打卡）", lambda: self._reset_checkin(item_id), True),
        ])

    def _clear_timing(self, item_id):
        ok = messagebox.askyesno(
            "清除计时数据",
            "确定清除该打卡项的计时数据吗？计时将归零。\n"
            "该操作只影响计时时长，完成状态、打卡时间、文字总结、图片和题库收录均保留。\n"
            "操作不可撤销，建议先在「设置 → 通用设置」中备份数据。",
            parent=self.master,
        )
        if not ok:
            return
        if self._timer_item_id == item_id:
            self._timer_stop()
        self.db.set_elapsed(item_id, 0)
        self.refresh()
        ui_toast(self.master, "已清除计时数据")

    def _clear_checkin_time(self, item_id):
        ok = messagebox.askyesno(
            "清除打卡时间数据",
            "确定清除该打卡项的打卡时间吗？完成状态会保留，\n"
            "文字总结、图片、计时和题库收录均不受影响。\n"
            "操作不可撤销，建议先在「设置 → 通用设置」中备份数据。",
            parent=self.master,
        )
        if not ok:
            return
        self.db.clear_checked_at(item_id)
        self.refresh()
        ui_toast(self.master, "已清除打卡时间")

    def _reset_checkin(self, item_id):
        ok = messagebox.askyesno(
            "清除打卡数据",
            "确定清除该打卡项的全部打卡数据吗？\n"
            "完成状态、打卡时间、文字总结、图片和计时都会复原为未打卡状态。\n"
            "题库中已收录的题目不会被删除，但来源关联会失效。\n"
            "操作不可撤销，建议先在「设置 → 通用设置」中备份数据。",
            parent=self.master,
        )
        if not ok:
            return
        if self._timer_item_id == item_id:
            self._timer_stop()
        self.db.reset_plan_item(item_id)
        self.refresh()
        ui_toast(self.master, "已复原为未打卡状态")

    def _export_range_fmt(self, fmt):
        day = self.current_date.isoformat()
        items = self.db.query_items(day, day)
        if not items:
            messagebox.showinfo("导出", "当天没有可导出的打卡项。", parent=self.master)
            return
        if fmt == "pdf":
            from habit_checkin.services.export_pdf import default_filename_pdf, export_pdf
            fn = default_filename_pdf(day, day)
            filetypes = [("PDF 文档", "*.pdf")]
            ext = ".pdf"
        elif fmt == "png":
            from habit_checkin.services.export_image import default_filename_png, export_image
            fn = default_filename_png(day, day)
            filetypes = [("PNG 图片", "*.png")]
            ext = ".png"
        else:
            from habit_checkin.services.export_docx import default_filename, export_docx
            fn = default_filename(day, day)
            filetypes = [("Word 文档", "*.docx")]
            ext = ".docx"
        path = filedialog.asksaveasfilename(
            parent=self.master, defaultextension=ext, initialfile=fn,
            filetypes=filetypes, title="导出今日打卡情况",
        )
        if not path:
            return
        try:
            if fmt == "pdf":
                stats = export_pdf(self.db, day, day, path)
            elif fmt == "png":
                stats = export_image(self.db, day, day, path)
            else:
                stats = export_docx(self.db, day, day, path)
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc), parent=self.master)
            return
        ui_toast(self.master, "已导出：{}（题目 {} 题）".format(path, stats.get("questions", 0)))
