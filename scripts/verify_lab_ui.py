# -*- coding: utf-8 -*-
"""面试实验室 UI 冒烟：登录 → 打开实验室 → 三个 Tab 截图 + 抓控制台报错。

前提：本地已启动 8011（uvicorn），且 web/dist 是最新构建。
用法：.venv\\Scripts\\python.exe scripts\\verify_lab_ui.py
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = __import__("os").environ.get("QH_BASE", "http://127.0.0.1:8011")
OUT = Path(__file__).resolve().parents[1] / "shots" / ("online" if "101.34" in BASE else "local")
OUT.mkdir(exist_ok=True)

req = urllib.request.Request(
    BASE + "/auth/login",
    data=json.dumps({"role": "student", "account": "AI20230001",
                     "password": "123456h"}).encode(),
    headers={"Content-Type": "application/json"},
)
with urllib.request.urlopen(req) as resp:
    auth = json.loads(resp.read())
print("login ok, token len:", len(auth["access_token"]))

errors: list[str] = []
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    page.on("console", lambda m: errors.append(f"{m.type}: {m.text}") if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))

    page.goto(BASE + "/login", wait_until="domcontentloaded")
    page.evaluate(
        """([t, r]) => { localStorage.setItem('qh_token', t); localStorage.setItem('qh_role', r); }""",
        [auth["access_token"], "student"],
    )

    page.goto(BASE + "/student/lab", wait_until="networkidle")
    page.wait_for_timeout(2500)
    page.screenshot(path=str(OUT / "lab-1-roundtable.png"), full_page=True)
    print("tab1 title:", page.locator("h1").first.inner_text())

    for key, name in (("能力护照", "lab-2-passport"), ("群面", "lab-3-group")):
        page.get_by_role("tab", name=key).click()
        page.wait_for_timeout(2600)
        page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
        print(f"tab [{key}] 截完")

    body = page.inner_text("body")
    for kw in ("面试实验室", "圆桌评审", "能力护照", "群面"):
        print(f"  文本包含「{kw}」:", kw in body)
    browser.close()

print("\n控制台错误：", len(errors))
for e in errors[:12]:
    print("  ", e[:200])
