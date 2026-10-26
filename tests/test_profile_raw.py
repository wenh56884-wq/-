# tests/test_profile_raw.py
# 职责：校验新源表管线（scripts\build_profile_raw.py）的取数、补齐语义与端到端写入
# 依赖：pytest / engine.profile / duckdb / pymysql
# 说明：离线用例对 module 内部的 _query 打桩；需要 MySQL 的用例自动跳过

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import duckdb  # noqa: E402
import pytest  # noqa: E402

from engine.profile import batch_build, build_features  # noqa: E402
from engine.store import DuckDBStore  # noqa: E402

_SCRIPT = _ROOT / "scripts" / "build_profile_raw.py"
_SPEC = importlib.util.spec_from_file_location("build_profile_raw", _SCRIPT)
bpr = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(bpr)

TERM = "2025-2026-2"
TENANT = 1


def _mysql_ok() -> bool:
    """MySQL 是否可连通（不可连通的用例自动跳过）。"""
    try:
        import pymysql

        from app.config import get_settings

        s = get_settings()
        conn = pymysql.connect(
            host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
            password=s.mysql_password, database=s.mysql_db, charset="utf8mb4",
        )
        conn.close()
        return True
    except Exception:
        return False


MYSQL_OK = _mysql_ok()
requires_mysql = pytest.mark.skipif(not MYSQL_OK, reason="MySQL 不可用")


# ----------------------------------------------------------------
# 离线用例：方向词典
# ----------------------------------------------------------------
def test_direction_dictionary_covers_ten():
    """方向词典必须覆盖要求的 10 个方向，且有「其他」兜底。"""
    names = [name for name, _kw in bpr.DIRECTIONS]
    for required in ("数据", "算法", "后端", "前端", "测试", "运维", "金融", "财务", "运营", "产品"):
        assert required in names, f"方向词典缺少 {required}"
    assert len(names) == len(set(names))
    assert bpr.DIRECTION_OTHER == "其他"


@pytest.mark.parametrize(
    "title,expected",
    [
        ("高级算法工程师（机器学习）", "算法"),
        ("数据分析师", "数据"),
        ("Java 后端开发工程师", "后端"),
        ("前端开发工程师（Vue）", "前端"),
        ("测试工程师（QA）", "测试"),
        ("运维工程师 / DevOps", "运维"),
        ("银行柜员", "金融"),
        ("会计专员（核算）", "财务"),
        ("电商运营专员", "运营"),
        ("产品经理助理", "产品"),
        ("司机随车配送员", "物流"),  # 词典 v2026.10 起新增「物流」方向
    ],
)
def test_classify_direction(title, expected):
    """ Title → 方向映射命中预期（含兜底）。"""
    assert bpr.classify_direction(title) == expected


# ----------------------------------------------------------------
# 离线用例：各 loader + 组装语义
# ----------------------------------------------------------------
def test_load_library_returns_raw_counts(monkeypatch):
    """library_visit_cnt 返回原始次数，不在脚本里预归一。"""
    monkeypatch.setattr(bpr, "_query", lambda sql, params: [
        {"student_no": "S1", "visit_cnt": 25},
        {"student_no": "S2", "visit_cnt": 130},
    ])
    assert bpr.load_library(TENANT, TERM) == {"S1": 25, "S2": 130}


def test_consumption_is_clamped(monkeypatch):
    """consumption_regularity = min(1, active_days / 120)，越界裁剪。"""
    monkeypatch.setattr(bpr, "_query", lambda sql, params: [
        {"student_no": "S0", "active_days": 0},
        {"student_no": "S1", "active_days": 60},
        {"student_no": "S2", "active_days": 120},
        {"student_no": "S3", "active_days": 200},
    ])
    assert bpr.load_consumption(TENANT, TERM) == {
        "S0": 0.0, "S1": 0.5, "S2": 1.0, "S3": 1.0,
    }


def test_activity_counts_only_known_types(monkeypatch):
    """cert/contest/project 按类型计数，未知类型忽略、无记录的类型不出现。"""
    monkeypatch.setattr(bpr, "_query", lambda sql, params: [
        {"student_no": "S1", "activity_type": "cert", "cnt": 2},
        {"student_no": "S1", "activity_type": "project", "cnt": 1},
        {"student_no": "S1", "activity_type": "unknown_kind", "cnt": 5},
    ])
    assert bpr.load_activity_counts(TENANT, TERM) == {"S1": {"cert": 2, "project": 1}}


