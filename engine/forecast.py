# engine/forecast.py
# 职责：学业预测引擎——按学期序列外推下学期均分、课程挂科风险、预警等级走向
# 铁律：数值全部确定性计算（加权最小二乘），禁止 import LLM；SQL 一律带租户编号
# 说明：历史学期不足 2 个时返回 unavailable，不冒充预测值（缺失不冒充）

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

import pymysql

from app.config import get_settings
from engine.warning import evaluate_student, get_rules

# 引擎版本号，用于前端/审计溯源
FORECAST_VERSION = "forecast-v1"

# 学期权重衰减：越近的学期权重越高（0.6 = 每远一个学期权重 ×0.6）
TREND_DECAY = 0.6
# 趋势判定阈值：每学期均分变化超过 ±0.5 分才算升/降，否则平稳
TREND_THRESHOLD = 0.5
# 95% 置信区间倍数
Z_95 = 1.96
# 残差不足时的最小波动（只有 2 个学期时残差必为 0，不能显得过度确定）
MIN_SPREAD = 1.0
# 预测所需的最少学期数
MIN_TERMS = 2
# 课程挂科线
PASS_SCORE = 60.0
# 高风险课程：该生该课分数低于此值才列入
RISKY_SCORE = 70.0
# 该课同租户历史挂科率高于此值也算高风险
HIGH_FAIL_RATE = 0.15
# 距挂科线多少分算「基本安全」：课程风险的低分程度按此折算
RISK_MARGIN = 15.0
# 风险等级切分
RISK_HIGH = 0.35
RISK_MID = 0.20


# ----------------------------------------------------------------
# MySQL 取数（每条 SQL 都带租户编号）
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
            return [dict(r) for r in cur.fetchall()]
    except (pymysql.MySQLError, OSError):
        return []
    finally:
        conn.close()


def fetch_profile(tenant_id: int, student_no: str) -> dict[str, Any]:
    """学生姓名 / 班级；查不到返回空字典。"""
    sql = ("SELECT s.`姓名` AS name, s.`班级` AS class_name "
           "FROM `学生` s WHERE s.`租户编号` = %s AND s.`学号` = %s")
    rows = _query(sql, (tenant_id, student_no))
    return rows[0] if rows else {}


def fetch_profile_by_id(tenant_id: int, student_id: int) -> dict[str, Any]:
    """按内部主键取学号/姓名/班级（路由层只有 ctx.student_id 主键，没有学号）。"""
    sql = ("SELECT s.`学号` AS student_no, s.`姓名` AS name, s.`班级` AS class_name "
           "FROM `学生` s WHERE s.`租户编号` = %s AND s.`编号` = %s")
    rows = _query(sql, (tenant_id, student_id))
    return rows[0] if rows else {}


def fetch_term_series(tenant_id: int, student_no: str) -> list[dict[str, Any]]:
    """该生各学期的均分 / 挂科门数 / 课程数，按学期升序。"""
    sql = (
        "SELECT sc.`学期` AS term, "
        "       AVG(sc.`分数`) AS gpa, "
        "       SUM(CASE WHEN sc.`分数` < %s THEN 1 ELSE 0 END) AS fail_count, "
        "       COUNT(*) AS course_count "
        "FROM `成绩` sc JOIN `学生` s ON s.`编号` = sc.`学生编号` "
        "WHERE s.`租户编号` = %s AND s.`学号` = %s "
        "GROUP BY sc.`学期` ORDER BY sc.`学期`"
    )
    return _query(sql, (PASS_SCORE, tenant_id, student_no))


def fetch_course_rows(tenant_id: int, student_no: str) -> list[dict[str, Any]]:
    """该生各科成绩（含课程名称），按学期升序。"""
    sql = (
        "SELECT sc.`课程编号` AS course_code, c.`课程名称` AS course_name, "
        "       sc.`学期` AS term, sc.`分数` AS score "
        "FROM `成绩` sc "
        "JOIN `学生` s ON s.`编号` = sc.`学生编号` "
        "LEFT JOIN `课程` c ON c.`编号` = sc.`课程编号` "
        "WHERE s.`租户编号` = %s AND s.`学号` = %s "
        "ORDER BY sc.`学期`, sc.`课程编号`"
    )
    return _query(sql, (tenant_id, student_no))


