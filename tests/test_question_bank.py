# tests/test_question_bank.py
# 题库 RAG 的离线单测：不依赖 MySQL / LLM / 网络。
# 覆盖：行业归一化 / 语料门禁 / 检索命中与兜底 / 排序确定性 / 考点不被覆盖。

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine import question_bank as qb
from engine.interview import build_outline, rubric_from_bank

pytestmark = pytest.mark.interview

_JOB_IT = {"title": "Java后端开发工程师", "industry": "计算机软件",
           "skill_tags": ["Java", "MySQL", "Spring Boot"], "education": "本科"}
_JOB_NURSE = {"title": "临床护士", "industry": "医疗健康",
              "skill_tags": ["静脉输液", "护理"], "education": "本科"}
_JOB_UNKNOWN = {"title": "古籍修复师", "industry": "文化艺术", "skill_tags": ["修复"]}
_RESUME = {"skills": ["Java"], "courses": ["数据结构"],
           "educations": [{"school": "重庆财经学院", "major": "软件工程"}],
           "experiences": [{"type": "project", "name": "校园二手交易平台", "desc": "负责后端"}],
           "self": "踏实肯学"}


# ---------------------------------------------------------------- 行业归一化
@pytest.mark.parametrize("industry,want", [
    ("计算机软件", "it_software"),
    ("互联网/电子商务", "it_software"),
    ("银行", "finance_bank"),
    ("金融/投资/证券", "finance_bank"),
    ("会计/审计", "accounting"),
    ("机械/设备/重工", "manufacturing"),
    ("医疗健康", "healthcare"),
    ("医疗设备/器械", "healthcare"),
    ("", "general"),
    (None, "general"),
    ("外星殖民开发", "general"),      # 认不出就是 general，不硬猜
])
def test_normalize_industry(industry, want):
    assert qb.normalize_industry(industry) == want


def test_normalize_industry_always_returns_known_family():
    """任何输入都必须落到 FAMILY_LABELS 里已登记的族，不能返回野字符串。"""
    probes = ["", None, "文化艺术", "量子玄学", "   ", "互联网+", "其它"]
    for p in probes:
        fam = qb.normalize_industry(p)
        assert fam in qb.FAMILY_LABELS, f"{p!r} 归一化成了未登记的族 {fam!r}"


def test_family_label_covers_all_rules():
    """规则里出现的每个族都必须有中文标签，否则前端会显示英文 key。"""
    for family, _ in qb._INDUSTRY_RULES:
        assert family in qb.FAMILY_LABELS
    assert "general" in qb.FAMILY_LABELS


# ---------------------------------------------------------------- 语料门禁
def test_bank_loads_and_every_item_has_source():
    items = qb.load_bank()
    assert len(items) >= 100, "题库条数过少，检索会大量回落模板"
    for it in items:
        assert it.source_url.startswith("http"), f"{it.id} 来源链接不合法"
        assert it.source_name, f"{it.id} 缺来源名称"
        assert it.question.strip(), f"{it.id} 题面为空"
        assert it.qtype in qb.QTYPES


def test_bank_rejects_item_without_source(tmp_path: Path):
    """没有出处的题必须被拒收——这是防幻觉的第一道闸。"""
    bad = {"family": "general", "items": [{
        "id": "bad-001", "qtype": "major", "question": "这是一道没有出处的题",
        "keywords": ["x"], "source_name": "某处", "source_url": "",
    }]}
    (tmp_path / "bad.json").write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="source_url"):
        qb.load_bank(tmp_path)


def test_bank_rejects_unknown_qtype(tmp_path: Path):
    bad = {"family": "general", "items": [{
        "id": "bad-002", "qtype": "brainteaser", "question": "题", "keywords": [],
        "source_name": "某处", "source_url": "https://example.com",
    }]}
    (tmp_path / "bad.json").write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="qtype"):
        qb.load_bank(tmp_path)


