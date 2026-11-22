# tests/test_interview_pool.py
# 职责：① 追问落进提纲的契约（轮次连续、可回溯、去重、预算）；② 岗位池扩到全国 2931 条后的接口契约。
# 说明：追问部分是纯函数测试；岗位池部分需要 MySQL（不可用时只跳过那一半）。

from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402

from app.routers.interview import (  # noqa: E402
    _build_probe_entry,
    _insert_probe,
    _job_for_outline,
    _probe_count,
    _used_bank_ids,
)
from engine.interview_probe import probe_plan  # noqa: E402

pytestmark = pytest.mark.interview

JOB = {"title": "Java后端开发工程师", "industry": "计算机软件",
       "skill_tags": ["Java", "MySQL", "Spring Boot"]}
WEAK = {"score": 55, "keyword_hits": ["Java"], "keyword_missed": ["索引", "事务"]}


def _outline(n: int = 6) -> list[dict]:
    return [{"round": i, "type": "project" if i in (3, 4) else "major",
             "question": f"第{i}题", "rubric": {"keywords": ["x"]},
             "source": {"kind": "bank", "id": f"q{i}"}} for i in range(1, n + 1)]


# ----------------------------------------------------------------
# 追问：落提纲
# ----------------------------------------------------------------
def test_insert_probe_keeps_rounds_contiguous_and_ordered():
    """追问插在本题之后，全表轮次必须仍是 1..N 连续整数（收卷靠顺序对齐）。"""
    outline = _outline(6)
    entry = {"round": 99, "type": "project", "question": "追问", "probe_of": 2,
             "source": {"kind": "bank", "id": "probe-x"}}
    _insert_probe(outline, 1, entry)          # 插在第 2 题（index=1）之后

    assert len(outline) == 7
    assert [o["round"] for o in outline] == list(range(1, 8))
    assert outline[2]["question"] == "追问"    # 位置对：紧跟被追问的那题
    assert outline[2]["probe_of"] == 2
    assert outline[3]["question"] == "第3题"   # 后面题序不丢


def test_insert_probe_at_tail_extends_interview():
    outline = _outline(6)
    _insert_probe(outline, 5, {"question": "尾追问", "probe_of": 6,
                               "source": {"kind": "bank", "id": "p"}})
    assert len(outline) == 7
    assert outline[-1]["question"] == "尾追问"
    assert outline[-1]["round"] == 7


def test_build_probe_entry_carries_bank_rubric_and_source():
    plan = probe_plan(JOB, "project", WEAK, "我会认真做。")
    assert plan, "浅答应能取到追问"
    entry = _build_probe_entry(plan, 3)

    assert entry is not None
    assert entry["probe_of"] == 3
    assert entry["round"] == 4
    assert entry["question_raw"] in entry["question"]
    # 评分口径来自题库考点，不是空的模板词
    assert entry["rubric"]["keywords"]
    assert entry["rubric"]["label"]
    assert entry["source"]["kind"] == "bank"
    assert entry["source"]["url"].startswith("http")
    assert entry["source"]["pool"] == "probe"


def test_build_probe_entry_refuses_unknown_bank_id():
    """取不到题库考点 → 放弃追问，绝不拿空 rubric 硬评。"""
    plan = {"question": "x", "bank_id": "__not_in_bank__", "qtype": "project",
            "source_name": "s", "source_url": "http://e.com", "family": "general",
            "engine_version": "probe-v1"}
    assert _build_probe_entry(plan, 1) is None


def test_used_bank_ids_dedupes_and_counts_probes():
    plan = probe_plan(JOB, "project", WEAK, "我会认真做。")
    entry = _build_probe_entry(plan, 2)
    outline = _outline(2) + [entry]

    used = _used_bank_ids(outline)
    assert len(used) == len(set(used)), "同一道题不能算两次"
    assert entry["source"]["id"] in used
    assert _probe_count(outline) == 1


