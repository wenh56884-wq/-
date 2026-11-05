# tests/test_pet_engine.py
# 职责：验证 engine/pet.py 的确定性数值逻辑——心情、记忆窗口、主动说话调度、模板兜底。
# 铁律 1：这些是数值真相源，必须单测锁死，LLM 不可参与。

from __future__ import annotations

import time

import pytest

from engine import pet as pet_engine


# ---------------- 心情 ----------------


def test_mood_decay_lowers_intensity_over_time():
    m = pet_engine.MoodState(intensity=1.0, last_interact_at=0.0)
    m.decay(now=10.0)
    assert m.intensity < 1.0


def test_mood_decay_clamped_at_floor():
    m = pet_engine.MoodState(intensity=0.05, last_interact_at=0.0)
    m.decay(now=1000.0)
    assert m.intensity == pytest.approx(0.05)


def test_long_inactivity_makes_pet_sleepy():
    m = pet_engine.MoodState(intensity=0.8, last_interact_at=0.0)
    m.decay(now=pet_engine.SLEEPY_THRESHOLD_SEC + 1)
    assert m.mood == pet_engine.MOOD_SLEEPY


def test_interaction_boosts_intensity_and_sets_mood():
    m = pet_engine.MoodState(intensity=0.1, last_interact_at=0.0)
    before = m.intensity
    m.apply_interaction(pet_engine.MOOD_HAPPY)
    assert m.intensity > before
    assert m.mood == pet_engine.MOOD_HAPPY


def test_invalid_interaction_mood_falls_back_to_happy():
    m = pet_engine.MoodState()
    m.apply_interaction("nonsense")
    assert m.mood == pet_engine.MOOD_HAPPY


def test_animation_mood_maps_happy_when_intense():
    m = pet_engine.MoodState(mood=pet_engine.MOOD_HAPPY, intensity=0.8)
    assert m.animation_mood() == pet_engine.MOOD_HAPPY


def test_animation_mood_sleepy_when_low_intensity():
    # 强度低于 0.3 时，无论基础心情是什么都画成困倦
    m = pet_engine.MoodState(mood=pet_engine.MOOD_HAPPY, intensity=0.2)
    assert m.animation_mood() == pet_engine.MOOD_SLEEPY


def test_animation_mood_idle_when_mid_intensity_not_happy():
    # 中等强度、不是开心 → 静止 idle
    m = pet_engine.MoodState(mood=pet_engine.MOOD_IDLE, intensity=0.4)
    assert m.animation_mood() == pet_engine.MOOD_IDLE


# ---------------- 短期记忆 ----------------


def test_short_memory_keeps_window_size():
    mem = pet_engine.ShortMemory(max_turns=5)
    for i in range(10):
        mem.add("user", f"q{i}", now=float(i))
    assert len(mem.turns) == 5
    # 裁掉的是最早的，保留最新的
    assert mem.turns[-1].text == "q9"
    assert mem.turns[0].text == "q5"


def test_short_memory_rejects_invalid_role():
    mem = pet_engine.ShortMemory()
    with pytest.raises(ValueError):
        mem.add("system", "x", now=0.0)


def test_short_memory_recent_limit():
    mem = pet_engine.ShortMemory(max_turns=10)
    for i in range(6):
        mem.add("user", f"q{i}", now=float(i))
    recent = mem.recent(limit=3)
    assert len(recent) == 3
    assert recent[-1].text == "q5"


def test_short_memory_clear():
    mem = pet_engine.ShortMemory()
    mem.add("user", "hi", now=0.0)
    mem.clear()
    assert len(mem.turns) == 0


# ---------------- 主动说话调度 ----------------


def test_proactive_speaks_after_interval():
    s = pet_engine.ProactiveScheduler(interval_sec=10, last_spoke_at=0.0)
    assert s.should_speak(now=5.0) is False
    assert s.should_speak(now=10.0) is True


def test_proactive_focus_mode_blocks_speaking():
    s = pet_engine.ProactiveScheduler(interval_sec=10, last_spoke_at=0.0, focus_mode=True)
    assert s.should_speak(now=1000.0) is False


def test_proactive_on_spoke_resets_timer():
    s = pet_engine.ProactiveScheduler(interval_sec=10, last_spoke_at=0.0)
    s.on_spoke(now=10.0)
    assert s.should_speak(now=19.0) is False
    assert s.should_speak(now=20.0) is True


def test_proactive_toggle_focus_returns_new_state():
    s = pet_engine.ProactiveScheduler()
    assert s.focus_mode is False
    assert s.toggle_focus() is True
    assert s.focus_mode is True


def test_proactive_next_speak_at_inf_when_focus():
    s = pet_engine.ProactiveScheduler(interval_sec=10, last_spoke_at=0.0, focus_mode=True)
    assert s.next_speak_at(now=5.0) == float("inf")


# ---------------- 状态聚合 + 模板兜底 ----------------


def test_build_state_aggregates_all_components():
    mood = pet_engine.MoodState(mood=pet_engine.MOOD_HAPPY, intensity=0.8)
    sched = pet_engine.ProactiveScheduler(interval_sec=10, last_spoke_at=0.0)
    mem = pet_engine.ShortMemory(max_turns=5)
    mem.add("user", "hi", now=0.0)
    state = pet_engine.build_state(mood, sched, mem, now=5.0)
    assert state.mood == pet_engine.MOOD_HAPPY
    assert state.intensity == pytest.approx(0.8)
    assert state.focus_mode is False
    assert state.memory_size == 1


def test_template_reply_is_readable_without_llm():
    reply = pet_engine.template_reply(pet_engine.DEFAULT_PERSONALITY, "今天考试好紧张")
    assert "加油" in reply or "慢慢来" in reply or "你做得很好" in reply


def test_default_personality_is_configured():
    assert pet_engine.DEFAULT_PERSONALITY.name == "小航"
    assert len(pet_engine.DEFAULT_PERSONALITY.encourage_pool) >= 1


def test_clamp_helper():
    assert pet_engine.clamp(0.5, 0.0, 1.0) == 0.5
    assert pet_engine.clamp(-1.0, 0.0, 1.0) == 0.0
    assert pet_engine.clamp(2.0, 0.0, 1.0) == 1.0
