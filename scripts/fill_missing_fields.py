"""scripts/fill_missing_fields.py

职责：补齐「有行但关键字段为空」的字段。铁律：真实派生 > 模拟，模拟的逐项打印并标注，
绝不把模拟值写成看不出来的真实值。

动作（可单独跑 --only）：
  resume_edu       简历教育经历.学历 / 成绩排名
                   学历：学校是本科院校、库内学生均为本科生 → 真实派生
                   排名：用「成绩 × 学分」算加权均分，在同专业同年级里算百分位 → 真实数据计算
  activity_time    学生活动.获得时间 → 按学期末派生（2025-2026-1 → 2026-01-15）
  resume_cert      简历技能证书.等级分数（skill 用熟练度、cert 用分数）+ cert 获得时间 → 模拟
  resume_ach       简历实践经历.成果 → 优先取描述里的量化句（原文派生），取不到才用中性表述（模拟）
  job_publish      岗位.发布时间 / 招聘岗位.截止日期 → 模拟（按数据集采集月份分布）
  class_threshold  班级预警阈值 → 演示用的班级级覆盖配置（模拟，教师可在页面上改）

用法：
    .venv\\Scripts\\python.exe scripts\\fill_missing_fields.py --dry-run
    .venv\\Scripts\\python.exe scripts\\fill_missing_fields.py --only resume_edu,activity_time
    .venv\\Scripts\\python.exe scripts\\fill_missing_fields.py
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import pymysql
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402

TENANT = 1
DRY = False


def _conn() -> pymysql.connections.Connection:
    load_dotenv(".env")
    s = get_settings()
    return pymysql.connect(
        host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
        password=s.mysql_password, database=s.mysql_db, charset="utf8mb4",
    )


def _h(text: str) -> int:
    """确定性哈希：同一输入永远给同一个序号，保证脚本可重复运行。"""
    return int(hashlib.md5(text.encode("utf-8")).hexdigest()[:8], 16)


# ---------------------------------------------------------------- 1. 简历教育经历

def resume_edu(cur) -> list[str]:
    """学历：学校为本科院校 → 统一补「本科」（真实派生）。
    成绩排名：用真实成绩算同专业同年级百分位。"""
    logs = []
    cur.execute(
        "UPDATE `简历教育经历` SET `学历`='本科' "
        "WHERE (`学历` IS NULL OR `学历`='') "
        "AND `学校` IN ('重庆财经学院')"
    )
    logs.append(f"学历（真实派生：学校本科）补 {cur.rowcount} 行")

    # 真实成绩 → 学分加权均分
    cur.execute(
        "SELECT s.`编号`, s.`专业`, s.`年级`, "
        "       SUM(sc.`分数`*c.`学分`)/NULLIF(SUM(c.`学分`),0) AS gpa "
        "FROM `学生` s "
        "JOIN `成绩` sc ON sc.`学生编号`=s.`编号` "
        "JOIN `课程` c ON c.`编号`=sc.`课程编号` "
        "WHERE s.`租户编号`=%s AND c.`学分` > 0 "
        "GROUP BY s.`编号`, s.`专业`, s.`年级`",
        (TENANT,),
    )
    rows = cur.fetchall()
    groups: dict[tuple, list] = defaultdict(list)
    for sid, major, grade, gpa in rows:
        if gpa is not None:
            groups[(major, grade)].append((sid, float(gpa)))

    pct_of: dict[int, str] = {}
    for peers in groups.values():
        if len(peers) < 5:          # 样本太小的组不出排名，避免“前 0%”式假精度
            continue
        peers.sort(key=lambda kv: (-kv[1], kv[0]))
        n = len(peers)
        for i, (sid, _g) in enumerate(peers):
            pct = round(i / (n - 1) * 100)
            pct_of[sid] = f"前 {max(1, pct)}%"

    if not pct_of:
        logs.append("成绩排名：没有可算的样本组，跳过")
        return logs

    # 简历 → 学生 → 写回该简历的教育经历
    cur.execute(
        "SELECT e.`编号`, r.`学生编号` FROM `简历教育经历` e "
        "JOIN `简历` r ON r.`编号`=e.`简历编号` "
        "WHERE e.`成绩排名` IS NULL OR e.`成绩排名`=''"
    )
    upd = 0
    for eid, sid in cur.fetchall():
        rank = pct_of.get(int(sid)) if sid is not None else None
        if not rank:
            continue
        if not DRY:
            cur.execute("UPDATE `简历教育经历` SET `成绩排名`=%s WHERE `编号`=%s", (rank, eid))
        upd += 1
    logs.append(f"成绩排名（真实成绩计算）补 {upd} 行")
    return logs


# ---------------------------------------------------------------- 2. 学生活动获得时间

def _term_end(term: str) -> str | None:
    """'2025-2026-1' → '2026-01-15'；'2025-2026-2' → '2026-07-15'。"""
    m = re.match(r"(\d{4})-(\d{4})-([12])", (term or "").strip())
    if not m:
        return None
    y2 = int(m.group(2))
    return f"{y2}-01-15" if m.group(3) == "1" else f"{y2}-07-15"


def activity_time(cur) -> list[str]:
    cur.execute(
        "SELECT DISTINCT `学期` FROM `学生活动` "
        "WHERE `获得时间` IS NULL AND `学期` IS NOT NULL AND `学期`<>''"
    )
    terms = [r[0] for r in cur.fetchall()]
    logs = []
    total = 0
    for t in terms:
        d = _term_end(t)
        if not d:
            continue
        if DRY:
            cur.execute(
                "SELECT COUNT(*) FROM `学生活动` WHERE `获得时间` IS NULL AND `学期`=%s", (t,)
            )
            total += cur.fetchone()[0]
        else:
            cur.execute(
                "UPDATE `学生活动` SET `获得时间`=%s "
                "WHERE `获得时间` IS NULL AND `学期`=%s",
                (d, t),
            )
            total += cur.rowcount
    logs.append(f"学生活动.获得时间（按学期末派生，{len(terms)} 个学期）补 {total} 行")
    return logs


# ---------------------------------------------------------------- 3. 技能证书

_SKILL_LEVELS = ("了解", "熟悉", "熟练", "精通")


def resume_cert(cur) -> list[str]:
    logs = []
    cur.execute(
        "SELECT `编号`, `类型`, `名称` FROM `简历技能证书` "
        "WHERE `等级分数` IS NULL OR `等级分数`=''"
    )
    rows = cur.fetchall()
    n_skill = n_cert = 0
    for cid, typ, name in rows:
        if typ == "skill":
            val = _SKILL_LEVELS[_h(str(name)) % len(_SKILL_LEVELS)]
            n_skill += 1
        else:
            # 证书给分数（60~99），确定性分布
            val = str(60 + _h(str(name)) % 40)
            n_cert += 1
        if not DRY:
            cur.execute("UPDATE `简历技能证书` SET `等级分数`=%s WHERE `编号`=%s", (val, cid))
    logs.append(f"等级分数（模拟）补 {len(rows)} 行：技能 {n_skill} / 证书 {n_cert}")

    # 只有证书才有「获得时间」；技能类留空是语义正确，不硬填
    cur.execute(
        "SELECT `编号`, `名称` FROM `简历技能证书` "
        "WHERE `类型`='cert' AND (`获得时间` IS NULL OR `获得时间`='')"
    )
    certs = cur.fetchall()
    for cid, name in certs:
        # 2024-09 ~ 2026-06 之间，确定性
        days = _h(str(name)) % 640
        d = (date(2024, 9, 1) + timedelta(days=days)).isoformat()
        if not DRY:
            cur.execute("UPDATE `简历技能证书` SET `获得时间`=%s WHERE `编号`=%s", (d, cid))
    logs.append(f"证书.获得时间（模拟）补 {len(certs)} 行；技能类按语义留空")
    return logs


# ---------------------------------------------------------------- 4. 实践成果

_ACH_PAT = re.compile(r"[^，。；]{0,18}\d+[^，。；]{0,18}")


def resume_ach(cur) -> list[str]:
    cur.execute(
        "SELECT `编号`, `描述` FROM `简历实践经历` WHERE `成果` IS NULL OR `成果`=''"
    )
    rows = cur.fetchall()
    derived = simulated = 0
    for pid, desc in rows:
        desc = (desc or "").strip()
        m = _ACH_PAT.search(desc)
        if m:
            val = m.group(0).strip(" ，。；")
            derived += 1
        else:
            # 描述里没有量化信息，只能给中性表述——这是模拟
            val = "按期交付并通过验收"
            simulated += 1
        if not DRY:
            cur.execute("UPDATE `简历实践经历` SET `成果`=%s WHERE `编号`=%s", (val, pid))
    return [f"实践成果补 {len(rows)} 行：原文量化句派生 {derived} / 中性表述(模拟) {simulated}"]


# ---------------------------------------------------------------- 5. 岗位发布时间

_SRC_MONTH = re.compile(r"(\d{4})(\d{2})")


def job_publish(cur) -> list[str]:
    logs = []
    cur.execute(
        "SELECT `来源`, COUNT(*) FROM `岗位` "
        "WHERE `发布时间` IS NULL GROUP BY `来源`"
    )
    by_src = cur.fetchall()
    total = 0
    for src, cnt in by_src:
        m = _SRC_MONTH.search(str(src or ""))
        if m:
            y, mo = int(m.group(1)), int(m.group(2))
        else:
            y, mo = 2025, 8
        if DRY:
            total += cnt
            continue
        # 该月 1~28 日内确定性分布
        cur.execute(
            "UPDATE `岗位` SET `发布时间` = DATE_ADD(%s, INTERVAL (CRC32(`原始键`) %% 28) DAY) "
            "WHERE `发布时间` IS NULL AND `来源`=%s",
            (date(y, mo, 1), src),
        )
        total += cur.rowcount
    logs.append(f"岗位.发布时间（模拟：按来源采集月份 {[s for s,_ in by_src]}）补 {total} 行")

    cur.execute(
        "SELECT COUNT(*) FROM `招聘岗位` "
        "WHERE `截止日期` IS NULL AND `发布日期` IS NOT NULL"
    )
    n = cur.fetchone()[0]
    if not DRY and n:
        cur.execute(
            "UPDATE `招聘岗位` SET `截止日期` = DATE_ADD(`发布日期`, INTERVAL 30 DAY) "
            "WHERE `截止日期` IS NULL AND `发布日期` IS NOT NULL"
        )
    logs.append(f"招聘岗位.截止日期（模拟：发布日 +30 天）补 {n} 行")
    return logs


# ---------------------------------------------------------------- 6. 班级阈值覆盖

_CLASS_RULES = (
    # 班级后缀 → (attendance_rate, gpa_drop, fail_count) 三档（红/橙/黄）
    ("2301", ((0.70, 0.85, 0.92), (20, 8, 3), (3, 2, 1))),
    ("2302", ((0.65, 0.80, 0.90), (25, 10, 4), (4, 2, 1))),
    ("2401", ((0.75, 0.88, 0.94), (15, 6, 2), (2, 1, 1))),
)
_METRIC_COLS = ("红色阈值", "橙色阈值", "黄色阈值")


def class_threshold(cur) -> list[str]:
    cur.execute("SELECT DISTINCT `班级` FROM `学生` WHERE `租户编号`=%s ORDER BY `班级`", (TENANT,))
    classes = [r[0] for r in cur.fetchall()]
    logs = []
    n = 0
    for cls in classes:
        rule = next((r for suffix, r in _CLASS_RULES if str(cls).endswith(suffix)), None)
        if not rule:
            continue
        for metric, vals in zip(("attendance_rate", "gpa_drop", "fail_count"), rule):
            if DRY:
                n += 1
                continue
            cur.execute(
                "INSERT INTO `班级预警阈值`"
                "(`租户编号`,`班级`,`指标`,`权重`,`红色阈值`,`橙色阈值`,`黄色阈值`) "
                "VALUES (%s,%s,%s,1,%s,%s,%s) "
                "ON DUPLICATE KEY UPDATE `红色阈值`=VALUES(`红色阈值`), "
                "`橙色阈值`=VALUES(`橙色阈值`), `黄色阈值`=VALUES(`黄色阈值`)",
                (TENANT, cls, metric, *vals),
            )
            n += 1
    logs.append(f"班级阈值覆盖（模拟配置，教师可改）写入 {n} 行 / {len(classes)} 个班中匹配到的班级")
    return logs


ACTIONS = {
    "resume_edu": resume_edu,
    "activity_time": activity_time,
    "resume_cert": resume_cert,
    "resume_ach": resume_ach,
    "job_publish": job_publish,
    "class_threshold": class_threshold,
}


def main() -> int:
    global DRY
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", default="", help="逗号分隔的动作名，默认全跑")
    args = ap.parse_args()
    DRY = args.dry_run

    names = [x.strip() for x in args.only.split(",") if x.strip()] or list(ACTIONS)
    unknown = [x for x in names if x not in ACTIONS]
    if unknown:
        print(f"未知动作: {unknown}；可选: {list(ACTIONS)}")
        return 2

    conn = _conn()
    try:
        with conn.cursor() as cur:
            for name in names:
                print(f"\n== {name} ==")
                for line in ACTIONS[name](cur):
                    print("   " + line)
        if DRY:
            conn.rollback()
            print("\n[dry-run] 已回滚，未写库")
        else:
            conn.commit()
            print("\n已提交")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
