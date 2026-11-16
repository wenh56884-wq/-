# tests/test_elective.py
# 职责：技能缺口选课推荐——引擎纯函数/取数隔离/智能体数值回查与白名单/工具注册守卫。
# 依赖：pytest / engine.elective / agents.elective（DB 与 LLM 全部 monkeypatch，离线可跑）。
# 说明：守住铁律 1（数值只出自引擎）、铁律 2（身份只用 ctx）、铁律 3（租户过滤在 SQL）。

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402

from agents import auto_plan  # noqa: E402
from agents import elective as elective_agent  # noqa: E402
from agents import graph as agent_graph  # noqa: E402
from agents import tools as agent_tools  # noqa: E402
from agents.critic import MAX_RETRY, verify  # noqa: E402
from agents.tools import ToolContext  # noqa: E402
from engine import career_guide as guide_engine  # noqa: E402
from engine import elective as eng  # noqa: E402
from engine import hybrid as hybrid_engine  # noqa: E402
from engine import recommend as rec  # noqa: E402

TERM = "2025-2026-2"

_POLICY = eng.load_policy()
_WINDOW = eng.window_status(_POLICY, datetime(2026, 11, 16))
_GENED = eng.gened_status(cohort=2026, major="软件工程",
                          taken_names=["数据挖掘实践"], policy=_POLICY)
_CREDITS = eng.credit_budget(earned_credits=83.5, elected_credits=2.0, policy=_POLICY)

FACTS: dict = {
    "student_no": "S001", "term": TERM, "engine_version": "elective-v2",
    "major": "软件工程", "gpa": 88.0,
    "taken_courses": ["数据挖掘实践"], "elected_directions": ["算法"],
    "target": {"job_id": 101, "title": "Java 后端开发工程师", "company": "示例科技",
               "direction": "后端", "directions": ["后端"],
               "required": ["Java", "SQL", "数据挖掘"], "source": "hybrid_top"},
    "required": ["Java", "SQL", "数据挖掘"],
    "covered": ["数据挖掘"],
    "skill_gaps": ["Java", "SQL"],
    "coverage": 0.3333,
    "recommendations": [
        {"name": "Java 程序设计", "direction": "后端", "credit": 3.0,
         "fills": ["Java"], "skills": ["Java", "编程基础"], "score": 0.65,
         "reason": "可补 1 项技能缺口（Java）；选修/浏览方向命中 后端"},
    ],
    "pool_total": 42,
    "note": "技能覆盖按已修课程与已选选修课全学期累计计算。",
    "policy": {"version": _POLICY["version"], "source": _POLICY["source"],
               "rules": list(_POLICY["rules"]), "entry": _POLICY["entry"],
               "equivalence": _POLICY["equivalence"],
               "min_students": _POLICY["min_students"],
               "start_week": _POLICY["start_week"],
               "withdraw_penalty_terms": _POLICY["withdraw_penalty_terms"]},
    "window": _WINDOW, "gened": _GENED, "credits": _CREDITS,
}

VALID_REPLY = (
    "你的技能覆盖 1/3，当前缺口：Java、SQL。建议先选修「Java 程序设计」"
    "（3.0学分，得分 0.65），可补 1 项技能缺口（Java）。"
    "\n【选课方案】\n{\"courses\": [\"Java 程序设计\"]}"
)


def _student_ctx() -> ToolContext:
    return ToolContext(actor_type="student", tenant_id=7, student_id=42, term=TERM)


# ----------------------------------------------------------------
# 1. 引擎纯函数：打分确定性 / 排除 / 排序 / 缺口翻转不变量
# ----------------------------------------------------------------
def test_score_elective_hand_computed_and_deterministic():
    assert eng.score_elective(2, 3, 1.0) == round(0.7 * 2 / 3 + 0.3, 4) == 0.7667
    assert eng.score_elective(2, 3, 1.0) == eng.score_elective(2, 3, 1.0)
    assert eng.score_elective(0, 3, 1.0) == 0.0
    assert eng.score_elective(2, 0, 1.0) == 0.0


def test_fills_of_reuses_recommend_hit():
    assert eng.fills_of("Java 程序设计", ["Java", "SQL"]) == ["Java"]
    assert eng.fills_of("体育欣赏", ["Java", "SQL"]) == []


