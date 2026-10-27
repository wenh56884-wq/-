# app/routers/workflow.py
# 职责：工作流的定义与运行——把「一次要点多次工具」固化成可复跑的流程。
# 鉴权：定义/删除限教师；运行不限角色，但只跑本人权限范围内的工具（ctx 原样透传）。
# 铁律：步骤只允许白名单工具；失败即停并落库；不执行任何用户提供的代码或表达式。

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import pymysql
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.audit import audit_event
from app.auth import get_current_ctx, require_teacher
from app.config import get_settings
from engine import workflow as wf_engine
from agents.tools import ToolContext

router = APIRouter(prefix="/workflow", tags=["workflow"])


def _conn() -> pymysql.connections.Connection:
    s = get_settings()
    return pymysql.connect(host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
                           password=s.mysql_password, database=s.mysql_db,
                           charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)


def _json_list(raw: Any) -> list:
    if isinstance(raw, list):
        return raw
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except (TypeError, ValueError):
        return []


class StepIn(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    tool: str = Field(min_length=1, max_length=40)
    title: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)
    on_error: str | None = Field(default=None, pattern="^(stop|continue)$")


class DefIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    steps: list[StepIn] = Field(min_length=1)


@router.get("/tools")
def list_tools(ctx: ToolContext = Depends(get_current_ctx)) -> dict[str, Any]:
    """可用步骤工具（白名单），给定义页做下拉。"""
    return {"items": [{"name": k, "label": v} for k, v in wf_engine.ALLOWED_TOOLS.items()],
            "max_steps": wf_engine.MAX_STEPS, "engine_version": wf_engine.WORKFLOW_VERSION}


@router.get("/defs")
def list_defs(ctx: ToolContext = Depends(get_current_ctx)) -> dict[str, Any]:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT `编号` AS id,`名称` AS name,`描述` AS description,`步骤` AS steps,"
                        "`是否启用` AS enabled,`创建时间` AS created_at FROM `工作流定义`"
                        " WHERE `租户编号`=%s ORDER BY `编号`", (ctx.tenant_id,))
            rows = list(cur.fetchall())
        for r in rows:
            r["steps"] = _json_list(r.get("steps"))
            r["step_count"] = len(r["steps"])
        return {"total": len(rows), "items": rows}
    finally:
        conn.close()


@router.post("/defs")
def create_def(inp: DefIn, ctx: ToolContext = Depends(require_teacher)) -> dict[str, Any]:
    steps = [s.model_dump() for s in inp.steps]
    problems = wf_engine.validate(steps)
    if problems:
        raise HTTPException(422, "；".join(problems))
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT `编号` FROM `工作流定义` WHERE `租户编号`=%s AND `名称`=%s",
                        (ctx.tenant_id, inp.name))
            exist = cur.fetchone()
            payload = json.dumps(steps, ensure_ascii=False)
            if exist:
                cur.execute("UPDATE `工作流定义` SET `描述`=%s,`步骤`=%s,`是否启用`=1 WHERE `编号`=%s",
                            (inp.description, payload, exist["编号"]))
                did = int(exist["编号"])
            else:
                cur.execute("INSERT INTO `工作流定义`(`租户编号`,`名称`,`描述`,`步骤`,`创建人`)"
                            " VALUES (%s,%s,%s,%s,%s)",
                            (ctx.tenant_id, inp.name, inp.description, payload,
                             f"teacher:{ctx.teacher_id}"))
                did = int(cur.lastrowid)
        conn.commit()
        audit_event(actor_type="teacher", actor_id=ctx.teacher_id or 0, action="workflow.define",
                    target=str(did), detail={"name": inp.name, "steps": len(steps)})
        return {"id": did, "name": inp.name, "steps": steps}
    finally:
        conn.close()


