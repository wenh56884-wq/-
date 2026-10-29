# tests/test_agent_entry.py
# 职责：覆盖「智能体成为统一入口」——工具集扩展后，各功能是否真的能被智能体调度到。
#
# 改造前的问题：智能体只有 9 个工具（班级 / 预警 / 画像 / 差距 / 知识库 / 联网 / 工作流），
# 成绩、学业预测、报考分析、知识图谱、竞赛、通知这些功能只能走页面接口；
# 学生端路由更是只有两条（推荐 → my_recommendations，其余一律 my_warning）。
#
# 本文件守住三件事：
#   1. 新功能能被路由到（成绩 / 预测 / 竞争力 / 通知 / 竞赛 / 图谱）
#   2. 铁律 2：学生端工具只用 ctx.student_id，外部塞学号无效
#   3. 角色裁剪：学生端拿不到查他人的工具

from __future__ import annotations

import pymysql
import pytest

from agents import auto_plan
from agents import graph as agent_graph
from agents import tools as agent_tools
from agents.tools import ToolContext
from app.config import get_settings


def _conn():
    s = get_settings()
    return pymysql.connect(host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
                           password=s.mysql_password, database=s.mysql_db,
                           charset="utf8mb4", autocommit=True,
                           cursorclass=pymysql.cursors.DictCursor)


def _mysql_ok() -> bool:
    try:
        _conn().close()
        return True
    except Exception:
        return False


# 真库测试标记：MySQL 不可用环境自动跳过（与 test_interview_pool 的 DB 同语义）
DB_OK = pytest.mark.skipif(not _mysql_ok(), reason="需要 MySQL")


def _teacher() -> ToolContext:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT `编号`,`租户编号` FROM `教师` ORDER BY `编号` LIMIT 1")
            row = cur.fetchone()
    finally:
        conn.close()
    return ToolContext(actor_type="teacher", tenant_id=int(row["租户编号"]),
                       teacher_id=int(row["编号"]))


def _student() -> ToolContext:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT `编号`,`租户编号` FROM `学生` ORDER BY `编号` LIMIT 1")
            row = cur.fetchone()
    finally:
        conn.close()
    return ToolContext(actor_type="student", tenant_id=int(row["租户编号"]),
                       student_id=int(row["编号"]))


def _plan(ctx: ToolContext, query: str) -> str:
    return agent_graph.plan_node({"ctx": ctx, "query": query, "history": []})["tool_name"]


# ----------------------------------------------------------------
# 1. 学生端路由：改造前除「推荐」外一律落到 my_warning
# ----------------------------------------------------------------
def test_student_grades_question_routes_to_my_grades():
    assert _plan(_student(), "我的成绩怎么样") == "my_grades"
    assert _plan(_student(), "我的绩点是多少") == "my_grades"


def test_student_forecast_wins_over_grades_for_prediction_wording():
    """「预测一下我下学期的绩点」含「绩点」，但不能被成绩路由吃掉。"""
    assert _plan(_student(), "预测一下我下学期的绩点") == "my_forecast"
    assert _plan(_student(), "我下学期会挂科吗") == "my_forecast"


def test_student_career_question_routes_to_competitiveness():
    assert _plan(_student(), "我考公有多大把握") == "my_career_forecast"
    assert _plan(_student(), "我考研竞争力怎么样") == "my_career_forecast"


def test_student_notice_and_competition_routes():
    assert _plan(_student(), "有没有新通知") == "my_notices"
    assert _plan(_student(), "有什么竞赛可以参加") == "competition_guide"


def test_student_data_intent_does_not_steal_kb_question():
    """「实习管理办法」仍要走知识库——数据路由只认明确的本人数据问法。"""
    assert _plan(_student(), "实习管理办法里实习多少周") == "kb_search"


def test_student_default_still_my_warning():
    assert _plan(_student(), "我的预警情况") == "my_warning"
    assert _plan(_student(), "帮我推荐几个岗位") == "my_recommendations"


