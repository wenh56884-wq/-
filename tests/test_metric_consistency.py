# tests/test_metric_consistency.py
# 职责：把 docs\指标口径字典.md v1.1 里两引擎的跨口径契约用测试钉死（缺失不冒充、rank 方向/分组、gpa 符号、存储约定）
# 依赖：engine.profile / engine.warning / engine.rules / pytest；**不连 MySQL、不连 DuckDB**（全部走 metrics= / raw 入参的纯函数）
# 说明：期望值一律以 docs\指标口径字典.md v1.1 为准；当前代码未达标的用例打 xfail(reason="待 P4-3B-x 修复")，修好后自动转 xpass

from __future__ import annotations

import pytest

from engine import profile, warning
from engine.rules import LEVEL_NONE, WarningRules

TERM = "2025-2026-2"
TENANT_ID = 1


# ----------------------------------------------------------------
# 1. gpa 方向契约（字典 §1 第 1.1 条第 1 点）
# ----------------------------------------------------------------
def test_gpa_drop_is_negative_of_gpa_trend():
    """同一份原始数据（上期 82、本期 71）必须满足 gpa_drop == -gpa_trend。

    warning 侧 gpa_drop = 上期 − 本期（正数=下降）；profile 侧 gpa_trend = 本期 − 上期（正数=进步）。
    违背了 docs\指标口径字典.md 第 1 节「1.1 三个最容易搞错的点」第 1 条。
    """
    prev_gpa, cur_gpa = 82.0, 71.0

    # warning 侧：把「上期 − 本期」喂进引擎，经 normalize_metrics 标准化后取出
    warned = warning.compute_student(
        TENANT_ID, "S001", TERM,
        metrics={
            "student_no": "S001", "name": "甲",
            "gpa": cur_gpa,
            "gpa_drop": round(prev_gpa - cur_gpa, 2),
            "fail_count": 0,
            "attendance_rate": 0.95,
        },
        rules=WarningRules.defaults(TENANT_ID),
    )
    # profile 侧：把「本期 − 上期」喂进引擎
    features = profile.build_features({
        "student_no": "S001", "term": TERM,
        "gpa": cur_gpa,
        "gpa_trend": round(cur_gpa - prev_gpa, 2),
    })

    drop = warned["metrics"]["gpa_drop"]
    trend = features["study"]["gpa_trend"]
    assert drop == 11.0, f"warning 侧 gpa_drop 应为 11.0，实际 {drop}；违背字典第 1 节第 1.1 条第 1 点"
    assert trend == -11.0, f"profile 侧 gpa_trend 应为 -11.0，实际 {trend}；违背字典第 1 节第 1.1 条第 1 点"
    assert drop == round(-trend, 2), "两引擎 gpa 符号必须互为相反数；违背字典第 1 节第 1.1 条第 1 点"


# ----------------------------------------------------------------
# 2. rank 方向一致（字典 §1：class_rank_pct / major_rank_pct 行）
# ----------------------------------------------------------------
def test_rank_pct_direction_consistent_between_engines():
    """两个 compute_rank_pct 方向一致：第一名 0.0、末位 1.0，值域 0~1。

    违背了 docs\指标口径字典.md 第 1 节「1.1 三个最容易搞错的点」第 2 点。
    """
    gpa_of = {"S1": 90.0, "S2": 80.0, "S3": 70.0}

    by_class = warning.compute_rank_pct(gpa_of)          # 班级口径
    by_major = profile.compute_rank_pct(gpa_of)          # 专业口径（缺省一组）

    for name, rank in (("warning/班级", by_class), ("profile/专业", by_major)):
        assert all(0.0 <= v <= 1.0 for v in rank.values()), f"{name} 越出 0~1；违背字典第 1 节第 1.1 条第 2 点"
        assert rank["S1"] == 0.0, f"{name} 最高分应为 0.0（第一），实际 {rank['S1']}"
        assert rank["S3"] == 1.0, f"{name} 最低分应为 1.0（末位），实际 {rank['S3']}"
    assert by_class == by_major == {"S1": 0.0, "S2": 0.5, "S3": 1.0}


