# -*- coding: utf-8 -*-
"""线上群面全流程：登录 → start → 两轮 turn → finish。"""
import json, os, time, urllib.request

BASE = os.environ.get("QH_BASE", "http://101.34.254.115")

def call(path, body, token=None):
    data = json.dumps(body).encode()
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())

auth = call("/auth/login", {"role": "student", "account": "AI20230001", "password": "123456h"})
tk = auth["access_token"]

r = call("/interview/lab/group/start", {"job_title": "数据分析岗", "skills": ["SQL", "数据治理", "可视化"]}, tk)
print("start:", r["topic"]["title"], "| gid", r["group_id"], "| turns", len(r["state"]["turns"]))
st = r["state"]

t0 = time.time()
r2 = call("/interview/lab/group/turn", {"state": st, "text": "我先说一个框架：先从成本看，再看风险和效率，最后落到一个可执行建议。"}, tk)
print(f"turn1 ({time.time()-t0:.1f}s) source={r2['source']} ai={r2['ai_turns'][0]['name'] if r2['ai_turns'] else '-'}: {r2['ai_turns'][0]['text'][:60] if r2['ai_turns'] else ''}")
st = r2["state"]

for i in range(2):
    t = time.time()
    r3 = call("/interview/lab/group/turn", {"state": st, "text": ""}, tk)
    st = r3["state"]
    print(f"turn{i+2} ({time.time()-t:.1f}s) source={r3['source']} ai={r3['ai_turns'][0]['name']}: {r3['ai_turns'][0]['text'][:60]}")

ev = call("/interview/lab/group/finish", {"state": st}, tk)
print("\nrole:", ev["role"]["label"], "|", ev["role"]["reason"][:70])
print("metrics:", ev["metrics"])
print("scores:", ev["scores"])
print("drill:", ev["next_drill"])
