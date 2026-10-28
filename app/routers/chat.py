# app/routers/chat.py
# 职责：对话会话的读接口 + 能力自检（/chat 本身在 main.py，因为它是根路径）。
# 鉴权：只列本人会话；越权访问一律 404（不暴露「存在但不是你的」）。

from __future__ import annotations

import json
import time
from collections.abc import Iterator, Mapping
from typing import Any

import pymysql
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.audit import audit_event
from app.auth import get_current_ctx
from app.config import get_settings
from app.schemas import ChatIn, FeedbackIn
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


_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",   # 关闭 Nginx 缓冲，逐块下发
    "Connection": "keep-alive",
}


def _sse(event: Mapping[str, Any]) -> str:
    """把事件编码成 SSE 帧：event 名 + 单行 JSON（JSON 会转义换行，天然一帧一行 data）。"""
    kind = str(event.get("type") or "message")
    return f"event: {kind}\ndata: {json.dumps(dict(event), ensure_ascii=False)}\n\n"


@router.post("/stream")
def stream_chat(body: ChatIn, ctx: ToolContext = Depends(get_current_ctx)) -> StreamingResponse:
    """流式对话（SSE）：status → replace/delta → done。

    身份同样只来自 get_current_ctx；数值口径与 /chat 一致——delta 只是生成过程，
    最终以 done.answer（已过 Critic）为准，前端收到 done 后整体覆盖气泡文本。
    """
    def gen() -> Iterator[str]:
        started = time.perf_counter()
        try:
            from app import chat_service

            for event in chat_service.handle_stream(ctx, body.query, body.term,
                                                    body.session_id, body.history):
                if event.get("type") == "done":
                    audit_event(
                        actor_type=ctx.actor_type, actor_id=_actor(ctx),
                        action="api.chat.stream", target=str(event.get("trace_id") or ""),
                        detail={"query": body.query[:120], "term": body.term,
                                "session_id": event.get("session_id"),
                                "tool": event.get("tool"),
                                "citations": len(event.get("citations") or []),
                                "degraded": bool(event.get("degraded"))},
                        duration_ms=(time.perf_counter() - started) * 1000,
                    )
                yield _sse(event)
        except Exception:
            yield _sse({"type": "error",
                        "message": "对话服务暂时不可用，请稍后重试（本轮不含任何未核对的数值）。"})

    return StreamingResponse(gen(), media_type="text/event-stream", headers=_SSE_HEADERS)


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


@router.post("/feedback")
def feedback(body: FeedbackIn, ctx: ToolContext = Depends(get_current_ctx)) -> dict[str, Any]:
    """对话质量反馈：点赞/点踩 + 备注，落审计（chat.feedback）。

    商业化闭环：没有反馈数据就无法向客户证明「助手确实在被使用且越用越准」。
    """
    entry = audit_event(
        actor_type=ctx.actor_type,
        actor_id=_actor(ctx),
        action="chat.feedback",
        target=body.trace_id,
        detail={"rating": body.rating, "comment": (body.comment or "")[:500]},
    )
    return {"ok": True, "trace_id": body.trace_id, "rating": body.rating,
            "recorded_at": str(entry.get("logged_at") or "")}


@router.get("/metrics")
def metrics(ctx: ToolContext = Depends(get_current_ctx)) -> dict[str, Any]:
    """助手质量指标（近 7 天，本租户）：问答量 / 降级率 / 好评率 / 平均耗时。

    仅教师可看；数据全部来自审计日志实数，不估算。
    """
    if ctx.actor_type != "teacher":
        raise HTTPException(403, "质量指标仅教师可查看")
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS n,"
                " SUM(CASE WHEN `详情` LIKE '%%\"degraded\": true%%' THEN 1 ELSE 0 END) AS degraded,"
                " AVG(CAST(JSON_EXTRACT(`详情`, '$.duration_ms') AS DECIMAL(12,2))) AS avg_ms"
                " FROM `审计日志` WHERE `动作`='agent.chat'"
                " AND `操作者类型`=%s AND `创建时间` >= CURDATE() - INTERVAL 7 DAY",
                (ctx.actor_type,))
            chat = cur.fetchone() or {}
            cur.execute(
                "SELECT SUM(CASE WHEN `详情` LIKE '%%\"rating\": \"up\"%%' THEN 1 ELSE 0 END) AS up,"
                " SUM(CASE WHEN `详情` LIKE '%%\"rating\": \"down\"%%' THEN 1 ELSE 0 END) AS down,"
                " COUNT(*) AS total"
                " FROM `审计日志` WHERE `动作`='chat.feedback'"
                " AND `操作者类型`=%s AND `创建时间` >= CURDATE() - INTERVAL 7 DAY",
                (ctx.actor_type,))
            fb = cur.fetchone() or {}
    except pymysql.MySQLError:
        # 审计表结构异常时如实报缺数，不编数字
        chat, fb = {}, {}
    finally:
        conn.close()

    total = int(chat.get("n") or 0)
    degraded = int(chat.get("degraded") or 0)
    up = int(fb.get("up") or 0)
    down = int(fb.get("down") or 0)
    return {
        "window_days": 7,
        "chat_total": total,
        "degraded_total": degraded,
        "degraded_rate": round(degraded / total, 4) if total else None,
        "avg_duration_ms": float(chat["avg_ms"]) if chat.get("avg_ms") is not None else None,
        "feedback_total": int(fb.get("total") or 0),
        "feedback_up": up,
        "feedback_down": down,
        "like_rate": round(up / (up + down), 4) if (up + down) else None,
    }


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
