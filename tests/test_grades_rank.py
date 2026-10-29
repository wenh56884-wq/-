# tests/test_grades_rank.py
# 职责：教师端成绩单的「全班总体平均成绩 / 个人平均成绩 / 同专业班级排名 / 同专业个人排名」。
# 说明：
#   1. 数值逻辑全在 engine.grades.build_rank（纯函数），所以主用例**不连库**，跑得快、结果可复现；
#   2. 口径与成绩单一致（同一门课取最高分 → 按学分加权），这条由本文件守住，
#      免得排名里的均分和成绩单上的加权均分两个数字打架；
#   3. 权限（只统计任教班级、学生不得调用）与智能体路由各有用例。

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agents import graph as agent_graph
from agents import tools as agent_tools
from agents.tools import ToolContext
from app.main import create_app
from engine.grades import build_rank

TERM = "2025-2026-2"


def _row(sid: int, no: str, name: str, major: str, cls: str,
         course: str, score, credit: float, term: str = TERM) -> dict:
    return {
        "student_id": sid, "student_no": no, "name": name, "major": major,
        "class_name": cls, "term": term, "score": score, "credit": credit,
        "course_code": course, "course_name": f"课程{course}",
        "retake": False, "record_id": sid * 100 + int(course[1:] or 0),
    }


def _by_no(result: dict) -> dict:
    return {s["student_no"]: s for s in result["students"]}


# ----------------------------------------------------------------
# 1. 口径：与成绩单一致（同一门课取最高分 → 按学分加权）
# ----------------------------------------------------------------
def test_weighted_avg_takes_best_score_and_weights_by_credit():
    """重修的低分不能拉低均分：(90*3 + 60*1) / 4 = 82.5。"""
    rows = [
        _row(1, "A", "甲", "软工", "C1", "K1", 60, 3),
        _row(1, "A", "甲", "软工", "C1", "K1", 90, 3),   # 重修高分，取它
        _row(1, "A", "甲", "软工", "C1", "K2", 60, 1),
    ]
    assert _by_no(build_rank(rows, term=TERM))["A"]["weighted_avg"] == 82.5


def test_other_term_rows_are_excluded():
    rows = [
        _row(1, "A", "甲", "软工", "C1", "K1", 90, 1, term=TERM),
        _row(1, "A", "甲", "软工", "C1", "K2", 40, 1, term="2024-2025-1"),
    ]
    assert _by_no(build_rank(rows, term=TERM))["A"]["weighted_avg"] == 90.0


# ----------------------------------------------------------------
# 2. 排名规则：降序、并列跳号、无成绩不参与
# ----------------------------------------------------------------
def test_rank_descending_with_tied_rank_and_gap():
    """并列第 2 名之后应是第 4 名而不是第 3 名，否则名次和总数语义对不上。"""
    rows = [
        _row(1, "A", "甲", "软工", "C1", "K1", 100, 1),
        _row(2, "B", "乙", "软工", "C1", "K1", 80, 1),
        _row(3, "C", "丙", "软工", "C1", "K1", 80, 1),
        _row(4, "D", "丁", "软工", "C1", "K1", 70, 1),
    ]
    ranked = _by_no(build_rank(rows, term=TERM))
    assert ranked["A"]["class_rank"] == 1
    assert ranked["B"]["class_rank"] == 2
    assert ranked["C"]["class_rank"] == 2      # 并列
    assert ranked["D"]["class_rank"] == 4      # 并列后跳号
    assert ranked["D"]["class_rank_total"] == 4


def test_student_without_score_is_not_ranked():
    rows = [_row(1, "A", "甲", "软工", "C1", "K1", None, 1)]
    student = _by_no(build_rank(rows, term=TERM))["A"]
    assert student["class_rank"] is None
    assert student["class_rank_total"] == 0


# ----------------------------------------------------------------
# 3. 全班总体平均成绩 = 各学生个人加权均分的算术平均（学生等权）
# ----------------------------------------------------------------
def test_class_avg_is_mean_of_student_weighted_avg():
    rows = [
        _row(1, "A", "甲", "软工", "C1", "K1", 100, 1),
        _row(2, "B", "乙", "软工", "C1", "K1", 60, 1),
    ]
    assert build_rank(rows, term=TERM)["classes"][0]["weighted_avg"] == 80.0


# ----------------------------------------------------------------
# 4. 同专业班级排名：班级与专业是多对多，一个班里多个专业要分别计名次
# ----------------------------------------------------------------
def test_class_rank_in_major_across_classes():
    rows = [
        _row(1, "A", "甲", "软工", "C1", "K1", 90, 1),
        _row(2, "B", "乙", "软工", "C2", "K1", 70, 1),
    ]
    ranks = {(r["major"], r["class_name"]): r["rank"]
             for r in build_rank(rows, term=TERM)["class_rank_in_major"]}
    assert ranks[("软工", "C1")] == 1
    assert ranks[("软工", "C2")] == 2


