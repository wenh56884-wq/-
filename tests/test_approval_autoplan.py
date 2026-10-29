# tests/test_approval_autoplan.py
# 职责：覆盖三个新能力——① 工作流人工审批 ② 知识库多跳检索 ③ 自主规划（可切换）
# 说明：凡是需要建库记录的用例，都在 finally 里删干净，不留下演示脏数据。

from __future__ import annotations

import json
import uuid

import pymysql
import pytest

from agents import auto_plan
from agents import tools as agent_tools
from agents.tools import ToolContext
from app import workflow_approval as approval
from app.config import get_settings
from engine import workflow as wf_engine


def _conn():
    s = get_settings()
    return pymysql.connect(host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
                           password=s.mysql_password, database=s.mysql_db,
                           charset="utf8mb4", autocommit=True,
                           cursorclass=pymysql.cursors.DictCursor)


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
            cur.execute("SELECT `编号`,`租户编号` FROM `学生` WHERE `学号` LIKE 'AI2023%'"
                        " ORDER BY `学号` LIMIT 1")
            row = cur.fetchone()
    finally:
        conn.close()
    return ToolContext(actor_type="student", tenant_id=int(row["租户编号"]),
                       student_id=int(row["编号"]))


# ----------------------------------------------------------------
# ① 工作流审批
# ----------------------------------------------------------------
def test_pending_run_does_not_execute_any_step():
    """挂起态必须一步都不跑：否则「审批」就成了走过场。"""
    ctx = _teacher()
    name = f"审批测试-{uuid.uuid4().hex[:6]}"
    steps = [{"id": "s1", "tool": "class_list", "title": "班级目录"}]
    conn = _conn()
    def_id = None
    run_id = None
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO `工作流定义`(`租户编号`,`名称`,`步骤`,`创建人`,`是否需要审批`)"
                        " VALUES (%s,%s,%s,%s,1)",
                        (ctx.tenant_id, name, json.dumps(steps, ensure_ascii=False),
                         "teacher:test"))
            def_id = int(cur.lastrowid)

        assert approval.needs_approval(def_id, ctx.tenant_id) is True

        submitted = approval.submit_for_approval(ctx, def_id, name)
        run_id = int(submitted["run_id"])
        assert submitted["status"] == wf_engine.STATUS_PENDING

        with conn.cursor() as cur:
            cur.execute("SELECT `状态`,`步骤结果` FROM `工作流运行` WHERE `编号`=%s", (run_id,))
            row = cur.fetchone()
        assert row["状态"] == wf_engine.STATUS_PENDING
        assert row["步骤结果"] is None, "挂起阶段不该有任何步骤产出"

        pending = approval.list_pending(ctx)
        assert any(int(i["id"]) == run_id for i in pending["items"])
    finally:
        with conn.cursor() as cur:
            if run_id:
                cur.execute("DELETE FROM `工作流审批` WHERE `运行编号`=%s", (run_id,))
                cur.execute("DELETE FROM `工作流运行` WHERE `编号`=%s", (run_id,))
            if def_id:
                cur.execute("DELETE FROM `工作流定义` WHERE `编号`=%s", (def_id,))
        conn.close()


def test_reject_runs_nothing():
    """驳回 = 一步都不执行，而不是「跑完再说」。"""
    ctx = _teacher()
    name = f"审批驳回-{uuid.uuid4().hex[:6]}"
    steps = [{"id": "s1", "tool": "class_list", "title": "班级目录"}]
    conn = _conn()
    def_id = run_id = None
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO `工作流定义`(`租户编号`,`名称`,`步骤`,`创建人`,`是否需要审批`)"
                        " VALUES (%s,%s,%s,%s,1)",
                        (ctx.tenant_id, name, json.dumps(steps, ensure_ascii=False),
                         "teacher:test"))
            def_id = int(cur.lastrowid)
        run_id = int(approval.submit_for_approval(ctx, def_id, name)["run_id"])

        res = approval.decide(ctx, run_id, "reject", "这次不需要")
        assert res["status"] == wf_engine.STATUS_REJECTED
        assert res["steps"] == [], "驳回后不应产生任何步骤"

        # 一次运行只审一次
        with pytest.raises(approval.ApprovalError):
            approval.decide(ctx, run_id, "approve")
    finally:
        with conn.cursor() as cur:
            if run_id:
                cur.execute("DELETE FROM `工作流审批` WHERE `运行编号`=%s", (run_id,))
                cur.execute("DELETE FROM `工作流运行` WHERE `编号`=%s", (run_id,))
            if def_id:
                cur.execute("DELETE FROM `工作流定义` WHERE `编号`=%s", (def_id,))
        conn.close()


