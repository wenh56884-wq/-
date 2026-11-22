# app/routers/export.py
# 职责：学生档案 / 成绩数据的下载接口（xlsx / csv / json）
# 依赖：app.exporters（渲染）、agents.tools（取数与权限）、engine.warning（口径）
# 说明：数值一律复用引擎与工具层，导出层只做「取数 → 摆列 → 换容器」，
#       不允许在这里重新计算，否则导出的数和页面显示的对不上。

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from agents import tools
from agents.tools import ToolContext
from app import exporters
from app.auth import get_current_ctx, require_student, require_teacher
from engine import warning

router = APIRouter(prefix="/export", tags=["数据导出"])

# 等级中文文案：与前端 TeacherStudents.vue 的 LEVELS 逐字一致，
# 导出的表和页面看到的必须是同一套说法
_LEVEL_TEXT = {"red": "红色预警", "orange": "橙色预警", "yellow": "黄色预警",
               "none": "正常", "unknown": "数据不足"}

_FMT = Query(default="xlsx", pattern="^(xlsx|csv|json)$",
             description="下载格式：xlsx / csv / json")


def _safe(text: str) -> str:
    """文件名去掉路径分隔符等非法字符，避免浏览器丢弃整个文件名。"""
    return "".join("-" if ch in '\\/:*?"<>|' else ch for ch in str(text)).strip() or "导出"


def _num(value: Any, digits: int = 2) -> float | None:
    """Decimal/str → float，供 Excel 识别为数值单元格；None 保持 None。"""
    if value is None or value == "":
        return None
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- 字段目录
# 「想要什么数据就导出什么」的实现：每个数据集声明一份字段目录，
# 导出时按用户勾选的 key 投影出表头与行；不传 fields = 全字段（保持老行为）。
# 取值全部在 _xxx_values() 里算好，投影层不碰业务口径，也不重算任何指标。


def _field(key: str, label: str, group: str) -> dict[str, str]:
    return {"key": key, "label": label, "group": group}


_STUDENT_FIELDS: list[dict[str, str]] = [
    _field("student_no", "学号", "基本信息"),
    _field("name", "姓名", "基本信息"),
    _field("college", "学院", "基本信息"),
    _field("major", "专业", "基本信息"),
    _field("class_name", "班级", "基本信息"),
    _field("grade", "年级", "基本信息"),
    _field("level_text", "预警等级", "预警"),
    _field("risk_score", "风险分", "预警"),
    _field("reasons", "预警原因", "预警"),
    _field("coverage", "数据覆盖率", "预警"),
    _field("handbook_flag", "触及手册警示线", "预警"),
    _field("gpa", "GPA", "学业指标"),
    _field("gpa_drop", "平均分下滑", "学业指标"),
    _field("fail_count", "挂科门数", "学业指标"),
    _field("fail_credits", "不及格学分", "学业指标"),
    _field("attendance_rate", "出勤率", "学业指标"),
    _field("class_rank_pct", "班级排名百分位", "学业指标"),
    _field("warning_count", "历史预警次数", "学业指标"),
]

_GRADE_FIELDS: list[dict[str, str]] = [
    _field("student_no", "学号", "学生"),
    _field("name", "姓名", "学生"),
    _field("class_name", "班级", "学生"),
    _field("term", "学期", "课程"),
    _field("course_code", "课程编号", "课程"),
    _field("course_name", "课程名称", "课程"),
    _field("credit", "学分", "课程"),
    _field("score", "分数", "成绩"),
    _field("passed", "是否及格", "成绩"),
    _field("retake_text", "是否重修", "成绩"),
]

# 数据集名 → (中文名, 字段目录, 说明, 允许的角色)
_DATASETS = {
    "students": ("班级学生档案", _STUDENT_FIELDS,
                 "名单 + 预警等级 + 风险分 + 归因 + 学业指标", "teacher"),
    "grades": ("全班成绩明细", _GRADE_FIELDS, "每生每课一行", "teacher"),
    "student-grades": ("单个学生成绩单", _GRADE_FIELDS, "跨学期逐门课程", "teacher"),
    "my-grades": ("我的成绩单", _GRADE_FIELDS, "跨学期逐门课程", "student"),
}


