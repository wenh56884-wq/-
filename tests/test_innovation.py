# tests/test_innovation.py
# 职责：钉住创新全景聚合层的四条红线——
#   ① 缺失一律 available=False + value=None，禁止用 0 冒充「没有数据」；
#   ② 抓取时间与核实日期分字段，不互相顶替；
#   ③ 越权（学生缺本人身份 / 教师无任教班级）必须抛 PermissionError，由路由转 403；
#   ④ 教师端不返回个人证据链（instance 恒为 None）。
# 前 8 个用例纯内存（monkeypatch 数据层），不依赖数据库；最后 4 个是真实库集成用例，
# 连不上库时自动跳过，不会把环境问题算成代码回归。

from __future__ import annotations

import pymysql
import pytest

from app.config import get_settings
from engine import innovation


# --------------------------------------------------------------------------- #
# 一、纯函数语义：缺失不冒充、日期不混用
# --------------------------------------------------------------------------- #
def test_kpi_without_value_is_unavailable_and_null():
    """没有数据时 value 必须是 None，且 available=False——绝不能写 0。"""
    card = innovation._kpi("real_interview", "真实投递与录用", None, None, "—", None)
    assert card["available"] is False
    assert card["value"] is None
    assert card["as_of"] is None


def test_kpi_with_value_marks_available_and_truncates_date():
    card = innovation._kpi("job_supply", "在库岗位", 2931, "条", "岗位", "2025-08-28 00:00:00")
    assert card["available"] is True
    assert card["value"] == 2931
    assert card["as_of"] == "2025-08-28"


def test_empty_step_is_unavailable_not_zero():
    step = innovation._step("fill", "补：缺口回到课程", None, "课程 / 岗位技能标签")
    assert step["available"] is False
    assert step["summary"] is None
    # 来源表仍要写清，方便前端显示「来源：课程 / 岗位技能标签」
    assert step["source_table"] == "课程 / 岗位技能标签"


def test_usable_tags_drops_punctuation_only_tags():
    """真实数据里出现过 "[" 这种脏标签，会渲染成「岗位要求[，你的课程记录未体现」。"""
    assert innovation._usable_tags(["数据分析", "[", "  ", "", None, "SQL"]) == ["数据分析", "SQL"]


# --------------------------------------------------------------------------- #
# 二、越权与角色边界
# --------------------------------------------------------------------------- #
def test_student_without_identity_is_rejected():
    with pytest.raises(PermissionError):
        innovation.build_overview(role="student", tenant_id=1, student_id=None)


def test_teacher_without_identity_is_rejected():
    with pytest.raises(PermissionError):
        innovation.build_overview(role="teacher", tenant_id=1, teacher_id=None)


def test_unknown_role_is_rejected():
    with pytest.raises(PermissionError):
        innovation.build_overview(role="admin", tenant_id=1, student_id=1)


# --------------------------------------------------------------------------- #
# 三、全空数据下的降级契约（monkeypatch 数据层，不连库）
# --------------------------------------------------------------------------- #
def _blank_student(monkeypatch):
    monkeypatch.setattr(innovation, "_student_row",
                        lambda tenant_id, student_id: {"id": student_id, "student_no": "X000",
                                                       "class_name": "C1", "major": "测试"})
    monkeypatch.setattr(innovation, "_latest_term", lambda student_id: None)
    monkeypatch.setattr(innovation, "_instance", lambda *a, **k: None)
    monkeypatch.setattr(innovation, "_query", lambda sql, params=(): [])
    monkeypatch.setattr(innovation, "_one", lambda sql, params=(): {})


def test_student_overview_degrades_to_unavailable_without_data(monkeypatch):
    _blank_student(monkeypatch)
    data = innovation.build_overview(role="student", tenant_id=1, student_id=7)

    assert data["role"] == "student"
    assert data["screens"]["loop"]["instance"] is None
    for card in data["screens"]["result"]["kpis"]:
        assert card["available"] is False, card["key"]
        assert card["value"] is None, card["key"]
    for step in data["screens"]["loop"]["steps"]:
        assert step["available"] is False, step["key"]
        assert step["summary"] is None, step["key"]
    for source in data["screens"]["trust"]["sources"]:
        assert source["records"] is None, source["name"]
    assert data["screens"]["trust"]["supply"]["cells"] == []
    assert data["screens"]["trust"]["interest"] == []


