# tests/test_interview_humanized.py
# 职责：模拟面试「人性化」路由契约——放弃收口、超时清理、报告 LLM 降级、单题用时落库。
# 说明：全部离线，假游标替身 DB；不连 MySQL、不调真实 LLM。

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agents.tools import ToolContext  # noqa: E402
from app.routers import interview as it  # noqa: E402


class FakeCursor:
    """最小游标替身：记录 SQL 与参数，按预设返回单行/多行。"""

    rowcount = 0

    def __init__(self, one=None, rows=None):
        self.one = one
        self.rows = rows or []
        self.calls: list[tuple[str, tuple]] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql: str, params=()):
        self.calls.append((sql, tuple(params)))

    def fetchone(self):
        return self.one

    def fetchall(self):
        return self.rows


class FakeConn:
    def __init__(self, one=None, rows=None):
        self.cur = FakeCursor(one, rows)
        self.commits = 0
        self.closed = False

    def cursor(self):
        return self.cur

    def commit(self):
        self.commits += 1

    def close(self):
        self.closed = True


def _ctx(student_id: int = 7, tenant_id: int = 1) -> ToolContext:
    return ToolContext(actor_type="student", tenant_id=tenant_id, student_id=student_id)


# ----------------------------------------------------------------
# 一、abandon 接口
# ----------------------------------------------------------------
def _patch_abandon_db(monkeypatch, row):
    conn = FakeConn(one=row)
    monkeypatch.setattr(it, "_conn", lambda: conn)
    monkeypatch.setattr(it, "audit_event", lambda **kwargs: {})
    return conn


def test_abandon_closes_own_ongoing_session(monkeypatch):
    conn = _patch_abandon_db(monkeypatch, {"租户编号": 1, "学生编号": 7, "状态": "ongoing"})
    assert it.interview_abandon(11, _ctx()) == {"status": "abandoned"}
    updates = [call for call in conn.cur.calls if call[0].lstrip().upper().startswith("UPDATE")]
    assert any("'abandoned'" in sql for sql, _ in updates)
    assert conn.commits == 1 and conn.closed


def test_abandon_is_idempotent(monkeypatch):
    conn = _patch_abandon_db(monkeypatch, {"租户编号": 1, "学生编号": 7, "状态": "abandoned"})
    assert it.interview_abandon(11, _ctx()) == {"status": "abandoned"}
    assert not [c for c in conn.cur.calls if c[0].lstrip().upper().startswith("UPDATE")]
    assert conn.commits == 0


def test_abandon_rejects_other_student_with_403(monkeypatch):
    _patch_abandon_db(monkeypatch, {"租户编号": 1, "学生编号": 8, "状态": "ongoing"})
    with pytest.raises(HTTPException) as exc:
        it.interview_abandon(11, _ctx())
    assert exc.value.status_code == 403


def test_abandon_rejects_other_tenant_with_403(monkeypatch):
    _patch_abandon_db(monkeypatch, {"租户编号": 2, "学生编号": 7, "状态": "ongoing"})
    with pytest.raises(HTTPException) as exc:
        it.interview_abandon(11, _ctx())
    assert exc.value.status_code == 403


def test_abandon_missing_session_is_404_and_finished_is_409(monkeypatch):
    _patch_abandon_db(monkeypatch, None)
    with pytest.raises(HTTPException) as missing:
        it.interview_abandon(11, _ctx())
    assert missing.value.status_code == 404

    _patch_abandon_db(monkeypatch, {"租户编号": 1, "学生编号": 7, "状态": "finished"})
    with pytest.raises(HTTPException) as finished:
        it.interview_abandon(11, _ctx())
    assert finished.value.status_code == 409


# ----------------------------------------------------------------
# 二、ongoing 超时收口
# ----------------------------------------------------------------
def test_stale_close_uses_module_threshold_and_scope():
    cur = FakeCursor()
    assert it.ONGOING_ABANDON_AFTER_HOURS == 24
    it._close_stale_ongoing(cur, 1, 7)
    sql, params = cur.calls[0]
    assert "'abandoned'" in sql and "'ongoing'" in sql
    assert "创建时间" in sql and "DATE_SUB" in sql
    assert params == (1, 7, 24)


