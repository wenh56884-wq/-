# app/routers/cert.py
# 职责：考证中心 API——目录（公开只读）+ 学生个性化推荐（需登录）。
#
# 设计对齐 exam.py（招考公告）：
# - 目录数据全部来自官方公告原文入库（db/cert_tables.sql，带来源链接与核实日期），
#   纯只读接口，不改任何状态；「预计」字段必须原样透传给前端显示，缺失不冒充。
# - 个性化推荐走 agents.tools.cert_guide（学生本人：去向/专业/年级/已持证书）。

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from agents import tools
from agents.tools import ToolContext
from app.auth import require_student

router = APIRouter(prefix="/cert", tags=["考证中心"])


@router.get("/list")
def cert_list(limit: int = Query(default=20, ge=1, le=50)) -> dict[str, Any]:
    """考证目录 + 实时报名状态（师生通用，公开只读）。"""
    return tools.cert_catalog(limit=limit)


@router.get("/recommend")
def cert_recommend(limit: int = Query(default=6, ge=1, le=20),
                   ctx: ToolContext = Depends(require_student)) -> dict[str, Any]:
    """本人考证推荐：按目标去向/专业/年级/已持证书排序，理由与差距全部可解释。"""
    return tools.cert_guide(ctx, limit=limit)
