# scripts/seed_elective.py
# 职责：给每个学生灌「选修课」记录，让 course_pref 不再全空（口径字典 §1）
# 依赖：pymysql / app.config / etl.school_cqufe（只读校情） / rules\direction_keywords.json
# 说明：课池里每门课自带方向标注 → 不靠事后猜课程名，口径可复核。
#       幂等：重复运行先按 (tenant_id, term) 清空本脚本负责的学期。
# 用法：.venv\Scripts\python.exe scripts\seed_elective.py --term 2025-2026-2

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pymysql

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.config import get_settings  # noqa: E402
from etl.school_cqufe import JOB_KEYWORDS, MAJORS  # noqa: E402

RULES_PATH = _ROOT / "rules" / "direction_keywords.json"

# 每生每学期选课门数区间
MIN_COURSES, MAX_COURSES = 2, 4
# 与本人专业方向相关的选课概率（其余随机，制造区分度）
MAJOR_RELATED_PROB = 0.60


def load_directions() -> tuple[list[tuple[str, tuple[str, ...]]], dict[str, list[dict[str, Any]]], str]:
    """读方向词典与选修课池。返回 (方向表, 课池, 兜底方向名)。"""
    data = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    directions = [
        (str(d["name"]), tuple(str(k).lower() for k in d.get("keywords") or ()))
        for d in data.get("directions") or ()
    ]
    pool = {str(k): list(v) for k, v in (data.get("elective_pool") or {}).items()}
    return directions, pool, str(data.get("fallback") or "其他")


class DirectionClassifier:
    """岗位标题/关键词 → 兴趣方向（顺序敏感，先匹配者胜）。"""

    def __init__(self) -> None:
        self.directions, self.pool, self.other = load_directions()

    def classify(self, text: str) -> str:
        low = str(text or "").lower()
        if not low:
            return self.other
        for name, keywords in self.directions:
            if any(k in low for k in keywords):
                return name
        return self.other

    def major_directions(self, major: str) -> list[str]:
        """专业 → 相关方向集合（用该校情模块给出的岗位关键词反推）。"""
        hits: list[str] = []
        for kw in JOB_KEYWORDS.get(major, ()):
            direction = self.classify(kw)
            if direction != self.other and direction in self.pool and direction not in hits:
                hits.append(direction)
        return hits


def _connect() -> pymysql.connections.Connection:
    s = get_settings()
    return pymysql.connect(
        host=s.mysql_host,
        port=s.mysql_port,
        user=s.mysql_user,
        password=s.mysql_password,
        database=s.mysql_db,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def load_students(tenant_id: int) -> list[dict[str, Any]]:
    """取学生 id / 学号 / 专业。"""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, student_no, name, major FROM student WHERE tenant_id = %s ORDER BY student_no",
                (tenant_id,),
            )
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def build_selections(
    students: list[dict[str, Any]],
    term: str,
    clf: DirectionClassifier,
    rng: random.Random,
) -> list[tuple[int, str, str, str, str, float]]:
    """为每名学生生成选课记录（避开本专业核心课程）。

    返回 (student_id, student_no, term, course_name, direction, credit)。
    """
    rows: list[tuple[int, str, str, str, str, float]] = []
    for stu in students:
        major = str(stu.get("major") or "")
        core = set(MAJORS.get(major, ("", "", []))[2]) if major in MAJORS else set()
        related = clf.major_directions(major)
        other_dirs = [d for d in clf.pool if d not in related]

        picked: set[str] = set()
        count = rng.randint(MIN_COURSES, MAX_COURSES)
        for _ in range(count):
            # 60% 概率优先从专业相关方向选，其余随机
            if related and rng.random() < MAJOR_RELATED_PROB:
                direction = rng.choice(related)
            elif other_dirs:
                direction = rng.choice(other_dirs)
            elif related:
                direction = rng.choice(related)
            else:
                direction = rng.choice(list(clf.pool))

            courses = [c for c in clf.pool.get(direction, []) if str(c["name"]) not in core]
            if not courses:
                continue
            course = rng.choice(courses)
            name = str(course["name"])
            if name in picked:
                continue
            picked.add(name)
            rows.append((
                int(stu["id"]),
                str(stu["student_no"]),
                term,
                name,
                direction,
                float(course.get("credit") or 2.0),
            ))
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="灌选修课记录，补齐 course_pref 数据源")
    parser.add_argument("--term", default="2025-2026-2,2025-2026-1",
                        help="学期，逗号分隔可多个")
    parser.add_argument("--tenant-id", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true", help="只打印统计不写库")
    args = parser.parse_args(argv)

    terms = [t.strip() for t in args.term.split(",") if t.strip()]
    clf = DirectionClassifier()
    rng = random.Random(42)

    try:
        students = load_students(args.tenant_id)
    except (pymysql.MySQLError, OSError) as exc:
        print(f"[ERROR] 连不上 MySQL：{exc}")
        print("        先确认 MySQL 服务在跑、.env 里口令正确，再重跑本脚本。")
        return 1
    if not students:
        print(f"[ERROR] 租户 {args.tenant_id} 下没有学生，先跑 seed_mock.py")
        return 1

    all_rows: list[tuple[Any, ...]] = []
    for term in terms:
        all_rows.extend(build_selections(students, term, clf, rng))

    # 统计：方向分布 + 每生选课门数
    dist = Counter(r[4] for r in all_rows)
    per_student = Counter((r[0], r[2]) for r in all_rows)
    print(f"租户 {args.tenant_id} · 学期 {terms}")
    print(f"学生 {len(students)} 人 · 选课记录 {len(all_rows)} 条 · "
          f"人均 {len(all_rows) / max(1, len(students) * len(terms)):.2f} 门")
    print("方向分布：")
    total = max(1, len(all_rows))
    for name, cnt in dist.most_common():
        print(f"  {name:<6} {cnt:>5}  {cnt / total * 100:5.1f}%")
    covered = len([d for d in dist if d != clf.other])
    print(f"覆盖方向数：{covered}（课池共 {len(clf.pool)} 个方向）")
    top_share = max(dist.values()) / total if dist else 0.0
    print(f"单方向最高占比：{top_share * 100:.1f}%  {'OK' if top_share <= 0.40 else '⚠ 过于集中'}")

    if args.dry_run:
        print("[dry-run] 未写库。样例：")
        for row in all_rows[:5]:
            print(f"  student_id={row[0]} term={row[2]} {row[3]} → {row[4]} ({row[5]} 学分)")
        return 0

    conn = _connect()
    try:
        with conn.cursor() as cur:
            for term in terms:
                cur.execute(
                    "DELETE es FROM elective_selection es "
                    "JOIN student s ON s.id = es.student_id "
                    "WHERE es.tenant_id = %s AND es.term = %s",
                    (args.tenant_id, term),
                )
            cur.executemany(
                "INSERT INTO elective_selection "
                "(tenant_id, student_id, term, course_name, direction, credit) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                [(args.tenant_id, r[0], r[2], r[3], r[4], r[5]) for r in all_rows],
            )
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM elective_selection WHERE tenant_id = %s",
                        (args.tenant_id,))
            print(f"写入 elective_selection：{cur.fetchone()['n']} 行")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
