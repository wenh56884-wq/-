# app/chat_service.py
# 职责：把「一次对话」从请求变成可追溯的会话——落库、取上下文、写引用。
# 依赖：agents.graph / app.audit / app.config / pymysql
# 铁律：
#   1. 上下文只从数据库取本人会话；不接受前端指定「别的会话」。
#   2. 摘要由规则拼装（首轮问题 + 最近问题），不调用模型二次生成，避免摘要本身说错话。
#   3. 引用清单原样存库，事后可核对「这句话当时引用的是哪一段」。

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any, Mapping

import pymysql

from agents import graph
from agents.tools import ToolContext
from app.config import get_settings

RECENT_TURNS = 8          # 直接带进上下文的最近轮数
SUMMARY_TRIGGER = 12      # 超过这么多条消息就开始拼摘要


class QuotaExceeded(Exception):
    """每日问答配额用尽：消息里给出上限实数与恢复时间，不吓唬用户。"""


def check_quota(ctx: ToolContext) -> dict[str, int]:
    """每日配额：数 audit_log 里本人今日 agent.chat 实数，超限抛 QuotaExceeded。

    agent_daily_limit=0 表示不限量（默认）；配额按「人天」计，跨天自动恢复。
    """
    from agents.tools import _query as _tools_query
    from app.config import get_settings

    limit = int(getattr(get_settings(), "agent_daily_limit", 0) or 0)
    if limit <= 0:
        return {"limit": 0, "used": 0, "remaining": -1}
    actor = _actor(ctx)
    if not actor:
        return {"limit": limit, "used": 0, "remaining": limit}
    rows = _tools_query(
        "SELECT COUNT(*) AS used FROM `审计日志` "
        "WHERE `动作`='agent.chat' AND `操作者类型`=%s AND `操作者编号`=%s "
        "AND `创建时间` >= CURDATE()",
        (ctx.actor_type, actor),
    )
    used = int((rows[0] if rows else {}).get("used") or 0)
    if used >= limit:
        raise QuotaExceeded(
            f"今天的提问次数已达上限（每天 {limit} 条）。已聊过的会话可以随时回看，"
            "明天再来继续问。"
        )
    return {"limit": limit, "used": used, "remaining": limit - used}


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


def ensure_session(ctx: ToolContext, session_id: int | None, title: str) -> int:
    """取本人会话；session_id 不属于本人一律新建（越权不报错、也不复用别人会话）。"""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            if session_id:
                cur.execute("SELECT `编号` FROM `对话会话` WHERE `编号`=%s AND `租户编号`=%s"
                            " AND `角色`=%s AND `主体编号`=%s",
                            (int(session_id), ctx.tenant_id, ctx.actor_type, _actor(ctx)))
                row = cur.fetchone()
                if row:
                    return int(row["编号"])
            cur.execute("INSERT INTO `对话会话`(`租户编号`,`角色`,`主体编号`,`标题`)"
                        " VALUES (%s,%s,%s,%s)",
                        (ctx.tenant_id, ctx.actor_type, _actor(ctx), title[:200] or "新对话"))
            sid = int(cur.lastrowid)
        conn.commit()
        return sid
    finally:
        conn.close()


def load_history(ctx: ToolContext, session_id: int) -> tuple[list[dict[str, str]], str]:
    """取最近若干轮 + 摘要。返回 (turns, summary)。"""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT `摘要` FROM `对话会话` WHERE `编号`=%s AND `租户编号`=%s",
                        (session_id, ctx.tenant_id))
            row = cur.fetchone() or {}
            summary = str(row.get("摘要") or "")
            cur.execute("SELECT `角色`,`内容` FROM `对话消息` WHERE `会话编号`=%s"
                        " ORDER BY `编号` DESC LIMIT %s", (session_id, RECENT_TURNS * 2))
            rows = list(cur.fetchall())[::-1]
        turns = [{"role": r["角色"], "text": str(r["内容"])[:500]} for r in rows]
        return turns, summary
    finally:
        conn.close()


def _build_summary(ctx: ToolContext, session_id: int) -> str:
    """规则摘要：只复述用户问过什么，不解释、不补充，避免摘要引入幻觉。"""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT `内容` FROM `对话消息` WHERE `会话编号`=%s AND `角色`='user'"
                        " ORDER BY `编号`", (session_id,))
            asks = [str(r["内容"]).strip().replace("\n", " ") for r in cur.fetchall()]
        if not asks:
            return ""
        head = "；".join(asks[:2])[:120]
        tail = asks[-1][:80] if len(asks) > 2 else ""
        return (f"本会话共 {len(asks)} 个提问；早期问的是：{head}"
                + (f"；最近问的是：{tail}" if tail else ""))[:900]
    finally:
        conn.close()


def last_tool(ctx: ToolContext, session_id: int) -> str | None:
    """上一轮用的能力：追问「那超标了怎么办」时沿用同一能力，不贸然切回校园数据。"""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT `工具` FROM `对话消息` WHERE `会话编号`=%s"
                        " AND `角色`='assistant' AND `工具` IS NOT NULL AND `工具`<>''"
                        " ORDER BY `编号` DESC LIMIT 1", (session_id,))
            row = cur.fetchone()
        return str(row["工具"]) if row else None
    finally:
        conn.close()


