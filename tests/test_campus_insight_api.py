# tests/test_campus_insight_api.py
# 职责：校园行为洞察——工具层取数/租户隔离、表达层数值回查与降级、路由契约（离线全 mock）。
# 依赖：pytest / agents.tools / agents.campus_insight / engine.campus_insight / FastAPI TestClient。
# 说明：守住铁律 1（数值只出自引擎）、铁律 2（身份只用 ctx）、铁律 3（租户过滤在 SQL）。

from __future__ import annotations

import re
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from agents import campus_insight as campus_agent  # noqa: E402
from agents import tools as agent_tools  # noqa: E402
from agents.critic import MAX_RETRY, verify  # noqa: E402
from agents.tools import ToolContext  # noqa: E402
from app.auth import get_current_ctx  # noqa: E402
from app.main import create_app  # noqa: E402
from app.routers import student as student_router  # noqa: E402
from app.routers import teacher as teacher_router  # noqa: E402
from engine import campus_insight as ci  # noqa: E402

TERM = "2025-2026-1"
TENANT = 7
STUDENT_ID = 42

STUDENT_CTX = ToolContext(actor_type="student", tenant_id=TENANT, student_id=STUDENT_ID)
TEACHER_CTX = ToolContext(actor_type="teacher", tenant_id=TENANT, teacher_id=1)

SELF_ROW = {"student_no": "AI20230001", "name": "张三", "major": "软件工程",
            "class_name": "AI2201", "enroll_year": 2023}

# 原始 DB 行（含 Decimal / date / JSON 字符串，验证工具层归一化）
LIB_RAW = [{"term": "2024-2025-2", "visits": 4, "borrows": 1},
           {"term": TERM, "visits": 9, "borrows": 3}]
CONS_RAW = [{"term": TERM, "count": 80, "active_days": 50,
             "daily_avg": Decimal("12.5")}]
ACT_COUNTS_RAW = [{"term": TERM, "type": "cert", "cnt": 2}]
ACT_RECENT_RAW = [{"name": "软考", "type": "cert", "level": "国家级",
                   "date": date(2025, 11, 1)}]
ATT_RAW = [{"term": TERM, "expected": 100, "absent": 5,
            "rate": Decimal("0.9500")}]
VIEWS_RAW = [{"term": TERM, "action": "view", "cnt": 6},
             {"term": TERM, "action": "favorite", "cnt": 2}]
CITIES_RAW = [{"city": "重庆", "cnt": 5}]
INDUSTRIES_RAW = [{"industry": "互联网", "cnt": 4}]
EXTRA_RAW = {"cet4": 520, "cet6": None, "politics": "群众",
             "target_city": "重庆", "weekly_hours": Decimal("12.5")}
SNAP_RAW = [{"year": 2025, "week": 12, "verdict": '{"overall": "B", "items": []}',
             "summary": "平稳"},
            {"year": 2025, "week": 10, "verdict": "broken-json", "summary": "上升"}]

# 归一化后的引擎入参（与工具层取数口径一致）
NORM_FACTS = dict(
    library=[dict(r) for r in LIB_RAW],
    consumption=[{"term": TERM, "count": 80, "active_days": 50, "daily_avg": 12.5}],
    activity_counts=[dict(r) for r in ACT_COUNTS_RAW],
    activity_recent=[{"name": "软考", "type": "cert", "level": "国家级",
                      "date": "2025-11-01"}],
    attendance=[{"term": TERM, "expected": 100, "absent": 5, "rate": 0.95}],
    job_view_counts=[dict(r) for r in VIEWS_RAW],
    job_top_cities=[dict(r) for r in CITIES_RAW],
    job_top_industries=[dict(r) for r in INDUSTRIES_RAW],
    extra={"cet4": 520, "cet6": None, "politics": "群众",
           "target_city": "重庆", "weekly_hours": 12.5},
    snapshots=[{"year": 2025, "week": 10, "overall": None, "summary": "上升"},
               {"year": 2025, "week": 12, "overall": "B", "summary": "平稳"}],
)

