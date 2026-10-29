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
from collections.abc import Iterator
from queue import Queue
from threading import Thread
from typing import Any, Callable, Mapping, Sequence, TypedDict

from langgraph.graph import END, StateGraph

from agents import llm as llm_client
from agents import intents as intents_cfg
from agents import teacher_agent
from agents import tools, auto_plan
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

GRAPH_VERSION = "graph-v5"

# AGENT_LLM_DRAFT=0 可关闭「大模型润色」，退回机械直引（演示/对比用）
def _llm_draft_enabled() -> bool:
    return str(os.getenv("AGENT_LLM_DRAFT", "1")).strip().lower() not in ("0", "false", "off", "no")


# 寒暄 / 关于助手本身的提问：不该触发任何取数
# 词表已配置化（rules/agent_intents.json 可覆盖）：商业化时实施方按客户问法增词，改完即生效
_CHITCHAT_KEYS = lambda: tuple(intents_cfg.section("chitchat"))  # noqa: E731

# 知识库（RAG）：问制度/流程/文档内容 → 走 kb_search，不碰校园数据
_KB_KEYS = lambda: tuple(intents_cfg.section("kb"))  # noqa: E731

# 联网搜索：只有明确要「网上/实时」才触发，避免「最新的预警名单」被误判到网上
_WEB_KEYS = lambda: tuple(intents_cfg.section("web"))  # noqa: E731

_EXTERNAL_TOOLS = ("kb_search", "web_search")

# 工作流：一句话触发已定义的多步流程
_WF_KEYS = lambda: tuple(intents_cfg.section("workflow"))  # noqa: E731
_WF_PREFIX = lambda: tuple(intents_cfg.section("workflow_prefix"))  # noqa: E731

# 引导式追问：答完后给用户 2~3 条「接下来可以问什么」（商业化产品化关键交互）
# 铁律：句子里不许出现数字（与降级话术同一红线），只描述可问的能力
_FOLLOWUP_BY_TOOL: dict[str, tuple[str, ...]] = {
    "class_overview": ("这个班这学期预警名单有哪些人",
                       "看下某个学生的四维画像（直接说姓名或学号）",
                       "这个班和岗位要求的能力差距在哪"),
    "class_list": ("看下其中一个班的整体情况", "哪个班预警人数最多"),
    "warning_list": ("这些学生里谁的风险最集中", "看下某个学生的画像（直接说姓名或学号）",
                     "这个班的预警阈值是怎么定的"),
    "student_profile": ("这个学生和目标岗位的差距在哪", "这个班整体情况怎么样"),
    "career_gap": ("班级侧哪个维度最容易补上来", "这个班这学期的就业意向分布"),
    "warning_thresholds": ("这个班的预警名单有哪些人", "阈值调整要走哪个功能页面"),
    "my_warning": ("我的岗位推荐有哪些", "知识库里有没有帮扶相关的制度"),
    "my_recommendations": ("我最近有没有学业预警", "这些岗位要求的证书知识库里有吗"),
    "kb_search": ("换一种说法再查一次", "这个问题校园数据里能不能看"),
    "web_search": ("这个问题知识库里有没有规定", "回到校园数据里继续查"),
    "run_workflow": ("看看刚才跑出来的名单", "帮我跑一遍另一个工作流"),
}
_FOLLOWUP_DEFAULT: tuple[str, ...] = ("换个说法再问一次", "看看别的班级或学生的情况")