def fetch_course_stats(tenant_id: int,
                       course_codes: Sequence[Any]) -> dict[str, dict[str, Any]]:
    """这些课程在同租户内的历史均分与挂科率（课程风险的客观基准）。"""
    if not course_codes:
        return {}
    codes = [str(c) for c in course_codes]
    placeholders = ",".join(["%s"] * len(codes))
    sql = (
        "SELECT sc.`课程编号` AS course_code, "
        "       AVG(sc.`分数`) AS avg_score, "
        "       SUM(CASE WHEN sc.`分数` < %s THEN 1 ELSE 0 END) AS fail_n, "
        "       COUNT(*) AS total "
        "FROM `成绩` sc JOIN `学生` s ON s.`编号` = sc.`学生编号` "
        f"WHERE s.`租户编号` = %s AND sc.`课程编号` IN ({placeholders}) "
        "GROUP BY sc.`课程编号`"
    )
    out: dict[str, dict[str, Any]] = {}
    for r in _query(sql, (PASS_SCORE, tenant_id, *codes)):
        total = int(r["total"] or 0)
        avg = r["avg_score"]
        out[str(r["course_code"])] = {
            "avg_score": round(float(avg), 2) if avg is not None else None,
            "fail_rate": round(int(r["fail_n"] or 0) / total, 4) if total else None,
            "sample": total,
        }
    return out


def fetch_attendance(tenant_id: int, student_no: str, term: str) -> float | None:
    """该生某学期出勤率；无考勤记录返回 None（不得按全勤处理）。"""
    sql = (
        "SELECT a.`应到次数` AS total, a.`缺勤次数` AS absent "
        "FROM `考勤` a JOIN `学生` s ON s.`编号` = a.`学生编号` "
        "WHERE s.`租户编号` = %s AND s.`学号` = %s AND a.`学期` = %s"
    )
    rows = _query(sql, (tenant_id, student_no, term))
    total = sum(float(r["total"] or 0) for r in rows)
    if total <= 0:
        return None
    absent = sum(float(r["absent"] or 0) for r in rows)
    return round((total - absent) / total, 4)


# ----------------------------------------------------------------
# 纯函数（无 IO，可独立测试）
# ----------------------------------------------------------------
def weighted_fit(values: Sequence[float],
                 decay: float = TREND_DECAY) -> tuple[float, float, float]:
    """加权最小二乘拟合 y = a + b·x，返回 (截距, 斜率, 加权残差标准差)。

    x 取学期序号 0..n-1，权重 decay^(n-1-i)（越近的学期权重越高）。
    n < 2 时斜率不可确定，返回 (最后一个值, 0.0, 0.0)。
    """
    nums = [float(v) for v in values]
    n = len(nums)
    if n == 0:
        return 0.0, 0.0, 0.0
    if n < 2:
        return nums[0], 0.0, 0.0
    weights = [decay ** (n - 1 - i) for i in range(n)]
    total_w = sum(weights)
    mean_x = sum(w * i for w, i in zip(weights, range(n))) / total_w
    mean_y = sum(w * y for w, y in zip(weights, nums)) / total_w
    sxx = sum(w * (i - mean_x) ** 2 for w, i in zip(weights, range(n)))
    sxy = sum(w * (i - mean_x) * (y - mean_y)
              for w, (i, y) in zip(weights, enumerate(nums)))
    slope = sxy / sxx if sxx > 0 else 0.0
    intercept = mean_y - slope * mean_x
    resid = sum(w * (y - (intercept + slope * i)) ** 2
                for w, (i, y) in zip(weights, enumerate(nums))) / total_w
    return intercept, slope, math.sqrt(max(resid, 0.0))


def trend_of(slope: float | None) -> str:
    """斜率 → 趋势文案；超过 ±TREND_THRESHOLD 才算升/降。"""
    if slope is None:
        return "unknown"
    if slope > TREND_THRESHOLD:
        return "上升"
    if slope < -TREND_THRESHOLD:
        return "下降"
    return "平稳"


def confidence_of(terms: int) -> str:
    """样本学期数 → 预测置信度（只做档位划分，不冒充精确概率）。"""
    if terms >= 6:
        return "高"
    if terms >= 4:
        return "中"
    if terms >= MIN_TERMS:
        return "低"
    return "insufficient"


