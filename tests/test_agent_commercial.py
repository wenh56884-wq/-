# tests/test_agent_commercial.py
# 职责：智能体商业化能力契约——意图配置化、引导式追问、反馈闭环、质量指标、每日配额。
# 说明：离线单测 + MySQL 门控的接口测试（沿用 test_api 的临时教师 fixture 模式）。

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402

from agents import graph as agent_graph  # noqa: E402
from agents import intents  # noqa: E402
from agents import teacher_agent  # noqa: E402
from agents.tools import ToolContext  # noqa: E402

CTX = ToolContext(actor_type="teacher", tenant_id=1, teacher_id=7)
STU_CTX = ToolContext(actor_type="student", tenant_id=1, student_id=1)


# ----------------------------------------------------------------
# 1. 意图配置化
# ----------------------------------------------------------------
def test_intents_defaults_loaded():
    data = intents.load(force=True)
    assert data["tools"]["warning_list"], "内置默认词表必须可用"
    assert "阈值" in data["tools"]["warning_thresholds"]


def test_intents_merge_appends_without_duplicates():
    base = {"kb": ["制度", "流程"], "levels": {"红色": "red"}}
    merged = intents._merge(base, {"kb": ["流程", "绩效"], "levels": {"橙色": "orange"},
                                   "notes": "x"})
    assert merged["kb"] == ["制度", "流程", "绩效"]
    assert merged["levels"] == {"红色": "red", "橙色": "orange"}
    assert merged["notes"] == "x"


def test_intents_new_section_accepted():
    merged = intents._merge({"kb": ["制度"]}, {"hr": ["入职", "试用期"]})
    assert merged["hr"] == ["入职", "试用期"]


def test_intents_bad_json_falls_back(monkeypatch, tmp_path):
    bad = tmp_path / "agent_intents.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(intents, "_PATH", bad)
    data = intents.load(force=True)
    assert data["tools"]["warning_list"], "配置坏了要退回内置默认，不能炸服务"


