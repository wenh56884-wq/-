# app/routers/student.py
# 职责：学生端 API 路由（本人预警 / 本人岗位推荐）
# 依赖：app.auth（身份注入）/ agents.tools / app.audit
# 说明：学生端**没有任何** student_no 入参——身份只来自 token，忽略一切传入学号

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from agents import tools
from agents.tools import ToolContext
from app.audit import audit_event
from app.auth import require_student

router = APIRouter(prefix="/student", tags=["学生端"])


def _guard(ctx: ToolContext, action: str, target: str, call) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        result = call()
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    finally:
        audit_event(actor_type=ctx.actor_type, actor_id=ctx.student_id,
                    action=f"api.{action}", target=target,
                    duration_ms=(time.perf_counter() - started) * 1000)
    return result


@router.get("/warning")
def my_warning(
    term: str | None = Query(default=None, description="学期，缺省回落到最新学期"),
    ctx: ToolContext = Depends(require_student),
) -> dict[str, Any]:
    """本人预警状态 + 归因（不接收学号，永远只看本人）。"""
    return _guard(ctx, "my_warning", term or "",
                  lambda: tools.my_warning(ctx, term))


@router.get("/recommendations")
def my_recommendations(
    term: str | None = Query(default=None, description="学期，缺省回落到最新学期"),
    top_n: int = Query(default=10, ge=1, le=50, description="返回条数"),
    ctx: ToolContext = Depends(require_student),
) -> dict[str, Any]:
    """本人岗位推荐 + 三段式理由（engine.recommend 规则版，确定性打分）。"""
    return _guard(ctx, "my_recommendations", term or "",
                  lambda: tools.my_recommendations(ctx, term, top_n=top_n))
