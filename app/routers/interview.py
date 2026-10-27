# app/routers/interview.py
# 职责：模拟面试官 API——简历（上传解析/问卷自填/诊断）+ 面试（开局/逐轮/报告/历史）。
# 鉴权：学生只能操作本人（ctx.student_id 由 JWT 注入，前端不可指定查谁）。
# 铁律：分数/差距由 engine.interview 计算；点评经 agents.interviewer 防虚构校验。

from __future__ import annotations

import json
import re
import zipfile
from datetime import datetime
from typing import Any

import pymysql
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from agents import interviewer
from app.audit import audit_event
from app.auth import require_student
from app.config import get_settings
from engine.interview import (
    INTERVIEW_ENGINE_VERSION,
    aggregate,
    build_outline,
    diagnose,
    gap_list,
    parse_resume,
    parse_resume as parse_resume_engine,
    rubric_of,
    score_answer,
)
from engine.recommend import clean_skill_tags
from agents.tools import ToolContext

router = APIRouter(prefix="/interview", tags=["interview"])

# 提纲之外允许的上下文长度（回答与证据传给模型前截断，防 prompt 爆炸）
_MAX_ANSWER = 2000


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
        try:
            r["courses"] += [str(c) for c in (e.get("courses") or [])]
        except TypeError:
            pass
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
        audit_event(actor_type="student", actor_id=ctx.student_id, action="resume.save",
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
def _load_job(cur, job_id: int) -> dict[str, Any] | None:
    j = _one(cur, "SELECT `编号` AS id,`岗位名称` AS title,`招聘单位` AS company,`城市` AS city,"
                  "`学历要求` AS education,`经验要求` AS experience,`技能标签` AS skill_tags,"
                  "`职位描述` AS description,`投递链接` AS url"
                  " FROM `招聘岗位` WHERE `编号`=%s", (job_id,))
    if not j:
        return None
    j["skill_tags"] = clean_skill_tags(j.get("skill_tags"))
    return j


@router.get("/jobs")
def job_candidates(keyword: str | None = None, limit: int = 30,
                   ctx: ToolContext = Depends(require_student)) -> dict[str, Any]:
    """可练习的岗位池：在招 + 有关键词的可搜。"""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            sql = ("SELECT `编号` AS id,`岗位名称` AS title,`招聘单位` AS company,`城市` AS city,"
                   "`学历要求` AS education,`技能标签` AS skill_tags"
                   " FROM `招聘岗位` WHERE `租户编号`=%s AND `状态`<>'closed'")
            params: list[Any] = [ctx.tenant_id]
            if keyword:
                sql += " AND (`岗位名称` LIKE %s OR `技能标签` LIKE %s)"
                params += [f"%{keyword}%", f"%{keyword}%"]
            sql += " ORDER BY `发布日期` DESC, `编号` DESC LIMIT %s"
            params.append(max(1, min(int(limit), 100)))
            rows = _rows(cur, sql, tuple(params))
        for r in rows:
            r["skill_tags"] = clean_skill_tags(r.get("skill_tags"))
        return {"total": len(rows), "items": rows}
    finally:
        conn.close()


@router.get("/resume/diagnosis")
def resume_diagnosis(job_id: int | None = None,
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
            job = _load_job(cur, job_id) if job_id else None
        result = diagnose(resume, job)
        audit_event(actor_type="student", actor_id=ctx.student_id, action="resume.diagnosis",
                    target=str(row["编号"]), detail={"job_id": job_id, "issues": len(result["issues"])})
        return result
    finally:
        conn.close()


# ----------------------------------------------------------------
# 面试主链路
# ----------------------------------------------------------------
class StartIn(BaseModel):
    job_id: int | None = None
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
            job = _load_job(cur, inp.job_id) if inp.job_id else None
            outline = build_outline(job, resume, max_rounds=max_rounds)
            if not outline:
                raise HTTPException(422, "简历信息不足以出题（连基本经历都没有），请先补全简历")
            job_snapshot = {"title": job["title"], "skill_tags": job["skill_tags"],
                            "education": job.get("education")} if job else None
            cur.execute(
                "INSERT INTO `面试会话`(`租户编号`,`学生编号`,`简历编号`,`岗位编号`,`岗位名称`,`岗位要求快照`,"
                "`状态`,`提纲`,`当前轮次`,`最大轮次`,`引擎版本`) VALUES (%s,%s,%s,%s,%s,%s,'ongoing',%s,0,%s,%s)",
                (ctx.tenant_id, ctx.student_id, resume["编号"], inp.job_id,
                 (job or {}).get("title"), json.dumps(job_snapshot, ensure_ascii=False) if job_snapshot else None,
                 json.dumps(outline, ensure_ascii=False), len(outline), INTERVIEW_ENGINE_VERSION))
            sid = cur.lastrowid
        conn.commit()
        audit_event(actor_type="student", actor_id=ctx.student_id, action="interview.start",
                    target=str(sid), detail={"job_id": inp.job_id, "rounds": len(outline)})
        q = outline[0]
        return {"session_id": sid, "total_rounds": len(outline), "round": 1,
                "question_type": q["type"], "question_label": rubric_of(q["type"], job_snapshot["skill_tags"] if job_snapshot else [])["label"],
                "question": q["question"]}
    finally:
        conn.close()


class AnswerIn(BaseModel):
    text: str | None = None   # None=跳过本题


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

            # 证据 = 简历原文 + 岗位快照（防虚构比对源）
            resume = _load_resume(cur, int(sess["简历编号"]), ctx.tenant_id)
            evidence = [str(resume.get("简历原文") or resume.get("self") or "")]
            evidence += [str(t) for t in (json.loads(sess["岗位要求快照"] or "null") or {}).get("skill_tags", [])]
            evidence += [str(e.get("desc") or "") for e in resume.get("experiences") or [] if e.get("desc")]
            evidence = [e for e in evidence if e.strip()]

            rubric = rubric_of(q["type"], evidence and (json.loads(sess["岗位要求快照"] or "null") or {}).get("skill_tags", []))
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
            cur.execute("UPDATE `面试会话` SET `当前轮次`=%s WHERE `编号`=%s", (nxt, sid))
        conn.commit()
    finally:
        conn.close()

    # 还有下一题 → 返回问题；否则收卷出报告
    if nxt < len(outline):
        nq = outline[nxt]
        return {"round_done": rnd + 1, "score": item["score"] if item else None,
                "comment": turn["comment"], "comment_version": turn["comment_version"],
                "next": {"round": nxt + 1, "question": nq["question"], "question_type": nq["type"]}}
    return _finish(sid, ctx)


def _finish(sid: int, ctx: ToolContext) -> dict[str, Any]:
    """收卷：引擎汇总总分/差距 → 报告落库。"""
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
    finally:
        conn.close()

    scores = [score_answer(a["学生回答"], rubric_of(str(o["type"]), job.get("skill_tags") or []),
                           [str(resume.get("简历原文") or "")]) for a, o in zip(answers, outline)]
    total = aggregate(scores, outline)
    gaps = gap_list(resume, job, scores, outline)
    items = []
    for o, a, s in zip(outline, answers, scores):
        items.append({"round": o["round"], "label": rubric_of(o["type"], job.get("skill_tags") or [])["label"],
                      "score": s["score"] if s else None,
                      "brief": (a["学生回答"] or "未作答")[:60]})
    strengths = [it["label"] for it, s in zip(items, scores) if s and float(s["score"]) >= 75]
    facts = {"total": total["total"] if total else None, "answered": total["answered"] if total else 0,
             "skipped": total["skipped"] if total else len(outline),
             "items": items, "strengths": strengths, "gaps": gaps}
    report = interviewer.render_report(facts)

    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE `面试会话` SET `状态`='finished',`总分`=%s,`报告`=%s,`差距清单`=%s,`完成时间`=%s"
                        " WHERE `编号`=%s",
                        (facts["total"], report, json.dumps(gaps, ensure_ascii=False),
                         datetime.now(), sid))
        conn.commit()
        audit_event(actor_type="student", actor_id=ctx.student_id, action="interview.finish",
                    target=str(sid), detail={"total": facts["total"], "gaps": len(gaps)})
    finally:
        conn.close()
    return {"round_done": len(outline), "score": items[-1]["score"] if items else None,
            "finished": True, "total": facts["total"], "report": report, "gaps": gaps,
            "items": items}


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
