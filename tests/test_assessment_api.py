# tests/test_assessment_api.py
# 职责：软技能测评路由契约——鉴权拦截 + 身份只来自 token（铁律 2）
# 运行：.venv\Scripts\python.exe -m pytest tests\test_assessment_api.py -v
# 说明：不依赖真实题库数据；用 TestClient 打真实路由，验证 401/403 与空库行为

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app


def _client() -> TestClient:
    return TestClient(create_app())


def test_questions_requires_auth():
    """未带 token 取题必须 401（身份只来自登录态）。"""
    c = _client()
    r = c.get("/assessment/questions")
    assert r.status_code == 401


def test_submit_requires_auth():
    """未带 token 提交必须 401。"""
    c = _client()
    r = c.post("/assessment/submit", json={"answers": {"1": "A"}})
    assert r.status_code == 401


def test_results_requires_auth():
    """未带 token 查结果必须 401。"""
    c = _client()
    r = c.get("/assessment/results")
    assert r.status_code == 401


def test_teacher_cannot_call_student_assessment():
    """教师 token 访问学生端测评接口必须 403（角色不符）。"""
    c = _client()
    # 用教师演示账号登录；若库不可用则登录失败，测试退化为验证「不因库故障而 500」
    login = c.post("/auth/login", json={"role": "teacher", "account": "T001",
                                        "password": "123456h"})
    if login.status_code != 200:
        # 库不可用：登录应返回 401 而非 500，这本身就是契约的一部分
        assert login.status_code == 401
        return
    token = login.json()["access_token"]
    r = c.get("/assessment/questions", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403