def _parse_fields(raw: str | None) -> list[str]:
    return [k.strip() for k in str(raw or "").split(",") if k.strip()]


def _project(catalog: list[dict[str, str]], records: list[dict[str, Any]],
             fields: str | None) -> tuple[list[str], list[list[Any]], list[str]]:
    """按勾选字段投影。返回 (表头, 行, 实际用到的 key)。

    顺序永远按目录顺序、不按用户勾选顺序——同一份导出换个人勾就是另一种列序，
    对账时会怀疑数据不一样。
    """
    wanted = _parse_fields(fields)
    known = {f["key"] for f in catalog}
    unknown = [k for k in wanted if k not in known]
    if unknown:
        raise HTTPException(status_code=422,
                            detail="不认识的字段：" + "、".join(unknown))
    cols = [f for f in catalog if not wanted or f["key"] in wanted]
    if not cols:
        raise HTTPException(status_code=422, detail="至少要选一个字段")
    headers = [f["label"] for f in cols]
    keys = [f["key"] for f in cols]
    rows = [[rec.get(k) for k in keys] for rec in records]
    return headers, rows, keys


def _student_values(stu: Mapping[str, Any], warn: Mapping[str, Any]) -> dict[str, Any]:
    """一名学生的全部可导出字段（值都在这里定死，投影层只挑列）。"""
    lv = str(warn.get("level") or "none")
    m = warn.get("metrics") or {}
    hb = warn.get("handbook") or None
    return {
        "student_no": str(stu.get("student_no") or ""),
        "name": stu.get("name") or "",
        "college": stu.get("college") or "",
        "major": stu.get("major") or "",
        "class_name": stu.get("class_name") or "",
        "grade": stu.get("grade") or "",
        "level_text": _LEVEL_TEXT.get(lv, lv),
        "risk_score": int(warn["risk_score"]) if warn.get("risk_score") is not None else None,
        "reasons": "；".join(warn.get("reasons") or []),
        "coverage": int(warn["coverage"]) if warn.get("coverage") is not None else None,
        "handbook_flag": ("是" if hb.get("warning_required") else "否") if hb else "",
        "gpa": _num(m.get("gpa")),
        "gpa_drop": _num(m.get("gpa_drop")),
        "fail_count": int(m["fail_count"]) if m.get("fail_count") is not None else None,
        "fail_credits": _num(m.get("fail_credits"), 1),
        "attendance_rate": _num(m.get("attendance_rate"), 4),
        "class_rank_pct": _num(m.get("class_rank_pct"), 1),
        "warning_count": int(m["warning_count"]) if m.get("warning_count") is not None else None,
    }


