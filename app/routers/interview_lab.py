# app/routers/interview_lab.py
# 职责：面试实验室 API——把面试结果与校内学业数据交叉，产出商业产品做不到的结论：
#   1) 圆桌评审（三面试官独立打分 + 分歧度）
#   2) 失分溯源（漏考点 → 具体课程 → 成绩分位）
#   3) 同辈分位（同专业同年级实测基准，样本不足诚实降级为课程代理）
#   4) 群面（无领导小组讨论）四方抢话模拟
#   5) 能力护照 / 示范骨架 / 复盘卡 / 表达力度量
#   6) 岗位就绪度（事前：岗位技能 → 课程成绩 → 简历证据链，挖出「被埋没的资产」）
#   7) 面试官视角（反转：学生给匿名作答排序，暴露自己的评分偏误）
# 铁律：分数一律由 engine 计算，本层只做取数与拼装；模型只组织语言且必须可降级；
#       学生只能访问本人数据，越权一律 404（不泄露存在性）。

from __future__ import annotations

import json
import math
import random
import re
import os
import time
import uuid
from collections import defaultdict
from typing import Any, Mapping, Sequence

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from agents import llm as llm_client
from agents.tools import ToolContext
from app.auth import require_student
from app.routers.interview import (_conn, _evidence, _json_list, _load_resume, _one,
                                   _rows, _rubric_of_q)
from engine import attribution as attr_engine
from engine import calibration as calib_engine
from engine import expression as expr_engine
from engine import group as group_engine
from engine import passport as passport_engine
from engine import peer as peer_engine
from engine import readiness as readi_engine
from engine import shadow as shadow_engine
from engine.kg import skills_for_course
from engine.interview import (
    QUESTION_TYPES,
    aggregate,
    core_problems,
    gap_list,
    improvement_plan,
    score_answer,
)
from engine.panel import dimension_percent, review

router = APIRouter(prefix="/interview/lab", tags=["interview-lab"])

DIMS = ("content", "structure", "depth", "evidence")
DIM_LABELS = {"content": "内容", "structure": "结构", "depth": "深度", "evidence": "证据"}

# 群面会话：进程内存储（单 worker，见 Dockerfile）；30 分钟 TTL，最多 200 场
_GROUP_TTL = 30 * 60
_GROUP_MAX = 200
_GROUP_SESSIONS: dict[str, dict[str, Any]] = {}


class ExpressionIn(BaseModel):
    text: str = ""
    duration_sec: float | None = None
    segments: list[dict[str, Any]] | None = None


class GroupStartIn(BaseModel):
    job_id: int | None = None
    job_title: str | None = None
    industry: str | None = None
    skills: list[str] | None = None


class GroupTurnIn(BaseModel):
    state: dict[str, Any]
    text: str | None = None


class ReadinessIn(BaseModel):
    job_id: int | None = None
    skills: list[str] | None = None
    job_title: str | None = None
    industry: str | None = None


class CalibrationJudgeIn(BaseModel):
    session_id: int
    ranks: list[dict[str, Any]] = []


# ----------------------------------------------------------------
# 取数：一场已完成面试的全部上下文（自带越权校验）
# ----------------------------------------------------------------
def _load_session(cur, sid: int, ctx: ToolContext) -> dict[str, Any]:
    sess = _one(cur, "SELECT * FROM `面试会话` WHERE `编号`=%s AND `租户编号`=%s",
                (sid, ctx.tenant_id))
    if not sess or int(sess["学生编号"]) != int(ctx.student_id or 0):
        raise HTTPException(404, "会话不存在或不属于本人")
    if sess["状态"] != "finished":
        raise HTTPException(409, "该场面试还没答完，暂不能生成分析")
    outline = json.loads(sess["提纲"] or "[]")
    answers = _rows(cur, "SELECT * FROM `面试问答` WHERE `会话编号`=%s ORDER BY `轮次`", (sid,))
    resume = _load_resume(cur, int(sess["简历编号"]), ctx.tenant_id) or {}
    snapshot = json.loads(sess["岗位要求快照"] or "null") or {}
    # 按轮次对齐（追问插入后 outline 与 answers 顺序仍一致，但用 map 更稳）
    amap = {int(a["轮次"]): a for a in answers}
    pairs = [(o, amap.get(int(o.get("round") or 0))) for o in outline]
    return {"sess": sess, "outline": outline, "answers": answers, "pairs": pairs,
            "resume": resume, "snapshot": snapshot,
            "job_skills": [str(s) for s in (snapshot.get("skill_tags") or [])]}


def _score_pairs(pairs: Sequence[tuple[Mapping, Mapping | None]],
                 evidence: Sequence[str], job_skills: Sequence[str]) -> list[dict | None]:
    """逐题确定性评分（与答题时同一函数，口径一致）。"""
    out: list[dict | None] = []
    for o, a in pairs:
        ans = (a or {}).get("学生回答")
        out.append(score_answer(ans, _rubric_of_q(o, job_skills), evidence))
    return out


def _dims_of(scores: Sequence[Mapping | None]) -> dict[str, float]:
    """整场四维百分制：已答题逐题折算后取均值；没答的维度不出现。"""
    acc: dict[str, list[float]] = defaultdict(list)
    for it in scores:
        if not it:
            continue
        dp = dimension_percent(it)
        for k in DIMS:
            if dp.get(k) is not None:
                acc[k].append(float(dp[k]))
    return {k: round(sum(v) / len(v), 2) for k, v in acc.items() if v}


def _probe_chain(outline: Sequence[Mapping], scores: Sequence[Mapping | None]) -> list[dict]:
    chain: list[dict] = []
    for o, s in zip(outline, scores):
        missed = list((s or {}).get("keyword_missed") or [])
        chain.append({
            "round": int(o.get("round") or 0),
            "label": QUESTION_TYPES.get(str(o.get("type")), {}).get("label", str(o.get("type"))),
            "question": str(o.get("question") or ""),
            "score": float(s["score"]) if s else None,
            "is_probe": bool(o.get("probe_of")),
            "probe_of": o.get("probe_of"),
            "gap": ("漏掉：" + "、".join(missed[:3])) if missed else "",
        })
    return chain


