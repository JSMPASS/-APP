"""90 天备考计划（公考行测 + 申论）的结构化数据与一键铺排逻辑。

数据来源：仓库根目录《90天学习计划.md》。本模块是计划的「单一数据源」，
供「备考进度」页导航展示，以及「一键铺排」生成每日 3 主 + 1 辅任务。
"""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta

TOTAL_DAYS = 90
DEFAULT_START = date(2026, 8, 20)   # 90 天备考计划首日（2026-08-20）
DEFAULT_END = DEFAULT_START + timedelta(days=TOTAL_DAYS - 1)


def _plan_range(day_start, day_end):
    """把计划第 N 天换算为「MM-DD ~ MM-DD」展示文本。"""
    s = DEFAULT_START + timedelta(days=day_start - 1)
    e = DEFAULT_START + timedelta(days=day_end - 1)
    return "{:02d}-{:02d} ~ {:02d}-{:02d}".format(
        s.month, s.day, e.month, e.day
    )


def default_plan_config():
    """返回内置默认计划配置（天数/阶段/周/检查点/作息）。"""
    return {
        "total_days": TOTAL_DAYS,
        "stages": [dict(s) for s in STAGES],
        "weeks": [[w[0], w[2]] for w in WEEKS],
        "checkpoints": [list(c) for c in CHECKPOINTS],
        "daily_routine": [list(r) for r in DAILY_ROUTINE],
    }


def normalize_plan_config(config=None):
    """补齐缺失字段，保证任意旧配置都能安全使用。"""
    base = default_plan_config()
    if not config:
        return base
    out = {}
    out["total_days"] = max(1, int(config.get("total_days") or base["total_days"]))
    out["stages"] = config.get("stages") or base["stages"]
    out["weeks"] = config.get("weeks") or base["weeks"]
    out["checkpoints"] = config.get("checkpoints") or base["checkpoints"]
    out["daily_routine"] = config.get("daily_routine") or base["daily_routine"]
    return out


def get_plan_config(db):
    """从数据库设置读取计划配置；无配置时返回内置默认值。"""
    raw = db.get_setting("plan_config", "") if hasattr(db, "get_setting") else ""
    try:
        return normalize_plan_config(json.loads(raw) if raw else None)
    except (ValueError, TypeError):
        return default_plan_config()


def save_plan_config(db, config):
    """保存计划配置到数据库设置。"""
    db.set_setting("plan_config", json.dumps(normalize_plan_config(config), ensure_ascii=False))


def datetime_now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# ---------------- 三阶段 ----------------
STAGES = [
    {
        "name": "基础奠基",
        "day_start": 1,
        "day_end": 30,
        "range": _plan_range(1, 30),
        "xingce": "判断推理系统学基础（花生判断13讲）；言语、资料基础课已学完直接限时提速；数量每周 3 次插空（花生数量课）；政治/常识每天积累（政治用小黑课）",
        "shenlun": "从零系统学（袁东系统课）：归纳概括 → 提出对策 → 综合分析 → 公文写作；每周大作文日练方法、提纲和段落仿写",
        "exit": "判断基础知识过完一遍；申论四类小题各完成 1-2 题；大作文完成提纲和段落仿写；言语、资料形成稳定方法",
    },
    {
        "name": "专项强化",
        "day_start": 31,
        "day_end": 60,
        "range": _plan_range(31, 60),
        "xingce": "言语、资料、判断限时专项；每周一次模块小测；数量每周 4 次插空",
        "shenlun": "按题型深度练习；每周大作文日完成一篇完整文章",
        "exit": "三大主模块做题速度和正确率明显提升；申论各题型有稳定思路；大作文能独立完成整篇",
    },
    {
        "name": "模考冲刺",
        "day_start": 61,
        "day_end": 90,
        "range": _plan_range(61, 90),
        "xingce": "每周 3 套行测套题；资料、言语每天保温；数量每周 2 次插空",
        "shenlun": "每周 1-2 套申论套题；大作文限时写作并修改，累计 4-5 篇",
        "exit": "行测套题完整做完并复盘；大作文修改稿完整；错题复做通过率高",
    },
]

