# app/routers/chat.py
# 职责：对话会话的读接口 + 能力自检（/chat 本身在 main.py，因为它是根路径）。
# 鉴权：只列本人会话；越权访问一律 404（不暴露「存在但不是你的」）。

from __future__ import annotations

import json
import time
from collections.abc import Iterator, Mapping
from typing import Any

import pymysql
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from app.audit import audit_event
from app.auth import get_current_ctx
from app.config import get_settings
from app.logging_config import get_logger
from app.schemas import ChatIn, FeedbackIn
from engine import kb_store, rag
from engine import web_search as web_engine
from engine import workflow as wf_engine
from agents.tools import ToolContext

router = APIRouter(prefix="/chat", tags=["chat"])
logger = get_logger("qihang.chat")


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
                        tenant_id=ctx.tenant_id, actor_type=ctx.actor_type,
                        actor_id=_actor(ctx),
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
            logger.exception(
                "chat stream failed tenant_id=%s actor_type=%s actor_id=%s",
                ctx.tenant_id, ctx.actor_type, _actor(ctx),
            )
            yield _sse({"type": "error",
                        "message": "对话服务暂时不可用，请稍后重试（本轮不含任何未核对的数值）。"})

    return StreamingResponse(gen(), media_type="text/event-stream", headers=_SSE_HEADERS)