def _grade_values(raw: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """成绩记录 → 全部可导出字段。"""
    out: list[dict[str, Any]] = []
    for r in raw:
        score = _num(r.get("score"))
        credit = _num(r.get("credit"), 1)
        out.append({
            "student_no": str(r.get("student_no") or ""),
            "name": r.get("name") or "",
            "class_name": r.get("class_name") or "",
            "term": r.get("term") or "",
            "course_code": r.get("course_code") or "",
            "course_name": r.get("course_name") or "",
            "credit": credit,
            "score": score,
            "passed": "" if score is None else ("及格" if score >= 60 else "不及格"),
            "retake_text": "是" if int(r.get("retake") or 0) else "否",
        })
    return out


def _student_base(ctx: ToolContext, class_name: str) -> list[dict[str, Any]]:
    """班级学生基础信息（学院/专业/年级不在预警引擎返回里，单独取一次）。"""
    return tools._query(
        "SELECT `学号` AS student_no, `姓名` AS name, `学院` AS college, "
        "       `专业` AS major, `班级` AS class_name, `年级` AS grade "
        "FROM `学生` WHERE `租户编号` = %s AND `班级` = %s ORDER BY `学号`",
        (ctx.tenant_id, class_name))


def _warning_map(ctx: ToolContext, class_name: str, term: str) -> dict[str, dict[str, Any]]:
    """预警引擎结果按学号索引；引擎不可用时返回空字典，导出退化为纯档案。"""
    try:
        results = warning.compute_class(ctx.tenant_id, class_name, term)
    except Exception:  # 引擎异常不能让人连档案都导不出来
        return {}
    return {str(r.get("student_no")): r for r in results}


# ---------------------------------------------------------------- 学生档案
def _student_records(ctx: ToolContext, class_name: str, term: str,
                    level: str) -> list[dict[str, Any]]:
    """一名学生一条记录（字段全量），过滤只发生在等级上。"""
    base = _student_base(ctx, class_name)
    warns = _warning_map(ctx, class_name, term)
    wanted = {lv.strip() for lv in str(level or "").split(",") if lv.strip()}

    out: list[dict[str, Any]] = []
    for stu in base:
        no = str(stu.get("student_no"))
        warn = warns.get(no) or {}
        lv = str(warn.get("level") or "none")
        if wanted and lv not in wanted:
            continue
        out.append(_student_values(stu, warn))
    return out


@router.get("/students")
def export_students(
    class_name: str = Query(description="班级名，必须属于本租户/任教范围"),
    term: str = Query(default="", description="学期；留空取引擎默认学期"),
    level: str = Query(default="", description="预警等级过滤，逗号分隔；留空=全部"),
    fields: str = Query(default="", description="逗号分隔的字段 key；留空=全部字段"),
    fmt: str = _FMT,
    ctx: ToolContext = Depends(require_teacher),
) -> Any:
    """导出班级学生档案：默认全字段，可用 fields 只挑想要的那几列。"""
    try:
        tools._require_class(ctx, class_name, "export_students")
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    term_used = tools._resolve_term(ctx, term)
    records = _student_records(ctx, class_name, term_used, level)
    headers, rows, keys = _project(_STUDENT_FIELDS, records, fields)
    tools._audit_call(ctx, "export_students", f"{class_name}/{term_used}",
                      {"format": fmt, "count": len(rows), "level": level or "all",
                       "fields": keys if _parse_fields(fields) else "all"})

    stem = _safe(f"学生档案-{class_name}-{term_used}")
    return exporters.build_response(
        fmt, stem,
        headers=headers, rows=rows,
        sheets=[("学生档案", headers, rows)],
        ascii_stem=_safe(f"students-{class_name}-{term_used}"),
        payload={
            "class_name": class_name, "term": term_used,
            "level": level or "all", "total": len(records),
            "fields": [{"key": k, "label": lb} for k, lb in zip(keys, headers)],
            "exported_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
            "students": [{k: v.get(k) for k in keys} for v in records],
        },
    )


# ---------------------------------------------------------------- 成绩
_GRADE_SQL = (
    "SELECT s.`学号` AS student_no, s.`姓名` AS name, s.`班级` AS class_name, "
    "       sc.`学期` AS term, c.`课程编号` AS course_code, "
    "       c.`课程名称` AS course_name, c.`学分` AS credit, "
    "       sc.`分数` AS score, sc.`是否重修` AS retake "
    "FROM `成绩` sc "
    "JOIN `学生` s ON s.`编号` = sc.`学生编号` "
    "LEFT JOIN `课程` c ON c.`编号` = sc.`课程编号` "
    "WHERE s.`租户编号` = %s AND sc.`学期` = %s "
)


def _summary_rows(rows: list[dict[str, Any]]) -> list[list[Any]]:
    """按学生汇总：均分 / 加权均分 / 门数 / 挂科数。与成绩单口径一致（取全部记录）。"""
    agg: dict[str, dict[str, Any]] = {}
    for r in rows:
        key = str(r.get("student_no") or "")
        if key not in agg:
            agg[key] = {"name": r.get("name") or "", "class_name": r.get("class_name") or "",
                        "scores": [], "weighted_num": 0.0, "weighted_den": 0.0,
                        "courses": set(), "fails": set()}
        item = agg[key]
        score = _num(r.get("score"))
        credit = _num(r.get("credit"), 1) or 0.0
        item["courses"].add(str(r.get("course_code") or ""))
        if score is None:
            continue
        item["scores"].append(score)
        if credit:
            item["weighted_num"] += score * credit
            item["weighted_den"] += credit
        if score < 60:
            item["fails"].add(str(r.get("course_code") or ""))

    out: list[list[Any]] = []
    for no, item in sorted(agg.items()):
        scores = item["scores"]
        avg = round(sum(scores) / len(scores), 2) if scores else None
        weighted = (round(item["weighted_num"] / item["weighted_den"], 2)
                    if item["weighted_den"] else None)
        # 修读门数按课程编号去重，成绩记录数含重修重复记录——两者口径不同，不能混用
        out.append([no, item["name"], item["class_name"], len(item["courses"]),
                    len(scores), avg, weighted, len(item["fails"])])
    return out


_SUMMARY_HEADERS = ["学号", "姓名", "班级", "修读门数", "成绩记录数",
                    "平均分", "加权均分", "挂科门数"]


@router.get("/grades")
def export_grades(
    class_name: str = Query(description="班级名，必须属于本租户/任教范围"),
    term: str = Query(default="", description="学期；留空取引擎默认学期"),
    fields: str = Query(default="", description="逗号分隔的字段 key；留空=全部字段"),
    fmt: str = _FMT,
    ctx: ToolContext = Depends(require_teacher),
) -> Any:
    """导出全班成绩明细（每生每课一行）；默认全字段，可只挑想要的列。

    选了字段就不再附「个人汇总」sheet——勾了几列却多出一张八列汇总，
    等于没尊重用户的选择。
    """
    try:
        tools._require_class(ctx, class_name, "export_grades")
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    term_used = tools._resolve_term(ctx, term)
    raw = tools._query(
        _GRADE_SQL + "AND s.`班级` = %s ORDER BY s.`学号`, c.`课程编号`",
        (ctx.tenant_id, term_used, class_name))
    recs = _grade_values(raw)
    headers, rows, keys = _project(_GRADE_FIELDS, recs, fields)
    summary = _summary_rows(raw)
    tools._audit_call(ctx, "export_grades", f"{class_name}/{term_used}",
                      {"format": fmt, "records": len(rows),
                       "fields": keys if _parse_fields(fields) else "all"})

    sheets = [("成绩明细", headers, rows)]
    if not _parse_fields(fields):
        sheets.append(("个人汇总", _SUMMARY_HEADERS, summary))

    stem = _safe(f"班级成绩-{class_name}-{term_used}")
    return exporters.build_response(
        fmt, stem,
        headers=headers, rows=rows,
        sheets=sheets,
        ascii_stem=_safe(f"class-grades-{class_name}-{term_used}"),
        payload={
            "class_name": class_name, "term": term_used,
            "record_count": len(rows), "student_count": len(summary),
            "fields": [{"key": k, "label": lb} for k, lb in zip(keys, headers)],
            # 勾了字段就不附汇总：JSON 里多一段用户没勾的 8 列数据，等于没尊重选择
            "summary": ([] if _parse_fields(fields)
                        else [dict(zip(_SUMMARY_HEADERS, r)) for r in summary]),
            "records": [{k: v.get(k) for k in keys} for v in recs],
        },
    )


def _one_student_grades(ctx: ToolContext, student_no: str, term: str) -> list[dict[str, Any]]:
    """单人成绩：两条独立 SQL 而不是字符串拼接，避免改动主 SQL 时静默错位。"""
    cols = ("SELECT s.`学号` AS student_no, s.`姓名` AS name, s.`班级` AS class_name, "
            "       sc.`学期` AS term, c.`课程编号` AS course_code, "
            "       c.`课程名称` AS course_name, c.`学分` AS credit, "
            "       sc.`分数` AS score, sc.`是否重修` AS retake "
            "FROM `成绩` sc "
            "JOIN `学生` s ON s.`编号` = sc.`学生编号` "
            "LEFT JOIN `课程` c ON c.`编号` = sc.`课程编号` ")
    if term:
        return tools._query(
            cols + "WHERE s.`租户编号` = %s AND sc.`学期` = %s AND s.`学号` = %s "
                   "ORDER BY sc.`学期`, c.`课程编号`",
            (ctx.tenant_id, term, student_no))
    return tools._query(
        cols + "WHERE s.`租户编号` = %s AND s.`学号` = %s "
               "ORDER BY sc.`学期`, c.`课程编号`",
        (ctx.tenant_id, student_no))


@router.get("/student-grades/{student_no}")
def export_student_grades(
    student_no: str,
    term: str = Query(default="", description="学期；留空导出全部学期"),
    fields: str = Query(default="", description="逗号分隔的字段 key；留空=全部字段"),
    fmt: str = _FMT,
    ctx: ToolContext = Depends(require_teacher),
) -> Any:
    """教师导出某一名学生的完整成绩单（默认跨全部学期，可只挑字段）。"""
    try:
        stu = tools._fetch_student(ctx, student_no, "export_student_grades")
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    raw = _one_student_grades(ctx, str(stu["student_no"]), term)
    recs = _grade_values(raw)
    headers, rows, keys = _project(_GRADE_FIELDS, recs, fields)
    tools._audit_call(ctx, "export_student_grades", str(student_no),
                      {"format": fmt, "records": len(rows),
                       "fields": keys if _parse_fields(fields) else "all"})

    stem = _safe(f"成绩单-{stu.get('name') or ''}-{stu['student_no']}")
    return exporters.build_response(
        fmt, stem,
        headers=headers, rows=rows,
        sheets=[("成绩单", headers, rows)],
        ascii_stem=f"grade-report-{stu['student_no']}",
        payload={
            "student": {k: stu.get(k) for k in
                        ("student_no", "name", "major", "class_name", "college", "enroll_year")},
            "term": term or "全部学期",
            "record_count": len(rows),
            "fields": [{"key": k, "label": lb} for k, lb in zip(keys, headers)],
            "records": [{k: v.get(k) for k in keys} for v in recs],
        },
    )


@router.get("/my-grades")
def export_my_grades(
    term: str = Query(default="", description="学期；留空导出全部学期"),
    fields: str = Query(default="", description="逗号分隔的字段 key；留空=全部字段"),
    fmt: str = _FMT,
    ctx: ToolContext = Depends(require_student),
) -> Any:
    """学生导出自己的成绩单：学号只来自 JWT，不接受任何入参指定他人。"""
    try:
        stu = tools._resolve_self(ctx, "export_my_grades")
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))

    raw = _one_student_grades(ctx, str(stu["student_no"]), term)
    recs = _grade_values(raw)
    headers, rows, keys = _project(_GRADE_FIELDS, recs, fields)
    tools._audit_call(ctx, "export_my_grades", str(stu["student_no"]),
                      {"format": fmt, "records": len(rows),
                       "fields": keys if _parse_fields(fields) else "all"})

    stem = _safe(f"我的成绩单-{stu['student_no']}")
    return exporters.build_response(
        fmt, stem,
        headers=headers, rows=rows,
        sheets=[("我的成绩单", headers, rows)],
        ascii_stem=f"my-grades-{stu['student_no']}",
        payload={
            "student": {k: stu.get(k) for k in
                        ("student_no", "name", "major", "class_name", "enroll_year")},
            "term": term or "全部学期",
            "record_count": len(rows),
            "fields": [{"key": k, "label": lb} for k, lb in zip(keys, headers)],
            "records": [{k: v.get(k) for k in keys} for v in recs],
        },
    )