def test_status_fetch_triggers_stale_close_before_query(monkeypatch):
    sess = {"编号": 11, "租户编号": 1, "学生编号": 7, "岗位名称": "后端",
            "状态": "abandoned", "总分": None,
            "报告": None, "差距清单": None, "当前轮次": 0, "最大轮次": 1,
            "创建时间": None, "提纲": "[]"}
    conn = FakeConn(one=sess, rows=[])
    monkeypatch.setattr(it, "_conn", lambda: conn)
    out = it.interview_detail(11, _ctx())
    assert out["session"]["状态"] == "abandoned"
    first_sql = conn.cur.calls[0][0]
    assert "'abandoned'" in first_sql and first_sql.lstrip().upper().startswith("UPDATE")
    assert conn.commits >= 1


# ----------------------------------------------------------------
# 三、报告接 LLM，失败回退模板
# ----------------------------------------------------------------
FACTS = {
    "total": 80, "answered": 1, "skipped": 0, "probes": 0,
    "items": [{"round": 1, "label": "专业", "score": 80, "answer": "回答", "brief": "回答"}],
    "strengths": ["专业"], "core_problems": [], "improvement_plan": [], "gaps": [],
}


def test_report_prefers_llm_when_available(monkeypatch):
    monkeypatch.setattr(it.interviewer, "render_report_llm", lambda facts: "LLM 组织后的报告",
                        raising=False)
    assert it._report_text(FACTS) == "LLM 组织后的报告"


def test_report_falls_back_when_llm_raises(monkeypatch):
    def boom(facts):
        raise RuntimeError("LLM 不可用")

    monkeypatch.setattr(it.interviewer, "render_report_llm", boom, raising=False)
    assert it._report_text(FACTS) == it.interviewer.render_report(FACTS)


def test_report_falls_back_when_llm_missing_or_empty(monkeypatch):
    monkeypatch.delattr(it.interviewer, "render_report_llm", raising=False)
    assert it._report_text(FACTS) == it.interviewer.render_report(FACTS)
    monkeypatch.setattr(it.interviewer, "render_report_llm", lambda facts: None, raising=False)
    assert it._report_text(FACTS) == it.interviewer.render_report(FACTS)


def test_finalize_report_uses_report_helper(monkeypatch):
    evaluation = {
        "total": 80, "answered": 1, "skipped": 0, "probes": 0,
        "per_question": [{"round": 1, "label": "专业", "score": 80, "answer": "回答"}],
        "strengths": [], "core_problems": [], "improvement_plan": [], "gaps": [],
        "report": "模板旧值",
    }
    monkeypatch.setattr(it, "_report_text", lambda facts: "MARK-LLM")
    assert it._finalize_report(evaluation) == "MARK-LLM"
    assert evaluation["report"] == "MARK-LLM"


# ----------------------------------------------------------------
# 四、单题用时落库
# ----------------------------------------------------------------
def test_answer_model_accepts_optional_elapsed_seconds():
    assert it.AnswerIn(expected_round=1, elapsed_seconds=42).elapsed_seconds == 42
    assert it.AnswerIn(expected_round=1).elapsed_seconds is None
    with pytest.raises(ValueError):
        it.AnswerIn(expected_round=1, elapsed_seconds=-1)


def test_answer_persists_elapsed_seconds(monkeypatch):
    sess = {"租户编号": 1, "学生编号": 7, "状态": "ongoing", "当前轮次": 0, "简历编号": 1,
            "岗位要求快照": None,
            "提纲": json.dumps([{"round": 1, "type": "major", "question": "讲讲 Python"}],
                               ensure_ascii=False)}
    conn = FakeConn(one=sess, rows=[])
    monkeypatch.setattr(it, "_conn", lambda: conn)
    monkeypatch.setattr(it, "_load_resume", lambda cur, rid, tid: {"简历原文": "简历", "experiences": []})
    monkeypatch.setattr(it, "score_answer", lambda *a, **k: {"score": 80, "keyword_hits": []})
    monkeypatch.setattr(it.interviewer, "run_turn",
                        lambda *a, **k: {"comment": "点评", "comment_version": "comment-v1"})
    monkeypatch.setattr(it, "_probe_enabled", lambda: False)
    monkeypatch.setattr(it, "_finish", lambda sid, ctx: {"finished": True})

    it.interview_answer(11, it.AnswerIn(expected_round=1, text="回答", elapsed_seconds=42), _ctx())

    inserts = [call for call in conn.cur.calls if call[0].lstrip().upper().startswith("INSERT")]
    assert len(inserts) == 1
    sql, params = inserts[0]
    assert "`用时秒`" in sql
    assert params[-1] == 42
