# tests/test_interview_lab_upgrade.py
# 职责：面试复盘实验室升级的路由契约——trend / course_hint / gap_bucket / printable。
# 说明：离线测试；假游标替身 DB，所有引擎/模型调用按需打桩。

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agents.tools import ToolContext  # noqa: E402
from app.routers import interview_lab as lab  # noqa: E402


def _ctx() -> ToolContext:
    return ToolContext(actor_type="student", tenant_id=1, student_id=7)


class FakeCursor:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=()):
        pass

    def fetchone(self):
        return None

    def fetchall(self):
        return []


class FakeConn:
    def cursor(self):
        return FakeCursor()

    def commit(self):
        pass

    def close(self):
        pass


# ----------------------------------------------------------------
# 纯拼装：trend / course_hint / gap_bucket / printable
# ----------------------------------------------------------------
def test_build_trend_is_single_type_ascending_and_averages_duplicate_rounds():
    # 输入故意是时间倒序；输出必须旧→新，且同场同题型多题取均分
    sessions = [{"sid": 13, "as_of": "2026-11-20"}, {"sid": 12, "as_of": "2026-11-19"}]
    scores = [{"sid": 12, "type": "major", "score": 55.2},
              {"sid": 13, "type": "major", "score": 70.0},
              {"sid": 13, "type": "major", "score": 71.0},
              {"sid": 13, "type": "project", "score": 80.0}]
    out = lab._build_trend(sessions, scores, "major")
    assert out == [
        {"sid": 12, "as_of": "2026-11-19", "type": "major", "score": 55.2},
        {"sid": 13, "as_of": "2026-11-20", "type": "major", "score": 70.5},
    ]


def test_focus_type_is_lowest_score_then_most_questions():
    pairs = [({"type": "major"}, None), ({"type": "project"}, None),
             ({"type": "counter"}, None)]
    assert lab._focus_type(pairs, [{"score": 80}, {"score": 50}, {"score": 60}]) == "project"
    assert lab._focus_type(pairs, [None, None, None]) == "counter"  # 题量并列取字典序，确定性
    pairs2 = [({"type": "major"}, None), ({"type": "major"}, None), ({"type": "project"}, None)]
    assert lab._focus_type(pairs2, [None, None, None]) == "major"


def test_course_hints_reuse_attribution_items_and_keep_missing_percentile():
    result = {"items": [
        {"concept": "Redis", "course": "数据库原理", "percentile": 31.0},
        {"concept": "Redis", "course": "数据库原理", "percentile": 31.0},
        {"concept": "缓存", "course": "Redis 实战", "percentile": None},
        {"concept": "无对应课程", "course": "", "percentile": 10.0},
    ]}
    assert lab._course_hints(result) == [
        {"dimension": "Redis", "course": "数据库原理", "percentile": 31.0},
        {"dimension": "缓存", "course": "Redis 实战", "percentile": None},
    ]


def test_gap_buckets_group_by_missing_count_with_deterministic_hint():
    jobs = [
        {"title": "后端A", "skills": ["Python", "Redis"]},
        {"title": "后端B", "skills": ["Python", "Kafka"]},
        {"title": "数据岗", "skills": ["Python", "Spark", "Hive", "Flink"]},
        {"title": "不相关", "skills": ["Words", "Excel"]},
    ]
    out = lab._gap_buckets(jobs, {"python", "redis"})
    assert [it["job"] for it in out["near"]] == ["后端B"]
    assert out["near"][0]["gaps"] == ["Kafka"]
    assert out["near"][0]["hint"] == "补上Kafka就能投「后端B」"
    assert [it["job"] for it in out["far"]] == ["数据岗"]
    assert all(len(bucket) <= 5 for bucket in out.values())


