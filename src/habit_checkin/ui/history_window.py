"""历史记录窗口：日期范围 + 分类筛选浏览打卡记录，可查看详情、导出 Word。"""
from __future__ import annotations

import tkinter as tk
from datetime import date, datetime
from tkinter import filedialog, messagebox, ttk

from habit_checkin.db import validate_date
from habit_checkin.ui.calendar import attach_calendar_on_click
from habit_checkin.services.export_docx import default_filename, export_docx
from habit_checkin.services.export_image import default_filename_png, export_image
from habit_checkin.services.export_pdf import default_filename_pdf, export_pdf
from habit_checkin.ui.export_dialog import ExportFormatDialog
from habit_checkin.ui.common import ScrollableFrame, center_window, make_thumbnail, setup_styles, show_image_zoom
from habit_checkin.ui.animate import fade_in
from habit_checkin.ui.theme import PALETTE, dialog_header
from habit_checkin.ui.theme_menu import ThemeMenu

_COLUMNS = ("day", "status", "topic", "remind", "checked")


class HistoryWindow(tk.Frame):
    def __init__(self, master, db):
        super().__init__(master, bg=PALETTE["bg"])
        self.db = db
        setup_styles(self)
        self.configure(bg=PALETTE["bg"])
        self._build_ui()
        self._query()

    def _build_ui(self):
        dialog_header(self, "历史打卡记录", "按日期浏览打卡记录与导出")
        top = ttk.Frame(self, padding=(12, 10))
        top.pack(fill="x")
        ttk.Label(top, text="开始日期：").pack(side="left")
        self.start_entry = ttk.Entry(top, width=11)
        self.start_entry.insert(0, date.today().isoformat())
        self.start_entry.pack(side="left", padx=(0, 8))
        attach_calendar_on_click(self.start_entry, lambda ds: self._set_entry(self.start_entry, ds))
        ttk.Label(top, text="结束日期：").pack(side="left")
        self.end_entry = ttk.Entry(top, width=11)
        self.end_entry.insert(0, date.today().isoformat())
        self.end_entry.pack(side="left", padx=(0, 8))
        attach_calendar_on_click(self.end_entry, lambda ds: self._set_entry(self.end_entry, ds))
        ttk.Label(top, text="科目：").pack(side="left")
        roots = self.db.root_topics()
        self.filter_var = tk.StringVar(value="全部")
        self.filter_box = ttk.Combobox(
            top, textvariable=self.filter_var, state="readonly", width=12,
            values=["全部"] + [r["name"] for r in roots],
        )
        self.filter_box.pack(side="left", padx=(0, 8))
        ttk.Button(top, text="查询", command=self._query).pack(side="left")
        ttk.Button(top, text="生成打卡报告", style="Accent.TButton",
                   command=self._open_export_dialog).pack(side="right")

        self.summary = tk.Label(self, text="", anchor="w", padx=16, pady=8,
                               bg=PALETTE["primary_light"], fg=PALETTE["primary_dark"],
                               font=("Microsoft YaHei UI", 13, "bold"))
        self.summary.pack(fill="x")

        list_frame = ttk.Frame(self, padding=(12, 6))
        list_frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(list_frame, columns=_COLUMNS, show="headings", selectmode="browse")
        for col, txt, width, anchor in (
            ("day", "日期", 100, "center"),
            ("status", "状态", 80, "center"),
            ("topic", "知识点", 380, "w"),
            ("remind", "提醒", 70, "center"),
            ("checked", "打卡时间", 140, "center"),
        ):
            self.tree.heading(col, text=txt)
            self.tree.column(col, width=width, anchor=anchor)
        self.tree.tag_configure("done_even", foreground=PALETTE["done"], background=PALETTE["input"])
        self.tree.tag_configure("done_odd", foreground=PALETTE["done"], background=PALETTE["stripe"])
        self.tree.tag_configure("todo_even", foreground=PALETTE["text"], background=PALETTE["input"])
        self.tree.tag_configure("todo_odd", foreground=PALETTE["text"], background=PALETTE["stripe"])
        vsb = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda e: self._show_detail())
        self.tree.bind("<Button-3>", self._on_right_click)

    # ---------- 查询 ----------
    @staticmethod
    def _set_entry(entry, ds):
        entry.delete(0, "end")
        entry.insert(0, ds)

    def _query(self):
        try:
            start = validate_date(self.start_entry.get())
            end = validate_date(self.end_entry.get())
        except ValueError as exc:
            messagebox.showwarning("日期错误", str(exc), parent=self)
            return
        if start > end:
            messagebox.showwarning("日期范围", "开始日期不能晚于结束日期。", parent=self)
            return
        root_id = None
        root_name = self.filter_var.get()
        if root_name != "全部":
            roots = self.db.root_topics()
            for r in roots:
                if r["name"] == root_name:
                    root_id = r["id"]
                    break
        items = self.db.query_items(start, end, root_topic_id=root_id)
        self._items = items
        self.tree.delete(*self.tree.get_children())
        done = sum(1 for it in items if it["done"])
        for idx, it in enumerate(items):
            stripe = "even" if idx % 2 == 0 else "odd"
            tag = ("done_" if it["done"] else "todo_") + stripe
            status = "✓ 已完成" if it["done"] else "○ 未完成"
            self.tree.insert(
                "", "end", iid=str(it["id"]), tags=(tag,),
                values=(
                    it["plan_date"], status, it["topic_path"],
                    it["reminder_time"] or "—", (it["checked_at"] or "")[11:16] or "—",
                ),
            )
        if items:
            self.summary.configure(
                text="{} 至 {}：共 {} 项，完成 {} 项（{:.0f}%）。双击查看详情。".format(
                    start, end, len(items), done, (done / len(items) * 100)
                )
            )
        else:
            self.summary.configure(text="该范围内没有打卡记录。")

    # ---------- 详情 ----------
    def _show_detail(self):
        sel = self.tree.selection()
        if not sel:
            return
        item_id = int(sel[0])
        item = self.db.get_plan_item(item_id)
        if not item:
            return
        DetailWindow(self, self.db, item)

    # ---------- 右键编辑/删除 ----------
    def _on_right_click(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        item_id = int(iid)
        self.tree.selection_set(iid)
        self.tree.focus(iid)
        menu = ThemeMenu(self)
        self._menu = menu
        menu.show(event.x_root, event.y_root, [
            ("✎ 编辑该记录", lambda: self._edit_item(item_id)),
            ("---",),
            ("✕ 删除该记录", lambda: self._delete_item(item_id), True),
        ])

    def _edit_item(self, item_id):
        item = self.db.get_plan_item(item_id)
        if not item:
            return
        dlg = EditItemDialog(self.master, self.db, item)
        self.wait_window(dlg)
        self._query()

    def _delete_item(self, item_id):
        item = self.db.get_plan_item(item_id)
        if not item:
            return
        ok = messagebox.askyesno(
            "删除记录",
            "确定删除「{}」这条记录吗？\n其文字总结和图片也会一并删除。".format(item["topic_path"]),
            parent=self,
        )
        if not ok:
            return
        self.db.delete_plan_item(item_id)
        self._query()

    # ---------- 导出 ----------
    def _open_export_dialog(self):
        ExportFormatDialog(self.master, self._export_fmt)

    def _export_fmt(self, fmt):
        try:
            start = validate_date(self.start_entry.get())
            end = validate_date(self.end_entry.get())
        except ValueError as exc:
            messagebox.showwarning("日期错误", str(exc), parent=self)
            return
        items = self.db.query_items(start, end)
        if not items:
            messagebox.showinfo("导出", "该范围内没有可导出的记录。", parent=self)
            return
        if fmt == "pdf":
            fn, filetypes, ext = default_filename_pdf(start, end), [("PDF 文档", "*.pdf")], ".pdf"
        elif fmt == "png":
            fn, filetypes, ext = default_filename_png(start, end), [("PNG 图片", "*.png")], ".png"
        else:
            fn, filetypes, ext = default_filename(start, end), [("Word 文档", "*.docx")], ".docx"
        path = filedialog.asksaveasfilename(
            parent=self, defaultextension=ext, initialfile=fn,
            filetypes=filetypes, title="导出打卡情况",
        )
        if not path:
            return
        try:
            if fmt == "pdf":
                stats = export_pdf(self.db, start, end, path)
            elif fmt == "png":
                stats = export_image(self.db, start, end, path)
            else:
                stats = export_docx(self.db, start, end, path)
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc), parent=self)
            return
        messagebox.showinfo(
            "导出成功",
            "已生成：{}\n计划 {} 项，完成 {} 项（{:.1f}%），收录题目 {} 题。".format(
                path, stats["total"], stats["done"], stats["rate"], stats.get("questions", 0)
            ),
            parent=self,
        )


