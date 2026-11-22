# tests/test_campus_insight.py
# 职责：engine/campus_insight.py 的离线单测（不连库、不调模型）。
# 重点验证铁律 1：个人/班级数值全部由引擎确定性计算，同输入两次结果一致；
# 缺键/None/空输入一律兜底不抛异常；排序与 low_engagement 规则逐条断言。

from __future__ import annotations

from engine import campus_insight as ci
from engine import profile


def _insight(**overrides) -> dict:
    """造一次个人画像调用：默认全空输入，按需覆盖单个域。"""
    kw = dict(
        student_no="S1", name="张三", class_name="AI2201", term="2025-2026-1",
        library=[], consumption=[], activity_counts=[], activity_recent=[],
        attendance=[], job_view_counts=[], job_top_cities=[], job_top_industries=[],
        extra=None, snapshots=[],
    )
    kw.update(overrides)
    return ci.build_student_insight(**kw)


def _class(students: list[dict]) -> dict:
    return ci.build_class_insight(
        tenant_id=1, class_name="AI2201", term="2025-2026-1", students=students)


# ---------------------------------------------------------------- 确定性


def test_determinism_same_input_same_output():
    kw = dict(
        student_no="S1", name="张三", class_name="AI2201", term="2025-2026-1",
        library=[{"term": "2025-2026-1", "visits": 9, "borrows": 3},
                 {"term": "2024-2025-2", "visits": 4, "borrows": 1}],
        consumption=[{"term": "2025-2026-1", "count": 80, "active_days": 50,
                      "daily_avg": 12.5}],
        activity_counts=[{"term": "2025-2026-1", "type": "cert", "cnt": 2},
                         {"term": "2024-2025-2", "type": "contest", "cnt": 1}],
        activity_recent=[{"name": "软考", "type": "cert", "level": "国家级",
                          "date": "2025-11-01"}],
        attendance=[{"term": "2025-2026-1", "expected": 100, "absent": 5,
                     "rate": 0.95}],
        job_view_counts=[{"term": "2025-2026-1", "action": "view", "cnt": 6},
                         {"term": "2025-2026-1", "action": "favorite", "cnt": 2}],
        job_top_cities=[{"city": "重庆", "cnt": 5}, {"city": "北京", "cnt": 5}],
        job_top_industries=[{"industry": "互联网", "cnt": 4}],
        extra={"cet4": 520, "cet6": None, "politics": "群众",
               "target_city": "重庆", "weekly_hours": 12.5},
        snapshots=[{"year": 2025, "week": 12, "overall": "B", "summary": "平稳"},
                   {"year": 2025, "week": 10, "overall": "A", "summary": "上升"}],
    )
    r1 = ci.build_student_insight(**kw)
    r2 = ci.build_student_insight(**kw)
    assert r1 == r2
    c1 = _class([r1, r2])
    c2 = _class([r1, r2])
    assert c1 == c2


# ---------------------------------------------------------------- 全空输入


def test_all_empty_inputs():
    r = _insight()
    assert r["engine_version"] == ci.CAMPUS_INSIGHT_ENGINE_VERSION
    assert r["calc_version"] == profile.CALC_VERSION
    assert r["note"] == "暂无校园行为数据"
    assert r["study_style"] == {"label": "暂无数据", "score": 0.0}
    assert r["library"] == {"terms": [], "total_visits": 0, "total_borrows": 0,
                            "latest": None, "trend": "flat"}
    assert r["consumption"] == {"terms": [], "latest": None, "regularity": 0.0}
    assert r["activities"] == {"by_type": {"cert": 0, "contest": 0, "project": 0},
                               "by_term": [], "recent": [], "total": 0}
    assert r["attendance"] == {"terms": [], "latest_rate": None, "avg_rate": None}
    assert r["job_interest"] == {"views_total": 0, "favorites_total": 0,
                                 "by_term": [], "top_cities": [],
                                 "top_industries": []}
    assert r["extra"] is None
    assert r["snapshots"] == []