def forecast_next(values: Sequence[float],
                  decay: float = TREND_DECAY) -> dict[str, Any]:
    """外推序列下一期：预测值 / 趋势 / 95% 区间 / 置信度。"""
    nums = [float(v) for v in values]
    n = len(nums)
    if n < MIN_TERMS:
        return {"predicted": None, "trend": "unknown", "slope": None,
                "low": None, "high": None, "terms_used": n,
                "confidence": "insufficient"}
    intercept, slope, std = weighted_fit(nums, decay)
    predicted = intercept + slope * n
    spread = max(std, MIN_SPREAD) * Z_95
    return {
        "predicted": round(predicted, 2),
        "trend": trend_of(slope),
        "slope": round(slope, 2),
        "low": round(predicted - spread, 2),
        "high": round(predicted + spread, 2),
        "terms_used": n,
        "confidence": confidence_of(n),
    }


def next_term(term: str) -> str:
    """学期推进：2025-2026-1 → 2025-2026-2；2025-2026-2 → 2026-2027-1。"""
    parts = str(term or "").split("-")
    try:
        y1, y2, idx = int(parts[0]), int(parts[1]), int(parts[2])
    except (IndexError, ValueError):
        return ""
    if idx == 1:
        return f"{y1}-{y2}-2"
    return f"{y1 + 1}-{y2 + 1}-1"


def risky_courses(course_rows: Sequence[Mapping[str, Any]],
                  stats: Mapping[str, Mapping[str, Any]],
                  limit: int = 5) -> list[dict[str, Any]]:
    """历史薄弱课程 + 该课挂科率 → 风险清单（按风险分降序）。

    库内没有下学期课表，因此只对「该生已修且分数偏低」或「该课历史挂科率高」
    的课程给风险，用途是提示补强方向，不冒充「下学期必挂哪门课」。
    """
    latest: dict[str, dict[str, Any]] = {}
    for r in course_rows:
        code = str(r.get("course_code") or "")
        raw = r.get("score")
        if raw is None:
            continue
        try:
            score = float(raw)
        except (TypeError, ValueError):
            continue
        prev = latest.get(code)
        if prev is None or str(r.get("term") or "") >= str(prev["term"]):
            latest[code] = {
                "course_code": code,
                "course_name": str(r.get("course_name") or f"课程{code}"),
                "term": str(r.get("term") or ""),
                "score": round(score, 2),
            }

    out: list[dict[str, Any]] = []
    for code, item in latest.items():
        st = stats.get(code) or {}
        fail_rate = st.get("fail_rate")
        score = item["score"]
        # 低分程度按「距挂科线的余量」折算：已挂科 = 1.0，高出 RISK_MARGIN 分 = 0.0
        margin = score - PASS_SCORE
        if margin <= 0:
            low_part = 1.0
        elif margin >= RISK_MARGIN:
            low_part = 0.0
        else:
            low_part = 1.0 - margin / RISK_MARGIN
        rate_part = float(fail_rate or 0.0)
        risk = round(low_part * 0.6 + rate_part * 0.4, 4)
        if score >= RISKY_SCORE and not (fail_rate is not None
                                         and fail_rate >= HIGH_FAIL_RATE):
            continue
        level = "高" if risk >= RISK_HIGH else ("中" if risk >= RISK_MID else "低")
        out.append({
            "course_code": code,
            "course_name": item["course_name"],
            "last_term": item["term"],
            "last_score": score,
            "course_fail_rate": fail_rate,
            "course_avg_score": st.get("avg_score"),
            "risk_score": risk,
            "risk_level": level,
        })
    out.sort(key=lambda x: (-x["risk_score"], x["course_code"]))
    return out[:limit]


