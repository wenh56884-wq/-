# app/routers/question_bank.py
# 职责：面试题库（RAG）只读查询 + 统计 + 热更新。
# 这些接口是「可解释性」的出口：面试官用的每道题都能在这里查到出处。
# 不提供写接口——题库只能通过 scripts/load_question_bank.py 从语料文件导入，
# 避免有人从 API 直接塞一条没有出处的题进来。

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from engine import question_bank as qb

router = APIRouter(prefix="/qb", tags=["question_bank"])


@router.get("/stats")
def stats() -> dict[str, Any]:
    """题库总览：条数、行业族 × 题型覆盖矩阵、来源清单。"""
    return qb.stats()


@router.get("/sources")
def sources() -> dict[str, Any]:
    """来源清单（按收录条数降序）——每条题库记录的可信度依据。"""
    s = qb.stats()
    return {"total": len(s["sources"]), "items": s["sources"]}


@router.get("/search")
def search(industry: str = Query(default="", max_length=60,
                                 description="岗位行业名，如 计算机软件 / 会计/审计"),
           q: str = Query(default="", max_length=200, description="岗位名称 + 技能标签"),
           qtype: str = Query(default="major", max_length=20),
           k: int = Query(default=5, ge=1, le=20)) -> dict[str, Any]:
    """按「行业族 + 题型」检索题库，返回带分数与命中项的结果。"""
    if qtype not in qb.QTYPES:
        return {"family": qb.normalize_industry(industry), "qtype": qtype,
                "items": [], "error": f"qtype 必须是 {list(qb.QTYPES)} 之一"}
    hits = qb.retrieve(industry, q, qtype, k=k)
    return {"family": qb.normalize_industry(industry),
            "family_label": qb.family_label(qb.normalize_industry(industry)),
            "qtype": qtype, "total": len(hits), "items": hits}


@router.post("/reload")
def reload_bank() -> dict[str, Any]:
    """语料文件更新后热加载（清进程缓存并重新构建索引）。"""
    qb.clear_cache()
    s = qb.stats()
    return {"ok": True, "total": s["total"], "families": len(s["families"])}
