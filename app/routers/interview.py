# app/routers/interview.py
# 职责：模拟面试官 API——简历（上传解析/问卷自填/诊断）+ 面试（开局/逐轮/报告/历史）。
# 鉴权：学生只能操作本人（ctx.student_id 由 JWT 注入，前端不可指定查谁）。
# 铁律：分数/差距由 engine.interview 计算；点评经 agents.interviewer 防虚构校验。

from __future__ import annotations

import json
import os
import re
import zipfile
from datetime import datetime
from typing import Any, Mapping, Sequence

import pymysql
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from agents import interviewer
from agents import llm as llm_client
from app.audit import audit_event
from app.auth import get_current_ctx, require_student
from app.config import get_settings
from engine import question_bank as qbank
from engine.interview import (
    INTERVIEW_ENGINE_VERSION,
    QUESTION_TYPES,
    aggregate,
    build_outline,
    core_problems,
    diagnose,
    dimension_scores,
    gap_list,
    improvement_plan,
    parse_resume,
    parse_resume as parse_resume_engine,
    rubric_from_bank,
    rubric_of,
    score_answer,
)
from engine.interview_probe import probe_plan
from engine.recommend import clean_skill_tags
from agents.tools import ToolContext

router = APIRouter(prefix="/interview", tags=["interview"])

QUESTION_LABELS = {k: v["label"] for k, v in QUESTION_TYPES.items()}

# 提纲之外允许的上下文长度（回答与证据传给模型前截断，防 prompt 爆炸）
_MAX_ANSWER = 2000

# 岗位池：national=全国岗位库（岗位表，2931 条，无租户）；tenant=租户在招池（招聘岗位表）
_JOB_POOLS = ("national", "tenant")
# 追问预算：一场面试最多追加几道追问（不含在开局的 max_rounds 里）
_PROBE_MAX = max(0, int(os.getenv("INTERVIEW_PROBE_MAX", "2")))


def _probe_enabled() -> bool:
    """追问总开关（与 engine.interview_probe.enabled 同一环境变量）。"""
    return str(os.getenv("INTERVIEW_PROBE", "1")).strip().lower() not in ("0", "false", "off", "no")


def _conn() -> pymysql.connections.Connection:
    s = get_settings()
    return pymysql.connect(host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
                           password=s.mysql_password, database=s.mysql_db,
                           charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)


def _one(cur, sql: str, params: tuple) -> dict[str, Any] | None:
    cur.execute(sql, params)
    row = cur.fetchone()
    return dict(row) if row else None


# ----------------------------------------------------------------
# 数据契约：MySQL JSON 列 / 评分证据（答题与收卷必须同口径）
# ----------------------------------------------------------------
def _json_list(raw: Any) -> list[str]:
    """把 MySQL JSON 列统一解析成字符串列表。

    pymysql 对 JSON 列（FIELD_TYPE 245）没有转换器，取出来是 str；
    直接迭代会把 '["数据结构"]' 拆成单字符（曾导致专业题问「你学过[」）。
    空值 / 坏 JSON 一律返回 []，不编造。
    """
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            return []
    if isinstance(raw, (list, tuple)):
        return [str(x) for x in raw if str(x).strip()]
    return []


def _evidence(resume: Mapping[str, Any], job_snapshot: Mapping[str, Any] | None) -> list[str]:
    """防虚构 / 评分共用的证据集：简历原文（或自评）+ 岗位技能 + 经历描述。

    逐题答题与收卷报告必须走同一个函数，否则 evidence_score 口径不同，
    报告逐题分会与答题时返回、落库的 `面试问答.评分` 对不上。
    """
    evidence = [str(resume.get("简历原文") or resume.get("self") or resume.get("自我评价") or "")]
    evidence += [str(t) for t in (job_snapshot or {}).get("skill_tags") or []]
    evidence += [str(e.get("desc") or "") for e in resume.get("experiences") or [] if e.get("desc")]
    return [e for e in evidence if e.strip()]


def _rubric_of_q(question: Mapping[str, Any], job_skills: Sequence[str]) -> dict[str, Any]:
    """取某道题的评分要点：优先用提纲里已存的（题库题带自己的考点）。

    build_outline 现在会把题库考点写进 outline[i]["rubric"]，如果这里再用
    `rubric_of(q["type"], job_skills)` 重算，题库考点就被通用关键词覆盖掉了，
    专业题会出现「答对了得分低、答偏了得分高」。老会话的提纲同样带 rubric 字段，
    因此这里直接取用是向后兼容的；取不到才回退重算。
    """
    stored = question.get("rubric")
    if isinstance(stored, Mapping) and stored.get("keywords") is not None:
        return dict(stored)
    return rubric_of(str(question.get("type") or "major"), job_skills)


