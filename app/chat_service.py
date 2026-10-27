# app/chat_service.py
# 职责：把「一次对话」从请求变成可追溯的会话——落库、取上下文、写引用。
# 依赖：agents.graph / app.audit / app.config / pymysql
# 铁律：
#   1. 上下文只从数据库取本人会话；不接受前端指定「别的会话」。
#   2. 摘要由规则拼装（首轮问题 + 最近问题），不调用模型二次生成，避免摘要本身说错话。
#   3. 引用清单原样存库，事后可核对「这句话当时引用的是哪一段」。

from __future__ import annotations

import json
from typing import Any, Mapping

import pymysql

from agents import graph
from agents.tools import ToolContext
from app.config import get_settings

RECENT_TURNS = 8          # 直接带进上下文的最近轮数
SUMMARY_TRIGGER = 12      # 超过这么多条消息就开始拼摘要


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
