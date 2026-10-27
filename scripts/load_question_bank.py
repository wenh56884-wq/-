# scripts/load_question_bank.py
# 职责：把 data/question_bank/*.json 校验后导入 MySQL「面试题库」表，并写导入日志。
# 用法：.venv\Scripts\python.exe scripts\load_question_bank.py [--dry-run]
# 铁律：缺 source_url / source_name / question 的条目一律拒收并记录原因，
#       绝不"先入库再说"——没有出处的题就是幻觉的入口。

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from engine import question_bank as qb  # noqa: E402


def _ddl_statements(sql_path: Path) -> list[str]:
    raw = sql_path.read_text(encoding="utf-8")
    # 去掉整行注释后再按分号切
    lines = [ln for ln in raw.splitlines() if not ln.strip().startswith("--")]
    body = "\n".join(lines)
    return [s.strip() for s in body.split(";") if s.strip()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只校验不写库")
    args = ap.parse_args()

    items = qb.load_bank()
    print("=" * 68)
    print("面试题库导入（题库 RAG）")
    print("=" * 68)
    print(f"语料版本 {qb.QB_VERSION}｜目录 {qb.BANK_DIR}")
    print(f"通过校验 {len(items)} 条")

    rejected: list[dict[str, str]] = []
    if args.dry_run:
        for it in items[:3]:
            print(f"  · {it.id} [{it.family}/{it.qtype}] {it.question[:34]}…")
        print("\n[dry-run] 未写库。")
        return 0

    from scripts.sync_recruit import _connect
    conn = _connect()
    added = updated = 0
    try:
        with conn.cursor() as cur:
            for stmt in _ddl_statements(_ROOT / "db" / "question_bank.sql"):
                cur.execute(stmt)
        with conn.cursor() as cur:
            for it in items:
                if not (it.source_url and it.source_name and it.question):
                    rejected.append({"id": it.id, "reason": "缺少来源或题面"})
                    continue
                cur.execute(
                    "INSERT INTO `面试题库`(`题目编号`,`行业族`,`岗位族`,`题型`,`题目`,`考点`,"
                    "`参考答案要点`,`难度`,`来源名称`,`来源链接`,`采集时间`,`校验状态`,`启用`)"
                    " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'verified',1)"
                    " ON DUPLICATE KEY UPDATE `行业族`=VALUES(`行业族`),`岗位族`=VALUES(`岗位族`),"
                    " `题型`=VALUES(`题型`),`题目`=VALUES(`题目`),`考点`=VALUES(`考点`),"
                    " `参考答案要点`=VALUES(`参考答案要点`),`难度`=VALUES(`难度`),"
                    " `来源名称`=VALUES(`来源名称`),`来源链接`=VALUES(`来源链接`),`启用`=1",
                    (it.id, it.family, it.job_family, it.qtype, it.question,
                     json.dumps(list(it.keywords), ensure_ascii=False),
                     it.answer_hint, it.difficulty, it.source_name, it.source_url,
                     date.today()),
                )
                if cur.rowcount == 1:
                    added += 1
                else:
                    updated += 1
            cur.execute(
                "INSERT INTO `面试题库导入日志`(`语料版本`,`总条数`,`新增`,`更新`,`跳过`,`被拒`,`详情`,`操作人`)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (qb.QB_VERSION, len(items), added, updated, 0, len(rejected),
                 json.dumps({"rejected": rejected}, ensure_ascii=False), "load_question_bank"),
            )
        conn.commit()
    finally:
        conn.close()

    st = qb.stats()
    print(f"新增 {added}｜更新 {updated}｜被拒 {len(rejected)}")
    print("\n行业族 × 题型覆盖：")
    header = "  " + "行业族".ljust(18) + "".join(q[:8].ljust(10) for q in st["qtypes"]) + "小计"
    print(header)
    for fam, info in st["families"].items():
        row = "  " + f"{fam}({info['label'][:6]})".ljust(18)
        row += "".join(str(info["by_qtype"].get(q, 0)).ljust(10) for q in st["qtypes"])
        print(row + str(info["total"]))
    print(f"\n来源 {len(st['sources'])} 个："
          + "、".join(f"{s['name']}({s['count']})" for s in st["sources"][:6]))
    qb.clear_cache()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
