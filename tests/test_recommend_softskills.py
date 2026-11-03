# tests/test_recommend_softskills.py
# 职责：四维匹配融合软技能测评——无测评回落四维 / 有测评六维打分 / 维度话术
# 运行：.venv\Scripts\python.exe -m pytest tests\test_recommend_softskills.py -v
# 说明：只测纯函数，不连库；abilities 来自 engine.assessment 的复合能力语义

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402

from engine.recommend import potential_of, score_job, soft_skills_of  # noqa: E402

JOB = {
    "id": 101, "title": "Java 后端开发工程师", "company": "示例科技", "city": "杭州",
    "salary_min": 12000, "salary_max": 20000, "education": "本科", "exp_min": 1,
    "skill_tags": ["Java", "MySQL", "数据结构"], "direction": "后端",
}

STUDENT_BASE = {
    "student_no": "S001", "term": "2025-2026-2", "major": "软件工程", "gpa": 88.0,
    "skills": ["Java程序设计", "MySQL数据库应用", "数据结构"],
    "directions": ["后端", "算法"],
}

ABILITIES_FULL = {
    "professional_skills": 90.0,
    "learning_ability": 85.0,
    "innovation_ability": 75.0,
    "stress_resistance": 70.0,
    "communication_ability": 80.0,
}


def test_no_abilities_falls_back_to_four_dims():
    """无 abilities 时：dims 只有四维，分数与融合前完全一致（不漂移）。"""
    scored = score_job(STUDENT_BASE, JOB)
    assert set(scored["dims"]) == {"major_match", "gpa_gate", "skill_cover", "interest_fit"}
    assert scored["has_soft_skills"] is False
    assert scored["has_potential"] is False
    # 四维全满：0.35+0.25+0.30+0.10 = 1.0
    assert scored["final_score"] == pytest.approx(1.0, abs=1e-4)


def test_with_abilities_adds_two_dims():
    """有 abilities 时：dims 变六维，软技能/潜力进入打分。"""
    scored = score_job({**STUDENT_BASE, "abilities": ABILITIES_FULL}, JOB)
    assert set(scored["dims"]) == {"major_match", "gpa_gate", "skill_cover",
                                   "interest_fit", "soft_skills", "potential"}
    assert scored["has_soft_skills"] is True
    assert scored["has_potential"] is True
    # 软技能=(80+70)/2/100=0.75；潜力=(85+75)/2/100=0.80
    assert scored["dims"]["soft_skills"] == pytest.approx(0.75, abs=1e-4)
    assert scored["dims"]["potential"] == pytest.approx(0.80, abs=1e-4)


def test_abilities_missing_one_key_disables_that_dim():
    """abilities 缺沟通能力 → 软技能维度整体判无数据（不拿抗压一项顶替）。"""
    partial = {k: v for k, v in ABILITIES_FULL.items() if k != "communication_ability"}
    scored = score_job({**STUDENT_BASE, "abilities": partial}, JOB)
    assert "soft_skills" not in scored["dims"]
    # 潜力两键齐全，仍参与
    assert "potential" in scored["dims"]


def test_soft_skills_of_semantics():
    """soft_skills_of：有值给归一化分 + 话术；无值不参与打分。"""
    score, reason, has = soft_skills_of(ABILITIES_FULL)
    assert has is True
    assert score == pytest.approx(0.75, abs=1e-4)
    assert "职业素养" in reason

    _, _, has_none = soft_skills_of(None)
    assert has_none is False


def test_potential_of_semantics():
    """potential_of：学习+创新均值归一化。"""
    score, reason, has = potential_of(ABILITIES_FULL)
    assert has is True
    assert score == pytest.approx(0.80, abs=1e-4)
    assert "发展潜力" in reason


def test_ability_score_clamped_to_0_1():
    """能力分超界（如 120）也归一化在 [0,1]。"""
    over = {**ABILITIES_FULL, "communication_ability": 120.0, "stress_resistance": 120.0}
    score, _, has = soft_skills_of(over)
    assert has is True
    assert 0.0 <= score <= 1.0
