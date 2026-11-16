# engine/elective.py
# 职责：技能缺口选课推荐——目标岗位技能要求 vs 已修/已选课程覆盖，确定性算缺口并给候选课打分。
# 依赖：engine.recommend（词面命中/方向词典/岗位取数）/ engine.hybrid（目标岗位同口径）/ engine.kg（技能展示）。
# 说明：不调大模型、不用随机数；数值唯一真相源，智能体（agents.elective）只引用本模块结果。

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from engine import recommend
from engine.kg import skills_for_course

ELECTIVE_ENGINE_VERSION = "elective-v2"
# 选课打分权重：补口占比 0.7 + 方向契合 0.3（仅作用于选课排序，不回写岗位推荐）
ELECTIVE_WEIGHTS: dict[str, float] = {"gap_fill": 0.7, "direction": 0.3}
# 方向聚合降级时最多取几个高频技能标签
AGGREGATE_TOP_K = 8
DEFAULT_TOP_N = 8
_SCORE_NDIGITS = 4

_RULES_PATH = Path(__file__).resolve().parents[1] / "rules" / "direction_keywords.json"
_pool_cache: dict[str, list[dict[str, Any]]] | None = None
_POLICY_PATH = Path(__file__).resolve().parents[1] / "rules" / "elective_policy.json"
_policy_cache: dict[str, Any] | None = None


# ----------------------------------------------------------------
# 纯计算部分（可被单测直接调用，不碰 IO）
# ----------------------------------------------------------------
def fills_of(course_name: str, gaps: Sequence[str]) -> list[str]:
    """该课能补的缺口项：与 recommend 同一套词面命中口径，保证缺口可翻转。"""
    return [g for g in gaps if recommend._hit(g, course_name)]


def score_elective(fill_cnt: int, gap_cnt: int, dir_score: float) -> float:
    """选课得分 = 0.7 * 补口占比 + 0.3 * 方向契合；无缺口时记 0。"""
    if gap_cnt <= 0 or fill_cnt <= 0:
        return 0.0
    ratio = min(1.0, fill_cnt / gap_cnt)
    return round(ELECTIVE_WEIGHTS["gap_fill"] * ratio
                 + ELECTIVE_WEIGHTS["direction"] * float(dir_score), _SCORE_NDIGITS)


def aggregate_required_tags(jobs: Sequence[Mapping[str, Any]],
                            top_k: int = AGGREGATE_TOP_K) -> list[str]:
    """无头部岗位时：聚合候选岗位技能标签频次，按 (-频次, 标签字典序) 取前 top_k。"""
    counter: Counter[str] = Counter()
    for job in jobs:
        for tag in recommend.clean_skill_tags(job.get("skill_tags")):
            counter[tag] += 1
    ordered = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    return [tag for tag, _cnt in ordered[: max(0, int(top_k))]]


def rank_electives(pool: Mapping[str, Sequence[Mapping[str, Any]]],
                   gaps: Sequence[str],
                   target_directions: Sequence[str],
                   taken: Sequence[str],
                   top_n: int = DEFAULT_TOP_N) -> list[dict[str, Any]]:
    """课池逐课打分排序：排除已修/已选，补不了缺口的不推荐，同输入必得同输出。"""
    taken_norm = {recommend._norm(t) for t in taken if str(t).strip()}
    scored: list[dict[str, Any]] = []
    for direction, courses in pool.items():
        for course in courses:
            name = str(course.get("name") or "").strip()
            if not name or recommend._norm(name) in taken_norm:
                continue
            fills = fills_of(name, gaps)
            if not fills:
                continue
            dir_score, dir_reason = recommend.interest_fit_of(
                target_directions, str(direction))
            credit = float(course.get("credit") or 0.0)
            score = score_elective(len(fills), len(gaps), dir_score)
            scored.append({
                "name": name,
                "direction": str(direction),
                "credit": credit,
                "fills": fills,
                "skills": list(skills_for_course(name)),
                "score": score,
                "reason": f"可补 {len(fills)} 项技能缺口（{'、'.join(fills)}）；{dir_reason}",
            })
    scored.sort(key=lambda x: (-x["score"], -len(x["fills"]), x["credit"], x["name"]))
    return scored[: max(1, int(top_n))]


