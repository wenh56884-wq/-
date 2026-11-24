# tests/test_interview_mode.py
# 职责：模拟面试模式切换的路由契约——归一、快照零迁移、模式阈值/tone、响应字段、老会话兼容。
# 说明：全部离线；引擎/模型调用按需打桩，不连 MySQL、不调真实 LLM。

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agents.tools import ToolContext  # noqa: E402
from app.routers import interview as it  # noqa: E402


class FakeCursor:
    rowcount = 0
    lastrowid = 11

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

    def cursor(self):
        return self.cur

    def commit(self):
        self.commits += 1

    def close(self):
        pass


def _ctx() -> ToolContext:
    return ToolContext(actor_type="student", tenant_id=1, student_id=7)


# ----------------------------------------------------------------
# 模式归一与快照读取（老会话没有 mode）
# ----------------------------------------------------------------
def test_start_model_default_and_normalize_never_raises():
    assert it.StartIn().mode == "standard"
    assert it._safe_mode("stress") == "stress"
    assert it._safe_mode("STRESS") == "stress"
    # 引擎归一契约：未知/中文别名都回 standard，绝不报错
    assert it._safe_mode("压力") == "standard"
    assert it._safe_mode("随便什么") == "standard"
    assert it._safe_mode(None) == "standard"
    assert it._safe_mode(123) == "standard"
    assert it._mode_label("stress") == it.MODE_LABELS["stress"]


def test_snapshot_mode_reads_mode_and_tolerates_old_or_broken_snapshots():
    assert it._snapshot_mode(None) == "standard"
    assert it._snapshot_mode("null") == "standard"
    assert it._snapshot_mode("{}") == "standard"
    assert it._snapshot_mode('{"title":"后端"}') == "standard"   # 老会话：无 mode
    assert it._snapshot_mode("not-json") == "standard"           # 坏 JSON 不 500
    assert it._snapshot_mode({"mode": "stress"}) == "stress"
    assert it._snapshot_mode('{"mode":"easy"}') == "easy"


# ----------------------------------------------------------------
# 引擎签名过渡：有 mode/tone 就传，没有就退回老调用
# ----------------------------------------------------------------
def test_outline_passes_mode_when_engine_supports_it(monkeypatch):
    seen = {}

    def outline(job, resume, **kwargs):
        seen.update(kwargs)
        return [{"round": 1, "type": "major", "question": "q"}]

    monkeypatch.setattr(it, "build_outline", outline)
    it._build_outline_for_mode({}, {}, max_rounds=3, exclude_bank_ids=set(),
                               weak=None, variant=0, mode="stress")
    assert seen["mode"] == "stress"


def test_outline_falls_back_when_engine_has_no_mode(monkeypatch):
    seen = {}

    def outline(job, resume, max_rounds, exclude_bank_ids, weak, variant):
        seen.update(max_rounds=max_rounds, variant=variant)
        return []

    monkeypatch.setattr(it, "build_outline", outline)
    assert it._build_outline_for_mode({}, {}, max_rounds=4, exclude_bank_ids=set(),
                                      weak=None, variant=2, mode="stress") == []
    assert "mode" not in seen and seen["variant"] == 2


def test_run_turn_passes_tone_when_supported(monkeypatch):
    seen = {}

    def turn(question, qtype, answer, item, evidence, tone=None):
        seen["tone"] = tone
        return {"comment": "ok", "comment_version": "v"}

    monkeypatch.setattr(it.interviewer, "run_turn", turn)
    it._run_turn_with_tone("q", "major", "a", {}, [], tone="stress")
    assert seen["tone"] == "stress"


def test_run_turn_falls_back_without_tone(monkeypatch):
    def turn(question, qtype, answer, item, evidence):
        return {"comment": "老引擎", "comment_version": "v"}

    monkeypatch.setattr(it.interviewer, "run_turn", turn)
    assert it._run_turn_with_tone("q", "major", "a", {}, [], tone="stress")["comment"] == "老引擎"


# ----------------------------------------------------------------
# 追问阈值走模式；引擎未落地阈值时用 should_probe
# ----------------------------------------------------------------
def test_probe_thresholds_are_mode_specific(monkeypatch):
    monkeypatch.setattr(it, "probe_thresholds",
                        lambda mode: {"score_below": 85, "answer_min": 200, "coverage_below": 0.9})
    item = {"score": 80, "keyword_hits": ["a"], "keyword_missed": []}
    assert it._should_probe_for_mode(item, "很长" * 100, "major", "stress") is True
    high = {"score": 95, "keyword_hits": ["a", "b"], "keyword_missed": []}
    assert it._should_probe_for_mode(high, "很长" * 100, "major", "stress") is False
    assert it._should_probe_for_mode(None, "回答", "major", "stress") is False
    assert it._should_probe_for_mode(high, "回答", "counter", "stress") is False