FACTS_STUDENT = {
    **ci.build_student_insight(student_no="AI20230001", name="张三",
                               class_name="AI2201", term=TERM, **NORM_FACTS),
    "tools_version": agent_tools.TOOLS_VERSION,
}


def _low_student() -> dict:
    return ci.build_student_insight(
        student_no="AI20230002", name="李四", class_name="AI2201", term=TERM,
        library=[{"term": TERM, "visits": 0, "borrows": 0}],
        consumption=[{"term": TERM, "count": 30, "active_days": 24, "daily_avg": 10.0}],
        activity_counts=[], activity_recent=[],
        attendance=[{"term": TERM, "expected": 100, "absent": 25, "rate": 0.75}],
        job_view_counts=[{"term": TERM, "action": "view", "cnt": 3}],
        job_top_cities=[{"city": "重庆", "cnt": 2}], job_top_industries=[],
        extra=None, snapshots=[])


def _high_student() -> dict:
    return ci.build_student_insight(
        student_no="AI20230001", name="张三", class_name="AI2201", term=TERM,
        library=[{"term": TERM, "visits": 30, "borrows": 4}],
        consumption=[{"term": TERM, "count": 150, "active_days": 120, "daily_avg": 18.0}],
        activity_counts=[{"term": TERM, "type": "cert", "cnt": 2},
                         {"term": TERM, "type": "contest", "cnt": 1}],
        activity_recent=[],
        attendance=[{"term": TERM, "expected": 100, "absent": 5, "rate": 0.95}],
        job_view_counts=[{"term": TERM, "action": "view", "cnt": 10},
                         {"term": TERM, "action": "favorite", "cnt": 2}],
        job_top_cities=[{"city": "重庆", "cnt": 3}, {"city": "北京", "cnt": 5}],
        job_top_industries=[], extra=None, snapshots=[])


CLASS_FACTS = {
    **ci.build_class_insight(tenant_id=TENANT, class_name="AI2201", term=TERM,
                             students=[_low_student(), _high_student()]),
    "tools_version": agent_tools.TOOLS_VERSION,
}


def _fake_campus_query(calls: list):
    """按 SQL 里的表名分发构造行；所有查询都被记录供租户断言。"""
    def fake_query(sql, params=()):
        calls.append((sql, tuple(params)))
        if "图书馆记录" in sql:
            return [dict(r) for r in LIB_RAW]
        if "消费记录" in sql:
            return [dict(r) for r in CONS_RAW]
        if "学生活动" in sql and "COUNT" in sql:
            return [dict(r) for r in ACT_COUNTS_RAW]
        if "学生活动" in sql:
            return [dict(r) for r in ACT_RECENT_RAW]
        if "考勤" in sql:
            return [dict(r) for r in ATT_RAW]
        if "岗位浏览日志" in sql and "城市" in sql:
            return [dict(r) for r in CITIES_RAW]
        if "岗位浏览日志" in sql and "行业" in sql:
            return [dict(r) for r in INDUSTRIES_RAW]
        if "岗位浏览日志" in sql:
            return [dict(r) for r in VIEWS_RAW]
        if "学生扩展信息" in sql:
            return [dict(EXTRA_RAW)]
        if "周快照" in sql:
            return [dict(r) for r in SNAP_RAW]
        if "FROM `学生`" in sql:
            return [dict(SELF_ROW)]
        return []
    return fake_query


