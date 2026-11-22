# agents/teacher_agent.py
# 职责：教师端 Agent 能力层——意图路由（选工具/抠参数）+ 教师专属话术
# 依赖：agents.tools（只取常量与 SQL 入口，不做任何越权查询）
# 说明：教师端与学生端共用 graph.py 的 plan → tool → draft → critic 管线，
#       这里只负责「教师问什么 → 用哪个工具、带什么参数」的映射与教师专属提示词。

from __future__ import annotations

import re
from typing import Any, Mapping

from agents import intents
from agents.tools import LEVELS, ToolContext, _query

TEACHER_AGENT_VERSION = "teacher-agent-v3"

# ----------------------------------------------------------------
# 教师端专属提示词：比通用稿多了任教范围与「不代学生查」的边界说明
# ----------------------------------------------------------------
TEACHER_CHAT_SYSTEM = (
    "你是「启航 · 生涯与岗位匹配系统」的辅导员端智能助手，帮老师做学业预警、\n"
    "班级概貌、学生画像、班级与岗位能力差距、企业知识库制度答疑、工作流编排。\n"
    "当前是闲聊或关于你自身能力的提问，没有查询任何数据。\n"
    "要求：中文口语、简短友好（120 字以内）。可以说明你能做的事——\n"
    "看班级整体情况与预警名单、查单个学生的四维画像、分析班级能力与岗位要求的差距、\n"
    "查询班级预警阈值配置、从企业知识库里查制度流程（会给出文档与页码）、\n"
    "按已定义的工作流一键跑多步流程。\n"
    "**本轮绝对禁止输出任何阿拉伯数字或中文数字**，不要编造任何数据，\n"
    "也不要承诺帮老师直接修改学生数据——数据修正要走对应功能页面。"
)

# ----------------------------------------------------------------
# 意图关键词：词表来自 agents/intents（rules/agent_intents.json 可覆盖，实施方按客户问法增词）
# ----------------------------------------------------------------
_TOOL_KEYWORDS = intents.tool_keywords
# 兜底：没命中任何关键词 → 班级概貌（覆盖「整体情况怎么样」这类问法）
OVERVIEW_KEYWORDS = lambda: tuple(intents.section("overview"))  # noqa: E731
RANK_MARKERS = lambda: tuple(intents.section("rank_markers"))  # noqa: E731

# 纯班级级统计工具：提问点名到某个具体学生时，这些工具要让位给个人工具。
# class_grades_rank **不在这里**：它同时提供个人名次，点名到人时该不该让位
# 要按「有没有名次信号词」单独判断（见 plan_teacher），不能一刀切让位。
_CLASS_LEVEL_TOOLS = ("career_gap", "teacher_career_search", "class_campus_insight")


def extract_level(query: str) -> str | None:
    """从提问里抠预警等级（红色/橙色/黄色 → red/orange/yellow）。"""
    text = str(query or "")
    for word, level in (intents.section("levels") or {}).items():
        if str(word) in text:
            return str(level)
    return None


def _extract_class_name(query: str) -> str | None:
    """从提问里抠班级名（形如 AI2201 / RJ2201）。"""
    match = re.search(r"\b([A-Za-z]{2,4}\d{3,4})\b", str(query or ""))
    return match.group(1) if match else None


def _extract_student_no(query: str) -> str | None:
    """从提问里抠学号（形如 AI22010101）。"""
    match = re.search(r"\b([A-Za-z]{2}\d{6,8})\b", str(query or ""))
    return match.group(1) if match else None


def _extract_student_name(query: str) -> str | None:
    """从提问里抠中文名（2~4 个汉字），剔除泛词与带动词前缀的误命中。

    为什么要剥动词前缀：「看下张三的画像」按 2~4 字滑窗会先命中「看下张三」，
    直接拿去查库必然查无此人。凡是以常见动词开头、或含「的」的候选都跳过。
    """
    text = str(query or "")
    stop_words = tuple(intents.section("student_name_stop_words") or ())
    verb_prefixes = ("看", "查", "帮", "请", "问", "给", "想", "要", "来", "去",
                     "打开", "显示", "这个", "那个", "哪个")
    fillers = "下个位这那吗呢吧啊了有是也就都还"  # 口语虚词：混进来基本是切窗切歪了
    candidates: list[tuple[int, int, str]] = []  # (长度, 起点, 名字)
    for size in (2, 3, 4):
        for start in range(0, max(1, len(text) - size + 1)):
            name = text[start:start + size]
            if not re.fullmatch(r"[\u4e00-\u9fa5]{2,4}", name):
                continue
            if "的" in name or any(w in name for w in stop_words):
                continue
            if name.startswith(verb_prefixes):
                continue
            if any(ch in fillers for ch in name):
                continue
            candidates.append((size, start, name))
    # 取最短候选（真正的名字一般是滑窗里最短的那个完整段），同长取最靠前
    return min(candidates, key=lambda c: (c[0], c[1]))[2] if candidates else None


def resolve_student_no(ctx: ToolContext, query: str) -> str:
    """学号优先；没有学号就按中文名在本租户（含任教范围）内精确找一个人。

    为什么要按名字找：老师日常说「看下张三的画像」，不会报学号；
    抠到名字去库里精确匹配，比每次都兜底到「本班第一个学生」有用得多。
    找不到或重名时返回空串，由上层兜底，不瞎猜。
    """
    no = _extract_student_no(query)
    if no:
        return no
    name = _extract_student_name(query)
    if not name:
        return ""
    rows = _query(
        "SELECT s.`学号` AS student_no FROM `学生` s "
        "WHERE s.`租户编号` = %s AND s.`姓名` = %s ORDER BY s.`学号` LIMIT 2",
        (ctx.tenant_id, name),
    )
    if len(rows) == 1:
        return str(rows[0]["student_no"])
    return ""  # 重名/查无此人：不猜，交给兜底


