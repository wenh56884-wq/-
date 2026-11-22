# tests/test_grades_api.py
# 职责：成绩单 API——学生本人 / 教师按学号 / 越权拦截 / 学年结构。
# 说明：需要 MySQL（可用时跑）；不依赖外部 LLM。

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

pytest.importorskip("fastapi")


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


requires_mysql = pytest.mark.skipif(not _mysql_ok(), reason="MySQL 不可用")
STUDENT = ("AI20230001", "123456h")
TEACHER = ("T001", "123456h")


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


def _token(client: TestClient, role: str, account: str, password: str) -> str:
    resp = client.post("/auth/login", json={"role": role, "account": account, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@requires_mysql
def test_student_me_returns_all_years(client):
    token = _token(client, "student", *STUDENT)
    resp = client.get("/grades/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["student"]["student_no"] == STUDENT[0]
    assert body["summary"]["year_count"] >= 1
    assert body["summary"]["term_count"] >= 1
    assert body["summary"]["record_count"] > 0
    assert len(body["years"]) == body["summary"]["year_count"]
    for year in body["years"]:
        assert year["terms"], f"{year['year']} 没有学期"
        for term in year["terms"]:
            assert term["records"], f"{term['term']} 没有成绩记录"
            assert term["courses"], f"{term['term']} 没有课程汇总"


@requires_mysql
def test_teacher_can_read_student_grades(client):
    student_token = _token(client, "student", *STUDENT)
    teacher_token = _token(client, "teacher", *TEACHER)
    mine = client.get("/grades/me", headers={"Authorization": f"Bearer {student_token}"}).json()
    resp = client.get(f"/grades/student/{STUDENT[0]}",
                      headers={"Authorization": f"Bearer {teacher_token}"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["summary"] == mine["summary"]


@requires_mysql
def test_student_cannot_use_teacher_grade_endpoint(client):
    token = _token(client, "student", *STUDENT)
    resp = client.get(f"/grades/student/{STUDENT[0]}",
                      headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


@requires_mysql
def test_unknown_student_is_denied_for_teacher(client):
    token = _token(client, "teacher", *TEACHER)
    resp = client.get("/grades/student/NO_SUCH_STUDENT_9",
                      headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403
