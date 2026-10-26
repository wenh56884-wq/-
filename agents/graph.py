# agents/graph.py
# 职责：LangGraph 状态机编排——plan → tool → draft → critic → (retry | fallback)
# 依赖：langgraph.StateGraph / agents.critic / agents.tools / app.audit
# 说明：Critic 不过就带 mismatches 重写草稿，最多重试 MAX_RETRY 次；
#       仍不过则走「无数字」降级模板并在审计里标 degraded；每次核对都写 audit_log。

from __future__ import annotations

import uuid
from typing import Any, Callable, Mapping, TypedDict

from langgraph.graph import END, StateGraph

from agents import tools
from agents.critic import MAX_RETRY, CRITIC_VERSION, Verdict, render_fallback, verify
from agents.tools import ToolContext
from app.audit import audit_event

GRAPH_VERSION = "graph-v1"

# Graph 状态
class AgentState(TypedDict, total=False):
    ctx: ToolContext
    query: str
    term: str | None
    plan: dict[str, Any]
    tool_result: dict[str, Any]
    tool_name: str
    draft_fn: Callable[..., str]
    draft: str
    feedback: str
    attempts: int
    verdict: dict[str, Any]
    answer: str
    degraded: bool
    trace_id: str


# ----------------------------------------------------------------
# 1. 计划：根据角色与提问关键词选工具（学生端只能选本人工具）
# ----------------------------------------------------------------
def plan_node(state: AgentState) -> dict[str, Any]:
    """按提问关键词挑工具；学生端强制映射到本人工具，忽略一切学号提取结果。"""
    ctx: ToolContext = state["ctx"]
    query = str(state.get("query") or "")
    term = state.get("term")

    if ctx.actor_type == "student":
        tool_name = "my_recommendations" if any(k in query for k in ("推荐", "岗位", "工作")) \
            else "my_warning"
        return {"plan": {"tool": tool_name}, "tool_name": tool_name}

    tool_name = "class_overview"
    if any(k in query for k in ("班级列表", "班级目录", "有哪些班", "哪些班级", "学院", "院系")):
        tool_name = "class_list"
    elif any(k in query for k in ("预警", "风险", "名单", "挂科")):
        tool_name = "warning_list"
    elif any(k in query for k in ("画像", "标签", "个人", "四维")):
        tool_name = "student_profile"
    elif any(k in query for k in ("差距", "岗位", "能力", "就业")):
        tool_name = "career_gap"

    args: dict[str, Any] = {"term": term or ""}
    class_name = _extract_class_name(query)
    if class_name:
        args["class_name"] = class_name
    if tool_name in ("class_overview", "warning_list", "career_gap") and not class_name:
        args["class_name"] = _default_class(ctx)
    if tool_name == "student_profile":
        args["student_no"] = _extract_student_no(ctx, query)
    return {"plan": {"tool": tool_name, "args": args}, "tool_name": tool_name}


def _extract_class_name(query: str) -> str | None:
    """从提问里抠班级名（形如 AI2201 / RJ2201）。"""
    import re

    match = re.search(r"\b([A-Za-z]{2,4}\d{3,4})\b", query)
    return match.group(1) if match else None


def _default_class(ctx: ToolContext) -> str:
    """没点名班级时取本租户第一个有成绩的班（避免全班扫库）。"""
    rows = tools._query(
        "SELECT s.class_name AS class_name FROM student s "
        "JOIN score sc ON sc.student_id = s.id "
        "WHERE s.tenant_id = %s GROUP BY s.class_name ORDER BY s.class_name LIMIT 1",
        (ctx.tenant_id,),
    )
    return str(rows[0]["class_name"]) if rows else ""


def _extract_student_no(ctx: ToolContext, query: str) -> str:
    """提问里带学号就用它，否则取本人/本班第一个学生（教师端允许查任意本班学生）。"""
    import re

    match = re.search(r"\b([A-Za-z]{2}\d{6,8})\b", query)
    if match:
        return match.group(1)
    rows = tools._query(
        "SELECT s.student_no AS student_no FROM student s "
        "JOIN score sc ON sc.student_id = s.id AND sc.term = %s "
        "WHERE s.tenant_id = %s ORDER BY s.student_no LIMIT 1",
        (state_term(ctx), ctx.tenant_id),
    )
    return str(rows[0]["student_no"]) if rows else ""


def state_term(ctx: ToolContext) -> str:
    """回落到该租户最新有成绩的学期（供 SQL 兜底使用）。"""
    return tools._resolve_term(ctx, None)


