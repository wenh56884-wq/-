# tests/test_chat_analyze.py
# 职责：覆盖 AI 助手临时资料分析接口的多文件读取、来源隔离与空请求校验。
# 依赖：pytest / fastapi TestClient；不连接真实 LLM 或共享知识库。
# 说明：上传内容只在本次请求中解析，接口返回来源清单但不落共享知识库。

from __future__ import annotations

from fastapi.testclient import TestClient

from agents.tools import ToolContext
from app.auth import get_current_ctx
from app.main import create_app


def _client() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_ctx] = lambda: ToolContext(
        actor_type="student", tenant_id=1, student_id=7, term="2025-2026-2"
    )
    return TestClient(app)


def test_analyze_sources_reads_multiple_files_without_persisting(monkeypatch):
    from agents import llm

    monkeypatch.setattr(llm, "generate_reply", lambda *args, **kwargs: "基于两份资料的交叉结论")
    client = _client()
    response = client.post(
        "/chat/analyze",
        data={"query": "比较两份资料的重点", "use_knowledge_base": "false", "use_web": "false"},
        files=[
            ("files", ("a.txt", "第一份资料：课程要求。".encode(), "text/plain")),
            ("files", ("b.md", "第二份资料：岗位要求。".encode(), "text/markdown")),
        ],
    )
    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "基于两份资料的交叉结论"
    assert body["source_count"] == 2
    assert [item["name"] for item in body["sources"]] == ["a.txt", "b.md"]
    assert body["stored"] is False


def test_analyze_sources_requires_a_source():
    response = _client().post(
        "/chat/analyze",
        data={"query": "请分析", "use_knowledge_base": "false", "use_web": "false"},
    )
    assert response.status_code == 422
