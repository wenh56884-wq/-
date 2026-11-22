# scripts/sync_recruit.py
# 职责：每天抓一次「招考公告 + 企业岗位」，增量入库，标注过期项。
#
# 用法：
#   .venv\Scripts\python.exe scripts\sync_recruit.py            # 抓全部（招考 + 岗位）
#   .venv\Scripts\python.exe scripts\sync_recruit.py --target exam
#   .venv\Scripts\python.exe scripts\sync_recruit.py --target job
#   .venv\Scripts\python.exe scripts\sync_recruit.py --dry-run  # 只抓不写
#   .venv\Scripts\python.exe scripts\sync_recruit.py --source cq-sydw --limit 5
#
# 设计：**只增不删**。抓不到的旧记录不删除，只在截止/有效期已过时把 status 置 closed，
# 保证「历年公告」「历史岗位」可查，学生能看到往年的分数线和要求。
#
# 两个 target：
#   exam → exam_notice  （考公 / 考编 / 考研，etl/recruit_fetch.py）
#   job  → recruit_job  （企业岗位，etl/job_fetch.py）

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pymysql

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.config import get_settings  # noqa: E402
from etl import job_fetch, recruit_fetch  # noqa: E402

TENANT_ID = 1

# 落库字段（与 db/recruit_tables.sql 的 招考公告 对应）
# _COLS 是「取值键」，保持英文：它同时用于从抓取结果 dict 里取值和拼 SQL。
_COLS = (
    "tenant_id", "exam_type", "source", "source_key", "title", "org_name", "region",
    "education_req", "degree_req", "major_req", "age_req", "political_req",
    "exp_req", "cert_req", "other_req", "headcount",
    "publish_date", "signup_start", "signup_end", "exam_date",
    "detail_url", "raw_text", "status",
)

# recruit_job 落库字段
_JOB_COLS = (
    "tenant_id", "source", "source_key", "title", "company", "industry",
    "city", "district", "salary_min", "salary_max", "education", "experience",
    "headcount", "skill_tags", "description", "apply_url",
    "published_at", "deadline", "status",
)

# 取值键 → 库中真实列名（中文）。同一个英文键在两张表里中文名可能不同
# （如 headcount：招考公告=招录人数，招聘岗位=招聘人数），所以分开两份。
_ZH_EXAM = {
    "tenant_id": "租户编号", "exam_type": "考试类型", "source": "来源",
    "source_key": "来源键", "title": "标题", "org_name": "招录单位",
    "region": "地区", "education_req": "学历要求", "degree_req": "学位要求",
    "major_req": "专业要求", "age_req": "年龄要求",
    "political_req": "政治面貌要求", "exp_req": "经历要求",
    "cert_req": "证书要求", "other_req": "其他要求", "headcount": "招录人数",
    "publish_date": "发布日期", "signup_start": "报名开始",
    "signup_end": "报名截止", "exam_date": "考试日期",
    "detail_url": "原文链接", "raw_text": "正文原文", "status": "状态",
}
_ZH_JOB = {
    "tenant_id": "租户编号", "source": "来源", "source_key": "来源键",
    "title": "岗位名称", "company": "招聘单位", "industry": "行业",
    "city": "城市", "district": "区县", "salary_min": "最低薪资",
    "salary_max": "最高薪资", "education": "学历要求", "experience": "经验要求",
    "headcount": "招聘人数", "skill_tags": "技能标签", "description": "职位描述",
    "apply_url": "投递链接", "published_at": "发布日期", "deadline": "截止日期",
    "status": "状态",
}


def _cols_sql(keys: tuple[str, ...], zh: dict[str, str]) -> str:
    """把取值键拼成中文列名列表（INSERT 的列清单）。"""
    return ", ".join(f"`{zh[k]}`" for k in keys)

# 每个字段的最大长度（与建表语句一致）；入库前统一截断，
# 避免「Data too long for column」把整轮同步打断。
_MAXLEN = {
    "exam_type": 20, "source": 40, "source_key": 32, "title": 300,
    "org_name": 200, "region": 60,
    "education_req": 200, "degree_req": 200, "major_req": 2000,
    "age_req": 200, "political_req": 200, "exp_req": 200,
    "cert_req": 200, "other_req": 2000,
    "detail_url": 500, "status": 10,
}

_JOB_MAXLEN = {
    "source": 40, "source_key": 32, "title": 200, "company": 200,
    "industry": 80, "city": 60, "district": 60,
    "education": 20, "experience": 30,
    "apply_url": 500, "status": 10,
}


def _connect():
    s = get_settings()
    return pymysql.connect(
        host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
        password=s.mysql_password, database=s.mysql_db, charset="utf8mb4",
        autocommit=True,
    )


