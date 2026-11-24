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


# ----------------------------------------------------------------
# 8) 降级率复现批次：同一批样本、脚本化模型，改动前后可比
# ----------------------------------------------------------------
BATCH_ANSWERS = [
    "背景是课程需要秒杀场景；目标是在有限预算内防超卖；行动是首先用Redis预扣库存，然后消息队列削峰；结果是支撑峰值5000并发且零超卖。",
    "我负责订单系统的重构；先梳理了库存扣减链路；再用Redis做原子预扣；最后通过压测验证了零超卖。",
    "项目背景是校内二手交易平台；目标是提升发布转化率；我引入了图片压缩与分类推荐；结果是转化率提升了15%。",
    "当时的问题是简历投递没有反馈；我先埋点统计各环节流失；再按渠道拆分数据；最后把无效渠道下线了。",
    "我负责社团招新页面；目标是提高报名完成率；我把表单从五步缩到两步；结果报名完成率提升了20%。",
    "这份实习主要做数据看板；我用SQL把日报自动化；并且加了异常波动告警；每天能省下两小时人工。",
    "我带队参加过算法竞赛；先做了特征清洗；然后换了梯度提升模型；最终在省赛拿到了二等奖。",
    "课程项目是图书馆预约系统；我负责后端接口；用Redis做了并发控制；压测时没有出现重复预约。",
]
FABRICATED = "主导过千万级用户系统重构"


def _batch_fake_llm(monkeypatch, guided: bool) -> list[str]:
    """脚本化模型：不调真实 LLM。guided=True 时模拟「看到可选引文清单就照抄」的模型。"""
    monkeypatch.setenv("AGENT_LLM_DRAFT", "1")
    prompts: list[str] = []

    def fake(actor_type: str, *, system_prompt: str, user_prompt: str, tag: str = "draft"):
        prompts.append(user_prompt)
        if guided and "可选引文清单" in user_prompt:
            tail = user_prompt.split("可选引文清单", 1)[1]
            for line in tail.splitlines():
                if line.strip().startswith("- "):
                    quote = line.strip()[2:].strip()
                    return f"你提到「{quote}」，结构清晰；建议再补充一条量化结果。"
        return f"你提到「{FABRICATED}」，这是亮点；建议补充细节。"

    monkeypatch.setattr(interviewer.llm_client, "generate_reply", fake)
    return prompts


def _degraded_count(monkeypatch, guided: bool) -> int:
    _batch_fake_llm(monkeypatch, guided=guided)
    degraded = 0
    for answer in BATCH_ANSWERS:
        item = score_answer(answer, RUBRIC, EVIDENCE)
        assert item is not None
        out = interviewer.run_turn("请讲项目", "project", answer, item, EVIDENCE)
        if out["comment_version"] == interviewer.COMMENT_FALLBACK_VERSION:
            degraded += 1
    return degraded


def test_fabricated_quotes_reproduce_degradation(monkeypatch):
    """改动前基线：模型只编造引文时，整批 8 条全部降级（45.6% 实测问题的离线复现）。"""
    assert _degraded_count(monkeypatch, guided=False) == len(BATCH_ANSWERS)


def test_quote_whitelist_cuts_degradation(monkeypatch):
    """同一批样本：模型照抄重试 prompt 里的预校验引文后，降级数必须下降。"""
    assert _degraded_count(monkeypatch, guided=True) == 0
    assert _degraded_count(monkeypatch, guided=False) == len(BATCH_ANSWERS)


def test_retry_prompt_carries_preverified_quote_list(monkeypatch):
    """清单里的每条引文都必须先过 verify_comment 的逐字规则。"""
    from engine.interview import verify_comment

    prompts = _fake_llm(monkeypatch, [f"你提到「{FABRICATED}」，这是亮点。", ANSWER])
    # 第二次回复也用编造引文，保证能看到带清单的重写 prompt
    out = interviewer.run_turn("请讲项目", "project", ANSWER, _item(), EVIDENCE)
    assert out["comment_version"] == interviewer.COMMENT_FALLBACK_VERSION
    assert "可选引文清单" in prompts[1]
    for line in prompts[1].splitlines():
        if line.startswith("- "):
            quote = line[2:].strip()
            ok, _bad = verify_comment(f"「{quote}」", ANSWER, EVIDENCE)
            assert ok, f"清单里出现未通过逐字校验的引文：{quote}"


