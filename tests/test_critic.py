# tests/test_critic.py
# 职责：校验 Critic 数值守门（逐条比对 / 百分比兼容 / 模糊词 / 重试降级 / 降级审计）
# 依赖：pytest / agents.critic / agents.graph（离线 run_chat：注入 tool_result 与 draft_fn）
# 说明：全部离线，不连 MySQL、不调 LLM

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402

from agents import critic  # noqa: E402
from agents.critic import MAX_RETRY, extract_numbers, render_fallback, verify  # noqa: E402
from agents.graph import run_chat  # noqa: E402
from agents.tools import ToolContext  # noqa: E402

# 一份「工具返回」样本：数值白名单由此生成
TOOL_RESULT = {
    "student_no": "RJ2022001",
    "term": "2025-2026-2",
    "risk_score": 67,
    "level": "red",
    "coverage": 3,
    "missing": [],
    "reasons": ["本学期挂科2门", "本学期平均成绩下滑11.6分", "本学期出勤率降至71%"],
    "metrics": {"fail_count": 2, "gpa": 68.4, "gpa_drop": 11.6, "attendance_rate": 0.71},
}


@pytest.fixture
def audit_sink(monkeypatch) -> list[dict]:
    """把审计条目同步写内存：降级事件必须可断言。"""
    sink: list[dict] = []
    import agents.tools as tools_mod

    monkeypatch.setattr(tools_mod, "AUDIT_SINK", sink)
    return sink


def _ctx() -> ToolContext:
    return ToolContext(actor_type="teacher", tenant_id=1, teacher_id=7)


# ----------------------------------------------------------------
# 1) 数值全对 → pass
# ----------------------------------------------------------------
def test_all_numbers_match_passes():
    """草稿数值全部来自工具结果 → 通过（浮点容差 1e-6）。"""
    draft = ("该生 RJ2022001 风险分 67，等级 red；"
             "挂科 2 门，均分 68.4，下滑 11.6 分。")
    verdict = verify(draft, TOOL_RESULT)
    assert verdict.passed, verdict.to_dict()
    assert verdict.mismatches == [] and verdict.fuzzy == []


# ----------------------------------------------------------------
# 2) 0.71 写成 71% → pass（归一化兼容）
# ----------------------------------------------------------------
def test_percent_and_decimal_are_compatible():
    """0.71 与 71% 必须互相兼容：两种写法都判通过。"""
    as_decimal = verify("出勤率 0.71。", TOOL_RESULT)
    as_percent = verify("出勤率 71%。", TOOL_RESULT)
    assert as_decimal.passed, as_decimal.to_dict()
    assert as_percent.passed, as_percent.to_dict()


# ----------------------------------------------------------------
# 3) 68.4 写成 78.4 → fail，mismatches 指出问题
# ----------------------------------------------------------------
def test_wrong_number_fails_with_mismatch():
    """写错一个数就判不通过，并指出最接近的允许值。"""
    draft = "该生均分 78.4。"
    verdict = verify(draft, TOOL_RESULT)
    assert not verdict.passed
    assert len(verdict.mismatches) == 1
    assert "78.4" in verdict.mismatches[0]
    assert "68.4" in verdict.mismatches[0]   # 给出最接近的允许值


# ----------------------------------------------------------------
# 4) "约 70 分" → fail（模糊表述）
# ----------------------------------------------------------------
@pytest.mark.parametrize("draft", [
    "该生风险分约 70。",
    "风险分大概 67。",
    "大概是 67 分吧。",
])
def test_fuzzy_expression_fails(draft):
    """出现「约/大概/估计 + 数字」一律判不通过，不给模糊话术放行。"""
    verdict = verify(draft, TOOL_RESULT)
    assert not verdict.passed
    assert verdict.fuzzy, f"应命中模糊词，实际：{verdict.to_dict()}"


