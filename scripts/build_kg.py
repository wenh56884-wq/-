# scripts/build_kg.py
# 职责：构建知识图谱并落盘 JSON + 打印统计（验收/答辩口径来源）。
# 用法：.venv\Scripts\python.exe scripts\build_kg.py

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from engine import kg  # noqa: E402


def main() -> int:
    g = kg.build_graph()
    stats = kg.graph_stats(g)
    path = kg.export_json(g)
    print("=" * 60)
    print("知识图谱构建完成（专业-课程-岗位-技能）")
    print("=" * 60)
    print(f"节点 {stats['nodes']}  边 {stats['edges']}")
    for k, v in sorted(stats["nodes_by_kind"].items()):
        print(f"  节点 {k:8} {v:>5}")
    for k, v in sorted(stats["edges_by_kind"].items(), key=lambda kv: -kv[1]):
        print(f"  边   {k:8} {v:>5}")
    print(f"落盘：{path}")

    # 三大查询演示（用图内真实存在的节点）
    skills = [n.split(":", 1)[1] for n in g.nodes if g.nodes[n]["kind"] == "skill"]
    majors = [n.split(":", 1)[1] for n in g.nodes if g.nodes[n]["kind"] == "major"]
    if skills:
        demo_skill = max(skills, key=lambda s: len(list(g.predecessors(f"skill:{s}"))))
        r = kg.query_jobs_by_skill(g, demo_skill, limit=5)
        print(f"\n[query_jobs_by_skill] {demo_skill} → {r['total']} 个岗位，例："
              + "、".join(i["title"][:16] for i in r["items"][:3]))
    if majors:
        demo_major = majors[0]
        r = kg.query_skills_by_major(g, demo_major)
        print(f"[query_skills_by_major] {demo_major} → {r['course_cnt']} 门课培养 "
              f"{r['total']} 项技能，例：" + "、".join(s["skill"] for s in r["skills"][:5]))
        # explain_path：找该专业对口的第一个岗位
        mn = f"major:{demo_major}"
        job_ids = [v for _, v, d in g.out_edges(mn, data=True) if d.get("kind") == "对口"]
        if job_ids:
            r = kg.explain_path(g, demo_major, int(job_ids[0].split(":", 1)[1]))
            print(f"[explain_path] {demo_major} → 岗位{r['job'][:14]}\n  {r['summary']}")
            for c in r["chain"][:2]:
                print(f"   经 {c['courses']} 学到 {c['skill']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
