# agents/elective.py
# 职责：选课规划智能体——基于引擎事实层，由 DeepSeek 生成个性化选课方案与理由（本板块主角）。
# 依赖：engine.elective（唯一数值真相源）/ agents.llm（双通道）/ agents.critic（数值回查）。
# 说明：模型只引用数值不生成；方案课名过白名单校验；critic 驳回超限或 LLM 不可用降级确定性模板。

from __future__ import annotations

import json
from typing import Any, Mapping

from agents import llm as llm_module
from agents.career.nodes import _extract_json
from agents.critic import MAX_RETRY, verify
from engine import elective as engine_elective

_PLAN_MARKER = "【选课方案】"

ELECTIVE_SYSTEM = """你是学生的选课规划智能体，负责把引擎算出的技能缺口变成个性化选课方案。

硬性约束（违反即视为失败）：
1. 所有数值（覆盖率、缺口门次、学分、得分）必须原样引用给定事实 JSON，禁止估算、四舍五入或编造；
2. 只能从 recommendations 候选列表里选课，禁止编造课名；
3. 结合学生专业、均分、已选方向解释「为什么选这几门、按什么顺序、如何支撑目标岗位」，不得臆造学生经历；
4. 学生有追问时先回应追问，再给方案；
5. 选课窗口只原样引用 window.text；state=closed 时明确「本窗口已结束，以后续教务处通知为准」，不得催促立即选课；
6. 选课规则原样引用 policy.rules：与必修课时间冲突不能选；先选先得、选满为止；不足20人可能合班或取消；开课后退课暂停1学期线下通识选修选课资格；
7. gened.applicable=true 时逐条列出 uncovered 模块，并说明课池未含通识模块课程、词面核对可能漏判、以教务管理系统认定为准；2024/2025级原样引用 equivalence.text（线下一门抵线上相应板块、再选只保留最高分）；
8. 学分只引用 credits 块数值，并原样说明分类核算不可确定性计算；毕业结构与置换上限按 facts 直引；
9. 选课入口只引用 entry：一站式门户→教务管理系统（http://jwmis.cfec.edu.cn）→选课→自主选课→查询；禁止编造其他链接或转述通知发布日期；
10. 正文之后另起一行输出：
【选课方案】
{"courses": ["课名1", "课名2"]}
课名必须与候选列表完全一致，顺序即建议选修顺序。"""


def _build_user(facts: Mapping[str, Any], message: str | None) -> str:
    return (
        "【引擎事实（唯一数值来源，只读）】\n"
        + json.dumps(facts, ensure_ascii=False, indent=2)
        + "\n\n【学生追问】\n"
        + (message.strip() if message and message.strip() else "（无）")
        + "\n\n请生成选课建议正文（≤300字）与【选课方案】。"
    )


def _split_plan(reply: str) -> tuple[str, Any]:
    """拆出正文与【选课方案】JSON（容忍围栏与前后废话）。"""
    if _PLAN_MARKER in reply:
        body, tail = reply.split(_PLAN_MARKER, 1)
        return body.strip(), _extract_json(tail)
    return reply.strip(), None


def _validate_plan(record: Any, facts: Mapping[str, Any]) -> dict[str, Any]:
    """方案白名单校验：课名必须在引擎候选列表里，编造即拒收并记录。"""
    allowed = {str(rec["name"]): rec for rec in facts.get("recommendations") or []}
    courses: list[dict[str, Any]] = []
    rejected: list[str] = []
    seen: set[str] = set()
    names = record.get("courses") if isinstance(record, Mapping) else None
    if not isinstance(names, list):
        return {"courses": [], "rejected": [], "ok": False, "reason": "bad_format"}
    for raw in names:
        name = str(raw or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        if name in allowed:
            courses.append(allowed[name])
        else:
            rejected.append(name)
    return {"courses": courses, "rejected": rejected, "ok": True, "reason": ""}


def advise(tenant_id: int, student_id: int, student_no: str, term: str,
           *, message: str | None = None, top_n: int = 8,
           enroll_year: int | None = None) -> dict[str, Any]:
    """智能体选课建议：事实层 → LLM 个性化方案 → critic 回查 → 白名单校验 → 降级兜底。"""
    facts = engine_elective.elective_advice_for_student(
        tenant_id, student_id, student_no, term, top_n, enroll_year=enroll_year)
    base: dict[str, Any] = {
        "facts": facts,
        "engine_version": engine_elective.ELECTIVE_ENGINE_VERSION,
        "plan": {"courses": [], "rejected": [], "ok": False, "reason": ""},
        "critic": {"passed": True, "retries": 0},
        "degraded": False,
        "reason": "",
    }
    target = facts.get("target") or {}
    if not target.get("source"):
        return {**base, "reply": engine_elective.template_advice(facts),
                "reason": "no_data"}
    if not facts.get("skill_gaps"):
        return {**base, "reply": engine_elective.template_advice(facts),
                "reason": "no_gap"}

    user = _build_user(facts, message)
    retries = 0
    reply = llm_module.generate_reply(
        "student", system_prompt=ELECTIVE_SYSTEM, user_prompt=user,
        tag="elective.advise", temperature=0.3)
    if reply is None:
        return {**base, "reply": engine_elective.template_advice(facts),
                "degraded": True, "reason": "llm_unavailable",
                "critic": {"passed": False, "retries": 0}}

    body, record = _split_plan(reply)
    verdict = verify(body, facts)
    while not verdict.passed and retries < MAX_RETRY:
        retries += 1
        retry_user = (user + "\n\n【上一版草稿】\n" + body
                      + "\n\n" + verdict.feedback())
        reply = llm_module.generate_reply(
            "student", system_prompt=ELECTIVE_SYSTEM, user_prompt=retry_user,
            tag="elective.retry", temperature=0.3)
        if reply is None:
            return {**base, "reply": engine_elective.template_advice(facts),
                    "degraded": True, "reason": "llm_unavailable",
                    "critic": {"passed": False, "retries": retries}}
        body, record = _split_plan(reply)
        verdict = verify(body, facts)

    if not verdict.passed:
        return {**base, "reply": engine_elective.template_advice(facts),
                "degraded": True, "reason": "critic_rejected",
                "critic": {"passed": False, "retries": retries,
                           "mismatches": verdict.mismatches}}

    return {**base, "reply": body, "plan": _validate_plan(record, facts),
            "critic": {"passed": True, "retries": retries}}