# app/workflow_approval.py
# 职责：工作流的人工审批——提交待审、通过、驳回、列出待我审批。
# 依赖：pymysql / engine.workflow / agents.tools（工具实现）/ app.audit
# 铁律：
#   1. **执行用「提交者」的身份，不是审批人的**——否则学生提交的「我的求职体检」
#      会以教师身份跑，my_warning 这类本人工具就会取到错误的人。
#   2. 待审状态下**一步都不执行**：审批通过才真正跑步骤，驳回则永远不跑。
#   3. 一次运行只审一次（表上 uk_approval_run 唯一键 + 这里再判一次状态）。

from __future__ import annotations

import json
from typing import Any

import pymysql

from app.audit import audit_event
from app.config import get_settings
from engine import workflow as wf_engine
from agents.tools import ToolContext


class ApprovalError(Exception):
    """审批不可继续：消息直接给用户看，必须是人话。"""


def _conn() -> pymysql.connections.Connection:
    s = get_settings()
    return pymysql.connect(host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
                           password=s.mysql_password, database=s.mysql_db,
                           charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)


def _json(raw: Any, default: Any) -> Any:
    if raw is None or raw == "":
        return default
    if isinstance(raw, (list, dict)):
        return raw
    try:
        data = json.loads(raw)
        return data if isinstance(data, type(default)) else default
    except (TypeError, ValueError):
        return default


def _impl_for(ctx: ToolContext) -> dict[str, Any]:
    """工作流步骤的工具实现：ctx 在闭包里绑好，步骤配置拿不到身份。"""
    from agents import tools

    return {
        "my_warning": lambda **kw: tools.my_warning(ctx, **kw),
        "my_recommendations": lambda **kw: tools.my_recommendations(ctx, **kw),
        "class_list": lambda **kw: tools.class_list(ctx),
        "class_overview": lambda **kw: tools.class_overview(ctx, **kw),
        "warning_list": lambda **kw: tools.warning_list(ctx, **kw),
        "career_gap": lambda **kw: tools.career_gap(ctx, **kw),
        "student_profile": lambda **kw: tools.student_profile(ctx, **kw),
        "kb_search": lambda **kw: tools.kb_search(ctx, **kw),
        "job_search": lambda **kw: tools.search_jobs(ctx, **kw),
    }


def needs_approval(def_id: int, tenant_id: int) -> bool:
    """该工作流是否需要人工审批（定义上没有这个开关就按「不需要」处理）。"""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT `是否需要审批` FROM `工作流定义`"
                        " WHERE `编号`=%s AND `租户编号`=%s", (def_id, tenant_id))
            row = cur.fetchone()
        return bool(int(row["是否需要审批"] or 0)) if row else False
    finally:
        conn.close()


