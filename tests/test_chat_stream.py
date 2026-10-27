# tests/test_chat_stream.py
# 职责：校验 SSE 流式对话的事件序列（status → replace/delta → done）、
#       驳回重写清空气泡、超限降级、旧接口不受影响。
# 说明：全部离线，不连 MySQL、不调 LLM（monkeypatch 流式生成）。

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agents import graph  # noqa: E402
from agents.tools import ToolContext  # noqa: E402

# 与 test_critic 相同的样本：数值白名单由此生成
TOOL_RESULT = {
    "student_no": "RJ2022001",
    "term": "2025-2026-2",
    "risk_score": 67,
    "level": "red",
    "coverage": 3,
    "missing": [],
    "reasons": ["本学期挂科2门", "本学期平均成绩下滑11.6分", "本学期出勤率降至71%"],
    "metrics": {"fail_count": 2, "gpa": 68.4, "gpa_drop": 11.6, "attendance_rate": 0.71},
}

GOOD_DRAFT = "该生风险分 67，挂科 2 门。"


def _ctx() -> ToolContext:
    return ToolContext(actor_type="teacher", tenant_id=1, teacher_id=7)


def _events(context: str = "这位学生成绩怎么样？", **kwargs) -> list[dict]:
    return list(graph.run_chat_stream(_ctx(), context, tool_result=TOOL_RESULT, **kwargs))


def _of(events: list[dict], kind: str) -> list[dict]:
    return [e for e in events if e.get("type") == kind]


# ----------------------------------------------------------------
# 1) 逐块下发 delta；done.answer 是完整且已核验的文本
# ----------------------------------------------------------------
def test_stream_deltas_then_done(monkeypatch):
    """LLM 流式回调的每块都变成 delta；done 给出最终答案与元信息。"""
    def fake_reply(actor_type, *, system_prompt, user_prompt, tag="draft", on_token=None):
        for piece in ("该生风险分 ", "67", "，挂科 2 门。"):
            assert on_token is not None, "流式路径必须带 on_token"
            on_token(piece)
        return GOOD_DRAFT

    monkeypatch.setattr(graph.llm_client, "generate_reply", fake_reply)
    events = _events()

    deltas = _of(events, "delta")
    assert len(deltas) == 3
    assert "".join(e["text"] for e in deltas) == GOOD_DRAFT

    done = _of(events, "done")
    assert len(done) == 1
    assert done[0]["answer"] == GOOD_DRAFT
    assert done[0]["degraded"] is False
    assert done[0]["attempts"] == 1
    assert done[0]["trace_id"]

    stages = [e.get("stage") for e in _of(events, "status")]
    assert stages[:2] == ["tool", "draft"], stages
    assert "critic" in stages


def test_stream_starts_with_empty_replace_to_reset_bubble(monkeypatch):
    """每次新稿先发 replace("")：上一稿即使已流出也不会残留在界面上。"""
    def fake_reply(actor_type, *, system_prompt, user_prompt, tag="draft", on_token=None):
        on_token(GOOD_DRAFT)
        return GOOD_DRAFT

    monkeypatch.setattr(graph.llm_client, "generate_reply", fake_reply)
    events = _events()
    assert _of(events, "replace")[0]["text"] == ""


# ----------------------------------------------------------------
# 2) 第一稿数值错误 → replace 清空、第二稿重写并最终通过
# ----------------------------------------------------------------
def test_stream_retry_replaces_wrong_draft(monkeypatch):
    calls = {"n": 0}

    def fake_reply(actor_type, *, system_prompt, user_prompt, tag="draft", on_token=None):
        calls["n"] += 1
        text = "该生均分 78.4。" if calls["n"] == 1 else "该生均分 68.4。"
        on_token(text)
        return text

    monkeypatch.setattr(graph.llm_client, "generate_reply", fake_reply)
    events = _events()

    replaces = _of(events, "replace")
    # 至少出现一次「重写前清空」，第二稿逐块流出的是修正后的版本
    assert any(r["text"] == "" and r.get("attempt") == 2 for r in replaces), replaces
    attempt2 = "".join(d["text"] for d in _of(events, "delta")
                       if d.get("attempt") == 2)
    assert attempt2 == "该生均分 68.4。"

    done = _of(events, "done")[0]
    assert done["answer"] == "该生均分 68.4。"
    assert done["degraded"] is False
    assert done["attempts"] == 2
    assert any(e.get("stage") == "retry" for e in _of(events, "status"))


# ----------------------------------------------------------------
# 3) 连续写错 → 超限降级，最终答案不含任何数字
# ----------------------------------------------------------------
def test_stream_falls_back_without_numbers():
    """注入一个坚持幻觉的草稿函数：重试耗尽后降级，最终答案不含任何数字。"""
    def lying_draft(result, feedback, attempt):
        return "该生均分 78.4，风险分 88。"

    events = _events(draft_fn=lying_draft)

    done = _of(events, "done")[0]
    assert done["degraded"] is True
    assert not any(ch.isdigit() for ch in done["answer"]), done["answer"]
    # 气泡最终显示的就是降级稿
    assert _of(events, "replace")[-1]["text"] == done["answer"]


# ----------------------------------------------------------------
# 4) LLM 不可用 → 模板直引整体下发，仍然通过回查
# ----------------------------------------------------------------
def test_stream_template_when_llm_unavailable(monkeypatch):
    monkeypatch.setattr(graph.llm_client, "generate_reply",
                        lambda *a, **kw: None)
    events = _events()

    replaces = _of(events, "replace")
    assert replaces[-1]["text"], "模板稿必须作为 replace 整体下发"
    assert not _of(events, "delta"), "模板稿不是逐块生成的"

    done = _of(events, "done")[0]
    assert done["degraded"] is False
    assert done["answer"] == replaces[-1]["text"]
    assert "67" in done["answer"]


# ----------------------------------------------------------------
# 5) SSE 编码：一帧一个事件，data 为单行 JSON
# ----------------------------------------------------------------
def test_sse_frame_is_single_line_json():
    from app.routers.chat import _sse

    frame = _sse({"type": "delta", "text": "你好\n世界"})
    assert frame.startswith("event: delta\n")
    assert frame.endswith("\n\n")
    data_lines = [l for l in frame.split("\n") if l.startswith("data: ")]
    assert len(data_lines) == 1, "换行必须被 JSON 转义，不能拆成多行 data"
    assert json.loads(data_lines[0][len("data: "):])["text"] == "你好\n世界"


def test_stream_endpoint_requires_auth():
    """/chat/stream 与 /chat 一样：无 token 一律 401。"""
    from fastapi.testclient import TestClient

    from app.main import create_app

    client = TestClient(create_app())
    resp = client.post("/chat/stream", json={"query": "hi"})
    assert resp.status_code == 401
