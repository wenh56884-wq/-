# tests/test_tools.py
# 职责：校验 Agent 工具层的越权防线（ctx 注入 / 租户隔离 / 审计留痕）与返回结构完整性
# 依赖：pytest / agents.tools / engine.warning
# 说明：越权类用例全部离线（monkeypatch 掉 MySQL 查询），数据类用例在 MySQL 不可用时自动跳过

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402

from agents import tools  # noqa: E402
from agents.tools import ToolContext  # noqa: E402
from engine import hybrid, recommend  # noqa: E402

TERM = "2025-2026-2"
TENANT_A = 1
CLASS = "RJ2201"
OTHER_STUDENT_NO = "RJ2022099"


def _mysql_ok() -> bool:
    """MySQL 是否可连通（不可连通的用例自动跳过）。"""
    try:
        import pymysql

        from app.config import get_settings

        s = get_settings()
        conn = pymysql.connect(
            host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
            password=s.mysql_password, database=s.mysql_db, charset="utf8mb4",
        )
        conn.close()
        return True
    except Exception:
        return False


MYSQL_OK = _mysql_ok()
requires_mysql = pytest.mark.skipif(not MYSQL_OK, reason="MySQL 不可用")


@pytest.fixture
def audit_sink(monkeypatch) -> list[dict]:
    """把审计条目同时写进内存 list，便于断言「越权必有审计」。"""
    sink: list[dict] = []
    monkeypatch.setattr(tools, "AUDIT_SINK", sink)
    return sink


def _teacher(tenant_id: int = TENANT_A, teacher_id: int = 7) -> ToolContext:
    return ToolContext(actor_type="teacher", tenant_id=tenant_id, teacher_id=teacher_id)


def _student(student_id: int = 101, tenant_id: int = TENANT_A) -> ToolContext:
    return ToolContext(actor_type="student", tenant_id=tenant_id, student_id=student_id)


def _offline_query(monkeypatch, rows: list[dict]) -> None:
    """离线场景：所有 MySQL 查询返回固定行（越权判定在查询之后也会走到）。"""
    monkeypatch.setattr(tools, "_query", lambda sql, params: list(rows))


# ----------------------------------------------------------------
# 1. 越权：学生调教师工具（写拒绝审计）
# ----------------------------------------------------------------
def test_student_cannot_call_teacher_tool(audit_sink):
    """学生调 class_overview → PermissionError，且落一条 .denied 审计。"""
    ctx = _student(student_id=101)
    with pytest.raises(PermissionError) as exc:
        tools.class_overview(ctx, CLASS, TERM)
    assert "仅限教师调用" in str(exc.value)
    assert audit_sink, "越权必须写审计"
    entry = audit_sink[-1]
    assert entry["actor_type"] == "student"
    assert entry["actor_id"] == 101
    assert entry["action"] == "class_overview.denied"
    assert entry["target"] == CLASS


def test_teacher_cannot_call_student_tool(audit_sink):
    """教师调 my_warning → PermissionError（学生端工具不认教师身份）。"""
    with pytest.raises(PermissionError) as exc:
        tools.my_warning(_teacher(), TERM)
    assert "仅限学生本人调用" in str(exc.value)
    assert audit_sink[-1]["action"] == "my_warning.denied"


def test_student_without_id_is_denied(audit_sink):
    """ctx.student_id 缺失时无法确定「本人」是谁 → 拒绝，不得退化成查全班。"""
    with pytest.raises(PermissionError) as exc:
        tools.my_recommendations(ToolContext(actor_type="student", tenant_id=TENANT_A))
    assert "student_id 缺失" in str(exc.value)
    assert audit_sink[-1]["action"] == "my_recommendations.denied"


# ----------------------------------------------------------------
# 2. 越权：跨租户 / 跨班级
# ----------------------------------------------------------------
def test_cross_tenant_class_is_denied(audit_sink, monkeypatch):
    """班级只在其他租户存在 → 拒绝并写审计（不得返回空数据假装成功）。"""
    def fake_query(sql: str, params: tuple):
        # 第一次查本租户（0 行），第二次查其他租户（存在）
        return [{"cnt": 1}] if "`租户编号` <> %s" in sql else [{"cnt": 0}]

    monkeypatch.setattr(tools, "_query", fake_query)
    with pytest.raises(PermissionError) as exc:
        tools.class_overview(_teacher(tenant_id=1), "RJ9901", TERM)
    assert "属于其他租户" in str(exc.value)
    assert audit_sink[-1]["action"] == "class_overview.denied"
    assert audit_sink[-1]["detail"]["reason"].startswith("班级 RJ9901")