def test_student_cannot_approve():
    """审批权只在教师手里：学生调 decide 必须是 PermissionError。"""
    with pytest.raises(PermissionError):
        approval.decide(_student(), 1, "approve")


def test_needs_approval_is_false_for_unknown_definition():
    assert approval.needs_approval(99999999, 1) is False


def test_graph_draft_reports_pending_instead_of_fake_success():
    """待审批不能谎报「已执行」——这是最容易骗过演示的话术漏洞。"""
    from agents import graph as agent_graph

    draft = agent_graph._workflow_draft(
        {"status": "pending", "name": "求职体检",
         "summary": "工作流「求职体检」已提交，等待教师审批后执行。"})
    assert "已提交" in draft
    assert "已按工作流" not in draft


# ----------------------------------------------------------------
# ② 知识库多跳检索
# ----------------------------------------------------------------
def test_multihop_off_keeps_single_hop_shape(monkeypatch):
    """关掉开关时，多跳必须完全等价于单跳（返回结构不变）。"""
    monkeypatch.setenv("AGENT_KB_MULTIHOP", "0")
    ctx = _teacher()
    res = agent_tools.kb_search_deep(ctx, "学业预警管理办法", top_k=3)
    assert res["multi_hop"] is False
    assert len(res["hops"]) == 1
    assert {"query", "total", "hits", "citations"} <= set(res)


_HIT_A = {"doc_id": 9, "title": "学业预警与帮扶管理办法", "page": 1, "chunk_no": 1,
          "score": 0.5, "text": "累计挂科 6 门及以上为红色预警"}
_HIT_B = {"doc_id": 11, "title": "学籍与学分管理规定", "page": 2, "chunk_no": 1, "score": 0.3,
          "text": "补考仍不及格须重修"}


def _patch_search(monkeypatch, per_hop_results):
    """按调用次序返回检索结果（第 1 跳、第 2 跳…），并记录每次的入参。"""
    calls: list[dict] = []

    def fake(ctx, query="", top_k=4, doc_id=None):
        calls.append({"query": query, "top_k": top_k})
        idx = min(len(calls) - 1, len(per_hop_results) - 1)
        hits = list(per_hop_results[idx])
        return {"query": query, "total": len(hits), "hits": hits,
                "citations": [], "engine_version": "", "note": ""}

    monkeypatch.setattr(agent_tools, "kb_search", fake)
    return calls


def test_multihop_merges_new_hit_and_renumbers_citations(monkeypatch):
    """模型说不够 → 第二跳带回新块：合并去重，引用编号连续重排。"""
    monkeypatch.setenv("AGENT_KB_MULTIHOP", "1")
    calls = _patch_search(monkeypatch, [[_HIT_A], [_HIT_A, _HIT_B]])
    monkeypatch.setattr(agent_tools, "_judge_enough", lambda *a, **k: (False, "改写后的检索词"))

    res = agent_tools.kb_search_deep(_teacher(), "预警等级怎么定，挂科后怎么重修", top_k=4)
    assert len(calls) == 2, "模型判定不足就该再跳一次"
    assert res["total"] == 2, "A 重复、B 新增，合计应为 2 而不是 3"
    assert res["new_hits"] == 1
    assert res["multi_hop"] is True
    assert [c["no"] for c in res["citations"]] == [1, 2]
    assert [h["title"] for h in res["hits"]] == ["学业预警与帮扶管理办法", "学籍与学分管理规定"]


def test_multihop_does_not_duplicate_repeated_hits(monkeypatch):
    """第二跳只捞回重复块 → 不重复计入，不虚增命中数。"""
    monkeypatch.setenv("AGENT_KB_MULTIHOP", "1")
    _patch_search(monkeypatch, [[_HIT_A], [_HIT_A]])
    monkeypatch.setattr(agent_tools, "_judge_enough", lambda *a, **k: (False, "改写词"))

    res = agent_tools.kb_search_deep(_teacher(), "预警等级", top_k=4)
    assert res["total"] == 1
    assert res["new_hits"] == 0