def ensure_tables(conn) -> None:
    """建表（幂等）+ 必要字段扩容。

    让脚本可在全新库上直接跑，不依赖手工执行 sql 文件。
    已存在的旧表不会被 CREATE IF NOT EXISTS 改动，所以这里显式补 ALTER。
    """
    sql_file = _ROOT / "db" / "recruit_tables.sql"
    text = sql_file.read_text(encoding="utf-8")
    # 粗暴按分号切句，跳过纯注释块
    stmts: list[str] = []
    buf: list[str] = []
    for line in text.splitlines():
        if line.strip().startswith("--"):
            continue
        buf.append(line)
        if line.strip().endswith(";"):
            stmt = "\n".join(buf).strip().rstrip(";")
            if stmt:
                stmts.append(stmt)
            buf = []
    with conn.cursor() as cur:
        for stmt in stmts:
            cur.execute(stmt)
        # 旧表扩容（把早期 60 字的要求字段放宽到 200，列已存在则 ALTER 会报错，忽略）
        for col in ("education_req", "degree_req", "age_req",
                    "political_req", "exp_req", "cert_req"):
            try:
                cur.execute(
                    f"ALTER TABLE `招考公告` MODIFY `{_ZH_EXAM[col]}` VARCHAR(200) NULL"
                )
            except pymysql.MySQLError:
                pass


def upsert_notices(cur, rows: list[dict[str, Any]]) -> tuple[int, int]:
    """增量 upsert，返回 (新增, 更新)。

    用 INSERT ... ON DUPLICATE KEY UPDATE：已存在的只刷新「要求/时间线/状态」，
    不动 first_seen_at，这样能看出某条公告是哪个周首次进入系统的。
    """
    if not rows:
        return 0, 0
    cols = _cols_sql(_COLS, _ZH_EXAM)
    ph = ", ".join(["%s"] * len(_COLS))
    # 冲突时更新的列：除业务主键和 first_seen_at 外全刷
    upd_cols = [c for c in _COLS if c not in ("tenant_id", "source", "source_key")]
    upd = ", ".join(f"`{_ZH_EXAM[c]}`=VALUES(`{_ZH_EXAM[c]}`)" for c in upd_cols)
    sql = f"INSERT INTO `招考公告` ({cols}) VALUES ({ph}) ON DUPLICATE KEY UPDATE {upd}"

    inserted = 0
    updated = 0
    for r in rows:
        n = cur.execute(sql, _payload(r, _COLS, _MAXLEN))
        # MySQL: 1=插入, 2=更新, 0=无变化
        if n == 1:
            inserted += 1
        elif n == 2:
            updated += 1
    return inserted, updated


def close_expired(cur) -> int:
    """把报名截止日已过、但仍标为 open 的公告置为 closed。"""
    n = cur.execute(
        "UPDATE `招考公告` SET `状态`='closed' "
        "WHERE `租户编号`=%s AND `状态`='open' AND `报名截止` IS NOT NULL "
        "AND `报名截止` < CURDATE()",
        (TENANT_ID,),
    )
    return int(n or 0)


# ---------------------------------------------------------------- 企业岗位


def _payload(row: dict[str, Any], cols: tuple[str, ...], maxlen: dict[str, int]) -> list:
    """按列顺序拼入库值：租户号补上、超长截断、JSON 序列化。"""
    out = []
    for c in cols:
        v = TENANT_ID if c == "tenant_id" else row.get(c)
        if isinstance(v, str) and c in maxlen:
            v = v[:maxlen[c]]
        elif isinstance(v, (list, dict)):
            # skill_tags 是 JSON 列，pymysql 不会自动序列化 list
            v = json.dumps(v, ensure_ascii=False)
        out.append(v)
    return out


def upsert_jobs(cur, rows: list[dict[str, Any]]) -> tuple[int, int]:
    """岗位增量 upsert，返回 (新增, 更新)。

    与招考一致：冲突时只刷业务字段，不动 first_seen_at。
    last_seen_at 由 ON UPDATE CURRENT_TIMESTAMP 自动刷新 —— 「这周还抓得到」就是
    它在招的证据；连续多周抓不到的自然就停在旧时间，可用于后续下架判定。
    """
    if not rows:
        return 0, 0
    cols = _cols_sql(_JOB_COLS, _ZH_JOB)
    ph = ", ".join(["%s"] * len(_JOB_COLS))
    upd_cols = [c for c in _JOB_COLS if c not in ("tenant_id", "source", "source_key")]
    upd = ", ".join(f"`{_ZH_JOB[c]}`=VALUES(`{_ZH_JOB[c]}`)" for c in upd_cols)
    sql = f"INSERT INTO `招聘岗位` ({cols}) VALUES ({ph}) ON DUPLICATE KEY UPDATE {upd}"

    inserted = updated = 0
    for r in rows:
        n = cur.execute(sql, _payload(r, _JOB_COLS, _JOB_MAXLEN))
        if n == 1:
            inserted += 1
        elif n == 2:
            updated += 1
    return inserted, updated