def test_unknown_class_is_value_error_not_permission(audit_sink, monkeypatch):
    """输入了任何租户都不存在的班级 → 422 参数错误，不写越权审计。"""
    _offline_query(monkeypatch, [{"cnt": 0}])
    with pytest.raises(ValueError) as exc:
        tools.class_overview(_teacher(tenant_id=1), "RJ9901", TERM)
    assert "不存在" in str(exc.value)
    assert audit_sink == [], "输错班级名不应被记成越权"


def test_teacher_scope_limits_class_list(audit_sink, monkeypatch):
    """配置了 teacher_class 的教师，班级目录只返回任教班级。"""
    def fake_query(sql: str, params: tuple):
        if "FROM `教师任教班级`" in sql:
            return [{"class_name": CLASS}]
        if "GROUP BY s.`学院`" in sql:
            return [
                {"college": "软件学院", "class_name": CLASS,
                 "major": "软件工程", "headcount": 30},
                {"college": "软件学院", "class_name": "RJ2202",
                 "major": "软件工程", "headcount": 30},
            ]
        return []

    monkeypatch.setattr(tools, "_query", fake_query)
    result = tools.class_list(_teacher())
    assert [item["class_name"] for item in result["classes"]] == [CLASS]
    assert result["scope"] == "assigned"
    assert result["assigned_class_cnt"] == 1


def test_teacher_scope_denies_student_outside_class(audit_sink, monkeypatch):
    """教师只能查任教班级的学生；跨班学号按越权拒绝并写审计。"""
    def fake_query(sql: str, params: tuple):
        if "FROM `教师任教班级`" in sql:
            return [{"class_name": CLASS}]
        if "FROM `学生` s WHERE" in sql:
            return [{
                "student_no": OTHER_STUDENT_NO, "name": "别班学生",
                "major": "软件工程", "class_name": "RJ2202",
                "student_id": 9, "college": "软件学院", "enroll_year": 2022,
            }]
        return []

    monkeypatch.setattr(tools, "_query", fake_query)
    with pytest.raises(PermissionError) as exc:
        tools._fetch_student(_teacher(), OTHER_STUDENT_NO, "student_profile")
    assert "任教范围" in str(exc.value)
    assert audit_sink[-1]["action"] == "student_profile.denied"


def test_cross_tenant_student_is_denied(audit_sink, monkeypatch):
    """教师查别租户的学号 → 拒绝并写审计。"""
    _offline_query(monkeypatch, [])
    with pytest.raises(PermissionError) as exc:
        tools.student_profile(_teacher(tenant_id=1), OTHER_STUDENT_NO, TERM)
    assert "不属于当前租户" in str(exc.value)
    assert audit_sink[-1]["target"] == OTHER_STUDENT_NO


def test_student_querying_other_student_is_denied(audit_sink):
    """学生即使拿到他人学号也无法通过 tools 通道查询（工具层没有这类入口）。"""
    ctx = _student(student_id=101)
    with pytest.raises(PermissionError):
        tools.student_profile(ctx, OTHER_STUDENT_NO, TERM)
    assert audit_sink[-1]["action"] == "student_profile.denied"
    assert audit_sink[-1]["actor_id"] == 101


# ----------------------------------------------------------------
# 3. ctx 必须由后端注入
# ----------------------------------------------------------------
def test_ctx_must_be_tool_context():
    """裸 dict 冒充 ctx → TypeError（禁止前端构造身份）。"""
    with pytest.raises(TypeError):
        tools.class_overview({"actor_type": "teacher", "tenant_id": 1}, CLASS, TERM)
    with pytest.raises(PermissionError):
        tools.class_overview(ToolContext(actor_type="hacker", tenant_id=1), CLASS, TERM)
    with pytest.raises(PermissionError):
        tools.class_overview(ToolContext(actor_type="teacher", tenant_id=0), CLASS, TERM)