# ----------------------------------------------------------------
# 1. 工具层：数值与引擎一致 / SQL 带租户 / 归一化 / 审计
# ----------------------------------------------------------------
def test_my_campus_insight_matches_engine_and_tenant_sql(monkeypatch):
    calls: list = []
    audits: list = []
    monkeypatch.setattr(agent_tools, "_query", _fake_campus_query(calls))
    monkeypatch.setattr(agent_tools, "write_audit",
                        lambda **kw: audits.append(kw))
    out = agent_tools.my_campus_insight(STUDENT_CTX, term=TERM)

    expected = ci.build_student_insight(
        student_no="AI20230001", name="张三", class_name="AI2201",
        term=TERM, **NORM_FACTS)
    assert out == {**expected, "tools_version": agent_tools.TOOLS_VERSION}
    assert out["study_style"] == {"label": "稳健型", "score": 0.53}
    assert out["consumption"]["latest"]["daily_avg"] == 12.5      # Decimal→float
    assert out["extra"]["weekly_hours"] == 12.5
    assert out["activities"]["recent"][0]["date"] == "2025-11-01"  # date→str
    assert out["snapshots"][0]["overall"] is None                  # 坏 JSON 容错
    assert out["snapshots"][1]["overall"] == "B"
    assert [s["week"] for s in out["snapshots"]] == [10, 12]       # 升序

    assert calls, "必须有取数 SQL"
    assert all("租户编号" in sql for sql, _p in calls), "每条 SQL 必须带租户过滤"
    assert all(p[0] == TENANT for _s, p in calls), "租户必须是第一个参数"
    att = [(s, p) for s, p in calls if "考勤" in s]
    assert att and "JOIN `学生`" in att[0][0] and att[0][1] == (TENANT, STUDENT_ID)
    views = [(s, p) for s, p in calls if "岗位浏览日志" in s]
    assert views and all("GROUP BY" in s for s, _p in views), "浏览日志走索引聚合"
    assert audits and audits[-1]["action"] == "my_campus_insight"
    assert audits[-1]["detail"]["student_no"] == "AI20230001"


def test_campus_sql_percent_placeholders_escaped(monkeypatch):
    """pymysql 把 %X 当占位符：SQL 里的字面百分号（DATE_FORMAT 等）必须转义成 %%。"""
    calls: list = []
    monkeypatch.setattr(agent_tools, "_query", _fake_campus_query(calls))
    monkeypatch.setattr(agent_tools, "write_audit", lambda **kw: None)
    agent_tools.my_campus_insight(STUDENT_CTX, term=TERM)
    assert calls
    for sql, _p in calls:
        stripped = sql.replace("%%", "")
        assert re.search(r"%(?!s)", stripped) is None, f"未转义的百分号占位符：{sql}"


def test_my_campus_insight_empty_reports_note(monkeypatch):
    monkeypatch.setattr(agent_tools, "_query", lambda sql, params=(): [])
    monkeypatch.setattr(agent_tools, "write_audit", lambda **kw: None)
    monkeypatch.setattr(agent_tools, "_resolve_self",
                        lambda ctx, action: dict(SELF_ROW, student_id=ctx.student_id))
    out = agent_tools.my_campus_insight(STUDENT_CTX, term=TERM)
    assert out["note"] == "暂无校园行为数据"
    assert out["study_style"] == {"label": "暂无数据", "score": 0.0}
    assert out["library"]["terms"] == [] and out["extra"] is None


def test_my_campus_insight_identity_only_from_ctx(monkeypatch):
    """铁律 2：教师调用被拒；学生工具不接受任何「查谁」入参。"""
    monkeypatch.setattr(agent_tools, "write_audit", lambda **kw: None)
    with pytest.raises(PermissionError):
        agent_tools.my_campus_insight(TEACHER_CTX, term=TERM)
    with pytest.raises(PermissionError):
        agent_tools.class_campus_insight(STUDENT_CTX, "AI2201", TERM)


