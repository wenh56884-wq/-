# app/routers/teacher.py
# 职责：教师端 API 路由（班级概览 / 预警名单 / 学生画像 / 职业差距）
# 依赖：app.auth（身份注入）/ agents.tools（取数）/ app.audit
# 说明：路由层不做任何业务判断，只负责「身份注入 → 调工具 → 翻译异常」

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from agents import tools
from agents.tools import ToolContext
from app.audit import audit_event
from app.auth import require_teacher

router = APIRouter(prefix="/teacher", tags=["教师端"])


class ThresholdItem(BaseModel):
    """一条指标阈值；留空/None 表示回退租户默认。"""

    metric: str = Field(max_length=40)
    weight: float | None = Field(default=None, ge=0)
    yellow_value: float | None = Field(default=None, ge=0)
    orange_value: float | None = Field(default=None, ge=0)
    red_value: float | None = Field(default=None, ge=0)


class ThresholdIn(BaseModel):
    """某班的完整阈值覆盖列表（整体替换）。"""

    thresholds: list[ThresholdItem] = Field(default_factory=list)


def _guard(ctx: ToolContext, action: str, target: str, call) -> dict[str, Any]:
    """统一异常翻译 + 留痕：PermissionError→403、ValueError→422，其余按 500 兜底。"""
    started = time.perf_counter()
    try:
        result = call()
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    finally:
        audit_event(actor_type=ctx.actor_type, actor_id=ctx.teacher_id,
                    action=f"api.{action}", target=target,
                    duration_ms=(time.perf_counter() - started) * 1000)
    return result


@router.get("/classes")
def classes(ctx: ToolContext = Depends(require_teacher)) -> dict[str, Any]:
    """教师端班级/学院目录：学院 → 班级（含专业与人数的名册），供前端下拉选择。"""
    return _guard(ctx, "class_list", "all", lambda: tools.class_list(ctx))


@router.get("/warning-thresholds")
def warning_thresholds(
    class_name: str = Query(description="班级名，必须属于本租户/任教范围"),
    ctx: ToolContext = Depends(require_teacher),
) -> dict[str, Any]:
    """读取某班的有效预警阈值（班级覆盖 > 租户默认 > 内置默认）。"""
    return _guard(ctx, "get_warning_thresholds", class_name,
                  lambda: tools.get_warning_thresholds(ctx, class_name))


@router.put("/warning-thresholds")
def put_warning_thresholds(
    payload: ThresholdIn,
    class_name: str = Query(description="班级名，必须属于本租户/任教范围"),
    ctx: ToolContext = Depends(require_teacher),
) -> dict[str, Any]:
    """整体替换某班阈值；空值表示回退上一级。"""
    rows = [item.model_dump() for item in payload.thresholds]
    return _guard(ctx, "save_warning_thresholds", class_name,
                  lambda: tools.save_warning_thresholds(ctx, class_name, rows))


@router.get("/class-overview")
def class_overview(
    class_name: str = Query(description="班级名，必须属于本租户"),
    term: str | None = Query(default=None, description="学期，缺省回落到最新学期"),
    ctx: ToolContext = Depends(require_teacher),
) -> dict[str, Any]:
    """班级概貌：人数 / 均分 / 挂科率 / 预警分布 / 就业意向。"""
    return _guard(ctx, "class_overview", f"{class_name}/{term or ''}",
                  lambda: tools.class_overview(ctx, class_name, term or ""))


@router.get("/warnings")
def warnings(
    class_name: str = Query(description="班级名，必须属于本租户"),
    term: str | None = Query(default=None, description="学期，缺省回落到最新学期"),
    level: str | None = Query(default=None, description="预警等级过滤：red/orange/yellow/none/unknown"),
    ctx: ToolContext = Depends(require_teacher),
) -> dict[str, Any]:
    """班级预警名单（调预警引擎，含 coverage/missing 与归因）。"""
    return _guard(ctx, "warning_list", f"{class_name}/{term or ''}",
                  lambda: tools.warning_list(ctx, class_name, term or "", level))


@router.get("/student/{student_no}")
def student_profile(
    student_no: str,
    term: str | None = Query(default=None, description="学期，缺省回落到最新学期"),
    ctx: ToolContext = Depends(require_teacher),
) -> dict[str, Any]:
    """学生四维画像 + 标签 + 成绩趋势；学号经租户校验，跨租户返回 403。"""
    return _guard(ctx, "student_profile", f"{student_no}/{term or ''}",
                  lambda: tools.student_profile(ctx, student_no, term or ""))


@router.get("/career-gap")
def career_gap(
    class_name: str = Query(description="班级名，必须属于本租户"),
    term: str | None = Query(default=None, description="学期，缺省回落到最新学期"),
    ctx: ToolContext = Depends(require_teacher),
) -> dict[str, Any]:
    """班级能力结构 vs 目标岗位需求差距（规则版口径）。"""
    return _guard(ctx, "career_gap", f"{class_name}/{term or ''}",
                  lambda: tools.career_gap(ctx, class_name, term or ""))
