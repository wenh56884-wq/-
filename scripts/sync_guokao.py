# scripts/sync_guokao.py
# 职责：下载/解析国家公务员局《招考简章》职位表，增量 upsert 进 `国考职位` 表并记运行日志。
# 依赖：pymysql / etl.exam_positions / app.config / xlrd
# 用法：
#   .venv\Scripts\python.exe scripts\sync_guokao.py --year 2027
#   .venv\Scripts\python.exe scripts\sync_guokao.py --year 2027 --dry-run
#   .venv\Scripts\python.exe scripts\sync_guokao.py --year 2027 --file data\raw\guokao\2027\招考简章.zip
#
# 设计：只增改不删；同一 (年度, 部门代码, 职位代码) 重复抓只刷新内容，不产生重复行。

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.config import get_settings  # noqa: E402
from etl import exam_positions  # noqa: E402

# 记录键 → 库中中文列名（与 db/guokao_positions.sql 对应）
_ZH = {
    "tenant_id": "租户编号", "year": "年度", "source": "来源", "source_key": "来源键",
    "category": "简章分类", "dept_code": "部门代码", "dept_name": "部门名称",
    "bureau": "用人司局", "org_nature": "机构性质", "position_name": "招考职位",
    "position_attr": "职位属性", "position_dist": "职位分布", "intro": "职位简介",
    "position_code": "职位代码", "org_level": "机构层级",
    "exam_category": "考试类别", "headcount": "招考人数", "major": "专业",
    "education": "学历", "degree": "学位", "political": "政治面貌",
    "work_years": "基层工作最低年限", "grassroots_project": "服务基层项目工作经历",
    "pro_test": "是否组织专业能力测试", "interview_ratio": "面试人员比例",
    "work_place": "工作地点", "settle_place": "落户地点", "remark": "备注",
    "dept_site": "部门网站", "phone1": "咨询电话1", "phone2": "咨询电话2",
    "phone3": "咨询电话3", "notice_url": "公告链接", "data_file": "数据文件",
}
_COLS = tuple(_ZH)
_BATCH = 500


def _connect():
    s = get_settings()
    import pymysql

    return pymysql.connect(
        host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
        password=s.mysql_password, database=s.mysql_db, charset="utf8mb4",
        autocommit=True, cursorclass=pymysql.cursors.DictCursor,
    )


def _split_sql(text: str) -> list[str]:
    """按分号切 SQL，丢掉纯注释与空句（与 sync_recruit.ensure_tables 同口径）。"""
    lines = [ln for ln in text.splitlines() if not ln.strip().startswith("--")]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]


def ensure_schema(conn) -> None:
    """建 `国考职位` 表；运行日志表从 recruit_tables.sql 里单独取建表句。"""
    with conn.cursor() as cur:
        for stmt in _split_sql((_ROOT / "db" / "guokao_positions.sql")
                               .read_text(encoding="utf-8")):
            cur.execute(stmt)
        recruit_sql = (_ROOT / "db" / "recruit_tables.sql").read_text(encoding="utf-8")
        for stmt in _split_sql(recruit_sql):
            if "`抓取运行日志`" in stmt:
                cur.execute(stmt)


