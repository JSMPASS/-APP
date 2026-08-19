# -*- coding: utf-8 -*-
"""统一字段编辑弹窗：项目内“单独修改”文本表单共用同一套交互与校验。

字段类型：text / multiline / integer / float / time / date / choice / color / bool。
通过 ask_fields(master, title, fields) 返回 {key: value}，取消返回 None。
"""
from __future__ import annotations

import re
import tkinter as tk
from datetime import date
from tkinter import colorchooser, messagebox, ttk

from habit_checkin.ui.animate import fade_in
from habit_checkin.ui.calendar import CalendarPopup
from habit_checkin.ui.common import ScrollableFrame, center_window, setup_styles
from habit_checkin.ui.theme import PALETTE, dialog_header

_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
_WINDOW_WIDTH = 560
_MAX_BODY = 460


def ask_fields(master, title, fields, subtitle=None):
    """弹出统一字段编辑框，返回 {key: value}；用户取消时返回 None。"""
    dlg = FieldEditDialog(master, title, fields, subtitle=subtitle)
    dlg.wait_window()
    return dlg.result


class FieldTextArea(tk.Text):
    """统一风格多行文本域：与编辑页控件一致，支持字数统计。"""

    def __init__(self, master, text="", height=8, count_label=None,
                 on_change=None, **kw):
        P = PALETTE
        super().__init__(
            master, height=height, wrap="word",
            font=("Microsoft YaHei UI", 12),
            bg=P["input"], fg=P["text"], relief="flat",
            highlightthickness=1, highlightbackground=P["border"],
            highlightcolor=P["focus"], insertbackground=P["text"], **kw,
        )
        self._count_label = count_label
        self._on_change = on_change
        if text:
            self.insert("1.0", text)
        self.bind("<KeyRelease>", self._on_key)
        self._update_count()

    def _on_key(self, event):
        self._update_count()
        if self._on_change:
            self._on_change()

    def _update_count(self):
        if self._count_label:
            try:
                n = len(self.get("1.0", "end-1c"))
            except tk.TclError:
                n = 0
            self._count_label.configure(text="{} 字".format(n))


class _PlaceholderEntry(tk.Entry):
    """带占位提示的单行输入框，聚焦后自动清除占位文字。"""

    def __init__(self, master, placeholder="", initial="", on_change=None, **kw):
        P = PALETTE
        self._placeholder = placeholder or ""
        self._on_change = on_change
        self._ph = False
        self._normal_fg = kw.pop("fg", P["text"])
        super().__init__(
            master, relief="flat", bd=0, highlightthickness=1,
            highlightbackground=P["border"], highlightcolor=P["focus"],
            insertbackground=P["text"], bg=P["input"], fg=self._normal_fg,
            font=("Microsoft YaHei UI", 12), **kw,
        )
        self.bind("<FocusIn>", self._on_focus_in)
        self.bind("<FocusOut>", self._on_focus_out)
        self.bind("<KeyRelease>", self._on_key)
        if initial:
            self.insert(0, initial)
        self._sync_placeholder()

    def _on_focus_in(self, event):
        if self._ph:
            self.delete(0, "end")
            self._ph = False
            self.configure(fg=self._normal_fg)

    def _on_focus_out(self, event):
        self._sync_placeholder()

    def _on_key(self, event):
        if self._ph:
            self.delete(0, "end")
            self._ph = False
            self.configure(fg=self._normal_fg)
        if self._on_change:
            self._on_change()

    def _sync_placeholder(self):
        if self._placeholder and not self.get().strip():
            self.delete(0, "end")
            self.insert(0, self._placeholder)
            self._ph = True
            self.configure(fg=PALETTE["faint"])

    def get_value(self):
        return "" if self._ph else self.get()

    def set_value(self, value):
        self.delete(0, "end")
        self._ph = False
        self.configure(fg=self._normal_fg)
        if value:
            self.insert(0, value)
        self._sync_placeholder()


