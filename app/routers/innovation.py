# app/routers/innovation.py
# 职责：创新全景看板唯一只读接口——把 engine.innovation 聚合出的事实原样返回前端。
# 鉴权：身份只由 JWT 注入；学生不接受任何「查谁」入参，教师只用任教范围（引擎内过滤）。
# 铁律：路由不算数、不补数、不改口径；缺失由引擎以 available=False / value=None 表达。

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from agents.tools import ToolContext
from app.auth import get_current_ctx
from app.config import get_settings
from engine.innovation import ENGINE_VERSION, build_overview

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/innovation", tags=["创新全景"])

_FORBIDDEN = status.HTTP_403_FORBIDDEN


@router.get("/overview", summary="创新全景：结果 / 测推练补 / 可信来源")
def get_overview(ctx: ToolContext = Depends(get_current_ctx)) -> dict[str, Any]:
    """学生取本人，教师取任教范围聚合。所有数字都带 source_table 与 as_of。"""
    try:
        return build_overview(
            role=ctx.actor_type,
            tenant_id=int(ctx.tenant_id),
            student_id=ctx.student_id,
            teacher_id=ctx.teacher_id,
        )
    except PermissionError as exc:
        # 越权不是 500：学生缺本人身份、教师无任教班级，都按权限错误返回
        raise HTTPException(status_code=_FORBIDDEN, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 —— 聚合失败不能让整页白屏
        logger.exception("创新全景聚合失败")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"创新全景暂不可用（{ENGINE_VERSION}）：数据聚合异常，请稍后重试",
        ) from exc
