# scripts/eval_hybrid.py
# 职责：混合推荐离线评测（20 名学生，precision@10 粗估，计划书 P0/P2 验收项）。
# 口径：
#   正样本 = 该生「收藏(favorite)」过的岗位（真实行为，非编造）；
#   候选池 = load_jobs(方向) ∪ 该生收藏岗位（保证正样本可达，三组共用同一池，公平）；
#   留一法 = 计算该生行为向量时剔除收藏岗位，避免自己泄露答案；
#   对比 = 纯内容(A) / 纯协同(B) / 混合(0.7A+0.3B)，同一 top10 截断；
#   precision@10 = |top10 ∩ 收藏集| / min(10, |收藏集|)。
# 用法：.venv\Scripts\python.exe scripts\eval_hybrid.py [--n 20]

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from engine import hybrid, recommend  # noqa: E402

TERM = "2025-2026-2"
TENANT = 1
OUT_PATH = _ROOT / "data" / "eval" / "hybrid_eval.json"


def _pick_students(n: int) -> list[dict]:
    """挑收藏数 ≥5、有成绩的学生（收藏是强正样本，行为足够才可评测）。"""
    return recommend._query(
        "SELECT s.`编号` AS sid, s.`学号` AS no, s.`专业` AS major, COUNT(b.`编号`) AS fav_cnt"
        " FROM `学生` s"
        " JOIN `岗位浏览日志` b ON b.`学生编号` = s.`编号` AND b.`动作` = 'favorite'"
        " JOIN `成绩` sc ON sc.`学生编号` = s.`编号` AND sc.`学期` = %s"
        " WHERE s.`租户编号` = %s"
        " GROUP BY s.`编号`, s.`学号`, s.`专业`"
        " HAVING COUNT(b.`编号`) >= 5"
        " ORDER BY s.`编号` LIMIT %s",
        (TERM, TENANT, n),
    )


def _jobs_by_ids(ids: list[int]) -> list[dict]:
    if not ids:
        return []
    id_list = ",".join(str(int(i)) for i in ids)
    rows = recommend._query(
        "SELECT `编号` AS id, `岗位名称` AS title, `企业` AS company, `城市` AS city,"
        " `最低薪资` AS salary_min, `最高薪资` AS salary_max, `学历` AS education,"
        " `最低经验` AS exp_min, `最高经验` AS exp_max, `技能标签` AS skill_tags"
        f" FROM `岗位` WHERE `编号` IN ({id_list})",
        (),
    )
    out = []
    for r in rows:
        tags = recommend.clean_skill_tags(r.get("skill_tags"))
        r["skill_tags"] = tags
        r["direction"] = recommend.direction_of(" ".join([str(r.get("title") or "")] + tags))
        out.append(r)
    return out


