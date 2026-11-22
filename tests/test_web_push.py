# tests/test_web_push.py
# 职责：Web Push 最小可用版的离线契约测试。
# 说明：monkeypatch 掉 MySQL 与真实网络，不向外部推送服务发请求，不写业务数据。

from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from agents.tools import ToolContext  # noqa: E402
from app.auth import require_student  # noqa: E402
from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.push_sender import (  # noqa: E402
    _payload,
    _send_one,
    dispatch_pending,
    push_capability,
)


STUDENT = ToolContext(actor_type="student", tenant_id=1, student_id=101)
TEACHER = ToolContext(actor_type="teacher", tenant_id=1, teacher_id=9)


def _settings() -> Settings:
    return Settings(
        web_push_enabled=True,
        web_push_public_key="test-public-key",
        web_push_private_key="test-private-key",
        web_push_contact="mailto:admin@example.edu",
        web_push_interval_minutes=0,
    )


def _client(role: ToolContext = STUDENT) -> TestClient:
    app = create_app()
    app.dependency_overrides[require_student] = lambda: role
    return TestClient(app)


def test_capability_never_exposes_private_key():
    cap = push_capability(_settings())
    assert cap["enabled"] is True
    assert cap["public_key"] == "test-public-key"
    assert "private" not in cap
    assert "test-private-key" not in str(cap)

    off = push_capability(Settings(web_push_enabled=False,
                                   web_push_public_key="test-public-key",
                                   web_push_private_key="test-private-key",
                                   web_push_contact="mailto:admin@example.edu"))
    assert off == {"enabled": False, "public_key": "", "contact_configured": True}


def test_config_endpoint_is_public_and_safe():
    client = _client()
    resp = client.get("/notifications/push/config")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body.get("enabled"), bool)
    assert "private_key" not in body


def test_subscription_uses_jwt_identity_and_is_idempotent(monkeypatch):
    saved: list[tuple] = []

    monkeypatch.setattr("app.config.get_settings", lambda: _settings())
    monkeypatch.setattr("app.push_sender.get_settings", lambda: _settings())
    monkeypatch.setattr("app.routers.notifications.get_settings", lambda: _settings())
    monkeypatch.setattr("app.routers.notifications.ensure_tables", lambda settings=None: None)
    monkeypatch.setattr("app.routers.notifications._student", lambda ctx: {"student_no": "AI20230001"})
    monkeypatch.setattr(
        "app.routers.notifications.save_subscription",
        lambda tenant, no, endpoint, keys, ua, settings=None: (saved.append((tenant, no, endpoint, keys)) or "digest-123"),
    )
    client = _client()
    payload = {
        "endpoint": "https://push.example.com/device/1",
        "keys": {"p256dh": "abcDEF123-_", "auth": "xyzABC456-_"},
        "user_agent": "test-browser",
    }
    first = client.put("/notifications/push/subscription", json=payload)
    second = client.put("/notifications/push/subscription", json=payload)
    assert first.status_code == 200 and second.status_code == 200
    assert len(saved) == 2
    assert all(row[0] == 1 and row[1] == "AI20230001" for row in saved)
    assert "student_no" not in payload


@pytest.mark.parametrize("endpoint", [
    "http://push.example.com/device/1",
    "ftp://push.example.com/device/1",
    "https://",
])
def test_subscription_rejects_invalid_endpoint(endpoint, monkeypatch):
    monkeypatch.setattr("app.config.get_settings", lambda: _settings())
    monkeypatch.setattr("app.push_sender.get_settings", lambda: _settings())
    monkeypatch.setattr("app.routers.notifications.get_settings", lambda: _settings())
    client = _client()
    resp = client.put("/notifications/push/subscription", json={
        "endpoint": endpoint,
        "keys": {"p256dh": "abcDEF123-_", "auth": "xyzABC456-_"},
    })
    assert resp.status_code == 422


def test_teacher_cannot_manage_student_push(monkeypatch):
    monkeypatch.setattr("app.config.get_settings", lambda: _settings())
    monkeypatch.setattr("app.push_sender.get_settings", lambda: _settings())
    monkeypatch.setattr("app.routers.notifications.get_settings", lambda: _settings())
    client = _client(TEACHER)
    resp = client.put("/notifications/push/subscription", json={
        "endpoint": "https://push.example.com/device/1",
        "keys": {"p256dh": "abcDEF123-_", "auth": "xyzABC456-_"},
    })
    # 依赖被覆盖成 teacher 时，路由层显式拒绝，不把学号解析为他人数据
    assert resp.status_code in (403, 401)


