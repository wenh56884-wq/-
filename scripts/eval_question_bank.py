# scripts/eval_question_bank.py
# 职责：题库 RAG 的离线评测——可回溯率 / 职位覆盖率 / 检索命中率 / 题面一致率。
# 用法：.venv\Scripts\python.exe scripts\eval_question_bank.py
# 结果落 data/eval/question_bank_eval.json（数字如实记录，不美化）。

from __future__ import annotations

import json
import random
import sys
from collections import Counter
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from engine import question_bank as qb  # noqa: E402
from engine.interview import build_outline  # noqa: E402

OUT = _ROOT / "data" / "eval" / "question_bank_eval.json"

# 判定「题库命中」的门槛：一场 6 轮面试至少 4 轮来自题库，
# 否则说明这个行业族覆盖不足，用户会退回到模板题。
MIN_BANK_ROUNDS = 4

_PROBE_RESUME = {
    "skills": ["Python", "MySQL"], "courses": ["数据分析基础"],
    "educations": [{"school": "重庆财经学院", "major": "软件工程"}],
    "experiences": [{"type": "project", "name": "课程设计-图书管理系统", "desc": "负责后端"}],
    "self": "踏实肯学",
}


def _jobs() -> list[dict]:
    """从真实岗位库抽样（按行业分层，每行业最多 40 条，保证覆盖到长尾行业）。"""
    from scripts.sync_recruit import _connect
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT `岗位名称`,`行业`,`技能标签` FROM `岗位`")
            rows = cur.fetchall()
    finally:
        conn.close()

    by_industry: dict[str, list[dict]] = {}
    for name, industry, tags in rows:
        try:
            skills = json.loads(tags) if isinstance(tags, str) and tags else []
        except Exception:
            skills = []
        by_industry.setdefault(industry or "", []).append(
            {"title": name, "industry": industry, "skill_tags": skills[:8]})
    out: list[dict] = []
    for industry, group in by_industry.items():
        out.extend(group[:40])
    return out


def main() -> int:
    items = qb.load_bank()
    st = qb.stats()

    # 1) 可回溯率：每条都必须有可打开的来源链接
    traceable = sum(1 for it in items if it.source_url.startswith("http"))
    trace_rate = traceable / len(items) if items else 0.0

    # 2) 覆盖矩阵：有题的 (族, 题型) 格子 / 全部格子（不含 general 行）
    families = [f for f in st["families"] if f != "general"]
    cells = [(f, q) for f in families for q in qb.QTYPES]
    filled = sum(1 for f, q in cells if st["families"][f]["by_qtype"].get(q, 0) > 0)
    cover_rate = filled / len(cells) if cells else 0.0

    # 3) 职位覆盖率：岗位库里有多少岗位能落到「有专项题库」的行业族
    jobs = _jobs()
    with_bank = {f for f in families if st["families"][f]["total"] > 0}
    # 行业为空/认不出时按岗位名推断（与线上 build_outline 的检索口径一致）
    fam_of = [qb.infer_family(j) for j in jobs]
    job_cover = sum(1 for f in fam_of if f in with_bank) / len(jobs) if jobs else 0.0
    fam_dist = Counter(fam_of)

    # 4) 检索命中率：抽样 200 个岗位，看一场面试有几轮来自题库
    random.seed(20261027)
    sample = random.sample(jobs, min(200, len(jobs)))
    hit_rounds: list[int] = []
    zero_rounds = 0
    for j in sample:
        outline = build_outline(j, _PROBE_RESUME, max_rounds=6)
        n = sum(1 for o in outline if o["source"]["kind"] == "bank")
        hit_rounds.append(n)
        if n == 0:
            zero_rounds += 1
    passed = sum(1 for n in hit_rounds if n >= MIN_BANK_ROUNDS)
    hit_rate = passed / len(sample) if sample else 0.0
    avg_rounds = sum(hit_rounds) / len(hit_rounds) if hit_rounds else 0.0

    # 5) 题面一致率：提纲里引用的题库原文必须能在语料里逐字找到
    by_id = {it.id: it for it in items}
    checked = matched = 0
    for j in sample[:60]:
        for o in build_outline(j, _PROBE_RESUME, max_rounds=6):
            src = o["source"]
            if src.get("kind") != "bank":
                continue
            checked += 1
            raw = src.get("question_raw") or ""
            if src["id"] in by_id and raw and raw == by_id[src["id"]].question:
                matched += 1
    fidelity = matched / checked if checked else 0.0

    result = {
        "evaluated_at": date.today().isoformat(),
        "version": qb.QB_VERSION,
        "bank": {"total": len(items), "families": len(st["families"]),
                 "sources": len(st["sources"]), "by_qtype": dict(
                     Counter(it.qtype for it in items))},
        "metrics": {
            "traceable_rate": round(trace_rate, 4),
            "matrix_cover_rate": round(cover_rate, 4),
            "job_cover_rate": round(job_cover, 4),
            "retrieval_hit_rate": round(hit_rate, 4),
            "question_fidelity": round(fidelity, 4),
            "avg_bank_rounds": round(avg_rounds, 2),
        },
        "detail": {
            "matrix_cells": f"{filled}/{len(cells)}",
            "jobs_sampled": len(jobs),
            "jobs_with_bank_family": round(job_cover * len(jobs)),
            "probe_sample": len(sample),
            "probe_zero_bank_rounds": zero_rounds,
            "fidelity_checked": checked,
            "family_distribution": {qb.family_label(k) if k in qb.FAMILY_LABELS else k: v
                                    for k, v in fam_dist.most_common()},
        },
        "thresholds": {"min_bank_rounds_per_interview": MIN_BANK_ROUNDS},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 70)
    print("题库 RAG 离线评测")
    print("=" * 70)
    print(f"语料 {len(items)} 条｜行业族 {len(st['families'])}｜来源 {len(st['sources'])}")
    print(f"题型分布 {result['bank']['by_qtype']}")
    print()
    m = result["metrics"]
    print(f"可回溯率（有来源链接）       {m['traceable_rate']:.2%}")
    print(f"覆盖矩阵（族×题型有题占比）   {m['matrix_cover_rate']:.2%}  ({result['detail']['matrix_cells']})")
    print(f"职位覆盖率（岗位落到有题库族）{m['job_cover_rate']:.2%}  ({result['detail']['jobs_with_bank_family']}/{len(jobs)})")
    print(f"检索命中率（≥{MIN_BANK_ROUNDS}轮来自题库）{m['retrieval_hit_rate']:.2%}  (样本 {len(sample)})")
    print(f"平均题库轮次                {m['avg_bank_rounds']:.2f} / 6")
    print(f"题面一致率（逐字对齐语料）    {m['question_fidelity']:.2%}  (校验 {checked} 条)")
    print(f"完全拿不到题库题的岗位       {zero_rounds} / {len(sample)}")
    print()
    print("行业分布（岗位库按族）：")
    for label, cnt in result["detail"]["family_distribution"].items():
        print(f"  {label:34s} {cnt:>5}")
    print(f"\n落盘：{OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