def _precision(top: list[int], truth: set[int], k: int = 10) -> float:
    if not truth:
        return 0.0
    hit = len(set(top[:k]) & truth)
    return round(hit / min(k, len(truth)), 4)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="混合推荐离线评测 precision@10")
    ap.add_argument("--n", type=int, default=20)
    args = ap.parse_args(argv)

    students = _pick_students(args.n)
    if not students:
        print("没有满足条件的评测学生（需收藏≥5 且有本学期成绩）")
        return 1

    rows = []
    print("=" * 92)
    print(f"混合推荐离线评测：{len(students)} 名学生，留一法，precision@10")
    print("=" * 92)
    print(f"{'学号':<12}{'专业':<16}{'收藏':>4}{'邻居':>5}"
          f"{'A内容':>8}{'B协同':>8}{'混合':>8}{'随机':>8}")
    for st in students:
        no, sid = str(st["no"]), int(st["sid"])
        student = recommend.load_student(TENANT, no, TERM)
        fav_rows = recommend._query(
            "SELECT `岗位编号` AS jid FROM `岗位浏览日志`"
            " WHERE `学生编号`=%s AND `动作`='favorite'", (sid,))
        truth = {int(r["jid"]) for r in fav_rows}
        if not truth:
            continue

        jobs = recommend.load_jobs(student["directions"])
        have = {int(j["id"]) for j in jobs}
        extra = sorted(truth - have)
        jobs += _jobs_by_ids(extra)
        ids = [int(j["id"]) for j in jobs]

        # 行为向量：全部行为剔除收藏（留一法）
        beh = recommend._query(
            "SELECT `岗位编号` AS jid, SUM(CASE WHEN `动作`='favorite' THEN 3 ELSE 1 END) AS w"
            " FROM `岗位浏览日志` WHERE `学生编号`=%s GROUP BY `岗位编号`", (sid,))
        my_vec = {int(r["jid"]): float(r["w"]) for r in beh if int(r["jid"]) not in truth}

        nids = hybrid._neighbor_ids(TENANT, TERM, str(student.get("major") or ""),
                                    student.get("gpa"), sid)
        neigh = hybrid._behavior_vectors(TENANT, TERM, nids, ids)
        cf = hybrid.cf_scores(my_vec, neigh, ids)

        scored = [recommend.score_job(student, j) for j in jobs]
        a_max = max((s["final_score"] for s in scored), default=1.0) or 1.0

        a_rank = sorted(scored, key=lambda x: (-x["final_score"], x["job_id"]))[:10]
        b_rank = sorted(scored,
                        key=lambda x: (-(cf.get(x["job_id"]) or 0.0), x["job_id"]))[:10]

        def mix_rank(wc: float, wf: float) -> list[int]:
            return [x["job_id"] for x in sorted(
                scored,
                key=lambda x: (-(wc * x["final_score"] / a_max + wf * (cf.get(x["job_id"]) or 0.0)),
                               x["job_id"]))[:10]]

        h_rank = mix_rank(0.7, 0.3)
        h50 = mix_rank(0.5, 0.5)
        h30 = mix_rank(0.3, 0.7)

        pa = _precision([x["job_id"] for x in a_rank], truth)
        pb = _precision([x["job_id"] for x in b_rank], truth)
        ph = _precision(h_rank, truth)
        # 随机基线：从同一候选池随机取 10 个的期望命中率 = 10·|truth|/|pool|
        rand_base = round(min(1.0, 10 * len(truth) / max(1, len(jobs))) / max(1, min(10, len(truth))), 4)
        rows.append({"student_no": no, "major": st["major"], "fav": len(truth),
                     "neighbors": len(neigh), "pool": len(jobs),
                     "p_at_10_content": pa, "p_at_10_cf": pb, "p_at_10_hybrid": ph,
                     "p_at_10_hybrid_5050": _precision(h50, truth),
                     "p_at_10_hybrid_3070": _precision(h30, truth),
                     "p_at_10_random": rand_base})
        print(f"{no:<12}{str(st['major'] or '')[:14]:<16}{len(truth):>4}{len(neigh):>5}"
              f"{pa:>8.2f}{pb:>8.2f}{ph:>8.2f}{rand_base:>8.2f}")

    def mean(key: str) -> float:
        return round(sum(r[key] for r in rows) / len(rows), 4) if rows else 0.0

    base = mean("p_at_10_random")
    summary = {"students": len(rows),
               "p_at_10_content": mean("p_at_10_content"),
               "p_at_10_cf": mean("p_at_10_cf"),
               "p_at_10_hybrid": mean("p_at_10_hybrid"),
               "p_at_10_hybrid_5050": mean("p_at_10_hybrid_5050"),
               "p_at_10_hybrid_3070": mean("p_at_10_hybrid_3070"),
               "p_at_10_random": base,
               "lift_cf_vs_random": round(mean("p_at_10_cf") / base, 2) if base else None,
               "lift_hybrid_vs_random": round(mean("p_at_10_hybrid") / base, 2) if base else None}
    print("-" * 100)
    print(f"均值：纯内容 {summary['p_at_10_content']:.4f} | "
          f"纯协同 {summary['p_at_10_cf']:.4f} | "
          f"混合 {summary['p_at_10_hybrid']:.4f} | "
          f"随机基线 {base:.4f}")
    if base:
        print(f"相对随机基线提升：协同 {summary['lift_cf_vs_random']}×，"
              f"混合 {summary['lift_hybrid_vs_random']}×")
    print(f"权重敏感性（内容/协同）：0.7/0.3 → {summary['p_at_10_hybrid']:.4f} | "
          f"0.5/0.5 → {summary['p_at_10_hybrid_5050']:.4f} | "
          f"0.3/0.7 → {summary['p_at_10_hybrid_3070']:.4f}")
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps({"term": TERM, "summary": summary, "rows": rows},
                                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"明细落盘：{OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
