# tests/test_chat_capabilities.py
# 职责：对话助手六项能力的内核契约——RAG 切块/引用/防编数字、联网诚实降级、工作流白名单与失败即停。
# 说明：全部离线，不依赖 MySQL / 网络 / LLM。

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402

from agents import graph as agent_graph  # noqa: E402
from agents.tools import ToolContext  # noqa: E402
from engine import rag, web_search, workflow  # noqa: E402

CTX = ToolContext(actor_type="student", tenant_id=1, student_id=1)

# 语料与项目主题一致：学业 / 职业规划类制度，而不是企业报销制度
POLICY = """学业预警与帮扶管理办法

一、预警等级
累计挂科 6 门及以上为红色预警，3 至 5 门为橙色预警，1 至 2 门为黄色预警。

二、帮扶措施
红色预警学生须在 15 日内与学业导师面谈，橙色预警由班主任在 30 日内约谈。"""


def _rows(text: str = POLICY, doc_id: int = 1, title: str = "学业预警与帮扶管理办法"):
    chunks = rag.chunk_pages([(None, text)])
    return [{"doc_id": doc_id, "title": title, "chunk_no": c.chunk_no,
             "page": c.page, "text": c.text} for c in chunks]


# ----------------------------------------------------------------
# RAG / PDF
# ----------------------------------------------------------------
def test_detect_type_whitelist():
    assert rag.detect_type("制度.pdf") == "pdf"
    assert rag.detect_type("a.docx") == "docx"
    assert rag.detect_type("x.md") == "md"
    assert rag.detect_type("x.txt") == "txt"
    assert rag.detect_type("x.exe") is None
    assert rag.detect_type("noext") is None


def test_chunk_splits_on_page_boundary():
    """一块只能有一个页码：否则第 2 页的内容会被标成第 1 页，引用就错了。"""
    pages = [(1, "第一页的内容。" * 20), (2, "第二页的内容。" * 20)]
    chunks = rag.chunk_pages(pages)
    assert {c.page for c in chunks} == {1, 2}
    for c in chunks:
        assert "第一页" not in c.text or "第二页" not in c.text


def test_chunk_numbers_are_contiguous():
    chunks = rag.chunk_pages([(None, POLICY)])
    assert [c.chunk_no for c in chunks] == list(range(1, len(chunks) + 1))


def test_search_returns_empty_for_irrelevant_query():
    assert rag.search("量子纠缠的退相干时间", _rows()) == []


def test_search_hits_carry_page_and_score():
    hits = rag.search("预警等级", _rows())
    assert hits and hits[0]["score"] > 0
    assert "预警等级" in hits[0]["text"]


def test_verify_citations_requires_reference():
    hits = rag.search("预警等级", _rows())
    ok, problems = rag.verify_citations("红色预警要求累计挂科 6 门。", hits)
    assert not ok and "没有" in problems[0]


def test_verify_citations_rejects_invented_number():
    """引用编号是真的、数字是编的——这类答案最容易骗过人工抽查。"""
    hits = rag.search("预警等级", _rows())
    ok, problems = rag.verify_citations("红色预警要求累计挂科 8 门[1]。", hits)
    assert not ok and any("8" in p for p in problems)


def test_verify_citations_accepts_verbatim_quote_and_number():
    hits = rag.search("预警等级", _rows())
    text = "红色预警要求累计挂科 6 门[1]，原文：「3 至 5 门为橙色预警」。"
    ok, problems = rag.verify_citations(text, hits)
    assert ok, problems


def test_verify_citations_rejects_fake_quote():
    hits = rag.search("预警等级", _rows())
    ok, _ = rag.verify_citations("办法写的是「挂科一律劝退」[1]。", hits)
    assert not ok


def test_citations_map_to_numbers():
    hits = rag.search("预警等级", _rows())
    cites = rag.as_citations(hits)
    assert [c["no"] for c in cites] == list(range(1, len(cites) + 1))
    assert all(c["title"] == "学业预警与帮扶管理办法" for c in cites)


