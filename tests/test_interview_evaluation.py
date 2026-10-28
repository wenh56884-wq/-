# tests/test_interview_evaluation.py
# 职责：interview-v2 评估报告引擎件契约——维度分 / 核心问题 / 改进计划 / 结构化评估。
# 说明：纯函数离线测试；不依赖 MySQL / LLM。

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from engine.interview import (  # noqa: E402
    INTERVIEW_ENGINE_VERSION,
    build_outline,
    core_problems,
    dimension_scores,
    improvement_plan,
    score_answer,
)

RESUME = {
    "educations": [{"school": "测试大学", "major": "软件工程", "dates": "2023-2027"}],
    "skills": ["Python", "MySQL"],
    "certs": [],
    "courses": ["数据结构"],
    "experiences": [{"type": "project", "name": "校园二手交易平台",
                     "desc": "负责后端开发，完成12个接口"}],
}
JOB = {"title": "Python 后端开发", "industry": "互联网",
       "skill_tags": ["Python", "MySQL", "FastAPI"], "education": "本科"}


def _outline():
    return build_outline(JOB, RESUME, max_rounds=4)


def _rubric_of(q):
    from engine.interview import rubric_of
    return rubric_of(str(q["type"]), JOB["skill_tags"])


def _answer(q, text):
    return score_answer(text, _rubric_of(q), [RESUME["experiences"][0]["desc"]])


# ----------------------------------------------------------------
# 维度分
# ----------------------------------------------------------------
def test_dimension_scores_only_listed_dimensions():
    outline = _outline()
    scores = [score_answer("我会Python也用过MySQL，分点一、分点二、分点三，"
                           "在校园二手交易平台完成12个接口" * 3, _rubric_of(o),
                           [RESUME["experiences"][0]["desc"]]) for o in outline]
    dims = dimension_scores(scores, outline)
    types = {d["type"] for d in dims}
    assert types <= {o["type"] for o in outline}, "维度必须是出过的题，不许冒充没问的维度"
    for d in dims:
        assert d["answered"] >= 1 and d["avg"] is not None


def test_dimension_scores_excludes_unanswered():
    outline = _outline()
    scores = [None, None, None, None]
    dims = dimension_scores(scores, outline)
    assert all(d["avg"] is None and d["answered"] == 0 for d in dims)


# ----------------------------------------------------------------
# 核心问题
# ----------------------------------------------------------------
def test_core_problems_flags_skipped_first():
    outline = _outline()
    problems = core_problems([None] * len(outline), outline)
    assert problems and problems[0]["severity"] == "high"
    assert "跳过" in problems[0]["problem"]


def test_core_problems_flags_missed_keywords():
    outline = _outline()[:2]
    # 全空回答：关键词全漏、结构 0、深度短 → 至少命中「考点覆盖」或「表达结构」
    scores = [score_answer("不知道", _rubric_of(o), []) for o in outline]
    problems = core_problems(scores, outline)
    dims = {p["dimension"] for p in problems}
    assert dims & {"考点覆盖", "表达结构", "回答深度"}


def test_core_problems_capped_and_sorted():
    outline = _outline()
    scores = [score_answer("不知道", _rubric_of(o), []) for o in outline]
    problems = core_problems(scores, outline)
    assert len(problems) <= 5
    order = {"high": 0, "medium": 1, "low": 2}
    severities = [order[p["severity"]] for p in problems]
    assert severities == sorted(severities)


def test_core_problems_good_answers_are_quiet():
    outline = _outline()
    good = ("第一，我修过数据库原理课程并且自己用Python和MySQL做过练习项目；"
            "第二，在校园二手交易平台负责后端开发，完成了12个接口；"
            "第三，结果上平台服务了500名学生，接口平均响应200ms。"
            "背景是学校二手交易难，目标就是做出可用系统，"
            "行动上我完成了全部后端接口开发，结果是上线后稳定运行。")
    scores = [score_answer(good, _rubric_of(o), [RESUME["experiences"][0]["desc"],
                                                " ".join(JOB["skill_tags"])])
              for o in outline]
    problems = core_problems(scores, outline)
    assert not any(p["dimension"] == "参与度" for p in problems)


# ----------------------------------------------------------------
# 改进计划
# ----------------------------------------------------------------
def test_improvement_plan_three_steps():
    outline = _outline()
    problems = core_problems([None] * len(outline), outline)
    gaps = [{"dimension": "技能", "gap": "缺 FastAPI", "action": "补齐"},
            {"dimension": "经历", "gap": "没实习", "action": "找实习"}]
    plan = improvement_plan(gaps, problems)
    assert plan and plan[0]["when"] in ("近 3 天", "保持")
    assert any(s["when"] == "两周内" for s in plan)
    assert len(plan) <= 4


def test_improvement_plan_falls_back_when_clean():
    plan = improvement_plan([], [])
    assert plan and plan[0]["focus"] == "整体表现"


# ----------------------------------------------------------------
# 结构化评估（router 层）
# ----------------------------------------------------------------
def test_build_evaluation_shape():
    from app.routers.interview import _build_evaluation

    outline = _outline()
    answer = ("我用Python和MySQL做过校园二手交易平台，负责后端12个接口。"
              "背景是学校二手交易难，目标是做出可用系统，"
              "行动是我完成全部后端接口，结果是服务500名学生。")
    answers = [{"学生回答": answer, "点评": f"「{answer[:6]}」引文点评", "点评版本": "comment-fallback-v1"}
               for _ in outline]
    evidence = [RESUME["experiences"][0]["desc"], " ".join(JOB["skill_tags"])]
    eva = _build_evaluation(outline, answers, evidence, JOB, RESUME)
    assert eva["engine_version"] == INTERVIEW_ENGINE_VERSION
    assert eva["total"] is not None
    assert len(eva["per_question"]) == len(outline)
    for q in eva["per_question"]:
        assert {"round", "label", "score", "comment", "keyword_missed",
                "is_probe"} <= set(q)
    assert "核心问题" in eva["report"] or "改进计划" in eva["report"]
    assert isinstance(eva["core_problems"], list) and isinstance(eva["improvement_plan"], list)


def test_build_evaluation_reuses_stored_comments():
    from app.routers.interview import _build_evaluation

    outline = _outline()
    answers = [{"学生回答": "不知道", "点评": "落库点评A", "点评版本": "comment-fallback-v1"}
               for _ in outline]
    eva = _build_evaluation(outline, answers, [], JOB, RESUME)
    assert all(q["comment"] == "落库点评A" for q in eva["per_question"]), \
        "收卷必须复用落库点评，不重跑模型"