def test_class_campus_insight_limit_clamp_and_sample_note(monkeypatch):
    calls: list = []
    roster_calls: list = []
    base = _fake_campus_query(calls)

    def fake_query(sql, params=()):
        if "教师任教班级" in sql:
            calls.append((sql, tuple(params)))
            return [{"class_name": "AI2201"}]
        if "COUNT(DISTINCT" in sql:
            calls.append((sql, tuple(params)))
            return [{"cnt": 5}]
        if "FROM `学生`" in sql and "LIMIT" in sql:
            calls.append((sql, tuple(params)))
            roster_calls.append(tuple(params))
            return [{"student_id": 11, "student_no": "AI20230001", "name": "张三"},
                    {"student_id": 12, "student_no": "AI20230002", "name": "李四"}
                    ][:int(params[-1])]
        return base(sql, params)

    monkeypatch.setattr(agent_tools, "_query", fake_query)
    monkeypatch.setattr(agent_tools, "write_audit", lambda **kw: None)

    out = agent_tools.class_campus_insight(TEACHER_CTX, "AI2201", TERM, limit=100)
    assert roster_calls[-1] == (TENANT, "AI2201", 60), "limit 上限夹到 60"
    assert out["student_total"] == 2
    assert out["note"] and "样本" in out["note"] and "5" in out["note"]
    expected = ci.build_class_insight(
        tenant_id=TENANT, class_name="AI2201", term=TERM,
        students=[ci.build_student_insight(
            student_no=no, name=name, class_name="AI2201", term=TERM, **NORM_FACTS)
            for no, name in (("AI20230001", "张三"), ("AI20230002", "李四"))])
    assert out["class_summary"] == expected["class_summary"]
    assert out["tools_version"] == agent_tools.TOOLS_VERSION
    assert all("租户编号" in sql for sql, _p in calls)
    assert all(p[0] == TENANT for _s, p in calls)

    agent_tools.class_campus_insight(TEACHER_CTX, "AI2201", TERM, limit=0)
    assert roster_calls[-1] == (TENANT, "AI2201", 1), "limit 下限夹到 1"


def test_class_campus_insight_cross_class_denied(monkeypatch):
    monkeypatch.setattr(agent_tools, "write_audit", lambda **kw: None)

    def deny(ctx, class_name, action):
        raise PermissionError(f"班级 {class_name} 不在当前教师的任教范围内")

    monkeypatch.setattr(agent_tools, "_require_class", deny)
    with pytest.raises(PermissionError):
        agent_tools.class_campus_insight(TEACHER_CTX, "RJ9901", TERM)


# ----------------------------------------------------------------
# 2. 表达层：合格稿过 critic / 编造数值驳回降级 / LLM 不可用降级
# ----------------------------------------------------------------
def _patch_expr(monkeypatch, reply):
    calls: list[str] = []
    monkeypatch.setattr(campus_agent.tools, "my_campus_insight",
                        lambda ctx, term=None: dict(FACTS_STUDENT))
    monkeypatch.setattr(campus_agent.tools, "class_campus_insight",
                        lambda ctx, class_name, term="", limit=30: dict(CLASS_FACTS))

    def fake_generate(actor_type, *, system_prompt, user_prompt, tag, **kw):
        calls.append(tag)
        return reply() if callable(reply) else reply

    monkeypatch.setattr(campus_agent.llm_module, "generate_reply", fake_generate)
    monkeypatch.setattr(campus_agent.llm_module, "provider_order",
                        lambda **kw: ("deepseek",))
    return calls


def test_interpret_student_valid_reply_passes_critic(monkeypatch):
    reply = ("你的学习投入分 0.53（稳健型），本学期到馆 9 次、出勤率 95%，"
             "消费规律性 0.4167。建议保持节奏并参与竞赛。")
    calls = _patch_expr(monkeypatch, reply)
    out = campus_agent.interpret_student(STUDENT_CTX, term=TERM)
    assert out["source"] == "llm" and out["provider"] == "deepseek"
    assert out["retries"] == 0 and out["text"] == reply
    assert out["engine_version"] == ci.CAMPUS_INSIGHT_ENGINE_VERSION
    assert out["tools_version"] == agent_tools.TOOLS_VERSION
    assert calls == ["campus_insight"], "合格稿不应触发重写"


