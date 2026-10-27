# scripts/build_profile_raw.py
# 职责：查齐「学业+出勤」与 7 类新源数据 → 组装完整 raw rows → 交给 engine.profile.batch_build
# 依赖：pymysql / app.config / engine.profile（只调用，不修改引擎）
# 说明：全部 SQL 带 WHERE s.tenant_id = %s；脚本不预归一，library_activity 由 build_features 从次数归一
# 口径：gpa_trend = 本期 − 上期（正数=进步）；major/class_rank_pct 分别按专业/班级分组（0=第一）；
#      缺失即不写键；兴趣方向词典统一读 rules\direction_keywords.json（与 seed_elective.py 共用一份）

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
# 兴趣方向词典：统一读 rules\direction_keywords.json，与 scripts\seed_elective.py 共用一份
# 匹配顺序敏感：数组越靠前优先级越高，先匹配者胜；匹配不上归 fallback
# ----------------------------------------------------------------
_DICT_PATH = _ROOT / "rules" / "direction_keywords.json"


def _load_direction_dict() -> tuple[str, tuple[tuple[str, tuple[str, ...]], ...]]:
    r"""从 rules\direction_keywords.json 加载 (fallback, 顺序敏感的方向词典)。"""
    data = json.loads(_DICT_PATH.read_text(encoding="utf-8"))
    directions = tuple((str(d["name"]), tuple(str(k) for k in d["keywords"]))
                       for d in data["directions"])
    return str(data.get("fallback", "其他")), directions


