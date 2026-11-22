# tests/test_export_fields.py
# 职责：导出「自选字段」——投影层纯函数 + 导出接口按 fields 只出勾选的列。
# 说明：纯函数部分不依赖数据库；接口部分需要 MySQL（不可用时跳过）。

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.routers import export as export_mod

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
TEACHER = ("T001", "123456h")


# ---------------------------------------------------------------- 投影层（纯函数）
_CAT = [
    {"key": "a", "label": "甲", "group": "G1"},
    {"key": "b", "label": "乙", "group": "G1"},
    {"key": "c", "label": "丙", "group": "G2"},
]
_RECS = [{"a": 1, "b": 2, "c": 3}, {"a": 4, "b": 5, "c": 6}]


def test_project_keeps_catalog_order():
    """勾选顺序不影响列序：按目录顺序出，换个人勾同一组字段结果必须一样。"""
    headers, rows, keys = export_mod._project(_CAT, _RECS, "c,a")
    assert headers == ["甲", "丙"]
    assert keys == ["a", "c"]
    assert rows == [[1, 3], [4, 6]]


def test_project_empty_means_all():
    headers, rows, keys = export_mod._project(_CAT, _RECS, "")
    assert keys == ["a", "b", "c"]
    assert headers == ["甲", "乙", "丙"]
    assert len(rows) == 2


def test_project_unknown_field_422():
    with pytest.raises(Exception) as exc:
        export_mod._project(_CAT, _RECS, "a,nope")
    assert "nope" in str(exc.value.detail)


def test_project_blank_fields_fall_back_to_all():
    """只有逗号空格（fields=,,）时按全字段处理，而不是报错。"""
    _, _, keys = export_mod._project(_CAT, _RECS, " , ,")
    assert keys == ["a", "b", "c"]


# ---------------------------------------------------------------- 取值（纯函数）
def test_student_values_missing_metrics_stay_none():
    """缺失指标保持 None，不写 0——否则导出的表看起来像「每项都考了 0 分」。"""
    v = export_mod._student_values(
        {"student_no": "S1", "name": "张三", "class_name": "C1"},
        {"level": "red", "risk_score": 82, "reasons": ["挂科2门", "出勤低"],
         "coverage": 100, "metrics": {"gpa": None, "fail_count": 2}},
    )
    assert v["risk_score"] == 82
    assert v["reasons"] == "挂科2门；出勤低"
    assert v["level_text"] == "红色预警"
    assert v["fail_count"] == 2
    assert v["gpa"] is None
    assert v["attendance_rate"] is None
    assert v["handbook_flag"] == ""


def test_grade_values_pass_flag_and_retake():
    recs = export_mod._grade_values([
        {"student_no": "S1", "name": "张三", "term": "2025-2026-2",
         "course_name": "数据结构", "credit": "4", "score": "59.5", "retake": 1},
        {"student_no": "S1", "name": "张三", "course_name": "算法", "credit": "3", "score": None},
    ])
    assert recs[0]["score"] == 59.5 and recs[0]["passed"] == "不及格"
    assert recs[0]["retake_text"] == "是" and recs[0]["credit"] == 4.0
    # 没分数就说没分数，不猜及格
    assert recs[1]["score"] is None and recs[1]["passed"] == ""


# ---------------------------------------------------------------- 接口
@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


def _token(client: TestClient, role: str, account: str, password: str) -> str:
    resp = client.post("/auth/login", json={"role": role, "account": account, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@requires_mysql
def test_fields_catalog(client: TestClient):
    tok = _token(client, "teacher", *TEACHER)
    h = {"Authorization": f"Bearer {tok}"}
    r = client.get("/export/fields", params={"dataset": "students"}, headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    keys = [f["key"] for f in data["fields"]]
    assert "student_no" in keys and "gpa" in keys and "handbook_flag" in keys
    assert data["total"] == len(keys)
    # 分组必须覆盖全部字段，不能有字段在界面上找不到
    grouped = sum(len(g["fields"]) for g in data["groups"])
    assert grouped == data["total"]

    bad = client.get("/export/fields", params={"dataset": "nope"}, headers=h)
    assert bad.status_code == 404


@requires_mysql
def test_fields_catalog_role_guard(client: TestClient):
    """学生不能拿到教师数据集（虽然拿到也没数据，但不该给口子）。"""
    tok = _token(client, "student", "AI20230001", "123456h")
    h = {"Authorization": f"Bearer {tok}"}
    assert client.get("/export/fields", params={"dataset": "students"}, headers=h).status_code == 403
    assert client.get("/export/fields", params={"dataset": "my-grades"}, headers=h).status_code == 200


@requires_mysql
def test_export_students_only_picked_columns(client: TestClient):
    tok = _token(client, "teacher", *TEACHER)
    h = {"Authorization": f"Bearer {tok}"}
    cls = client.get("/teacher/classes", headers=h).json()["classes"][0]["class_name"]
    r = client.get("/export/students",
                   params={"class_name": cls, "fields": "name,risk_score,gpa", "fmt": "json"},
                   headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert [f["label"] for f in data["fields"]] == ["姓名", "风险分", "GPA"]
    first = data["students"][0]
    assert set(first) == {"name", "risk_score", "gpa"}


@requires_mysql
def test_export_grades_drops_summary_when_fields_picked(client: TestClient):
    """勾了字段就不该再附一张 8 列的「个人汇总」sheet。"""
    tok = _token(client, "teacher", *TEACHER)
    h = {"Authorization": f"Bearer {tok}"}
    cls = client.get("/teacher/classes", headers=h).json()["classes"][0]["class_name"]

    r = client.get("/export/grades",
                   params={"class_name": cls, "fields": "course_name,score", "fmt": "json"},
                   headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["summary"] == []

    full = client.get("/export/grades", params={"class_name": cls, "fmt": "json"}, headers=h)
    assert len(full.json()["summary"]) > 0


@requires_mysql
def test_export_xlsx_headers_follow_fields(client: TestClient):
    """Excel 真文件里表头就是勾的那几列（防止只改了 JSON 忘了表格）。"""
    openpyxl = pytest.importorskip("openpyxl")
    tok = _token(client, "teacher", *TEACHER)
    h = {"Authorization": f"Bearer {tok}"}
    cls = client.get("/teacher/classes", headers=h).json()["classes"][0]["class_name"]
    r = client.get("/export/students",
                   params={"class_name": cls, "fields": "name,gpa", "fmt": "xlsx"},
                   headers=h)
    assert r.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    ws = wb[wb.sheetnames[0]]
    assert [c.value for c in next(ws.iter_rows(max_row=1))] == ["姓名", "GPA"]