def test_rank_excludes_taken_normalized():
    pool = {"后端": [{"name": "Java 程序设计", "credit": 3.0}]}
    recs = eng.rank_electives(pool, ["Java"], ["后端"], ["  JAVA 程序设计 "])
    assert recs == [], "已修/已选课程（大小写空格归一后）必须排除"


def test_rank_drops_zero_fill_and_sorts():
    pool = {
        "后端": [{"name": "Java 程序设计", "credit": 3.0},
                 {"name": "Java 高级编程", "credit": 2.0}],
        "设计": [{"name": "体育欣赏", "credit": 1.0}],
    }
    recs = eng.rank_electives(pool, ["Java"], ["后端"], [])
    assert [r["name"] for r in recs] == ["Java 高级编程", "Java 程序设计"], \
        "同分按学分升序；补不了缺口的课不推荐"
    assert all(r["score"] == 1.0 for r in recs)
    assert eng.rank_electives(pool, ["Java"], ["后端"], []) == recs, "同输入必得同输出"


def test_rank_name_tiebreak():
    pool = {"后端": [{"name": "Java B", "credit": 2.0}, {"name": "Java A", "credit": 2.0}]}
    recs = eng.rank_electives(pool, ["Java"], ["后端"], [])
    assert [r["name"] for r in recs] == ["Java A", "Java B"]


def test_gap_flip_invariant():
    """推荐课名加入技能证据后，它声称能补的缺口必须真的翻转（同一词面口径）。"""
    required = ["Java", "数据挖掘", "SQL"]
    taken = ["数据挖掘实践"]
    _cov0, _hits0, gaps0 = rec.skill_cover_of(taken, required)
    recs = eng.rank_electives(eng.load_pool(), gaps0, ["后端", "算法"], taken)
    assert recs, "课池里应有能补 Java/数据挖掘 缺口的课"
    for r in recs:
        _cov1, _hits1, gaps1 = rec.skill_cover_of(taken + [r["name"]], required)
        assert all(f not in gaps1 for f in r["fills"]), \
            f"{r['name']} 声称补 {r['fills']}，但缺口未翻转：{gaps1}"


def test_aggregate_required_tags_freq_order_and_welfare():
    jobs = [{"skill_tags": ["Java", "SQL", "五险一金"]},
            {"skill_tags": ["Java", "Python"]}]
    assert eng.aggregate_required_tags(jobs, top_k=3) == ["Java", "Python", "SQL"]
    assert "五险一金" not in eng.aggregate_required_tags(jobs, top_k=8)
    assert eng.aggregate_required_tags([], top_k=8) == []


def test_template_advice_quotes_facts_and_passes_critic():
    draft = eng.template_advice(FACTS)
    assert "None" not in draft
    assert "1/3" in draft and "0.65" in draft and "3.0" in draft
    assert "选课窗口" in draft and "剩余 74.5" in draft, "政策块必须直引进降级稿"
    assert "http://jwmis.cfec.edu.cn" in draft
    assert verify(draft, FACTS).passed, "降级模板稿必须能过 critic 数值回查"


# ----------------------------------------------------------------
# 2. 引擎入口：租户隔离 / 目标两来源 / 空数据降级（DB 全 mock）
# ----------------------------------------------------------------
def _patch_db(monkeypatch, *, electives=(), completed=(), job_tags=(),
              student=None, hybrid_items=(), jobs=(), earned=0.0):
    calls: list[tuple[str, tuple]] = []

    def fake_query(sql, params=()):
        calls.append((sql, tuple(params)))
        if "选课记录" in sql:
            return [dict(e) for e in electives]
        if "earned" in sql:
            return [{"earned": earned}]
        if "成绩" in sql:
            return [{"name": n} for n in completed]
        if "岗位" in sql:
            return [{"skill_tags": list(job_tags)}]
        return []

    monkeypatch.setattr(eng, "_query", fake_query)
    monkeypatch.setattr(rec, "load_student",
                        lambda *a, **k: dict(student or {"major": "", "gpa": None,
                                                         "directions": []}))
    monkeypatch.setattr(hybrid_engine, "hybrid_recommend",
                        lambda *a, **k: {"items": [dict(i) for i in hybrid_items]})
    monkeypatch.setattr(rec, "load_jobs", lambda *a, **k: [dict(j) for j in jobs])
    return calls