def test_one_class_with_two_majors_ranks_separately():
    """同一个班里既有软工又有金融，两个专业各自算班级名次与个人名次。"""
    rows = [
        _row(1, "A", "甲", "软工", "C1", "K1", 90, 1),
        _row(2, "B", "乙", "金融", "C1", "K1", 80, 1),
        _row(3, "C", "丙", "软工", "C2", "K1", 70, 1),
    ]
    result = build_rank(rows, term=TERM)
    ranks = {(r["major"], r["class_name"]): r["rank"]
             for r in result["class_rank_in_major"]}
    assert ranks[("软工", "C1")] == 1
    assert ranks[("软工", "C2")] == 2
    assert ranks[("金融", "C1")] == 1          # 该专业只有一个班

    ranked = _by_no(result)
    assert ranked["A"]["major_rank"] == 1 and ranked["A"]["major_rank_total"] == 2
    assert ranked["B"]["major_rank"] == 1 and ranked["B"]["major_rank_total"] == 1
    assert ranked["C"]["major_rank"] == 2


# ----------------------------------------------------------------
# 5. 权限：任教范围收敛 + 学生不得调用
# ----------------------------------------------------------------
def test_scope_classes_limits_statistics():
    rows = [
        _row(1, "A", "甲", "软工", "C1", "K1", 90, 1),
        _row(2, "B", "乙", "软工", "C2", "K1", 70, 1),
    ]
    result = build_rank(rows, term=TERM, scope_classes=["C1"])
    assert len(result["students"]) == 1
    assert [c["class_name"] for c in result["classes"]] == ["C1"], \
        "范围外的班级不该出现在统计里"


def test_class_grades_rank_denies_student():
    """学生不能查班级排名（会带出同班同学的成绩）。"""
    import pymysql

    from app.config import get_settings

    s = get_settings()
    conn = pymysql.connect(host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
                           password=s.mysql_password, database=s.mysql_db,
                           charset="utf8mb4", autocommit=True,
                           cursorclass=pymysql.cursors.DictCursor)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT `编号`,`租户编号` FROM `学生` ORDER BY `编号` LIMIT 1")
            row = cur.fetchone()
    finally:
        conn.close()
    ctx = ToolContext(actor_type="student", tenant_id=int(row["租户编号"]),
                      student_id=int(row["编号"]))
    with pytest.raises(PermissionError):
        agent_tools.class_grades_rank(ctx, "AI2301", None)


# ----------------------------------------------------------------
# 6. 接口 + 智能体路由
# ----------------------------------------------------------------
def test_class_rank_api_returns_only_current_class_detail():
    """同专业其他班只用于算名次，明细不能随响应下发。"""
    client = TestClient(create_app())
    r = client.post("/auth/login", json={"role": "teacher", "account": "T001",
                                         "password": "teacher@123"})
    assert r.status_code == 200, r.text[:200]
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

    classes = client.get("/teacher/classes", headers=headers).json().get("classes") or []
    assert classes, "教师看不到任何班级，无法验证"
    target = classes[0]["class_name"]

    resp = client.get("/grades/class-rank", headers=headers,
                      params={"class_name": target, "term": TERM})
    assert resp.status_code == 200, resp.text[:200]
    data = resp.json()
    assert data["class_name"] == target
    assert data["term"] == TERM
    assert data["engine_version"].startswith("grades-rank")
    assert {s["class_name"] for s in data["students"]} <= {target}, \
        "明细里出现了别的班的学生"
    assert data["available_terms"], "学期下拉需要可用学期列表"
    for item in data["classes"]:
        assert set(item) >= {"class_name", "weighted_avg", "student_cnt"}


def test_teacher_rank_question_routes_to_class_grades_rank():
    import pymysql

    from app.config import get_settings

    s = get_settings()
    conn = pymysql.connect(host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
                           password=s.mysql_password, database=s.mysql_db,
                           charset="utf8mb4", autocommit=True,
                           cursorclass=pymysql.cursors.DictCursor)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT `编号`,`租户编号` FROM `教师` ORDER BY `编号` LIMIT 1")
            t = cur.fetchone()
            cur.execute("SELECT `班级` FROM `教师任教班级` WHERE `租户编号`=%s AND `教师编号`=%s"
                        " ORDER BY `班级`", (t["租户编号"], t["编号"]))
            scope = [row["班级"] for row in cur.fetchall()]
    finally:
        conn.close()
    ctx = ToolContext(actor_type="teacher", tenant_id=int(t["租户编号"]),
                      teacher_id=int(t["编号"]))
    target = scope[0] if scope else "AI2301"

    # 「点名班级但没点名到人」的问法必须给班级统计：不修的话会落到
    # student_grades 再兜底成第一个学生的成绩，教师问全班看到一个人。
    for question in (f"{target} 的成绩排名", f"{target} 班级排名怎么样",
                     f"{target} 的平均成绩", f"{target} 成绩怎么样",
                     f"{target} 的均分", f"{target} 平均绩点"):
        plan = agent_graph.plan_node({"ctx": ctx, "query": question, "history": []})
        assert plan["tool_name"] == "class_grades_rank", f"{question} 没路由到班级排名"
        assert plan["plan"]["args"].get("class_name") == target

    # 没带班级名但说「这个班」的问法也要命中班级统计（班级名走默认班，不强校验）
    plan = agent_graph.plan_node({"ctx": ctx, "query": "这个班整体成绩", "history": []})
    assert plan["tool_name"] == "class_grades_rank", "「这个班整体成绩」没路由到班级排名"