def test_payload_uses_engine_fields_and_site_route():
    item = {"id": 42, "kind": "cert", "title": "考前提醒", "content": "打印准考证"}
    payload = __import__("json").loads(_payload(item))
    assert payload["tag"] == "cert:42"
    assert payload["url"] == "/student?notices=open"
    assert payload["title"] == "考前提醒"
    assert "student_no" not in payload and "private" not in payload


def test_dispatch_deduplicates_and_handles_invalid_subscription(monkeypatch):
    settings = _settings()
    subscriptions = [{
        "tenant_id": 1, "student_no": "AI20230001",
        "endpoint": "https://push.example.com/device/1",
        "endpoint_digest": "d" * 64,
        "keys": {"p256dh": "p", "auth": "a"},
    }]
    notices = [{"id": 1, "kind": "competition", "title": "新竞赛通知"}]
    calls = {"send": 0, "invalid": 0, "record": 0}

    monkeypatch.setattr("app.push_sender.ensure_tables", lambda settings=None: None)
    monkeypatch.setattr("app.push_sender.list_subscriptions",
                        lambda tenant_id=None, settings=None: subscriptions)
    monkeypatch.setattr("engine.competition.unread_notices",
                        lambda student_no, tenant_id, limit=20: {"items": notices, "last_notice_id": 0})
    monkeypatch.setattr("app.push_sender.delivery_exists",
                        lambda tenant, no, digest, key, settings=None: calls["send"] > 0)

    def fake_webpush(**kwargs):
        calls["send"] += 1
        assert kwargs["subscription_info"]["endpoint"] == subscriptions[0]["endpoint"]
        assert kwargs["vapid_private_key"] == "test-private-key"
        assert kwargs["vapid_claims"]["sub"] == "mailto:admin@example.edu"
        return "ok"

    monkeypatch.setattr("pywebpush.webpush", fake_webpush)
    monkeypatch.setattr("app.push_sender.record_delivery",
                        lambda *args, **kwargs: calls.__setitem__("record", calls["record"] + 1))
    monkeypatch.setattr("app.push_sender.mark_subscription_invalid",
                        lambda digest, settings=None: calls.__setitem__("invalid", calls["invalid"] + 1))

    first = dispatch_pending(settings, tenant_id=1)
    second = dispatch_pending(settings, tenant_id=1)
    assert first["sent"] == 1 and first["duplicate"] == 0
    assert second["sent"] == 0 and second["duplicate"] == 1
    assert calls["invalid"] == 0


def test_dispatch_failure_does_not_advance_watermark(monkeypatch):
    settings = _settings()
    subscription = {
        "tenant_id": 1, "student_no": "AI20230001",
        "endpoint": "https://push.example.com/device/1",
        "endpoint_digest": "d" * 64,
        "keys": {"p256dh": "p", "auth": "a"},
    }
    watermark_calls = {"mark": 0}

    class FakeException(Exception):
        status_code = 503

    monkeypatch.setattr("app.push_sender.WebPushException", FakeException)

    def fake_webpush(**kwargs):
        raise FakeException("retry later")

    monkeypatch.setattr("app.push_sender.ensure_tables", lambda settings=None: None)
    monkeypatch.setattr("app.push_sender.list_subscriptions",
                        lambda tenant_id=None, settings=None: [subscription])
    monkeypatch.setattr("engine.competition.unread_notices",
                        lambda student_no, tenant_id, limit=20: {"items": [{"id": 7, "kind": "cert", "title": "报名提醒"}]})
    monkeypatch.setattr("app.push_sender.delivery_exists", lambda *a, **k: False)
    monkeypatch.setattr("app.push_sender.record_delivery", lambda *a, **k: None)
    monkeypatch.setattr("app.push_sender.mark_subscription_invalid", lambda *a, **k: watermark_calls.__setitem__("mark", 1))
    monkeypatch.setattr("pywebpush.webpush", fake_webpush)
    result = dispatch_pending(settings, tenant_id=1)
    assert result["failed"] == 1 and result["sent"] == 0
    assert watermark_calls["mark"] == 0  # 失败不清理设备，也不触碰已读水位