def test_entry_filters_tenant_in_sql(monkeypatch):
    calls = _patch_db(
        monkeypatch,
        electives=[{"name": "数据挖掘实践", "direction": "算法", "term": TERM, "credit": 2.0}],
        completed=["Java 程序设计"],
        hybrid_items=[{"job_id": 101, "title": "Java 后端开发工程师",
                       "company": "示例科技", "direction": "后端"}],
        job_tags=["Java", "SQL"])
    eng.elective_advice_for_student(7, 42, "S042", TERM)
    elective_sqls = [s for s, _p in calls if "选课记录" in s]
    grade_sqls = [s for s, _p in calls if "成绩" in s]
    assert elective_sqls and all("租户编号" in s for s in elective_sqls)
    assert grade_sqls and all("租户编号" in s for s in grade_sqls)
    assert all(p[0] == 7 for _s, p in calls if "选课记录" in _s or "成绩" in _s)


def test_entry_hybrid_top_target(monkeypatch):
    _patch_db(
        monkeypatch,
        hybrid_items=[{"job_id": 101, "title": "Java 后端开发工程师",
                       "company": "示例科技", "direction": "后端"}],
        job_tags=["Java", "SQL"],
        student={"major": "软件工程", "gpa": 88.0, "directions": ["后端"]})
    out = eng.elective_advice_for_student(7, 42, "S042", TERM)
    assert out["target"]["source"] == "hybrid_top"
    assert out["required"] == ["Java", "SQL"]
    assert out["skill_gaps"] == ["Java", "SQL"]
    assert out["recommendations"][0]["name"] == "Java 程序设计"
    assert out["recommendations"][0]["score"] == 0.65


def test_entry_direction_aggregate_fallback(monkeypatch):
    _patch_db(
        monkeypatch,
        electives=[{"name": "数据挖掘实践", "direction": "算法", "term": TERM, "credit": 2.0}],
        hybrid_items=[],
        jobs=[{"skill_tags": ["Java", "SQL", "五险一金"]},
              {"skill_tags": ["Java", "Python"]}])
    out = eng.elective_advice_for_student(7, 42, "S042", TERM)
    assert out["target"]["source"] == "direction_aggregate"
    assert out["target"]["directions"] == ["算法"]
    assert out["required"] == ["Java", "Python", "SQL"]
    assert "聚合" in out["note"]


def test_entry_no_data_returns_empty_with_note(monkeypatch):
    _patch_db(monkeypatch)
    out = eng.elective_advice_for_student(7, 42, "S042", TERM)
    assert out["recommendations"] == []
    assert out["target"]["source"] == ""
    assert out["note"], "查无数据必须如实给 note，不编造"


def test_entry_full_cover_no_recommendation(monkeypatch):
    _patch_db(
        monkeypatch,
        completed=["Java 程序设计"],
        hybrid_items=[{"job_id": 101, "title": "Java 后端开发工程师",
                       "company": "示例科技", "direction": "后端"}],
        job_tags=["Java"])
    out = eng.elective_advice_for_student(7, 42, "S042", TERM)
    assert out["skill_gaps"] == []
    assert out["coverage"] == 1.0
    assert out["recommendations"] == []
    assert "已全部覆盖" in out["note"]


# ----------------------------------------------------------------
# 3. 智能体节点：数值回查 / 白名单 / 降级（LLM 全 mock）
# ----------------------------------------------------------------
def _patch_agent(monkeypatch, reply, facts=None):
    calls: list[str] = []

    def fake_generate(actor_type, *, system_prompt, user_prompt, tag, **kw):
        calls.append(tag)
        return reply() if callable(reply) else reply

    monkeypatch.setattr(elective_agent.engine_elective, "elective_advice_for_student",
                        lambda *a, **k: dict(facts if facts is not None else FACTS))
    monkeypatch.setattr(elective_agent.llm_module, "generate_reply", fake_generate)
    return calls


def test_advise_valid_reply_passes_critic_and_whitelist(monkeypatch):
    calls = _patch_agent(monkeypatch, VALID_REPLY)
    out = elective_agent.advise(7, 42, "S001", TERM)
    assert out["degraded"] is False
    assert out["critic"]["passed"] is True
    assert out["plan"]["courses"][0]["name"] == "Java 程序设计"
    assert out["plan"]["rejected"] == []
    assert calls == ["elective.advise"], "合格稿不应触发重写"