def test_multihop_skips_when_model_says_enough(monkeypatch):
    """模型说够了 → 一次都不跳，不白白多花一次模型调用。"""
    monkeypatch.setenv("AGENT_KB_MULTIHOP", "1")
    calls = _patch_search(monkeypatch, [[_HIT_A]])
    monkeypatch.setattr(agent_tools, "_judge_enough", lambda *a, **k: (True, ""))

    res = agent_tools.kb_search_deep(_teacher(), "预警等级", top_k=4)
    assert len(calls) == 1
    assert res["multi_hop"] is False
    assert res["new_hits"] == 0


def test_multihop_expands_recall_on_later_hops(monkeypatch):
    """补跳要扩大召回：沿用同样的 top_k 会把第一跳那几块再捞一遍，等于白跳一次。"""
    monkeypatch.setenv("AGENT_KB_MULTIHOP", "1")
    calls = _patch_search(monkeypatch, [[_HIT_A], []])
    monkeypatch.setattr(agent_tools, "_judge_enough", lambda *a, **k: (False, "改写词"))

    agent_tools.kb_search_deep(_teacher(), "预警等级", top_k=4)
    assert [c["top_k"] for c in calls] == [4, 8]


def test_judge_falls_back_to_enough_on_broken_json(monkeypatch):
    """模型返回不是 JSON → 按「够了」处理，宁可少跳也不乱跳。"""
    import agents.llm as llm_client

    monkeypatch.setattr(llm_client, "generate_reply", lambda *a, **k: "这不是 JSON")
    enough, nxt = agent_tools._judge_enough(
        _teacher(), "预警等级",
        [{"title": "学业预警与帮扶管理办法", "text": "累计挂科 6 门及以上为红色预警"}])
    assert enough is True and nxt == ""


def test_judge_parses_valid_json(monkeypatch):
    """模型说不够 → 返回改写词，供第二跳使用。"""
    import agents.llm as llm_client

    monkeypatch.setattr(llm_client, "generate_reply",
                        lambda *a, **k: '{"enough": false, "query": "挂科 重修 学分"}')
    enough, nxt = agent_tools._judge_enough(_teacher(), "预警等级", [])
    assert enough is False
    assert nxt == "挂科 重修 学分"


def test_judge_unavailable_model_means_enough(monkeypatch):
    """模型不可用 → 按「够了」处理，不再多跳（不能因为模型挂了就让问答失败）。"""
    import agents.llm as llm_client

    monkeypatch.setattr(llm_client, "generate_reply", lambda *a, **k: None)
    enough, nxt = agent_tools._judge_enough(_teacher(), "不存在的办法", [])
    assert enough is True and nxt == ""


# ----------------------------------------------------------------
# ③ 自主规划（可切换）
# ----------------------------------------------------------------
def test_auto_mode_is_off_by_default(monkeypatch):
    monkeypatch.delenv("AGENT_MODE", raising=False)
    assert auto_plan.auto_mode_enabled() is False


def test_auto_mode_enabled_only_for_auto(monkeypatch):
    monkeypatch.setenv("AGENT_MODE", "auto")
    assert auto_plan.auto_mode_enabled() is True
    monkeypatch.setenv("AGENT_MODE", "graph")
    assert auto_plan.auto_mode_enabled() is False


def test_student_toolset_excludes_others_data():
    """学生端不能出现查他人的工具：给模型选项就是给攻击面。"""
    names = {t.name for t in auto_plan._STUDENT_TOOLS}
    assert "my_warning" in names and "my_recommendations" in names
    assert "student_profile" not in names
    assert "warning_list" not in names
    assert "class_overview" not in names


def test_plan_returns_none_for_unknown_actor():
    assert auto_plan.plan_with_llm(ToolContext(actor_type="ghost", tenant_id=1),
                                   "查一下班级") is None


def test_plan_returns_none_when_model_unavailable(monkeypatch):
    """模型挂了就退回确定性路由，不能让整轮对话失败。"""

    def boom():
        raise RuntimeError("LLM 不可用")

    monkeypatch.setattr(auto_plan.llm_client, "get_teacher_llm", boom)
    assert auto_plan.plan_with_llm(_teacher(), "AI2301 预警名单") is None


def test_plan_rejects_tool_outside_role(monkeypatch):
    """模型给学生选了教师工具 → 拒绝，退回确定性路由。"""

    class _Resp:
        tool_calls = [{"name": "student_profile", "args": {"student_no": "AI20230002"}}]

    class _Bound:
        def invoke(self, _messages):
            return _Resp()

    class _Model:
        def bind_tools(self, _tools, **_kw):
            return _Bound()

    monkeypatch.setattr(auto_plan.llm_client, "get_student_llm", lambda: _Model())
    assert auto_plan.plan_with_llm(_student(), "查一下 AI20230002 的画像") is None


