# tests/test_brain.py
# 职责：自主大脑的规划校验、循环执行、观察反思、Critic 回退与对话接入。
# 依赖：pytest / agents.brain / agents.graph / 假 LLM 与假工具分发（不依赖真实模型）。
# 说明：测试不访问数据库：_connect 被替换为抛错，大脑按「无记忆」路径继续。

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402

from agents import brain, graph  # noqa: E402
from agents.tools import ToolContext  # noqa: E402


def _ctx() -> ToolContext:
    return ToolContext(actor_type="student", tenant_id=1, student_id=1)


def _no_db(monkeypatch):
    def _raise():
        raise RuntimeError("unit-test: no db")

    monkeypatch.setattr(brain, "_connect", _raise)
    monkeypatch.setenv("AGENT_MEMORY_EXTRACT", "0")


def _fake_llm(plan: dict, reflect: dict, draft: str):
    def fake(actor_type, *, system_prompt, user_prompt, tag="draft", on_token=None):
        if tag == "brain_plan":
            return json.dumps(plan, ensure_ascii=False)
        if tag == "brain_reflect":
            return json.dumps(reflect, ensure_ascii=False)
        if tag == "brain_draft":
            return draft
        if tag == "brain_memory":
            return "[]"
        return ""
    return fake


def _fake_dispatch(results: dict):
    def fake(ctx, name, args):
        return results[name]
    return fake


# ----------------------------------------------------------------
# 1. 模式判定与步骤校验
# ----------------------------------------------------------------
def test_should_run_modes(monkeypatch):
    monkeypatch.setenv("AGENT_BRAIN", "auto")
    assert brain.should_run("帮我查国考职位，同时看看我的预警")
    assert brain.should_run("先查岗位，再查差距")
    assert not brain.should_run("我的成绩怎么样")
    monkeypatch.setenv("AGENT_BRAIN", "0")
    assert not brain.should_run("帮我查国考职位，同时看看我的预警")
    monkeypatch.setenv("AGENT_BRAIN", "1")
    assert brain.should_run("我的成绩怎么样")


def test_valid_steps_filters_unknown_duplicates_and_side_effects():
    steps = brain._valid_steps([
        {"tool": "exam_notices", "args": {"exam_type": "civil"}, "purpose": "查公告"},
        {"tool": "exam_notices", "args": {"exam_type": "civil"}, "purpose": "重复"},
        {"tool": "not_a_tool", "args": {}, "purpose": "编造"},
        {"tool": "save_warning_thresholds", "args": {}, "purpose": "有副作用"},
        {"tool": "my_warning", "args": "not-a-dict", "purpose": "参数错"},
    ], {"exam_notices", "my_warning", "save_warning_thresholds"}, limit=6)
    assert [s["tool"] for s in steps] == ["exam_notices", "my_warning"]
    assert steps[1]["args"] == {}


def test_remember_regex():
    match = brain._REMEMBER_RE.match("记住：我想考公务员，优先重庆")
    assert match and "考公务员" in match.group(1)


# ----------------------------------------------------------------
# 2. 循环：两步执行 + 反思停止 + Critic 通过
# ----------------------------------------------------------------
def test_brain_runs_two_steps_and_passes_critic(monkeypatch):
    _no_db(monkeypatch)
    monkeypatch.setattr(brain.llm, "generate_reply", _fake_llm(
        {"thought": "先查公告再查预警",
         "steps": [
             {"tool": "exam_notices", "args": {"exam_type": "civil"}, "purpose": "查公告"},
             {"tool": "my_warning", "args": {}, "purpose": "查本人预警"},
         ]},
        {"done": True, "thought": "够了"},
        "共 2 条公告，风险分 80。",
    ))
    monkeypatch.setattr(graph, "_dispatch", _fake_dispatch({
        "exam_notices": {"notice_total": 2,
                         "items": [{"title": "公告A", "org_name": "单位",
                                    "signup_end": "2026-01-01", "detail_url": ""}]},
        "my_warning": {"risk_score": 80, "level": "红色", "reasons": ["挂科"]},
    }))
    result = brain.run_brain(_ctx(), "帮我查公告，同时看看我的预警")
    assert result is not None
    assert result["planner"] == "brain"
    assert [step["tool"] for step in result["steps"]] == ["exam_notices", "my_warning"]
    assert all(step["ok"] for step in result["steps"])
    assert result["verdict"]["passed"] is True
    assert result["degraded"] is False
    assert "2" in result["answer"] and "80" in result["answer"]


