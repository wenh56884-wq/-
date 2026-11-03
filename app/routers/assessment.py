# app/routers/assessment.py
# 职责：软技能测评 API——取题 / 提交答题 / 查本人结果
# 依赖：app.auth（身份注入）/ engine.assessment（确定性计分）/ pymysql
# 说明：student_id 只从 JWT 取，接口无任何「查谁」入参；分数与画像由引擎算，模型不参与

from __future__ import annotations

import json
import time
from typing import Any, Mapping

import pymysql
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.audit import audit_event
from app.auth import require_student
from app.config import get_settings
from agents.tools import ToolContext
from engine import assessment as assess

router = APIRouter(prefix="/assessment", tags=["软技能测评"])


class AnswersIn(BaseModel):
    """提交的答题：题目编号 → 选项键。只取本人 token 身份，不接受学号。"""

    answers: dict[int, str] = Field(description='形如 {1:"A",2:"B"}，键为题目编号')


def _conn() -> pymysql.connections.Connection:
    s = get_settings()
    return pymysql.connect(host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
                           password=s.mysql_password, database=s.mysql_db,
                           charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)


def _question_row(qid: int) -> dict[str, Any] | None:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT `编号`,`类别`,`维度`,`题面`,`选项`,`选项分值` "
                "FROM `测评题目` WHERE `编号`=%s AND `是否启用`=1", (qid,))
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()


@router.get("/questions")
def get_questions(ctx: ToolContext = Depends(require_student)) -> dict[str, Any]:
    """取启用中的全部测评题（选项与分值一并下发，分值供前端本地即时计分预览）。"""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT `编号`,`类别`,`维度`,`题面`,`选项`,`选项分值` "
                "FROM `测评题目` WHERE `是否启用`=1 ORDER BY `排序` ASC")
            rows = [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

    questions: list[dict[str, Any]] = []
    for r in rows:
        questions.append({
            "id": int(r["编号"]),
            "category": r["类别"],
            "dimension": r["维度"],
            "content": r["题面"],
            "options": json.loads(r["选项"]) if r.get("选项") else {},
            "scoring": json.loads(r["选项分值"]) if r.get("选项分值") else {},
        })
    return {"questions": questions, "total": len(questions)}


@router.post("/submit")
def submit_answers(body: AnswersIn,
                   ctx: ToolContext = Depends(require_student)) -> dict[str, Any]:
    """提交答题：引擎按题库分值确定性计分并落库，返回维度得分与复合能力。"""
    if not body.answers:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="答案不能为空")

    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT `编号`,`维度`,`选项分值` FROM `测评题目` WHERE `是否启用`=1")
            rows = [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

    questions = [{
        "id": int(r["编号"]),
        "dimension": r["维度"],
        "scoring": json.loads(r["选项分值"]) if r.get("选项分值") else {},
    } for r in rows]

    result = assess.score_answers(questions, body.answers)

    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO `测评结果` (`租户编号`,`学生编号`,`答案`,`维度得分`,`总分`,`满分`,`复合能力`) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (int(ctx.tenant_id), int(ctx.student_id),
                 json.dumps({str(k): v for k, v in body.answers.items()}, ensure_ascii=False),
                 json.dumps(result["dimensions"], ensure_ascii=False),
                 result["total_score"], result["total_max"],
                 json.dumps(result["abilities"], ensure_ascii=False)))
            result_id = int(cur.lastrowid)
        conn.commit()
    finally:
        conn.close()

    audit_event(actor_type=ctx.actor_type, actor_id=ctx.student_id,
                action="assessment.submit", target=str(result_id),
                detail={"answered": result["answered"]})

    return {
        "result_id": result_id,
        "total_score": result["total_score"],
        "total_max": result["total_max"],
        "answered": result["answered"],
        "dimension_scores": result["dimension_scores"],
        "abilities": result["abilities"],
        "engine_version": assess.ASSESSMENT_ENGINE_VERSION,
    }


@router.get("/results")
def my_results(ctx: ToolContext = Depends(require_student)) -> dict[str, Any]:
    """查本人历史测评结果（按时间倒序，最多 20 条）。"""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT `编号`,`维度得分`,`总分`,`满分`,`复合能力`,`创建时间` "
                "FROM `测评结果` WHERE `租户编号`=%s AND `学生编号`=%s "
                "ORDER BY `创建时间` DESC LIMIT 20",
                (int(ctx.tenant_id), int(ctx.student_id)))
            rows = [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

    results: list[dict[str, Any]] = []
    for r in rows:
        dimensions = json.loads(r["维度得分"]) if r.get("维度得分") else {}
        abilities = json.loads(r["复合能力"]) if r.get("复合能力") else {}
        # 历史结果的 dimension_scores 从已存的 pct 还原，保证与提交时同口径
        pcts = {dim: float(agg["pct"]) for dim, agg in dimensions.items()
                if isinstance(agg, dict) and agg.get("pct") is not None}
        results.append({
            "result_id": int(r["编号"]),
            "total_score": float(r["总分"]) if r.get("总分") is not None else None,
            "total_max": float(r["满分"]) if r.get("满分") is not None else None,
            "dimensions": dimensions,
            "dimension_scores": assess.weighted_dimension_scores(pcts),
            "abilities": abilities,
            "engine_version": assess.ASSESSMENT_ENGINE_VERSION,
            "create_time": str(r["创建时间"]),
        })
    return {"results": results, "total": len(results)}
