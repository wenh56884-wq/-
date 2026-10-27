# scripts/seed_demo_coverage.py
# 职责：补齐演示库的空表/稀疏表——预警阈值、班级覆盖、通知已读水位、学生扩展信息、目标对齐。
# 依赖：pymysql / app.config；幂等执行，不覆盖已有学生选择。
# 说明：只补缺失不删数据；扩展信息按学号哈希确定性生成，可重复运行。

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
DEMO_STUDENT_NO = "AI20230001"
DEMO_CLASS = "AI2301"

# (指标, 权重, 黄色阈值, 橙色阈值, 红色阈值)；与 engine/rules.py 内置默认同值
TENANT_THRESHOLDS: tuple[tuple[str, float, float, float | None, float | None], ...] = (
    ("fail_count", 1.0, 15.0, 30.0, 45.0),
    ("gpa_drop", 1.0, 5.0, 10.0, 30.0),
    ("gpa_drop_slope", 1.0, 2.0, None, None),
    ("attendance_rate", 1.0, 0.85, 0.60, 25.0),
    ("level", 1.0, 25.0, 45.0, 65.0),
)

POLITICAL = ("群众", "共青团员", "共青团员", "中共预备党员", "中共党员")
CITIES = ("重庆", "成都", "西安", "深圳", "杭州")


def _h(student_no: str, start: int, end: int) -> int:
    """按学号哈希取一段整数：同一学号每次结果一致。"""
    return int(hashlib.sha256(student_no.encode("utf-8")).hexdigest()[start:end], 16)


def extra_info(student_no: str) -> tuple[int, int | None, str, str, float]:
    """确定性生成一名学生的扩展信息（四六级/政治面貌/意向城市/每周学时）。"""
    cet4 = 380 + _h(student_no, 0, 4) % 180
    cet6 = None if _h(student_no, 4, 6) % 3 else 425 + _h(student_no, 6, 10) % 136
    political = POLITICAL[_h(student_no, 10, 14) % len(POLITICAL)]
    city = CITIES[_h(student_no, 14, 18) % len(CITIES)]
    hours = float(6 + _h(student_no, 18, 22) % 15)
    return cet4, cet6, political, city, hours


def seed_thresholds(cur) -> int:
    """租户默认预警阈值：与引擎内置默认同值，入库后可在页面上看到并调整。"""
    sql = (
        "INSERT INTO `预警阈值`(`租户编号`,`指标`,`权重`,`红色阈值`,`橙色阈值`,`黄色阈值`) "
        "VALUES (%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE "
        "`权重`=VALUES(`权重`),`红色阈值`=VALUES(`红色阈值`),"
        "`橙色阈值`=VALUES(`橙色阈值`),`黄色阈值`=VALUES(`黄色阈值`)"
    )
    for metric, weight, yellow, orange, red in TENANT_THRESHOLDS:
        cur.execute(sql, (TENANT_ID, metric, weight, red, orange, yellow))
    return len(TENANT_THRESHOLDS)


def seed_class_override(cur) -> int:
    """给演示班一个班级级覆盖，证明「班级覆盖 > 租户默认」链路可用。

    权重取默认值 1.0：页面能看到 source=class，但预警分数与默认口径一致，
    不会因为演示数据改动而影响既有测试/演示数字。
    """
    cur.execute(
        "INSERT INTO `班级预警阈值`(`租户编号`,`班级`,`指标`,`权重`) VALUES (%s,%s,%s,%s) "
        "ON DUPLICATE KEY UPDATE `权重`=VALUES(`权重`)",
        (TENANT_ID, DEMO_CLASS, "attendance_rate", 1.0),
    )
    return 1


def seed_notice_read(cur) -> dict[str, int | str]:
    """给同班另一名学生写已读水位（不影响演示学生的 9 条未读）。"""
    cur.execute("SELECT COALESCE(MAX(`编号`),0) AS max_id FROM `竞赛通知`")
    max_id = int(cur.fetchone()["max_id"])
    cur.execute(
        "SELECT `学号` FROM `学生` WHERE `租户编号`=%s AND `班级`=%s AND `学号`<>%s "
        "ORDER BY `编号` LIMIT 1",
        (TENANT_ID, DEMO_CLASS, DEMO_STUDENT_NO),
    )
    row = cur.fetchone()
    if not row:
        return {"student_no": "", "watermark": 0}
    student_no = str(row["学号"])
    watermark = max(0, max_id - 1)
    cur.execute(
        "INSERT INTO `学生通知已读`(`学号`,`租户编号`,`已读通知编号`,`最后已读时间`) "
        "VALUES (%s,%s,%s,NOW()) ON DUPLICATE KEY UPDATE "
        "`已读通知编号`=VALUES(`已读通知编号`),`最后已读时间`=NOW()",
        (student_no, TENANT_ID, watermark),
    )
    return {"student_no": student_no, "watermark": watermark}


def seed_extra_info(cur) -> int:
    """给所有还没有扩展信息的学生补确定性数据；已有记录不覆盖。"""
    cur.execute(
        "SELECT s.`编号`, s.`学号` FROM `学生` s "
        "LEFT JOIN `学生扩展信息` e ON e.`学生编号`=s.`编号` "
        "WHERE s.`租户编号`=%s AND e.`编号` IS NULL",
        (TENANT_ID,),
    )
    rows = cur.fetchall()
    params = [
        (TENANT_ID, int(r["编号"]), *extra_info(str(r["学号"])))
        for r in rows
    ]
    if params:
        cur.executemany(
            "INSERT INTO `学生扩展信息`"
            "(`租户编号`,`学生编号`,`四级分数`,`六级分数`,`政治面貌`,`意向城市`,`每周学时`) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            params,
        )
    return len(params)


def align_demo_intent(cur) -> bool:
    """把演示学生的职业目标与已提交的考公规划对齐，避免同页两个方向。"""
    cur.execute("SELECT `编号` FROM `学生` WHERE `学号`=%s AND `租户编号`=%s",
                (DEMO_STUDENT_NO, TENANT_ID))
    row = cur.fetchone()
    if not row:
        return False
    cur.execute(
        "INSERT INTO `职业意向`(`租户编号`,`学生编号`,`意向`) VALUES (%s,%s,'考公') "
        "ON DUPLICATE KEY UPDATE `意向`='考公'",
        (TENANT_ID, int(row["编号"])),
    )
    return True


def main() -> int:
    s = get_settings()
    conn = pymysql.connect(host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
                           password=s.mysql_password, database=s.mysql_db,
                           charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)
    try:
        with conn.cursor() as cur:
            n_threshold = seed_thresholds(cur)
            n_class = seed_class_override(cur)
            notice = seed_notice_read(cur)
            n_extra = seed_extra_info(cur)
            intent_ok = align_demo_intent(cur)
        conn.commit()
    finally:
        conn.close()
    print(f"预警阈值: {n_threshold} 条（租户默认）")
    print(f"班级覆盖: {n_class} 条（{DEMO_CLASS} attendance_rate 权重 1.0，与默认同值）")
    print(f"通知已读水位: {notice}")
    print(f"学生扩展信息: 新增 {n_extra} 条")
    print(f"演示学生目标对齐: {'已设为考公' if intent_ok else '未找到 ' + DEMO_STUDENT_NO}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
