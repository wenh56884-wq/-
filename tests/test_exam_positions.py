# tests/test_exam_positions.py
# 职责：国考职位表解析（纯函数）+ 入库成果 + /exam/positions API 回归。
# 依赖：pytest / fastapi.testclient / pymysql / etl.exam_positions（真实文件用例另需 xlrd）。
# 说明：MySQL 或职位表未同步时，相关用例自动跳过，不影响离线回归。

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402

from etl import exam_positions  # noqa: E402

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402

REAL_FILE = _ROOT / "data" / "raw" / "guokao" / "2027" / "招考简章.zip"

_HEADERS = [
    "部门代码", "部门名称", "用人司局", "机构性质", "招考职位", "职位属性",
    "职位分布", "职位简介", "职位代码", "机构层级", "考试类别", "招考人数",
    "专业", "学历", "学位", "政治面貌", "基层工作最低年限",
    "服务基层项目工作经历", "是否在面试阶段组织专业能力测试", "面试人员比例",
    "工作地点", "落户地点", "备注", "部门网站", "咨询电话1", "咨询电话2", "咨询电话3",
]

_SAMPLE = [
    "002000", "中央办公厅", "警卫局", "中央党群机关",
    "绿化管理岗位一级主任科员及以下", "普通职位", "其他职位", "从事绿化管理工作",
    "100110001001", "中央", "中央机关及其省级直属机构综合管理类", "1",
    "本科：082803风景园林；研究生：0862风景园林", "本科或硕士研究生",
    "与最高学历相对应的学位", "中共党员", "二年", "无限制", "是", "5:1",
    "北京市", "北京市", "备注原文", "www.example.gov.cn",
    "010-1", "", "",
]


# ----------------------------------------------------------------
# 1. 解析纯函数：字段映射 / 空行跳过 / 类型归一
# ----------------------------------------------------------------
def test_parse_rows_maps_fields_and_skips_blank_rows():
    rows = [
        ["招考职位由招录机关编报，专业、学历等由招录机关负责解释。"],
        _HEADERS,
        _SAMPLE,
        [""] * len(_HEADERS),                       # 空行：跳过
        ["002000", "中央办公厅", "", "", "", "", "", "", "", "", "", ""],  # 无职位代码：跳过
    ]
    out = exam_positions.parse_rows(rows, 2027, "中央党群机关", "test.xls")
    assert len(out) == 1
    rec = out[0]
    assert rec["dept_name"] == "中央办公厅"
    assert rec["bureau"] == "警卫局"
    assert rec["position_code"] == "100110001001"
    assert rec["headcount"] == 1
    assert rec["education"] == "本科或硕士研究生"
    assert rec["category"] == "中央党群机关"
    assert rec["data_file"] == "test.xls"
    assert rec["notice_url"] == "http://bm.scs.gov.cn/kl2027/"
    assert rec["source_key"] == exam_positions.source_key(2027, "002000", "100110001001")


def test_parse_rows_headcount_float_and_missing_header():
    rows = [_HEADERS, [*_SAMPLE[:11], 2.0, *_SAMPLE[12:]]]
    out = exam_positions.parse_rows(rows, 2027)
    assert out and out[0]["headcount"] == 2
    with pytest.raises(ValueError):
        exam_positions.parse_rows([["随便", "几列"]], 2027)


def test_source_key_is_year_scoped_and_stable():
    a = exam_positions.source_key(2027, "002000", "100110001001")
    b = exam_positions.source_key(2027, "002000", "100110001001")
    c = exam_positions.source_key(2028, "002000", "100110001001")
    assert a == b and a != c and len(a) == 32


# ----------------------------------------------------------------
# 2. 真实官方文件（data/raw 不入库；没有文件时跳过）
# ----------------------------------------------------------------
@pytest.mark.skipif(not REAL_FILE.exists(), reason="未下载 2027 招考简章.zip")
def test_real_official_file_counts():
    records = exam_positions.load_from_path(REAL_FILE, 2027)
    assert len(records) == 19426
    assert sum(int(r.get("headcount") or 0) for r in records) == 35691
    assert {r["category"] for r in records} == {
        "中央党群机关", "中央国家行政机关（本级）",
        "中央国家行政机关省级以下直属机构",
        "中央国家行政机关参照公务员法管理事业单位",
    }


# ----------------------------------------------------------------
# 3. 入库成果 + API（MySQL 无数据时跳过）
# ----------------------------------------------------------------
def _mysql_ok() -> bool:
    try:
        import pymysql

        from app.config import get_settings

        s = get_settings()
        conn = pymysql.connect(host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
                               password=s.mysql_password, database=s.mysql_db,
                               charset="utf8mb4")
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM `国考职位` WHERE `年度` = 2027")
            ok = int(cur.fetchone()[0]) > 0
        conn.close()
        return ok
    except Exception:
        return False


DB_OK = pytest.mark.skipif(not _mysql_ok(), reason="需要已同步国考职位的 MySQL")


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


@DB_OK
def test_positions_api_list_and_filters(client):
    resp = client.get("/exam/positions", params={"page_size": 5})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["year"] == 2027
    assert body["total"] == 19426
    assert body["total_headcount"] == 35691
    assert len(body["items"]) == 5
    first = body["items"][0]
    assert first["dept_name"] and first["position_name"] and first["headcount"] > 0

    resp = client.get("/exam/positions",
                      params={"dept": "国家税务总局重庆市税务局", "page_size": 3})
    assert resp.status_code == 200
    body = resp.json()
    assert 0 < body["total"] < 19426
    assert all("国家税务总局重庆市税务局" in it["dept_name"] for it in body["items"])

    resp = client.get("/exam/positions",
                      params={"place": "重庆", "education": "本科", "page_size": 3})
    assert resp.status_code == 200
    body = resp.json()
    assert 0 < body["total"] and 0 < body["total_headcount"]
    assert all("重庆" in it["work_place"] for it in body["items"])


@DB_OK
def test_positions_facets_and_detail(client):
    resp = client.get("/exam/positions/facets")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["year"] == 2027
    assert body["total_positions"] == 19426
    assert body["total_headcount"] == 35691
    assert body["source_url"].endswith("/kl2027/")
    assert {e["name"] for e in body["educations"]} >= {"本科及以上", "仅限本科"}

    pos_id = client.get("/exam/positions", params={"page_size": 1}).json()["items"][0]["id"]
    resp = client.get(f"/exam/positions/{pos_id}")
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["id"] == pos_id
    assert detail["dept_code"] and detail["position_code"]
    assert detail["notice_url"].endswith("/kl2027/")

    assert client.get("/exam/positions/999999999").status_code == 404
