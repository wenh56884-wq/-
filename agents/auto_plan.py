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

import hashlib
import json
import os
import re
from typing import Any

from langchain_core.tools import tool

from agents import llm as llm_client

AUTO_PLAN_VERSION = "auto-plan-v2"

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
def teacher_career_search(class_name: str = "", term: str = "", intent: str = "",
                          limit: int = 20) -> str:
    """查询某个班级的生涯规划档案：班级摘要（人数/预警/均分/方向分布/风险定级/
    成绩前列/高匹配岗位）+ 每位学生的全域档案（成绩/预警/预测/岗位/面试/竞赛/测评/
    选课/招考/图谱）。class_name 形如 AI2301；intent 填 考公/考研/考编/就业 之一做方向过滤；
    limit 控制完整档案的学生数（默认 20，班级人数多时按学号截断，摘要为样本口径）。"""


@tool
def my_warning(term: str = "") -> str:
    """查询**本人**的学业预警状态：风险分、等级、归因。只能查自己。"""


@tool
def my_recommendations(term: str = "") -> str:
    """查询**本人**的岗位推荐列表与推荐理由。只能查自己。"""


@tool
def my_assessment() -> str:
    """查询**本人**的软技能测评结果：五维复合能力画像（专业技能/学习/创新/抗压/沟通）。
    只能查自己。没有做过测评时如实说明，并指向「职业测评」页。"""


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
def class_grades_rank(class_name: str = "", term: str = "") -> str:
    """查询某个班的成绩分析：全班总体平均成绩、每个人的平均成绩，
    以及同专业之间的班级排名、同专业内的个人排名。
    class_name 形如 AI2301；term 形如 2025-2026-2，留空表示最近学期。"""


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
def mark_notices_read() -> str:
    """把**本人**的竞赛通知全部标记为已读（已读水位推到最新）。只能操作自己。"""


@tool
def save_career_intent(intent: str) -> str:
    """保存**本人**的职业目标。intent 只能是 考公 / 考研 / 考编 / 就业 之一。
    用于「把我的目标定为考公」这类明确的操作请求；只是问竞争力分析请用 my_career_forecast。"""


@tool
def my_career_guide() -> str:
    """查询**本人**按年级分层的职业规划路径（大一先选目标，大二大三直接给路径）。只能查自己。"""


@tool
def competition_guide(track: str = "就业", direction: str = "") -> str:
    """按去向（考公 / 就业）和岗位方向推荐该参加的竞赛，结果附官方来源链接。"""


@tool
def cert_guide(limit: int = 6) -> str:
    """推荐**本人**适合考的证书（计算机等级/软考/四六级/普通话/教资等）：
    谁负责、差什么前提、能获得什么、报名窗口与考试时间，全部来自官方公告。
    只查自己。"""


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
def exam_positions(keyword: str = "", dept: str = "", education: str = "",
                   political: str = "", place: str = "") -> str:
    """查询国考（国家公务员考试）的具体职位明细：部门、用人司局、招考职位、招录人数、
    学历、专业、政治面貌、工作地点。可按职位/部门/专业关键词、部门、学历、政治面貌、
    工作地点筛选。查不到就如实说，不拿往年职位凑数。"""


@tool
def my_interviews(limit: int = 8) -> str:
    """查询**本人**的模拟面试场次：状态、总分、轮次。只能查自己。"""


@tool
def question_bank_lookup(query: str = "", family: str = "", qtype: str = "") -> str:
    """检索面试题库：按关键词/行业/题型找真题，每条带出处链接。用于回答「面试一般会问什么」。"""


@tool
def my_elective_advice(term: str = "", top_n: int = 8) -> str:
    """查询**本人**的技能缺口选课推荐：目标岗位技能要求对比已修/已选课程，
    算出缺口并推荐能补缺口的选修课。只能查自己。用于「选什么课/补什么课/技能缺口」。"""


