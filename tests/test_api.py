# tests/test_api.py
# 职责：校验 P6-1 网关层——JWT 登录、身份注入、越权拦截、/health、/chat 与审计留痕
# 依赖：pytest / fastapi.testclient / httpx / pymysql
# 说明：需要 MySQL（不可用时整文件跳过）；教师账号由 fixture 临时插入并在用例结束后清理

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from app.auth import hash_password  # noqa: E402
from app.main import create_app  # noqa: E402

TERM = "2025-2026-2"
TENANT = 1
# 进程唯一：同一台机器并行跑测试时，避免两个进程互相删除对方的临时教师
EMPLOYEE_NO = f"T9{os.getpid() % 100000:05d}"
TEACHER_PWD = "teacher@123"


def _mysql_ok() -> bool:
    try:
        import pymysql

        from app.config import get_settings

        s = get_settings()
        conn = pymysql.connect(host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
                               password=s.mysql_password, database=s.mysql_db,
                               charset="utf8mb4")
        conn.close()
        return True
    except Exception:
        return False


MYSQL_OK = _mysql_ok()
requires_mysql = pytest.mark.skipif(not MYSQL_OK, reason="MySQL 不可用")


def _conn():
    import pymysql

    from app.config import get_settings

    s = get_settings()
    # autocommit=True：避免同一连接长时间持事务导致读不到其它连接新写的审计行
    return pymysql.connect(host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
                           password=s.mysql_password, database=s.mysql_db,
                           charset="utf8mb4", autocommit=True,
                           cursorclass=pymysql.cursors.DictCursor)


@pytest.fixture(scope="module")
def db():
    """MySQL 连接 + 准备一个教师账号与一个真实班级/学生，用例结束清理。"""
    conn = _conn()
    created = False
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM teacher WHERE employee_no = %s", (EMPLOYEE_NO,))
        if cur.fetchone() is None:
            cur.execute(
                "INSERT INTO teacher (tenant_id, name, employee_no, role, password_hash) "
                "VALUES (%s, %s, %s, 'teacher', %s)",
                (TENANT, "测试教师", EMPLOYEE_NO, hash_password(TEACHER_PWD)),
            )
            created = True
        cur.execute(
            "SELECT s.class_name AS class_name, COUNT(DISTINCT s.id) AS n "
            "FROM student s JOIN score sc ON sc.student_id = s.id AND sc.term = %s "
            "WHERE s.tenant_id = %s GROUP BY s.class_name ORDER BY n DESC LIMIT 1",
            (TERM, TENANT),
        )
        klass_row = cur.fetchone() or {}
        cur.execute(
            "SELECT s.id AS id, s.student_no AS student_no FROM student s "
            "JOIN score sc ON sc.student_id = s.id AND sc.term = %s "
            "WHERE s.tenant_id = %s AND s.class_name = %s "
            "ORDER BY s.student_no LIMIT 1", (TERM, TENANT, klass_row.get("class_name")),
        )
        stu_row = cur.fetchone() or {}
    conn.commit()
    yield conn, str(klass_row.get("class_name") or ""), stu_row
    if created:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM teacher WHERE employee_no = %s", (EMPLOYEE_NO,))
        conn.commit()
    conn.close()


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


def _login(client: TestClient, role: str, account: str, password: str):
    return client.post("/auth/login",
                       json={"role": role, "account": account, "password": password})


# ----------------------------------------------------------------
# 1. 登录
# ----------------------------------------------------------------
@requires_mysql
def test_login_success_returns_token(client, db):
    """教师登录成功 → token + 身份摘要，且不含任何口令字段。"""
    resp = _login(client, "teacher", EMPLOYEE_NO, TEACHER_PWD)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["access_token"] and body["token_type"] == "bearer"
    assert body["role"] == "teacher" and body["tenant_id"] == TENANT
    assert "password" not in body and "password_hash" not in body
    assert body["expires_in"] > 0


@requires_mysql
def test_login_wrong_password_is_401(client, db):
    """口令错误 → 401 中文提示（不泄露账号是否存在）。"""
    resp = _login(client, "teacher", EMPLOYEE_NO, "wrong-password")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "账号或口令错误"


