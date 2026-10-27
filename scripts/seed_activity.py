# scripts/seed_activity.py
# 职责：给 4 张新源表灌模拟数据（library_record / consumption_record / student_activity / job_view_log）
# 依赖：pymysql / app.config / etl.school_cqufe / random(seed=42) / pathlib
# 说明：幂等（先删本租户本学期的行再插）；风险名单来自 data\hidden_risk.csv；零侵入，不碰既有表

from __future__ import annotations

import csv
import math
import random
import sys
from pathlib import Path

import pymysql

# 把项目根目录加入 sys.path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.config import get_settings  # noqa: E402
from etl import school_cqufe  # noqa: E402

# ----------------------------------------------------------------
# 常量
# ----------------------------------------------------------------
_TENANT_ID = 1
_SEED = 42
_TERMS = ["2025-2026-1", "2025-2026-2"]

# 图书馆：非风险 λ=25，风险 λ=8，裁剪 0~120
_LIBRARY_LAM = 25.0
_LIBRARY_LAM_RISK = 8.0
_LIBRARY_MAX = 120
_BORROW_MAX = 8

# 一卡通：active_days = 120 × U(a,b)，风险学生上限由 0.95 降到 0.60
_CONSUME_DAY_CAP = 120
_CONSUME_ACTIVE_RANGE = (0.35, 0.95)
_CONSUME_ACTIVE_RANGE_RISK = (0.35, 0.60)
_MEAL_PER_DAY_RANGE = (1.2, 2.4)
_MEAL_UNIT_RANGE = (9.0, 18.0)

# 证书/竞赛/项目：先按「0~3 条 + 类型权重」抽，再按覆盖率补齐（保证非空率 ≥95%）
_RECORD_MIN, _RECORD_MAX = 0, 3
_TYPE_WEIGHTS = (("cert", 0.50), ("project", 0.30), ("contest", 0.20))
_TYPE_COUNT_RANGE = {"cert": (1, 3), "contest": (1, 2), "project": (1, 2)}
_COVER_FILL = {"cert": 0.96, "contest": 0.96, "project": 0.96}
_COVER_FILL_RISK = {"project": 0.70}
_RISK_PROJECT_DROP = 0.5  # 风险学生每条 project 记录 50% 丢弃 → 项目期望减半

# 岗位浏览/收藏
_VIEW_MAX = 60
_FAV_MAX = 8
_FAV_ZERO_RATE = 0.03  # 仅 3% 学生无收藏，保证 job_favorite_cnt 非空率 ≥95%
_JOB_MAJOR_HIT = 0.6  # 60% 落在本人专业 JOB_KEYWORDS 命中的岗位上

# 写库分批大小：单批 5 千行，逐行 3 个占位符也远低于 max_allowed_packet(4MB)
_INSERT_BATCH = 5000


def _poisson(rng: random.Random, lam: float) -> int:
    """Knuth 泊松抽样，lam ≥ 0，返回非负整数。"""
    limit = math.exp(-lam)
    k = 0
    p = 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def _pick_type(rng: random.Random) -> str:
    """按类型权重抽一条活动的类型。"""
    x = rng.random()
    acc = 0.0
    for name, weight in _TYPE_WEIGHTS:
        acc += weight
        if x < acc:
            return name
    return _TYPE_WEIGHTS[-1][0]