def cohort_of(enroll_year: Any, student_no: str) -> int | None:
    """入学届别：DB 入学年份优先，学号抠年份兜底；皆无返回 None。"""
    try:
        if enroll_year not in (None, ""):
            return int(enroll_year)
    except (TypeError, ValueError):
        pass
    match = re.search(r"20\d{2}", str(student_no or ""))
    return int(match.group(0)) if match else None


def window_status(policy: Mapping[str, Any],
                  now: datetime | None = None) -> dict[str, Any]:
    """选课窗口三态；展示文本不带年份（日期数字会被 critic 掩码，不进白名单）。"""
    window = policy.get("window") or {}
    moment = now or datetime.now()
    start = datetime.fromisoformat(str(window.get("start")))
    end = datetime.fromisoformat(str(window.get("end")))
    state = "before" if moment < start else ("open" if moment < end else "closed")
    text = f"选课窗口 {window.get('start_text')}-{window.get('end_text')}"
    if state == "closed":
        text += "（本窗口已结束，以后续教务处通知为准）"
    elif state == "before":
        text += "（尚未开放）"
    else:
        text += "（开放中，先选先得）"
    return {"state": state, "text": text, "term": str(window.get("term") or ""),
            "start_text": str(window.get("start_text") or ""),
            "end_text": str(window.get("end_text") or "")}


def gened_status(*, cohort: int | None, major: str,
                 taken_names: Sequence[str],
                 policy: Mapping[str, Any]) -> dict[str, Any]:
    """通知必修通识模块核对：每模块专属关键词+子串；按专业类别豁免。"""
    gened = policy.get("gened") or {}
    required_cohort = int(gened.get("cohort") or 0)
    major_text = str(major or "")
    is_art = any(k in major_text for k in gened.get("art_major_keywords") or [])
    is_eng = any(k in major_text for k in gened.get("engineering_major_keywords") or [])
    modules: list[dict[str, Any]] = []
    for module in gened.get("modules") or []:
        kind = module.get("exempt")
        exempt = (kind == "art" and is_art) or (kind == "non_engineering" and not is_eng)
        matched = next((t for t in taken_names
                        if any(k in str(t) for k in module.get("keywords") or [])), "")
        modules.append({"name": str(module.get("name") or ""), "covered": bool(matched),
                        "matched_course": matched, "exempt": bool(exempt)})
    uncovered = [m["name"] for m in modules if not m["covered"] and not m["exempt"]]
    exempted = [m["name"] for m in modules if m["exempt"]]
    applicable = cohort is not None and cohort == required_cohort
    equivalence = policy.get("equivalence") or {}
    if applicable:
        note = (f"以上模块为教务处通知 {required_cohort} 级毕业前选修要求；"
                "词面核对可能漏判，以教务管理系统认定为准；课池未含通识模块课程。")
    elif cohort in (equivalence.get("cohorts") or []):
        note = (str(equivalence.get("text") or "")
                + " 你所在年级非通知适用年级，模块清单仅供参考，以本年级培养方案为准。")
    else:
        note = "入学届别未确认或不在通知适用范围内，模块清单仅供参考，以本年级培养方案与教务处通知为准。"
    return {"applicable": applicable, "cohort": cohort, "required_cohort": required_cohort,
            "major_category": "art" if is_art else ("engineering" if is_eng else "other"),
            "modules": modules, "uncovered": uncovered, "exempted": exempted, "note": note}


