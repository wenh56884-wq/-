# tests/test_metrics.py
# 职责：校验考核指标纯函数（预警二分类 / Critic / 延迟 / 推荐 / 对话）
# 依赖：engine.metrics（纯函数，全程离线）
# 说明：不连 MySQL / DuckDB；真实取数在 scripts/gen_kpi_report.py

from __future__ import annotations

import pytest

from engine import metrics


# ----------------------------------------------------------------
# 1) 预警二分类
# ----------------------------------------------------------------
def test_classification_metrics_perfect():
    y_true = {"S1": 1, "S2": 0, "S3": 1}
    y_pred = {"S1": "red", "S2": "none", "S3": "yellow"}
    out = metrics.classification_metrics(y_true, y_pred)
    assert out["tp"] == 2 and out["tn"] == 1
    assert out["fp"] == 0 and out["fn"] == 0
    assert out["accuracy"] == 1.0
    assert out["precision"] == 1.0
    assert out["recall"] == 1.0
    assert out["f1"] == 1.0
    assert out["coverage"] == 1.0


def test_classification_metrics_mixed_and_missing():
    y_true = {"S1": 1, "S2": 0, "S3": 1, "S4": 0}
    # S3 没有预测（无成绩）→ 阳性样本计为 FN；S4 unknown → 不算阳性
    y_pred = {"S1": "red", "S2": "orange"}
    out = metrics.classification_metrics(y_true, y_pred)
    assert out["sample"] == 4
    assert out["matched"] == 2
    assert out["tp"] == 1 and out["fp"] == 1
    assert out["fn"] == 1 and out["tn"] == 1
    assert out["accuracy"] == 0.5
    assert out["precision"] == 0.5
    assert out["recall"] == 0.5
    assert out["f1"] == 0.5


def test_classification_metrics_crisis_levels():
    """危机口径只把 red/orange 算阳性；yellow 退回未预警。"""
    y_true = {"S1": 1, "S2": 1, "S3": 0}
    y_pred = {"S1": "red", "S2": "yellow", "S3": "orange"}
    out = metrics.classification_metrics(
        y_true, y_pred, positive_levels=("red", "orange")
    )
    assert out["tp"] == 1
    assert out["fn"] == 1
    assert out["fp"] == 1
    assert out["tn"] == 0
    assert out["positive_levels"] == ["orange", "red"]


def test_classification_metrics_empty():
    out = metrics.classification_metrics({}, {})
    assert out["sample"] == 0
    assert out["accuracy"] is None
    assert out["precision"] is None
    assert out["recall"] is None
    assert out["f1"] is None


def test_level_distribution_unknown_key():
    out = metrics.level_distribution(["red", "red", "unknown", "weird"])
    assert out["red"] == 2
    assert out["unknown"] == 2
    assert sum(out.values()) == 4


# ----------------------------------------------------------------
# 2) 延迟分位数
# ----------------------------------------------------------------
def test_percentile_nearest_rank():
    values = [10, 20, 30, 40, 50]
    assert metrics.percentile(values, 0) == 10
    assert metrics.percentile(values, 50) == 30
    assert metrics.percentile(values, 95) == 50
    assert metrics.percentile([], 95) is None
    with pytest.raises(ValueError):
        metrics.percentile(values, 101)


def test_summarize_latency():
    out = metrics.summarize_latency([10, 20, 30, 40, 50, None])
    assert out["count"] == 5
    assert out["avg_ms"] == 30.0
    assert out["p50_ms"] == 30
    assert out["p95_ms"] == 50
    assert out["max_ms"] == 50


# ----------------------------------------------------------------
# 3) Critic / 推荐 / 对话
# ----------------------------------------------------------------
def test_summarize_critic():
    rows = [
        {"passed": True, "mismatches": [], "fuzzy": [], "attempt": 1},
        {"passed": False, "mismatches": ["数值不在结果中"], "fuzzy": [], "attempt": 1},
        {"passed": False, "mismatches": [], "fuzzy": ["出现模糊表述"], "attempt": 2},
    ]
    out = metrics.summarize_critic(rows)
    assert out["total"] == 3
    assert out["passed"] == 1
    assert out["pass_rate"] == pytest.approx(1 / 3, abs=1e-4)
    assert out["first_attempts"] == 2
    assert out["first_passed"] == 1
    assert out["first_pass_rate"] == 0.5
    assert out["mismatch_rows"] == 2
    assert out["fuzzy_rows"] == 1
    assert out["hallucination_rate"] == pytest.approx(2 / 3, abs=1e-4)


def test_summarize_recommend_parses_json_strings():
    rows = [
        {"student_no": "S1", "final_score": 0.8, "cf_score": None,
         "hit_items": '["专业匹配"]', "gap_items": '["缺 SQL"]'},
        {"student_no": "S1", "final_score": 0.6, "cf_score": 0.5,
         "hit_items": ["技能覆盖"], "gap_items": []},
    ]
    out = metrics.summarize_recommend(rows)
    assert out["total"] == 2
    assert out["students"] == 1
    assert out["avg_final_score"] == 0.7
    assert out["cf_present"] == 1
    assert out["cf_coverage"] == 0.5
    assert out["avg_hit_items"] == 1.0
    assert out["avg_gap_items"] == 0.5


def test_summarize_chat():
    rows = [{"degraded": True, "attempts": 3}, {"degraded": False, "attempts": 1}]
    out = metrics.summarize_chat(rows)
    assert out["total"] == 2
    assert out["degraded"] == 1
    assert out["degraded_rate"] == 0.5
    assert out["avg_attempts"] == 2.0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
