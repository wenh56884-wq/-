# tests/test_assessment.py
# 职责：钉死软技能测评打分口径（assessment-v1）
# 运行：.venv\Scripts\python.exe -m pytest tests\test_assessment.py -v
# 说明：全部走纯函数，不连 MySQL、不调大模型

from __future__ import annotations

import pytest

from engine import assessment as a


def _q(qid: int, dimension: str, scoring: dict) -> dict:
    return {"id": qid, "dimension": dimension, "scoring": scoring}


def test_single_question_full_score():
    """单题选满分选项，维度 pct 应为 100。"""
    qs = [_q(1, "逻辑思维", {"A": 5, "B": 4, "C": 2, "D": 1})]
    r = a.score_answers(qs, {1: "A"})
    assert r["total_score"] == 5.0
    assert r["total_max"] == 5.0
    assert r["dimensions"]["逻辑思维"]["pct"] == 100.0


def test_single_question_partial_score():
    """选非满分选项，按选项分值计分，不是线性 A=1。"""
    qs = [_q(1, "沟通表达", {"A": 5, "B": 4, "C": 2, "D": 1})]
    r = a.score_answers(qs, {1: "B"})
    assert r["dimensions"]["沟通表达"]["pct"] == 80.0


def test_unanswered_question_excluded():
    """未作答的题不进满分分母，不影响维度 pct。"""
    qs = [_q(1, "逻辑思维", {"A": 5, "B": 4}), _q(2, "逻辑思维", {"A": 5, "B": 4})]
    r = a.score_answers(qs, {1: "A"})
    assert r["answered"] == 1
    assert r["total_max"] == 5.0
    assert r["dimensions"]["逻辑思维"]["pct"] == 100.0


def test_weight_caps_at_100():
    """权重放大（如逻辑思维 1.2）后复合能力分封顶 100。"""
    qs = [_q(1, "逻辑思维", {"A": 5, "B": 4, "C": 2, "D": 1})]
    r = a.score_answers(qs, {1: "A"})
    # 维度加权分 = 100 * 1.2 = 120 → 封顶 100
    assert r["dimension_scores"]["逻辑思维"] == 100.0
    assert r["abilities"]["professional_skills"] == 100.0


def test_dimension_maps_to_ability():
    """量表维度正确归入复合能力：沟通表达 → communication_ability。"""
    qs = [_q(1, "沟通表达", {"A": 5, "B": 4, "C": 2, "D": 1})]
    r = a.score_answers(qs, {1: "B"})
    assert r["abilities"]["communication_ability"] == 80.0


def test_missing_ability_falls_back_to_50():
    """未覆盖到的复合能力回中性 50，不冒充 0。"""
    qs = [_q(1, "逻辑思维", {"A": 5, "B": 4})]
    r = a.score_answers(qs, {1: "A"})
    assert r["abilities"]["learning_ability"] == 50.0
    assert r["abilities"]["stress_resistance"] == 50.0


def test_unknown_option_scores_zero():
    """选了不在分值表里的选项，该题得 0 分（不计为满分）。"""
    qs = [_q(1, "逻辑思维", {"A": 5, "B": 4})]
    r = a.score_answers(qs, {1: "Z"})
    assert r["total_score"] == 0.0
    assert r["dimensions"]["逻辑思维"]["pct"] == 0.0


def test_deterministic():
    """同输入必得同输出。"""
    qs = [
        _q(1, "逻辑思维", {"A": 5, "B": 4, "C": 2, "D": 1}),
        _q(2, "沟通表达", {"A": 5, "B": 4, "C": 2, "D": 1}),
        _q(3, "抗压能力", {"A": 5, "B": 4, "C": 2, "D": 1}),
    ]
    answers = {1: "A", 2: "B", 3: "C"}
    r1 = a.score_answers(qs, answers)
    r2 = a.score_answers(qs, answers)
    assert r1 == r2
