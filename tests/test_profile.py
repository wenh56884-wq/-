# tests/test_profile.py
# 职责：四维画像引擎用例（默认离线；可取数时用注入的 raw_rows 与临时 DuckDB）
# 依赖：pytest / engine.profile / engine.store / duckdb
# 说明：不调用大模型，断言值全部由常量表推导，随引擎改动同步调整

from __future__ import annotations

import sys
from pathlib import Path

# 把项目根目录加入 sys.path（无 conftest 时保证 engine 包可导入）
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, _ROOT)

import duckdb
import pytest

from engine.profile import (
    CALC_VERSION,
    batch_build,
    build_features,
    fetch_student_raw,
    make_tags,
    to_feature_row,
    top_direction,
)
from engine.store import DuckDBStore

TERM = "2025-2026-2"
TENANT = 1

_FULL_RAW: dict = {
    "student_no": "RJ2022001",
    "term": TERM,
    "gpa": 88.0,
    "gpa_trend": 3.0,
    "fail_count": 0,
    "rank_pct": 0.15,
    "attendance_rate": 0.95,
    "library_activity": 0.60,
    "consumption_regularity": 0.80,
    "course_pref": {"算法": 3, "前端": 1},
    "job_view_pref": {"算法": 8},
    "job_view_cnt": 30,
    "job_favorite_cnt": 10,
    "cert_count": 2,
    "contest_count": 1,
    "project_cnt": 0,
}


def _rows(n: int = 3) -> list[dict]:
    """构造 n 条原始宽行（学号不同，其余一致）。"""
    # 项目数奇偶交替，一次覆盖「缺乏项目经历」与「能力履历完整」两种能力标签
    return [
        {**_FULL_RAW, "student_no": f"RJ2022{i:03d}",
         "project_cnt": 0 if i % 2 == 1 else 1}
        for i in range(1, n + 1)
    ]


def _tmp_store(tmp_path: Path) -> tuple[DuckDBStore, Path]:
    """用临时 DuckDB 文件建表并返回 Store 与文件路径。"""
    db_file = tmp_path / "profile.duckdb"
    schema = (_ROOT / "db" / "duckdb_schema.sql").read_text(encoding="utf-8")
    con = duckdb.connect(str(db_file))
    try:
        con.execute(schema)
    finally:
        con.close()
    return DuckDBStore(db_file), db_file


def _count_rows(db_file: Path) -> int:
    """统计 student_feature 行数。"""
    con = duckdb.connect(str(db_file))
    try:
        return int(con.execute("SELECT COUNT(*) FROM student_feature").fetchone()[0])
    finally:
        con.close()


def test_empty_raw_falls_back():
    """空数据兜底：has_data=False，tags 给「数据不足」，各维分为 None。"""
    features = build_features({})
    assert features["has_data"] is False
    assert features["tags"] == ["数据不足"]
    assert make_tags(features) == ["数据不足"]
    assert features["calc_version"] == CALC_VERSION == "v1.0"
    for dim in ("study", "behavior", "interest", "ability"):
        assert features[dim]["score"] is None
        assert features["scores"][dim] is None
    assert features["interest"]["top_direction"] is None


def test_three_tags_are_all_correct():
    """前20% + 算法岗偏好 + 无项目经历 → 三标签全对，四维分落在预期值上。"""
    features = build_features(_FULL_RAW)
    assert features["tags"] == ["专业前20%", "偏好算法岗", "缺乏项目经历"]
    assert features["study"]["score"] == 0.837      # 0.4*0.88+0.2*0.575+0.2*1+0.2*0.85
    assert features["behavior"]["score"] == 0.815   # 0.5*0.95+0.3*0.6+0.2*0.8
    assert features["interest"]["score"] == 0.5967  # 0.4*(4/6)+0.3*0.6+0.3*0.5
    assert features["ability"]["score"] == 0.35     # 0.4*0+0.3*(2/3)+0.3*0.5
    assert features["interest"]["top_direction"] == "算法"