# ----------------------------------------------------------------
# 简历：载入 / 保存
# ----------------------------------------------------------------
def _load_resume(cur, resume_id: int, tenant_id: int) -> dict[str, Any] | None:
    r = _one(cur, "SELECT * FROM `简历` WHERE `编号`=%s AND `租户编号`=%s", (resume_id, tenant_id))
    if not r:
        return None
    rid = r["编号"]
    # 中文列名 + AS 英文别名：库里是真中文，引擎侧读英文键（与 parse_resume 输出对齐）
    r["educations"] = _rows(
        cur,
        "SELECT `学校` AS school, `专业` AS major, `学历` AS degree, "
        "       `起止时间` AS dates, `成绩排名` AS `rank`, `主修课程` AS courses "
        "FROM `简历教育经历` WHERE `简历编号`=%s ORDER BY `排序号`", (rid,))
    r["skills_certs"] = _rows(
        cur,
        "SELECT `类型` AS type, `名称` AS name, `等级分数` AS level, "
        "       `获得时间` AS date FROM `简历技能证书` "
        "WHERE `简历编号`=%s ORDER BY `排序号`", (rid,))
    r["experiences"] = _rows(
        cur,
        "SELECT `类型` AS type, `名称` AS name, `角色` AS role, "
        "       `起止时间` AS dates, `描述` AS `desc`, `成果` AS result "
        "FROM `简历实践经历` WHERE `简历编号`=%s ORDER BY `排序号`", (rid,))
    # 引擎口径的三段结构（与 engine.interview.parse_resume 输出对齐）
    r["skills"] = [str(x["name"]) for x in r["skills_certs"] if x["type"] == "skill"]
    r["certs"] = [{"name": str(x["name"]), "level": x["level"]}
                  for x in r["skills_certs"] if x["type"] != "skill"]
    r["courses"] = []
    for e in r["educations"]:
        r["courses"] += _json_list(e.get("courses"))
    return r


def _rows(cur, sql: str, params: tuple) -> list[dict[str, Any]]:
    cur.execute(sql, params)
    return [dict(r) for r in cur.fetchall()]


class ResumeIn(BaseModel):
    """问卷自填路径：结构化直接入库（数据接口拿不到时的降级，计划书 2.3）。"""
    self_eval: str | None = None
    intent: str | None = None
    educations: list[dict[str, Any]] = []
    skills: list[dict[str, Any]] = []      # [{type,name,level,date}]
    experiences: list[dict[str, Any]] = [] # [{type,name,role,dates,desc,result}]
    raw_text: str | None = None


class ParseIn(BaseModel):
    text: str


class ResumeRewriteIn(BaseModel):
    text: str
    target_job: str | None = None


def _resume_number_tokens(text: str) -> list[str]:
    """提取原简历中的数值证据；AI 改写不得遗漏、增加或改动这些数字。"""
    return re.findall(r"\d+(?:\.\d+)?%?", text or "")


def _rewrite_preserves_numbers(source: str, rewritten: str) -> bool:
    """用多重集合比对数字，避免模型改数量、年份、百分比或重复次数。"""
    from collections import Counter

    return Counter(_resume_number_tokens(source)) == Counter(_resume_number_tokens(rewritten))


@router.post("/resume/rewrite")
def resume_rewrite(inp: ResumeRewriteIn,
                   ctx: ToolContext = Depends(require_student)) -> dict[str, Any]:
    """基于学生主动提交的简历文本做表达润色；不读他人数据、不增删数值事实。"""
    source = (inp.text or "").strip()
    if len(source) < 30:
        raise HTTPException(422, "请至少提供 30 个字符的简历内容后再进行 AI 改写")
    if len(source) > 12000:
        raise HTTPException(413, "简历内容过长，请控制在 12000 个字符以内")
    target = (inp.target_job or "").strip()[:120]
    system = (
        "你是中文简历编辑助手。只润色用户提供的事实，不得虚构姓名、学校、技能、职责、成果、证书或经历；"
        "不得新增、删除、换算或改写任何数字、年份、日期、百分比、数量或度量单位；"
        "不得把参与改成负责/主导，不得把不确定描述升级成确定结论。"
        "可以改善结构、语法、专业表达和岗位关键词自然度；信息不足处用【建议补充：具体信息】标出。"
        "只返回可直接使用的简历正文，不要附带解释或 Markdown 代码围栏。"
    )
    user = f"目标岗位：{target or '未指定，采用通用校招表达'}\n请改写以下简历，并完整保留所有事实与数字：\n\n{source}"
    rewritten = llm_client.generate_reply("student", system_prompt=system,
                                          user_prompt=user, tag="resume.rewrite")
    if not rewritten:
        raise HTTPException(503, "AI 简历服务暂不可用，请稍后重试；原文不会被覆盖")
    result = str(rewritten).strip().removeprefix("```text").removeprefix("```").removesuffix("```").strip()
    if not result or not _rewrite_preserves_numbers(source, result):
        audit_event(tenant_id=ctx.tenant_id, actor_type="student", actor_id=ctx.student_id,
                    action="resume.rewrite.rejected", detail={"reason": "numeric_evidence_mismatch"})
        raise HTTPException(502, "AI 改写未通过数字事实校验，原文保持不变，请重试")
    return {"rewritten_text": result, "target_job": target or None,
            "numbers_verified": True, "saved": False}


@router.post("/resume/parse")
def resume_parse(inp: ParseIn, ctx: ToolContext = Depends(require_student)) -> dict[str, Any]:
    """粘贴文本 → 规则解析为三段结构（不入库，前端确认后再保存）。"""
    parsed = parse_resume_engine(inp.text or "")
    return {"engine_version": parsed.get("raw_text") and "resume-parse-v1",
            "parsed": {k: v for k, v in parsed.items() if k != "raw_text"},
            "raw_len": len(parsed.get("raw_text") or "")}