def test_student_major_skills_routes_to_kg():
    assert _plan(_student(), "我的专业能学到什么技能") == "kg_major_skills"


# ----------------------------------------------------------------
# 2. 教师端路由：新工具要能拿到学号
# ----------------------------------------------------------------
def test_teacher_grades_question_routes_with_student_no():
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT `学号`,`租户编号` FROM `学生` ORDER BY `学号` LIMIT 1")
            row = cur.fetchone()
    finally:
        conn.close()
    ctx = ToolContext(actor_type="teacher", tenant_id=int(row["租户编号"]), teacher_id=1)

    plan = agent_graph.plan_node({"ctx": ctx, "query": f"{row['学号']} 的成绩单",
                                  "history": []})
    assert plan["tool_name"] == "student_grades"
    assert plan["plan"]["args"]["student_no"] == row["学号"], "教师查成绩得带上学号"


def test_teacher_forecast_question_routes_with_student_no():
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT `学号`,`租户编号` FROM `学生` ORDER BY `学号` LIMIT 1")
            row = cur.fetchone()
    finally:
        conn.close()
    ctx = ToolContext(actor_type="teacher", tenant_id=int(row["租户编号"]), teacher_id=1)

    plan = agent_graph.plan_node({"ctx": ctx, "query": f"{row['学号']} 下学期预测",
                                  "history": []})
    assert plan["tool_name"] == "student_forecast"
    assert plan["plan"]["args"]["student_no"] == row["学号"]


# ----------------------------------------------------------------
# 3. 分发表：新工具名要真的能调到（参数对应关系也不能错）
# ----------------------------------------------------------------
_NEW_TOOLS = ("my_grades", "my_forecast", "my_career_forecast", "student_grades",
              "student_forecast", "kg_major_skills", "kg_skill_jobs", "kg_path",
              "my_notices", "my_career_guide", "competition_guide", "search_jobs",
              "job_facets")


def test_dispatch_reaches_every_new_tool(monkeypatch):
    """每个新工具名都能被 tool_node 分发出去（工具名写错会静默失效，必须测）。"""
    seen: dict[str, tuple] = {}

    def fake(name):
        def _fn(*args, **kwargs):
            seen[name] = (args, kwargs)
            return {"tool": name}
        return _fn

    for name in _NEW_TOOLS:
        monkeypatch.setattr(agent_tools, name, fake(name), raising=True)

    for name in _NEW_TOOLS:
        agent_graph._dispatch(_student(), name, {})
    assert set(seen) == set(_NEW_TOOLS)


def test_dispatch_passes_student_no_for_teacher_side_tools(monkeypatch):
    """教师端查成绩/预测时，学号要真的传下去。"""
    seen: dict[str, tuple] = {}

    def fake(name):
        def _fn(*args, **kwargs):
            seen[name] = args
            return {"tool": name}
        return _fn

    for name in ("student_grades", "student_forecast"):
        monkeypatch.setattr(agent_tools, name, fake(name), raising=True)

    agent_graph._dispatch(_teacher(), "student_grades", {"student_no": "AI20230001"})
    agent_graph._dispatch(_teacher(), "student_forecast", {"student_no": "AI20230001"})
    assert seen["student_grades"][1] == "AI20230001"
    assert seen["student_forecast"][1] == "AI20230001"


# ----------------------------------------------------------------
# 4. 铁律：学生端工具只用 ctx，不给查别人的机会
# ----------------------------------------------------------------
def test_my_grades_uses_ctx_identity_only(monkeypatch):
    """铁律 2：my_grades 用 ctx.student_id 取本人，args 里塞别人的学号也无效。"""
    captured: dict = {}

    monkeypatch.setattr(
        agent_tools, "_resolve_self",
        lambda ctx, action: {"student_no": "SELF", "student_id": ctx.student_id,
                             "name": "本人", "enroll_year": 2023})
    def fake_report(ctx, stu):
        captured["stu"] = dict(stu)
        return {"summary": {"record_count": 0}}

    monkeypatch.setattr(agent_tools, "_grades_report", fake_report)

    ctx = _student()
    agent_tools.my_grades(ctx)
    assert captured["stu"]["student_id"] == ctx.student_id
    assert captured["stu"]["student_no"] == "SELF"