@tool
def my_campus_insight(term: str = "") -> str:
    """查询**本人**的校园行为洞察：图书馆到馆/借阅、一卡通消费规律、证书/竞赛/项目活动、
    出勤率、岗位浏览兴趣与学习投入画像。只能查自己。用于「校园洞察/行为画像/到馆/消费/出勤」。"""


@tool
def class_campus_insight(class_name: str = "", term: str = "", limit: int = 30) -> str:
    """查询某个班级的校园行为洞察：投入画像分布、低投入名单及原因、活动覆盖率、
    岗位兴趣城市与班级均值。class_name 形如 AI2301；limit 控制样本学生数
    （默认 30，上限 60，班级人数多时按学号截断，摘要为样本口径）。"""


@tool
def student_campus_insight(student_no: str = "", term: str = "") -> str:
    """教师查询**某个学生**的校园行为洞察：图书馆/消费/活动/出勤/岗位兴趣与学习投入画像。
    不受班级样本截断限制，全班任何学生都能查；student_no 填学号，姓名需先换成学号。"""


@tool
def class_roster(class_name: str = "") -> str:
    """查询某个班级的**完整学生名册**（学号/姓名/专业，不截断）。
    用于「班里有哪些学生 / 全班名单」，或先拿学号再查某个学生的行为洞察。"""


# 教师端可用全部；学生端**只给本人工具**——不给 student_profile / warning_list /
# student_grades / student_forecast，免得模型顺着「帮我看看张三」去查别人
# （越权会在工具层被拦，但根本不该给它选项）。
# 知识图谱是全校公共数据（专业-课程-岗位-技能），两端都给。
_TEACHER_TOOLS = (class_list, class_overview, warning_list, warning_thresholds,
                  student_profile, student_grades, student_forecast, class_grades_rank,
                  career_gap, teacher_career_search, class_campus_insight,
                  student_campus_insight, class_roster,
                  kg_major_skills, kg_skill_jobs, kg_path,
                  exam_notices, exam_positions, question_bank_lookup,
                  kb_search, web_search, run_workflow)
_STUDENT_TOOLS = (my_warning, my_recommendations, my_grades, my_forecast,
                  my_career_forecast, my_elective_advice, my_campus_insight,
                  my_notices, mark_notices_read, save_career_intent, my_career_guide,
                  competition_guide, cert_guide,
                  search_jobs, job_facets, my_interviews, my_assessment,
                  kg_major_skills, kg_skill_jobs, kg_path,
                  exam_notices, exam_positions, question_bank_lookup,
                  kb_search, web_search, run_workflow)

# graph.tool_node 能执行的工具全集：模型选出来的名字必须在这个集合里，否则退回确定性路由
EXECUTABLE = {t.name for t in _TEACHER_TOOLS} | {t.name for t in _STUDENT_TOOLS}

# 有副作用的工具：自主规划里不能让模型「顺手」调用——把通知全部标已读、
# 改掉职业目标这类操作必须由用户明确说出。query 里没有操作意图词时，
# 模型即使选了也退回确定性路由（brain-v1 的 _BLOCKED_TOOLS 同口径）。
_SIDE_EFFECT_TOOLS = frozenset({"mark_notices_read", "save_career_intent"})
_SIDE_EFFECT_MARKERS = ("标记已读", "标为已读", "设为已读", "全部已读",
                        "保存", "设置", "定为", "改成", "更新为",
                        "我的目标", "目标是", "记下")


def _tools_for(actor_type: str) -> tuple[Any, ...]:
    return _TEACHER_TOOLS if actor_type == "teacher" else _STUDENT_TOOLS


_TOOLS_BY_NAME = {t.name: t for t in (*_TEACHER_TOOLS, *_STUDENT_TOOLS)}