def test_none_inputs_equal_empty():
    fields = ("library", "consumption", "activity_counts", "activity_recent",
              "attendance", "job_view_counts", "job_top_cities",
              "job_top_industries", "snapshots")
    assert _insight(**{k: None for k in fields}) == _insight()


# ---------------------------------------------------------------- 图书馆 trend


def test_library_trend_up_down_flat():
    t1, t2 = "2024-2025-1", "2024-2025-2"
    up = _insight(library=[{"term": t1, "visits": 3, "borrows": 1},
                           {"term": t2, "visits": 8, "borrows": 2}])
    assert up["library"]["trend"] == "up"
    assert up["library"]["total_visits"] == 11
    assert up["library"]["total_borrows"] == 3
    assert up["library"]["latest"] == {"term": t2, "visits": 8, "borrows": 2}
    down = _insight(library=[{"term": t1, "visits": 8, "borrows": 0},
                             {"term": t2, "visits": 3, "borrows": 0}])
    assert down["library"]["trend"] == "down"
    flat = _insight(library=[{"term": t1, "visits": 5, "borrows": 0},
                             {"term": t2, "visits": 5, "borrows": 0}])
    assert flat["library"]["trend"] == "flat"
    single = _insight(library=[{"term": t1, "visits": 9, "borrows": 0}])
    assert single["library"]["trend"] == "flat"
    assert _insight()["library"]["trend"] == "flat"


def test_library_terms_sorted_ascending():
    r = _insight(library=[{"term": "2025-2026-1", "visits": 9, "borrows": 0},
                          {"term": "2024-2025-2", "visits": 4, "borrows": 0},
                          {"term": "2024-2025-1", "visits": 1, "borrows": 0}])
    assert [t["term"] for t in r["library"]["terms"]] == [
        "2024-2025-1", "2024-2025-2", "2025-2026-1"]
    assert r["library"]["trend"] == "up"      # 排序后比较最后两学期 4→9


# ---------------------------------------------------------------- 消费规律性


def test_regularity_cap_and_rounding():
    capped = _insight(consumption=[{"term": "2025-2026-1", "count": 300,
                                    "active_days": 200, "daily_avg": 15.0}])
    assert capped["consumption"]["regularity"] == 1.0
    rounded = _insight(consumption=[{"term": "2025-2026-1", "count": 60,
                                     "active_days": 50, "daily_avg": None}])
    assert rounded["consumption"]["regularity"] == 0.4167   # 50/120 round 4
    assert rounded["consumption"]["latest"]["active_days"] == 50


# ---------------------------------------------------------------- 排序确定性


def test_top_cities_tie_sorted_by_name_and_capped():
    r = _insight(job_top_cities=[{"city": "重庆", "cnt": 5},
                                 {"city": "北京", "cnt": 5},
                                 {"city": "上海", "cnt": 9}])
    assert r["job_interest"]["top_cities"] == [
        {"city": "上海", "cnt": 9}, {"city": "北京", "cnt": 5},
        {"city": "重庆", "cnt": 5}]
    many = [{"city": f"C{i:02d}", "cnt": i} for i in range(10)]
    capped = _insight(job_top_cities=many)
    assert len(capped["job_interest"]["top_cities"]) == 8
    assert capped["job_interest"]["top_cities"][0] == {"city": "C09", "cnt": 9}


def test_top_industries_tie_sorted_by_name():
    r = _insight(job_top_industries=[{"industry": "制造业", "cnt": 4},
                                     {"industry": "互联网", "cnt": 4}])
    assert r["job_interest"]["top_industries"] == [
        {"industry": "互联网", "cnt": 4}, {"industry": "制造业", "cnt": 4}]


def test_snapshots_sorted_and_capped():
    snaps = [{"year": 2025, "week": w, "overall": None, "summary": None}
             for w in range(10, 0, -1)]
    r = _insight(snapshots=snaps)
    assert len(r["snapshots"]) == 8
    assert [s["week"] for s in r["snapshots"]] == list(range(1, 9))


