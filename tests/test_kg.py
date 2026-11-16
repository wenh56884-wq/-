# tests/test_kg.py
# 知识图谱单测：离线手工构造小图（不依赖 MySQL），验证三个查询与 explain_path 口径。

from __future__ import annotations

import networkx as nx
import pytest

from engine.kg import (
    KG_VERSION,
    _skill_match,
    explain_path,
    graph_stats,
    query_jobs_by_skill,
    query_skills_by_major,
    skills_for_course,
)

pytestmark = pytest.mark.kg


def _mini_graph() -> nx.DiGraph:
    g = nx.DiGraph()
    g.graph["version"] = KG_VERSION
    g.add_node("major:会计学", kind="major", label="会计学")
    g.add_node("course:基础会计", kind="course", label="基础会计")
    g.add_node("course:财务管理", kind="course", label="财务管理")
    g.add_node("skill:会计核算", kind="skill", label="会计核算")
    g.add_node("skill:财务管理", kind="skill", label="财务管理")
    g.add_node("skill:Excel", kind="skill", label="Excel")
    g.add_node("job:1", kind="job", label="会计专员", company="某公司", city="重庆",
               direction="财务", education="本科", salary_min=4000, salary_max=6000, tags=[])
    g.add_node("job:2", kind="job", label="数据专员", company="某公司", city="重庆",
               direction="数据", education="不限", salary_min=5000, salary_max=8000, tags=[])
    g.add_edge("major:会计学", "course:基础会计", kind="开设")
    g.add_edge("major:会计学", "course:财务管理", kind="开设")
    g.add_edge("course:基础会计", "skill:会计核算", kind="培养")
    g.add_edge("course:财务管理", "skill:财务管理", kind="培养")
    g.add_edge("course:财务管理", "skill:Excel", kind="培养")
    g.add_edge("job:1", "skill:会计核算", kind="要求")
    g.add_edge("job:1", "skill:Excel", kind="要求")
    g.add_edge("job:2", "skill:Excel", kind="要求")
    g.add_edge("major:会计学", "job:1", kind="对口")
    return g


def test_stats_counts_kinds():
    s = graph_stats(_mini_graph())
    assert s["nodes_by_kind"] == {"major": 1, "course": 2, "skill": 3, "job": 2}
    assert s["edges_by_kind"] == {"开设": 2, "培养": 3, "要求": 3, "对口": 1}


def test_query_jobs_by_skill_hits_predecessors():
    r = query_jobs_by_skill(_mini_graph(), "Excel")
    assert r["total"] == 2 and {i["id"] for i in r["items"]} == {1, 2}
    # 薪资高的排前（确定性排序）
    assert r["items"][0]["id"] == 2


def test_query_jobs_by_skill_unknown_returns_empty():
    assert query_jobs_by_skill(_mini_graph(), "区块链")["total"] == 0


def test_query_skills_by_major_walks_courses():
    r = query_skills_by_major(_mini_graph(), "会计学")
    assert r["course_cnt"] == 2
    names = {s["skill"] for s in r["skills"]}
    assert names == {"会计核算", "财务管理", "Excel"}


def test_query_skills_by_major_unknown_major():
    r = query_skills_by_major(_mini_graph(), "航天工程")
    assert r["total"] == 0 and r["courses"] == []


def test_skill_match_substring_and_case():
    assert _skill_match("财务管理", "财务")
    assert _skill_match("HIVE", "hive")
    assert not _skill_match("会计", "审计")


def test_explain_path_full_chain_with_missing():
    r = explain_path(_mini_graph(), "会计学", 1)
    assert r["found"] and r["job"] == "会计专员"
    assert set(r["covered"]) == {"会计核算", "Excel"}
    assert r["missing"] == []
    chain_skill = {c["skill"] for c in r["chain"]}
    assert chain_skill == {"会计核算", "Excel"}


def test_explain_path_reports_gap():
    g = _mini_graph()
    g.add_edge("job:1", "skill:税务处理", kind="要求")
    g.add_node("skill:税务处理", kind="skill", label="税务处理")
    r = explain_path(g, "会计学", 1)
    assert r["missing"] == ["税务处理"] and "缺 1 项" in r["summary"]


def test_explain_path_unknown_job():
    assert not explain_path(_mini_graph(), "会计学", 999)["found"]


def test_skills_for_course_maps_ai_core_courses():
    """工科核心课能落到真实技能；「算法」不得被「法」误判成法律合规。"""
    assert skills_for_course("人工智能导论") == ("人工智能", "算法")
    assert skills_for_course("计算机视觉") == ("算法", "机器学习")
    assert skills_for_course("深度学习") == ("机器学习", "算法")
    assert "法律合规" not in skills_for_course("数据结构与算法")
    assert "法律合规" in skills_for_course("经济法")
    assert skills_for_course("高等数学") == ()
