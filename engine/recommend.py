# engine/recommend.py
# 职责：可解释的规则版岗位推荐——四维打分 + 命中/缺口/建议，全部来自确定性规则
# 依赖：engine.rules（权重与映射表）/ engine.store.DuckDBStore（写 recommend_log）/ 标准库
# 说明：**不调大模型、不用随机数**；冷启动只算 major_match 与 gpa_gate 并标记 cold_start；
#       结果写 recommend_log 表（engine_version="v1.0"）；同输入必得同输出（排序键包含 job_id）。

from __future__ import annotations

import json
import math
import re
import time
from typing import Any, Iterable, Mapping, Sequence

import pymysql

from app.config import Settings, get_settings
from engine.rules import (
    DEFAULT_ADVICE_COURSE,
    DIR_MAJORS,
    DIR_RELATED_DIRS,
    DIR_RELATED_MAJORS,
    GPA_BASE,
    GPA_EDU_PREMIUM,
    GPA_EXP_CAP,
    GPA_EXP_PREMIUM,
    GPA_MAX_GATE,
    RECOMMEND_ENGINE_VERSION,
    RECOMMEND_WEIGHTS,
    SKILL_ADVICE_COURSE,
    WELFARE_STOPWORDS,
    to_float,
)

# 各维度得分与 final_score 保留位数
_SCORE_NDIGITS = 4
# 单次最多候选岗位数（按 job_id 升序确定性截断）
MAX_CANDIDATES = 400
DEFAULT_TOP_N = 10


# ----------------------------------------------------------------
# 纯计算部分（可被单测直接调用，不碰 IO）
# ----------------------------------------------------------------
def min_gpa_of(job: Mapping[str, Any]) -> float:
    """岗位成绩门槛 = 基准 60 + 学历溢价 + 经验溢价（上限 90）。

    job 表没有 min_gpa 列，故按此规则折算；参数集中在 rules.py 便于审计与调参。
    """
    edu = str(job.get("education") or "").strip()
    premium = GPA_EDU_PREMIUM.get(edu, 0.0)
    exp = int(to_float(job.get("exp_min")) or 0)
    premium += min(exp, GPA_EXP_CAP) * GPA_EXP_PREMIUM
    return float(min(GPA_BASE + premium, GPA_MAX_GATE))


_ENG_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+\-#.]{1,}")
_ZH_CLEAN_RE = re.compile(r"[^一-鿿]")


def _norm(token: str) -> str:
    return str(token or "").strip().lower()


def _tokens(text: str) -> set[str]:
    """切成可比对的特征词：英文/数字串（≥2 字符）+ 中文整词与二元组。"""
    low = _norm(text)
    tokens: set[str] = set()
    for match in _ENG_TOKEN_RE.finditer(low):
        tokens.add(match.group(0))
    zh = _ZH_CLEAN_RE.sub("", low)
    if zh:
        tokens.add(zh)
        for i in range(len(zh) - 1):
            tokens.add(zh[i:i + 2])
    return tokens


def _hit(a: str, b: str) -> bool:
    """技能命中判定：完全相等，或存在共同特征词（'Java开发经验' 命中课程 'Java程序设计'）。"""
    if not str(a or "").strip() or not str(b or "").strip():
        return False
    if _norm(a) == _norm(b):
        return True
    return bool(_tokens(a) & _tokens(b))


def skill_cover_of(student_skills: Sequence[str],
                   job_tags: Sequence[str]) -> tuple[float, list[str], list[str]]:
    """技能覆盖率 = 命中数 / 岗位要求技能数；同时返回命中项与缺口项。"""
    tags = [str(t) for t in job_tags if str(t).strip()]
    if not tags:
        return 0.0, [], []
    hits = [t for t in tags if any(_hit(t, s) for s in student_skills)]
    gaps = [t for t in tags if t not in hits]
    return round(len(hits) / len(tags), _SCORE_NDIGITS), hits, gaps


def major_match_of(major: str, direction: str) -> tuple[float, str]:
    """专业匹配度：对口 1.0 / 相关 0.6 / 不符 0.0。"""
    major = str(major or "").strip()
    if not major or not direction:
        return 0.0, "专业信息缺失，无法判定专业匹配"
    if major in DIR_MAJORS.get(direction, ()):
        return 1.0, "专业完全匹配"
    if major in DIR_RELATED_MAJORS.get(direction, ()):
        return 0.6, f"{major} 属于 {direction} 方向的相近专业"
    return 0.0, f"{major} 不在 {direction} 方向的对口专业范围内"