class DetailWindow(tk.Toplevel):
    def __init__(self, master, db, item):
        super().__init__(master, bg=PALETTE["bg"])
        self.db = db
        self.item = item
        self.title("打卡详情")
        self.geometry("520x480")
        self.transient(master)
        setup_styles(self)
        self.configure(bg=PALETTE["bg"])
        dialog_header(self, "打卡详情", item["plan_date"])
        head = ttk.Frame(self, padding=(12, 10))
        head.pack(fill="x")
        ttk.Label(head, text=item["topic_path"], font=("Microsoft YaHei UI", 15, "bold")).pack(anchor="w")
        status = "✓ 已完成（{}）".format((item["checked_at"] or "")[11:16]) if item["done"] else "○ 未完成"
        ttk.Label(head, text="{}  {}".format(item["plan_date"], status)).pack(anchor="w", pady=(2, 0))

        note_frame = ttk.LabelFrame(self, text="文字总结", padding=8)
        note_frame.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        txt = tk.Text(note_frame, wrap="word", height=8, font=("Microsoft YaHei UI", 13),
                      bg=PALETTE["input"], fg=PALETTE["text"], relief="flat", highlightthickness=1,
                      highlightbackground=PALETTE["border"], insertbackground=PALETTE["text"])
        txt.insert("1.0", item["note"] or "（未填写）")
        txt.configure(state="disabled")
        txt.pack(fill="both", expand=True)

        img_frame = ttk.LabelFrame(self, text="图片", padding=8)
        img_frame.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        scroll = ScrollableFrame(img_frame)
        scroll.pack(fill="both", expand=True)
        images = item.get("images") or []
        if not images:
            tk.Label(scroll.inner, text="（无图片）", bg=PALETTE["card"], fg=PALETTE["muted"],
                     font=("Microsoft YaHei UI", 11)).pack(anchor="w", pady=4)
        else:
            row = ttk.Frame(scroll.inner)
            row.pack(fill="x", pady=2)
            for idx, img in enumerate(images):
                if idx % 5 == 0 and idx > 0:
                    row = ttk.Frame(scroll.inner)
                    row.pack(fill="x", pady=2)
                try:
                    tk_img = make_thumbnail(db.abs_path(img["file_path"]), 100)
                except Exception:
                    continue
                f = tk.Frame(row, width=106, height=112, bg=PALETTE["card"])
                f.pack_propagate(False)
                f.pack(side="left", padx=4)
                lab = tk.Label(f, image=tk_img, bg=PALETTE["card"], cursor="hand2")
                lab.pack(pady=(2, 0))
                lab.bind("<Double-1>", lambda e, p=db.abs_path(img["file_path"]): show_image_zoom(self, p))
                tk.Label(f, text=str(idx + 1), font=("Microsoft YaHei UI", 11),
                         bg=PALETTE["card"], fg=PALETTE["muted"]).pack()
                scroll._images = getattr(scroll, "_images", []) + [tk_img]
        ttk.Button(self, text="关闭", command=self.destroy).pack(pady=(0, 10))
        center_window(self)
        fade_in(self)


