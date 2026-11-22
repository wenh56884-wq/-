# app/routers/teacher.py
# 职责：教师端 API 路由（班级概览 / 预警名单 / 学生画像 / 职业差距）
# 依赖：app.auth（身份注入）/ agents.tools（取数）/ app.audit
# 说明：路由层不做任何业务判断，只负责「身份注入 → 调工具 → 翻译异常」

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from agents import campus_insight as campus_agent
from agents import tools
from agents.tools import ToolContext
from app.auth import require_teacher
from engine.career_guide import INTENTS

router = APIRouter(prefix="/teacher", tags=["教师端"])


class CampusInsightIn(BaseModel):
    """班级校园行为洞察解读输入：班级必填，身份不在入参里（只从 JWT 取）。"""

    class_name: str = Field(max_length=40)
    term: str | None = Field(default=None, max_length=20)
    limit: int = Field(default=30, ge=1, le=60)


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
    try:
        result = call()
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
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


@router.get("/career-search")
def career_search(
    class_name: str = Query(description="班级名，必须属于本租户/任教范围"),
    term: str | None = Query(default=None, description="学期，缺省回落到最新学期"),
    intent: str | None = Query(default=None,
                               description="方向过滤：考公/考研/考编/就业，留空为全班"),
    limit: int = Query(default=20, ge=1, le=60,
                       description="完整档案的学生数上限（班级人数多时按学号截断）"),
    ctx: ToolContext = Depends(require_teacher),
) -> dict[str, Any]:
    """班级生涯规划搜索：班级摘要 + 每位学生全域档案（成绩/预警/预测/岗位/面试/竞赛/测评/选课/招考/图谱）。"""
    if intent and intent not in INTENTS:
        raise HTTPException(
            status_code=422, detail=f"方向只能是 {'/'.join(INTENTS)}，收到「{intent}」")
    return _guard(ctx, "career_search", f"{class_name}/{intent or ''}",
                  lambda: tools.teacher_career_search(ctx, class_name,
                                                      term or "", intent, limit))


@router.get("/warnings")
def warnings(
    class_name: str = Query(description="班级名，必须属于本租户"),
    term: str | None = Query(default=None, description="学期，缺省回落到最新学期"),
    level: str | None = Query(default=None, description="预警等级过滤：red/orange/yellow/none/unknown"),
    include_metrics: bool = Query(
        default=False, description="是否返回引擎原始 metrics（风险沙盘画绩点散点用）"
    ),
    ctx: ToolContext = Depends(require_teacher),
) -> dict[str, Any]:
    """班级预警名单（调预警引擎，含 coverage/missing 与归因）。"""
    return _guard(ctx, "warning_list", f"{class_name}/{term or ''}",
                  lambda: tools.warning_list(ctx, class_name, term or "", level,
                                             include_metrics=include_metrics))


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


# ================================================================
# 校园行为洞察（事实 GET + 智能体 POST，数值来自 engine.campus_insight）
# ================================================================
@router.get("/campus-insight")
def campus_insight(
    class_name: str = Query(description="班级名，必须属于本租户/任教范围"),
    term: str | None = Query(default=None, max_length=20,
                             description="学期，缺省回落到最新学期"),
    limit: int = Query(default=30, ge=1, le=60,
                       description="样本学生数上限（班级人数多时按学号截断）"),
    ctx: ToolContext = Depends(require_teacher),
) -> dict[str, Any]:
    """事实层：班级投入画像分布/低投入名单/活动覆盖率/兴趣城市（确定性引擎）。"""
    return _guard(ctx, "class_campus_insight", f"{class_name}/{term or ''}",
                  lambda: tools.class_campus_insight(ctx, class_name,
                                                     term or "", limit))


@router.get("/campus-insight/student/{student_no}")
def campus_insight_student(
    student_no: str,
    term: str | None = Query(default=None, max_length=20,
                             description="学期，缺省回落到最新学期"),
    ctx: ToolContext = Depends(require_teacher),
) -> dict[str, Any]:
    """事实层（逐生口径）：班级里任意一个学生的校园行为洞察，不受样本截断限制。
    学号经租户 + 任教范围双校验，越权 403。"""
    return _guard(ctx, "student_campus_insight", f"{student_no}/{term or ''}",
                  lambda: tools.student_campus_insight(ctx, student_no, term or ""))


@router.get("/class-roster")
def class_roster(
    class_name: str = Query(description="班级名，必须属于本租户/任教范围"),
    ctx: ToolContext = Depends(require_teacher),
) -> dict[str, Any]:
    """事实层：全班完整名册（学号/姓名/专业，不截断），供前端定位任意学生。"""
    return _guard(ctx, "class_roster", class_name,
                  lambda: tools.class_roster(ctx, class_name))


@router.post("/campus-insight/interpret")
def campus_insight_interpret(
    inp: CampusInsightIn,
    ctx: ToolContext = Depends(require_teacher),
) -> dict[str, Any]:
    """智能体层（主角）：大模型基于班级事实生成班主任式管理建议；critic 回查数值，
    LLM 不可用/被驳回时降级确定性模板（source=template）。跨班级 403。"""
    return _guard(ctx, "campus_insight_interpret", inp.class_name,
                  lambda: campus_agent.interpret_class(ctx, inp.class_name,
                                                       inp.term or "", inp.limit))