@router.post("/resume/upload")
async def resume_upload(file: UploadFile = File(...),
                        ctx: ToolContext = Depends(require_student)) -> dict[str, Any]:
    """上传 .docx / .txt → 抽全文 → 规则解析（不入库）。"""
    name = file.filename or ""
    blob = await file.read()
    if name.lower().endswith(".docx"):
        try:
            import io
            with zipfile.ZipFile(io.BytesIO(blob)) as z:
                xml = z.read("word/document.xml").decode("utf-8", "ignore")
            texts = re.findall(r"<w:t[^>]*>(.*?)</w:t>", xml)
            text = "\n".join(t for t in (x.strip() for x in texts) if t)
        except Exception as exc:
            raise HTTPException(422, f"docx 解析失败：{exc}")
    elif name.lower().endswith(".txt"):
        text = blob.decode("utf-8", "ignore")
    else:
        raise HTTPException(415, "仅支持 .docx / .txt；其他格式请用「粘贴文本」或问卷自填")
    if len(text.strip()) < 30:
        raise HTTPException(422, "文档内容过短，解析不出有效简历")
    parsed = parse_resume_engine(text)
    return {"parsed": {k: v for k, v in parsed.items() if k != "raw_text"},
            "filename": name[:200], "raw_len": len(text)}


def _next_version(cur, tenant_id: int, student_id: int) -> int:
    cur.execute("SELECT COALESCE(MAX(`版本号`),0)+1 AS v FROM `简历` WHERE `租户编号`=%s AND `学生编号`=%s",
                (tenant_id, student_id))
    return int(cur.fetchone()["v"])


def _save_resume(cur, ctx: ToolContext, source: str, parsed: dict[str, Any],
                 filename: str | None) -> int:
    """写简历主表 + 三张经历表；旧 active 降级 retained（版本只增不删）。"""
    cur.execute("UPDATE `简历` SET `状态`='retained' WHERE `租户编号`=%s AND `学生编号`=%s AND `状态`='active'",
                (ctx.tenant_id, ctx.student_id))
    ver = _next_version(cur, ctx.tenant_id, ctx.student_id)
    cur.execute(
        "INSERT INTO `简历`(`租户编号`,`学生编号`,`版本号`,`来源`,`来源文件名`,`简历原文`,`自我评价`,`意向方向`,`状态`)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'active')",
        (ctx.tenant_id, ctx.student_id, ver, source, filename,
         (parsed.get("raw_text") or None), (parsed.get("self") or None), (parsed.get("intent") or None)))
    rid = cur.lastrowid
    for i, e in enumerate(parsed.get("educations") or []):
        cur.execute("INSERT INTO `简历教育经历`(`简历编号`,`学校`,`专业`,`学历`,`起止时间`,`成绩排名`,`主修课程`,`排序号`)"
                    " VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (rid, str(e.get("school") or e.get("学校") or "未填")[:120],
                     e.get("major") or e.get("专业"), e.get("degree") or e.get("学历"),
                     e.get("dates"), e.get("rank"),
                     json.dumps(e.get("courses") or [], ensure_ascii=False), i))
    for i, s in enumerate(parsed.get("skills_certs") or parsed.get("skills") or []):
        if isinstance(s, str):
            s = {"type": "skill", "name": s}
        stype = str(s.get("type") or "skill")
        stype = stype if stype in ("skill", "cert", "language") else "skill"
        cur.execute("INSERT INTO `简历技能证书`(`简历编号`,`类型`,`名称`,`等级分数`,`获得时间`,`排序号`)"
                    " VALUES (%s,%s,%s,%s,%s,%s)",
                    (rid, stype, str(s.get("name") or "")[:120], s.get("level"), s.get("date"), i))
    for i, e in enumerate(parsed.get("experiences") or []):
        etype = str(e.get("type") or "project")
        etype = etype if etype in ("intern", "project", "contest", "activity") else "project"
        cur.execute("INSERT INTO `简历实践经历`(`简历编号`,`类型`,`名称`,`角色`,`起止时间`,`描述`,`成果`,`排序号`)"
                    " VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (rid, etype, str(e.get("name") or "")[:200], e.get("role"), e.get("dates"),
                     (e.get("desc") or e.get("description") or None), e.get("result"), i))
    return rid


@router.post("/resume")
def resume_save(inp: ResumeIn, ctx: ToolContext = Depends(require_student)) -> dict[str, Any]:
    parsed = {"self": inp.self_eval, "intent": inp.intent, "raw_text": inp.raw_text,
              "educations": inp.educations, "skills": inp.skills, "experiences": inp.experiences}
    conn = _conn()
    try:
        with conn.cursor() as cur:
            rid = _save_resume(cur, ctx, "questionnaire", parsed, None)
        conn.commit()
        audit_event(tenant_id=ctx.tenant_id, actor_type="student",
                    actor_id=ctx.student_id, action="resume.save",
                    target=str(rid), detail={"source": "questionnaire"})
        return {"resume_id": rid}
    finally:
        conn.close()


@router.get("/resume/me")
def resume_me(ctx: ToolContext = Depends(require_student)) -> dict[str, Any]:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT `编号` FROM `简历` WHERE `租户编号`=%s AND `学生编号`=%s AND `状态`='active'"
                        " ORDER BY `版本号` DESC LIMIT 1", (ctx.tenant_id, ctx.student_id))
            row = cur.fetchone()
            if not row:
                return {"resume": None}
            return {"resume": _load_resume(cur, int(row["编号"]), ctx.tenant_id)}
    finally:
        conn.close()


