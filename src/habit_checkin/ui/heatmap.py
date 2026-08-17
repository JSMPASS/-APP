# -*- coding: utf-8 -*-
"""打卡热力图（GitHub 风格，按月份分块）。

默认展示上个月、本月、下个月三个月份；每个月从 1 号所在星期开始，
月份变化时由调用方按当前日期重新计算日期范围并自动刷新。
"""
from __future__ import annotations

import calendar as _cal
import tkinter as tk
from datetime import date, timedelta

from habit_checkin.ui.theme import PALETTE

_WEEK_CN = ["一", "二", "三", "四", "五", "六", "日"]

# 完成率 → 颜色（0 表示无计划，1~4 表示 0-25% / 25-50% / 50-75% / 75%+）
_LEVEL_COLORS = {
    0: "#E9EDF3",   # 无计划
    1: "#D3E8DC",
    2: "#A6D6BE",
    3: "#5FBF8F",
    4: "#16A34A",
}

_AXIS_H = 26
_LABEL_W = 42


def level_of(done, total):
    if not total:
        return 0
    if done >= total:
        return 4
    rate = done / total
    if rate >= 0.75:
        return 3
    if rate >= 0.5:
        return 2
    if rate > 0:
        return 1
    return 0


def _add_months(year, month, delta):
    total = year * 12 + (month - 1) + delta
    return total // 12, total % 12 + 1


class CalendarHeatmap(tk.Canvas):
    """按月分块的打卡热力图组件。"""

    def __init__(self, master, daily, months=None, cell=20, gap=5, month_gap=18, bg=None):
        bg = bg or PALETTE["surface"]
        self.daily = daily or {}
        today = date.today()
        self.months = sorted(months or [
            _add_months(today.year, today.month, d) for d in (-1, 0, 1)
        ])
        self.cell = cell
        self.gap = gap
        self.month_gap = month_gap
        self._label_w = _LABEL_W
        self._meta = {}
        self._hover_label = None
        self._click_handler = None

        self._month_meta = []
        for year, month in self.months:
            first_wd = date(year, month, 1).weekday()
            days = _cal.monthrange(year, month)[1]
            cols = (first_wd + days + 6) // 7
            self._month_meta.append({
                "year": year, "month": month, "days": days,
                "first_wd": first_wd, "cols": cols,
            })
        total_cols = sum(m["cols"] for m in self._month_meta)
        grid_w = total_cols * (cell + gap) - gap + month_gap * (len(self.months) - 1)
        self._legend_w = 5 * (cell + 58) - 8
        width = max(self._label_w + grid_w + 8, self._label_w + self._legend_w + 8)
        height = _AXIS_H + 7 * (cell + gap) - gap + cell + 18
        super().__init__(master, width=width, height=height, bg=bg,
                         highlightthickness=0, bd=0)
        self._draw()

    def _draw(self):
        self.delete("all")
        self._meta = {}
        x0, y0 = self._label_w, _AXIS_H
        # 星期纵轴
        for r, wd in enumerate(_WEEK_CN):
            self.create_text(
                self._label_w - 10, y0 + r * (self.cell + self.gap) + self.cell / 2,
                text=wd, fill=PALETTE["muted"], font=("Microsoft YaHei UI", 12, "bold"),
            )

        x = x0
        for mm in self._month_meta:
            m_x0 = x
            year, month, days, first_wd, cols = (
                mm["year"], mm["month"], mm["days"], mm["first_wd"], mm["cols"]
            )
            day = 1
            for col in range(cols):
                for row in range(7):
                    if (col == 0 and row < first_wd) or day > days:
                        # 空白占位格，保持每月 1 号落在真实星期位置
                        bx = x + col * (self.cell + self.gap)
                        by = y0 + row * (self.cell + self.gap)
                        self.create_rectangle(
                            bx, by, bx + self.cell, by + self.cell,
                            fill=PALETTE["input"], outline=PALETTE["divider"], width=1,
                        )
                        continue
                    d = date(year, month, day)
                    info = self.daily.get(d.isoformat())
                    done = info["done"] if info else 0
                    total = info["total"] if info else 0
                    lvl = level_of(done, total)
                    bx = x + col * (self.cell + self.gap)
                    by = y0 + row * (self.cell + self.gap)
                    rid = self.create_rectangle(
                        bx, by, bx + self.cell, by + self.cell,
                        fill=_LEVEL_COLORS[lvl], outline="", tags=("cell",),
                    )
                    self._meta[rid] = (d, done, total)
                    day += 1
            m_x1 = x + cols * (self.cell + self.gap) - self.gap
            self.create_text(
                (m_x0 + m_x1) / 2, _AXIS_H / 2,
                text="{}年{}月".format(year, month),
                fill=PALETTE["muted"], font=("Microsoft YaHei UI", 11, "bold"),
            )
            x += cols * (self.cell + self.gap) + self.month_gap

        # 图例（相对网格居中）
        grid_w = (x - self.month_gap) - x0
        lx = x0 + max(0, (grid_w - self._legend_w) // 2)
        ly = y0 + 7 * (self.cell + self.gap) - self.gap + 10
        for lvl, label in ((0, "无计划"), (1, "起步"), (2, "过半"), (3, "接近"), (4, "完成")):
            self.create_rectangle(lx, ly, lx + self.cell, ly + self.cell,
                                  fill=_LEVEL_COLORS[lvl], outline="")
            self.create_text(lx + self.cell + 6, ly + self.cell / 2, text=label,
                             fill=PALETTE["muted"], font=("Microsoft YaHei UI", 12),
                             anchor="w")
            lx += self.cell + 58

    def set_hover_label(self, label_widget):
        """把悬停信息写入 label_widget（tk.Label）。"""
        self._hover_label = label_widget
        self.tag_bind("cell", "<Enter>", self._on_enter)
        self.tag_bind("cell", "<Leave>", lambda e: label_widget.configure(text=""))

    def set_click_handler(self, handler):
        """点击格子时回调 handler(date_str)。"""
        self._click_handler = handler
        self.tag_bind("cell", "<Button-1>", self._on_click)

    def _on_click(self, event):
        ids = self.find_withtag("current")
        if not ids:
            return
        meta = self._meta.get(ids[0])
        if not meta or self._click_handler is None:
            return
        self._click_handler(meta[0].isoformat())

    def _on_enter(self, event):
        ids = self.find_withtag("current")
        if not ids:
            return
        meta = self._meta.get(ids[0])
        if not meta or self._hover_label is None:
            return
        d, done, total = meta
        if total:
            text = "{}：完成 {} / {}（{:.0f}%）".format(
                d.isoformat(), done, total, done / total * 100
            )
        else:
            text = "{}：无计划".format(d.isoformat())
        self._hover_label.configure(text=text)