def _load_hidden_risk(path: Path) -> dict[str, bool]:
    """读 data/hidden_risk.csv（P2-2a 产物），返回 {student_no: 是否风险}。"""
    risk: dict[str, bool] = {}
    with open(path, "r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            risk[row["student_no"]] = row["true_risk"] == "1"
    return risk


def _load_students(cur, tenant_id: int) -> list[tuple[int, str, str]]:
    """取本租户学生的 (id, student_no, major)，按学号升序保证可复现。"""
    cur.execute(
        "SELECT `编号`, `学号`, `专业` FROM `学生` WHERE `租户编号` = %s ORDER BY `学号`",
        (tenant_id,),
    )
    return [(int(r[0]), str(r[1]), str(r[2])) for r in cur.fetchall()]


def _load_jobs(cur) -> list[tuple[int, str]]:
    """取真实岗位表的 (id, title)。"""
    cur.execute("SELECT `编号`, `岗位名称` FROM `岗位` ORDER BY `编号`")
    return [(int(r[0]), str(r[1])) for r in cur.fetchall()]


def _jobs_hitting_keywords(jobs: list[tuple[int, str]], keywords: list[str]) -> list[int]:
    """返回标题命中任一专业关键词的岗位 id 列表。"""
    lowered = [str(k).lower() for k in keywords]
    hits = [jid for jid, title in jobs
            if any(k in str(title).lower() for k in lowered)]
    return hits


def _gen_library_rows(rng: random.Random, students: list[tuple], risk_map: dict) -> list[tuple]:
    """生成 library_record 行：非风险 λ=25，风险 λ=8，到馆次数裁剪 0~120。"""
    rows: list[tuple] = []
    for sid, sno, _major in students:
        lam = _LIBRARY_LAM_RISK if risk_map.get(sno) else _LIBRARY_LAM
        for term in _TERMS:
            visit = min(_LIBRARY_MAX, _poisson(rng, lam))
            rows.append((_TENANT_ID, sid, term, visit, rng.randint(0, _BORROW_MAX)))
    return rows


def _gen_consumption_rows(rng: random.Random, students: list[tuple], risk_map: dict) -> list[tuple]:
    """生成 consumption_record 行：风险学生活跃天数系数上限降到 0.60。"""
    rows: list[tuple] = []
    for sid, sno, _major in students:
        low, high = (_CONSUME_ACTIVE_RANGE_RISK if risk_map.get(sno)
                     else _CONSUME_ACTIVE_RANGE)
        for term in _TERMS:
            active_days = int(_CONSUME_DAY_CAP * rng.uniform(low, high))
            meal_cnt = int(active_days * rng.uniform(*_MEAL_PER_DAY_RANGE))
            avg_amount = round(rng.uniform(*_MEAL_UNIT_RANGE) * rng.uniform(0.7, 1.3), 2)
            rows.append((_TENANT_ID, sid, term, meal_cnt, active_days, avg_amount))
    return rows


def _activity_title(rng: random.Random, activity_type: str, major: str) -> str:
    """按专业关键词生成活动名称。"""
    keywords = school_cqufe.JOB_KEYWORDS.get(major) or [major]
    kw = rng.choice(keywords)
    suffix = {"cert": "职业资格证书", "contest": "创新大赛", "project": "实践项目"}
    return f"{kw}{suffix[activity_type]}"


def _gen_activity_rows(rng: random.Random, students: list[tuple], risk_map: dict) -> list[tuple]:
    """生成 student_activity 行：0~3 条主抽 + 覆盖率补齐 + 风险学生项目减半。"""
    rows: list[tuple] = []
    levels = ("校级", "省级", "国家级", "企业级")
    for sid, sno, major in students:
        is_risk = risk_map.get(sno, False)
        for term in _TERMS:
            counts: dict[str, int] = {}
            for _ in range(rng.randint(_RECORD_MIN, _RECORD_MAX)):
                kind = _pick_type(rng)
                # 风险学生：每条 project 记录 50% 丢弃 → 期望减半
                if is_risk and kind == "project" and rng.random() < _RISK_PROJECT_DROP:
                    continue
                counts[kind] = counts.get(kind, 0) + 1
            # 覆盖率补齐：保证 cert/contest/project 非空率 ≥95%；风险学生项目补齐率更低
            for kind in ("cert", "contest", "project"):
                if counts.get(kind):
                    continue
                fill = _COVER_FILL_RISK.get(kind) if is_risk else None
                prob = fill if fill is not None else _COVER_FILL.get(kind, 0.0)
                if rng.random() < prob:
                    low, high = _TYPE_COUNT_RANGE[kind]
                    counts[kind] = rng.randint(low, high)
            for kind, count in sorted(counts.items()):
                for _ in range(count):
                    rows.append((
                        _TENANT_ID, sid, term, kind,
                        _activity_title(rng, kind, major),
                        rng.choice(levels), None,
                    ))
    return rows


def _gen_job_view_rows(
    rng: random.Random, students: list[tuple], risk_map: dict, jobs: list[tuple]
) -> list[tuple]:
    """生成 job_view_log 行：60% 落在本人专业关键词命中的岗位上。"""
    all_ids = [jid for jid, _t in jobs]
    hit_pool: dict[str, list[int]] = {}
    for _sid, _sno, major in students:
        if major not in hit_pool:
            hits = _jobs_hitting_keywords(jobs, school_cqufe.JOB_KEYWORDS.get(major, []))
            hit_pool[major] = hits or all_ids
    rows: list[tuple] = []
    for sid, sno, major in students:
        pool = hit_pool[major]
        for term in _TERMS:
            for _ in range(rng.randint(0, _VIEW_MAX)):
                jid = rng.choice(pool) if rng.random() < _JOB_MAJOR_HIT else rng.choice(all_ids)
                rows.append((_TENANT_ID, sid, jid, "view", term))
            fav_cnt = 0 if rng.random() < _FAV_ZERO_RATE else rng.randint(1, _FAV_MAX)
            for _ in range(fav_cnt):
                jid = rng.choice(pool) if rng.random() < _JOB_MAJOR_HIT else rng.choice(all_ids)
                rows.append((_TENANT_ID, sid, jid, "favorite", term))
    return rows


def _clear_and_insert(cur, table: str, columns: str, rows: list[tuple]) -> int:
    """幂等 + **原子**：先删本租户本学期的行，再分批插入，返回插入行数。

    两个坑，都必须处理：
    1. 分批是必须的：`岗位浏览日志` 一次要写 ~68 万行，pymysql 的 executemany 会
       把它拼成一条超长 SQL，超过 max_allowed_packet（默认 4 MB）后整批被截断。
    2. 原子是必须的：连接是 autocommit=True，DELETE 立即生效，若中途被打断
       （Ctrl-C / 进程被杀 / 磁盘满），表里就只剩前几批 —— 表现是「打印说插入
       68 万行，表里只有 4.5 万行」。所以这里显式开事务，删+插一起提交，
       失败整体回滚，绝不会留下半张表。
    """
    placeholders = ", ".join(["%s"] * len(_TERMS))
    cur.execute("START TRANSACTION")
    try:
        cur.execute(
            f"DELETE FROM `{table}` WHERE `租户编号` = %s AND `学期` IN ({placeholders})",
            [_TENANT_ID, *_TERMS],
        )
        deleted = cur.rowcount
        inserted = 0
        if rows:
            marks = ", ".join(["%s"] * len(rows[0]))
            sql = f"INSERT INTO `{table}` ({columns}) VALUES ({marks})"
            for start in range(0, len(rows), _INSERT_BATCH):
                chunk = rows[start:start + _INSERT_BATCH]
                cur.executemany(sql, chunk)
                inserted += len(chunk)
        if inserted != len(rows):
            raise RuntimeError(f"{table} 插入行数不符：生成 {len(rows)}，实际 {inserted}")
        cur.execute("COMMIT")
    except BaseException:
        cur.execute("ROLLBACK")
        print(f"  {table:<18} 失败已回滚（表保持原样）")
        raise
    print(f"  {table:<18} 删除 {deleted} 行，插入 {inserted} 行")
    return inserted


def _print_counts(cur) -> None:
    """打印 4 张表的行数。"""
    print()
    print("=" * 56)
    print("四张源表行数")
    print("=" * 56)
    for table in ("图书馆记录", "消费记录", "学生活动", "岗位浏览日志"):
        cur.execute(
            f"SELECT COUNT(*) FROM `{table}` WHERE `租户编号` = %s", (_TENANT_ID,)
        )
        total = cur.fetchone()[0]
        cur.execute(
            f"SELECT `学期` AS term, COUNT(*) FROM `{table}` WHERE `租户编号` = %s "
            "GROUP BY `学期` ORDER BY `学期`",
            (_TENANT_ID,),
        )
        by_term = ", ".join(f"{t}:{c}" for t, c in cur.fetchall())
        print(f"  {table:<18} 合计 {total:>6} 行  （{by_term}）")


def main() -> None:
    """入口：灌 4 张源表并打印行数。"""
    errs = school_cqufe.validate()
    if errs:
        print("校情自检失败：")
        for e in errs:
            print(f"  {e}")
        raise SystemExit(1)

    risk_path = _ROOT / "data" / "hidden_risk.csv"
    if not risk_path.exists():
        print(f"缺少风险名单文件：{risk_path}")
        raise SystemExit(1)

    rng = random.Random(_SEED)
    risk_map = _load_hidden_risk(risk_path)
    settings = get_settings()

    conn = pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=settings.mysql_db,
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        with conn.cursor() as cur:
            students = _load_students(cur, _TENANT_ID)
            jobs = _load_jobs(cur)
            print(f"本租户学生 {len(students)} 人，其中风险学生 "
                  f"{sum(1 for _i, s, _m in students if risk_map.get(s))} 人；"
                  f"真实岗位 {len(jobs)} 条")
            print("灌入 4 张源表：")
            _clear_and_insert(
                cur, "图书馆记录",
                "`租户编号`, `学生编号`, `学期`, `到馆次数`, `借阅册数`",
                _gen_library_rows(rng, students, risk_map),
            )
            _clear_and_insert(
                cur, "消费记录",
                "`租户编号`, `学生编号`, `学期`, `消费笔数`, `活跃天数`, `日均金额`",
                _gen_consumption_rows(rng, students, risk_map),
            )
            _clear_and_insert(
                cur, "学生活动",
                "`租户编号`, `学生编号`, `学期`, `活动类型`, `名称`, `级别`, `获得时间`",
                _gen_activity_rows(rng, students, risk_map),
            )
            _clear_and_insert(
                cur, "岗位浏览日志",
                "`租户编号`, `学生编号`, `岗位编号`, `动作`, `学期`",
                _gen_job_view_rows(rng, students, risk_map, jobs),
            )
            _print_counts(cur)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