# ----------------------------------------------------------------
# 2. 调工具
# ----------------------------------------------------------------
def tool_node(state: AgentState) -> dict[str, Any]:
    """调工具层的对应工具；越权按「无权限」处理，不抛给上层。"""
    ctx: ToolContext = state["ctx"]
    plan = state.get("plan") or {}
    name = str(plan.get("tool") or "")
    args: Mapping[str, Any] = plan.get("args") or {}
    try:
        if name == "class_list":
            result = tools.class_list(ctx)
        elif name == "warning_list":
            result = tools.warning_list(ctx, args.get("class_name", ""), args.get("term", ""))
        elif name == "student_profile":
            result = tools.student_profile(ctx, args.get("student_no", ""), args.get("term", ""))
        elif name == "career_gap":
            result = tools.career_gap(ctx, args.get("class_name", ""), args.get("term", ""))
        elif name == "my_warning":
            result = tools.my_warning(ctx, args.get("term") or None)
        elif name == "my_recommendations":
            result = tools.my_recommendations(ctx, args.get("term") or None)
        else:
            result = tools.class_overview(ctx, args.get("class_name", ""), args.get("term", ""))
    except PermissionError as exc:
        return {"tool_result": {"error": str(exc)}, "tool_name": name}
    return {"tool_result": dict(result), "tool_name": name}


# ----------------------------------------------------------------
# 3. 草稿（默认模板直引；可注入 LLM 版用于演示/幻觉复现）
# ----------------------------------------------------------------
def _template_draft(result: Mapping[str, Any], feedback: str = "") -> str:
    """把工具结果「原样直引」成一段话：不归纳、不估算、不换算。"""
    if not result:
        return "未查到相关数据。"
    if "error" in result:
        return "该数据你没有访问权限，请确认班级/学号是否属于本租户。"
    parts: list[str] = []
    if "classes" in result:
        parts.append(
            f"本租户共 {result.get('class_cnt')} 个班、{result.get('student_cnt')} 名学生。"
        )
        colleges: dict[str, list[Any]] = {}
        for row in (result.get("classes") or []):
            colleges.setdefault(str(row.get("college") or "未分配学院"), []).append(row)
        for college, rows in colleges.items():
            names = "、".join(str(row.get("class_name") or "") for row in rows)
            parts.append(f"{college}：{names} 共 {len(rows)} 个班。")
        parts.append("各班人数：" + "、".join(
            f"{row.get('class_name')} {row.get('headcount')} 人"
            for row in (result.get("classes") or [])) + "。")
    if "headcount" in result:
        parts.append(
            f"班级 {result.get('class_name')} 在 {result.get('term')} 学期共 "
            f"{result.get('headcount')} 人有成绩记录，平均绩点写实值 {result.get('avg_gpa')}，"
            f"挂科率 {result.get('fail_rate')}。"
        )
        dist = dict(result.get("warning_distribution") or {})
        if dist:
            parts.append("预警分布：" + "、".join(f"{k} {v} 人" for k, v in dist.items()) + "。")
    if "items" in result:
        parts.append(f"预警名单共命中 {result.get('count')} 人。")
        for item in (result.get("items") or [])[:3]:
            parts.append(
                f"{item.get('name')}（{item.get('student_no')}）风险分 {item.get('risk_score')}，"
                f"等级 {item.get('level')}；归因：{'；'.join(item.get('reasons') or []) or '无'}。"
            )
    if "gaps" in result:
        for gap in (result.get("gaps") or [])[:3]:
            parts.append(
                f"差距维度 {gap.get('dimension')}：岗位侧 {gap.get('demand_rate')}，"
                f"班级侧 {gap.get('class_rate')}，缺口 {gap.get('shortfall')}。"
            )
    if "dimensions" in result:
        dims = dict(result.get("dimensions") or {})
        parts.append("四维得分：" + "、".join(
            f"{k} {v}" for k, v in dims.items()) + "。")
        parts.append("标签：" + "、".join(result.get("tags") or []) + "。")
    if "risk_score" in result:
        parts.append(
            f"本人预警：风险分 {result.get('risk_score')}，等级 {result.get('level')}；"
            f"归因：{'；'.join(result.get('reasons') or []) or '无'}。"
        )
    if not parts:
        parts.append("已获取结构化结果，详见对应列表。")
    draft = "\n".join(parts)
    if feedback:
        draft = f"（按核对意见修正）\n{draft}"
    return draft


def draft_node(state: AgentState) -> dict[str, Any]:
    """生成草稿：优先用注入的 draft_fn（便于注入幻觉做拦截演示），否则模板直引。"""
    draft_fn = state.get("draft_fn")
    feedback = str(state.get("feedback") or "")
    attempts = int(state.get("attempts") or 0) + 1
    result = state.get("tool_result") or {}
    if draft_fn is not None:
        draft = str(draft_fn(result, feedback, attempts))
    else:
        draft = _template_draft(result, feedback)
    return {"draft": draft, "attempts": attempts}


