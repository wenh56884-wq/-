# engine/campus_insight.py
# 职责：校园行为（图书馆/消费/活动/出勤/岗位浏览）的个人画像与班级聚合——纯函数确定性计算。
# 铁律 1：不连库、不调模型、无副作用；合计/均值/比例/定级全部在本模块算出，缺失按 0/None 兜底。
# 口径：消费规律性 min(1, active_days/120) 与 scripts/build_profile_raw.py 一致；排序全部带确定性 tie-break。

from __future__ import annotations

from collections import defaultdict
from typing import Any

from engine import profile

CAMPUS_INSIGHT_ENGINE_VERSION = "campus-insight-v1"
CONSUME_DAY_CAP = 120.0

_ACTIVITY_TYPES = ("cert", "contest", "project")
_TOP_N = 8
_SNAPSHOT_N = 8
_RECENT_N = 10
_VISIT_SATURATION = 30.0


def _i(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _f(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _term_key(term: Any) -> tuple[int, int]:
    """把 2022-2023-1 转成 (2022, 1)，保证按学年/学期稳定排序（与 engine.grades 同口径）。"""
    parts = str(term or "").split("-")
    try:
        return int(parts[0]), int(parts[-1])
    except (ValueError, IndexError):
        return 0, 0


def _rows(value: list[dict] | None) -> list[dict[str, Any]]:
    return [dict(r) for r in (value or [])]


def _sort_terms(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda r: _term_key(r.get("term")))


def _merge_top(rows: list[dict] | None, key: str) -> list[dict[str, Any]]:
    """按名称合并 cnt 后降序取前 N；同 cnt 按名称升序，保证确定性。"""
    totals: dict[str, int] = defaultdict(int)
    for row in rows or []:
        totals[str(row.get(key) or "")] += _i(row.get("cnt"))
    items = [{key: name, "cnt": cnt} for name, cnt in totals.items()]
    items.sort(key=lambda x: (-x["cnt"], x[key]))
    return items[:_TOP_N]


def _library_block(rows: list[dict] | None) -> dict[str, Any]:
    terms = _sort_terms(_rows(rows))
    latest = terms[-1] if terms else None
    trend = "flat"
    if len(terms) >= 2:
        prev, cur = _i(terms[-2].get("visits")), _i(terms[-1].get("visits"))
        trend = "up" if cur > prev else "down" if cur < prev else "flat"
    return {
        "terms": terms,
        "total_visits": sum(_i(r.get("visits")) for r in terms),
        "total_borrows": sum(_i(r.get("borrows")) for r in terms),
        "latest": latest,
        "trend": trend,
    }


def _consumption_block(rows: list[dict] | None) -> dict[str, Any]:
    terms = _sort_terms(_rows(rows))
    latest = terms[-1] if terms else None
    days = _i(latest.get("active_days")) if latest else 0
    return {
        "terms": terms,
        "latest": latest,
        "regularity": round(min(1.0, days / CONSUME_DAY_CAP), 4),
    }


def _activities_block(counts: list[dict] | None,
                      recent: list[dict] | None) -> dict[str, Any]:
    by_type: dict[str, int] = {t: 0 for t in _ACTIVITY_TYPES}
    per_term: dict[str, dict[str, int]] = defaultdict(
        lambda: {t: 0 for t in _ACTIVITY_TYPES})
    for row in counts or []:
        kind = str(row.get("type") or "")
        if kind not in by_type:
            continue
        cnt = _i(row.get("cnt"))
        by_type[kind] += cnt
        per_term[str(row.get("term") or "")][kind] += cnt
    by_term = [{"term": term, **vals} for term, vals
               in sorted(per_term.items(), key=lambda kv: _term_key(kv[0]))]
    return {
        "by_type": by_type,
        "by_term": by_term,
        "recent": _rows(recent)[:_RECENT_N],
        "total": sum(by_type.values()),
    }


def _attendance_block(rows: list[dict] | None) -> dict[str, Any]:
    terms = _sort_terms(_rows(rows))
    rates = [_f(r.get("rate")) for r in terms]
    valid = [x for x in rates if x is not None]
    return {
        "terms": terms,
        "latest_rate": round(rates[-1], 4) if rates and rates[-1] is not None else None,
        "avg_rate": round(sum(valid) / len(valid), 4) if valid else None,
    }


def _job_interest_block(view_counts: list[dict] | None,
                        cities: list[dict] | None,
                        industries: list[dict] | None) -> dict[str, Any]:
    views = favorites = 0
    per_term: dict[str, dict[str, int]] = defaultdict(
        lambda: {"views": 0, "favorites": 0})
    for row in view_counts or []:
        action = str(row.get("action") or "")
        cnt = _i(row.get("cnt"))
        bucket = per_term[str(row.get("term") or "")]
        if action == "view":
            views += cnt
            bucket["views"] += cnt
        elif action == "favorite":
            favorites += cnt
            bucket["favorites"] += cnt
    by_term = [{"term": term, **vals} for term, vals
               in sorted(per_term.items(), key=lambda kv: _term_key(kv[0]))]
    return {
        "views_total": views,
        "favorites_total": favorites,
        "by_term": by_term,
        "top_cities": _merge_top(cities, "city"),
        "top_industries": _merge_top(industries, "industry"),
    }


def _snapshot_rows(rows: list[dict] | None) -> list[dict[str, Any]]:
    picked = _rows(rows)
    picked.sort(key=lambda r: (_i(r.get("year")), _i(r.get("week"))))
    return picked[:_SNAPSHOT_N]


def _study_style(latest_visits: int, latest_rate: float | None,
                 regularity: float) -> dict[str, Any]:
    score = round(0.4 * min(1.0, latest_visits / _VISIT_SATURATION)
                  + 0.3 * (latest_rate or 0.0) + 0.3 * regularity, 4)
    if score >= 0.7:
        label = "高投入型"
    elif score >= 0.4:
        label = "稳健型"
    elif score > 0:
        label = "待激活"
    else:
        label = "暂无数据"
    return {"label": label, "score": score}


def build_student_insight(
    *,
    student_no: str,
    name: str,
    class_name: str,
    term: str,
    library: list[dict] | None,
    consumption: list[dict] | None,
    activity_counts: list[dict] | None,
    activity_recent: list[dict] | None,
    attendance: list[dict] | None,
    job_view_counts: list[dict] | None,
    job_top_cities: list[dict] | None,
    job_top_industries: list[dict] | None,
    extra: dict | None,
    snapshots: list[dict] | None,
) -> dict[str, Any]:
    """把 SQL 取好的校园行为行聚合成个人画像（纯函数：不连库、不调模型）。

    所有入参均可为空列表/None，数值键缺失或为 None 一律按 0/空兜底；
    原样行只做排序与截断，不改写内容；派生数值全部在本函数确定性计算。
    """
    lib = _library_block(library)
    cons = _consumption_block(consumption)
    acts = _activities_block(activity_counts, activity_recent)
    att = _attendance_block(attendance)
    jobs = _job_interest_block(job_view_counts, job_top_cities, job_top_industries)
    snaps = _snapshot_rows(snapshots)

    latest_visits = _i(lib["latest"].get("visits")) if lib["latest"] else 0
    style = _study_style(latest_visits, att["latest_rate"], cons["regularity"])

    has_data = bool(extra) or any([
        library, consumption, activity_counts, activity_recent, attendance,
        job_view_counts, job_top_cities, job_top_industries, snapshots,
    ])
    return {
        "engine_version": CAMPUS_INSIGHT_ENGINE_VERSION,
        "calc_version": profile.CALC_VERSION,
        "student_no": str(student_no),
        "name": str(name),
        "class_name": str(class_name),
        "term": str(term),
        "library": lib,
        "consumption": cons,
        "activities": acts,
        "attendance": att,
        "job_interest": jobs,
        "extra": dict(extra) if extra is not None else None,
        "snapshots": snaps,
        "study_style": style,
        "note": "" if has_data else "暂无校园行为数据",
    }


def build_class_insight(
    *,
    tenant_id: int,
    class_name: str,
    term: str,
    students: list[dict] | None,
) -> dict[str, Any]:
    """把 build_student_insight 的输出列表聚合成班级画像（纯函数，学生等权）。

    均值分母为全班人数（无 latest 的生按 0 计入）；出勤均值只统计非 None；
    low_engagement 逐生按固定顺序命中规则，输出按 student_no 升序。
    """
    rows = sorted(_rows(students), key=lambda s: str(s.get("student_no") or ""))
    total = len(rows)

    visits_sum = borrows_sum = 0
    rates: list[float] = []
    reg_sum = 0.0
    activity_counts: dict[str, int] = {t: 0 for t in _ACTIVITY_TYPES}
    active_students = 0
    views = favorites = 0
    city_rows: list[dict[str, Any]] = []
    industry_rows: list[dict[str, Any]] = []
    distribution: dict[str, int] = {}
    low_engagement: list[dict[str, Any]] = []

    for s in rows:
        lib = s.get("library") or {}
        latest = lib.get("latest")
        visits = _i(latest.get("visits")) if latest else 0
        borrows = _i(latest.get("borrows")) if latest else 0
        visits_sum += visits
        borrows_sum += borrows

        rate = _f((s.get("attendance") or {}).get("latest_rate"))
        if rate is not None:
            rates.append(rate)
        regularity = _f((s.get("consumption") or {}).get("regularity")) or 0.0
        reg_sum += regularity

        acts = s.get("activities") or {}
        by_type = acts.get("by_type") or {}
        for kind in _ACTIVITY_TYPES:
            activity_counts[kind] += _i(by_type.get(kind))
        act_total = _i(acts.get("total"))
        if act_total > 0:
            active_students += 1

        jobs = s.get("job_interest") or {}
        views += _i(jobs.get("views_total"))
        favorites += _i(jobs.get("favorites_total"))
        city_rows.extend(jobs.get("top_cities") or [])
        industry_rows.extend(jobs.get("top_industries") or [])

        label = str((s.get("study_style") or {}).get("label") or "")
        if label:
            distribution[label] = distribution.get(label, 0) + 1

        reasons: list[str] = []
        if rate is not None and rate < 0.8:
            reasons.append("出勤率低于80%")
        if latest is not None and visits == 0:
            reasons.append("本学期未到馆")
        if regularity < 0.3:
            reasons.append("消费规律性偏低")
        if act_total == 0:
            reasons.append("无证书/竞赛/项目")
        if reasons:
            low_engagement.append({
                "student_no": str(s.get("student_no") or ""),
                "name": str(s.get("name") or ""),
                "reasons": reasons,
            })

    class_summary = {
        "student_total": total,
        "avg_library_visits": round(visits_sum / total, 2) if total else 0.0,
        "avg_borrows": round(borrows_sum / total, 2) if total else 0.0,
        "avg_attendance_rate": round(sum(rates) / len(rates), 4) if rates else 0.0,
        "avg_regularity": round(reg_sum / total, 4) if total else 0.0,
        "activity_counts": activity_counts,
        "activity_coverage_rate": round(active_students / total, 4) if total else 0.0,
        "job_views_total": views,
        "job_favorites_total": favorites,
        "top_cities": _merge_top(city_rows, "city"),
        "top_industries": _merge_top(industry_rows, "industry"),
        "study_style_distribution": distribution,
        "low_engagement": low_engagement,
    }
    return {
        "engine_version": CAMPUS_INSIGHT_ENGINE_VERSION,
        "calc_version": profile.CALC_VERSION,
        "tenant_id": int(tenant_id),
        "class_name": str(class_name),
        "term": str(term),
        "class_summary": class_summary,
        "students": rows,
        "student_total": total,
        "note": "" if rows else "暂无学生行为数据",
    }