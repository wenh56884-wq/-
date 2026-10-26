# scripts/build_profile_raw.py
# 职责：查齐「学业+出勤」与 7 类新源数据 → 组装完整 raw rows → 交给 engine.profile.batch_build
# 依赖：pymysql / app.config / engine.profile（只调用，不修改引擎）
# 说明：全部 SQL 带 WHERE s.tenant_id = %s；脚本不预归一，library_activity 由 build_features 从次数归一
# 口径：gpa_trend = 本期 − 上期（正数=进步）；rank_pct 按专业分组（0=第一）；缺失即不写键

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pymysql

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.config import get_settings  # noqa: E402
from engine.profile import batch_build, compute_rank_pct  # noqa: E402

# 一卡通活跃天数上限（docs\指标口径字典.md 第 1 节：min(1, active_days / 120)）
CONSUME_DAY_CAP = 120.0

# 7 类新特征对应的 raw 行键
FEATURE_KEYS: tuple[str, ...] = (
    "library_visit_cnt", "consumption_regularity",
    "cert_count", "contest_count", "project_cnt",
    "job_view_cnt", "job_favorite_cnt",
)

# activity_type → raw 行键
_ACTIVITY_KEYS = {"cert": "cert_count", "contest": "contest_count", "project": "project_cnt"}

# ----------------------------------------------------------------
# 兴趣方向词典（顺序敏感：先匹配者优先）
# 覆盖要求的数据/算法/后端/前端/测试/运维/金融/财务/运营/产品，匹配不上归「其他」
# ----------------------------------------------------------------
DIRECTION_OTHER = "其他"
DIRECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("算法", ("机器学习", "深度学习", "算法", "人工智能", "大模型", "视觉", "图像", "nlp", "自然语言处理")),
    ("数据", ("数据分析", "大数据分析", "大数据", "数据仓库", "etl", "bi", "商业分析", "数据统计", "数据")),
    ("前端", ("前端", "web", "h5", "小程序", "vue", "react", "安卓", "ios", "ui设计")),
    ("后端", ("后端", "服务端", "java", "c++", "go开发", "php", ".net", "python", "全栈", "开发")),
    ("测试", ("测试", "qa", "品质")),
    ("运维", ("运维", "devops", "sre", "实施工程师", "网络管理", "系统工程师", "技术支持")),
    ("产品", ("产品经理", "产品助理", "需求分析", "产品")),
    ("运营", ("运营", "电商", "直播", "推广", "社群", "策划", "内容", "市场", "招商")),
    ("金融", ("银行", "证券", "投资", "金融", "风控", "信贷", "基金", "保险", "理财", "柜员", "信托", "清算")),
    ("财务", ("会计", "财务", "审计", "税务", "出纳", "核算", "预算", "报税")),
)


def classify_direction(title: str) -> str:
    """把岗位标题映射成兴趣方向；匹配不到返回「其他」。"""
    low = str(title or "").lower()
    for direction, keywords in DIRECTIONS:
        if any(k in low for k in keywords):
            return direction
    return DIRECTION_OTHER


# ----------------------------------------------------------------
# MySQL 取数（每条 SQL 都带 s.tenant_id）
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
    )


