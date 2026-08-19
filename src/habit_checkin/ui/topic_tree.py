"""科目树通用交互：长按拖拽调序/调层级、右键增删改，供计划与设置复用。"""
from __future__ import annotations

import time
import tkinter as tk
from tkinter import messagebox

from habit_checkin.ui.field_edit_dialog import ask_fields
from habit_checkin.ui.theme_menu import ThemeMenu


class TopicTreeMixin:
    """依赖 self.db、self.tree，并提供 _refresh_tree() 的科目树编辑能力。"""

    # ---------- 长按拖拽 ----------
    def _is_descendant(self, iid, ancestor):
        p = self.tree.parent(iid)
        while p:
            if p == ancestor:
                return True
            p = self.tree.parent(p)
        return False

    def _visible_rows(self):
        rows = []

        def walk(parent):
            for iid in self.tree.get_children(parent):
                rows.append(iid)
                if self.tree.item(iid, "open"):
                    walk(iid)

        walk("")
        return rows

    def _highlight(self, iid):
        self._clear_highlight()
        if iid:
            try:
                self.tree.item(iid, tags=("drag_target",))
            except tk.TclError:
                pass
        self._drag_target = iid

    def _clear_highlight(self):
        if getattr(self, "_drag_target", None):
            try:
                self.tree.item(self._drag_target, tags=())
            except tk.TclError:
                pass
        self._drag_target = None

    def _on_drag_press(self, event):
        self._drag_item = self.tree.identify_row(event.y)
        self._drag_press_time = time.monotonic()
        self._drag_active = False
        self._drag_target = None

    def _on_drag_motion(self, event):
        if not self._drag_item:
            return
        if time.monotonic() - self._drag_press_time < 0.4:
            return  # 长按判定
        if not self._drag_active:
            self._drag_active = True
            self.tree.configure(cursor="hand2")
        target = self.tree.identify_row(event.y)
        if target != self._drag_target:
            self._highlight(target)

    def _on_drag_release(self, event):
        if not self._drag_item:
            return
        self._clear_highlight()
        if self._drag_active:
            self._apply_drop(event)
            self.tree.configure(cursor="")
        elif hasattr(self, "_on_tree_click"):
            self._on_tree_click(event)
        self._drag_item = None
        self._drag_active = False

    def _apply_drop(self, event):
        item = self._drag_item
        y = event.y
        target = self.tree.identify_row(y)

        def valid_parent(parent):
            return parent != item and not self._is_descendant(parent, item)

        if target and target != item:
            if self.tree.get_children(target) and not self._is_descendant(target, item):
                # 拖到分类上 → 成为其子项（末尾）
                self.tree.move(item, target, "end")
                self.tree.item(target, open=True)
            else:
                parent = self.tree.parent(target)
                if not valid_parent(parent):
                    return
                bbox = self.tree.bbox(target)
                index = self.tree.index(target)
                if bbox and y > bbox[1] + bbox[3] / 2:
                    index += 1
                try:
                    self.tree.move(item, parent, index)
                except tk.TclError:
                    return
        else:
            # 空白区域：放到上方最近一行之后（其父级末尾）；没有则放到根顶部
            nearest = None
            for iid in self._visible_rows():
                bb = self.tree.bbox(iid)
                if bb and bb[1] + bb[3] <= y:
                    nearest = iid
            if nearest is not None:
                parent = self.tree.parent(nearest)
                if not valid_parent(parent):
                    return
                try:
                    self.tree.move(item, parent, self.tree.index(nearest) + 1)
                except tk.TclError:
                    return
            else:
                try:
                    self.tree.move(item, "", 0)
                except tk.TclError:
                    return
        self._save_tree_order()
        self.tree.see(item)

    def _save_tree_order(self):
        entries = []

        def walk(parent_iid, parent_id):
            for idx, iid in enumerate(self.tree.get_children(parent_iid)):
                tid = int(iid[1:])
                entries.append((tid, parent_id, idx))
                walk(iid, tid)

        walk("", None)
        try:
            self.db.update_topic_tree(entries)
        except ValueError as exc:
            messagebox.showwarning("移动失败", str(exc), parent=self)
            self._on_tree_order_error()

    def _on_tree_order_error(self):
        self._refresh_tree()

    # ---------- 右键增删改 ----------
    def _on_right_click(self, event):
        iid = self.tree.identify_row(event.y)
        menu = ThemeMenu(self)
        self._menu = menu
        if iid:
            topic_id = int(iid[1:])
            row = self.db.conn.execute(
                "SELECT name, kind, is_preset, disabled FROM topics WHERE id=?", (topic_id,)
            ).fetchone()
            if not row:
                return
            name = row["name"]
            next_kind = "具体做法" if row["kind"] == "category" else "具体分类"
            items = [
                ("＋ 新增子知识点", lambda: self._add_child_for(topic_id)),
                ("---",),
                ("切换为{}".format(next_kind), lambda: self._toggle_kind_for(topic_id)),
                ("---",),
            ]
            if row["is_preset"]:
                items.append((
                    "✎ 重命名（系统默认不可改）",
                    lambda: messagebox.showinfo("重命名", "系统默认科目不支持重命名，可新增自定义科目代替。", parent=self),
                ))
                items.append((
                    "✕ 删除（系统默认不可删）",
                    lambda: messagebox.showinfo("删除", "系统默认科目不支持删除，可改用「停用/启用」隐藏。", parent=self),
                    True,
                ))
            else:
                items.append(("✎ 重命名「{}」".format(name), lambda: self._rename_for(topic_id)))
                items.append(("✕ 删除「{}」".format(name), lambda: self._delete_for(topic_id), True))
            items.append((
                ("停用「{}」" if not row["disabled"] else "启用「{}」").format(name),
                lambda: self._toggle_disabled_for(topic_id),
            ))
        else:
            items = [("＋ 新增科目", self._add_root)]
        menu.show(event.x_root, event.y_root, items)

    def _add_root(self):
        values = ask_fields(
            self, "新增科目", [
                {"key": "name", "label": "科目名称", "required": True,
                 "placeholder": "例如：资料分析"},
            ],
            subtitle="新增后将出现在科目管理中",
        )
        if not values:
            return
        name = values["name"].strip()
        try:
            self.db.add_topic(name, parent_id=None)
        except ValueError as exc:
            messagebox.showwarning("新增失败", str(exc), parent=self)
        self._refresh_tree()

    def _add_child_for(self, parent_id):
        values = ask_fields(
            self, "新增子知识点", [
                {"key": "name", "label": "知识点名称", "required": True,
                 "placeholder": "例如：单一指标"},
            ],
            subtitle="新建后将作为该科目的子知识点",
        )
        if not values:
            return
        name = values["name"].strip()
        try:
            self.db.add_topic(name, parent_id=parent_id)
        except ValueError as exc:
            messagebox.showwarning("新增失败", str(exc), parent=self)
        self._refresh_tree()

    def _rename_for(self, topic_id):
        row = self.db.conn.execute("SELECT name FROM topics WHERE id=?", (topic_id,)).fetchone()
        values = ask_fields(
            self, "重命名知识点", [
                {"key": "name", "label": "新名称", "required": True,
                 "value": row["name"] if row else "",
                 "placeholder": "输入新的名称"},
            ],
            subtitle="修改后将同步到计划、思维导图与细分查询",
        )
        if not values:
            return
        name = values["name"].strip()
        try:
            self.db.rename_topic(topic_id, name)
        except ValueError as exc:
            messagebox.showwarning("重命名失败", str(exc), parent=self)
        self._refresh_tree()

    def _delete_for(self, topic_id):
        row = self.db.conn.execute("SELECT name FROM topics WHERE id=?", (topic_id,)).fetchone()
        if not messagebox.askyesno(
            "删除确认",
            "确定删除「{}」及其所有子知识点吗？\n相关打卡记录和图片将一并删除，不可恢复。".format(row["name"]),
            parent=self,
        ):
            return
        self.db.delete_topic_cascade(topic_id)
        self._refresh_tree()
        self._after_topic_changed(topic_id)

    def _toggle_disabled_for(self, topic_id):
        row = self.db.conn.execute("SELECT disabled FROM topics WHERE id=?", (topic_id,)).fetchone()
        self.db.set_topic_disabled(topic_id, not row["disabled"])
        self._refresh_tree()
        self._after_topic_changed(topic_id)

    def _toggle_kind_for(self, topic_id):
        row = self.db.conn.execute("SELECT name, kind FROM topics WHERE id=?", (topic_id,)).fetchone()
        if not row:
            return
        new_kind = "method" if row["kind"] == "category" else "category"
        label = "具体做法" if new_kind == "method" else "具体分类"
        if not messagebox.askyesno(
            "切换类型",
            "确定将「{}」切换为「{}」吗？\n"
            "具体分类会进入思维导图和细分查询；\n"
            "具体做法只用于生成计划，不入思维导图。".format(row["name"], label),
            parent=self,
        ):
            return
        try:
            self.db.set_topic_kind(topic_id, new_kind)
        except ValueError as exc:
            messagebox.showwarning("切换失败", str(exc), parent=self)
        self._refresh_tree()
        self._after_topic_changed(topic_id)

    def _after_topic_changed(self, topic_id):
        """子类可覆写，用于删除/停用后清理选中状态。"""
