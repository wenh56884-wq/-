# tests/test_question_bank_infer.py
# 职责：空行业岗位的行业族推断、新族覆盖矩阵、RAG 检索的族内命中。
# 说明：全部离线，不依赖 MySQL / LLM / 网络。

from __future__ import annotations

import pytest

from engine import question_bank as qb
from engine.interview import build_outline

_RESUME = {
    "skills": ["Java"], "courses": ["数据结构"],
    "educations": [{"school": "重庆财经学院", "major": "软件工程"}],
    "experiences": [{"type": "project", "name": "校园二手交易平台", "desc": "负责后端"}],
    "self": "踏实肯学",
}


@pytest.mark.parametrize("title,want", [
    ("U3D开发工程师", "it_software"),
    ("测试工程师", "it_software"),
    ("数据分析师", "it_software"),
    ("物流专员", "logistics"),
    ("物业管家", "property"),
    ("新媒体运营", "media_design"),
    ("教师", "education"),
    ("酒店前台", "hospitality"),
    ("通信工程师", "telecom"),
    ("农业技术员", "agriculture"),
    ("机械结构工程师", "manufacturing"),
    ("临床护士", "healthcare"),
])
def test_infer_family_uses_title_when_industry_blank(title: str, want: str):
    """行业为空时按岗位名推断；不能全部落到 general。"""
    assert qb.infer_family({"title": title, "industry": ""}) == want


def test_infer_family_keeps_known_industry():
    """行业字段有明确归属时优先于标题推断。"""
    assert qb.infer_family({"title": "随便写", "industry": "医疗健康"}) == "healthcare"


def test_infer_family_unknown_stays_general():
    assert qb.infer_family({"title": "古籍修复师", "industry": "文化艺术"}) == "general"


@pytest.mark.parametrize("family", [
    "logistics", "education", "media_design", "property",
    "hospitality", "telecom", "agriculture",
])
def test_new_families_have_all_qtypes(family: str):
    """新族必须覆盖 6 种题型，否则覆盖矩阵会出现空洞。"""
    st = qb.stats()
    assert family in st["families"], f"{family} 没有语料"
    missing = [q for q in qb.QTYPES if st["families"][family]["by_qtype"].get(q, 0) == 0]
    assert not missing, f"{family} 缺题型 {missing}"


def test_blank_industry_it_job_hits_family_pool():
    """空行业 IT 岗位必须命中 it_software 专项池，而不是 general 兜底。"""
    job = {"title": "U3D开发工程师", "industry": "", "skill_tags": ["Unity", "C#"]}
    hits = qb.retrieve_for_job(job, "major", k=1)
    assert hits, "检索为空"
    assert hits[0]["pool"] == "family"
    assert hits[0]["family"] == "it_software"
    assert hits[0]["source_url"].startswith("http")


def test_blank_industry_logistics_outline_uses_bank():
    """物流岗位的提纲必须至少有一轮来自题库，且带出处。"""
    job = {"title": "物流专员", "industry": "", "skill_tags": ["仓储", "运输"]}
    outline = build_outline(job, _RESUME, max_rounds=6)
    bank_rounds = [o for o in outline if o["source"]["kind"] == "bank"]
    assert bank_rounds
    assert all(o["source"]["url"].startswith("http") for o in bank_rounds)
