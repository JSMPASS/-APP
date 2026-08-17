# -*- coding: utf-8 -*-
"""数据库自动备份：每天最多备份一次 app.db，保留最近 N 份。"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from urllib.parse import quote


def _readonly_source_uri(db_path):
    """返回 SQLite 只读 URI，供 WAL 模式下的在线备份使用。"""
    posix = str(Path(db_path).resolve().as_posix())
    return "file:{}?mode=ro".format(quote(posix, safe="/:"))


def backup_db(db_path, backup_dir, keep=14):
    """在线备份 app.db 到备份目录（文件名带时间戳），清理超出 keep 份的旧备份。

    使用 SQLite backup API，应用运行中手动备份也不会复制到不一致的快照。
    返回备份路径或 None。
    """
    src = Path(db_path)
    if not src.is_file():
        return None
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = backup_dir / "app_{}.db".format(stamp)
    src_conn = None
    dst_conn = None
    try:
        try:
            src_conn = sqlite3.connect(_readonly_source_uri(src), uri=True, timeout=5)
        except sqlite3.Error:
            src_conn = sqlite3.connect(str(src), timeout=5)
        dst_conn = sqlite3.connect(str(dst))
        src_conn.backup(dst_conn)
    except (sqlite3.Error, OSError):
        try:
            dst.unlink(missing_ok=True)
        except OSError:
            pass
        return None
    finally:
        if dst_conn is not None:
            dst_conn.close()
        if src_conn is not None:
            src_conn.close()
    backups = sorted(backup_dir.glob("app_*.db"))
    for old in backups[:-keep]:
        try:
            old.unlink(missing_ok=True)
        except OSError:
            pass
    return dst


def backup_if_due(db_path, backup_dir, keep=14):
    """每天最多自动备份一次；当天已备份过则跳过。返回备份路径或 None。"""
    src = Path(db_path)
    if not src.is_file():
        return None
    backup_dir = Path(backup_dir)
    today = datetime.now().strftime("%Y%m%d")
    if backup_dir.is_dir():
        for f in backup_dir.glob("app_{}_*.db".format(today)):
            return None  # 今天已备份
    return backup_db(db_path, backup_dir, keep=keep)


def list_backups(backup_dir):
    """返回备份文件列表（按时间倒序）。"""
    backup_dir = Path(backup_dir)
    if not backup_dir.is_dir():
        return []
    return sorted(backup_dir.glob("app_*.db"), reverse=True)