# ----------------------------------------------------------------
# 9) 会话内记忆：None / 空不改变行为，有值时只带最后 2 轮且回答截断 120 字
# ----------------------------------------------------------------
def test_history_none_and_empty_leave_behavior_unchanged(monkeypatch):
    reply = ["你提到「支撑峰值5000并发且零超卖」，结构清晰；建议补上「预算」约束。" for _ in range(3)]
    prompts = _fake_llm(monkeypatch, reply)
    default = interviewer.run_turn("请讲项目", "project", ANSWER, _item(), EVIDENCE)
    with_none = interviewer.run_turn("请讲项目", "project", ANSWER, _item(), EVIDENCE, history=None)
    with_empty = interviewer.run_turn("请讲项目", "project", ANSWER, _item(), EVIDENCE, history=[])

    assert prompts[0] == prompts[1] == prompts[2]
    assert default == with_none == with_empty
    assert "本场前情" not in prompts[0]


def test_history_keeps_last_two_rounds_and_truncates_answers(monkeypatch):
    prompts = _fake_llm(monkeypatch, ["你提到「支撑峰值5000并发且零超卖」，结构清晰。"])
    history = [
        {"q": "第一轮问题", "a": "甲" * 200},
        {"q": "第二轮问题", "a": "乙" * 200},
        {"q": "第三轮问题", "a": "丙" * 200},
    ]
    interviewer.run_turn("请讲项目", "project", ANSWER, _item(), EVIDENCE, history=history)
    prompt = prompts[0]

    assert "本场前情（最多 2 轮，每轮回答截断 120 字）" in prompt
    assert "第一轮问题" not in prompt
    assert "第二轮问题" in prompt and "第三轮问题" in prompt
    assert "乙" * 120 in prompt and "乙" * 121 not in prompt


# ----------------------------------------------------------------
# 10) 报告改写：tag 固定、数字原样、异常回退模板
# ----------------------------------------------------------------
REPORT_FACTS = {
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


def test_render_report_llm_uses_report_tag_and_keeps_numbers(monkeypatch):
    monkeypatch.setenv("AGENT_LLM_DRAFT", "1")
    calls: list[tuple[str, str]] = []

    def fake(actor_type: str, *, system_prompt: str, user_prompt: str, tag: str = "draft"):
        calls.append((actor_type, tag))
        return "这份面试表现有亮点：总分 72.5，已答 2 题，跳过 1 题；第1题 80.0 分；缺 Redis 要补。"

    monkeypatch.setattr(interviewer.llm_client, "generate_reply", fake)
    text = interviewer.render_report_llm(REPORT_FACTS)

    assert calls == [("student", "interview.report")]
    assert text.startswith("这份面试表现有亮点")
    assert all(n in text for n in ("72.5", "2", "1", "80.0", "缺 Redis"))


def test_render_report_llm_falls_back_when_numbers_lost_or_llm_fails(monkeypatch):
    monkeypatch.setenv("AGENT_LLM_DRAFT", "1")
    monkeypatch.setattr(interviewer.llm_client, "generate_reply",
                        lambda *a, **k: "这次表现不错，继续加油。")
    assert interviewer.render_report_llm(REPORT_FACTS) == interviewer.render_report(REPORT_FACTS)

    def boom(*a, **k):
        raise RuntimeError("LLM 不可用")

    monkeypatch.setattr(interviewer.llm_client, "generate_reply", boom)
    assert interviewer.render_report_llm(REPORT_FACTS) == interviewer.render_report(REPORT_FACTS)
