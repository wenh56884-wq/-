# tests/test_security_hardening.py
# 职责：锁定安全收口——JWT fail-closed、匿名写接口、审计租户隔离。
# 说明：JWT/审计写入为离线单测；接口鉴权使用 TestClient，不触发实际重建或重载。

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agents import tools as tools_mod
from agents.tools import ToolContext
from app import audit as audit_mod
from app import auth
from app.main import _should_persist_db_audit, create_app
from app.routers import chat as chat_router
from app.routers import kg as kg_router
from app.routers import question_bank as qb_router
from starlette.requests import Request


def _settings(secret: str) -> SimpleNamespace:
    return SimpleNamespace(jwt_secret=secret)


@pytest.mark.parametrize(
    "secret",
    ["", "short-secret", "REPLACE_WITH_32_RANDOM_CHARS", "qihang-dev-secret-change-me"],
)
def test_jwt_secret_fails_closed(secret):
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        auth._secret(_settings(secret))


def test_jwt_secret_accepts_strong_value():
    secret = "0123456789abcdef0123456789abcdef"
    assert auth._secret(_settings(secret)) == secret


def test_public_demo_mode_requires_long_password_and_allowlist():
    settings = SimpleNamespace(
        jwt_secret="0123456789abcdef0123456789abcdef",
        public_demo_mode=True,
        public_demo_password="too-short",
        public_demo_accounts="teacher:T001",
    )
    with pytest.raises(RuntimeError, match="PUBLIC_DEMO_PASSWORD"):
        auth.validate_security_config(settings)

    settings.public_demo_password = "a" * 24
    settings.public_demo_accounts = ""
    with pytest.raises(RuntimeError, match="PUBLIC_DEMO_ACCOUNTS"):
        auth.validate_security_config(settings)


def test_public_demo_mode_can_explicitly_allow_weak_password():
    """显式开关才允许 123456h 这类短口令，默认仍要求 24+ 字符。"""
    settings = SimpleNamespace(
        jwt_secret="0123456789abcdef0123456789abcdef",
        public_demo_mode=True,
        public_demo_password="123456h",
        public_demo_accounts="teacher:T001",
        public_demo_allow_weak_password=True,
    )
    auth.validate_security_config(settings)  # 不抛异常即通过


def test_public_demo_account_list_ignores_invalid_entries():
    settings = SimpleNamespace(
        public_demo_accounts=(
            "teacher:T001,student:AI20230001,admin:root,student:"
        )
    )
    assert auth._public_demo_accounts(settings) == {
        ("teacher", "T001"), ("student", "AI20230001")
    }


def test_public_demo_mode_rejects_non_allowlisted_account(monkeypatch):
    settings = SimpleNamespace(
        public_demo_mode=True,
        public_demo_password="a" * 24,
        public_demo_accounts="teacher:T001",
    )
    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    monkeypatch.setattr(
        auth, "_connect", lambda: pytest.fail("白名单外账号不应查询数据库")
    )
    assert auth.authenticate("student", "AI20230001", "a" * 24) is None


def test_public_demo_mode_uses_shared_password_for_allowlisted_account(monkeypatch):
    settings = SimpleNamespace(
        public_demo_mode=True,
        public_demo_password="a" * 24,
        public_demo_accounts="teacher:T001",
    )

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, _sql, _params):
            return None

        def fetchall(self):
            return [{
                "id": 7,
                "tenant_id": 1,
                "name": "演示教师",
                "employee_no": "T001",
                "password_hash": "legacy-hash-is-not-used-in-public-demo-mode",
            }]

    class Connection:
        def cursor(self):
            return Cursor()

        def close(self):
            return None

    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    monkeypatch.setattr(auth, "_connect", lambda: Connection())

    assert auth.authenticate("teacher", "T001", "a" * 24) == {
        "role": "teacher",
        "tenant_id": 1,
        "actor_id": 7,
        "account": "T001",
        "name": "演示教师",
        "student_no": None,
    }
    assert auth.authenticate("teacher", "T001", "wrong-password") is None


def test_app_startup_uses_jwt_validation(monkeypatch):
    monkeypatch.setattr(auth, "get_settings", lambda: _settings(""))
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        create_app()


def test_kg_rebuild_requires_auth():
    client = TestClient(create_app())
    resp = client.post("/kg/rebuild")
    assert resp.status_code == 401


def test_question_bank_reload_requires_auth():
    client = TestClient(create_app())
    resp = client.post("/qb/reload")
    assert resp.status_code == 401