def submit_for_approval(ctx: ToolContext, def_id: int, def_name: str,
                        inputs: dict[str, Any] | None = None,
                        steps: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """提交一次运行并挂起等审批：**不执行任何步骤**，只留一条 pending 记录。

    steps 会作为**提交时快照**存进运行记录：审批通过后按快照执行，不按定义表的
    最新内容执行——否则提交后有人改了定义，审批的 A 跟跑的 B 就是两回事。
    """
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO `工作流运行`(`定义编号`,`触发角色`,`触发人编号`,`入参`,"
                        "`状态`,`步骤快照`) VALUES (%s,%s,%s,%s,%s,%s)",
                        (def_id, ctx.actor_type,
                         ctx.teacher_id if ctx.actor_type == "teacher" else ctx.student_id,
                         json.dumps(inputs or {}, ensure_ascii=False),
                         wf_engine.STATUS_PENDING,
                         json.dumps(steps or [], ensure_ascii=False)))
            run_id = int(cur.lastrowid)
        conn.commit()
    finally:
        conn.close()

    audit_event(tenant_id=ctx.tenant_id, actor_type=ctx.actor_type,
                actor_id=ctx.teacher_id or ctx.student_id or 0,
                action="workflow.submit_pending", target=str(def_id),
                detail={"run_id": run_id, "name": def_name})
    return {
        "run_id": run_id,
        "name": def_name,
        "status": wf_engine.STATUS_PENDING,
        "needs_approval": True,
        # 与「直接执行」的返回保持同形：挂起态 steps 恒为空，前端不用分支判断
        "steps": [],
        "elapsed_ms": 0,
        "message": f"工作流「{def_name}」已提交，等待教师审批后执行。",
        "approval_version": wf_engine.APPROVAL_VERSION,
    }


def list_pending(ctx: ToolContext, limit: int = 20) -> dict[str, Any]:
    """本租户待审批的运行（教师视角：谁提交、跑什么、什么时候）。"""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT r.`编号` AS id, d.`名称` AS name, d.`描述` AS description,"
                        " r.`触发角色` AS actor_type, r.`触发人编号` AS actor_id,"
                        " r.`入参` AS inputs, r.`步骤快照` AS steps_snapshot,"
                        " d.`步骤` AS steps, r.`开始时间` AS submitted_at,"
                        " s.`姓名` AS student_name, t.`姓名` AS teacher_name"
                        " FROM `工作流运行` r"
                        " JOIN `工作流定义` d ON d.`编号`=r.`定义编号`"
                        " LEFT JOIN `学生` s ON r.`触发角色`='student' AND s.`编号`=r.`触发人编号`"
                        " LEFT JOIN `教师` t ON r.`触发角色`='teacher' AND t.`编号`=r.`触发人编号`"
                        " WHERE d.`租户编号`=%s AND r.`状态`=%s"
                        " ORDER BY r.`编号` DESC LIMIT %s",
                        (ctx.tenant_id, wf_engine.STATUS_PENDING,
                         max(1, min(int(limit), 100))))
            rows = list(cur.fetchall())
    finally:
        conn.close()

    items = []
    for r in rows:
        snapshot = _json(r.get("steps_snapshot"), [])
        current = _json(r.get("steps"), [])
        items.append({
            "id": int(r["id"]),
            "name": r["name"],
            "description": r.get("description"),
            "submitted_by": {
                "actor_type": r.get("actor_type"),
                "actor_id": r.get("actor_id"),
                "name": r.get("student_name") or r.get("teacher_name") or "未知",
            },
            "inputs": _json(r.get("inputs"), {}),
            # 审批人必须先看到「通过后会跑哪几步」：工具名 + 中文名，直接来自执行快照。
            # 没有这个明细的审批就是盲签——只对着一个名字点通过。
            "steps": _step_brief(snapshot or current),
            # 快照与定义不一致 = 提交后有人改过流程，审批前要让人看出来
            "definition_changed": bool(snapshot) and snapshot != current,
            "step_count": len(snapshot or current),
            "submitted_at": r.get("submitted_at").isoformat() if r.get("submitted_at") else None,
        })
    return {"total": len(items), "items": items,
            "approval_version": wf_engine.APPROVAL_VERSION}


def _step_brief(steps: list[dict[str, Any]]) -> list[dict[str, str]]:
    """步骤快照 → 展示用明细（顺序即执行顺序）。"""
    out: list[dict[str, str]] = []
    for st in steps or []:
        tool = str(st.get("tool") or "")
        out.append({
            "id": str(st.get("id") or tool),
            "tool": tool,
            "label": wf_engine.ALLOWED_TOOLS.get(tool, tool),
            "title": str(st.get("title") or wf_engine.ALLOWED_TOOLS.get(tool, tool)),
            "on_error": str(st.get("on_error") or "stop"),
        })
    return out


def list_history(ctx: ToolContext, limit: int = 20) -> dict[str, Any]:
    """本租户最近已处理的审批（教师回查：批了谁、批了什么、结果如何）。"""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT a.`运行编号` AS run_id, a.`动作` AS action, a.`意见` AS comment,"
                " a.`审批时间` AS decided_at, a.`审批人编号` AS approver_id,"
                " r.`状态` AS status, r.`错误` AS error, r.`耗时毫秒` AS elapsed_ms,"
                " r.`触发角色` AS actor_type, r.`触发人编号` AS actor_id,"
                " d.`编号` AS def_id, d.`名称` AS name,"
                " s.`姓名` AS student_name, t.`姓名` AS teacher_name, ap.`姓名` AS approver_name"
                " FROM `工作流审批` a"
                " JOIN `工作流运行` r ON r.`编号`=a.`运行编号`"
                " JOIN `工作流定义` d ON d.`编号`=r.`定义编号` AND d.`租户编号`=%s"
                " LEFT JOIN `学生` s ON r.`触发角色`='student' AND s.`编号`=r.`触发人编号`"
                " LEFT JOIN `教师` t ON r.`触发角色`='teacher' AND t.`编号`=r.`触发人编号`"
                " LEFT JOIN `教师` ap ON ap.`编号`=a.`审批人编号`"
                " ORDER BY a.`审批时间` DESC LIMIT %s",
                (ctx.tenant_id, max(1, min(int(limit), 100))))
            rows = list(cur.fetchall())
    finally:
        conn.close()

    items = []
    for r in rows:
        items.append({
            "run_id": int(r["run_id"]),
            "def_id": int(r["def_id"]),
            "name": r["name"],
            "action": str(r["action"]),
            "comment": r.get("comment"),
            "approver_name": r.get("approver_name") or "未知",
            "decided_at": r.get("decided_at").isoformat() if r.get("decided_at") else None,
            "status": str(r["status"]),
            "error": r.get("error"),
            "elapsed_ms": int(r.get("elapsed_ms") or 0),
            "submitted_by": {
                "actor_type": r.get("actor_type"),
                "name": r.get("student_name") or r.get("teacher_name") or "未知",
            },
        })
    return {"total": len(items), "items": items,
            "approval_version": wf_engine.APPROVAL_VERSION}


