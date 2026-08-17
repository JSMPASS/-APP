"""SQLite 数据层：建表、预置科目、计划/打卡/历史/设置 的增删改查。

所有图片以副本存入 data/images/，数据库记录相对项目根目录的路径，
保证整个项目目录可整体拷贝迁移。
"""
from __future__ import annotations

import os
import re
import shutil
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id INTEGER REFERENCES topics(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'category',
    is_preset INTEGER NOT NULL DEFAULT 0,
    disabled INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plan_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id INTEGER NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
    topic_id INTEGER NOT NULL REFERENCES topics(id),
    reminder_time TEXT,
    task_type TEXT NOT NULL DEFAULT 'main',
    done INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '',
    checked_at TEXT,
    elapsed_seconds INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS checkin_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_item_id INTEGER NOT NULL REFERENCES plan_items(id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE INDEX IF NOT EXISTS idx_plan_items_plan ON plan_items(plan_id);
CREATE INDEX IF NOT EXISTS idx_plan_items_topic ON plan_items(topic_id);
CREATE INDEX IF NOT EXISTS idx_images_item ON checkin_images(plan_item_id);
CREATE INDEX IF NOT EXISTS idx_plans_date ON plans(date);
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    topic_id INTEGER REFERENCES topics(id),
    source TEXT NOT NULL DEFAULT 'manual',
    source_item_id INTEGER,
    question_text TEXT NOT NULL DEFAULT '',
    analysis TEXT NOT NULL DEFAULT '',
    result TEXT,
    result_reason TEXT NOT NULL DEFAULT '',
    self_analysis TEXT NOT NULL DEFAULT '',
    correct_analysis TEXT NOT NULL DEFAULT '',
    reflection TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS question_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS progress_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'custom',
    builtin_key TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    value REAL NOT NULL DEFAULT 0,
    target REAL,
    unit TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS weekly_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    week_start TEXT NOT NULL UNIQUE,
    review_text TEXT NOT NULL DEFAULT '',
    next_focus TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS question_types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id INTEGER REFERENCES question_types(id) ON DELETE CASCADE,
    map_id INTEGER,
    topic_id INTEGER REFERENCES topics(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    node_type TEXT NOT NULL DEFAULT 'type',
    recognition TEXT NOT NULL DEFAULT '',
    approach TEXT NOT NULL DEFAULT '',
    method TEXT NOT NULL DEFAULT '',
    remark TEXT NOT NULL DEFAULT '',
    color TEXT NOT NULL DEFAULT '',
    node_width REAL NOT NULL DEFAULT 0,
    pos_x REAL NOT NULL DEFAULT 0,
    pos_y REAL NOT NULL DEFAULT 0,
    collapsed INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS question_maps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_name TEXT NOT NULL UNIQUE,
    topic_id INTEGER REFERENCES topics(id) ON DELETE CASCADE,
    color TEXT NOT NULL DEFAULT '#4A7BE0',
    layout_mode TEXT NOT NULL DEFAULT 'auto',
    view_scale REAL NOT NULL DEFAULT 1.0,
    view_offset_x REAL NOT NULL DEFAULT 0,
    view_offset_y REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_question_types_parent ON question_types(parent_id);

CREATE INDEX IF NOT EXISTS idx_questions_topic ON questions(topic_id);
CREATE INDEX IF NOT EXISTS idx_questions_created ON questions(created_at);
CREATE INDEX IF NOT EXISTS idx_qimages_question ON question_images(question_id);
"""

# 预置科目目录（叶子节点即打卡项）；版本升级时重建
CURRENT_SEED_VERSION = 3

# 具体做法：可出现在打卡计划中，但不作为「细分」参与题目分类，也不导入思维导图
METHOD_TOPIC_NAMES = {
    "自由补弱",
    "行测套题",
    "全模块小测",
    "申论套题",
    "知识学习",
    "实践",
}

SEED_TOPICS = [
    ("行测", [
        ("政治理论", []),
        ("常识判断", []),
        ("言语理解与表达", ["逻辑填空（选词填空）", "片段阅读", "语句表达"]),
        ("数量关系", ["数字推理", "数学运算"]),
        ("判断推理", ["图形推理", "定义判断", "类比推理", "逻辑判断"]),
        ("资料分析", ["单一指标", "和差型指标", "分数型指标", "乘积型指标"]),
    ]),
    ("申论", [
        ("概括题", []), ("综合分析题", []),
        ("公文写作题", []), ("提出对策题", []), ("大作文", []),
    ]),
]

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff", ".tif"}
MAX_IMAGE_EDGE = 1600  # 图片入库时统一压缩到的长边上限（像素）


class Database:
    def __init__(self, db_path, images_dir, base_dir):
        self.db_path = str(db_path)
        self.images_dir = Path(images_dir)
        self.base_dir = Path(base_dir)
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA busy_timeout = 5000")
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()
        self._seed_topics()
        self._migrate_remove_cuoti_topic()
        self._migrate_topic_kinds()
        self._seed_metrics()
        self._seed_question_types()

    # ---------- 基础 ----------
    # 轻量迁移：后续给表加字段时在此追加 (表名, 列名, ALTER DDL)，按需幂等执行
    _COLUMN_MIGRATIONS = [
        ("plan_items", "elapsed_seconds",
         "ALTER TABLE plan_items ADD COLUMN elapsed_seconds INTEGER NOT NULL DEFAULT 0"),
        ("plan_items", "task_type",
         "ALTER TABLE plan_items ADD COLUMN task_type TEXT NOT NULL DEFAULT 'main'"),
        ("question_types", "map_id",
         "ALTER TABLE question_types ADD COLUMN map_id INTEGER"),
        ("question_types", "remark",
         "ALTER TABLE question_types ADD COLUMN remark TEXT NOT NULL DEFAULT ''"),
        ("question_types", "color",
         "ALTER TABLE question_types ADD COLUMN color TEXT NOT NULL DEFAULT ''"),
        ("question_types", "pos_x",
         "ALTER TABLE question_types ADD COLUMN pos_x REAL NOT NULL DEFAULT 0"),
        ("question_types", "pos_y",
         "ALTER TABLE question_types ADD COLUMN pos_y REAL NOT NULL DEFAULT 0"),
        ("question_types", "collapsed",
         "ALTER TABLE question_types ADD COLUMN collapsed INTEGER NOT NULL DEFAULT 0"),
        ("question_types", "topic_id",
         "ALTER TABLE question_types ADD COLUMN topic_id INTEGER"),
        ("question_types", "node_width",
         "ALTER TABLE question_types ADD COLUMN node_width REAL NOT NULL DEFAULT 0"),
        ("topics", "kind",
         "ALTER TABLE topics ADD COLUMN kind TEXT NOT NULL DEFAULT 'category'"),
        ("question_maps", "topic_id",
         "ALTER TABLE question_maps ADD COLUMN topic_id INTEGER"),
        ("question_maps", "layout_mode",
         "ALTER TABLE question_maps ADD COLUMN layout_mode TEXT NOT NULL DEFAULT 'auto'"),
        ("question_maps", "view_scale",
         "ALTER TABLE question_maps ADD COLUMN view_scale REAL NOT NULL DEFAULT 1.0"),
        ("question_maps", "view_offset_x",
         "ALTER TABLE question_maps ADD COLUMN view_offset_x REAL NOT NULL DEFAULT 0"),
        ("question_maps", "view_offset_y",
         "ALTER TABLE question_maps ADD COLUMN view_offset_y REAL NOT NULL DEFAULT 0"),
        ("question_maps", "layout_type",
         "ALTER TABLE question_maps ADD COLUMN layout_type TEXT NOT NULL DEFAULT 'radial'"),
        ("question_types", "free_float",
         "ALTER TABLE question_types ADD COLUMN free_float INTEGER NOT NULL DEFAULT 0"),
    ]

    def _init_schema(self):
        self.conn.executescript(_SCHEMA)
        for table, column, ddl in self._COLUMN_MIGRATIONS:
            cols = [r[1] for r in self.conn.execute("PRAGMA table_info({})".format(table)).fetchall()]
            if column not in cols:
                self.conn.execute(ddl)
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_question_types_map ON question_types(map_id, parent_id)")
        self.conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_question_maps_topic ON question_maps(topic_id)")
        self.conn.commit()

    def _seed_topics(self):
        cur = self.conn.execute("SELECT value FROM settings WHERE key='seed_version'")
        row = cur.fetchone()
        if row and row["value"] == str(CURRENT_SEED_VERSION):
            return
        # 版本升级：重建预置科目（级联清理其关联计划与图片），保留自定义科目
        preset_ids = [r["id"] for r in self.conn.execute("SELECT id FROM topics WHERE is_preset=1")]
        for pid in preset_ids:
            self.delete_topic_cascade(pid)
        for root_idx, (root, children) in enumerate(SEED_TOPICS):
            cur = self.conn.execute(
                "INSERT INTO topics(parent_id, name, is_preset, sort_order) VALUES (?,?,?,?)",
                (None, root, 1, root_idx),
            )
            root_id = cur.lastrowid
            for child_idx, (child, leaves) in enumerate(children):
                cur = self.conn.execute(
                    "INSERT INTO topics(parent_id, name, is_preset, sort_order) VALUES (?,?,?,?)",
                    (root_id, child, 1, child_idx),
                )
                child_id = cur.lastrowid
                for leaf_idx, leaf in enumerate(leaves):
                    self.conn.execute(
                        "INSERT INTO topics(parent_id, name, is_preset, sort_order) VALUES (?,?,?,?)",
                        (child_id, leaf, 1, leaf_idx),
                    )
        self.set_setting("seed_version", str(CURRENT_SEED_VERSION))
        self._seed_metrics()

    def _migrate_remove_cuoti_topic(self):
        """把旧版「行测 / 错题复盘」节点合并到「行测 / 自由补弱」，并删除该专用节点。"""
        root = self.conn.execute(
            "SELECT id FROM topics WHERE parent_id IS NULL AND name='行测'"
        ).fetchone()
        if not root:
            return
        old = self.conn.execute(
            "SELECT id FROM topics WHERE parent_id=? AND name='错题复盘'", (root["id"],)
        ).fetchone()
        if not old:
            return
        new_id = self.ensure_topic_by_path(("行测", "自由补弱"))
        self.conn.execute("UPDATE plan_items SET topic_id=? WHERE topic_id=?", (new_id, old["id"]))
        self.conn.execute("UPDATE questions SET topic_id=? WHERE topic_id=?", (new_id, old["id"]))
        self.conn.execute("DELETE FROM topics WHERE id=?", (old["id"],))
        self.conn.commit()

    def _migrate_topic_kinds(self):
        """把已知的具体做法科目标记为 method，其余保持 category（幂等）。"""
        placeholders = ",".join("?" * len(METHOD_TOPIC_NAMES))
        self.conn.execute(
            "UPDATE topics SET kind='method' WHERE name IN ({})".format(placeholders),
            tuple(METHOD_TOPIC_NAMES),
        )
        self.conn.commit()


    BUILTIN_METRICS = [
        ("累计打卡次数", "checkin_count", "次"),
        ("累计打卡天数", "checkin_days", "天"),
        ("收录题目数", "question_count", "题"),
        ("累计错题数", "wrong_count", "题"),
        ("行测套题/模考次数", "mock_exam_count", "次"),
        ("申论大作文篇数", "essay_count", "篇"),
    ]

    def _seed_metrics(self):
        """确保内置指标都存在（缺失则补齐，不影响自定义指标与已设置的目标）。"""
        existing = {
            r["builtin_key"]
            for r in self.conn.execute(
                "SELECT builtin_key FROM progress_metrics WHERE kind='builtin'"
            ).fetchall()
        }
        for idx, (name, key, unit) in enumerate(self.BUILTIN_METRICS):
            if key in existing:
                continue
            self.conn.execute(
                "INSERT INTO progress_metrics(name, kind, builtin_key, enabled, unit, sort_order) "
                "VALUES (?, 'builtin', ?, 1, ?, ?)",
                (name, key, unit, idx),
            )
        self.conn.commit()


    _SUBJECT_COLORS = ["#4A7BE0", "#2FBF71", "#E39A3B", "#DC2626", "#8B5CF6", "#0EA5E9", "#F59E0B"]

    def _seed_question_types(self):
        """初始化/迁移题型思维导图：每个科目一张独立导图，根节点一一对应。"""
        roots = self.conn.execute(
            "SELECT id, name FROM topics WHERE parent_id IS NULL ORDER BY sort_order, id"
        ).fetchall()
        for idx, root in enumerate(roots):
            self._ensure_map_for_topic(
                root["id"], root["name"], self._SUBJECT_COLORS[idx % len(self._SUBJECT_COLORS)]
            )
        self.conn.commit()
        self._auto_import_preset_types()

    def _ensure_map_for_topic(self, topic_id, subject_name, color=None):
        """确保根科目存在对应思维导图和根节点；已存在时同步名称与绑定。"""
        row = self.conn.execute(
            "SELECT * FROM question_maps WHERE topic_id=? OR subject_name=?",
            (topic_id, subject_name),
        ).fetchone()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if row:
            map_id = row["id"]
            if row["topic_id"] is None:
                self.conn.execute("UPDATE question_maps SET topic_id=? WHERE id=?", (topic_id, map_id))
            if row["subject_name"] != subject_name:
                self.conn.execute(
                    "UPDATE question_maps SET subject_name=?, updated_at=? WHERE id=?",
                    (subject_name, now, map_id),
                )
            color = color or row["color"] or self._SUBJECT_COLORS[0]
            root = self.conn.execute(
                "SELECT id, name, color FROM question_types WHERE map_id=? AND parent_id IS NULL",
                (map_id,),
            ).fetchone()
            if root:
                if root["name"] != subject_name:
                    self.conn.execute(
                        "UPDATE question_types SET name=?, updated_at=? WHERE id=?",
                        (subject_name, now, root["id"]),
                    )
                if not root["color"]:
                    self.conn.execute(
                        "UPDATE question_types SET color=?, updated_at=? WHERE id=?",
                        (color, now, root["id"]),
                    )
            else:
                self.conn.execute(
                    "INSERT INTO question_types(parent_id, map_id, name, node_type, color, sort_order, created_at, updated_at) "
                    "VALUES (NULL, ?, ?, 'subject', ?, 0, ?, ?)",
                    (map_id, subject_name, color, now, now),
                )
        else:
            color = color or self._SUBJECT_COLORS[0]
            cur = self.conn.execute(
                "INSERT INTO question_maps(subject_name, topic_id, color, created_at, updated_at) "
                "VALUES (?,?,?,?,?)",
                (subject_name, topic_id, color, now, now),
            )
            map_id = cur.lastrowid
            self.conn.execute(
                "INSERT INTO question_types(parent_id, map_id, name, node_type, color, sort_order, created_at, updated_at) "
                "VALUES (NULL, ?, ?, 'subject', ?, 0, ?, ?)",
                (map_id, subject_name, color, now, now),
            )

    def ensure_map_for_topic(self, topic_id, subject_name, color=None):
        self._ensure_map_for_topic(topic_id, subject_name, color)
        self.conn.commit()

    def import_preset_question_types(self, map_id):
        """把科目管理的知识点树按层级导入该科目思维导图（幂等）。

        层级映射：中间层 -> category 节点，叶子 -> type 节点，均关联 topic_id
        （这样节点直接显示题目统计）。去重：同一导图内已存在相同 topic_id
        或同名节点则跳过该分支。返回导入的节点数。
        """
        m = self.get_question_map(map_id)
        if not m or not m.get("topic_id"):
            return 0
        root_node = self.conn.execute(
            "SELECT id FROM question_types WHERE map_id=? AND parent_id IS NULL", (map_id,)
        ).fetchone()
        if not root_node:
            return 0
        topics = self.conn.execute(
            "SELECT id, parent_id, name, sort_order, kind FROM topics"
        ).fetchall()
        by_parent = {}
        for t in topics:
            by_parent.setdefault(t["parent_id"], []).append(t)
        for lst in by_parent.values():
            lst.sort(key=lambda t: (t["sort_order"], t["id"]))
        existing = self.conn.execute(
            "SELECT name, topic_id FROM question_types WHERE map_id=?", (map_id,)
        ).fetchall()
        seen_topic = {r["topic_id"] for r in existing if r["topic_id"] is not None}
        seen_name = {r["name"] for r in existing}
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        imported = 0

        def walk(topic, parent_node_id, order):
            nonlocal imported
            if topic["id"] in seen_topic or topic["name"] in seen_name:
                return
            if topic["kind"] == "method":
                return  # 具体做法不入思维导图，其子节点一并跳过
            kids = by_parent.get(topic["id"], [])
            node_type = "category" if kids else "type"
            cur = self.conn.execute(
                "INSERT INTO question_types(parent_id, map_id, name, node_type, topic_id, "
                "sort_order, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (parent_node_id, map_id, topic["name"], node_type, topic["id"], order, now, now),
            )
            imported += 1
            seen_topic.add(topic["id"])
            seen_name.add(topic["name"])
            for idx, kid in enumerate(kids):
                walk(kid, cur.lastrowid, idx)

        for idx, kid in enumerate(by_parent.get(m["topic_id"], [])):
            walk(kid, root_node["id"], idx)
        self.conn.commit()
        return imported

    def _auto_import_preset_types(self):
        """首次初始化时把预置科目的知识点树导入其思维导图（仅一次）。

        仅在科目根节点下还没有任何子节点时导入，避免覆盖用户手建结构；
        完成后写标记，此后不自动重复（手动「导入节点」按钮随时可重导）。
        """
        if self.get_setting("mindmap_preset_imported"):
            return
        maps = self.conn.execute(
            "SELECT id FROM question_maps WHERE topic_id IS NOT NULL"
        ).fetchall()
        for r in maps:
            has_children = self.conn.execute(
                "SELECT 1 FROM question_types WHERE map_id=? AND parent_id IS NOT NULL LIMIT 1",
                (r["id"],),
            ).fetchone()
            if not has_children:
                self.import_preset_question_types(r["id"])
        self.set_setting("mindmap_preset_imported", "1")
        self.conn.commit()

    def close(self):
        self.conn.close()

    # ---------- 图片与路径 ----------
    def rel_path(self, abs_path):
        """把绝对路径转换为相对项目根目录的路径（正斜杠）。"""
        p = Path(abs_path).resolve()
        try:
            rel = p.relative_to(self.base_dir.resolve())
            return rel.as_posix()
        except ValueError:
            return p.as_posix()

    def abs_path(self, rel):
        p = Path(rel)
        if p.is_absolute():
            return str(p)
        return str((self.base_dir / p).resolve())

    def store_image_from_path(self, src_path):
        """复制图片到 data/images/，返回相对路径。

        - webp 等 Word 不支持的格式转成 PNG；
        - 长边超过 MAX_IMAGE_EDGE 时等比压缩（减小 data/ 体积）；
        - GIF 保持原样以保留动画；未缩放的非 webp 图片原样拷贝，避免重复编码损失质量。
        """
        src = Path(src_path)
        if not src.is_file():
            raise FileNotFoundError(src_path)
        img = None
        try:
            from PIL import Image
            img = Image.open(src)
            fmt = (img.format or "").upper()
        except Exception:
            fmt = src.suffix[1:].upper() if src.suffix else ""
        ext = (".png" if fmt == "WEBP" else src.suffix.lower())
        if ext not in _IMAGE_EXTS:
            ext = ".png"
        name = "{}_{}{}".format(datetime.now().strftime("%Y%m%d%H%M%S"), uuid.uuid4().hex[:8], ext)
        dest = self.images_dir / name
        try:
            if img is None or fmt == "GIF":
                shutil.copy2(src, dest)
                return self.rel_path(dest)
            resized = False
            w, h = img.size
            if max(w, h) > MAX_IMAGE_EDGE:
                scale = MAX_IMAGE_EDGE / float(max(w, h))
                img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
                resized = True
            if fmt == "WEBP":
                img = img.convert("RGB")
                img.save(dest, "PNG")
            elif resized:
                if fmt in ("JPEG", "JPG"):
                    img = img.convert("RGB")
                    img.save(dest, "JPEG", quality=90)
                else:
                    img.save(dest)
            else:
                shutil.copy2(src, dest)
            return self.rel_path(dest)
        finally:
            if img is not None:
                img.close()

    def delete_image_files(self, rel_paths):
        for rel in rel_paths:
            if not rel:
                continue
            try:
                p = Path(self.abs_path(rel))
                if p.is_file() and p.resolve().is_relative_to(self.images_dir.resolve()):
                    p.unlink(missing_ok=True)
            except OSError:
                pass

    # ---------- 科目 ----------
    def list_topics(self, include_disabled=False):
        sql = "SELECT * FROM topics"
        if not include_disabled:
            sql += " WHERE disabled = 0"
        sql += " ORDER BY parent_id IS NOT NULL, sort_order, id"
        return [dict(r) for r in self.conn.execute(sql)]

    def topic_path(self, topic_id):
        parts = []
        cur = topic_id
        for _ in range(10):
            row = self.conn.execute("SELECT id, parent_id, name FROM topics WHERE id=?", (cur,)).fetchone()
            if not row:
                break
            parts.append(row["name"])
            if row["parent_id"] is None:
                break
            cur = row["parent_id"]
        return " / ".join(reversed(parts))

    def topic_paths(self, topic_ids):
        """批量计算科目路径，避免逐条向上遍历查询。"""
        ids = {i for i in topic_ids if i is not None}
        if not ids:
            return {}
        rows = self.conn.execute("SELECT id, parent_id, name FROM topics").fetchall()
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

    def add_topic(self, name, parent_id=None, kind=None):
        name = name.strip()
        if not name:
            raise ValueError("名称不能为空")
        if kind is None:
            kind = "method" if name in METHOD_TOPIC_NAMES else "category"
        if kind not in ("category", "method"):
            raise ValueError("科目类型必须是「具体分类」或「具体做法」")
        if parent_id is not None:
            row = self.conn.execute("SELECT id FROM topics WHERE id=?", (parent_id,)).fetchone()
            if not row:
                raise ValueError("父科目不存在")
        elif self.conn.execute(
            "SELECT id FROM topics WHERE parent_id IS NULL AND name=? AND disabled=0", (name,)
        ).fetchone():
            raise ValueError("科目已存在")
        max_order = self.conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) AS m FROM topics WHERE parent_id IS ?",
            (parent_id,),
        ).fetchone()["m"]
        cur = self.conn.execute(
            "INSERT INTO topics(parent_id, name, kind, is_preset, sort_order) VALUES (?,?,?,?,?)",
            (parent_id, name, kind, 0, max_order + 1),
        )
        self.conn.commit()
        if parent_id is None:
            self._ensure_map_for_topic(cur.lastrowid, name)
            self.conn.commit()
        return cur.lastrowid

    def set_topic_kind(self, topic_id, kind):
        """切换科目类型：category=具体分类（进入细分/思维导图），method=具体做法。"""
        if kind not in ("category", "method"):
            raise ValueError("科目类型必须是「具体分类」或「具体做法」")
        self.conn.execute("UPDATE topics SET kind=? WHERE id=?", (kind, topic_id))
        self.conn.commit()

    def rename_topic(self, topic_id, name):
        name = name.strip()
        if not name:
            raise ValueError("名称不能为空")
        self.conn.execute("UPDATE topics SET name=? WHERE id=?", (name, topic_id))
        self.conn.commit()
        row = self.conn.execute("SELECT parent_id FROM topics WHERE id=?", (topic_id,)).fetchone()
        if row and row["parent_id"] is None:
            self._ensure_map_for_topic(topic_id, name)
            self.conn.commit()

    def set_topic_disabled(self, topic_id, disabled):
        self.conn.execute("UPDATE topics SET disabled=? WHERE id=?", (1 if disabled else 0, topic_id))
        self.conn.commit()

    def subtree_ids(self, topic_id):
        ids = [topic_id]
        changed = True
        while changed:
            changed = False
            placeholders = ",".join("?" * len(ids))
            rows = self.conn.execute(
                f"SELECT id FROM topics WHERE parent_id IN ({placeholders})", ids
            ).fetchall()
            for r in rows:
                if r["id"] not in ids:
                    ids.append(r["id"])
                    changed = True
        return ids

    def category_subtopic_paths(self, root_id):
        """返回 root_id 下所有「具体分类」节点的相对路径，具体做法及其子树不返回。"""
        topics = self.list_topics()
        children = {}
        for t in topics:
            children.setdefault(t["parent_id"], []).append(t)
        out = []

        def walk(parent_id, prefix):
            for t in children.get(parent_id, []):
                if t["kind"] == "method":
                    continue
                rel = (prefix + " / " + t["name"]).strip(" / ")
                out.append((rel, t["id"]))
                walk(t["id"], rel)

        walk(root_id, "")
        return out

    def category_paths(self):
        """返回全部「具体分类」节点的完整路径（根 → 叶），具体做法及其子树不返回。"""
        topics = self.list_topics()
        children = {}
        for t in topics:
            children.setdefault(t["parent_id"], []).append(t)
        out = []

        def walk(t, prefix):
            if t["kind"] == "method":
                return
            rel = (prefix + " / " + t["name"]).strip(" / ")
            out.append((rel, t["id"]))
            for kid in children.get(t["id"], []):
                walk(kid, rel)

        for r in children.get(None, []):
            walk(r, "")
        return out

    def delete_topic_cascade(self, topic_id):
        ids = self.subtree_ids(topic_id)
        placeholders = ",".join("?" * len(ids))
        rows = self.conn.execute(
            f"SELECT pi.id, ci.file_path FROM plan_items pi "
            f"LEFT JOIN checkin_images ci ON ci.plan_item_id = pi.id "
            f"WHERE pi.topic_id IN ({placeholders})",
            ids,
        ).fetchall()
        rels = {r["file_path"] for r in rows if r["file_path"]}
        item_ids = list({r["id"] for r in rows if r["id"] is not None})
        if item_ids:
            ip = ",".join("?" * len(item_ids))
            self.conn.execute(f"DELETE FROM checkin_images WHERE plan_item_id IN ({ip})", item_ids)
            self.conn.execute(f"DELETE FROM plan_items WHERE id IN ({ip})", item_ids)
        self.conn.execute(
            "UPDATE question_types SET topic_id=NULL WHERE topic_id IN ({})".format(placeholders), ids
        )
        # 题目保留到“未分类”，避免删除科目时因外键失败，也避免误删用户题库
        self.conn.execute(
            "UPDATE questions SET topic_id=NULL WHERE topic_id IN ({})".format(placeholders), ids
        )
        for mr in self.conn.execute(
            "SELECT id FROM question_maps WHERE topic_id IN ({})".format(placeholders), ids
        ).fetchall():
            self.conn.execute("DELETE FROM question_types WHERE map_id=?", (mr["id"],))
            self.conn.execute("DELETE FROM question_maps WHERE id=?", (mr["id"],))
        self.conn.execute(f"DELETE FROM topics WHERE id IN ({placeholders})", ids)
        self.conn.commit()
        self.delete_image_files(rels)

    def root_topics(self):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM topics WHERE parent_id IS NULL AND disabled=0 ORDER BY sort_order, id"
        )]

    def topic_index(self):
        """返回 {主题路径（' / ' 连接）: topic_id} 映射，便于按名称查找。"""
        topics = self.list_topics(include_disabled=False)
        paths = self.topic_paths([t["id"] for t in topics])
        out = {}
        for t in topics:
            path = paths.get(t["id"], "")
            if path:
                out[path] = t["id"]
        return out

    def ensure_topic_by_path(self, names, kind=None):
        """按名称路径（根 → 叶）查找科目，不存在则逐级创建为自定义科目，返回末级 id。"""
        parent_id = None
        for raw in names:
            name = (raw or "").strip()
            if not name:
                continue
            if parent_id is None:
                row = self.conn.execute(
                    "SELECT id FROM topics WHERE parent_id IS NULL AND name=? AND disabled=0",
                    (name,),
                ).fetchone()
            else:
                row = self.conn.execute(
                    "SELECT id FROM topics WHERE parent_id=? AND name=? AND disabled=0",
                    (parent_id, name),
                ).fetchone()
            if row:
                parent_id = row["id"]
            else:
                parent_id = self.add_topic(name, parent_id=parent_id, kind=kind)
        return parent_id

    # ---------- 计划 ----------
    def get_plan(self, date):
        row = self.conn.execute("SELECT * FROM plans WHERE date=?", (date,)).fetchone()
        return dict(row) if row else None

    def create_plan(self, date, title=""):
        row = self.conn.execute("SELECT id FROM plans WHERE date=?", (date,)).fetchone()
        if row:
            raise ValueError(f"{date} 已有计划")
        cur = self.conn.execute(
            "INSERT INTO plans(date, title, created_at) VALUES (?,?,?)",
            (date, title, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        self.conn.commit()
        return cur.lastrowid

    def delete_plan(self, plan_id):
        rows = self.conn.execute(
            "SELECT ci.file_path FROM plan_items pi "
            "LEFT JOIN checkin_images ci ON ci.plan_item_id = pi.id WHERE pi.plan_id=?",
            (plan_id,),
        ).fetchall()
        rels = {r["file_path"] for r in rows if r["file_path"]}
        self.conn.execute("DELETE FROM plans WHERE id=?", (plan_id,))
        self.conn.commit()
        self.delete_image_files(rels)

    def copy_plan(self, src_date, dst_date, replace_existing=True):
        src = self.get_plan(src_date)
        if not src:
            raise ValueError(f"{src_date} 没有可复制的计划")
        if self.get_plan(dst_date):
            if not replace_existing:
                raise ValueError(f"{dst_date} 已有计划")
            self.delete_plan(self.get_plan(dst_date)["id"])
        plan_id = self.create_plan(dst_date, title=src["title"] or "")
        items = self.conn.execute(
            "SELECT topic_id, reminder_time, task_type FROM plan_items WHERE plan_id=? "
            "ORDER BY (reminder_time IS NULL OR reminder_time = ''), reminder_time, id",
            (src["id"],),
        ).fetchall()
        for it in items:
            self.conn.execute(
                "INSERT INTO plan_items(plan_id, topic_id, reminder_time, task_type, done, note, checked_at, created_at) "
                "VALUES (?,?,?,?,0,'',NULL,?)",
                (plan_id, it["topic_id"], it["reminder_time"], it["task_type"],
                 datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            )
        self.conn.commit()
        return len(items)

    # ---------- 计划项 ----------
    def get_plan_items(self, plan_id):
        # 未完成在前（按提醒时间），已完成的自动沉底（按提醒时间）；无提醒时间排在有时间的后面
        rows = self.conn.execute(
            "SELECT * FROM plan_items WHERE plan_id=? "
            "ORDER BY done ASC, (reminder_time IS NULL OR reminder_time = ''), "
            "reminder_time ASC, id ASC",
            (plan_id,),
        ).fetchall()
        paths = self.topic_paths([r["topic_id"] for r in rows])
        images_map = self.query_images_for_items([r["id"] for r in rows])
        items = []
        for r in rows:
            d = dict(r)
            d["topic_path"] = paths.get(d["topic_id"], "")
            d["images"] = images_map.get(d["id"], [])
            items.append(d)
        return items

    def get_plan_item(self, item_id):
        row = self.conn.execute("SELECT * FROM plan_items WHERE id=?", (item_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["topic_path"] = self.topic_path(d["topic_id"])
        d["images"] = self.get_images(d["id"])
        return d

    def get_elapsed(self, item_id):
        row = self.conn.execute(
            "SELECT elapsed_seconds FROM plan_items WHERE id=?", (item_id,)
        ).fetchone()
        return row["elapsed_seconds"] if row else 0

    def set_elapsed(self, item_id, seconds):
        """覆盖写入打卡计时（秒），调用方传入累计值。"""
        self.conn.execute(
            "UPDATE plan_items SET elapsed_seconds = MAX(0, ?) WHERE id=?",
            (int(seconds), item_id),
        )
        self.conn.commit()

    def add_plan_item(self, plan_id, topic_id, reminder_time=None, task_type="main", note=""):
        if reminder_time and not _TIME_RE.match(reminder_time):
            raise ValueError("提醒时间格式应为 HH:MM")
        cur = self.conn.execute(
            "INSERT INTO plan_items(plan_id, topic_id, reminder_time, task_type, note, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (plan_id, topic_id, reminder_time, task_type, note or "",
             datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        self.conn.commit()
        return cur.lastrowid

    def add_plan_items(self, plan_id, entries):
        """批量添加计划项，entries: [(topic_id, reminder_time, task_type), ...]。"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        rows = []
        for topic_id, reminder_time, task_type in entries:
            if reminder_time and not _TIME_RE.match(reminder_time):
                raise ValueError("提醒时间格式应为 HH:MM")
            rows.append((plan_id, topic_id, reminder_time, task_type, "", now))
        self.conn.executemany(
            "INSERT INTO plan_items(plan_id, topic_id, reminder_time, task_type, note, created_at) "
            "VALUES (?,?,?,?,?,?)",
            rows,
        )
        self.conn.commit()
        return len(rows)

    def set_item_reminder(self, item_id, reminder_time):
        if reminder_time and not _TIME_RE.match(reminder_time):
            raise ValueError("提醒时间格式应为 HH:MM")
        self.conn.execute("UPDATE plan_items SET reminder_time=? WHERE id=?", (reminder_time, item_id))
        self.conn.commit()

    def update_checkin(self, item_id, note, done=True, checked_at=None, preserve_time=True):
        row = self.conn.execute("SELECT done, checked_at FROM plan_items WHERE id=?", (item_id,)).fetchone()
        if checked_at is None:
            checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # 已完成的项保留首次打卡时间
        if preserve_time and row and row["done"] and row["checked_at"]:
            checked_at = row["checked_at"]
        self.conn.execute(
            "UPDATE plan_items SET note=?, done=?, checked_at=? WHERE id=?",
            (note or "", 1 if done else 0, checked_at if done else None, item_id),
        )
        self.conn.commit()

    def clear_checked_at(self, item_id):
        """仅清空打卡时间，保留完成状态与总结。"""
        self.conn.execute("UPDATE plan_items SET checked_at=NULL WHERE id=?", (item_id,))
        self.conn.commit()

    def reset_plan_item(self, item_id):
        """把打卡项复原为未打卡：清除状态、时间、总结、图片与计时。"""
        rows = self.conn.execute(
            "SELECT file_path FROM checkin_images WHERE plan_item_id=?", (item_id,)
        ).fetchall()
        rels = {r["file_path"] for r in rows if r["file_path"]}
        self.conn.execute("DELETE FROM checkin_images WHERE plan_item_id=?", (item_id,))
        self.conn.execute(
            "UPDATE plan_items SET done=0, note='', checked_at=NULL, elapsed_seconds=0 WHERE id=?",
            (item_id,),
        )
        self.conn.commit()
        self.delete_image_files(rels)

    def delete_plan_item(self, item_id):
        rows = self.conn.execute(
            "SELECT file_path FROM checkin_images WHERE plan_item_id=?", (item_id,)
        ).fetchall()
        rels = {r["file_path"] for r in rows if r["file_path"]}
        self.conn.execute("DELETE FROM checkin_images WHERE plan_item_id=?", (item_id,))
        self.conn.execute("DELETE FROM plan_items WHERE id=?", (item_id,))
        self.conn.commit()
        self.delete_image_files(rels)

    # ---------- 图片 ----------
    def add_image(self, item_id, rel_path, sort_order=0):
        cur = self.conn.execute(
            "INSERT INTO checkin_images(plan_item_id, file_path, sort_order) VALUES (?,?,?)",
            (item_id, rel_path, sort_order),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_images(self, item_id):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM checkin_images WHERE plan_item_id=? ORDER BY sort_order, id", (item_id,)
        )]

    def sync_checkin_images(self, item_id, kept_rels, new_sources):
        """同步打卡项图片：新增 new_sources，保留 kept_rels，删除其余已存图片。

        返回该打卡项最新的图片列表。
        """
        return self._sync_images("checkin_images", "plan_item_id", item_id, kept_rels, new_sources)

    def _sync_images(self, table, fk_col, owner_id, kept_rels, new_sources):
        """checkin_images / question_images 共用的同步实现。"""
        new_rels = []
        for src in new_sources:
            rel = self.store_image_from_path(src)
            new_rels.append(rel)
            max_order = self.conn.execute(
                "SELECT COALESCE(MAX(sort_order), -1) AS m FROM {} WHERE {}=?".format(table, fk_col),
                (owner_id,),
            ).fetchone()["m"]
            self.conn.execute(
                "INSERT INTO {}({}, file_path, sort_order) VALUES (?,?,?)".format(table, fk_col),
                (owner_id, rel, max_order + 1),
            )
        keep = set(kept_rels) | set(new_rels)
        rows = self.conn.execute(
            "SELECT id, file_path FROM {} WHERE {} = ?".format(table, fk_col), (owner_id,)
        ).fetchall()
        for img in rows:
            if img["file_path"] not in keep:
                self.conn.execute("DELETE FROM {} WHERE id=?".format(table), (img["id"],))
                self.delete_image_files([img["file_path"]])
        self.conn.commit()
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM {} WHERE {} = ? ORDER BY sort_order, id".format(table, fk_col),
            (owner_id,),
        )]

    def delete_image(self, image_id):
        row = self.conn.execute("SELECT file_path FROM checkin_images WHERE id=?", (image_id,)).fetchone()
        if not row:
            return
        self.conn.execute("DELETE FROM checkin_images WHERE id=?", (image_id,))
        self.conn.commit()
        self.delete_image_files([row["file_path"]])

    # ---------- 历史查询 ----------
    def query_items(self, start_date, end_date, root_topic_id=None):
        sql = (
            "SELECT pi.id, pi.plan_id, pi.topic_id, pi.reminder_time, pi.done, pi.note, pi.checked_at, "
            "pi.elapsed_seconds, p.date AS plan_date FROM plan_items pi JOIN plans p ON p.id=pi.plan_id "
            "WHERE p.date BETWEEN ? AND ?"
        )
        params = [start_date, end_date]
        if root_topic_id is not None:
            ids = self.subtree_ids(root_topic_id)
            sql += " AND pi.topic_id IN ({})".format(",".join("?" * len(ids)))
            params.extend(ids)
        sql += (
            " ORDER BY p.date, "
            "(pi.reminder_time IS NULL OR pi.reminder_time = ''), "
            "pi.reminder_time, pi.id"
        )
        rows = self.conn.execute(sql, params).fetchall()
        paths = self.topic_paths([r["topic_id"] for r in rows])
        items = []
        for r in rows:
            d = dict(r)
            d["topic_path"] = paths.get(d["topic_id"], "")
            items.append(d)
        return items

    def query_images_for_items(self, item_ids):
        if not item_ids:
            return {}
        placeholders = ",".join("?" * len(item_ids))
        rows = self.conn.execute(
            f"SELECT * FROM checkin_images WHERE plan_item_id IN ({placeholders}) "
            f"ORDER BY sort_order, id",
            item_ids,
        ).fetchall()
        result = {}
        for r in rows:
            result.setdefault(r["plan_item_id"], []).append(dict(r))
        return result

    # ---------- 设置 ----------
    def get_setting(self, key, default=None):
        row = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key, value):
        self.conn.execute(
            "INSERT INTO settings(key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )
        self.conn.commit()

    def get_bool_setting(self, key, default=False):
        v = self.get_setting(key, None)
        if v is None:
            return default
        return str(v).lower() in ("1", "true", "yes", "on")

    # ---------- 科目层级 ----------
    def move_topic(self, topic_id, new_parent_id, new_order):
        """移动科目到新父级（None 表示根级）并设置同级顺序；禁止移入自身子孙。"""
        if new_parent_id is not None:
            if new_parent_id == topic_id or new_parent_id in self.subtree_ids(topic_id):
                raise ValueError("不能移动到自身或其子科目下")
        self.conn.execute(
            "UPDATE topics SET parent_id=?, sort_order=? WHERE id=?",
            (new_parent_id, new_order, topic_id),
        )
        self.conn.commit()

    def update_topic_tree(self, entries):
        """批量保存科目树结构。entries: [(topic_id, parent_id, sort_order), ...]"""
        for tid, pid, order in entries:
            if pid is not None and (pid == tid or pid in self.subtree_ids(tid)):
                raise ValueError("科目层级关系不合法（不能把科目移动到自身子孙下）")
        self.conn.executemany(
            "UPDATE topics SET parent_id=?, sort_order=? WHERE id=?",
            [(pid, order, tid) for tid, pid, order in entries],
        )
        self.conn.commit()

    # ---------- 题库 ----------
    def collected_checkin_texts(self, item_id):
        """该打卡项已收录进题库的题目文字（用于打卡自动收录去重）。"""
        rows = self.conn.execute(
            "SELECT question_text FROM questions WHERE source='checkin' AND source_item_id=?",
            (item_id,),
        ).fetchall()
        return {r["question_text"] for r in rows}

    def next_question_code(self):
        row = self.conn.execute("SELECT value FROM settings WHERE key='question_seq'").fetchone()
        seq = int(row["value"]) if row and row["value"] else 0
        db_row = self.conn.execute(
            "SELECT MAX(CAST(SUBSTR(code, 2) AS INTEGER)) AS m FROM questions "
            "WHERE code GLOB 'Q[0-9]*'"
        ).fetchone()
        max_code = db_row["m"] or 0
        return "Q{:04d}".format(max(seq, max_code) + 1)

    def add_question(self, topic_id=None, question_text="", analysis="", result=None,
                     result_reason="", source="manual", source_item_id=None,
                     self_analysis="", correct_analysis="", reflection=""):
        code = self.next_question_code()
        cur = self.conn.execute(
            "INSERT INTO questions(code, topic_id, source, source_item_id, question_text, analysis, "
            "result, result_reason, self_analysis, correct_analysis, reflection, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (code, topic_id, source, source_item_id, question_text or "", analysis or "",
             result, result_reason or "", self_analysis or "", correct_analysis or "",
             reflection or "", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        self.conn.execute(
            "INSERT INTO settings(key, value) VALUES ('question_seq', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (int(code[1:]),),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_question(self, qid):
        row = self.conn.execute("SELECT * FROM questions WHERE id=?", (qid,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["topic_path"] = self.topic_path(d["topic_id"]) if d["topic_id"] else "（未分类）"
        d["images"] = self.get_question_images(qid)
        return d

    def list_questions(self, topic_id=None, result=None, start_date=None, end_date=None, search=None):
        sql = "SELECT * FROM questions WHERE 1=1"
        params = []
        if topic_id is not None:
            ids = self.subtree_ids(topic_id)
            sql += " AND topic_id IN ({})".format(",".join("?" * len(ids)))
            params.extend(ids)
        if result:
            sql += " AND result=?"
            params.append(result)
        if start_date:
            sql += " AND created_at >= ?"
            params.append(start_date + " 00:00:00")
        if end_date:
            sql += " AND created_at <= ?"
            params.append(end_date + " 23:59:59")
        if search:
            sql += " AND (code LIKE ? OR question_text LIKE ? OR analysis LIKE ?)"
            params.extend(["%" + search + "%"] * 3)
        sql += " ORDER BY id DESC"
        rows = self.conn.execute(sql, params).fetchall()
        paths = self.topic_paths([r["topic_id"] for r in rows if r["topic_id"]])
        items = []
        for r in rows:
            d = dict(r)
            d["topic_path"] = paths.get(d["topic_id"], "（未分类）") if d["topic_id"] else "（未分类）"
            items.append(d)
        return items

    def update_question(self, qid, **fields):
        allowed = {"topic_id", "question_text", "analysis", "result", "result_reason",
                   "self_analysis", "correct_analysis", "reflection"}
        sets, params = [], []
        for k, v in fields.items():
            if k in allowed:
                sets.append("{} = ?".format(k))
                params.append(v)
        if not sets:
            return
        params.append(qid)
        self.conn.execute("UPDATE questions SET {} WHERE id=?".format(", ".join(sets)), params)
        self.conn.commit()

    def delete_question(self, qid):
        rows = self.conn.execute(
            "SELECT file_path FROM question_images WHERE question_id=?", (qid,)
        ).fetchall()
        rels = {r["file_path"] for r in rows if r["file_path"]}
        self.conn.execute("DELETE FROM question_images WHERE question_id=?", (qid,))
        self.conn.execute("DELETE FROM questions WHERE id=?", (qid,))
        self.conn.commit()
        self.delete_image_files(rels)

    def add_question_image(self, qid, rel_path, sort_order=0):
        cur = self.conn.execute(
            "INSERT INTO question_images(question_id, file_path, sort_order) VALUES (?,?,?)",
            (qid, rel_path, sort_order),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_question_images(self, qid):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM question_images WHERE question_id=? ORDER BY sort_order, id", (qid,)
        )]

    def sync_question_images(self, qid, kept_rels, new_sources):
        """同步题目图片：新增 new_sources，保留 kept_rels，删除其余。"""
        return self._sync_images("question_images", "question_id", qid, kept_rels, new_sources)

    def wrong_questions(self, start_date, end_date):
        return self.list_questions(result="wrong", start_date=start_date, end_date=end_date)

    # ---------- 总体统计 ----------
    def overall_stats(self):
        """全量打卡统计：计划总数、已完成数、完成率。

        只统计已到期（date <= 今天）的计划项，未来日期不计入；
        若设置了 stats_reset_date（清零统计），则只统计该日期及之后的项。
        """
        today = datetime.now().strftime("%Y-%m-%d")
        reset = self.get_setting("stats_reset_date", "")
        cond = "p.date <= ?"
        args = [today]
        if reset:
            cond += " AND p.date >= ?"
            args.append(reset)
        row = self.conn.execute(
            "SELECT COUNT(*) AS total, "
            "COALESCE(SUM(CASE WHEN pi.done=1 AND pi.checked_at IS NOT NULL THEN 1 ELSE 0 END), 0) AS done "
            "FROM plan_items pi JOIN plans p ON p.id = pi.plan_id WHERE " + cond,
            args,
        ).fetchone()
        total = row["total"] or 0
        done = row["done"] or 0
        return {"total": total, "done": done, "rate": (done / total * 100) if total else 0}

    def checkin_dates(self):
        """所有存在完成打卡项的日期（升序，YYYY-MM-DD）。"""
        rows = self.conn.execute(
            "SELECT DISTINCT p.date AS d FROM plan_items pi JOIN plans p ON p.id=pi.plan_id "
            "WHERE pi.done=1 ORDER BY p.date"
        ).fetchall()
        return [r["d"] for r in rows]

    def streak_stats(self):
        """连续打卡统计：当前连续天数、最长连续天数、累计打卡天数。"""
        from datetime import date as _date
        from datetime import timedelta
        done_dates = {_date.fromisoformat(d) for d in self.checkin_dates()}
        days = len(done_dates)
        today = _date.today()
        cur = 0
        d = today if today in done_dates else today - timedelta(days=1)
        while d in done_dates:
            cur += 1
            d -= timedelta(days=1)
        best = 0
        run = 0
        prev = None
        for dt in sorted(done_dates):
            run = run + 1 if (prev is not None and (dt - prev).days == 1) else 1
            best = max(best, run)
            prev = dt
        return {"current": cur, "best": best, "days": days}

    def daily_completion(self, start_date, end_date):
        """按日期返回 {date_str: {'total': n, 'done': m}}（用于热力图与阶段完成率）。"""
        rows = self.conn.execute(
            "SELECT p.date AS d, COUNT(pi.id) AS total, COALESCE(SUM(pi.done), 0) AS done "
            "FROM plans p LEFT JOIN plan_items pi ON pi.plan_id = p.id "
            "WHERE p.date BETWEEN ? AND ? GROUP BY p.date ORDER BY p.date",
            (start_date, end_date),
        ).fetchall()
        return {r["d"]: {"total": r["total"], "done": r["done"]} for r in rows}

    # ---------- 每周复盘 ----------
    def get_weekly_review(self, week_start):
        row = self.conn.execute(
            "SELECT * FROM weekly_reviews WHERE week_start=?", (week_start,)
        ).fetchone()
        return dict(row) if row else None

    def save_weekly_review(self, week_start, review_text="", next_focus=""):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.conn.execute(
            "INSERT INTO weekly_reviews(week_start, review_text, next_focus, created_at, updated_at) "
            "VALUES (?,?,?,?,?) "
            "ON CONFLICT(week_start) DO UPDATE SET "
            "review_text=excluded.review_text, next_focus=excluded.next_focus, "
            "updated_at=excluded.updated_at",
            (week_start, review_text or "", next_focus or "", now, now),
        )
        self.conn.commit()

    # ---------- 总体进度指标 ----------
    def list_metrics(self):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM progress_metrics ORDER BY sort_order, id"
        )]

    def metric_computed_value(self, key):
        if key == "checkin_count":
            return self.conn.execute("SELECT COUNT(*) AS c FROM plan_items WHERE done=1").fetchone()["c"]
        if key == "checkin_days":
            return self.conn.execute(
                "SELECT COUNT(DISTINCT p.date) AS c FROM plan_items pi "
                "JOIN plans p ON p.id=pi.plan_id WHERE pi.done=1"
            ).fetchone()["c"]
        if key == "question_count":
            return self.conn.execute("SELECT COUNT(*) AS c FROM questions").fetchone()["c"]
        if key == "wrong_count":
            return self.conn.execute(
                "SELECT COUNT(*) AS c FROM questions WHERE result='wrong'"
            ).fetchone()["c"]
        if key == "mock_exam_count":
            return self.conn.execute(
                "SELECT COUNT(*) AS c FROM plan_items pi JOIN topics t ON t.id=pi.topic_id "
                "WHERE pi.done=1 AND (t.name LIKE '%套题%' OR t.name LIKE '%模考%' OR t.name LIKE '%小测%')"
            ).fetchone()["c"]
        if key == "essay_count":
            return self.conn.execute(
                "SELECT COUNT(*) AS c FROM plan_items pi JOIN topics t ON t.id=pi.topic_id "
                "WHERE pi.done=1 AND t.name LIKE '%大作文%'"
            ).fetchone()["c"]
        return 0

    def metric_values(self):
        out = []
        for m in self.list_metrics():
            d = dict(m)
            if d["kind"] == "builtin" and d["builtin_key"]:
                d["current"] = self.metric_computed_value(d["builtin_key"])
            else:
                d["current"] = int(d["value"] or 0)
            out.append(d)
        return out

    def set_metric_enabled(self, mid, enabled):
        self.conn.execute("UPDATE progress_metrics SET enabled=? WHERE id=?", (1 if enabled else 0, mid))
        self.conn.commit()

    def add_custom_metric(self, name, unit="", target=None):
        name = name.strip()
        if not name:
            raise ValueError("指标名称不能为空")
        max_order = self.conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) AS m FROM progress_metrics"
        ).fetchone()["m"]
        cur = self.conn.execute(
            "INSERT INTO progress_metrics(name, kind, enabled, value, target, unit, sort_order) "
            "VALUES (?, 'custom', 1, 0, ?, ?, ?)",
            (name, target, unit or "", max_order + 1),
        )
        self.conn.commit()
        return cur.lastrowid

    def delete_metric(self, mid):
        row = self.conn.execute("SELECT kind FROM progress_metrics WHERE id=?", (mid,)).fetchone()
        if not row or row["kind"] != "custom":
            return
        self.conn.execute("DELETE FROM progress_metrics WHERE id=?", (mid,))
        self.conn.commit()

    def set_metric_value(self, mid, value):
        self.conn.execute("UPDATE progress_metrics SET value=? WHERE id=?", (float(value), mid))
        self.conn.commit()

    def set_metric_target(self, mid, target):
        self.conn.execute(
            "UPDATE progress_metrics SET target=? WHERE id=?", (float(target) if target not in (None, "") else None, mid)
        )
        self.conn.commit()




    # ---------- 题型总结 ----------
    # ---------- 题型思维导图 ----------
    def list_question_maps(self):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM question_maps ORDER BY id"
        )]

    def get_question_map(self, map_id):
        row = self.conn.execute("SELECT * FROM question_maps WHERE id=?", (map_id,)).fetchone()
        return dict(row) if row else None

    def add_question_map(self, subject_name, color="#4A7BE0", topic_id=None, layout_mode="auto"):
        subject_name = subject_name.strip()
        if not subject_name:
            raise ValueError("科目名称不能为空")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur = self.conn.execute(
            "INSERT INTO question_maps(subject_name, topic_id, color, layout_mode, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (subject_name, topic_id, color, layout_mode, now, now),
        )
        map_id = cur.lastrowid
        # 自动创建该科目的根节点
        self.conn.execute(
            "INSERT INTO question_types(parent_id, map_id, name, node_type, color, sort_order, created_at, updated_at) "
            "VALUES (NULL, ?, ?, 'subject', ?, 0, ?, ?)",
            (map_id, subject_name, color, now, now),
        )
        self.conn.commit()
        return map_id

    def delete_question_map(self, map_id):
        # 删除该导图下所有节点，再删除导图
        self.conn.execute("DELETE FROM question_types WHERE map_id=?", (map_id,))
        self.conn.execute("DELETE FROM question_maps WHERE id=?", (map_id,))
        self.conn.commit()

    def update_question_map(self, map_id, **fields):
        allowed = {"subject_name", "color", "layout_mode", "layout_type",
                   "view_scale", "view_offset_x", "view_offset_y"}
        sets, params = [], []
        for k, v in fields.items():
            if k in allowed:
                sets.append("{} = ?".format(k))
                params.append(v)
        if not sets:
            return
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # 参数顺序：字段值..., updated_at, id（原实现 id/now 颠倒导致 UPDATE 永不命中）
        params.extend([now, map_id])
        self.conn.execute(
            "UPDATE question_maps SET {}, updated_at=? WHERE id=?".format(", ".join(sets)),
            params,
        )
        self.conn.commit()

    def question_types_by_map(self, map_id):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM question_types WHERE map_id=? ORDER BY parent_id IS NOT NULL, sort_order, id",
            (map_id,),
        )]

    def question_stats_by_map(self, map_id):
        """导图内各节点 topic_id 关联的题目统计：{topic_id: (total, wrong)}。"""
        rows = self.conn.execute(
            "SELECT q.topic_id AS tid, COUNT(*) AS total, "
            "SUM(CASE WHEN q.result='wrong' THEN 1 ELSE 0 END) AS wrong "
            "FROM questions q JOIN question_types n ON n.topic_id = q.topic_id "
            "WHERE n.map_id=? GROUP BY q.topic_id",
            (map_id,),
        ).fetchall()
        return {r["tid"]: (int(r["total"]), int(r["wrong"] or 0)) for r in rows}

    def list_question_types(self):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM question_types ORDER BY parent_id IS NOT NULL, sort_order, id"
        )]

    def get_question_type(self, qtype_id):
        row = self.conn.execute("SELECT * FROM question_types WHERE id=?", (qtype_id,)).fetchone()
        return dict(row) if row else None

    def _question_type_subtree_ids(self, qtype_id):
        ids = [qtype_id]
        changed = True
        while changed:
            changed = False
            ph = ",".join("?" * len(ids))
            rows = self.conn.execute(
                "SELECT id FROM question_types WHERE parent_id IN ({})".format(ph), ids
            ).fetchall()
            for r in rows:
                if r["id"] not in ids:
                    ids.append(r["id"])
                    changed = True
        return ids

    def _validate_question_type_parent(self, parent_id, map_id=None, exclude_id=None):
        if parent_id is None:
            return
        parent = self.get_question_type(parent_id)
        if not parent:
            raise ValueError("父节点不存在")
        if map_id is not None and parent.get("map_id") != map_id:
            raise ValueError("父节点不属于当前思维导图")
        if exclude_id is not None and parent_id in self._question_type_subtree_ids(exclude_id):
            raise ValueError("不能移动到自身或其子节点下")

    def set_question_types_collapsed(self, map_id, collapsed):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.conn.execute(
            "UPDATE question_types SET collapsed=?, updated_at=? WHERE map_id=?",
            (1 if collapsed else 0, now, map_id),
        )
        self.conn.commit()

    def add_question_type(self, name, parent_id=None, node_type="type",
                          recognition="", approach="", method=""):
        name = name.strip()
        if not name:
            raise ValueError("名称不能为空")
        if parent_id is not None:
            row = self.conn.execute("SELECT id FROM question_types WHERE id=?", (parent_id,)).fetchone()
            if not row:
                raise ValueError("父节点不存在")
        max_order = self.conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) AS m FROM question_types WHERE parent_id IS ?",
            (parent_id,),
        ).fetchone()["m"]
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur = self.conn.execute(
            "INSERT INTO question_types(parent_id, name, node_type, recognition, approach, method, sort_order, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (parent_id, name, node_type, recognition or "", approach or "", method or "",
             max_order + 1, now, now),
        )
        self.conn.commit()
        return cur.lastrowid


    def add_question_type_full(self, name, parent_id=None, node_type="type", map_id=None,
                               recognition="", approach="", method="", remark="",
                               color="", node_width=0, pos_x=0, pos_y=0, collapsed=0,
                               topic_id=None):
        """新增题型节点（支持思维导图完整字段）。"""
        name = name.strip()
        if not name:
            raise ValueError("名称不能为空")
        self._validate_question_type_parent(parent_id, map_id=map_id)
        if parent_id is not None and map_id is None:
            map_id = self.get_question_type(parent_id)["map_id"]
        if map_id is None:
            raise ValueError("缺少 map_id，无法确定所属思维导图")
        max_order = self.conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) AS m FROM question_types WHERE parent_id IS ?",
            (parent_id,),
        ).fetchone()["m"]
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur = self.conn.execute(
            "INSERT INTO question_types(parent_id, map_id, name, node_type, recognition, approach, method, "
            "remark, color, node_width, pos_x, pos_y, collapsed, topic_id, sort_order, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (parent_id, map_id, name, node_type, recognition or "", approach or "", method or "",
             remark or "", color or "", float(node_width or 0), float(pos_x or 0),
             float(pos_y or 0), 1 if collapsed else 0, topic_id, max_order + 1, now, now),
        )
        self.conn.commit()
        return cur.lastrowid

    def update_question_type_full(self, qtype_id, **fields):
        allowed = {"name", "parent_id", "node_type", "recognition", "approach", "method",
                   "remark", "color", "node_width", "pos_x", "pos_y", "collapsed", "map_id", "topic_id",
                   "free_float", "sort_order"}
        if "parent_id" in fields:
            node = self.get_question_type(qtype_id)
            if not node:
                return
            self._validate_question_type_parent(
                fields["parent_id"], map_id=node.get("map_id"), exclude_id=qtype_id
            )
            if node.get("parent_id") is None and fields["parent_id"] is not None:
                raise ValueError("科目根节点不能移动到其他节点下")
        sets, params = [], []
        for k, v in fields.items():
            if k in allowed:
                sets.append("{} = ?".format(k))
                params.append(v)
        if not sets:
            return
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # 参数顺序：字段值..., updated_at, id（原实现 id/now 颠倒导致 UPDATE 永不命中）
        params.extend([now, qtype_id])
        self.conn.execute(
            "UPDATE question_types SET {}, updated_at=? WHERE id=?".format(", ".join(sets)),
            params,
        )
        self.conn.commit()

    def toggle_question_type_collapsed(self, qtype_id, collapsed=None):
        node = self.get_question_type(qtype_id)
        if not node:
            return
        val = int(collapsed) if collapsed is not None else (0 if node.get("collapsed") else 1)
        self.conn.execute("UPDATE question_types SET collapsed=? WHERE id=?", (val, qtype_id))
        self.conn.commit()

    def update_question_type(self, qtype_id, **fields):
        allowed = {"name", "parent_id", "node_type", "recognition", "approach", "method"}
        sets, params = [], []
        for k, v in fields.items():
            if k in allowed:
                sets.append("{} = ?".format(k))
                params.append(v)
        if not sets:
            return
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # 参数顺序：字段值..., updated_at, id（原实现 id/now 颠倒导致 UPDATE 永不命中）
        params.extend([now, qtype_id])
        self.conn.execute(
            "UPDATE question_types SET {}, updated_at=? WHERE id=?".format(", ".join(sets)),
            params,
        )
        self.conn.commit()

    def delete_question_type(self, qtype_id):
        self.conn.execute("DELETE FROM question_types WHERE id=?", (qtype_id,))
        self.conn.commit()

    def move_question_type(self, qtype_id, new_parent_id, index=None):
        """移动题型节点：改父层级 + 同级位置（index=None 追加到末尾）。

        同父移动=同级重排；跨父移动=改变层级。校验：目标存在、不能移到自身
        或其后代下、科目根不能变子节点。返回受影响行数。
        """
        node = self.get_question_type(qtype_id)
        if not node:
            raise ValueError("节点不存在")
        self._validate_question_type_parent(
            new_parent_id, map_id=node.get("map_id"), exclude_id=qtype_id)
        if node.get("parent_id") is None and new_parent_id is not None:
            raise ValueError("科目根节点不能移动到其他节点下")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        old_parent = node.get("parent_id")
        old_order = node.get("sort_order") or 0
        # 从旧父移除：后续兄弟 sort_order 前移
        if old_parent is not None:
            self.conn.execute(
                "UPDATE question_types SET sort_order = sort_order - 1, updated_at=? "
                "WHERE parent_id=? AND sort_order > ?",
                (now, old_parent, old_order),
            )
        # 新父下的插入位置
        siblings = [r["id"] for r in self.conn.execute(
            "SELECT id FROM question_types WHERE parent_id IS ? ORDER BY sort_order, id",
            (new_parent_id,),
        ).fetchall()]
        if qtype_id in siblings:
            siblings.remove(qtype_id)
        if index is None or index >= len(siblings):
            pos = len(siblings)
        else:
            pos = max(0, index)
        # 新父下从 pos 开始的兄弟后移
        self.conn.execute(
            "UPDATE question_types SET sort_order = sort_order + 1, updated_at=? "
            "WHERE parent_id IS ? AND sort_order >= ?",
            (now, new_parent_id, pos),
        )
        self.conn.execute(
            "UPDATE question_types SET parent_id=?, sort_order=?, updated_at=? WHERE id=?",
            (new_parent_id, pos, now, qtype_id),
        )
        self.conn.commit()
        return self.conn.total_changes

    def question_type_children(self, parent_id=None):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM question_types WHERE parent_id IS ? ORDER BY sort_order, id",
            (parent_id,),
        )]

def validate_date(value):
    value = str(value).strip()
    if not _DATE_RE.match(value):
        raise ValueError("日期格式应为 YYYY-MM-DD")
    from datetime import date as _date
    try:
        _date.fromisoformat(value)
    except ValueError:
        raise ValueError("日期不存在")
    return value


def validate_time(value):
    value = str(value).strip()
    if value == "":
        return None
    if not _TIME_RE.match(value):
        raise ValueError("提醒时间格式应为 HH:MM（如 19:30）")
    return value