def _grade(total: float | None) -> str | None:
    if total is None:
        return None
    if total >= 85:
        return "A"
    if total >= 75:
        return "B+"
    if total >= 65:
        return "B"
    if total >= 55:
        return "C+"
    return "C"


# ----------------------------------------------------------------
# 1. 圆桌评审
# ----------------------------------------------------------------
@router.get("/panel/{sid}")
def panel_review(sid: int, llm: bool = False, ctx: ToolContext = Depends(require_student)) -> dict:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            ctxd = _load_session(cur, sid, ctx)
        evidence = _evidence(ctxd["resume"], ctxd["snapshot"])
        scores = _score_pairs(ctxd["pairs"], evidence, ctxd["job_skills"])
        result = review(scores, ctxd["outline"], ctxd["job_skills"])
        if llm and result.get("consensus", {}).get("score") is not None:
            result["consensus"]["summary"] = _panel_summary(result, ctxd)
        return {"session_id": sid, "job_title": ctxd["sess"].get("岗位名称"),
                "panel": result, "job_skills": ctxd["job_skills"]}
    finally:
        conn.close()


def _panel_summary(result: Mapping, ctxd: Mapping) -> str:
    """模型只改写合议措辞；数字已由引擎算好，失败保留模板。"""
    facts = []
    for p in result.get("panelists") or []:
        facts.append(f"{p['title']}·{p['name']}：{p['score']} 分（{p['verdict']}），最在意{p['focus']}")
    c = result.get("consensus") or {}
    user = (
        f"岗位：{ctxd['sess'].get('岗位名称') or '通用岗位'}\n"
        + "\n".join(facts)
        + f"\n三人分差 {c.get('spread')} 分（{c.get('level')}），合议 {c.get('score')} 分。\n"
        + f"分歧点：{(result.get('divergence') or {}).get('note') or '无'}\n"
        "请写一段 90~140 字的合议总结：说明三人为什么看法不同、学生最该改的一件事。"
        "不得修改任何分数，不得编造学生没说过的内容。"
    )
    try:
        text = llm_client.generate_reply("teacher", system_prompt="你是校招面试评审组长，说话直接、不客套。",
                                         user_prompt=user, tag="panel.consensus")
        if text and text.strip():
            return text.strip()
    except Exception:
        pass
    return str(c.get("summary") or "")


# ----------------------------------------------------------------
# 2. 示范回答骨架
# ----------------------------------------------------------------
@router.get("/shadow/{sid}")
def shadow_items(sid: int, ctx: ToolContext = Depends(require_student)) -> dict:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            ctxd = _load_session(cur, sid, ctx)
        evidence = _evidence(ctxd["resume"], ctxd["snapshot"])
        scores = _score_pairs(ctxd["pairs"], evidence, ctxd["job_skills"])
        terms = [str(t) for t in (ctxd["resume"].get("courses") or [])][:8]
        items = []
        for (o, a), s in zip(ctxd["pairs"], scores):
            items.append({
                "round": int(o.get("round") or 0),
                "label": QUESTION_TYPES.get(str(o.get("type")), {}).get("label", str(o.get("type"))),
                "question": str(o.get("question") or ""),
                "answer": ((a or {}).get("学生回答") or ""),
                "missed": list((s or {}).get("keyword_missed") or []),
                "shadow": shadow_engine.shadow(str(o.get("type") or "project"),
                                               _rubric_of_q(o, ctxd["job_skills"]), terms),
            })
        return {"session_id": sid, "items": items}
    finally:
        conn.close()


# ----------------------------------------------------------------
# 3. 表达力度量
# ----------------------------------------------------------------
@router.post("/expression")
def expression(inp: ExpressionIn, ctx: ToolContext = Depends(require_student)) -> dict:
    return expr_engine.analyze(inp.text or "", inp.duration_sec, inp.segments)


# ----------------------------------------------------------------
# 4. 能力护照
# ----------------------------------------------------------------
@router.get("/passport")
def passport(target: str | None = None, ctx: ToolContext = Depends(require_student)) -> dict:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            sessions = _rows(
                cur,
                "SELECT `编号`,`岗位名称`,`总分`,`创建时间`,`完成时间`,`提纲`,`简历编号`,`岗位要求快照`"
                " FROM `面试会话` WHERE `租户编号`=%s AND `学生编号`=%s AND `状态`='finished'"
                " ORDER BY `创建时间`", (ctx.tenant_id, ctx.student_id))
            if not sessions:
                return passport_engine.build_passport([], _target_of(target))
            ids = [int(s["编号"]) for s in sessions]
            qa = _rows(cur, "SELECT `会话编号`,`轮次`,`问题类型`,`学生回答` FROM `面试问答`"
                            " WHERE `会话编号` IN (" + ",".join(["%s"] * len(ids)) + ")"
                            " ORDER BY `会话编号`,`轮次`", tuple(ids))
        by_sid: dict[int, list[dict]] = defaultdict(list)
        for r in qa:
            by_sid[int(r["会话编号"])].append(r)
        rows: list[dict] = []
        resume_cache: dict[int, dict] = {}
        for s in sessions:
            sid = int(s["编号"])
            outline = json.loads(s["提纲"] or "[]")
            snapshot = json.loads(s["岗位要求快照"] or "null") or {}
            skills = [str(x) for x in (snapshot.get("skill_tags") or [])]
            amap = {int(a["轮次"]): a for a in by_sid.get(sid, [])}
            pairs = [(o, amap.get(int(o.get("round") or 0))) for o in outline]
            # 证据必须逐场取真实值：传空会让 evidence 维度恒为 0，雷达图与报告页对不上
            rid = int(s.get("简历编号") or 0)
            if rid not in resume_cache:
                with conn.cursor() as cur2:
                    resume_cache[rid] = _load_resume(cur2, rid, ctx.tenant_id) or {}
            scores = _score_pairs(pairs, _evidence(resume_cache[rid], snapshot), skills)
            dims = _dims_of(scores)
            total = s.get("总分")
            if total is None:
                agg = aggregate(scores, outline)
                total = agg["total"] if agg else None
            rows.append({
                "session_id": sid,
                "date": str(s.get("完成时间") or s.get("创建时间") or "")[:10],
                "total": float(total) if total is not None else None,
                "job_title": s.get("岗位名称"),
                "dims": dims,
                "probes": sum(1 for o in outline if o.get("probe_of")),
                "spread": float(review(scores, outline, skills).get("consensus", {}).get("spread") or 0),
            })
        return passport_engine.build_passport(rows, _target_of(target))
    finally:
        conn.close()