# ---------------------------------------------------------------- 字段目录接口
@router.get("/fields")
def export_fields(
    dataset: str = Query(default="students", description="students / grades / student-grades / my-grades"),
    ctx: ToolContext = Depends(get_current_ctx),
) -> dict:
    """列出某个数据集能导出哪些字段，供前端画勾选框。

    顺带返回每组的字段数与推荐默认勾选（全选），前端不必自己猜顺序。
    """
    item = _DATASETS.get(str(dataset or "").strip())
    if not item:
        raise HTTPException(status_code=404, detail=f"未知数据集：{dataset}")
    label, catalog, desc, role = item
    if role == "teacher" and ctx.actor_type != "teacher":
        raise HTTPException(status_code=403, detail="该数据集仅教师可导出")
    if role == "student" and ctx.actor_type != "student":
        raise HTTPException(status_code=403, detail="该数据集仅学生本人可导出")

    groups: list[dict[str, Any]] = []
    for f in catalog:
        grp = next((g for g in groups if g["name"] == f["group"]), None)
        if grp is None:
            grp = {"name": f["group"], "fields": []}
            groups.append(grp)
        grp["fields"].append({"key": f["key"], "label": f["label"]})

    return {
        "dataset": dataset,
        "label": label,
        "desc": desc,
        "role": role,
        "total": len(catalog),
        "groups": groups,
        "fields": [{"key": f["key"], "label": f["label"], "group": f["group"]} for f in catalog],
    }
