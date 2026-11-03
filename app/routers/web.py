# app/routers/web.py
# 职责：联网搜索接口——把引擎的 web_search 结果原样透出给前端，不加工、不编造。
# 鉴权：登录用户（学生/教师）均可调用；搜索本身不涉及租户数据，身份仅用于放行。
# 铁律：
#   1. 未配置密钥 / 请求失败 / 无结果，一律如实返回 configured=False 或 error，
#      绝不返回假结果、绝不用模型记忆冒充搜索结果。
#   2. 每条结果必须带真实 URL，前端据此点开原网页核对。

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.auth import get_current_ctx
from agents.tools import ToolContext
from engine import web_search

router = APIRouter(prefix="/web", tags=["web-search"])


@router.get("/search")
def search(q: str, top_k: int = 8,
           ctx: ToolContext = Depends(get_current_ctx)) -> dict[str, Any]:
    """联网搜索：q 为查询词，top_k 为条数（1..10）。结果形状与引擎一致。"""
    if not str(q or "").strip():
        raise HTTPException(422, "请输入搜索关键词")
    # 前端传 top_k=8；引擎内部按 1..10 截断，这里再限一次避免异常值
    return web_search.search(q, top_k=max(1, min(top_k, 10)))