def test_interpret_student_fabricated_number_degrades(monkeypatch):
    bad = "你的学习投入分高达 99.9 分，到馆 999 次，远超全班同学。"
    calls = _patch_expr(monkeypatch, bad)
    out = campus_agent.interpret_student(STUDENT_CTX, term=TERM)
    assert out["source"] == "template" and out["provider"] is None
    assert out["retries"] == MAX_RETRY and len(calls) == MAX_RETRY + 1
    assert out["text"] == campus_agent._template_student(FACTS_STUDENT)
    assert verify(out["text"], FACTS_STUDENT).passed, "模板数值必须全部来自 facts"


def test_interpret_student_llm_unavailable_degrades(monkeypatch):
    _patch_expr(monkeypatch, None)
    out = campus_agent.interpret_student(STUDENT_CTX, term=TERM)
    assert out["source"] == "template" and out["retries"] == 0
    assert out["text"] == campus_agent._template_student(FACTS_STUDENT)


def test_interpret_student_empty_skips_llm(monkeypatch):
    empty = {**ci.build_student_insight(
        student_no="S1", name="张三", class_name="AI2201", term=TERM,
        library=[], consumption=[], activity_counts=[], activity_recent=[],
        attendance=[], job_view_counts=[], job_top_cities=[],
        job_top_industries=[], extra=None, snapshots=[]),
        "tools_version": agent_tools.TOOLS_VERSION}
    calls: list = []
    monkeypatch.setattr(campus_agent.tools, "my_campus_insight",
                        lambda ctx, term=None: dict(empty))
    monkeypatch.setattr(campus_agent.llm_module, "generate_reply",
                        lambda *a, **k: calls.append(1) or "不应被调用")
    out = campus_agent.interpret_student(STUDENT_CTX, term=TERM)
    assert calls == [], "无数据时不该调用大模型"
    assert out["source"] == "template" and "暂无校园行为数据" in out["text"]


def test_interpret_student_identity_from_ctx(monkeypatch):
    seen: dict = {}

    def fake_facts(ctx, term=None):
        seen.update(ctx=ctx, term=term)
        return dict(FACTS_STUDENT)

    monkeypatch.setattr(campus_agent.tools, "my_campus_insight", fake_facts)
    monkeypatch.setattr(campus_agent.llm_module, "generate_reply",
                        lambda *a, **k: None)
    campus_agent.interpret_student(STUDENT_CTX, term=TERM)
    assert seen["ctx"] is STUDENT_CTX and seen["term"] == TERM


def test_interpret_class_valid_and_degraded(monkeypatch):
    reply = ("班级共 2 人，投入画像分布 待激活 1 人、高投入型 1 人，"
             "平均出勤率 85%，活动覆盖率 50%。建议对低投入学生逐一谈话。")
    calls = _patch_expr(monkeypatch, reply)
    out = campus_agent.interpret_class(TEACHER_CTX, "AI2201", TERM, 30)
    assert out["source"] == "llm" and out["text"] == reply and out["retries"] == 0
    assert calls == ["campus_insight"]

    bad = "全班平均出勤率高达 99.9%，无人低投入，覆盖率达到 99%。"
    calls2 = _patch_expr(monkeypatch, bad)
    out2 = campus_agent.interpret_class(TEACHER_CTX, "AI2201", TERM, 30)
    assert out2["source"] == "template" and out2["retries"] == MAX_RETRY
    assert len(calls2) == MAX_RETRY + 1
    assert out2["text"] == campus_agent._template_class(CLASS_FACTS)
    assert verify(out2["text"], CLASS_FACTS).passed