def test_advise_fabricated_number_retries_then_degrades(monkeypatch):
    bad = "你的技能覆盖率高达 99%，远超同学。建议选修「Java 程序设计」。"
    calls = _patch_agent(monkeypatch, bad)
    out = elective_agent.advise(7, 42, "S001", TERM)
    assert out["degraded"] is True
    assert out["reason"] == "critic_rejected"
    assert out["critic"]["retries"] == MAX_RETRY
    assert len(calls) == MAX_RETRY + 1
    assert out["reply"] == eng.template_advice(FACTS), "超限必须降级为引擎模板稿"


def test_advise_unknown_course_rejected(monkeypatch):
    reply = (VALID_REPLY.split("【选课方案】")[0]
             + "\n【选课方案】\n{\"courses\": [\"Java 程序设计\", \"量子波动速读\"]}")
    _patch_agent(monkeypatch, reply)
    out = elective_agent.advise(7, 42, "S001", TERM)
    assert [c["name"] for c in out["plan"]["courses"]] == ["Java 程序设计"]
    assert out["plan"]["rejected"] == ["量子波动速读"]


def test_advise_llm_unavailable_degrades(monkeypatch):
    _patch_agent(monkeypatch, None)
    out = elective_agent.advise(7, 42, "S001", TERM)
    assert out["degraded"] is True
    assert out["reason"] == "llm_unavailable"
    assert out["reply"] == eng.template_advice(FACTS)


def test_advise_no_data_skips_llm(monkeypatch):
    empty = {**FACTS, "target": {**FACTS["target"], "source": ""},
             "required": [], "covered": [], "skill_gaps": [], "recommendations": []}
    calls = _patch_agent(monkeypatch, VALID_REPLY, facts=empty)
    out = elective_agent.advise(7, 42, "S001", TERM)
    assert calls == [], "无数据时不该调用大模型"
    assert out["reason"] == "no_data"


def test_advise_no_gap_skips_llm(monkeypatch):
    full = {**FACTS, "skill_gaps": [], "covered": FACTS["required"], "coverage": 1.0}
    calls = _patch_agent(monkeypatch, VALID_REPLY, facts=full)
    out = elective_agent.advise(7, 42, "S001", TERM)
    assert calls == []
    assert out["reason"] == "no_gap"