def credit_budget(*, earned_credits: float, elected_credits: float,
                  policy: Mapping[str, Any]) -> dict[str, Any]:
    """学生手册毕业学分核算：总学分口径；分类核算不可算，如实 note。"""
    credits = policy.get("credits") or {}
    total = float(credits.get("total") or 0.0)
    earned = round(float(earned_credits), 1)
    elected = round(float(elected_credits), 1)
    return {"total_required": total, "earned": earned, "elected": elected,
            "remaining": round(max(0.0, total - earned - elected), 1),
            "structure": {"general": float(credits.get("general") or 0.0),
                          "major": float(credits.get("major") or 0.0),
                          "practice": float(credits.get("practice") or 0.0)},
            "substitution_cap": float(credits.get("substitution_cap") or 0.0),
            "source": str(credits.get("source") or ""),
            "note": "课程表无类别列，通识/专业/实践分类核算不可确定性计算，仅给总学分口径。"}


def template_advice(facts: Mapping[str, Any]) -> str:
    """LLM 不可用/被驳回时的确定性降级稿：全部数值原样直引事实层。"""
    target = facts.get("target") or {}
    gaps = list(facts.get("skill_gaps") or [])
    recs = list(facts.get("recommendations") or [])
    lines: list[str] = []
    if not target.get("source"):
        lines.append(str(facts.get("note") or "暂无选课建议数据。"))
    title = str(target.get("title") or "")
    if title:
        lines.append(f"目标岗位：{title}（{target.get('company') or '未知企业'}）。")
    else:
        lines.append("目标岗位：按你的选修方向聚合的岗位技能要求。")
    covered = list(facts.get("covered") or [])
    required = list(facts.get("required") or [])
    lines.append(f"技能覆盖 {len(covered)}/{len(required)}。")
    if gaps:
        lines.append(f"当前缺口：{'、'.join(gaps)}。")
    else:
        lines.append("目标技能要求已全部覆盖，暂无需补课。")
    for rec in recs[:3]:
        lines.append(
            f"建议选修「{rec['name']}」（{rec['direction']}方向，{rec['credit']}学分，"
            f"得分 {rec['score']}）：{rec['reason']}。")
    if not recs and gaps:
        lines.append("课池中暂无能补当前缺口的课程。")
    lines.extend(_policy_lines(facts))
    return "\n".join(lines)


def _policy_lines(facts: Mapping[str, Any]) -> list[str]:
    """政策块确定性直引行：窗口/通识模块/学分预算/选课入口。"""
    lines: list[str] = []
    window = facts.get("window") or {}
    if window.get("text"):
        lines.append(str(window["text"]))
    gened = facts.get("gened") or {}
    if gened.get("applicable") and gened.get("uncovered"):
        lines.append(f"{gened.get('required_cohort')}级毕业前必修选修模块尚未覆盖："
                     + "、".join(str(m) for m in gened["uncovered"]) + "。")
    if gened.get("note"):
        lines.append(str(gened["note"]))
    credits = facts.get("credits") or {}
    if credits:
        lines.append(f"毕业最低总学分 {credits.get('total_required')}，已修 {credits.get('earned')}，"
                     f"已选 {credits.get('elected')}，剩余 {credits.get('remaining')} 学分。"
                     f"{credits.get('note')}")
    entry = (facts.get("policy") or {}).get("entry") or {}
    if entry.get("url"):
        lines.append(f"选课入口：{entry.get('path')}（{entry['url']}）。")
    return lines


