# scripts/seed_teacher_scope.py
# 职责：配置教师任教班级（教师任教班级），供教师端按班隔离与阈值配置使用
# 依赖：pymysql / app.config；不依赖 FastAPI 服务
# 说明：--clear 清空绑定——教师此后**看不到任何班级**（2026-11-10 起未绑定不再
#       回退租户范围，每个辅导员账号只能管理自己绑定的班）；--all 绑定本租户全部班级
#       （仅在「全校管理员」场景使用）

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pymysql

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.config import get_settings  # noqa: E402


def _connect(settings) -> pymysql.connections.Connection:
    return pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=settings.mysql_db,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=5,
    )


def _teacher_id(cur, tenant_id: int, employee_no: str) -> int:
    cur.execute(
        "SELECT `编号` AS id FROM `教师` WHERE `租户编号` = %s AND `工号` = %s",
        (tenant_id, employee_no),
    )
    row = cur.fetchone()
    if not row:
        raise ValueError(f"教师工号不存在：{employee_no}（租户 {tenant_id}）")
    return int(row["id"])


def _tenant_classes(cur, tenant_id: int) -> list[str]:
    cur.execute(
        "SELECT DISTINCT `班级` AS class_name FROM `学生` "
        "WHERE `租户编号` = %s AND `班级` <> '' ORDER BY `班级`",
        (tenant_id,),
    )
    return [str(row["class_name"]) for row in cur.fetchall()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="配置教师任教班级")
    parser.add_argument("--teacher", default="T001", help="教师工号")
    parser.add_argument("--tenant-id", type=int, default=1)
    parser.add_argument("--classes", default="", help="逗号分隔的班级名")
    parser.add_argument("--all", action="store_true", help="绑定本租户全部班级")
    parser.add_argument("--clear", action="store_true", help="清空绑定（回退租户范围）")
    args = parser.parse_args(argv)

    settings = get_settings()
    conn = _connect(settings)
    try:
        with conn.cursor() as cur:
            teacher_id = _teacher_id(cur, args.tenant_id, args.teacher)
            available = _tenant_classes(cur, args.tenant_id)

            if args.clear:
                target = []
            elif args.all:
                target = available
            else:
                target = [name.strip() for name in args.classes.split(",") if name.strip()]
                missing = [name for name in target if name not in set(available)]
                if missing:
                    raise ValueError(f"班级不存在于租户 {args.tenant_id}：{missing}")

            cur.execute("DELETE FROM `教师任教班级` WHERE `教师编号` = %s", (teacher_id,))
            for class_name in target:
                cur.execute(
                    "INSERT INTO `教师任教班级` (`租户编号`, `教师编号`, `班级`) "
                    "VALUES (%s, %s, %s)",
                    (args.tenant_id, teacher_id, class_name),
                )
            conn.commit()

        if not target:
            print(f"{args.teacher}：已清空任教班级绑定——此后该账号看不到任何班级，"
                  f"请用 --classes 重新绑定。")
        else:
            print(f"{args.teacher}：已绑定 {len(target)} 个班：")
            for class_name in target:
                print(f"  {class_name}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
