# tests/test_career_guide.py
# 职责：校验按年级分层的确定性生涯规划（大一先选目标，大二/大三直接给路径）
# 依赖：engine.career_guide（纯函数，全程离线）
# 说明：不连 MySQL / DuckDB / 模型；只断言引擎输出的结构与确定性

from __future__ import annotations

from datetime import date

import pytest

from engine import career_guide


TODAY = date(2026, 10, 26)


# ----------------------------------------------------------------
# 1) 年级与阶段
# ----------------------------------------------------------------
def test_grade_label_and_stage():
    assert career_guide.grade_label(2026, TODAY) == "大一"
    assert career_guide.grade_label(2025, TODAY) == "大二"
    assert career_guide.grade_label(2024, TODAY) == "大三"
    assert career_guide.grade_label(2023, TODAY) == "大四"
    assert career_guide.grade_label(2022, TODAY) == "已毕业"
    assert career_guide.grade_label(None, TODAY) is None
    assert career_guide.stage_of("大一") == "freshman"
    assert career_guide.stage_of("大二") == "sophomore"
    assert career_guide.stage_of("未知") == "unknown"


# ----------------------------------------------------------------
# 2) 大一新生：未选目标必须先选
# ----------------------------------------------------------------
def test_freshman_must_choose_intent():
    guide = career_guide.build_guide(grade="大一")
    assert guide["needs_intent"] is True
    assert guide["intent"] is None
    assert guide["steps"] == []
    assert [opt["value"] for opt in guide["options"]] == list(career_guide.INTENTS)
    assert "先定方向" in guide["headline"]


def test_freshman_plan_after_intent():
    guide = career_guide.build_guide(grade="大一", intent="考编")
    assert guide["needs_intent"] is False
    assert guide["intent"] == "考编"
    assert len(guide["steps"]) == 4
    assert guide["steps"][0]["阶段"].startswith("大一")
    assert "考编" in guide["headline"]


# ----------------------------------------------------------------
# 3) 大二/大三：未选目标也直接给规划，不强制先选
# ----------------------------------------------------------------
def test_sophomore_gets_explore_plan_without_intent():
    guide = career_guide.build_guide(grade="大二")
    assert guide["needs_intent"] is False
    assert guide["intent"] is None
    assert len(guide["steps"]) >= 2
    assert guide["steps"][0]["阶段"].startswith("大二")


def test_junior_with_intent_starts_from_junior():
    guide = career_guide.build_guide(grade="大三", intent="考研")
    assert guide["needs_intent"] is False
    assert len(guide["steps"]) == 2
    assert guide["steps"][0]["阶段"].startswith("大三")


def test_senior_and_graduated_get_final_stage():
    senior = career_guide.build_guide(grade="大四", intent="就业")
    assert len(senior["steps"]) == 1
    assert senior["steps"][0]["阶段"].startswith("大四")

    graduated = career_guide.build_guide(grade="已毕业", intent="考公")
    assert len(graduated["steps"]) == 1
    assert graduated["steps"][0]["阶段"].startswith("毕业后")


# ----------------------------------------------------------------
# 4) 方向优先级与非法目标
# ----------------------------------------------------------------
def test_direction_prefers_profile_over_intent():
    guide = career_guide.build_guide(
        grade="大二", intent="就业", direction="数据", major="软件工程",
    )
    assert guide["direction"] == {"name": "数据", "source": "profile.interest"}

    fallback = career_guide.build_guide(grade="大二", intent="考研")
    assert fallback["direction"]["name"] == "本专业深造"
    assert fallback["direction"]["source"] == "intent"


def test_invalid_intent_is_treated_as_unselected():
    guide = career_guide.build_guide(grade="大一", intent="随便")
    assert guide["intent"] is None
    assert guide["needs_intent"] is True


# ----------------------------------------------------------------
# 5) 同输入同输出（无随机数）
# ----------------------------------------------------------------
def test_build_guide_is_deterministic():
    first = career_guide.build_guide(grade="大三", intent="考公", direction="数据")
    second = career_guide.build_guide(grade="大三", intent="考公", direction="数据")
    assert first == second
    assert first["engine_version"] == career_guide.GUIDE_ENGINE_VERSION


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
