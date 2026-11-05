# tests/test_pet_store.py
# 职责：验证宠物持久化层的真实 MySQL 读写——跨会话保留运行时与记忆。
# 依赖：MySQL 可用时跑，否则整文件 skip（与 test_api.py 同策略）。
# 铁律：纯数据存取，无 LLM；按身份隔离。

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402

pytest.importorskip("pymysql")

from engine import pet as pet_engine  # noqa: E402
from engine import pet_store  # noqa: E402

IDENTITY = 999999  # 测试专用身份，用例前后清理，不污染真实用户
TENANT = 1


def _conn():
    import pymysql

    from app.config import get_settings

    s = get_settings()
    return pymysql.connect(host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
                           password=s.mysql_password, database=s.mysql_db,
                           charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)


def _mysql_ok() -> bool:
    try:
        conn = _conn()
        conn.close()
        return True
    except Exception:
        return False


MYSQL_OK = _mysql_ok()
requires_mysql = pytest.mark.skipif(not MYSQL_OK, reason="MySQL 不可用")


@pytest.fixture
def conn():
    c = _conn()
    pet_store.ensure_schema(c)
    _clean(c)
    try:
        yield c
    finally:
        _clean(c)
        c.close()


def _clean(conn) -> None:
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM `宠物记忆` WHERE `身份编号` = %s", (IDENTITY,))
            cur.execute("DELETE FROM `宠物运行时` WHERE `身份编号` = %s", (IDENTITY,))
            cur.execute("DELETE FROM `宠物人格` WHERE `身份编号` = %s", (IDENTITY,))
            cur.execute("DELETE FROM `宠物长期记忆` WHERE `身份编号` = %s", (IDENTITY,))
        conn.commit()
    except Exception:
        pass


@requires_mysql
def test_ensure_schema_creates_tables(conn):
    with conn.cursor() as cur:
        cur.execute("SHOW TABLES LIKE '宠物运行时'")
        assert cur.fetchone() is not None
        cur.execute("SHOW TABLES LIKE '宠物记忆'")
        assert cur.fetchone() is not None


@requires_mysql
def test_save_and_load_runtime_roundtrip(conn):
    rt = pet_engine.PetRuntime(
        personality=pet_engine.DEFAULT_PERSONALITY,
        mood=pet_engine.MoodState(mood=pet_engine.MOOD_HAPPY, intensity=0.8,
                                  last_interact_at=1000.0),
        memory=pet_engine.ShortMemory(),
        scheduler=pet_engine.ProactiveScheduler(interval_sec=300, focus_mode=True,
                                                 last_spoke_at=500.0),
    )
    pet_store.save_runtime(conn, IDENTITY, TENANT, rt)
    data = pet_store.load_runtime(conn, IDENTITY)
    assert data is not None
    assert data["mood"] == pet_engine.MOOD_HAPPY
    assert data["intensity"] == pytest.approx(0.8)
    assert data["focus_mode"] is True
    assert data["interval_sec"] == 300
    assert data["last_spoke_at"] == pytest.approx(500.0)
    assert data["name"] == "小航"


@requires_mysql
def test_load_runtime_returns_none_when_missing(conn):
    data = pet_store.load_runtime(conn, 888888)
    assert data is None


@requires_mysql
def test_add_and_load_memory_roundtrip(conn):
    pet_store.add_memory(conn, IDENTITY, TENANT, "user", "今天好累", 1000.0)
    pet_store.add_memory(conn, IDENTITY, TENANT, "pet", "加油哦", 1001.0)
    turns = pet_store.load_memory(conn, IDENTITY, 10)
    assert len(turns) == 2
    assert turns[0].role == "user"
    assert turns[0].text == "今天好累"
    assert turns[1].role == "pet"
    assert turns[1].text == "加油哦"


@requires_mysql
def test_trim_memory_keeps_recent(conn):
    for i in range(10):
        pet_store.add_memory(conn, IDENTITY, TENANT, "user", f"q{i}", float(i))
    deleted = pet_store.trim_memory(conn, IDENTITY, 3)
    assert deleted == 7
    turns = pet_store.load_memory(conn, IDENTITY, 10)
    assert len(turns) == 3
    assert turns[0].text == "q7"  # 正序：最早的保留轮
    assert turns[-1].text == "q9"


@requires_mysql
def test_memory_isolated_by_identity(conn):
    pet_store.add_memory(conn, IDENTITY, TENANT, "user", "A的记忆", 1000.0)
    other = pet_store.load_memory(conn, 777777, 10)
    assert other == []  # 不同身份看不到


@requires_mysql
def test_runtime_isolated_by_identity(conn):
    rt = pet_engine.PetRuntime(
        personality=pet_engine.DEFAULT_PERSONALITY,
        mood=pet_engine.MoodState(mood=pet_engine.MOOD_HAPPY, intensity=0.7),
        memory=pet_engine.ShortMemory(),
        scheduler=pet_engine.ProactiveScheduler(),
    )
    pet_store.save_runtime(conn, IDENTITY, TENANT, rt)
    other = pet_store.load_runtime(conn, 777777)
    assert other is None  # 不同身份不串


@requires_mysql
def test_personality_roundtrip(conn):
    p = pet_engine.Personality(name="豆豆", tone="温柔", greeting="嗨我是豆豆")
    pet_store.save_personality(conn, IDENTITY, TENANT, p)
    data = pet_store.load_personality(conn, IDENTITY)
    assert data["name"] == "豆豆"
    assert data["tone"] == "温柔"
    assert data["greeting"] == "嗨我是豆豆"


@requires_mysql
def test_personality_missing_returns_none(conn):
    data = pet_store.load_personality(conn, 888888)
    assert data is None


