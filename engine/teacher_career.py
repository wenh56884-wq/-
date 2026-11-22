# engine/teacher_career.py
# 职责：把「每位学生的全域结构化事实」聚合成班级生涯报告——纯函数，不连库、不调模型。
# 依赖：仅标准库；数值（人数、比例、均分、名次、定级）全部在本模块确定性计算。
# 铁律 1：大模型只负责表达，本模块是唯一的班级级数值真相源；工具层只做取数与编排。

from __future__ import annotations

from typing import Any, Mapping, Sequence

from engine import profile
from engine.career_guide import INTENTS, normalize_intent
from engine.rules import LEVEL_ORANGE, LEVEL_RED, LEVEL_YELLOW

TEACHER_CAREER_ENGINE_VERSION = "teacher-career-v1"

# 视为「在预警」的等级：红/橙/黄为主动预警；none=正常、unknown=数据不足，都不算预警
_WARN_LEVELS = frozenset({LEVEL_RED, LEVEL_ORANGE, LEVEL_YELLOW})

# 班级摘要里展示的成绩前列人数 / 岗位匹配前列人数
_TOP_GRADE_N = 5
_TOP_JOB_N = 5


def _f(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mean(values: Sequence[float]) -> float | None:
    nums = [float(v) for v in values if v is not None]
    return round(sum(nums) / len(nums), 2) if nums else None


def _rank_desc(items: list[dict[str, Any]], *, rank_field: str = "rank",
               key: str = "gpa") -> None:
    """按 key 降序就地写名次；同分同名次（并列后跳号），无成绩者名次为空。

    与 engine.grades._rank 同口径：并列第 2 名之后是第 4 名，名次总数与「第几名」语义一致。
    """
    for item in items:
        item[rank_field] = None
    scored = [(idx, float(item[key])) for idx, item in enumerate(items)
              if item.get(key) is not None]
    scored.sort(key=lambda pair: (-pair[1], pair[0]))
    prev_value: float | None = None
    prev_rank = 0
    for position, (idx, value) in enumerate(scored, start=1):
        rank = prev_rank if (prev_value is not None
                             and abs(value - prev_value) < 1e-9) else position
        items[idx][rank_field] = rank
        prev_value, prev_rank = value, rank


def _is_warned(warning: Mapping[str, Any] | None) -> bool:
    """该生是否处于主动预警（红/橙/黄）。数据不足(unknown)/正常(none)不算。"""
    return str((warning or {}).get("level") or "") in _WARN_LEVELS


def _intent_distribution(students: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """四个方向的选向人数 + 未选人数；始终全班口径。"""
    dist: dict[str, int] = {name: 0 for name in INTENTS}
    unselected = 0
    for s in students:
        intent = normalize_intent(s.get("intent"))
        if intent is None:
            unselected += 1
        else:
            dist[intent] += 1
    if unselected:
        dist["未选"] = unselected
    return dist


def _grade_rank_top(students: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """班级成绩前列：按个人加权均分降序，同分并列，取前 N。无成绩者不参与。"""
    picked = []
    for s in students:
        gpa = _f(s.get("gpa"))
        if gpa is None:
            continue
        picked.append({
            "student_no": str(s.get("student_no") or ""),
            "name": str(s.get("name") or ""),
            "gpa": round(gpa, 2),
        })
    _rank_desc(picked, rank_field="rank", key="gpa")
    picked.sort(key=lambda x: (int(x["rank"] or 10**9), x["student_no"]))
    return picked[:_TOP_GRADE_N]


def _job_match_top(students: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """班级岗位匹配前列：聚合全班推荐项，按 final_score 降序去重取前 N。

    同一岗位被多名学生推荐时保留最高分那条，并记录被推荐人数——这是「全班都关注」的信号。
    """
    best: dict[int, dict[str, Any]] = {}
    counts: dict[int, int] = {}
    for s in students:
        rec = s.get("recommendations") or {}
        for item in (rec.get("items") or []):
            try:
                job_id = int(item.get("job_id"))
            except (TypeError, ValueError):
                continue
            score = _f(item.get("final_score"))
            if score is None:
                continue
            counts[job_id] = counts.get(job_id, 0) + 1
            cur = best.get(job_id)
            if cur is None or score > cur["final_score"]:
                best[job_id] = {
                    "job_id": job_id,
                    "title": str(item.get("title") or ""),
                    "company": str(item.get("company") or ""),
                    "city": str(item.get("city") or ""),
                    "final_score": round(score, 2),
                    "recommended_by": counts[job_id],
                }
            else:
                cur["recommended_by"] = counts[job_id]
    items = sorted(best.values(), key=lambda x: (-x["final_score"], x["job_id"]))
    return items[:_TOP_JOB_N]


def _risk_level(students: Sequence[Mapping[str, Any]]) -> str:
    """班级风险定级：预警率为主、预测数据缺口为辅，纯数值推导。

    - 预警率 = 处于红/橙/黄的学生占比；
    - 预测缺口率 = 学业预测不可用（历史学期不足）的学生占比；
    数据不足不等于正常，故缺口率也计入风险。定级阈值固定，不含随机/模型。
    """
    total = len(students)
    if total == 0:
        return "unknown"
    warn_rate = sum(1 for s in students if _is_warned(s.get("warning"))) / total
    gap_rate = sum(
        1 for s in students if not (s.get("forecast") or {}).get("available", False)
    ) / total
    if warn_rate >= 0.4 or gap_rate >= 0.6:
        return "高"
    if warn_rate >= 0.2 or gap_rate >= 0.3:
        return "中"
    return "低"


def build_class_career_report(
    *,
    tenant_id: int,
    class_name: str,
    term: str,
    intent: Any = None,
    students: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """把每位学生的全域结构化事实聚合成班级生涯报告。

    students：工具层编排好的每位学生全域事实字典（成绩/预警/预测/岗位/面试/竞赛/
              测评/选课/招考/图谱等子结果已填好，引擎只做聚合、排序、门次、比例）。
    intent：只过滤 students 列表（指定方向时只保留该方向学生）；class_summary 始终全班。

    返回的数值全部由本函数确定性计算；子结果原样透传，不重新计算、不改写。
    """
    rows = [dict(s) for s in students]
    selected_intent = normalize_intent(intent)

    class_summary = {
        "student_total": len(rows),
        "warning_count": sum(1 for s in rows if _is_warned(s.get("warning"))),
        "warning_rate": (
            round(sum(1 for s in rows if _is_warned(s.get("warning"))) / len(rows), 4)
            if rows else 0.0
        ),
        "avg_grade": _mean([_f(s.get("gpa")) for s in rows]),
        "grade_rank_top": _grade_rank_top(rows),
        "intent_distribution": _intent_distribution(rows),
        "job_match_top": _job_match_top(rows),
        "risk_level": _risk_level(rows),
    }

    filtered = [
        s for s in rows if selected_intent is None
        or normalize_intent(s.get("intent")) == selected_intent
    ]

    return {
        "engine_version": TEACHER_CAREER_ENGINE_VERSION,
        "calc_version": profile.CALC_VERSION,
        "tenant_id": int(tenant_id),
        "class_name": str(class_name),
        "term": str(term),
        "intent": selected_intent,
        "class_summary": class_summary,
        "students": filtered,
        "student_total": len(rows),
        "filtered_total": len(filtered),
        "note": "班级摘要基于传入学生集合计算（工具层按上限截断时为样本口径，不冒充全班）；"
                "学生列表按所选方向过滤。所有数值由确定性引擎计算。",
    }
