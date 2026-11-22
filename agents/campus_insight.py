# agents/campus_insight.py
# 职责：校园行为洞察智能体——基于引擎事实层，由大模型生成个人/班级行为解读（本板块主角）。
# 依赖：agents.tools（事实取数）/ engine.campus_insight（唯一数值真相源）/ agents.llm / agents.critic。
# 说明：模型只引用数值不生成；critic 逐数字回查，驳回超限或 LLM 不可用降级确定性模板（纯函数）。

from __future__ import annotations

import json
from typing import Any, Callable, Mapping

from agents import llm as llm_module
from agents import tools
from agents.critic import MAX_RETRY, verify
from agents.tools import ToolContext

CAMPUS_INSIGHT_AGENT_VERSION = "campus-insight-agent-v1"

STUDENT_SYSTEM = """你是学生的校园行为洞察智能体，负责把引擎算出的校园行为画像变成个性化解读与行动建议。

硬性约束（违反即视为失败）：
1. 所有数值（投入分、到馆次数、借阅册数、出勤率、消费规律性、活动数、浏览/收藏数、四六级分数等）必须原样引用给定事实 JSON，禁止生成、估算、四舍五入或换算改写；
2. 结合 study_style（学习投入定级）、图书馆到馆/借阅趋势、一卡通消费规律、出勤、证书/竞赛/项目活动与岗位浏览兴趣，给出个性化解读；
3. 不得臆造学生经历：事实里没有的活动、证书、消费行为一律不得提及；
4. 数据为空（note 非空或对应域为空）时如实说明「暂无该域数据」，不得编造；
5. 不得出现「约 / 大概 / 估计 / 大约 / 差不多 / 左右 / 似乎」这类模糊词；
6. 正文 ≤250 字：先给投入画像结论，再给 2-3 条可执行的行动建议；中文口语，不用 Markdown 标题。"""

CLASS_SYSTEM = """你是教师的班级校园行为洞察智能体，负责把引擎算出的班级行为聚合变成班主任式管理建议。

硬性约束（违反即视为失败）：
1. 所有数值（人数、均值、覆盖率、分布计数、出勤率等）必须原样引用给定事实 JSON，禁止生成、估算、四舍五入或换算改写；
2. 围绕投入画像分布（study_style_distribution）、低投入名单及原因（low_engagement）、活动覆盖率（activity_coverage_rate）、岗位兴趣城市（top_cities）组织解读；
3. 低投入名单只引用事实里的学生与原因，不得臆造学生或归因；
4. 数据为空时如实说明，不得编造；样本口径（note）必须原样转述，不冒充全班；
5. 不得出现「约 / 大概 / 估计 / 大约 / 差不多 / 左右 / 似乎」这类模糊词；
6. 正文 ≤300 字：先给班级整体结论，再给 2-3 条班主任式管理建议；中文口语，不用 Markdown 标题。"""


def _pct(value: Any) -> str:
    """比率→百分比文本（critic 白名单兼容 0.85↔85）；None 如实说暂无记录。"""
    if value is None:
        return "暂无记录"
    return f"{round(float(value) * 100, 2):g}%"


def _template_student(facts: Mapping[str, Any]) -> str:
    """个人确定性模板稿（纯函数）：数值全部直引 facts，LLM 不可用/被驳回时兜底。"""
    note = str(facts.get("note") or "")
    if note:
        return (f"{note}。建议：先保持规律作息与正常出勤，逐步参与到馆学习和校园活动，"
                "等数据积累后再看投入画像变化。")
    style = facts.get("study_style") or {}
    latest = (facts.get("library") or {}).get("latest") or {}
    visits = latest.get("visits") or 0
    borrows = latest.get("borrows") or 0
    rate = (facts.get("attendance") or {}).get("latest_rate")
    reg = (facts.get("consumption") or {}).get("regularity") or 0.0
    cities = (facts.get("job_interest") or {}).get("top_cities") or []
    city_text = f"；岗位兴趣城市：{cities[0].get('city')}" if cities else ""
    advice = {
        "高投入型": "保持当前节奏，把借阅与活动经历沉淀成简历素材。",
        "稳健型": "建议提高到馆频次，并参与证书/竞赛补齐实践经历。",
        "待激活": "建议从规律作息与每周到馆开始，逐步参与校园活动。",
    }.get(str(style.get("label") or ""), "建议先完善到馆/消费/活动记录，再观察投入变化。")
    return (f"学习投入分 {style.get('score')}（{style.get('label')}）；"
            f"本学期到馆 {visits} 次、借阅 {borrows} 册，出勤率 {_pct(rate)}，"
            f"消费规律性 {reg}{city_text}。建议：{advice}")