def test_batch_build_is_idempotent(tmp_path):
    """幂等：同一批原始行连跑两次，student_feature 行数不变且可回读。"""
    store, db_file = _tmp_store(tmp_path)
    rows = _rows(3)
    assert batch_build(TENANT, TERM, raw_rows=rows, store=store) == 3
    assert _count_rows(db_file) == 3
    assert batch_build(TENANT, TERM, raw_rows=rows, store=store) == 3
    assert _count_rows(db_file) == 3

    saved = store.read_student_feature("RJ2022001", TERM)
    assert saved is not None
    assert saved["calc_version"] == "v1.0"
    assert saved["tags"] == ["专业前20%", "偏好算法岗", "缺乏项目经历"]
    assert int(saved["library_activity"]) == 60  # 0.60 按百分制写入
    assert float(saved["gpa"]) == 88.0
    assert saved["course_pref"] == {"算法": 3, "前端": 1}
    # 项目数为 1 的另一行应得到「能力履历完整」
    other = store.read_student_feature("RJ2022002", TERM)
    assert other is not None
    assert other["tags"][2] == "能力履历完整"


def test_rank_pct_boundaries():
    """边界值：rank_pct=0 为前20%，=1 为后50%，门槛沿线取值也要正确。"""
    base = {k: v for k, v in _FULL_RAW.items() if k != "rank_pct"}
    assert build_features({**base, "rank_pct": 0.0})["tags"][0] == "专业前20%"
    assert build_features({**base, "rank_pct": 1.0})["tags"][0] == "专业后50%"
    assert build_features({**base, "rank_pct": 0.20})["tags"][0] == "专业前20%"
    assert build_features({**base, "rank_pct": 0.21})["tags"][0] == "专业前50%"
    assert build_features({**base, "rank_pct": 0.50})["tags"][0] == "专业前50%"
    assert build_features({**base, "rank_pct": 0.51})["tags"][0] == "专业后50%"


def test_missing_fields_do_not_fake_zero():
    """缺失项不参与打分（剩余权重归一），不写 0 冒充。"""
    features = build_features({"student_no": "S1", "term": TERM,
                               "attendance_rate": 0.8, "cert_count": 1})
    assert features["has_data"] is True
    assert features["study"]["score"] is None
    assert features["behavior"]["score"] == 0.8  # 仅出勤一项，归一后即其自身
    assert features["tags"] == ["学业数据不足", "方向未明", "能力履历完整"]


def test_normalization_is_clamped_and_deterministic():
    """归一化越界裁剪 + 同输入两次结果完全一致 + 落库行可还原活跃度。"""
    raw = {**_FULL_RAW, "gpa": 120.0, "fail_count": 99, "gpa_trend": -50.0,
           "attendance_rate": 1.5}
    first = build_features(raw)
    second = build_features(raw)
    assert first == second
    assert first["study"]["norm"]["gpa"] == 1.0
    assert first["study"]["norm"]["gpa_trend"] == 0.0
    assert first["study"]["norm"]["fail_count"] == 0.0
    assert first["behavior"]["norm"]["attendance_rate"] == 1.0

    row = to_feature_row(build_features({**_FULL_RAW, "library_activity": 0.42}))
    assert row["library_activity"] == 42
    assert row["term"] == TERM
    assert row["calc_version"] == "v1.0"


def test_direction_tie_and_empty():
    """方向频次合并：浏览折半计入，无数据返回 None。"""
    assert top_direction({"course_pref": {"算法": 2, "数据": 2}}) == "数据"  # 同频按名字升序
    assert top_direction({"job_view_pref": {"算法": 10}}) == "算法"
    assert top_direction({}) is None
    features = build_features({"course_pref": {"算法": 2}})
    assert features["tags"][1] == "偏好算法岗"


def test_unknown_tenant_returns_empty():
    """多租户兜底：取数租户不存在时返回空列表（库不可用时同样为空）。"""
    assert fetch_student_raw(999999, TERM) == []


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