class FieldEditDialog(tk.Toplevel):
    """按字段列表生成统一编辑窗口，保存后返回字段值。"""

    def __init__(self, master, title, fields, subtitle=None, footer_buttons=None):
        super().__init__(master)
        self.fields = fields
        self.result = None
        self._widgets = {}
        self._dirty = False
        self._footer_buttons = footer_buttons or []
        self.title(title)
        self.minsize(520, 360)
        self.transient(master)
        setup_styles(self)
        self.configure(bg=PALETTE["bg"])
        dialog_header(self, title, subtitle or "", title_size=14, subtitle_size=9)
        self._build()
        self._set_geometry()
        center_window(self)
        fade_in(self)
        self.grab_set()

    # ---------- 构建 ----------
    def _field_type(self, field):
        return field.get("type") or ("multiline" if field.get("multiline") else "text")

    def _estimated_height(self):
        total = 0
        for field in self.fields:
            if self._field_type(field) == "multiline":
                total += field.get("height", 3) * 22 + 62
            elif self._field_type(field) == "bool":
                total += 46
            else:
                total += 74
        return total

    def _set_geometry(self):
        est = self._estimated_height()
        body_h = min(max(est, 180), _MAX_BODY)
        self.geometry("{}x{}".format(_WINDOW_WIDTH, min(700, 150 + body_h)))

    def _build(self):
        P = PALETTE
        est = self._estimated_height()
        self._use_scroll = est > _MAX_BODY
        if self._use_scroll:
            body = ScrollableFrame(self, bg=P["bg"])
            inner = body.inner
            self._scroll = body
        else:
            body = tk.Frame(self, bg=P["bg"])
            inner = body
            self._scroll = None
        body.pack(fill="both", expand=True, padx=18, pady=10)
        inner.columnconfigure(0, weight=1, uniform="field")
        inner.columnconfigure(1, weight=1, uniform="field")
        if self._scroll:
            self._scroll.bind_wheel_all()

        row, col = 0, 0
        for field in self.fields:
            full = self._field_type(field) in ("multiline", "bool")
            if full and col == 1:
                row += 1
                col = 0
            cell = self._build_field(inner, field)
            if full:
                cell.grid(row=row, column=0, columnspan=2, sticky="nsew",
                          pady=(2, 2))
                row += 1
            else:
                cell.grid(row=row, column=col, sticky="nsew", padx=(0, 8),
                          pady=(2, 2))
                col = 1 - col
                if col == 0:
                    row += 1

        bottom = tk.Frame(self, bg=P["bg"], padx=18, pady=10)
        bottom.pack(fill="x")
        for text, command in self._footer_buttons:
            ttk.Button(bottom, text=text, command=command).pack(side="left")
        ttk.Button(bottom, text="取消", command=self._close).pack(side="right")
        ttk.Button(bottom, text="保存", style="Accent.TButton",
                   command=self._save).pack(side="right", padx=8)
        self.bind("<Escape>", lambda e: self._close())

    def _build_field(self, parent, field):
        P = PALETTE
        ftype = self._field_type(field)
        label = field.get("label", field["key"])
        required = bool(field.get("required"))
        cell = tk.Frame(parent, bg=P["bg"])
        label_row = tk.Frame(cell, bg=P["bg"])
        label_row.pack(fill="x")
        tk.Label(label_row, text=label, bg=P["bg"], fg=P["text"],
                 font=("Microsoft YaHei UI", 12)).pack(side="left")
        if required:
            tk.Label(label_row, text="*", bg=P["bg"], fg=P["danger"],
                     font=("Microsoft YaHei UI", 12, "bold")).pack(side="left")

        ctl = {"field": field, "kind": ftype, "error": None}

        if ftype == "multiline":
            count = tk.Label(label_row, text="", bg=P["bg"], fg=P["faint"],
                             font=("Microsoft YaHei UI", 10))
            count.pack(side="right")
            text = FieldTextArea(
                cell, text=field.get("value", ""),
                height=field.get("height", 3), count_label=count,
                on_change=self._mark_dirty,
            )
            text.pack(fill="both", expand=True, pady=(2, 0))
            text.bind("<Control-Return>", lambda e: self._save())
            ctl["text"] = text
        elif ftype == "bool":
            var = tk.BooleanVar(value=bool(field.get("value")))
            cb = ttk.Checkbutton(cell, text=field.get("check_text", ""),
                                 variable=var, command=self._mark_dirty)
            cb.pack(anchor="w", pady=(2, 0))
            ctl["var"] = var
        else:
            row = tk.Frame(cell, bg=P["bg"])
            row.pack(fill="x", pady=(2, 0))
            entry = _PlaceholderEntry(
                row, placeholder=field.get("placeholder", ""),
                initial=field.get("value", ""), on_change=self._mark_dirty,
            )
            entry.pack(side="left", fill="x", expand=True)
            entry.bind("<Return>", lambda e: self._save())
            ctl["entry"] = entry
            if ftype == "choice":
                choices = field.get("choices", [])
                var = tk.StringVar(value=field.get("value", choices[0] if choices else ""))
                combo = ttk.Combobox(
                    row, textvariable=var, state="readonly", values=choices,
                )
                combo.pack(side="left", fill="x", expand=True)
                combo.bind("<<ComboboxSelected>>", lambda e: self._mark_dirty())
                entry.pack_forget()
                ctl["var"] = var
            elif ftype == "color":
                ttk.Button(row, text="选择",
                           command=lambda: self._pick_color(ctl)).pack(
                    side="left", padx=(8, 0))
            elif ftype == "date":
                ttk.Button(row, text="选择",
                           command=lambda: self._pick_date(ctl)).pack(
                    side="left", padx=(8, 0))

        error = tk.Label(cell, text="", bg=P["bg"], fg=P["danger"],
                         font=("Microsoft YaHei UI", 9), anchor="w", height=1)
        error.pack(fill="x", pady=(1, 0))
        ctl["error"] = error
        self._widgets[field["key"]] = ctl
        return cell

    # ---------- 辅助控件 ----------
    def _pick_color(self, ctl):
        current = ctl["entry"].get_value() or "#4A7BE0"
        chosen = colorchooser.askcolor(color=current, parent=self)[1]
        if chosen:
            ctl["entry"].set_value(chosen)
            self._mark_dirty()

    def _pick_date(self, ctl):
        current = ctl["entry"].get_value()
        try:
            initial = date.fromisoformat(current) if current else date.today()
        except ValueError:
            initial = date.today()

        def on_select(day_str):
            ctl["entry"].set_value(day_str)
            self._mark_dirty()

        CalendarPopup(ctl["entry"], initial_date=initial, on_select=on_select)

    # ---------- 校验与保存 ----------
    def _mark_dirty(self, *args):
        self._dirty = True

    def _close(self):
        if self._dirty and not messagebox.askyesno(
            "未保存", "有未保存的修改，确定关闭吗？", parent=self,
        ):
            return
        self.destroy()

    def _collect_values(self):
        values = {}
        for key, ctl in self._widgets.items():
            kind = ctl["kind"]
            if kind == "multiline":
                values[key] = ctl["text"].get("1.0", "end").strip()
            elif kind == "bool":
                values[key] = bool(ctl["var"].get())
            elif kind == "choice":
                values[key] = ctl["var"].get().strip()
            else:
                values[key] = ctl["entry"].get_value().strip()
        return values

    def _validate_values(self, values):
        """逐字段校验并转换类型，返回 [(key, message)]。"""
        errors = []
        for field in self.fields:
            key = field["key"]
            label = field.get("label", key)
            ftype = self._field_type(field)
            raw = values.get(key)
            if ftype == "bool":
                continue
            if field.get("required") and not raw:
                errors.append((key, "请填写{}".format(label)))
                continue
            if not raw:
                if ftype in ("integer", "float"):
                    values[key] = None
                else:
                    values[key] = ""
                continue
            if ftype == "text" or ftype == "multiline":
                continue
            if ftype == "integer":
                try:
                    val = int(raw)
                except (ValueError, TypeError):
                    errors.append((key, "请输入整数"))
                    continue
                if field.get("min") is not None and val < field["min"]:
                    errors.append((key, "不能小于 {}".format(field["min"])))
                    continue
                if field.get("max") is not None and val > field["max"]:
                    errors.append((key, "不能大于 {}".format(field["max"])))
                    continue
                values[key] = val
            elif ftype == "float":
                try:
                    val = float(raw)
                except (ValueError, TypeError):
                    errors.append((key, "请输入数字"))
                    continue
                if field.get("min") is not None and val < field["min"]:
                    errors.append((key, "不能小于 {}".format(field["min"])))
                    continue
                if field.get("max") is not None and val > field["max"]:
                    errors.append((key, "不能大于 {}".format(field["max"])))
                    continue
                values[key] = val
            elif ftype == "time":
                m = _TIME_RE.match(raw)
                if not m:
                    errors.append((key, "时间格式应为 HH:MM"))
                    continue
                values[key] = "{:02d}:{:02d}".format(int(m.group(1)), int(m.group(2)))
            elif ftype == "date":
                try:
                    values[key] = date.fromisoformat(raw).isoformat()
                except ValueError:
                    errors.append((key, "日期格式应为 YYYY-MM-DD"))
            elif ftype == "choice":
                if raw not in field.get("choices", []):
                    errors.append((key, "请选择{}".format(label)))
            elif ftype == "color":
                try:
                    self.winfo_rgb(raw)
                except tk.TclError:
                    errors.append((key, "颜色值无效"))
        return errors

    def _show_errors(self, errors):
        for key, ctl in self._widgets.items():
            ctl["error"].configure(text="")
        first = None
        for key, msg in errors:
            ctl = self._widgets.get(key)
            if not ctl:
                continue
            ctl["error"].configure(text=msg)
            if first is None:
                first = ctl
        if first:
            widget = first.get("text") or first.get("entry")
            if widget:
                widget.focus_set()

    def _save(self, event=None):
        values = self._collect_values()
        errors = self._validate_values(values)
        if errors:
            self._show_errors(errors)
            return
        self.result = values
        self.destroy()
