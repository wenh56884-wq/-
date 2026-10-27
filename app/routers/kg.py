# app/routers/kg.py
# 职责：知识图谱查询 API——统计 / 技能→岗位 / 专业→技能 / explain_path / 邻接子图 / 重建。
# 图构建较重（全表扫描 + NetworkX），做进程级缓存；/kg/rebuild 显式刷新。

from __future__ import annotations

import threading
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from engine import kg

router = APIRouter(prefix="/kg", tags=["kg"])

_lock = threading.Lock()
_graph_cache: dict[str, Any] = {"graph": None, "built_at": None}


def _graph():
    with _lock:
        if _graph_cache["graph"] is None:
            _graph_cache["graph"] = kg.build_graph()
            from datetime import datetime
            _graph_cache["built_at"] = datetime.now().isoformat(timespec="seconds")
        return _graph_cache["graph"]


@router.get("/stats")
def stats() -> dict[str, Any]:
    return {**kg.graph_stats(_graph()), "built_at": _graph_cache["built_at"]}


@router.post("/rebuild")
def rebuild() -> dict[str, Any]:
    with _lock:
        _graph_cache["graph"] = kg.build_graph()
        from datetime import datetime
        _graph_cache["built_at"] = datetime.now().isoformat(timespec="seconds")
    return {"ok": True, **kg.graph_stats(_graph_cache["graph"])}


@router.get("/jobs-by-skill")
def jobs_by_skill(skill: str = Query(min_length=1, max_length=60),
                  limit: int = Query(default=15, ge=1, le=100)) -> dict[str, Any]:
    return kg.query_jobs_by_skill(_graph(), skill, limit=limit)


@router.get("/skills-by-major")
def skills_by_major(major: str = Query(min_length=1, max_length=60)) -> dict[str, Any]:
    return kg.query_skills_by_major(_graph(), major)


@router.get("/explain")
def explain(major: str = Query(min_length=1, max_length=60),
            job_id: int = Query(ge=1)) -> dict[str, Any]:
    r = kg.explain_path(_graph(), major, job_id)
    if not r.get("found"):
        raise HTTPException(404, r.get("reason", "未找到"))
    return r


@router.get("/facets")
def facets() -> dict[str, Any]:
    """前端下拉：技能名与专业名（按邻接岗位数/课程数排序）。"""
    g = _graph()
    skill_cnt = [(g.nodes[n]["label"], len(list(g.predecessors(n))))
                 for n in g.nodes if g.nodes[n]["kind"] == "skill"]
    major_cnt = [(g.nodes[n]["label"], len(list(g.out_edges(n))))
                 for n in g.nodes if g.nodes[n]["kind"] == "major"]
    return {"skills": sorted(skill_cnt, key=lambda x: -x[1])[:80],
            "majors": sorted(major_cnt, key=lambda x: -x[1])[:80]}


@router.get("/neighborhood")
def neighborhood(skill: str = Query(min_length=1, max_length=60),
                 max_jobs: int = Query(default=10, ge=1, le=30),
                 max_courses: int = Query(default=8, ge=0, le=30)) -> dict[str, Any]:
    """以技能为中心的邻接子图（前端 SVG 环形布局数据源）。"""
    g = _graph()
    sn = f"skill:{skill}"
    if sn not in g.nodes:
        raise HTTPException(404, f"图谱中没有技能「{skill}」")
    jobs, courses = [], []
    for jn in g.predecessors(sn):
        n = g.nodes[jn]
        if n["kind"] == "job" and len(jobs) < max_jobs:
            jobs.append({"id": jn, "label": n["label"], "company": n.get("company"),
                         "city": n.get("city"), "salary_max": n.get("salary_max")})
        if n["kind"] == "course" and len(courses) < max_courses:
            courses.append({"id": jn, "label": n["label"]})
    return {"center": skill, "jobs": jobs, "courses": courses,
            "job_total": len(list(g.predecessors(sn)))}
