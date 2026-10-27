# agents/graph.py
# 职责：LangGraph 状态机编排——plan → tool → draft → critic → (retry | fallback)
# 依赖：langgraph.StateGraph / agents.critic / agents.tools / app.audit
# 说明：Critic 不过就带 mismatches 重写草稿，最多重试 MAX_RETRY 次；
#       仍不过则走「无数字」降级模板并在审计里标 degraded；每次核对都写 audit_log。

from __future__ import annotations

import json
import os
import re
import uuid
from typing import Any, Callable, Mapping, Sequence, TypedDict

from langgraph.graph import END, StateGraph

from agents import llm as llm_client
from agents import tools
from agents.critic import (
    MAX_RETRY,
    CRITIC_VERSION,
    Verdict,
    extract_numbers,
    render_fallback,
    verify,
)
from agents.tools import ToolContext
from app.audit import audit_event
from engine import rag as rag_engine

GRAPH_VERSION = "graph-v2"

# AGENT_LLM_DRAFT=0 可关闭「大模型润色」，退回机械直引（演示/对比用）
def _llm_draft_enabled() -> bool:
    return str(os.getenv("AGENT_LLM_DRAFT", "1")).strip().lower() not in ("0", "false", "off", "no")


# 寒暄 / 关于助手本身的提问：不该触发任何取数
_CHITCHAT_KEYS: tuple[str, ...] = (
    "你好", "您好", "hi", "hello", "早", "嗨", "谢谢", "感谢", "再见", "拜拜",
    "你是谁", "你能做什么", "能干什么", "会什么", "功能是", "怎么用", "如何使用",
)

# 知识库（RAG）：问制度/流程/文档内容 → 走 kb_search，不碰校园数据
_KB_KEYS: tuple[str, ...] = (
    "知识库", "制度", "规定", "流程", "手册", "sop", "faq", "常见问题",
    "报销", "请假", "考勤", "合同", "发票", "入职", "离职", "培训文档",
    "文档里", "文件里", "pdf", "制度里", "政策文件",
)

# 联网搜索：只有明确要「网上/实时」才触发，避免「最新的预警名单」被误判到网上
_WEB_KEYS: tuple[str, ...] = (
    "联网", "搜一下", "搜索一下", "上网查", "网上查", "网络搜索",
    "最新新闻", "实时行情", "今年政策", "最近政策", "公开招聘信息",
)

_EXTERNAL_TOOLS = ("kb_search", "web_search")

# 工作流：一句话触发已定义的多步流程
_WF_KEYS: tuple[str, ...] = ("工作流", "一键", "批量", "跑一遍", "走一遍", "自动执行", "自动跑")
_WF_PREFIX = ("帮我跑一遍", "帮我跑一下", "帮我执行", "跑一遍", "跑一下", "走一遍",
              "执行一下", "执行", "工作流", "一键", "批量", "自动执行", "自动跑", "帮我", "一下")

# Graph 状态
class AgentState(TypedDict, total=False):
    ctx: ToolContext
    query: str
    term: str | None
    history: list[dict[str, str]]
    plan: dict[str, Any]
    tool_result: dict[str, Any]
    tool_name: str
    last_tool: str | None
    draft_fn: Callable[..., str]
    draft: str
    draft_mode: str
    feedback: str
    attempts: int
    verdict: dict[str, Any]
    answer: str
    degraded: bool
    trace_id: str


