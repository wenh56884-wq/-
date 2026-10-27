# tests/test_forecast.py
# 职责：学业预测引擎用例——加权回归 / 趋势判定 / 学期推进 / 课程风险 / 缺失不冒充
# 说明：全部走注入数据，不依赖 MySQL（纯函数优先）

from __future__ import annotations

import pytest

from engine import forecast


def test_weighted_fit_recovers_rising_trend():
    intercept, slope, _std = forecast.weighted_fit([70.0, 72.0, 74.0, 76.0])
    # 完美等差序列：加权回归应还原出每学期 +2 分、起点 70 分
    assert slope == pytest.approx(2.0, abs=0.01)
    assert forecast.trend_of(slope) == "上升"
    assert intercept == pytest.approx(70.0, abs=0.5)


def test_weighted_fit_single_value_has_no_slope():
    intercept, slope, std = forecast.weighted_fit([80.0])
    assert slope == 0.0
    assert std == 0.0
    assert intercept == 80.0


def test_forecast_next_insufficient_terms():
    out = forecast.forecast_next([80.0])
    assert out["predicted"] is None
    assert out["confidence"] == "insufficient"
    assert out["terms_used"] == 1


def test_forecast_next_rising():
    out = forecast.forecast_next([70.0, 72.0, 74.0])
    assert out["predicted"] > 74.0
    assert out["trend"] == "上升"
    assert out["low"] < out["predicted"] < out["high"]


def test_forecast_next_falling():
    out = forecast.forecast_next([80.0, 77.0, 74.0])
    assert out["predicted"] < 74.0
    assert out["trend"] == "下降"


def test_forecast_is_deterministic():
    series = [70.0, 72.0, 74.0, 71.0]
    assert forecast.forecast_next(series) == forecast.forecast_next(series)


def test_confidence_levels():
    assert forecast.confidence_of(1) == "insufficient"
    assert forecast.confidence_of(2) == "低"
    assert forecast.confidence_of(4) == "中"
    assert forecast.confidence_of(6) == "高"


@pytest.mark.parametrize(
    "term,expected",
    [("2025-2026-1", "2025-2026-2"), ("2025-2026-2", "2026-2027-1"), ("", "")],
)
def test_next_term(term, expected):
    assert forecast.next_term(term) == expected


def test_risky_courses_excludes_strong_courses():
    rows = [
        {"course_code": "1", "course_name": "高分课", "term": "2025-2026-2", "score": 92.0},
        {"course_code": "2", "course_name": "薄弱课", "term": "2025-2026-2", "score": 52.0},
    ]
    stats = {
        "1": {"avg_score": 88.0, "fail_rate": 0.01, "sample": 100},
        "2": {"avg_score": 60.0, "fail_rate": 0.30, "sample": 100},
    }
    out = forecast.risky_courses(rows, stats)
    names = [c["course_name"] for c in out]
    assert "薄弱课" in names
    assert "高分课" not in names
    assert out[0]["course_name"] == "薄弱课"
    assert out[0]["risk_level"] == "高"


def test_compute_forecast_unavailable_when_short_history():
    res = forecast.compute_student_forecast(
        1, "TEST001",
        series=[{"term": "2025-2026-2", "gpa": 80.0, "fail_count": 0, "course_count": 5}],
        course_rows=[], attendance=0.95,
        profile={"name": "测试", "class_name": "T1"},
    )
    assert res["available"] is False
    assert "不足" in res["reason"]
    assert res["risky_courses"] == []
    assert res["history"] == []


def test_compute_forecast_full_and_declining():
    res = forecast.compute_student_forecast(
        1, "TEST001",
        series=[
            {"term": "2024-2025-1", "gpa": 78.0, "fail_count": 0, "course_count": 6},
            {"term": "2024-2025-2", "gpa": 76.0, "fail_count": 1, "course_count": 6},
            {"term": "2025-2026-1", "gpa": 74.0, "fail_count": 1, "course_count": 6},
            {"term": "2025-2026-2", "gpa": 72.0, "fail_count": 2, "course_count": 6},
        ],
        course_rows=[], attendance=0.90,
        profile={"name": "测试", "class_name": "T1"},
    )
    assert res["available"] is True
    assert res["base_term"] == "2025-2026-2"
    assert res["next_term"] == "2026-2027-1"
    assert res["gpa_forecast"]["predicted"] < 72.0
    assert res["gpa_forecast"]["trend"] == "下降"
    assert res["fail_forecast"]["predicted"] >= 0
    assert res["level_forecast"]["level"] in (
        "red", "orange", "yellow", "none", "unknown")
    assert len(res["assumptions"]) == 3
    assert len(res["history"]) == 4