# Graph 状态
class AgentState(TypedDict, total=False):
    ctx: ToolContext
    query: str
    term: str | None
    history: list[dict[str, str]]
    plan: dict[str, Any]
    tool_result: dict[str, Any]
    tool_name: str
    planner: str      # "graph"=确定性路由 / "auto"=模型自主选工具（AGENT_MODE=auto）
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
    if len(text) <= 12 and any(key in text for key in _CHITCHAT_KEYS()):
        return True
    return any(key in text for key in _CHITCHAT_KEYS()) and len(text) <= 20


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

    # 自主规划（可切换，AGENT_MODE=auto）：模型自己从工具清单里选。
    # 只替换「选哪个工具」，执行与校验仍走下面的确定性节点；
    # 模型不可用/选不出来/选了越权工具 → 返回 None，自动退回确定性路由。
    if auto_plan.auto_mode_enabled():
        picked = auto_plan.plan_with_llm(ctx, query, term, list(state.get("history") or []))
        if picked:
            return {"plan": {"tool": picked["tool"], "args": picked.get("args") or {}},
                    "tool_name": picked["tool"], "planner": "auto"}
    followup = _looks_like_followup(query)
    # 追问时把上一轮问题拼进检索串：「那超标了怎么办」单独检索是查不到东西的
    search_query = query
    if followup:
        prev = _last_user_text(state)
        if prev and prev not in query:
            search_query = f"{prev} {query}"

    # 学生端「本人数据」意图要排在知识库**之前**：否则「我的成绩」「我的学分」
    # 会被知识库词表里的「学分」这类制度词抢走，答出一堆管理办法而不是本人数据。
    if ctx.actor_type == "student":
        personal = _student_data_tool(intent)
        if personal:
            return {"plan": {"tool": personal, "args": _student_tool_args(personal, query)},
                    "tool_name": personal}

    if any(k in intent for k in _KB_KEYS()):
        return {"plan": {"tool": "kb_search", "args": {"query": search_query}},
                "tool_name": "kb_search"}

    # 追问：短句 + 指代词，且上一轮就在查知识库/联网 → 沿用同一能力
    if last_tool in ("kb_search", "web_search") and followup:
        return {"plan": {"tool": last_tool, "args": {"query": search_query}},
                "tool_name": last_tool}

    if any(k in intent for k in _WF_KEYS()):
        return {"plan": {"tool": "run_workflow", "args": {"name": _workflow_name(query)}},
                "tool_name": "run_workflow"}
    if any(k in intent for k in _WEB_KEYS()):
        return {"plan": {"tool": "web_search", "args": {"query": search_query}},
                "tool_name": "web_search"}

    if ctx.actor_type == "student":
        tool_name = _student_default_tool(intent)
        return {"plan": {"tool": tool_name}, "tool_name": tool_name}

    # 教师端：意图路由与参数抠取全部下沉到 teacher_agent 能力层
    return dict(teacher_agent.plan_teacher(ctx, intent, query, term))


# 学生端「本人数据」意图表：命中即选工具，**未命中返回 None** 继续走后面的分支。
# 只列明确指向本人数据的问法；「推荐 / 岗位」这类留给下面的默认分支，
# 这样「实习管理办法」仍会正确落到知识库，而不是被塞进某个数据工具。
_STUDENT_DATA_ROUTES: tuple[tuple[str, tuple[str, ...]], ...] = (
    # agent-entry-v2：招考/面试/题库放最前，具体词优先于宽泛词
    #（「招考公告」要在 my_notices 的「公告」之前被吃掉）
    ("question_bank_lookup", ("面试题", "题库", "会问什么", "都会问", "常问",
                              "面试问什么", "面试一般")),
    ("my_interviews", ("面试记录", "面试历史", "面试成绩", "我面过",
                       "模拟面试成绩", "面试了多少", "面过几场")),
    ("exam_notices", ("招考", "公务员考试", "事业单位招聘", "国考", "省考", "报名截止")),
    # 预测要排在成绩之前：问「预测一下我下学期的绩点」时，
    # 「绩点」会先被成绩路由吃掉，答成历史成绩而不是预测。
    ("my_forecast", ("预测", "下学期", "走势", "未来", "会怎样", "会不会挂")),
    ("my_grades", ("成绩", "成绩单", "分数", "绩点", "均分", "考了多少")),
    ("my_career_forecast", ("竞争力", "上岸", "胜算", "把握", "考公", "考研", "考编", "报考")),
    ("my_notices", ("通知", "消息", "公告")),
    ("competition_guide", ("竞赛", "比赛", "挑战杯")),
    ("my_career_guide", ("规划", "怎么准备", "怎么规划", "发展方向")),
    ("kg_major_skills", ("专业学什么", "能学到什么", "专业能学")),
)


