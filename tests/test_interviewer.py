# tests/test_interviewer.py
# 职责：模拟面试官 Agent 契约——未答不计分 / 引文逐字校验 / 驳回重试 / 模板降级 / 报告数字原样引用
# 说明：全部离线，不连 MySQL、不调真实 LLM（monkeypatch generate_reply）

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agents import interviewer  # noqa: E402
from engine.interview import score_answer  # noqa: E402

ANSWER = (
    "背景是课程需要秒杀场景；目标是在有限预算内防超卖；"
    "行动是首先用Redis预扣库存，然后消息队列削峰；"
    "结果是支撑峰值5000并发且零超卖。"
)
RESUME = "秒杀系统设计｜完成秒杀模块，支撑峰值5000并发"
EVIDENCE = [RESUME]
RUBRIC = {
    "keywords": ["Redis", "库存", "结果"],
    "struct_marks": ["背景", "目标", "行动", "结果", "首先", "然后"],
    "weight": 0.25,
    "label": "项目深挖",
}


def _item() -> dict:
    item = score_answer(ANSWER, RUBRIC, EVIDENCE)
    assert item is not None and item["score"] > 0
    return item


def _fake_llm(monkeypatch, replies: list[str | None]) -> list[str]:
    """按顺序返回预设回复，并记录每次的 user_prompt。

    显式打开 AGENT_LLM_DRAFT：同目录其他测试模块可能在 import 时把它设为 0，
    monkeypatch 会在本测试结束后还原，避免测试之间互相污染。
    """
    monkeypatch.setenv("AGENT_LLM_DRAFT", "1")
    prompts: list[str] = []
    reply_iter = iter(replies)

    def fake(actor_type: str, *, system_prompt: str, user_prompt: str, tag: str = "draft"):
        prompts.append(user_prompt)
        return next(reply_iter)

    monkeypatch.setattr(interviewer.llm_client, "generate_reply", fake)
    return prompts


# ----------------------------------------------------------------
# 1) 未作答：不计分、不调 LLM、模板说明
# ----------------------------------------------------------------
def test_unanswered_does_not_call_llm(monkeypatch):
    def fake(**kwargs):
        raise AssertionError("未作答不应调用 LLM")

    monkeypatch.setattr(interviewer.llm_client, "generate_reply", fake)
    out = interviewer.run_turn("请讲项目", "project", None, None, EVIDENCE)
    assert out["comment_version"] == interviewer.COMMENT_FALLBACK_VERSION
    assert out["quotes_ok"] is True
    assert out["attempts"] == 0
    assert "未作答" in out["comment"]


# ----------------------------------------------------------------
# 2) 合法引文：一次通过，不重试
# ----------------------------------------------------------------
def test_valid_quote_passes_without_retry(monkeypatch):
    prompts = _fake_llm(monkeypatch, [
        "你回答提到「支撑峰值5000并发且零超卖」，结构清晰；建议补上「预算」约束。",
    ])
    out = interviewer.run_turn("请讲项目", "project", ANSWER, _item(), EVIDENCE)
    assert out["comment_version"] == interviewer.COMMENT_VERSION
    assert out["quotes_ok"] is True
    assert out["attempts"] == 0
    assert len(prompts) == 1


# ----------------------------------------------------------------
# 3) 编造引文：驳回重试，耗尽后模板降级
# ----------------------------------------------------------------
def test_fabricated_quote_retries_then_falls_back(monkeypatch):
    prompts = _fake_llm(monkeypatch, ["你提到「主导过千万级用户系统重构」，这是亮点。"] * 9)
    out = interviewer.run_turn("请讲项目", "project", ANSWER, _item(), EVIDENCE)
    assert out["comment_version"] == interviewer.COMMENT_FALLBACK_VERSION
    assert out["attempts"] == interviewer.MAX_RETRY
    assert len(prompts) == interviewer.MAX_RETRY + 1
    assert "千万级" not in out["comment"], f"降级点评不得引用编造内容：{out['comment']}"


# ----------------------------------------------------------------
# 4) 重写提示必须带上一版被驳回的原因（否则重试是空转）
# ----------------------------------------------------------------
def test_retry_prompt_carries_rejection_feedback(monkeypatch):
    prompts = _fake_llm(monkeypatch, [
        "你提到「主导过千万级用户系统重构」，这是亮点。",
        "你回答提到「支撑峰值5000并发且零超卖」，结构清晰。",
    ])
    out = interviewer.run_turn("请讲项目", "project", ANSWER, _item(), EVIDENCE)
    assert out["comment_version"] == interviewer.COMMENT_VERSION
    assert out["attempts"] == 1
    assert len(prompts) == 2
    assert "驳回" in prompts[1], "重写 prompt 必须说明被驳回"
    assert "千万级" in prompts[1], "重写 prompt 必须点名违规引文"


# ----------------------------------------------------------------
# 5) LLM 不可用（返回 None）：立即降级，不空转重试
# ----------------------------------------------------------------
def test_llm_unavailable_degrades_immediately(monkeypatch):
    prompts = _fake_llm(monkeypatch, [None])
    out = interviewer.run_turn("请讲项目", "project", ANSWER, _item(), EVIDENCE)
    assert out["comment_version"] == interviewer.COMMENT_FALLBACK_VERSION
    assert out["quotes_ok"] is True
    assert len(prompts) == 1, f"LLM 不可用应立即降级，实际调用 {len(prompts)} 次"
    assert "None" not in out["comment"]


# ----------------------------------------------------------------
# 6) 环境开关关闭 LLM：直接走模板，且引用引擎分数
# ----------------------------------------------------------------
def test_llm_disabled_uses_template_with_engine_score(monkeypatch):
    monkeypatch.setenv("AGENT_LLM_DRAFT", "0")
    item = _item()

    def fake(**kwargs):
        raise AssertionError("AGENT_LLM_DRAFT=0 时不得调用 LLM")

    monkeypatch.setattr(interviewer.llm_client, "generate_reply", fake)
    out = interviewer.run_turn("请讲项目", "project", ANSWER, item, EVIDENCE)
    assert out["comment_version"] == interviewer.COMMENT_FALLBACK_VERSION
    assert str(item["score"]) in out["comment"]


# ----------------------------------------------------------------
# 7) 报告：数字全部原样引用 facts，不改写
# ----------------------------------------------------------------
def test_render_report_uses_engine_facts_verbatim():
    facts = {
        "total": 72.5,
        "answered": 2,
        "skipped": 1,
        "items": [
            {"round": 1, "label": "项目深挖", "score": 80.0, "brief": "秒杀项目"},
            {"round": 2, "label": "抗压应对", "score": None, "brief": "未作答"},
        ],
        "strengths": ["项目深挖"],
        "gaps": [{"dimension": "技能", "gap": "缺 Redis", "action": "补项目"}],
    }
    text = interviewer.render_report(facts)
    assert "72.5" in text
    assert "80.0" in text
    assert "未作答" in text
    assert "缺 Redis" in text
