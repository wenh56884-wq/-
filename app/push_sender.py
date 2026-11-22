# app/push_sender.py
# 职责：把已有未读通知投递到学生浏览器，发送器不生成数值、不改水位。
# 边界：只消费 competition.unread_notices 的结构化结果，按设备与通知源键去重。

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from typing import Any, Mapping

from pywebpush import WebPushException

from app.config import Settings, get_settings
from app.notification_store import (
    delivery_exists,
    ensure_tables,
    list_subscriptions,
    mark_subscription_invalid,
    record_delivery,
)
from engine import competition

logger = logging.getLogger("qihang.push_sender")


@dataclass(frozen=True)
class PushConfig:
    """从配置解析出的发送态，不暴露私钥给调用方之外。"""

    enabled: bool
    public_key: str
    private_key: str
    contact: str


def _configured(settings: Settings | None = None) -> PushConfig:
    s = settings or get_settings()
    public = str(s.web_push_public_key or "").strip()
    private = str(s.web_push_private_key or "").strip()
    contact = str(s.web_push_contact or "").strip()
    enabled = bool(s.web_push_enabled) and all(
        value and value != "REPLACE_ME" for value in (public, private, contact)
    )
    return PushConfig(enabled, public, private, contact)


def push_capability(settings: Settings | None = None) -> dict[str, Any]:
    """前端可见的配置摘要：永远只返回公钥和开关。"""
    cfg = _configured(settings)
    return {
        "enabled": cfg.enabled,
        "public_key": cfg.public_key if cfg.enabled else "",
        "contact_configured": bool(cfg.contact and cfg.contact != "REPLACE_ME"),
    }


def _source_key(item: Mapping[str, Any]) -> str:
    """按引擎返回的实际字段生成稳定键；不拼接时间，避免同一通知重复推送。"""
    kind = str(item.get("kind") or item.get("source") or "competition")
    notice_id = item.get("id")
    if notice_id is None:
        # 兜底仅用于旧数据缺 id：标题+发布日期比随机时间稳定，仍来自引擎结果。
        stable = f"{item.get('title', '')}|{item.get('published_at', '')}"
        import hashlib

        notice_id = hashlib.sha256(stable.encode("utf-8")).hexdigest()[:24]
    return f"{kind}:{notice_id}"[:191]


def _payload(item: Mapping[str, Any]) -> str:
    """Web Push payload 只带展示所需字段和本站路由，不带身份或密钥。"""
    return json.dumps({
        "title": str(item.get("title") or "启航新通知")[:120],
        "body": str(item.get("content") or item.get("title") or "你有一条新的站内通知")[:200],
        "tag": _source_key(item),
        "url": "/student?notices=open",
        "kind": str(item.get("kind") or item.get("source") or "competition")[:32],
    }, ensure_ascii=False)


def _send_one(
    cfg: PushConfig,
    subscription: Mapping[str, Any],
    item: Mapping[str, Any],
    settings: Settings | None = None,
) -> str:
    """向一个设备发送一条通知，返回 sent / duplicate / invalid / failed。"""
    from pywebpush import webpush

    tenant_id = int(subscription.get("tenant_id") or 0)
    student_no = str(subscription.get("student_no") or "")
    digest = str(subscription.get("endpoint_digest") or "")
    source_key = _source_key(item)
    notice_type = str(item.get("kind") or item.get("source") or "competition")[:32]
    if not tenant_id or not student_no or not digest:
        return "failed"
    if delivery_exists(tenant_id, student_no, digest, source_key, settings):
        return "duplicate"

    info = {
        "endpoint": str(subscription.get("endpoint") or ""),
        "keys": dict(subscription.get("keys") or {}),
    }
    if not info["endpoint"] or not info["keys"].get("p256dh") or not info["keys"].get("auth"):
        record_delivery(tenant_id, student_no, digest, source_key,
                        notice_type, "failed", "bad_subscription", settings)
        return "failed"
    try:
        webpush(
            subscription_info=info,
            data=_payload(item),
            vapid_private_key=cfg.private_key,
            vapid_claims={"sub": cfg.contact},
            ttl=3600,
            timeout=10,
        )
    except WebPushException as exc:
        status = int(getattr(exc, "status_code", 0) or 0)
        if status in (404, 410):
            mark_subscription_invalid(digest, settings)
            record_delivery(tenant_id, student_no, digest, source_key,
                            notice_type, "invalid", str(status), settings)
            return "invalid"
        code = f"http_{status}" if status else "transport"
        logger.warning("web push failed student=%s code=%s", student_no, code)
        record_delivery(tenant_id, student_no, digest, source_key,
                        notice_type, "failed", code[:32], settings)
        return "failed"
    except Exception as exc:  # 依赖/网络异常不影响站内通知
        logger.warning("web push unexpected error student=%s error=%s", student_no, type(exc).__name__)
        record_delivery(tenant_id, student_no, digest, source_key,
                        notice_type, "failed", "unexpected", settings)
        return "failed"
    record_delivery(tenant_id, student_no, digest, source_key,
                    notice_type, "sent", "", settings)
    return "sent"


_LOCK = threading.Lock()


def dispatch_pending(
    settings: Settings | None = None,
    tenant_id: int | None = None,
) -> dict[str, int]:
    """扫描订阅学生的未读通知并投递；进程内同一时刻只允许一轮。"""
    cfg = _configured(settings)
    result = {"students": 0, "notices": 0, "sent": 0,
              "duplicate": 0, "invalid": 0, "failed": 0}
    if not cfg.enabled or not _LOCK.acquire(blocking=False):
        return result
    try:
        ensure_tables(settings)
        subscriptions = list_subscriptions(tenant_id=tenant_id, settings=settings)
        by_student: dict[tuple[int, str], list[dict[str, Any]]] = {}
        for row in subscriptions:
            key = (int(row["tenant_id"]), str(row["student_no"]))
            by_student.setdefault(key, []).append(row)
        result["students"] = len(by_student)
        for (tenant_id, student_no), devices in by_student.items():
            try:
                notices = competition.unread_notices(
                    student_no, tenant_id, limit=20).get("items") or []
            except Exception:
                logger.warning("unread notices unavailable student=%s", student_no)
                continue
            result["notices"] += len(notices[:5])
            # 最新通知优先，避免一次性推送里翻出很旧的历史条目。
            for item in notices[:5]:
                for device in devices:
                    outcome = _send_one(cfg, device, item, settings)
                    result[outcome] = result.get(outcome, 0) + 1
        return result
    finally:
        _LOCK.release()


def sync_interval_minutes(settings: Settings | None = None) -> float:
    s = settings or get_settings()
    raw = os.getenv("WEB_PUSH_INTERVAL_MINUTES", str(s.web_push_interval_minutes))
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 5.0


_started = False


def start_background_dispatch(settings: Settings | None = None) -> bool:
    """低频扫描真实未读通知；0/未配置密钥时静默关闭，不抛错拖垮服务。"""
    global _started
    minutes = sync_interval_minutes(settings)
    cfg = _configured(settings)
    if _started or minutes <= 0 or not cfg.enabled:
        return False
    _started = True

    def loop() -> None:
        stop = threading.Event()
        while not stop.wait(minutes * 60):
            try:
                dispatch_pending(settings)
            except Exception:
                logger.exception("web push dispatch failed")

    threading.Thread(target=loop, name="web-push-dispatch", daemon=True).start()
    return True