def _student_data_tool(intent: str) -> str | None:
    """学生端数据意图路由：命中返回工具名，未命中返回 None。

    放在知识库分支之前调用，原因是知识库词表含「学分 / 实习 / 管理办法」等词，
    学生问「我的成绩怎么样」时会被误判成查制度文档。
    """
    for name, keywords in _STUDENT_DATA_ROUTES:
        if any(k in intent for k in keywords):
            return name
    return None


def _student_tool_args(tool_name: str, query: str) -> dict[str, Any]:
    """按工具从提问里抠参数；抠不到就留空——工具层对空参有明确语义（不猜）。"""
    import re

    args: dict[str, Any] = {}
    if tool_name == "exam_notices":
        # 先剥掉「招考」再匹配目标词：「招考公告」里含子串「考公」，不剥会误判成考公
        text = query.replace("招考", "")
        for word, code in (("考公", "civil"), ("公务员", "civil"), ("国考", "civil"),
                           ("省考", "civil"), ("考编", "institution"),
                           ("事业单位", "institution"), ("考研", "postgraduate"),
                           ("研究生", "postgraduate")):
            if word in text:
                args["exam_type"] = code
                break
        quoted = re.search(r"[\"“']([^\"”']{1,30})[\"”']", query)
        if quoted:
            args["keyword"] = quoted.group(1)
    elif tool_name == "question_bank_lookup":
        quoted = re.search(r"[\"“']([^\"”']{1,30})[\"”']", query)
        if quoted:
            args["query"] = quoted.group(1)
        else:
            # 去掉「面试会问什么」这类虚词后，剩余连续汉字当检索词
            cleaned = re.sub(r"面试|题库|一般|都会|会问|什么|哪些|有|的|吗|？|\?", "", query)
            cleaned = cleaned.strip(" 　，。")
            if len(cleaned) >= 2:
                args["query"] = cleaned[:20]
    return args