# ----------------------------------------------------------------
# 3. rank 分组差异是合法的（字典 §1 第 1.1 条第 2 点）
# ----------------------------------------------------------------
def test_class_rank_and_major_rank_are_legally_different():
    """2 个班同属 1 个专业：班级第一 ≠ 专业第一，分组差异不是 bug。

    违背了 docs\指标口径字典.md 第 1 节「1.1 三个最容易搞错的点」第 2 点。
    """
    gpa_of = {"S1": 95.0, "S2": 60.0, "S3": 70.0, "S4": 65.0}
    class_of = {"S1": "AI2401", "S2": "AI2401", "S3": "AI2402", "S4": "AI2402"}
    major_of = {sno: "人工智能" for sno in gpa_of}

    # 班级口径：warning 侧按班级分组逐个班算
    rank_2401 = warning.compute_rank_pct({s: gpa_of[s] for s in ("S1", "S2")})
    rank_2402 = warning.compute_rank_pct({s: gpa_of[s] for s in ("S3", "S4")})
    # 专业口径：profile 侧按 major 分组（4 人同专业 → 一组）
    rank_major = profile.compute_rank_pct(gpa_of, major_of)

    assert class_of["S3"] == "AI2402"
    assert rank_2401["S1"] == 0.0 and rank_2401["S2"] == 1.0
    assert rank_2402["S3"] == 0.0 and rank_2402["S4"] == 1.0       # S3 是 AI2402 班第一
    assert rank_major["S3"] == pytest.approx(1 / 3, abs=1e-4)      # 但专业口径只排第三
    assert all(0.0 <= v <= 1.0 for v in rank_major.values())

    # 两种口径各自都成立，画像标签只能读专业口径
    tag = profile.build_features(
        {"gpa": gpa_of["S3"], "major_rank_pct": rank_major["S3"]})["tags"][0]
    assert tag == "专业前50%", f"S3 专业口径标签应为「专业前50%」，实际 {tag}；违背字典第 1 节第 1.1 条第 2 点"


# ----------------------------------------------------------------
# 4. library_activity 存储约定（字典 §4：DECIMAL(5,4) 存 0-1）
#    P4-3B-1 已还债：student_feature 该列改 DECIMAL(5,4)，不再 ×100
# ----------------------------------------------------------------
def test_library_activity_stored_as_zero_to_one():
    """to_feature_row 写 0.42，读回必须还是 0.42（误差 < 1e-4）。

    违背了 docs\指标口径字典.md 第 4 节「library_activity DECIMAL(5,4)，取消 ×100 折中」。
    """
    features = profile.build_features({
        "student_no": "S004", "term": TERM, "library_activity": 0.42,
    })
    assert features["behavior"]["library_activity"] == pytest.approx(0.42, abs=1e-4)

    row = profile.to_feature_row(features)
    stored = row["library_activity"]
    assert stored is not None, "字典第 4 节：library_activity 必须写入，不得丢弃"
    assert abs(float(stored) - 0.42) < 1e-4, f"落库读回 {stored}，期望 0.42；违背字典第 4 节"


