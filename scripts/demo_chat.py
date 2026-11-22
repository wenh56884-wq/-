# scripts/demo_chat.py
# 职责：一键演示对话助手的六项能力——ChatBot / RAG / PDF 问答 / 多轮记忆 / 联网 / 工作流。
# 用法：先启动服务（8001）并跑过 seed_chat_demo.py，再
#   .venv\Scripts\python.exe scripts\demo_chat.py
# 说明：演示全程逐字打印后端返回，不做任何美化性改写；未配置的能力会如实显示「不可用」。

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from app.config import get_settings  # noqa: E402

BASE = os.getenv("QH_BASE", "http://127.0.0.1:8001").rstrip("/")
STEP = 0


def _call(method: str, path: str, token: str | None = None, body: dict | None = None):
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "{}")


def step(title: str) -> None:
    global STEP
    STEP += 1
    print(f"\n[{STEP:02d}] {title}")


def ask(token: str, query: str, session_id: int | None = None) -> dict:
    body: dict = {"query": query}
    if session_id:
        body["session_id"] = session_id
    code, data = _call("POST", "/chat", token, body)
    print(f"  问：{query}")
    print(f"  HTTP {code}｜能力={data.get('tool')}｜会话={data.get('session_id')}"
          f"｜降级={data.get('degraded')}")
    for line in str(data.get("answer") or "").splitlines():
        print(f"    {line}")
    cites = data.get("citations") or []
    if cites:
        print(f"  引用 {len(cites)} 条：")
        for c in cites:
            where = f"第 {c['page']} 页" if c.get("page") else (f"第 {c.get('chunk_no')} 块"
                                                                if c.get("chunk_no") else "")
            print(f"    [{c['no']}] {c.get('title')} {where}"
                  + (f"  {c.get('url')}" if c.get("url") else ""))
    return data


def _student_account() -> str:
    import pymysql

    from app.config import get_settings

    s = get_settings()
    conn = pymysql.connect(host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
                           password=s.mysql_password, database=s.mysql_db,
                           charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT `学号` FROM `学生` ORDER BY `学号` LIMIT 1")
            row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        raise SystemExit("库里没有学生账号")
    return str(row["学号"])


def main() -> int:
    account = _student_account()
    demo_password = str(get_settings().demo_password or "").strip()
    demo_accounts = {"AI20230001", "AI20260001", "AI20260004",
                     "AI20250001", "AI20240004"}
    password = demo_password if account in demo_accounts and demo_password else account
    code, body = _call("POST", "/auth/login",
                       body={"role": "student", "account": account, "password": password})
    if code != 200:
        raise SystemExit(f"登录失败：{code} {body}")
    token = body["access_token"]

    step("能力自检：六项能力是否真的就绪")
    code, caps = _call("GET", "/chat/capabilities", token)
    for it in caps.get("items") or []:
        print(f"  [{'可用' if it['ready'] else '未就绪'}] {it['name']} —— {it['detail']}")

    step("ChatBot：寒暄不触发任何取数")
    ask(token, "你好，你能做什么？")

    step("RAG 企业知识库：问制度，回答必须带引用")
    first = ask(token, "报销的住宿标准是多少？")
    sid = first.get("session_id")

    step("多轮对话记忆：同一会话里追问，沿用上一轮能力")
    ask(token, "那超标了怎么办？", session_id=sid)

    step("PDF 文档问答：引用精确到页码")
    ask(token, "知识库里那份 PDF 说的 hotel cap per night 是多少？")

    step("联网搜索：没配密钥就明说没有联网能力（不编结果）")
    ask(token, "联网搜一下重庆 2026 届秋招政策")

    step("工作流自动化：一句话跑多步流程")
    ask(token, "跑一遍求职体检")

    step("会话留痕：回看这一场的历史与引用")
    code, detail = _call("GET", f"/chat/sessions/{sid}", token)
    msgs = detail.get("messages") or []
    print(f"  HTTP {code}｜消息 {len(msgs)} 条")
    for m in msgs:
        tag = m.get("tool") or "-"
        print(f"    {m['role']:9s} [{tag}] {str(m['text'])[:46].replace(chr(10), ' / ')}")

    step("知识库规模与命中率自检")
    code, stats = _call("GET", "/kb/stats", token)
    print(f"  文档 {stats.get('docs')} 份｜分块 {stats.get('chunks')} 个｜"
          f"页数 {stats.get('pages')}｜类型 {stats.get('by_type')}")
    code, hits = _call("GET", "/kb/search?q=" + urllib.parse.quote("年假有几天"), token)
    print(f"  检索「年假有几天」→ {hits.get('total')} 条命中")
    for c in (hits.get("citations") or [])[:2]:
        print(f"    [{c['no']}] {c['title']} 第 {c.get('page') or c.get('chunk_no')} 段："
              f"{c['snippet'][:40]}")

    print("\n演示结束。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
