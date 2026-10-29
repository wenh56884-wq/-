# agents/tools.py
# 职责：Agent 工具层——ctx 只能由后端（FastAPI）注入，工具内部不接受「查谁」的 id 参数
# 依赖：pymysql / duckdb / app.config / engine.warning / engine.profile / engine.store / engine.career_rules
# 说明：返回值一律是结构化 dict（禁止自然语言）；越权一律 PermissionError + 写 audit_log；
#       所有 SQL 带 tenant_id 条件；每条返回都带 engine_version / calc_version 便于 Critic 回查来源。

from __future__ import annotations

import json
import os
import re
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import pymysql

from agents.career import context as career_context
from app.config import Settings, get_settings
from engine import career_guide, competition, hybrid, job_search, profile, recommend, warning
from engine import forecast as forecast_engine      # 学业预测（绩点/挂科/等级走向）
from engine import grades as grades_engine          # 成绩聚合（纯函数）
from engine import kb_store, rag
from engine import kg as kg_engine                  # 知识图谱（专业-课程-岗位-技能）
from engine import question_bank as qbank           # 面试题库（与出题同源硬校验池）
from engine import web_search as web_engine
from engine import workflow as workflow_engine
from engine.career_rules import CAREER_ENGINE_VERSION
from engine.rules import LEVELS
from engine.store import DuckDBStore

# 工具层版本（随返回值下发，便于前端/Critic 溯源）
TOOLS_VERSION = "tools-v2"
# 角色常量
ACTOR_TEACHER = "teacher"
ACTOR_STUDENT = "student"
_ACTORS: tuple[str, ...] = (ACTOR_TEACHER, ACTOR_STUDENT)

# 方向词典（与 scripts\build_profile_raw.py 共用同一份 JSON，避免关键词两处漂移）
_DICT_PATH = Path(__file__).resolve().parents[1] / "rules" / "direction_keywords.json"

# 测试注入口：非空时审计条目同步写内存，便于断言（monkeypatch.setattr(tools, "AUDIT_SINK", [])）
AUDIT_SINK: list[dict[str, Any]] | None = None

# 升学/就业缺口的三类 DIM（教师端班级差距口径，与岗位推荐打分口径相互独立）
_GAP_DIMS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("实践/项目经历", ("项目", "实习", "工程实践", "实践经验"), "project_rate"),
    ("职业证书", ("证书", "资格证", "持证"), "cert_rate"),
    ("竞赛经历", ("竞赛", "比赛", "挑战杯"), "contest_rate"),
)


# ----------------------------------------------------------------
# 调用身份
# ----------------------------------------------------------------
@dataclass(frozen=True)
class ToolContext:
    """一次请求的调用身份：只能由 FastAPI 层从 JWT 解析后注入。

    student_id / teacher_id 是**内部主键**：工具不接受外部传入的「查谁」参数，
    学生端一律只用 ctx.student_id 查本人。
    """

    actor_type: str
    tenant_id: int
    student_id: int | None = None
    teacher_id: int | None = None
    term: str | None = None


def _check_ctx(ctx: Any) -> ToolContext:
    """校验 ctx 合法性：类型、角色、租户三缺一即拒绝。"""
    if not isinstance(ctx, ToolContext):
        raise TypeError("ctx 必须是 ToolContext，且只能由后端注入，禁止前端构造")
    if ctx.actor_type not in _ACTORS:
        raise PermissionError(f"未知调用角色：{ctx.actor_type}，可选 {_ACTORS}")
    if not ctx.tenant_id:
        raise PermissionError("ctx.tenant_id 缺失：多租户工具必须明确租户")
    return ctx


def _actor_id(ctx: ToolContext) -> int:
    """审计用的 actor_id（内部主键；缺失记 0，不得因缺 id 就不写审计）。"""
    raw = ctx.teacher_id if ctx.actor_type == ACTOR_TEACHER else ctx.student_id
    return int(raw) if raw else 0


# ----------------------------------------------------------------
# MySQL / 审计
# ----------------------------------------------------------------
def _connect(settings: Settings | None = None) -> pymysql.connections.Connection:
    s = settings or get_settings()
    return pymysql.connect(
        host=s.mysql_host,
        port=s.mysql_port,
        user=s.mysql_user,
        password=s.mysql_password,
        database=s.mysql_db,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=5,
    )


def _query(sql: str, params: Sequence[Any]) -> list[dict[str, Any]]:
    """带租户条件的查询统一入口；库不可用时返回空列表（由上层按空结果处理）。"""
    try:
        conn = _connect()
    except (pymysql.MySQLError, OSError) as exc:  # pragma: no cover - 依赖环境
        print(f"[tools] MySQL 连接失败：{exc}", file=sys.stderr)
        return []
    try:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            return [dict(r) for r in cur.fetchall()]
    except (pymysql.MySQLError, OSError) as exc:  # pragma: no cover - 依赖环境
        print(f"[tools] MySQL 查询失败：{exc}", file=sys.stderr)
        return []
    finally:
        conn.close()


def _write_raw(sql: str, params: Sequence[Any]) -> int:
    """写操作统一入口，返回影响行数；失败返回 0（审计失败不得影响主流程）。"""
    try:
        conn = _connect()
    except (pymysql.MySQLError, OSError) as exc:  # pragma: no cover - 依赖环境
        print(f"[tools] MySQL 连接失败：{exc}", file=sys.stderr)
        return 0
    try:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            conn.commit()
            return int(cur.rowcount)
    except (pymysql.MySQLError, OSError) as exc:  # pragma: no cover - 依赖环境
        print(f"[tools] MySQL 写入失败：{exc}", file=sys.stderr)
        return 0
    finally:
        conn.close()