def test_probe_budget_is_bounded(monkeypatch):
    """追问预算由 INTERVIEW_PROBE_MAX 控制（默认 2），超了就不再追问。"""
    import importlib

    import app.routers.interview as mod

    monkeypatch.setenv("INTERVIEW_PROBE_MAX", "1")
    reloaded = importlib.reload(mod)
    assert reloaded._PROBE_MAX == 1
    monkeypatch.setenv("INTERVIEW_PROBE_MAX", "2")
    importlib.reload(mod)


def test_job_snapshot_keeps_industry_for_retrieval():
    """行业丢了，题库只能落 general 族，追问就会跨行业乱抽。"""
    job = _job_for_outline({"title": "成本会计", "industry": "会计/审计",
                            "skill_tags": ["成本核算"], "education": "本科"})
    assert job["industry"] == "会计/审计"
    assert job["skill_tags"] == ["成本核算"]


# ----------------------------------------------------------------
# 岗位池：全国 2931 条
# ----------------------------------------------------------------
def _mysql_ok() -> bool:
    try:
        import pymysql

        from app.config import get_settings

        s = get_settings()
        pymysql.connect(host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
                        password=s.mysql_password, database=s.mysql_db).close()
        return True
    except Exception:
        return False


DB = pytest.mark.skipif(not _mysql_ok(), reason="需要 MySQL")


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from app.main import create_app

    return TestClient(create_app())


