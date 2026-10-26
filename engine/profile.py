# engine/profile.py
# 职责：四维学生职业画像——特征构建 build_features / 标签合成 make_tags / 批量入库 batch_build
# 依赖：engine.store / app.config / pymysql；禁止调用大模型、禁止引入 Spark、无随机数
# 说明：归一化统一用「固定上下界 min-max + clamp」，纯行内计算，可被 PySpark 的 withColumn 逐列复现

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence

import pymysql

from app.config import get_settings
from engine.store import DuckDBStore, Store

# 画像计算版本号，写入 DuckDB student_feature.calc_version
CALC_VERSION = "v1.1"

# ----------------------------------------------------------------
# 归一化常量表（min-max 固定上下界 / 次数饱和值）
# 口径说明：每个子指标独立 clamp 到 [0,1]，不依赖批次分布，
# 因此在 PySpark 里只要平移同一组常量即可逐行计算（map-only，无需 shuffle）。
# ----------------------------------------------------------------
GPA_MIN, GPA_MAX = 0.0, 100.0            # 均分区间
TREND_MIN, TREND_MAX = -40.0, 20.0       # 两学期均分差值区间（负=退步；v1.1 由 -20 放宽）
# 极端退步阈值：<= 该值额外打标签，避免被 clamp 后与「无变化」混淆（口径字典第 2 节）
EXTREME_DECLINE_AT = -30.0
FAIL_CAP = 3.0                           # 挂科门次饱和值（≥3 门该项记 0）
LIBRARY_CAP = 60.0                       # 到馆/借阅次数饱和值（raw 给次数时使用）
PREF_CAP = 6.0                           # 选修方向门次饱和值
JOB_VIEW_CAP = 50.0                      # 岗位浏览次数饱和值
JOB_FAV_CAP = 20.0                       # 岗位收藏次数饱和值
CERT_CAP = 3.0                           # 证书个数饱和值
CONTEST_CAP = 2.0                        # 竞赛个数饱和值
PROJECT_CAP = 2.0                        # 项目个数饱和值
# job_view 频次换算成「方向频次」时的折扣：浏览弱于实际选课
JOB_VIEW_DIRECTION_WEIGHT = 0.5

# ----------------------------------------------------------------
# 维度内权重（缺失子指标不参与，剩余权重归一）
# ----------------------------------------------------------------
STUDY_WEIGHTS: dict[str, float] = {
    "gpa": 0.40, "gpa_trend": 0.20, "fail_count": 0.20, "major_rank_pct": 0.20,
}
BEHAVIOR_WEIGHTS: dict[str, float] = {
    "attendance_rate": 0.50, "library_activity": 0.30, "consumption_regularity": 0.20,
}
INTEREST_WEIGHTS: dict[str, float] = {
    "course_pref": 0.40, "job_view_cnt": 0.30, "job_favorite_cnt": 0.30,
}
ABILITY_WEIGHTS: dict[str, float] = {
    "project_cnt": 0.40, "cert_count": 0.30, "contest_count": 0.30,
}

# 学业档位门槛（rank_pct 越小越靠前：0=专业第一，1=专业末位）
RANK_TOP20 = 0.20
RANK_TOP50 = 0.50
# 能力短板优先级：项目经历最关键，其次证书、竞赛
ABILITY_PRIORITY: tuple[tuple[str, str], ...] = (
    ("project_cnt", "缺乏项目经历"),
    ("cert_count", "无技能证书"),
    ("contest_count", "未参加学科竞赛"),
)

# 标签常量
TAG_NO_DATA = "数据不足"
TAG_NO_STUDY = "学业数据不足"
TAG_NO_ABILITY = "能力数据不足"
TAG_NO_DIRECTION = "方向未明"
TAG_ABILITY_OK = "能力履历完整"
TAG_EXTREME_DECLINE = "学业急剧下滑"

# 原始行里允许出现的业务字段（用于判定「空数据兜底」）
_RAW_KEYS: tuple[str, ...] = (
    "gpa", "gpa_trend", "fail_count", "class_rank_pct", "major_rank_pct",
    "attendance_rate", "library_activity", "library_visit_cnt",
    "consumption_regularity", "course_pref", "job_view_cnt",
    "job_view_pref", "job_favorite_cnt",
    "cert_count", "contest_count", "project_cnt",
)