# ----------------------------------------------------------------
# 联网搜索：没有密钥就说没有
# ----------------------------------------------------------------
def test_web_search_unconfigured_is_honest(monkeypatch):
    # 三家都要清干净：.env 里配了哪家，漏清哪家这条就会「明明没网却说有网」。
    # 博查（BOCHA_API_KEY）是后加的 provider，当初只清了 serper / bing 两家。
    for key in ("SERPER_API_KEY", "BING_SEARCH_KEY", "BOCHA_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    assert web_search.configured() is False
    res = web_search.search("重庆 秋招 政策")
    assert res["configured"] is False
    assert res["results"] == []
    assert "没有联网能力" in (res["error"] or "")


def test_web_search_empty_query_does_not_call_provider(monkeypatch):
    monkeypatch.setenv("SERPER_API_KEY", "fake")
    res = web_search.search("   ")
    assert res["results"] == []
    assert res["error"] == "查询为空"


# ----------------------------------------------------------------
# 工作流
# ----------------------------------------------------------------
STEPS = [
    {"id": "a", "tool": "my_warning", "title": "预警"},
    {"id": "b", "tool": "my_recommendations", "title": "推荐"},
]


def test_workflow_rejects_non_whitelisted_tool():
    problems = workflow.validate([{"id": "x", "tool": "__import__"}])
    assert problems and "白名单" in problems[0]


def test_workflow_rejects_duplicate_ids_and_too_many_steps():
    assert workflow.validate([{"id": "a", "tool": "my_warning"},
                              {"id": "a", "tool": "my_warning"}])
    many = [{"id": f"s{i}", "tool": "my_warning"} for i in range(workflow.MAX_STEPS + 1)]
    assert workflow.validate(many)


def test_workflow_runs_in_order_and_records_each_step():
    calls: list[str] = []

    def impl(name):
        def _fn(**kw):
            calls.append(name)
            return {"tool": name, "value": 1}
        return _fn

    result = workflow.run(STEPS, {"my_warning": impl("warn"),
                                  "my_recommendations": impl("rec")})
    assert calls == ["warn", "rec"]
    assert result["status"] == "success"
    assert [s["status"] for s in result["steps"]] == ["success", "success"]
    assert len(result["outputs"]) == 2


def test_workflow_stops_on_failure_by_default():
    def boom(**kw):
        raise RuntimeError("数据不可用")

    result = workflow.run(STEPS, {"my_warning": boom,
                                  "my_recommendations": lambda **kw: {"ok": True}})
    assert result["status"] == "failed"
    assert len(result["steps"]) == 1, "默认失败即停，不应继续执行后续步骤"
    assert "数据不可用" in (result["error"] or "")


def test_workflow_continue_when_explicitly_allowed():
    steps = [{"id": "a", "tool": "my_warning", "on_error": "continue"},
             {"id": "b", "tool": "my_recommendations"}]

    def boom(**kw):
        raise RuntimeError("单步失败")

    result = workflow.run(steps, {"my_warning": boom,
                                  "my_recommendations": lambda **kw: {"ok": True}})
    assert len(result["steps"]) == 2
    assert result["steps"][0]["status"] == "failed"
    assert result["steps"][1]["status"] == "success"


def test_workflow_reference_resolution():
    steps = [{"id": "a", "tool": "my_warning"},
             {"id": "b", "tool": "my_recommendations", "args": {"seed": "{{steps.a.value}}"}}]
    seen: dict = {}

    def rec(**kw):
        seen.update(kw)
        return {"ok": True}

    workflow.run(steps, {"my_warning": lambda **kw: {"value": 7}, "my_recommendations": rec})
    assert seen["seed"] == 7


def test_workflow_bad_reference_fails_fast():
    steps = [{"id": "a", "tool": "my_warning"},
             {"id": "b", "tool": "my_recommendations", "args": {"seed": "{{steps.a.nope}}"}}]
    result = workflow.run(steps, {"my_warning": lambda **kw: {"value": 1},
                                  "my_recommendations": lambda **kw: {"ok": True}})
    assert result["status"] == "failed"
    assert "取不到值" in (result["error"] or "")


def test_workflow_chat_draft_has_no_digits():
    """对话里的工作流稿不能带数字：Critic 只认工具结果里的数字，凭空的数字会被打回。"""
    draft = agent_graph._workflow_draft({
        "status": "success", "name": "求职体检",
        "steps": [{"id": "a", "tool": "my_warning", "title": "预警", "status": "success"}]})
    assert "✅" in draft
    assert not any(ch.isdigit() for ch in draft), draft


def test_workflow_summary_marks_failure():
    result = {"status": "failed", "steps": [
        {"id": "a", "tool": "x", "title": "预警", "status": "failed", "error": "数据不可用"}],
        "error": "第 a 步失败：数据不可用", "elapsed_ms": 3}
    summary = workflow.render_summary(result)
    assert "❌" in summary and "数据不可用" in summary


# ----------------------------------------------------------------
# 意图路由：六项能力要能被正确选中
# ----------------------------------------------------------------
def _plan(query: str, last_tool: str | None = None) -> str:
    return agent_graph.plan_node({"ctx": CTX, "query": query, "last_tool": last_tool,
                                  "history": []})["tool_name"]


def test_plan_routes_kb_question_to_rag():
    assert _plan("学业预警管理办法里红色预警怎么定") == "kb_search"
    assert _plan("实习制度里要实习多少周") == "kb_search"


def test_plan_routes_workflow_phrase():
    assert _plan("帮我跑一遍求职体检") == "run_workflow"


def test_plan_routes_web_only_on_explicit_ask():
    assert _plan("联网搜一下今年的秋招政策") == "web_search"
    # 没有「网上/联网」字样时不能被误判到联网
    assert _plan("最新的预警名单") != "web_search"


def test_plan_reuses_last_tool_for_followup():
    plan = agent_graph.plan_node(
        {"ctx": CTX, "query": "那重修呢", "last_tool": "kb_search",
         "history": [{"role": "user", "text": "学业预警管理办法里红色预警怎么定"}]})
    assert plan["tool_name"] == "kb_search"
    assert "学业预警管理办法里红色预警怎么定" in plan["plan"]["args"]["query"], \
        "追问要带上一轮问题，否则检索不到"


def test_plan_does_not_reuse_tool_for_long_question():
    assert _plan("这一届学生整体的发展情况是怎么安排的", last_tool="kb_search") != "kb_search"


def test_chitchat_does_not_touch_data():
    assert _plan("你好") == "chitchat"
