# tests/test_workflow_flow.py
# 职责：校验「学生发起 → 教师审批 → 学生看到结果」这条链路的可读性契约：
#   ① 待审单必须带「将执行哪几步」（否则教师是盲签）；
#   ② 审批历史能回查到动作、意见与执行结果；
#   ③ 学生的 my-runs 只看得到自己的申请，且驳回意见能传到学生侧。
# 说明：需要 MySQL；建的定义 / 运行 / 审批记录在用例结束后全部删除。

from __future__ import annotations

import uuid

import pymysql
import pytest

from agents.tools import ToolContext
from app import workflow_approval as approval
from app.config import get_settings
from app.routers import workflow as wf_routes
from engine import workflow as wf_engine


def _conn():
    s = get_settings()
    return pymysql.connect(host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
                           password=s.mysql_password, database=s.mysql_db,
                           charset="utf8mb4", autocommit=True,
                           cursorclass=pymysql.cursors.DictCursor)


def _mysql_ok() -> bool:
    try:
        _conn().close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _mysql_ok(), reason="MySQL 不可用")


def _teacher() -> ToolContext:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT `编号`,`租户编号` FROM `教师` ORDER BY `编号` LIMIT 1")
            row = cur.fetchone()
    finally:
        conn.close()
    return ToolContext(actor_type="teacher", tenant_id=int(row["租户编号"]),
                       teacher_id=int(row["编号"]))


def _students(n: int = 2) -> list[ToolContext]:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT `编号`,`租户编号` FROM `学生` ORDER BY `编号` LIMIT %s", (n,))
            rows = list(cur.fetchall())
    finally:
        conn.close()
    return [ToolContext(actor_type="student", tenant_id=int(r["租户编号"]),
                        student_id=int(r["编号"])) for r in rows]


@pytest.fixture()
def temp_def():
    """建一个「需要审批」的临时工作流，结束后连带运行 / 审批记录一起删掉。"""
    teacher = _teacher()
    name = f"审批链路测试-{uuid.uuid4().hex[:8]}"
    steps = [
        {"id": "s1", "tool": "my_warning", "title": "本人学业预警", "args": {}},
        {"id": "s2", "tool": "my_recommendations", "title": "本人岗位推荐", "args": {}},
    ]
    import json

    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO `工作流定义`(`租户编号`,`名称`,`描述`,`步骤`,`创建人`,"
                        "`是否启用`,`是否需要审批`) VALUES (%s,%s,%s,%s,%s,1,1)",
                        (teacher.tenant_id, name, "测试用，勿手动执行",
                         json.dumps(steps, ensure_ascii=False), "test"))
            def_id = int(cur.lastrowid)
    finally:
        conn.close()

    yield {"id": def_id, "name": name, "teacher": teacher}

    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT `编号` FROM `工作流运行` WHERE `定义编号`=%s", (def_id,))
            run_ids = [int(r["编号"]) for r in cur.fetchall()]
            for rid in run_ids:
                cur.execute("DELETE FROM `工作流审批` WHERE `运行编号`=%s", (rid,))
                cur.execute("DELETE FROM `工作流运行` WHERE `编号`=%s", (rid,))
            cur.execute("DELETE FROM `工作流定义` WHERE `编号`=%s", (def_id,))
    finally:
        conn.close()


def test_pending_carries_step_detail(temp_def):
    """待审单必须能看出「通过后会跑哪几步」——只有步骤数等于盲签。"""
    student = _students(1)[0]
    submitted = approval.submit_for_approval(
        student, temp_def["id"], temp_def["name"], None,
        steps=[{"id": "s1", "tool": "my_warning", "title": "本人学业预警", "args": {}},
               {"id": "s2", "tool": "my_recommendations", "args": {}}])

    pending = approval.list_pending(temp_def["teacher"], limit=50)
    item = next(i for i in pending["items"] if i["id"] == submitted["run_id"])
    assert [s["label"] for s in item["steps"]] == ["本人学业预警", "本人岗位推荐"]
    # 没写 title 的步骤也要有中文名，不能把工具名直接甩给教师
    assert item["steps"][1]["title"] == "本人岗位推荐"
    assert item["step_count"] == 2
    # 挂起态：一步都没跑
    assert submitted["status"] == wf_engine.STATUS_PENDING
    assert submitted["steps"] == []


def test_history_and_student_see_reject_reason(temp_def):
    """驳回后：教师侧能回查，学生侧必须看到驳回意见原文。"""
    student = _students(1)[0]
    submitted = approval.submit_for_approval(student, temp_def["id"], temp_def["name"], None)
    comment = "先补数据结构，下学期再体检"

    approval.decide(temp_def["teacher"], submitted["run_id"], wf_engine.ACTION_REJECT, comment)

    hist = approval.list_history(temp_def["teacher"], limit=50)
    row = next(i for i in hist["items"] if i["run_id"] == submitted["run_id"])
    assert row["action"] == "reject"
    assert row["comment"] == comment
    assert row["status"] == wf_engine.STATUS_REJECTED

    mine = wf_routes.my_runs(limit=20, ctx=student)
    rec = next(i for i in mine["items"] if i["id"] == submitted["run_id"])
    assert rec["status"] == wf_engine.STATUS_REJECTED
    assert rec["status_text"] == "已驳回"
    assert rec["decided"]["comment"] == comment
    # 驳回意味着一步都没跑，不能给学生展示假的「执行结果」
    assert rec["steps"] == []


def test_approve_then_student_sees_steps(temp_def):
    """通过后：学生看到「已执行完成」与逐步结果，与教师侧同一份数据。"""
    student = _students(1)[0]
    submitted = approval.submit_for_approval(student, temp_def["id"], temp_def["name"], None)
    result = approval.decide(temp_def["teacher"], submitted["run_id"],
                             wf_engine.ACTION_APPROVE, "同意")

    assert result["action"] == "approve"
    assert result["status"] in ("success", "failed")

    mine = wf_routes.my_runs(limit=20, ctx=student)
    rec = next(i for i in mine["items"] if i["id"] == submitted["run_id"])
    assert rec["status"] == result["status"]
    assert [s["title"] for s in rec["steps"]] == [s["title"] for s in result["steps"]]


def test_my_runs_isolated_between_students(temp_def):
    """学生 A 的申请不能出现在学生 B 的列表里（学号只认 JWT）。"""
    students = _students(2)
    if len(students) < 2:
        pytest.skip("学生不足两人，跳过隔离校验")
    a, b = students

    submitted = approval.submit_for_approval(a, temp_def["id"], temp_def["name"], None)

    ids_a = {i["id"] for i in wf_routes.my_runs(limit=50, ctx=a)["items"]}
    ids_b = {i["id"] for i in wf_routes.my_runs(limit=50, ctx=b)["items"]}
    assert submitted["run_id"] in ids_a
    assert submitted["run_id"] not in ids_b


def test_decided_run_cannot_be_decided_again(temp_def):
    """同一单只能审一次：重复审批必须报错，不能第二次又跑一遍步骤。"""
    student = _students(1)[0]
    submitted = approval.submit_for_approval(student, temp_def["id"], temp_def["name"], None)
    approval.decide(temp_def["teacher"], submitted["run_id"], wf_engine.ACTION_REJECT, None)

    with pytest.raises(approval.ApprovalError):
        approval.decide(temp_def["teacher"], submitted["run_id"],
                        wf_engine.ACTION_APPROVE, None)