def test_plan_accepts_allowed_tool_and_cleans_args(monkeypatch):
    """正常情况：模型选的工具在允许集内，参数只保留标量。"""

    class _Resp:
        tool_calls = [{"name": "class_overview",
                       "args": {"class_name": "AI2301", "term": "2025-2026-2",
                                "junk": {"a": 1}}}]

    class _Bound:
        def invoke(self, _messages):
            return _Resp()

    class _Model:
        def bind_tools(self, _tools, **_kw):
            return _Bound()

    monkeypatch.setattr(auto_plan.llm_client, "get_teacher_llm", lambda: _Model())
    picked = auto_plan.plan_with_llm(_teacher(), "AI2301 这学期怎么样")
    assert picked is not None
    assert picked["tool"] == "class_overview"
    assert picked["args"]["class_name"] == "AI2301"
    assert "junk" not in picked["args"], "字典类参数不该被塞进工具调用"


# ----------------------------------------------------------------
# ① 补充：审批「通过」的正向路径（唯一会真正执行步骤的分支）
# ----------------------------------------------------------------
def test_approve_executes_snapshot_and_cannot_be_repeated():
    """通过 = 按提交时快照执行一次；重复审批必须被拦，且不能覆盖已有结果。

    两条防线一起测：
      1. 提交后定义被改，执行要按快照（否则「审的 A、跑的 B」）；
      2. 先抢后跑——抢不到 state 就一步都不执行，也不许把 success 覆盖成 rejected。
    """
    ctx = _teacher()
    name = f"审批通过-{uuid.uuid4().hex[:6]}"
    steps = [{"id": "s1", "tool": "class_list", "title": "班级目录"}]
    conn = _conn()
    def_id = run_id = None
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO `工作流定义`(`租户编号`,`名称`,`步骤`,`创建人`,`是否需要审批`)"
                        " VALUES (%s,%s,%s,%s,1)",
                        (ctx.tenant_id, name, json.dumps(steps, ensure_ascii=False),
                         "teacher:test"))
            def_id = int(cur.lastrowid)
        submitted = approval.submit_for_approval(ctx, def_id, name, steps=steps)
        run_id = int(submitted["run_id"])
        assert submitted["status"] == wf_engine.STATUS_PENDING

        # 提交后有人给流程加了一步：执行必须按快照 1 步，不是最新的 2 步
        changed = steps + [{"id": "s2", "tool": "class_list", "title": "后来加的"}]
        with conn.cursor() as cur:
            cur.execute("UPDATE `工作流定义` SET `步骤`=%s WHERE `编号`=%s",
                        (json.dumps(changed, ensure_ascii=False), def_id))

        res = approval.decide(ctx, run_id, "approve", "同意")
        assert res["status"] == wf_engine.STATUS_SUCCESS, res
        assert len(res["steps"]) == 1, f"应按提交时快照跑 1 步，实际 {len(res['steps'])} 步"
        assert res["definition_changed"] is True, "定义被改动这事必须显式告知审批人"

        with pytest.raises(approval.ApprovalError):
            approval.decide(ctx, run_id, "reject", "重复点一下")

        with conn.cursor() as cur:
            cur.execute("SELECT `状态` FROM `工作流运行` WHERE `编号`=%s", (run_id,))
            assert str(cur.fetchone()["状态"]) == wf_engine.STATUS_SUCCESS, (
                "重复审批把已成功的运行覆盖成别的状态了")
            cur.execute("SELECT `动作` FROM `工作流审批` WHERE `运行编号`=%s", (run_id,))
            assert [r["动作"] for r in cur.fetchall()] == ["approve"], "审批留痕应只有一条"
    finally:
        with conn.cursor() as cur:
            if run_id:
                cur.execute("DELETE FROM `工作流审批` WHERE `运行编号`=%s", (run_id,))
                cur.execute("DELETE FROM `工作流运行` WHERE `编号`=%s", (run_id,))
            if def_id:
                cur.execute("DELETE FROM `工作流定义` WHERE `编号`=%s", (def_id,))
        conn.close()