def _target_of(raw: str | None) -> dict[str, float] | None:
    """?target=content:80,structure:75 形式；非法项忽略。"""
    if not raw:
        return None
    out: dict[str, float] = {}
    for part in raw.split(","):
        if ":" not in part:
            continue
        k, v = part.split(":", 1)
        k = k.strip()
        if k in DIMS:
            try:
                out[k] = max(0.0, min(100.0, float(v)))
            except ValueError:
                continue
    return out or None


# ----------------------------------------------------------------
# 5. 失分溯源到课程
# ----------------------------------------------------------------
@router.get("/attribution/{sid}")
def attribution(sid: int, ctx: ToolContext = Depends(require_student)) -> dict:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            ctxd = _load_session(cur, sid, ctx)
            student = _one(cur, "SELECT `专业`,`年级` FROM `学生` WHERE `编号`=%s"
                                " AND `租户编号`=%s", (ctx.student_id, ctx.tenant_id)) or {}
            major, grade = student.get("专业"), student.get("年级")
            courses = _rows(
                cur,
                "SELECT c.`编号` AS course_id, c.`课程名称` AS name, c.`学分` AS credit,"
                "       MAX(g.`分数`) AS score"
                " FROM `成绩` g JOIN `课程` c ON c.`编号`=g.`课程编号`"
                " WHERE g.`学生编号`=%s GROUP BY c.`编号`"
                " ORDER BY c.`学分` DESC", (ctx.student_id,))
            # 同专业同年级该课的成绩分布 → 每门课的分位
            dist: dict[int, list[float]] = defaultdict(list)
            if major and grade:
                for r in _rows(
                        cur,
                        "SELECT g.`课程编号` AS cid, g.`分数` AS score"
                        " FROM `成绩` g JOIN `学生` st ON st.`编号`=g.`学生编号`"
                        " WHERE st.`专业`=%s AND st.`年级`=%s", (major, grade)):
                    dist[int(r["cid"])].append(float(r["score"]))
        evidence = _evidence(ctxd["resume"], ctxd["snapshot"])
        scores = _score_pairs(ctxd["pairs"], evidence, ctxd["job_skills"])
        # 漏考点按轮次归集（同一考点在多轮漏掉 → 更该被点名）
        missed_by_round: dict[int, list[str]] = {}
        for (o, _a), s in zip(ctxd["pairs"], scores):
            if s and s.get("keyword_missed"):
                missed_by_round[int(o.get("round") or 0)] = list(s["keyword_missed"])
        for c in courses:
            vals = dist.get(int(c["course_id"])) or []
            c["score"] = float(c["score"] or 0)
            c["percentile"] = peer_engine.percentile_of(c["score"], vals) if vals else None
            # 知识图谱的「课程→技能」映射：考点命中技能即可命中课程，比 2-gram 准得多
            c["skills"] = list(skills_for_course(str(c["name"])))
        return {"session_id": sid, "job_title": ctxd["sess"].get("岗位名称"),
                **attr_engine.attribute(missed_by_round, courses)}
    finally:
        conn.close()


# ----------------------------------------------------------------
# 6. 同辈分位
# ----------------------------------------------------------------
# 维度 → 课程名关键词（用于样本不足时的诚实代理基准，可解释、可复核）
_PROXY_HINTS = {
    "content": ("基础", "概论", "导论", "原理", "数学", "统计"),
    "structure": ("设计", "系统", "架构", "工程", "管理", "规划"),
    "depth": ("算法", "分析", "模型", "进阶", "高级", "优化"),
    "evidence": ("实验", "实践", "实训", "课程设计", "项目", "实习"),
}


@router.get("/peer/{sid}")
def peer_bench(sid: int, ctx: ToolContext = Depends(require_student)) -> dict:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            ctxd = _load_session(cur, sid, ctx)
            student = _one(cur, "SELECT `专业`,`年级` FROM `学生` WHERE `编号`=%s"
                                " AND `租户编号`=%s", (ctx.student_id, ctx.tenant_id)) or {}
            major, grade = student.get("专业"), student.get("年级")
            cohort = 0
            samples: list[float] = []
            proxy: dict[str, list[float]] = {k: [] for k in DIMS}
            if major and grade:
                row = _one(cur, "SELECT COUNT(*) AS n FROM `学生` WHERE `专业`=%s AND `年级`=%s",
                           (major, grade))
                cohort = int((row or {}).get("n") or 0)
                # 实测样本：同专业同年级每人最新一场（避免同一人反复刷分把分布拉偏）
                samples = [float(r["total"]) for r in _rows(
                    cur,
                    "SELECT s.`总分` AS total FROM `面试会话` s"
                    " JOIN `学生` st ON st.`编号`=s.`学生编号`"
                    " WHERE st.`专业`=%s AND st.`年级`=%s AND s.`状态`='finished'"
                    "   AND s.`总分` IS NOT NULL"
                    "   AND s.`编号`=(SELECT MAX(s2.`编号`) FROM `面试会话` s2"
                    "               WHERE s2.`学生编号`=s.`学生编号` AND s2.`状态`='finished')",
                    (major, grade))]
                # 代理样本：每个学生各维度相关课程均分 → 个体层面的分布
                per_student: dict[int, dict[str, list[float]]] = defaultdict(lambda: {k: [] for k in DIMS})
                for r in _rows(
                        cur,
                        "SELECT g.`学生编号` AS sid, c.`课程名称` AS name, g.`分数` AS score"
                        " FROM `成绩` g JOIN `课程` c ON c.`编号`=g.`课程编号`"
                        " JOIN `学生` st ON st.`编号`=g.`学生编号`"
                        " WHERE st.`专业`=%s AND st.`年级`=%s", (major, grade)):
                    name = str(r["name"] or "")
                    for dim, hints in _PROXY_HINTS.items():
                        if any(h in name for h in hints):
                            per_student[int(r["sid"])][dim].append(float(r["score"]))
                for _sid, dims in per_student.items():
                    for dim, vals in dims.items():
                        if vals:
                            proxy[dim].append(round(sum(vals) / len(vals), 2))
        evidence = _evidence(ctxd["resume"], ctxd["snapshot"])
        scores = _score_pairs(ctxd["pairs"], evidence, ctxd["job_skills"])
        dims = _dims_of(scores)
        agg = aggregate(scores, ctxd["outline"])
        result = peer_engine.benchmark(agg["total"] if agg else None, dims, samples, cohort,
                                       {k: v for k, v in proxy.items() if v})
        return {"session_id": sid, **result}
    finally:
        conn.close()