def _teacher_headers(client: TestClient) -> dict[str, str]:
    resp = client.post(
        "/auth/login",
        json={"role": "teacher", "account": "T001", "password": "123456h"},
    )
    if resp.status_code != 200:
        pytest.skip("教师演示账号不可用，跳过鉴权成功路径")
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_kg_rebuild_allows_teacher_and_audits(monkeypatch):
    monkeypatch.setattr(kg_router.kg, "build_graph", lambda: object())
    monkeypatch.setattr(
        kg_router.kg, "graph_stats", lambda _graph: {"nodes": 1, "edges": 0}
    )
    calls = []
    monkeypatch.setattr(kg_router, "audit_event", lambda **kwargs: calls.append(kwargs))

    client = TestClient(create_app())
    resp = client.post("/kg/rebuild", headers=_teacher_headers(client))
    assert resp.status_code == 200
    assert calls[-1]["action"] == "kg.rebuild"
    assert calls[-1]["tenant_id"] == 1


def test_qb_reload_allows_teacher_and_audits(monkeypatch):
    monkeypatch.setattr(qb_router.qb, "clear_cache", lambda: None)
    monkeypatch.setattr(
        qb_router.qb,
        "stats",
        lambda: {"total": 3, "families": {"general": {"total": 3}}},
    )
    calls = []
    monkeypatch.setattr(qb_router, "audit_event", lambda **kwargs: calls.append(kwargs))

    client = TestClient(create_app())
    resp = client.post("/qb/reload", headers=_teacher_headers(client))
    assert resp.status_code == 200
    assert calls[-1]["action"] == "question_bank.reload"
    assert calls[-1]["tenant_id"] == 1


def test_request_id_header_is_returned():
    client = TestClient(create_app())
    resp = client.get("/docs")
    assert resp.status_code == 200
    assert resp.headers["X-Request-ID"]


def test_audit_event_passes_tenant(monkeypatch):
    captured = {}

    def fake_write_audit(**kwargs):
        captured.update(kwargs)
        return dict(kwargs)

    monkeypatch.setattr(audit_mod, "write_audit", fake_write_audit)
    audit_mod.audit_event(
        tenant_id=42,
        actor_type="teacher",
        actor_id=7,
        action="test.action",
    )
    assert captured["tenant_id"] == 42


def test_audit_writer_persists_tenant(monkeypatch):
    captured = {}

    def fake_raw(sql, params):
        captured["sql"] = sql
        captured["params"] = tuple(params)
        return 1

    monkeypatch.setattr(tools_mod, "_write_raw", fake_raw)
    entry = tools_mod.write_audit(
        tenant_id=42,
        actor_type="teacher",
        actor_id=7,
        action="test.action",
        detail={"ok": True},
    )
    assert entry["tenant_id"] == 42
    assert "`租户编号`" in captured["sql"]
    assert captured["params"][0] == 42


@pytest.mark.parametrize(
    ("path", "status", "expected"),
    [
        ("/health", 200, False),
        ("/assets/app.js", 200, False),
        ("/docs", 200, False),
        ("/job/list", 200, False),
        ("/job/list", 500, True),
        ("/teacher/warnings", 401, True),
    ],
)
def test_db_audit_only_keeps_failures(path, status, expected):
    request = Request({"type": "http", "method": "GET", "path": path, "headers": []})
    assert _should_persist_db_audit(request, status) is expected


class _FakeCursor:
    def __init__(self):
        self.calls = []
        self._answers = [
            {"n": 2, "degraded": 0, "avg_ms": None},
            {"up": 1, "down": 0, "total": 1},
        ]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params):
        self.calls.append((sql, tuple(params)))

    def fetchone(self):
        return self._answers.pop(0)


class _FakeConnection:
    def __init__(self):
        self._cursor = _FakeCursor()
        self.closed = False

    def cursor(self):
        return self._cursor

    def close(self):
        self.closed = True


def test_chat_metrics_filters_audit_by_tenant(monkeypatch):
    conn = _FakeConnection()
    monkeypatch.setattr(chat_router, "_conn", lambda: conn)

    result = chat_router.metrics(
        ToolContext(actor_type="teacher", tenant_id=42, teacher_id=7)
    )

    assert result["window_days"] == 7
    assert len(conn._cursor.calls) == 2
    for sql, params in conn._cursor.calls:
        assert "`租户编号`=%s" in sql
        assert params[0] == 42
        assert params[1] == "teacher"
    assert conn.closed is True