# ----------------------------------------------------------------
# 1. 计划：根据角色与提问关键词选工具（学生端只能选本人工具）
# ----------------------------------------------------------------
def _intent_text(state: AgentState, query: str) -> str:
    """意图判定的依据：追问（如「为什么」「那他呢」）要带上最近一轮用户原话，
    否则「那些人怎么了」这类追问会因为没关键词而落到默认工具上。"""
    last_user = ""
    for turn in reversed(list(state.get("history") or [])):
        if str(turn.get("role") or "") == "user":
            last_user = str(turn.get("text") or "")
            break
    joined = f"{last_user} {query}".strip()
    # 追问占全长一半以上时才拼上下文，避免长句被无关历史污染
    if last_user and len(query) <= max(8, len(last_user) // 2):
        return joined
    return query


def _is_chitchat(query: str) -> bool:
    """寒暄 / 询问助手能力：不取数，直接对话。"""
    text = query.strip().lower()
    if len(text) <= 12 and any(key in text for key in _CHITCHAT_KEYS):
        return True
    return any(key in text for key in _CHITCHAT_KEYS) and len(text) <= 20


def plan_node(state: AgentState) -> dict[str, Any]:
    """按提问关键词挑工具；学生端强制映射到本人工具，忽略一切学号提取结果。"""
    ctx: ToolContext = state["ctx"]
    query = str(state.get("query") or "")
    term = state.get("term")

    if _is_chitchat(query):
        return {"plan": {"tool": "chitchat", "args": {}}, "tool_name": "chitchat"}

    # 外部事实：知识库优先于联网（有内部制度就先查内部，别去网上找）
    intent = _intent_text(state, query)
    last_tool = str(state.get("last_tool") or "")
    followup = _looks_like_followup(query)
    # 追问时把上一轮问题拼进检索串：「那超标了怎么办」单独检索是查不到东西的
    search_query = query
    if followup:
        prev = _last_user_text(state)
        if prev and prev not in query:
            search_query = f"{prev} {query}"

    if any(k in intent for k in _KB_KEYS):
        return {"plan": {"tool": "kb_search", "args": {"query": search_query}},
                "tool_name": "kb_search"}

    # 追问：短句 + 指代词，且上一轮就在查知识库/联网 → 沿用同一能力
    if last_tool in ("kb_search", "web_search") and followup:
        return {"plan": {"tool": last_tool, "args": {"query": search_query}},
                "tool_name": last_tool}

    if any(k in intent for k in _WF_KEYS):
        return {"plan": {"tool": "run_workflow", "args": {"name": _workflow_name(query)}},
                "tool_name": "run_workflow"}
    if any(k in intent for k in _WEB_KEYS):
        return {"plan": {"tool": "web_search", "args": {"query": search_query}},
                "tool_name": "web_search"}

    if ctx.actor_type == "student":
        tool_name = "my_recommendations" if any(k in intent for k in ("推荐", "岗位", "工作")) \
            else "my_warning"
        return {"plan": {"tool": tool_name}, "tool_name": tool_name}

    tool_name = "class_overview"
    if any(k in intent for k in ("班级列表", "班级目录", "有哪些班", "哪些班级", "学院", "院系")):
        tool_name = "class_list"
    elif any(k in intent for k in ("预警", "风险", "名单", "挂科")):
        tool_name = "warning_list"
    elif any(k in intent for k in ("画像", "标签", "个人", "四维")):
        tool_name = "student_profile"
    elif any(k in intent for k in ("差距", "岗位", "能力", "就业")):
        tool_name = "career_gap"

    args: dict[str, Any] = {"term": term or ""}
    # 班级名既能从本次提问抠，也能从历史追问里继承（「那这个班呢」）
    class_name = _extract_class_name(query) or _extract_class_name(intent)
    if class_name:
        args["class_name"] = class_name
    if tool_name in ("class_overview", "warning_list", "career_gap") and not class_name:
        args["class_name"] = _default_class(ctx)
    if tool_name == "student_profile":
        args["student_no"] = _extract_student_no(ctx, query or intent)
    return {"plan": {"tool": tool_name, "args": args}, "tool_name": tool_name}


def _extract_class_name(query: str) -> str | None:
    """从提问里抠班级名（形如 AI2201 / RJ2201）。"""
    import re

    match = re.search(r"\b([A-Za-z]{2,4}\d{3,4})\b", query)
    return match.group(1) if match else None


def _last_user_text(state: AgentState) -> str:
    for turn in reversed(list(state.get("history") or [])):
        if str(turn.get("role") or "") == "user" and str(turn.get("text") or "").strip():
            return str(turn["text"]).strip()
    return ""


def _looks_like_followup(query: str) -> bool:
    """短句 + 指代/追加词 → 视为追问（长句自成问题，不沿用上一轮能力）。"""
    text = str(query or "").strip()
    if not text or len(text) > 24:
        return False
    markers = ("那", "这个", "那个", "它", "还有", "再", "呢", "为什么", "怎么算", "具体")
    return any(m in text for m in markers)


def _workflow_name(query: str) -> str:
    """从「帮我跑一遍求职体检」里剥出工作流名。

    只剥固定前缀词，剥不干净就带着残余去匹配——匹配失败会返回「没找到」，
    不会瞎猜一个流程去执行。
    """
    name = str(query or "").strip()
    for token in _WF_PREFIX:
        name = name.replace(token, "")
    return name.strip(" ：:，,。.帮我想请")


def _default_class(ctx: ToolContext) -> str:
    """没点名班级时取本租户第一个有成绩的班（避免全班扫库）。"""
    rows = tools._query(
        "SELECT s.`班级` AS class_name FROM `学生` s "
        "JOIN `成绩` sc ON sc.`学生编号` = s.`编号` "
        "WHERE s.`租户编号` = %s GROUP BY s.`班级` ORDER BY s.`班级` LIMIT 1",
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
        "SELECT s.`学号` AS student_no FROM `学生` s "
        "JOIN `成绩` sc ON sc.`学生编号` = s.`编号` AND sc.`学期` = %s "
        "WHERE s.`租户编号` = %s ORDER BY s.`学号` LIMIT 1",
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
    if name == "chitchat":
        # 纯对话：不碰任何数据
        return {"tool_result": {"mode": "chitchat"}, "tool_name": "chitchat"}
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
        elif name == "kb_search":
            result = tools.kb_search(ctx, args.get("query") or "", top_k=4)
        elif name == "web_search":
            result = tools.web_search(ctx, args.get("query") or "", top_k=5)
        elif name == "run_workflow":
            result = tools.run_workflow(ctx, args.get("name") or "")
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
    return draft


# ---- LLM 润色提示词：把「只能直引」讲成模型听得懂的话 ----
_DRAFT_SYSTEM = (
    "你是「启航 · 生涯与岗位匹配系统」的智能助手，面对高校师生做学业预警、岗位匹配类答疑。\n"
    "你说话要像一个靠谱、干练的辅导员：先给结论，再补 1~2 句依据，必要时给一句可执行的建议。\n"
    "中文口语表达，不用 Markdown 标题、不用项目符号堆砌、不要说「根据工具返回结果」。\n"
    "\n"
    "## 铁律（违反即回答作废）\n"
    "1. 只能陈述给定事实里存在的内容，禁止补充任何数据、背景或推测。\n"
    "2. 所有数值必须**原样照抄**「允许引用的数值」列表里的写法："
    "不得换算单位、不得换算百分比、不得四舍五入、不得改写成中文数字（如「六门」「三成」）。\n"
    "3. 不得出现「约 / 大概 / 估计 / 大约 / 差不多 / 左右 / 似乎」这类模糊词。\n"
    "4. 不要臆造名单里没有的人名、班级名或岗位名。\n"
    "5. 给建议时同样禁止出现任何数字（如「前 5 名」「重点盯 3 个人」），"
    "改用「名单里风险最高的几位」这类不带数字的说法。\n"
    "6. 正文控制在 200 字以内，句子短，别写公文腔。"
)

_CHAT_SYSTEM = (
    "你是「启航 · 生涯与岗位匹配系统」的智能助手，面对高校师生做学业预警、岗位匹配、"
    "企业制度与流程答疑。\n"
    "当前是闲聊或关于你自身能力的提问，没有查询任何数据。\n"
    "要求：中文口语、简短友好（120 字以内）。可以说明你能做的事——"
    "查班级概貌与预警名单、看学生画像、分析班级与岗位的能力差距、"
    "从企业知识库里查制度与流程（会给出文档与页码）、按已定义的工作流一键跑多步流程；"
    "如果被问到实时信息，如实说你能否联网。"
    "**本轮绝对禁止输出任何阿拉伯数字或中文数字**，不要编造任何数据，"
    "也不要承诺做不到的事。结尾可以邀请对方提出具体问题。"
)

# 知识库/联网问答的系统提示：只许用检索到的原文，且必须标引用
_RAG_SYSTEM = (
    "你是「启航」的知识库问答助手，只能依据【检索到的原文】回答，禁止使用任何模型记忆。\n"
    "硬性要求：\n"
    "1. 每条结论后面必须标引用编号，如 [1]；编号只能来自本次检索结果。\n"
    "2. 引用原文时用「」逐字摘抄，一个字都不能改。\n"
    "3. 原文里没有的数字、日期、比例一律不得出现；不得换算（30 天不能写成一个月）。\n"
    "4. 原文没说的内容，直接回答「知识库里没有相关规定」，不要推测。\n"
    "5. 中文口语，200 字以内，不要写 Markdown 标题。"
)


def _best_sentence(text: str, query: str) -> str:
    """从块里挑一句与提问最贴的原文句：逐字返回，不改写（模板兜底用）。

    先把块内换行折成空格再切句——制度原文常为排版手动换行，
    直接按 \\n 切会把一句话劈成两半，引用出来就是残句。
    """
    flat = re.sub(r"\s*\n\s*", "", str(text or ""))
    sentences = [s.strip() for s in re.split(r"(?<=[。！？；!?;])", flat) if s.strip()]
    if not sentences:
        return ""
    q = {query[i:i + 2] for i in range(max(1, len(query) - 1))}
    best, best_score = sentences[0], -1
    for s in sentences:
        score = sum(1 for g in q if g and g in s)
        if score > best_score:          # 同分取靠前的句子，保证确定性
            best, best_score = s, score
    if len(best) <= 160:
        return best
    # 过长时截到最后一个逗号，且**不补句号**——补了就不再是原文子串，引用校验会驳回
    return best[:160].rsplit("，", 1)[0]


def _external_draft(state: AgentState, result: Mapping[str, Any]) -> str:
    """知识库/联网的模板稿：只直引原文片段，不归纳、不补数字。"""
    tool = str(state.get("tool_name") or "")
    query = str(state.get("query") or "")

    if tool == "kb_search":
        hits = result.get("hits") or []
        if not hits:
            return ("知识库里没有检索到与这个问题相关的内容。"
                    "可以换个说法，或者让老师先把相关制度文档传进知识库。")
        lines = ["知识库里查到这些原文（未做改写）："]
        for i, h in enumerate(hits[:2], start=1):
            page = f"第 {h['page']} 页" if h.get("page") else f"第 {h['chunk_no']} 块"
            sent = _best_sentence(str(h.get("text") or ""), query)
            lines.append(f"[{i}]《{h.get('title')}》{page}：「{sent}」")
        return "\n".join(lines)

    if not result.get("configured"):
        return "当前没有配置联网搜索，我查不了实时信息。可以让我先从知识库或校内数据里找。"
    if result.get("error"):
        return f"联网搜索这次没成功（{result.get('error')}），我不能凭空给结论。"
    rows = result.get("results") or []
    if not rows:
        return "网上没有搜到相关结果，我不能凭空给结论。"
    lines = ["联网搜到这些结果（未做归纳）："]
    for i, r in enumerate(rows[:3], start=1):
        lines.append(f"[{i}] {r.get('title')}：{str(r.get('snippet') or '')[:90]}")
    return "\n".join(lines)


def _workflow_draft(result: Mapping[str, Any]) -> str:
    """工作流的模板稿：逐步成功/失败，不含任何数字（避免与 Critic 的口径冲突）。"""
    status = str(result.get("status") or "")
    if status == "list":
        items = [str(i.get("name")) for i in (result.get("available") or [])]
        return ("可以直接跑这些工作流：" + "、".join(items)
                + "。说「跑一遍<名字>」就行。") if items else "当前没有可用的工作流。"
    if status in ("empty", "not_found", "invalid"):
        return str(result.get("summary") or "这个工作流现在跑不了。")

    lines = [f"已按工作流「{result.get('name')}」执行："]
    for st in result.get("steps") or []:
        mark = "✅" if st.get("status") == "success" else "❌"
        ok = st.get("status") == "success"
        lines.append(f"{mark} {st.get('title') or st.get('tool')}"
                     + ("" if ok else f"：{st.get('error')}"))
    lines.append("全部步骤已成功执行。" if status == "success" else "流程在中途失败，已停止后续步骤。")
    return "\n".join(lines)


def _evidence_lines(result: Mapping[str, Any], tool: str, limit: int = 4) -> str:
    """把检索结果整理成「[n] 标题（页码）原文」——模型只能从这里编号。"""
    lines: list[str] = []
    if tool == "kb_search":
        for i, h in enumerate((result.get("hits") or [])[:limit], start=1):
            page = f"第{h['page']}页" if h.get("page") else f"第{h['chunk_no']}块"
            lines.append(f"[{i}]《{h.get('title')}》{page}：{h.get('text')}")
    else:
        for i, r in enumerate((result.get("results") or [])[:limit], start=1):
            lines.append(f"[{i}] {r.get('title')}（{r.get('url')}）：{r.get('snippet')}")
    return "\n\n".join(lines) if lines else "（没有检索到任何原文）"


def _llm_external_draft(state: AgentState, result: Mapping[str, Any],
                        feedback: str) -> str | None:
    """知识库/联网的模型稿：仍受引用校验约束，不过就退回模板直引。"""
    ctx: ToolContext = state["ctx"]
    tool = str(state.get("tool_name") or "")
    parts = [f"【提问】{state.get('query') or ''}"]
    history = _history_text(state)
    if history:
        parts.append(f"【前面对话】\n{history}")
    parts.append("【检索到的原文】（每条前面的 [n] 就是可用的引用编号）\n"
                 + _evidence_lines(result, tool))
    if feedback:
        parts.append(f"【上一稿被退回的原因，务必逐条改正】\n{feedback}")
    return llm_client.generate_reply(ctx.actor_type, system_prompt=_RAG_SYSTEM,
                                     user_prompt="\n\n".join(parts), tag="rag")


def _facts_blob(result: Mapping[str, Any], limit: int = 3000) -> str:
    """工具结果原文（给模型看的事实来源）。"""
    try:
        blob = json.dumps(result, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        blob = str(result)
    return blob[:limit]


def _allowed_numbers(result: Mapping[str, Any]) -> list[str]:
    """结果里出现过的数值原文清单：模型只能照抄这些写法。

    注意走的是 Critic 同一套抽数方法——模型抄这里的值，核对必然命中。
    """
    blob = _facts_blob(result)
    return sorted({claim.raw for claim in extract_numbers(blob)}, key=lambda s: (-len(s), s))


def _history_text(state: AgentState, limit: int = 4) -> str:
    """最近几轮对话，给模型做上下文（不参与任何授权判断）。"""
    turns = list(state.get("history") or [])[-limit:]
    lines: list[str] = []
    for turn in turns:
        role = "用户" if str(turn.get("role") or "") == "user" else "助手"
        text = str(turn.get("text") or "").strip()
        if text:
            lines.append(f"{role}：{text[:300]}")
    return "\n".join(lines)


def _llm_draft(state: AgentState, result: Mapping[str, Any], feedback: str) -> str | None:
    """让 LLM 把结构化结果说成人话；返回值仍需过 Critic，不可用时返回 None。"""
    ctx: ToolContext = state["ctx"]
    query = str(state.get("query") or "")
    who = "教师" if ctx.actor_type == "teacher" else "学生"
    tool_name = str(state.get("tool_name") or "")

    parts = [f"【身份】{who}", f"【提问】{query}"]
    history = _history_text(state)
    if history:
        parts.append(f"【前面对话】\n{history}")
    parts.append(f"【工具】{tool_name}")
    parts.append(f"【事实原文】\n{_facts_blob(result)}")
    allowed = _allowed_numbers(result)
    if allowed:
        parts.append("【允许引用的数值（必须原样照抄，禁止任何改写）】\n" + "、".join(allowed))
    if feedback:
        parts.append(f"【上一稿被退回的原因，务必逐条改正】\n{feedback}")
    parts.append("请直接输出回复正文，不要加任何前缀或说明。")

    return llm_client.generate_reply(
        ctx.actor_type,
        system_prompt=_DRAFT_SYSTEM,
        user_prompt="\n\n".join(parts),
        tag="draft",
    )


def _llm_chitchat(state: AgentState) -> str | None:
    """寒暄 / 能力提问：纯对话，不带任何数据。"""
    ctx: ToolContext = state["ctx"]
    parts = [f"【提问】{state.get('query') or ''}"]
    history = _history_text(state)
    if history:
        parts.append(f"【前面对话】\n{history}")
    return llm_client.generate_reply(
        ctx.actor_type,
        system_prompt=_CHAT_SYSTEM,
        user_prompt="\n\n".join(parts),
        tag="chitchat",
    )


def _external_verify(answer: str, result: Mapping[str, Any],
                     tool: str) -> tuple[bool, list[str]]:
    """知识库/联网的验收判据：引用编号 + 逐字引文 + 数字不越界。

    没有命中时反过来要求「不许出现数字、必须明说没查到」——
    这类场景最容易用模型记忆补一段看似合理的内容。
    """
    text = str(answer or "")
    if tool == "kb_search":
        hits = result.get("hits") or []
        if not hits:
            if re.search(r"\d", text):
                return False, ["知识库没有命中，回答里却出现了数字"]
            if not any(k in text for k in ("没有", "未", "查不到", "没查到")):
                return False, ["知识库没有命中，回答没有明确说明查不到"]
            return True, []
        return rag_engine.verify_citations(text, hits)

    if not result.get("configured") or result.get("error") or not (result.get("results") or []):
        if re.search(r"\d", text):
            return False, ["没有可用的搜索结果，回答里却出现了数字"]
        if not any(k in text for k in ("没有", "未", "失败", "不能")):
            return False, ["没有可用的搜索结果，回答没有说明原因"]
        return True, []
    snippets = [{"text": f"{r.get('title')} {r.get('snippet')}"} for r in result["results"]]
    return rag_engine.verify_citations(text, snippets)


def draft_node(state: AgentState) -> dict[str, Any]:
    """生成草稿：注入优先（演示幻觉拦截）→ LLM 润色 → 模板直引兜底。

    生成顺序：第 1、2 稿用 LLM（第 2 稿带 Critic 退回意见做修正），
    第 3 稿起回到模板直引保底——模板是原样引用、几乎必然通过审核，
    即使大模型连续说错数字，用户拿到的也是有依据的版本，而不是无数值的降级话术。
    """
    draft_fn = state.get("draft_fn")
    feedback = str(state.get("feedback") or "")
    attempts = int(state.get("attempts") or 0) + 1
    result = state.get("tool_result") or {}

    mode = "template"
    if draft_fn is not None:
        draft = str(draft_fn(result, feedback, attempts))
        mode = "injected"
    elif (result or {}).get("mode") == "chitchat":
        fallback_text = (
            "你好，我是启航智能助手。我可以帮你查班级概貌与预警名单、看学生的四维画像，"
            "分析班级与岗位的能力差距，也能从企业知识库里查制度流程（会给出文档与页码），"
            "还能按已定义的工作流一键跑多步流程。比如直接问「报销的住宿标准是多少」就行。"
        )
        draft = _llm_chitchat(state) or fallback_text
        mode = "chitchat"
    elif str(state.get("tool_name") or "") == "run_workflow":
        draft = _workflow_draft(result)
        mode = "workflow"
    elif str(state.get("tool_name") or "") in _EXTERNAL_TOOLS:
        # 知识库/联网：模型先写，引用校验不过就退回「原文直引」模板
        if attempts >= 3 or not _llm_draft_enabled():
            draft = _external_draft(state, result)
        else:
            draft = _llm_external_draft(state, result, feedback) or _external_draft(state, result)
        mode = "rag"
    elif attempts >= 3 or not _llm_draft_enabled():
        draft = _template_draft(result, feedback)
        mode = "template"
    else:
        draft = _llm_draft(state, result, feedback) or _template_draft(result, feedback)
        mode = "draft" if draft else "template"
    if not draft:
        draft = _template_draft(result, feedback)
        mode = "template"
    return {"draft": draft, "attempts": attempts, "draft_mode": mode}


# ----------------------------------------------------------------
# 4. Critic 核对
# ----------------------------------------------------------------
def critic_node(state: AgentState) -> dict[str, Any]:
    """逐条比对草稿数值与工具结果；每次核对都写审计（含 mismatches 摘要）。"""
    ctx: ToolContext = state["ctx"]
    result = state.get("tool_result") or {}
    tool = str(state.get("tool_name") or "")
    if tool in _EXTERNAL_TOOLS:
        passed, problems = _external_verify(str(state.get("draft") or ""), result, tool)
        verdict = {"passed": passed, "mismatches": problems, "fuzzy": []}
        feedback = "" if passed else "；".join(problems)
    else:
        checked: Verdict = verify(str(state.get("draft") or ""), result)
        verdict = checked.to_dict()
        feedback = "" if checked.passed else checked.feedback()
    audit_event(
        actor_type=ctx.actor_type,
        actor_id=ctx.student_id or ctx.teacher_id or 0,
        action="critic.verify",
        target=str(state.get("trace_id") or ""),
        detail={
            "passed": bool(verdict.get("passed")),
            "attempt": int(state.get("attempts") or 0),
            "tool": tool,
            "mismatches": list(verdict.get("mismatches") or [])[:5],
            "fuzzy": list(verdict.get("fuzzy") or [])[:5],
            "critic_version": CRITIC_VERSION,
        },
    )
    return {"verdict": verdict, "feedback": feedback}


def fallback_node(state: AgentState) -> dict[str, Any]:
    """超限降级：知识库/联网退回原文直引；其它场景输出不含数字的模板话术。"""
    result = state.get("tool_result") or {}
    if str(state.get("tool_name") or "") in _EXTERNAL_TOOLS:
        return {"answer": _external_draft(state, result), "degraded": True}
    answer = render_fallback(result)
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
    history: Sequence[Mapping[str, str]] | None = None,
    last_tool: str | None = None,
) -> dict[str, Any]:
    """跑一次对话：返回 answer / trace_id / degraded / verdict / attempts。

    draft_fn 可注入用于演示「幻觉被拦截」；tool_result 非空时跳过真实工具调用（离线测试用）；
    history 是前端回传的最近几轮对话，只作为 LLM 上下文，不参与任何鉴权。
    """
    trace_id = uuid.uuid4().hex[:12]
    turns: list[dict[str, str]] = []
    for item in list(history or [])[-8:]:
        role = str(item.get("role") or "")
        text = str(item.get("text") or "").strip()
        if role in ("user", "assistant") and text:
            turns.append({"role": role, "text": text[:500]})
    state: AgentState = {
        "ctx": ctx,
        "query": str(query),
        "term": term,
        "history": turns,
        "last_tool": last_tool,
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
            "draft_mode": str(state.get("draft_mode") or ""),
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
        # 引用清单（知识库给页码、联网给 URL）：前端据此渲染可点开的出处
        "citations": list((state.get("tool_result") or {}).get("citations") or []),
    }