# ---------------- 13 周逐周计划 ----------------
WEEKS = [
    (1, _plan_range(1, 7), "判断推理：逻辑基础；申论：归纳概括入门；言语、资料摸底"),
    (2, _plan_range(8, 14), "判断推理：图形推理、定义判断；申论：归纳概括深化；言语：逻辑填空方法"),
    (3, _plan_range(15, 21), "判断推理：类比推理、逻辑判断进阶；申论：提出对策；资料：单一指标、和差型指标"),
    (4, _plan_range(22, 28), "判断推理：全题型基础收尾；申论：综合分析；行测模块小测"),
    (5, _plan_range(29, 35), "言语：逻辑填空、片段阅读限时；资料：分数型、乘积型；申论：公文写作"),
    (6, _plan_range(36, 42), "判断：逻辑、定义专项；资料：全题型提速；申论：综合分析深挖 + 公文巩固"),
    (7, _plan_range(43, 49), "言语：语句表达、文段结构；判断：全题型限时；申论：大作文完整文章 + 精改"),
    (8, _plan_range(50, 56), "行测模块限时测；错题重做；申论：全题型周测"),
    (9, _plan_range(57, 63), "三大主模块提速专项；数量补弱；申论：完整小题 + 大作文限时写作"),
    (10, _plan_range(64, 70), "行测套题 2 套；申论套题 1 套；错题复盘"),
    (11, _plan_range(71, 77), "行测套题 2 套；申论套题 1 套；大作文限时写 + 修改"),
    (12, _plan_range(78, 84), "行测套题 3 套；申论套题 1 套；查漏补缺"),
    (13, _plan_range(85, 90), "全真模拟 2 次；错题清零；节奏和心态调整"),
]

# ---------------- 检查点（第 N 天 -> 检查内容） ----------------
CHECKPOINTS = [
    (10, "判断基础是否推进；申论归纳概括是否完成"),
    (20, "判断基础是否过半；申论提出对策是否完成"),
    (30, "阶段 1 退出标准：判断基础过完；申论概括/对策/综合分析完成、公文入门；大作文完成提纲和段落仿写"),
    (45, "三大主模块是否开始限时；模块小测是否稳定"),
    (60, "阶段 2 退出标准：速度明显提升；大作文能独立完成整篇并修改"),
    (75, "套题能否完整做完；错题是否在减少"),
    (90, "最终复盘：套题节奏、申论答卷、大作文 4-5 篇、错题清零"),
]

# ---------------- 每日作息（固定模板，用于展示与提醒时间） ----------------
DAILY_ROUTINE = [
    ("09:00", "政治理论：小黑课 1 节（周一/三/五）或 背诵清单挖空版（周二/四/六），周日晨读范文"),
    ("09:30", "行测主模块 A（判断 / 套题）"),
    ("11:00", "行测主模块 B（资料 / 言语）"),
    ("13:30", "申论专题（袁东系统课 + 对应题型 1 题；周日为大作文日）"),
    ("15:00", "数量关系插空（周一/三/五） / 模块小测"),
    ("16:00", "错题复盘（ABCD 分类）+ 方法本整理"),
    ("19:00", "收听新闻联播 + 记录时政要点"),
    ("19:30", "ComfyUI / 软件编程创作（自由创作 2 小时）"),
    ("21:30", "明日计划、轻量收尾"),
    ("23:00", "睡觉"),
]

# ---------------- 每周执行模板（星期 0=周一 ... 6=周日） ----------------
# 三元组：(主模块 A, 主模块 B, 申论/专项)；行测A 槽以判断推理为主攻（定制方案）
WEEK_TEMPLATE = {
    0: ("判断", "资料", "申论小题"),
    1: ("判断", "言语", "申论小题"),
    2: ("判断", "资料", "申论小题"),
    3: ("判断", "言语", "申论小题"),
    4: ("判断", "资料", "申论小题"),
    5: ("全模块小测", "资料保温", "申论小题"),
    6: ("错题复盘", "自由补弱", "大作文"),
}