def test_recent_capped_and_extra_passthrough():
    recent = [{"name": f"活动{i}", "type": "cert", "level": None, "date": None}
              for i in range(12)]
    extra = {"cet4": 520, "cet6": None, "politics": "群众",
             "target_city": "重庆", "weekly_hours": 12.5}
    r = _insight(activity_recent=recent, extra=extra)
    assert len(r["activities"]["recent"]) == 10
    assert r["activities"]["recent"] == recent[:10]
    assert r["extra"] == extra
    assert r["note"] == ""


# ---------------------------------------------------------------- 分学期聚合


def test_activities_and_jobs_by_term():
    r = _insight(
        activity_counts=[{"term": "2025-2026-1", "type": "cert", "cnt": 2},
                         {"term": "2024-2025-2", "type": "contest", "cnt": 1},
                         {"term": "2025-2026-1", "type": "project", "cnt": 1},
                         {"term": "2025-2026-1", "type": "cert", "cnt": 1}],
        job_view_counts=[{"term": "2025-2026-1", "action": "view", "cnt": 4},
                         {"term": "2024-2025-2", "action": "favorite", "cnt": 2},
                         {"term": "2025-2026-1", "action": "favorite", "cnt": 1}])
    assert r["activities"]["by_type"] == {"cert": 3, "contest": 1, "project": 1}
    assert r["activities"]["total"] == 5
    assert r["activities"]["by_term"] == [
        {"term": "2024-2025-2", "cert": 0, "contest": 1, "project": 0},
        {"term": "2025-2026-1", "cert": 3, "contest": 0, "project": 1}]
    jobs = r["job_interest"]
    assert jobs["views_total"] == 4
    assert jobs["favorites_total"] == 3
    assert jobs["by_term"] == [
        {"term": "2024-2025-2", "views": 0, "favorites": 2},
        {"term": "2025-2026-1", "views": 4, "favorites": 1}]


def test_attendance_avg_and_latest():
    r = _insight(attendance=[
        {"term": "2025-2026-1", "expected": 100, "absent": 5, "rate": 0.95},
        {"term": "2024-2025-2", "expected": 100, "absent": 20, "rate": 0.8},
        {"term": "2024-2025-1", "expected": 100, "absent": 10, "rate": 0.9}])
    assert r["attendance"]["latest_rate"] == 0.95
    assert r["attendance"]["avg_rate"] == 0.8833   # (0.95+0.8+0.9)/3 round 4
    assert [t["term"] for t in r["attendance"]["terms"]] == [
        "2024-2025-1", "2024-2025-2", "2025-2026-1"]


# ---------------------------------------------------------------- study_style


def test_study_style_thresholds():
    high = _insight(library=[{"term": "t", "visits": 30}],
                    attendance=[{"term": "t", "rate": 1.0}],
                    consumption=[{"term": "t", "active_days": 120}])
    assert high["study_style"] == {"label": "高投入型", "score": 1.0}
    saturated = _insight(library=[{"term": "t", "visits": 60}],
                         attendance=[{"term": "t", "rate": 1.0}],
                         consumption=[{"term": "t", "active_days": 120}])
    assert saturated["study_style"]["score"] == 1.0   # visits 饱和于 30
    steady = _insight(library=[{"term": "t", "visits": 30}])
    assert steady["study_style"] == {"label": "稳健型", "score": 0.4}
    pending = _insight(attendance=[{"term": "t", "rate": 0.5}])
    assert pending["study_style"] == {"label": "待激活", "score": 0.15}
    assert _insight()["study_style"] == {"label": "暂无数据", "score": 0.0}


# ---------------------------------------------------------------- 缺键/None 兜底