# ----------------------------------------------------------------
# 简历诊断（独立入口）与岗位候选
# ----------------------------------------------------------------
def _load_job(cur, job_id: int, pool: str | None = None) -> dict[str, Any] | None:
    """按池取岗位。

    - national：全国岗位库（`岗位` 表，2931 条，无租户维度，字段最全）
    - tenant：租户在招池（`招聘岗位` 表，含投递链接与状态）
    - pool=None：先全国后租户（与岗位选择器的默认池一致）

    两张表的 `编号` 各自独立、会撞号，所以池必须显式传；这里不做「猜池」。
    """
    order = [pool] if pool in _JOB_POOLS else ["national", "tenant"]
    for p in order:
        if p == "national":
            j = _one(cur, "SELECT `编号` AS id,`岗位名称` AS title,`企业` AS company,"
                          "`行业` AS industry,`城市` AS city,`学历` AS education,"
                          "`技能标签` AS skill_tags,`岗位描述` AS description,"
                          "`最低薪资` AS salary_min,`最高薪资` AS salary_max"
                          " FROM `岗位` WHERE `编号`=%s", (job_id,))
        else:
            j = _one(cur, "SELECT `编号` AS id,`岗位名称` AS title,`招聘单位` AS company,"
                          "`行业` AS industry,`城市` AS city,`学历要求` AS education,"
                          "`技能标签` AS skill_tags,`职位描述` AS description,"
                          "`最低薪资` AS salary_min,`最高薪资` AS salary_max,`投递链接` AS url"
                          " FROM `招聘岗位` WHERE `编号`=%s", (job_id,))
        if j:
            j["skill_tags"] = clean_skill_tags(j.get("skill_tags"))
            j["pool"] = p
            return j
    return None


@router.get("/jobs")
def job_candidates(keyword: str | None = None, city: str | None = None,
                   industry: str | None = None, pool: str = "national",
                   limit: int = 50, offset: int = 0,
                   ctx: ToolContext = Depends(require_student)) -> dict[str, Any]:
    """可练习的岗位池（默认全国 2931 条），支持关键词 / 城市 / 行业过滤与分页。

    返回真实 total（过滤后的总数），前端据此显示「共 N 个岗位」并做远程搜索。
    排序：有关键词时岗位名称命中优先；其余按编号升序（分页稳定、无随机）。
    """
    pool = pool if pool in _JOB_POOLS else "national"
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))

    if pool == "national":
        table, title_col, comp_col, edu_col, desc_col = "岗位", "岗位名称", "企业", "学历", "岗位描述"
        base = " FROM `岗位` WHERE 1=1"
        select = ("SELECT `编号` AS id,`岗位名称` AS title,`企业` AS company,`行业` AS industry,"
                  "`城市` AS city,`学历` AS education,`技能标签` AS skill_tags,"
                  "`最低薪资` AS salary_min,`最高薪资` AS salary_max" + base)
    else:
        base = " FROM `招聘岗位` WHERE `租户编号`=%s AND `状态`<>'closed'"
        select = ("SELECT `编号` AS id,`岗位名称` AS title,`招聘单位` AS company,`行业` AS industry,"
                  "`城市` AS city,`学历要求` AS education,`技能标签` AS skill_tags,"
                  "`最低薪资` AS salary_min,`最高薪资` AS salary_max" + base)

    where, params = "", ([] if pool == "national" else [ctx.tenant_id])
    if keyword:
        kw = f"%{keyword}%"
        if pool == "national":
            where += " AND (`岗位名称` LIKE %s OR `技能标签` LIKE %s OR `企业` LIKE %s" \
                     " OR `行业` LIKE %s OR `城市` LIKE %s)"
            params += [kw] * 5
        else:
            where += " AND (`岗位名称` LIKE %s OR `技能标签` LIKE %s)"
            params += [kw, kw]
    if city:
        where += " AND `城市` LIKE %s"
        params.append(f"%{city}%")
    if industry:
        where += " AND `行业` LIKE %s"
        params.append(f"%{industry}%")

    order = " ORDER BY `编号` ASC"
    params_count = list(params)       # COUNT 只要过滤参数，不带 ORDER BY 的那个
    if keyword and pool == "national":
        order = " ORDER BY (`岗位名称` LIKE %s) DESC, `编号` ASC"
        params = list(params) + [f"%{keyword}%"]

    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c" + base + where, tuple(params_count))
            total = int((cur.fetchone() or {}).get("c") or 0)
            rows = _rows(cur, select + where + order + " LIMIT %s OFFSET %s",
                         tuple(params) + (limit, offset))
        for r in rows:
            r["skill_tags"] = clean_skill_tags(r.get("skill_tags"))
            r["pool"] = pool
        return {"pool": pool, "total": total, "offset": offset, "limit": limit, "items": rows}
    finally:
        conn.close()


@router.get("/jobs/facets")
def job_facets(ctx: ToolContext = Depends(require_student)) -> dict[str, Any]:
    """岗位选择器的筛选项：行业与城市分布（按岗位数降序）。"""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM `岗位`")
            total = int((cur.fetchone() or {}).get("c") or 0)
            cur.execute("SELECT `行业` AS name, COUNT(*) AS cnt FROM `岗位`"
                        " WHERE `行业` IS NOT NULL AND `行业`<>''"
                        " GROUP BY `行业` ORDER BY cnt DESC, name ASC")
            industries = [{"name": r["name"], "count": int(r["cnt"])} for r in cur.fetchall()]
            cur.execute("SELECT `城市` AS name, COUNT(*) AS cnt FROM `岗位`"
                        " WHERE `城市` IS NOT NULL AND `城市`<>''"
                        " GROUP BY `城市` ORDER BY cnt DESC, name ASC")
            cities = [{"name": r["name"], "count": int(r["cnt"])} for r in cur.fetchall()]
        return {"total": total, "industries": industries, "cities": cities}
    finally:
        conn.close()


