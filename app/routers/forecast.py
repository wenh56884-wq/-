# app/routers/forecast.py
# 职责：学业预测 API 路由（本人下学期均分 / 课程挂科风险 / 预警等级走向）
# 依赖：app.auth（身份注入）/ engine.forecast / app.audit
# 说明：不接收学号——身份只来自 token，永远只看本人

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from agents.tools import ToolContext
from app.audit import audit_event
from app.auth import require_student
from engine import forecast

# 注意：不能用 /student 前缀——/student/* 是前端 SPA 路由，同名会被 FastAPI 先匹配，
# 导致直接访问页面 URL 时拿到 401 JSON 而不是 index.html。预测接口统一走 /forecast。
router = APIRouter(prefix="/forecast", tags=["学生端·学业预测"])


@router.get("/me")
def my_forecast(ctx: ToolContext = Depends(require_student)) -> dict[str, Any]:
    """本人学业预测（均分外推 + 挂科风险 + 预警走向）。

    数值全部由 engine.forecast 确定性计算，接口只做身份解析与透传，不改任何数值。
    """
    started = time.perf_counter()
    try:
        prof = forecast.fetch_profile_by_id(ctx.tenant_id, int(ctx.student_id or 0))
        if not prof:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail="未找到该学生档案")
        return forecast.compute_student_forecast(
            ctx.tenant_id, str(prof["student_no"]), profile=prof)
    finally:
        audit_event(actor_type=ctx.actor_type, actor_id=ctx.student_id,
                    action="api.my_forecast", target="self",
                    duration_ms=(time.perf_counter() - started) * 1000)
