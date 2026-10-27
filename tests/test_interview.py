# tests/test_interview.py
# 模拟面试官引擎离线单测：不依赖 MySQL / LLM（AGENT_LLM_DRAFT=0 走模板降级路径）

from __future__ import annotations

import os

import pytest

os.environ.setdefault("AGENT_LLM_DRAFT", "0")  # 引擎级测试不依赖外部 LLM

from agents import interviewer  # noqa: E402
from engine.interview import (  # noqa: E402
    aggregate,
    build_outline,
    diagnose,
    extract_quotes,
    fallback_comment,
    gap_list,
    parse_resume,
    rubric_of,
    score_answer,
    verify_comment,
)

pytestmark = pytest.mark.interview

_RESUME = {
    "skills": ["Java", "MySQL", "Spring Boot"], "certs": [{"name": "CET-6", "level": "568"}],
    "courses": ["数据结构"], "educations": [{"school": "重庆财经学院", "major": "软件工程"}],
    "experiences": [{"type": "project", "name": "校园二手交易平台", "desc": "负责后端开发"}],
    "self": "踏实肯学",
}
_JOB = {"title": "Java开发工程师", "skill_tags": ["Java", "Spring Boot", "Redis"], "education": "本科"}


# ---------------- 提纲 ----------------
def test_outline_covers_project_when_experience_exists():
    outline = build_outline(_JOB, _RESUME)
    types = [o["type"] for o in outline]
    assert "project" in types and types[0] == "motivation" and types[-1] == "counter"


def test_outline_skips_major_without_skill_or_course():
    bare = {"experiences": [{"type": "project", "name": "课程作业", "desc": "写了个页面"}]}
    outline = build_outline({"title": "x", "skill_tags": []}, bare)
    assert "major" not in [o["type"] for o in outline]  # 缺证据不出题，不编造


def test_outline_question_places_project_name():
    outline = build_outline(_JOB, _RESUME)
    q = next(o for o in outline if o["type"] == "project")["question"]
    assert "校园二手交易平台" in q


def test_outline_rounds_capped():
    assert len(build_outline(_JOB, _RESUME, max_rounds=3)) <= 3


# ---------------- 评分 ----------------
def test_score_answer_none_when_unanswered():
    assert score_answer(None, rubric_of("project", []), ["x"]) is None
    assert score_answer("   ", rubric_of("project", []), ["x"]) is None


def test_score_answer_structured_beats_vague():
    rubric = rubric_of("project", _JOB["skill_tags"])
    good = score_answer("首先分析需求，然后实现接口，结果支撑500用户，负责后端整体设计。", rubric, [])
    vague = score_answer("就是正常做。", rubric, [])
    assert good["score"] > vague["score"]


def test_score_answer_capped_at_100():
    rubric = rubric_of("project", _JOB["skill_tags"])
    item = score_answer("首先然后最后，负责完成结果实现解决，" * 20, rubric, [])
    assert 0 <= item["score"] <= 100


def test_aggregate_skips_unanswered_and_none_when_all_skipped():
    outline = build_outline(_JOB, _RESUME)
    items = [score_answer("答" * 60, o["rubric"], []) for o in outline]
    items[0] = None
    total = aggregate(items, outline)
    assert total["skipped"] == 1 and total["answered"] == len(outline) - 1
    assert aggregate([None] * len(outline), outline) is None


# ---------------- 防虚构 ----------------
def test_verify_comment_rejects_fabrication():
    ok, bad = verify_comment("你提到「主导千万级重构」。", "我只是参与了小项目。", ["简历片段"])
    assert not ok and bad == ["主导千万级重构"]


def test_verify_comment_requires_at_least_one_quote():
    ok, bad = verify_comment("回答得不错，继续加油。", "回答内容", ["证据"])
    assert not ok  # 无引文也算不通过：防虚构要求可回溯


def test_verify_comment_accepts_verbatim_quote():
    ans = "我负责后端开发，结果支撑500用户。"
    ok, bad = verify_comment("你回答提到「负责后端开发」，结果有数字支撑。", ans, [])
    assert ok and not bad


def test_extract_quotes_full_width_and_semicolon_variants():
    assert extract_quotes("他说「A」，她说『B』") == ["A", "B"]


def test_fallback_comment_quotes_answer_verbatim():
    item = score_answer("我负责后端开发，结果不错。", rubric_of("project", []), [])
    fb = fallback_comment("q", item, "我负责后端开发，结果不错。")
    assert verify_comment(fb, "我负责后端开发，结果不错。", [])[0]


def test_agent_turn_graph_fallback_path_uses_template():
    out = interviewer.run_turn("问", "project", "我负责后端开发，结果不错。",
                               score_answer("我负责后端开发，结果不错。", rubric_of("project", []), []),
                               ["简历"])
    assert out["quotes_ok"] and out["comment_version"] == "comment-fallback-v1"


def test_agent_turn_graph_unanswered_is_recorded_not_scored():
    out = interviewer.run_turn("问", "project", None, None, [])
    assert "未作答" in out["comment"]


# ---------------- 差距与解析 ----------------
def test_gap_list_reports_missing_job_skill():
    gaps = gap_list(_RESUME, _JOB)
    assert any(g["dimension"] == "技能" and "Redis" in g["gap"] for g in gaps)


def test_gap_list_reports_no_intern_and_missing_education():
    gaps = gap_list({"skills": [], "certs": [], "educations": [], "experiences": []}, _JOB)
    dims = {g["dimension"] for g in gaps}
    assert {"经历", "信息"} <= dims


def test_parse_resume_sections_and_cert_score():
    text = ("教育经历\n重庆财经学院｜软件工程｜2023.09-2027.06\n技能证书\nCET-6 568\nJava、MySQL\n"
            "实践经历\n校园平台｜完成12个接口\n自我评价\n踏实")
    p = parse_resume(text)
    assert p["educations"][0]["school"] == "重庆财经学院"
    assert p["educations"][0]["major"] == "软件工程"
    assert p["skills"] == ["Java", "MySQL"]
    assert p["certs"][0]["level"] == "568"
    assert p["experiences"][0]["type"] in ("project", "activity")


def test_parse_resume_never_fabricates():
    p = parse_resume("只有一句话的简历")
    assert p["educations"] == [] and p["experiences"] == []


def test_diagnose_flags_missing_quantify_and_alignment():
    p = parse_resume("实践经历\n校园平台｜负责开发工作\n")
    d = diagnose(p, {"skill_tags": ["Java", "Redis"]})
    kinds = {i["kind"] for i in d["issues"]}
    assert {"quantify", "alignment"} <= kinds