def test_student_toolset_has_no_peer_data_tools():
    """学生端工具集不能出现「查别人」的工具（越权会在工具层被拦，但根本不该给选项）。"""
    student_tools = {t.name for t in auto_plan._STUDENT_TOOLS}
    forbidden = {"student_profile", "warning_list", "student_grades", "student_forecast",
                 "class_overview", "career_gap", "class_list", "warning_thresholds"}
    assert student_tools & forbidden == set(), f"学生端出现了越权工具：{student_tools & forbidden}"


def test_new_tools_are_selectable_by_auto_planner():
    """自主规划（AGENT_MODE=auto）时，新工具必须在可选集合里，否则选了会被退回。"""
    for name in _NEW_TOOLS:
        assert name in auto_plan.EXECUTABLE, f"{name} 不在可执行集合里"


# ----------------------------------------------------------------
# 5. agent-entry-v2 补全：招考公告 / 模拟面试历史 / 面试题库
# ----------------------------------------------------------------
_NEW_TOOLS_V2 = ("exam_notices", "my_interviews", "question_bank_lookup")


def test_v2_tools_registered_everywhere():
    for name in _NEW_TOOLS_V2:
        assert name in auto_plan.EXECUTABLE, f"{name} 不在可执行集合里"
    # 招考/题库师生都给；面试历史只给本人
    tnames = {t.name for t in auto_plan._TEACHER_TOOLS}
    snames = {t.name for t in auto_plan._STUDENT_TOOLS}
    assert {"exam_notices", "question_bank_lookup"} <= tnames
    assert {"exam_notices", "question_bank_lookup", "my_interviews"} <= snames
    assert "my_interviews" not in tnames
    # 注册表同步
    assert "my_interviews" in agent_tools.STUDENT_TOOLS
    assert "my_interviews" not in agent_tools.TEACHER_TOOLS
    assert {"exam_notices", "question_bank_lookup"} <= set(agent_tools.TEACHER_TOOLS)


def test_v2_dispatch_reaches_every_tool(monkeypatch):
    seen: dict[str, tuple] = {}

    def fake(name):
        def _fn(*args, **kwargs):
            seen[name] = (args, kwargs)
            return {"tool": name}
        return _fn

    for name in _NEW_TOOLS_V2:
        monkeypatch.setattr(agent_tools, name, fake(name), raising=True)
    for name in _NEW_TOOLS_V2:
        agent_graph._dispatch(_student(), name, {})
    assert set(seen) == set(_NEW_TOOLS_V2)


def _plan_v2(query: str):
    plan = agent_graph.plan_node({"ctx": _student(), "query": query, "history": []})
    args = dict((plan.get("plan") or {}).get("args") or {})
    return plan["tool_name"], args


def test_v2_student_routing():
    assert _plan_v2("面试一般会问什么")[0] == "question_bank_lookup"
    assert _plan_v2("我模拟面试成绩怎么样")[0] == "my_interviews"
    tool, _ = _plan_v2("最近有什么招考公告")
    assert tool == "exam_notices", "「招考公告」要命中 exam_notices，不能被 my_notices 抢走"
    # 原有路由不被破坏
    assert _plan_v2("我的预警情况") == ("my_warning", {})
    assert _plan_v2("帮我推荐几个岗位")[0] == "my_recommendations"


