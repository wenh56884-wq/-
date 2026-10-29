# app/routers/grades.py
# 职责：成绩单 API——学生看本人、教师看任教范围内学生的全部学年成绩。
# 鉴权：身份来自 JWT；学生不接受学号入参；教师经租户 + 任教范围校验（数据层过滤）。
# 铁律：聚合由 engine.grades 计算；路由只做取数、鉴权与异常翻译。

from __future__ import annotations

from typing import Any

import pymysql
from fastapi import APIRouter, Depends, HTTPException, status

from agents import tools
from agents.tools import ToolContext
from app.audit import audit_event
from app.auth import require_student, require_teacher
from app.config import get_settings
from engine.career_guide import grade_label
from engine.grades import build_report

router = APIRouter(prefix="/grades", tags=["成绩单"])

_GRADE_SQL = (
    "SELECT sc.`编号` AS record_id, sc.`学期` AS term, sc.`分数` AS score, "
    "       sc.`是否重修` AS retake, c.`课程编号` AS course_code, "
    "       c.`课程名称` AS course_name, c.`学分` AS credit "
    "FROM `成绩` sc "
    "JOIN `课程` c ON c.`编号` = sc.`课程编号` "
    "JOIN `学生` s ON s.`编号` = sc.`学生编号` "
    "WHERE s.`租户编号` = %s AND sc.`学生编号` = %s "
    "ORDER BY sc.`学期`, c.`课程编号`, sc.`编号`"
)


def _conn() -> pymysql.connections.Connection:
    s = get_settings()
    return pymysql.connect(host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
                           password=s.mysql_password, database=s.mysql_db,
                           charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)


def _report(ctx: ToolContext, stu: dict[str, Any]) -> dict[str, Any]:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(_GRADE_SQL, (ctx.tenant_id, int(stu["student_id"])))
            rows = [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
    student = {k: stu.get(k) for k in
               ("student_no", "name", "major", "class_name", "college", "enroll_year")}
    student["grade"] = grade_label(stu.get("enroll_year"))
    return build_report(rows, student)


@router.get("/me")
def my_grades(ctx: ToolContext = Depends(require_student)) -> dict[str, Any]:
    """学生本人全部成绩；学号只来自 JWT，不接受任何入参指定他人。"""
    try:
        stu = tools._resolve_self(ctx, "grades")
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    report = _report(ctx, stu)
    audit_event(actor_type=ctx.actor_type, actor_id=ctx.student_id, action="grades.view",
                target=str(stu["student_no"]),
                detail={"self": True, "records": report["summary"]["record_count"]})
    return report


@router.get("/student/{student_no}")
def student_grades(student_no: str,
                   ctx: ToolContext = Depends(require_teacher)) -> dict[str, Any]:
    """教师查看学生全部成绩；租户 + 任教范围校验在 tools 层完成。"""
    try:
        stu = tools._fetch_student(ctx, student_no, "grades")
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    report = _report(ctx, stu)
    audit_event(actor_type=ctx.actor_type, actor_id=ctx.teacher_id, action="grades.view",
                target=str(student_no),
                detail={"records": report["summary"]["record_count"]})
    return report


@router.get("/class-rank")
def class_rank(class_name: str, term: str | None = None,
               ctx: ToolContext = Depends(require_teacher)) -> dict[str, Any]:
    """教师端成绩分析：全班总体均分、个人均分，以及同专业内的班级排名与个人排名。

    取数与计算都在 tools.class_grades_rank（和智能体用的是同一份），
    路由只做鉴权与异常翻译，避免接口和智能体两套口径漂掉。
    """
    try:
        result = tools.class_grades_rank(ctx, class_name, term)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except ValueError as exc:
        # 班级名写错不是越权，按 404 给出候选提示
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    audit_event(actor_type=ctx.actor_type, actor_id=ctx.teacher_id,
                action="grades.class_rank", target=str(class_name),
                detail={"term": result.get("term"),
                        "student_cnt": len(result.get("students") or []),
                        "class_cnt": len(result.get("classes") or [])})
    return result