# ----------------------------------------------------------------
# 4. 参数缺省行为
# ----------------------------------------------------------------
def test_default_term_falls_back_to_latest_term(monkeypatch):
    """term 缺省时的优先级：显式入参 > ctx.term > 最新有成绩学期。"""
    seen: list[tuple] = []

    def _fake(sql: str, params) -> list[dict]:
        seen.append((sql, tuple(params)))
        if "ORDER BY sc.`学期` DESC LIMIT 1" in sql:
            return [{"term": "2025-2026-2"}]
        if "COUNT(DISTINCT s.`编号`) AS cnt" in sql:
            return [{"cnt": 1}]
        if "AVG(sc.`分数`) AS gpa" in sql and "GROUP BY s.`学号`" in sql:
            return [{"headcount": 1, "fail_students": 0, "fail_courses": 0, "avg_gpa": 80.0}]
        return []

    monkeypatch.setattr(tools, "_query", _fake)
    monkeypatch.setattr(tools.warning, "compute_class", lambda *a, **k: [])

    ctx_term = ToolContext(actor_type="teacher", tenant_id=1, term="2024-2025-2")
    out = tools.class_overview(ctx_term, CLASS, "")
    assert out["term"] == "2024-2025-2", "应为 ctx.term 兜底"

    out2 = tools.class_overview(_teacher(), CLASS, "")
    assert out2["term"] == "2025-2026-2", "应回落到最新有成绩学期"
    assert any("ORDER BY sc.`学期` DESC LIMIT 1" in q[0] for q in seen)


def test_illegal_level_raises_value_error(monkeypatch):
    """非法预警等级 ValueError（区别于越权的 PermissionError）。"""
    _offline_query(monkeypatch, [{"cnt": 1}])
    monkeypatch.setattr(tools.warning, "compute_class", lambda *a, **k: [])
    with pytest.raises(ValueError):
        tools.warning_list(_teacher(), CLASS, TERM, "purple")


# ----------------------------------------------------------------
# 5. 返回结构完整
# ----------------------------------------------------------------
def test_returns_are_structured_with_versions(monkeypatch):
    """每个返回值必须是 dict，且带 engine_version / calc_version（禁止自然语言）。"""
    def _fake(sql: str, params) -> list[dict]:
        if "COUNT(DISTINCT s.`编号`) AS cnt" in sql:
            return [{"cnt": 2}]
        if "headcount" in sql or "SUM(t.fail_cnt" in sql:
            return [{"headcount": 2, "fail_students": 1, "fail_courses": 3, "avg_gpa": 76.5}]
        if "COUNT(*) AS cnt" in sql and "j.`岗位名称`" in sql:
            return [{"title": "Java 后端开发工程师", "cnt": 5}]
        if "j.`最低薪资`" in sql:  # 目标岗位样本（career_gap 的需求侧）
            return [{
                "title": "Java 后端开发工程师", "salary_min": 8000, "salary_max": 15000,
                "exp_min": 1, "education": "本科",
                "skill_tags": '["Java", "Spring", "项目经验"]',
                "description": "要求有项目经验和团队协作能力",
            }]
        if "SELECT s.`学号` AS student_no FROM `学生` s" in sql:
            return [{"student_no": "RJ2022001"}, {"student_no": "RJ2022002"}]
        if "s.`姓名` AS name, s.`专业` AS major" in sql:
            return [{"student_no": "RJ2022001", "name": "张三", "major": "软件工程",
                     "class_name": CLASS, "student_id": 1}]
        if "GROUP BY s.`学号`" in sql and "AVG(sc.`分数`) AS gpa" in sql:
            return [{"student_no": "RJ2022001", "gpa": 76.5, "fail_cnt": 1}]
        if "ORDER BY sc.`学期`" in sql:
            return [{"term": TERM, "gpa": 76.5}]
        return []

    monkeypatch.setattr(tools, "_query", _fake)
    monkeypatch.setattr(tools, "read_features", lambda term, nos: [{
        "student_no": nos[0], "term": term, "gpa": 76.5, "fail_count": 1,
        "cert_count": 1, "contest_count": 0, "project_cnt": 1,
        "tags": ["专业前20%", "偏好后端岗", "能力履历完整"],
        "calc_version": "v1.1", "extreme_decline": False,
    }])
    monkeypatch.setattr(tools.warning, "compute_class", lambda *a, **k: [{
        "student_no": "RJ2022001", "name": "张三", "risk_score": 45, "level": "orange",
        "reasons": ["本学期挂科1门"], "coverage": 3, "missing": [], "metrics": {},
    }])

    overview = tools.class_overview(_teacher(), CLASS, TERM)
    assert isinstance(overview, dict)
    assert overview["class_name"] == CLASS and overview["term"] == TERM
    assert overview["headcount"] == 2 and overview["fail_rate"] == 0.5
    assert overview["warning_distribution"]["orange"] == 1
    assert overview["employment_intent"]["top_directions"][0]["direction"] == "后端"
    assert overview["engine_version"] and overview["calc_version"]

    profile = tools.student_profile(_teacher(), "RJ2022001", TERM)
    assert profile["has_data"] is True
    assert profile["tags"] == ["专业前20%", "偏好后端岗", "能力履历完整"]
    assert set(profile["dimensions"]) == {"study", "behavior", "interest", "ability"}
    assert profile["dimensions"]["study"] is not None
    assert profile["gpa_trend_series"] == [{"term": TERM, "gpa": 76.5}]
    assert profile["calc_version"] == "v1.1"

    warns = tools.warning_list(_teacher(), CLASS, TERM)
    assert warns["items"][0]["level"] == "orange"
    assert warns["count"] == 1 and warns["distribution"]["orange"] == 1

    gap = tools.career_gap(_teacher(), CLASS, TERM)
    assert gap["target_direction"] == "后端"
    assert gap["class_ability"]["sample"] >= 0
    assert isinstance(gap["gaps"], list)


