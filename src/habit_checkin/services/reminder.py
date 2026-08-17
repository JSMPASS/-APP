"""提醒服务：后台线程定时检查未完成且到点的打卡项。

- 提醒只在 App 运行时生效。
- 同一打卡项同一天只提醒一次；支持“稍后 10 分钟”与“忽略今天”。
- collect_due_items 为纯逻辑函数，便于单元测试。
"""
from __future__ import annotations

import queue
import sqlite3
import threading
import time
from datetime import datetime, timedelta


def collect_due_items(conn, now, fired, snoozed, ignored):
    """返回到点需要提醒的计划项列表。

    参数:
        conn: SQLite 连接（提醒线程专用）
        now: datetime，当前时间
        fired: set[(item_id, date_str)] 已提醒过的项
        snoozed: dict[item_id -> datetime] 稍后提醒的时间
        ignored: set[(item_id, date_str)] 今天忽略的项
    返回:
        list[dict]，字段: item_id, plan_date, topic_path, reminder_time
    """
    today = now.strftime("%Y-%m-%d")
    now_hm = now.strftime("%H:%M")
    rows = conn.execute(
        "SELECT pi.id AS item_id, p.date AS plan_date, pi.reminder_time, t.id AS topic_id "
        "FROM plan_items pi "
        "JOIN plans p ON p.id = pi.plan_id "
        "JOIN topics t ON t.id = pi.topic_id "
        "WHERE p.date = ? AND pi.done = 0 AND pi.reminder_time IS NOT NULL AND pi.reminder_time <= ?",
        (today, now_hm),
    ).fetchall()
    due = []
    paths = _topic_paths(conn, [r["topic_id"] for r in rows])
    for r in rows:
        item_id = r["item_id"]
        key = (item_id, today)
        if key in fired or key in ignored:
            continue
        if item_id in snoozed:
            if snoozed[item_id] > now:
                continue
            del snoozed[item_id]
        d = dict(r)
        d["topic_path"] = paths.get(r["topic_id"], "")
        due.append(d)
    return due


def _topic_paths(conn, topic_ids):
    ids = {i for i in topic_ids if i is not None}
    if not ids:
        return {}
    rows = conn.execute("SELECT id, parent_id, name FROM topics").fetchall()
    by_id = {r["id"]: (r["parent_id"], r["name"]) for r in rows}
    cache = {}

    def build(topic_id):
        if topic_id in cache:
            return cache[topic_id]
        parts = []
        cur = topic_id
        seen = set()
        while cur is not None and cur not in seen:
            seen.add(cur)
            node = by_id.get(cur)
            if node is None:
                break
            parent_id, name = node
            parts.append(name)
            cur = parent_id
        path = " / ".join(reversed(parts))
        cache[topic_id] = path
        return path

    return {tid: build(tid) for tid in ids}


def prune_reminder_state(fired, ignored, snoozed, now):
    """清理跨天的已提醒/已忽略状态与过期稍后提醒，返回 (fired, ignored, snoozed)。"""
    today = now.strftime("%Y-%m-%d")
    return (
        {key for key in fired if key[1] == today},
        {key for key in ignored if key[1] == today},
        {item_id: due for item_id, due in snoozed.items() if due > now},
    )


class ReminderService(threading.Thread):
    """后台提醒线程：通过队列把到点事件抛给主线程 UI。"""

    def __init__(self, db_path, interval=30):
        super().__init__(daemon=True)
        self.db_path = str(db_path)
        self.interval = interval
        self._stop = threading.Event()
        self._events = queue.Queue()
        self._lock = threading.Lock()
        self._fired = set()
        self._snoozed = {}
        self._ignored = set()

    def run(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            while not self._stop.is_set():
                now = datetime.now()
                with self._lock:
                    self._fired, self._ignored, self._snoozed = prune_reminder_state(
                        self._fired, self._ignored, self._snoozed, now
                    )
                    due = collect_due_items(
                        conn, now, self._fired, self._snoozed, self._ignored
                    )
                    today = now.strftime("%Y-%m-%d")
                    for d in due:
                        self._fired.add((d["item_id"], today))
                for d in due:
                    self._events.put(d)
                self._stop.wait(self.interval)
        finally:
            conn.close()

    def stop(self):
        self._stop.set()

    def get_event(self):
        try:
            return self._events.get_nowait()
        except queue.Empty:
            return None

    def snooze(self, item_id, minutes=10):
        with self._lock:
            self._snoozed[item_id] = datetime.now() + timedelta(minutes=minutes)

    def ignore_today(self, item_id):
        today = datetime.now().strftime("%Y-%m-%d")
        with self._lock:
            self._ignored.add((item_id, today))
