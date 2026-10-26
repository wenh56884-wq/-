# engine/warning.py
# 职责：学业预警引擎——MySQL 取数（强制 tenant_id）+ 规则打分 + 分级 + 归因
# 依赖：engine.rules / app.config / pymysql；禁止 import 任何 LLM 模块
# 说明：全部数值确定性计算，无随机数；同输入必同输出

from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

import pymysql

from app.config import get_settings
from engine.rules import (
    LEVEL_UNKNOWN,
    LEVELS,
    WarningRules,
    build_rules,
)

# 引擎版本号，用于前端/审计溯源
ENGINE_VERSION = "warning-v2"
# 风险分裁剪区间
SCORE_MIN = 0
SCORE_MAX = 100
# metrics 字段统一保留位数（缺失件不在这里补默认值）
_METRIC_NDIGITS = {"gpa": 2, "gpa_drop": 2, "attendance_rate": 4, "class_rank_pct": 4}
# 参与打分的三个指标（顺序固定：也是 missing 列表的输出顺序）
_SCORE_METRICS: tuple[str, ...] = ("fail_count", "gpa_drop", "attendance_rate")
# 可用指标不足时的灰档话术
REASON_INSUFFICIENT = "数据不足，无法评估"
# 少于这么多可用指标就不再重归权重（字典 3.2：1 项外推会凭空造出高风险档）
MIN_COVERAGE_TO_RESCALE = 2

MetricsFetcher = Callable[[int, str, str], Mapping[str, Any] | None]
RowsFetcher = Callable[[int, str, str], Sequence[Mapping[str, Any]]]


# ----------------------------------------------------------------
# 数值工具
# ----------------------------------------------------------------
def _round_half_up(value: float) -> int:
    """四舍五入（避免 Python round 的银行家舍入导致的不确定性）。"""
    return int(float(value) + 0.5) if float(value) >= 0 else -int(-float(value) + 0.5)


def _clamp(value: float, low: float, high: float) -> float:
    """把数值裁剪到 [low, high]。"""
    return max(low, min(high, float(value)))


def _fmt(value: float) -> str:
    """格式化数值：去掉无意义的小数尾零（11.60→"11.6"，12.0→"12"）。"""
    v = round(float(value), 2)
    if v == int(v):
        return str(int(v))
    return f"{v:.2f}".rstrip("0").rstrip(".")


def normalize_metrics(raw: Mapping[str, Any]) -> dict[str, Any]:
    """把原始行（MySQL Decimal / 手工 dict）统一转成标准 metrics 字典。

    **缺失即 None，不参与加权**：不写 0 / 0.0 / 1.0 填充（见 docs\指标口径字典.md 第 3.2 节）。
    class_rank_pct 仅供展示，不参与打分；缺失同样为 None。
    """
    def _f(key: str) -> float | None:
        v = raw.get(key)
        if v is None:
            return None
        return round(float(v), _METRIC_NDIGITS[key])

    fail_count = raw.get("fail_count")
    return {
        "fail_count": None if fail_count is None else int(fail_count),
        "gpa": _f("gpa"),
        "gpa_drop": _f("gpa_drop"),
        "attendance_rate": _f("attendance_rate"),
        "class_rank_pct": _f("class_rank_pct"),
    }


# ----------------------------------------------------------------
# MySQL 取数（每条 SQL 都带 tenant_id）
# ----------------------------------------------------------------
def _connect() -> pymysql.connections.Connection:
    """建立 MySQL 连接（口令只从 .env 读，禁止硬编码），字典游标。"""
    s = get_settings()
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