def test_printable_card_is_deterministic_and_bounded():
    agg = {"total": 82.0, "answered": 4, "skipped": 1}
    dims = {"content": 80.0, "depth": 70.0, "evidence": 90.0}
    problems = [{"dimension": "结构", "problem": "缺少结果"}] * 5
    gaps = [{"dimension": "证据", "action": "补项目"}]
    plan = [{"when": "本周", "focus": "Redis", "action": "做一个缓存demo"}]
    out = lab._printable_card(agg, dims, problems, gaps, plan)
    assert out["summary"] == "本场模拟面试总分 82.0 分，评级 B+；已答 4 题，跳过 1 题。"
    assert out["strengths"] == ["证据维度 90.0 分", "内容维度 80.0 分", "深度维度 70.0 分"]
    assert len(out["weaknesses"]) == 3 and len(out["actions"]) == 1
    assert lab._printable_card(None, {}, [], [], []) == {
        "summary": "本场暂无可汇总的评分数据。", "strengths": [], "weaknesses": [], "actions": []
    }


# ----------------------------------------------------------------
# 端点接线：三处响应体都带新字段
# ----------------------------------------------------------------
def test_attribution_response_has_trend_and_course_hint(monkeypatch):
    ctxd = {"sess": {"岗位名称": "后端"}, "outline": [{"type": "major", "round": 1}],
            "pairs": [({"type": "major", "round": 1}, None)],
            "resume": {}, "snapshot": {}, "job_skills": []}
    monkeypatch.setattr(lab, "_conn", lambda: FakeConn())
    monkeypatch.setattr(lab, "_load_session", lambda cur, sid, ctx: ctxd)
    monkeypatch.setattr(lab, "_one", lambda cur, sql, params: {"专业": None, "年级": None})
    monkeypatch.setattr(lab, "_evidence", lambda resume, snapshot: [])
    monkeypatch.setattr(lab, "_score_pairs",
                        lambda *a: [{"score": 60.0, "keyword_missed": ["Redis"]}])
    monkeypatch.setattr(lab.attr_engine, "attribute", lambda *a: {
        "type": "foundation",
        "items": [{"concept": "Redis", "course": "数据库原理", "percentile": 31.0}],
    })

    def rows(cur, sql, params):
        if "LIMIT 3" in sql and "JOIN" in sql:
            return [{"sid": 13, "as_of": "2026-11-20"}]
        if "`问题类型` AS type" in sql:
            return [{"sid": 13, "type": "major", "score": 70.4}]
        if "GROUP BY c.`编号`" in sql:
            return [{"course_id": 1, "name": "数据库原理", "credit": 3, "score": 68}]
        return []

    monkeypatch.setattr(lab, "_rows", rows)
    res = lab.attribution(13, _ctx())
    assert res["trend"] == [{"sid": 13, "as_of": "2026-11-20", "type": "major", "score": 70.4}]
    assert res["course_hint"] == [
        {"dimension": "Redis", "course": "数据库原理", "percentile": 31.0}]
    assert res["type"] == "foundation"