def test_v2_exam_args_from_words():
    tool, args = _plan_v2("最新的国考公告有哪些")
    assert tool == "exam_notices" and args.get("exam_type") == "civil"
    tool, args = _plan_v2("考研的招考公告")
    assert tool == "exam_notices" and args.get("exam_type") == "postgraduate"


def test_v2_bank_query_extract():
    tool, args = _plan_v2('面试题库里搜"数据分析"的题')
    assert tool == "question_bank_lookup" and args.get("query") == "数据分析"


@DB_OK
def test_exam_notices_real_and_goal_words():
    ctx = _student()
    r = agent_tools.exam_notices(ctx, limit=5)
    assert r["capability_version"] == "agent-entry-v2"
    assert r["notice_total"] >= 0 and isinstance(r["items"], list)
    # 口语词归一：传「考公」落到 civil
    r2 = agent_tools.exam_notices(ctx, exam_type="考公", limit=5)
    assert r2["exam_type"] == "civil"
    assert all(it.get("exam_type") == "civil" for it in r2["items"])
    # 不认识的类型要报错，不能静默吞掉意图
    with pytest.raises(ValueError):
        agent_tools.exam_notices(ctx, exam_type="火星考试")
    # 查无就返回空，不编公告
    r3 = agent_tools.exam_notices(ctx, keyword="绝对不存在の公告XYZ", limit=5)
    assert r3["notice_total"] == 0 and r3["items"] == []


@DB_OK
def test_my_interviews_student_only():
    r = agent_tools.my_interviews(_student(), limit=5)
    assert r["count"] == len(r["items"]) and r["finished_count"] <= r["count"]
    with pytest.raises(PermissionError):
        agent_tools.my_interviews(_teacher())


def test_question_bank_lookup_hits_and_filters():
    ctx = _student()
    r = agent_tools.question_bank_lookup(ctx, limit=5)
    assert r["bank_total"] >= 200
    for h in r["hits"]:
        assert h.get("source_url") or h.get("source_name"), "每条题必须带出处"
    # 中文行业词归一
    r2 = agent_tools.question_bank_lookup(ctx, family="计算机软件", limit=10)
    assert r2["family"] == "it_software"
    assert all(h["family"] == "it_software" for h in r2["hits"])
    with pytest.raises(ValueError):
        agent_tools.question_bank_lookup(ctx, qtype="not_a_qtype")
    r3 = agent_tools.question_bank_lookup(ctx, query="绝对不存在の题目XYZ")
    assert r3["hits"] == []
    # 教师也能用
    assert len(agent_tools.question_bank_lookup(_teacher(), limit=3)["hits"]) <= 3


# ----------------------------------------------------------------
# 5.1 agent-entry-v3：国考职位表（逐职位明细）
# ----------------------------------------------------------------
def test_v3_exam_positions_registered_everywhere():
    assert "exam_positions" in auto_plan.EXECUTABLE
    assert "exam_positions" in {t.name for t in auto_plan._TEACHER_TOOLS}
    assert "exam_positions" in {t.name for t in auto_plan._STUDENT_TOOLS}
    assert "exam_positions" in agent_tools.TEACHER_TOOLS
    assert "exam_positions" in agent_tools.STUDENT_TOOLS


def test_v3_dispatch_and_routing(monkeypatch):
    seen: dict[str, tuple] = {}

    def fake(*args, **kwargs):
        seen["exam_positions"] = (args, kwargs)
        return {"tool": "exam_positions"}

    monkeypatch.setattr(agent_tools, "exam_positions", fake, raising=True)
    agent_graph._dispatch(_student(), "exam_positions", {})
    assert "exam_positions" in seen

    tool, args = _plan_v2("国考职位表里重庆有哪些岗位")
    assert tool == "exam_positions" and args.get("place") == "重庆"
    # 只问公告仍归 exam_notices，不被职位表抢走
    assert _plan_v2("国考公告有哪些")[0] == "exam_notices"
    # 教师端确定性路由也能命中
    plan = agent_graph.plan_node(
        {"ctx": _teacher(), "query": "国考职位表里有哪些税务岗位", "history": []})
    assert plan["tool_name"] == "exam_positions"