def _student_default_tool(intent: str) -> str:
    """学生端兜底路由（知识库 / 联网 / 工作流都没命中时）。"""
    if any(k in intent for k in ("推荐", "岗位", "工作")):
        return "my_recommendations"
    if any(k in intent for k in ("技能", "需要学", "要学什么")):
        return "kg_skill_jobs"
    return "my_warning"


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
    for token in _WF_PREFIX():
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
def _dispatch(ctx: ToolContext, name: str, args: Mapping[str, Any]) -> dict[str, Any]:
    """工具名 → 实际调用。身份一律只用 ctx，args 里只放业务参数（班级、学期、关键词）。

    学生端工具（my_*）内部强制用 ctx.student_id 取本人数据，所以即便 args 里
    被塞进别人的学号也无效——这是铁律 2（身份只来自后端登录态）的兜底。
    未知工具名兜底到 class_overview，保持改造前的行为。
    """
    a = args
    if name == "class_list":
        return tools.class_list(ctx)
    if name == "warning_thresholds":
        return tools.get_warning_thresholds(ctx, str(a.get("class_name") or ""))
    if name == "warning_list":
        return tools.warning_list(ctx, a.get("class_name", ""), a.get("term", ""),
                                  level=a.get("level"))
    if name == "student_profile":
        return tools.student_profile(ctx, a.get("student_no", ""), a.get("term", ""))
    if name == "career_gap":
        return tools.career_gap(ctx, a.get("class_name", ""), a.get("term", ""))
    if name == "student_grades":
        return tools.student_grades(ctx, a.get("student_no", ""))
    if name == "student_forecast":
        return tools.student_forecast(ctx, a.get("student_no", ""))
    if name == "my_grades":
        return tools.my_grades(ctx)
    if name == "my_forecast":
        return tools.my_forecast(ctx)
    if name == "my_career_forecast":
        return tools.my_career_forecast(ctx, a.get("goal", ""))
    if name == "my_warning":
        return tools.my_warning(ctx, a.get("term") or None)
    if name == "my_recommendations":
        return tools.my_recommendations(ctx, a.get("term") or None)
    if name == "my_notices":
        return tools.my_notices(ctx, limit=int(a.get("limit") or 20))
    if name == "my_career_guide":
        return tools.my_career_guide(ctx, a.get("term") or None)
    if name == "competition_guide":
        return tools.competition_guide(ctx, str(a.get("track") or "就业"),
                                       str(a.get("direction") or ""))
    if name == "search_jobs":
        return tools.search_jobs(ctx, a.get("query") or "", limit=int(a.get("limit") or 20))
    if name == "job_facets":
        return tools.job_facets(ctx)
    if name == "kg_major_skills":
        return tools.kg_major_skills(ctx, a.get("major", ""))
    if name == "kg_skill_jobs":
        return tools.kg_skill_jobs(ctx, a.get("skill", ""), limit=int(a.get("limit") or 10))
    if name == "kg_path":
        return tools.kg_path(ctx, int(a.get("job_id") or 0), str(a.get("major") or ""))
    if name == "exam_notices":
        return tools.exam_notices(ctx, keyword=str(a.get("keyword") or ""),
                                  exam_type=str(a.get("exam_type") or ""),
                                  only_open=bool(a.get("only_open")),
                                  limit=int(a.get("limit") or 6))
    if name == "my_interviews":
        return tools.my_interviews(ctx, limit=int(a.get("limit") or 8))
    if name == "question_bank_lookup":
        return tools.question_bank_lookup(ctx, query=str(a.get("query") or ""),
                                          family=str(a.get("family") or ""),
                                          qtype=str(a.get("qtype") or ""),
                                          limit=int(a.get("limit") or 5))
    if name == "kb_search":
        # 多跳：单跳不足以回答时改写检索词再补一跳（AGENT_KB_MULTIHOP=0 可退回单跳）
        return tools.kb_search_deep(ctx, a.get("query") or "", top_k=4)
    if name == "web_search":
        return tools.web_search(ctx, a.get("query") or "", top_k=5)
    if name == "run_workflow":
        return tools.run_workflow(ctx, a.get("name") or "")
    return tools.class_overview(ctx, a.get("class_name", ""), a.get("term", ""))


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
        result = _dispatch(ctx, name, args)
    except PermissionError as exc:
        return {"tool_result": {"error": str(exc)}, "tool_name": name}
    except ValueError as exc:
        # 参数错（班级不存在等）与越权分开呈现，不吓唬用户
        return {"tool_result": {"error": str(exc), "error_kind": "bad_request"},
                "tool_name": name}
    return {"tool_result": dict(result), "tool_name": name}


