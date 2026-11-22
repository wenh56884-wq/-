# -*- coding: utf-8 -*-
"""冷场提示 UI 验证：1v1 面试 45 秒不动笔、群面 60 秒不发言 → AI 宠物冒提示。

前提：本地 8000 已启动且 web/dist 为最新构建。真实等待计时器触发，全程约 2-3 分钟。
用法：.venv\\Scripts\\python.exe scripts/verify_idle_hint.py
"""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = os.environ.get("QH_BASE", "http://127.0.0.1:8000")
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
print("login ok")

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

    # ---------- 场景 1：1v1 面试 45 秒不动笔 ----------
    page.goto(BASE + "/student/interview", wait_until="networkidle")
    page.wait_for_timeout(2000)
    start_btn = page.get_by_role("button", name="开始模拟面试")
    if start_btn.count() and not start_btn.is_enabled():
        # 岗位未选中：点开岗位下拉取第一个选项
        page.locator("#interview-job-select").click()
        page.wait_for_timeout(900)
        page.locator(".el-select-dropdown__item:visible").first.click()
        page.wait_for_timeout(600)
    if start_btn.count() and start_btn.is_enabled():
        start_btn.click()
        page.wait_for_selector(".question", timeout=90000)
        print("1v1 已出题，开始等 45 秒冷场…")
        try:
            page.wait_for_selector(".pet-bubble", timeout=70000)
            text = page.inner_text(".pet-bubble")
            print("1v1 宠物提示:", text[:60])
            page.screenshot(path=str(OUT / "idle-hint-interview.png"), full_page=False)
        except Exception:
            print("1v1 未等到宠物气泡（超时）")
    else:
        print("1v1 跳过：无简历或岗位未选中，无法开始")

    # ---------- 场景 2：群面 60 秒不发言 ----------
    page.goto(BASE + "/student/lab", wait_until="networkidle")
    page.wait_for_timeout(2000)
    page.get_by_role("tab", name="群面").click()
    page.wait_for_timeout(1500)
    page.get_by_role("button", name="进入会议室").click()
    page.wait_for_selector(".gr-composer", timeout=90000)
    print("群面已进房，开始等 60 秒冷场…")
    try:
        page.wait_for_selector(".pet-bubble", timeout=90000)
        text = page.inner_text(".pet-bubble")
        print("群面宠物提示:", text[:60])
        page.screenshot(path=str(OUT / "idle-hint-group.png"), full_page=False)
    except Exception:
        print("群面未等到宠物气泡（超时）")

    browser.close()

print("\n控制台错误：", len(errors))
for e in errors[:12]:
    print("  ", e[:220])