def _shift_term(ctx: ToolContext, offset: int) -> str:
    """取该租户第 offset 新的学期（0=最新，1=上学期）。"""
    rows = _query(
        "SELECT DISTINCT sc.`学期` AS term FROM `成绩` sc "
        "JOIN `学生` s ON s.`编号` = sc.`学生编号` AND s.`租户编号` = %s "
        "ORDER BY sc.`学期` DESC LIMIT %s",
        (ctx.tenant_id, offset + 1),
    )
    if len(rows) > offset:
        return str(rows[offset]["term"])
    return ""


def extract_term(ctx: ToolContext, query: str) -> str | None:
    """从提问里抠学期口径（本学期/上学期/具体学期号），抠不到返回 None。"""
    text = str(query or "")
    if any(w in text for w in ("上学期", "上一学期", "上上学期")):
        offset = 2 if "上上" in text else 1
        return _shift_term(ctx, offset) or None
    if any(w in text for w in ("这学期", "本学期", "这学期以来", "最近")):
        return _shift_term(ctx, 0) or None
    match = re.search(r"(\d{4}[-—~]\d{4}[-第]?[12]?)", text)
    if match:
        return match.group(1).replace("—", "-").replace("~", "-")
    return None


def _first_student(ctx: ToolContext, term: str | None) -> str:
    """该学期有成绩的第一个学生学号（供画像兜底，不扫全租户无成绩的人）。"""
    if not term:
        return ""
    rows = _query(
        "SELECT s.`学号` AS student_no FROM `学生` s "
        "JOIN `成绩` sc ON sc.`学生编号` = s.`编号` AND sc.`学期` = %s "
        "WHERE s.`租户编号` = %s ORDER BY s.`学号` LIMIT 1",
        (term, ctx.tenant_id),
    )
    return str(rows[0]["student_no"]) if rows else ""


def _default_class(ctx: ToolContext) -> str:
    """没点名班级时取本租户第一个有成绩的班（与 graph._default_class 同口径）。"""
    rows = _query(
        "SELECT s.`班级` AS class_name FROM `学生` s "
        "JOIN `成绩` sc ON sc.`学生编号` = s.`编号` "
        "WHERE s.`租户编号` = %s GROUP BY s.`班级` ORDER BY s.`班级` LIMIT 1",
        (ctx.tenant_id,),
    )
    return str(rows[0]["class_name"]) if rows else ""


def plan_teacher(ctx: ToolContext, intent: str, query: str,
                 term: str | None, history: Mapping[str, Any] | None = None
                 ) -> dict[str, Any]:
    """教师端意图路由：返回 {"plan": {...}, "tool_name": str}。

    参数抠取优先级：本次提问 > 历史追问里带出的上下文（class 由 graph 层传入意图串）。
    没点名班级的班级级工具一律走 default_class，不扫全租户。
    """
    tool_name = "class_overview"
    # 点名到具体学生时，班级级统计让位给个人工具（成绩单 / 画像 / 预测）
    named_student = bool(resolve_student_no(ctx, query))
    for name, keywords in _TOOL_KEYWORDS():
        if named_student and name in _CLASS_LEVEL_TOOLS:
            continue
        # 例外：真的在问名次时不让位。个人名次算在班级排名里，
        # 成绩单没有名次字段，「XX 排第几」交给成绩单会答不出来。
        if named_student and name == "class_grades_rank" \
                and not any(m in intent for m in RANK_MARKERS()):
            continue
        if any(k in intent for k in keywords):
            tool_name = name
            break

    args: dict[str, Any] = {}
    resolved_term = term or extract_term(ctx, query)
    class_name = _extract_class_name(query) or _extract_class_name(intent)

    # 教师点名了班级（或说「这个班 / 我们班」）却没点名到人时，「成绩 / 均分 / 绩点」
    # 指的是全班统计：词表里的「成绩 / 均分 / 绩点」是按个人成绩单写的，不修的话
    # 这类问法会落到 student_grades，再兜底成「第一个学生」的成绩——
    # 教师问的是全班，看到的却是随机一个人的成绩，答非所问。
    class_signal = bool(class_name) or any(
        k in intent for k in ("这个班", "我们班", "全班", "班上", "班里"))
    if class_signal and not named_student and tool_name == "student_grades":
        tool_name = "class_grades_rank"

    # 需要「查谁」的工具：成绩单 / 学业预测 / 逐生行为洞察与画像一样，都得先把学号抠出来
    if tool_name in ("student_profile", "student_grades", "student_forecast",
                     "student_campus_insight"):
        student_no = resolve_student_no(ctx, query)
        if not student_no:
            # 没点名任何人：兜底到该学期有成绩的第一个学生（与旧口径一致）
            student_no = _first_student(ctx, resolved_term)
        args["student_no"] = student_no
        args["term"] = resolved_term or ""
        return {"plan": {"tool": tool_name, "args": args}, "tool_name": tool_name}

    if tool_name == "warning_thresholds":
        args["class_name"] = class_name or _default_class(ctx)
        return {"plan": {"tool": tool_name, "args": args}, "tool_name": tool_name}

    args["term"] = resolved_term or ""
    args["class_name"] = class_name or _default_class(ctx)
    if tool_name == "warning_list":
        level = extract_level(query)
        if level:
            args["level"] = level
    return {"plan": {"tool": tool_name, "args": args}, "tool_name": tool_name}