# ----------------------------------------------------------------
# 3. 草稿（默认模板直引；可注入 LLM 版用于演示/幻觉复现）
# ----------------------------------------------------------------
def _template_draft(result: Mapping[str, Any], feedback: str = "") -> str:
    """把工具结果「原样直引」成一段话：不归纳、不估算、不换算。"""
    if not result:
        return "未查到相关数据。"
    if "error" in result:
        # 越权与参数错（班级写错等）分开说话，不把输错名字说成越权
        if result.get("error_kind") == "bad_request":
            return f"这个数据查不了：{result.get('error')}"
        return f"该数据你没有访问权限：{result.get('error')}"
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
        # 教师端补充：职业意向与就业去向分布（口径与 class_overview 工具一致）
        ci = dict((result.get("career_intent") or {}).get("distribution") or {})
        if ci:
            parts.append("职业意向分布：" + "、".join(f"{k} {v} 人" for k, v in ci.items()) + "。")
        ei = (result.get("employment_intent") or {}).get("top_directions") or []
        if ei:
            parts.append("就业意向前几的方向：" + "、".join(
                f"{row.get('direction')}（浏览 {row.get('views')} 次）" for row in ei[:3]) + "。")
    if "thresholds" in result:
        parts.append(f"班级 {result.get('class_name')} 的预警阈值配置如下（空值表示沿用上一级默认）。")
        for row in result.get("thresholds") or []:
            parts.append(
                f"{row.get('label')}（来源 {row.get('source')}）："
                f"黄色 {row.get('yellow_value')}，橙色 {row.get('orange_value')}，"
                f"红色 {row.get('red_value')}"
                + (f"，权重 {row.get('weight')}" if row.get("weight") is not None else "") + "。"
            )
    if "items" in result:
        parts.append(f"预警名单共命中 {result.get('count')} 人。")
        for item in (result.get("items") or [])[:3]:
            parts.append(
                f"{item.get('name')}（{item.get('student_no')}）风险分 {item.get('risk_score')}，"
                f"等级 {item.get('level')}；归因：{'；'.join(item.get('reasons') or []) or '无'}。"
            )
    if "gaps" in result:
        if result.get("target_direction"):
            parts.append(f"目标岗位方向：{result.get('target_direction')}。")
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
    # ---- 统一入口能力层模板稿（agent-entry）：原样直引，不归纳不估算 ----
    if "summary" in result and "years" in result:
        s = result.get("summary") or {}
        parts.append(
            f"{(result.get('student') or {}).get('name') or '该生'} 共 "
            f"{s.get('term_count')} 个学期 {s.get('record_count')} 条成绩记录，"
            f"加权均分 {s.get('weighted_avg')}，挂科 {s.get('failed_count')} 门。"
        )
        for year in (result.get("years") or [])[-2:]:
            for t in (year.get("terms") or [])[-2:]:
                parts.append(
                    f"{t.get('term')}：均分 {t.get('avg_score')}，挂科 {t.get('failed_count')} 门。"
                )
    if "gpa_forecast" in result:
        if not result.get("available"):
            parts.append(str(result.get("reason") or "历史学期不足，无法做确定性预测。"))
        else:
            gpa = result.get("gpa_forecast") or {}
            fail = result.get("fail_forecast") or {}
            lvl = result.get("level_forecast") or {}
            parts.append(
                f"下学期（{result.get('next_term')}）均分预测 {gpa.get('predicted')}，"
                f"95% 区间 {gpa.get('low')}~{gpa.get('high')}，趋势 {gpa.get('trend')}；"
                f"挂科门次预测 {fail.get('predicted')}；"
                f"预警走向 {lvl.get('level') or lvl.get('level_text') or '见数据'}。"
                f"（{gpa.get('confidence')}）"
            )
    if "composite" in result:
        comp = result.get("composite") or {}
        parts.append(
            f"报考分析（{result.get('goal_label') or result.get('goal')}）："
            f"综合分 {comp.get('score')}，档位 {comp.get('tier_label') or comp.get('tier')}。"
            f"这是规则分，不是录取概率。"
        )
        for d in (result.get("dimensions") or [])[:4]:
            parts.append(f"维度 {d.get('key')}：{d.get('score')}（{d.get('level_text') or d.get('level')}）。")
    if "needs_intent" in result and result.get("needs_intent"):
        parts.append(str(result.get("reason") or "请先选定方向。"))
    if "notice_total" in result:
        parts.append(f"招考公告共命中 {result.get('notice_total')} 条。")
        for it in (result.get("items") or [])[:3]:
            link = f"，原文：{it.get('detail_url')}" if it.get("detail_url") else ""
            parts.append(
                f"{it.get('title')}（{it.get('org_name') or '单位未标注'}，"
                f"截止 {it.get('signup_end') or '未标注'}）{link}。"
            )
        if not result.get("items"):
            parts.append("没有命中任何公告——库里实抓的就这些，不拿往年凑数。")
    if "bank_total" in result:
        parts.append(f"题库共 {result.get('bank_total')} 题，命中 {len(result.get('hits') or [])} 条。")
        for h in (result.get("hits") or [])[:3]:
            parts.append(
                f"《{h.get('question')}》（{h.get('family')}/{h.get('qtype')}），"
                f"出处：{h.get('source_name') or h.get('source_url') or '模板题'}。"
            )
    if "finished_count" in result and "best_total" in result:
        parts.append(
            f"模拟面试共 {result.get('count')} 场，完成 {result.get('finished_count')} 场"
            + (f"，最高总分 {result.get('best_total')}。" if result.get("best_total") is not None else "。")
        )
        for it in (result.get("items") or [])[:3]:
            parts.append(
                f"{it.get('job_title') or '未标注岗位'}：{it.get('status')}，"
                f"进度 {it.get('cur_round')}/{it.get('max_round')}"
                + (f"，总分 {it.get('total')}" if it.get("total") is not None else "") + "。"
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
    # pending 不是失败：流程已提交，只是等教师审批（人工审核环节）
    if status in ("empty", "not_found", "invalid", "pending"):
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
                        feedback: str, on_token: Callable[[str], None] | None = None) -> str | None:
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
                                     user_prompt="\n\n".join(parts), tag="rag",
                                     on_token=on_token)


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


