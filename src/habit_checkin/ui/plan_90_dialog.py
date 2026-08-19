# -*- coding: utf-8 -*-
"""一键铺排 90 天计划对话框：选择开始日期，按每周执行模板批量生成每日任务。"""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from datetime import date, timedelta
from tkinter import messagebox, ttk

from habit_checkin.services.study_plan import generate_90day_plan, get_plan_config
from habit_checkin.ui.animate import fade_in
from habit_checkin.ui.calendar import attach_calendar_on_click
from habit_checkin.ui.common import center_window, setup_styles
from habit_checkin.ui.theme import PALETTE, dialog_header


class Plan90Dialog(tk.Toplevel):
    def __init__(self, master, db, on_done=None):
        super().__init__(master)
        self.db = db
        self.on_done = on_done
        self._cancel = False
        self.config = get_plan_config(db)
        self.total_days = self.config["total_days"]
        start = self._default_start()
        self.title("一键铺排计划")
        self.geometry("620x560")
        self.resizable(False, False)
        self.transient(master)
        setup_styles(self)
        self.configure(bg=PALETTE["bg"])
        dialog_header(self, "一键铺排计划", "按计划配置批量生成每日任务")

        P = PALETTE
        body = tk.Frame(self, bg=P["bg"], padx=20, pady=16)
        body.pack(fill="both", expand=True)

        row = tk.Frame(body, bg=P["bg"])
        row.pack(fill="x")
        tk.Label(row, text="开始日期（第 1 天）：", bg=P["bg"]).pack(side="left")
        self.date_entry = ttk.Entry(row, width=12)
        self.date_entry.insert(0, start)
        self.date_entry.pack(side="left", padx=(0, 6))
        attach_calendar_on_click(self.date_entry, lambda ds: self._set_date(ds))
        ttk.Button(row, text="今天", command=lambda: self._set_date(date.today().isoformat())).pack(side="left")

        tk.Label(body, text="", bg=P["bg"]).pack()
        self.range_label = tk.Label(body, text="", bg=P["bg"], fg=P["primary_dark"],
                                    font=("Microsoft YaHei UI", 13, "bold"))
        self.range_label.pack(anchor="w")

        desc = tk.Label(
            body,
            text="每天自动生成：3 个主任务（行测模块 A / 模块 B / 申论·大作文）+ "
                 "固定辅助任务（政治积累、错题复盘/重点整理、新闻联播、创作），并带作息提醒时间；\n"
                 "周一 / 三 / 五额外插入「数量关系插空」；周日申论时段自动设为「大作文学习与写作」。\n"
                 "生成的计划可在「今日」页按天查看、修改或删除。",
            bg=P["bg"], fg=P["muted"], font=("Microsoft YaHei UI", 11), justify="left",
            wraplength=560,
        )
        desc.pack(fill="x", pady=(8, 4))

        self.overwrite_var = tk.BooleanVar(value=False)
        cb = ttk.Checkbutton(body, text="覆盖已有计划（勾选后：已存在的日期会先删除再重建，可能丢失该日打卡内容）",
                             variable=self.overwrite_var)
        cb.pack(anchor="w", pady=(4, 0))
        ttk.Button(body, text="计划设置", command=self._open_settings).pack(anchor="w", pady=(4, 0))

        self.progress = ttk.Progressbar(body, maximum=self.total_days)
        self.progress.pack(fill="x", pady=(12, 0))
        self.status_label = tk.Label(body, text="", bg=P["bg"], fg=P["muted"],
                                     font=("Microsoft YaHei UI", 11))
        self.status_label.pack(anchor="w", pady=(4, 0))

        btns = tk.Frame(body, bg=P["bg"])
        btns.pack(fill="x", pady=(14, 0))
        self.btn_cancel = ttk.Button(btns, text="取消", command=self._close)
        self.btn_cancel.pack(side="right")
        self.btn_start = ttk.Button(btns, text="开始铺排", style="Accent.TButton",
                                    command=self._start)
        self.btn_start.pack(side="right", padx=8)

        self._set_date(start)
        center_window(self)
        fade_in(self)
        self.grab_set()

    def _open_settings(self):
        from habit_checkin.ui.plan_settings_dialog import PlanSettingsDialog
        PlanSettingsDialog(self.master, self.db)
        self.config = get_plan_config(self.db)
        self.total_days = self.config["total_days"]
        self.progress.configure(maximum=self.total_days)
        self._update_range()

    def _default_start(self):
        saved = self.db.get_setting("plan_start_date", "")
        try:
            date.fromisoformat(saved)
            return saved
        except (ValueError, TypeError):
            from habit_checkin.services.study_plan import DEFAULT_START
            return DEFAULT_START.isoformat()

    def _set_date(self, ds):
        self.date_entry.delete(0, "end")
        self.date_entry.insert(0, ds)
        self._update_range()

    def _update_range(self):
        try:
            d = date.fromisoformat(self.date_entry.get().strip())
        except ValueError:
            self.range_label.configure(text="日期格式不正确")
            return
        end = d + timedelta(days=self.total_days - 1)
        self.range_label.configure(text="第 1 天 {} → 第 {} 天 {}（共 {} 天）".format(
            d.isoformat(), self.total_days, end.isoformat(), self.total_days))

    def _start(self):
        try:
            d = date.fromisoformat(self.date_entry.get().strip())
        except ValueError:
            messagebox.showwarning("一键铺排", "开始日期格式不正确（YYYY-MM-DD）。", parent=self)
            return
        self._cancel = False
        self.btn_start.configure(state="disabled")
        overwrite = self.overwrite_var.get()
        self._queue = queue.Queue()

        def progress_cb(day, note=None):
            # 子线程只往队列投递，不直接操作 UI（线程安全）
            self._queue.put(("progress", day, note))

        def work():
            # 子线程必须使用独立的 SQLite 连接（主线程连接不可跨线程使用）
            from habit_checkin.db import Database
            worker_db = None
            try:
                worker_db = Database(self.db.db_path, self.db.images_dir, self.db.base_dir)
                stats = generate_90day_plan(
                    worker_db, d, overwrite=overwrite,
                    progress_cb=progress_cb,
                    cancel_cb=lambda: self._cancel,
                    delay=0.02,  # 每铺排一天略作停顿，便于进度条实时推进
                    config=self.config,
                )
                self._queue.put(("done", stats, None))
            except Exception as exc:  # noqa: BLE001
                self._queue.put(("fail", str(exc), None))
            finally:
                if worker_db is not None:
                    try:
                        worker_db.close()
                    except Exception:  # noqa: BLE001
                        pass

        threading.Thread(target=work, daemon=True).start()
        self.after(50, self._poll_queue)

    def _poll_queue(self):
        """主线程定时从队列取进度/完成/失败事件，安全地更新 UI。"""
        try:
            while True:
                kind, a, b = self._queue.get_nowait()
                if kind == "progress":
                    self._on_progress(a, b)
                elif kind == "done":
                    self._done(a)
                    return
                elif kind == "fail":
                    self._fail(a)
                    return
        except queue.Empty:
            pass
        try:
            if self.winfo_exists():
                self.after(50, self._poll_queue)
        except tk.TclError:
            pass

    def _on_progress(self, day, note):
        self.progress.configure(value=day)
        self.status_label.configure(
            text=("正在铺排 第 {} / {} 天".format(day, self.total_days)) + ((" · " + note) if note else "")
        )

    def _done(self, stats):
        self.progress.configure(value=self.total_days)
        self.status_label.configure(
            text="铺排完成：共 {} 天 · {} 项任务{}".format(
                stats["created_days"], stats["created_items"],
                ("（跳过 {} 天）".format(stats["skipped_days"]) if stats["skipped_days"] else ""),
            )
        )
        msg = "已铺排 {} 天计划（{} 项任务）。".format(stats["created_days"], stats["created_items"])
        if stats["skipped_days"]:
            msg += "\n跳过 {} 天（已有计划，未覆盖）。".format(stats["skipped_days"])
        messagebox.showinfo("铺排完成", msg, parent=self)
        self.destroy()
        if self.on_done:
            self.on_done()

    def _fail(self, err):
        messagebox.showerror("铺排失败", str(err), parent=self)
        self.btn_start.configure(state="normal")

    def _close(self):
        self._cancel = True
        self.destroy()