def _query(sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    """执行查询并返回字典行；库不可用时返回空列表（离线单测可对此打桩）。"""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
    except (pymysql.MySQLError, OSError):
        return []
    finally:
        conn.close()


def load_study_base(tenant_id: int, term: str) -> list[dict[str, Any]]:
    """学业四项 + 出勤（口径与 engine/profile.py: fetch_student_raw 一致）。

    每行：student_no / name / term / gpa / gpa_trend / fail_count /
    rank_pct（专业分组，0=第一） / attendance_rate（无考勤记 None）。
    """
    cur_sql = (
        "SELECT s.student_no AS student_no, s.name AS name, s.major AS major, "
        "       AVG(sc.score) AS gpa, "
        "       SUM(CASE WHEN sc.score < 60 THEN 1 ELSE 0 END) AS fail_count "
        "FROM student s "
        "JOIN score sc ON sc.student_id = s.id AND sc.term = %s "
        "WHERE s.tenant_id = %s "
        "GROUP BY s.student_no, s.name, s.major"
    )
    cur_rows = _query(cur_sql, (term, tenant_id))

    prev_sql = (
        "SELECT sc.term AS term "
        "FROM score sc "
        "JOIN student s ON s.id = sc.student_id "
        "WHERE s.tenant_id = %s AND sc.term < %s "
        "GROUP BY sc.term ORDER BY sc.term DESC LIMIT 1"
    )
    prev_rows = _query(prev_sql, (tenant_id, term))
    prev_gpa: dict[str, float] = {}
    if prev_rows:
        prev_term = str(prev_rows[0]["term"])
        prev_sql = (
            "SELECT s.student_no AS student_no, AVG(sc.score) AS gpa "
            "FROM student s "
            "JOIN score sc ON sc.student_id = s.id AND sc.term = %s "
            "WHERE s.tenant_id = %s "
            "GROUP BY s.student_no"
        )
        prev_gpa = {str(r["student_no"]): float(r["gpa"])
                    for r in _query(prev_sql, (prev_term, tenant_id))}

    gpa_of = {str(r["student_no"]): float(r["gpa"]) for r in cur_rows}
    group_of = {str(r["student_no"]): str(r["major"]) for r in cur_rows}
    rank_pct = compute_rank_pct(gpa_of, group_of)

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
    for r in sorted(cur_rows, key=lambda x: str(x["student_no"])):
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
            "rank_pct": rank_pct.get(sno),
            # 口径字典：无考勤记 None，不得按 1.0 处理
            "attendance_rate": attendance.get(sno),
        })
    return rows


def load_library(tenant_id: int, term: str) -> dict[str, int]:
    """library_visit_cnt：原始到馆次数（不预归一，交给 build_features）。"""
    sql = (
        "SELECT s.student_no AS student_no, SUM(lr.visit_cnt) AS visit_cnt "
        "FROM library_record lr "
        "JOIN student s ON s.id = lr.student_id "
        "WHERE s.tenant_id = %s AND lr.term = %s "
        "GROUP BY s.student_no"
    )
    return {str(r["student_no"]): int(r["visit_cnt"] or 0)
            for r in _query(sql, (tenant_id, term))}


def load_consumption(tenant_id: int, term: str) -> dict[str, float]:
    """consumption_regularity = min(1, active_days / 120)。"""
    sql = (
        "SELECT s.student_no AS student_no, SUM(cr.active_days) AS active_days "
        "FROM consumption_record cr "
        "JOIN student s ON s.id = cr.student_id "
        "WHERE s.tenant_id = %s AND cr.term = %s "
        "GROUP BY s.student_no"
    )
    return {
        str(r["student_no"]): min(1.0, round(float(r["active_days"] or 0) / CONSUME_DAY_CAP, 4))
        for r in _query(sql, (tenant_id, term))
    }


def load_activity_counts(tenant_id: int, term: str) -> dict[str, dict[str, int]]:
    """证书/竞赛/项目计数：按 student_no + activity_type 聚合，无记录的类型不出现。"""
    sql = (
        "SELECT s.student_no AS student_no, sa.activity_type AS activity_type, "
        "       COUNT(*) AS cnt "
        "FROM student_activity sa "
        "JOIN student s ON s.id = sa.student_id "
        "WHERE s.tenant_id = %s AND sa.term = %s "
        "GROUP BY s.student_no, sa.activity_type"
    )
    result: dict[str, dict[str, int]] = {}
    for r in _query(sql, (tenant_id, term)):
        sno = str(r["student_no"])
        counts = result.setdefault(sno, {})
        kind = str(r["activity_type"])
        if kind in _ACTIVITY_KEYS:
            counts[kind] = int(r["cnt"] or 0)
    return result


def load_job_view_counts(tenant_id: int, term: str) -> tuple[dict[str, int], dict[str, int]]:
    """岗位浏览/收藏计数：返回 (view 计数 dict, favorite 计数 dict)。"""
    sql = (
        "SELECT s.student_no AS student_no, jvl.action AS action, COUNT(*) AS cnt "
        "FROM job_view_log jvl "
        "JOIN student s ON s.id = jvl.student_id "
        "WHERE s.tenant_id = %s AND jvl.term = %s "
        "GROUP BY s.student_no, jvl.action"
    )
    views: dict[str, int] = {}
    favorites: dict[str, int] = {}
    for r in _query(sql, (tenant_id, term)):
        sno = str(r["student_no"])
        cnt = int(r["cnt"] or 0)
        if str(r["action"]) == "view":
            views[sno] = cnt
        elif str(r["action"]) == "favorite":
            favorites[sno] = cnt
    return views, favorites


