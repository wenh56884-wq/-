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


# ================================================================
# 岗位搜索（与推荐是两套逻辑：搜索按相关性，推荐按画像）
# ================================================================
@router.get("/jobs/facets")
def job_facets(ctx: ToolContext = Depends(require_student)) -> dict[str, Any]:
    """筛选器下拉选项：城市 / 学历及其岗位数。"""
    return _guard(ctx, "job_facets", "all", lambda: tools.job_facets(ctx))


@router.get("/jobs/search")
def search_jobs(
    q: str = Query(default="", max_length=100, description="关键词，空格分隔多个"),
    city: list[str] | None = Query(default=None, description="城市，可多选"),
    education: list[str] | None = Query(default=None, description="学历，可多选"),
    salary_min: float | None = Query(default=None, ge=0, le=1000000,
                                     description="薪资下限（元/月），只留 ≥ 该值的岗位"),
    exp_max: float | None = Query(default=None, ge=0, le=50,
                                  description="经验上限（年），只留「应届也能投」的岗位"),
    limit: int = Query(default=20, ge=1, le=100, description="每页条数"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
    ctx: ToolContext = Depends(require_student),
) -> dict[str, Any]:
    """关键词搜索岗位。**不带个人画像**——搜索是检索，推荐才是个性化。

    没有命中时返回空 items + suggestions（该方向下更可能命中的词），
    绝不拿不相关岗位充数。
    """
    return _guard(
        ctx, "job_search", (q or "")[:60],
        lambda: tools.search_jobs(
            ctx, q,
            cities=city, educations=education,
            salary_min_gte=salary_min, exp_max_lte=exp_max,
            limit=limit, offset=offset,
        ),
    )


@router.get("/jobs/{job_id}")
def job_detail(job_id: int, ctx: ToolContext = Depends(require_student)) -> dict[str, Any]:
    """岗位详情（含 JD 全文与福利）。"""
    return _guard(ctx, "job_detail", str(job_id),
                  lambda: tools.job_detail(ctx, job_id))