def test_intents_override_extends_teacher_route(monkeypatch, tmp_path):
    override = tmp_path / "agent_intents.json"
    override.write_text(json.dumps({"tools": {"warning_list": ["谁来补考"]}},
                                   ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(intents, "_PATH", override)
    intents.load(force=True)
    try:
        plan = teacher_agent.plan_teacher(CTX, "谁来补考的话怎么看", "谁来补考的话怎么看", None)
        assert plan["tool_name"] == "warning_list"
    finally:
        monkeypatch.undo()
        intents.load(force=True)


def test_intents_mtime_cache_reloads(monkeypatch, tmp_path):
    f = tmp_path / "agent_intents.json"
    f.write_text(json.dumps({"kb": ["第一条"]}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(intents, "_PATH", f)
    assert "第一条" in intents.load(force=True)["kb"]
    f.write_text(json.dumps({"kb": ["第二条"]}, ensure_ascii=False), encoding="utf-8")
    import os
    import time

    os.utime(f, (time.time(), time.time() + 10))  # Windows 上 ns 元组会报参数错误，用秒
    assert "第二条" in intents.load()["kb"], "mtime 变了要自动重载，无需重启"


# ----------------------------------------------------------------
# 2. 引导式追问（离线注入模式 tool_name='injected' 时跳过，这里直接测选择逻辑）
# ----------------------------------------------------------------
def test_followups_present_and_digit_free():
    ups = agent_graph._suggested_followups({"tool_name": "class_overview"})
    assert 1 <= len(ups) <= 3
    assert all(not any(ch.isdigit() for ch in s) for s in ups), "追问建议不许带数字"
    assert any("预警" in s or "画像" in s for s in ups)


def test_followups_tool_specific():
    assert any("差距" in s or "维度" in s
               for s in agent_graph._suggested_followups({"tool_name": "career_gap"}))
    assert agent_graph._suggested_followups({"tool_name": "warning_list"})
    assert agent_graph._suggested_followups({"tool_name": "unknown_tool"})  # 走默认兜底


def test_followups_injected_tool_result_skipped():
    state = {"tool_name": "injected"}
    assert agent_graph._suggested_followups(state) == []


def test_run_chat_result_carries_followups_key():
    result = agent_graph.run_chat(CTX, "概貌", tool_result={"headcount": 30})
    assert isinstance(result.get("suggested_followups"), list)


def test_stream_done_event_carries_followups_key():
    events = list(agent_graph.run_chat_stream(
        STU_CTX, "我的预警", tool_result={"risk_score": 1, "level": "yellow", "reasons": []}))
    done = [e for e in events if e.get("type") == "done"][0]
    assert isinstance(done["suggested_followups"], list)


# ----------------------------------------------------------------
# 3. 每日配额（离线：monkeypatch 计数 SQL）
# ----------------------------------------------------------------
def test_quota_unlimited_by_default(monkeypatch):
    import app.config as cfg

    monkeypatch.setattr(cfg.get_settings(), "agent_daily_limit", 0)
    from app import chat_service

    assert chat_service.check_quota(CTX)["remaining"] == -1


def test_quota_blocks_when_used_up(monkeypatch):
    import app.config as cfg
    from agents import teacher_agent as ta

    monkeypatch.setattr(cfg.get_settings(), "agent_daily_limit", 5)
    monkeypatch.setattr(ta, "_query", lambda *a, **k: [{"used": 5}])
    monkeypatch.setattr("app.chat_service._tools_query", None, raising=False)
    import app.chat_service as cs

    monkeypatch.setattr(cs, "_actor", lambda ctx: 7)
    # chat_service 里 quota 用的是 agents.tools._query 的别名导入，得打它
    # （check_quota 内部 from agents.tools import _query）
    monkeypatch.setattr("agents.tools._query", lambda *a, **k: [{"used": 5}])
    with pytest.raises(cs.QuotaExceeded):
        cs.check_quota(CTX)


def test_quota_message_contains_limit(monkeypatch):
    import app.config as cfg

    monkeypatch.setattr(cfg.get_settings(), "agent_daily_limit", 5)
    monkeypatch.setattr("agents.tools._query", lambda *a, **k: [{"used": 5}])
    import app.chat_service as cs

    monkeypatch.setattr(cs, "_actor", lambda ctx: 7)
    with pytest.raises(cs.QuotaExceeded) as ei:
        cs.check_quota(CTX)
    assert "5" in str(ei.value)


# ----------------------------------------------------------------
# 4. 反馈闭环 + 质量指标（MySQL 门控）
# ----------------------------------------------------------------
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from app.auth import hash_password  # noqa: E402
from app.main import create_app  # noqa: E402


def _mysql_ok() -> bool:
    try:
        import pymysql

        from app.config import get_settings

        s = get_settings()
        conn = pymysql.connect(host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
                               password=s.mysql_password, database=s.mysql_db, charset="utf8mb4")
        conn.close()
        return True
    except Exception:
        return False


requires_mysql = pytest.mark.skipif(not _mysql_ok(), reason="MySQL 不可用")

EMPLOYEE_NO = f"TC{__import__('os').getpid() % 100000:05d}"
TEACHER_PWD = "teacher@123"


@pytest.fixture(scope="module")
def api():
    client = TestClient(create_app())
    conn = None
    import pymysql

    from app.config import get_settings

    s = get_settings()
    conn = pymysql.connect(host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
                           password=s.mysql_password, database=s.mysql_db,
                           charset="utf8mb4", autocommit=True)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO `教师` (`租户编号`,`姓名`,`工号`,`角色`,`口令摘要`)"
                    " VALUES (1,'商业化测试教师',%s,'teacher',%s)",
                    (EMPLOYEE_NO, hash_password(TEACHER_PWD)))
    token = client.post("/auth/login", json={"role": "teacher", "account": EMPLOYEE_NO,
                                             "password": TEACHER_PWD}).json()
    yield client, {"Authorization": f"Bearer {token['access_token']}"}
    with conn.cursor() as cur:
        cur.execute("DELETE FROM `教师` WHERE `工号`=%s", (EMPLOYEE_NO,))
    conn.close()


@requires_mysql
def test_feedback_roundtrip(api):
    client, headers = api
    resp = client.post("/chat/feedback", headers=headers,
                       json={"trace_id": "t" + EMPLOYEE_NO, "rating": "up",
                             "comment": "名单很清楚"})
    assert resp.status_code == 200 and resp.json()["ok"] is True
    # 指标接口里能看到这条反馈
    metrics = client.get("/chat/metrics", headers=headers).json()
    assert metrics["feedback_up"] >= 1


@requires_mysql
def test_feedback_validates_rating(api):
    client, headers = api
    resp = client.post("/chat/feedback", headers=headers,
                       json={"trace_id": "x", "rating": "meh"})
    assert resp.status_code == 422


@requires_mysql
def test_metrics_teacher_only(api):
    client, headers = api
    assert client.get("/chat/metrics").status_code == 401
    metrics = client.get("/chat/metrics", headers=headers).json()
    assert metrics["window_days"] == 7
    assert "chat_total" in metrics and "like_rate" in metrics