# ----------------------------------------------------------------
# 7. 复盘卡
# ----------------------------------------------------------------
@router.get("/report-card/{sid}")
def report_card(sid: int, ctx: ToolContext = Depends(require_student)) -> dict:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            ctxd = _load_session(cur, sid, ctx)
        evidence = _evidence(ctxd["resume"], ctxd["snapshot"])
        scores = _score_pairs(ctxd["pairs"], evidence, ctxd["job_skills"])
        panel = review(scores, ctxd["outline"], ctxd["job_skills"])
        agg = aggregate(scores, ctxd["outline"])
        problems = core_problems(scores, ctxd["outline"])
        gaps = gap_list(ctxd["resume"], {"title": ctxd["sess"].get("岗位名称"),
                                        "skill_tags": ctxd["job_skills"]}, scores, ctxd["outline"])
        plan = improvement_plan(gaps, problems)
        dims = _dims_of(scores)
        return {
            "session_id": sid,
            "job_title": ctxd["sess"].get("岗位名称"),
            "date": str(ctxd["sess"].get("完成时间") or ctxd["sess"].get("创建时间") or "")[:10],
            "total": agg["total"] if agg else None,
            "grade": _grade(agg["total"] if agg else None),
            "panel": panel,
            "passport_dot": dims,
            "probe_chain": _probe_chain(ctxd["outline"], scores),
            "top_problems": [f"[{p['dimension']}] {p['problem']}" for p in problems][:3],
            "next_actions": [f"{s['when']}｜{s['focus']}：{s['action']}" for s in plan][:2]
                            or [f"{g['dimension']}：{g['action']}" for g in gaps][:2],
            "expression": None,
        }
    finally:
        conn.close()


# ----------------------------------------------------------------
# 8. 群面（无领导小组讨论）
# ----------------------------------------------------------------
def _prune_groups() -> None:
    now = time.time()
    for gid in [k for k, v in _GROUP_SESSIONS.items() if now - v["ts"] > _GROUP_TTL]:
        _GROUP_SESSIONS.pop(gid, None)
    while len(_GROUP_SESSIONS) > _GROUP_MAX:
        oldest = min(_GROUP_SESSIONS.items(), key=lambda kv: kv[1]["ts"])[0]
        _GROUP_SESSIONS.pop(oldest, None)


def _group_speak(system: str, user: str) -> str:
    """群面发言调用模型；任何异常向上抛，由 engine.group 的降级兜住。"""
    text = llm_client.generate_reply("student", system_prompt=system, user_prompt=user,
                                     tag="group.turn")
    if not text:
        raise RuntimeError("模型未返回内容")
    return str(text)


@router.post("/group/start")
def group_start(inp: GroupStartIn, ctx: ToolContext = Depends(require_student)) -> dict:
    title, industry, skills = inp.job_title, inp.industry, list(inp.skills or [])
    if inp.job_id:
        conn = _conn()
        try:
            with conn.cursor() as cur:
                job = _one(cur, "SELECT `岗位名称`,`行业`,`技能标签` FROM `岗位` WHERE `编号`=%s",
                           (inp.job_id,))
            if job:
                title = title or job.get("岗位名称")
                industry = industry or job.get("行业")
                if not skills:
                    raw = job.get("技能标签")
                    skills = json.loads(raw) if isinstance(raw, str) else list(raw or [])
        finally:
            conn.close()
    # 每场随机 seed：同一岗位不同场次换不同题型（模板 12 种），seed 固定仍可复现
    topic = group_engine.make_topic(title or "数据分析岗", industry, skills,
                                    seed=random.randrange(1 << 20))
    state = {"version": group_engine.GROUP_VERSION, "topic": topic, "turns": [],
             "student_turns": [], "elapsed_turns": 0}
    op = group_engine.opening(topic)
    state["turns"].append(op["first_turn"])
    state["elapsed_turns"] = 1
    gid = uuid.uuid4().hex[:12]
    _prune_groups()
    _GROUP_SESSIONS[gid] = {"ts": time.time(), "student_id": ctx.student_id}
    return {"group_id": gid, "topic": topic, "opening": op, "state": state}


@router.post("/group/turn")
def group_turn(inp: GroupTurnIn, ctx: ToolContext = Depends(require_student)) -> dict:
    state = dict(inp.state or {})
    text = (inp.text or "").strip()
    ai_turns: list[dict] = []
    try:
        if text:
            r = group_engine.student_turn(state, text)
            state = r["state"]
        # 下一位 AI：按已发言的 AI 数轮转 ice → data → spark
        ai_count = sum(1 for t in state.get("turns") or [] if t.get("speaker") != "student")
        cand = group_engine.CANDIDATES[ai_count % len(group_engine.CANDIDATES)]
        r2 = group_engine.ai_turn(state, cand["id"], _group_speak)
        state = r2["state"]
        ai_turns.append(r2["turn"])
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return {"state": state, "ai_turns": ai_turns, "source": r2.get("source")}


