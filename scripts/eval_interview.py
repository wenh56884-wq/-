# scripts/eval_interview.py
# 职责：模拟面试官离线评测（≥20 条，计划书 P0 验收项）。
#   A. 提纲覆盖：案例期望的题型必须出现在提纲里（核心场景通过率，目标 ≥85%）
#   B. 防虚构拦截：编造引文的点评必须 100% 被 verify_comment 拒绝
#   C. 引文放行：真实引文的点评必须 100% 通过（不误伤）
#   D. 评分一致性：同一输入跑两遍，逐 case 评分与提纲完全一致（确定性，目标 ≥95%，实为 100%）
#   E. 差距核对：期望的差距维度必须出现
# 离线运行（不依赖 MySQL / LLM）：
#   .venv\Scripts\python.exe scripts\eval_interview.py

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from engine.interview import (
    build_outline,
    diagnose,
    gap_list,
    parse_resume,
    rubric_of,
    score_answer,
    verify_comment,
)

CASES_PATH = _ROOT / "data" / "eval" / "interview_cases.json"
PASS_THRESHOLD_COVERAGE = 0.85   # 核心场景通过率目标
PASS_THRESHOLD_CONSIST = 0.95    # 评分一致性目标


def _resume_from_text(text: str) -> dict:
    return parse_resume(text)


def main() -> int:
    data = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    cases = data["cases"]
    n_ok = {"outline": 0, "fabricated_reject": 0, "valid_accept": 0, "consistency": 0, "gap": 0}
    n_valid_denom = 0  # 合法引文分母：仅统计能构造出引文的案例
    failures: list[str] = []

    for case in cases:
        cid = case["id"]
        resume = _resume_from_text(case["resume_text"])
        job = case["job"]

        # A. 提纲覆盖
        outline = build_outline(job, resume)
        types = [o["type"] for o in outline]
        want = case.get("expect_outline_has")
        if want is None:
            ok_a = True  # 空简历等案例不强制题型
        else:
            ok_a = want in types
        n_ok["outline"] += ok_a
        if not ok_a:
            failures.append(f"{cid} 提纲缺 {want}，实际 {types}")

        # B/C. 防虚构：编造引文必须拒；真实引文必须过
        # 评测集里的回答都是针对「项目深挖」题写的 → 取该题的 rubric 评分
        answer = case.get("answer")
        item = None
        if answer:
            proj = next((o for o in outline if o["type"] == "project"), outline[0])
            item = score_answer(answer, rubric_of(proj["type"], job["skill_tags"]),
                                [case["resume_text"]])
        ok_b, _ = verify_comment(data["fabricated_comment_probe"], answer or "",
                                 [case["resume_text"]])
        n_ok["fabricated_reject"] += (not ok_b)
        if ok_b:
            failures.append(f"{cid} 编造引文未被拦截")

        if answer and item:
            hits = list(item.get("keyword_hits") or [])
            missed = list(item.get("keyword_missed") or [])
            # 「」只能包回答里逐字存在的片段；要点词不是引文，放句子外面
            quote = next((h for h in hits if h in answer), None)
            if quote:
                n_valid_denom += 1
                tail = []
                if missed:
                    tail.append("漏掉了" + "、".join(missed[:2]))
                tail.append("建议用 STAR 结构补充结果与数字")
                tail.append(f"本题得分 {item['score']}。")
                valid = f"你回答提到「{quote}」，讲清了做法；{'；'.join(tail)}"
                ok_c, bad = verify_comment(valid, answer, [case["resume_text"]])
                n_ok["valid_accept"] += ok_c
                if not ok_c:
                    failures.append(f"{cid} 合法引文被误伤：{bad}")

        # D. 一致性：重跑一遍提纲+评分，逐字段比对
        outline2 = build_outline(job, resume)
        item2 = None
        if answer:
            proj2 = next((o for o in outline2 if o["type"] == "project"), outline2[0])
            item2 = score_answer(answer, rubric_of(proj2["type"], job["skill_tags"]),
                                 [case["resume_text"]])
        same = (outline == outline2 and
                (item or {}).get("score") == (item2 or {}).get("score"))
        n_ok["consistency"] += same
        if not same:
            failures.append(f"{cid} 两次运行结果不一致（确定性被破坏）")

        # E. 差距维度
        gaps = gap_list(resume, job, [item] if item else None, outline)
        want_dim = case.get("expect_gap_dim")
        if want_dim:
            ok_e = any(g["dimension"] == want_dim for g in gaps)
            n_ok["gap"] += ok_e
            if not ok_e:
                failures.append(f"{cid} 差距缺维度 {want_dim}，实际 {[g['dimension'] for g in gaps]}")
        else:
            ok_e = True

        # 附带：诊断不抛异常且可序列化（冒烟）
        diagnose(resume, job)

    total = len(cases)
    print("=" * 64)
    print(f"模拟面试官离线评测（{total} 条）")
    print("=" * 64)
    rows = [
        ("提纲覆盖", n_ok["outline"], total, PASS_THRESHOLD_COVERAGE),
        ("防虚构拦截（编造引文 100% 拒绝）", n_ok["fabricated_reject"], total, 1.0),
        ("合法引文放行（不误伤）", n_ok["valid_accept"], n_valid_denom, 1.0),
        ("评分一致性（确定性）", n_ok["consistency"], total, PASS_THRESHOLD_CONSIST),
        ("差距维度核对", n_ok["gap"], sum(1 for c in cases if c.get("expect_gap_dim")), 1.0),
    ]
    hard_fail = False
    for name, ok, tot, th in rows:
        rate = ok / tot if tot else 1.0
        flag = "PASS" if rate >= th else "FAIL"
        if flag == "FAIL":
            hard_fail = True
        print(f"  [{flag}] {name:32} {ok:>2}/{tot:<2} = {rate:.1%}（目标 ≥{th:.0%}）")
    if failures:
        print("\n失败明细：")
        for f in failures[:20]:
            print("  -", f)
    return 1 if hard_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