@DB_OK
def test_exam_positions_real_and_empty():
    r = agent_tools.exam_positions(_student(), place="重庆", education="本科", limit=3)
    assert r["year"] == 2027
    assert r["position_total"] > 0 and r["total_headcount"] > 0
    assert len(r["positions"]) == 3
    assert all("重庆" in p["work_place"] for p in r["positions"])
    assert all("本科" in p["education"] for p in r["positions"])
    # 查无如实报：空列表 + note，不拿往年凑数
    r2 = agent_tools.exam_positions(_student(), keyword="绝对不存在の职位XYZ")
    assert r2["position_total"] == 0 and r2["positions"] == [] and r2["note"]
    # 师生通用（公共数据）
    assert agent_tools.exam_positions(_teacher(), limit=2)["year"] == 2027


def test_draft_v3_positions():
    result = {
        "year": 2027, "position_total": 2, "total_headcount": 3,
        "positions": [{"dept_name": "A部门", "bureau": "B司局",
                       "position_name": "P职位", "headcount": 2,
                       "education": "本科", "work_place": "重庆"}],
    }
    draft = agent_graph._template_draft(result)
    assert "2" in draft and "A部门" in draft and "P职位" in draft
    empty = agent_graph._template_draft(
        {"year": 2027, "position_total": 0, "total_headcount": 0,
         "positions": [], "note": "没有匹配职位"})
    assert "没有匹配职位" in empty


# ----------------------------------------------------------------
# 6. 模板稿：新工具结果的原样直引（Critic 校验兜底也要可读）
# ----------------------------------------------------------------
def test_draft_v2_grades_and_forecast_and_career():
    grades = {"summary": {"term_count": 8, "record_count": 48,
                          "weighted_avg": 76.12, "failed_count": 2},
              "years": [], "student": {"name": "吴强"}}
    d = agent_graph._template_draft(grades)
    assert "48" in d and "76.12" in d and "吴强" in d

    fc = {"available": True, "next_term": "2026-2027-1",
          "gpa_forecast": {"predicted": 78.27, "low": 70.91, "high": 85.64,
                           "trend": "下降", "confidence": "高"},
          "fail_forecast": {"predicted": 0}, "level_forecast": {"level": "正常"}}
    d1 = agent_graph._template_draft(fc)
    assert "78.27" in d1 and "2026-2027-1" in d1

    career = {"available": True, "goal_label": "考公",
              "composite": {"score": 55.1, "tier": "C", "tier_label": "C 档"},
              "dimensions": []}
    d2 = agent_graph._template_draft(career)
    assert "55.1" in d2 and "考公" in d2 and "不是录取概率" in d2


def test_draft_v2_exam_bank_interviews():
    ex = {"notice_total": 1, "items": [{"title": "T", "org_name": "U",
                                        "signup_end": "2026-01-01"}]}
    assert "T" in agent_graph._template_draft(ex)
    assert "不拿往年凑数" in agent_graph._template_draft({"notice_total": 0, "items": []})
    bank = {"bank_total": 234, "hits": [{"question": "Q", "family": "it_software",
                                         "qtype": "project", "source_name": "牛客网"}]}
    assert "234" in agent_graph._template_draft(bank)
    iv = {"count": 2, "finished_count": 1, "best_total": 61.5,
          "items": [{"job_title": "数据分析", "status": "finished", "cur_round": 6,
                     "max_round": 6, "total": 61.5}]}
    assert "61.5" in agent_graph._template_draft(iv)
    d = agent_graph._template_draft({"needs_intent": True, "reason": "还没选方向。"})
    assert "还没选方向" in d


