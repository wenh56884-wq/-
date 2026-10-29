# agents/auto_plan.py
# 职责：**自主规划**分支——让模型自己从工具清单里选工具并填参数（LangChain tool calling）。
# 依赖：langchain_core.tools / agents.llm（DeepSeek）
#
# 定位：只替换现有图里的「规划」这一步（plan_node 选工具），
#       **工具执行、数值口径、Critic 校验、降级模板全部照旧**——
#       这样既拿到了自主性，又不会把「学生只能查本人」这类硬约束交给提示词去守。
#
# 开关：AGENT_MODE=auto 才启用，默认 graph（确定性路由），两套并存。
#       模型不可用 / 选不出工具 / 选了越权工具 → 一律退回确定性路由，不硬撑。

from __future__ import annotations

import os
from typing import Any

from langchain_core.tools import tool

from agents import llm as llm_client

AUTO_PLAN_VERSION = "auto-plan-v1"

# 寒暄不进自主规划：交给图里的 chitchat 分支（不取数、纯对话）
_CHITCHAT_HINT = "（如果是打招呼或问「你能做什么」，不要选工具，直接回答即可。）"


def auto_mode_enabled() -> bool:
    """AGENT_MODE=auto 时启用自主规划；其它值一律走确定性路由。"""
    return str(os.getenv("AGENT_MODE", "graph")).strip().lower() == "auto"


# ----------------------------------------------------------------
# 工具声明：只用于给模型看 schema，**不在这里执行任何取数**
# ----------------------------------------------------------------
@tool
def class_list() -> str:
    """列出本学校的班级目录：有哪些班、每个班多少人，按学院分组。"""


@tool
def class_overview(class_name: str = "", term: str = "") -> str:
    """查询某个班级的整体情况：人数、平均绩点、挂科率、预警分布、职业意向分布。
    class_name 形如 AI2301；留空表示教师任教的默认班级。"""


@tool
def warning_list(class_name: str = "", term: str = "", level: str = "") -> str:
    """查询某个班级的学业预警名单：谁有风险、风险分、等级、归因。
    level 可填 red/orange/yellow/none/unknown 之一做筛选。"""


@tool
def warning_thresholds(class_name: str = "") -> str:
    """查询某个班级的预警阈值配置：各项指标的黄/橙/红阈值是多少。"""


@tool
def student_profile(student_no: str = "", term: str = "") -> str:
    """查询某个学生的四维画像：学业、行为、兴趣、能力的得分与标签。
    可以按学号查，也可以按姓名查（姓名重名时会要求补学号）。"""


@tool
def career_gap(class_name: str = "", term: str = "") -> str:
    """分析某个班级的能力与目标岗位要求之间的差距：哪些维度差、差多少。"""


@tool
def my_warning(term: str = "") -> str:
    """查询**本人**的学业预警状态：风险分、等级、归因。只能查自己。"""


@tool
def my_recommendations(term: str = "") -> str:
    """查询**本人**的岗位推荐列表与推荐理由。只能查自己。"""


@tool
def kb_search(query: str = "") -> str:
    """在企业知识库里检索制度、流程、办事指南等文档内容（会给出文档名与页码）。
    用于回答「规定是怎样的 / 流程怎么走」这类问题。"""


@tool
def web_search(query: str = "") -> str:
    """联网搜索实时信息。只有用户明确要查网上的、知识库里没有的内容时才用。"""


@tool
def run_workflow(name: str = "") -> str:
    """按名称执行一个已定义好的多步工作流；不带名称时只列出可用工作流。"""


# ---- agent-entry-v1 新增：成绩 / 学业预测 / 报考分析 / 知识图谱 / 岗位 / 通知 ----
# 这些功能原先只有页面接口能调，智能体调不到；现在一并纳入工具集，
# 数值仍由 engine 的确定性函数算出，工具只负责取数与结构化。
@tool
def student_grades(student_no: str = "") -> str:
    """查询某个学生的成绩单：各学年 / 学期均分、加权均分、学分、挂科门次。"""


@tool
def student_forecast(student_no: str = "") -> str:
    """预测某个学生下学期的绩点、挂科门次与预警等级走向；学期不足 2 个时会明确说明无法预测，不会编数字。"""


@tool
def my_grades() -> str:
    """查询**本人**的成绩单：各学年 / 学期均分、加权均分、学分、挂科门次。只能查自己。"""


@tool
def my_forecast() -> str:
    """预测**本人**下学期的绩点与挂科门次，并列出风险课。只能查自己。"""


@tool
def my_career_forecast(goal: str = "") -> str:
    """分析**本人**报考竞争力：硬门槛、四维评分、时间窗与提分杠杆。
    goal 填 考公 / 考编 / 考研 之一；留空时沿用学生自己填的发展意向。只能查自己。"""


@tool
def my_notices(limit: int = 20) -> str:
    """查询**本人**未读的竞赛 / 招考通知。只能查自己。"""


@tool
def my_career_guide() -> str:
    """查询**本人**按年级分层的职业规划路径（大一先选目标，大二大三直接给路径）。只能查自己。"""


@tool
def competition_guide(track: str = "就业", direction: str = "") -> str:
    """按去向（考公 / 就业）和岗位方向推荐该参加的竞赛，结果附官方来源链接。"""