def test_missing_and_none_values_fallback():
    r = _insight(library=[{"term": "2025-2026-1"}],
                 consumption=[{"term": "2025-2026-1", "active_days": None}],
                 activity_counts=[{"term": "2025-2026-1", "type": "cert",
                                   "cnt": None}],
                 attendance=[{"term": "2025-2026-1", "rate": None}],
                 job_view_counts=[{"term": "2025-2026-1", "action": "view"}],
                 job_top_cities=[{"city": "重庆"}],
                 snapshots=[{"summary": "x"}])
    assert r["library"]["total_visits"] == 0
    assert r["library"]["total_borrows"] == 0
    assert r["consumption"]["regularity"] == 0.0
    assert r["activities"]["by_type"]["cert"] == 0
    assert r["activities"]["total"] == 0
    assert r["attendance"]["latest_rate"] is None
    assert r["attendance"]["avg_rate"] is None
    assert r["job_interest"]["views_total"] == 0
    assert r["job_interest"]["top_cities"] == [{"city": "重庆", "cnt": 0}]
    assert r["snapshots"] == [{"summary": "x"}]
    assert r["study_style"] == {"label": "暂无数据", "score": 0.0}
    assert r["note"] == ""                     # 有行即视为有数据域


# ---------------------------------------------------------------- 班级聚合


def _low_student() -> dict:
    """出勤 0.75 / 到馆 0 / regularity 0.2 / 无活动 → 命中全部 4 条 reasons。"""
    return _insight(
        student_no="S1", name="低投入",
        library=[{"term": "2025-2026-1", "visits": 0, "borrows": 0}],
        consumption=[{"term": "2025-2026-1", "count": 30, "active_days": 24,
                      "daily_avg": 10.0}],
        attendance=[{"term": "2025-2026-1", "expected": 100, "absent": 25,
                     "rate": 0.75}],
        job_view_counts=[{"term": "2025-2026-1", "action": "view", "cnt": 3},
                         {"term": "2025-2026-1", "action": "favorite", "cnt": 1}],
        job_top_cities=[{"city": "重庆", "cnt": 2}])


def _high_student() -> dict:
    return _insight(
        student_no="S2", name="高投入",
        library=[{"term": "2025-2026-1", "visits": 30, "borrows": 4}],
        consumption=[{"term": "2025-2026-1", "count": 150, "active_days": 120,
                      "daily_avg": 18.0}],
        activity_counts=[{"term": "2025-2026-1", "type": "cert", "cnt": 2},
                         {"term": "2025-2026-1", "type": "contest", "cnt": 1}],
        attendance=[{"term": "2025-2026-1", "expected": 100, "absent": 5,
                     "rate": 0.95}],
        job_view_counts=[{"term": "2025-2026-1", "action": "view", "cnt": 10},
                         {"term": "2025-2026-1", "action": "favorite", "cnt": 2}],
        job_top_cities=[{"city": "重庆", "cnt": 3}, {"city": "北京", "cnt": 5}])


def test_class_aggregation_numbers():
    s1, s2 = _low_student(), _high_student()
    assert s1["study_style"] == {"label": "待激活", "score": 0.285}
    assert s2["study_style"] == {"label": "高投入型", "score": 0.985}
    r = _class([s2, s1])                       # 乱序传入
    assert r["note"] == ""
    assert r["student_total"] == 2
    assert [s["student_no"] for s in r["students"]] == ["S1", "S2"]
    assert r["students"][0] == s1              # 原样透传
    assert r["students"][1] == s2
    cs = r["class_summary"]
    assert cs["student_total"] == 2
    assert cs["avg_library_visits"] == 15.0    # (0+30)/2
    assert cs["avg_borrows"] == 2.0            # (0+4)/2
    assert cs["avg_attendance_rate"] == 0.85   # (0.75+0.95)/2
    assert cs["avg_regularity"] == 0.6         # (0.2+1.0)/2
    assert cs["activity_counts"] == {"cert": 2, "contest": 1, "project": 0}
    assert cs["activity_coverage_rate"] == 0.5
    assert cs["job_views_total"] == 13
    assert cs["job_favorites_total"] == 3
    assert cs["top_cities"] == [{"city": "北京", "cnt": 5},
                                {"city": "重庆", "cnt": 5}]   # 合并 2+3，并列按名升序
    assert cs["study_style_distribution"] == {"待激活": 1, "高投入型": 1}
    assert cs["low_engagement"] == [{
        "student_no": "S1", "name": "低投入",
        "reasons": ["出勤率低于80%", "本学期未到馆", "消费规律性偏低",
                    "无证书/竞赛/项目"],
    }]


