# agents/tools.py
# 职责：Agent 工具层——ctx 只能由后端（FastAPI）注入，工具内部不接受「查谁」的 id 参数
# 依赖：pymysql / duckdb / app.config / engine.warning / engine.profile / engine.store / engine.career_rules
# 说明：返回值一律是结构化 dict（禁止自然语言）；越权一律 PermissionError + 写 audit_log；
#       所有 SQL 带 tenant_id 条件；每条返回都带 engine_version / calc_version 便于 Critic 回查来源。

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import pymysql

from app.config import Settings, get_settings
from engine import profile, recommend, warning
from engine.career_rules import CAREER_ENGINE_VERSION
from engine.rules import LEVELS
from engine.store import DuckDBStore

# 工具层版本（随返回值下发，便于前端/Critic 溯源）
TOOLS_VERSION = "tools-v1"
# 角色常量
ACTOR_TEACHER = "teacher"
ACTOR_STUDENT = "student"
_ACTORS: tuple[str, ...] = (ACTOR_TEACHER, ACTOR_STUDENT)

# 方向词典（与 scripts\build_profile_raw.py 共用同一份 JSON，避免关键词两处漂移）
_DICT_PATH = Path(__file__).resolve().parents[1] / "rules" / "direction_keywords.json"

# 测试注入口：非空时审计条目同步写内存，便于断言（monkeypatch.setattr(tools, "AUDIT_SINK", [])）
AUDIT_SINK: list[dict[str, Any]] | None = None

# 升学/就业缺口的三类 DIM（规则版占位，推荐引擎 P9 未实现前的口径）
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
    )


def _query(sql: str, params: Sequence[Any]) -> list[dict[str, Any]]:
    """带租户条件的查询统一入口；库不可用时返回空列表（由上层按空结果处理）。"""
    conn = _connect()
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
    conn = _connect()
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
        "INSERT INTO audit_log (actor_type, actor_id, action, target, detail) "
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


def _require_class(ctx: ToolContext, class_name: str, action: str) -> dict[str, Any]:
    """班级必须属于本租户，否则按「跨租户」拒绝并留痕。"""
    rows = _query(
        "SELECT COUNT(DISTINCT s.id) AS cnt FROM student s "
        "WHERE s.tenant_id = %s AND s.class_name = %s",
        (ctx.tenant_id, class_name),
    )
    cnt = int(rows[0]["cnt"]) if rows else 0
    if cnt == 0:
        _deny(ctx, action, str(class_name),
              f"班级 {class_name} 不属于当前租户（或该班无数据）")
    return {"headcount": cnt}


def _fetch_student(ctx: ToolContext, student_no: str, action: str) -> dict[str, Any]:
    """按学号取学生档案（带 tenant_id）；查不到即视为跨租户。"""
    rows = _query(
        "SELECT s.student_no AS student_no, s.name AS name, s.major AS major, "
        "       s.class_name AS class_name, s.id AS student_id "
        "FROM student s WHERE s.tenant_id = %s AND s.student_no = %s",
        (ctx.tenant_id, student_no),
    )
    if not rows:
        _deny(ctx, action, str(student_no),
              f"学生 {student_no} 不属于当前租户")
    item = dict(rows[0])
    item["student_no"] = str(item["student_no"])
    return item


def _resolve_self(ctx: ToolContext, action: str) -> dict[str, Any]:
    """学生端：把 ctx.student_id 解析成本人学号（带 tenant_id 兜底校验）。"""
    rows = _query(
        "SELECT s.student_no AS student_no, s.name AS name, s.major AS major, "
        "       s.class_name AS class_name "
        "FROM student s WHERE s.tenant_id = %s AND s.id = %s",
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
        "SELECT sc.term AS term FROM score sc "
        "JOIN student s ON s.id = sc.student_id AND s.tenant_id = %s "
        "GROUP BY sc.term ORDER BY sc.term DESC LIMIT 1",
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
    """一次取多名学生的画像落库行（只按学号过滤，学号集合来自已鉴权的 MySQL 结果）。"""
    nos = [str(s) for s in student_nos if s]
    if not nos:
        return []
    store = DuckDBStore()
    rows: list[dict[str, Any]] = []
    for sno in nos:
        row = store.read_student_feature(sno, term)
        if row is not None:
            rows.append(dict(row))
    return rows


# ----------------------------------------------------------------
# 教师端工具
# ----------------------------------------------------------------
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
        "  SELECT s.student_no AS student_no, AVG(sc.score) AS gpa, "
        "         SUM(CASE WHEN sc.score < 60 THEN 1 ELSE 0 END) AS fail_cnt "
        "  FROM student s "
        "  JOIN score sc ON sc.student_id = s.id AND sc.term = %s "
        "  WHERE s.tenant_id = %s AND s.class_name = %s "
        "  GROUP BY s.student_no"
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
        "engine_version": warning.ENGINE_VERSION,
        "calc_version": profile.CALC_VERSION,
        "tools_version": TOOLS_VERSION,
    }