# ----------------------------------------------------------------
# 4. Critic 核对
# ----------------------------------------------------------------
def critic_node(state: AgentState) -> dict[str, Any]:
    """逐条比对草稿数值与工具结果；每次核对都写审计（含 mismatches 摘要）。"""
    ctx: ToolContext = state["ctx"]
    result = state.get("tool_result") or {}
    verdict: Verdict = verify(str(state.get("draft") or ""), result)
    audit_event(
        actor_type=ctx.actor_type,
        actor_id=ctx.student_id or ctx.teacher_id or 0,
        action="critic.verify",
        target=str(state.get("trace_id") or ""),
        detail={
            "passed": verdict.passed,
            "attempt": int(state.get("attempts") or 0),
            "mismatches": verdict.mismatches[:5],
            "fuzzy": verdict.fuzzy[:5],
            "critic_version": CRITIC_VERSION,
        },
    )
    return {
        "verdict": verdict.to_dict(),
        "feedback": "" if verdict.passed else verdict.feedback(),
    }


def fallback_node(state: AgentState) -> dict[str, Any]:
    """超限降级：输出不含任何数字的模板话术。"""
    answer = render_fallback(state.get("tool_result") or {})
    return {"answer": answer, "degraded": True}


def accept_node(state: AgentState) -> dict[str, Any]:
    return {"answer": str(state.get("draft") or ""), "degraded": False}


def route_after_critic(state: AgentState) -> str:
    """通过→结束；重试次数用完→降级；否则回草稿重写。"""
    if bool((state.get("verdict") or {}).get("passed")):
        return "accept"
    if int(state.get("attempts") or 0) > MAX_RETRY:
        return "fallback"
    return "draft"


# ----------------------------------------------------------------
# 5. 图装配与对外入口
# ----------------------------------------------------------------
def build_graph():
    """装配并编译 LangGraph（plan → tool → draft → critic → accept/fallback）。"""
    builder = StateGraph(AgentState)
    builder.add_node("plan", plan_node)
    builder.add_node("tool", tool_node)
    builder.add_node("draft", draft_node)
    builder.add_node("critic", critic_node)
    builder.add_node("accept", accept_node)
    builder.add_node("fallback", fallback_node)

    builder.set_entry_point("plan")
    builder.add_edge("plan", "tool")
    builder.add_edge("tool", "draft")
    builder.add_edge("draft", "critic")
    builder.add_conditional_edges(
        "critic", route_after_critic,
        {"accept": "accept", "fallback": "fallback", "draft": "draft"},
    )
    builder.add_edge("accept", END)
    builder.add_edge("fallback", END)
    return builder.compile()


_GRAPH = None


def get_graph():
    """图单例（懒加载，避免导入即编译）。"""
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    return _GRAPH


def run_chat(
    ctx: ToolContext,
    query: str,
    term: str | None = None,
    claims: Mapping[str, Any] | None = None,
    *,
    draft_fn: Callable[..., str] | None = None,
    tool_result: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """跑一次对话：返回 answer / trace_id / degraded / verdict / attempts。

    draft_fn 可注入用于演示「幻觉被拦截」；tool_result 非空时跳过真实工具调用（离线测试用）。
    """
    trace_id = uuid.uuid4().hex[:12]
    state: AgentState = {
        "ctx": ctx,
        "query": str(query),
        "term": term,
        "attempts": 0,
        "feedback": "",
        "trace_id": trace_id,
    }
    if draft_fn is not None:
        state["draft_fn"] = draft_fn

    if tool_result is not None:
        # 离线模式：直接进 draft → critic（跳过取数）
        state["tool_result"] = dict(tool_result)
        state["tool_name"] = "injected"
        state["plan"] = {"tool": "injected"}
    else:
        graph = get_graph()
        state = dict(graph.invoke(state))

    if tool_result is not None:
        # 手动跑 draft → critic → accept/fallback（离线注入模式，不编译图）
        verdict: dict[str, Any] = {}
        while True:
            state.update(draft_node(state))
            state.update(critic_node(state))
            verdict = dict(state["verdict"])
            if verdict.get("passed") or int(state["attempts"]) > MAX_RETRY:
                break

        if verdict.get("passed"):
            state.update(accept_node(state))
        else:
            state.update(fallback_node(state))

    answer = str(state.get("answer") or "")
    degraded = bool(state.get("degraded"))
    audit_event(
        actor_type=ctx.actor_type,
        actor_id=ctx.student_id or ctx.teacher_id or 0,
        action="agent.chat",
        target=trace_id,
        detail={
            "query": str(query)[:120],
            "term": term,
            "tool": state.get("tool_name"),
            "attempts": int(state.get("attempts") or 0),
            "passed": bool((state.get("verdict") or {}).get("passed")),
            "degraded": degraded,
            "graph_version": GRAPH_VERSION,
            "critic_version": CRITIC_VERSION,
        },
    )
    return {
        "answer": answer,
        "trace_id": trace_id,
        "term": term,
        "degraded": degraded,
        "verdict": state.get("verdict") or {},
        "attempts": int(state.get("attempts") or 0),
        "tool_name": str(state.get("tool_name") or ""),
    }