@router.post("/group/finish")
def group_finish(inp: GroupTurnIn, ctx: ToolContext = Depends(require_student)) -> dict:
    try:
        return group_engine.evaluate(inp.state or {})
    except ValueError as exc:
        raise HTTPException(422, str(exc))


# ----------------------------------------------------------------
# 9. 岗位就绪度（事前诊断：岗位技能 × 课程成绩 × 简历原文）
# ----------------------------------------------------------------
# 课程表几乎不变，但每次评估都要全表扫一遍 → 进程内缓存 10 分钟
_CATALOG_TTL = 600.0
_catalog_cache: dict[str, Any] = {"at": 0.0, "names": []}


def _catalog_names(conn) -> list[str]:
    """学校开设的全部课程名（给空白技能找补课路径用，只反查、不编造）。"""
    now = time.time()
    cached = _catalog_cache.get("names") or []
    if cached and now - float(_catalog_cache.get("at") or 0) < _CATALOG_TTL:
        return list(cached)
    with conn.cursor() as cur:
        names = [str(r["name"]) for r in _rows(
            cur, "SELECT DISTINCT `课程名称` AS name FROM `课程`", ())]
    _catalog_cache.update({"at": now, "names": names})
    return names


# 简历「实践经历」的描述列里混着 Word XML 片段（<w:p w14:paraId=…>），不清掉会污染技能匹配
_RESUME_TAG_RE = re.compile(r"<[^>]{0,500}>")


def _resume_text_of(resume: Mapping[str, Any] | None) -> str:
    """简历原文 + 结构化段落拼成一段长文本。

    只用于判断「简历里有没有提这项技能」，所以宁可多拼（技能/证书名也要拼进去），
    漏拼会把「其实写了」误判成「没写」——那正是这个功能最不能出的错。
    """
    if not resume:
        return ""
    parts = [str(resume.get("简历原文") or ""), str(resume.get("自我评价") or ""),
             str(resume.get("求职意向") or "")]
    for e in resume.get("experiences") or []:
        parts.extend(str(e.get(k) or "") for k in ("type", "name", "role", "desc", "result"))
    for e in resume.get("educations") or []:
        parts.extend(str(e.get(k) or "") for k in ("school", "major", "courses"))
    for x in resume.get("skills_certs") or []:
        parts.extend(str(x.get(k) or "") for k in ("name", "level"))
    parts.extend(str(x) for x in resume.get("skills") or [])
    raw = "\n".join(p for p in parts if p.strip())
    raw = _RESUME_TAG_RE.sub(" ", raw)
    return raw.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


def _graded_courses(cur, ctx: ToolContext) -> list[dict[str, Any]]:
    """该生全部有成绩的课程 + 同专业同年级分位（与 attribution 同口径，但要保留 None 不填 0）。"""
    student = _one(cur, "SELECT `专业`,`年级` FROM `学生` WHERE `编号`=%s AND `租户编号`=%s",
                   (ctx.student_id, ctx.tenant_id)) or {}
    major, grade = student.get("专业"), student.get("年级")
    rows = _rows(cur,
                 "SELECT c.`编号` AS course_id, c.`课程名称` AS name, c.`学分` AS credit,"
                 "       MAX(g.`分数`) AS score"
                 " FROM `成绩` g JOIN `课程` c ON c.`编号`=g.`课程编号`"
                 " WHERE g.`学生编号`=%s GROUP BY c.`编号` ORDER BY c.`学分` DESC",
                 (ctx.student_id,))
    dist: dict[int, list[float]] = defaultdict(list)
    if major and grade:
        for r in _rows(cur,
                       "SELECT g.`课程编号` AS cid, g.`分数` AS score"
                       " FROM `成绩` g JOIN `学生` st ON st.`编号`=g.`学生编号`"
                       " WHERE st.`专业`=%s AND st.`年级`=%s", (major, grade)):
            dist[int(r["cid"])].append(float(r["score"]))
    out: list[dict[str, Any]] = []
    for c in rows:
        score = float(c["score"]) if c.get("score") is not None else None
        vals = dist.get(int(c["course_id"])) or []
        out.append({
            "name": str(c["name"] or ""),
            "score": score,
            "credit": float(c["credit"] or 0),
            "percentile": peer_engine.percentile_of(score, vals) if (score is not None and vals) else None,
        })
    return out


# 岗位表 2560 行、几乎不变：首次解析后驻内存 10 分钟，排序就能全量做。
# 只捞最近 200 个不行——那 200 个恰好全是「银行客服」这类岗位，排序等于没排。
_JOBS_TTL = 600.0
_jobs_cache: dict[str, Any] = {"at": 0.0, "rows": []}


def _skill_hit(a: str, b: str) -> bool:
    """技能与技能的宽松相等（双向包含，短词不参与），只用于列表排序。"""
    x = "".join(str(a).split()).lower()
    y = "".join(str(b).split()).lower()
    if not x or not y:
        return False
    if x == y:
        return True
    return len(x) >= 2 and len(y) >= 2 and (x in y or y in x)


def _my_skill_pool(cur, ctx: ToolContext) -> set[str]:
    """学生已修课程的培养技能集合（用课程-技能图谱反推，判断岗位像不像他的方向）。"""
    names = [str(r["name"]) for r in _rows(
        cur,
        "SELECT DISTINCT c.`课程名称` AS name FROM `成绩` g"
        " JOIN `课程` c ON c.`编号`=g.`课程编号` WHERE g.`学生编号`=%s",
        (ctx.student_id,))]
    pool: set[str] = set()
    for name in names:
        for skill in skills_for_course(name):
            pool.add("".join(str(skill).split()).lower())
    return pool


def _all_jobs(conn) -> list[dict[str, Any]]:
    """全部带技能标签的岗位（10 分钟进程内缓存）。"""
    now = time.time()
    cached = _jobs_cache.get("rows") or []
    if cached and now - float(_jobs_cache.get("at") or 0) < _JOBS_TTL:
        return cached
    with conn.cursor() as cur:
        raw = _rows(cur, "SELECT `编号`,`岗位名称`,`企业`,`城市`,`行业`,`技能标签` FROM `岗位`"
                          " WHERE `技能标签` IS NOT NULL", ())
    rows: list[dict[str, Any]] = []
    for r in raw:
        skills = [str(x) for x in _json_list(r.get("技能标签"))]
        if not skills:
            continue
        rows.append({
            "job_id": int(r["编号"]),
            "title": str(r.get("岗位名称") or ""),
            "company": r.get("企业"),
            "city": r.get("城市"),
            "industry": r.get("行业"),
            "skills": skills,
        })
    _jobs_cache.update({"at": now, "rows": rows})
    return rows