def test_teacher_never_gets_personal_instance(monkeypatch):
    monkeypatch.setattr(innovation, "_teacher_classes", lambda tenant_id, teacher_id: ["C1", "C2"])
    monkeypatch.setattr(innovation, "_latest_term", lambda student_id: None)
    monkeypatch.setattr(innovation, "_query", lambda sql, params=(): [])
    monkeypatch.setattr(innovation, "_one", lambda sql, params=(): {})

    # 捕获 _kpis_practice 的范围入参：教师端 KPI 必须限定在任教班级，不许全租户聚合
    captured: dict[str, object] = {}
    real_practice = innovation._kpis_practice

    def spy(tenant_id, class_names):
        captured["classes"] = class_names
        return real_practice(tenant_id, class_names)

    monkeypatch.setattr(innovation, "_kpis_practice", spy)
    data = innovation.build_overview(role="teacher", tenant_id=1, teacher_id=3)

    assert data["role"] == "teacher"
    assert data["screens"]["loop"]["instance"] is None, "教师端不得出现个人证据链"
    assert data["scope"]["class_count"] == 2
    assert data["scope"]["class_id"] is None, "多班任教时不假装只有一个班"
    assert captured["classes"] == ["C1", "C2"], "KPI 聚合范围必须是任教班级"


def test_sources_keep_verified_and_fetched_apart(monkeypatch):
    """考证（人工核实）与招考（抓取）不得互相顶替日期字段。"""
    canned = {
        "招考公告": {"n": 43, "fetched": "2026-11-16 18:13:12", "published": "2026-11-01"},
        "国考职位": {"n": 19426, "fetched": "2026-11-22 18:00:45", "published": None},
        "考证目录": {"n": 8, "verified": "2026-11-19"},
        "面试题库": {"n": 234, "fetched": "2026-10-27"},
        "FROM `岗位`": {"n": 2931, "published": "2025-08-28"},
    }

    def fake_one(sql, params=()):
        for key, row in canned.items():
            if key in sql:
                return dict(row)
        return {}

    monkeypatch.setattr(innovation, "_one", fake_one)
    sources = {s["name"]: s for s in innovation._sources(1)}

    cert = sources["考证目录"]
    assert cert["kind"] == "verified"
    assert cert["latest_verified_at"] == "2026-11-19"
    assert cert["latest_fetched_at"] is None

    exam = sources["招考公告（考公/考编/考研）"]
    assert exam["kind"] == "fetched"
    assert exam["latest_fetched_at"] == "2026-11-16"
    assert exam["latest_verified_at"] is None, "抓取时间不许冒充核实日期"


def test_supply_empty_data_returns_empty_city_counts(monkeypatch):
    """查不到城市/行业时，city_counts 也必须降级为空字典，不用 0 冒充。"""
    monkeypatch.setattr(innovation, "_query", lambda sql, params=(): [])
    supply = innovation._supply()

    assert supply["city_counts"] == {}
    assert supply["cells"] == []
    assert supply["cities"] == []
    assert supply["industries"] == []


def test_supply_empty_data_returns_empty_province_counts(monkeypatch):
    """空数据时省级聚合也必须降级：空字典 + 0 个未映射城市。"""
    monkeypatch.setattr(innovation, "_query", lambda sql, params=(): [])
    supply = innovation._supply()

    assert supply["province_counts"] == {}
    assert supply["unmapped_cities"] == 0
    assert isinstance(supply["unmapped_cities"], int)


# --------------------------------------------------------------------------- #
# 四、真实库集成（连不上库就跳过）
# --------------------------------------------------------------------------- #
def _db_available() -> bool:
    try:
        s = get_settings()
        conn = pymysql.connect(host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
                               password=s.mysql_password, database=s.mysql_db, connect_timeout=2)
    except Exception:
        return False
    conn.close()
    return True


needs_db = pytest.mark.skipif(not _db_available(), reason="本机没有可连的 MySQL，跳过集成用例")


def _student_id(student_no: str) -> int | None:
    rows = innovation._query("SELECT `编号` AS id FROM `学生` WHERE `租户编号` = 1 AND `学号` = %s",
                             (student_no,))
    return int(rows[0]["id"]) if rows else None


def _teacher_id(teacher_no: str) -> int | None:
    rows = innovation._query("SELECT `编号` AS id FROM `教师` WHERE `租户编号` = 1 AND `工号` = %s",
                             (teacher_no,))
    return int(rows[0]["id"]) if rows else None


@needs_db
def test_real_student_overview_shape():
    sid = _student_id("AI20230001")
    if not sid:
        pytest.skip("演示学生 AI20230001 不在库")

    data = innovation.build_overview(role="student", tenant_id=1, student_id=sid)
    kpis = {c["key"]: c for c in data["screens"]["result"]["kpis"]}

    # 在库岗位是真实数据，必须有值且带来源表与日期
    assert kpis["job_supply"]["available"] is True
    assert kpis["job_supply"]["value"] > 0
    assert kpis["job_supply"]["source_table"] == "岗位"
    assert kpis["job_supply"]["as_of"]

    # 库内没有投递/录用表：学生端也必须有这张卡，且显式「未采集」而不是缺席或写 0
    assert kpis["real_interview"]["available"] is False
    assert kpis["real_interview"]["value"] is None
    inst = data["screens"]["loop"]["instance"]
    if inst:
        assert inst["job_title"]
        assert 0 <= float(inst["final_score"]) <= 1
        for ev in inst["evidence"]:
            assert ev["course"]
            assert ev["percentile"] is None or 0 <= ev["percentile"] <= 100