def test_trend_uses_one_focus_type_ascending_and_at_most_three(monkeypatch):
    """回归：同一 sid 多种题型 → 必须只留焦点题型，按 as_of 旧→新，最多 3 条。"""
    ctxd = {"sess": {"岗位名称": "后端"},
            "outline": [{"type": t, "round": i + 1}
                        for i, t in enumerate(("motivation", "major", "project"))],
            "pairs": [({"type": t, "round": i + 1}, None)
                      for i, t in enumerate(("motivation", "major", "project"))],
            "resume": {}, "snapshot": {}, "job_skills": []}
    monkeypatch.setattr(lab, "_conn", lambda: FakeConn())
    monkeypatch.setattr(lab, "_load_session", lambda cur, sid, ctx: ctxd)
    monkeypatch.setattr(lab, "_one", lambda cur, sql, params: {"专业": None, "年级": None})
    monkeypatch.setattr(lab, "_evidence", lambda resume, snapshot: [])
    # major 最低分 → 焦点题型；其余题型不得出现在 trend
    monkeypatch.setattr(lab, "_score_pairs",
                        lambda *a: [{"score": 80.0}, {"score": 50.0}, {"score": 70.0}])
    monkeypatch.setattr(lab.attr_engine, "attribute", lambda *a: {"items": []})

    def rows(cur, sql, params):
        if "LIMIT 3" in sql and "JOIN" in sql:
            # 故意时间倒序返回，验证输出被修正为升序
            return [{"sid": 26, "as_of": "2026-11-24"},
                    {"sid": 25, "as_of": "2026-11-23"},
                    {"sid": 24, "as_of": "2026-11-22"}]
        if "`问题类型` AS type" in sql:
            return [{"sid": 24, "type": "major", "score": 40.0},
                    {"sid": 25, "type": "major", "score": 55.0},
                    {"sid": 26, "type": "major", "score": 60.0},
                    {"sid": 26, "type": "project", "score": 90.0}]
        return []

    monkeypatch.setattr(lab, "_rows", rows)
    trend = lab.attribution(26, _ctx())["trend"]
    assert len(trend) <= 3
    assert {item["type"] for item in trend} == {"major"}
    assert [item["as_of"] for item in trend] == sorted(item["as_of"] for item in trend)
    assert [item["sid"] for item in trend] == [24, 25, 26]


def test_readiness_post_and_get_expose_gap_bucket(monkeypatch):
    monkeypatch.setattr(lab, "_conn", lambda: FakeConn())
    monkeypatch.setattr(lab, "_graded_courses", lambda cur, ctx: [])
    monkeypatch.setattr(lab, "_one", lambda cur, sql, params: None)
    monkeypatch.setattr(lab, "_catalog_names", lambda conn: [])
    monkeypatch.setattr(lab, "_my_skill_pool", lambda cur, ctx: {"python"})
    monkeypatch.setattr(lab, "_all_jobs", lambda conn: [
        {"title": "后端B", "skills": ["Python", "Kafka"]},
        {"title": "数据岗", "skills": ["Python", "Spark", "Hive", "Flink"]},
    ])
    monkeypatch.setattr(lab.readi_engine, "assess", lambda *a: {"readiness": 60.0})

    post = lab.readiness(lab.ReadinessIn(job_title="后端"), _ctx())
    get = lab.readiness_get(job_title="后端", ctx=_ctx())
    assert post == get
    assert post["gap_bucket"]["near"][0]["job"] == "后端B"
    assert post["gap_bucket"]["far"][0]["gaps"] == ["Spark", "Hive", "Flink"]


def test_report_card_response_has_printable(monkeypatch):
    ctxd = {"sess": {"岗位名称": "后端", "完成时间": "2026-11-24"},
            "outline": [], "pairs": [], "resume": {}, "snapshot": {}, "job_skills": []}
    monkeypatch.setattr(lab, "_conn", lambda: FakeConn())
    monkeypatch.setattr(lab, "_load_session", lambda cur, sid, ctx: ctxd)
    monkeypatch.setattr(lab, "_evidence", lambda *a: [])
    monkeypatch.setattr(lab, "_score_pairs", lambda *a: [])
    monkeypatch.setattr(lab, "review", lambda *a: {})
    monkeypatch.setattr(lab, "aggregate", lambda *a: {"total": 75.0, "answered": 2, "skipped": 0})
    monkeypatch.setattr(lab, "core_problems", lambda *a: [])
    monkeypatch.setattr(lab, "gap_list", lambda *a: [])
    monkeypatch.setattr(lab, "improvement_plan", lambda *a: [])
    monkeypatch.setattr(lab, "_dims_of", lambda scores: {"content": 80.0})

    res = lab.report_card(13, _ctx())
    assert set(res["printable"]) == {"summary", "strengths", "weaknesses", "actions"}
    assert res["printable"]["strengths"] == ["内容维度 80.0 分"]
    assert res["printable"]["weaknesses"] == [] and res["printable"]["actions"] == []
