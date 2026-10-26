# app/routers/career.py
# 职责：职业规划模块 API（画像解析 / 规则匹配 / 周监控 / 通知过滤 / 陪伴对话）
# 依赖：app.auth（身份注入）/ agents.career.nodes / app.audit
# 说明：与 student.py 同一铁律——**student_id 只从 JWT 取**，接口里没有任何「查谁」入参。
#       学生只能操作自己的职业规划，teacher 角色不允许调用（避免越权代填）。

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from agents import tools
from agents.career import context as cx
from agents.career import nodes
from agents.tools import ToolContext
from app.audit import audit_event
from app.auth import require_student

router = APIRouter(prefix="/career", tags=["职业规划"])


# ----------------------------------------------------------------
# 入参模型
# ----------------------------------------------------------------
class PlanIn(BaseModel):
    """提交职业规划原文。"""

    raw_text: str = Field(min_length=10, max_length=4000, description="学生填写的规划原文")


class ExtraIn(BaseModel):
    """补充信息（四六级/政治面貌等）。全部可选，只更新传入的字段。"""

    cet4_score: int | None = Field(default=None, ge=0, le=710)
    cet6_score: int | None = Field(default=None, ge=0, le=710)
    political_status: str | None = Field(default=None, max_length=20)
    target_city: str | None = Field(default=None, max_length=60)
    weekly_hours: float | None = Field(default=None, ge=0, le=168)


class WeeklyIn(BaseModel):
    """周度自报数据。键名必须与规则库 weekly_metrics 的「指标」一致。"""

    self_report: dict[str, Any] = Field(
        default_factory=dict,
        description='形如 {"行测刷题量": 260, "行测正确率": 0.62}；缺的键由引擎判 unknown',
    )


class ChatIn(BaseModel):
    """陪伴对话输入。"""

    message: str = Field(min_length=1, max_length=1000)


class IntentIn(BaseModel):
    """职业目标选择：大一新生必须先选，大二/大三可调整。"""

    intent: str = Field(min_length=1, max_length=10,
                        description="考公 / 考研 / 考编 / 就业")


# ----------------------------------------------------------------
# 统一守卫：把引擎/模型的异常翻译成 HTTP 语义
# ----------------------------------------------------------------
def _guard(ctx: ToolContext, action: str, call):
    if not ctx.student_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="缺少学生身份")
    started = time.perf_counter()
    try:
        return call()
    except ValueError as exc:
        # 前置条件不满足（没画像 / 没规则 / 原文为空）
        raise HTTPException(status_code=422, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except RuntimeError as exc:
        # 模型返回非法 JSON / 未配置 Key
        raise HTTPException(status_code=502, detail=f"模型调用失败：{exc}")
    finally:
        audit_event(
            actor_type=ctx.actor_type, actor_id=ctx.student_id,
            action=f"career.{action}", target=str(ctx.student_id),
            duration_ms=(time.perf_counter() - started) * 1000,
        )


# ----------------------------------------------------------------
# 接口
# ----------------------------------------------------------------
@router.get("/templates")
def list_templates(ctx: ToolContext = Depends(require_student)) -> dict[str, Any]:
    """可用规则模板（考公/考研/就业）+ 引擎版本，供前端下拉与自检。"""
    from engine.career_rules import CAREER_ENGINE_VERSION

    return {
        "templates": cx.available_templates(),
        "engine_version": CAREER_ENGINE_VERSION,
    }


@router.get("/guide")
def career_guide(ctx: ToolContext = Depends(require_student)) -> dict[str, Any]:
    """本人年级 + 目标 + 确定性规划路径；大一未选目标时返回 needs_intent。"""
    return _guard(ctx, "career_guide", lambda: tools.my_career_guide(ctx))


@router.put("/intent")
def put_intent(
    payload: IntentIn,
    ctx: ToolContext = Depends(require_student),
) -> dict[str, Any]:
    """保存本人职业目标（考公/考研/考编/就业），重复提交覆盖。"""
    return _guard(ctx, "save_career_intent",
                  lambda: tools.save_career_intent(ctx, payload.intent))


@router.put("/extra")
def put_extra(
    payload: ExtraIn,
    ctx: ToolContext = Depends(require_student),
) -> dict[str, Any]:
    """提交/更新补充信息（四六级、政治面貌）。历史提交留痕。"""
    return _guard(
        ctx, "put_extra",
        lambda: (
            cx.save_student_extra(
                ctx.tenant_id, int(ctx.student_id),
                cet4_score=payload.cet4_score,
                cet6_score=payload.cet6_score,
                political_status=payload.political_status,
                target_city=payload.target_city,
                weekly_hours=payload.weekly_hours,
            ),
            {"ok": True, "student_no": cx.fetch_student_facts(ctx.tenant_id, int(ctx.student_id))["student_no"]},
        )[1],
    )


@router.post("/plan")
def post_plan(
    payload: PlanIn,
    ctx: ToolContext = Depends(require_student),
) -> dict[str, Any]:
    """解析规划原文（提示词一）。模型只抽取，门槛与差距由引擎算。"""
    return _guard(
        ctx, "parse_plan",
        lambda: nodes.parse_plan(ctx.tenant_id, int(ctx.student_id), payload.raw_text),
    )


@router.get("/plan")
def get_plan(ctx: ToolContext = Depends(require_student)) -> dict[str, Any]:
    """查看当前生效的画像（不调模型，纯读库）。"""
    return _guard(
        ctx, "get_plan",
        lambda: cx.fetch_active_plan(ctx.tenant_id, int(ctx.student_id))
        or {"empty": True, "note": "尚未提交职业规划"},
    )


@router.post("/match")
def post_match(ctx: ToolContext = Depends(require_student)) -> dict[str, Any]:
    """选模板 + 算阶段 + 算硬门槛（提示词二）。日期与周数由引擎算，模型只写解释。"""
    return _guard(
        ctx, "match_rule",
        lambda: nodes.match_rule(ctx.tenant_id, int(ctx.student_id), 0),
    )


@router.get("/rule")
def get_rule(ctx: ToolContext = Depends(require_student)) -> dict[str, Any]:
    """查看当前生效的规培规则（不调模型）。"""
    return _guard(
        ctx, "get_rule",
        lambda: cx.fetch_active_rule(ctx.tenant_id, int(ctx.student_id))
        or {"empty": True, "note": "尚未生成规培规则"},
    )


@router.post("/weekly")
def post_weekly(
    payload: WeeklyIn,
    ctx: ToolContext = Depends(require_student),
) -> dict[str, Any]:
    """周度监控（提示词三）。三色与升级由引擎判，模型只写摘要与 ≤3 条建议。"""
    return _guard(
        ctx, "weekly_review",
        lambda: nodes.weekly_review(
            ctx.tenant_id, int(ctx.student_id), self_report=payload.self_report,
        ),
    )


@router.get("/notices")
def get_notices(ctx: ToolContext = Depends(require_student)) -> dict[str, Any]:
    """通知相关性过滤（提示词四）。已截止的在代码里剔除，模型看不到。"""
    return _guard(
        ctx, "filter_notices",
        lambda: nodes.filter_notices(ctx.tenant_id, int(ctx.student_id)),
    )


@router.post("/chat")
def post_chat(
    payload: ChatIn,
    ctx: ToolContext = Depends(require_student),
) -> dict[str, Any]:
    """陪伴对话（提示词五）。【系统记录】过白名单，越权项整条丢弃。"""
    return _guard(
        ctx, "coach_chat",
        lambda: nodes.coach_chat(ctx.tenant_id, int(ctx.student_id), payload.message),
    )
