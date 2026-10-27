"""scripts/reclean_exam_requirements.py

职责：用当前 etl.recruit_fetch.extract_requirements 规则，重跑「招考公告」的要求字段。

背景：旧规则里政治面貌/经历/证书三类用的是「报考条件」「工作经历」「职业（执业）资格」
这类泛词，同一段资格审查流程话会被三个字段同时命中——数据看着是满的，语义全错。
新规则只认字段专属强词、过滤报名流程句、同一句不重复分配。

只更新 8 个要求字段 + 考试日期，不动正文原文/原文链接/时间线/状态。
抽不到就写 NULL，前端显示「公告未单独说明，具体以附件岗位表为准」。

用法：
    .venv\\Scripts\\python.exe scripts\\reclean_exam_requirements.py --dry-run
    .venv\\Scripts\\python.exe scripts\\reclean_exam_requirements.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pymysql
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from etl.recruit_fetch import extract_requirements  # noqa: E402

# 抽取器字段名 → 表列名
_COLS = {
    "education_req": "学历要求",
    "degree_req": "学位要求",
    "major_req": "专业要求",
    "age_req": "年龄要求",
    "political_req": "政治面貌要求",
    "exp_req": "经历要求",
    "cert_req": "证书要求",
    "other_req": "其他要求",
    "exam_date": "考试日期",
}

_FIELDS = ("编号", "标题", "正文原文", *_COLS.values())


def _norm(v) -> str | None:
    """统一成可比较的字符串：NULL/空串/日期都归一，日期转 iso 文本。"""
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _conn() -> pymysql.connections.Connection:
    load_dotenv(".env")
    s = get_settings()
    return pymysql.connect(
        host=s.mysql_host,
        port=s.mysql_port,
        user=s.mysql_user,
        password=s.mysql_password,
        database=s.mysql_db,
        charset="utf8mb4",
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只打印差异，不写库")
    args = ap.parse_args()

    conn = _conn()
    changed_rows = 0
    changed_cells = 0
    filled = 0
    emptied = 0

    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {', '.join(f'`{c}`' for c in _FIELDS)} FROM `招考公告` ORDER BY `编号`"
        )
        rows = cur.fetchall()

        for row in rows:
            rec = dict(zip(_FIELDS, row))
            text = rec["正文原文"] or ""
            got = extract_requirements(text)

            diffs = []
            for key, col in _COLS.items():
                old_s = _norm(rec[col])
                new_s = _norm(got.get(key))
                if old_s == new_s:
                    continue
                diffs.append((col, old_s, new_s))
                if old_s is None and new_s:
                    filled += 1
                elif old_s and new_s is None:
                    emptied += 1

            if not diffs:
                continue

            changed_rows += 1
            changed_cells += len(diffs)
            print(f"\n[{rec['编号']}] {str(rec['标题'])[:40]}")
            for col, old, new in diffs:
                o = (old or "∅")[:46]
                n = (new or "∅")[:46]
                print(f"    {col}: {o}  →  {n}")

            if not args.dry_run:
                sets = ", ".join(f"`{col}`=%s" for col, _o, _n in diffs)
                vals = [new_s for _c, _o, new_s in diffs] + [rec["编号"]]
                cur.execute(f"UPDATE `招考公告` SET {sets} WHERE `编号`=%s", vals)

    if not args.dry_run:
        conn.commit()

    print(
        f"\n{'[dry-run] ' if args.dry_run else ''}"
        f"扫描 {len(rows)} 条，改动 {changed_rows} 条 / {changed_cells} 个字段"
        f"（新抽到 {filled}、清空错值 {emptied}）"
    )
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
