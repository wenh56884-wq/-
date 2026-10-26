# tests/test_metric_consistency.py
# 职责：把 docs\指标口径字典.md v1.1 的跨引擎契约用测试钉死。
#       **本文件是纯新增，不改任何引擎代码。**
#
# === 债务看板（xfail = 当前代码还不符，修好后应删除 xfail 标记）===
#   [ ] 1. TREND_MIN 仍是 -20（字典要求 -40）        → P4-3B-1
#   [ ] 2. student_feature 未拆 major_rank_pct        → P4-3B-1
#   [ ] 3. library_activity 仍按 ×100 存整数          → P4-3B-1
#   [ ] 4. 缺 extreme_decline 标签                    → P4-3B-1
#   [ ] 5. warning 缺 attendance 时按全勤 1.0 冒充     → P4-3B-2
#   [ ] 6. course_pref 无源表，永远为 None            → 补 elective_selection
#
# 运行：.venv\Scripts\python.exe -m pytest tests\test_metric_consistency.py -v
# 期望：4 passed + 5 xfailed（债务未还时）；债务还清后应为 9 passed。

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine import profile, warning
from engine.rules import WarningRules

ROOT = Path(__file__).resolve().parents[1]


# ============================================================
# 一、已达成一致的契约（这些必须一直是 pass）
# ============================================================
def test_gpa_direction_opposite_between_engines():
    """§2.1：warning.gpa_drop 与 profile 的 gpa_trend 互为相反数。

    warning 侧：gpa_drop = 上期 − 本期（正数 = 下降，风险）
    profile 侧：gpa_trend = 本期 − 上期（正数 = 进步）
    两者用同一份两学期数据时必须互为相反数，否则一旦同写一张表就互相打脸。
    """
    prev_gpa, cur_gpa = 82.0, 71.0

    gpa_drop = round(prev_gpa - cur_gpa, 2)   # warning 侧口径
    gpa_trend = round(cur_gpa - prev_gpa, 2)  # profile 侧口径

    assert gpa_drop == 11.0
    assert gpa_trend == -11.0
    assert gpa_drop == round(-gpa_trend, 2)

    # 落到函数上：下滑 11 分必须被判为风险项（得分 > 0）
    rules = WarningRules.defaults(0)
    assert rules.gpa_drop.score(gpa_drop) > 0
    # 同一份数据在画像侧必须表现为"退步"（归一值 < 0.5 中点）
    feat = profile.build_features({"gpa": cur_gpa, "gpa_trend": gpa_trend})
    assert feat["study"]["norm"]["gpa_trend"] < 0.5


def test_rank_pct_same_direction_both_engines():
    """§4：两个 compute_rank_pct 方向一致（0 = 第一，1 = 末位）。"""
    gpa = {"A": 90.0, "B": 80.0, "C": 70.0}
    prof = profile.compute_rank_pct(gpa)
    warn = warning.compute_rank_pct(gpa)

    assert prof == warn == {"A": 0.0, "B": 0.5, "C": 1.0}
    assert all(0.0 <= v <= 1.0 for v in prof.values())


def test_rank_pct_grouping_is_legal_difference():
    """§4：班级口径与专业口径可以不同 —— 这是分组差异，不是 bug。"""
    gpa = {"A": 90.0, "B": 80.0, "C": 70.0, "D": 60.0}
    group = {"A": "1班", "B": "1班", "C": "2班", "D": "2班"}
    by_class = profile.compute_rank_pct(gpa, group)

    assert by_class["A"] == 0.0 and by_class["B"] == 1.0  # 1 班内：A 第一
    assert by_class["C"] == 0.0 and by_class["D"] == 1.0  # 2 班内：C 第一
    # C 在班里第一，但在全体里是第三 —— 两种口径都合法
    assert profile.compute_rank_pct(gpa)["C"] == pytest.approx(0.6667, abs=1e-3)


def test_library_activity_current_storage_contract():
    """§3：当前约定 —— 存百分制整数，回读 /100 还原 0-1（P4-3B-1 会改列类型）。"""
    feat = profile.build_features({"library_visit_cnt": 42})
    norm = feat["behavior"]["norm"]["library_activity"]
    assert norm is not None

    row = profile.to_feature_row(feat)
    assert isinstance(row["library_activity"], int)
    assert row["library_activity"] == int(round(norm * 100))
    # 回读还原
    assert abs(row["library_activity"] / 100 - norm) < 1e-6