def test_brain_falls_back_to_template_when_critic_rejects(monkeypatch):
    _no_db(monkeypatch)
    monkeypatch.setattr(brain.llm, "generate_reply", _fake_llm(
        {"thought": "查公告",
         "steps": [{"tool": "exam_notices", "args": {}, "purpose": "查公告"}]},
        {"done": True},
        "共 999 条公告。",
    ))
    monkeypatch.setattr(graph, "_dispatch", _fake_dispatch({
        "exam_notices": {"notice_total": 2,
                         "items": [{"title": "公告A", "org_name": "单位",
                                    "signup_end": "2026-01-01", "detail_url": ""}]},
    }))
    result = brain.run_brain(_ctx(), "帮我查公告，同时分析一下")
    assert result is not None
    assert "999" not in result["answer"], "错误数值不能留在最终答案里"
    assert "2" in result["answer"], "应退回引擎模板直引"
    assert result["degraded"] is True


def test_brain_rejects_example_count_as_total(monkeypatch):
    _no_db(monkeypatch)
    monkeypatch.setattr(brain.llm, "generate_reply", _fake_llm(
        {"thought": "查职位",
         "steps": [{"tool": "exam_positions", "args": {"place": "重庆"},
                    "purpose": "查职位"}]},
        {"done": True},
        "重庆国考职位总数没查到，只看到 3 条。",
    ))
    monkeypatch.setattr(graph, "_dispatch", _fake_dispatch({
        "exam_positions": {"position_total": 284, "total_headcount": 461,
                           "positions": [{"dept_name": "A部门", "position_name": "P职位",
                                          "headcount": 6, "education": "本科",
                                          "work_place": "重庆"}]},
    }))
    result = brain.run_brain(_ctx(), "帮我查重庆国考职位，同时分析一下")
    assert result is not None
    assert "共命中 284 个" in result["answer"]
    assert "只看到 3 条" not in result["answer"]
    assert result["degraded"] is True


def test_brain_returns_none_when_planner_unavailable(monkeypatch):
    _no_db(monkeypatch)
    monkeypatch.setattr(brain.llm, "generate_reply",
                        lambda *a, **k: None)
    assert brain.run_brain(_ctx(), "帮我查公告，同时分析一下") is None


# ----------------------------------------------------------------
# 3. 接入对话：AGENT_BRAIN=1 时 run_chat 走大脑
# ----------------------------------------------------------------
def test_run_chat_uses_brain_when_enabled(monkeypatch):
    monkeypatch.setenv("AGENT_BRAIN", "1")
    sentinel = {"answer": "大脑结果", "trace_id": "t", "planner": "brain",
                "degraded": False, "attempts": 1, "tool_name": "brain",
                "citations": [], "suggested_followups": [], "steps": []}
    monkeypatch.setattr(brain, "run_brain", lambda *a, **k: sentinel)
    monkeypatch.setattr(graph, "audit_event", lambda **k: None)
    assert graph.run_chat(_ctx(), "帮我查公告，同时分析一下", history=[]) is sentinel


def test_run_chat_stream_emits_brain_progress(monkeypatch):
    monkeypatch.setenv("AGENT_BRAIN", "1")
    monkeypatch.setattr(graph, "audit_event", lambda **k: None)
    sentinel = {"answer": "大脑流式结果", "trace_id": "t2", "degraded": False,
                "attempts": 1, "tool_name": "brain", "citations": [],
                "suggested_followups": [], "steps": [{"index": 1, "tool": "exam_notices",
                                                      "ok": True}], "verdict": {}}

    def fake_run(ctx, query, **kwargs):
        callback = kwargs.get("on_event")
        if callback:
            callback({"stage": "plan", "text": "正在制定执行计划…"})
            callback({"stage": "tool", "tool": "exam_notices", "text": "正在调用 exam_notices…"})
        return sentinel

    monkeypatch.setattr(brain, "run_brain", fake_run)
    events = list(graph.run_chat_stream(_ctx(), "帮我查公告，同时分析一下", history=[]))
    statuses = [event for event in events if event.get("type") == "status"]
    assert any(event.get("stage") == "tool" for event in statuses)
    assert events[-1]["type"] == "done"
    assert events[-1]["answer"] == "大脑流式结果"
    assert events[-1]["steps"]


def test_describe_exposes_brain_and_memory(monkeypatch):
    monkeypatch.setenv("AGENT_BRAIN", "auto")
    info = brain.describe()
    assert info["brain_version"] == brain.BRAIN_VERSION
    assert info["mode"] == "auto"
    assert info["memory"] == "memory-v1"
    assert "save_warning_thresholds" in info["blocked_tools"]