def gpa_gate_of(gpa: float | None, min_gpa: float) -> tuple[float, str, str, float]:
    """成绩门槛达成度 = clamp(gpa / min_gpa, 0, 1)；同时给出命中/缺口话术与差值。"""
    if gpa is None:
        return 0.0, "", "成绩数据缺失，无法核对门槛", 0.0
    ratio = 0.0 if min_gpa <= 0 else max(0.0, min(1.0, float(gpa) / min_gpa))
    delta = round(float(gpa) - min_gpa, 2)
    if delta >= 0:
        return round(ratio, _SCORE_NDIGITS), f"成绩超过门槛 {abs(delta)} 分", "", delta
    return round(ratio, _SCORE_NDIGITS), "", f"成绩低于门槛 {abs(delta)} 分", delta


def interest_fit_of(directions: Iterable[str], job_direction: str) -> tuple[float, str]:
    """兴趣重合度：方向命中 1.0 / 相关方向 0.5 / 无关 0。"""
    directions = {str(d) for d in directions if str(d).strip()}
    if not directions:
        return 0.0, "无选修/浏览方向数据，兴趣项不参与打分"
    if job_direction in directions:
        return 1.0, f"选修/浏览方向命中 {job_direction}"
    for d in directions:
        if job_direction in DIR_RELATED_DIRS.get(d, ()):
            return 0.5, f"{d} 与 {job_direction} 属相关方向"
    return 0.0, f"未选修/浏览过 {job_direction} 方向"


def _action_items_of(gaps: Sequence[str], skill_gaps: Sequence[str],
                     gpa_gap: str, min_gpa: float, gpa: float | None,
                     cold_start: bool) -> list[str]:
    """「需要做的」清单：每条都由缺口直接推导，不引入任何新数值与推断。

    顺序：补技能 → 补成绩 → 补经历。没有缺口时给一条保底动作。
    """
    actions: list[str] = []
    for skill in list(skill_gaps)[:3]:
        course = ""
        for key, value in SKILL_ADVICE_COURSE.items():
            if _hit(skill, key):
                course = value
                break
        # SKILL_ADVICE_COURSE 的值自带《》，这里不再重复包一层
        actions.append(
            f"补齐「{skill}」：选修{course}或完成一个用到它的实战项目"
            if course else f"补齐「{skill}」：在课程或项目里做出可展示的成果"
        )
    if gpa_gap and gpa is not None:
        actions.append(f"把本学期均分提到 {min_gpa} 以上（当前 {round(float(gpa), 2)}，{gpa_gap}）")
    if not skill_gaps and not gpa_gap:
        actions.append("保持当前水平，争取一次与目标岗位直接相关的实习或竞赛经历")
    if cold_start:
        actions.append("先填一次职业意向并选修方向课程，让推荐有依据可算")
    return actions[:4]


def _advice_of(gaps: Sequence[str]) -> str:
    """建议段：优先补齐最缺技能对应的课程；无技能缺口时给通用建议。"""
    for skill in list(gaps)[:2]:
        for key, course in SKILL_ADVICE_COURSE.items():
            if _hit(skill, key):
                return f"建议选修{course}并完成一个实战项目"
    return f"建议选修{DEFAULT_ADVICE_COURSE}，并积累一次相关实习经历"


def score_job(student: Mapping[str, Any], job: Mapping[str, Any]) -> dict[str, Any]:
    """单岗位打分：四维加权和；缺失维度不参与打分，权重在可用项内重归。

    student 约定键：student_no / major / gpa / skills(list[str]) / directions(list[str])
    job 约定键：id / title / company / city / salary_min / salary_max /
               education / exp_min / skill_tags(list[str]) / direction
    """
    direction = str(job.get("direction") or "")
    tags = [str(t) for t in (job.get("skill_tags") or [])]

    major_score, major_reason = major_match_of(student.get("major"), direction)
    gate = min_gpa_of(job)
    gpa_score, gpa_hit, gpa_gap, _delta = gpa_gate_of(to_float(student.get("gpa")), gate)
    cover_score, skill_hits, skill_gaps = skill_cover_of(
        list(student.get("skills") or []), tags)
    interest_score, interest_reason = interest_fit_of(
        list(student.get("directions") or []), direction)

    dims = {
        "major_match": major_score,
        "gpa_gate": gpa_score,
        "skill_cover": cover_score,
        "interest_fit": interest_score,
    }
    has_skill = bool(tags)
    has_interest = bool(student.get("directions"))
    available = [k for k in dims
                 if k not in ("skill_cover", "interest_fit")
                 or (k == "skill_cover" and has_skill)
                 or (k == "interest_fit" and has_interest)]
    cold_start = not has_skill and not has_interest
    total_w = sum(RECOMMEND_WEIGHTS[k] for k in available) or 1.0
    final = sum(RECOMMEND_WEIGHTS[k] * dims[k] for k in available) / total_w

    hit_items: list[str] = []
    gap_items: list[str] = []
    hit_items.append(major_reason if major_score >= 0.6 else "")
    if gpa_hit:
        hit_items.append(gpa_hit)
    if has_skill:
        hit_items.append(f"技能覆盖 {len(skill_hits)}/{len(tags)}")
        gap_items += [f"岗位要求{skill}，你的课程记录未体现" for skill in skill_gaps[:3]]
    if gpa_gap:
        gap_items.append(gpa_gap)
    if has_interest:
        (hit_items if interest_score > 0 else gap_items).append(interest_reason)
    hit_items = [h for h in hit_items if h]
    gap_items = [g for g in gap_items if g]

    return {
        "job_id": int(job.get("id") or 0),
        "title": str(job.get("title") or ""),
        "company": str(job.get("company") or ""),
        "city": str(job.get("city") or ""),
        "salary_min": to_float(job.get("salary_min")),
        "salary_max": to_float(job.get("salary_max")),
        "direction": direction,
        "min_gpa": round(gate, 2),
        "final_score": round(final, _SCORE_NDIGITS),
        "dims": {k: round(v, _SCORE_NDIGITS) for k, v in dims.items()},
        "hit_items": hit_items,
        "gap_items": gap_items,
        "action_items": _action_items_of(gap_items, skill_gaps, gpa_gap, gate,
                                         to_float(student.get("gpa")), cold_start),
        "advice": _advice_of(skill_gaps),
        "cold_start": cold_start,
    }


