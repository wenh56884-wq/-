# tests/test_interview_probe.py
# 职责：真实面试追问契约——浅答/漏考点才追问、题库取题可回溯、强答不追问。
# 说明：全部离线，不依赖 MySQL / LLM / 网络。

from __future__ import annotations

import pytest

from engine import interview_probe as probe

JOB = {"title": "Java后端开发工程师", "industry": "计算机软件",
       "skill_tags": ["Java", "MySQL", "Spring Boot"]}
ITEM_LOW = {"score": 55, "keyword_hits": ["Java"], "keyword_missed": ["索引", "事务"]}
ITEM_HIGH = {"score": 88, "keyword_hits": ["Java", "索引", "事务", "锁"], "keyword_missed": []}
SHORT = "我会认真做。"
LONG = "背景是课程项目需要高并发，我的目标是把接口响应降到 200ms 以内；行动上先加索引，再用 Redis 缓存热点数据，最后压测验证；结果是 P95 从 800ms 降到 180ms。"


def test_should_probe_when_answer_is_shallow_or_misses_keywords():
    assert probe.should_probe(ITEM_LOW, SHORT, "project") is True
    assert probe.should_probe(ITEM_LOW, LONG, "project") is True


def test_should_not_probe_strong_answer():
    assert probe.should_probe(ITEM_HIGH, LONG, "project") is False


def test_should_not_probe_unanswered_or_counter():
    assert probe.should_probe(None, LONG, "project") is False
    assert probe.should_probe(ITEM_LOW, "", "project") is False
    assert probe.should_probe(ITEM_LOW, SHORT, "counter") is False


def test_pick_probe_is_deterministic_and_skips_used():
    first = probe.pick_probe(JOB, "project")
    assert first and first["source_url"].startswith("http")
    again = probe.pick_probe(JOB, "project")
    assert again["id"] == first["id"]

    other = probe.pick_probe(JOB, "project", used_ids=[first["id"]])
    assert other is None or other["id"] != first["id"]


def test_probe_plan_carries_bank_source_and_student_quote():
    plan = probe.probe_plan(JOB, "project", ITEM_LOW, SHORT)
    assert plan is not None
    assert plan["source_url"].startswith("http")
    assert plan["question_raw"] in plan["question"]
    assert "「我会认真做。」" in plan["question"]
    assert plan["engine_version"] == "probe-v1"


def test_probe_plan_none_for_strong_answer():
    assert probe.probe_plan(JOB, "project", ITEM_HIGH, LONG) is None


def test_probe_plan_none_when_bank_empty(tmp_path):
    assert probe.probe_plan(JOB, "project", ITEM_LOW, SHORT, bank_dir=tmp_path) is None


def test_env_switch(monkeypatch):
    monkeypatch.setenv("INTERVIEW_PROBE", "0")
    assert probe.enabled() is False
    monkeypatch.setenv("INTERVIEW_PROBE", "1")
    assert probe.enabled() is True
