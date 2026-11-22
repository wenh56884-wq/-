# tests/test_job_catalog.py
# 职责：验证前台岗位目录与智能体岗位检索共用 `岗位` 主表。
# 说明：需要 MySQL；只读查询，不修改岗位数据。

from __future__ import annotations

from fastapi.testclient import TestClient
import pymysql
import pytest

from app.config import get_settings
from app.main import create_app


def _job_count() -> int:
    s = get_settings()
    try:
        conn = pymysql.connect(
            host=s.mysql_host,
            port=s.mysql_port,
            user=s.mysql_user,
            password=s.mysql_password,
            database=s.mysql_db,
            charset="utf8mb4",
            connect_timeout=3,
        )
    except (pymysql.MySQLError, OSError):
        pytest.skip("MySQL 不可用，跳过岗位目录集成测试")
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM `岗位`")
            return int(cur.fetchone()[0])
    finally:
        conn.close()


def test_job_api_uses_canonical_catalog():
    total = _job_count()
    if total <= 0:
        pytest.skip("岗位主表为空")

    client = TestClient(create_app())
    resp = client.get("/job/list", params={"page_size": 1})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == total
    assert len(body["items"]) == 1

    item = body["items"][0]
    assert item["id"] > 0
    assert item["title"]
    assert item["company"]
    assert item["status"] == "unknown"

    detail = client.get(f"/job/list/{item['id']}")
    assert detail.status_code == 200
    assert detail.json()["title"] == item["title"]
