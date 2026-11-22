# -*- coding: utf-8 -*-
"""面试实验室第三批（岗位就绪度 / 面试官视角）自检：直调路由函数，不起 HTTP。

用法：.venv\\Scripts\\python.exe scripts\\verify_lab2.py [student_id]
"""
from __future__ import annotations

import json
import sys

sys.path.insert(0, r"D:\qihang")

from agents.tools import ToolContext
from app.routers import interview_lab as lab
from app.routers.interview import _conn


def show(name: str, fn):
    try:
        r = fn()
        print(f"[OK] {name}  len={len(json.dumps(r, ensure_ascii=False))}")
        return r
    except Exception as exc:  # noqa: BLE001 - 自检脚本要看到全部失败
        print(f"[FAIL] {name}: {type(exc).__name__}: {exc}")
        return None


def main() -> None:
    stu = int(sys.argv[1]) if len(sys.argv) > 1 else 3701
    ctx = ToolContext(actor_type="student", tenant_id=1, student_id=stu)

    jobs = show("readiness/jobs q=数据", lambda: lab.readiness_jobs("数据", 8, ctx))
    if jobs and jobs.get("items"):
        for j in jobs["items"][:5]:
            print(f"    {j['job_id']:>5}  {j['title'][:20]:<22} {j['city'] or '-':<6} {j['skills'][:3]}")
        jid = jobs["items"][0]["job_id"]
        r = show("readiness", lambda: lab.readiness(lab.ReadinessIn(job_id=jid), ctx))
        if r:
            print(f"    就绪度 {r['readiness']} / {r['level']} {r['level_label']}")
            print(f"    五态 {r['counts']}")
            for it in r["items"][:8]:
                print(f"      [{it['status']:<8}] {it['skill'][:14]:<16} "
                      f"课={str(it['course'])[:14]:<16} 分={it['score']} 简历={'写' if it['in_resume'] else '没写'}")
            for h in r.get("hidden_assets") or []:
                print(f"    ★ 埋没: {h['skill']} ← 《{h['course']}》{h['score']}")
                print(f"      建议: {h['suggestion'][:90]}")
            for g in (r.get("gaps") or [])[:3]:
                print(f"    gap: {g['skill']} [{g['how']}] {g['fix'][:60]}")
            print(f"    追问: {(r.get('interview_hooks') or ['-'])[0][:70]}")
            print(f"    结论: {r['narrative'][:150]}")

    cases = show("calibration/cases", lambda: lab.calibration_cases(None, ctx))
    if cases and cases.get("items"):
        sid = cases["session_id"]
        print(f"    会话 {sid} / {cases['job_title']} / {len(cases['items'])} 题")
        first = cases["items"][0]
        print(f"    题1: {first['question'][:60]}")
        for c in first["candidates"]:
            print(f"      {c['id']:<7} {len(c['answer']):>3}字  {c['answer'][:70]}")
        # 故意把 talker 排第一，看诊断能不能识别
        ranks = []
        for i, it in enumerate(cases["items"]):
            order = {"talker": 1, "doer": 3, "vague": 2}
            for c in it["candidates"]:
                ranks.append({"round": it["round"], "id": c["id"], "rank": order[c["id"]]})
        j1 = show("judge(故意排错)", lambda: lab.calibration_judge(
            lab.CalibrationJudgeIn(session_id=sid, ranks=ranks), ctx))
        if j1:
            print(f"    accuracy={j1['accuracy']} level={j1['level']} {j1['level_label']}")
            for b in j1["biases"]:
                print(f"    偏误 [{b['label']}] {b['detail'][:80]}")
            for s in j1["insights"][:3]:
                print(f"    洞察: {s[:90]}")
            print(f"    练习: {j1['next_drill'][:80]}")
            for it in j1["items"]:
                print(f"    题{it['round']} 判定: {it.get('verdict', '')[:70]}")
                for c in sorted(it["candidates"], key=lambda x: (x.get("standard_rank") or 9)):
                    print(f"      {c['label']:<4} 标准{c['standard']:>6} 名次{c['standard_rank']} "
                          f"你的{c['my_rank']} dims={ {k: round(v, 1) for k, v in (c.get('dims') or {}).items()} }")

        # 正确排序 → 应该 accuracy=100
        ranks2 = [{"round": it["round"], "id": c["id"], "rank": c["standard_rank"]}
                  for it in (j1 or {}).get("items", []) for c in it.get("candidates", [])
                  if c.get("standard_rank")]
        if ranks2:
            j2 = show("judge(全对)", lambda: lab.calibration_judge(
                lab.CalibrationJudgeIn(session_id=sid, ranks=ranks2), ctx))
            if j2:
                print(f"    accuracy={j2['accuracy']} level={j2['level']} biases={len(j2['biases'])}")

        show("judge(空排序)", lambda: lab.calibration_judge(
            lab.CalibrationJudgeIn(session_id=sid, ranks=[]), ctx))


if __name__ == "__main__":
    main()