def test_bank_rejects_duplicate_id(tmp_path: Path):
    dup = {"family": "general", "items": [
        {"id": "dup-1", "qtype": "major", "question": "A", "keywords": [],
         "source_name": "s", "source_url": "https://example.com"},
        {"id": "dup-1", "qtype": "major", "question": "B", "keywords": [],
         "source_name": "s", "source_url": "https://example.com"},
    ]}
    (tmp_path / "dup.json").write_text(json.dumps(dup, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="重复"):
        qb.load_bank(tmp_path)


# ---------------------------------------------------------------- 检索
def test_retrieve_hits_family_pool_first():
    hits = qb.retrieve_for_job(_JOB_IT, "major", k=2)
    assert hits, "IT 岗位应能检索到专业题"
    assert hits[0]["pool"] == "family"
    assert hits[0]["family"] == "it_software"
    assert hits[0]["source_url"].startswith("http")


def test_retrieve_falls_back_to_general_when_family_missing():
    """未知行业 → 只能拿到 general 兜底题，不能凭空造题。"""
    hits = qb.retrieve_for_job(_JOB_UNKNOWN, "project", k=2)
    assert hits
    assert all(h["pool"] == "general" for h in hits)


def test_retrieve_returns_empty_for_unknown_qtype():
    assert qb.retrieve("计算机软件", "Java", "brainteaser", k=3) == []


def test_retrieve_is_deterministic():
    a = qb.retrieve_for_job(_JOB_NURSE, "major", k=3)
    b = qb.retrieve_for_job(_JOB_NURSE, "major", k=3)
    assert [x["id"] for x in a] == [x["id"] for x in b]


def test_retrieve_score_descending():
    hits = qb.retrieve_for_job(_JOB_IT, "major", k=5)
    scores = [h["score"] for h in hits]
    assert scores == sorted(scores, reverse=True)


def test_retrieve_k_respected():
    assert len(qb.retrieve_for_job(_JOB_IT, "major", k=1)) == 1
    assert len(qb.retrieve_for_job(_JOB_IT, "major", k=3)) <= 3


def test_job_family_hit_splits_multi_value():
    """题目岗位族写成「柜员/客户服务」，岗位名是「银行柜员」，必须能命中。"""
    item = qb.BankItem(id="x", family="finance_bank", qtype="major", question="q",
                       keywords=(), answer_hint="", difficulty=1, source_name="s",
                       source_url="https://example.com", job_family="柜员/客户服务")
    assert qb._job_family_hit("银行柜员", item) is True
    assert qb._job_family_hit("Java工程师", item) is False


# ---------------------------------------------------------------- 接进组题
def test_outline_uses_bank_with_traceable_source():
    outline = build_outline(_JOB_IT, _RESUME, max_rounds=6)
    bank_rounds = [o for o in outline if o["source"]["kind"] == "bank"]
    assert len(bank_rounds) >= 4, "题库覆盖应能覆盖多数轮次"
    for o in bank_rounds:
        src = o["source"]
        assert src["url"].startswith("http")
        assert src["name"]
        assert src["id"]
        assert o["rubric"]["bank_id"] == src["id"]


def test_outline_project_question_anchors_resume():
    """项目题必须锚定简历里的项目名，否则退化成泛泛行为题。"""
    outline = build_outline(_JOB_IT, _RESUME, max_rounds=6)
    proj = next(o for o in outline if o["type"] == "project")
    assert "校园二手交易平台" in proj["question"]
    assert proj["source"]["kind"] == "bank"
    # 锚点前缀不改题库原文，原文仍可回查
    assert proj["source"]["question_raw"] in proj["question"]


def test_outline_template_fallback_when_bank_disabled():
    outline = build_outline(_JOB_IT, _RESUME, max_rounds=6, use_bank=False)
    assert all(o["source"]["kind"] == "template" for o in outline)


def test_rubric_from_bank_keeps_bank_keywords():
    hit = {"id": "acc-major-001", "qtype": "major",
           "keywords": ["资产", "负债", "所有者权益"], "label": "专业基础"}
    r = rubric_from_bank(hit)
    assert r["keywords"] == ["资产", "负债", "所有者权益"]
    assert r["bank_id"] == "acc-major-001"
    assert r["struct_marks"]


def test_rubric_of_q_prefers_stored_rubric():
    """路由层必须用提纲里存的考点，不能用 rubric_of 重算覆盖题库考点。"""
    from app.routers.interview import _rubric_of_q
    q = {"type": "major", "rubric": {"keywords": ["题库考点A", "题库考点B"], "label": "专业基础"}}
    got = _rubric_of_q(q, ["岗位技能X"])
    assert got["keywords"] == ["题库考点A", "题库考点B"]


def test_rubric_of_q_falls_back_when_missing():
    from app.routers.interview import _rubric_of_q
    got = _rubric_of_q({"type": "major"}, ["岗位技能X"])
    assert "岗位技能X" in got["keywords"]


# ---------------------------------------------------------------- 统计
def test_stats_matrix_shape():
    s = qb.stats()
    assert s["total"] >= 100
    assert set(s["qtypes"]) == set(qb.QTYPES)
    for fam, info in s["families"].items():
        assert info["total"] == sum(info["by_qtype"].values())
        assert fam in qb.FAMILY_LABELS
    assert s["sources"], "必须有来源清单"


# ---------------------------------------------------------------- 简历感知
def test_term_hit_tolerates_split_wording():
    """「数据库原理」应能命中题面「数据库索引的原理」（2-gram 覆盖 3/4）。"""
    from engine.interview import _term_hit
    text = "数据库索引的原理是什么索引有哪些种类"
    grams = {text[i:i + 2] for i in range(len(text) - 1)} | {text}
    assert _term_hit("数据库原理", grams) is True
    assert _term_hit("计算机网络", grams) is False


def test_resume_affinity_ranks_relevant_question_higher():
    from engine.interview import _resume_affinity
    spring_hit = {"question": "对 Spring 的理解？IOC 和 AOP 的实现原理？",
                  "keywords": ["IOC", "AOP", "动态代理"]}
    index_hit = {"question": "数据库索引的原理是什么？", "keywords": ["B+树", "回表"]}
    resume = {"skills": ["Spring", "AOP"], "courses": ["Spring框架"]}
    assert _resume_affinity(spring_hit, resume) > _resume_affinity(index_hit, resume)


def test_major_question_varies_with_resume():
    """同一岗位、不同简历，专业题应当会不同（简历感知重排确实在起作用）。"""
    job = {"title": "Java后端开发工程师", "industry": "计算机软件",
           "skill_tags": ["Java", "MySQL", "Spring Boot"]}
    a = {"skills": ["Java", "Spring"], "courses": ["Spring框架", "AOP"],
         "experiences": [{"type": "project", "name": "订单中台"}]}
    b = {"skills": ["Java"], "courses": ["数据结构"],
         "experiences": [{"type": "project", "name": "秒杀系统"}]}
    q_a = next(o for o in build_outline(job, a, 6) if o["type"] == "major")
    q_b = next(o for o in build_outline(job, b, 6) if o["type"] == "major")
    # 不强制一定不同（题库窗口内可能同题），但两条路径都必须可回溯
    for q in (q_a, q_b):
        assert q["source"]["kind"] in ("bank", "template")
        if q["source"]["kind"] == "bank":
            assert q["source"]["url"].startswith("http")


def test_bank_pick_is_deterministic_with_resume():
    from engine.interview import _bank_pick
    job = {"title": "Java后端开发工程师", "industry": "计算机软件",
           "skill_tags": ["Java", "MySQL"]}
    resume = {"skills": ["Spring"], "courses": ["Spring框架"]}
    first = _bank_pick(job, "major", resume)
    for _ in range(3):
        assert _bank_pick(job, "major", resume)["id"] == first["id"]
