"""备份服务测试：SQLite backup API 在线备份与每日去重。"""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from habit_checkin.db import Database
from habit_checkin.services.backup import backup_db, backup_if_due


class TestBackup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = Database(self.root / "app.db", self.root / "images", self.root)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_backup_db_creates_restorable_copy(self):
        self.db.create_plan("2026-08-11", "backup test")
        dst = backup_db(self.db.db_path, self.root / "backups")
        self.assertIsNotNone(dst)
        conn = sqlite3.connect(dst)
        try:
            count = conn.execute("SELECT COUNT(*) FROM plans").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(count, 1)

    def test_backup_if_due_runs_once_per_day(self):
        first = backup_if_due(self.db.db_path, self.root / "backups")
        second = backup_if_due(self.db.db_path, self.root / "backups")
        self.assertIsNotNone(first)
        self.assertIsNone(second)


if __name__ == "__main__":
    unittest.main()
