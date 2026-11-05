# tests/test_pet_api.py
# 职责：校验宠物陪伴路由的接口契约——chat/state/focus/proactive/personality。
# 方法：覆盖 get_current_ctx（不依赖 MySQL 登录）+ monkeypatch LLM（不发真实请求）。
# 铁律：聚焦确定性路由逻辑；数值（心情/专注/degraded）由 engine.pet 算出。

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from agents import llm  # noqa: E402
from app.auth import get_current_ctx  # noqa: E402
from engine import pet as pet_engine  # noqa: E402
from app.main import create_app  # noqa: E402
from app.routers import pet as pet_router  # noqa: E402
from agents.tools import ToolContext  # noqa: E402


def _client(monkeypatch, student_id: int = 1) -> TestClient:
    """构造 TestClient：覆盖鉴权 + LLM + 强制内存模式（不连 MySQL）。"""
    pet_router._PETS.clear()  # 隔离：避免记忆在用例间串味
    monkeypatch.setattr(llm, "generate_reply", lambda *a, **k: "陪伴回复测试")
    monkeypatch.setattr(pet_router, "_try_db", lambda: None)  # 强制内存降级
    app = create_app()
    app.dependency_overrides[get_current_ctx] = lambda: ToolContext(
        actor_type="student", tenant_id=1, student_id=student_id,
    )
    return TestClient(app)


def test_pet_chat_returns_reply_and_not_degraded(monkeypatch):
    c = _client(monkeypatch)
    r = c.post("/pet/chat", json={"text": "今天好累"})
    assert r.status_code == 200
    d = r.json()
    assert d["reply"] == "陪伴回复测试"
    assert d["degraded"] is False  # LLM 成功，非降级
    assert d["mood"] in ("idle", "happy", "thinking", "sleepy")


def test_pet_chat_degrades_to_template_when_llm_fails(monkeypatch):
    c = _client(monkeypatch)
    monkeypatch.setattr(llm, "generate_reply", lambda *a, **k: None)
    r = c.post("/pet/chat", json={"text": "在吗"})
    assert r.status_code == 200
    d = r.json()
    assert d["degraded"] is True  # LLM 失败 → 模板兜底
    assert d["reply"]  # 模板仍可读


def test_pet_state_returns_mood_and_fields(monkeypatch):
    c = _client(monkeypatch)
    r = c.get("/pet/state")
    assert r.status_code == 200
    d = r.json()
    assert {"mood", "focus_mode", "name", "intensity"} <= set(d)


def test_pet_focus_toggle(monkeypatch):
    c = _client(monkeypatch)
    r = c.post("/pet/focus", json={"on": True})
    assert r.json()["focus_mode"] is True
    r = c.post("/pet/focus", json={"on": False})
    assert r.json()["focus_mode"] is False


def test_pet_proactive_silent_when_focus_on(monkeypatch):
    c = _client(monkeypatch)
    c.post("/pet/focus", json={"on": True})
    r = c.post("/pet/proactive")
    assert r.status_code == 200
    assert r.json()["spoke"] is False


def test_pet_proactive_speaks_when_due(monkeypatch):
    c = _client(monkeypatch)
    c.get("/pet/state")  # 触发 _runtime 创建当前身份的运行时
    rt = pet_router._PETS[1]
    rt.scheduler.last_spoke_at = 0  # 把上次说话时间设为很久以前，强制到期
    r = c.post("/pet/proactive")
    d = r.json()
    assert d["spoke"] is True
    assert d["text"] == "陪伴回复测试"


def test_pet_personality_default(monkeypatch):
    c = _client(monkeypatch)
    r = c.get("/pet/personality")
    assert r.status_code == 200
    assert r.json()["name"] == "小航"


def test_pet_update_personality(monkeypatch):
    c = _client(monkeypatch)
    r = c.put("/pet/personality", json={"name": "豆豆", "tone": "温柔", "greeting": "嗨，我是豆豆"})
    assert r.status_code == 200
    d = r.json()
    assert d["name"] == "豆豆"
    assert d["tone"] == "温柔"
    assert d["greeting"] == "嗨，我是豆豆"


def test_pet_personality_partial_update_keeps_other_fields(monkeypatch):
    c = _client(monkeypatch)
    c.put("/pet/personality", json={"name": "豆豆", "tone": "温柔"})
    r = c.get("/pet/personality")
    d = r.json()
    assert d["name"] == "豆豆"
    assert d["tone"] == "温柔"
    # greeting 未传则保留默认
    assert d["greeting"] == pet_engine.DEFAULT_PERSONALITY.greeting


def test_pet_personality_persists_across_requests(monkeypatch):
    c = _client(monkeypatch)
    c.put("/pet/personality", json={"name": "豆豆"})
    r = c.get("/pet/personality")
    assert r.json()["name"] == "豆豆"


def test_pet_update_personality_requires_name(monkeypatch):
    c = _client(monkeypatch)
    r = c.put("/pet/personality", json={"tone": "温柔"})
    assert r.status_code == 422  # name 必填


