# scripts/demo_interview.py — 面试模块端到端演示（需先启动后端）
"""模拟面试官端到端演示：登录 → 简历 → 诊断 → 开局 → 多轮作答 → 报告。

前置：后端已启动（默认 http://127.0.0.1:8001，可用环境变量 DEMO_BASE 覆盖）。
用法：python scripts/demo_interview.py
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.sync_recruit import _connect  # noqa: E402

BASE = os.getenv("DEMO_BASE", "http://127.0.0.1:8001").rstrip("/")

conn = _connect()
with conn.cursor() as cur:
    cur.execute('SELECT `学号` FROM `学生` ORDER BY `学号` LIMIT 1')
    acc = cur.fetchone()[0]
conn.close()

body = json.dumps({"account": acc, "password": acc, "role": "student"}).encode()
req = urllib.request.Request(BASE + "/auth/login", data=body,
                             headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=15) as r:
    tok = json.loads(r.read().decode())["access_token"]
H = {"Content-Type": "application/json", "Authorization": "Bearer " + tok}


def call(method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers=H, method=method)
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


RESUME_TEXT = """教育经历
重庆财经学院｜大数据管理与应用｜2023.09-2027.06
技能证书
CET-6 568
Python、MySQL、Hive
实践经历
电商用户行为分析平台｜负责数据清洗与报表，处理100万条数据，产出12张报表
自我评价
踏实肯学，喜欢钻研数据"""

# 1. 解析
s, d = call("POST", "/interview/resume/parse", {"text": RESUME_TEXT})
print("1.解析", s, "技能", d["parsed"]["skills"], "经历", d["parsed"]["experiences"][0]["name"][:14])

# 2. 保存
s, d = call("POST", "/interview/resume", {
    "self_eval": "踏实肯学", "intent": "数据分析",
    "educations": [{"school": "重庆财经学院", "major": "大数据管理与应用",
                    "dates": "2023.09-2027.06", "courses": ["数据库原理", "统计学"]}],
    "skills": [{"type": "skill", "name": "Python"}, {"type": "skill", "name": "MySQL"},
               {"type": "skill", "name": "Hive"}, {"type": "cert", "name": "CET-6", "level": "568"}],
    "experiences": [{"type": "project", "name": "电商用户行为分析平台", "role": "数据处理",
                     "dates": "2025.03-2025.06",
                     "desc": "负责数据清洗与报表，处理100万条数据，产出12张报表"}]})
print("2.保存", s, d)
rid = d["resume_id"]

# 3. 诊断
s, d = call("GET", "/interview/resume/diagnosis?job_id=1")
print("3.诊断", s, "问题", len(d.get("issues", [])), [i["kind"] for i in d.get("issues", [])][:4])

# 4. 岗位池
s, d = call("GET", "/interview/jobs?limit=5")
print("4.岗位池", s, d["total"], [i["title"][:12] for i in d["items"][:3]])
jid = d["items"][0]["id"] if d["items"] else None

# 5. 开局
s, d = call("POST", "/interview/start", {"job_id": jid})
print("5.开局", s, "round", d.get("round"), "type", d.get("question_type"))
print("   Q:", (d.get("question") or "")[:60])
sid = d["session_id"]

ANSWERS = [
    "我应聘这个岗位是因为它和数据方向一致，我的规划是先打好SQL和Python基础，然后深入业务分析。",
    "我通过数据库原理课程掌握了MySQL，通过统计课程掌握了分析思路，课下自学了Hive并做了练习项目。",
    "在电商用户行为分析平台里，我负责数据清洗与报表，遇到的最大困难是数据质量差，我先写了校验规则，结果处理了100万条数据并产出12张报表。",
    "我会先跟主管确认需求优先级，然后协调数据方给出时间点，同步自己的进度，最后复盘避免再次发生。",
    "我的简历虽然项目不多，但我处理的100万条数据量是真实的，学习能力强，能快速上手岗位技能。",
]
# 6. 逐轮作答
for i, ans in enumerate(ANSWERS, 1):
    s, d = call("POST", f"/interview/{sid}/answer", {"text": ans})
    if d.get("finished"):
        print(f"6.第{i}轮 -> 收卷")
        break
    print(f"6.第{i}轮 得分", d.get("score"), "下一题", (d.get("next") or {}).get("question_type"))
    print("   点评:", (d.get("comment") or "")[:80])
else:
    s, d = call("POST", f"/interview/{sid}/answer", {"text": "我想问问团队的数据栈是什么？"})

# 7. 报告
print("7.总分", d.get("total"), "差距数", len(d.get("gaps") or []))
print("   报告头:", (d.get("report") or "")[:60].replace(chr(10), " / "))
for g in (d.get("gaps") or [])[:3]:
    print("   差距:", g["dimension"], "|", g["gap"][:40])

# 8. 详情与历史
s, d2 = call("GET", f"/interview/{sid}")
print("8.详情", s, "问答数", len(d2.get("qa", [])), "状态", d2["session"]["状态"])
s, d3 = call("GET", "/interview/history/me")
print("9.历史", s, d3["total"], "场")