def persist_turn(ctx: ToolContext, session_id: int, query: str, result: Mapping[str, Any],
                 elapsed_ms: int) -> None:
    """写两条消息 + 更新会话计数/标题/摘要。写库失败不影响本次回答。"""
    citations = list(result.get("citations") or [])
    degraded = bool(result.get("degraded"))
    try:
        conn = _conn()
    except (pymysql.MySQLError, OSError):
        return
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO `对话消息`(`会话编号`,`角色`,`内容`,`工具`,`引用`,`追踪号`,"
                        "`是否降级`) VALUES (%s,'user',%s,NULL,NULL,%s,0)",
                        (session_id, str(query)[:4000], str(result.get("trace_id") or "")))
            cur.execute("INSERT INTO `对话消息`(`会话编号`,`角色`,`内容`,`工具`,`引用`,`追踪号`,"
                        "`是否降级`,`耗时毫秒`) VALUES (%s,'assistant',%s,%s,%s,%s,%s,%s)",
                        (session_id, str(result.get("answer") or "")[:8000],
                         str(result.get("tool_name") or "") or None,
                         json.dumps(citations, ensure_ascii=False) if citations else None,
                         str(result.get("trace_id") or ""), 1 if degraded else 0, int(elapsed_ms)))
            cur.execute("UPDATE `对话会话` SET `消息数`=`消息数`+2, `最近时间`=NOW(),"
                        " `标题`=IF(`标题`='新对话', %s, `标题`) WHERE `编号`=%s",
                        (str(query).strip().replace("\n", " ")[:60] or "新对话", session_id))
            cur.execute("SELECT COUNT(*) AS c FROM `对话消息` WHERE `会话编号`=%s", (session_id,))
            if int((cur.fetchone() or {}).get("c") or 0) > SUMMARY_TRIGGER:
                summary = _build_summary(ctx, session_id)
                cur.execute("UPDATE `对话会话` SET `摘要`=%s WHERE `编号`=%s", (summary, session_id))
        conn.commit()
    except (pymysql.MySQLError, OSError):
        pass
    finally:
        conn.close()


def handle(ctx: ToolContext, query: str, term: str | None,
           session_id: int | None, client_history: Any = None) -> dict[str, Any]:
    """一次完整对话：定会话 → 取上下文 → 跑图 → 落库。"""
    import time

    check_quota(ctx)
    sid = ensure_session(ctx, session_id, str(query)[:60])
    turns, summary = load_history(ctx, sid)
    if summary:
        turns = [{"role": "assistant", "text": f"（此前对话摘要）{summary}"}, *turns]
    if not turns:
        # 没有服务端历史时，退回前端传的最近几轮（兼容旧调用）
        turns = [{"role": t.role, "text": t.text} for t in (client_history or [])][-RECENT_TURNS:]

    started = time.time()
    prev_tool = last_tool(ctx, sid)
    result = graph.run_chat(ctx, query, term=term, history=turns, last_tool=prev_tool)
    result["session_id"] = sid
    persist_turn(ctx, sid, query, result, int((time.time() - started) * 1000))
    return result


def _client_turns(client_history: Any) -> list[dict[str, str]]:
    """前端回传的最近几轮（仅在服务端历史不可用时使用）。"""
    return [{"role": t.role, "text": t.text}
            for t in (client_history or [])][-RECENT_TURNS:]


def handle_stream(ctx: ToolContext, query: str, term: str | None,
                  session_id: int | None,
                  client_history: Any = None) -> Iterator[dict[str, Any]]:
    """流式对话：事件原样转发，拿到最终答案后落库，再补上 session_id 发 done。

    存储不可用不阻塞回答：定会话/取历史失败时退回前端历史，本轮不留痕；
    回答照常流式给出——与 handle 的容错原则一致。
    """
    import time

    try:
        check_quota(ctx)
    except QuotaExceeded as exc:
        # 配额用尽：给一句明确的话术并直接终止，不进入取数与生成
        yield {"type": "error", "message": str(exc), "quota_exceeded": True}
        return

    sid: int | None = None
    turns: list[dict[str, str]] = []
    summary = ""
    prev_tool: str | None = None
    try:
        sid = ensure_session(ctx, session_id, str(query)[:60])
        turns, summary = load_history(ctx, sid)
        prev_tool = last_tool(ctx, sid)
    except Exception:
        sid = None
    if summary:
        turns = [{"role": "assistant", "text": f"（此前对话摘要）{summary}"}, *turns]
    if not turns:
        turns = _client_turns(client_history)

    started = time.time()
    for event in graph.run_chat_stream(ctx, query, term=term, history=turns,
                                       last_tool=prev_tool):
        if event.get("type") == "done" and sid is not None:
            result = {
                "answer": event.get("answer"),
                "degraded": event.get("degraded"),
                "trace_id": event.get("trace_id"),
                "tool_name": event.get("tool"),
                "citations": event.get("citations") or [],
            }
            persist_turn(ctx, sid, query, result, int((time.time() - started) * 1000))
            event["session_id"] = sid
        yield event