def _employment_intent(ctx: ToolContext, class_name: str, term: str) -> dict[str, Any]:
    """就业意向：本班浏览/收藏过的岗位按方向聚合（取前 5）。"""
    rows = _query(
        "SELECT j.title AS title, COUNT(*) AS cnt "
        "FROM job_view_log v "
        "JOIN student s ON s.id = v.student_id AND s.tenant_id = %s "
        "JOIN job j ON j.id = v.job_id "
        "WHERE v.term = %s AND s.class_name = %s "
        "GROUP BY j.title",
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
        "major": str(stu.get("major") or ""),
        "class_name": str(stu.get("class_name") or ""),
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
        "SELECT sc.term AS term, AVG(sc.score) AS gpa "
        "FROM score sc "
        "JOIN student s ON s.id = sc.student_id AND s.tenant_id = %s "
        "WHERE s.student_no = %s "
        "GROUP BY sc.term ORDER BY sc.term",
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
    if level is not None and level not in LEVELS:
        raise ValueError(f"非法预警等级：{level}，可选 {LEVELS}")

    results = warning.compute_class(ctx.tenant_id, class_name, term)
    items = [
        {
            "student_no": r["student_no"], "name": r["name"],
            "risk_score": r["risk_score"], "level": r["level"],
            "reasons": r["reasons"], "coverage": r["coverage"],
            "missing": r["missing"],
        }
        for r in results
        if level is None or r["level"] == level
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
    """班级能力结构 vs 目标岗位需求差距（规则版，推荐引擎 P9 未实现前的口径）。

    目标方向 = 本班浏览最多的岗位方向；岗位侧需求取本班浏览过的该类岗位；
    缺口口径：需求侧出现对应关键词的岗位占比 − 班级侧具备该项经历的人数占比。
    """
    ctx = _check_ctx(ctx)
    _require_teacher(ctx, "career_gap", str(class_name))
    term = _resolve_term(ctx, term)
    _require_class(ctx, class_name, "career_gap")

    roster = _query(
        "SELECT s.student_no AS student_no FROM student s "
        "WHERE s.tenant_id = %s AND s.class_name = %s "
        "ORDER BY s.student_no",
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
        "note": "规则版缺口（关键词 prevalence 差）；推荐引擎 P9 实现后改为匹配打分口径",
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
        "SELECT j.title AS title, j.salary_min AS salary_min, j.salary_max AS salary_max, "
        "       j.exp_min AS exp_min, j.education AS education, "
        "       j.skill_tags AS skill_tags, j.description AS description "
        "FROM job_view_log v "
        "JOIN student s ON s.id = v.student_id AND s.tenant_id = %s "
        "JOIN job j ON j.id = v.job_id "
        "WHERE v.term = %s AND s.class_name = %s",
        (ctx.tenant_id, term, class_name),
    )
    jobs = [r for r in rows if direction_of(r.get("title")) == target]
    total = len(jobs)
    skill_counter: dict[str, int] = {}
    edu_counter: dict[str, int] = {}
    for job in jobs:
        for tag in _iter_tags(job.get("skill_tags")):
            skill_counter[tag] = skill_counter.get(tag, 0) + 1
        edu = str(job.get("education") or "").strip()
        if edu:
            edu_counter[edu] = edu_counter.get(edu, 0) + 1

    def _prev(keywords_: tuple[str, ...]) -> float | None:
        if not total:
            return None
        hit = 0
        for job in jobs:
            blob = " ".join([str(job.get("title") or "")] + list(_iter_tags(job.get("skill_tags")))
                            + [str(job.get("description") or "")])
            if any(k in blob for k in keywords_):
                hit += 1
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

    result = warning.compute_student(ctx.tenant_id, me["student_no"], term)
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
    """本人岗位推荐 + 三段式理由：调 engine.recommend（规则版，无大模型无随机数）。"""
    ctx = _check_ctx(ctx)
    _require_student(ctx, "my_recommendations", "self")
    term = _resolve_term(ctx, term)
    me = _resolve_self(ctx, "my_recommendations")

    try:
        result = recommend.recommend_for_student(
            ctx.tenant_id, me["student_no"], term, top_n=top_n)
        note = ""
    except Exception as exc:  # 推荐失败不得让整个对话崩掉
        result = {"items": [], "cold_start": False, "candidate_cnt": 0}
        note = f"推荐引擎暂不可用：{exc}"

    _audit_call(ctx, "my_recommendations", f"{me['student_no']}/{term}",
                {"top_n": top_n, "recommend_version": recommend.RECOMMEND_ENGINE_VERSION})
    return {
        "student_no": me["student_no"],
        "name": str(me.get("name") or ""),
        "term": term,
        "top_n": int(top_n),
        "recommend_version": recommend.RECOMMEND_ENGINE_VERSION,
        "cold_start": bool(result.get("cold_start")),
        "candidate_cnt": int(result.get("candidate_cnt") or 0),
        "items": list(result.get("items") or []),
        "reasons_schema": {"knowledge": "", "skill": "", "potential": ""},
        "note": note or str(result.get("note") or ""),
        "engine_version": recommend.RECOMMEND_ENGINE_VERSION,
        "calc_version": profile.CALC_VERSION,
        "tools_version": TOOLS_VERSION,
    }


# 对外工具清单：便于 FastAPI / LangGraph 统一注册与自检
TEACHER_TOOLS: tuple[str, ...] = (
    "class_overview", "student_profile", "warning_list", "career_gap",
)
STUDENT_TOOLS: tuple[str, ...] = ("my_warning", "my_recommendations")