def _load_pending_run(run_id: int, tenant_id: int) -> dict[str, Any]:
    """取一条仍处 pending 的运行（含定义与租户校验），否则抛 ApprovalError。"""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT r.`编号` AS run_id, r.`状态` AS status, r.`触发角色` AS actor_type,"
                        " r.`触发人编号` AS actor_id, r.`入参` AS inputs,"
                        " r.`步骤快照` AS steps_snapshot,"
                        " d.`编号` AS def_id, d.`名称` AS name, d.`步骤` AS steps,"
                        " d.`租户编号` AS tenant_id"
                        " FROM `工作流运行` r JOIN `工作流定义` d ON d.`编号`=r.`定义编号`"
                        " WHERE r.`编号`=%s AND d.`租户编号`=%s", (run_id, tenant_id))
            row = cur.fetchone()
        if not row:
            raise ApprovalError("这条审批单不存在，或不在你所属的学校内。")
        if str(row["status"]) != wf_engine.STATUS_PENDING:
            raise ApprovalError(f"这条审批单已经处理过了（当前状态：{row['status']}）。")
        # 按提交时的快照执行；老记录没有快照时回退到定义表当前内容
        snapshot = _json(row.get("steps_snapshot"), [])
        current = _json(row.get("steps"), [])
        row["executable_steps"] = snapshot or current
        row["definition_changed"] = bool(snapshot) and snapshot != current
        return row
    finally:
        conn.close()


def _claim(run_id: int, ctx: ToolContext, action: str,
           comment: str | None) -> None:
    """抢占这条待审运行：审批留痕 + 条件改状态，同一事务，抢占失败即整体回滚。

    为什么必须「先抢再跑」：审批单是会被两个人同时点的。原来先跑步骤、
    后插审批记录，approve 与 reject 并发时两边都能通过 pending 校验——
    通过的那边走完、驳回的那边又把状态覆盖成 rejected，结果是「显示已驳回，
    步骤却真跑过了」。改成先抢：状态不是 pending 就抢不到，抢不到一步都不执行。
    """
    claim_status = (wf_engine.STATUS_RUNNING if action == wf_engine.ACTION_APPROVE
                    else wf_engine.STATUS_REJECTED)
    conn = _conn()
    try:
        conn.begin()
        try:
            with conn.cursor() as cur:
                # 唯一键 uk_approval_run：一次运行只能留一条审批记录
                cur.execute("INSERT INTO `工作流审批`(`运行编号`,`租户编号`,`审批人角色`,"
                            "`审批人编号`,`动作`,`意见`) VALUES (%s,%s,%s,%s,%s,%s)",
                            (run_id, ctx.tenant_id, ctx.actor_type, ctx.teacher_id,
                             action, comment or None))
                cur.execute("UPDATE `工作流运行` SET `状态`=%s"
                            " WHERE `编号`=%s AND `状态`=%s",
                            (claim_status, run_id, wf_engine.STATUS_PENDING))
                if cur.rowcount != 1:
                    raise ApprovalError("这条审批单刚刚已被处理，不能重复审批。")
            conn.commit()
        except pymysql.err.IntegrityError:
            conn.rollback()
            raise ApprovalError("这条审批单刚刚已被处理，不能重复审批。") from None
        except Exception:                   # 含 rowcount!=1 抛出的 ApprovalError：整体回滚
            conn.rollback()
            raise
    finally:
        conn.close()


