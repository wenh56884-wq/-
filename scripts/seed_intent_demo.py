# scripts/seed_intent_demo.py
# 职责：为演示库补职业目标分布（非 2026 级学生），让教师端能看到四类人数
# 依赖：pymysql / app.config / engine.career_guide
# 说明：只补「尚未填写」的学生，不覆盖学生真实选择；2026 级大一保持未填写以演示先选目标

from __future__ import annotations

import sys
from pathlib import Path

import pymysql

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.config import get_settings  # noqa: E402
from engine.career_guide import INTENTS  # noqa: E402

TENANT_ID = 1
FRESHMAN_YEAR = 2026


def seed() -> int:
    """按学生 id 顺序确定性分配四类目标，返回本次新增条数。"""
    settings = get_settings()
    conn = pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=settings.mysql_db,
        charset="utf8mb4",
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM student "
                "WHERE tenant_id = %s AND enroll_year <> %s ORDER BY id",
                (TENANT_ID, FRESHMAN_YEAR),
            )
            student_ids = [int(row[0]) for row in cur.fetchall()]

            cur.execute(
                "SELECT student_id FROM career_intent WHERE tenant_id = %s",
                (TENANT_ID,),
            )
            existing = {int(row[0]) for row in cur.fetchall()}

            rows = [
                (TENANT_ID, student_id, INTENTS[index % len(INTENTS)])
                for index, student_id in enumerate(student_ids)
                if student_id not in existing
            ]
            if rows:
                cur.executemany(
                    "INSERT INTO career_intent (tenant_id, student_id, intent) "
                    "VALUES (%s, %s, %s)",
                    rows,
                )
            conn.commit()
            return len(rows)
    finally:
        conn.close()


def main() -> None:
    """入口：补数据并打印教师端会看到的分布。"""
    created = seed()
    settings = get_settings()
    conn = pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=settings.mysql_db,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT intent, COUNT(*) AS n FROM career_intent "
                "WHERE tenant_id = %s GROUP BY intent ORDER BY intent",
                (TENANT_ID,),
            )
            print(f"本次新增 {created} 条职业目标。当前分布：")
            for row in cur.fetchall():
                print(f"  {row['intent']}: {row['n']} 人")
            cur.execute(
                "SELECT COUNT(*) AS n FROM student "
                "WHERE tenant_id = %s AND enroll_year = %s",
                (TENANT_ID, FRESHMAN_YEAR),
            )
            print(f"  2026 级未填写（保留给“大一先选目标”演示）：{cur.fetchone()['n']} 人")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
