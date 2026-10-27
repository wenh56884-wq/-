# tests/test_spark_features.py
# 二期②：Spark 版特征工程的边界用例（离线，不起 MySQL/服务）。
#
# 口径基准 = engine/profile.build_features（v1.1），每个用例都是
# 「pandas 引擎原版 vs Spark 版」双跑对比，断言两者逐字段相等。
# 这样测试同时钉死两件事：Spark 实现没漂 + 引擎口径没被顺手改。

from __future__ import annotations

import pytest

pyspark = pytest.importorskip("pyspark", reason="未安装 pyspark，跳过 Spark 版测试")

pytestmark = pytest.mark.spark  # pytest -m "not spark" 可跳过（见 pytest.ini）

from engine.profile import build_features, to_feature_row  # noqa: E402
from features.batch_features import spark_build_rows  # noqa: E402


@pytest.fixture(scope="module")
def spark():
    from scripts.spark_env import get_spark

    s = get_spark("test-spark-features")
    yield s
    s.stop()


def _both(spark, raw: dict) -> tuple[dict, dict]:
    """同一份 raw 行分别跑 pandas 引擎与 Spark 版，返回 (pandas_row, spark_row)。"""
    raw = {"student_no": "T0001", "term": "2025-2026-2", **raw}
    p_row = to_feature_row(build_features(raw))
    s_rows = spark_build_rows(spark, [raw])
    assert len(s_rows) == 1
    return p_row, s_rows[0]


def _assert_equal(p_row: dict, s_row: dict) -> None:
    for key in p_row:
        pv, sv = p_row[key], s_row.get(key)
        if isinstance(pv, dict):
            assert {k: round(float(v), 6) for k, v in pv.items()} == \
                   {k: round(float(v), 6) for k, v in (sv or {}).items()}, key
        elif isinstance(pv, list):
            assert [str(x) for x in pv] == [str(x) for x in (sv or [])], key
        elif isinstance(pv, float):
            assert pv == pytest.approx(float(sv), abs=1e-9), key
        else:
            assert pv == sv, key


def test_empty_raw_is_no_data(spark):
    """全空 raw：标签只有「数据不足」，四维得分全 NULL，不冒充 0。"""
    p, s = _both(spark, {})
    assert p["tags"] == ["数据不足"]
    _assert_equal(p, s)


def test_missing_rank_gives_study_tag_fallback(spark):
    """无排名数据：学业标签兜底「学业数据不足」，study.score 不含 rank 权重。"""
    p, s = _both(spark, {"gpa": 80.0, "fail_count": 0})
    assert "学业数据不足" in p["tags"]
    _assert_equal(p, s)


def test_extreme_decline_appends_tag(spark):
    """gpa_trend=-35：正常三标签后追加「学业急剧下滑」，原三标签不动。"""
    raw = {"gpa": 70.0, "gpa_trend": -35.0, "fail_count": 1,
           "major_rank_pct": 0.6, "cert_count": 1}
    p, s = _both(spark, raw)
    assert p["tags"][-1] == "学业急剧下滑"
    assert len(p["tags"]) == 4
    _assert_equal(p, s)


def test_direction_tie_breaks_by_name(spark):
    """两方向频次相同：按方向名升序取第一（与引擎 sorted key 一致）。"""
    raw = {"course_pref": {"金融": 2, "大数据": 2}}
    p, s = _both(spark, raw)
    assert p["tags"][1] == "偏好大数据岗"
    _assert_equal(p, s)


def test_direction_suffix_kept_for岗(spark):
    """方向名已以「岗」结尾：不再重复加「岗」。"""
    raw = {"course_pref": {"算法岗": 3}}
    p, s = _both(spark, raw)
    assert p["tags"][1] == "偏好算法岗"
    _assert_equal(p, s)


def test_job_view_pref_weighted_half(spark):
    """job_view_pref 权重 0.5：选课 1 次 vs 浏览 2 次同频，平局按名称。"""
    raw = {"course_pref": {"前端": 2}, "job_view_pref": {"后端": 4}}
    p, s = _both(spark, raw)
    assert p["tags"][1] == "偏好前端岗"  # 2 vs 4*0.5=2 → 平局 → 名称升序
    _assert_equal(p, s)


def test_saturation_caps_at_one(spark):
    """次数远超饱和值：归一化封顶 1.0（不发散）。"""
    raw = {"library_visit_cnt": 600, "job_view_cnt": 500, "cert_count": 9}
    p, s = _both(spark, raw)
    assert p["library_activity"] == 1.0
    _assert_equal(p, s)


def test_library_visit_fallback_when_activity_missing(spark):
    """library_activity 缺失但给了次数：按 60 次饱和折算，不冒充 0。"""
    p, s = _both(spark, {"library_visit_cnt": 30})
    assert p["library_activity"] == 0.5
    _assert_equal(p, s)


def test_weight_renormalized_on_missing(spark):
    """缺失子指标不参与：剩余权重归一（gpa 0.4 全占 study.score）。"""
    p, s = _both(spark, {"gpa": 50.0, "major_rank_pct": 0.75})
    # gpa_norm=0.5, rank_norm=0.25 → (0.5*0.4 + 0.25*0.2)/0.6 ≈ 0.5
    assert abs(p["gpa"] - 50.0) < 1e-9
    _assert_equal(p, s)


def test_batch_rows_aligned_by_student_no(spark):
    """批量入口：乱序输入也要按 student_no 对齐产出，不丢行。"""
    raws = [
        {"student_no": "S002", "term": "2025-2026-2", "gpa": 90.0,
         "major_rank_pct": 0.1, "cert_count": 1},
        {"student_no": "S001", "term": "2025-2026-2", "gpa": 60.0,
         "major_rank_pct": 0.9, "contest_count": 2},
        {"student_no": "S003", "term": "2025-2026-2"},
    ]
    s_rows = spark_build_rows(spark, raws)
    assert {r["student_no"] for r in s_rows} == {"S001", "S002", "S003"}
    by_no = {r["student_no"]: r for r in s_rows}
    for raw in raws:
        p_row = to_feature_row(build_features({"term": "2025-2026-2", **raw}))
        _assert_equal(p_row, by_no[raw["student_no"]])