# ----------------------------------------------------------------
# 4. 工具层：身份只用 ctx / 教师拒绝 / 注册守卫 / 路由 / 模板稿
# ----------------------------------------------------------------
def test_tool_uses_ctx_identity_only(monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(agent_tools, "write_audit", lambda **kw: None)
    monkeypatch.setattr(agent_tools, "_resolve_term", lambda ctx, term: TERM)
    monkeypatch.setattr(agent_tools, "_resolve_self",
                        lambda ctx, action: {"student_no": "S042", "student_id": ctx.student_id})

    def fake_engine(tenant_id, student_id, student_no, term, top_n=8, **kw):
        seen.update(tenant_id=tenant_id, student_id=student_id,
                    student_no=student_no, term=term, top_n=top_n,
                    enroll_year=kw.get("enroll_year"))
        return dict(FACTS)

    monkeypatch.setattr(eng, "elective_advice_for_student", fake_engine)
    out = agent_tools.my_elective_advice(_student_ctx(), term=None, top_n=5)
    assert seen == {"tenant_id": 7, "student_id": 42, "student_no": "S042",
                    "term": TERM, "top_n": 5, "enroll_year": None}
    assert out["student_no"] == "S001"


def test_tool_teacher_denied(monkeypatch):
    monkeypatch.setattr(agent_tools, "write_audit", lambda **kw: None)
    ctx = ToolContext(actor_type="teacher", tenant_id=7, teacher_id=1)
    with pytest.raises(PermissionError):
        agent_tools.my_elective_advice(ctx)
    with pytest.raises(PermissionError):
        agent_tools.elective_advise(ctx)


def test_my_elective_advice_registered_everywhere():
    assert "my_elective_advice" in agent_tools.STUDENT_TOOLS
    assert "my_elective_advice" not in agent_tools.TEACHER_TOOLS
    assert "my_elective_advice" in {t.name for t in auto_plan._STUDENT_TOOLS}
    assert "my_elective_advice" not in {t.name for t in auto_plan._TEACHER_TOOLS}
    assert "my_elective_advice" in auto_plan.EXECUTABLE


def test_my_elective_advice_dispatch_reachable(monkeypatch):
    seen: dict = {}

    def fake(ctx, term=None, top_n=8):
        seen.update(term=term, top_n=top_n)
        return dict(FACTS)

    monkeypatch.setattr(agent_tools, "my_elective_advice", fake)
    agent_graph._dispatch(_student_ctx(), "my_elective_advice",
                          {"term": TERM, "top_n": 5})
    assert seen == {"term": TERM, "top_n": 5}


def test_elective_routing():
    ctx = _student_ctx()

    def plan(query):
        return agent_graph.plan_node({"ctx": ctx, "query": query, "history": []})["tool_name"]

    assert plan("我选什么课能补技能缺口") == "my_elective_advice"
    assert plan("选修课有什么推荐") == "my_elective_advice"
    assert plan("我的技能缺口怎么补") == "my_elective_advice"
    assert plan("给我推荐岗位") == "my_recommendations", "岗位推荐不能被选课路由抢走"
    assert plan("我的成绩怎么样") == "my_grades", "成绩路由回归"


def test_draft_elective_quotes_engine_values():
    draft = agent_graph._template_draft(FACTS)
    assert "None" not in draft
    assert "技能覆盖 1/3" in draft
    assert "Java 程序设计" in draft and "0.65" in draft and "3.0" in draft
    assert verify(draft, FACTS).passed, "模板稿必须能过 critic"


def test_draft_elective_empty_shows_note():
    empty = {**FACTS, "target": {**FACTS["target"], "source": ""},
             "required": [], "covered": [], "skill_gaps": [], "recommendations": []}
    draft = agent_graph._template_draft(empty)
    assert draft == FACTS["note"]


# ----------------------------------------------------------------
# 5. 政策层：窗口三态 / 通识模块豁免与词面口径 / 学分预算 / 租户 SQL
# ----------------------------------------------------------------
def test_window_status_three_states():
    before = eng.window_status(_POLICY, datetime(2026, 10, 20))
    open_ = eng.window_status(_POLICY, datetime(2026, 10, 23))
    closed = eng.window_status(_POLICY, datetime(2026, 11, 16))
    assert (before["state"], open_["state"], closed["state"]) == ("before", "open", "closed")
    assert "10月22日10:30" in open_["text"] and "10月25日24:00" in open_["text"]
    assert "已结束" in closed["text"] and "催促" not in closed["text"]
    assert closed["term"] == "2026-2027-1"


def test_entry_window_applies_to_current_term(monkeypatch):
    _patch_db(monkeypatch)
    same = eng.elective_advice_for_student(7, 42, "S042", "2026-2027-1")
    other = eng.elective_advice_for_student(7, 42, "S042", TERM)
    assert same["window"]["applies_to_current_term"] is True
    assert other["window"]["applies_to_current_term"] is False


def test_gened_exemptions_by_major_category():
    eng_major = eng.gened_status(cohort=2026, major="空间信息与数字技术",
                                 taken_names=[], policy=_POLICY)
    assert eng_major["major_category"] == "engineering"
    assert eng_major["applicable"] is True
    assert "新财经素养教程" in eng_major["uncovered"], "工科必修新财经素养"
    assert "艺术欣赏与审美体验" in eng_major["uncovered"], "工科不豁免艺术模块"
    assert eng_major["exempted"] == []
    art = eng.gened_status(cohort=2026, major="播音与主持艺术",
                           taken_names=[], policy=_POLICY)
    assert art["major_category"] == "art"
    assert "艺术欣赏与审美体验" in art["exempted"]
    assert "新媒体电商素养课程" in art["exempted"]
    assert "新财经素养教程" in art["exempted"], "艺术类属非工科，豁免新财经素养"
    assert not set(art["exempted"]) & set(art["uncovered"])


def test_gened_keyword_precision_not_substring_noise():
    g = eng.gened_status(cohort=2026, major="软件工程",
                         taken_names=["人工智能基础", "劳动关系学"], policy=_POLICY)
    by_name = {m["name"]: m for m in g["modules"]}
    assert by_name["AI素养教程"]["covered"] is False, "人工智能基础 ≠ AI素养教程"
    assert by_name["大学生劳动教育"]["covered"] is False, "劳动关系学 ≠ 劳动教育"
    hit = eng.gened_status(cohort=2026, major="软件工程",
                           taken_names=["AI素养教程（线上）"], policy=_POLICY)
    assert {m["name"]: m for m in hit["modules"]}["AI素养教程"]["covered"] is True


def test_gened_cohort_scope_and_equivalence():
    g25 = eng.gened_status(cohort=2025, major="软件工程", taken_names=[], policy=_POLICY)
    assert g25["applicable"] is False
    assert "24级" in g25["note"] and "培养方案" in g25["note"]
    g_none = eng.gened_status(cohort=None, major="软件工程", taken_names=[], policy=_POLICY)
    assert g_none["applicable"] is False and "仅供参考" in g_none["note"]


def test_credit_budget_hand_computed_and_floor():
    c = eng.credit_budget(earned_credits=83.5, elected_credits=5.0, policy=_POLICY)
    assert c["total_required"] == 160.0 and c["remaining"] == 71.5
    assert c["structure"] == {"general": 48.0, "major": 72.0, "practice": 40.0}
    assert c["substitution_cap"] == 10.0
    assert "分类" in c["note"]
    over = eng.credit_budget(earned_credits=200.0, elected_credits=0.0, policy=_POLICY)
    assert over["remaining"] == 0.0


def test_load_earned_credits_sql_tenant_and_pass_mark(monkeypatch):
    seen: list[tuple[str, tuple]] = []
    monkeypatch.setattr(eng, "_query",
                        lambda sql, params=(): seen.append((sql, tuple(params)))
                        or [{"earned": 83.54}])
    assert eng.load_earned_credits(7, 42) == 83.5
    sql, params = seen[0]
    assert "租户编号" in sql and ">= 60" in sql and "DISTINCT" in sql
    assert params == (7, 42)


def test_entry_policy_blocks_on_both_paths(monkeypatch):
    _patch_db(monkeypatch, earned=83.5,
              electives=[{"name": "数据挖掘实践", "direction": "算法",
                          "term": TERM, "credit": 2.0}],
              hybrid_items=[{"job_id": 101, "title": "Java 后端开发工程师",
                             "company": "示例科技", "direction": "后端"}],
              job_tags=["Java", "SQL"],
              student={"major": "软件工程", "gpa": 88.0, "directions": ["后端"]})
    out = eng.elective_advice_for_student(7, 42, "AI20260004", TERM, enroll_year=2026)
    for key in ("policy", "window", "gened", "credits"):
        assert key in out, f"正常路径缺政策块 {key}"
    assert out["gened"]["applicable"] is True and out["gened"]["cohort"] == 2026
    assert out["credits"]["earned"] == 83.5 and out["credits"]["elected"] == 2.0
    assert out["credits"]["remaining"] == 74.5
    assert "通识必修模块尚未覆盖" in out["note"]
    _patch_db(monkeypatch)
    empty = eng.elective_advice_for_student(7, 42, "S042", TERM)
    for key in ("policy", "window", "gened", "credits"):
        assert key in empty, f"空数据路径缺政策块 {key}"


def test_cohort_of_db_first_then_student_no():
    assert eng.cohort_of(2025, "AI20260004") == 2025
    assert eng.cohort_of(None, "AI20260004") == 2026
    assert eng.cohort_of(None, "X001") is None


# ----------------------------------------------------------------
# 6. 生涯指南联动：草稿直引 + critic / 行动注入位置
# ----------------------------------------------------------------
def test_draft_guide_quotes_elective_and_passes_critic():
    guide = guide_engine.build_guide(grade="大二", intent="就业",
                                     direction="后端", major="软件工程", elective=FACTS)
    draft = agent_graph._template_draft(guide)
    assert "None" not in draft
    assert "Java 程序设计" in draft and "0.65" in draft
    assert "剩余 74.5" in draft and "选课窗口" in draft
    assert "2026级毕业前必修选修模块尚未覆盖" in draft
    assert "http://jwmis.cfec.edu.cn" in draft
    assert verify(draft, guide).passed, "指南草稿必须能过 critic 数值回查"


def test_draft_guide_needs_intent_still_links_elective():
    guide = guide_engine.build_guide(grade="大一", intent=None, elective=FACTS)
    draft = agent_graph._template_draft(guide)
    assert "请先选定方向" in draft
    assert "Java 程序设计" in draft and "剩余 74.5" in draft
    assert verify(draft, guide).passed


def test_draft_guide_elective_unavailable_shows_note():
    guide = guide_engine.build_guide(grade="大二", intent="就业")
    guide["elective"] = {"available": False, "note": "选课联动暂不可用：取数失败。"}
    draft = agent_graph._template_draft(guide)
    assert "选课联动暂不可用" in draft
    assert verify(draft, guide).passed