# ----------------------------------------------------------------
# 数值工具
# ----------------------------------------------------------------
def _as_float(value: Any) -> float | None:
    """把 Decimal / str / int 转成 float；None 与非法值返回 None（表示缺失）。"""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    """转成 int；None 与非法值返回 None。"""
    f = _as_float(value)
    return None if f is None else int(f)


def _clamp01(value: float) -> float:
    """裁剪到 [0,1] 并保留 4 位小数。"""
    return round(max(0.0, min(1.0, float(value))), 4)


def _min_max(value: float | None, low: float, high: float) -> float | None:
    """固定上下界 min-max 归一化：clamp 后线性映射到 [0,1]。"""
    if value is None:
        return None
    return _clamp01((float(value) - low) / (high - low))


def _saturate(value: float | None, cap: float) -> float | None:
    """次数类饱和归一化：min(1, value / cap)，负值记 0。"""
    if value is None:
        return None
    if cap <= 0:
        return None
    return _clamp01(float(value) / cap)


def _weighted_mean(norms: Mapping[str, float | None], weights: Mapping[str, float]) -> float | None:
    """按缺失项归一化后的权重求加权均值；全部缺失返回 None。"""
    total_w = 0.0
    total_v = 0.0
    for key, weight in weights.items():
        value = norms.get(key)
        if value is None:
            continue
        total_w += weight
        total_v += value * weight
    if total_w <= 0:
        return None
    return round(total_v / total_w, 4)


# ----------------------------------------------------------------
# 兴趣方向
# ----------------------------------------------------------------
def _count_map(raw: Mapping[str, Any], key: str) -> dict[str, float]:
    """取出 {方向: 次数} 形式的字典，非法类型一律忽略。"""
    value = raw.get(key)
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, float] = {}
    for direction, count in value.items():
        n = _as_float(count)
        if n is not None and n > 0:
            result[str(direction)] = result.get(str(direction), 0.0) + n
    return result


def top_direction(raw: Mapping[str, Any]) -> str | None:
    """合并 course_pref（权重 1）与 job_view_pref（权重 0.5）取频次最高方向。

    同频次时按方向名升序打破平局，保证结果确定。
    """
    freq: Counter[str] = Counter()
    for direction, count in _count_map(raw, "course_pref").items():
        freq[direction] += count
    for direction, count in _count_map(raw, "job_view_pref").items():
        freq[direction] += count * JOB_VIEW_DIRECTION_WEIGHT
    if not freq:
        return None
    # 频次取 4 位小数后再比较，避免浮点尾差影响排序
    return sorted(freq.items(), key=lambda kv: (-round(kv[1], 4), kv[0]))[0][0]