def test_templates_are_pure_and_critic_safe():
    s = campus_agent._template_student(FACTS_STUDENT)
    assert "None" not in s and "0.53" in s and "95%" in s
    assert verify(s, FACTS_STUDENT).passed
    assert campus_agent._template_student(FACTS_STUDENT) == s   # 纯函数确定性
    c = campus_agent._template_class(CLASS_FACTS)
    assert "None" not in c and "共 2 人" in c and "李四" in c
    assert verify(c, CLASS_FACTS).passed
    empty = ci.build_class_insight(tenant_id=TENANT, class_name="AI2201",
                                   term=TERM, students=[])
    assert "暂无学生行为数据" in campus_agent._template_class(empty)


# ----------------------------------------------------------------
# 3. 路由：事实 GET + 智能体 POST / 身份注入 / 异常翻译
# ----------------------------------------------------------------
def _client(ctx: ToolContext | None = None) -> TestClient:
    app = create_app()
    if ctx is not None:
        app.dependency_overrides[get_current_ctx] = lambda: ctx
    return TestClient(app)


def test_student_get_campus_insight(monkeypatch):
    seen: dict = {}

    def fake(ctx, term=None):
        seen.update(ctx=ctx, term=term)
        return dict(FACTS_STUDENT)

    monkeypatch.setattr(student_router.tools, "my_campus_insight", fake)
    resp = _client(STUDENT_CTX).get("/student/campus-insight", params={"term": TERM})
    assert resp.status_code == 200, resp.text
    assert seen["ctx"] is STUDENT_CTX and seen["term"] == TERM
    body = resp.json()
    assert body["study_style"] == {"label": "稳健型", "score": 0.53}
    assert body["tools_version"] == agent_tools.TOOLS_VERSION


def test_student_post_interpret_ignores_identity_params(monkeypatch):
    """POST 不接受「查谁」入参：塞 student_id 也被忽略，身份只从 JWT 取。"""
    seen: dict = {}

    def fake(ctx, term=None):
        seen.update(ctx=ctx, term=term)
        return {"text": "解读", "source": "template", "provider": None, "retries": 0,
                "engine_version": ci.CAMPUS_INSIGHT_ENGINE_VERSION,
                "calc_version": FACTS_STUDENT["calc_version"],
                "tools_version": agent_tools.TOOLS_VERSION}

    monkeypatch.setattr(student_router.campus_agent, "interpret_student", fake)
    resp = _client(STUDENT_CTX).post("/student/campus-insight/interpret",
                                     json={"term": TERM, "student_id": 999})
    assert resp.status_code == 200, resp.text
    assert seen["ctx"] is STUDENT_CTX and seen["ctx"].student_id == STUDENT_ID
    assert seen["term"] == TERM
    body = resp.json()
    for key in ("text", "source", "provider", "retries",
                "engine_version", "calc_version", "tools_version"):
        assert key in body, f"前端契约缺字段 {key}"
    assert body["source"] in ("llm", "template")


def test_student_post_interpret_llm_down_returns_template(monkeypatch):
    monkeypatch.setattr(campus_agent.tools, "my_campus_insight",
                        lambda ctx, term=None: dict(FACTS_STUDENT))
    monkeypatch.setattr(campus_agent.llm_module, "generate_reply",
                        lambda *a, **k: None)
    resp = _client(STUDENT_CTX).post("/student/campus-insight/interpret", json={})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source"] == "template" and body["provider"] is None
    assert body["text"] == campus_agent._template_student(FACTS_STUDENT)


def test_teacher_get_campus_insight(monkeypatch):
    seen: dict = {}

    def fake(ctx, class_name, term="", limit=30):
        seen.update(ctx=ctx, class_name=class_name, term=term, limit=limit)
        return dict(CLASS_FACTS)

    monkeypatch.setattr(teacher_router.tools, "class_campus_insight", fake)
    resp = _client(TEACHER_CTX).get(
        "/teacher/campus-insight",
        params={"class_name": "AI2201", "term": TERM, "limit": 10})
    assert resp.status_code == 200, resp.text
    assert seen == {"ctx": TEACHER_CTX, "class_name": "AI2201",
                    "term": TERM, "limit": 10}
    assert resp.json()["class_summary"]["student_total"] == 2