class EditItemDialog(tk.Toplevel):
    """编辑单条历史记录：文字总结、完成状态与打卡时间。"""

    def __init__(self, master, db, item):
        super().__init__(master, bg=PALETTE["bg"])
        self.db = db
        self.item = item
        self.title("编辑打卡记录")
        self.geometry("560x520")
        self.transient(master)
        setup_styles(self)
        self.configure(bg=PALETTE["bg"])
        dialog_header(self, "编辑打卡记录", item["plan_date"])

        head = ttk.Frame(self, padding=(12, 10))
        head.pack(fill="x")
        ttk.Label(head, text=item["topic_path"], font=("Microsoft YaHei UI", 15, "bold")).pack(anchor="w")

        note_frame = ttk.LabelFrame(self, text="文字总结", padding=8)
        note_frame.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self.note_text = tk.Text(
            note_frame, wrap="word", height=8, font=("Microsoft YaHei UI", 13),
            bg=PALETTE["input"], fg=PALETTE["text"], relief="flat", highlightthickness=1,
            highlightbackground=PALETTE["border"], insertbackground=PALETTE["text"],
        )
        self.note_text.insert("1.0", item["note"] or "")
        self.note_text.pack(fill="both", expand=True)

        status_frame = ttk.LabelFrame(self, text="状态", padding=10)
        status_frame.pack(fill="x", padx=12, pady=(0, 8))
        self.done_var = tk.BooleanVar(value=bool(item["done"]))
        ttk.Checkbutton(status_frame, text="已完成", variable=self.done_var).pack(side="left")
        ttk.Label(status_frame, text="打卡时间（HH:MM）：").pack(side="left", padx=(20, 4))
        self.time_var = tk.StringVar(value=(item["checked_at"] or "")[11:16] if item["done"] else "")
        ttk.Entry(status_frame, textvariable=self.time_var, width=8).pack(side="left")

        bottom = tk.Frame(self, bg=PALETTE["bg"], padx=12, pady=10)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="取消", command=self.destroy).pack(side="right")
        ttk.Button(bottom, text="保存", style="Accent.TButton", command=self._save).pack(side="right", padx=8)
        center_window(self)
        fade_in(self)
        self.grab_set()

    def _save(self):
        note = self.note_text.get("1.0", "end").strip()
        done = bool(self.done_var.get())
        time_str = self.time_var.get().strip()
        if done:
            if not time_str:
                time_str = datetime.now().strftime("%H:%M")
            parts = time_str.split(":")
            if len(parts) != 2 or not all(p.isdigit() for p in parts):
                messagebox.showwarning("编辑打卡记录", "打卡时间格式应为 HH:MM。", parent=self)
                return
            base_date = (self.item.get("checked_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"))[:10]
            checked_at = "{} {}:00".format(base_date, time_str)
        else:
            checked_at = None
        self.db.update_checkin(
            self.item["id"], note, done=done, checked_at=checked_at, preserve_time=False
        )
        self.destroy()