# ----------------------------------------------------------------
# 四维特征构建
# ----------------------------------------------------------------
def build_features(raw: Mapping[str, Any]) -> dict[str, Any]:
    """把一行原始宽表数据构建成四维画像特征（纯函数，缺失即 None）。

    raw 约定键（缺失的键表示该项无数据，不参与打分，也不写 0 冒充）：
      学业：gpa / gpa_trend（本学期 − 上学期，正数为进步）/ fail_count /
           major_rank_pct（专业口径，0=专业第一）/ class_rank_pct（班级口径，仅透传）
      行为：attendance_rate / library_activity(0-1) 或 library_visit_cnt(次数) / consumption_regularity
      兴趣：course_pref{方向:门次} / job_view_cnt / job_view_pref{方向:次数} / job_favorite_cnt
      能力：cert_count / contest_count / project_cnt
    """
    raw = raw or {}
    has_data = any(raw.get(k) is not None for k in _RAW_KEYS)

    # --- 学业 ---
    gpa = _as_float(raw.get("gpa"))
    gpa_trend = _as_float(raw.get("gpa_trend"))
    fail_count = _as_int(raw.get("fail_count"))
    major_rank_pct = _as_float(raw.get("major_rank_pct"))
    class_rank_pct = _as_float(raw.get("class_rank_pct"))
    extreme_decline = gpa_trend is not None and gpa_trend <= EXTREME_DECLINE_AT
    study_norm = {
        "gpa": _min_max(gpa, GPA_MIN, GPA_MAX),
        "gpa_trend": _min_max(gpa_trend, TREND_MIN, TREND_MAX),
        # 挂科越多分越低：0 门记 1.0，≥FAIL_CAP 门记 0.0
        "fail_count": (None if fail_count is None
                       else _clamp01(1.0 - min(1.0, max(0.0, fail_count) / FAIL_CAP))),
        "major_rank_pct": (None if major_rank_pct is None
                           else _clamp01(1.0 - major_rank_pct)),
    }

    # --- 行为 ---
    attendance_rate = _as_float(raw.get("attendance_rate"))
    library_visit = _as_float(raw.get("library_visit_cnt"))
    library_activity = _as_float(raw.get("library_activity"))
    if library_activity is None and library_visit is not None:
        library_activity = _saturate(library_visit, LIBRARY_CAP)
    else:
        library_activity = (None if library_activity is None
                            else _clamp01(library_activity))
    consumption = _as_float(raw.get("consumption_regularity"))
    behavior_norm = {
        "attendance_rate": (None if attendance_rate is None
                            else _clamp01(attendance_rate)),
        "library_activity": library_activity,
        "consumption_regularity": (None if consumption is None
                                   else _clamp01(consumption)),
    }

    # --- 兴趣 ---
    course_pref = _count_map(raw, "course_pref")
    job_view_cnt = _as_int(raw.get("job_view_cnt"))
    job_favorite_cnt = _as_int(raw.get("job_favorite_cnt"))
    pref_total = sum(course_pref.values()) if course_pref else None
    interest_norm = {
        "course_pref": _saturate(pref_total, PREF_CAP),
        "job_view_cnt": _saturate(job_view_cnt, JOB_VIEW_CAP),
        "job_favorite_cnt": _saturate(job_favorite_cnt, JOB_FAV_CAP),
    }

    # --- 能力 ---
    cert_count = _as_int(raw.get("cert_count"))
    contest_count = _as_int(raw.get("contest_count"))
    project_cnt = _as_int(raw.get("project_cnt"))
    ability_norm = {
        "cert_count": _saturate(cert_count, CERT_CAP),
        "contest_count": _saturate(contest_count, CONTEST_CAP),
        "project_cnt": _saturate(project_cnt, PROJECT_CAP),
    }

    features: dict[str, Any] = {
        "student_no": str(raw.get("student_no") or ""),
        "term": str(raw.get("term") or ""),
        "calc_version": CALC_VERSION,
        "has_data": has_data,
        "study": {
            "score": _weighted_mean(study_norm, STUDY_WEIGHTS),
            "gpa": None if gpa is None else round(gpa, 2),
            "gpa_trend": None if gpa_trend is None else round(gpa_trend, 2),
            "fail_count": fail_count,
            "major_rank_pct": (None if major_rank_pct is None
                               else _clamp01(major_rank_pct)),
            # 仅透传：不参与打分、不影响标签（教师端看板用）
            "class_rank_pct": (None if class_rank_pct is None
                               else _clamp01(class_rank_pct)),
            "extreme_decline": extreme_decline,
            "norm": study_norm,
        },
        "behavior": {
            "score": _weighted_mean(behavior_norm, BEHAVIOR_WEIGHTS),
            "attendance_rate": (None if attendance_rate is None
                                else _clamp01(attendance_rate)),
            "library_visit_cnt": (None if library_visit is None
                                  else int(library_visit)),
            "library_activity": library_activity,
            "consumption_regularity": (None if consumption is None
                                       else _clamp01(consumption)),
            "norm": behavior_norm,
        },
        "interest": {
            "score": _weighted_mean(interest_norm, INTEREST_WEIGHTS),
            "course_pref": course_pref,
            "top_direction": top_direction(raw),
            "job_view_cnt": job_view_cnt,
            "job_favorite_cnt": job_favorite_cnt,
            "norm": interest_norm,
        },
        "ability": {
            "score": _weighted_mean(ability_norm, ABILITY_WEIGHTS),
            "cert_count": cert_count,
            "contest_count": contest_count,
            "project_cnt": project_cnt,
            "norm": ability_norm,
        },
        "scores": {},
    }
    for dim in ("study", "behavior", "interest", "ability"):
        features["scores"][dim] = features[dim]["score"]
    features["tags"] = make_tags(features)
    return features


# ----------------------------------------------------------------
# 标签合成
# ----------------------------------------------------------------
def _study_tag(features: Mapping[str, Any]) -> str:
    """学业档位标签：前 20% / 前 50% / 后 50%，无 ranking 数据单独兜底。"""
    rank = features.get("study", {}).get("major_rank_pct")
    if rank is None:
        return TAG_NO_STUDY
    if rank <= RANK_TOP20:
        return "专业前20%"
    if rank <= RANK_TOP50:
        return "专业前50%"
    return "专业后50%"