@router.get("/resume/diagnosis")
def resume_diagnosis(job_id: int | None = None, job_pool: str | None = None,
                     ctx: ToolContext = Depends(require_student)) -> dict[str, Any]:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT `编号` FROM `简历` WHERE `租户编号`=%s AND `学生编号`=%s AND `状态`='active'"
                        " ORDER BY `版本号` DESC LIMIT 1", (ctx.tenant_id, ctx.student_id))
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "还没有简历：请先上传或问卷自填")
            resume = _load_resume(cur, int(row["编号"]), ctx.tenant_id)
            job = _load_job(cur, job_id, job_pool) if job_id else None
        result = diagnose(resume, job)
        audit_event(tenant_id=ctx.tenant_id, actor_type="student",
                    actor_id=ctx.student_id, action="resume.diagnosis",
                    target=str(row["编号"]), detail={"job_id": job_id, "issues": len(result["issues"])})
        return result
    finally:
        conn.close()


# ----------------------------------------------------------------
# 面试主链路
# ----------------------------------------------------------------
class StartIn(BaseModel):
    job_id: int | None = None
    job_pool: str | None = None      # national（默认，全国池）/ tenant（租户在招池）
    resume_id: int | None = None
    max_rounds: int = 6


@router.post("/start")
def interview_start(inp: StartIn, ctx: ToolContext = Depends(require_student)) -> dict[str, Any]:
    max_rounds = max(3, min(int(inp.max_rounds or 6), 8))
    conn = _conn()
    try:
        with conn.cursor() as cur:
            if inp.resume_id:
                resume = _load_resume(cur, int(inp.resume_id), ctx.tenant_id)
                if not resume or int(resume["学生编号"]) != int(ctx.student_id or 0):
                    raise HTTPException(403, "简历不存在或不属于本人")
            else:
                cur.execute("SELECT `编号` FROM `简历` WHERE `租户编号`=%s AND `学生编号`=%s AND `状态`='active'"
                            " ORDER BY `版本号` DESC LIMIT 1", (ctx.tenant_id, ctx.student_id))
                row = cur.fetchone()
                if not row:
                    raise HTTPException(404, "还没有简历：请先上传或问卷自填（简历是出题依据）")
                resume = _load_resume(cur, int(row["编号"]), ctx.tenant_id)
            job = _load_job(cur, int(inp.job_id), inp.job_pool) if inp.job_id else None
            if inp.job_id and not job:
                raise HTTPException(404, f"岗位不存在（池 {inp.job_pool or 'national'}）")
            outline = build_outline(job, resume, max_rounds=max_rounds)
            if not outline:
                raise HTTPException(422, "简历信息不足以出题（连基本经历都没有），请先补全简历")
            # 行业要进快照：追问/题库检索都靠 industry 归族，缺了就只能落 general
            job_snapshot = {"title": job["title"], "skill_tags": job["skill_tags"],
                            "education": job.get("education"), "industry": job.get("industry"),
                            "city": job.get("city"), "pool": job.get("pool")} if job else None
            cur.execute(
                "INSERT INTO `面试会话`(`租户编号`,`学生编号`,`简历编号`,`岗位编号`,`岗位名称`,`岗位要求快照`,"
                "`状态`,`提纲`,`当前轮次`,`最大轮次`,`引擎版本`) VALUES (%s,%s,%s,%s,%s,%s,'ongoing',%s,0,%s,%s)",
                (ctx.tenant_id, ctx.student_id, resume["编号"], inp.job_id,
                 (job or {}).get("title"), json.dumps(job_snapshot, ensure_ascii=False) if job_snapshot else None,
                 json.dumps(outline, ensure_ascii=False), len(outline), INTERVIEW_ENGINE_VERSION))
            sid = cur.lastrowid
        conn.commit()
        audit_event(tenant_id=ctx.tenant_id, actor_type="student",
                    actor_id=ctx.student_id, action="interview.start",
                    target=str(sid), detail={"job_id": inp.job_id, "rounds": len(outline)})
        q = outline[0]
        return {"session_id": sid, "total_rounds": len(outline), "round": 1,
                "question_type": q["type"], "question_label": _rubric_of_q(q, job_snapshot["skill_tags"] if job_snapshot else [])["label"],
                "question": q["question"], "source": q.get("source")}
    finally:
        conn.close()


class AnswerIn(BaseModel):
    text: str | None = None   # None=跳过本题


# ----------------------------------------------------------------
# 追问（浅答/漏考点时从同族题库补一道更深的题，插在本题之后）
# ----------------------------------------------------------------
def _used_bank_ids(outline: Sequence[Mapping[str, Any]]) -> list[str]:
    """本场已经出过的题库题号（含追问）：追问不得重复出题。"""
    used: list[str] = []
    for o in outline:
        src = o.get("source") or {}
        if src.get("kind") == "bank" and src.get("id"):
            used.append(str(src["id"]))
        probe = o.get("probe") or {}
        if probe.get("bank_id"):
            used.append(str(probe["bank_id"]))
    return list(dict.fromkeys(used))