def test_low_engagement_rules_individual():
    base = dict(library=[{"term": "t", "visits": 5, "borrows": 1}],
                consumption=[{"term": "t", "active_days": 60}],   # reg 0.5
                activity_counts=[{"term": "t", "type": "cert", "cnt": 1}],
                attendance=[{"term": "t", "rate": 0.8}])          # 边界不命中
    ok = _insight(student_no="OK", **base)
    assert _class([ok])["class_summary"]["low_engagement"] == []

    low_att = _insight(student_no="A", **{**base, "attendance": [
        {"term": "t", "rate": 0.79}]})
    assert _class([low_att])["class_summary"]["low_engagement"][0]["reasons"] == [
        "出勤率低于80%"]

    no_visit = _insight(student_no="B", **{**base, "library": [
        {"term": "t", "visits": 0, "borrows": 0}]})
    assert _class([no_visit])["class_summary"]["low_engagement"][0]["reasons"] == [
        "本学期未到馆"]

    low_reg = _insight(student_no="C", **{**base, "consumption": [
        {"term": "t", "active_days": 30}]})                        # reg 0.25
    assert _class([low_reg])["class_summary"]["low_engagement"][0]["reasons"] == [
        "消费规律性偏低"]

    no_act = _insight(student_no="D", **{**base, "activity_counts": []})
    assert _class([no_act])["class_summary"]["low_engagement"][0]["reasons"] == [
        "无证书/竞赛/项目"]

    # latest 为 None（无到馆行）不触发「本学期未到馆」，其余规则照常
    no_lib = _insight(student_no="E", library=[],
                      consumption=[{"term": "t", "active_days": 24}],
                      attendance=[{"term": "t", "rate": 0.75}])
    assert _class([no_lib])["class_summary"]["low_engagement"][0]["reasons"] == [
        "出勤率低于80%", "消费规律性偏低", "无证书/竞赛/项目"]


def test_class_avg_attendance_skips_none():
    s1 = _insight(student_no="S1", attendance=[{"term": "t", "rate": 0.9}])
    s2 = _insight(student_no="S2")             # latest_rate None 不入均值
    cs = _class([s1, s2])["class_summary"]
    assert cs["avg_attendance_rate"] == 0.9
    assert cs["avg_library_visits"] == 0.0     # 无 latest 按 0 计入分母
    assert cs["avg_regularity"] == 0.0
    assert cs["activity_coverage_rate"] == 0.0


def test_empty_class_zero_summary():
    r = _class([])
    cs = r["class_summary"]
    assert cs["student_total"] == 0
    assert cs["avg_library_visits"] == 0.0
    assert cs["avg_borrows"] == 0.0
    assert cs["avg_attendance_rate"] == 0.0
    assert cs["avg_regularity"] == 0.0
    assert cs["activity_counts"] == {"cert": 0, "contest": 0, "project": 0}
    assert cs["activity_coverage_rate"] == 0.0
    assert cs["job_views_total"] == 0
    assert cs["job_favorites_total"] == 0
    assert cs["top_cities"] == []
    assert cs["top_industries"] == []
    assert cs["study_style_distribution"] == {}
    assert cs["low_engagement"] == []
    assert r["students"] == []
    assert r["student_total"] == 0
    assert r["note"] == "暂无学生行为数据"