# 申论题型按天推进（袁东系统课主线）：W1-2 概括 → W3 对策 → W4 综合 → W5 公文 → W6 综合深挖 → W7+ 轮转
def _shenlun_for_day(day):
    if day <= 14:
        return "归纳概括"
    if day <= 21:
        return "提出对策"
    if day <= 28:
        return "综合分析"
    if day <= 35:
        return "公文写作"
    if day <= 42:
        return "综合分析"
    return "申论小题"

# ---------------- 任务标签 -> 科目路径（根 → 叶） ----------------
_MODULE_TOPIC = {
    "言语": ("行测", "言语理解与表达"),
    "资料": ("行测", "资料分析"),
    "资料保温": ("行测", "资料分析"),
    "判断": ("行测", "判断推理"),
    "数量": ("行测", "数量关系"),
    "全模块小测": ("行测", "全模块小测"),
    "行测套题": ("行测", "行测套题"),
    "错题复盘": ("行测", "自由补弱"),
    "当日重点整理": ("行测", "知识学习"),
    "新闻联播": ("行测", "知识学习"),
    "创作": ("行测", "实践"),
    "自由补弱": ("行测", "自由补弱"),
}

_SHENLUN_TOPIC = {
    "归纳概括": ("申论", "概括题"),
    "综合分析": ("申论", "综合分析题"),
    "提出对策": ("申论", "提出对策题"),
    "公文写作": ("申论", "公文写作题"),
    "大作文": ("申论", "大作文"),
    "综合小题/补弱": ("申论", "综合分析题"),
    "申论小题": ("申论", "提出对策题"),
    "申论套题": ("申论", "申论套题"),
}


def day_number(start, d):
    """返回 d 是计划的第几天（1 起）；早于开始返回 0，超出 90 返回 >90 的数值。"""
    return (d - start).days + 1


def remaining_days(start, d, total_days=None):
    """剩余天数（含当天）。"""
    total_days = total_days or TOTAL_DAYS
    return max(0, total_days - day_number(start, d) + 1)


def stage_for(day, stages=None):
    stages = stages or STAGES
    for s in stages:
        if s["day_start"] <= day <= s["day_end"]:
            return s
    return None


def week_for(day, weeks=None):
    weeks = weeks or WEEKS
    idx = (day - 1) // 7
    if 0 <= idx < len(weeks):
        return weeks[idx]
    return None