@tool
def search_jobs(query: str = "", limit: int = 20) -> str:
    """按关键词搜索岗位库。注意：搜索是检索，**不是**个性化推荐；推荐请用 my_recommendations。"""


@tool
def job_facets() -> str:
    """查看岗位库的可筛选项：城市、学历、薪资、经验等的取值分布。"""


@tool
def kg_major_skills(major: str = "") -> str:
    """查询某个专业通过课程能学到哪些技能（专业 → 课程 → 技能）。"""


@tool
def kg_skill_jobs(skill: str = "", limit: int = 10) -> str:
    """查询掌握某项技能能胜任哪些岗位。"""


@tool
def kg_path(job_id: int = 0, major: str = "") -> str:
    """查询从某个专业到目标岗位的达成路径：已具备什么、还缺什么、经过哪些课程与技能。"""


# ---- agent-entry-v2 新增：招考公告 / 模拟面试历史 / 面试题库 ----
@tool
def exam_notices(keyword: str = "", exam_type: str = "", only_open: bool = False) -> str:
    """检索真实的招考公告（标题/招录单位/报名截止/原文链接）。
    exam_type 填 考公 / 考编 / 考研 之一，也可以直接说关键词。查不到就如实说，不编公告。"""


@tool
def my_interviews(limit: int = 8) -> str:
    """查询**本人**的模拟面试场次：状态、总分、轮次。只能查自己。"""


@tool
def question_bank_lookup(query: str = "", family: str = "", qtype: str = "") -> str:
    """检索面试题库：按关键词/行业/题型找真题，每条带出处链接。用于回答「面试一般会问什么」。"""


# 教师端可用全部；学生端**只给本人工具**——不给 student_profile / warning_list /
# student_grades / student_forecast，免得模型顺着「帮我看看张三」去查别人
# （越权会在工具层被拦，但根本不该给它选项）。
# 知识图谱是全校公共数据（专业-课程-岗位-技能），两端都给。
_TEACHER_TOOLS = (class_list, class_overview, warning_list, warning_thresholds,
                  student_profile, student_grades, student_forecast, career_gap,
                  kg_major_skills, kg_skill_jobs, kg_path,
                  exam_notices, question_bank_lookup,
                  kb_search, web_search, run_workflow)
_STUDENT_TOOLS = (my_warning, my_recommendations, my_grades, my_forecast,
                  my_career_forecast, my_notices, my_career_guide, competition_guide,
                  search_jobs, job_facets, my_interviews,
                  kg_major_skills, kg_skill_jobs, kg_path,
                  exam_notices, question_bank_lookup,
                  kb_search, web_search, run_workflow)

# graph.tool_node 能执行的工具全集：模型选出来的名字必须在这个集合里，否则退回确定性路由
EXECUTABLE = {t.name for t in _TEACHER_TOOLS} | {t.name for t in _STUDENT_TOOLS}


def _tools_for(actor_type: str) -> tuple[Any, ...]:
    return _TEACHER_TOOLS if actor_type == "teacher" else _STUDENT_TOOLS


def plan_with_llm(ctx: Any, query: str, term: str | None = None,
                  history: list[dict[str, str]] | None = None) -> dict[str, Any] | None:
    """让模型自主选一个工具并填参数。

    返回 {"tool": ..., "args": {...}}；不可用/没选工具/选了不允许的工具 → 返回 None，
    由调用方退回确定性路由。**这里不执行任何工具**，执行仍在 graph.tool_node。
    """
    actor = str(getattr(ctx, "actor_type", "") or "")
    if actor not in ("teacher", "student"):
        return None

    tools = _tools_for(actor)
    names = ", ".join(t.name for t in tools)
    who = "教师" if actor == "teacher" else "学生"
    lines = [f"当前使用者是{who}。", f"可选工具：{names}。", _CHITCHAT_HINT]
    if term:
        lines.append(f"当前学期：{term}（用户没指定学期就不用填 term）。")
    for turn in list(history or [])[-4:]:
        text = str(turn.get("text") or "").strip()
        if text:
            role = "用户" if str(turn.get("role") or "") == "user" else "助手"
            lines.append(f"{role}：{text[:200]}")
    lines.append(f"用户问题：{query}")

    try:
        model = (llm_client.get_teacher_llm() if actor == "teacher"
                 else llm_client.get_student_llm())
        bound = model.bind_tools(tools, tool_choice="auto")
        resp = bound.invoke([("system", "你是「启航」智能助手的意图路由，"
                                        "只负责从工具清单里挑一个最合适的工具。"),
                             ("user", "\n".join(lines))])
    except Exception:
        return None        # 模型不可用：交给确定性路由，不硬撑

    calls = list(getattr(resp, "tool_calls", None) or [])
    if not calls:
        return None
    call = calls[0]
    name = str(call.get("name") or "")
    if name not in EXECUTABLE:
        return None
    allowed = {t.name for t in tools}
    if name not in allowed:          # 角色越权：学生不能选教师工具
        return None
    args = call.get("args") or {}
    if not isinstance(args, dict):
        args = {}
    # 只保留字符串/数字/布尔参数，避免模型塞进奇怪结构
    clean = {k: v for k, v in args.items()
             if isinstance(v, (str, int, float, bool)) and k != "self"}
    return {"tool": name, "args": clean, "planner": AUTO_PLAN_VERSION}