def _probe_count(outline: Sequence[Mapping[str, Any]]) -> int:
    return sum(1 for o in outline if o.get("probe_of"))


def _build_probe_entry(plan: Mapping[str, Any], answered_round: int) -> dict[str, Any] | None:
    """把追问计划落成提纲里的一轮。

    取不到题库考点就放弃追问 —— 宁可少问一句，也不拿空 rubric 硬评。
    追问条目的 rubric 来自题库，与模板题的评分口径（结构/深度/证据）保持一致。
    """
    item = qbank.get_item(str(plan.get("bank_id") or ""))
    if not item:
        return None
    qtype = str(plan.get("qtype") or item.get("qtype") or "project")
    return {
        "round": answered_round + 1,
        "type": qtype,
        "question": plan["question"],
        "question_raw": plan.get("question_raw"),
        "rubric": rubric_from_bank({**item, "qtype": qtype}),
        "probe_of": answered_round,
        "probe_version": plan.get("engine_version"),
        "probe": {"bank_id": plan.get("bank_id"), "trigger": "shallow_or_missed_keywords"},
        "source": {"kind": "bank", "id": plan.get("bank_id"),
                   "name": plan.get("source_name"), "url": plan.get("source_url"),
                   "pool": "probe", "family": plan.get("family"),
                   "family_label": qbank.family_label(str(plan.get("family") or "")),
                   "matched_by": [f"第 {answered_round} 题追问"]},
    }


def _job_for_outline(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """快照 → 出题/追问用的岗位字典（行业是题库归族的关键，不能丢）。"""
    return {"title": snapshot.get("title"), "industry": snapshot.get("industry"),
            "skill_tags": snapshot.get("skill_tags") or [],
            "education": snapshot.get("education")}


def _insert_probe(outline: list[dict[str, Any]], index: int,
                  entry: Mapping[str, Any]) -> list[dict[str, Any]]:
    """把追问插到第 index 题之后，并把全表轮次重排成 1..N 连续整数。

    轮次必须是整数且连续：收卷时 `zip(answers, outline)` 靠顺序对齐，
    一旦出现 x.y 小数轮次或空洞，逐题得分就会串行错位。
    """
    outline.insert(index + 1, dict(entry))
    for i, o in enumerate(outline, start=1):
        o["round"] = i
    return outline


@router.post("/{sid}/answer")
def interview_answer(sid: int, inp: AnswerIn,
                     ctx: ToolContext = Depends(require_student)) -> dict[str, Any]:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            sess = _one(cur, "SELECT * FROM `面试会话` WHERE `编号`=%s AND `租户编号`=%s", (sid, ctx.tenant_id))
            if not sess or int(sess["学生编号"]) != int(ctx.student_id or 0):
                raise HTTPException(404, "会话不存在或不属于本人")
            if sess["状态"] != "ongoing":
                raise HTTPException(409, "该场面试已结束")
            outline = json.loads(sess["提纲"] or "[]")
            rnd = int(sess["当前轮次"])
            if rnd >= len(outline):
                raise HTTPException(409, "已经是最后一题，请查看报告")
            q = outline[rnd]
            answer = (inp.text or "").strip()[:_MAX_ANSWER] or None

            # 证据与收卷共用同一口径（防虚构比对源 + 评分 evidence_score）
            job_snapshot = json.loads(sess["岗位要求快照"] or "null") or {}
            resume = _load_resume(cur, int(sess["简历编号"]), ctx.tenant_id)
            evidence = _evidence(resume, job_snapshot)

            rubric = _rubric_of_q(q, job_snapshot.get("skill_tags") or [])
            item = score_answer(answer, rubric, evidence)
            turn = interviewer.run_turn(q["question"], q["type"], answer, item, evidence)

            cur.execute(
                "INSERT INTO `面试问答`(`会话编号`,`轮次`,`问题类型`,`问题`,`学生回答`,`点评`,`评分`,`引用原文`,`点评版本`)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (sid, rnd + 1, q["type"], q["question"], answer, turn["comment"],
                 item["score"] if item else None,
                 json.dumps([f"「{x}」" for x in (item.get("keyword_hits") or [])], ensure_ascii=False) if item else None,
                 turn["comment_version"]))
            nxt = rnd + 1

            # 追问：答得浅/漏考点 → 从同族题库补一道更深的题插到本轮之后。
            # 追问是「额外一轮」而不是 x.y 小数轮次：轮次保持整型，
            # 提纲重排后与质问答的 `轮次` 一一对应，收卷 zip 不会错位。
            probed = False
            if _probe_enabled() and _probe_count(outline) < _PROBE_MAX:
                plan = probe_plan(_job_for_outline(job_snapshot), q["type"], item, answer,
                                  used_ids=_used_bank_ids(outline))
                entry = _build_probe_entry(plan, int(q.get("round") or rnd + 1)) if plan else None
                if entry:
                    _insert_probe(outline, rnd, entry)
                    probed = True

            if probed:
                cur.execute("UPDATE `面试会话` SET `当前轮次`=%s,`最大轮次`=%s,`提纲`=%s WHERE `编号`=%s",
                            (nxt, len(outline), json.dumps(outline, ensure_ascii=False), sid))
            else:
                cur.execute("UPDATE `面试会话` SET `当前轮次`=%s WHERE `编号`=%s", (nxt, sid))
        conn.commit()
    finally:
        conn.close()

    # 还有下一题 → 返回问题；否则收卷出报告
    if nxt < len(outline):
        nq = outline[nxt]
        return {"round_done": rnd + 1, "score": item["score"] if item else None,
                "comment": turn["comment"], "comment_version": turn["comment_version"],
                "total_rounds": len(outline), "probed": probed,
                "next": {"round": nxt + 1, "question": nq["question"], "question_type": nq["type"],
                         "source": nq.get("source"), "is_probe": bool(nq.get("probe_of")),
                         "probe_of": nq.get("probe_of")}}
    return _finish(sid, ctx)


