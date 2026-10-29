# tests/test_agent_memory.py
# 职责：长期记忆的向量归一化、召回排序、租户/主体隔离与去重（纯函数 + MySQL）。
# 依赖：pytest / engine.agent_memory / agents.tools.ToolContext / pymysql。
# 说明：MySQL 不可用时只跑离线向量用例；写库用例自动跳过。

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402

from agents.tools import ToolContext  # noqa: E402
from engine import agent_memory as mem  # noqa: E402


def _mysql_conn():
    import pymysql

    from app.config import get_settings

    s = get_settings()
    return pymysql.connect(host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
                           password=s.mysql_password, database=s.mysql_db,
                           charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)


def _mysql_ok() -> bool:
    try:
        _mysql_conn().close()
        return True
    except Exception:
        return False


DB_OK = pytest.mark.skipif(not _mysql_ok(), reason="需要 MySQL")


# ----------------------------------------------------------------
# 1. 离线：归一化与向量
# ----------------------------------------------------------------
def test_normalize_removes_filler_but_keeps_domain_words():
    text = mem.normalize_text("我是计算机专业，想考公务员，优先重庆的岗位")
    assert "计算机" in text and "公务员" in text and "重庆" in text
    assert "我是" not in text and "想" not in text and "的" not in text


def test_embed_is_deterministic_and_short_query_matches():
    a = mem.embed("我是计算机专业，想考公务员，优先重庆的岗位")
    b = mem.embed("我是计算机专业，想考公务员，优先重庆的岗位")
    assert a == b
    query = mem.embed("考公 重庆 岗位")
    assert mem._dot(query, a) > mem._dot(mem.embed("我的成绩怎么样"), a)
    # 无关问题不应该拿到召回分
    assert mem._dot(mem.embed("奖学金政策"), a) < mem.MIN_RECALL_SCORE


def test_format_for_prompt_marks_numbers_as_background():
    text = mem.format_for_prompt([{"kind": "goal", "content": "想考公务员"}])
    assert "想考公务员" in text and "数字不得直接引用" in text


# ----------------------------------------------------------------
# 2. 写库：去重 / 召回 / 隔离 / 归档
# ----------------------------------------------------------------
@DB_OK
def test_memory_roundtrip_isolation_and_archive():
    import uuid

    conn = _mysql_conn()
    mem.ensure_schema(conn)
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("SELECT `编号`,`租户编号` FROM `学生` ORDER BY `编号` LIMIT 2")
        students = cur.fetchall()
    assert len(students) >= 2, "演示库至少需要两名学生"
    a = ToolContext(actor_type="student", tenant_id=int(students[0]["租户编号"]),
                    student_id=int(students[0]["编号"]))
    b = ToolContext(actor_type="student", tenant_id=int(students[1]["租户编号"]),
                    student_id=int(students[1]["编号"]))

    marker = uuid.uuid4().hex[:8]
    content = f"单元测试记忆{marker}：想考公务员，优先重庆的岗位"
    try:
        mid, is_new = mem.add(conn, a, content, kind="goal", importance=4)
        conn.commit()
        assert is_new
        # 去重：同一件事再说一遍只更新，不新增
        mid2, is_new2 = mem.add(conn, a, content, kind="goal", importance=3)
        conn.commit()
        assert mid2 == mid and not is_new2

        def marker_hits(ctx, query):
            # 只认本次用例写入的内容，避免并行进程/历史记忆干扰断言
            return [h for h in mem.search(conn, ctx, query) if marker in h["content"]]

        hits = marker_hits(a, "考公 重庆 岗位")
        conn.commit()
        assert hits and hits[0]["id"] == mid
        assert hits[0]["score"] >= mem.MIN_RECALL_SCORE
        # 无关问题不召回
        assert marker_hits(a, "奖学金政策") == []
        # 主体隔离：另一个学生看不到
        assert marker_hits(b, "考公 重庆 岗位") == []
        # 归档后本人也看不到
        assert mem.archive(conn, a, mid)
        conn.commit()
        assert marker_hits(a, "考公 重庆 岗位") == []
    finally:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM `智能体记忆` WHERE `内容` LIKE %s", (f"%{marker}%",))
        conn.commit()
        conn.close()


@DB_OK
def test_memory_tenant_isolation():
    conn = _mysql_conn()
    mem.ensure_schema(conn)
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("SELECT `编号`,`租户编号` FROM `学生` ORDER BY `编号` LIMIT 1")
        student = cur.fetchone()
    ctx = ToolContext(actor_type="student", tenant_id=int(student["租户编号"]),
                      student_id=int(student["编号"]))
    other = ToolContext(actor_type="student", tenant_id=999,
                        student_id=int(student["编号"]))
    mid = 0
    try:
        mid, _ = mem.add(conn, other, "这是另一个租户的记忆", kind="fact")
        conn.commit()
        assert not [h for h in mem.search(conn, ctx, "另一个租户的记忆")
                    if "另一个租户的记忆" in h["content"]]
        assert [h for h in mem.search(conn, other, "另一个租户的记忆")
                if "另一个租户的记忆" in h["content"]]
    finally:
        if mid:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM `智能体记忆` WHERE `编号`=%s", (mid,))
            conn.commit()
        conn.close()