# ----------------------------------------------------------------
# 6. 学生端只看本人
# ----------------------------------------------------------------
@requires_mysql
def test_student_only_sees_self(audit_sink):
    """Same ctx 两次调用得到同一个学号：学生没有任何入口指定「查谁」。"""
    from app.config import get_settings

    import pymysql

    s = get_settings()
    conn = pymysql.connect(host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
                           password=s.mysql_password, database=s.mysql_db,
                           charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT s.`编号` AS id, s.`学号` AS student_no FROM `学生` s "
                "JOIN `成绩` sc ON sc.`学生编号` = s.`编号` AND sc.`学期` = %s "
                "WHERE s.`租户编号` = %s ORDER BY s.`学号` LIMIT 1",
                (TERM, TENANT_A),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    assert row, "需要至少一个有成绩的学生"

    ctx = _student(student_id=int(row["id"]))
    result = tools.my_warning(ctx, TERM)
    assert result["student_no"] == str(row["student_no"])
    assert result["engine_version"] and result["calc_version"]
    assert set(("risk_score", "level", "reasons", "coverage", "missing")) <= set(result)
    assert audit_sink[-1]["action"] == "my_warning"

    recs = tools.my_recommendations(ctx, TERM, top_n=3)
    assert recs["student_no"] == str(row["student_no"])
    # P9 已实现：不再是占位结构，返回真实推荐且每条字段齐全
    # 二期C：工具层已切到 engine.hybrid，版本随混合引擎走
    assert recs["recommend_version"] == hybrid.HYBRID_ENGINE_VERSION
    assert isinstance(recs["items"], list)
    for item in recs["items"]:
        assert set(("job_id", "title", "company", "final_score",
                    "hit_items", "gap_items", "advice")) <= set(item)
    assert set(recs["reasons_schema"]) == {"knowledge", "skill", "potential"}


@requires_mysql
def test_all_sql_carries_tenant_condition():
    """自检：工具层每条 SQL 都必须带 tenant_id 条件（多租户第一道防线）。"""
    src = (_ROOT / "agents" / "tools.py").read_text(encoding="utf-8")
    for banned in ("import random", "openai", "langchain"):
        assert banned not in src, f"tools.py 出现禁用记号：{banned}"
    # 取数类 SQL（.execute / _query 里的 SELECT）必须 tenant 过滤
    select_sql = [
        line for line in src.splitlines()
        if "`租户编号` = %s" in line or "v.student_id = s.id AND s.tenant_id" in line
    ]
    assert len(select_sql) >= 8, f"带 tenant_id 条件的 SQL 行数不足：{len(select_sql)}"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
