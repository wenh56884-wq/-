# scripts/seed_approval_demo.py
# 职责：造一条「工作流审批」演示数据——需审批的求职体检流程 + 一张学生提交的待审单。
# 依赖：fastapi.testclient / app.main（走真实接口，鉴权、快照、审计与线上一致）。
# 说明：幂等；重复执行只会在没有待审单时补交一张，不会重复造单。
# 用法：
#   .venv\Scripts\python.exe scripts\seed_approval_demo.py
#   教师登录后打开「工作流审批」即可看到；点“通过”才会真正用学生身份跑两步工具。

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402

WORKFLOW_NAME = "求职体检（审批演示）"
WORKFLOW_DESC = "学生提交后先挂起，教师通过才执行：本人预警 → 本人岗位推荐。"
STEPS = [
    {"id": "warning", "tool": "my_warning", "title": "本人学业预警", "args": {}},
    {"id": "recommend", "tool": "my_recommendations", "title": "本人岗位推荐",
     "args": {"top_n": 5}},
]


def _login(client: TestClient, role: str, account: str, password: str) -> dict[str, str]:
    resp = client.post("/auth/login", json={"role": role, "account": account,
                                            "password": password})
    if resp.status_code != 200:
        raise SystemExit(f"{role} 登录失败：{resp.status_code} {resp.text[:200]}")
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _pending_has(client: TestClient, headers: dict[str, str]) -> bool:
    resp = client.get("/workflow/approvals/pending", headers=headers)
    if resp.status_code != 200:
        raise SystemExit(f"读取待审列表失败：{resp.status_code} {resp.text[:200]}")
    return any(item.get("name") == WORKFLOW_NAME
               for item in resp.json().get("items") or [])


def main() -> int:
    client = TestClient(create_app())
    teacher = _login(client, "teacher", "T001", "teacher@123")
    student = _login(client, "student", "AI20230001", "AI20230001")

    # 1) 定义（同名则更新）：打开 needs_approval，步骤快照用当前定义
    resp = client.post("/workflow/defs", headers=teacher, json={
        "name": WORKFLOW_NAME, "description": WORKFLOW_DESC,
        "steps": STEPS, "needs_approval": True,
    })
    if resp.status_code != 200:
        raise SystemExit(f"定义工作流失败：{resp.status_code} {resp.text[:300]}")
    def_id = int(resp.json()["id"])
    print(f"[OK] 工作流已就绪：#{def_id} {WORKFLOW_NAME}（需要教师审批）")

    # 2) 已有待审单就不重复提交
    if _pending_has(client, teacher):
        print("[跳过] 已有一张待审单，教师端「工作流审批」可直接看到")
        return 0

    # 3) 学生提交：只挂起，不执行任何步骤
    resp = client.post(f"/workflow/defs/{def_id}/run", headers=student, json={})
    if resp.status_code != 200:
        raise SystemExit(f"提交待审失败：{resp.status_code} {resp.text[:300]}")
    body = resp.json()
    print(f"[OK] 学生已提交：run_id={body.get('run_id')} 状态={body.get('status')} "
          f"步骤数={len(body.get('steps') or [])}")
    print(f"     说明：{body.get('message')}")

    pending = client.get("/workflow/approvals/pending", headers=teacher).json()
    print(f"[OK] 教师待审列表：{pending.get('total')} 条")
    for item in pending.get("items") or []:
        submitter = (item.get("submitted_by") or {}).get("name") or "-"
        print(f"     #{item.get('id')} {item.get('name')} 提交人={submitter}")
    print("\n演示路径：教师登录 → 工作流审批 → 通过（会以提交学生的身份执行两步）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