def test_pet_update_personality_encourage(monkeypatch):
    c = _client(monkeypatch)
    r = c.put("/pet/personality", json={"name": "豆豆", "encourage": ["加油哦", "慢慢来"]})
    assert r.status_code == 200
    assert r.json()["encourage"] == ["加油哦", "慢慢来"]


def test_pet_update_personality_encourage_not_passed_keeps_default(monkeypatch):
    c = _client(monkeypatch)
    r = c.put("/pet/personality", json={"name": "豆豆"})
    assert r.json()["encourage"] == list(pet_engine.DEFAULT_PERSONALITY.encourage_pool)


def test_pet_update_personality_encourage_capped_at_10(monkeypatch):
    c = _client(monkeypatch)
    r = c.put("/pet/personality", json={"name": "豆豆", "encourage": [f"e{i}" for i in range(15)]})
    assert len(r.json()["encourage"]) == 10  # 截断到上限


def test_pet_update_personality_encourage_empty_falls_back(monkeypatch):
    c = _client(monkeypatch)
    r = c.put("/pet/personality", json={"name": "豆豆", "encourage": ["", "  "]})
    assert r.json()["encourage"] == list(pet_engine.DEFAULT_PERSONALITY.encourage_pool)


def test_pet_personality_get_returns_encourage(monkeypatch):
    c = _client(monkeypatch)
    r = c.get("/pet/personality")
    d = r.json()
    assert "encourage" in d
    assert d["encourage"] == list(pet_engine.DEFAULT_PERSONALITY.encourage_pool)


def test_pet_memories_endpoint_memory_mode(monkeypatch):
    c = _client(monkeypatch)
    r = c.get("/pet/memories")
    assert r.status_code == 200
    d = r.json()
    assert "total" in d and "items" in d
    assert d["total"] == 0  # 内存模式（_try_db=None）无长期记忆


def test_pet_memory_update_delete_404_in_memory_mode(monkeypatch):
    """内存模式无持久化：编辑/删除一律 404（查无如实报）。"""
    c = _client(monkeypatch)
    assert c.put("/pet/memories/1", json={"content": "改一改"}).status_code == 404
    assert c.delete("/pet/memories/1").status_code == 404


def test_pet_memory_update_validates_content(monkeypatch):
    """编辑内容校验：空串/超长直接 422，不触达存储层。"""
    c = _client(monkeypatch)
    assert c.put("/pet/memories/1", json={"content": "   "}).status_code == 422
    assert c.put("/pet/memories/1", json={"content": "长" * 61}).status_code == 422


def test_pet_state_isolated_by_identity(monkeypatch):
    """多租户：不同身份的宠物状态互不影响。"""
    c1 = _client(monkeypatch, student_id=1)
    c2 = _client(monkeypatch, student_id=2)
    c1.post("/pet/chat", json={"text": "学生1的消息"})
    c1.post("/pet/focus", json={"on": True})
    # 学生2 不应看到学生1 的专注状态
    r = c2.get("/pet/state")
    assert r.json()["focus_mode"] is False


def test_pet_reply_punctuation_normalized(monkeypatch):
    """LLM 输出的半角标点/波浪号要被确定性归一（铁律 1：后处理不经过模型）。"""
    c = _client(monkeypatch)
    monkeypatch.setattr(llm, "generate_reply", lambda *a, **k: "很高兴见到你~今天想聊点啥? 加油!!")
    r = c.post("/pet/chat", json={"text": "你好"})
    d = r.json()
    assert d["reply"] == "很高兴见到你～今天想聊点啥？ 加油！！"
    assert "?" not in d["reply"] and "!!" not in d["reply"]


def test_pet_normalize_reply_collapses_wave_runs():
    """连续波浪号收敛为单个全角波浪号。"""
    assert pet_router.normalize_reply("好耶～～~！") == "好耶～！"
    assert pet_router.normalize_reply(None) == ""


def test_build_user_prompt_includes_academic():
    """学业状态注入 user prompt：宠物据此给针对性鼓励。"""
    p = pet_engine.DEFAULT_PERSONALITY
    academic = {"name": "小明", "level": "orange", "level_cn": "预警"}
    out = pet_router._build_user_prompt(
        [], "今天好累", p, memories=["想考公务员"], academic=academic,
    )
    assert "【用户学业状态】" in out
    assert "小明" in out
    assert "预警" in out
    assert "【用户长期记忆】" in out


def test_build_user_prompt_without_academic():
    """无学业状态时不注入该段，仍含长期记忆。"""
    p = pet_engine.DEFAULT_PERSONALITY
    out = pet_router._build_user_prompt([], "hi", p, memories=["想考公务员"], academic=None)
    assert "【用户学业状态】" not in out
    assert "【用户长期记忆】" in out


def test_academic_snapshot_none_for_teacher():
    """教师无个人学业数据，快照返回 None（不调用引擎）。"""
    from agents.tools import ToolContext
    ctx = ToolContext(actor_type="teacher", tenant_id=1, teacher_id=1)
    assert pet_router._academic_snapshot(ctx) is None
