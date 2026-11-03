# scripts/seed_assessment.py
# 职责：把 engine/assessment_bank.py 的题库灌入「测评题目」表
# 依赖：pymysql / app.config（读 .env）/ engine.assessment_bank（题库唯一真相源）
# 说明：幂等——表内已有题目时默认跳过，--reset 先清空重灌
# 用法：.venv\Scripts\python.exe scripts\seed_assessment.py [--reset]

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pymysql  # noqa: E402

from app.config import get_settings  # noqa: E402
from engine.assessment_bank import ASSESSMENT_BANK_VERSION, build_questions  # noqa: E402


def _connect() -> pymysql.connections.Connection:
    s = get_settings()
    return pymysql.connect(host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
                           password=s.mysql_password, database=s.mysql_db,
                           charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)


def ensure_tables(conn: pymysql.connections.Connection) -> None:
    """执行 db/assessment_tables.sql（幂等），确保两张表存在。"""
    sql_path = _ROOT / "db" / "assessment_tables.sql"
    raw = sql_path.read_text(encoding="utf-8")
    # 去掉整行注释（-- 开头），再按分号拆成语句逐个执行
    raw = re.sub(r"(?m)^\s*--.*$", "", raw)
    with conn.cursor() as cur:
        for stmt in raw.split(";"):
            stmt = stmt.strip()
            if stmt:
                cur.execute(stmt)
    conn.commit()


def main() -> None:
    reset = "--reset" in sys.argv
    qs = build_questions()

    conn = _connect()
    try:
        ensure_tables(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM `测评题目`")
            existing = int(cur.fetchone()["n"])
            if existing > 0 and not reset:
                print(f"题库已有 {existing} 题，跳过（--reset 可清空重灌）")
                return
            if reset:
                cur.execute("DELETE FROM `测评题目`")
                print(f"已清空原 {existing} 题")

            for idx, q in enumerate(qs, start=1):
                cur.execute(
                    "INSERT INTO `测评题目` (`类别`,`维度`,`题面`,`选项`,`选项分值`,`排序`) "
                    "VALUES (%s,%s,%s,%s,%s,%s)",
                    (q["category"], q["dimension"], q["content"],
                     json.dumps(q["options"], ensure_ascii=False),
                     json.dumps(q["scoring"], ensure_ascii=False),
                     idx),
                )
            conn.commit()
            print(f"灌入 {len(qs)} 道测评题（{ASSESSMENT_BANK_VERSION}）")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
