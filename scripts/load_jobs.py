# scripts/load_jobs.py
# 职责：调用 etl.clean_jobs 清洗 → 灌入 MySQL job 表 + DuckDB job_feature 表
# 依赖：pymysql / duckdb / pandas / etl.clean_jobs / app.config
# 说明：INSERT IGNORE 防重灌（raw_key 唯一键），全流程 ≤30 秒

from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb
import pymysql
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.config import get_settings
from etl.clean_jobs import clean_all, save_cleaned

_CALC_VERSION = "v1"


def load_to_mysql(df: pd.DataFrame, settings) -> tuple[int, int]:
    """灌入 MySQL job 表（INSERT IGNORE），返回 (inserted, skipped)。"""
    conn = pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        db=settings.mysql_db,
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        cur = conn.cursor()
        # 先清空旧数据（幂等）
        cur.execute("TRUNCATE TABLE job")
        inserted = 0
        skipped = 0
        rows = []
        for _, r in df.iterrows():
            skill_tags = r["skill_tags"]
            if isinstance(skill_tags, str):
                skill_tags = [t for t in skill_tags.split(";") if t]
            benefits = r["benefits"]
            if isinstance(benefits, str):
                benefits = [t for t in benefits.split(";") if t]
            rows.append((
                r["title"], r["company"], r["industry"], r["company_size"],
                r["city"], r["district"],
                float(r["salary_min"]), float(r["salary_max"]),
                r["salary_unit"], r["salary_months"] if pd.notna(r["salary_months"]) else None,
                int(r["exp_min"]), int(r["exp_max"]), r["education"],
                json.dumps(skill_tags, ensure_ascii=False),
                json.dumps(benefits, ensure_ascii=False),
                r["description"], r["source"], r["raw_key"], None,
            ))
        sql = (
            "INSERT IGNORE INTO job "
            "(title, company, industry, company_size, city, district, "
            "salary_min, salary_max, salary_unit, salary_months, "
            "exp_min, exp_max, education, skill_tags, benefits, "
            "description, source, raw_key, published_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
        )
        cur.executemany(sql, rows)
        inserted = cur.rowcount
        skipped = len(rows) - inserted
        return inserted, skipped
    finally:
        conn.close()


def load_to_duckdb(df: pd.DataFrame, settings) -> int:
    """灌入 DuckDB job_feature 表，返回插入行数。"""
    db_path = settings.duckdb_path_obj
    conn = duckdb.connect(str(db_path))
    try:
        # 先清空
        conn.execute("DELETE FROM job_feature")
        records = []
        for _, r in df.iterrows():
            skill_tags = r["skill_tags"]
            if isinstance(skill_tags, str):
                skill_tags = [t for t in skill_tags.split(";") if t]
            records.append((
                r["title"], r["city"],
                float(r["salary_min"]), float(r["salary_max"]),
                r["education"], int(r["exp_min"]), int(r["exp_max"]),
                json.dumps(skill_tags, ensure_ascii=False),
                r["source"], _CALC_VERSION,
            ))
        conn.executemany(
            "INSERT INTO job_feature "
            "(title, city, salary_min, salary_max, education, exp_min, exp_max, "
            "skill_tags, source, calc_version) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            records,
        )
        return len(records)
    finally:
        conn.close()


def show_city_counts(settings) -> None:
    """打印 MySQL job 表按城市分组统计。"""
    conn = pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        db=settings.mysql_db,
        charset="utf8mb4",
    )
    try:
        cur = conn.cursor()
        cur.execute("SELECT city, COUNT(*) FROM job GROUP BY city ORDER BY COUNT(*) DESC")
        print("\n=== MySQL job 表城市分布 ===")
        for row in cur.fetchall():
            print(f"  {row[0]}: {row[1]}")
    finally:
        conn.close()


def show_samples(df: pd.DataFrame, n: int = 5) -> None:
    """随机抽 n 条清洗后数据展示。"""
    import random
    rng = random.Random(42)
    indices = rng.sample(range(len(df)), min(n, len(df)))
    print("\n=== 随机抽取 5 条清洗后数据 ===")
    for i, idx in enumerate(indices, 1):
        r = df.iloc[idx]
        print(f"\n[{i}] {r['title']} | {r['company']} | {r['city']}")
        print(f"    薪资: {r['salary_min']}-{r['salary_max']} {r['salary_unit']}"
              + (f"·{int(r['salary_months'])}薪" if pd.notna(r['salary_months']) else ""))
        print(f"    经验: {r['exp_min']}-{r['exp_max']}年 | 学历: {r['education']}")
        print(f"    来源: {r['source']}")


def main() -> None:
    print("=== 步骤 1: 清洗 data/raw/ 下 5 个招聘 CSV ===")
    df, stats = clean_all()

    total_in = sum(s["input"] for s in stats)
    total_out = sum(s["output"] for s in stats)
    total_drop = sum(s["dropped"] for s in stats)
    rate = (total_in - total_drop) / total_in * 100 if total_in else 0

    print(f"\n汇总: {total_in} -> {len(df)} (drop {total_drop})")
    print(f"薪资解析成功率: {rate:.1f}%")

    print("\n=== 步骤 2: 保存清洗结果 ===")
    out_path = save_cleaned(df)
    print(f"  输出: {out_path} ({len(df)} 行)")

    print("\n=== 步骤 3: 灌入 MySQL job 表 ===")
    settings = get_settings()
    inserted, skipped = load_to_mysql(df, settings)
    print(f"  MySQL: inserted={inserted}, skipped(dup)={skipped}")

    print("\n=== 步骤 4: 灌入 DuckDB job_feature 表 ===")
    n_duck = load_to_duckdb(df, settings)
    print(f"  DuckDB: {n_duck} 行")

    # 验收
    show_city_counts(settings)
    show_samples(df)


if __name__ == "__main__":
    main()
