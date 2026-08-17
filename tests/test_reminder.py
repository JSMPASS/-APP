"""提醒逻辑单元测试：到点判定、去重、稍后、忽略。"""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from habit_checkin.db import Database
from habit_checkin.services.reminder import collect_due_items, prune_reminder_state


class TestReminder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = Database(self.root / "app.db", self.root / "images", self.root)
        self.pid = self.db.create_plan("2026-08-11", "")
        self.leaf = [t for t in self.db.list_topics() if t["name"] == "逻辑填空（选词填空）"][0]
        self.other = [t for t in self.db.list_topics() if t["name"] == "大作文"][0]

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def _conn(self):
        conn = sqlite3.connect(self.db.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def test_due_and_not_due(self):
        iid_early = self.db.add_plan_item(self.pid, self.leaf["id"], "08:00")
        iid_late = self.db.add_plan_item(self.pid, self.other["id"], "23:00")
        now = datetime(2026, 8, 11, 12, 0, 0)
        conn = self._conn()
        try:
            due = collect_due_items(conn, now, fired=set(), snoozed={}, ignored=set())
        finally:
            conn.close()
        ids = {d["item_id"] for d in due}
        self.assertIn(iid_early, ids)
        self.assertNotIn(iid_late, ids)

    def test_fired_and_done_skipped(self):
        iid = self.db.add_plan_item(self.pid, self.leaf["id"], "08:00")
        done_id = self.db.add_plan_item(self.pid, self.other["id"], "08:00")
        self.db.update_checkin(done_id, "已完成", done=True)
        now = datetime(2026, 8, 11, 12, 0, 0)
        conn = self._conn()
        try:
            due = collect_due_items(conn, now, fired={(iid, "2026-08-11")}, snoozed={}, ignored=set())
        finally:
            conn.close()
        self.assertEqual([d["item_id"] for d in due], [])

    def test_snooze_and_ignore(self):
        iid = self.db.add_plan_item(self.pid, self.leaf["id"], "08:00")
        now = datetime(2026, 8, 11, 12, 0, 0)
        conn = self._conn()
        try:
            due = collect_due_items(conn, now, fired=set(), snoozed={iid: now + timedelta(minutes=5)}, ignored=set())
            self.assertEqual(due, [])
            due2 = collect_due_items(conn, now, fired=set(), snoozed={iid: now - timedelta(minutes=1)}, ignored=set())
            self.assertEqual([d["item_id"] for d in due2], [iid])
            due3 = collect_due_items(conn, now, fired=set(), snoozed={}, ignored={(iid, "2026-08-11")})
            self.assertEqual(due3, [])
        finally:
            conn.close()

    def test_topic_path_and_fields(self):
        iid = self.db.add_plan_item(self.pid, self.leaf["id"], "09:00")
        now = datetime(2026, 8, 11, 10, 0, 0)
        conn = self._conn()
        try:
            due = collect_due_items(conn, now, fired=set(), snoozed={}, ignored=set())
        finally:
            conn.close()
        self.assertEqual(len(due), 1)
        d = due[0]
        self.assertEqual(d["topic_path"], "行测 / 言语理解与表达 / 逻辑填空（选词填空）")
        self.assertEqual(d["plan_date"], "2026-08-11")
        self.assertEqual(d["reminder_time"], "09:00")

    def test_prune_reminder_state(self):
        now = datetime(2026, 8, 11, 9, 0, 0)
        fired = {(1, "2026-08-10"), (2, "2026-08-11")}
        ignored = {(1, "2026-08-11"), (2, "2026-08-10")}
        snoozed = {3: now - timedelta(minutes=1), 4: now + timedelta(minutes=5)}
        fired2, ignored2, snoozed2 = prune_reminder_state(fired, ignored, snoozed, now)
        self.assertEqual(fired2, {(2, "2026-08-11")})
        self.assertEqual(ignored2, {(1, "2026-08-11")})
        self.assertEqual(snoozed2, {4: now + timedelta(minutes=5)})


if __name__ == "__main__":
    unittest.main()