def _ability_tag(features: Mapping[str, Any]) -> str:
    """能力短板标签：按 project > cert > contest 优先级取第一个为 0 的已知项。"""
    ability = features.get("ability", {})
    known = False
    for key, text in ABILITY_PRIORITY:
        value = ability.get(key)
        if value is None:
            continue
        known = True
        if int(value) == 0:
            return text
    return TAG_ABILITY_OK if known else TAG_NO_ABILITY


def make_tags(features: Mapping[str, Any]) -> list[str]:
    """合成三标签 [学业档位, 兴趣方向, 能力短板]；空数据返回 ["数据不足"]。

    极端退步（gpa_trend <= -30）时**追加**第 4 个标签，原三标签的构成与顺序不动。
    """
    if not features.get("has_data"):
        return [TAG_NO_DATA]
    direction = features.get("interest", {}).get("top_direction")
    if direction:
        suffix = "" if str(direction).endswith(("岗", "方向", "类")) else "岗"
        direction_tag = f"偏好{direction}{suffix}"
    else:
        direction_tag = TAG_NO_DIRECTION
    tags = [_study_tag(features), direction_tag, _ability_tag(features)]
    if features.get("study", {}).get("extreme_decline"):
        tags.append(TAG_EXTREME_DECLINE)
    return tags


# ----------------------------------------------------------------
# 落库行转换
# ----------------------------------------------------------------
def to_feature_row(features: Mapping[str, Any]) -> dict[str, Any]:
    """把画像特征转成 student_feature 表的一行（键与 store.write_student_feature 对齐）。

    v1.1 起 library_activity 列改为 DECIMAL(5,4)，直接写 0-1 原值，不再 ×100 折中；
    原始次数落在 library_visit_cnt（INTEGER）列。两个 rank 口径分列写入。
    """
    study = features.get("study", {})
    behavior = features.get("behavior", {})
    interest = features.get("interest", {})
    ability = features.get("ability", {})
    return {
        "student_no": features.get("student_no", ""),
        "term": features.get("term", ""),
        "gpa": study.get("gpa"),
        "gpa_trend": study.get("gpa_trend"),
        "extreme_decline": study.get("extreme_decline"),
        "fail_count": study.get("fail_count"),
        "class_rank_pct": study.get("class_rank_pct"),
        "major_rank_pct": study.get("major_rank_pct"),
        "attendance_rate": behavior.get("attendance_rate"),
        "library_visit_cnt": behavior.get("library_visit_cnt"),
        "library_activity": behavior.get("library_activity"),
        "consumption_regularity": behavior.get("consumption_regularity"),
        "course_pref": dict(interest.get("course_pref") or {}),
        "job_view_cnt": interest.get("job_view_cnt"),
        "job_favorite_cnt": interest.get("job_favorite_cnt"),
        "cert_count": ability.get("cert_count"),
        "contest_count": ability.get("contest_count"),
        "project_cnt": ability.get("project_cnt"),
        "tags": list(features.get("tags") or []),
        "calc_version": CALC_VERSION,
    }


# ----------------------------------------------------------------
# MySQL 取数（每条 SQL 都带 tenant_id）
# ----------------------------------------------------------------
def _connect() -> pymysql.connections.Connection:
    """建立 MySQL 连接（口令只从 .env 读），字典游标。"""
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
    """执行查询并返回字典行列表；库不可用时返回空列表。"""
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


def _term_aggregate(tenant_id: int, term: str) -> list[dict[str, Any]]:
    """取该租户某学期的学生均分、挂科数与所属专业、班级。"""
    sql = (
        "SELECT s.student_no AS student_no, s.name AS name, s.major AS major, "
        "       s.class_name AS class_name, "
        "       AVG(sc.score) AS gpa, "
        "       SUM(CASE WHEN sc.score < 60 THEN 1 ELSE 0 END) AS fail_count "
        "FROM student s "
        "JOIN score sc ON sc.student_id = s.id AND sc.term = %s "
        "WHERE s.tenant_id = %s "
        "GROUP BY s.student_no, s.name, s.major, s.class_name"
    )
    return _query(sql, (term, tenant_id))


def _previous_term(tenant_id: int, term: str) -> str | None:
    """取小于当前学期且最接近的学期号。"""
    sql = (
        "SELECT sc.term AS term "
        "FROM score sc "
        "JOIN student s ON s.id = sc.student_id "
        "WHERE s.tenant_id = %s AND sc.term < %s "
        "GROUP BY sc.term ORDER BY sc.term DESC LIMIT 1"
    )
    rows = _query(sql, (tenant_id, term))
    return str(rows[0]["term"]) if rows else None