def _finish(sid: int, ctx: ToolContext) -> dict[str, Any]:
    """收卷：引擎汇总总分/差距 → 结构化评估 + 报告落库。"""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            sess = _one(cur, "SELECT * FROM `面试会话` WHERE `编号`=%s", (sid,))
            outline = json.loads(sess["提纲"] or "[]")
            answers = _rows(cur, "SELECT * FROM `面试问答` WHERE `会话编号`=%s ORDER BY `轮次`", (sid,))
            # 注意：简历必须在游标存活期内加载（pymysql 的 with 退出即关游标）
            resume = _load_resume(cur, int(sess["简历编号"]), ctx.tenant_id)
        job_snapshot = json.loads(sess["岗位要求快照"] or "null") or {}
        job = {"title": job_snapshot.get("title"), "skill_tags": job_snapshot.get("skill_tags") or [],
               "education": job_snapshot.get("education")}
        # 与答题时同一证据集，否则报告分会和逐题落库分不一致
        evidence = _evidence(resume, job_snapshot)
        evaluation = _build_evaluation(outline, answers, evidence, job, resume)
        report = evaluation["report"]
        gaps = evaluation["gaps"]

        with conn.cursor() as cur:
            cur.execute("UPDATE `面试会话` SET `状态`='finished',`总分`=%s,`报告`=%s,`差距清单`=%s,`完成时间`=%s"
                        " WHERE `编号`=%s",
                        (evaluation["total"], report, json.dumps(gaps, ensure_ascii=False),
                         datetime.now(), sid))
        conn.commit()
        audit_event(tenant_id=ctx.tenant_id, actor_type="student",
                    actor_id=ctx.student_id, action="interview.finish",
                    target=str(sid), detail={"total": evaluation["total"], "gaps": len(gaps)})
    finally:
        conn.close()
    return {"round_done": len(outline),
            "score": evaluation["per_question"][-1]["score"] if evaluation["per_question"] else None,
            "finished": True, "total": evaluation["total"], "probes": evaluation["probes"],
            "report": report, "gaps": gaps,
            "evaluation": evaluation,
            "items": evaluation["per_question"],
            "sources": [_source_row(o) for o in outline]}