# ----------------------------------------------------------------
# 5. 缺失不冒充（字典 §3.2：coverage / missing / 灰档）
# ----------------------------------------------------------------
@pytest.mark.xfail(
    reason="技术债：normalize_metrics 仍在用 1.0/0.0 填充，待 P4-3B-2",
    strict=False,
)
def test_missing_attendance_reports_coverage_and_no_green_level():
    """缺出勤时：coverage==2、missing==["attendance_rate"]、level 不得是正常档。

    违背了 docs\指标口径字典.md 第 3 节「3.2 预警引擎（v1.1 必须改，当前在冒充）」第 1~3 条。
    """
    result = warning.compute_student(
        TENANT_ID, "S005", TERM,
        metrics={
            "student_no": "S005", "name": "戊",
            "gpa": 68.0, "gpa_drop": 12.0, "fail_count": 2,
            # attendance_rate 故意缺失：不得按全勤 1.0 处理
        },
        rules=WarningRules.defaults(TENANT_ID),
    )

    assert result.get("coverage") == 2, f"可用指标应为 2，实际 {result.get('coverage')}；违背字典第 3 节第 3.2 条第 1 条"
    assert result.get("missing") == ["attendance_rate"], (
        f"缺失清单应为 ['attendance_rate']，实际 {result.get('missing')}；违背字典第 3 节第 3.2 条第 1 条"
    )
    assert result.get("level") != LEVEL_NONE, (
        f"缺数据不得标为正常档，实际 {result.get('level')}；违背字典第 3 节第 3.2 条第 3 条"
    )


# ----------------------------------------------------------------
# 6. 极端退步（字典 §2：TREND_MIN=-40 + extreme_decline 标签）
#    P4-3B-1 已还债：TREND_MIN 放宽到 -40 并输出 extreme_decline
# ----------------------------------------------------------------
def test_extreme_decline_is_flagged_and_tagged():
    """gpa_trend=-35 时 study["extreme_decline"] is True，且标签含「学业急剧下滑」。

    违背了 docs\指标口径字典.md 第 2 节末「极端值不静默裁剪」与第 4 节 extreme_decline 列。
    """
    assert profile.TREND_MIN == -40.0, f"TREND_MIN 应为 -40，实际 {profile.TREND_MIN}；违背字典第 2 节 TREND_MIN 行"

    features = profile.build_features({
        "student_no": "S006", "term": TERM,
        "gpa": 45.0, "gpa_trend": -35.0, "fail_count": 3, "major_rank_pct": 0.9,
    })
    assert features["study"].get("extreme_decline") is True, (
        f"extreme_decline 应为 True，实际 {features['study'].get('extreme_decline')}；违背字典第 2 节"
    )
    assert "学业急剧下滑" in (features.get("tags") or []), (
        f"标签应含「学业急剧下滑」，实际 {features.get('tags')}；违背字典第 2 节"
    )


# ----------------------------------------------------------------
# 7. rank 拆列（字典 §4：class_rank_pct / major_rank_pct 分列存储，不许共用一个 rank_pct）
#    P4-3B-1 已还债：student_feature 两口径各占一列
# ----------------------------------------------------------------
def test_feature_row_has_split_rank_columns():
    """落库行必须同时给出专业口径与班级口径两列。

    违背了 docs\\指标口径字典.md 第 4 节「class_rank_pct 新增，major_rank_pct 由 profile 写入」。
    """
    row = profile.to_feature_row(
        profile.build_features({"gpa": 80.0, "major_rank_pct": 0.3, "class_rank_pct": 0.1}))

    assert "major_rank_pct" in row, f"缺 major_rank_pct，现有列：{sorted(row)}；违背字典第 4 节"
    assert "class_rank_pct" in row, f"缺 class_rank_pct，现有列：{sorted(row)}；违背字典第 4 节"
    assert row["major_rank_pct"] == pytest.approx(0.3, abs=1e-4)


# ----------------------------------------------------------------
# 8. course_pref 真的被装配（字典 §1：兴趣方向不能只靠浏览记录）
#    P4-3B-1 已还债：load_course_pref 查 elective_selection 并写进 raw rows
# ----------------------------------------------------------------
def test_course_pref_is_assembled_by_build_script():
    """管线必须真的去查选修方向；函数支持不算完成。

    违背了 docs\\指标口径字典.md 第 1 节「course_pref 由 elective_selection 按 direction 聚合」。
    """
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "scripts" / "build_profile_raw.py").read_text(
        encoding="utf-8"
    )
    assert "course_pref" in src, "build_profile_raw.py 未装配 course_pref；违背字典第 1 节"
    assert "elective_selection" in src, "未从 elective_selection 取选修方向；违背字典第 1 节"