def fetch_student_raw(tenant_id: int, term: str) -> list[dict[str, Any]]:
    """组装画像原始行：学业四项 + 出勤来自 MySQL，其余字段留空待 ETL 补。"""
    cur = _term_aggregate(tenant_id, term)
    prev_term = _previous_term(tenant_id, term)
    prev_gpa: dict[str, float] = {}
    if prev_term is not None:
        prev_gpa = {
            str(r["student_no"]): float(r["gpa"])
            for r in _term_aggregate(tenant_id, prev_term)
        }

    # 两种分组口径：班级（教师端看板用）/ 专业（画像打标签用）
    gpa_of = {str(r["student_no"]): float(r["gpa"]) for r in cur}
    major_rank_pct = compute_rank_pct(
        gpa_of, {str(r["student_no"]): str(r["major"]) for r in cur},
    )
    class_rank_pct = compute_rank_pct(
        gpa_of, {str(r["student_no"]): str(r["class_name"]) for r in cur},
    )

    att_sql = (
        "SELECT s.student_no AS student_no, "
        "       SUM(a.total_sessions) AS total_sessions, "
        "       SUM(a.absent_sessions) AS absent_sessions "
        "FROM student s "
        "JOIN attendance a ON a.student_id = s.id AND a.term = %s "
        "WHERE s.tenant_id = %s "
        "GROUP BY s.student_no"
    )
    attendance: dict[str, float] = {}
    for r in _query(att_sql, (term, tenant_id)):
        total = float(r["total_sessions"] or 0)
        if total > 0:
            attendance[str(r["student_no"])] = round(
                (total - float(r["absent_sessions"] or 0)) / total, 4
            )

    rows: list[dict[str, Any]] = []
    for r in sorted(cur, key=lambda x: str(x["student_no"])):
        sno = str(r["student_no"])
        gpa = round(float(r["gpa"]), 2)
        prev = prev_gpa.get(sno)
        rows.append({
            "student_no": sno,
            "name": str(r["name"] or ""),
            "term": term,
            "gpa": gpa,
            "gpa_trend": round(gpa - prev, 2) if prev is not None else None,
            "fail_count": int(r["fail_count"] or 0),
            "major_rank_pct": major_rank_pct.get(sno),
            "class_rank_pct": class_rank_pct.get(sno),
            "attendance_rate": attendance.get(sno),
        })
    return rows


def compute_rank_pct(
    gpa_of: Mapping[str, float],
    group_of: Mapping[str, str] | None = None,
) -> dict[str, float]:
    """按组（默认全体）算专业排名百分位：0.0=第一，1.0=末位。

    单人组恒为 0.0；同分按 student_no 升序定序，保证 PySpark 复算结果一致。
    """
    groups: dict[str, list[str]] = {}
    for sno in gpa_of:
        key = str(group_of.get(sno)) if group_of else "__all__"
        groups.setdefault(key, []).append(sno)
    result: dict[str, float] = {}
    for members in groups.values():
        ordered = sorted(members, key=lambda s: (-round(float(gpa_of[s]), 2), s))
        n = len(ordered)
        if n <= 1:
            result[ordered[0]] = 0.0
            continue
        for i, sno in enumerate(ordered):
            result[sno] = round(i / (n - 1), 4)
    return result


# ----------------------------------------------------------------
# 批量计算 + upsert
# ----------------------------------------------------------------
def batch_build(
    tenant_id: int,
    term: str,
    *,
    raw_rows: Sequence[Mapping[str, Any]] | None = None,
    store: Store | None = None,
) -> int:
    """整批计算画像并 upsert 到 DuckDB student_feature，返回写入条数。

    raw_rows 非空时跳过 MySQL 取数；store 非空时用指定存储（便于单测隔离）。
    主键 (student_no, term) 使 upsert 幂等：重复执行行数不变、内容覆盖。
    """
    rows = raw_rows if raw_rows is not None else fetch_student_raw(tenant_id, term)
    target = store if store is not None else DuckDBStore()
    count = 0
    for raw in rows:
        features = build_features(raw)
        row = to_feature_row(features)
        if not row["term"]:
            row["term"] = term
        target.write_student_feature(row)
        count += 1
    return count