def close_stale_jobs(cur, days: int = 21) -> int:
    """把「超过 N 天没再被抓到」的岗位标为 closed。

    招聘岗不给报名截止日，所以不能用 deadline 判。缺省 21 天：
    一个还在招的岗位，三周内总会在列表页重新出现一次；连续三周不见就是下线了。
    只用 last_seen_at 这一个可核对的事实，不做「推测已招满」。
    """
    n = cur.execute(
        "UPDATE `招聘岗位` SET `状态`='closed' "
        "WHERE `租户编号`=%s AND `状态`='open' "
        "AND `最近发现时间` < DATE_SUB(NOW(), INTERVAL %s DAY)",
        (TENANT_ID, int(days)),
    )
    return int(n or 0)


def sync_job_source(conn, source_id: str, *, dry_run: bool = False,
                    limit: int = 40, trigger: str = "manual") -> dict[str, Any]:
    """抓一个岗位源并入库。异常转成 ok=False，不影响其它源。"""
    try:
        rows = job_fetch.fetch_jobs(source_id, with_detail=True, limit=limit)
    except Exception as exc:
        if not dry_run and conn is not None:
            with conn.cursor() as cur:
                log_run(cur, "job", source_id, 0, 0, 0, 0, False,
                        f"{type(exc).__name__}: {exc}", trigger)
        return {"source": source_id, "fetched": 0, "inserted": 0, "updated": 0,
                "closed": 0, "ok": False, "err": str(exc)[:200]}

    if dry_run:
        return {"source": source_id, "fetched": len(rows), "inserted": 0,
                "updated": 0, "closed": 0, "ok": True, "err": None, "rows": rows}

    with conn.cursor() as cur:
        ins, upd = upsert_jobs(cur, rows)
        closed = close_stale_jobs(cur)
        log_run(cur, "job", source_id, len(rows), ins, upd, closed, True, None, trigger)
    return {"source": source_id, "fetched": len(rows), "inserted": ins,
            "updated": upd, "closed": closed, "ok": True, "err": None}


def log_run(cur, target: str, source: str, fetched: int, ins: int, upd: int,
            closed: int, ok: bool, err: str | None, trigger: str = "manual") -> None:
    cur.execute(
        "INSERT INTO `抓取运行日志` "
        "(`触发方式`, `目标`, `来源`, `抓取数`, `新增数`, `更新数`, `关闭数`, `是否成功`, `错误`) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (trigger, target, source, fetched, ins, upd, closed, 1 if ok else 0,
         (err or "")[:500] or None),
    )