DIRECTION_OTHER, DIRECTIONS = _load_direction_dict()


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
    major_rank_pct（专业分组，0=第一）/ class_rank_pct（班级分组） /
    attendance_rate（无考勤记 None）。
    """
    cur_sql = (
        "SELECT s.`学号` AS student_no, s.`姓名` AS name, s.`专业` AS major, "
        "       s.`班级` AS class_name, "
        "       AVG(sc.`分数`) AS gpa, "
        "       SUM(CASE WHEN sc.`分数` < 60 THEN 1 ELSE 0 END) AS fail_count "
        "FROM `学生` s "
        "JOIN `成绩` sc ON sc.`学生编号` = s.`编号` AND sc.`学期` = %s "
        "WHERE s.`租户编号` = %s "
        "GROUP BY s.`学号`, s.`姓名`, s.`专业`, s.`班级`"
    )
    cur_rows = _query(cur_sql, (term, tenant_id))

    prev_sql = (
        "SELECT sc.`学期` AS term "
        "FROM `成绩` sc "
        "JOIN `学生` s ON s.`编号` = sc.`学生编号` "
        "WHERE s.`租户编号` = %s AND sc.`学期` < %s "
        "GROUP BY sc.`学期` ORDER BY sc.`学期` DESC LIMIT 1"
    )
    prev_rows = _query(prev_sql, (tenant_id, term))
    prev_gpa: dict[str, float] = {}
    if prev_rows:
        prev_term = str(prev_rows[0]["term"])
        prev_sql = (
            "SELECT s.`学号` AS student_no, AVG(sc.`分数`) AS gpa "
            "FROM `学生` s "
            "JOIN `成绩` sc ON sc.`学生编号` = s.`编号` AND sc.`学期` = %s "
            "WHERE s.`租户编号` = %s "
            "GROUP BY s.`学号`"
        )
        prev_gpa = {str(r["student_no"]): float(r["gpa"])
                    for r in _query(prev_sql, (prev_term, tenant_id))}

    gpa_of = {str(r["student_no"]): float(r["gpa"]) for r in cur_rows}
    major_rank_pct = compute_rank_pct(
        gpa_of, {str(r["student_no"]): str(r["major"]) for r in cur_rows})
    class_rank_pct = compute_rank_pct(
        gpa_of, {str(r["student_no"]): str(r["class_name"]) for r in cur_rows})

    att_sql = (
        "SELECT s.`学号` AS student_no, "
        "       SUM(a.`应到次数`) AS total_sessions, "
        "       SUM(a.`缺勤次数`) AS absent_sessions "
        "FROM `学生` s "
        "JOIN `考勤` a ON a.`学生编号` = s.`编号` AND a.`学期` = %s "
        "WHERE s.`租户编号` = %s "
        "GROUP BY s.`学号`"
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
            "major_rank_pct": major_rank_pct.get(sno),
            "class_rank_pct": class_rank_pct.get(sno),
            # 口径字典：无考勤记 None，不得按 1.0 处理
            "attendance_rate": attendance.get(sno),
        })
    return rows


def load_course_pref(tenant_id: int, term: str) -> dict[str, dict[str, int]]:
    """选修方向偏好：elective_selection → {student_no: {方向: 门次}}。

    方向已在表内 direction 列标注，此处只做聚合计数。
    """
    sql = (
        "SELECT s.`学号` AS student_no, es.`方向` AS direction, "
        "       COUNT(*) AS cnt "
        "FROM `选课记录` es "
        "JOIN `学生` s ON s.`编号` = es.`学生编号` "
        "WHERE es.`租户编号` = %s AND es.`学期` = %s "
        "GROUP BY s.`学号`, es.`方向`"
    )
    pref: dict[str, dict[str, int]] = {}
    for r in _query(sql, (tenant_id, term)):
        sno = str(r["student_no"])
        pref.setdefault(sno, {})[str(r["direction"])] = int(r["cnt"])
    return pref


def load_library(tenant_id: int, term: str) -> dict[str, int]:
    """library_visit_cnt：原始到馆次数（不预归一，交给 build_features）。"""
    sql = (
        "SELECT s.`学号` AS student_no, SUM(lr.`到馆次数`) AS visit_cnt "
        "FROM `图书馆记录` lr "
        "JOIN `学生` s ON s.`编号` = lr.`学生编号` "
        "WHERE s.`租户编号` = %s AND lr.`学期` = %s "
        "GROUP BY s.`学号`"
    )
    return {str(r["student_no"]): int(r["visit_cnt"] or 0)
            for r in _query(sql, (tenant_id, term))}


def load_consumption(tenant_id: int, term: str) -> dict[str, float]:
    """consumption_regularity = min(1, active_days / 120)。"""
    sql = (
        "SELECT s.`学号` AS student_no, SUM(cr.`活跃天数`) AS active_days "
        "FROM `消费记录` cr "
        "JOIN `学生` s ON s.`编号` = cr.`学生编号` "
        "WHERE s.`租户编号` = %s AND cr.`学期` = %s "
        "GROUP BY s.`学号`"
    )
    return {
        str(r["student_no"]): min(1.0, round(float(r["active_days"] or 0) / CONSUME_DAY_CAP, 4))
        for r in _query(sql, (tenant_id, term))
    }


def load_activity_counts(tenant_id: int, term: str) -> dict[str, dict[str, int]]:
    """证书/竞赛/项目计数：按 student_no + activity_type 聚合，无记录的类型不出现。"""
    sql = (
        "SELECT s.`学号` AS student_no, sa.`活动类型` AS activity_type, "
        "       COUNT(*) AS cnt "
        "FROM `学生活动` sa "
        "JOIN `学生` s ON s.`编号` = sa.`学生编号` "
        "WHERE s.`租户编号` = %s AND sa.`学期` = %s "
        "GROUP BY s.`学号`, sa.`活动类型`"
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
        "SELECT s.`学号` AS student_no, jvl.`动作` AS action, COUNT(*) AS cnt "
        "FROM `岗位浏览日志` jvl "
        "JOIN `学生` s ON s.`编号` = jvl.`学生编号` "
        "WHERE s.`租户编号` = %s AND jvl.`学期` = %s "
        "GROUP BY s.`学号`, jvl.`动作`"
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
    """job_view_pref：view 流水 JOIN `岗位` 表，按标题匹配方向词典聚合成 {方向: 次数}。"""
    sql = (
        "SELECT s.`学号` AS student_no, j.`岗位名称` AS title "
        "FROM `岗位浏览日志` jvl "
        "JOIN `岗位` j ON j.`编号` = jvl.`岗位编号` "
        "JOIN `学生` s ON s.`编号` = jvl.`学生编号` "
        "WHERE s.`租户编号` = %s AND jvl.`学期` = %s AND jvl.`动作` = 'view'"
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
    course_prefs = load_course_pref(tenant_id, term)

    for row in rows:
        sno = row["student_no"]
        # 缺失语义：有选修记录才写 course_pref，没有就不写（禁止补 {}）
        if sno in course_prefs:
            row["course_pref"] = dict(sorted(course_prefs[sno].items(),
                                             key=lambda kv: (-kv[1], kv[0])))
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
    if rows:
        hit = sum(1 for r in rows if r.get("course_pref"))
        print(f"  {'course_pref（选修方向）':<24} {hit / len(rows) * 100:6.2f}%"
              f"   有选修的人数 {hit}/{len(rows)}")
    if rows and not any(r.get("course_pref") for r in rows):
        print("  选修方向行校验失败：course_pref 全为空！")
        print("  请按顺序执行：mysql -u root -p qihang < db\\elective_tables.sql")
        print("               python scripts\\seed_elective.py --term \"2025-2026-1,2025-2026-2\"")
    if args.dry_run:
        print("[dry-run] 未写库，样例首行：")
        print(json.dumps(rows[0], ensure_ascii=False, indent=2) if rows else "  （无数据）")
        return 0

    count = batch_build(args.tenant_id, args.term, raw_rows=rows)
    print(f"batch_build 写入 student_feature：{count} 行")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