def test_job_view_counts_and_pref(monkeypatch):
    """浏览/收藏计数按 action 分流；job_view_pref 由标题落到方向。"""
    monkeypatch.setattr(bpr, "_query", lambda sql, params: [
        {"student_no": "S1", "action": "view", "cnt": 30},
        {"student_no": "S1", "action": "favorite", "cnt": 4},
    ])
    views, favs = bpr.load_job_view_counts(TENANT, TERM)
    assert (views, favs) == ({"S1": 30}, {"S1": 4})

    monkeypatch.setattr(bpr, "_query", lambda sql, params: [
        {"student_no": "S1", "title": "Java 后端开发"},
        {"student_no": "S1", "title": "Java 后端开发"},
        {"student_no": "S1", "title": "数据分析师"},
        {"student_no": "S1", "title": "司机"},  # 词典 v2026.10 起归「物流」
    ])
    assert bpr.load_job_view_pref(TENANT, TERM) == {"S1": {"后端": 2, "数据": 1, "物流": 1}}


def test_assemble_rows_missing_source_omits_key(monkeypatch):
    """核心语义：整份源表无记录的学生才不写键；有记录但某类型为 0 写真实 0。"""
    # S1 全量数据 / S2 有证书但无项目、无考勤 / S3 新源表一律无记录
    monkeypatch.setattr(bpr, "load_study_base", lambda t, term: [
        {"student_no": s, "name": n, "term": term, "gpa": g, "gpa_trend": tr,
         "fail_count": f, "major_rank_pct": r, "attendance_rate": a}
        for s, n, g, tr, f, r, a in (
            ("S1", "甲", 80.0, 2.0, 0, 0.10, 0.95),
            ("S2", "乙", 70.0, -5.0, 1, 0.50, None),
            ("S3", "丙", 60.0, None, 0, 0.90, 0.90),
        )
    ])
    monkeypatch.setattr(bpr, "load_library", lambda t, term: {"S1": 30})
    monkeypatch.setattr(bpr, "load_consumption", lambda t, term: {"S1": 0.8, "S2": 0.4})
    monkeypatch.setattr(
        bpr, "load_activity_counts",
        lambda t, term: {"S1": {"cert": 2, "contest": 1, "project": 1}, "S2": {"cert": 1}},
    )
    monkeypatch.setattr(
        bpr, "load_job_view_counts", lambda t, term: ({"S1": 40, "S2": 12}, {"S1": 5})
    )
    monkeypatch.setattr(
        bpr, "load_job_view_pref",
        lambda t, term: {"S1": {"算法": 9, "后端": 1}},
    )

    rows = bpr.assemble_rows(TENANT, TERM)
    s1, s2, s3 = rows[0], rows[1], rows[2]

    # 缺失语义：这几类源数据查不到就不写键
    assert s1["library_visit_cnt"] == 30 and "library_visit_cnt" not in s2
    assert s2["attendance_rate"] is None
    assert s1["job_favorite_cnt"] == 5 and "job_favorite_cnt" not in s2
    assert s1["job_view_pref"] == {"算法": 9, "后端": 1} and "job_view_pref" not in s2
    for key in ("cert_count", "contest_count", "project_cnt"):
        assert key not in s3, f"S3 无活动记录却写了 {key}"

    # 有记录但某类型为 0：写真实 0，让「缺乏项目经历」标签出得来
    assert (s2["cert_count"], s2["contest_count"], s2["project_cnt"]) == (1, 0, 0)
    features = build_features(s2)
    assert features["tags"][2] == "缺乏项目经历"
    # 整份无记录 → 缺失，不得冒充 0
    assert build_features(s3)["tags"][2] == "能力数据不足"


def test_feature_coverage_counts_keys_only():
    """覆盖率统计只看键是否存在，不看数值。"""
    rows = [
        {"student_no": "S1", "cert_count": 1},
        {"student_no": "S2"},
    ]
    cov = bpr.feature_coverage(rows)
    assert cov["cert_count"] == 0.5
    assert cov["project_cnt"] == 0.0
    assert bpr.feature_coverage([]) == {k: 0.0 for k in bpr.FEATURE_KEYS}


# ----------------------------------------------------------------
# 需要 MySQL 的用例
# ----------------------------------------------------------------
@pytest.fixture(scope="module")
def real_rows():
    """从真实 MySQL 组装一次，模块内复用。"""
    assert MYSQL_OK, "MySQL 不可用"
    return bpr.assemble_rows(TENANT, TERM)