def recommend(student: Mapping[str, Any], jobs: Sequence[Mapping[str, Any]],
              top_n: int = DEFAULT_TOP_N) -> dict[str, Any]:
    """给一名学生排 top_n 岗位：先打分，再按 (-final_score, -salary_max, job_id) 确定性排序。"""
    scored = [score_job(student, job) for job in jobs]
    # 二次键薪资上限、三次键 job_id：同分时结果依然稳定且更有参考性（无随机数）
    scored.sort(key=lambda x: (-x["final_score"], -(x["salary_max"] or 0.0), x["job_id"]))
    items = scored[:max(1, int(top_n))]
    return {
        "student_no": str(student.get("student_no") or ""),
        "term": str(student.get("term") or ""),
        "engine_version": RECOMMEND_ENGINE_VERSION,
        "cold_start": bool(items[0]["cold_start"]) if items else False,
        "candidate_cnt": len(scored),
        "items": items,
    }


# ----------------------------------------------------------------
# 数据库部分（取数 + 落推荐日志）
# ----------------------------------------------------------------
def _connect(settings: Settings | None = None) -> pymysql.connections.Connection:
    s = settings or get_settings()
    return pymysql.connect(host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
                           password=s.mysql_password, database=s.mysql_db,
                           charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
                           connect_timeout=5)


def _query(sql: str, params: Sequence[Any]) -> list[dict[str, Any]]:
    try:
        conn = _connect()
    except (pymysql.MySQLError, OSError):
        return []
    try:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            return [dict(r) for r in cur.fetchall()]
    except (pymysql.MySQLError, OSError):
        return []
    finally:
        conn.close()


def load_student(tenant_id: int, student_no: str, term: str) -> dict[str, Any]:
    """取推荐所需画像：专业 / 均分 / 技能（课名映射）/ 方向（DuckDB 的 course_pref）。"""
    rows = _query(
        "SELECT s.student_no AS student_no, s.major AS major, AVG(sc.score) AS gpa "
        "FROM student s "
        "JOIN score sc ON sc.student_id = s.id AND sc.term = %s "
        "WHERE s.tenant_id = %s AND s.student_no = %s "
        "GROUP BY s.student_no, s.major",
        (term, tenant_id, student_no),
    )
    base = rows[0] if rows else {}
    courses = _query(
        "SELECT DISTINCT c.name AS name FROM score sc "
        "JOIN course c ON c.id = sc.course_id "
        "JOIN student s ON s.id = sc.student_id AND s.tenant_id = %s "
        "WHERE s.student_no = %s AND sc.term = %s",
        (tenant_id, student_no, term),
    )
    directions: list[str] = []
    try:
        from engine.store import DuckDBStore

        row = DuckDBStore().read_student_feature(student_no, term) or {}
        pref = row.get("course_pref") or {}
        if isinstance(pref, str):
            pref = json.loads(pref)
        directions = sorted(str(k) for k in pref)
    except Exception:
        directions = []
    return {
        "student_no": str(base.get("student_no") or student_no),
        "term": term,
        "major": str(base.get("major") or ""),
        "gpa": to_float(base.get("gpa")),
        "skills": [str(c["name"]) for c in courses],  # 课名即技能证据
        "directions": directions,
    }


_dict_cache: tuple[tuple[tuple[str, tuple[str, ...]], ...], str] | None = None