def _dedupe(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """同一来源键只保留最后一条，避免同批 INSERT 里重复主键。"""
    by_key: dict[str, dict[str, Any]] = {}
    for rec in records:
        by_key[str(rec["source_key"])] = rec
    return list(by_key.values())


def _existing_keys(cur, tenant_id: int, year: int) -> set[str]:
    cur.execute(
        "SELECT `来源键` FROM `国考职位` WHERE `租户编号` = %s AND `年度` = %s",
        (tenant_id, year),
    )
    return {str(row["来源键"]) for row in cur.fetchall()}


def upsert_positions(conn, records: list[dict[str, Any]], tenant_id: int) -> tuple[int, int]:
    """批量 upsert，返回 (新增, 更新)。行数按入库前已存在的来源键判定。"""
    records = _dedupe(records)
    if not records:
        return 0, 0
    year = int(records[0]["year"])
    with conn.cursor() as cur:
        existing = _existing_keys(cur, tenant_id, year)
        cols = ", ".join(f"`{_ZH[c]}`" for c in _COLS)
        row_ph = "(" + ", ".join(["%s"] * len(_COLS)) + ")"
        upd_cols = [c for c in _ZH
                    if c not in ("tenant_id", "year", "source", "source_key")]
        upd = ", ".join(f"`{_ZH[c]}`=VALUES(`{_ZH[c]}`)" for c in upd_cols)
        upd += ", `最近发现时间`=CURRENT_TIMESTAMP"
        for start in range(0, len(records), _BATCH):
            batch = records[start:start + _BATCH]
            sql = (f"INSERT INTO `国考职位` ({cols}) VALUES "
                   + ", ".join([row_ph] * len(batch))
                   + f" ON DUPLICATE KEY UPDATE {upd}")
            params: list[Any] = []
            for rec in batch:
                params.extend(tenant_id if c == "tenant_id" else rec.get(c)
                              for c in _ZH)
            cur.execute(sql, params)
    inserted = sum(1 for r in records if str(r["source_key"]) not in existing)
    return inserted, len(records) - inserted


def log_run(conn, *, year: int, fetched: int, inserted: int, updated: int,
            ok: bool, error: str = "", trigger: str = "manual") -> None:
    """写一条抓取运行日志（失败也要写，便于前端看数据新鲜度）。

    trigger：manual（命令行）/ schedule（后台守护线程）/ api（接口触发）。
    """
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO `抓取运行日志` (`触发方式`, `目标`, `来源`, `抓取数`, "
            "`新增数`, `更新数`, `关闭数`, `是否成功`, `错误`) "
            "VALUES (%s, 'guokao', %s, %s, %s, %s, 0, %s, %s)",
            (trigger, f"scs-gk-{year}", fetched, inserted, updated,
             1 if ok else 0, error[:500] or None),
        )


def print_summary(records: list[dict[str, Any]], source: str) -> None:
    """dry-run / 正常同步都打印口径：职位数、人数、分类分布、前 5 部门。"""
    total_people = sum(int(r.get("headcount") or 0) for r in records)
    by_category: dict[str, int] = {}
    by_dept: dict[str, int] = {}
    for rec in records:
        by_category[str(rec.get("category") or "未分类")] = (
            by_category.get(str(rec.get("category") or "未分类"), 0) + 1)
        by_dept[str(rec.get("dept_name") or "未标注")] = (
            by_dept.get(str(rec.get("dept_name") or "未标注"), 0) + 1)
    print(f"来源文件：{source}")
    print(f"解析职位：{len(records)} 个，招录人数合计：{total_people} 人")
    print("分类分布：" + "、".join(f"{k} {v} 个" for k, v in by_category.items()))
    top = sorted(by_dept.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
    print("职位数前 5 部门：" + "、".join(f"{k} {v} 个" for k, v in top))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="同步国考职位表到 MySQL")
    parser.add_argument("--year", type=int, default=2027, help="考试年度，默认 2027")
    parser.add_argument("--file", type=Path, default=None,
                        help="本地 zip/xls 路径；不传则下载官方《招考简章》")
    parser.add_argument("--url", default=None, help="自定义官方下载地址（未知年度用）")
    parser.add_argument("--tenant", type=int, default=1, help="租户编号，默认 1")
    parser.add_argument("--dry-run", action="store_true", help="只解析打印，不写库")
    parser.add_argument("--trigger", default="manual",
                        choices=("manual", "schedule", "api"),
                        help="运行日志里的触发方式，默认 manual")
    args = parser.parse_args(argv)

    year = int(args.year)
    source_path = args.file
    try:
        if source_path is None:
            dest_dir = _ROOT / "data" / "raw" / "guokao" / str(year)
            source_path = exam_positions.download_positions(year, dest_dir, url=args.url)
            print(f"已下载：{source_path}")
        records = exam_positions.load_from_path(Path(source_path), year)
    except Exception as exc:  # 下载/解析失败：如实打印，写失败日志，返回非零
        print(f"[失败] {type(exc).__name__}: {exc}", file=sys.stderr)
        try:
            conn = _connect()
            try:
                ensure_schema(conn)
                log_run(conn, year=year, fetched=0, inserted=0, updated=0,
                        ok=False, error=f"{type(exc).__name__}: {exc}",
                        trigger=args.trigger)
            finally:
                conn.close()
        except Exception as log_exc:  # 连库都不可用时只提示，不掩盖原始错误
            print(f"[警告] 失败日志未写入：{type(log_exc).__name__}: {log_exc}",
                  file=sys.stderr)
        return 1

    print_summary(records, str(source_path))
    if args.dry_run:
        print("dry-run：未写库。")
        return 0

    conn = _connect()
    try:
        ensure_schema(conn)
        inserted, updated = upsert_positions(conn, records, int(args.tenant))
        log_run(conn, year=year, fetched=len(records), inserted=inserted,
                updated=updated, ok=True, trigger=args.trigger)
    finally:
        conn.close()

    print(f"入库完成：新增 {inserted} 条，更新 {updated} 条，"
          f"合计 {inserted + updated} 条（租户 {args.tenant}，年度 {year}）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