def _build_evaluation(outline: list[dict[str, Any]], answers: list[dict[str, Any]],
                      evidence: list[str], job: Mapping[str, Any],
                      resume: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """结构化评估（interview-v2，纯引擎确定性）：逐题分 + 维度分 + 核心问题 + 改进计划。

    逐题点评直接复用答题时落库的 `面试问答.点评`（当时已过防虚构校验），收卷不重跑模型；
    评分用同一引擎重算——确定性函数，与落库分必然一致。
    """
    job_skills = job.get("skill_tags") or []
    scores = [score_answer(a["学生回答"], _rubric_of_q(o, job_skills), evidence)
              for a, o in zip(answers, outline)]
    total = aggregate(scores, outline)
    gaps = gap_list(resume or {"skills": [], "certs": [], "experiences": [], "educations": []},
                    job, scores, outline)
    problems = core_problems(scores, outline)
    plan = improvement_plan(gaps, problems)

    per_question: list[dict[str, Any]] = []
    for o, a, s in zip(outline, answers, scores):
        label = _rubric_of_q(o, job_skills)["label"]
        is_probe = bool(o.get("probe_of"))
        comment = s and str(a.get("点评") or "") or None
        per_question.append({
            "round": o["round"],
            "label": f"{label}（追问）" if is_probe else label,
            "type": str(o.get("type")),
            "question": str(o.get("question") or ""),
            "is_probe": is_probe,
            "probe_of": o.get("probe_of"),
            "score": s["score"] if s else None,
            "answered": s is not None,
            "comment": comment or ("本题未作答" if s is None else ""),
            "comment_version": str(a.get("点评版本") or "") if s else None,
            "keyword_hits": list(s.get("keyword_hits") or []) if s else [],
            "keyword_missed": list(s.get("keyword_missed") or []) if s else [],
            "struct_score": s.get("struct_score") if s else None,
            "evidence_score": s.get("evidence_score") if s else None,
            "answer": (a["学生回答"] or "")[:500] if s else "",
        })
    strengths = [q["label"] for q, s in zip(per_question, scores)
                 if s and float(s["score"]) >= 75]
    return {
        "engine_version": INTERVIEW_ENGINE_VERSION,
        "total": total["total"] if total else None,
        "answered": total["answered"] if total else 0,
        "skipped": total["skipped"] if total else len(outline),
        "probes": _probe_count(outline),
        "dimensions": dimension_scores(scores, outline),
        "per_question": per_question,
        "strengths": strengths,
        "core_problems": problems,
        "improvement_plan": plan,
        "gaps": gaps,
        "report": interviewer.render_report({
            "total": total["total"] if total else None,
            "answered": total["answered"] if total else 0,
            "skipped": total["skipped"] if total else len(outline),
            "probes": _probe_count(outline),
            "items": per_question, "strengths": strengths,
            "core_problems": problems, "improvement_plan": plan, "gaps": gaps,
        }),
    }


@router.get("/{sid}/evaluation")
def interview_evaluation(sid: int, ctx: ToolContext = Depends(require_student)) -> dict[str, Any]:
    """历史场次的结构化评估报告：与收卷同一引擎重算（确定性，结果一致）。"""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            sess = _one(cur, "SELECT * FROM `面试会话` WHERE `编号`=%s AND `租户编号`=%s",
                        (sid, ctx.tenant_id))
            if not sess or int(sess["学生编号"]) != int(ctx.student_id or 0):
                raise HTTPException(404, "会话不存在或不属于本人")
            if sess["状态"] != "finished":
                raise HTTPException(409, "该场面试还没答完，没有评估报告")
            outline = json.loads(sess["提纲"] or "[]")
            answers = _rows(cur, "SELECT * FROM `面试问答` WHERE `会话编号`=%s ORDER BY `轮次`", (sid,))
            resume = _load_resume(cur, int(sess["简历编号"]), ctx.tenant_id)
        job_snapshot = json.loads(sess["岗位要求快照"] or "null") or {}
        job = {"title": job_snapshot.get("title"), "skill_tags": job_snapshot.get("skill_tags") or [],
               "education": job_snapshot.get("education")}
        evidence = _evidence(resume, job_snapshot)
        evaluation = _build_evaluation(outline, answers, evidence, job, resume)
        return {"session_id": sid, "job_title": sess.get("岗位名称"), "evaluation": evaluation}
    finally:
        conn.close()


def _source_row(q: Mapping[str, Any]) -> dict[str, Any]:
    """报告页用：每轮的题型 + 题目 + 出处（题库命中给链接，模板题明确标注）。"""
    src = q.get("source") or {"kind": "template"}
    return {"round": q.get("round"), "type": q.get("type"),
            "label": QUESTION_LABELS.get(str(q.get("type")), str(q.get("type"))),
            "question": q.get("question"),
            "kind": src.get("kind", "template"),
            "name": src.get("name") or ("模板出题" if src.get("kind") != "bank" else ""),
            "url": src.get("url"), "bank_id": src.get("id"),
            "is_probe": bool(q.get("probe_of")), "probe_of": q.get("probe_of"),
            "question_raw": q.get("question_raw")}


@router.get("/bank")
def bank_browse(family: str = "", qtype: str = "", q: str = "",
                limit: int = 30, ctx: ToolContext = Depends(get_current_ctx)) -> dict[str, Any]:
    """题库浏览（只读）：按行业族 / 题型 / 关键词过滤，每条带出处可回溯。

    数据源与出题检索同源（data/question_bank/*.json 硬校验后的池），
    缺字段或坏条目在加载时就已抛错，这里只做过滤，缺失不冒充。
    """
    limit = max(1, min(limit, 100))
    text = qbank._norm(q)
    items = []
    for it in qbank.load_bank():
        if family and it.family != qbank.normalize_industry(family):
            continue
        if qtype and it.qtype != qtype:
            continue
        if text and text not in qbank._norm(it.question) \
                and not any(text in qbank._norm(k) for k in it.keywords):
            continue
        items.append({"id": it.id, "family": it.family,
                      "family_label": qbank.family_label(it.family),
                      "qtype": it.qtype, "question": it.question,
                      "keywords": list(it.keywords), "difficulty": it.difficulty,
                      "source_name": it.source_name, "source_url": it.source_url})
    audit_event(tenant_id=ctx.tenant_id, actor_type=ctx.actor_type,
                actor_id=ctx.teacher_id if ctx.actor_type == "teacher" else ctx.student_id,
                action="interview.bank.browse",
                detail={"family": family, "qtype": qtype, "hits": len(items)})
    return {"total": len(items), "shown": min(len(items), limit), "items": items[:limit],
            "families": dict(qbank.FAMILY_LABELS),
            "qtypes": list(qbank.QTYPES)}


@router.get("/{sid}")
def interview_detail(sid: int, ctx: ToolContext = Depends(require_student)) -> dict[str, Any]:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            sess = _one(cur, "SELECT * FROM `面试会话` WHERE `编号`=%s AND `租户编号`=%s", (sid, ctx.tenant_id))
            if not sess or int(sess["学生编号"]) != int(ctx.student_id or 0):
                raise HTTPException(404, "会话不存在或不属于本人")
            qa = _rows(cur, "SELECT * FROM `面试问答` WHERE `会话编号`=%s ORDER BY `轮次`", (sid,))
        return {"session": {k: sess[k] for k in
                            ("编号", "岗位名称", "状态", "总分", "报告", "差距清单", "当前轮次", "最大轮次", "创建时间")},
                "outline": json.loads(sess["提纲"] or "[]"), "qa": qa}
    finally:
        conn.close()


@router.get("/history/me")
def interview_history(ctx: ToolContext = Depends(require_student)) -> dict[str, Any]:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            rows = _rows(cur, "SELECT `编号`,`岗位名称`,`状态`,`总分`,`当前轮次`,`最大轮次`,`创建时间`,`完成时间`"
                              " FROM `面试会话` WHERE `租户编号`=%s AND `学生编号`=%s ORDER BY `编号` DESC LIMIT 50",
                         (ctx.tenant_id, ctx.student_id))
        return {"total": len(rows), "items": rows}
    finally:
        conn.close()