# ----------------------------------------------------------------
# 6. 词表冲突回归：新工具不能抢走既有路由，也不能被既有工具抢
# ----------------------------------------------------------------
def _teacher_fixtures() -> tuple[ToolContext, str, str]:
    """取该教师第一个任教班级与该班第一个学生的学号（用来构造点名到人的问法）。"""
    ctx = _teacher()
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT `班级` AS c FROM `教师任教班级` "
                        "WHERE `租户编号`=%s AND `教师编号`=%s ORDER BY `班级`",
                        (ctx.tenant_id, ctx.teacher_id))
            rows = cur.fetchall()
            class_name = str(rows[0]["c"]) if rows else ""
            cur.execute("SELECT `学号` AS no FROM `学生` WHERE `租户编号`=%s AND `班级`=%s"
                        " ORDER BY `学号` LIMIT 1", (ctx.tenant_id, class_name))
            row = cur.fetchone() if class_name else None
    finally:
        conn.close()
    return ctx, class_name, (str(row["no"]) if row else "")


@DB_OK
def test_class_rank_keywords_do_not_hijack_existing_routes():
    """班级排名新增「排名 / 平均成绩」等词后，不能抢走预警、画像、成绩单这些既有路由。

    真实踩过的坑：加了「平均成绩」后，「AI20230001 的平均成绩」被班级统计接走，
    答成全班均分——问的是这个人，统计的却是全班。所以点名到人时班级统计要让位；
    但真在问名次时又不能让位，因为个人名次只存在于班级排名里，成绩单没有名次字段。
    """
    ctx, class_name, student_no = _teacher_fixtures()
    if not class_name or not student_no:
        pytest.skip("缺少班级或学生数据，跳过路由冲突回归")

    cases = [
        # 既有路由：一条都不该被新词抢走
        ("预警阈值是多少", "warning_thresholds"),
        (f"{class_name} 的预警名单", "warning_list"),
        ("这个学生的画像", "student_profile"),
        (f"{class_name} 的能力差距", "career_gap"),
        (f"{student_no} 的成绩单", "student_grades"),
        ("会了 Python 能做什么", "kg_skill_jobs"),
        # 新工具：班级级问法必须命中
        (f"{class_name} 的班级排名", "class_grades_rank"),
        (f"{class_name} 全班平均成绩", "class_grades_rank"),
        # 点名到人：问个人成绩归成绩单，问名次仍归班级排名
        (f"{student_no} 的平均成绩", "student_grades"),
        (f"{student_no} 排第几", "class_grades_rank"),
    ]
    wrong = []
    for question, want in cases:
        got = _plan(ctx, question)
        if got != want:
            wrong.append((question, want, got))
    assert not wrong, f"以下问法路由不符预期（问法 / 期望 / 实际）: {wrong}"


# ----------------------------------------------------------------
# 7. 联网搜索：没密钥时如实说，不能让模型润色成「知识库里没有」
# ----------------------------------------------------------------
def test_web_search_without_key_says_so(monkeypatch):
    """没配搜索密钥时，回答必须直说「没有配置联网搜索」。

    修过的坑：联网和知识库共用 RAG 提示词，那条提示词要求「原文没说就答
    「知识库里没有相关规定」」，于是「没联网」被模型说成「知识库里没有」，
    用户以为搜过了，其实是没网。空结果一律走模板，不让模型润色。
    """
    import engine.web_search as web_engine

    monkeypatch.setattr(
        web_engine, "search",
        lambda *a, **k: {"configured": False, "provider": None, "results": [],
                         "error": "未配置联网搜索密钥", "engine_version": "web-v1"})
    ctx = _teacher()
    result = agent_graph.run_chat(ctx, "联网查一下最新的公开招聘信息")
    assert result["tool_name"] == "web_search", "没路由到联网搜索"
    assert "没有配置联网搜索" in result["answer"], (
        f"没密钥时应明说原因，实际回答：{result['answer']}")


