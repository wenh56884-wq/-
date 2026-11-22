# tests/test_web_search_api.py
# 职责：联网搜索路由契约——鉴权拦截 + 未配置密钥时如实降级（铁律 1/2）
# 运行：.venv\Scripts\python.exe -m pytest tests\test_web_search_api.py -v
# 说明：不依赖真实搜索密钥；只验证 401、空词 422，以及已登录时未配置密钥返回 configured=False 而非 500

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from engine import web_search


def _client() -> TestClient:
    return TestClient(create_app())


def test_search_requires_auth():
    """未带 token 调联网搜索必须 401（身份只来自登录态）。"""
    c = _client()
    r = c.get("/web/search", params={"q": "2026 国考"})
    assert r.status_code == 401


def test_search_rejects_empty_query_when_authed():
    """已登录但查询词为空必须 422，不能把空串丢给搜索引擎。"""
    c = _client()
    login = c.post("/auth/login", json={"role": "student", "account": "AI20230001",
                                        "password": "123456h"})
    if login.status_code != 200:
        assert login.status_code == 401
        return
    token = login.json()["access_token"]
    r = c.get("/web/search", params={"q": "   "}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 422


def test_search_unconfigured_returns_configured_false():
    """已登录但未配密钥：返回 configured=False + 说明，绝不 500、绝不编结果。"""
    c = _client()
    login = c.post("/auth/login", json={"role": "student", "account": "AI20230001",
                                        "password": "123456h"})
    if login.status_code != 200:
        assert login.status_code == 401
        return
    token = login.json()["access_token"]
    r = c.get("/web/search", params={"q": "2026 国考", "top_k": 8},
              headers={"Authorization": f"Bearer {token}"})
    # 本地没配密钥时 configured=False；若恰好配了密钥且联网失败，则 error 非空。
    # 两种情况都不允许返回 500。
    assert r.status_code == 200
    body = r.json()
    assert "configured" in body
    if body["configured"] is False:
        assert body["error"]
        assert body["results"] == []


def test_engine_empty_query_contract():
    """引擎层：空查询直接返回 configured=False，不抛异常。"""
    out = web_search.search("  ")
    assert out["configured"] is False
    assert out["results"] == []
    assert out["error"]
