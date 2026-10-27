# app/routers/job.py
# 职责：企业岗位查询 API（全国职业岗位），数据由 scripts/sync_recruit.py 周更入库。
#
# 设计：
# - 纯只读接口；每条都带 apply_url + published_at，可点开原文核对。
# - 薪资/学历/人数可能为 None（站点没写），前端必须显示「未标注」，
#   不能显示成 0 或「不限」——**缺失不冒充**。
#   注意区别：「学历不限」是真信息（该岗不卡学历），「education is None」是没抓到。
# - 默认只返回在招岗位；要查已下架的历史岗位用 include_closed=true。
# - 这是「搜索」，不是「推荐」：按关键词/条件筛，不碰画像评分（推荐在 /career 里）。

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/job", tags=["岗位"])


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


def _dec(v: Any) -> float | None:
    """DECIMAL → float；None 保持 None（不能变 0.0）。"""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _row_to_dict(row: dict[str, Any], *, full: bool = False) -> dict[str, Any]:
    """统一输出结构；日期转 ISO，缺失保持 None，并显式标注哪些字段未标注。"""
    out = dict(row)
    for k in ("published_at", "deadline"):
        v = out.get(k)
        out[k] = v.isoformat() if hasattr(v, "isoformat") else v
    for k in ("first_seen_at", "last_seen_at"):
        v = out.get(k)
        out[k] = v.isoformat(sep=" ") if hasattr(v, "isoformat") else v
    out["salary_min"] = _dec(out.get("salary_min"))
    out["salary_max"] = _dec(out.get("salary_max"))
    out["salary_text"] = _salary_text(out["salary_min"], out["salary_max"])

    # 技能标签是 JSON 列，MySQL 可能回字符串
    tags = out.get("skill_tags")
    if isinstance(tags, str):
        import json
        try:
            tags = json.loads(tags)
        except (ValueError, TypeError):
            tags = None
    out["skill_tags"] = tags or []

    # 显式告诉前端「这些是真没抓到」，避免被渲染成「不限」
    out["missing_fields"] = [
        k for k in ("salary_min", "education", "experience", "headcount", "company")
        if out.get(k) in (None, "")
    ]
    if not full:
        out.pop("description", None)
    return out


def _salary_text(lo: float | None, hi: float | None) -> str | None:
    """人读薪资文案；两者都未知时返回 None（前端显示「薪资未标注」）。"""
    if lo is None and hi is None:
        return None
    if lo is not None and hi is None:
        return f"{lo / 1000:.0f}K 起"
    if lo is None and hi is not None:
        return f"最高 {hi / 1000:.0f}K"
    return f"{lo / 1000:.0f}-{hi / 1000:.0f}K"


