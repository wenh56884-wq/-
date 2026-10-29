# app/routers/exam.py
# 职责：招考公告查询 API（考公 / 考编 / 考研），数据由 scripts/sync_recruit.py 周更入库。
#
# 设计：
# - 纯只读接口，不改任何状态；数据全部来自官方公告原文，带链接可核对。
# - 「要求」字段可能为 None（公告附件里才有具体岗位表），前端必须显示为「详见公告」，
#   不能显示成「不限」——**缺失不冒充**。
# - 默认只返回未截止 + 状态未知的公告；要查历年用 include_closed=true。

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/exam", tags=["招考信息"])

_EXAM_TYPES = {"civil", "institution", "postgraduate"}
_TYPE_LABEL = {"civil": "考公", "institution": "考编", "postgraduate": "考研"}


def _conn():
    """取 MySQL 连接（DictCursor：按列名取值，避免位置索引写错）。"""
    import pymysql

    from app.config import get_settings

    s = get_settings()
    return pymysql.connect(
        host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
        password=s.mysql_password, database=s.mysql_db, charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def _row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    """统一转成前端友好的结构；日期转 ISO 字符串，缺失保持 None。"""
    out = dict(row)
    for k in ("publish_date", "signup_start", "signup_end", "exam_date"):
        v = out.get(k)
        out[k] = v.isoformat() if hasattr(v, "isoformat") else v
    for k in ("first_seen_at", "last_seen_at"):
        v = out.get(k)
        out[k] = v.isoformat(sep=" ") if hasattr(v, "isoformat") else v
    out["exam_type_label"] = _TYPE_LABEL.get(out.get("exam_type") or "", "")
    # 明确告诉前端哪些要求是「公告没写」，避免被渲染成「不限」
    out["missing_requirements"] = [
        k for k in ("education_req", "degree_req", "major_req", "age_req",
                    "political_req", "exp_req", "cert_req", "other_req")
        if not out.get(k)
    ]
    return out


@router.get("/notices")
def list_notices(
    exam_type: str | None = Query(default=None, description="civil/institution/postgraduate"),
    region: str | None = Query(default=None, description="地区，如 重庆"),
    keyword: str | None = Query(default=None, max_length=60, description="标题关键词"),
    include_closed: bool = Query(default=False, description="是否包含已截止的历史公告"),
    only_open: bool = Query(default=False, description="只看在招（status=open）"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """按条件分页查招考公告。"""
    if exam_type and exam_type not in _EXAM_TYPES:
        raise HTTPException(status_code=422, detail=f"exam_type 只能是 {sorted(_EXAM_TYPES)}")

    where = ["`租户编号` = %s"]
    params: list[Any] = [1]
    if exam_type:
        where.append("`考试类型` = %s")
        params.append(exam_type)
    if region:
        where.append("`地区` LIKE %s")
        params.append(f"%{region}%")
    if keyword:
        where.append("`标题` LIKE %s")
        params.append(f"%{keyword}%")
    if only_open:
        where.append("`状态` = 'open'")
    elif not include_closed:
        # 默认：未截止 + 状态未知（unknown 不能当成已截止丢掉）
        where.append("`状态` <> 'closed'")

    cond = " AND ".join(where)
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS n FROM `招考公告` WHERE {cond}", params)
            total = int(cur.fetchone()["n"])
            cur.execute(
                "SELECT `编号` AS id, `考试类型` AS exam_type, `来源` AS source, "
                "`标题` AS title, `招录单位` AS org_name, `地区` AS region, "
                "`学历要求` AS education_req, `学位要求` AS degree_req, "
                "`专业要求` AS major_req, `年龄要求` AS age_req, "
                "`政治面貌要求` AS political_req, `经历要求` AS exp_req, "
                "`证书要求` AS cert_req, `其他要求` AS other_req, "
                "`招录人数` AS headcount, `发布日期` AS publish_date, "
                "`报名开始` AS signup_start, `报名截止` AS signup_end, "
                "`考试日期` AS exam_date, `原文链接` AS detail_url, `状态` AS status, "
                "`首次发现时间` AS first_seen_at, `最近发现时间` AS last_seen_at "
                f"FROM `招考公告` WHERE {cond} "
                "ORDER BY (`发布日期` IS NULL), `发布日期` DESC, `编号` DESC "
                "LIMIT %s OFFSET %s",
                [*params, page_size, (page - 1) * page_size],
            )
            rows = [_row_to_dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": rows,
    }


@router.get("/notices/{notice_id}")
def get_notice(notice_id: int) -> dict[str, Any]:
    """单条公告详情（含正文原文，便于核对要求）。"""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT `编号` AS id, `考试类型` AS exam_type, `来源` AS source, "
                "`标题` AS title, `招录单位` AS org_name, `地区` AS region, "
                "`学历要求` AS education_req, `学位要求` AS degree_req, "
                "`专业要求` AS major_req, `年龄要求` AS age_req, "
                "`政治面貌要求` AS political_req, `经历要求` AS exp_req, "
                "`证书要求` AS cert_req, `其他要求` AS other_req, "
                "`招录人数` AS headcount, `发布日期` AS publish_date, "
                "`报名开始` AS signup_start, `报名截止` AS signup_end, "
                "`考试日期` AS exam_date, `原文链接` AS detail_url, `状态` AS status, "
                "`正文原文` AS raw_text, `首次发现时间` AS first_seen_at, "
                "`最近发现时间` AS last_seen_at "
                "FROM `招考公告` WHERE `编号` = %s AND `租户编号` = %s",
                (notice_id, 1),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="公告不存在")
    return _row_to_dict(row)


# ----------------------------------------------------------------
# 国考职位表（国家公务员局《招考简章》逐职位明细）
# ----------------------------------------------------------------
_POSITION_LIST_FIELDS = (
    "`编号` AS id, `年度` AS year, `简章分类` AS category, "
    "`部门名称` AS dept_name, `用人司局` AS bureau, `招考职位` AS position_name, "
    "`职位代码` AS position_code, `招考人数` AS headcount, `学历` AS education, "
    "`学位` AS degree, `政治面貌` AS political, `专业` AS major, "
    "`工作地点` AS work_place, `机构层级` AS org_level, `考试类别` AS exam_category"
)


def _latest_position_year(cur, tenant_id: int = 1) -> int | None:
    cur.execute("SELECT MAX(`年度`) AS y FROM `国考职位` WHERE `租户编号` = %s",
                (tenant_id,))
    row = cur.fetchone()
    return int(row["y"]) if row and row["y"] is not None else None


def _position_where(year: int, keyword: str, dept: str, education: str,
                    degree: str, political: str, place: str,
                    category: str) -> tuple[str, list[Any]]:
    """拼职位筛选条件；所有值走参数绑定，不拼字符串。"""
    where = ["`租户编号` = %s", "`年度` = %s"]
    params: list[Any] = [1, year]
    if keyword:
        where.append("(`招考职位` LIKE %s OR `部门名称` LIKE %s OR "
                     "`用人司局` LIKE %s OR `专业` LIKE %s OR `职位代码` LIKE %s)")
        params.extend([f"%{keyword}%"] * 5)
    if dept:
        where.append("`部门名称` LIKE %s")
        params.append(f"%{dept}%")
    if education:
        where.append("`学历` LIKE %s")
        params.append(f"%{education}%")
    if degree:
        where.append("`学位` LIKE %s")
        params.append(f"%{degree}%")
    if political:
        where.append("`政治面貌` LIKE %s")
        params.append(f"%{political}%")
    if place:
        where.append("`工作地点` LIKE %s")
        params.append(f"%{place}%")
    if category:
        where.append("`简章分类` LIKE %s")
        params.append(f"%{category}%")
    return " AND ".join(where), params


@router.get("/positions/facets")
def position_facets(year: int | None = Query(default=None)) -> dict[str, Any]:
    """职位筛选器与总量：年度、分类、部门、学历、政治面貌、工作地点。"""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            latest = _latest_position_year(cur)
            if latest is None:
                return {"year": None, "years": [], "total_positions": 0,
                        "total_headcount": 0, "categories": [], "departments": [],
                        "educations": [], "politicals": [], "places": [],
                        "source_url": ""}
            use_year = int(year or latest)
            base = ("FROM `国考职位` WHERE `租户编号` = 1 AND `年度` = %s")
            cur.execute(f"SELECT COUNT(*) AS n, COALESCE(SUM(`招考人数`),0) AS p {base}",
                        (use_year,))
            totals = cur.fetchone()
            cur.execute(f"SELECT `公告链接` AS u {base} LIMIT 1", (use_year,))
            source = cur.fetchone()
            cur.execute(
                "SELECT `年度` AS year, COUNT(*) AS positions, "
                f"COALESCE(SUM(`招考人数`),0) AS headcount FROM `国考职位` "
                "WHERE `租户编号` = 1 GROUP BY `年度` ORDER BY `年度` DESC")
            years = [{"year": int(r["year"]), "positions": int(r["positions"]),
                      "headcount": int(r["headcount"])} for r in cur.fetchall()]

            def facet(column: str, limit: int = 30) -> list[dict[str, Any]]:
                cur.execute(
                    f"SELECT `{column}` AS name, COUNT(*) AS n {base} "
                    f"GROUP BY `{column}` ORDER BY n DESC, `{column}` LIMIT %s",
                    (use_year, limit))
                return [{"name": r["name"], "positions": int(r["n"])}
                        for r in cur.fetchall() if r["name"]]

            out = {
                "year": use_year,
                "years": years,
                "total_positions": int(totals["n"]),
                "total_headcount": int(totals["p"]),
                "categories": facet("简章分类"),
                "departments": facet("部门名称"),
                "educations": facet("学历"),
                "politicals": facet("政治面貌"),
                "places": facet("工作地点"),
                "source_url": (source or {}).get("u") or "",
            }
    finally:
        conn.close()
    return out


@router.get("/positions")
def list_positions(
    year: int | None = Query(default=None, description="考试年度，默认最新年度"),
    keyword: str | None = Query(default=None, max_length=60,
                               description="职位/部门/司局/专业/职位代码"),
    dept: str | None = Query(default=None, max_length=100, description="部门名称（模糊）"),
    education: str | None = Query(default=None, max_length=60, description="学历（模糊）"),
    degree: str | None = Query(default=None, max_length=60, description="学位（模糊）"),
    political: str | None = Query(default=None, max_length=60, description="政治面貌（模糊）"),
    place: str | None = Query(default=None, max_length=60, description="工作地点（模糊）"),
    category: str | None = Query(default=None, max_length=100, description="简章分类（模糊）"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """国考职位分页查询：返回职位明细 + 命中总数 + 招录人数合计。"""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            latest = _latest_position_year(cur)
            if latest is None:
                return {"year": None, "total": 0, "total_headcount": 0,
                        "page": page, "page_size": page_size, "items": []}
            use_year = int(year or latest)
            cond, params = _position_where(
                use_year, str(keyword or "").strip(), str(dept or "").strip(),
                str(education or "").strip(), str(degree or "").strip(),
                str(political or "").strip(), str(place or "").strip(),
                str(category or "").strip())
            cur.execute(
                f"SELECT COUNT(*) AS n, COALESCE(SUM(`招考人数`),0) AS p "
                f"FROM `国考职位` WHERE {cond}", params)
            totals = cur.fetchone()
            cur.execute(
                f"SELECT {_POSITION_LIST_FIELDS} FROM `国考职位` WHERE {cond} "
                "ORDER BY `招考人数` DESC, `编号` ASC LIMIT %s OFFSET %s",
                [*params, page_size, (page - 1) * page_size])
            items = [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
    return {
        "year": use_year,
        "total": int(totals["n"]),
        "total_headcount": int(totals["p"]),
        "page": page,
        "page_size": page_size,
        "items": items,
    }


@router.get("/positions/{position_id}")
def get_position(position_id: int) -> dict[str, Any]:
    """单条职位详情（全部原文要求 + 官方专题链接）。"""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT `编号` AS id, `年度` AS year, `来源` AS source, "
                "`简章分类` AS category, `部门代码` AS dept_code, "
                "`部门名称` AS dept_name, `用人司局` AS bureau, "
                "`机构性质` AS org_nature, `招考职位` AS position_name, "
                "`职位属性` AS position_attr, `职位分布` AS position_dist, "
                "`职位简介` AS intro, `职位代码` AS position_code, "
                "`机构层级` AS org_level, `考试类别` AS exam_category, "
                "`招考人数` AS headcount, `专业` AS major, `学历` AS education, "
                "`学位` AS degree, `政治面貌` AS political, "
                "`基层工作最低年限` AS work_years, "
                "`服务基层项目工作经历` AS grassroots_project, "
                "`是否组织专业能力测试` AS pro_test, "
                "`面试人员比例` AS interview_ratio, `工作地点` AS work_place, "
                "`落户地点` AS settle_place, `备注` AS remark, "
                "`部门网站` AS dept_site, `咨询电话1` AS phone1, "
                "`咨询电话2` AS phone2, `咨询电话3` AS phone3, "
                "`公告链接` AS notice_url, `数据文件` AS data_file, "
                "`首次发现时间` AS first_seen_at, `最近发现时间` AS last_seen_at "
                "FROM `国考职位` WHERE `编号` = %s AND `租户编号` = %s",
                (position_id, 1))
            row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="职位不存在")
    out = dict(row)
    for key in ("first_seen_at", "last_seen_at"):
        value = out.get(key)
        out[key] = value.isoformat(sep=" ") if hasattr(value, "isoformat") else value
    return out


@router.get("/stats")
def stats() -> dict[str, Any]:
    """各类型条数与数据新鲜度（最后一次成功抓取时间）。"""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT `考试类型` AS exam_type, COUNT(*) AS n, "
                "       SUM(`状态`='open') AS open_n "
                "FROM `招考公告` WHERE `租户编号`=%s GROUP BY `考试类型`",
                (1,),
            )
            by_type = [
                {"exam_type": r["exam_type"],
                 "label": _TYPE_LABEL.get(r["exam_type"], ""),
                 "total": int(r["n"]),
                 "open": int(r["open_n"] or 0)}
                for r in cur.fetchall()
            ]
            cur.execute(
                "SELECT MAX(`运行时间`) AS last_ok FROM `抓取运行日志` "
                "WHERE `是否成功` = 1 AND `目标` IN ('civil','institution','postgraduate')"
            )
            last = cur.fetchone()["last_ok"]
    finally:
        conn.close()
    return {
        "by_type": by_type,
        "last_success_at": last.isoformat(sep=" ") if hasattr(last, "isoformat") else last,
    }
