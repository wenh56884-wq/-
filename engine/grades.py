# engine/grades.py
# 职责：学生成绩单的确定性聚合——学年/学期/课程分组、多次记录、最高分与学分加权均分。
# 铁律：所有数值由本模块计算；只做展示聚合，不改动原始成绩；缺失返回 None 不冒充。
# 口径：同一课程同一学期可能有多条记录（多次考核/重修），逐条保留；课程汇总取最高分。

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping

GRADES_ENGINE_VERSION = "grades-v1"
PASS_SCORE = 60.0


def _f(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mean(values: Iterable[float]) -> float | None:
    nums = [float(v) for v in values if v is not None]
    return round(sum(nums) / len(nums), 2) if nums else None


def _term_key(term: str) -> tuple[int, int]:
    """把 2022-2023-1 转成 (2022, 1)，保证按学年/学期稳定排序。"""
    parts = str(term or "").split("-")
    try:
        return int(parts[0]), int(parts[-1])
    except (ValueError, IndexError):
        return 0, 0


def _year_of(term: str) -> str:
    parts = str(term or "").split("-")
    return "-".join(parts[:2]) if len(parts) >= 2 else str(term or "")


def _record_id(row: Mapping[str, Any]) -> tuple[int, str]:
    value = row.get("record_id")
    try:
        return int(value), ""
    except (TypeError, ValueError):
        return 10**12, str(value or "")


def _weighted(courses: list[Mapping[str, Any]]) -> float | None:
    pairs = [(float(c["score"]), float(c["credit"])) for c in courses
             if c.get("score") is not None and c.get("credit")]
    total = sum(w for _, w in pairs)
    return round(sum(s * w for s, w in pairs) / total, 2) if total > 0 else None


def _term_summary(term: str, records: list[Mapping[str, Any]]) -> dict[str, Any]:
    by_course: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in records:
        by_course[str(row.get("course_code") or "")].append(row)

    courses: list[dict[str, Any]] = []
    all_records: list[dict[str, Any]] = []
    for code, group in sorted(by_course.items()):
        group = sorted(group, key=_record_id)
        scores = [float(r["score"]) for r in group if _f(r.get("score")) is not None]
        best = max(scores) if scores else None
        latest = float(group[-1]["score"]) if group and _f(group[-1].get("score")) is not None else None
        credit = _f(group[0].get("credit")) if group else None
        courses.append({
            "course_code": code,
            "course_name": str(group[0].get("course_name") or "") if group else "",
            "credit": round(credit, 2) if credit is not None else None,
            "score": round(best, 2) if best is not None else None,
            "latest_score": round(latest, 2) if latest is not None else None,
            "attempts": len(group),
            "retake_any": any(bool(r.get("retake")) for r in group),
            "passed": bool(best is not None and best >= PASS_SCORE),
        })
        for idx, row in enumerate(group, start=1):
            all_records.append({
                "record_id": row.get("record_id"),
                "course_code": code,
                "course_name": str(row.get("course_name") or ""),
                "credit": _f(row.get("credit")),
                "score": round(float(row["score"]), 2) if _f(row.get("score")) is not None else None,
                "retake": bool(row.get("retake")),
                "attempt": idx,
            })

    credits = sum(float(c["credit"]) for c in courses if c.get("credit") is not None)
    failed = sum(1 for c in courses if c.get("score") is not None and not c["passed"])
    return {
        "term": str(term),
        "term_label": f"{_year_of(term)} 学年 · 第 {str(term).split('-')[-1]} 学期",
        "avg_score": _mean(c["score"] for c in courses),
        "weighted_avg": _weighted(courses),
        "credits": round(credits, 2),
        "course_count": len(courses),
        "failed_count": failed,
        "record_count": len(all_records),
        "courses": courses,
        "records": all_records,
    }


def _year_summary(year: str, terms: list[dict[str, Any]]) -> dict[str, Any]:
    """学年汇总：课程/学分按学年内去重，均分按各学期课程最高分计算。"""
    all_courses = [c for t in terms for c in t["courses"]]
    unique: dict[str, dict[str, Any]] = {}
    for c in all_courses:
        code = c["course_code"]
        if code not in unique or (c.get("credit") or 0) > (unique[code].get("credit") or 0):
            unique[code] = c
    failed_codes = {c["course_code"] for c in all_courses
                    if c.get("score") is not None and not c["passed"]}
    credits = sum(float(c["credit"]) for c in unique.values() if c.get("credit") is not None)
    return {
        "year": year,
        "avg_score": _mean(c["score"] for c in all_courses),
        "weighted_avg": _weighted(all_courses),
        "credits": round(credits, 2),
        "course_count": len(unique),
        "failed_count": len(failed_codes),
        "record_count": sum(t["record_count"] for t in terms),
        "terms": terms,
    }


def build_report(rows: Iterable[Mapping[str, Any]],
                 student: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """把成绩行聚合成「学年 → 学期 → 课程/逐条记录」的成绩单。"""
    by_term: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        by_term[str(row.get("term") or "")].append(dict(row))

    terms = [_term_summary(term, by_term[term])
             for term in sorted(by_term, key=_term_key)]
    by_year: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for term in terms:
        by_year[_year_of(term["term"])].append(term)
    years = [_year_summary(year, by_year[year])
             for year in sorted(by_year, key=lambda y: _term_key(f"{y}-1"))]

    all_courses = [c for t in terms for c in t["courses"]]
    unique = {}
    for c in all_courses:
        if c["course_code"] not in unique:
            unique[c["course_code"]] = c
    failed_codes = {c["course_code"] for c in all_courses
                    if c.get("score") is not None and not c["passed"]}
    summary = {
        "avg_score": _mean(c["score"] for c in all_courses),
        "weighted_avg": _weighted(all_courses),
        "credits": round(sum(float(c["credit"]) for c in unique.values()
                             if c.get("credit") is not None), 2),
        "course_count": len(unique),
        "failed_count": len(failed_codes),
        "record_count": sum(t["record_count"] for t in terms),
        "term_count": len(terms),
        "year_count": len(years),
    }
    return {
        "engine_version": GRADES_ENGINE_VERSION,
        "student": dict(student or {}),
        "summary": summary,
        "years": years,
        "notes": [
            "同一课程同一学期的多次记录逐条展示（第几次按录入顺序）；",
            "课程成绩汇总取该课程最高分，学期/学年加权均分按学分计算；",
            "成绩缺失不在任何汇总里补 0。",
        ],
    }


CLASS_RANK_VERSION = "grades-rank-v1"


def _rank(items: list[dict[str, Any]], *, rank_field: str = "rank",
          total_field: str = "rank_total", key: str = "weighted_avg") -> None:
    """按 key 降序就地写名次；同分同名次（并列后跳号），无成绩者名次为空。

    为什么不直接用 enumerate：并列第 2 名之后应是第 4 名而不是第 3 名，
    否则名次总数和「第几名」的语义对不上。
    """
    for item in items:
        item[rank_field] = None
        item[total_field] = 0
    scored = [(idx, float(item[key])) for idx, item in enumerate(items)
              if item.get(key) is not None]
    scored.sort(key=lambda pair: (-pair[1], pair[0]))
    for item in items:
        item[total_field] = len(scored)
    prev_value: float | None = None
    prev_rank = 0
    for position, (idx, value) in enumerate(scored, start=1):
        rank = prev_rank if (prev_value is not None
                             and abs(value - prev_value) < 1e-9) else position
        items[idx][rank_field] = rank
        prev_value, prev_rank = value, rank


def build_rank(rows: Iterable[Mapping[str, Any]], *, term: str = "",
               scope_classes: Iterable[str] | None = None) -> dict[str, Any]:
    """班级 / 专业成绩排名（纯函数：不连库、不调模型，数值全部在这里算出来）。

    口径与成绩单严格一致：同一门课取最高分 → 按学分加权（见 build_report 的 notes），
    所以这里给出的个人均分与成绩单上显示的加权均分是同一个数。

    班级均分 = 该班每个学生个人加权均分的算术平均（学生等权，不是把全班成绩混在一起算），
    这样不会让选课多的学生主导班级分数。

    scope_classes：可见班级集合，None 表示不按班级收窄（由上层保证权限已校验）。
    """
    picked: list[dict[str, Any]] = []
    for row in rows:
        if term and str(row.get("term") or "") != str(term):
            continue
        picked.append(dict(row))
    if scope_classes is not None:
        allowed = {str(name) for name in scope_classes}
        picked = [r for r in picked if str(r.get("class_name") or "") in allowed]

    by_student: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    meta: dict[str, dict[str, str]] = {}
    for row in picked:
        sid = str(row.get("student_id") or row.get("student_no") or "")
        by_student[sid].append(row)
        meta[sid] = {
            "student_no": str(row.get("student_no") or ""),
            "name": str(row.get("name") or ""),
            "major": str(row.get("major") or ""),
            "class_name": str(row.get("class_name") or ""),
        }

    students: list[dict[str, Any]] = []
    for sid, records in by_student.items():
        term_summary = _term_summary(str(term), records)
        students.append({
            "student_no": meta[sid]["student_no"],
            "name": meta[sid]["name"],
            "major": meta[sid]["major"],
            "class_name": meta[sid]["class_name"],
            "weighted_avg": term_summary["weighted_avg"],
            "avg_score": term_summary["avg_score"],
            "credits": term_summary["credits"],
            "course_count": term_summary["course_count"],
            "failed_count": term_summary["failed_count"],
        })

    by_class: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for student in students:
        by_class[student["class_name"]].append(student)
    for members in by_class.values():                      # 班内排名（不分专业）
        _rank(members, rank_field="class_rank", total_field="class_rank_total")

    by_major: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for student in students:
        by_major[student["major"]].append(student)
    for members in by_major.values():                      # 专业内排名（跨班）
        _rank(members, rank_field="major_rank", total_field="major_rank_total")

    def _mean_of(values: list[float]) -> float | None:
        return round(sum(values) / len(values), 2) if values else None

    classes: list[dict[str, Any]] = []
    for name, members in sorted(by_class.items()):
        weighted = [m["weighted_avg"] for m in members if m["weighted_avg"] is not None]
        plain = [m["avg_score"] for m in members if m["avg_score"] is not None]
        classes.append({
            "class_name": name,
            "student_cnt": len(members),
            "graded_cnt": len(weighted),
            "weighted_avg": _mean_of(weighted),
            "avg_score": _mean_of(plain),
            "max_weighted_avg": round(max(weighted), 2) if weighted else None,
            "min_weighted_avg": round(min(weighted), 2) if weighted else None,
        })

    # 同专业内各班排名：一个班里可能有多个专业，所以按 (专业, 班级) 聚合
    cells: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for student in students:
        cells[(student["major"], student["class_name"])].append(student)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (major, name), members in cells.items():
        weighted = [m["weighted_avg"] for m in members if m["weighted_avg"] is not None]
        grouped[major].append({
            "major": major,
            "class_name": name,
            "student_cnt": len(members),
            "graded_cnt": len(weighted),
            "weighted_avg": _mean_of(weighted),
        })
    class_rank_in_major: list[dict[str, Any]] = []
    for major, items in grouped.items():
        _rank(items, rank_field="rank", total_field="rank_total")
        class_rank_in_major.extend(items)
    class_rank_in_major.sort(
        key=lambda item: (str(item["major"]), int(item["rank"] or 10**9),
                          str(item["class_name"])))

    students.sort(key=lambda s: (str(s["class_name"]), int(s["class_rank"] or 10**9),
                                 str(s["student_no"])))
    return {
        "engine_version": CLASS_RANK_VERSION,
        "term": str(term),
        "classes": classes,
        "class_rank_in_major": class_rank_in_major,
        "students": students,
        "notes": [
            "个人加权均分口径与成绩单一致：同一门课取最高分后按学分加权；",
            "班级均分 = 该班各学生个人加权均分的算术平均（学生等权）；",
            "同专业班级排名按 (专业, 班级) 聚合，一个班里有多个专业时会分别计名次；",
            "名次并列后跳号（并列第 2 名之后是第 4 名），无成绩者不参与排名。",
        ],
    }