@pytest.fixture(scope="module")
def token(client):
    import pymysql

    from app.config import get_settings

    s = get_settings()
    conn = pymysql.connect(host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
                           password=s.mysql_password, database=s.mysql_db,
                           charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT `学号` FROM `学生` WHERE `租户编号`=1 ORDER BY `学号` LIMIT 1")
            row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        pytest.skip("库里没有学生")
    account = str(row["学号"])
    demo_password = str(getattr(s, "demo_password", "") or "")
    r = client.post("/auth/login", json={"role": "student", "account": account,
                                         "password": demo_password}) if demo_password else None
    if r is None or r.status_code != 200:
        r = client.post("/auth/login", json={"role": "student", "account": account,
                                             "password": account})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@DB
def test_jobs_default_pool_is_national(client, token):
    r = client.get("/interview/jobs", params={"limit": 5}, headers=token)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pool"] == "national"
    assert body["total"] >= 2900, f"全国池应约 2931 条，实际 {body['total']}"
    assert len(body["items"]) == 5
    assert body["items"][0]["pool"] == "national"


@DB
def test_jobs_keyword_filter_narrows_and_stays_consistent(client, token):
    full = client.get("/interview/jobs", params={"limit": 1}, headers=token).json()["total"]
    r = client.get("/interview/jobs", params={"limit": 20, "keyword": "会计"}, headers=token)
    body = r.json()
    assert 0 < body["total"] < full
    assert len(body["items"]) <= 20
    for it in body["items"]:
        hay = " ".join(str(it.get(k) or "") for k in ("title", "industry", "city", "company")
                       ) + " ".join(it.get("skill_tags") or [])
        assert "会计" in hay


@DB
def test_jobs_pagination_is_stable_without_overlap(client, token):
    p1 = client.get("/interview/jobs", params={"limit": 10, "offset": 0}, headers=token).json()
    p2 = client.get("/interview/jobs", params={"limit": 10, "offset": 10}, headers=token).json()
    ids1 = [it["id"] for it in p1["items"]]
    ids2 = [it["id"] for it in p2["items"]]
    assert len(ids1) == len(ids2) == 10
    assert not set(ids1) & set(ids2), "分页不能重复返回同一岗位"


@DB
def test_jobs_city_and_industry_filters(client, token):
    fac = client.get("/interview/jobs/facets", headers=token).json()
    city = fac["cities"][0]["name"]
    industry = fac["industries"][0]["name"]
    r1 = client.get("/interview/jobs", params={"limit": 5, "city": city}, headers=token).json()
    r2 = client.get("/interview/jobs", params={"limit": 5, "industry": industry}, headers=token).json()
    assert r1["total"] > 0 and all(city in (it["city"] or "") for it in r1["items"])
    assert r2["total"] > 0 and all(industry in (it["industry"] or "") for it in r2["items"])
    assert fac["total"] == client.get("/interview/jobs", params={"limit": 1},
                                      headers=token).json()["total"]


@DB
def test_jobs_tenant_pool_still_available(client, token):
    r = client.get("/interview/jobs", params={"limit": 5, "pool": "tenant"}, headers=token)
    body = r.json()
    assert body["pool"] == "tenant"
    assert body["total"] > 0
    assert all(it["pool"] == "tenant" for it in body["items"])


# ----------------------------------------------------------------
# 题库浏览 API：/interview/bank（只读，带出处）
# ----------------------------------------------------------------
@DB
def test_bank_browse_lists_items_with_sources(client, token):
    r = client.get("/interview/bank", params={"limit": 20}, headers=token)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 200, f"题库应 ≥200 条，实际 {body['total']}"
    assert 0 < body["shown"] <= 20
    it = body["items"][0]
    assert it["source_name"] and it["source_url"], "每条题必须带出处"
    assert it["qtype"] in body["qtypes"]
    assert set(body["families"]) >= {"it_software", "finance_bank", "accounting"}


@DB
def test_bank_browse_filters(client, token):
    r = client.get("/interview/bank", params={"family": "计算机软件", "limit": 100},
                   headers=token).json()
    assert r["total"] > 0
    assert all(it["family"] == "it_software" for it in r["items"]), "行业词要归到行业族"

    r2 = client.get("/interview/bank", params={"qtype": "scenario", "limit": 100},
                    headers=token).json()
    assert r2["total"] > 0 and all(it["qtype"] == "scenario" for it in r2["items"])

    r3 = client.get("/interview/bank", params={"q": "不存在の关键词xyz", "limit": 10},
                    headers=token).json()
    assert r3["total"] == 0 and r3["items"] == [], "无命中返回空，不冒充"


@DB
def test_bank_browse_requires_auth(client):
    assert client.get("/interview/bank").status_code == 401


# ----------------------------------------------------------------
# 岗位池：行业分层（diverse=1）
# ----------------------------------------------------------------
def _mysql_ok():
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


requires_mysql2 = pytest.mark.skipif(not _mysql_ok(), reason="MySQL 不可用")


def _student_ctx():
    from agents.tools import ToolContext

    import pymysql

    from app.config import get_settings

    s = get_settings()
    conn = pymysql.connect(host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
                           password=s.mysql_password, database=s.mysql_db,
                           charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT `编号`,`租户编号` FROM `学生` ORDER BY `编号` LIMIT 1")
            row = cur.fetchone()
    finally:
        conn.close()
    return ToolContext(actor_type="student", tenant_id=int(row["租户编号"]),
                       student_id=int(row["编号"]))


@requires_mysql2
def test_jobs_diverse_covers_industries_not_head_bias():
    """diverse=1：每个行业一个代表岗，行业数 = total；不做分层会只剩表头的 IT 岗。"""
    from app.routers.interview import job_candidates

    ctx = _student_ctx()
    res = job_candidates(diverse=1, limit=100, ctx=ctx)
    items = res["items"]
    assert len(items) >= 30, f"分层样本太小：{len(items)}"
    industries = [(i.get("industry") or "其他") for i in items]
    assert len(set(industries)) == len(industries), "分层要求每行业只出现一个代表岗"
    assert res["total"] == len(set((i.get("industry") or "其他") for i in items))
    # 不带关键词时 total 就是行业代表岗总数（即去重行业数），且 ≤ 全库岗位数
    plain = job_candidates(limit=5, ctx=ctx)
    assert plain["total"] >= res["total"]


@requires_mysql2
def test_jobs_without_diverse_keeps_old_behavior():
    """不带 diverse：老行为不变（按编号升序、total=全库过滤后总数）。"""
    from app.routers.interview import job_candidates

    ctx = _student_ctx()
    res = job_candidates(limit=5, ctx=ctx)
    ids = [i["id"] for i in res["items"]]
    assert ids == sorted(ids), "默认仍应按编号升序（分页稳定）"
    assert res["total"] > len(items_industries := res["items"])