def write_audit(
    *,
    actor_type: str,
    actor_id: int,
    action: str,
    target: str = "",
    detail: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """写一条 audit_log（actor / action / target / detail），失败不影响主流程。"""
    payload = {} if detail is None else dict(detail)
    entry = {
        "actor_type": str(actor_type),
        "actor_id": int(actor_id or 0),
        "action": str(action),
        "target": str(target or ""),
        "detail": payload,
    }
    if AUDIT_SINK is not None:
        AUDIT_SINK.append(dict(entry))
    _write_raw(
        "INSERT INTO `审计日志` (`操作者类型`, `操作者编号`, `动作`, `对象`, `详情`) "
        "VALUES (%s, %s, %s, %s, %s)",
        (
            entry["actor_type"],
            entry["actor_id"],
            entry["action"],
            entry["target"],
            json.dumps(payload, ensure_ascii=False),
        ),
    )
    return entry


def _audit_call(ctx: ToolContext, action: str, target: str = "",
                detail: Mapping[str, Any] | None = None) -> None:
    """正常调用的留痕。"""
    write_audit(actor_type=ctx.actor_type, actor_id=_actor_id(ctx),
                action=action, target=target, detail=detail)


def _deny(ctx: ToolContext, action: str, target: str, reason: str) -> None:
    """越权：先写审计再抛 PermissionError（**顺序不能反**，否则审计会丢）。"""
    write_audit(
        actor_type=ctx.actor_type,
        actor_id=_actor_id(ctx),
        action=f"{action}.denied",
        target=target,
        detail={"reason": reason},
    )
    raise PermissionError(f"{reason}（已记入审计：{action}.denied）")


# ----------------------------------------------------------------
# 鉴权：角色 / 归属
# ----------------------------------------------------------------
def _require_teacher(ctx: ToolContext, action: str, target: str) -> None:
    if ctx.actor_type != ACTOR_TEACHER:
        _deny(ctx, action, target, f"工具 {action} 仅限教师调用，越权已拦截")


def _require_student(ctx: ToolContext, action: str, target: str) -> None:
    if ctx.actor_type != ACTOR_STUDENT:
        _deny(ctx, action, target, f"工具 {action} 仅限学生本人调用，越权已拦截")
    if not ctx.student_id:
        _deny(ctx, action, target, "ctx.student_id 缺失，无法确定「本人」是谁")


def _nearby_classes(ctx: ToolContext, class_name: str, limit: int = 5) -> list[str]:
    """找与输入最相近的班级名，供「你是不是想找 X」提示。

    为什么要这一步：把「AI220100」当成越权拒绝，用户只会看到一句拦人话，
    却不知道正确写法是「AI2201」。给出候选比给一句报错有用得多。
    匹配规则：输入的字母前缀相同，或输入是候选的前缀（反之亦然）。
    """
    rows = _query(
        "SELECT DISTINCT s.`班级` AS class_name FROM `学生` s "
        "WHERE s.`租户编号` = %s ORDER BY s.`班级`",
        (ctx.tenant_id,),
    )
    names = [str(r.get("class_name") or "") for r in rows if r.get("class_name")]
    scope = _teacher_class_scope(ctx)
    if scope is not None:
        names = [name for name in names if name in scope]
    if not names:
        return []
    probe = str(class_name or "").strip().lower()
    if not probe:
        return names[:limit]

    import re as _re

    prefix = _re.match(r"[a-z]+", probe)
    pattern = prefix.group(0) if prefix else ""

    def rank(name: str) -> tuple[int, int, str]:
        low = name.lower()
        if low == probe:
            return (0, 0, low)
        # 一方是另一方的前缀（AI220100 / AI2201 这种多打几位最常见的错法）
        if low.startswith(probe) or probe.startswith(low):
            return (1, abs(len(low) - len(probe)), low)
        # 字母前缀相同（AI220100 vs AI2301）
        if pattern and low.startswith(pattern):
            return (2, abs(len(low) - len(probe)), low)
        # 公共前缀长度越长越像
        common = 0
        for a, b in zip(low, probe):
            if a != b:
                break
            common += 1
        return (3, -common, low)

    ranked = sorted(names, key=rank)
    # 只保留「真的像」的：同字母前缀，或共同前缀 >= 2 个字符。
    # 不加这一层的话，输入 ZZZZ999 也会硬推荐 AI2201，属于乱猜。
    picked = [n for n in ranked
              if (pattern and n.lower().startswith(pattern))
              or (len(n) >= 2 and len(probe) >= 2 and n.lower()[:2] == probe[:2])]
    return picked[:limit]


def _teacher_class_scope(ctx: ToolContext) -> set[str] | None:
    """教师任教班级集合；未配置任何绑定返回 None（兼容旧演示：租户范围）。

    为什么要 None 而不是空集合：空集合会让所有旧教师账号突然看不到任何班，
    破坏演示；只有显式配置过 teacher_class 的教师才收窄范围。
    """
    if ctx.actor_type != ACTOR_TEACHER:
        return None
    rows = _query(
        "SELECT `班级` AS class_name FROM `教师任教班级` "
        "WHERE `租户编号` = %s AND `教师编号` = %s ORDER BY `班级`",
        (ctx.tenant_id, int(ctx.teacher_id or 0)),
    )
    names = {str(row.get("class_name")) for row in rows if row.get("class_name")}
    return names or None


def _require_class(ctx: ToolContext, class_name: str, action: str) -> dict[str, Any]:
    """校验班级可访问。**三种情况分开处理**，不把「输错名字」当成越权。

    1) 本租户有该班        → 正常返回
    2) 该班只在别的租户存在 → 越权（403 + 审计 denied），这才是真的跨租户访问
    3) 任何租户都没有该班   → 参数错误（422 + 提示相近班级），不是安全问题

    为什么要分开：原来 2/3 都走 _deny（403「不属于当前租户」），
    用户把 AI2201 打成 AI220100 时会看到一句「越权」，既误导又污染审计日志。
    """
    rows = _query(
        "SELECT COUNT(DISTINCT s.`编号`) AS cnt FROM `学生` s "
        "WHERE s.`租户编号` = %s AND s.`班级` = %s",
        (ctx.tenant_id, class_name),
    )
    cnt = int(rows[0]["cnt"]) if rows else 0
    if cnt > 0:
        scope = _teacher_class_scope(ctx)
        if scope is not None and class_name not in scope:
            _deny(ctx, action, str(class_name),
                  f"班级 {class_name} 不在当前教师的任教范围内")
        return {"headcount": cnt}

    # 该班是否存在于其他租户？存在 → 真越权
    other = _query(
        "SELECT COUNT(DISTINCT s.`编号`) AS cnt FROM `学生` s "
        "WHERE s.`租户编号` <> %s AND s.`班级` = %s",
        (ctx.tenant_id, class_name),
    )
    other_cnt = int(other[0]["cnt"]) if other else 0
    if other_cnt > 0:
        # _deny 内部会抛 PermissionError，这里不会继续往下走
        _deny(ctx, action, str(class_name),
              f"班级 {class_name} 属于其他租户，跨租户访问已拦截")

    # 哪都没有 → 输错了，给候选而不是判越权
    nearby = _nearby_classes(ctx, class_name)
    hint = f"；你是不是想找：{'、'.join(nearby)}" if nearby else ""
    raise ValueError(
        f"班级「{class_name}」不存在（本租户没有这个班）{hint}"
    )


def _fetch_student(ctx: ToolContext, student_no: str, action: str) -> dict[str, Any]:
    """按学号取学生档案（带 tenant_id）；查不到即视为跨租户。"""
    rows = _query(
        "SELECT s.`学号` AS student_no, s.`姓名` AS name, s.`专业` AS major, "
        "       s.`班级` AS class_name, s.`编号` AS student_id, s.`学院` AS college, "
        "       s.`入学年份` AS enroll_year "
        "FROM `学生` s WHERE s.`租户编号` = %s AND s.`学号` = %s",
        (ctx.tenant_id, student_no),
    )
    if not rows:
        _deny(ctx, action, str(student_no),
              f"学生 {student_no} 不属于当前租户")
    item = dict(rows[0])
    item["student_no"] = str(item["student_no"])
    if ctx.actor_type == ACTOR_TEACHER:
        scope = _teacher_class_scope(ctx)
        class_name = str(item.get("class_name") or "")
        if scope is not None and class_name not in scope:
            _deny(ctx, action, str(student_no),
                  f"学生 {student_no} 的班级不在当前教师的任教范围内")
    return item


def _resolve_self(ctx: ToolContext, action: str) -> dict[str, Any]:
    """学生端：把 ctx.student_id 解析成本人学号（带 tenant_id 兜底校验）。"""
    rows = _query(
        "SELECT s.`学号` AS student_no, s.`姓名` AS name, s.`专业` AS major, "
        "       s.`班级` AS class_name, s.`入学年份` AS enroll_year "
        "FROM `学生` s WHERE s.`租户编号` = %s AND s.`编号` = %s",
        (ctx.tenant_id, ctx.student_id),
    )
    if not rows:
        _deny(ctx, action, str(ctx.student_id),
              f"student_id={ctx.student_id} 不属于当前租户")
    item = dict(rows[0])
    item["student_no"] = str(item["student_no"])
    item["student_id"] = int(ctx.student_id or 0)
    return item


def _resolve_term(ctx: ToolContext, term: str | None) -> str:
    """参数缺省行为：显式 term > ctx.term > 该租户最新有成绩的学期。"""
    if term:
        return str(term)
    if ctx.term:
        return str(ctx.term)
    rows = _query(
        "SELECT sc.`学期` AS term FROM `成绩` sc "
        "JOIN `学生` s ON s.`编号` = sc.`学生编号` AND s.`租户编号` = %s "
        "GROUP BY sc.`学期` ORDER BY sc.`学期` DESC LIMIT 1",
        (ctx.tenant_id,),
    )
    return str(rows[0]["term"]) if rows else ""


# ----------------------------------------------------------------
# 方向词典 / 画像回算 / DuckDB
# ----------------------------------------------------------------
_DIR_CACHE: tuple[tuple[tuple[str, tuple[str, ...]], ...], str] | None = None


def _load_directions() -> tuple[tuple[tuple[str, tuple[str, ...]], ...], str]:
    data = json.loads(_DICT_PATH.read_text(encoding="utf-8"))
    directions = tuple(
        (str(d["name"]), tuple(str(k) for k in d["keywords"])) for d in data["directions"]
    )
    return directions, str(data.get("fallback", "其他"))


def direction_of(title: Any) -> str:
    """岗位标题 → 方向（顺序敏感，同一份 JSON；匹配不上归 fallback）。"""
    global _DIR_CACHE
    if _DIR_CACHE is None:
        _DIR_CACHE = _load_directions()
    directions, fallback = _DIR_CACHE
    text = str(title or "").lower()
    for name, keywords in directions:
        if any(k.lower() in text for k in keywords):
            return name
    return fallback


_STORED_TO_RAW: tuple[tuple[str, str], ...] = (
    ("gpa", "gpa"), ("gpa_trend", "gpa_trend"), ("fail_count", "fail_count"),
    ("class_rank_pct", "class_rank_pct"), ("major_rank_pct", "major_rank_pct"),
    ("attendance_rate", "attendance_rate"),
    ("library_visit_cnt", "library_visit_cnt"),
    ("library_activity", "library_activity"),
    ("consumption_regularity", "consumption_regularity"),
    ("course_pref", "course_pref"), ("job_view_cnt", "job_view_cnt"),
    ("job_favorite_cnt", "job_favorite_cnt"),
    ("cert_count", "cert_count"), ("contest_count", "contest_count"),
    ("project_cnt", "project_cnt"),
)


def _rebuild_features(stored: Mapping[str, Any]) -> dict[str, Any] | None:
    """用落库行回算四维画像（None 键一律不下传，保持「缺失不冒充」）。"""
    if not stored:
        return None
    raw: dict[str, Any] = {"student_no": stored.get("student_no"),
                           "term": stored.get("term")}
    for col, key in _STORED_TO_RAW:
        value = stored.get(col)
        if value is not None:
            raw[key] = value
    return profile.build_features(raw)


def read_features(term: str, student_nos: Sequence[str]) -> list[dict[str, Any]]:
    """一次取多名学生的画像落库行（只按学号过滤，学号集合来自已鉴权的 MySQL 结果）。

    走批量读取：逐人读取每人都会新开一次 DuckDB 连接（580 人约 5.8 秒），
    这里一次 IN 查询取回，结果与逐条读取一致。
    """
    nos = [str(s) for s in student_nos if s]
    if not nos:
        return []
    return [dict(row) for row in DuckDBStore().read_student_features(nos, term)]


# ----------------------------------------------------------------
# 教师端工具
# ----------------------------------------------------------------
def class_list(ctx: ToolContext) -> dict[str, Any]:
    """教师端班级/学院目录：本租户 student 表按 学院 → 班级 → 专业 分组的名册。

    权限说明：teacher 表没有「任教班级」绑定关系，所以可见范围 = 本租户全部班级，
    与其余教师端工具一致地只做 tenant_id 隔离；更细的任教授权待有绑定表后再加。
    """
    ctx = _check_ctx(ctx)
    _require_teacher(ctx, "class_list", "all")
    scope = _teacher_class_scope(ctx)
    rows = _query(
        "SELECT s.`学院` AS college, s.`班级` AS class_name, s.`专业` AS major, "
        "       COUNT(DISTINCT s.`编号`) AS headcount "
        "FROM `学生` s WHERE s.`租户编号` = %s "
        "GROUP BY s.`学院`, s.`班级`, s.`专业` "
        "ORDER BY s.`学院`, s.`班级`, s.`专业`",
        (ctx.tenant_id,),
    )
    if scope is not None:
        rows = [row for row in rows if str(row.get("class_name") or "") in scope]

    classes: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = str(row.get("class_name") or "")
        item = classes.setdefault(
            name,
            {"class_name": name, "college": str(row.get("college") or ""),
             "majors": [], "headcount": 0},
        )
        item["headcount"] += int(row.get("headcount") or 0)
        major = str(row.get("major") or "")
        if major and major not in item["majors"]:
            item["majors"].append(major)

    class_rows = [classes[key] for key in sorted(classes)]
    colleges: dict[str, dict[str, Any]] = {}
    for item in class_rows:
        entry = colleges.setdefault(
            item["college"] or "未分配学院",
            {"college": item["college"] or "未分配学院", "class_cnt": 0,
             "student_cnt": 0, "majors": []},
        )
        entry["class_cnt"] += 1
        entry["student_cnt"] += int(item["headcount"])
        for major in item["majors"]:
            if major not in entry["majors"]:
                entry["majors"].append(major)

    # 专业层（学院 → 专业 → 班级 三级级联用）：人数按 (学院, 专业) 精确求和，
    # 班级名取自原始分组，不做任何推断
    major_index: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        college_name = str(row.get("college") or "") or "未分配学院"
        major_name = str(row.get("major") or "") or "未分配专业"
        entry = major_index.setdefault(
            (college_name, major_name),
            {"college": college_name, "major": major_name, "class_cnt": 0,
             "student_cnt": 0, "classes": []},
        )
        entry["student_cnt"] += int(row.get("headcount") or 0)
        class_name = str(row.get("class_name") or "")
        if class_name and class_name not in entry["classes"]:
            entry["classes"].append(class_name)
    for entry in major_index.values():
        entry["classes"] = sorted(entry["classes"])
        entry["class_cnt"] = len(entry["classes"])

    major_rows = [major_index[key] for key in sorted(major_index)]

    _audit_call(ctx, "class_list", "all",
                {"class_cnt": len(class_rows), "college_cnt": len(colleges),
                 "major_cnt": len(major_rows)})
    return {
        "tenant_id": int(ctx.tenant_id),
        "source": "mysql.student",
        "class_cnt": len(class_rows),
        "student_cnt": sum(int(item["headcount"]) for item in class_rows),
        "classes": class_rows,
        "colleges": [colleges[key] for key in sorted(colleges)],
        "majors": major_rows,
        "major_cnt": len(major_rows),
        "scope": "assigned" if scope is not None else "tenant",
        "assigned_class_cnt": len(scope) if scope is not None else 0,
        "note": ("班级范围 = 任教班级" if scope is not None
                 else "未配置任教班级，回退本租户全部班级"),
        "tools_version": TOOLS_VERSION,
    }


# ----------------------------------------------------------------
# 班级级预警阈值（教师按班配置；未覆盖的指标回退租户默认）
# ----------------------------------------------------------------
THRESHOLD_METRICS: tuple[str, ...] = (
    "fail_count", "gpa_drop", "gpa_drop_slope", "attendance_rate", "level",
)


def _threshold_snapshot(ctx: ToolContext, class_name: str) -> dict[str, Any]:
    """把有效规则展开成前端可直接编辑的行。"""
    rules = warning.get_rules(ctx.tenant_id, class_name)
    tenant_metrics = {
        str(row.get("metric")) for row in warning.fetch_threshold_rows(ctx.tenant_id)
    }
    class_metrics = {
        str(row.get("metric"))
        for row in warning.fetch_class_threshold_rows(ctx.tenant_id, class_name)
    }

    def source(metric: str) -> str:
        if metric in class_metrics:
            return "class"
        if metric in tenant_metrics:
            return "tenant"
        return "default"

    rows = [
        {"metric": "fail_count", "label": "挂科门次",
         "weight": rules.fail_count.weight,
         "yellow_value": rules.fail_count.score_1,
         "orange_value": rules.fail_count.score_2,
         "red_value": rules.fail_count.score_3},
        {"metric": "gpa_drop", "label": "均分下滑",
         "weight": rules.gpa_drop.weight,
         "yellow_value": rules.gpa_drop.start,
         "orange_value": rules.gpa_drop.base,
         "red_value": rules.gpa_drop.ceiling},
        {"metric": "gpa_drop_slope", "label": "下滑斜率",
         "weight": None,
         "yellow_value": rules.gpa_drop.slope,
         "orange_value": None,
         "red_value": None},
        {"metric": "attendance_rate", "label": "出勤率",
         "weight": rules.attendance.weight,
         "yellow_value": rules.attendance.start,
         "orange_value": rules.attendance.floor,
         "red_value": rules.attendance.ceiling},
        {"metric": "level", "label": "分级门槛",
         "weight": None,
         "yellow_value": rules.level.yellow,
         "orange_value": rules.level.orange,
         "red_value": rules.level.red},
    ]
    for row in rows:
        row["source"] = source(str(row["metric"]))
    return {
        "class_name": str(class_name),
        "thresholds": rows,
        "tenant_override_metrics": sorted(tenant_metrics),
        "class_override_metrics": sorted(class_metrics),
        "note": "班级覆盖 > 租户默认 > 引擎内置默认；留空表示回退上一级。",
        "engine_version": warning.ENGINE_VERSION,
        "tools_version": TOOLS_VERSION,
    }


def _replace_class_thresholds(
    tenant_id: int,
    class_name: str,
    rows: Sequence[tuple[str, float | None, float | None, float | None, float | None]],
) -> None:
    """整体替换某班的阈值覆盖（先删后插，事务提交）。"""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM `班级预警阈值` "
                "WHERE `租户编号` = %s AND `班级` = %s",
                (tenant_id, class_name),
            )
            for metric, weight, red, orange, yellow in rows:
                cur.execute(
                    "INSERT INTO `班级预警阈值` "
                    "(`租户编号`, `班级`, `指标`, `权重`, `红色阈值`, `橙色阈值`, `黄色阈值`) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (tenant_id, class_name, metric, weight, red, orange, yellow),
                )
        conn.commit()
    finally:
        conn.close()