def plan_week_of(start, d, total_days=None, weeks=None):
    """返回 (周序号 1..N, 本周第一天日期)。"""
    weeks = weeks or WEEKS
    total_days = total_days or TOTAL_DAYS
    day = day_number(start, d)
    idx = (day - 1) // 7
    week_num = min(max(idx + 1, 1), max(len(weeks), (total_days + 6) // 7))
    week_start = start + timedelta(days=(week_num - 1) * 7)
    return week_num, week_start


def checkpoint_for(day, checkpoints=None):
    """若 day 是检查点，返回 (天数, 检查内容)，否则 None。"""
    checkpoints = checkpoints or CHECKPOINTS
    for cp_day, content in checkpoints:
        if cp_day == day:
            return (cp_day, content)
    return None


def resolve_topic(db, label, day=1):
    """把任务标签解析为科目 id；特殊科目缺失时自动创建为自定义科目。"""
    if label in ("当日重点整理", "新闻联播"):
        return db.ensure_topic_by_path(("行测", "知识学习"), kind="method")
    if label == "创作":
        return db.ensure_topic_by_path(("行测", "实践"), kind="method")
    if label in _MODULE_TOPIC:
        return db.ensure_topic_by_path(_MODULE_TOPIC[label])
    if label in _SHENLUN_TOPIC:
        return db.ensure_topic_by_path(_SHENLUN_TOPIC[label])
    if label == "政治理论·常识积累":
        return db.ensure_topic_by_path(("行测", "政治理论"))
    raise ValueError("无法解析任务主题：{}".format(label))


def build_daily_tasks(weekday, day=1, config=None):
    """返回某天（星期几）的任务列表 [(task_type, label, reminder_time), ...]。

    每天固定 3 主 + 4~5 辅；周一/三/五额外插入「数量关系插空」；
    16:00 固定错题复盘/当日重点整理，19:00 新闻联播，19:30 创作；
    冲刺阶段（默认第 61 天起）行测转向套题模考、申论转向套题。
    """
    cfg = normalize_plan_config(config)
    stages = cfg["stages"]
    module_a, module_b, shenlun = WEEK_TEMPLATE[weekday]
    if shenlun == "申论小题":
        shenlun = _shenlun_for_day(day)
    sprint_start = 61
    for s in stages:
        if "模考" in s["name"] or "冲刺" in s["name"]:
            sprint_start = s["day_start"]
            break
    else:
        if len(stages) >= 3:
            sprint_start = stages[-1]["day_start"]
        else:
            sprint_start = max(1, int(cfg["total_days"] * 2 / 3))
    if day >= sprint_start:
        if weekday in (0, 2, 4):     # 周一/三/五 行测套题
            module_a = "行测套题"
        if weekday in (1, 3):        # 周二/四 申论套题
            shenlun = "申论套题"
    tasks = [
        ("aux", "政治理论·常识积累", "09:00"),
        ("main", module_a, "09:30"),
        ("main", module_b, "11:00"),
        ("main", shenlun, "13:30"),
    ]
    if weekday in (0, 2, 4):  # 周一/三/五 数量插空
        tasks.insert(4, ("aux", "数量", "15:00"))
    review_label = "当日重点整理" if weekday == 6 else "错题复盘"
    tasks.extend([
        ("aux", review_label, "16:00"),
        ("aux", "新闻联播", "19:00"),
        ("aux", "创作", "19:30"),
    ])
    return tasks


# 判断推理课程推进：花生判断 13 讲 → 全题型练习 → 某笔专项 → 限时
JUDGE_SPECIAL = [
    "某笔专项·空间类①（三视图+立体拼合）",
    "某笔专项·空间类②（截面图+多面体折叠）",
    "某笔专项·图形中的黑白块",
    "某笔专项·逻辑判断-真假推理",
    "某笔专项·逻辑判断-集合推理",
    "某笔专项·推理形式及逻辑错误",
]


def _judge_note(count):
    """判断课程进度文案（count=第几次判断 A 槽）。"""
    if count <= 13:
        return "花生判断第{:02d}讲 + 例题重做".format(count)
    if count <= 17:
        return "判断全题型练习20题（限时）"
    idx = (count - 18) % len(JUDGE_SPECIAL)
    return JUDGE_SPECIAL[idx] + " + 配套练习"


def _sh_type_name(shenlun):
    """申论题型的中文名（用于文案）。"""
    return {
        "归纳概括": "归纳概括",
        "提出对策": "提出对策",
        "综合分析": "综合分析",
        "公文写作": "公文写作",
        "申论小题": "申论小题",
        "大作文": "大作文",
        "申论套题": "申论套题",
    }.get(shenlun, shenlun)


def generate_90day_plan(db, start_date, overwrite=False, progress_cb=None, cancel_cb=None,
                         delay=0.0, config=None):
    """一键铺排计划（默认 90 天，可按配置自定义）。

    - 逐日创建计划（标题含第 N 天 / 第 W 周 / 阶段 / 当日主任务摘要），
      每条任务带具体内容备注（课程节次、题量、限时标准）；
    - 已有计划的日期：overwrite=False 时跳过，True 时先删除再重建；
    - 结束后写入 plan_start_date 设置；
    - delay>0 时每铺排一天 sleep(delay) 秒，便于界面实时显示进度（测试时传 0）。
    返回统计 dict。
    """
    cfg = normalize_plan_config(config)
    total_days = cfg["total_days"]
    stages = cfg["stages"]
    created_days = skipped_days = created_items = 0
    end = start_date + timedelta(days=total_days - 1)
    topic_cache = {}
    judge_count = 0
    num_count = 0

    def resolve_label(label, day):
        key = (label, day % 2)
        if key not in topic_cache:
            topic_cache[key] = resolve_topic(db, label, day)
        return topic_cache[key]

    for day in range(1, total_days + 1):
        if cancel_cb and cancel_cb():
            break
        d = start_date + timedelta(days=day - 1)
        day_str = d.isoformat()
        existing_plan = db.get_plan(day_str)
        if existing_plan:
            if not overwrite:
                skipped_days += 1
                if progress_cb:
                    progress_cb(day, "跳过已有")
                if delay:
                    time.sleep(delay)
                continue
            db.delete_plan(existing_plan["id"])
        weekday = d.weekday()
        week_idx = (day - 1) // 7 + 1
        stage = stage_for(day, stages)
        stage_tag = {
            "基础奠基": "基础奠基",
            "专项强化": "专项强化·限时",
            "模考冲刺": "模考冲刺·套题",
        }.get(stage["name"] if stage else "", stage["name"] if stage else "")

        spec = build_daily_tasks(weekday, day, cfg)
        # 生成每条任务的具体备注
        entries = []
        labels = []
        for task_type, label, remind in spec:
            if label == "判断":
                judge_count += 1
                note = _judge_note(judge_count)
            elif label == "数量":
                num_count += 1
                note = ("花生数量第{:02d}讲 + 当天题型10题".format(num_count) if num_count <= 22
                        else "数量限时练习10题（8分钟）")
            elif label in ("资料", "资料保温"):
                note = "20题限时{} + 公式默写".format("25分钟" if day <= 28 else "20分钟")
            elif label == "言语":
                note = "20题限时{} + 成语积累10个".format("20分钟" if day <= 35 else "18分钟")
            elif label in ("归纳概括", "提出对策", "综合分析", "公文写作", "申论小题"):
                note = "袁东·{}方法课 + {}1题".format(_sh_type_name(label), _sh_type_name(label))
            elif label == "大作文":
                note = "大作文日：20分钟学方法列提纲 + 70分钟动笔"
            elif label == "申论套题":
                note = "申论套题（限时150分钟）"
            elif label == "全模块小测":
                note = "行测全模块限时测（120分钟）"
            elif label == "行测套题":
                note = "行测套题（限时120分钟）+ 涂卡"
            elif label == "错题复盘":
                note = "错题ABCD分类 + 当日重点整理 + 方法本整理"
            elif label == "当日重点整理":
                note = "当日重点整理 + 方法本整理"
            elif label == "新闻联播":
                note = "收听新闻联播 + 记录时政要点"
            elif label == "创作":
                note = "ComfyUI / 软件编程创作（自由创作 2 小时）"
            elif label == "自由补弱":
                note = "薄弱模块自由补强"
            elif label == "政治理论·常识积累":
                note = "小黑课1节 + 要点笔记" if weekday in (0, 2, 4) else "背诵清单挖空版 + 睡前复习"
            else:
                note = ""
            entries.append((resolve_label(label, day), remind, task_type, note))
            labels.append(label)

        title = "第 {} 天 · W{} 周".format(day, week_idx)
        if stage_tag:
            title += " · " + stage_tag
        plan_id = db.create_plan(day_str, title=title)
        # 插入带备注的任务
        now = datetime_now()
        rows = [
            (plan_id, topic_id, remind, task_type, note, now)
            for topic_id, remind, task_type, note in entries
        ]
        db.conn.executemany(
            "INSERT INTO plan_items(plan_id, topic_id, reminder_time, task_type, note, created_at) "
            "VALUES (?,?,?,?,?,?)",
            rows,
        )
        db.conn.commit()
        created_items += len(rows)
        created_days += 1
        if progress_cb:
            progress_cb(day, None)
        if delay:
            time.sleep(delay)
    db.set_setting("plan_start_date", start_date.isoformat())
    return {
        "created_days": created_days,
        "skipped_days": skipped_days,
        "created_items": created_items,
        "end": end.isoformat(),
    }