@router.get("/readiness/jobs")
def readiness_jobs(q: str | None = None, limit: int = 20,
                   ctx: ToolContext = Depends(require_student)) -> dict:
    """岗位搜索：只列有技能标签的岗位（没标签就没法评估，不拿空岗位糊弄）。

    默认不按编号倒序——那样点开第一个往往是完全不对口的岗位，演示第一眼就是「一轮游」。
    改成按「岗位技能里有多少项能从你的课程里找到影子」排序，把与你专业相关的岗位浮上来。
    """
    n = max(1, min(int(limit or 20), 50))
    conn = _conn()
    try:
        with conn.cursor() as cur:
            pool = _my_skill_pool(cur, ctx)
        rows = _all_jobs(conn)
    finally:
        conn.close()

    kw = str(q or "").strip().lower()
    scored: list[tuple[float, int, int, dict[str, Any]]] = []
    for r in rows:
        if kw and kw not in str(r["title"]).lower():
            continue
        skills = r["skills"]
        hit = sum(1 for s in skills if any(_skill_hit(s, p) for p in pool))
        score = (hit / len(skills)) if skills else 0.0
        scored.append((score, hit, -int(r["job_id"]), {
            "job_id": r["job_id"],
            "title": r["title"],
            "company": r["company"],
            "city": r["city"],
            "industry": r["industry"],
            "skills": skills[:8],
            "match_hint": round(score, 2),
        }))
    scored.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
    return {"items": [it for *_w, it in scored[:n]]}


@router.post("/readiness")
def readiness(inp: ReadinessIn, ctx: ToolContext = Depends(require_student)) -> dict:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            job_id = inp.job_id
            title, industry = inp.job_title, inp.industry
            skills = [str(s) for s in (inp.skills or []) if str(s).strip()]
            if job_id:
                row = _one(cur, "SELECT `编号`,`岗位名称`,`企业`,`城市`,`行业`,`技能标签`"
                                " FROM `岗位` WHERE `编号`=%s", (job_id,))
                if not row:
                    raise HTTPException(404, "岗位不存在")
                title = str(row.get("岗位名称") or "")
                industry = row.get("行业")
                skills = _json_list(row.get("技能标签"))
            courses = _graded_courses(cur, ctx)
            rrow = _one(cur, "SELECT `编号` FROM `简历` WHERE `学生编号`=%s AND `租户编号`=%s"
                              " AND `状态`='active' ORDER BY `版本号` DESC LIMIT 1",
                        (ctx.student_id, ctx.tenant_id))
            resume = _load_resume(cur, int(rrow["编号"]), ctx.tenant_id) if rrow else None
        catalog = _catalog_names(conn)
    finally:
        conn.close()
    job_title = title or "未命名岗位"
    result = readi_engine.assess(
        {"title": job_title, "industry": industry, "skills": skills},
        courses, _resume_text_of(resume), catalog)
    return {"job_id": job_id, "job_title": job_title, **result}


# ----------------------------------------------------------------
# 10. 面试官视角（反转视角：学生排序，揭晓引擎标准分，诊断偏误）
# ----------------------------------------------------------------
_CALIB_MAX_CASES = 3

# 结构词与软性词：都不是「知识点」，拿它们当评分对象讲不出干货，
# 造出来的「实干型」答案会变成「当时背景那块最卡」这种病句。选题时按硬关键词数降权。
_STRUCT_WORDS = frozenset({"背景", "目标", "行动", "结果", "首先", "其次", "然后", "最后",
                           "第一", "第二", "第三", "一是", "二是", "三是"})
_SOFT_WORDS = frozenset({"兴趣", "项目", "学习方法", "学习能力", "实践", "源码", "团队", "挑战",
                         "流程", "衡量", "沟通", "动机", "规划", "性格", "态度", "细节", "动作"})


def _hard_keyword_count(rubric: Mapping[str, Any]) -> int:
    """rubric 里「能讲出干货」的关键词个数（既不是结构词也不是软性词）。"""
    n = 0
    for k in rubric.get("keywords") or []:
        key = "".join(str(k).split()).strip().lower()
        if key and key not in _STRUCT_WORDS and key not in _SOFT_WORDS:
            n += 1
    return n


def _calibration_pool(ctxd: Mapping[str, Any]) -> list[dict[str, Any]]:
    """选题优先级：硬关键词多 > 本人真答过且篇幅够 > 其余。

    硬关键词是硬门槛：全是「背景/负责/结果」这类结构词或「兴趣/团队」这类软性词的题，
    引擎照样能算分，但造出来的三条答案读着就不像人话，教学价值还不如不选。
    """
    ranked: list[tuple[int, int, int, dict[str, Any]]] = []
    seen: set[int] = set()
    for idx, (o, a) in enumerate(ctxd["pairs"]):
        rnd = int(o.get("round") or 0)
        if rnd in seen:
            continue
        rub = _rubric_of_q(o, ctxd["job_skills"])
        if not (rub.get("keywords") or []):
            continue
        seen.add(rnd)
        ans = (a or {}).get("学生回答")
        answered = 1 if (ans and len(str(ans).strip()) >= 60) else 0
        ranked.append((_hard_keyword_count(rub), answered, -idx,
                       {"round": rnd, "question": str(o.get("question") or ""), "rubric": rub}))
    ranked.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
    return [it for *_w, it in ranked[:_CALIB_MAX_CASES]]