def load_job_view_pref(tenant_id: int, term: str) -> dict[str, dict[str, int]]:
    """job_view_pref：view 流水 JOIN job 表，按标题匹配方向词典聚合成 {方向: 次数}。"""
    sql = (
        "SELECT s.student_no AS student_no, j.title AS title "
        "FROM job_view_log jvl "
        "JOIN job j ON j.id = jvl.job_id "
        "JOIN student s ON s.id = jvl.student_id "
        "WHERE s.tenant_id = %s AND jvl.term = %s AND jvl.action = 'view'"
    )
    result: dict[str, dict[str, int]] = {}
    for r in _query(sql, (tenant_id, term)):
        sno = str(r["student_no"])
        direction = classify_direction(r["title"])
        freq = result.setdefault(sno, {})
        freq[direction] = freq.get(direction, 0) + 1
    return result


def assemble_rows(tenant_id: int, term: str) -> list[dict[str, Any]]:
    """组装完整 raw rows：学业+出勤 + 7 类新特征（无源数据一律不写该键）。"""
    rows = load_study_base(tenant_id, term)
    library = load_library(tenant_id, term)
    consumption = load_consumption(tenant_id, term)
    activity = load_activity_counts(tenant_id, term)
    views, favorites = load_job_view_counts(tenant_id, term)
    prefs = load_job_view_pref(tenant_id, term)

    for row in rows:
        sno = row["student_no"]
        if sno in library:
            row["library_visit_cnt"] = library[sno]
        if sno in consumption:
            row["consumption_regularity"] = consumption[sno]
        counts = activity.get(sno)
        # 活动表整份都没记录 → 三个键都不写（缺失语义，禁止补 0）；
        # 有记录但某类型为 0 → 写真实 0（这才让「缺乏项目经历」标签出得来）
        if counts is not None:
            for kind, key in _ACTIVITY_KEYS.items():
                row[key] = int(counts.get(kind, 0))
        if sno in views:
            row["job_view_cnt"] = views[sno]
        if sno in favorites:
            row["job_favorite_cnt"] = favorites[sno]
        pref = prefs.get(sno)
        if pref:
            row["job_view_pref"] = dict(sorted(pref.items(), key=lambda kv: (-kv[1], kv[0])))
    return rows


def feature_coverage(rows: list[dict[str, Any]]) -> dict[str, float]:
    """统计 7 类新特征的非空率（0~1），用于验收自检。"""
    total = len(rows)
    if total == 0:
        return {key: 0.0 for key in FEATURE_KEYS}
    return {
        key: round(sum(1 for r in rows if key in r) / total, 4) for key in FEATURE_KEYS
    }


def main(argv: list[str] | None = None) -> int:
    """命令行入口：--term 指定学期，--dry-run 只组装打印不写 DuckDB。"""
    parser = argparse.ArgumentParser(description="组装画像 raw rows 并写入 student_feature")
    parser.add_argument("--term", default="2025-2026-2", help="学期，如 2025-2026-2")
    parser.add_argument("--tenant-id", type=int, default=1, help="租户 id")
    parser.add_argument("--dry-run", action="store_true", help="只组装与打印，不写库")
    args = parser.parse_args(argv)

    rows = assemble_rows(args.tenant_id, args.term)
    coverage = feature_coverage(rows)
    print(f"租户 {args.tenant_id} · 学期 {args.term} · 组装 raw rows：{len(rows)} 行")
    print("7 类新特征非空率：")
    for key in FEATURE_KEYS:
        print(f"  {key:<24} {coverage[key] * 100:6.2f}%")
    if args.dry_run:
        print("[dry-run] 未写库，样例首行：")
        print(json.dumps(rows[0], ensure_ascii=False, indent=2) if rows else "  （无数据）")
        return 0

    count = batch_build(args.tenant_id, args.term, raw_rows=rows)
    print(f"batch_build 写入 student_feature：{count} 行")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
