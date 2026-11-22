# tests/test_teacher_career.py
# 职责：engine/teacher_career.py 的离线单测（不连库、不调模型）。
#
# 重点验证铁律 1：班级级数值（人数/比例/均分/名次/定级）全部由引擎确定性计算，
# 同输入两次结果一致；intent 过滤只动 students、不动 class_summary；缺数据如实兜底。

from __future__ import annotations

from engine import teacher_career as tc


def _student(no: str, *, gpa=None, intent=None, level="none",
             forecast_available=True, job_id=None, job_score=None) -> dict:
    """造一条全域事实字典（仅填引擎聚合所需的最小字段，其余子结果留空）。"""
    rec = {
        "student_no": no, "name": f"学生{no}", "grade": "大三",
        "intent": intent, "direction": "专业对口岗位", "major": "数据科学",
        "gpa": gpa,
        "grades": {"engine_version": "grades-v1", "summary": {}},
        "warning": {"student_no": no, "level": level, "risk_score": 0},
        "forecast": {"available": forecast_available},
        "recommendations": {"items": []},
        "interview": {}, "competitions": {}, "assessment": {},
        "elective": {}, "exam": [], "kg": {},
    }
    if job_id is not None:
        rec["recommendations"] = {"items": [{
            "job_id": job_id, "title": f"岗位{job_id}", "company": "某公司",
            "city": "重庆", "final_score": job_score,
        }]}
    return rec


# ---------------------------------------------------------------- 确定性


def test_determinism_same_input_same_numbers():
    students = [
        _student("A1", gpa=88.0, intent="就业", level="yellow", job_id=1, job_score=82),
        _student("A2", gpa=76.5, intent="考公", level="none", job_id=2, job_score=70),
        _student("A3", gpa=92.0, intent="就业", level="red"),
    ]
    kw = dict(tenant_id=1, class_name="AI2201", term="2025-2026-1", intent=None,
              students=students)
    r1 = tc.build_class_career_report(**kw)
    r2 = tc.build_class_career_report(**kw)
    assert r1["class_summary"] == r2["class_summary"]
    assert r1["students"] == r2["students"]


# ---------------------------------------------------------------- intent 过滤


def test_intent_filter_only_affects_students():
    students = [
        _student("A1", intent="就业"),
        _student("A2", intent="考公"),
        _student("A3", intent="就业"),
    ]
    r = tc.build_class_career_report(
        tenant_id=1, class_name="AI2201", term="2025-2026-1",
        intent="就业", students=students)
    # class_summary 始终全班
    assert r["class_summary"]["student_total"] == 3
    assert r["student_total"] == 3
    # students 只含就业
    assert r["filtered_total"] == 2
    assert all(s["intent"] == "就业" for s in r["students"])
    assert [s["student_no"] for s in r["students"]] == ["A1", "A3"]


def test_intent_none_keeps_all_students():
    students = [_student("A1", intent="就业"), _student("A2", intent="考公")]
    r = tc.build_class_career_report(
        tenant_id=1, class_name="AI2201", term="2025-2026-1",
        intent=None, students=students)
    assert r["filtered_total"] == 2
    assert r["intent"] is None


def test_intent_distribution_counts_all():
    students = [
        _student("A1", intent="就业"),
        _student("A2", intent="就业"),
        _student("A3", intent="考公"),
        _student("A4", intent=None),
    ]
    r = tc.build_class_career_report(
        tenant_id=1, class_name="AI2201", term="2025-2026-1",
        intent=None, students=students)
    dist = r["class_summary"]["intent_distribution"]
    assert dist["就业"] == 2
    assert dist["考公"] == 1
    assert dist["考研"] == 0
    assert dist["考编"] == 0
    assert dist["未选"] == 1


# ---------------------------------------------------------------- 缺数据兜底


def test_missing_sub_results_no_error():
    """缺测评/选课/预测/岗位等子结果时不报错，如实留空或 None。"""
    students = [_student("A1", gpa=None, intent=None, forecast_available=False)]
    r = tc.build_class_career_report(
        tenant_id=1, class_name="AI2201", term="2025-2026-1",
        intent=None, students=students)
    s = r["class_summary"]
    assert s["avg_grade"] is None            # 无成绩不补 0
    assert s["warning_count"] == 0          # 无预警数据不算预警
    assert s["grade_rank_top"] == []        # 无成绩不进排名
    assert s["job_match_top"] == []
    # 预测缺口率 1.0（≥0.6）→ 数据不足也计入风险，定级「高」
    assert s["risk_level"] == "高"


def test_empty_class_returns_zero_summary():
    r = tc.build_class_career_report(
        tenant_id=1, class_name="AI2201", term="2025-2026-1",
        intent=None, students=[])
    s = r["class_summary"]
    assert s["student_total"] == 0
    assert s["warning_rate"] == 0.0
    assert s["avg_grade"] is None
    assert s["risk_level"] == "unknown"
    assert r["students"] == []


# ---------------------------------------------------------------- 排名并列


def test_grade_rank_ties_share_rank_and_skip():
    """同分并列同名次，并列后跳号（与 engine.grades 同口径）。"""
    students = [
        _student("A1", gpa=90.0),
        _student("A2", gpa=85.0),
        _student("A3", gpa=85.0),   # 与 A2 并列
        _student("A4", gpa=80.0),
    ]
    r = tc.build_class_career_report(
        tenant_id=1, class_name="AI2201", term="2025-2026-1",
        intent=None, students=students)
    top = r["class_summary"]["grade_rank_top"]
    ranks = {s["student_no"]: s["rank"] for s in top}
    assert ranks["A1"] == 1
    assert ranks["A2"] == 2
    assert ranks["A3"] == 2          # 并列第 2
    assert ranks["A4"] == 4          # 跳号到第 4


# ---------------------------------------------------------------- 岗位匹配聚合


def test_job_match_top_dedup_and_sort():
    """同一岗位被多生推荐保留最高分并累计推荐人数；按分数降序。"""
    students = [
        _student("A1", job_id=1, job_score=80),
        _student("A2", job_id=1, job_score=85),   # 同岗位更高分
        _student("A3", job_id=2, job_score=90),
    ]
    r = tc.build_class_career_report(
        tenant_id=1, class_name="AI2201", term="2025-2026-1",
        intent=None, students=students)
    top = r["class_summary"]["job_match_top"]
    assert top[0]["job_id"] == 2 and top[0]["final_score"] == 90.0
    job1 = next(x for x in top if x["job_id"] == 1)
    assert job1["final_score"] == 85.0          # 取最高分
    assert job1["recommended_by"] == 2          # 两人推荐


# ---------------------------------------------------------------- 风险定级


def test_risk_level_thresholds():
    def lvl(students):
        return tc.build_class_career_report(
            tenant_id=1, class_name="C", term="t", intent=None,
            students=students)["class_summary"]["risk_level"]

    low = [_student(f"S{i}", level="none", forecast_available=True) for i in range(5)]
    assert lvl(low) == "低"

    mid = [_student(f"S{i}", level="yellow" if i < 2 else "none",
                    forecast_available=True) for i in range(5)]  # 预警率 0.4 → 高
    assert lvl(mid) == "高"

    mid2 = [_student(f"S{i}", level="yellow" if i < 1 else "none",
                     forecast_available=True) for i in range(5)]  # 预警率 0.2 → 中
    assert lvl(mid2) == "中"