# ============================================================
# 二、待还的债（xfail：修好后删掉标记，它们会自然变 pass）
# ============================================================
@pytest.mark.xfail(
    reason="债务1：TREND_MIN=-20，-28.91 与 -20 都被压成 0，无法区分「明显退步」与「极端退步」；P4-3B-1 改 -40",
    strict=False,
)
def test_trend_extreme_decline_not_clamped_to_zero():
    """§3：-28.91 与 -20 必须能区分开（前者归一值应更低）。

    当前两者都 clamp 到 -20 → norm 都是 0.0，等于"看不出更严重"。
    """
    norm_extreme = profile.build_features({"gpa_trend": -28.91})["study"]["norm"]["gpa_trend"]
    norm_mild = profile.build_features({"gpa_trend": -20.0})["study"]["norm"]["gpa_trend"]
    assert norm_extreme < norm_mild, f"无法区分：-28.91→{norm_extreme}，-20→{norm_mild}"


@pytest.mark.xfail(
    reason="债务2：student_feature 只有 rank_pct，未拆 major_rank_pct/class_rank_pct；P4-3B-1 拆列",
    strict=False,
)
def test_feature_row_has_split_rank_columns():
    """§4：班级口径与专业口径必须分列存储，不能共用一个 rank_pct。"""
    row = profile.to_feature_row(profile.build_features({"gpa": 80.0, "rank_pct": 0.3}))
    assert "major_rank_pct" in row
    assert "class_rank_pct" in row


@pytest.mark.xfail(
    reason="债务3：library_activity 列在 DuckDB 是 INTEGER，无法存 0-1；P4-3B-1 改 DECIMAL(5,4)",
    strict=False,
)
def test_library_activity_column_accepts_decimal():
    """§3：列类型必须是 DECIMAL(5,4)，让 0.42 原样入库，不再靠 ×100 折中。"""
    sql = (ROOT / "db" / "duckdb_schema.sql").read_text(encoding="utf-8")
    assert "library_activity" in sql
    # 取出 library_activity 那一行，断言类型不是 INTEGER
    line = next(ln for ln in sql.splitlines() if "library_activity" in ln)
    assert "INTEGER" not in line.upper(), f"仍是整数列：{line.strip()}"


@pytest.mark.xfail(
    reason="债务4：make_tags 未产出 extreme_decline；P4-3B-1 补标签",
    strict=False,
)
def test_extreme_decline_tag_exists():
    """§3：极端退步（trend ≤ -25）应能打出标签，供教师端筛选。"""
    feat = profile.build_features({"gpa": 60.0, "gpa_trend": -35.0, "fail_count": 2})
    tags = " ".join(feat.get("tags") or [])
    assert "extreme_decline" in tags or "大幅退步" in tags, f"tags={feat.get('tags')}"


@pytest.mark.xfail(
    reason="债务5：normalize_metrics 缺 attendance 时取 1.0（按全勤），风险被系统性低估；P4-3B-2 修",
    strict=False,
)
def test_missing_attendance_not_filled_as_full():
    """§3：缺考勤必须记 None/unknown，绝不能冒充「全勤」。"""
    m = warning.normalize_metrics({"fail_count": 2, "gpa": 75.0, "gpa_drop": 8.0})
    assert m["attendance_rate"] is None, f"缺考勤被填成 {m['attendance_rate']}"


@pytest.mark.xfail(
    reason="债务6：MySQL 无选修方向源表，build_profile_raw 也没装配 course_pref；补 elective_selection + seed 后转 pass",
    strict=False,
)
def test_course_pref_is_assembled_by_build_script():
    """§1：管线必须真的去查选修方向 —— 不是函数支持就算完成。

    这里检查装配脚本是否包含 course_pref 的取数与赋值逻辑；
    有源表、有装配、跑出非空值，才算这条债还清。
    """
    src = (ROOT / "scripts" / "build_profile_raw.py").read_text(encoding="utf-8")
    assert "course_pref" in src, "build_profile_raw.py 未装配 course_pref"
    assert "elective_selection" in src, "未从 elective_selection 取选修数据"


# ============================================================
# 三、技术债可视化（不做断言，只输出当前债务清单）
# ============================================================
def test_debt_report(capsys):
    """把当前口径与技术债打印出来，方便每天收尾时看一眼进度。"""
    report = {
        "calc_version": profile.CALC_VERSION,
        "warning_engine": warning.ENGINE_VERSION,
        "TREND_MIN": profile.TREND_MIN,
        "TREND_MAX": profile.TREND_MAX,
        "library_activity_column": "INTEGER",
        "rank_columns": ["rank_pct"],
        "metric_dict": "docs/指标口径字典.md v1.1",
    }
    print("\n=== 口径现状 ===")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    assert report["TREND_MIN"] == -20.0 or report["TREND_MIN"] == -40.0