def test_claim_blocks_concurrent_approve_and_reject():
    """抢占本身要能挡住并发：两个审批人同时点，只能有一个抢到。

    这是「一次运行只审一次」的落点——_load_pending_run 的 pending 校验是**读**，
    两个人可以同时读到 pending；真正的互斥在 _claim 的条件 UPDATE 上。
    """
    ctx = _teacher()
    name = f"抢占测试-{uuid.uuid4().hex[:6]}"
    steps = [{"id": "s1", "tool": "class_list", "title": "班级目录"}]
    conn = _conn()
    def_id = run_id = None
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO `工作流定义`(`租户编号`,`名称`,`步骤`,`创建人`,`是否需要审批`)"
                        " VALUES (%s,%s,%s,%s,1)",
                        (ctx.tenant_id, name, json.dumps(steps, ensure_ascii=False),
                         "teacher:test"))
            def_id = int(cur.lastrowid)
        run_id = int(approval.submit_for_approval(ctx, def_id, name, steps=steps)["run_id"])

        approval._claim(run_id, ctx, "approve", None)          # 甲先抢到，状态转 running
        with pytest.raises(approval.ApprovalError):            # 乙的驳回抢不到了
            approval._claim(run_id, ctx, "reject", None)

        with conn.cursor() as cur:
            cur.execute("SELECT `状态` FROM `工作流运行` WHERE `编号`=%s", (run_id,))
            assert str(cur.fetchone()["状态"]) == wf_engine.STATUS_RUNNING, (
                "驳回把已抢占的运行状态覆盖了")
            cur.execute("SELECT COUNT(*) AS n FROM `工作流审批` WHERE `运行编号`=%s", (run_id,))
            assert int(cur.fetchone()["n"]) == 1, "抢失败的那次不该留下审批记录"
    finally:
        with conn.cursor() as cur:
            if run_id:
                cur.execute("DELETE FROM `工作流审批` WHERE `运行编号`=%s", (run_id,))
                cur.execute("DELETE FROM `工作流运行` WHERE `编号`=%s", (run_id,))
            if def_id:
                cur.execute("DELETE FROM `工作流定义` WHERE `编号`=%s", (def_id,))
        conn.close()


def test_approval_routes_roundtrip():
    """审批走真实 HTTP 路由：提交挂起 → 待审列表可见 → 通过执行 → 重复审批 409。

    服务层有用例不代表接口通：/workflow/approvals/pending 与 /runs/{id}/decide
    是这轮新加的路由，漏挂依赖或返回结构对不上，纯服务层测不出来。
    """
    from fastapi.testclient import TestClient

    from app.main import create_app

    client = TestClient(create_app())
    login = client.post("/auth/login", json={"role": "teacher", "account": "T001",
                                            "password": "teacher@123"})
    assert login.status_code == 200, login.text[:200]
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    conn = _conn()
    def_id = run_id = None
    try:
        name = f"接口冒烟-{uuid.uuid4().hex[:6]}"
        created = client.post("/workflow/defs",
                              json={"name": name, "steps": [{"id": "s1",
                                                             "tool": "class_list"}],
                                    "needs_approval": True}, headers=headers)
        assert created.status_code in (200, 201), created.text[:300]
        def_id = int(created.json()["id"])

        started = client.post(f"/workflow/defs/{def_id}/run", json={}, headers=headers)
        assert started.status_code == 200, started.text[:300]
        run_id = int(started.json()["run_id"])
        assert started.json()["status"] == wf_engine.STATUS_PENDING
        assert not started.json().get("steps")

        pending = client.get("/workflow/approvals/pending", headers=headers)
        assert pending.status_code == 200, pending.text[:300]
        mine = [i for i in pending.json()["items"] if i["id"] == run_id]
        assert mine and mine[0]["step_count"] == 1

        ok = client.post(f"/workflow/runs/{run_id}/decide",
                         json={"action": "approve", "comment": "接口冒烟"}, headers=headers)
        assert ok.status_code == 200, ok.text[:300]
        assert ok.json()["status"] == wf_engine.STATUS_SUCCESS
        assert len(ok.json()["steps"]) == 1

        again = client.post(f"/workflow/runs/{run_id}/decide",
                            json={"action": "reject"}, headers=headers)
        assert again.status_code == 409, f"重复审批应 409，实际 {again.status_code}"
    finally:
        with conn.cursor() as cur:
            if run_id:
                cur.execute("DELETE FROM `工作流审批` WHERE `运行编号`=%s", (run_id,))
                cur.execute("DELETE FROM `工作流运行` WHERE `编号`=%s", (run_id,))
            if def_id:
                cur.execute("DELETE FROM `工作流运行` WHERE `定义编号`=%s", (def_id,))
                cur.execute("DELETE FROM `工作流定义` WHERE `编号`=%s", (def_id,))
        conn.close()
