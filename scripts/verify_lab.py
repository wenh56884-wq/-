# -*- coding: utf-8 -*-
"""面试实验室自检：不启 HTTP，直接调路由函数，验证七个接口能出真实数据。

用法：.venv\\Scripts\\python.exe scripts\\verify_lab.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.tools import ToolContext
from app.routers import interview_lab as lab
from app.routers.interview import _conn

c = _conn()
cur = c.cursor()
cur.execute("SELECT s.`编号`, s.`学生编号`, s.`岗位名称`, s.`总分`, COUNT(q.`编号`) n "
            "FROM `面试会话` s LEFT JOIN `面试问答` q ON q.`会话编号`=s.`编号` "
            "WHERE s.`状态`='finished' GROUP BY s.`编号` HAVING n>=3 ORDER BY n DESC LIMIT 5")
rows = cur.fetchall()
c.close()
if not rows:
    print("没有可用的已完成面试样本")
    raise SystemExit(1)
for r in rows:
    print("候选:", r)

first = rows[0]
sid = int(first["编号"])
ctx = ToolContext(actor_type="student", tenant_id=1, student_id=int(first["学生编号"]))
print(f"\n>>> 测试会话 {sid} / {first['岗位名称']} / {first['总分']} 分 / {first['n']} 题\n")


def show(name, fn, limit=760):
    try:
        r = fn()
        s = json.dumps(r, ensure_ascii=False, default=str)
        print(f"[OK] {name}  len={len(s)}")
        print(s[:limit], "\n")
        return r
    except Exception as exc:  # noqa: BLE001 - 自检脚本要暴露全部异常
        print(f"[FAIL] {name}: {type(exc).__name__}: {exc}\n")
        return None


show("panel", lambda: lab.panel_review(sid, False, ctx))
show("attribution", lambda: lab.attribution(sid, ctx))
show("peer", lambda: lab.peer_bench(sid, ctx))
show("report-card", lambda: lab.report_card(sid, ctx))
show("passport", lambda: lab.passport(None, ctx))
show("shadow", lambda: lab.shadow_items(sid, ctx))
show("expression", lambda: lab.expression(lab.ExpressionIn(
    text="嗯，首先我觉得这个项目主要是做数据治理，然后就是我们把数据清洗了一遍，对吧。"
         "其次我们做了指标体系，最后把报表自动化了。",
    duration_sec=25.0), ctx))

print("\n=== 群面引擎（离线，不调模型）===")
from engine import group as g  # noqa: E402

topic = g.make_topic("数据分析岗", "互联网", ["SQL", "数据治理", "可视化"])
print("topic:", json.dumps(topic, ensure_ascii=False))
state = {"version": g.GROUP_VERSION, "topic": topic, "turns": [], "student_turns": [], "elapsed_turns": 0}
op = g.opening(topic)
state["turns"].append(op["first_turn"])
state = g.student_turn(state, "我觉得应该先看成本，再从风险和效率两个维度拆，最后统一到一条建议。")["state"]


def fake_speak(system: str, user: str) -> str:
    return "我补充一点，同类项目通常 3 人 2 周，成本口径要先对齐。"


for cand in g.CANDIDATES:
    state = g.ai_turn(state, cand["id"], fake_speak)["state"]
print("turns:", len(state["turns"]))
print("evaluate:", json.dumps(g.evaluate(state), ensure_ascii=False)[:900])
