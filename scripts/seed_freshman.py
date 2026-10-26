# scripts/seed_freshman.py
# 职责：幂等插入 2026 级大一新生演示账号（用于“大一先选目标”页面）
# 依赖：pymysql / app.config；不依赖 FastAPI 服务
# 说明：口令沿用演示约定「学号即初始口令」；同时补确定性成绩/考勤，便于教师端按班查看

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pymysql

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.config import get_settings  # noqa: E402

TENANT_ID = 1
# 与现有演示数据保持同一学期，保证教师端默认查询能看到这些学生
TERM = "2025-2026-2"

# 四个学院各放一名，方便演示不同专业的大一新生。
#
# class_name 故意不写：2026 级只有这 4 个人，单独编班就会冒出「AI2601 1 人」
# 这种班级，教师端班级概览里只有一个学生、预警列表只可能一条，看着像 bug。
# 改成运行时并入**该学院人数最多的现有班**，让他们混在正常班级里演示。
FRESHMEN: tuple[dict[str, str], ...] = (
    {"student_no": "AI2026001", "name": "林一",
     "college": "讯飞人工智能学院", "major": "数据科学与大数据技术"},
    {"student_no": "RJ2026001", "name": "周航",
     "college": "软件学院", "major": "软件工程"},
    {"student_no": "KJ2026001", "name": "陈欣",
     "college": "会计学院", "major": "会计学"},
    {"student_no": "JR2026001", "name": "唐悦",
     "college": "金融学院", "major": "金融学"},
)


def _resolve_class(cur, college: str) -> str:
    """取该学院人数最多的现有班级，用于安置大一演示账号。

    学院一个班都没有时（空库直接跑本脚本）兜底成「学院缩写 + 2601」，
    不抛异常 —— 这个脚本只负责演示账号，不该阻断初始化流程。
    """
    cur.execute(
        "SELECT class_name, COUNT(*) AS n FROM student "
        "WHERE tenant_id = %s AND college = %s AND class_name IS NOT NULL "
        "AND class_name <> '' GROUP BY class_name ORDER BY n DESC, class_name LIMIT 1",
        (TENANT_ID, college),
    )
    row = cur.fetchone()
    if row and row[0]:
        return str(row[0])
    abbr = {"讯飞人工智能学院": "AI", "软件学院": "RJ",
            "会计学院": "KJ", "金融学院": "JR"}.get(college, "XX")
    return f"{abbr}2601"


def _legacy_hash(account: str) -> str:
    """与 scripts/seed_mock.py 一致的演示口令摘要（口令=学号）。"""
    return hashlib.sha256(f"qihang_{account}".encode()).hexdigest()[:32]


def _seed_learning(cur, student_id: int, major: str) -> None:
    """给大一演示账号补一份确定性的成绩/考勤，避免教师端班级名单为空。

    只在该生该学期没有任何成绩时写入；数值固定，不引入随机数。
    """
    cur.execute("SELECT COUNT(*) AS n FROM score WHERE student_id = %s AND term = %s",
                (student_id, TERM))
    if int(cur.fetchone()[0] or 0) > 0:
        return
    cur.execute("SELECT id FROM course WHERE major = %s ORDER BY id LIMIT 6", (major,))
    course_ids = [int(row[0]) for row in cur.fetchall()]
    if not course_ids:
        return
    for index, course_id in enumerate(course_ids):
        score = 82 + (index * 3) % 12
        cur.execute(
            "INSERT INTO score (student_id, course_id, term, score, is_retake) "
            "VALUES (%s, %s, %s, %s, 0)",
            (student_id, course_id, TERM, score),
        )
    cur.execute(
        "INSERT INTO attendance "
        "(student_id, term, total_sessions, absent_sessions, attendance_rate) "
        "VALUES (%s, %s, 20, 0, 1.0)",
        (student_id, TERM),
    )


def seed() -> int:
    """插入缺失的大一账号，返回本次新增条数。"""
    settings = get_settings()
    conn = pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=settings.mysql_db,
        charset="utf8mb4",
    )
    created = 0
    try:
        with conn.cursor() as cur:
            for item in FRESHMEN:
                class_name = _resolve_class(cur, item["college"])
                item["class_name"] = class_name  # 回填给 main 打印
                cur.execute(
                    "INSERT IGNORE INTO student "
                    "(tenant_id, student_no, name, college, major, class_name, "
                    " grade, enroll_year, password_hash) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        TENANT_ID, item["student_no"], item["name"], item["college"],
                        item["major"], class_name, "2026", 2026,
                        _legacy_hash(item["student_no"]),
                    ),
                )
                created += int(cur.rowcount or 0)
                # 已存在的老数据也纠正班级：历史版本给 2026 级单独编过班
                # （AI2601 之类 1 人班），这里统一并入该学院的正常班。
                cur.execute(
                    "UPDATE student SET class_name = %s WHERE student_no = %s",
                    (class_name, item["student_no"]),
                )
                cur.execute("SELECT id FROM student WHERE student_no = %s",
                            (item["student_no"],))
                row = cur.fetchone()
                if row:
                    _seed_learning(cur, int(row[0]), item["major"])
        conn.commit()
    finally:
        conn.close()
    return created


def main() -> None:
    """入口：打印新增/已存在结果与登录提示。"""
    created = seed()
    print(f"大一演示账号：新增 {created} 个，已存在 {len(FRESHMEN) - created} 个。")
    for item in FRESHMEN:
        print(f"  {item['student_no']}  {item['name']}  {item['class_name']}  "
              f"（初始口令 = 学号）")
    print(f"已补齐 {TERM} 的演示成绩/考勤（无随机数）；如需画像，再运行：")
    print("  python scripts\\build_profile_raw.py --term 2025-2026-2")


if __name__ == "__main__":
    main()
