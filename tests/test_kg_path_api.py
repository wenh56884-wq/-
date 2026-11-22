# tests/test_kg_path_api.py
# 职责：锁定学生端 /kg/path/my——身份只来自登录态、教师/匿名被拒、透传 engine.kg 差距结构。
# 说明：TestClient + dependency_overrides + monkeypatch，隔离真实 JWT / 图谱 / 数据库。

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agents.tools import ToolContext
from app.auth import get_current_ctx
from app.main import create_app
from app.routers import kg as kg_router

pytestmark = pytest.mark.kg

STUDENT_CTX = ToolContext(actor_type="student", tenant_id=1, student_id=7)
TEACHER_CTX = ToolContext(actor_type="teacher", tenant_id=1, teacher_id=3)

PATH_RESULT = {
    "found": True,
    "version": "kg-v1",
    "major": "会计学",
    "job_id": 42,
    "job": "会计专员",
    "direction": "财务",
    "required": ["会计核算", "Excel", "税务处理"],
    "covered": ["会计核算", "Excel"],
    "missing": ["税务处理"],
    "chain": [
        {"skill": "会计核算", "owned_as": "会计核算",
         "courses": ["基础会计"], "job": "会计专员"},
    ],
    "summary": "岗位要求 3 项技能，课程链覆盖 2 项，缺 1 项：税务处理",
}


def _client(ctx: ToolContext | None = None) -> TestClient:
    app = create_app()
    if ctx is not None:
        app.dependency_overrides[get_current_ctx] = lambda: ctx
    return TestClient(app)


def test_student_gets_path_for_own_major(monkeypatch):
    """学生登录态 → 调用 kg_path(job_id)，专业不由请求指定。"""
    calls: dict = {}

    def fake_kg_path(ctx, job_id=0, major=""):
        calls.update(ctx=ctx, job_id=job_id, major=major)
        return dict(PATH_RESULT)

    monkeypatch.setattr(kg_router.tools, "kg_path", fake_kg_path)
    resp = _client(STUDENT_CTX).get("/kg/path/my", params={"job_id": 42})

    assert resp.status_code == 200, resp.text
    assert calls["ctx"] is STUDENT_CTX
    assert calls["job_id"] == 42
    assert calls["major"] == ""
    body = resp.json()
    assert body["found"] is True
    for key in ("required", "covered", "missing", "chain"):
        assert isinstance(body[key], list)
    assert body["missing"] == ["税务处理"]
    assert "缺 1 项" in body["summary"]


def test_anonymous_is_401():
    """无 token → 401，不进入引擎。"""
    resp = _client().get("/kg/path/my", params={"job_id": 42})
    assert resp.status_code == 401


def test_teacher_is_403_and_tool_not_called(monkeypatch):
    """教师访问学生端工具 → 403；学生端取数函数不得被调用。"""
    monkeypatch.setattr(
        kg_router.tools, "kg_path",
        lambda *args, **kwargs: pytest.fail("教师不应进入学生端 kg_path"),
    )
    resp = _client(TEACHER_CTX).get("/kg/path/my", params={"job_id": 42})
    assert resp.status_code == 403


def test_engine_not_found_is_passed_through(monkeypatch):
    """岗位不在图谱 → 200 + found=false（前端据此显示缺失态，不当作接口故障）。"""
    monkeypatch.setattr(
        kg_router.tools, "kg_path",
        lambda ctx, job_id=0, major="": {"found": False, "reason": "岗位不在图谱中"},
    )
    resp = _client(STUDENT_CTX).get("/kg/path/my", params={"job_id": 999999})

    assert resp.status_code == 200
    assert resp.json() == {"found": False, "reason": "岗位不在图谱中"}


def test_tool_value_error_is_400(monkeypatch):
    """工具层身份/专业缺失 → 400（不让 500 冒出去）。"""

    def fake_kg_path(ctx, job_id=0, major=""):
        raise ValueError("请说明要查哪个专业")

    monkeypatch.setattr(kg_router.tools, "kg_path", fake_kg_path)
    resp = _client(STUDENT_CTX).get("/kg/path/my", params={"job_id": 42})

    assert resp.status_code == 400
    assert resp.json()["detail"] == "请说明要查哪个专业"


def test_job_id_must_be_positive(monkeypatch):
    """job_id 参数校验：0 直接 422，不进入引擎。"""
    monkeypatch.setattr(
        kg_router.tools, "kg_path",
        lambda *args, **kwargs: pytest.fail("非法 job_id 不应进入引擎"),
    )
    resp = _client(STUDENT_CTX).get("/kg/path/my", params={"job_id": 0})
    assert resp.status_code == 422
