"""AI 对话的导出意图测试：确认「下载」类提问得到引导而不是「不支持」。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)


def login(role: str, account: str) -> str:
    r = client.post("/auth/login", json={"role": role, "account": account,
                                         "password": "123456h"})
    assert r.status_code == 200, r.text[:200]
    return r.json()["access_token"]


def ask(token: str, query: str) -> dict:
    r = client.post("/chat", json={"query": query, "term": "2025-2026-2"},
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
    return r.json()


def show(label: str, data: dict) -> None:
    ans = (data.get("answer") or "").replace("\n", " ")
    print(f"\n[{label}]")
    print(f"  tool={data.get('tool')} | draft_mode={data.get('draft_mode')} "
          f"| degraded={data.get('degraded')}")
    print(f"  answer: {ans[:220]}")


def main() -> None:
    t = login("teacher", "T001")
    s = login("student", "AI20230001")

    # 1. 截图里那句原话
    show("教师：把我学生的数据下载一份文档出来", ask(t, "把我学生的数据下载一份文档出来"))
    # 2. 其他说法
    show("教师：导出班级学生名单", ask(t, "导出 AI2301 班的学生名单"))
    show("教师：成绩能存成表格吗", ask(t, "这个班成绩能存成表格吗"))
    # 3. 学生端
    show("学生：下载我的成绩单", ask(s, "帮我把成绩单下载下来"))

    # 4. 回归：普通问题不能被导出分支吃掉
    show("回归：我这学期成绩怎么样", ask(s, "我这学期成绩怎么样"))


if __name__ == "__main__":
    main()