@router.delete("/defs/{def_id}")
def delete_def(def_id: int, ctx: ToolContext = Depends(require_teacher)) -> dict[str, Any]:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM `工作流定义` WHERE `编号`=%s AND `租户编号`=%s",
                        (def_id, ctx.tenant_id))
            if cur.rowcount <= 0:
                raise HTTPException(404, "工作流不存在")
        conn.commit()
        return {"deleted": def_id}
    finally:
        conn.close()


def run_definition(ctx: ToolContext, def_id: int, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
    """执行一个已定义的工作流，并把逐步结果落库。"""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM `工作流定义` WHERE `编号`=%s AND `租户编号`=%s",
                        (def_id, ctx.tenant_id))
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "工作流不存在")
            if not int(row["是否启用"]):
                raise HTTPException(409, "该工作流已停用")
            steps = _json_list(row["步骤"])
            name = str(row["名称"])
    finally:
        conn.close()

    started = datetime.now()
    try:
        result = wf_engine.run(steps, _impl_for(ctx), extra_args=inputs or {})
    except wf_engine.WorkflowError as exc:
        raise HTTPException(422, str(exc)) from exc

    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO `工作流运行`(`定义编号`,`触发角色`,`触发人编号`,`入参`,`状态`,"
                        "`步骤结果`,`错误`,`耗时毫秒`,`结束时间`)"
                        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NOW())",
                        (def_id, ctx.actor_type,
                         ctx.teacher_id if ctx.actor_type == "teacher" else ctx.student_id,
                         json.dumps(inputs or {}, ensure_ascii=False), result["status"],
                         json.dumps(result["steps"], ensure_ascii=False, default=str),
                         result.get("error"), result["elapsed_ms"]))
            run_id = int(cur.lastrowid)
        conn.commit()
        audit_event(actor_type=ctx.actor_type, actor_id=ctx.teacher_id or ctx.student_id or 0,
                    action="workflow.run", target=str(def_id),
                    detail={"run_id": run_id, "status": result["status"],
                            "steps": len(result["steps"])})
    finally:
        conn.close()
    return {"run_id": run_id, "name": name, "started_at": started.isoformat(timespec="seconds"),
            **result, "summary": wf_engine.render_summary(result)}


def _impl_for(ctx: ToolContext):
    from agents import tools

    return {
        "my_warning": lambda **kw: tools.my_warning(ctx, **kw),
        "my_recommendations": lambda **kw: tools.my_recommendations(ctx, **kw),
        "class_list": lambda **kw: tools.class_list(ctx),
        "class_overview": lambda **kw: tools.class_overview(ctx, **kw),
        "warning_list": lambda **kw: tools.warning_list(ctx, **kw),
        "career_gap": lambda **kw: tools.career_gap(ctx, **kw),
        "student_profile": lambda **kw: tools.student_profile(ctx, **kw),
        "kb_search": lambda **kw: tools.kb_search(ctx, **kw),
        "job_search": lambda **kw: tools.search_jobs(ctx, **kw),
    }


@router.post("/defs/{def_id}/run")
def run_def(def_id: int, inputs: dict[str, Any] | None = None,
            ctx: ToolContext = Depends(get_current_ctx)) -> dict[str, Any]:
    return run_definition(ctx, def_id, inputs)


@router.get("/runs")
def list_runs(limit: int = 20, ctx: ToolContext = Depends(get_current_ctx)) -> dict[str, Any]:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT r.`编号` AS id, d.`名称` AS name, r.`状态` AS status,"
                        " r.`错误` AS error, r.`耗时毫秒` AS elapsed_ms, r.`开始时间` AS started_at,"
                        " r.`步骤结果` AS steps FROM `工作流运行` r"
                        " JOIN `工作流定义` d ON d.`编号`=r.`定义编号`"
                        " WHERE d.`租户编号`=%s ORDER BY r.`编号` DESC LIMIT %s",
                        (ctx.tenant_id, max(1, min(int(limit), 100))))
            rows = list(cur.fetchall())
        for r in rows:
            r["steps"] = _json_list(r.get("steps"))
        return {"total": len(rows), "items": rows}
    finally:
        conn.close()