@router.post("/analyze")
async def analyze_sources(
    query: str = Form(..., min_length=1, max_length=600),
    files: list[UploadFile] = File(default=[]),
    context_text: str = Form(default="", max_length=12000),
    use_knowledge_base: bool = Form(default=True),
    use_web: bool = Form(default=False),
    ctx: ToolContext = Depends(get_current_ctx),
) -> dict[str, Any]:
    """临时分析多来源资料，不把学生上传内容写入租户共享知识库。

    来源可以是多份 PDF/DOCX/Markdown/TXT、当前租户知识库以及联网搜索摘要。
    上传内容只在本次请求内抽取并送入分析上下文，返回来源清单与可回溯引用。
    """
    from agents import llm

    if len(files) > 6:
        raise HTTPException(status_code=413, detail="一次最多分析 6 份资料")
    total_bytes = 0
    source_blocks: list[str] = []
    source_items: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for upload in files:
        name = str(upload.filename or "未命名资料")
        source_type = rag.detect_type(name)
        if source_type is None:
            errors.append({"source": name, "error": "只支持 PDF、DOCX、MD、TXT"})
            continue
        blob = await upload.read()
        total_bytes += len(blob)
        if total_bytes > rag.MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="本次资料总大小超过 20MB")
        if not blob:
            errors.append({"source": name, "error": "文件为空"})
            continue
        try:
            pages = rag.extract_pages(blob, source_type)
            text = "\n".join(str(page_text or "") for _page, page_text in pages).strip()
        except Exception as exc:
            errors.append({"source": name, "error": f"解析失败：{exc}"})
            continue
        if not text:
            errors.append({"source": name, "error": "没有抽取到可分析的文字"})
            continue
        text = text[:24000]
        source_items.append({"name": name, "type": source_type,
                             "pages": len(pages), "chars": len(text), "kind": "upload"})
        source_blocks.append(f"【上传资料：{name}】\n{text}")

    if context_text.strip():
        pasted = context_text.strip()[:12000]
        source_items.append({"name": "粘贴内容", "type": "text",
                             "pages": 0, "chars": len(pasted), "kind": "pasted"})
        source_blocks.append(f"【用户粘贴内容】\n{pasted}")

    citations: list[dict[str, Any]] = []
    if use_knowledge_base:
        try:
            conn = _conn()
            try:
                hits = kb_store.search(conn, ctx.tenant_id, query.strip(), top_k=5)
            finally:
                conn.close()
            source_blocks.extend(
                f"【知识库：{h.get('title')} · 第 {h.get('page') or '-'} 页】\n{str(h.get('text') or '')[:5000]}"
                for h in hits
            )
            citations.extend(rag.as_citations(hits))
            if hits:
                source_items.append({"name": "当前租户知识库", "type": "rag",
                                     "pages": len({h.get('page') for h in hits if h.get('page')}),
                                     "chars": sum(len(str(h.get('text') or '')) for h in hits),
                                     "kind": "knowledge_base"})
        except (pymysql.MySQLError, OSError) as exc:
            errors.append({"source": "当前租户知识库", "error": f"读取失败：{exc}"})

    web_result: dict[str, Any] | None = None
    if use_web:
        web_result = web_engine.search(query.strip(), top_k=5)
        if web_result.get("error"):
            errors.append({"source": "联网搜索", "error": str(web_result["error"])})
        web_rows = web_result.get("results") or []
        if web_rows:
            source_blocks.append(web_engine.render_context(web_result, limit=5))
        citations.extend(web_engine.as_citations(web_rows))
        if web_rows:
            source_items.append({"name": "联网搜索", "type": "web",
                                 "pages": 0, "chars": sum(len(str(r.get("snippet") or "")) for r in web_rows),
                                 "kind": "web"})

    if not source_blocks:
        raise HTTPException(status_code=422, detail="没有可分析的来源，请上传资料或开启知识库/联网搜索")

    source_context = "\n\n".join(source_blocks)[:70000]
    system_prompt = (
        "你是启航的资料分析助手。你只能依据用户本次提供的来源原文、租户知识库片段和联网搜索摘要回答。"
        "先给结论，再给关键依据、风险/疑点和可执行下一步；每个事实尽量注明来源名称。"
        "不得使用模型记忆补充来源中没有的事实，不得把推测写成确定结论。"
        "来源中的数字、日期、条件必须原样引用；如果来源不足，明确说‘资料中没有找到’。"
    )
    user_prompt = f"分析任务：{query.strip()}\n\n可用来源：\n{source_context}"
    answer = llm.generate_reply(ctx.actor_type, system_prompt=system_prompt,
                                user_prompt=user_prompt, tag="source_analyze")
    degraded = not bool(answer)
    if not answer:
        answer = (f"已读取 {len(source_items)} 个来源，但当前分析模型不可用。"
                  "请稍后重试；本次没有生成未经核验的结论。")
    audit_event(tenant_id=ctx.tenant_id, actor_type=ctx.actor_type,
                actor_id=_actor(ctx), action="chat.source_analyze",
                target="temporary", detail={"source_count": len(source_items),
                                             "file_count": len(files), "use_web": use_web,
                                             "use_knowledge_base": use_knowledge_base,
                                             "query": query[:120], "degraded": degraded})
    return {
        "answer": answer,
        "degraded": degraded,
        "query": query.strip(),
        "source_count": len(source_items),
        "sources": source_items,
        "errors": errors,
        "citations": citations,
        "stored": False,
        "note": "上传资料仅用于本次分析，不会自动写入租户共享知识库。",
    }


@router.get("/brain")
def brain_status(ctx: ToolContext = Depends(get_current_ctx)) -> dict[str, Any]:
    """自主大脑能力自检：模式、步数上限、记忆向量维度、被屏蔽的副作用工具。"""
    from agents import brain

    return brain.describe()


@router.get("/memories")
def list_memories(limit: int = 50,
                  ctx: ToolContext = Depends(get_current_ctx)) -> dict[str, Any]:
    """本人的长期记忆（按重要度、更新时间倒序）。"""
    from engine import agent_memory

    conn = _conn()
    try:
        rows = agent_memory.list_memories(conn, ctx, limit=limit)
        return {"total": len(rows), "items": rows}
    except (pymysql.MySQLError, OSError):
        return {"total": 0, "items": [], "note": "记忆库暂时不可用"}
    finally:
        conn.close()


