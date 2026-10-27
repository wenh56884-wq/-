# app/routers/chat.py
# 职责：对话会话的读接口 + 能力自检（/chat 本身在 main.py，因为它是根路径）。
# 鉴权：只列本人会话；越权访问一律 404（不暴露「存在但不是你的」）。

from __future__ import annotations

import json
from typing import Any

import pymysql
from fastapi import APIRouter, Depends, HTTPException

from app.auth import get_current_ctx
from app.config import get_settings
from engine import rag
from engine import web_search as web_engine
from engine import workflow as wf_engine
from agents.tools import ToolContext

router = APIRouter(prefix="/chat", tags=["chat"])


def _conn() -> pymysql.connections.Connection:
    s = get_settings()
    return pymysql.connect(host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
                           password=s.mysql_password, database=s.mysql_db,
                           charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)


def _actor(ctx: ToolContext) -> int:
    return int((ctx.teacher_id if ctx.actor_type == "teacher" else ctx.student_id) or 0)


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


@router.get("/sessions")
def list_sessions(limit: int = 20, ctx: ToolContext = Depends(get_current_ctx)) -> dict[str, Any]:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT `编号` AS id,`标题` AS title,`摘要` AS summary,"
                        "`消息数` AS messages,`创建时间` AS created_at,`最近时间` AS updated_at"
                        " FROM `对话会话` WHERE `租户编号`=%s AND `角色`=%s AND `主体编号`=%s"
                        " ORDER BY `最近时间` DESC LIMIT %s",
                        (ctx.tenant_id, ctx.actor_type, _actor(ctx),
                         max(1, min(int(limit), 100))))
            rows = list(cur.fetchall())
        return {"total": len(rows), "items": rows}
    finally:
        conn.close()


@router.get("/sessions/{sid}")
def get_session(sid: int, ctx: ToolContext = Depends(get_current_ctx)) -> dict[str, Any]:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT `编号` AS id,`标题` AS title,`摘要` AS summary,`消息数` AS messages"
                        " FROM `对话会话` WHERE `编号`=%s AND `租户编号`=%s AND `角色`=%s"
                        " AND `主体编号`=%s", (sid, ctx.tenant_id, ctx.actor_type, _actor(ctx)))
            sess = cur.fetchone()
            if not sess:
                raise HTTPException(404, "会话不存在")
            cur.execute("SELECT `角色` AS role,`内容` AS text,`工具` AS tool,`引用` AS citations,"
                        "`追踪号` AS trace_id,`是否降级` AS degraded,`创建时间` AS created_at"
                        " FROM `对话消息` WHERE `会话编号`=%s ORDER BY `编号`", (sid,))
            msgs = list(cur.fetchall())
        for m in msgs:
            m["citations"] = _json_list(m.get("citations"))
            m["degraded"] = bool(m.get("degraded"))
        return {"session": sess, "messages": msgs}
    finally:
        conn.close()


@router.delete("/sessions/{sid}")
def delete_session(sid: int, ctx: ToolContext = Depends(get_current_ctx)) -> dict[str, Any]:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT `编号` FROM `对话会话` WHERE `编号`=%s AND `租户编号`=%s"
                        " AND `角色`=%s AND `主体编号`=%s",
                        (sid, ctx.tenant_id, ctx.actor_type, _actor(ctx)))
            if not cur.fetchone():
                raise HTTPException(404, "会话不存在")
            cur.execute("DELETE FROM `对话消息` WHERE `会话编号`=%s", (sid,))
            cur.execute("DELETE FROM `对话会话` WHERE `编号`=%s", (sid,))
        conn.commit()
        return {"deleted": sid}
    finally:
        conn.close()


@router.get("/capabilities")
def capabilities(ctx: ToolContext = Depends(get_current_ctx)) -> dict[str, Any]:
    """六项能力的真实状态（自检用）：不写「已支持」，只报可验证的事实。"""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS docs, COALESCE(SUM(`分块数`),0) AS chunks"
                        " FROM `知识库文档` WHERE `租户编号`=%s AND `状态`='ready'",
                        (ctx.tenant_id,))
            kb = cur.fetchone() or {}
            cur.execute("SELECT COUNT(*) AS n FROM `工作流定义` WHERE `租户编号`=%s AND `是否启用`=1",
                        (ctx.tenant_id,))
            wf = int((cur.fetchone() or {}).get("n") or 0)
    finally:
        conn.close()

    configured = web_engine.configured()
    return {
        "items": [
            {"key": "chatbot", "name": "AI 聊天机器人", "ready": True,
             "detail": "LangGraph 编排：意图 → 工具 → 草稿 → 核验"},
            {"key": "rag", "name": "RAG 企业知识库", "ready": int(kb.get("docs") or 0) > 0,
             "detail": f"已入库 {int(kb.get('docs') or 0)} 份文档 / {int(kb.get('chunks') or 0)} 个分块"
                       f"（{rag.RAG_VERSION}）"},
            {"key": "pdf", "name": "PDF 文档问答", "ready": True,
             "detail": "pypdf 按页抽取，引用精确到页码"},
            {"key": "memory", "name": "多轮对话与上下文记忆", "ready": True,
             "detail": "会话与消息落库，超长会话自动规则摘要"},
            {"key": "web", "name": "联网搜索与工具调用", "ready": configured,
             "detail": ("已配置 " + str(web_engine.provider())) if configured
                       else "未配置密钥（SERPER_API_KEY / BING_SEARCH_KEY），当前不具备联网能力"},
            {"key": "workflow", "name": "工作流自动化", "ready": wf > 0,
             "detail": f"已定义 {wf} 个工作流（{wf_engine.WORKFLOW_VERSION}，白名单 "
                       f"{len(wf_engine.ALLOWED_TOOLS)} 个工具）"},
        ]
    }