def test_probe_falls_back_to_engine_when_thresholds_absent(monkeypatch):
    monkeypatch.setattr(it, "probe_thresholds", None)
    monkeypatch.setattr(it, "should_probe", lambda item, answer, qtype: True)
    assert it._should_probe_for_mode({"score": 100}, "回答", "major", "standard") is True


# ----------------------------------------------------------------
# start：快照只追加 mode；响应带 mode / mode_label
# ----------------------------------------------------------------
def test_start_writes_mode_to_snapshot_and_response(monkeypatch):
    conn = FakeConn(one={"n": 0}, rows=[])
    monkeypatch.setattr(it, "_conn", lambda: conn)
    monkeypatch.setattr(it, "audit_event", lambda **kwargs: {})
    monkeypatch.setattr(it, "_load_resume",
                        lambda cur, rid, tid: {"编号": rid, "学生编号": 7, "experiences": [{"desc": "做过接口"}]})
    job = {"title": "后端", "skill_tags": ["Python"], "education": "本科",
           "industry": "互联网", "city": "重庆", "pool": "national"}
    monkeypatch.setattr(it, "_load_job", lambda cur, jid, pool: job)
    monkeypatch.setattr(it, "_build_outline_for_mode",
                        lambda *a, **k: [{"round": 1, "type": "major", "question": "讲讲 Python"}])

    res = it.interview_start(it.StartIn(job_id=3, resume_id=5, mode="stress"), _ctx())
    assert res["mode"] == "stress" and res["mode_label"] == it.MODE_LABELS["stress"]

    insert = [c for c in conn.cur.calls if c[0].lstrip().upper().startswith("INSERT")][0]
    snapshot = json.loads(insert[1][5])
    assert snapshot["mode"] == "stress"
    assert {k: snapshot[k] for k in job} == job, "mode 之外快照键必须原样保留"


# ----------------------------------------------------------------
# 三个响应体：start / 详情 / evaluation（evaluation 为历史报告接口）
# ----------------------------------------------------------------
def test_detail_exposes_mode_from_snapshot(monkeypatch):
    sess = {"编号": 11, "租户编号": 1, "学生编号": 7, "岗位名称": "后端",
            "状态": "finished", "总分": 80, "报告": "报告", "差距清单": "[]",
            "当前轮次": 1, "最大轮次": 1, "创建时间": None,
            "提纲": "[]", "岗位要求快照": '{"mode":"stress"}'}
    conn = FakeConn(one=sess, rows=[])
    monkeypatch.setattr(it, "_conn", lambda: conn)
    out = it.interview_detail(11, _ctx())
    assert out["mode"] == "stress"
    assert out["mode_label"] == it.MODE_LABELS["stress"]


def test_evaluation_exposes_mode_and_tolerates_old_snapshot(monkeypatch):
    sess = {"编号": 11, "租户编号": 1, "学生编号": 7, "简历编号": 1,
            "状态": "finished", "岗位名称": "后端", "提纲": "[]", "岗位要求快照": None}
    conn = FakeConn(one=sess, rows=[])
    monkeypatch.setattr(it, "_conn", lambda: conn)
    monkeypatch.setattr(it, "_load_resume", lambda cur, rid, tid: {"简历原文": "简历", "experiences": []})
    monkeypatch.setattr(it, "_build_evaluation", lambda *a, **k: {"report": "模板"})
    monkeypatch.setattr(it, "_finalize_report", lambda eva: "模板")
    out = it.interview_evaluation(11, _ctx())
    assert out["mode"] == "standard"           # 老会话无 mode，不 500
    assert out["mode_label"] == it.MODE_LABELS["standard"]


# ----------------------------------------------------------------
# 老会话：answer 全流程按 standard 正常跑
# ----------------------------------------------------------------
def test_old_session_answer_runs_as_standard(monkeypatch):
    sess = {"租户编号": 1, "学生编号": 7, "状态": "ongoing", "当前轮次": 0,
            "简历编号": 1, "岗位要求快照": '{"title":"后端"}',  # 老快照，没有 mode
            "提纲": json.dumps([{"round": 1, "type": "major", "question": "讲讲 Python"}],
                               ensure_ascii=False)}
    conn = FakeConn(one=sess, rows=[])
    monkeypatch.setattr(it, "_conn", lambda: conn)
    monkeypatch.setattr(it, "_load_resume", lambda cur, rid, tid: {"简历原文": "简历", "experiences": []})
    monkeypatch.setattr(it, "score_answer", lambda *a, **k: {"score": 80, "keyword_hits": []})
    seen = {}

    def turn(question, qtype, answer, item, evidence, tone=None):
        seen["tone"] = tone
        return {"comment": "点评", "comment_version": "comment-v1"}

    monkeypatch.setattr(it.interviewer, "run_turn", turn)
    monkeypatch.setattr(it, "_probe_enabled", lambda: False)
    monkeypatch.setattr(it, "_finish", lambda sid, ctx: {"finished": True})

    out = it.interview_answer(11, it.AnswerIn(expected_round=1, text="回答"), _ctx())
    assert out["finished"] is True
    assert seen["tone"] == "standard"