@requires_mysql
def test_seven_features_coverage_ge_95(real_rows):
    """验收：7 类新特征非空率均 ≥95%。"""
    cov = bpr.feature_coverage(real_rows)
    assert len(real_rows) == 500
    low = {k: v for k, v in cov.items() if v < 0.95}
    assert not low, f"非空率不足的特征：{low}"


@requires_mysql
def test_activity_counts_match_source(real_rows):
    """有活动记录的学生三类都落位（缺某类型写真实 0）；源表查不到的一律不写键。"""
    activity = bpr.load_activity_counts(TENANT, TERM)
    by_no = {r["student_no"]: r for r in real_rows}
    zero_project = 0
    for sno, counts in activity.items():
        row = by_no.get(sno)
        assert row is not None, f"{sno} 有活动记录却未出现在 raw rows 里"
        assert row["cert_count"] == counts.get("cert", 0)
        assert row["contest_count"] == counts.get("contest", 0)
        assert row["project_cnt"] == counts.get("project", 0)
        zero_project += 1 if row["project_cnt"] == 0 else 0
    assert zero_project > 0, "没有缺乏项目经历的学生，能力短板标签出不来"

    for row in real_rows:
        if row["student_no"] not in activity:
            for key in ("cert_count", "contest_count", "project_cnt"):
                assert key not in row, f"{row['student_no']} 无活动记录却被补 {key}"


@requires_mysql
def test_gpa_trend_sign_matches_profile(real_rows):
    """口径自查：本管线 gpa_trend 与 engine/profile.py 取数一致（正数=进步）。"""
    from engine.profile import fetch_student_raw

    base = {r["student_no"]: r for r in fetch_student_raw(TENANT, TERM)}
    checked = 0
    for row in real_rows[:20]:
        other = base.get(row["student_no"])
        if other is None or other.get("gpa_trend") is None:
            continue
        assert abs(row["gpa_trend"] - other["gpa_trend"]) < 0.01
        assert abs(row["gpa"] - other["gpa"]) < 0.01
        checked += 1
    assert checked >= 10


@requires_mysql
def test_gpa_drop_is_negative_of_trend(real_rows):
    """口径字典 §5.1：warning 侧 gpa_drop == -(profile 侧 gpa_trend)。"""
    from engine.warning import compute_student

    for row in real_rows[:5]:
        result = compute_student(TENANT, row["student_no"], TERM)
        assert abs(result["metrics"]["gpa_drop"] + row["gpa_trend"]) < 0.01


@requires_mysql
def test_end_to_end_batch_build_idempotent(real_rows, tmp_path):
    """端到端：写入临时 DuckDB，连跑两次行数不变，且写入的是补齐后的画像。"""
    schema = (_ROOT / "db" / "duckdb_schema.sql").read_text(encoding="utf-8")
    db_file = tmp_path / "profile_raw.duckdb"
    con = duckdb.connect(str(db_file))
    try:
        con.execute(schema)
    finally:
        con.close()

    store = DuckDBStore(db_file)
    subset = real_rows[:60]
    assert batch_build(TENANT, TERM, raw_rows=subset, store=store) == 60
    assert batch_build(TENANT, TERM, raw_rows=subset, store=store) == 60

    con = duckdb.connect(str(db_file))
    try:
        count = con.execute("SELECT COUNT(*) FROM student_feature").fetchone()[0]
        sample_no = subset[0]["student_no"]
        saved_tags = con.execute(
            "SELECT tags FROM student_feature WHERE student_no = ?", (sample_no,)
        ).fetchone()[0]
    finally:
        con.close()
    assert count == 60
    tags = json.loads(saved_tags)
    # 三标签 +（极端退步时追加的）第 4 个「学业急剧下滑」
    assert tags != ["数据不足"]
    assert len(tags) in (3, 4)
    if len(tags) == 4:
        assert tags[3] == "学业急剧下滑"


@requires_mysql
def test_features_dimensions_populated(real_rows):
    """补齐后：行为/兴趣/能力三维不再缺失或不打分。"""
    total = len(real_rows)
    dim_scores = {"behavior": 0, "interest": 0, "ability": 0}
    for row in real_rows:
        features = build_features(row)
        for dim in dim_scores:
            if features[dim]["score"] is not None:
                dim_scores[dim] += 1
    for dim, count in dim_scores.items():
        assert count / total >= 0.95, f"{dim} 维有值比例不足：{count}/{total}"