def test_teacher_get_limit_validation(monkeypatch):
    monkeypatch.setattr(teacher_router.tools, "class_campus_insight",
                        lambda *a, **k: pytest.fail("非法 limit 不应进入工具"))
    client = _client(TEACHER_CTX)
    assert client.get("/teacher/campus-insight",
                      params={"class_name": "AI2201", "limit": 0}).status_code == 422
    assert client.get("/teacher/campus-insight",
                      params={"class_name": "AI2201", "limit": 61}).status_code == 422


def test_teacher_get_cross_class_is_403(monkeypatch):
    monkeypatch.setattr(agent_tools, "write_audit", lambda **kw: None)

    def deny(ctx, class_name, action):
        raise PermissionError(f"班级 {class_name} 不在当前教师的任教范围内")

    monkeypatch.setattr(agent_tools, "_require_class", deny)
    resp = _client(TEACHER_CTX).get("/teacher/campus-insight",
                                    params={"class_name": "RJ9901"})
    assert resp.status_code == 403
    assert "任教范围" in resp.json()["detail"]


def test_teacher_post_interpret(monkeypatch):
    seen: dict = {}

    def fake(ctx, class_name, term="", limit=30):
        seen.update(ctx=ctx, class_name=class_name, term=term, limit=limit)
        return {"text": "班级解读", "source": "llm", "provider": "deepseek",
                "retries": 0, "engine_version": ci.CAMPUS_INSIGHT_ENGINE_VERSION,
                "calc_version": CLASS_FACTS["calc_version"],
                "tools_version": agent_tools.TOOLS_VERSION}

    monkeypatch.setattr(teacher_router.campus_agent, "interpret_class", fake)
    resp = _client(TEACHER_CTX).post(
        "/teacher/campus-insight/interpret",
        json={"class_name": "AI2201", "term": TERM, "limit": 15})
    assert resp.status_code == 200, resp.text
    assert seen == {"ctx": TEACHER_CTX, "class_name": "AI2201",
                    "term": TERM, "limit": 15}
    assert resp.json()["source"] == "llm"


def test_anonymous_and_wrong_role_rejected():
    assert _client().get("/student/campus-insight").status_code == 401
    assert _client(STUDENT_CTX).get(
        "/teacher/campus-insight", params={"class_name": "AI2201"}).status_code == 403
    assert _client(TEACHER_CTX).get("/student/campus-insight").status_code == 403


# ----------------------------------------------------------------
# 4. 全班覆盖：逐生洞察工具 / 名册工具 / 两个新 GET 端点
# ----------------------------------------------------------------
def test_student_campus_insight_teacher_scope_and_tenant(monkeypatch):
    calls: list = []
    base = _fake_campus_query(calls)

    def fake_query(sql, params=()):
        if "教师任教班级" in sql:
            calls.append((sql, tuple(params)))
            return [{"class_name": "AI2201"}]
        if "FROM `学生` s WHERE" in sql:
            calls.append((sql, tuple(params)))
            return [dict(SELF_ROW, student_id=STUDENT_ID)]
        return base(sql, params)

    monkeypatch.setattr(agent_tools, "_query", fake_query)
    monkeypatch.setattr(agent_tools, "write_audit", lambda **kw: None)
    out = agent_tools.student_campus_insight(TEACHER_CTX, "AI20230001", TERM)
    assert out["study_style"] == {"label": "稳健型", "score": 0.53}
    assert out["student_no"] == "AI20230001"
    assert calls and all("租户编号" in sql for sql, _p in calls)
    assert all(p[0] == TENANT for _s, p in calls)
    # 铁律 2：学生端调用教师逐生工具被拒
    with pytest.raises(PermissionError):
        agent_tools.student_campus_insight(STUDENT_CTX, "AI20230001", TERM)


