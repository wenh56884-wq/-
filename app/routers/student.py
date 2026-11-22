# app/routers/student.py
# 职责：学生端 API 路由（本人预警 / 本人岗位推荐）
# 依赖：app.auth（身份注入）/ agents.tools / app.audit
# 说明：学生端**没有任何** student_no 入参——身份只来自 token，忽略一切传入学号

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from agents import campus_insight as campus_agent
from agents import tools
from agents.tools import ToolContext
from app.auth import require_student

router = APIRouter(prefix="/student", tags=["学生端"])


class CampusInsightIn(BaseModel):
    """校园行为洞察解读输入：学期可选，身份不在入参里（只从 JWT 取）。"""

    term: str | None = Field(default=None, max_length=20)


def _guard(ctx: ToolContext, action: str, target: str, call) -> dict[str, Any]:
    try:
        result = call()
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
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
# 竞赛推荐与通知推送（数据来自重庆财经学院教务处官方名单/通知）
# ================================================================
@router.get("/competitions")
def my_competitions(
    track: str = Query(default="就业", description="去向：考公 / 就业"),
    direction: str = Query(default="", description="岗位方向，如 数据 / 财务 / 后端"),
    job_title: str = Query(default="", max_length=200, description="目标岗位标题，用于相关性匹配"),
    limit: int = Query(default=8, ge=1, le=30),
    ctx: ToolContext = Depends(require_student),
) -> dict[str, Any]:
    """按目标岗位推荐该参加的比赛；官方名单内挑选，每条附来源通知链接。"""
    return _guard(ctx, "competition_guide", track,
                  lambda: tools.competition_guide(ctx, track, direction, job_title, [], limit))


@router.get("/notices")
def my_notices(limit: int = Query(default=20, ge=1, le=50),
               ctx: ToolContext = Depends(require_student)) -> dict[str, Any]:
    """未读竞赛通知：官方一发布即入库，这里返回该生水位线之后的新通知。"""
    return _guard(ctx, "my_notices", "self", lambda: tools.my_notices(ctx, limit))


@router.post("/notices/read")
def read_notices(ctx: ToolContext = Depends(require_student)) -> dict[str, Any]:
    """把已读水位推到当前时间。"""
    return _guard(ctx, "mark_notices_read", "self", lambda: tools.mark_notices_read(ctx))


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


# ================================================================
# 校园行为洞察（事实 GET + 智能体 POST，数值来自 engine.campus_insight）
# ================================================================
@router.get("/campus-insight")
def campus_insight(
    term: str | None = Query(default=None, max_length=20,
                             description="学期，缺省回落到最新学期"),
    ctx: ToolContext = Depends(require_student),
) -> dict[str, Any]:
    """事实层：本人图书馆/消费/活动/出勤/岗位兴趣 → 学习投入画像（确定性引擎）。"""
    return _guard(ctx, "my_campus_insight", term or "",
                  lambda: tools.my_campus_insight(ctx, term))


@router.post("/campus-insight/interpret")
def campus_insight_interpret(
    inp: CampusInsightIn,
    ctx: ToolContext = Depends(require_student),
) -> dict[str, Any]:
    """智能体层（主角）：大模型基于事实生成个性化解读与行动建议；critic 回查数值，
    LLM 不可用/被驳回时降级确定性模板（source=template）。不接收任何「查谁」入参。"""
    return _guard(ctx, "campus_insight_interpret", "self",
                  lambda: campus_agent.interpret_student(ctx, inp.term))
