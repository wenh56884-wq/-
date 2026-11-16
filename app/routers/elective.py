# app/routers/elective.py
# 职责：技能缺口选课推荐 API——事实层（GET /advice）+ 选课规划智能体（POST /advise，大模型主导）。
# 依赖：app.auth（身份注入）/ agents.tools（身份解析与审计）/ agents.elective（智能体节点）。
# 说明：与 career.py 同一铁律——student_id 只从 JWT 取，接口没有任何「查谁」入参；教师不允许调用。

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from agents import tools
from agents.tools import ToolContext
from app.audit import audit_event
from app.auth import require_student

router = APIRouter(prefix="/elective", tags=["选课推荐"])


class AdviseIn(BaseModel):
    """选课规划智能体输入：追问可选，身份不在入参里。"""

    message: str | None = Field(default=None, max_length=1000,
                                description="学生追问（可选），如「先补哪门课」")
    term: str | None = Field(default=None, max_length=20)
    top_n: int = Field(default=8, ge=1, le=20)


def _guard(ctx: ToolContext, action: str, call):
    """统一守卫：把引擎/模型异常翻译成 HTTP 语义（与 career.py 同口径）。"""
    if not ctx.student_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="缺少学生身份")
    started = time.perf_counter()
    try:
        return call()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=f"模型调用失败：{exc}")
    finally:
        audit_event(
            tenant_id=ctx.tenant_id, actor_type=ctx.actor_type,
            actor_id=ctx.student_id,
            action=f"elective.{action}", target=str(ctx.student_id),
            duration_ms=(time.perf_counter() - started) * 1000,
        )


@router.get("/advice")
def elective_advice(term: str | None = Query(default=None, max_length=20),
                    top_n: int = Query(default=8, ge=1, le=20),
                    ctx: ToolContext = Depends(require_student)) -> dict[str, Any]:
    """事实层：目标岗位技能要求 vs 已修/已选覆盖 → 缺口 → 候选课排序（确定性引擎）。"""
    return _guard(ctx, "advice", lambda: tools.my_elective_advice(ctx, term, top_n))


@router.post("/advise")
def elective_advise(inp: AdviseIn,
                    ctx: ToolContext = Depends(require_student)) -> dict[str, Any]:
    """智能体层（主角）：DeepSeek 基于事实生成个性化选课方案；critic 回查数值，
    方案课名过白名单；LLM 不可用/被驳回时降级确定性模板（degraded=True）。"""
    return _guard(ctx, "advise",
                  lambda: tools.elective_advise(ctx, inp.message, inp.term, inp.top_n))