@requires_mysql
def test_login_unknown_role_is_422(client, db):
    """role 非法 → 422 参数错。"""
    resp = _login(client, "hacker", "x", "y")
    assert resp.status_code == 422
    assert "role 只能是" in resp.json()["detail"]


# ----------------------------------------------------------------
# 2. 身份注入与越权
# ----------------------------------------------------------------
@requires_mysql
def test_no_token_is_401(client, db):
    """未携带 token → 401。"""
    conn, klass, _ = db
    resp = client.get("/teacher/warnings", params={"class_name": klass, "term": TERM})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "未认证或 token 已失效"


@requires_mysql
def test_student_calling_teacher_api_is_403(client, db):
    """学生 token 调教师接口 → 403（学生拿不到班级数据）。"""
    conn, klass, stu = db
    token = _login(client, "student", stu["student_no"], stu["student_no"]).json()
    assert token["access_token"], "学生应能用『学号即初始口令』登录（演示约定）"
    resp = client.get(
        "/teacher/warnings",
        params={"class_name": klass, "term": TERM},
        headers={"Authorization": f"Bearer {token['access_token']}"},
    )
    assert resp.status_code == 403
    assert "学生账号无权访问教师端接口" in resp.json()["detail"]


@requires_mysql
def test_student_sees_only_self(client, db):
    """学生端没有入参学号：返回的永远是本人（= 登录学号）。"""
    conn, klass, stu = db
    token = _login(client, "student", stu["student_no"], stu["student_no"]).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.get("/student/warning", params={"term": TERM}, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["student_no"] == str(stu["student_no"])
    assert set(("risk_score", "level", "reasons", "coverage", "missing")) <= set(body)

    recs = client.get("/student/recommendations", params={"term": TERM, "top_n": 3},
                      headers=headers)
    assert recs.status_code == 200
    body_rec = recs.json()
    assert body_rec["student_no"] == str(stu["student_no"])
    # P9 已实现：返回真实推荐（v1.0），每条字段齐全
    assert body_rec["recommend_version"] == "v1.0"
    assert isinstance(body_rec["items"], list)
    for item in body_rec["items"][:5]:
        assert set(("job_id", "title", "final_score", "advice")) <= set(item)


@requires_mysql
def test_unknown_class_is_422(client, db):
    """教师输入不存在的班级 → 422 参数错误（真正的跨租户 403 由工具层测试覆盖）。"""
    token = _login(client, "teacher", EMPLOYEE_NO, TEACHER_PWD).json()["access_token"]
    resp = client.get("/teacher/class-overview",
                      params={"class_name": "RJ9901", "term": TERM},
                      headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 422
    assert "不存在" in resp.json()["detail"]


@requires_mysql
def test_student_and_teacher_numbers_agree(client, db):
    """同一名学生：学生端接口与教师端接口给出的风险分必须一致（跨入口一致性）。"""
    conn, klass, stu = db
    token = _login(client, "teacher", EMPLOYEE_NO, TEACHER_PWD).json()["access_token"]
    t_headers = {"Authorization": f"Bearer {token}"}
    listed = client.get("/teacher/warnings", params={"class_name": klass, "term": TERM},
                        headers=t_headers).json()
    mine_row = next((r for r in listed["items"]
                     if r["student_no"] == str(stu["student_no"])), None)

    s_token = _login(client, "student", stu["student_no"], stu["student_no"]).json()["access_token"]
    mine = client.get("/student/warning", params={"term": TERM},
                      headers={"Authorization": f"Bearer {s_token}"}).json()
    if mine_row is not None:
        assert mine_row["risk_score"] == mine["risk_score"], "两端数值必须一致"
        assert mine_row["level"] == mine["level"]


# ----------------------------------------------------------------
# 3. /health 与 /chat
# ----------------------------------------------------------------
@requires_mysql
def test_health_reports_real_connectivity(client, db):
    """/health 真实检测 db / duckdb；llm 只看 key 是否配置。"""
    body = client.get("/health").json()
    assert set(body) == {"status", "db", "duckdb", "llm"}
    assert body["db"] == "ok" and body["duckdb"] == "ok"
    assert body["llm"] in ("configured", "missing")
    assert body["status"] == "ok"


@requires_mysql
def test_chat_returns_answer_and_trace_id(client, db):
    """/chat 必须返回 answer + trace_id（图未就绪时降级，但不许报错）。"""
    token = _login(client, "teacher", EMPLOYEE_NO, TEACHER_PWD).json()["access_token"]
    resp = client.post("/chat", json={"query": "本周有哪些高风险学生？", "term": TERM},
                       headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["answer"] and body["trace_id"]
    assert "degraded" in body


@requires_mysql
def test_chat_requires_auth(client, db):
    resp = client.post("/chat", json={"query": "hi"})
    assert resp.status_code == 401


# ----------------------------------------------------------------
# 4. 审计：匿名请求也留痕
# ----------------------------------------------------------------
@requires_mysql
def test_anonymous_request_still_audited(client, db):
    """失败请求（无 token）也要写 audit_log：这是『失败也写』的硬性规则。"""
    conn, klass, _ = db
    probe = f"audit-{uuid.uuid4().hex[:8]}"
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(1) AS n FROM audit_log")
        before = int(cur.fetchone()["n"])

    client.get("/teacher/warnings",
               params={"class_name": klass, "term": TERM, "probe": probe})

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(1) AS n FROM audit_log")
        after = int(cur.fetchone()["n"])
        # 只认本次请求的探针，避免并行测试进程的审计行插在中间
        cur.execute(
            "SELECT actor_type, actor_id, action, detail FROM audit_log "
            "WHERE action = %s AND target LIKE %s ORDER BY id DESC LIMIT 1",
            ("GET /teacher/warnings", f"%{probe}%"),
        )
        last = cur.fetchone()
    assert after > before, "匿名/失败请求也必须写审计"
    assert last is not None, f"未找到本次请求的审计行（probe={probe}）"
    detail = last["detail"]
    if not isinstance(detail, dict):
        import json

        detail = json.loads(detail)
    assert last["action"] == "GET /teacher/warnings"
    assert detail["status"] == 401
    assert "duration_ms" in detail


# ----------------------------------------------------------------
# 5. 生涯规划：年级分层 + 目标选择
# ----------------------------------------------------------------
@requires_mysql
def test_career_guide_returns_grade_and_options(client, db):
    """学生端 /career/guide：必须返回年级、四选一选项与规划结构。"""
    conn, klass, stu = db
    token = _login(client, "student", stu["student_no"], stu["student_no"]).json()["access_token"]
    resp = client.get("/career/guide", params={"term": TERM},
                      headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["student_no"] == str(stu["student_no"])
    assert body["grade"]
    assert [opt["value"] for opt in body["options"]] == ["考公", "考研", "考编", "就业"]
    assert isinstance(body["steps"], list)
    assert body["engine_version"] == "career-guide-v1"


@requires_mysql
def test_career_intent_roundtrip_and_restore(client, db):
    """保存目标后 guide 能读到；用例结束恢复原值（不污染演示数据）。"""
    conn, klass, stu = db
    student_id = int(stu["id"])
    token = _login(client, "student", stu["student_no"], stu["student_no"]).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    with conn.cursor() as cur:
        cur.execute("SELECT intent FROM career_intent WHERE student_id = %s", (student_id,))
        before = cur.fetchone()

    try:
        saved = client.put("/career/intent", json={"intent": "考研"}, headers=headers)
        assert saved.status_code == 200, saved.text
        assert saved.json()["intent"] == "考研"

        guide = client.get("/career/guide", params={"term": TERM}, headers=headers).json()
        assert guide["intent"] == "考研"
        assert guide["needs_intent"] is False
        assert guide["steps"]
    finally:
        with conn.cursor() as cur:
            if before is None:
                cur.execute("DELETE FROM career_intent WHERE student_id = %s", (student_id,))
            else:
                cur.execute("UPDATE career_intent SET intent = %s WHERE student_id = %s",
                            (before["intent"], student_id))
        conn.commit()


@requires_mysql
def test_career_intent_rejects_unknown_value(client, db):
    """非法目标 → 422，不落库。"""
    conn, klass, stu = db
    token = _login(client, "student", stu["student_no"], stu["student_no"]).json()["access_token"]
    resp = client.put("/career/intent", json={"intent": "乱写"},
                      headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 422
    assert "考公/考研/考编/就业" in resp.json()["detail"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