def test_extract_numbers_ignores_terms_and_versions():
    """学期号 / 版本号 / 学号这类「非论断数字」不得被当成数值断言。"""
    claims = extract_numbers("学期 2025-2026-2 版本 v1.1 学号 RJ2022001 风险分 67")
    values = [c.value for c in claims]
    assert values == [67.0], f"应只剩风险分一个数，实际 {values}"


# ----------------------------------------------------------------
# 5) 重试 2 次仍错 → 走降级模板，输出无数字
# ----------------------------------------------------------------
def test_retry_exhausted_falls_back_without_numbers(audit_sink, monkeypatch):
    """注入一个「坚持幻觉」的草稿函数：重试耗尽后必须降级且答案不含任何数字。"""
    monkeypatch.setattr(critic, "MAX_RETRY", MAX_RETRY)  # 默认上限，显式化便于阅读

    def lying_draft(result, feedback, attempt):
        return "该生均分 78.4，风险分 88。"  # 每次都写错，且带 feedback 也不改

    out = run_chat(_ctx(), "这位学生成绩怎么样？", tool_result=TOOL_RESULT,
                   draft_fn=lying_draft)
    assert out["degraded"] is True
    assert out["attempts"] == MAX_RETRY + 1, f"应尝试 {MAX_RETRY + 1} 次，实际 {out['attempts']}"
    assert not out["verdict"]["passed"]
    assert not any(ch.isdigit() for ch in out["answer"]), \
        f"降级答案不得含数字：{out['answer']}"


def test_draft_can_be_fixed_on_retry():
    """注入「第 2 次改对」的草稿：重写后通过，且不降级。"""
    def fixing_draft(result, feedback, attempt):
        return "该生均分 68.4，风险分 67。" if attempt >= 2 else "该生均分 78.4。"

    out = run_chat(_ctx(), "这位学生成绩怎么样？", tool_result=TOOL_RESULT,
                   draft_fn=fixing_draft)
    assert out["degraded"] is False
    assert out["attempts"] == 2
    assert out["verdict"]["passed"] is True
    assert "68.4" in out["answer"]


# ----------------------------------------------------------------
# 6) 降级事件写审计（含 mismatches 与重试次数）
# ----------------------------------------------------------------
def test_degraded_event_is_audited(audit_sink):
    """降级必须可追溯：agent.chat 审计里带 degraded / attempts / passed。"""
    def lying_draft(result, feedback, attempt):
        return "风险分 99。"

    out = run_chat(_ctx(), "风险怎么样？", tool_result=TOOL_RESULT, draft_fn=lying_draft)
    chat_events = [e for e in audit_sink if e["action"] == "agent.chat"]
    assert chat_events, "未写 agent.chat 审计"
    detail = chat_events[-1]["detail"]
    assert detail["degraded"] is True and detail["attempts"] == MAX_RETRY + 1
    assert detail["passed"] is False

    verify_events = [e for e in audit_sink if e["action"] == "critic.verify"]
    assert len(verify_events) == MAX_RETRY + 1
    assert verify_events[-1]["detail"]["mismatches"], "核对事件必须带 mismatches 摘要"
    assert out["trace_id"]


# ----------------------------------------------------------------
# 额外：降级模板本身不含数字；意图严肃性
# ----------------------------------------------------------------
def test_fallback_template_has_no_digits():
    """降级模板在任何输入下都不得吐出数字。"""
    for sample in (TOOL_RESULT, {"items": [{"risk_score": 90}]},
                   {"gaps": [{"shortfall": 0.4}]}, {"error": "无权限"}, {}):
        text = render_fallback(sample)
        assert not any(ch.isdigit() for ch in text), f"含数字：{text}"


