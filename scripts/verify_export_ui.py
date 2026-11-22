# -*- coding: utf-8 -*-
"""自选字段导出的端到端验证：勾 3 列 → 下载 → 用 openpyxl / csv 读回表头核对。

前提：本地后端在跑，web/dist 为最新构建（后端直接托管 dist）。
用法：.venv\\Scripts\\python.exe scripts/verify_export_ui.py
"""
from __future__ import annotations

import json
import os
import tempfile
import urllib.request
from pathlib import Path

import openpyxl
from playwright.sync_api import sync_playwright

BASE = os.environ.get("QH_BASE", "http://127.0.0.1:8000")
OUT = Path(__file__).resolve().parents[1] / "shots" / ("online" if "101.34" in BASE else "local")
OUT.mkdir(parents=True, exist_ok=True)


def login(role: str, account: str) -> str:
    req = urllib.request.Request(
        BASE + "/auth/login",
        data=json.dumps({"role": role, "account": account, "password": "123456h"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    return json.loads(urllib.request.urlopen(req).read())["access_token"]


def pick(text: str) -> str:
    return f'.el-dropdown-menu__item:visible:has-text("{text}")'


errors: list[str] = []
tmp = Path(tempfile.gettempdir())

with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1500, "height": 1000}, accept_downloads=True)
    page = ctx.new_page()
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))

    tok = login("teacher", "T001")
    page.goto(BASE + "/login")
    page.evaluate(
        """(t) => {
            localStorage.setItem('qh_token', t);
            localStorage.setItem('qh_role', 'teacher');
            localStorage.setItem('qh_tenant_id', '1');
        }""",
        tok,
    )

    # ---------- 全班成绩：自选 3 列 ----------
    page.goto(BASE + "/teacher?tab=grades")
    page.wait_for_timeout(3500)
    page.get_by_role("button", name="全班成绩").click()
    page.wait_for_timeout(600)
    page.locator(pick("自选字段")).first.click()
    page.wait_for_timeout(2000)
    shot1 = OUT / "export-01-dialog.png"
    page.screenshot(path=str(shot1))
    print("可勾字段数:", page.locator(".exp-field").count())

    page.locator(".exp-link:visible", has_text="清空").first.click()
    page.wait_for_timeout(250)
    for label in ("课程名称", "学分", "分数"):
        page.locator(".exp-field:visible", has_text=label).first.click()
    picked = page.locator(".exp-count b").inner_text()
    print("已选:", picked)
    page.screenshot(path=str(OUT / "export-02-picked.png"))

    with page.expect_download(timeout=30000) as dl:
        page.locator("button:visible", has_text="导出 3 列").first.click()
    d = dl.value
    f1 = tmp / d.suggested_filename
    d.save_as(f1)
    print("下载:", d.suggested_filename, f1.stat().st_size, "bytes")
    if d.suggested_filename.endswith(".xlsx"):
        wb = openpyxl.load_workbook(f1)
        ws = wb[wb.sheetnames[0]]
        print("  sheets:", wb.sheetnames)
        print("  表头:", [c.value for c in next(ws.iter_rows(max_row=1))])
        print("  首行:", [c.value for c in next(ws.iter_rows(min_row=2, max_row=2))])

    # ---------- 学生档案：自选 3 列 ----------
    page.wait_for_timeout(1000)
    page.goto(BASE + "/teacher?tab=roster")
    page.wait_for_timeout(3200)
    page.get_by_role("button", name="下载名单").click()
    page.wait_for_timeout(500)
    page.locator(pick("自选字段")).first.click()
    page.wait_for_timeout(1800)
    page.screenshot(path=str(OUT / "export-03-roster-dialog.png"))
    print("档案字段数:", page.locator(".exp-field").count())

    page.locator(".exp-link:visible", has_text="清空").first.click()
    page.wait_for_timeout(250)
    for label in ("姓名", "GPA", "出勤率"):
        page.locator(".exp-field:visible", has_text=label).first.click()
    with page.expect_download(timeout=30000) as dl2:
        page.locator("button:visible", has_text="导出 3 列").first.click()
    d2 = dl2.value
    f2 = tmp / d2.suggested_filename
    d2.save_as(f2)
    print("档案导出:", d2.suggested_filename)
    if d2.suggested_filename.endswith(".xlsx"):
        wb2 = openpyxl.load_workbook(f2)
        ws2 = wb2[wb2.sheetnames[0]]
        print("  表头:", [c.value for c in next(ws2.iter_rows(max_row=1))])
        print("  首行:", [c.value for c in next(ws2.iter_rows(min_row=2, max_row=2))])
    else:
        for line in f2.read_text(encoding="utf-8-sig").splitlines()[:3]:
            print("  ", line)

    browser.close()

print("\n控制台错误:", errors[:6] if errors else "无")
