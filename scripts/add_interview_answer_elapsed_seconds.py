# scripts/add_interview_answer_elapsed_seconds.py
# 职责：幂等补列——给 `面试问答` 增加「用时秒」INT NULL，供单题用时落库（前端回传）。
# 用法：手动执行；应用启动时不自动跑，列已存在则直接跳过，不重复 ALTER。

from __future__ import annotations

import pymysql

from app.config import get_settings


def _column_exists(cur, table: str, column: str) -> bool:
    cur.execute(
        "SELECT COUNT(*) AS n FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND COLUMN_NAME=%s",
        (table, column))
    row = cur.fetchone() or {}
    return int(row.get("n") or 0) > 0


def main() -> None:
    settings = get_settings()
    conn = pymysql.connect(
        host=settings.mysql_host, port=settings.mysql_port,
        user=settings.mysql_user, password=settings.mysql_password,
        database=settings.mysql_db, charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor)
    try:
        with conn.cursor() as cur:
            if _column_exists(cur, "面试问答", "用时秒"):
                print("`面试问答`.`用时秒` 已存在，跳过")
                return
            cur.execute(
                "ALTER TABLE `面试问答` ADD COLUMN `用时秒` INT NULL "
                "COMMENT '单题用时（秒，前端回传）' AFTER `创建时间`")
        conn.commit()
        print("已添加 `面试问答`.`用时秒` INT NULL")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
