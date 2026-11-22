"""导出接口冒烟测试：直接打 FastAPI，不经过浏览器。

覆盖：学生档案 / 全班成绩 / 单人成绩 / 学生本人成绩 × xlsx|csv|json
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)

CLASS = "AI2301"
TERM = "2025-2026-2"


def login(role: str, account: str) -> str:
    r = client.post("/auth/login", json={"role": role, "account": account,
                                         "password": "123456h"})
    assert r.status_code == 200, f"登录失败 {role}/{account}: {r.status_code} {r.text[:200]}"
    return r.json()["access_token"]


def check(name: str, url: str, token: str, params: dict, fmt: str) -> None:
    r = client.get(url, params={**params, "fmt": fmt},
                   headers={"Authorization": f"Bearer {token}"})
    if r.status_code != 200:
        print(f"  [FAIL] {name:26s} {fmt:5s} -> {r.status_code} {r.text[:160]}")
        return
    body = r.content
    disp = r.headers.get("content-disposition", "")
    # 解出 filename*=UTF-8'' 里的中文实名
    from urllib.parse import unquote
    real_name = ""
    if "filename*=UTF-8''" in disp:
        real_name = unquote(disp.split("filename*=UTF-8''", 1)[1])
    print(f"  [ok]   {name:12s} {fmt:5s} {len(body):>9,d} B  -> {real_name}")
    if fmt == "xlsx":
        path = f"_tmp_{name}_{fmt}.xlsx"
        with open(path, "wb") as f:
            f.write(body)
        from openpyxl import load_workbook
        wb = load_workbook(path)
        for ws in wb.worksheets:
            head = [c.value for c in ws[1]][:7]
            first = [c.value for c in ws[2]][:7] if ws.max_row > 1 else []
            print(f"         [{ws.title}] {ws.max_row - 1} 行 x {ws.max_column} 列")
            print(f"         表头 {head}")
            print(f"         首行 {first}")


def main() -> None:
    t_tok = login("teacher", "T001")
    s_tok = login("student", "AI20230001")
    print("登录 ok")

    for fmt in ("xlsx", "csv", "json"):
        check("学生档案", "/export/students", t_tok,
              {"class_name": CLASS, "term": TERM}, fmt)
        check("班级成绩", "/export/grades", t_tok,
              {"class_name": CLASS, "term": TERM}, fmt)
        check("单人成绩", "/export/student-grades/AI20230001", t_tok, {}, fmt)
        check("学生本人成绩", "/export/my-grades", s_tok, {}, fmt)

    # 越权：学生拿教师接口
    r = client.get("/export/students", params={"class_name": CLASS},
                   headers={"Authorization": f"Bearer {s_tok}"})
    print(f"\n越权检查（学生访问教师导出）-> {r.status_code}（期望 403）")

    # 参数校验
    r = client.get("/export/students", params={"class_name": CLASS, "fmt": "pdf"},
                   headers={"Authorization": f"Bearer {t_tok}"})
    print(f"非法格式 pdf -> {r.status_code}（期望 422）")

    r = client.get("/export/students", params={"class_name": "不存在的班级XYZ"},
                   headers={"Authorization": f"Bearer {t_tok}"})
    print(f"不存在班级 -> {r.status_code}（期望 422/404）")


if __name__ == "__main__":
    main()
