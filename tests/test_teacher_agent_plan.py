# tests/test_teacher_agent_plan.py
# 职责：教师端智能体能力层契约——意图路由、参数抠取、阈值工具、错误口径。
# 说明：全部离线，不依赖 MySQL / 网络 / LLM；_query 统一 monkeypatch。

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402

from agents import graph as agent_graph  # noqa: E402
from agents import teacher_agent  # noqa: E402
from agents.tools import ToolContext  # noqa: E402

CTX = ToolContext(actor_type="teacher", tenant_id=1, teacher_id=7)


def _plan(query: str, history: list[dict[str, str]] | None = None,
          term: str | None = None) -> dict:
    return agent_graph.plan_node({"ctx": CTX, "query": query, "term": term,
                                  "history": history or [], "last_tool": None})


@pytest.fixture
def no_db(monkeypatch):
    """默认打掉 DB：路由测试不该碰库；需要命中兜底班级时单独 patch。"""
    monkeypatch.setattr(teacher_agent, "_query", lambda *a, **k: [])


# ----------------------------------------------------------------
# 意图路由
# ----------------------------------------------------------------
def test_plan_teacher_overview_by_default(no_db):
    assert _plan("AI2201 这学期整体情况怎么样")["tool_name"] == "class_overview"


def test_plan_teacher_warning_list_with_level(no_db):
    plan = _plan("AI2201 这学期红色预警有哪些人")
    assert plan["tool_name"] == "warning_list"
    assert plan["plan"]["args"]["level"] == "red"


def test_plan_teacher_profile_by_student_no(no_db):
    plan = _plan("看下 AI22010101 的画像")
    assert plan["tool_name"] == "student_profile"
    assert plan["plan"]["args"]["student_no"] == "AI22010101"


def test_plan_teacher_profile_by_chinese_name(no_db, monkeypatch):
    monkeypatch.setattr(teacher_agent, "_query",
                        lambda *a, **k: [{"student_no": "AI22010102"}])
    plan = _plan("看下张三的画像")
    assert plan["tool_name"] == "student_profile"
    assert plan["plan"]["args"]["student_no"] == "AI22010102"


def test_plan_teacher_ambiguous_name_falls_back(no_db, monkeypatch):
    # 重名：两人同名 → 不瞎猜，兜底到第一个学生（_query 返回空再兜底）
    monkeypatch.setattr(teacher_agent, "_query", lambda *a, **k: [])
    plan = _plan("看下张三的画像")
    assert plan["tool_name"] == "student_profile"
    assert "student_no" in plan["plan"]["args"]


def test_plan_teacher_thresholds(no_db):
    plan = _plan("AI2201 的预警阈值是多少")
    assert plan["tool_name"] == "warning_thresholds"
    assert plan["plan"]["args"]["class_name"] == "AI2201"


def test_plan_teacher_gap(no_db):
    assert _plan("AI2201 和岗位要求的差距在哪")["tool_name"] == "career_gap"


def test_plan_teacher_term_phrase(no_db):
    plan = _plan("AI2201 上学期挂科的名单")
    assert plan["tool_name"] == "warning_list"


# ----------------------------------------------------------------
# 等级 / 学期抠取（纯函数）
# ----------------------------------------------------------------
def test_extract_level_words():
    assert teacher_agent.extract_level("红色预警有哪些") == "red"
    assert teacher_agent.extract_level("橙色名单") == "orange"
    assert teacher_agent.extract_level("黄色") == "yellow"
    assert teacher_agent.extract_level("全部名单") is None


def test_extract_student_name_ignores_stop_words():
    assert teacher_agent._extract_student_name("看下张三的画像") == "张三"
    assert teacher_agent._extract_student_name("这个学生的情况") is None


def test_resolve_student_no_rejects_duplicates(monkeypatch):
    monkeypatch.setattr(teacher_agent, "_query",
                        lambda *a, **k: [{"student_no": "A1"}, {"student_no": "A2"}])
    assert teacher_agent.resolve_student_no(CTX, "看下李四的画像") == ""


# ----------------------------------------------------------------
# 工具节点与模板稿
# ----------------------------------------------------------------
def test_template_draft_renders_thresholds():
    result = {
        "class_name": "AI2201", "source": "tenant",
        "thresholds": [
            {"metric": "fail_count", "label": "挂科门次", "source": "class",
             "weight": 40, "yellow_value": 1, "orange_value": 2, "red_value": 3},
        ],
    }
    draft = agent_graph._template_draft(result)
    assert "挂科门次" in draft and "来源 class" in draft


def test_template_draft_distinguishes_bad_request_from_denied():
    denied = agent_graph._template_draft({"error": "越权已拦截"})
    bad = agent_graph._template_draft({"error": "班级不存在", "error_kind": "bad_request"})
    assert "没有访问权限" in denied
    assert "查不了" in bad and "越权" not in bad


def test_tool_node_wraps_value_error(monkeypatch):
    def boom(ctx, class_name, term, level=None):
        raise ValueError("班级「ZZZZ」不存在（本租户没有这个班）")

    monkeypatch.setattr(agent_graph.tools, "warning_list", boom)
    out = agent_graph.tool_node({
        "ctx": CTX, "tool_name": "warning_list",
        "plan": {"tool": "warning_list", "args": {"class_name": "ZZZZ", "term": ""}},
    })
    assert out["tool_result"]["error_kind"] == "bad_request"


def test_teacher_chat_system_is_distinct():
    assert teacher_agent.TEACHER_CHAT_SYSTEM != agent_graph._CHAT_SYSTEM
    assert "辅导员" in teacher_agent.TEACHER_CHAT_SYSTEM
