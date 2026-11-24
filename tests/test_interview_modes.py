# tests/test_interview_modes.py
# 职责：钉住面试模式切换契约——模式只改提纲顺序/追问阈值/点评语气，不改评分与逐字校验。
# 说明：全部离线；use_bank=False 避免题库检索，LLM 用 monkeypatch 替身。

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agents import interviewer  # noqa: E402
from engine.interview import (  # noqa: E402
    MODE_LABELS,
    build_outline,
    normalize_mode,
    score_answer,
)
from engine.interview_probe import probe_thresholds, should_probe  # noqa: E402

JOB = {"title": "后端工程师", "skill_tags": ["Python", "Redis"]}
RESUME = {"experiences": [{"name": "秒杀项目"}], "skills": ["Python"], "courses": ["数据库原理"]}
ANSWER = ("背景是课程需要秒杀场景；目标是在有限预算内防超卖；"
          "行动是首先用Redis预扣库存；结果是支撑峰值5000并发且零超卖。")
RUBRIC = {"keywords": ["Redis", "库存", "结果"],
          "struct_marks": ["背景", "目标", "行动", "结果"],
          "weight": 0.25, "label": "项目深挖"}
EVIDENCE = ["秒杀系统设计｜完成秒杀模块，支撑峰值5000并发"]


def _outline(mode: str | None = None) -> list[dict]:
    kwargs = {"use_bank": False}
    if mode is not None:
        kwargs["mode"] = mode
    return build_outline(JOB, RESUME, **kwargs)


# ----------------------------------------------------------------
# 1) 模式归一化与标签
# ----------------------------------------------------------------
def test_mode_contract():
    assert MODE_LABELS == {"easy": "轻松", "standard": "标准", "stress": "压力"}
    assert normalize_mode(None) == "standard"
    assert normalize_mode("") == "standard"
    assert normalize_mode("   ") == "standard"
    assert normalize_mode("bogus") == "standard"
    assert normalize_mode(" EASY ") == "easy"


# ----------------------------------------------------------------
# 2) 提纲：standard 逐字等于现状，easy 去 stress，stress 提到第 3 位
# ----------------------------------------------------------------
def test_standard_outline_is_byte_for_byte_unchanged():
    baseline = _outline()
    explicit = _outline("standard")
    assert explicit == baseline
    assert [o["type"] for o in baseline] == [
        "motivation", "major", "project", "scenario", "stress", "counter"]
    assert [o["question"] for o in explicit] == [o["question"] for o in baseline]


def test_mode_outline_type_sequences():
    standard = [o["type"] for o in _outline("standard")]
    easy = [o["type"] for o in _outline("easy")]
    stress = [o["type"] for o in _outline("stress")]

    assert easy == ["motivation", "major", "project", "scenario", "counter"]
    assert "stress" not in easy
    assert stress == ["motivation", "major", "stress", "project", "scenario", "counter"]
    assert stress[2] == "stress"
    # 题数不变、只是顺序变化
    assert sorted(standard) == sorted(easy + ["stress"]) == sorted(stress)


def test_unknown_mode_outline_falls_back_to_standard():
    assert _outline("bogus") == _outline("standard")


# ----------------------------------------------------------------
# 3) 追问阈值
# ----------------------------------------------------------------
def test_probe_thresholds_contract():
    assert probe_thresholds("easy") == {"score_below": 60.0, "answer_min": 60, "coverage_below": 0.4}
    assert probe_thresholds("standard") == {"score_below": 70.0, "answer_min": 80, "coverage_below": 0.5}
    assert probe_thresholds("stress") == {"score_below": 75.0, "answer_min": 100, "coverage_below": 0.55}
    assert probe_thresholds(None) == probe_thresholds("standard")
    assert probe_thresholds("bogus") == probe_thresholds("standard")


def test_probe_thresholds_change_decision_without_touching_score():
    answer = "乙" * 80  # 80 字：standard 的 answer_min 恰好不触发
    borderline = {"score": 70.0, "keyword_hits": ["Redis", "库存"], "keyword_missed": []}
    assert should_probe(borderline, answer, "major") is False
    assert should_probe(borderline, answer, "major", thresholds=probe_thresholds("standard")) is False
    assert should_probe(borderline, answer, "major", thresholds=probe_thresholds("stress")) is True

    mid = {"score": 65.0, "keyword_hits": ["Redis", "库存"], "keyword_missed": []}
    assert should_probe(mid, answer, "major", thresholds=probe_thresholds("standard")) is True
    assert should_probe(mid, answer, "major", thresholds=probe_thresholds("easy")) is False


# ----------------------------------------------------------------
# 4) 分数不依赖 mode
# ----------------------------------------------------------------
def test_score_is_identical_across_modes():
    scored = [score_answer(ANSWER, RUBRIC, EVIDENCE) for _ in MODE_LABELS]
    assert all(s == scored[0] for s in scored)

    # 同一题型在不同模式提纲里的 rubric 也必须逐字相同
    for qtype in ("major", "scenario", "stress", "counter"):
        rubrics = [next((o["rubric"] for o in _outline(m) if o["type"] == qtype), None)
                   for m in MODE_LABELS]
        present = [r for r in rubrics if r is not None]  # easy 没有 stress 题
        assert present and len(set(map(repr, present))) == 1, qtype


# ----------------------------------------------------------------
# 5) tone 只影响 system prompt；缺省/standard/未知一字不追加
# ----------------------------------------------------------------
def _capture(monkeypatch, tone: str | None = None):
    monkeypatch.setenv("AGENT_LLM_DRAFT", "1")
    seen: dict[str, str] = {}

    def fake(actor_type: str, *, system_prompt: str, user_prompt: str, tag: str = "draft"):
        seen["system"] = system_prompt
        seen["user"] = user_prompt
        return "你提到「支撑峰值5000并发且零超卖」，结构清晰；建议补上预算约束。"

    monkeypatch.setattr(interviewer.llm_client, "generate_reply", fake)
    item = score_answer(ANSWER, RUBRIC, EVIDENCE)
    assert item is not None
    out = interviewer.run_turn("请讲项目", "project", ANSWER, item, EVIDENCE, tone=tone)
    return seen, out


def test_tone_none_standard_and_unknown_leave_prompt_unchanged(monkeypatch):
    baseline, out_default = _capture(monkeypatch)  # 不传 tone
    none, _ = _capture(monkeypatch, None)
    standard, _ = _capture(monkeypatch, "standard")
    unknown, _ = _capture(monkeypatch, "bogus")

    assert baseline["system"] == none["system"] == standard["system"] == unknown["system"]
    assert "模式：" not in baseline["system"]
    assert out_default["comment_version"] == interviewer.COMMENT_VERSION


def test_easy_and_stress_only_append_style_rules(monkeypatch):
    baseline, _ = _capture(monkeypatch)
    easy, _ = _capture(monkeypatch, "easy")
    stress, _ = _capture(monkeypatch, "stress")

    assert easy["user"] == baseline["user"] == stress["user"]
    assert "轻松模式" in easy["system"] and "禁止使用否定性定性词" in easy["system"]
    assert "压力模式" in stress["system"] and "人身评价" in stress["system"]
    # 两种语气都必须保留原有引文逐字规则，一字不少
    for system in (baseline["system"], easy["system"], stress["system"]):
        assert "引用学生回答或简历时必须用「」原样摘抄" in system