@router.get("/calibration/cases")
def calibration_cases(sid: int | None = None,
                      ctx: ToolContext = Depends(require_student)) -> dict:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            if sid is None:
                row = _one(cur, "SELECT `编号` FROM `面试会话` WHERE `学生编号`=%s AND `租户编号`=%s"
                                " AND `状态`='finished' ORDER BY `编号` DESC LIMIT 1",
                           (ctx.student_id, ctx.tenant_id))
                if not row:
                    raise HTTPException(404, "还没有已完成的面试，先去答完一场再当面试官")
                sid = int(row["编号"])
            ctxd = _load_session(cur, sid, ctx)
    finally:
        conn.close()
    items = []
    for it in _calibration_pool(ctxd):
        cands = calib_engine.build_candidates(it["question"], it["rubric"])
        items.append({"round": it["round"], "question": it["question"],
                      "candidates": [{"id": c["id"], "answer": c["answer"]} for c in cands]})
    return {"session_id": sid, "job_title": ctxd["sess"].get("岗位名称"), "items": items}


@router.post("/calibration/judge")
def calibration_judge(inp: CalibrationJudgeIn,
                      ctx: ToolContext = Depends(require_student)) -> dict:
    """标准分在这里重算（不信任前端传的答案），保证与学生真实面试同一把尺子。"""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            ctxd = _load_session(cur, int(inp.session_id), ctx)
    finally:
        conn.close()
    evidence = _evidence(ctxd["resume"], ctxd["snapshot"])
    blocks: list[dict[str, Any]] = []
    for it in _calibration_pool(ctxd):
        cands = calib_engine.build_candidates(it["question"], it["rubric"])
        blocks.append({"round": it["round"], "question": it["question"],
                       "candidates": calib_engine.score_candidates(cands, it["rubric"], evidence)})
    return calib_engine.judge(list(inp.ranks or []), blocks)


# ----------------------------------------------------------------
# 11. 实验室总览：把六个工具串成一条结论 + 下一步做什么
# ----------------------------------------------------------------
# 设计说明：实验室原本是六个互不相识的分析器，学生进来先面对一排 Tab 不知道点哪个，
# 看完也不记得自己该干嘛。总览这一屏只做三件事：
#   ① 三个数（岗位就绪度 / 最近一场 / 同辈分位）给出「现在在哪」；
#   ② 一条近几场的分数走势 + 与上一场的差值，给出「在不在变好」；
#   ③ 三件按优先级排好的下一步，每件都能一键跳到对应工具。
# 所有数值来自既有引擎，本层只做取数与排序，不新增算法，保证与学生各页看到的口径一致。

_LAB_STEP_PRIORITY = ("first", "readiness", "hidden", "weak", "judge", "group", "voice")


def _target_job(jobs: Sequence[Mapping[str, Any]], pool: set[str],
                job_id: int | None) -> dict[str, Any] | None:
    """目标岗位：指定优先；否则取「课程技能命中率最高」的那个，避免默认落到银行客服岗。"""
    if job_id:
        for j in jobs:
            if int(j["job_id"]) == int(job_id):
                return dict(j)
        return None
    best: tuple[float, int, int, dict[str, Any]] | None = None
    for j in jobs:
        skills = j["skills"]
        if not skills:
            continue
        hit = sum(1 for s in skills if any(_skill_hit(s, p) for p in pool))
        key = (hit / len(skills), hit, -int(j["job_id"]), dict(j))
        if best is None or key[:3] > best[:3]:
            best = key
    return best[3] if best else None


