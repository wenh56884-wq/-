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

    where = ["tenant_id = %s"]
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
