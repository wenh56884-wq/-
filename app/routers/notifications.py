# app/routers/notifications.py
# 职责：学生站内通知中心 + 浏览器 Web Push 订阅入口（身份只来自 JWT）。
# 边界：不改既有通知生成、已读水位和引擎计算；新表只存设备订阅与投递状态。

from __future__ import annotations

import re
from typing import Any, Mapping
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from agents.tools import ToolContext, _resolve_self
from app.auth import ROLE_STUDENT, require_student
from app.config import get_settings
from app.notification_store import (
    delete_subscription,
    ensure_tables,
    save_subscription,
    subscription_exists,
)
from app.push_sender import dispatch_pending, push_capability

router = APIRouter(prefix="/notifications", tags=["学生通知"])

_ENDPOINT_MAX = 1000
_KEY_RE = re.compile(r"^[A-Za-z0-9_\-=]+$")


class PushSubscriptionIn(BaseModel):
    """只接受浏览器 PushSubscription.toJSON() 的必要字段。"""

    endpoint: str = Field(min_length=1, max_length=_ENDPOINT_MAX)
    keys: dict[str, str] = Field(default_factory=dict)
    user_agent: str = Field(default="", max_length=300)


class PushUnsubscribeIn(BaseModel):
    endpoint: str = Field(min_length=1, max_length=_ENDPOINT_MAX)


def _student(ctx: ToolContext) -> dict[str, Any]:
    if ctx.actor_type != ROLE_STUDENT or not ctx.student_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="只有学生账号可以管理本人推送设备")
    return _resolve_self(ctx, "notifications.push")


def _validate_endpoint(raw: str) -> str:
    parsed = urlparse(str(raw or "").strip())
    host = (parsed.hostname or "").lower()
    # Push service 要求 HTTPS；localhost 仅用于本地开发验证。
    if parsed.scheme != "https" and not (parsed.scheme == "http" and host in {"localhost", "127.0.0.1"}):
        raise HTTPException(status_code=422, detail="推送端点必须使用 HTTPS")
    if not host:
        raise HTTPException(status_code=422, detail="推送端点缺少主机名")
    return str(raw).strip()


def _validate_keys(keys: Mapping[str, Any]) -> dict[str, str]:
    out = {
        "p256dh": str(keys.get("p256dh") or "").strip(),
        "auth": str(keys.get("auth") or "").strip(),
    }
    for value in out.values():
        if not value or len(value) > 512 or not _KEY_RE.fullmatch(value):
            raise HTTPException(status_code=422, detail="推送订阅密钥格式不正确")
    return out


@router.get("/push/config")
def get_push_config() -> dict[str, Any]:
    """返回浏览器订阅所需公钥；不返回私钥，也不要求登录态。"""
    return push_capability(get_settings())


@router.put("/push/subscription")
def put_push_subscription(
    body: PushSubscriptionIn,
    ctx: ToolContext = Depends(require_student),
) -> dict[str, Any]:
    """当前学生显式授权后，绑定当前设备；重复调用保持幂等。"""
    cfg = push_capability(get_settings())
    if not cfg["enabled"]:
        raise HTTPException(status_code=503, detail="服务端尚未配置浏览器推送")
    endpoint = _validate_endpoint(body.endpoint)
    keys = _validate_keys(body.keys)
    me = _student(ctx)
    ensure_tables(get_settings())
    digest = save_subscription(
        ctx.tenant_id, me["student_no"], endpoint, keys,
        str(body.user_agent or ""), get_settings())
    return {"registered": True, "endpoint_digest": digest[:12], "student_no": me["student_no"]}


@router.delete("/push/subscription")
def delete_push_subscription(
    body: PushUnsubscribeIn,
    ctx: ToolContext = Depends(require_student),
) -> dict[str, Any]:
    """关闭推送：只删除属于当前学生与租户的设备。"""
    endpoint = _validate_endpoint(body.endpoint)
    me = _student(ctx)
    removed = delete_subscription(
        ctx.tenant_id, me["student_no"], endpoint, get_settings())
    return {"removed": removed > 0, "student_no": me["student_no"]}


@router.get("/push/status")
def get_push_status(
    endpoint: str,
    ctx: ToolContext = Depends(require_student),
) -> dict[str, Any]:
    """查询当前端点是否已订阅；不改变任何状态。"""
    me = _student(ctx)
    endpoint = _validate_endpoint(endpoint)
    return {
        "enabled": subscription_exists(
            ctx.tenant_id, me["student_no"], endpoint, get_settings()),
        "server_enabled": bool(push_capability(get_settings())["enabled"]),
    }


@router.post("/push/dispatch-test")
def dispatch_test(
    ctx: ToolContext = Depends(require_student),
) -> dict[str, Any]:
    """显式触发一轮当前租户的未读投递；用于部署联调，不自动向其他租户发消息。"""
    cfg = push_capability(get_settings())
    if not cfg["enabled"]:
        raise HTTPException(status_code=503, detail="服务端尚未配置浏览器推送")
    _student(ctx)  # 先确认身份合法；发送器按订阅表自身的 tenant_id 隔离
    settings = get_settings()
    return dispatch_pending(settings, tenant_id=int(ctx.tenant_id))