def test_student_campus_insight_cross_class_denied(monkeypatch):
    monkeypatch.setattr(agent_tools, "write_audit", lambda **kw: None)

    def fake_fetch(ctx, student_no, action):
        raise PermissionError(f"学生 {student_no} 的班级不在当前教师的任教范围内")

    monkeypatch.setattr(agent_tools, "_fetch_student", fake_fetch)
    with pytest.raises(PermissionError):
        agent_tools.student_campus_insight(TEACHER_CTX, "AI20230009", TERM)


def test_class_roster_full_and_tenant(monkeypatch):
    calls: list = []

    def fake_query(sql, params=()):
        calls.append((sql, tuple(params)))
        if "教师任教班级" in sql:
            return [{"class_name": "AI2201"}]
        if "COUNT(DISTINCT" in sql:
            return [{"cnt": 2}]
        if "FROM `学生`" in sql:
            assert "LIMIT" not in sql, "名册不截断，全班学生都要能定位"
            return [{"student_no": "AI20230001", "name": "张三", "major": "软件工程"},
                    {"student_no": "AI20230002", "name": "李四", "major": "软件工程"}]
        return []

    monkeypatch.setattr(agent_tools, "_query", fake_query)
    monkeypatch.setattr(agent_tools, "write_audit", lambda **kw: None)
    out = agent_tools.class_roster(TEACHER_CTX, "AI2201")
    assert out["total"] == 2 and len(out["roster"]) == 2
    assert "headcount" not in out, "名册形状不能撞班级概览模板分支"
    assert all("租户编号" in sql for sql, _p in calls)
    with pytest.raises(PermissionError):
        agent_tools.class_roster(STUDENT_CTX, "AI2201")


def test_teacher_get_student_campus_insight(monkeypatch):
    seen: dict = {}

    def fake(ctx, student_no, term=""):
        seen.update(ctx=ctx, student_no=student_no, term=term)
        return dict(FACTS_STUDENT)

    monkeypatch.setattr(teacher_router.tools, "student_campus_insight", fake)
    resp = _client(TEACHER_CTX).get(
        "/teacher/campus-insight/student/AI20230001", params={"term": TERM})
    assert resp.status_code == 200, resp.text
    assert seen == {"ctx": TEACHER_CTX, "student_no": "AI20230001", "term": TERM}
    assert resp.json()["study_style"]["label"] == "稳健型"


def test_teacher_get_student_campus_insight_403(monkeypatch):
    def deny(ctx, student_no, term=""):
        raise PermissionError("学生 AI20230009 的班级不在当前教师的任教范围内")

    monkeypatch.setattr(teacher_router.tools, "student_campus_insight", deny)
    resp = _client(TEACHER_CTX).get("/teacher/campus-insight/student/AI20230009")
    assert resp.status_code == 403
    assert "任教范围" in resp.json()["detail"]


def test_teacher_get_class_roster(monkeypatch):
    seen: dict = {}

    def fake(ctx, class_name):
        seen.update(ctx=ctx, class_name=class_name)
        return {"class_name": class_name, "total": 2,
                "roster": [{"student_no": "AI20230001", "name": "张三",
                            "major": "软件工程"}],
                "tools_version": agent_tools.TOOLS_VERSION}

    monkeypatch.setattr(teacher_router.tools, "class_roster", fake)
    resp = _client(TEACHER_CTX).get(
        "/teacher/class-roster", params={"class_name": "AI2201"})
    assert resp.status_code == 200, resp.text
    assert seen["class_name"] == "AI2201"
    assert resp.json()["total"] == 2
    assert _client(STUDENT_CTX).get(
        "/teacher/class-roster", params={"class_name": "AI2201"}).status_code == 403