def get_warning_thresholds(ctx: ToolContext, class_name: str) -> dict[str, Any]:
    """读取某班的有效阈值（含来源：class/tenant/default）。"""
    ctx = _check_ctx(ctx)
    _require_teacher(ctx, "get_warning_thresholds", str(class_name))
    _require_class(ctx, class_name, "get_warning_thresholds")
    snapshot = _threshold_snapshot(ctx, class_name)
    _audit_call(ctx, "get_warning_thresholds", str(class_name))
    return snapshot


def save_warning_thresholds(
    ctx: ToolContext,
    class_name: str,
    thresholds: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """整体替换某班阈值；只接受 THRESHOLD_METRICS，空值表示回退。"""
    ctx = _check_ctx(ctx)
    _require_teacher(ctx, "save_warning_thresholds", str(class_name))
    _require_class(ctx, class_name, "save_warning_thresholds")

    allowed = set(THRESHOLD_METRICS)
    clean: dict[str, dict[str, float | None]] = {}
    for item in thresholds:
        metric = str(item.get("metric") or "").strip()
        if metric not in allowed:
            raise ValueError(f"非法阈值指标：{metric}，可选 {THRESHOLD_METRICS}")
        values: dict[str, float | None] = {}
        for key in ("weight", "yellow_value", "orange_value", "red_value"):
            raw = item.get(key)
            if raw is None or str(raw).strip() == "":
                values[key] = None
                continue
            try:
                number = float(raw)
            except (TypeError, ValueError):
                raise ValueError(f"{metric}.{key} 必须是数字")
            if number < 0:
                raise ValueError(f"{metric}.{key} 不能为负数")
            values[key] = number
        clean[metric] = values

    rows: list[tuple[str, float | None, float | None, float | None, float | None]] = []
    for metric, values in clean.items():
        if all(values[key] is None for key in values):
            continue
        rows.append((
            metric,
            values["weight"],
            values["red_value"],
            values["orange_value"],
            values["yellow_value"],
        ))
    _replace_class_thresholds(ctx.tenant_id, str(class_name), rows)
    _audit_call(ctx, "save_warning_thresholds", str(class_name),
                {"metrics": [row[0] for row in rows]})
    return _threshold_snapshot(ctx, str(class_name))


def class_overview(ctx: ToolContext, class_name: str, term: str) -> dict[str, Any]:
    """班级概貌：人数 / 均分 / 挂科率 / 预警分布 / 就业意向分布。"""
    ctx = _check_ctx(ctx)
    _require_teacher(ctx, "class_overview", str(class_name))
    term = _resolve_term(ctx, term)
    roster = _require_class(ctx, class_name, "class_overview")

    agg_rows = _query(
        "SELECT COUNT(*) AS headcount, "
        "       SUM(t.fail_cnt >= 1) AS fail_students, "
        "       SUM(t.fail_cnt) AS fail_courses, "
        "       AVG(t.gpa) AS avg_gpa "
        "FROM ("
        "  SELECT s.`学号` AS student_no, AVG(sc.`分数`) AS gpa, "
        "         SUM(CASE WHEN sc.`分数` < 60 THEN 1 ELSE 0 END) AS fail_cnt "
        "  FROM `学生` s "
        "  JOIN `成绩` sc ON sc.`学生编号` = s.`编号` AND sc.`学期` = %s "
        "  WHERE s.`租户编号` = %s AND s.`班级` = %s "
        "  GROUP BY s.`学号`"
        ") t",
        (term, ctx.tenant_id, class_name),
    )
    agg = agg_rows[0] if agg_rows else {}
    headcount = int(agg.get("headcount") or 0)
    avg_gpa = None if agg.get("avg_gpa") is None else round(float(agg["avg_gpa"]), 2)
    fail_students = int(agg.get("fail_students") or 0)
    fail_courses = int(agg.get("fail_courses") or 0)
    fail_rate = None if headcount == 0 else round(fail_students / headcount, 4)

    distribution = {level: 0 for level in LEVELS}
    top5: list[dict[str, Any]] = []
    results = warning.compute_class(ctx.tenant_id, class_name, term) if headcount else []
    for item in results:
        level = str(item.get("level"))
        distribution[level] = distribution.get(level, 0) + 1
    for item in sorted(results, key=lambda x: (-x["risk_score"], x["student_no"]))[:5]:
        top5.append({
            "student_no": item["student_no"], "name": item["name"],
            "risk_score": item["risk_score"], "level": item["level"],
            "coverage": item.get("coverage"),
        })

    _audit_call(ctx, "class_overview", f"{class_name}/{term}",
                {"headcount": headcount, "roster": roster["headcount"]})
    return {
        "class_name": str(class_name),
        "term": term,
        "headcount": headcount,
        "roster_count": roster["headcount"],
        "avg_gpa": avg_gpa,
        "fail_students": fail_students,
        "fail_courses": fail_courses,
        "fail_rate": fail_rate,
        "warning_distribution": distribution,
        "top_risk_students": top5,
        "employment_intent": _employment_intent(ctx, class_name, term),
        "career_intent": _career_intent_distribution(ctx, class_name),
        "engine_version": warning.ENGINE_VERSION,
        "calc_version": profile.CALC_VERSION,
        "tools_version": TOOLS_VERSION,
    }


def _career_intent_distribution(ctx: ToolContext, class_name: str) -> dict[str, Any]:
    """本班学生职业目标分布：考公/考研/考编/就业 + 未填写（按学生数，不按成绩行）。

    口径：以 student 表在册人数为分母；没有选择目标的学生计入「未填写」，
    不用 0 冒充，也不把未填写从分母里剔除。
    """
    rows = _query(
        "SELECT COALESCE(ci.`意向`, '未填写') AS intent, COUNT(*) AS cnt "
        "FROM `学生` s "
        "LEFT JOIN `职业意向` ci "
        "       ON ci.`学生编号` = s.`编号` AND ci.`租户编号` = s.`租户编号` "
        "WHERE s.`租户编号` = %s AND s.`班级` = %s "
        "GROUP BY COALESCE(ci.`意向`, '未填写')",
        (ctx.tenant_id, class_name),
    )
    distribution = {intent: 0 for intent in career_guide.INTENTS}
    distribution["未填写"] = 0
    for row in rows:
        key = str(row.get("intent") or "未填写")
        if key not in distribution:
            key = "未填写"  # 脏数据不新增未知档位
        distribution[key] += int(row.get("cnt") or 0)

    total = sum(distribution.values())
    filled = total - distribution["未填写"]
    return {
        "distribution": distribution,
        "total": total,
        "filled": filled,
        "unfilled": distribution["未填写"],
        "fill_rate": round(filled / total, 4) if total else None,
    }


def _employment_intent(ctx: ToolContext, class_name: str, term: str) -> dict[str, Any]:
    """就业意向：本班浏览/收藏过的岗位按方向聚合（取前 5）。"""
    rows = _query(
        "SELECT j.`岗位名称` AS title, COUNT(*) AS cnt "
        "FROM `岗位浏览日志` v "
        "JOIN `学生` s ON s.`编号` = v.`学生编号` AND s.`租户编号` = %s "
        "JOIN `岗位` j ON j.`编号` = v.`岗位编号` "
        "WHERE v.`学期` = %s AND s.`班级` = %s "
        "GROUP BY j.`岗位名称`",
        (ctx.tenant_id, term, class_name),
    )
    counter: dict[str, int] = {}
    for row in rows:
        direction = direction_of(row.get("title"))
        counter[direction] = counter.get(direction, 0) + int(row.get("cnt") or 0)
    total = sum(counter.values())
    top = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
    return {
        "view_total": total,
        "top_directions": [
            {"direction": d, "views": c, "rate": round(c / total, 4) if total else None}
            for d, c in top
        ],
    }


def student_profile(ctx: ToolContext, student_no: str, term: str) -> dict[str, Any]:
    """单个学生的四维画像 + 标签 + 成绩趋势（画像读 DuckDB 落库行后回算）。"""
    ctx = _check_ctx(ctx)
    _require_teacher(ctx, "student_profile", str(student_no))
    term = _resolve_term(ctx, term)
    stu = _fetch_student(ctx, student_no, "student_profile")

    stored_rows = read_features(term, [str(student_no)])
    stored = stored_rows[0] if stored_rows else {}
    features = _rebuild_features(stored)

    _audit_call(ctx, "student_profile", f"{student_no}/{term}")
    return {
        "student_no": str(student_no),
        "name": str(stu.get("name") or ""),
        "college": str(stu.get("college") or ""),
        "major": str(stu.get("major") or ""),
        "class_name": str(stu.get("class_name") or ""),
        "grade": career_guide.grade_label(stu.get("enroll_year")),
        "term": term,
        "has_data": bool(stored),
        "tags": stored.get("tags") or [],
        "extreme_decline": stored.get("extreme_decline"),
        "dimensions": {
            dim: None if features is None else features[dim]["score"]
            for dim in ("study", "behavior", "interest", "ability")
        },
        "gpa_trend_series": _gpa_series(ctx, str(student_no)),
        "stored": {
            key: stored.get(key) for key in
            ("gpa", "gpa_trend", "fail_count", "class_rank_pct", "major_rank_pct",
             "attendance_rate", "library_visit_cnt", "library_activity",
             "cert_count", "contest_count", "project_cnt", "course_pref")
        },
        "source": "duckdb.student_feature" if stored else "none",
        "engine_version": TOOLS_VERSION,
        "calc_version": stored.get("calc_version") or profile.CALC_VERSION,
        "tools_version": TOOLS_VERSION,
    }


def _gpa_series(ctx: ToolContext, student_no: str) -> list[dict[str, Any]]:
    """该生逐学期均分（升序），用于前端画趋势线。"""
    rows = _query(
        "SELECT sc.`学期` AS term, AVG(sc.`分数`) AS gpa "
        "FROM `成绩` sc "
        "JOIN `学生` s ON s.`编号` = sc.`学生编号` AND s.`租户编号` = %s "
        "WHERE s.`学号` = %s "
        "GROUP BY sc.`学期` ORDER BY sc.`学期`",
        (ctx.tenant_id, student_no),
    )
    return [{"term": str(r["term"]),
             "gpa": None if r["gpa"] is None else round(float(r["gpa"]), 2)}
            for r in rows]


def warning_list(ctx: ToolContext, class_name: str, term: str,
                 level: str | None = None) -> dict[str, Any]:
    """班级预警名单（调预警引擎）；level 为空返回全班，非法等级抛 ValueError。"""
    ctx = _check_ctx(ctx)
    _require_teacher(ctx, "warning_list", str(class_name))
    term = _resolve_term(ctx, term)
    _require_class(ctx, class_name, "warning_list")

    results = warning.compute_class(ctx.tenant_id, class_name, term)
    # level 支持单值或逗号分隔多值（如 "red,orange,yellow"），解析校验在引擎层
    levels = warning.parse_levels(level)
    items = [
        {
            "student_no": r["student_no"], "name": r["name"],
            "risk_score": r["risk_score"], "level": r["level"],
            "reasons": r["reasons"], "coverage": r["coverage"],
            "missing": r["missing"],
        }
        for r in results
        if levels is None or r["level"] in levels
    ]
    distribution = {lv: sum(1 for r in results if r["level"] == lv) for lv in LEVELS}
    _audit_call(ctx, "warning_list", f"{class_name}/{term}",
                {"level": level or "all", "count": len(items)})
    return {
        "class_name": str(class_name),
        "term": term,
        "level": level,
        "count": len(items),
        "distribution": distribution,
        "items": items,
        "engine_version": warning.ENGINE_VERSION,
        "calc_version": profile.CALC_VERSION,
        "tools_version": TOOLS_VERSION,
    }


def career_gap(ctx: ToolContext, class_name: str, term: str) -> dict[str, Any]:
    """班级能力结构 vs 目标岗位需求差距（规则版班级口径）。

    目标方向 = 本班浏览最多的岗位方向；岗位侧需求取本班浏览过的该类岗位；
    缺口口径：需求侧出现对应关键词的岗位占比 − 班级侧具备该项经历的人数占比。
    """
    ctx = _check_ctx(ctx)
    _require_teacher(ctx, "career_gap", str(class_name))
    term = _resolve_term(ctx, term)
    _require_class(ctx, class_name, "career_gap")

    roster = _query(
        "SELECT s.`学号` AS student_no FROM `学生` s "
        "WHERE s.`租户编号` = %s AND s.`班级` = %s "
        "ORDER BY s.`学号`",
        (ctx.tenant_id, class_name),
    )
    student_nos = [str(r["student_no"]) for r in roster]
    features_rows = read_features(term, student_nos)
    sample = len(features_rows)

    def _rate(key: str, threshold: float = 1.0) -> float | None:
        if not sample:
            return None
        hit = sum(1 for r in features_rows if (r.get(key) or 0) >= threshold)
        return round(hit / sample, 4)

    ability = {
        "sample": sample,
        "cert_rate": _rate("cert_count"),
        "contest_rate": _rate("contest_count"),
        "project_rate": _rate("project_cnt"),
        "cert_avg": _avg(features_rows, "cert_count"),
        "contest_avg": _avg(features_rows, "contest_count"),
        "project_avg": _avg(features_rows, "project_cnt"),
        "gpa_avg": _avg(features_rows, "gpa"),
    }

    intent = _employment_intent(ctx, class_name, term)
    target = intent["top_directions"][0]["direction"] if intent["top_directions"] else None
    demand = _job_demand(ctx, class_name, term, target)

    gaps: list[dict[str, Any]] = []
    for dim_name, keywords, rate_key in _GAP_DIMS:
        class_rate = ability.get(rate_key)
        demand_rate = demand.get("keyword_rates", {}).get(dim_name)
        if class_rate is None or demand_rate is None:
            gaps.append({"dimension": dim_name, "class_rate": class_rate,
                         "demand_rate": demand_rate, "shortfall": None,
                         "level": "unknown"})
            continue
        shortfall = round(demand_rate - class_rate, 4)
        gaps.append({
            "dimension": dim_name, "class_rate": class_rate,
            "demand_rate": demand_rate, "shortfall": shortfall,
            "level": "red" if shortfall >= 0.30 else ("orange" if shortfall >= 0.10 else "none"),
        })

    _audit_call(ctx, "career_gap", f"{class_name}/{term}",
                {"target_direction": target, "sample": sample})
    return {
        "class_name": str(class_name),
        "term": term,
        "target_direction": target,
        "class_ability": ability,
        "job_demand": demand,
        "gaps": gaps,
        "note": "规则版缺口（需求侧关键词出现率 − 班级具备率）；与个人推荐打分口径相互独立",
        "engine_version": CAREER_ENGINE_VERSION,
        "calc_version": profile.CALC_VERSION,
        "tools_version": TOOLS_VERSION,
    }


def _avg(rows: Sequence[Mapping[str, Any]], key: str) -> float | None:
    values = [float(r[key]) for r in rows if r.get(key) is not None]
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _job_demand(ctx: ToolContext, class_name: str, term: str,
                target: str | None) -> dict[str, Any]:
    """本班浏览过的、属于目标方向的岗位：薪资/经验/学历要求 + 关键词 Prevalence。"""
    if not target:
        return {"sample_jobs": 0, "keyword_rates": {}, "top_skills": [],
                "education_top": [], "salary_range": None, "avg_exp_min": None}
    keywords = ()
    directions, _ = _DIR_CACHE or _load_directions()
    for name, kws in directions:
        if name == target:
            keywords = kws
            break
    if not keywords:
        return {"sample_jobs": 0, "keyword_rates": {}, "top_skills": [],
                "education_top": [], "salary_range": None, "avg_exp_min": None}

    rows = _query(
        "SELECT j.`岗位名称` AS title, j.`最低薪资` AS salary_min, "
        "       j.`最高薪资` AS salary_max, "
        "       j.`最低经验` AS exp_min, j.`学历` AS education, "
        "       j.`技能标签` AS skill_tags, j.`岗位描述` AS description "
        "FROM `岗位浏览日志` v "
        "JOIN `学生` s ON s.`编号` = v.`学生编号` AND s.`租户编号` = %s "
        "JOIN `岗位` j ON j.`编号` = v.`岗位编号` "
        "WHERE v.`学期` = %s AND s.`班级` = %s",
        (ctx.tenant_id, term, class_name),
    )
    # direction_of 原样逐行调用：2 万条浏览记录 ×（15 个方向 × 20 个关键词）的匹配，
    # 而岗位名去重后不过千余个。同一次调用内缓存，结果与逐行调用完全一致，不改口径。
    dir_cache: dict[str, str] = {}

    def _direction(title: Any) -> str:
        key = str(title or "")
        cached = dir_cache.get(key)
        if cached is None:
            cached = direction_of(key)
            dir_cache[key] = cached
        return cached

    jobs = [r for r in rows if _direction(r.get("title")) == target]
    total = len(jobs)
    skill_counter: dict[str, int] = {}
    edu_counter: dict[str, int] = {}
    for job in jobs:
        for tag in _iter_tags(job.get("skill_tags")):
            skill_counter[tag] = skill_counter.get(tag, 0) + 1
        edu = str(job.get("education") or "").strip()
        if edu:
            edu_counter[edu] = edu_counter.get(edu, 0) + 1

    # 每个岗位的检索文本只拼一次：原来 _prev 按维度各拼一遍（3 维 × 上万行），
    # 且每拼一次都要 json.loads 技能标签——这是 14 秒耗时的主要来源
    blobs = [
        " ".join([str(job.get("title") or "")] + _iter_tags(job.get("skill_tags"))
                 + [str(job.get("description") or "")])
        for job in jobs
    ]

    def _prev(keywords_: tuple[str, ...]) -> float | None:
        if not total:
            return None
        hit = sum(1 for blob in blobs if any(k in blob for k in keywords_))
        return round(hit / total, 4)

    salary = [float(j["salary_max"] or 0) for j in jobs if j.get("salary_max") is not None]
    exp = [float(j["exp_min"] or 0) for j in jobs if j.get("exp_min") is not None]
    return {
        "sample_jobs": total,
        "keyword_rates": {dim: _prev(kws) for dim, kws, _k in _GAP_DIMS},
        "top_skills": [{"skill": k, "jobs": v}
                       for k, v in sorted(skill_counter.items(),
                                          key=lambda kv: (-kv[1], kv[0]))[:5]],
        "education_top": [{"education": k, "jobs": v}
                          for k, v in sorted(edu_counter.items(),
                                             key=lambda kv: (-kv[1], kv[0]))[:3]],
        "salary_range": None if not salary else [min(salary), max(salary)],
        "avg_exp_min": None if not exp else round(sum(exp) / len(exp), 2),
    }


def _iter_tags(raw: Any) -> list[str]:
    """skill_tags 可能是 JSON 字符串或 list[str]，统一成字符串列表。"""
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return []
    else:
        data = raw
    if isinstance(data, list):
        return [str(x) for x in data]
    if isinstance(data, Mapping):
        return [str(v) for v in data.values()]
    return []


# ----------------------------------------------------------------
# 学生端工具
# ----------------------------------------------------------------
def my_warning(ctx: ToolContext, term: str | None = None) -> dict[str, Any]:
    """本人预警状态 + 归因（只用 ctx.student_id，忽略任何外部传入的学号）。"""
    ctx = _check_ctx(ctx)
    _require_student(ctx, "my_warning", "self")
    term = _resolve_term(ctx, term)
    me = _resolve_self(ctx, "my_warning")

    result = warning.compute_student(
        ctx.tenant_id, me["student_no"], term,
        class_name=str(me.get("class_name") or ""),
    )
    _audit_call(ctx, "my_warning", f"{me['student_no']}/{term}",
                {"level": result.get("level"), "coverage": result.get("coverage")})
    return {
        "student_no": me["student_no"],
        "name": str(me.get("name") or ""),
        "term": term,
        "risk_score": result["risk_score"],
        "level": result["level"],
        "reasons": result["reasons"],
        "coverage": result["coverage"],
        "missing": result["missing"],
        "metrics": dict(result["metrics"]),
        "engine_version": warning.ENGINE_VERSION,
        "calc_version": profile.CALC_VERSION,
        "tools_version": TOOLS_VERSION,
    }


def my_recommendations(ctx: ToolContext, term: str | None = None,
                       top_n: int = 10) -> dict[str, Any]:
    """本人岗位推荐 + 三段式理由：调 engine.hybrid（0.7 内容 + 0.3 协同过滤）。

    三段式（与计划书口径一致）：
      knowledge = 内容匹配证据（A 的命中点）
      skill     = KG 课程链（学过X→掌握Y→满足Z）或技能缺口
      potential = 协同过滤同伴证据（同专业同成绩段同学的行为）
    """
    ctx = _check_ctx(ctx)
    _require_student(ctx, "my_recommendations", "self")
    term = _resolve_term(ctx, term)
    me = _resolve_self(ctx, "my_recommendations")

    try:
        result = hybrid.hybrid_recommend(
            ctx.tenant_id, me["student_no"], term, top_n=top_n, student_id=ctx.student_id)
        note = ""
    except Exception as exc:  # 推荐失败不得让整个对话崩掉
        result = {"items": [], "cold_start": False, "candidate_cnt": 0}
        note = f"推荐引擎暂不可用：{exc}"

    for item in result.get("items") or []:
        item["reasons"] = _hybrid_reasons(item, bool(result.get("cf_active")))

    _audit_call(ctx, "my_recommendations", f"{me['student_no']}/{term}",
                {"top_n": top_n, "engine_version": hybrid.HYBRID_ENGINE_VERSION,
                 "cf_active": bool(result.get("cf_active")),
                 "neighbor_cnt": int(result.get("neighbor_cnt") or 0)})
    return {
        "student_no": me["student_no"],
        "name": str(me.get("name") or ""),
        "term": term,
        "top_n": int(top_n),
        "recommend_version": hybrid.HYBRID_ENGINE_VERSION,
        "cold_start": bool(result.get("cold_start")),
        "cf_active": bool(result.get("cf_active")),
        "neighbor_cnt": int(result.get("neighbor_cnt") or 0),
        "weights": result.get("weights") or {"content": 0.7, "cf": 0.3},
        "candidate_cnt": int(result.get("candidate_cnt") or 0),
        "items": list(result.get("items") or []),
        "reasons_schema": {"knowledge": "内容匹配", "skill": "KG课程链", "potential": "同伴证据"},
        "note": note or str(result.get("note") or ""),
        "engine_version": hybrid.HYBRID_ENGINE_VERSION,
        "calc_version": profile.CALC_VERSION,
        "tools_version": TOOLS_VERSION,
    }


def _hybrid_reasons(item: Mapping[str, Any], cf_active: bool) -> dict[str, str]:
    """三段式理由（全部来自引擎字段，无模型参与）。

    成绩门槛是内容召回的 gpa_fit 维度，与课程/技能缺口不是一个口径：
    engine.recommend 把两者都塞进了 gap_items，这里按前缀拆开——
    成绩类归 knowledge（内容匹配），课程技能类才归 skill（KG 课程链）。
    """
    hits = [str(x) for x in (item.get("hit_items") or [])]
    gaps = [str(x) for x in (item.get("gap_items") or [])]
    gpa_gaps = [g for g in gaps if g.startswith("成绩")]
    skill_gaps = [g for g in gaps if not g.startswith("成绩")]
    if gpa_gaps:
        hits = hits + gpa_gaps[:1]
    knowledge = "；".join(hits[:3]) if hits else "内容匹配分来自专业方向与成绩门槛"
    kgx = item.get("kg_explain") or {}
    skill = str(kgx.get("summary") or "") if kgx else ""
    if not skill:
        skill = "需补：" + "、".join(skill_gaps[:3]) if skill_gaps else "技能匹配良好"
    peers = item.get("peer_count")
    if peers:
        potential = f"{peers} 位同专业同成绩段同学关注过该岗位（协同权重 {item.get('cf_score')}）"
    elif cf_active:
        potential = "同段位同学暂未关注该岗位，按内容匹配排序"
    else:
        potential = "暂无本人行为数据，协同过滤冷启动跳过"
    return {"knowledge": knowledge, "skill": skill, "potential": potential}


# ================================================================
# 竞赛推荐与通知推送（数据来自重庆财经学院教务处公布的官方名单/通知）
# ================================================================
def competition_guide(ctx: ToolContext, track: str = "就业", direction: str = "",
                      job_title: str = "", gap_skills: Sequence[str] = (),
                      limit: int = 8) -> dict[str, Any]:
    """按去向（考公/就业）+ 岗位方向推荐该参加的比赛；纯规则，结果附官方来源链接。"""
    ctx = _check_ctx(ctx)
    _require_student(ctx, "competition_guide", "self")
    me = _resolve_self(ctx, "competition_guide")

    result = competition.recommend_competitions(
        track=track, direction=direction, job_title=job_title,
        gap_skills=list(gap_skills or ()), limit=limit)
    _audit_call(ctx, "competition_guide", f"{me['student_no']}/{track}",
                {"returned": len(result.get("items") or [])})
    return {
        "student_no": me["student_no"],
        **result,
        "tools_version": TOOLS_VERSION,
    }


def my_notices(ctx: ToolContext, limit: int = 20) -> dict[str, Any]:
    """本人未读的竞赛通知（官方新发布即推送，按已读水位判定）。"""
    ctx = _check_ctx(ctx)
    _require_student(ctx, "my_notices", "self")
    me = _resolve_self(ctx, "my_notices")
    result = competition.unread_notices(me["student_no"], ctx.tenant_id, limit=limit)
    return {**result, "tools_version": TOOLS_VERSION}


def mark_notices_read(ctx: ToolContext) -> dict[str, Any]:
    """把已读水位推到当前时间（之后发布的新通知才会再次提醒）。"""
    ctx = _check_ctx(ctx)
    _require_student(ctx, "mark_notices_read", "self")
    me = _resolve_self(ctx, "mark_notices_read")
    return competition.mark_read(me["student_no"], ctx.tenant_id)


# ================================================================
# 生涯规划（按年级分层：大一先选目标，大二/大三直接给路径）
# ================================================================
def my_career_guide(ctx: ToolContext, term: str | None = None) -> dict[str, Any]:
    """本人年级 + 职业目标 + 确定性规划路径（不调模型）。

    大一且未选目标时返回 needs_intent=True，前端必须先让学选择；
    大二/大三未选目标也会返回探索型规划，不强制补选。
    """
    ctx = _check_ctx(ctx)
    _require_student(ctx, "career_guide", "self")
    term = _resolve_term(ctx, term)
    me = _resolve_self(ctx, "career_guide")

    grade = career_guide.grade_label(me.get("enroll_year"))
    intent = career_context.fetch_intent(ctx.tenant_id, int(ctx.student_id or 0))

    stored_rows = read_features(term, [me["student_no"]])
    stored = stored_rows[0] if stored_rows else {}
    features = _rebuild_features(stored)
    direction = None
    if features:
        direction = (features.get("interest") or {}).get("top_direction")

    guide = career_guide.build_guide(
        grade=grade, intent=intent, direction=direction, major=me.get("major"),
    )
    _audit_call(
        ctx, "career_guide", f"{me['student_no']}/{term}",
        {"grade": grade, "intent": intent, "needs_intent": guide["needs_intent"]},
    )
    return {
        **guide,
        "student_no": me["student_no"],
        "name": str(me.get("name") or ""),
        "class_name": str(me.get("class_name") or ""),
        "term": term,
        "source": "duckdb.student_feature" if stored else "none",
        "calc_version": profile.CALC_VERSION,
        "tools_version": TOOLS_VERSION,
    }


def save_career_intent(ctx: ToolContext, intent: str) -> dict[str, Any]:
    """保存本人职业目标；只接受 考公/考研/考编/就业 四个值。"""
    ctx = _check_ctx(ctx)
    _require_student(ctx, "save_career_intent", "self")
    value = career_guide.normalize_intent(intent)
    if value is None:
        raise ValueError("职业目标必须是 考公/考研/考编/就业 之一")
    saved = career_context.save_intent(
        ctx.tenant_id, int(ctx.student_id or 0), value,
    )
    _audit_call(ctx, "save_career_intent", str(ctx.student_id), {"intent": value})
    return {
        "intent": value,
        "saved": bool(saved),
        "options": [dict(option) for option in career_guide.INTENT_OPTIONS],
        "engine_version": career_guide.GUIDE_ENGINE_VERSION,
        "tools_version": TOOLS_VERSION,
    }


# ================================================================
# 岗位搜索（与 my_recommendations 是两套逻辑，互不污染）
# ================================================================
# 搜索要扫全表（当前 2931 条），不能用 recommend 的 400 条抽样上限。
SEARCH_SCAN_LIMIT = 5000


def _load_jobs_for_search(limit: int = SEARCH_SCAN_LIMIT) -> list[dict[str, Any]]:
    """取搜索用岗位池。job_search 是纯函数，取数全部在这一层完成。"""
    rows = _query(
        "SELECT `编号` AS id, `岗位名称` AS title, `企业` AS company, `行业` AS industry, "
        "       `企业规模` AS company_size, `城市` AS city, `区县` AS district, "
        "       `最低薪资` AS salary_min, `最高薪资` AS salary_max, "
        "       `薪资单位` AS salary_unit, `薪资月数` AS salary_months, "
        "       `最低经验` AS exp_min, `最高经验` AS exp_max, `学历` AS education, "
        "       `技能标签` AS skill_tags, `福利待遇` AS benefits, "
        "       `岗位描述` AS description, `来源` AS source "
        "FROM `岗位` ORDER BY `编号` LIMIT %s",
        (int(limit),),
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        # JSON 列在 MySQL 里可能以 str 返回，统一成 list（前端要直接渲染）
        for key in ("skill_tags", "benefits"):
            raw = item.get(key)
            if isinstance(raw, str):
                try:
                    item[key] = json.loads(raw)
                except ValueError:
                    item[key] = []
            elif raw is None:
                item[key] = []
        for key in ("salary_min", "salary_max"):
            if item.get(key) is not None:
                item[key] = float(item[key])
        # 搜索不需要 JD 全文回传给前端（太大），但打分要用 → 保留在内部字段
        out.append(item)
    return out


def _job_brief(job: Mapping[str, Any], *, with_desc: bool = False) -> dict[str, Any]:
    """岗位对外字段：默认不带 JD 全文（列表里用不上，徒增体积）。"""
    item = {
        "id": job.get("id"),
        "title": job.get("title"),
        "company": job.get("company"),
        "industry": job.get("industry"),
        "company_size": job.get("company_size"),
        "city": job.get("city"),
        "district": job.get("district"),
        "salary_min": job.get("salary_min"),
        "salary_max": job.get("salary_max"),
        "salary_unit": job.get("salary_unit"),
        "salary_months": job.get("salary_months"),
        "exp_min": job.get("exp_min"),
        "exp_max": job.get("exp_max"),
        "education": job.get("education"),
        "skill_tags": list(job.get("skill_tags") or []),
        "source": job.get("source"),
    }
    if with_desc:
        item["description"] = job.get("description") or ""
        item["benefits"] = list(job.get("benefits") or [])
    return item


def search_jobs(ctx: ToolContext, query: str = "", *,
                cities: Sequence[str] | None = None,
                educations: Sequence[str] | None = None,
                salary_min_gte: float | None = None,
                exp_max_lte: float | None = None,
                limit: int = 20, offset: int = 0) -> dict[str, Any]:
    """关键词搜索岗位。**不带个人画像**——搜索是检索，推荐才是个性化。

    没命中时不硬凑：返回空 items + suggestions（该方向下更可能命中的词）。
    """
    ctx = _check_ctx(ctx)
    _require_student(ctx, "job_search", "self")

    filters: dict[str, Any] = {}
    if cities:
        filters["cities"] = list(cities)
    if educations:
        filters["educations"] = list(educations)
    if salary_min_gte is not None:
        filters["salary_min_gte"] = float(salary_min_gte)
    if exp_max_lte is not None:
        filters["exp_max_lte"] = float(exp_max_lte)

    pool = _load_jobs_for_search()
    raw = job_search.search_jobs(pool, query, filters=filters or None,
                                 limit=limit, offset=offset)

    items = [_job_brief(j) | {
        "relevance_score": j.get("relevance_score"),
        "relevance_level": j.get("relevance_level"),
        "matched_keywords": list(j.get("matched_keywords") or []),
        "matched_fields": [
            job_search.FIELD_LABELS.get(f, f) for f in (j.get("matched_fields") or [])
        ],
    } for j in raw.get("items") or []]

    result: dict[str, Any] = {
        "query": str(query or ""),
        "keywords": list(raw.get("keywords") or []),
        "total": int(raw.get("total") or 0),
        "items": items,
        "page": raw.get("page") or {},
        "filters": filters,
        "pool_size": len(pool),
        "engine_version": job_search.JOB_SEARCH_VERSION,
    }

    # 没命中时给「是不是想找」，绝不返回不相关岗位充数
    if int(raw.get("total") or 0) == 0 and (query or "").strip():
        result["suggestions"] = job_search.suggest_keywords(query)
        result["note"] = ("没有找到同时满足关键词与筛选条件的岗位。"
                          "可以换个说法，或放宽筛选条件。")
    elif int(raw.get("total") or 0) == 0:
        result["suggestions"] = []
        result["note"] = "当前筛选条件下没有岗位，试着放宽条件。"

    _audit_call(ctx, "job_search", str(query or "")[:60],
                {"query": str(query or ""), "filters": filters,
                 "total": result["total"]})
    return result


def job_detail(ctx: ToolContext, job_id: int) -> dict[str, Any]:
    """岗位详情（含 JD 全文与福利）。"""
    ctx = _check_ctx(ctx)
    _require_student(ctx, "job_detail", str(job_id))

    try:
        job_id = int(job_id)
    except (TypeError, ValueError):
        raise ValueError("岗位 id 必须是整数")

    rows = _query(
        "SELECT `编号` AS id, `岗位名称` AS title, `企业` AS company, `行业` AS industry, "
        "       `企业规模` AS company_size, `城市` AS city, `区县` AS district, "
        "       `最低薪资` AS salary_min, `最高薪资` AS salary_max, "
        "       `薪资单位` AS salary_unit, `薪资月数` AS salary_months, "
        "       `最低经验` AS exp_min, `最高经验` AS exp_max, `学历` AS education, "
        "       `技能标签` AS skill_tags, `福利待遇` AS benefits, "
        "       `岗位描述` AS description, `来源` AS source "
        "FROM `岗位` WHERE `编号` = %s",
        (job_id,),
    )
    if not rows:
        raise ValueError(f"岗位不存在：{job_id}")

    row = dict(rows[0])
    for key in ("skill_tags", "benefits"):
        raw = row.get(key)
        if isinstance(raw, str):
            try:
                row[key] = json.loads(raw)
            except ValueError:
                row[key] = []
        elif raw is None:
            row[key] = []
    for key in ("salary_min", "salary_max"):
        if row.get(key) is not None:
            row[key] = float(row[key])

    _audit_call(ctx, "job_detail", str(job_id), {"job_id": job_id})
    return {"job": _job_brief(row, with_desc=True)}


def job_facets(ctx: ToolContext) -> dict[str, Any]:
    """筛选器下拉选项（城市 / 学历及其岗位数），供前端渲染。"""
    ctx = _check_ctx(ctx)
    _require_student(ctx, "job_facets", "all")
    pool = _load_jobs_for_search()
    out = job_search.build_facets(pool)
    _audit_call(ctx, "job_facets", "all", {"pool_size": len(pool)})
    out["pool_size"] = len(pool)
    return out


# 对外工具清单：便于 FastAPI / LangGraph 统一注册与自检
# 「智能体统一入口」注册表（agent-entry-v1）：覆盖系统全部板块的只读工具，
# 铁律不变——数值全部由 engine 确定性计算，工具层只做校验、取数与审计。
TEACHER_TOOLS: tuple[str, ...] = (
    "class_overview", "class_list", "student_profile", "warning_list", "career_gap",
    "get_warning_thresholds", "save_warning_thresholds",
    # 成绩 / 预测（教师按学号查，任教范围校验在工具内）
    "student_grades", "student_forecast", "class_grades_rank",
    # 岗位 / 图谱
    "search_jobs", "job_facets", "kg_major_skills", "kg_skill_jobs", "kg_path",
    # agent-entry-v2：招考公告 / 面试题库（师生通用，都带出处）
    "exam_notices", "exam_positions", "question_bank_lookup",
)
STUDENT_TOOLS: tuple[str, ...] = (
    "my_warning", "my_recommendations", "job_search",
    "career_guide", "save_career_intent",
    # 成绩 / 预测 / 报考分析（本人视角，学号只来自登录态）
    "my_grades", "my_forecast", "my_career_forecast",
    # 通知 / 竞赛 / 规划
    "my_notices", "mark_notices_read", "competition_guide", "my_career_guide",
    # 岗位 / 图谱
    "search_jobs", "job_facets", "kg_major_skills", "kg_skill_jobs", "kg_path",
    # agent-entry-v2：招考公告 / 模拟面试历史（只本人）/ 面试题库
    "exam_notices", "exam_positions", "my_interviews", "question_bank_lookup",
)


# ----------------------------------------------------------------
# 知识库（RAG）与联网搜索：两类「外部事实」入口
# ----------------------------------------------------------------
def kb_search(ctx: ToolContext, query: str = "", top_k: int = 4,
              doc_id: int | None = None) -> dict[str, Any]:
    """在企业知识库里检索企业制度/流程/FAQ，返回块级命中（带文档名与页码）。

    查不到就返回空 hits，并在 note 里说明——绝不用模型记忆补一段「知识库内容」。
    """
    ctx = _check_ctx(ctx)
    q = str(query or "").strip()
    if not q:
        return {"query": q, "total": 0, "hits": [], "citations": [],
                "engine_version": rag.RAG_VERSION, "note": "查询为空"}
    try:
        conn = _connect()
    except (pymysql.MySQLError, OSError) as exc:  # pragma: no cover - 依赖环境
        print(f"[tools] MySQL 连接失败：{exc}", file=sys.stderr)
        return {"query": q, "total": 0, "hits": [], "citations": [],
                "engine_version": rag.RAG_VERSION, "note": "知识库暂时不可用"}
    try:
        hits = kb_store.search(conn, ctx.tenant_id, q,
                               top_k=max(1, min(int(top_k or 4), 10)), doc_id=doc_id)
    except (pymysql.MySQLError, OSError) as exc:  # pragma: no cover - 依赖环境
        print(f"[tools] 知识库检索失败：{exc}", file=sys.stderr)
        return {"query": q, "total": 0, "hits": [], "citations": [],
                "engine_version": rag.RAG_VERSION, "note": "知识库暂时不可用"}
    finally:
        conn.close()
    _audit_call(ctx, "tool.kb_search", "kb", {"query": q[:80], "hits": len(hits)})
    return {"query": q, "total": len(hits), "hits": hits,
            "citations": rag.as_citations(hits), "engine_version": rag.RAG_VERSION,
            "note": "" if hits else "知识库里没有检索到相关内容"}


# ----------------------------------------------------------------
# 知识库多跳检索（rag-multihop-v1）
# ----------------------------------------------------------------
# 为什么要有：单跳检索碰到「原文只提了一句、要点散在另一段」的问题就只能答
# 「没查到」。这里在模型判定「不足以回答」时改写检索词再补一跳，命中合并去重。
# 铁律不变：改写词只能用原文或原问题里出现过的词，禁止引入两者都没有的新实体；
# 引用编号仍由 as_citations 统一编排，verify_citations 的校验口径一行没改。
_MULTIHOP_SYSTEM = (
    "你是检索助手。判断下面【原文片段】是否足以回答【问题】。\n"
    "只输出一行 JSON，不要任何解释：{\"enough\": true, \"query\": \"\"}"
    " 或 {\"enough\": false, \"query\": \"改写后的检索词\"}\n"
    "规则：\n"
    "1. 原文里有能直接支撑答案的句子 → enough=true，query 留空。\n"
    "2. 不足 → enough=false，query 写一个新的检索词：换同义词、拆出子问题、"
    "或补上原文里出现的主体。不要照抄原问题。\n"
    "3. 改写词只能用原文或原问题里出现过的词，禁止引入两者都没有的新实体。\n"
    "4. 不要输出 JSON 以外的内容。"
)


def _multihop_enabled() -> bool:
    """AGENT_KB_MULTIHOP=0 可关闭多跳，退回单跳（对比用）。"""
    return str(os.getenv("AGENT_KB_MULTIHOP", "1")).strip().lower() not in ("0", "false", "off", "no")


def _hit_key(hit: Mapping[str, Any]) -> tuple[Any, ...]:
    return (str(hit.get("title") or ""), hit.get("page"), int(hit.get("chunk_no") or 0))


def _judge_enough(ctx: ToolContext, query: str,
                  hits: Sequence[Mapping[str, Any]]) -> tuple[bool, str]:
    """让模型判断够不够；不足则给改写词。模型不可用 → 按「够」处理，不再多跳。"""
    from agents import llm as llm_client

    blob = "\n".join(f"[{i}] {str(h.get('title'))}：{str(h.get('text') or '')[:260]}"
                     for i, h in enumerate(list(hits)[:4], start=1)) or "（没有检索到任何原文）"
    raw = llm_client.generate_reply(ctx.actor_type, system_prompt=_MULTIHOP_SYSTEM,
                                    user_prompt=f"【问题】{query}\n\n【原文片段】\n{blob}",
                                    tag="kb_hop")
    if not raw:
        return True, ""
    match = re.search(r"\{.*\}", raw, re.S)
    if not match:
        return True, ""
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return True, ""
    if not isinstance(data, dict):
        return True, ""
    return bool(data.get("enough")), str(data.get("query") or "").strip()[:80]


def kb_search_deep(ctx: ToolContext, query: str = "", top_k: int = 4,
                   max_hops: int = 2) -> dict[str, Any]:
    """知识库多跳检索：第一跳不足以回答时，改写检索词再查一轮（最多再补 1 跳）。

    返回结构与 kb_search 完全一致（多 hops / multi_hop / new_hits 三个字段），
    所以 _external_draft 与 verify_citations 都不需要改。
    """
    ctx = _check_ctx(ctx)
    q = str(query or "").strip()
    first = kb_search(ctx, q, top_k=top_k)
    hops: list[dict[str, Any]] = [{"query": q, "hits": len(first.get("hits") or [])}]
    if not _multihop_enabled() or max_hops < 2:
        return {**first, "hops": hops, "multi_hop": False, "new_hits": 0}

    merged: list[dict[str, Any]] = list(first.get("hits") or [])
    seen = {_hit_key(h) for h in merged}
    used = {q}
    new_hits = 0
    for _ in range(max_hops - 1):
        enough, nxt = _judge_enough(ctx, q, merged)
        if enough or len(nxt) < 2 or nxt in used:
            break
        used.add(nxt)
        # 补跳时扩大召回：沿用同样的 top_k 会把第一跳那几块再捞一遍，
        # 去重后等于白跳一次——小语料上尤其明显（实测过 added 恒为 0）。
        nxt_res = kb_search(ctx, nxt, top_k=min(int(top_k) * 2, 10))
        added = 0
        for h in (nxt_res.get("hits") or []):
            key = _hit_key(h)
            if key not in seen:
                seen.add(key)
                merged.append(h)
                added += 1
        new_hits += added
        hops.append({"query": nxt, "hits": len(nxt_res.get("hits") or []), "added": added})
        if added == 0:      # 这一跳没带回任何新原文，再跳也没意义
            break

    _audit_call(ctx, "tool.kb_search_deep", "kb",
                {"query": q[:80], "hops": len(hops), "hits": len(merged),
                 "new_hits": new_hits})
    return {"query": q, "total": len(merged), "hits": merged,
            "citations": rag.as_citations(merged), "engine_version": rag.RAG_VERSION,
            "note": "" if merged else "知识库里没有检索到相关内容",
            "hops": hops, "multi_hop": len(hops) > 1, "new_hits": new_hits}


def web_search(ctx: ToolContext, query: str = "", top_k: int = 5) -> dict[str, Any]:
    """联网搜索（需配置 SERPER_API_KEY / BING_SEARCH_KEY）。

    未配置时 configured=False + 明确原因：宁可说「没有联网能力」，也不编搜索结果。
    """
    ctx = _check_ctx(ctx)
    res = web_engine.search(query, top_k=max(1, min(int(top_k or 5), 10)))
    res["citations"] = web_engine.as_citations(res.get("results") or [])
    _audit_call(ctx, "tool.web_search", "web",
                {"query": str(query or "")[:80], "configured": res.get("configured"),
                 "results": len(res.get("results") or [])})
    return res


def run_workflow(ctx: ToolContext, name: str = "", inputs: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """按名称执行本租户的工作流；不带名称时只列出可用流程（不执行）。

    执行用的是调用者自己的 ctx，所以学生跑「我的求职体检」只会拿到自己的数据，
    即便这个工作流是教师定义的。
    """
    ctx = _check_ctx(ctx)
    rows = _query("SELECT `编号`,`名称`,`描述`,`步骤`,`是否需要审批` FROM `工作流定义`"
                  " WHERE `租户编号`=%s AND `是否启用`=1 ORDER BY `编号`", (ctx.tenant_id,))
    if not rows:
        return {"mode": "workflow", "status": "empty", "available": [],
                "summary": "当前没有可用的工作流。教师可以先在「工作流」里定义一个。"}
    if not str(name or "").strip():
        items = [{"id": int(r["编号"]), "name": r["名称"], "description": r.get("描述")}
                 for r in rows]
        return {"mode": "workflow", "status": "list", "available": items,
                "summary": "可用工作流：" + "、".join(i["name"] for i in items)}

    target = None
    for r in rows:                       # 全等优先，其次包含，保持确定性
        if str(r["名称"]) == str(name).strip():
            target = r
            break
    if target is None:
        for r in rows:
            if str(name).strip() in str(r["名称"]):
                target = r
                break
    if target is None:
        return {"mode": "workflow", "status": "not_found", "available": [],
                "summary": f"没有找到名为「{name}」的工作流。"}

    # 人工审批：定义了「需要审批」的流程，谁触发都不跑，挂起等教师点头
    if int(target.get("是否需要审批") or 0):
        from app import workflow_approval     # 延迟导入：避免 agents ↔ app 循环依赖
        pending = workflow_approval.submit_for_approval(
            ctx, int(target["编号"]), str(target["名称"]))
        _audit_call(ctx, "tool.run_workflow.pending", str(target["编号"]),
                    {"name": target["名称"], "run_id": pending["run_id"]})
        return {"mode": "workflow", "status": "pending", "name": target["名称"],
                "needs_approval": True, "summary": pending["message"]}

    steps = []
    try:
        raw = target["步骤"]
        steps = json.loads(raw) if isinstance(raw, str) else list(raw or [])
    except (TypeError, ValueError):
        steps = []
    try:
        result = workflow_engine.run_default(steps, ctx)
    except workflow_engine.WorkflowError as exc:
        return {"mode": "workflow", "status": "invalid", "summary": f"工作流定义有问题：{exc}"}
    _audit_call(ctx, "tool.run_workflow", str(target["编号"]),
                {"name": target["名称"], "status": result["status"],
                 "steps": len(result.get("steps") or [])})
    return {"mode": "workflow", "status": result["status"], "name": target["名称"],
            "steps": result["steps"], "outputs": result.get("outputs") or {},
            "sources": [], "engine_version": result["engine_version"],
            "summary": workflow_engine.render_summary(result)}


# ----------------------------------------------------------------
# 学业数据类工具（agent-entry-v1）
# ----------------------------------------------------------------
# 为什么扩这些：原先智能体只有 9 个工具，成绩 / 学业预测 / 报考分析 / 知识图谱
# 这些功能只能走页面接口，智能体根本调不到——「以智能体为主」就无从谈起。
#
# 铁律不变：数值一律由 engine 的确定性函数算出。这里只做四步：
#   权限校验 → 取数（带租户 / 任教班级隔离）→ 调引擎 → 结构化返回（禁止自然语言）。
# 表达仍交给上层 draft，工具不替模型编话。

_GRADE_SQL = (
    "SELECT sc.`编号` AS record_id, sc.`学期` AS term, sc.`分数` AS score, "
    "       sc.`是否重修` AS retake, c.`课程编号` AS course_code, "
    "       c.`课程名称` AS course_name, c.`学分` AS credit "
    "FROM `成绩` sc "
    "JOIN `课程` c ON c.`编号` = sc.`课程编号` "
    "JOIN `学生` s ON s.`编号` = sc.`学生编号` "
    "WHERE s.`租户编号` = %s AND sc.`学生编号` = %s "
    "ORDER BY sc.`学期`, c.`课程编号`, sc.`编号`"
)


def _grades_report(ctx: ToolContext, stu: Mapping[str, Any]) -> dict[str, Any]:
    """取数 → 交给 engine.grades 聚合（均分 / 加权 / 学分 / 挂科门次全由引擎算）。"""
    rows = _query(_GRADE_SQL, (ctx.tenant_id, int(stu["student_id"])))
    student = {k: stu.get(k) for k in
               ("student_no", "name", "major", "class_name", "college", "enroll_year")}
    student["grade"] = career_guide.grade_label(stu.get("enroll_year"))
    report = grades_engine.build_report(rows, student)
    report["tools_version"] = TOOLS_VERSION
    return report


def my_grades(ctx: ToolContext) -> dict[str, Any]:
    """本人成绩单（学生端）：各学年 / 学期均分、加权均分、学分、挂科门次。
    学号只来自登录态，不接受任何「查谁」的入参。"""
    ctx = _check_ctx(ctx)
    _require_student(ctx, "my_grades", "self")
    me = _resolve_self(ctx, "my_grades")
    report = _grades_report(ctx, me)
    _audit_call(ctx, "my_grades", str(me["student_no"]),
                {"records": report["summary"]["record_count"]})
    return report


def student_grades(ctx: ToolContext, student_no: str = "") -> dict[str, Any]:
    """某个学生的成绩单（教师端）；租户 + 任教范围校验在 _fetch_student 内完成。"""
    ctx = _check_ctx(ctx)
    _require_teacher(ctx, "student_grades", str(student_no))
    stu = _fetch_student(ctx, str(student_no or ""), "student_grades")
    report = _grades_report(ctx, stu)
    _audit_call(ctx, "student_grades", str(stu["student_no"]),
                {"records": report["summary"]["record_count"]})
    return report


# 排名取数：要连同专业的其他班一起取，否则算不出「同专业班级排名」
_RANK_SQL_HEAD = (
    "SELECT s.`编号` AS student_id, s.`学号` AS student_no, s.`姓名` AS name, "
    "       s.`专业` AS major, s.`班级` AS class_name, sc.`学期` AS term, "
    "       sc.`分数` AS score, sc.`是否重修` AS retake, sc.`编号` AS record_id, "
    "       c.`课程编号` AS course_code, c.`课程名称` AS course_name, c.`学分` AS credit "
    "FROM `成绩` sc "
    "JOIN `课程` c ON c.`编号` = sc.`课程编号` "
    "JOIN `学生` s ON s.`编号` = sc.`学生编号` "
    "WHERE s.`租户编号` = %s AND sc.`学期` = %s"
)


def class_grades_rank(ctx: ToolContext, class_name: str = "",
                      term: str | None = None) -> dict[str, Any]:
    """教师端成绩分析：全班总体均分、个人均分、同专业内的班级排名与个人排名。

    口径与成绩单严格一致（同一门课取最高分 → 按学分加权），所以排名里的个人均分
    与成绩单上显示的加权均分是同一个数，不会出现两个页面数字打架。

    统计范围 = 教师任教班级（未绑定时回退本租户全部班级）：带不到班的教师看不到
    范围外班级的成绩——这是铁律 3 的落点，不是前端隐藏。
    """
    ctx = _check_ctx(ctx)
    _require_teacher(ctx, "class_grades_rank", str(class_name))
    term = _resolve_term(ctx, term)
    roster = _require_class(ctx, str(class_name or ""), "class_grades_rank")
    scope = _teacher_class_scope(ctx)

    params: list[Any] = [ctx.tenant_id, term]
    sql = _RANK_SQL_HEAD
    if scope:
        sql += " AND s.`班级` IN (" + ",".join(["%s"] * len(scope)) + ")"
        params.extend(sorted(scope))
    rows = _query(sql, params)

    result = grades_engine.build_rank(rows, term=term, scope_classes=scope)
    # 明细只回当前班：其他班的数据只用于算同专业名次，不随结果外发
    result["students"] = [s for s in result["students"]
                          if str(s["class_name"]) == str(class_name)]
    # 学期下拉要用：本租户有成绩的学期（前端不必硬编码）
    result["available_terms"] = [
        str(r["term"]) for r in _query(
            "SELECT DISTINCT sc.`学期` AS term FROM `成绩` sc "
            "JOIN `学生` s ON s.`编号` = sc.`学生编号` "
            "WHERE s.`租户编号` = %s ORDER BY sc.`学期` DESC", (ctx.tenant_id,))
    ]
    result["class_name"] = str(class_name)
    result["headcount"] = int(roster.get("headcount") or 0)
    result["scope"] = "assigned" if scope else "tenant"
    result["tools_version"] = TOOLS_VERSION
    _audit_call(ctx, "class_grades_rank", f"{class_name}/{term}",
                {"student_cnt": len(result["students"]),
                 "class_cnt": len(result["classes"]), "scope": result["scope"]})
    return result


def my_forecast(ctx: ToolContext) -> dict[str, Any]:
    """本人学业预测（学生端）：下学期绩点 / 挂科门次、风险课、预警等级走向。
    学期不足 2 个时引擎返回 available=False 并说明原因，**不冒充预测值**。"""
    ctx = _check_ctx(ctx)
    _require_student(ctx, "my_forecast", "self")
    me = _resolve_self(ctx, "my_forecast")
    result = forecast_engine.compute_student_forecast(ctx.tenant_id, str(me["student_no"]))
    _audit_call(ctx, "my_forecast", str(me["student_no"]),
                {"available": bool(result.get("available"))})
    return dict(result)


def student_forecast(ctx: ToolContext, student_no: str = "") -> dict[str, Any]:
    """某个学生的学业预测（教师端）；班级预警阈值由引擎按该生所在班级取。"""
    ctx = _check_ctx(ctx)
    _require_teacher(ctx, "student_forecast", str(student_no))
    stu = _fetch_student(ctx, str(student_no or ""), "student_forecast")
    result = forecast_engine.compute_student_forecast(ctx.tenant_id, str(stu["student_no"]))
    _audit_call(ctx, "student_forecast", str(stu["student_no"]),
                {"available": bool(result.get("available"))})
    return dict(result)


def my_career_forecast(ctx: ToolContext, goal: str = "") -> dict[str, Any]:
    """本人报考竞争力分析（学生端）：考公 / 考编 / 考研 三选一，含硬门槛校验、
    四维评分、时间窗与提分杠杆。goal 留空时沿用学生自己填的发展意向。

    只给学生本人：这是个人竞争力数据，教师端不暴露。
    """
    ctx = _check_ctx(ctx)
    _require_student(ctx, "my_career_forecast", "self")
    from agents.career import nodes as career_nodes   # 延迟导入：nodes 反过来依赖 tools

    result = career_nodes.forecast_career(ctx.tenant_id, ctx.student_id, goal or None)
    _audit_call(ctx, "my_career_forecast", f"student:{ctx.student_id}",
                {"goal": str(goal or ""), "available": bool(result.get("available"))})
    return dict(result)


# 知识图谱：构图要扫全表（课程 / 岗位），进程内缓存一份，避免每次对话重建
_KG_CACHE: Any = None
_KG_LOCK = threading.Lock()


def _kg_graph() -> Any:
    global _KG_CACHE
    if _KG_CACHE is None:
        with _KG_LOCK:
            if _KG_CACHE is None:
                _KG_CACHE = kg_engine.build_graph()
    return _KG_CACHE


def _my_major(ctx: ToolContext, action: str) -> str:
    """学生端只能看自己专业的链路，不接受外部传专业。"""
    return str(_resolve_self(ctx, action).get("major") or "")


def kg_major_skills(ctx: ToolContext, major: str = "") -> dict[str, Any]:
    """某专业通过课程能学到哪些技能（专业 → 课程 → 技能）。
    学生端强制用本人专业；教师端可指定专业。"""
    ctx = _check_ctx(ctx)
    m = str(major or "").strip()
    if ctx.actor_type == ACTOR_STUDENT or not m:
        m = _my_major(ctx, "kg_major_skills")
    if not m:
        raise ValueError("请说明要查哪个专业")
    result = kg_engine.query_skills_by_major(_kg_graph(), m)
    _audit_call(ctx, "kg_major_skills", m, {"total": int(result.get("total") or 0)})
    return dict(result)


def kg_skill_jobs(ctx: ToolContext, skill: str = "", limit: int = 10) -> dict[str, Any]:
    """掌握某项技能能胜任哪些岗位。"""
    ctx = _check_ctx(ctx)
    s = str(skill or "").strip()
    if not s:
        raise ValueError("请说明要查哪项技能")
    result = kg_engine.query_jobs_by_skill(_kg_graph(), s, limit=int(limit))
    _audit_call(ctx, "kg_skill_jobs", s, {"total": int(result.get("total") or 0)})
    return dict(result)


def kg_path(ctx: ToolContext, job_id: int = 0, major: str = "") -> dict[str, Any]:
    """从专业到目标岗位的达成路径：已具备什么、还缺什么、中间经过哪些课程与技能。
    学生端强制按本人专业算（忽略 major 入参），免得跨专业看别人的链。"""
    ctx = _check_ctx(ctx)
    m = str(major or "").strip()
    if ctx.actor_type == ACTOR_STUDENT:
        m = _my_major(ctx, "kg_path")
    if not m:
        raise ValueError("请说明要查哪个专业")
    result = kg_engine.explain_path(_kg_graph(), m, int(job_id or 0))
    _audit_call(ctx, "kg_path", f"{m}->{job_id}",
                {"found": bool(result.get("found"))})
    return dict(result)


# ----------------------------------------------------------------
# 统一入口补全（agent-entry-v2）：招考公告 / 模拟面试 / 题库
# ----------------------------------------------------------------
_EXAM_TYPES: tuple[str, ...] = ("civil", "institution", "postgraduate")
_EXAM_GOAL_WORDS: tuple[tuple[str, str], ...] = (
    ("考公", "civil"), ("公务员", "civil"),
    ("考编", "institution"), ("事业单位", "institution"),
    ("考研", "postgraduate"), ("研究生", "postgraduate"),
)


def exam_notices(ctx: ToolContext, keyword: str = "", exam_type: str = "",
                 only_open: bool = False, limit: int = 6) -> dict[str, Any]:
    """招考公告检索（师生通用）：只报库里实抓到的标题/单位/截止/原文链接。

    数据来自 `招考公告` 表（清洗管线写入），查不到就返回空列表并说明——
    绝不拿模型记忆补一条「往年公告」。exam_type 用考公/考编/考研的口语词也行。
    """
    ctx = _check_ctx(ctx)
    exam_type = str(exam_type or "").strip()
    if exam_type and exam_type not in _EXAM_TYPES:
        # 口语词归一：「考公」→ civil；归不上就报错，不静默吞掉用户意图
        matched = [code for word, code in _EXAM_GOAL_WORDS if word in exam_type]
        if not matched:
            raise ValueError(
                f"考试类型不认识：{exam_type}。可用 {'/'.join(_EXAM_TYPES)}"
                "，或直接说 考公 / 考编 / 考研。")
        exam_type = matched[0]
    limit = max(1, min(int(limit or 6), 10))
    where = ["`租户编号` = %s"]
    params: list[Any] = [ctx.tenant_id]
    kw = str(keyword or "").strip()
    if kw:
        where.append("`标题` LIKE %s")
        params.append(f"%{kw}%")
    if exam_type:
        where.append("`考试类型` = %s")
        params.append(exam_type)
    if only_open:
        where.append("`状态` = 'open'")
    cond = " AND ".join(where)

    total_rows = _query(f"SELECT COUNT(*) AS total FROM `招考公告` WHERE {cond}", params)
    rows = _query(
        "SELECT `编号` AS id, `考试类型` AS exam_type, `标题` AS title, "
        "`招录单位` AS org_name, `地区` AS region, `招录人数` AS headcount, "
        "`报名截止` AS signup_end, `原文链接` AS detail_url, `状态` AS status "
        f"FROM `招考公告` WHERE {cond} "
        "ORDER BY (`发布日期` IS NULL), `发布日期` DESC, `编号` DESC LIMIT %s",
        [*params, limit])
    def _row_json(r: Mapping[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, v in r.items():
            if v is None:
                continue
            if hasattr(v, "isoformat"):
                try:
                    v = v.isoformat(sep=" ")
                except TypeError:        # date.isoformat() 不收 sep
                    v = v.isoformat()
            out[k] = v
        return out

    items = [_row_json(r) for r in rows]
    _audit_call(ctx, "exam_notices", kw or exam_type or "all",
                {"total": int(total_rows[0]["total"]) if total_rows else 0})
    return {
        "capability_version": "agent-entry-v2",
        "keyword": kw,
        "exam_type": exam_type,
        "notice_total": int(total_rows[0]["total"]) if total_rows else 0,
        "items": items,
    }


def exam_positions(ctx: ToolContext, keyword: str = "", dept: str = "",
                   education: str = "", political: str = "", place: str = "",
                   year: int | None = None, limit: int = 8) -> dict[str, Any]:
    """国考职位查询（师生通用）：只报 `国考职位` 表里实抓到的职位与人数。

    数据来自国家公务员局《招考简章》逐职位明细；查不到就返回空列表并说明，
    绝不拿往年职位或模型记忆凑一条。teacher/student 都可查（公共数据）。
    """
    ctx = _check_ctx(ctx)
    limit = max(1, min(int(limit or 8), 20))
    rows = _query(
        "SELECT MAX(`年度`) AS y FROM `国考职位` WHERE `租户编号` = %s",
        (ctx.tenant_id,))
    latest = rows[0]["y"] if rows else None
    if latest is None:
        _audit_call(ctx, "exam_positions", "empty", {"reason": "no_data"})
        return {
            "capability_version": "agent-entry-v3", "year": None,
            "position_total": 0, "total_headcount": 0, "positions": [],
            "note": "职位表还没有同步，先运行 scripts/sync_guokao.py。",
        }
    use_year = int(year or latest)

    where = ["`租户编号` = %s", "`年度` = %s"]
    params: list[Any] = [ctx.tenant_id, use_year]
    kw = str(keyword or "").strip()
    if kw:
        where.append("(`招考职位` LIKE %s OR `部门名称` LIKE %s OR `用人司局` LIKE %s "
                     "OR `专业` LIKE %s OR `职位代码` LIKE %s)")
        params.extend([f"%{kw}%"] * 5)
    for value, column in ((dept, "部门名称"), (education, "学历"),
                          (political, "政治面貌"), (place, "工作地点")):
        text = str(value or "").strip()
        if text:
            where.append(f"`{column}` LIKE %s")
            params.append(f"%{text}%")
    cond = " AND ".join(where)

    totals = _query(
        f"SELECT COUNT(*) AS n, COALESCE(SUM(`招考人数`),0) AS p "
        f"FROM `国考职位` WHERE {cond}", params)
    rows = _query(
        "SELECT `编号` AS id, `部门名称` AS dept_name, `用人司局` AS bureau, "
        "`招考职位` AS position_name, `职位代码` AS position_code, "
        "`招考人数` AS headcount, `学历` AS education, `学位` AS degree, "
        "`政治面貌` AS political, `专业` AS major, `工作地点` AS work_place, "
        "`公告链接` AS notice_url "
        f"FROM `国考职位` WHERE {cond} "
        "ORDER BY `招考人数` DESC, `编号` ASC LIMIT %s",
        [*params, limit])
    total = int(totals[0]["n"]) if totals else 0
    people = int(totals[0]["p"]) if totals else 0
    _audit_call(ctx, "exam_positions", kw or dept or place or "all",
                {"year": use_year, "total": total})
    return {
        "capability_version": "agent-entry-v3",
        "year": use_year,
        "position_total": total,
        "total_headcount": people,
        "filters": {"keyword": kw, "dept": str(dept or "").strip(),
                    "education": str(education or "").strip(),
                    "political": str(political or "").strip(),
                    "place": str(place or "").strip()},
        "positions": [dict(r) for r in rows],
        "note": "" if total else "国考职位表里没有匹配的职位——不拿往年职位凑数。",
    }


def my_interviews(ctx: ToolContext, limit: int = 8) -> dict[str, Any]:
    """本人模拟面试场次（学生端）：状态/总分/轮次，SQL 实查。"""
    ctx = _check_ctx(ctx)
    _require_student(ctx, "my_interviews", "self")
    limit = max(1, min(int(limit or 8), 20))
    rows = _query(
        "SELECT `编号` AS id, `岗位名称` AS job_title, `状态` AS status, "
        "`总分` AS total, `当前轮次` AS cur_round, `最大轮次` AS max_round, "
        "`创建时间` AS created_at, `完成时间` AS finished_at "
        "FROM `面试会话` WHERE `租户编号` = %s AND `学生编号` = %s "
        "ORDER BY `编号` DESC LIMIT %s",
        (ctx.tenant_id, int(ctx.student_id or 0), limit))
    def _row_json(r: Mapping[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, v in r.items():
            if v is None:
                continue
            if hasattr(v, "isoformat"):
                try:
                    v = v.isoformat(sep=" ")
                except TypeError:        # date.isoformat() 不收 sep
                    v = v.isoformat()
            out[k] = v
        return out

    items = [_row_json(r) for r in rows]
    finished = [r for r in items if r.get("status") == "finished"
                and r.get("total") is not None]
    _audit_call(ctx, "my_interviews", "self", {"count": len(items)})
    return {
        "capability_version": "agent-entry-v2",
        "count": len(items),
        "finished_count": len(finished),
        "best_total": max((float(r["total"]) for r in finished), default=None),
        "items": items,
    }


def question_bank_lookup(ctx: ToolContext, query: str = "", family: str = "",
                         qtype: str = "", limit: int = 5) -> dict[str, Any]:
    """面试题库检索（师生通用）：命中题面/考点，每条带出处可回溯原文。

    语料 = data/question_bank/*.json（与出题检索同一份硬校验池），
    无命中返回空列表，不用模型记忆凑数。
    """
    ctx = _check_ctx(ctx)
    limit = max(1, min(int(limit or 5), 10))
    kw = str(query or "").strip()
    qtype = str(qtype or "").strip()
    if qtype and qtype not in qbank.QTYPES:
        raise ValueError(f"题型只能是 {'/'.join(qbank.QTYPES)}")
    fam = str(family or "").strip()
    fam_code = qbank.normalize_industry(fam) if fam else ""
    if fam and fam_code not in qbank.FAMILY_LABELS:
        fam_code = ""     # 未知行业词不硬猜，退化为全文匹配

    hits: list[dict[str, Any]] = []
    for item in qbank.load_bank():
        if fam_code and item.family != fam_code:
            continue
        if qtype and item.qtype != qtype:
            continue
        if kw and kw not in f"{item.question} {' '.join(item.keywords)}":
            continue
        hits.append(item.as_dict())
        if len(hits) >= limit:
            break
    _audit_call(ctx, "question_bank_lookup", kw or fam or qtype or "all",
                {"hits": len(hits)})
    return {
        "capability_version": "agent-entry-v2",
        "query": kw,
        "family": fam_code or fam,
        "qtype": qtype,
        "bank_total": len(qbank.load_bank()),
        "hits": hits,
    }