def _llm_draft(state: AgentState, result: Mapping[str, Any], feedback: str,
               on_token: Callable[[str], None] | None = None) -> str | None:
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
        on_token=on_token,
    )


def _llm_chitchat(state: AgentState,
                  on_token: Callable[[str], None] | None = None) -> str | None:
    """寒暄 / 能力提问：纯对话，不带任何数据；教师端用专属能力话术。"""
    ctx: ToolContext = state["ctx"]
    is_teacher = ctx.actor_type == "teacher"
    parts = [f"【身份】{'教师' if is_teacher else '学生'}", f"【提问】{state.get('query') or ''}"]
    history = _history_text(state)
    if history:
        parts.append(f"【前面对话】\n{history}")
    return llm_client.generate_reply(
        ctx.actor_type,
        system_prompt=teacher_agent.TEACHER_CHAT_SYSTEM if is_teacher else _CHAT_SYSTEM,
        user_prompt="\n\n".join(parts),
        tag="chitchat",
        on_token=on_token,
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


def draft_node(state: AgentState,
               on_token: Callable[[str], None] | None = None) -> dict[str, Any]:
    """生成草稿：注入优先（演示幻觉拦截）→ LLM 润色 → 模板直引兜底。

    生成顺序：第 1、2 稿用 LLM（第 2 稿带 Critic 退回意见做修正），
    第 3 稿起回到模板直引保底——模板是原样引用、几乎必然通过审核，
    即使大模型连续说错数字，用户拿到的也是有依据的版本，而不是无数值的降级话术。

    on_token 非空时 LLM 走流式，逐块回调；模板稿瞬间生成，不回调。
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
        is_teacher = (state.get("ctx") or ToolContext("", 0)).actor_type == "teacher"
        fallback_text = (
            "你好，我是启航智能助手。我可以帮您看班级整体情况与预警名单、查单个学生的四维画像、"
            "成绩单与学业预测，分析班级能力与岗位要求的差距，也能查各班的预警阈值配置；"
            "还能检索招考公告、面试题库（都带出处可回溯），从企业知识库里查制度流程（给出文档与页码），"
            "按已定义的工作流一键跑多步流程。比如直接问「AI2201 这学期预警情况怎么样」就行。"
            if is_teacher else
            "你好，我是启航智能助手。我可以帮你看本人的预警、成绩单、学业预测和报考分析（考公/考编/考研），"
            "推荐匹配的岗位、搜岗位库，查你模拟面试的记录和场次总分，"
            "检索面试真题题库和招考公告（都带出处），"
            "从企业知识库里查制度流程，也能按已定义的工作流一键跑多步流程。"
            "比如直接问「我最近有没有预警」就行。"
        )
        draft = _llm_chitchat(state, on_token) or fallback_text
        mode = "chitchat"
    elif str(state.get("tool_name") or "") == "run_workflow":
        draft = _workflow_draft(result)
        mode = "workflow"
    elif str(state.get("tool_name") or "") in _EXTERNAL_TOOLS:
        # 知识库/联网：模型先写，引用校验不过就退回「原文直引」模板
        if attempts >= 3 or not _llm_draft_enabled():
            draft = _external_draft(state, result)
        else:
            draft = (_llm_external_draft(state, result, feedback, on_token)
                     or _external_draft(state, result))
        mode = "rag"
    elif attempts >= 3 or not _llm_draft_enabled():
        draft = _template_draft(result, feedback)
        mode = "template"
    else:
        draft = (_llm_draft(state, result, feedback, on_token)
                 or _template_draft(result, feedback))
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


def _suggested_followups(state: AgentState) -> list[str]:
    """答完后给 2~3 条引导式追问：用户不用想「还能问什么」（商业化产品化交互）。

    只从固定模板里选，不经过模型——追问建议本身也不能带任何未核对的数字。
    """
    tool = str(state.get("tool_name") or "")
    if tool == "injected":          # 离线注入（测试/演示）不给建议
        return []
    picks = _FOLLOWUP_BY_TOOL.get(tool) or _FOLLOWUP_DEFAULT
    return list(picks[:3])


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


def _normalize_history(history: Sequence[Mapping[str, str]] | None) -> list[dict[str, str]]:
    """最近几轮对话：只保留 user/assistant 且非空，单轮截到 500 字。"""
    turns: list[dict[str, str]] = []
    for item in list(history or [])[-8:]:
        role = str(item.get("role") or "")
        text = str(item.get("text") or "").strip()
        if role in ("user", "assistant") and text:
            turns.append({"role": role, "text": text[:500]})
    return turns


def _initial_state(ctx: ToolContext, query: str, term: str | None,
                   history: Sequence[Mapping[str, str]] | None,
                   last_tool: str | None, trace_id: str) -> AgentState:
    return {
        "ctx": ctx,
        "query": str(query),
        "term": term,
        "history": _normalize_history(history),
        "last_tool": last_tool,
        "attempts": 0,
        "feedback": "",
        "trace_id": trace_id,
    }


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
    state = _initial_state(ctx, query, term, history, last_tool, trace_id)
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
            "planner": str(state.get("planner") or "graph"),
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
        # 引导式追问：前端渲染成可点的问题 chips
        "suggested_followups": _suggested_followups(state),
    }


def run_chat_stream(
    ctx: ToolContext,
    query: str,
    term: str | None = None,
    claims: Mapping[str, Any] | None = None,
    *,
    draft_fn: Callable[..., str] | None = None,
    tool_result: Mapping[str, Any] | None = None,
    history: Sequence[Mapping[str, str]] | None = None,
    last_tool: str | None = None,
) -> Iterator[dict[str, Any]]:
    """流式跑一次对话：逐事件产出 status / replace / delta / done / error。

    事件口径：
      status  —— 阶段提示（plan / tool / draft / critic / retry），前端只做文案展示；
      replace —— 用给定文本**整体替换**当前气泡（重写新稿、模板稿、降级稿都走它）；
      delta   —— 追加一段正文（LLM 逐块产出）；
      done    —— 最终答案（已过 Critic）与元信息，前端以此为准覆盖气泡文本；
      error   —— 本次失败的安全话术，不含任何数值。

    与 run_chat 的数值口径一致：delta 只是「边生成边看」，Critic 驳回就 replace 重写，
    超过 MAX_RETRY 走降级模板，done.answer 永远是唯一最终的、已核验的答案。
    """
    trace_id = uuid.uuid4().hex[:12]
    state = _initial_state(ctx, query, term, history, last_tool, trace_id)
    if draft_fn is not None:
        state["draft_fn"] = draft_fn

    try:
        if tool_result is not None:
            # 离线模式：跳过 plan/tool（测试与演示注入用）
            state["tool_result"] = dict(tool_result)
            state["tool_name"] = "injected"
            state["plan"] = {"tool": "injected"}
            yield {"type": "status", "stage": "tool", "text": "已载入注入的工具结果"}
        else:
            yield {"type": "status", "stage": "plan", "text": "正在理解问题…"}
            state.update(plan_node(state))
            yield {"type": "status", "stage": "tool",
                   "text": f"正在调用 {state.get('tool_name')}…",
                   "tool": state.get("tool_name")}
            state.update(tool_node(state))

        while True:
            attempt = int(state.get("attempts") or 0) + 1
            # 每次新稿先清空气泡：上一稿即使被驳回也不留在界面上
            yield {"type": "replace", "text": "", "attempt": attempt}
            yield {"type": "status", "stage": "draft", "attempt": attempt,
                   "text": "正在生成回答…" if attempt == 1 else "正在按回查意见重写…"}
            # 草稿在工作线程里生成，token 经队列回到本生成器：
            # 主线程不阻塞在 draft_node 上，才能把每块正文立刻 yield 给 SSE。
            streamed: list[str] = []
            token_q: Queue[str | None] = Queue()
            box: dict[str, Any] = {}
            failure: list[Exception] = []

            def _run_draft() -> None:
                try:
                    box.update(draft_node(state, on_token=token_q.put))
                except Exception as exc:      # 交给主线程统一走安全话术
                    failure.append(exc)
                finally:
                    token_q.put(None)          # 结束标记：无论成败都要放

            worker = Thread(target=_run_draft, daemon=True)
            worker.start()
            while True:
                piece = token_q.get()
                if piece is None:
                    break
                streamed.append(piece)
                yield {"type": "delta", "text": piece, "attempt": attempt}
            worker.join()
            if failure:
                raise failure[0]
            state.update(box)
            draft = str(state.get("draft") or "")
            if "".join(streamed).strip() != draft.strip():
                # 模板稿 / 流式中途断流 / 注入稿：没有逐块输出，整体下发
                yield {"type": "replace", "text": draft, "attempt": attempt}
            yield {"type": "status", "stage": "critic", "attempt": attempt,
                   "text": "正在逐条核对数值…"}
            state.update(critic_node(state))
            verdict = dict(state.get("verdict") or {})
            if verdict.get("passed"):
                state.update(accept_node(state))
                break
            if int(state.get("attempts") or 0) > MAX_RETRY:
                state.update(fallback_node(state))
                yield {"type": "replace", "text": str(state.get("answer") or ""),
                       "attempt": attempt}
                break
            yield {"type": "status", "stage": "retry", "attempt": attempt,
                   "text": "数值回查未通过，正在重写…"}

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
                "stream": True,
                "planner": str(state.get("planner") or "graph"),
                "graph_version": GRAPH_VERSION,
                "critic_version": CRITIC_VERSION,
            },
        )
        yield {
            "type": "done",
            "answer": answer,
            "trace_id": trace_id,
            "term": term,
            "degraded": degraded,
            "attempts": int(state.get("attempts") or 0),
            "tool": str(state.get("tool_name") or ""),
            "citations": list((state.get("tool_result") or {}).get("citations") or []),
            "suggested_followups": _suggested_followups(state),
        }
    except Exception as exc:  # 断库/工具异常等：给安全话术，不外泄堆栈
        audit_event(actor_type=ctx.actor_type,
                    actor_id=ctx.student_id or ctx.teacher_id or 0,
                    action="agent.chat.failed", target=trace_id,
                    detail={"query": str(query)[:120], "stream": True,
                            "error": str(exc)[:200]})
        yield {"type": "error", "trace_id": trace_id,
               "message": "智能体处理失败，已停止本轮回答（不含任何未核对的数值）。"}