@requires_mysql
def test_personality_isolated_by_identity(conn):
    p = pet_engine.Personality(name="A的宠物")
    pet_store.save_personality(conn, IDENTITY, TENANT, p)
    other = pet_store.load_personality(conn, 777777)
    assert other is None  # 不同身份不串


@requires_mysql
def test_personality_encourage_roundtrip(conn):
    p = pet_engine.Personality(
        name="豆豆", tone="温柔", greeting="嗨",
        encourage_pool=("加油哦", "慢慢来", "你做得很好"),
    )
    pet_store.save_personality(conn, IDENTITY, TENANT, p)
    data = pet_store.load_personality(conn, IDENTITY)
    assert data["encourage"] == ["加油哦", "慢慢来", "你做得很好"]


@requires_mysql
def test_long_memory_roundtrip(conn):
    pet_store.add_long_memory(conn, IDENTITY, TENANT, "想考公务员", "goal", 5, 1000.0)
    pet_store.add_long_memory(conn, IDENTITY, TENANT, "喜欢猫", "preference", 3, 1001.0)
    mems = pet_store.load_long_memories(conn, IDENTITY, 10)
    # 按重要度倒序：goal(5) 在前
    assert mems[0]["content"] == "想考公务员"
    assert mems[0]["importance"] == 5


@requires_mysql
def test_long_memory_trim_keeps_top(conn):
    for i in range(15):
        pet_store.add_long_memory(conn, IDENTITY, TENANT, f"f{i}", "fact", 1, float(i))
    deleted = pet_store.trim_long_memories(conn, IDENTITY, 5)
    assert deleted == 10
    mems = pet_store.load_long_memories(conn, IDENTITY, 10)
    assert len(mems) == 5


@requires_mysql
def test_long_memory_isolated(conn):
    pet_store.add_long_memory(conn, IDENTITY, TENANT, "A的记忆", "fact", 3, 1000.0)
    other = pet_store.load_long_memories(conn, 777777, 10)
    assert other == []


@requires_mysql
def test_chat_extracts_long_memory(conn):
    """chat 后提取链路：LLM 提取 → 落库 → GET /pet/memories 可见。"""
    from fastapi.testclient import TestClient

    from app.auth import get_current_ctx
    from app.main import create_app
    from agents.tools import ToolContext
    from agents import llm as llm_mod

    app = create_app()
    app.dependency_overrides[get_current_ctx] = lambda: ToolContext(
        actor_type="student", tenant_id=1, student_id=IDENTITY,
    )

    orig = llm_mod.generate_reply

    def fake_llm(*args, **kwargs):
        if kwargs.get("tag") == "pet.extract":
            return "想考公务员\n喜欢猫"
        return "陪伴回复"

    llm_mod.generate_reply = fake_llm
    try:
        client = TestClient(app)
        r = client.post("/pet/chat", json={"text": "我打算考公务员，还喜欢猫"})
        assert r.status_code == 200
        items = client.get("/pet/memories").json()["items"]
        assert any("考公务员" in i["content"] for i in items)
        assert all("id" in i for i in items)  # 条目带编号，供编辑/删除
    finally:
        llm_mod.generate_reply = orig


@requires_mysql
def test_long_memory_update_and_delete(conn):
    """编辑/删除：本人可改可删，改后重算向量，删后不可见。"""
    mem_id = pet_store.add_long_memory(conn, IDENTITY, TENANT, "喜欢猫", "preference", 3, 1000.0)
    assert mem_id > 0

    ok = pet_store.update_long_memory(conn, IDENTITY, mem_id, "特别喜欢橘猫")
    assert ok is True
    mems = pet_store.load_long_memories(conn, IDENTITY, 10)
    assert [m["content"] for m in mems] == ["特别喜欢橘猫"]

    ok = pet_store.delete_long_memory(conn, IDENTITY, mem_id)
    assert ok is True
    assert pet_store.load_long_memories(conn, IDENTITY, 10) == []
    # 再删一次：已不存在，返回 False
    assert pet_store.delete_long_memory(conn, IDENTITY, mem_id) is False


@requires_mysql
def test_long_memory_update_delete_isolated(conn):
    """铁律 3：编辑/删除别人的记忆一律无效。"""
    mem_id = pet_store.add_long_memory(conn, IDENTITY, TENANT, "A的私事", "fact", 3, 1000.0)
    assert pet_store.update_long_memory(conn, 777777, mem_id, "越权改") is False
    assert pet_store.delete_long_memory(conn, 777777, mem_id) is False
    mems = pet_store.load_long_memories(conn, IDENTITY, 10)
    assert [m["content"] for m in mems] == ["A的私事"]


@requires_mysql
def test_long_memory_dedup_similar(conn):
    """去重：语义高度相似的新记忆更新原行而不是重复插入。"""
    first_id = pet_store.add_long_memory(conn, IDENTITY, TENANT, "我想考公务员", "goal", 3, 1000.0)
    second_id = pet_store.add_long_memory(conn, IDENTITY, TENANT, "我打算考公务员", "goal", 3, 1001.0)
    assert second_id == first_id  # 命中同一行
    mems = pet_store.load_long_memories(conn, IDENTITY, 10)
    assert len(mems) == 1
    assert mems[0]["content"] == "我打算考公务员"  # 新文本覆盖


@requires_mysql
def test_long_memory_dedup_keeps_distinct(conn):
    """去重不误伤：语义不同的记忆各自成行。"""
    pet_store.add_long_memory(conn, IDENTITY, TENANT, "想考公务员", "goal", 3, 1000.0)
    pet_store.add_long_memory(conn, IDENTITY, TENANT, "不想考公务员了", "fact", 3, 1001.0)
    mems = pet_store.load_long_memories(conn, IDENTITY, 10)
    assert len(mems) == 2  # 语义反转不能被吞掉