# ----------------------------------------------------------------
# 参数归一化：模型很爱把「第二个学期」「红色预警」原样塞进参数
# ----------------------------------------------------------------
_TERM_RE = re.compile(r"(20\d{2})\D{0,4}(20\d{2})\D{0,12}?(?:第)?([12一二上下])")
_TERM_INDEX = {"一": "1", "二": "2", "上": "1", "下": "2"}
_LEVEL_MAP = {
    "红色": "red", "红": "red", "red": "red",
    "橙色": "orange", "橙": "orange", "orange": "orange",
    "黄色": "yellow", "黄": "yellow", "yellow": "yellow",
    "正常": "none", "无预警": "none", "none": "none",
    "未知": "unknown", "数据不足": "unknown", "unknown": "unknown",
}
_EXAM_TYPE_MAP = {
    "考公": "civil", "公务员": "civil", "国考": "civil", "省考": "civil", "civil": "civil",
    "考编": "institution", "事业编": "institution", "事业单位": "institution",
    "institution": "institution",
    "考研": "postgraduate", "研究生": "postgraduate", "postgraduate": "postgraduate",
}
# 返回条数类参数：越界会让工具直接报错或拖垮响应，统一夹紧
_COUNT_PARAMS = {"limit": (1, 50), "top_n": (1, 50), "top_k": (1, 50)}


def _norm_term(value: str) -> str:
    """「2025-2026学年第二学期」→「2025-2026-2」；认不出来就原样返回，不猜。"""
    text = str(value or "").strip()
    match = _TERM_RE.search(text)
    if not match:
        return text
    index = _TERM_INDEX.get(match.group(3), match.group(3))
    return f"{match.group(1)}-{match.group(2)}-{index}"


def _norm_class(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).upper()


def _normalize_args(name: str, args: Any) -> dict[str, Any]:
    """把模型给的参数规整成工具真能吃下的形状。

    只做四件事：去掉工具没声明的键、字符串去空白、枚举/学期/班级按口径改写、
    条数类参数夹到合法区间。不做任何「猜学号」「补班级」这类补全——
    补出来的参数等于替用户编事实。
    """
    if not isinstance(args, dict):
        return {}
    tool = _TOOLS_BY_NAME.get(name)
    declared = set(getattr(tool, "args", {}) or {}) if tool else None
    out: dict[str, Any] = {}
    for key, value in args.items():
        if key == "self" or value is None:
            continue
        if declared is not None and key not in declared:
            continue
        if isinstance(value, bool):
            out[key] = value
            continue
        if isinstance(value, (int, float)):
            out[key] = _clamp(key, value)
            continue
        text = str(value).strip()
        if not text:
            continue
        if key == "term":
            text = _norm_term(text)
        elif key == "class_name":
            text = _norm_class(text)
        elif key == "level":
            text = _norm_level(text)
        elif key == "exam_type":
            text = _EXAM_TYPE_MAP.get(text, text)
        elif (key in _COUNT_PARAMS or key == "job_id") and re.fullmatch(r"\d+", text):
            out[key] = _clamp(key, int(text))
            continue
        out[key] = text
    return out


def _norm_level(value: str) -> str:
    """「红色预警」「橙色」→ red / orange；认不出就原样小写，不硬猜。"""
    text = str(value or "").strip()
    if text in _LEVEL_MAP:
        return _LEVEL_MAP[text]
    stripped = re.sub(r"(预警|等级|级别|风险)$", "", text)
    return _LEVEL_MAP.get(stripped, _LEVEL_MAP.get(stripped.lower(), text.lower()))


def _clamp(key: str, value: float) -> int:
    low, high = _COUNT_PARAMS.get(key, (0, 10 ** 9))
    return max(low, min(int(value), high))


def plan_with_llm(ctx: Any, query: str, term: str | None = None,
                  history: list[dict[str, str]] | None = None) -> dict[str, Any] | None:
    """让模型自主选**一个**工具并填参数（旧接口，保留兼容）。

    返回 {"tool": ..., "args": {...}}；不可用/没选工具/选了不允许的工具 → 返回 None，
    由调用方退回确定性路由。**这里不执行任何工具**，执行仍在 graph.tool_node。
    """
    plans = plan_many(ctx, query, term, history, max_calls=1)
    return plans[0] if plans else None