@needs_db
def test_real_teacher_overview_is_aggregate_only():
    tid = _teacher_id("T001")
    if not tid:
        pytest.skip("演示教师 T001 不在库")

    data = innovation.build_overview(role="teacher", tenant_id=1, teacher_id=tid)
    kpis = {c["key"]: c for c in data["screens"]["result"]["kpis"]}

    assert data["screens"]["loop"]["instance"] is None
    assert kpis["real_interview"]["available"] is False
    assert kpis["real_interview"]["value"] is None
    # 每张事实卡都必须写清来源表（口径可溯源），不允许无出处的数字
    for card in kpis.values():
        assert card["source_table"], card["key"]


@needs_db
def test_real_supply_city_counts_and_cells():
    """city_counts 复用城市查询的 COUNT(*)，不得改变原有 cells 的结构与语义。"""
    supply = innovation._supply()
    cities = supply["cities"]
    industries = supply["industries"]
    city_counts = supply["city_counts"]

    # 键来自 cities，且原有查询查出的每个城市都必须带上数（一个都不能丢）
    assert set(city_counts) <= set(cities)
    assert set(city_counts) == set(cities)
    assert city_counts
    assert all(isinstance(v, int) and not isinstance(v, bool) and v > 0
               for v in city_counts.values())

    # 原有 cells 语义不变：仍是城市 × 行业计数，且每格不超过该城市在库总数
    assert isinstance(supply["cells"], list)
    for cell in supply["cells"]:
        assert set(cell) == {"city", "industry", "count"}
        assert cell["city"] in cities
        assert cell["industry"] in industries
        assert isinstance(cell["count"], int) and cell["count"] > 0
        assert cell["count"] <= city_counts[cell["city"]]


@needs_db
def test_real_supply_province_counts():
    """省级键必须全部来自 geo 白名单；已映射岗位数 + 未映射岗位数 == 在库总数。"""
    import json
    from pathlib import Path

    geo = Path(__file__).resolve().parents[1] / "web" / "public" / "geo" / "china.json"
    features = json.loads(geo.read_text(encoding="utf-8"))["features"]
    whitelist = {f["properties"]["name"] for f in features if f["properties"]["name"]}

    supply = innovation._supply()
    province_counts = supply["province_counts"]
    assert province_counts

    assert set(province_counts) <= whitelist, "出现了 geo 文件里不存在的省级名"
    assert all(isinstance(v, int) and not isinstance(v, bool) and v > 0
               for v in province_counts.values()), "值为 0 的省不得出现在字典里"
    assert isinstance(supply["unmapped_cities"], int)
    assert supply["unmapped_cities"] >= 0

    # 用同一张岗位表独立取一份全量分组，核对「一个岗位都不能凭空消失」
    bt = chr(96)
    rows = innovation._query(
        f"SELECT {bt}城市{bt} AS city, COUNT(*) AS n FROM {bt}岗位{bt} "
        f"GROUP BY {bt}城市{bt}")
    unmapped = [str(r.get("city") or "") for r in rows
                if str(r.get("city") or "") not in innovation._CITY_TO_PROVINCE]
    total_jobs = sum(int(r["n"]) for r in rows)
    unmapped_jobs = sum(int(r["n"]) for r in rows
                        if str(r.get("city") or "") in unmapped)

    assert supply["unmapped_cities"] == len(unmapped)
    assert sum(province_counts.values()) + unmapped_jobs == total_jobs
    assert sum(province_counts.values()) <= total_jobs


@needs_db
def test_overview_route_auth_scope_and_contract():
    """路由级：无 token 401、学生 200 且契约完整、越权教师 403。

    引擎层 PermissionError 测过不代表路由挂对了依赖、翻译对了状态码。
    """
    from fastapi.testclient import TestClient

    from agents.tools import ToolContext
    from app.auth import get_current_ctx
    from app.main import create_app

    client = TestClient(create_app())
    # ① 无 token → 401（身份缺失不是 500）
    assert client.get("/innovation/overview").status_code == 401

    # ② 学生正常取数 → 200，role/scope/kpis 形状完整
    login = client.post("/auth/login", json={"role": "student", "account": "AI20230001",
                                             "password": "123456h"})
    assert login.status_code == 200, login.text[:200]
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    resp = client.get("/innovation/overview", headers=headers)
    assert resp.status_code == 200, resp.text[:300]
    body = resp.json()
    assert body["role"] == "student"
    assert body["scope"]["tenant_id"] == 1
    assert {"result", "loop", "trust"} <= set(body["screens"])

    # ③ 教师身份但没有任何任教班级 → 403（不是 500，也不返回空数据冒充）
    app = create_app()
    app.dependency_overrides[get_current_ctx] = lambda: ToolContext(
        actor_type="teacher", tenant_id=1, teacher_id=999999)
    fresh = TestClient(app)
    denied = fresh.get("/innovation/overview", headers=headers)
    assert denied.status_code == 403, denied.text[:200]