def test_graph_pipeline_blocks_hallucination(monkeypatch):
    """真实 LangGraph 跑一遍（plan→tool→draft→critic→fallback）：幻觉被拦截并降级。

    工具调用只把关：teacher-class-overview 返回固定的白名单负载，验证位移在于 Critic。
    """
    from agents import tools as tools_mod
    from agents.graph import get_graph

    payload = {
        "class_name": "AI2201", "term": "2025-2026-2", "headcount": 3,
        "avg_gpa": 76.5, "fail_rate": 0.3333,
        "warning_distribution": {"red": 1, "orange": 0, "yellow": 0,
                                 "none": 2, "unknown": 0},
        "items": [], "employment_intent": {"view_total": 10, "top_directions": []},
        "engine_version": "warning-v2", "calc_version": "v1.1",
    }
    monkeypatch.setattr(tools_mod, "class_overview", lambda ctx, name, term: dict(payload))

    def lying_draft(result, feedback, attempt):
        return "班级平均绩点 88.8，挂科率 0.9。"

    out = run_chat(_ctx(), "AI2201 班级情况如何？", draft_fn=lying_draft)
    assert out["tool_name"] == "class_overview", out["tool_name"]
    assert out["attempts"] == MAX_RETRY + 1
    assert out["degraded"] is True
    assert not any(ch.isdigit() for ch in out["answer"])
    assert get_graph() is not None  # 图编译成功（plan→tool→draft→critic→fallback 通路）


def test_feedback_lists_what_to_fix():
    """重写提示里要点名错值与允许值，不能只说『你错了』。"""
    verdict = verify("均分 90.5。", TOOL_RESULT)
    feedback = verdict.feedback()
    assert "90.5" in feedback and "不在工具返回结果中" in feedback


# ----------------------------------------------------------------
# 8) 列表型结果的序号 / 行引用 / 条数（exam_positions 草稿实测翻车点）
# ----------------------------------------------------------------
POSITIONS_RESULT = {
    'year': 2027, 'position_total': 17061, 'total_headcount': 31821,
    'positions': [
        {'dept_name': '外交部', 'position_name': '外交国政和英语',
         'position_code': '200110001001', 'headcount': 15},
        {'dept_name': '外交部', 'position_name': '法律',
         'position_code': '200110001002', 'headcount': 15},
        {'dept_name': '外交部', 'position_name': '预算和财务管理',
         'position_code': '200110004001', 'headcount': 12},
    ],
}


def test_list_ordinals_are_not_claims():
    # 「1. 外交部…」的行首序号不是数值论断，不得把合格草稿判成编造
    draft = ("2027 国考职位如下：\n1. 外交部：招 15 人。\n"
             "2. 外交部：招 15 人。\n3. 外交部：招 12 人。")
    verdict = verify(draft, POSITIONS_RESULT)
    assert verdict.passed, verdict.mismatches


def test_row_references_within_list_len_pass():
    # 「第1、3条」是引用返回列表的行号，行数内合法
    verdict = verify('第1、3条在北京市，第2条要求法律专业。', POSITIONS_RESULT)
    assert verdict.passed, verdict.mismatches


def test_row_reference_beyond_list_len_fails():
    # 行引用超出返回列表行数（列表只有 3 行却说「第5条」）必须驳回
    verdict = verify('第5条在深圳市。', POSITIONS_RESULT)
    assert not verdict.passed
    assert any('超出返回列表行数' in m for m in verdict.mismatches)


def test_list_item_count_is_verifiable():
    # 「共 3 条」的条数 = len(返回列表)，是引擎事实，应通过；说错仍要驳回
    assert verify("共命中 3 条职位。", POSITIONS_RESULT).passed
    assert not verify("共命中 9 条职位。", POSITIONS_RESULT).passed


def test_draft_node_exam_positions_no_type_crash(monkeypatch):
    # 回归：exam_positions 专用草稿分支曾把 attempts 转成 str 再与 int 比较，
    # 一进该分支必抛 TypeError（用户实测「正在生成回答…→ 智能体处理失败」）。
    import agents.graph as g

    monkeypatch.setattr(g, '_llm_draft_enabled', lambda: False)
    state = {'ctx': ToolContext(actor_type='student', tenant_id=1, student_id=1),
             'tool_name': 'exam_positions', 'tool_result': POSITIONS_RESULT,
             'attempts': 1, 'feedback': ''}
    out = g.draft_node(state)
    assert out['draft'], '模板稿不应为空'
    assert out['attempts'] == 2
