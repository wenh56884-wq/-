# scripts/seed_intent_demo.py
# 职责：为演示库补职业目标分布（非 2026 级学生），让教师端能看到四类人数
# 依赖：pymysql / app.config / engine.career_guide
# 说明：只补「尚未填写」的学生，不覆盖学生真实选择；2026 级大一保持未填写以演示先选目标

from __future__ import annotations

import argparse
import hashlib
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


def _intent_for(student_no: str) -> str:
    """按学号哈希确定性分配目标，避免与分班顺序/自增 id 产生共振。"""
    digest = hashlib.sha256(str(student_no).encode("utf-8")).hexdigest()
    return INTENTS[int(digest[:8], 16) % len(INTENTS)]


def seed(reset: bool = False) -> int:
    """为未填写目标的学生补演示数据，返回本次新增条数。

    reset=True 时先清掉非 2026 级的演示目标再重建，用于修正旧分布；
    默认不覆盖已有选择。
    """
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
            if reset:
                cur.execute(
                    "DELETE ci FROM career_intent ci "
                    "JOIN student s ON s.id = ci.student_id "
                    "WHERE ci.tenant_id = %s AND s.enroll_year <> %s",
                    (TENANT_ID, FRESHMAN_YEAR),
                )

            cur.execute(
                "SELECT id, student_no FROM student "
                "WHERE tenant_id = %s AND enroll_year <> %s ORDER BY id",
                (TENANT_ID, FRESHMAN_YEAR),
            )
            students = [(int(row[0]), str(row[1])) for row in cur.fetchall()]

            cur.execute(
                "SELECT student_id FROM career_intent WHERE tenant_id = %s",
                (TENANT_ID,),
            )
            existing = {int(row[0]) for row in cur.fetchall()}

            rows = [
                (TENANT_ID, student_id, _intent_for(student_no))
                for student_id, student_no in students
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
    parser = argparse.ArgumentParser(description="补齐职业目标演示数据")
    parser.add_argument("--reset", action="store_true",
                        help="先清空非 2026 级演示目标再重建（会覆盖这些学生的选择）")
    args = parser.parse_args()
    created = seed(reset=args.reset)
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