def forecast_level(tenant_id: int,
                   student_no: str,
                   class_name: str,
                   name: str,
                   predicted_gpa: float | None,
                   predicted_fail: float | None,
                   last_gpa: float | None,
                   attendance: float | None) -> dict[str, Any]:
    """把预测值代入现有预警规则，给出下学期预警等级走向。

    复用 engine.warning 的分级口径（同一套规则，不另立一套），
    gpa_drop 沿用「正数=下降」的约定。
    """
    rules = get_rules(tenant_id, class_name or None)
    gpa_drop: float | None = None
    if predicted_gpa is not None and last_gpa is not None:
        gpa_drop = round(last_gpa - predicted_gpa, 2)
    metrics = {
        "student_no": student_no,
        "name": name,
        "class_name": class_name or "",
        "gpa": predicted_gpa,
        "fail_count": None if predicted_fail is None else int(round(predicted_fail)),
        "gpa_drop": gpa_drop,
        "attendance_rate": attendance,
    }
    return evaluate_student(student_no, metrics, rules, name=name)


# ----------------------------------------------------------------
# 对外主入口
# ----------------------------------------------------------------
def compute_student_forecast(
    tenant_id: int,
    student_no: str,
    *,
    series: Sequence[Mapping[str, Any]] | None = None,
    course_rows: Sequence[Mapping[str, Any]] | None = None,
    attendance: float | None = None,
    profile: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """学生学业预测（均分 / 挂科 / 预警等级三项）。

    series / course_rows / profile 可注入以便单测（纯函数优先，便于迁移 Spark）。
    """
    prof = dict(profile) if profile is not None else fetch_profile(tenant_id, student_no)
    name = str(prof.get("name") or "")
    class_name = str(prof.get("class_name") or "")

    rows = list(series) if series is not None else fetch_term_series(tenant_id, student_no)
    base: dict[str, Any] = {
        "engine_version": FORECAST_VERSION,
        "student_no": str(student_no),
        "name": name,
        "class_name": class_name,
    }
    if len(rows) < MIN_TERMS:
        base.update({
            "available": False,
            "reason": f"历史学期不足（需要至少 {MIN_TERMS} 个学期，当前 {len(rows)} 个）",
            "history": [],
            "gpa_forecast": forecast_next([]),
            "fail_forecast": forecast_next([]),
            "level_forecast": {},
            "risky_courses": [],
        })
        return base

    history = [{
        "term": str(r.get("term") or ""),
        "gpa": round(float(r["gpa"]), 2) if r.get("gpa") is not None else None,
        "fail_count": int(r.get("fail_count") or 0),
        "course_count": int(r.get("course_count") or 0),
    } for r in rows]

    gpas = [h["gpa"] for h in history if h["gpa"] is not None]
    fails = [float(h["fail_count"]) for h in history]
    last_term = history[-1]["term"]
    last_gpa = gpas[-1] if gpas else None

    gpa_forecast = forecast_next(gpas)
    fail_forecast = forecast_next(fails)
    predicted_fail = fail_forecast["predicted"]
    if predicted_fail is not None:
        # 挂科门数不能为负，也不做小数展示
        predicted_fail = float(max(0, int(round(predicted_fail))))
        fail_forecast = dict(fail_forecast, predicted=predicted_fail)

    att = attendance if attendance is not None else (
        fetch_attendance(tenant_id, student_no, last_term) if last_term else None)
    level = forecast_level(tenant_id, student_no, class_name, name,
                           gpa_forecast["predicted"], predicted_fail,
                           last_gpa, att)

    crows = list(course_rows) if course_rows is not None else fetch_course_rows(
        tenant_id, student_no)
    stats = fetch_course_stats(tenant_id, [r.get("course_code") for r in crows])

    base.update({
        "available": True,
        "reason": "",
        "base_term": last_term,
        "next_term": next_term(last_term),
        "history": history,
        "gpa_forecast": gpa_forecast,
        "fail_forecast": fail_forecast,
        "level_forecast": {
            "level": str(level.get("level") or ""),
            "risk_score": level.get("risk_score"),
            "reasons": list(level.get("reasons") or []),
            "coverage": level.get("coverage"),
            "missing": list(level.get("missing") or []),
        },
        "risky_courses": risky_courses(crows, stats),
        "assumptions": [
            f"均分/挂科按该生 {len(gpas)} 个学期的加权回归外推，近期学期权重更高",
            "下学期课表库内暂无，课程风险按历史薄弱科目与课程挂科率给出",
            "出勤率按最近学期实际值假设不变（库内无出勤率的历史预测依据）",
        ],
    })
    return base