def _query(sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    """执行查询并返回全部字典行；连接不可用或表缺失时返回空列表。"""
    try:
        conn = _connect()
    except (pymysql.MySQLError, OSError):
        return []
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            return [dict(r) for r in rows]
    except (pymysql.MySQLError, OSError):
        # 阈值表/明细表不可用 → 交由上层按默认规则或空结果处理
        return []
    finally:
        conn.close()


def fetch_threshold_rows(tenant_id: int) -> list[dict[str, Any]]:
    """读取该租户的预警阈值行（WHERE tenant_id=?，禁止全表扫描）。"""
    sql = (
        "SELECT metric, weight, red_value, orange_value, yellow_value "
        "FROM warning_threshold WHERE tenant_id = %s ORDER BY metric"
    )
    return _query(sql, (tenant_id,))


def fetch_class_threshold_rows(tenant_id: int, class_name: str) -> list[dict[str, Any]]:
    """读取某班级的阈值覆盖行；无覆盖返回空列表。"""
    sql = (
        "SELECT metric, weight, red_value, orange_value, yellow_value "
        "FROM class_warning_threshold "
        "WHERE tenant_id = %s AND class_name = %s ORDER BY metric"
    )
    return _query(sql, (tenant_id, class_name))


def get_rules(tenant_id: int, class_name: str | None = None) -> WarningRules:
    """该租户/班级的预警规则：班级覆盖 > 租户默认 > 引擎内置默认。

    build_rules 按行顺序覆盖，因此把班级行放在租户行之后即可实现优先级。
    """
    rows = fetch_threshold_rows(tenant_id)
    if class_name:
        rows = rows + fetch_class_threshold_rows(tenant_id, class_name)
    return build_rules(tenant_id, rows)


def compute_rank_pct(gpa_of: Mapping[str, float]) -> dict[str, float]:
    """按班级均分算落后百分位：0.0=班级第一，1.0=班级末位。

    单人班级恒为 0.0；同分时按 student_no 升序打破平局，保证排序确定。
    """
    n = len(gpa_of)
    if n <= 1:
        return {sno: 0.0 for sno in gpa_of}
    ordered = sorted(gpa_of.items(), key=lambda kv: (-round(float(kv[1]), 2), kv[0]))
    return {sno: round(i / (n - 1), 4) for i, (sno, _g) in enumerate(ordered)}


def _fetch_previous_term(tenant_id: int, class_name: str, term: str) -> str | None:
    """返回该班级小于当前学期且最接近的学期号；不存在返回 None。"""
    sql = (
        "SELECT sc.term AS term "
        "FROM score sc "
        "JOIN student s ON s.id = sc.student_id "
        "WHERE s.tenant_id = %s AND s.class_name = %s AND sc.term < %s "
        "GROUP BY sc.term ORDER BY sc.term DESC LIMIT 1"
    )
    rows = _query(sql, (tenant_id, class_name, term))
    return str(rows[0]["term"]) if rows else None


def fetch_class_rows(tenant_id: int, class_name: str, term: str) -> list[dict[str, Any]]:
    """读取该租户某班级某学期的原始指标行（含 name），按 student_no 升序。

    仅对有成绩记录的学生出行；class_rank_pct 在本函数内按班级均分排名确定。
    缺考勤 / 无上学期成绩时对应字段一律为 None（不得按全勤 1.0 或下滑 0.0 冒充）。
    """
    cur_sql = (
        "SELECT s.student_no AS student_no, s.name AS name, "
        "       AVG(sc.score) AS gpa, "
        "       SUM(CASE WHEN sc.score < 60 THEN 1 ELSE 0 END) AS fail_count "
        "FROM student s "
        "JOIN score sc ON sc.student_id = s.id AND sc.term = %s "
        "WHERE s.tenant_id = %s AND s.class_name = %s "
        "GROUP BY s.student_no, s.name"
    )
    cur_rows = _query(cur_sql, (term, tenant_id, class_name))

    prev_term = _fetch_previous_term(tenant_id, class_name, term)
    prev_gpa: dict[str, float] = {}
    if prev_term is not None:
        prev_sql = (
            "SELECT s.student_no AS student_no, AVG(sc.score) AS gpa "
            "FROM student s "
            "JOIN score sc ON sc.student_id = s.id AND sc.term = %s "
            "WHERE s.tenant_id = %s AND s.class_name = %s "
            "GROUP BY s.student_no"
        )
        prev_gpa = {
            str(r["student_no"]): float(r["gpa"])
            for r in _query(prev_sql, (prev_term, tenant_id, class_name))
        }

    att_sql = (
        "SELECT s.student_no AS student_no, "
        "       SUM(a.total_sessions) AS total_sessions, "
        "       SUM(a.absent_sessions) AS absent_sessions "
        "FROM student s "
        "JOIN attendance a ON a.student_id = s.id AND a.term = %s "
        "WHERE s.tenant_id = %s AND s.class_name = %s "
        "GROUP BY s.student_no"
    )
    attendance: dict[str, float] = {}
    for r in _query(att_sql, (term, tenant_id, class_name)):
        total = float(r["total_sessions"] or 0)
        absent = float(r["absent_sessions"] or 0)
        if total > 0:
            attendance[str(r["student_no"])] = (total - absent) / total

    # class_rank_pct：按班级均分由高到低排名换算的落后百分位（0=第一，1=末位）
    gpa_of = {str(r["student_no"]): round(float(r["gpa"]), 2) for r in cur_rows}
    class_rank_pct = compute_rank_pct(gpa_of)

    rows: list[dict[str, Any]] = []
    for r in sorted(cur_rows, key=lambda x: str(x["student_no"])):
        sno = str(r["student_no"])
        gpa = gpa_of[sno]
        prev = prev_gpa.get(sno)
        # 方向显式化：先算「本学期 − 上学期」（正数=进步，与 profile.gpa_trend 同向），
        # 预警侧再取反写 gpa_drop（正数=下降），保证 gpa_drop == -gpa_trend（字典 1.1 节第 1 点）
        delta = round(gpa - prev, 2) if prev is not None else None
        gpa_drop = None if delta is None else round(-delta, 2)
        # 无考勤记录 → None（不得按 1.0 全勤处理）
        rate = attendance.get(sno)
        rows.append({
            "student_no": sno,
            "name": str(r["name"]) if r["name"] is not None else "",
            "class_name": class_name,
            "fail_count": int(r["fail_count"] or 0),
            "gpa": gpa,
            "gpa_drop": gpa_drop,
            "attendance_rate": None if rate is None else round(rate, 4),
            "class_rank_pct": class_rank_pct[sno],
        })
    return rows


def fetch_student_row(tenant_id: int, student_no: str, term: str) -> dict[str, Any] | None:
    """读取单个学生的原始指标行；无成绩记录返回 None。"""
    sql = (
        "SELECT s.student_no AS student_no, s.name AS name, s.class_name AS class_name "
        "FROM student s "
        "JOIN score sc ON sc.student_id = s.id AND sc.term = %s "
        "WHERE s.tenant_id = %s AND s.student_no = %s "
        "GROUP BY s.student_no, s.name, s.class_name"
    )
    rows = _query(sql, (term, tenant_id, student_no))
    if not rows:
        return None
    class_name = str(rows[0]["class_name"])
    for r in fetch_class_rows(tenant_id, class_name, term):
        if r["student_no"] == student_no:
            return r
    return None


# ----------------------------------------------------------------
# 打分 / 分级 / 归因（纯计算）
# ----------------------------------------------------------------
def _reason_templates(metrics: Mapping[str, Any]) -> dict[str, str]:
    """三条指标的模板化归因句式（数值全部取自 metrics，无主观词）。

    缺失项**不生成句子**（字典 3.2 节）：不得对 None 做 int()/float()。
    """
    templates: dict[str, str] = {}
    if metrics.get("fail_count") is not None:
        templates["fail_count"] = f"本学期挂科{int(metrics['fail_count'])}门"
    if metrics.get("gpa_drop") is not None:
        templates["gpa_drop"] = f"本学期平均成绩下滑{_fmt(metrics['gpa_drop'])}分"
    if metrics.get("attendance_rate") is not None:
        templates["attendance_rate"] = (
            f"本学期出勤率降至{_fmt(round(float(metrics['attendance_rate']) * 100, 1))}%"
        )
    return templates


def build_reasons(metrics: Mapping[str, Any], rules: WarningRules) -> list[str]:
    """取触发项中得分最高的 1~3 条归因，得分相同时按指标固定顺序。

    缺失（None）项直接跳过，不产生归因句。
    """
    scorers = {
        "fail_count": rules.fail_count.score,
        "gpa_drop": rules.gpa_drop.score,
        "attendance_rate": rules.attendance.score,
    }
    order = ("fail_count", "gpa_drop", "attendance_rate")
    # 只对非 None 项打分：None 直接跳过，不进计分规则（否则 float(None) 抛 TypeError）
    scores = {k: scorers[k](metrics[k]) for k in order if metrics.get(k) is not None}
    triggered = [(k, scores[k]) for k in order if k in scores and scores[k] > 0]
    triggered.sort(key=lambda kv: (-kv[1], order.index(kv[0])))
    templates = _reason_templates(metrics)
    return [templates[k] for k, _s in triggered[:3]]


def coverage_and_score(metrics: Mapping[str, Any], rules: WarningRules) -> tuple[int, int]:
    """返回 (可用指标数, 风险分)：只对可用项打分，权重在可用项内重新归一。

    factor = Σ三项 weight / Σ可用项 weight，**仅当 coverage >= MIN_COVERAGE_TO_RESCALE 时启用**；
    coverage < 2 时 factor = 1.0 —— 只有 1 项可用时外推会把 1 门挂科放大成 45 分，
    凭空造出高风险档，比不放大更糟（docs\指标口径字典.md 第 3.2 节第 2 条）。
    """
    scorers = {
        "fail_count": rules.fail_count.score,
        "gpa_drop": rules.gpa_drop.score,
        "attendance_rate": rules.attendance.score,
    }
    weights = {
        "fail_count": rules.fail_count.weight,
        "gpa_drop": rules.gpa_drop.weight,
        "attendance_rate": rules.attendance.weight,
    }
    available = [k for k in _SCORE_METRICS if metrics.get(k) is not None]
    coverage = len(available)
    raw_total = sum(scorers[k](metrics[k]) for k in available)

    factor = 1.0
    if coverage >= MIN_COVERAGE_TO_RESCALE:
        available_w = sum(weights[k] for k in available)
        total_w = sum(weights[k] for k in _SCORE_METRICS)
        factor = total_w / available_w if available_w > 0 else 1.0
    return coverage, int(_clamp(_round_half_up(raw_total * factor), SCORE_MIN, SCORE_MAX))


def risk_score_of(metrics: Mapping[str, Any], rules: WarningRules) -> int:
    """三项指标加权和（缺失项不参与），四舍五入后裁剪到 0~100。"""
    _coverage, score = coverage_and_score(metrics, rules)
    return score


def evaluate_student(
    student_no: str,
    metrics: Mapping[str, Any],
    rules: WarningRules,
    name: str = "",
) -> dict[str, Any]:
    """把一条原始指标行算成标准预警结果（纯函数，不碰 IO）。

    可用指标不足 MIN_COVERAGE_TO_RESCALE 项时给灰档 unknown，
    **不得标为绿色（正常）**——「没有数据」≠「一切正常」（字典 3.2 节第 3 条）。
    """
    m = normalize_metrics(metrics)
    coverage, score = coverage_and_score(m, rules)
    missing = [k for k in _SCORE_METRICS if m.get(k) is None]
    if coverage < MIN_COVERAGE_TO_RESCALE:
        # 数据不足：等级灰档、不参与红/橙/黄排名，reasons 给出固定话术
        return {
            "student_no": student_no,
            "name": name if name else str(metrics.get("name") or ""),
            "risk_score": score,
            "level": LEVEL_UNKNOWN,
            "reasons": [REASON_INSUFFICIENT],
            "coverage": coverage,
            "missing": missing,
            "metrics": m,
        }
    return {
        "student_no": student_no,
        "name": name if name else str(metrics.get("name") or ""),
        "risk_score": score,
        "level": rules.level_of(score),
        "reasons": build_reasons(m, rules),
        "coverage": coverage,
        "missing": missing,
        "metrics": m,
    }


# ----------------------------------------------------------------
# 对外接口
# ----------------------------------------------------------------
def compute_student(
    tenant_id: int,
    student_no: str,
    term: str,
    *,
    class_name: str | None = None,
    metrics: Mapping[str, Any] | None = None,
    rules: WarningRules | None = None,
    fetcher: MetricsFetcher | None = None,
) -> dict[str, Any]:
    """单个学生的预警结果。

    tenant_id 为强制入参，MySQL 取数一律带 WHERE tenant_id=?。
    metrics 非空时跳过取数（便于单测与离线复算）；不然用 fetcher，
    fetcher 为空则走默认 MySQL 取数。
    班级级阈值优先：class_name 可由调用方传入，也可从取数行里的 class_name 推导。
    """
    if metrics is None:
        if fetcher is not None:
            metrics = fetcher(tenant_id, student_no, term)
        else:
            metrics = fetch_student_row(tenant_id, student_no, term)

    effective_class = class_name or str((metrics or {}).get("class_name") or "")
    used_rules = rules if rules is not None else get_rules(tenant_id, effective_class or None)
    if metrics is None:
        return evaluate_student(student_no, {}, used_rules, name="")
    name = str(metrics.get("name") or "")
    return evaluate_student(student_no, metrics, used_rules, name=name)


def compute_class(
    tenant_id: int,
    class_name: str,
    term: str,
    *,
    rows: Sequence[Mapping[str, Any]] | None = None,
    rules: WarningRules | None = None,
    fetcher: RowsFetcher | None = None,
) -> list[dict[str, Any]]:
    """整班预警结果，按 risk_score 降序、student_no 升序排序。"""
    used_rules = rules if rules is not None else get_rules(tenant_id, class_name)
    if rows is None:
        if fetcher is not None:
            rows = fetcher(tenant_id, class_name, term)
        else:
            rows = fetch_class_rows(tenant_id, class_name, term)
    results = [
        evaluate_student(str(r.get("student_no") or ""), r, used_rules,
                         name=str(r.get("name") or ""))
        for r in rows
    ]
    results.sort(key=lambda x: (-x["risk_score"], x["student_no"]))
    return results


def get_warning_list(
    tenant_id: int,
    class_name: str,
    term: str,
    level: str | None = None,
    *,
    rows: Sequence[Mapping[str, Any]] | None = None,
    rules: WarningRules | None = None,
    fetcher: RowsFetcher | None = None,
) -> list[dict[str, Any]]:
    """按等级过滤的预警名单；level 为空返回全班，level 非法抛 ValueError。"""
    if level is not None and level not in LEVELS:
        raise ValueError(f"非法预警等级：{level}，可选 {LEVELS}")
    results = compute_class(
        tenant_id, class_name, term, rows=rows, rules=rules, fetcher=fetcher
    )
    if level is None:
        return results
    return [r for r in results if r["level"] == level]