def _load_direction_dict() -> tuple[tuple[tuple[str, tuple[str, ...]], ...], str]:
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "rules" / "direction_keywords.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    directions = tuple((str(d["name"]), tuple(str(k) for k in d["keywords"]))
                       for d in data["directions"])
    return directions, str(data.get("fallback", "其他"))


def direction_of(text: str) -> str:
    """复用同一份方向词典（与 build_profile_raw / agents.tools 一致）。"""
    global _dict_cache
    if _dict_cache is None:
        _dict_cache = _load_direction_dict()
    directions, fallback = _dict_cache
    low = str(text or "").lower()
    for name, keywords in directions:
        if any(k.lower() in low for k in keywords):
            return name
    return fallback


def _parse_tags(raw: Any) -> list[str]:
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


def clean_skill_tags(raw: Any) -> list[str]:
    """剔除福利类噪声 tag（招聘站常把「五险一金/年度体检」写进 skill_tags）。

    不清洗会让「岗位要求年度体检，你的课程记录未体现」这类句子混进缺口归因。
    """
    tags = _parse_tags(raw)
    kept: list[str] = []
    for tag in tags:
        text = str(tag).strip()
        if not text or any(stop in text for stop in WELFARE_STOPWORDS):
            continue
        kept.append(text)
    return kept


def load_jobs(directions: Sequence[str], limit: int = MAX_CANDIDATES) -> list[dict[str, Any]]:
    """候选岗位：与本学生方向相关的岗位**全部**入选在前，其余按 id 步长确定性抽样补足。

    抽样按固定步长取（不是随机、也不是只取前 N 条），保证覆盖全 id 区间且同输入同结果。
    """
    rows = _query(
        "SELECT id, title, company, city, salary_min, salary_max, education, "
        "       exp_min, exp_max, skill_tags "
        "FROM job ORDER BY id",
        (),
    )
    jobs: list[dict[str, Any]] = []
    for row in rows:
        tags = clean_skill_tags(row.get("skill_tags"))
        row["skill_tags"] = tags
        row["direction"] = direction_of(" ".join([str(row.get("title") or "")] + tags))
        jobs.append(row)

    wanted = {str(d) for d in directions if str(d)}
    if not wanted:
        return _stride_sample(jobs, limit)
    related = [j for j in jobs if j["direction"] in wanted]
    others = _stride_sample([j for j in jobs if j["direction"] not in wanted],
                            max(0, limit - len(related)))
    return (related + others)[: max(limit, len(related))]


def _stride_sample(jobs: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """确定性抽样：按固定步长抽取，覆盖全表 id 区间。"""
    limit = max(0, int(limit))
    if limit == 0:
        return []
    if len(jobs) <= limit:
        return jobs
    stride = math.ceil(len(jobs) / limit)
    return list(jobs[::stride])[:limit]


def write_recommend_log(result: Mapping[str, Any]) -> int:
    """把本次推荐写进 DuckDB recommend_log（engine_version 随行）。"""
    written = 0
    try:
        from engine.store import DuckDBStore

        store = DuckDBStore()
    except Exception:
        return 0
    base_id = int(time.time() * 1000) * 1000
    for idx, item in enumerate(result.get("items") or []):
        try:
            written += int(store.write_recommend_log({
                "id": base_id + idx,
                "student_no": str(result.get("student_no") or ""),
                "job_id": int(item.get("job_id") or 0),
                "content_score": float(item.get("final_score") or 0.0),
                "cf_score": None,  # 协同过滤未实现，占位留空
                "final_score": float(item.get("final_score") or 0.0),
                # 原样传 list：DuckDBStore.write_recommend_log 负责统一序列化。
                # 这里若先 json.dumps，store 会再 dumps 一次，落库变成双重转义字符串。
                "hit_items": list(item.get("hit_items") or []),
                "gap_items": list(item.get("gap_items") or []),
                "advice": str(item.get("advice") or ""),
                "engine_version": RECOMMEND_ENGINE_VERSION,
            }) or 0)
        except Exception:
            continue
    return written


def recommend_for_student(tenant_id: int, student_no: str, term: str,
                          top_n: int = DEFAULT_TOP_N,
                          *, write_log: bool = True) -> dict[str, Any]:
    """端到端：取画像 → 取候选 → 打分排序 →（可选）写 recommend_log。"""
    student = load_student(tenant_id, student_no, term)
    if not student["major"] and student["gpa"] is None:
        return {
            "student_no": student_no, "term": term,
            "engine_version": RECOMMEND_ENGINE_VERSION,
            "cold_start": True, "candidate_cnt": 0, "items": [],
            "note": "该生在本学期无成绩记录，无法推荐",
        }
    jobs = load_jobs(student["directions"])
    result = recommend(student, jobs, top_n=top_n)
    if write_log:
        result["logged"] = write_recommend_log(result)
    return result