def plan_many(ctx: Any, query: str, term: str | None = None,
              history: list[dict[str, str]] | None = None,
              max_calls: int = 3) -> list[dict[str, Any]]:
    """让模型自主拆出**多个**工具调用（v2）。

    旧版只取 tool_calls[0]，模型明明识别出「查成绩 + 查预警」两件事，
    第二件会被直接丢掉，用户看到的回答就少一半。v2 把同一次响应里的
    多个调用都收下来（去重、限流、副作用工具仍要显式意图），
    交给调用方并发执行。返回值：[] 表示不可用/没选出可用工具。
    """
    actor = str(getattr(ctx, "actor_type", "") or "")
    if actor not in ("teacher", "student"):
        return []

    cache_key = _cache_key(actor, query, term, history, max_calls)
    cached = _cache_get(cache_key)
    if cached is not None:
        return [dict(item) for item in cached]

    tools = _tools_for(actor)
    names = ", ".join(t.name for t in tools)
    who = "教师" if actor == "teacher" else "学生"
    lines = [f"当前使用者是{who}。", f"可选工具：{names}。", _CHITCHAT_HINT]
    if term:
        lines.append(f"当前学期：{term}（用户没指定学期就不用填 term）。")
    if max_calls > 1:
        lines.append(f"如果一个问题需要查多件事，最多给出 {max_calls} 个互不依赖的工具调用。")
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
                                        "只负责从工具清单里挑最合适的工具。"),
                             ("user", "\n".join(lines))])
    except Exception:
        return []          # 模型不可用：交给确定性路由，不硬撑

    allowed = {t.name for t in tools}
    plans: list[dict[str, Any]] = []
    seen: set[str] = set()
    for call in list(getattr(resp, "tool_calls", None) or [])[:max_calls]:
        name = str(call.get("name") or "")
        if name not in EXECUTABLE or name not in allowed:
            continue           # 编造的工具名 / 角色越权：整条丢弃
        if name in _SIDE_EFFECT_TOOLS and not any(
                marker in str(query or "") for marker in _SIDE_EFFECT_MARKERS):
            # 副作用工具但用户没有明确表达操作意图：不执行，退回确定性路由
            continue
        args = _normalize_args(name, call.get("args") or {})
        signature = name + "|" + json.dumps(args, sort_keys=True, ensure_ascii=False)
        if signature in seen:
            continue
        seen.add(signature)
        plans.append({"tool": name, "args": args, "planner": AUTO_PLAN_VERSION})
    if plans:
        _cache_put(cache_key, plans)
    return plans


# ----------------------------------------------------------------
# 决策缓存：同一个问题在一次演示里常被连问两遍（评委复述、用户重试），
# 第二次没必要再付一次模型往返
# ----------------------------------------------------------------
_PLAN_CACHE: dict[str, list[dict[str, Any]]] = {}
_CACHE_LIMIT = 256


def _cache_enabled() -> bool:
    return str(os.getenv("AGENT_PLAN_CACHE", "1")).strip().lower() not in (
        "0", "false", "off", "no")


def _cache_key(actor: str, query: str, term: str | None,
               history: list[dict[str, str]] | None, max_calls: int) -> str:
    last_user = ""
    for turn in reversed(list(history or [])):
        if str(turn.get("role") or "") == "user":
            last_user = str(turn.get("text") or "")[:80]
            break
    raw = f"{actor}|{term or ''}|{max_calls}|{str(query or '').strip()}|{last_user}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cache_get(key: str) -> list[dict[str, Any]] | None:
    if not _cache_enabled():
        return None
    return _PLAN_CACHE.get(key)


def _cache_put(key: str, plans: list[dict[str, Any]]) -> None:
    if not _cache_enabled():
        return
    if len(_PLAN_CACHE) >= _CACHE_LIMIT:
        _PLAN_CACHE.pop(next(iter(_PLAN_CACHE)))   # FIFO：先淘汰最早的一条
    _PLAN_CACHE[key] = [dict(item, args=dict(item.get("args") or {})) for item in plans]


def clear_cache() -> None:
    """测试与热更新用：清掉规划缓存。"""
    _PLAN_CACHE.clear()