def _template_class(facts: Mapping[str, Any]) -> str:
    """班级确定性模板稿（纯函数）：数值全部直引 facts，班主任式建议不带数字。"""
    cs = facts.get("class_summary") or {}
    total = cs.get("student_total") or 0
    if not total:
        note = str(facts.get("note") or "暂无学生行为数据")
        return f"{note}。建议：先确认班级名册与行为数据接入，再开展班级洞察。"
    dist = cs.get("study_style_distribution") or {}
    dist_text = "、".join(f"{k} {v} 人" for k, v in dist.items()) or "暂无"
    low = cs.get("low_engagement") or []
    if low:
        brief = "；".join(
            f"{s.get('name')}（{'、'.join(s.get('reasons') or [])}）" for s in low[:3])
        low_text = f"低投入 {len(low)} 人：{brief}"
        if len(low) > 3:
            low_text += "，其余见名单"
    else:
        low_text = "暂无低投入学生"
    cities = cs.get("top_cities") or []
    city_text = "、".join(str(c.get("city")) for c in cities[:3]) or "暂无"
    note = str(facts.get("note") or "")
    note_text = f"（{note}）" if note else ""
    return (f"班级 {facts.get('class_name')}（{facts.get('term') or '当前学期'}）"
            f"共 {total} 人：投入画像分布 {dist_text}；"
            f"平均到馆 {cs.get('avg_library_visits')} 次，"
            f"平均出勤率 {_pct(cs.get('avg_attendance_rate'))}，"
            f"活动覆盖率 {_pct(cs.get('activity_coverage_rate'))}。{low_text}。"
            f"兴趣城市：{city_text}。建议：对低投入学生逐一谈话核实原因，"
            f"组织到馆打卡与证书/竞赛动员，提升活动覆盖。{note_text}")


def _build_user(facts: Mapping[str, Any], max_chars: int) -> str:
    return (
        "【引擎事实（唯一数值来源，只读）】\n"
        + json.dumps(facts, ensure_ascii=False, indent=2, default=str)
        + f"\n\n请生成行为洞察解读正文（≤{max_chars}字）与行动建议。"
    )


def _interpret(facts: Mapping[str, Any], *, actor_type: str, system: str,
               template: Callable[[Mapping[str, Any]], str],
               max_chars: int) -> dict[str, Any]:
    """事实 → LLM 解读 → critic 回查 → 驳回重试 ≤MAX_RETRY → 超限/不可用降级模板。"""
    base: dict[str, Any] = {
        "engine_version": facts.get("engine_version"),
        "calc_version": facts.get("calc_version"),
        "tools_version": facts.get("tools_version"),
    }

    def _fallback(retries: int) -> dict[str, Any]:
        return {**base, "text": template(facts), "source": "template",
                "provider": None, "retries": retries}

    user = _build_user(facts, max_chars)
    retries = 0
    reply = llm_module.generate_reply(
        actor_type, system_prompt=system, user_prompt=user,
        tag="campus_insight", temperature=0.3)
    if reply is None:
        return _fallback(0)
    draft = reply.strip()
    verdict = verify(draft, facts)
    while not verdict.passed and retries < MAX_RETRY:
        retries += 1
        retry_user = (user + "\n\n【上一版草稿】\n" + draft
                      + "\n\n" + verdict.feedback())
        reply = llm_module.generate_reply(
            actor_type, system_prompt=system, user_prompt=retry_user,
            tag="campus_insight.retry", temperature=0.3)
        if reply is None:
            return _fallback(retries)
        draft = reply.strip()
        verdict = verify(draft, facts)
    if not verdict.passed:
        return _fallback(retries)
    order = llm_module.provider_order()
    return {**base, "text": draft, "source": "llm",
            "provider": order[0] if order else None, "retries": retries}


def interpret_student(ctx: ToolContext, term: str | None = None) -> dict[str, Any]:
    """个人校园行为洞察解读：身份只从 ctx 取；数值由引擎供给、critic 回查。

    返回前端契约：text / source(llm|template) / provider / retries /
    engine_version / calc_version / tools_version。
    """
    facts = tools.my_campus_insight(ctx, term)
    if facts.get("note"):                       # 查无数据：不调模型，模板如实说明
        return {"text": _template_student(facts), "source": "template",
                "provider": None, "retries": 0,
                "engine_version": facts.get("engine_version"),
                "calc_version": facts.get("calc_version"),
                "tools_version": facts.get("tools_version")}
    return _interpret(facts, actor_type="student", system=STUDENT_SYSTEM,
                      template=_template_student, max_chars=250)


def interpret_class(ctx: ToolContext, class_name: str, term: str = "",
                    limit: int = 30) -> dict[str, Any]:
    """班级校园行为洞察解读（教师端）：班级校验在工具层 _require_class 完成。"""
    facts = tools.class_campus_insight(ctx, class_name, term, limit)
    if not (facts.get("class_summary") or {}).get("student_total"):
        return {"text": _template_class(facts), "source": "template",
                "provider": None, "retries": 0,
                "engine_version": facts.get("engine_version"),
                "calc_version": facts.get("calc_version"),
                "tools_version": facts.get("tools_version")}
    return _interpret(facts, actor_type="teacher", system=CLASS_SYSTEM,
                      template=_template_class, max_chars=300)