@router.get("/list")
def list_jobs(
    keyword: str | None = Query(default=None, max_length=60, description="岗位名/单位关键词"),
    city: str | None = Query(default=None, max_length=40, description="城市，如 重庆"),
    industry: str | None = Query(default=None, max_length=40, description="行业关键词"),
    education: str | None = Query(default=None, max_length=20, description="学历，如 本科"),
    salary_min: int | None = Query(default=None, ge=0, description="月薪下限（元）"),
    include_closed: bool = Query(default=False, description="是否包含已下架岗位"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """按条件分页查岗位。"""
    where = ["`租户编号` = %s"]
    params: list[Any] = [1]
    if keyword:
        # 岗位名或单位名命中都算（学生常按公司搜）
        where.append("(`岗位名称` LIKE %s OR `招聘单位` LIKE %s)")
        params += [f"%{keyword}%", f"%{keyword}%"]
    if city:
        where.append("`城市` LIKE %s")
        params.append(f"%{city}%")
    if industry:
        where.append("`行业` LIKE %s")
        params.append(f"%{industry}%")
    if education:
        where.append("`学历要求` LIKE %s")
        params.append(f"%{education}%")
    if salary_min:
        # 只要「该岗上限能达到」就算匹配；上限未知的岗不能因为 unknown 被筛掉，
        # 否则会系统性漏掉「面议」的高薪岗。这里只按已知上限判。
        where.append("(`最高薪资` IS NULL OR `最高薪资` >= %s)")
        params.append(salary_min)
    if not include_closed:
        where.append("`状态` <> 'closed'")

    cond = " AND ".join(where)
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS n FROM `招聘岗位` WHERE {cond}", params)
            total = int(cur.fetchone()["n"])
            cur.execute(
                "SELECT `编号` AS id, `来源` AS source, `岗位名称` AS title, "
                "`招聘单位` AS company, `行业` AS industry, `城市` AS city, "
                "`区县` AS district, `最低薪资` AS salary_min, `最高薪资` AS salary_max, "
                "`学历要求` AS education, `经验要求` AS experience, "
                "`招聘人数` AS headcount, `技能标签` AS skill_tags, "
                "`投递链接` AS apply_url, `发布日期` AS published_at, "
                "`截止日期` AS deadline, `状态` AS status, "
                "`首次发现时间` AS first_seen_at, `最近发现时间` AS last_seen_at, "
                "LEFT(`职位描述`, 200) AS description "
                f"FROM `招聘岗位` WHERE {cond} "
                "ORDER BY (`发布日期` IS NULL), `发布日期` DESC, `编号` DESC "
                "LIMIT %s OFFSET %s",
                [*params, page_size, (page - 1) * page_size],
            )
            rows = [_row_to_dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

    return {"total": total, "page": page, "page_size": page_size, "items": rows}


@router.get("/list/{job_id}")
def get_job(job_id: int) -> dict[str, Any]:
    """单条岗位详情（含完整 JD）。"""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT `编号` AS id, `来源` AS source, `岗位名称` AS title, "
                "`招聘单位` AS company, `行业` AS industry, `城市` AS city, "
                "`区县` AS district, `最低薪资` AS salary_min, `最高薪资` AS salary_max, "
                "`学历要求` AS education, `经验要求` AS experience, "
                "`招聘人数` AS headcount, `技能标签` AS skill_tags, "
                "`职位描述` AS description, `投递链接` AS apply_url, "
                "`发布日期` AS published_at, `截止日期` AS deadline, `状态` AS status, "
                "`首次发现时间` AS first_seen_at, `最近发现时间` AS last_seen_at "
                "FROM `招聘岗位` WHERE `编号` = %s AND `租户编号` = %s",
                (job_id, 1),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="岗位不存在")
    return _row_to_dict(row, full=True)


@router.get("/stats")
def stats() -> dict[str, Any]:
    """岗位总量、在招量、覆盖城市/行业，以及最后一次成功抓取时间。"""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS n, SUM(`状态`='open') AS open_n, "
                "       COUNT(DISTINCT `招聘单位`) AS firms, "
                "       COUNT(DISTINCT `城市`) AS cities, "
                "       COUNT(DISTINCT `行业`) AS industries "
                "FROM `招聘岗位` WHERE `租户编号`=%s",
                (1,),
            )
            r = cur.fetchone()
            cur.execute(
                "SELECT MAX(`运行时间`) AS last_ok FROM `抓取运行日志` "
                "WHERE `是否成功` = 1 AND `目标` = 'job'"
            )
            last = cur.fetchone()["last_ok"]
            cur.execute(
                "SELECT `行业` AS industry, COUNT(*) AS n FROM `招聘岗位` "
                "WHERE `租户编号`=%s AND `行业` IS NOT NULL "
                "GROUP BY `行业` ORDER BY n DESC LIMIT 8",
                (1,),
            )
            top_ind = [{"industry": x["industry"], "total": int(x["n"])}
                       for x in cur.fetchall()]
    finally:
        conn.close()
    return {
        "total": int(r["n"]),
        "open": int(r["open_n"] or 0),
        "companies": int(r["firms"] or 0),
        "cities": int(r["cities"] or 0),
        "industries": int(r["industries"] or 0),
        "top_industries": top_ind,
        "last_success_at": last.isoformat(sep=" ") if hasattr(last, "isoformat") else last,
    }
