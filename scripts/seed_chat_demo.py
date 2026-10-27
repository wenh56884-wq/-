# scripts/seed_chat_demo.py
# 职责：为「知识库 + 多轮记忆 + 工作流」演示准备可复现的数据。
# 用法：先启动服务（8001），再执行
#   .venv\Scripts\python.exe scripts\seed_chat_demo.py
# 说明：幂等——按标题清理旧示例文档再重入；工作流同名覆盖。

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

BASE = os.getenv("QH_BASE", "http://127.0.0.1:8001").rstrip("/")

DOCS = [
    {
        "title": "员工报销制度",
        "source_type": "txt",
        "text": """员工报销制度（2026 版）

一、差旅报销
员工出差前须在 OA 提交出差申请，经直属主管审批后方可出行。交通费按实际发生额报销，
高铁二等座、经济舱为上限。住宿标准：一线城市每晚不超过 500 元，其他城市每晚不超过
350 元，超标部分由个人自理。

二、报销时限
报销单须在费用发生后 30 天内提交，逾期需部门总监签字说明。每月 25 日为当月报销截止日，
25 日之后提交的单据顺延至下月处理。

三、发票要求
必须提供增值税发票原件，抬头为公司全称。餐饮发票需注明事由与参与人数。""",
    },
    {
        "title": "请假与考勤制度",
        "source_type": "txt",
        "text": """请假与考勤制度

一、请假类型
事假：按天扣发当日工资，全年累计不超过 15 天。
病假：需提供二级以上医院证明，病假期间按基本工资的 80% 发放。
年假：入职满一年享 5 天，满三年享 10 天，满五年享 15 天。

二、审批流程
请假 1 天以内由直属主管审批；1 天以上 3 天以内由部门经理审批；超过 3 天须报人力资源部备案。

三、迟到与早退
每月迟到累计超过 3 次，扣发当月全勤奖。迟到超过 60 分钟按半天事假处理。""",
    },
    {
        "title": "采购与付款流程",
        "source_type": "md",
        "text": """# 采购与付款流程

## 一、采购申请
需求部门填写采购申请单，注明用途、预算、供应商比价结果（至少三家）。

## 二、审批权限
- 单笔 5000 元以下：部门经理审批
- 5000 元至 50000 元：分管副总审批
- 50000 元以上：总经理审批，并附董事会授权文件

## 三、付款
验收合格后 15 个工作日内付款。预付款比例不得超过合同金额的 30%。""",
    },
]

WORKFLOWS = [
    {
        "name": "求职体检",
        "description": "一键生成个人求职体检：先看学业预警，再看岗位推荐。",
        "steps": [
            {"id": "warn", "tool": "my_warning", "title": "本人学业预警"},
            {"id": "rec", "tool": "my_recommendations", "title": "岗位推荐"},
        ],
    },
    {
        "name": "班级周报",
        "description": "教师一键出周报：班级概览 → 预警名单 → 能力差距（需要 class_name 入参）。",
        "steps": [
            {"id": "overview", "tool": "class_overview", "title": "班级概览"},
            {"id": "warn", "tool": "warning_list", "title": "预警名单"},
            {"id": "gap", "tool": "career_gap", "title": "能力差距"},
        ],
    },
]


def _call(method: str, path: str, token: str | None = None, body: dict | None = None):
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "{}")


def _upload(path: str, token: str, file_path: Path, title: str):
    import mimetypes
    import uuid

    boundary = "----qh" + uuid.uuid4().hex
    content = file_path.read_bytes()
    ctype = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    parts = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"title\"\r\n\r\n{title}\r\n".encode(),
        (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
         f"filename=\"{file_path.name}\"\r\nContent-Type: {ctype}\r\n\r\n").encode(),
        content, f"\r\n--{boundary}--\r\n".encode(),
    ]
    body = b"".join(parts)
    req = urllib.request.Request(BASE + path, data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "{}")


def _teacher_token() -> str:
    import pymysql

    from app.config import get_settings

    s = get_settings()
    conn = pymysql.connect(host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
                           password=s.mysql_password, database=s.mysql_db,
                           charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT `工号` FROM `教师` WHERE `角色`='teacher' ORDER BY `编号` LIMIT 1")
            row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        raise SystemExit("库里没有教师账号，先跑 scripts/gen_verify_report.py 建号")
    code, body = _call("POST", "/auth/login",
                       body={"role": "teacher", "account": row["工号"], "password": "teacher@123"})
    if code != 200:
        raise SystemExit(f"教师登录失败：{code} {body}")
    return body["access_token"]


def main() -> int:
    token = _teacher_token()
    titles = [d["title"] for d in DOCS] + ["员工报销制度（PDF 样本）"]

    # 1) 清理同名示例文档，保证幂等
    code, body = _call("GET", "/kb/docs", token)
    for doc in (body.get("items") or []):
        if doc["title"] in titles:
            _call("DELETE", f"/kb/docs/{doc['id']}", token)
            print(f"  清理旧文档 {doc['id']} {doc['title']}")

    # 2) 文本入库
    for d in DOCS:
        code, body = _call("POST", "/kb/docs/text", token, d)
        print(f"  入库[{code}] {d['title']} → {body.get('chunks')} 块"
              + ("（已存在，未重复入库）" if body.get("duplicated") else ""))

    # 3) PDF 入库（按页抽取，用于演示页码引用）
    pdf = _ROOT / "data" / "samples" / "reimbursement_policy.pdf"
    if not pdf.exists():
        from scripts.make_sample_pdf import write_sample

        write_sample(pdf)
    code, body = _upload("/kb/docs", token, pdf, "员工报销制度（PDF 样本）")
    print(f"  入库[{code}] PDF → {body.get('chunks')} 块，{body.get('duplicated')}")

    # 4) 工作流
    for wf in WORKFLOWS:
        code, body = _call("POST", "/workflow/defs", token, wf)
        print(f"  工作流[{code}] {wf['name']} → id={body.get('id')}")
        if code != 200:
            print(f"     !! {body}")

    # 5) 能力自检
    code, body = _call("GET", "/chat/capabilities", token)
    print("\n能力状态：")
    for it in body.get("items") or []:
        print(f"  [{'可用' if it['ready'] else '未就绪'}] {it['name']} —— {it['detail']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