# ----------------------------------------------------------------
# 取数部分（失败返回空，缺失不冒充；租户隔离在 SQL 里）
# ----------------------------------------------------------------
def _query(sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
    """与 engine.kg 相同的取数模式：连接/查询失败返回空列表。"""
    try:
        from app.config import get_settings
        import pymysql
        s = get_settings()
        conn = pymysql.connect(host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
                               password=s.mysql_password, database=s.mysql_db,
                               charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
                               connect_timeout=5)
    except Exception:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            return [dict(r) for r in cur.fetchall()]
    except Exception:
        return []
    finally:
        conn.close()


def load_pool() -> dict[str, list[dict[str, Any]]]:
    """选修课池：rules/direction_keywords.json 的 elective_pool（方向→课程列表）。"""
    global _pool_cache
    if _pool_cache is None:
        data = json.loads(_RULES_PATH.read_text(encoding="utf-8"))
        _pool_cache = {str(k): [dict(c) for c in v]
                       for k, v in (data.get("elective_pool") or {}).items()}
    return _pool_cache


def load_policy() -> dict[str, Any]:
    """选课政策快照：教务处通知 + 学生手册学分口径（rules/elective_policy.json）。"""
    global _policy_cache
    if _policy_cache is None:
        _policy_cache = json.loads(_POLICY_PATH.read_text(encoding="utf-8"))
    return _policy_cache


def load_electives(tenant_id: int, student_id: int) -> list[dict[str, Any]]:
    """本人已选选修课（选课记录表，租户+学生编号双过滤）。"""
    return _query(
        "SELECT `课程名称` AS name, `方向` AS direction, `学期` AS term, `学分` AS credit "
        "FROM `选课记录` WHERE `租户编号` = %s AND `学生编号` = %s "
        "ORDER BY `学期`, `课程名称`",
        (tenant_id, student_id),
    )


def load_completed_courses(tenant_id: int, student_id: int) -> list[str]:
    """本人已修课程名（成绩⋈课程，全学期累计；租户口径经学生表过滤）。"""
    rows = _query(
        "SELECT DISTINCT c.`课程名称` AS name FROM `成绩` sc "
        "JOIN `课程` c ON c.`编号` = sc.`课程编号` "
        "JOIN `学生` s ON s.`编号` = sc.`学生编号` AND s.`租户编号` = %s "
        "WHERE sc.`学生编号` = %s",
        (tenant_id, student_id),
    )
    return [str(r["name"]) for r in rows if r.get("name")]


def load_earned_credits(tenant_id: int, student_id: int) -> float:
    """已获学分（分数>=60，DISTINCT 课程防重修重复计；租户过滤）。"""
    rows = _query(
        "SELECT COALESCE(SUM(t.credit), 0) AS earned FROM ("
        " SELECT DISTINCT c.`编号`, c.`学分` AS credit FROM `成绩` sc "
        " JOIN `课程` c ON c.`编号` = sc.`课程编号` "
        " JOIN `学生` s ON s.`编号` = sc.`学生编号` AND s.`租户编号` = %s "
        " WHERE sc.`学生编号` = %s AND sc.`分数` >= 60) t",
        (tenant_id, student_id),
    )
    return round(float(rows[0].get("earned") or 0.0), 1) if rows else 0.0


def load_job_tags(job_id: int) -> list[str]:
    """岗位技能标签（清洗福利类噪声后）。"""
    rows = _query("SELECT `技能标签` AS skill_tags FROM `岗位` WHERE `编号` = %s",
                  (job_id,))
    if not rows:
        return []
    return recommend.clean_skill_tags(rows[0].get("skill_tags"))


def _resolve_target(tenant_id: int, student_id: int, student_no: str, term: str,
                    student: Mapping[str, Any],
                    electives: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """目标岗位：hybrid 头部岗位优先；空/异常降级为方向聚合。两来源都如实标注。"""
    try:
        from engine.hybrid import hybrid_recommend
        result = hybrid_recommend(tenant_id, student_no, term, top_n=1,
                                  write_log=False, student_id=student_id)
        items = list(result.get("items") or [])
    except Exception:
        items = []
    if items:
        top = items[0]
        job_id = int(top.get("job_id") or 0)
        tags = load_job_tags(job_id)
        if job_id and tags:
            direction = str(top.get("direction") or "")
            return {
                "job_id": job_id,
                "title": str(top.get("title") or ""),
                "company": str(top.get("company") or ""),
                "direction": direction,
                "directions": [direction] if direction else [],
                "required": tags,
                "source": "hybrid_top",
            }
    directions = sorted({str(e.get("direction") or "") for e in electives
                         if str(e.get("direction") or "").strip()}
                        | {str(d) for d in (student.get("directions") or [])
                           if str(d).strip()})
    if not directions:
        return {"job_id": None, "title": "", "company": "", "direction": "",
                "directions": [], "required": [], "source": ""}
    jobs = recommend.load_jobs(directions)
    tags = aggregate_required_tags(jobs)
    return {"job_id": None, "title": "", "company": "", "direction": "",
            "directions": directions, "required": tags,
            "source": "direction_aggregate" if tags else ""}


def elective_advice_for_student(tenant_id: int, student_id: int, student_no: str,
                                term: str, top_n: int = DEFAULT_TOP_N, *,
                                enroll_year: int | None = None,
                                now: datetime | None = None) -> dict[str, Any]:
    """入口：目标岗位技能要求 vs 已修+已选覆盖 → 缺口 → 候选课排序。查无如实报空+note。

    同时按教务处通知与学生手册算政策事实：窗口/通识模块/学分预算/选课入口。
    """
    student = recommend.load_student(tenant_id, student_no, term)
    electives = load_electives(tenant_id, student_id)
    completed = load_completed_courses(tenant_id, student_id)
    taken = completed + [str(e.get("name") or "") for e in electives]
    policy = load_policy()
    window = window_status(policy, now)
    window["applies_to_current_term"] = window["term"] == str(term)
    gened = gened_status(cohort=cohort_of(enroll_year, student_no),
                         major=str(student.get("major") or ""),
                         taken_names=taken, policy=policy)
    completed_norm = {recommend._norm(c) for c in completed}
    elected_credits = sum(float(e.get("credit") or 0.0) for e in electives
                          if recommend._norm(str(e.get("name") or "")) not in completed_norm)
    credits = credit_budget(earned_credits=load_earned_credits(tenant_id, student_id),
                            elected_credits=elected_credits, policy=policy)

    base: dict[str, Any] = {
        "student_no": str(student_no),
        "term": str(term),
        "engine_version": ELECTIVE_ENGINE_VERSION,
        "major": str(student.get("major") or ""),
        "gpa": student.get("gpa"),
        "taken_courses": sorted({t for t in taken if t}),
        "elected_directions": sorted({str(e.get("direction") or "") for e in electives
                                      if str(e.get("direction") or "").strip()}),
        "policy": {"version": policy.get("version"), "source": policy.get("source"),
                   "rules": list(policy.get("rules") or []),
                   "entry": policy.get("entry"), "equivalence": policy.get("equivalence"),
                   "min_students": policy.get("min_students"),
                   "start_week": policy.get("start_week"),
                   "withdraw_penalty_terms": policy.get("withdraw_penalty_terms")},
        "window": window, "gened": gened, "credits": credits,
    }
    target = _resolve_target(tenant_id, student_id, student_no, term, student, electives)
    required = list(target.get("required") or [])
    if not required:
        return {**base, "target": target, "required": [], "covered": [],
                "skill_gaps": [], "coverage": 0.0, "recommendations": [],
                "pool_total": sum(len(v) for v in load_pool().values()),
                "note": "暂无可核对的岗位技能要求：先看一次岗位推荐，或确认选课记录已入库。"}

    coverage, covered, skill_gaps = recommend.skill_cover_of(taken, required)
    # 覆盖口径为全学期累计（岗位推荐按当学期），差异在此明示
    note = "技能覆盖按已修课程与已选选修课全学期累计计算。"
    if target.get("source") == "direction_aggregate":
        note += "目标技能来自你选修方向相关岗位的高频标签聚合（非单一岗位）。"
    recommendations: list[dict[str, Any]] = []
    if skill_gaps:
        recommendations = rank_electives(load_pool(), skill_gaps,
                                         list(target.get("directions") or []),
                                         taken, top_n)
        if not recommendations:
            note += "课池中暂无能补当前缺口的课程。"
    else:
        note += "目标技能要求已全部覆盖，暂无需补课。"
    if gened.get("applicable") and gened.get("uncovered"):
        note += ("通识必修模块尚未覆盖：" + "、".join(gened["uncovered"])
                 + "（课池未含通识课程，以教务处通知为准）。")
    return {**base, "target": target, "required": required, "covered": covered,
            "skill_gaps": skill_gaps, "coverage": coverage,
            "recommendations": recommendations,
            "pool_total": sum(len(v) for v in load_pool().values()),
            "note": note}