def _finish(run_id: int, result: dict[str, Any], *, executed: bool) -> None:
    """把终态写回运行记录（此刻已抢占成功，只认自己这一次）。"""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            if executed:
                cur.execute("UPDATE `工作流运行` SET `状态`=%s,`步骤结果`=%s,`错误`=%s,"
                            "`耗时毫秒`=%s,`结束时间`=NOW()"
                            " WHERE `编号`=%s AND `状态`=%s",
                            (result["status"],
                             json.dumps(result.get("steps") or [], ensure_ascii=False,
                                        default=str),
                             result.get("error"), int(result.get("elapsed_ms") or 0),
                             run_id, wf_engine.STATUS_RUNNING))
            else:
                # 驳回：状态已在抢占时落成 rejected，这里只补结束时间
                cur.execute("UPDATE `工作流运行` SET `结束时间`=NOW()"
                            " WHERE `编号`=%s AND `状态`=%s",
                            (run_id, wf_engine.STATUS_REJECTED))
        conn.commit()
    finally:
        conn.close()


def decide(ctx: ToolContext, run_id: int, action: str,
           comment: str | None = None) -> dict[str, Any]:
    """审批一条待审运行：approve 才真正执行，reject 一步都不跑。"""
    if action not in (wf_engine.ACTION_APPROVE, wf_engine.ACTION_REJECT):
        raise ApprovalError("审批动作只能是「通过」或「驳回」。")
    if ctx.actor_type != "teacher":
        raise PermissionError("只有教师可以审批工作流。")

    row = _load_pending_run(run_id, ctx.tenant_id)
    def_id = int(row["def_id"])
    name = str(row["name"])
    steps = row["executable_steps"] or []
    inputs = _json(row["inputs"], {})
    changed = bool(row.get("definition_changed"))

    # 用**提交者**的身份执行：学生提交的流程只能看到学生自己的数据
    actor_type = str(row["actor_type"])
    actor_id = int(row["actor_id"] or 0)
    submitter = ToolContext(
        actor_type=actor_type,
        tenant_id=int(row["tenant_id"]),
        teacher_id=actor_id if actor_type == "teacher" else None,
        student_id=actor_id if actor_type == "student" else None,
    )

    # 抢占：抢不到说明刚被别人处理过，直接报错，绝不执行
    _claim(run_id, ctx, action, comment)

    result: dict[str, Any] = {}
    if action == wf_engine.ACTION_APPROVE:
        try:
            result = wf_engine.run(steps, _impl_for(submitter), extra_args=inputs)
        except wf_engine.WorkflowError as exc:
            result = {"status": wf_engine.STATUS_FAILED, "error": str(exc),
                      "steps": [], "elapsed_ms": 0, "outputs": {}}
        except Exception as exc:                       # 工具内部异常也要落终态
            result = {"status": wf_engine.STATUS_FAILED,
                      "error": f"{type(exc).__name__}: {exc}",
                      "steps": [], "elapsed_ms": 0, "outputs": {}}
    else:
        result = {"status": wf_engine.STATUS_REJECTED, "steps": [],
                  "elapsed_ms": 0, "outputs": {}}

    try:
        _finish(run_id, result, executed=action == wf_engine.ACTION_APPROVE)
    except Exception:                                  # 落库失败也不能把异常吞成 500 之外的怪象
        raise ApprovalError("审批已生效，但执行结果写回失败，请刷新后核对。") from None

    audit_event(tenant_id=ctx.tenant_id, actor_type=ctx.actor_type,
                actor_id=ctx.teacher_id or 0,
                action=f"workflow.{action}", target=str(run_id),
                detail={"def_id": def_id, "name": name, "status": result["status"],
                        "steps": len(result.get("steps") or []),
                        "definition_changed": changed,
                        "comment": (comment or "")[:200]})

    summary = (wf_engine.render_summary(result) if action == wf_engine.ACTION_APPROVE
               else f"已驳回「{name}」，工作流没有执行任何步骤。")
    if changed:
        summary += "（注意：提交后定义被改动过，本次按提交时的快照执行。）"
    return {
        "run_id": run_id,
        "name": name,
        "action": action,
        "status": result["status"],
        "steps": result.get("steps") or [],
        "elapsed_ms": int(result.get("elapsed_ms") or 0),
        "definition_changed": changed,
        "summary": summary,
        "approval_version": wf_engine.APPROVAL_VERSION,
    }