def test_web_search_provider_picks_bocha(monkeypatch):
    """只配博查密钥时 provider 要能选中它（国内可直连的那家）。

    别家在境外，国内网络连不上；博查是后来补的适配层，容易漏进优先级判断。
    """
    import engine.web_search as web_engine

    for name in ("SERPER_API_KEY", "BING_SEARCH_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("BOCHA_API_KEY", "ak-unit-test-only")
    assert web_engine.provider() == "bocha"

    monkeypatch.delenv("BOCHA_API_KEY", raising=False)
    assert web_engine.provider() is None, "一个密钥都没有时应诚实降级"


# ----------------------------------------------------------------
# 7. 注册表守卫（反向）：能分发的工具必须有归属
# ----------------------------------------------------------------
# 这几类工具不进「数据工具注册表」：外部检索、工作流、闲聊、阈值配置，
# 它们不对应某个板块的数据取数，归属由各自模块管。
_NON_DATA_TOOLS = {"kb_search", "web_search", "run_workflow", "chitchat",
                   "warning_thresholds"}


def test_every_dispatchable_tool_is_registered():
    """反向断言：graph._dispatch 能认的名字，必须在 TEACHER_TOOLS / STUDENT_TOOLS 里。

    只测正向（注册了的都在三处）会漏人：class_grades_rank 当初分发、词表、
    auto_plan 三处都接了，唯独 TEACHER_TOOLS 漏了，正向断言完全看不见它——
    而 AGENTS.md §3 要求「工具注册表、分发、auto_plan 三处必须同步」。
    """
    import re
    from pathlib import Path

    source = Path(agent_graph.__file__).read_text(encoding="utf-8")
    dispatched = set(re.findall(r'name == "([a-z_]+)"', source))
    registered = set(agent_tools.TEACHER_TOOLS) | set(agent_tools.STUDENT_TOOLS)
    missing = sorted(dispatched - registered - _NON_DATA_TOOLS)
    assert not missing, f"这些工具能分发但没登记进注册表：{missing}"


def test_class_rank_registered_everywhere():
    """class_grades_rank 与 exam_positions 一样，三处同步缺一不可。"""
    assert "class_grades_rank" in agent_tools.TEACHER_TOOLS
    assert "class_grades_rank" in {t.name for t in auto_plan._TEACHER_TOOLS}
    assert "class_grades_rank" in auto_plan.EXECUTABLE
    assert "class_grades_rank" not in agent_tools.STUDENT_TOOLS, "排名是教师口径，不给学生端"


def test_draft_class_rank_reads_engine_values_only():
    """排名结果不能落进「班级概览」的形状分支：那里会输出 None 个班 / 平均绩点 None。"""
    result = {
        "engine_version": "grades-rank-v1", "term": "2024-2025-1",
        "class_name": "AI2301", "headcount": 41, "scope": "assigned",
        "classes": [{"class_name": "AI2301", "student_cnt": 41, "graded_cnt": 40,
                     "weighted_avg": 78.4, "avg_score": 77.9,
                     "max_weighted_avg": 92.1, "min_weighted_avg": 58.3}],
        "class_rank_in_major": [{"major": "人工智能", "class_name": "AI2301",
                                 "student_cnt": 41, "graded_cnt": 40,
                                 "weighted_avg": 78.4, "rank": 2, "rank_total": 3}],
        "students": [{"student_no": "AI2023001", "name": "张三",
                      "class_rank": 3, "class_rank_total": 40,
                      "major_rank": 7, "major_rank_total": 120,
                      "weighted_avg": 85.2}],
    }
    draft = agent_graph._template_draft(result)
    assert "None" not in draft, f"模板稿里出现了 None：{draft}"
    for value in ("78.4", "77.9", "85.2", "第 2 / 3", "班内第 3/40", "同专业第 7/120"):
        assert value in draft, f"模板稿缺引擎值 {value}：{draft}"
    assert "本租户共" not in draft, "排名结果被当成班级概览了"