def sync_source(conn, source_id: str, *, dry_run: bool = False,
                limit: int = 60, trigger: str = "manual") -> dict[str, Any]:
    """抓一个源并入库，返回统计。异常不抛出，转成 ok=False 的记录。

    dry_run=True 时 conn 允许为 None（只抓不写，也不记日志）。
    """
    cfg = recruit_fetch.SOURCES[source_id]
    try:
        rows = recruit_fetch.fetch_notices(source_id, with_detail=True, limit=limit)
    except Exception as exc:  # 断网 / 官网改版：记录失败，不影响其它源
        if not dry_run and conn is not None:
            with conn.cursor() as cur:
                log_run(cur, cfg["exam_type"], source_id, 0, 0, 0, 0, False,
                        f"{type(exc).__name__}: {exc}", trigger)
        return {"source": source_id, "fetched": 0, "inserted": 0, "updated": 0,
                "closed": 0, "ok": False, "err": str(exc)[:200]}

    if dry_run:
        return {"source": source_id, "fetched": len(rows), "inserted": 0,
                "updated": 0, "closed": 0, "ok": True, "err": None, "rows": rows}

    with conn.cursor() as cur:
        ins, upd = upsert_notices(cur, rows)
        closed = close_expired(cur)
        log_run(cur, cfg["exam_type"], source_id, len(rows), ins, upd, closed,
                True, None, trigger)
    return {"source": source_id, "fetched": len(rows), "inserted": ins,
            "updated": upd, "closed": closed, "ok": True, "err": None}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="招考公告 + 企业岗位 日更入库")
    ap.add_argument("--target", action="append", default=None,
                    choices=["exam", "job"],
                    help="抓哪类：exam=考公考编考研，job=企业岗位；可多次传，默认两类都抓")
    ap.add_argument("--source", action="append", default=None,
                    help=f"指定来源，可多次传；默认全部。招考：{', '.join(recruit_fetch.SOURCES)}；"
                         f"岗位：{', '.join(job_fetch.JOB_SOURCES)}")
    ap.add_argument("--limit", type=int, default=None,
                    help="每个源最多抓多少条（默认招考 60、岗位 40）")
    ap.add_argument("--dry-run", action="store_true", help="只抓不写库")
    ap.add_argument("--trigger", default="manual", help="触发方式（manual/schedule）")
    args = ap.parse_args(argv)

    targets = args.target or ["exam", "job"]
    exam_ids = list(recruit_fetch.SOURCES) if "exam" in targets else []
    job_ids = list(job_fetch.JOB_SOURCES) if "job" in targets else []

    # --source 要按 target 分流：给招考传 liepin-cq 是打错字，直接报错比静默 0 条好
    if args.source:
        unknown = [s for s in args.source if s not in recruit_fetch.SOURCES
                   and s not in job_fetch.JOB_SOURCES]
        if unknown:
            ap.error(f"未知来源：{', '.join(unknown)}")
        exam_ids = [s for s in args.source if s in recruit_fetch.SOURCES]
        job_ids = [s for s in args.source if s in job_fetch.JOB_SOURCES]

    exam_limit = args.limit or 60
    job_limit = args.limit or 40

    if args.dry_run:
        print("=" * 64)
        print("[dry-run] 只抓取，不写库")
        print("=" * 64)
        for sid in exam_ids:
            res = sync_source(None, sid, dry_run=True, limit=exam_limit)
            print(f"  [招考] {sid:12} {res['fetched']:>3} 条  ok={res['ok']}")
            for r in (res.get("rows") or [])[:2]:
                print(f"      · {r['title'][:50]}  ({r['publish_date']})")
        for sid in job_ids:
            res = sync_job_source(None, sid, dry_run=True, limit=job_limit)
            print(f"  [岗位] {sid:12} {res['fetched']:>3} 条  ok={res['ok']}")
            for r in (res.get("rows") or [])[:3]:
                print(f"      · {r['title'][:36]:38} {r['company'][:16]:18} "
                      f"{r['salary_min']}-{r['salary_max']}")
        return 0

    conn = _connect()
    try:
        ensure_tables(conn)
        print("=" * 64)
        print("招考公告 + 企业岗位 日更入库")
        print("=" * 64)
        total_ins = total_upd = total_fetched = total_closed = 0
        failed: list[str] = []

        def _report(res: dict[str, Any]) -> None:
            nonlocal total_fetched, total_ins, total_upd, total_closed
            flag = "OK " if res["ok"] else "FAIL"
            print(f"  [{flag}] {res['source']:12} 抓 {res['fetched']:>3} · "
                  f"新增 {res['inserted']:>3} · 更新 {res['updated']:>3} · "
                  f"截止 {res['closed']:>3}"
                  + (f"  ({res['err'][:60]})" if res["err"] else ""))
            total_fetched += res["fetched"]
            total_ins += res["inserted"]
            total_upd += res["updated"]
            total_closed += res["closed"]
            if not res["ok"]:
                failed.append(res["source"])

        if exam_ids:
            print("\n-- 招考公告（考公 / 考编 / 考研）--")
            for sid in exam_ids:
                _report(sync_source(conn, sid, limit=exam_limit, trigger=args.trigger))
        if job_ids:
            print("\n-- 企业岗位 --")
            for sid in job_ids:
                _report(sync_job_source(conn, sid, limit=job_limit, trigger=args.trigger))

        with conn.cursor() as cur:
            cur.execute(
                "SELECT `考试类型`, COUNT(*) AS n, SUM(`状态`='open') AS open_n "
                "FROM `招考公告` WHERE `租户编号`=%s GROUP BY `考试类型` ORDER BY `考试类型`",
                (TENANT_ID,),
            )
            print()
            print("招考库内现状：")
            for row in cur.fetchall():
                print(f"  {row[0]:14} 共 {row[1]:>4} 条，其中在招 {row[2] or 0:>4} 条")

            cur.execute(
                "SELECT COUNT(*) AS n, SUM(`状态`='open') AS open_n, "
                "       COUNT(DISTINCT `招聘单位`) AS firms "
                "FROM `招聘岗位` WHERE `租户编号`=%s",
                (TENANT_ID,),
            )
            row = cur.fetchone()
            print(f"岗位库内现状：共 {row[0]} 条，在招 {row[1] or 0} 条，"
                  f"涉及 {row[2]} 家单位")

        print()
        print(f"合计：抓取 {total_fetched} · 新增 {total_ins} · 更新 {total_upd} · "
              f"标记截止 {total_closed}")
        if failed:
            print(f"失败源：{', '.join(failed)}（详见 recruit_sync_log）")
            return 1
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