@router.get("/summary")
def lab_summary(job_id: int | None = None, ctx: ToolContext = Depends(require_student)) -> dict:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            sessions = _rows(
                cur,
                "SELECT `编号`,`岗位名称`,`总分`,`创建时间`,`完成时间`,`状态`"
                " FROM `面试会话` WHERE `租户编号`=%s AND `学生编号`=%s ORDER BY `编号`",
                (ctx.tenant_id, ctx.student_id))
            finished = [s for s in sessions if str(s.get("状态")) == "finished"]
            latest = finished[-1] if finished else None
            ctxd = _load_session(cur, int(latest["编号"]), ctx) if latest else None
            courses = _graded_courses(cur, ctx)
            pool = _my_skill_pool(cur, ctx)
            rrow = _one(cur, "SELECT `编号` FROM `简历` WHERE `学生编号`=%s AND `租户编号`=%s"
                             " AND `状态`='active' ORDER BY `版本号` DESC LIMIT 1",
                        (ctx.student_id, ctx.tenant_id))
            resume = _load_resume(cur, int(rrow["编号"]), ctx.tenant_id) if rrow else None
            student = _one(cur, "SELECT `专业`,`年级` FROM `学生` WHERE `编号`=%s"
                                " AND `租户编号`=%s", (ctx.student_id, ctx.tenant_id)) or {}
            major, grade = student.get("专业"), student.get("年级")
            cohort, samples = 0, []
            if major and grade:
                row = _one(cur, "SELECT COUNT(*) AS n FROM `学生` WHERE `专业`=%s AND `年级`=%s",
                           (major, grade))
                cohort = int((row or {}).get("n") or 0)
                samples = [float(r["total"]) for r in _rows(
                    cur,
                    "SELECT s.`总分` AS total FROM `面试会话` s"
                    " JOIN `学生` st ON st.`编号`=s.`学生编号`"
                    " WHERE st.`专业`=%s AND st.`年级`=%s AND s.`状态`='finished'"
                    "   AND s.`总分` IS NOT NULL"
                    "   AND s.`编号`=(SELECT MAX(s2.`编号`) FROM `面试会话` s2"
                    "               WHERE s2.`学生编号`=s.`学生编号` AND s2.`状态`='finished')",
                    (major, grade))]
        catalog = _catalog_names(conn)
        jobs = _all_jobs(conn)
        target = _target_job(jobs, pool, job_id)
        resume_text = _resume_text_of(resume)
    finally:
        conn.close()

    # ---- 目标岗位就绪度（与「岗位就绪」页同一把尺子）----
    ready_block: dict[str, Any] | None = None
    if target:
        res = readi_engine.assess(
            {"title": target["title"], "industry": target.get("industry"),
             "skills": target["skills"]}, courses, resume_text, catalog)
        ready_block = {
            "job_id": target["job_id"],
            "job_title": res["job_title"],
            "company": target.get("company"),
            "readiness": res["readiness"],
            "level": res["level"],
            "level_label": res["level_label"],
            "counts": res["counts"],
            "hidden": [{"skill": h["skill"], "course": h["course"], "score": h["score"]}
                       for h in res["hidden_assets"]],
            "gap_top": (res["gaps"][0]["skill"] if res["gaps"] else None),
            "gap_fix": (res["gaps"][0]["fix"] if res["gaps"] else None),
        }

    # ---- 最近一场：四维 + 最弱一环 ----
    latest_block: dict[str, Any] | None = None
    dims: dict[str, float] = {}
    if ctxd:
        evidence = _evidence(ctxd["resume"], ctxd["snapshot"])
        scores = _score_pairs(ctxd["pairs"], evidence, ctxd["job_skills"])
        dims = _dims_of(scores)
        agg = aggregate(scores, ctxd["outline"])
        total = latest.get("总分")
        if total is None and agg:
            total = agg["total"]
        total = float(total) if total is not None else None
        weakest = None
        if dims:
            key = min(dims, key=lambda k: dims[k])
            weakest = {"key": key, "label": DIM_LABELS.get(key, key), "value": round(dims[key], 1)}
        latest_block = {
            "session_id": int(latest["编号"]),
            "job_title": latest.get("岗位名称"),
            "date": str(latest.get("完成时间") or latest.get("创建时间") or "")[:10],
            "total": total,
            "grade": _grade(total),
            "dims": {k: round(v, 1) for k, v in dims.items()},
            "weakest": weakest,
            "rounds": len(ctxd["outline"]),
        }

    # ---- 走势：只留最近 6 场有效成绩 ----
    # 没有总分的会话（历史脏数据 / 中途弃答）不进曲线：折线断在半空比不画更误导。
    trend = [{
        "session_id": int(s["编号"]),
        "date": str(s.get("完成时间") or s.get("创建时间") or "")[:10],
        "total": float(s["总分"]),
        "job_title": s.get("岗位名称"),
    } for s in finished if s.get("总分") is not None][-6:]
    vals = [t["total"] for t in trend]
    # delta = 最近一场 - 上一场（真实的「比上一场」，不是与均值比）
    delta = round(vals[-1] - vals[-2], 1) if len(vals) >= 2 else None

    # ---- 同辈分位：样本不足就老实说样本不足（不拿代理冒充实测）----
    peer_block = None
    if latest_block and latest_block["total"] is not None:
        pb = peer_engine.benchmark(latest_block["total"], dims, samples, cohort, {})
        peer_block = {"basis": pb.get("basis"), "cohort": pb.get("cohort"),
                      "sample_n": pb.get("sample_n"),
                      "percentile": (pb.get("total") or {}).get("percentile"),
                      "label": (pb.get("total") or {}).get("label"),
                      "note": pb.get("note")}

    # ---- 下一步：规则排序，前三条 ----
    steps: list[dict[str, Any]] = []
    if not finished:
        steps.append({"key": "first", "tab": "practice", "cta": "去答一场",
                      "title": "先答完一场模拟面试",
                      "why": "实验室的六个工具都要一场已完成面试才出结论，先把这个环闭上"})
    if ready_block and ready_block["readiness"] is not None and ready_block["readiness"] < 65:
        steps.append({"key": "readiness", "tab": "ready", "cta": "看差距怎么补",
                      "title": f"「{ready_block['job_title']}」就绪度 {ready_block['readiness']} 分",
                      "why": (ready_block["gap_fix"] or "岗位要求里还有几项你既没成绩背书、也没写进简历")})
    if ready_block and ready_block["hidden"]:
        n = len(ready_block["hidden"])
        steps.append({"key": "hidden", "tab": "ready", "cta": "拿可粘贴的建议句",
                      "title": f"{n} 项能力考得好但简历没写",
                      "why": "成绩单里有分数、简历里一个字没提，改一行简历就能补上证据"})
    if latest_block and latest_block["weakest"] and latest_block["weakest"]["value"] < 68:
        w = latest_block["weakest"]
        steps.append({"key": "weak", "tab": "practice", "cta": "开一场靶向面试",
                      "title": f"最近一场最弱的是「{w['label']}」{w['value']} 分",
                      "why": "下一场模拟面试会重点考察最弱的题型，并自动避开你近 3 场做过的题"})
    if finished:
        steps.append({"key": "judge", "tab": "judge", "cta": "当一次面试官",
                      "title": "换到面试官那一侧看自己",
                      "why": "你给别人的答案排完序，就知道自己是不是「爱听漂亮话」"})
        steps.append({"key": "group", "tab": "group", "cta": "开一场群面",
                      "title": "练一次无领导小组讨论",
                      "why": "校招最常见的淘汰环节，1v1 练不到"})
    steps.append({"key": "voice", "tab": "voice", "cta": "测一次表达力",
                  "title": "把一段回答拿去量一量",
                  "why": "内容不差但听着啰嗦，通常是句子太长、连接词太少"})
    steps.sort(key=lambda s: _LAB_STEP_PRIORITY.index(s["key"]))
    steps = steps[:3]

    # ---- 工具状态：锁定态要说清为什么锁 ----
    def state(key: str) -> dict[str, str]:
        if key in ("ready", "voice", "group"):
            return {"state": "ready", "note": ""}
        if finished:
            return {"state": "ready", "note": ""}
        return {"state": "locked", "note": "需要一场已完成的面试"}

    tools = [{"key": k, "label": lbl, **state(k)} for k, lbl in (
        ("panel", "圆桌评审"), ("ready", "岗位就绪"), ("passport", "能力护照"),
        ("voice", "表达力"), ("group", "群面"), ("judge", "当面试官"))]

    return {
        "version": "lab-summary-v1",
        "sessions": {"finished": len(finished), "all": len(sessions)},
        "latest": latest_block,
        "trend": trend,
        "delta": delta,
        "peer": peer_block,
        "target": ready_block,
        "next_steps": steps,
        "tools": tools,
    }