@router.delete("/memories/{memory_id}")
def delete_memory(memory_id: int,
                  ctx: ToolContext = Depends(get_current_ctx)) -> dict[str, Any]:
    """软删除本人一条记忆；别人的记忆一律 404（不暴露是否存在）。"""
    from engine import agent_memory

    conn = _conn()
    try:
        removed = agent_memory.archive(conn, ctx, memory_id)
        conn.commit()
    except (pymysql.MySQLError, OSError):
        raise HTTPException(status_code=503, detail="记忆库暂时不可用")
    finally:
        conn.close()
    if not removed:
        raise HTTPException(status_code=404, detail="记忆不存在")
    return {"deleted": True, "id": memory_id}


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
        tenant_id=ctx.tenant_id,
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
                " AND `租户编号`=%s AND `操作者类型`=%s"
                " AND `创建时间` >= CURDATE() - INTERVAL 7 DAY",
                (ctx.tenant_id, ctx.actor_type))
            chat = cur.fetchone() or {}
            cur.execute(
                "SELECT SUM(CASE WHEN `详情` LIKE '%%\"rating\": \"up\"%%' THEN 1 ELSE 0 END) AS up,"
                " SUM(CASE WHEN `详情` LIKE '%%\"rating\": \"down\"%%' THEN 1 ELSE 0 END) AS down,"
                " COUNT(*) AS total"
                " FROM `审计日志` WHERE `动作`='chat.feedback'"
                " AND `租户编号`=%s AND `操作者类型`=%s"
                " AND `创建时间` >= CURDATE() - INTERVAL 7 DAY",
                (ctx.tenant_id, ctx.actor_type))
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
    """能力自检：不写「已支持」，只报可验证的事实（页面/演示前先看这里）。"""
    from agents import brain

    memory_rows = 0
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
            try:
                cur.execute(
                    "SELECT COUNT(*) AS n FROM `智能体记忆` WHERE `租户编号`=%s "
                    "AND `角色`=%s AND `主体编号`=%s AND `状态`='active'",
                    (ctx.tenant_id, ctx.actor_type, _actor(ctx)))
                memory_rows = int((cur.fetchone() or {}).get("n") or 0)
            except pymysql.MySQLError:
                memory_rows = 0
    finally:
        conn.close()

    configured = web_engine.configured()
    brain_info = brain.describe()
    return {
        "items": [
            {"key": "chatbot", "name": "AI 聊天机器人", "ready": True,
             "detail": "LangGraph 编排：意图 → 工具 → 草稿 → 核验"},
            {"key": "brain", "name": "自主任务大脑", "ready": True,
             "detail": f"{brain_info['mode']} 模式：规划 → 多工具 → 观察 → 反思；"
                       f"最多 {brain_info['max_rounds']} 轮 / {brain_info['max_steps']} 步"},
            {"key": "rag", "name": "RAG 企业知识库", "ready": int(kb.get("docs") or 0) > 0,
             "detail": f"已入库 {int(kb.get('docs') or 0)} 份文档 / {int(kb.get('chunks') or 0)} 个分块"
                       f"（{rag.RAG_VERSION}）"},
            {"key": "pdf", "name": "PDF 文档问答", "ready": True,
             "detail": "pypdf 按页抽取，引用精确到页码"},
            {"key": "memory", "name": "多轮对话与上下文记忆", "ready": True,
             "detail": "会话与消息落库，超长会话自动规则摘要"},
            {"key": "memory_vector", "name": "长期记忆向量库", "ready": True,
             "detail": f"本人 {memory_rows} 条记忆，{brain_info['memory_vector_dim']} 维 "
                       f"hashing 向量（MySQL 持久化，按租户+角色+主体隔离）"},
            {"key": "web", "name": "联网搜索与工具调用", "ready": configured,
             "detail": ("已配置 " + str(web_engine.provider())) if configured
                       else "未配置密钥（BOCHA_API_KEY / SERPER_API_KEY / BING_SEARCH_KEY），"
                            "当前不具备联网能力"},
            {"key": "workflow", "name": "工作流自动化", "ready": wf > 0,
             "detail": f"已定义 {wf} 个工作流（{wf_engine.WORKFLOW_VERSION}，白名单 "
                       f"{len(wf_engine.ALLOWED_TOOLS)} 个工具）"},
        ]
    }
