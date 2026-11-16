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


# ----------------------------------------------------------------
# 6) 完整四年主线（供前端时间轴）：all_steps 不改变 steps 的剩余阶段语义
# ----------------------------------------------------------------
def test_all_steps_is_full_plan_while_steps_remains_remaining():
    guide = career_guide.build_guide(grade="大三", intent="考公")
    assert len(guide["steps"]) == 2
    assert len(guide["all_steps"]) == 4
    assert [step["阶段"][:2] for step in guide["all_steps"]] == ["大一", "大二", "大三", "大四"]
    assert guide["all_steps"][2:] == guide["steps"]

    no_intent = career_guide.build_guide(grade="大一")
    assert no_intent["needs_intent"] is True
    assert no_intent["all_steps"] == []


# ----------------------------------------------------------------
# 7) 选课联动：不传参逐键不变；传参行动追加末尾 + 摘要键齐
# ----------------------------------------------------------------
ELECTIVE_FACTS = {
    "engine_version": "elective-v2",
    "recommendations": [
        {"name": "Java 程序设计", "direction": "后端", "credit": 3.0, "score": 0.65},
    ],
    "window": {"state": "closed",
               "text": "选课窗口 10月22日10:30-10月25日24:00（本窗口已结束，以后续教务处通知为准）"},
    "gened": {"applicable": False, "uncovered": []},
    "credits": {"total_required": 160.0, "earned": 83.5, "elected": 2.0, "remaining": 74.5},
    "policy": {"entry": {"url": "http://jwmis.cfec.edu.cn", "path": "一站式门户→教务管理系统→选课→自主选课→查询"},
               "source": {"title": "关于2026-2027-1学期线下通识课程选课的通知"}},
}


def test_build_guide_without_elective_is_unchanged():
    base = career_guide.build_guide(grade="大二", intent="就业",
                                    direction="后端", major="软件工程")
    assert "elective" not in base
    assert all("选修「" not in a for step in base["steps"] for a in step["行动"])
    assert base == career_guide.build_guide(grade="大二", intent="就业",
                                            direction="后端", major="软件工程")


def test_build_guide_elective_actions_appended_at_end():
    base = career_guide.build_guide(grade="大二", intent="就业",
                                    direction="后端", major="软件工程")
    linked = career_guide.build_guide(grade="大二", intent="就业",
                                      direction="后端", major="软件工程",
                                      elective=ELECTIVE_FACTS)
    base_actions = base["steps"][0]["行动"]
    actions = linked["steps"][0]["行动"]
    assert actions[:len(base_actions)] == base_actions, "原有行动顺序不能被挤占"
    assert any("选修「Java 程序设计」" in a and "0.65" in a for a in actions[len(base_actions):])
    assert not any("选课窗口内完成自主选课" in a for a in actions), "窗口 closed 不催选"
    summary = linked["elective"]
    assert summary["available"] is True
    assert summary["recommendations"][0]["name"] == "Java 程序设计"
    assert summary["credits"]["remaining"] == 74.5
    assert summary["entry"]["url"] == "http://jwmis.cfec.edu.cn"
    assert summary["engine_version"] == "elective-v2"
    open_facts = {**ELECTIVE_FACTS,
                  "window": {**ELECTIVE_FACTS["window"], "state": "open"}}
    opened = career_guide.build_guide(grade="大二", intent="就业", elective=open_facts)
    assert any("选课窗口内完成自主选课" in a for a in opened["steps"][0]["行动"])


def test_build_guide_needs_intent_keeps_empty_steps_but_summary():
    linked = career_guide.build_guide(grade="大一", intent=None, elective=ELECTIVE_FACTS)
    assert linked["needs_intent"] is True
    assert linked["steps"] == []
    assert linked["elective"]["available"] is True


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
