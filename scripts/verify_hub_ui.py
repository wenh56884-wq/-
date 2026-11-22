# -*- coding: utf-8 -*-
"""模拟面试板块（实战演练 + 复盘实验室）UI 冒烟：截图 + 控制台错误 + 关键交互。

前提：本地已启动服务（默认 8012），web/dist 为最新构建。
用法：QH_BASE=http://127.0.0.1:8012 .venv\\Scripts\\python.exe scripts/verify_hub_ui.py
"""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = os.environ.get("QH_BASE", "http://127.0.0.1:8012")
OUT = Path(__file__).resolve().parents[1] / "shots" / ("online" if "101.34" in BASE else "local")
OUT.mkdir(parents=True, exist_ok=True)

req = urllib.request.Request(
    BASE + "/auth/login",
    data=json.dumps({"role": "student", "account": "AI20230001",
                     "password": "123456h"}).encode(),
    headers={"Content-Type": "application/json"},
)
with urllib.request.urlopen(req) as resp:
    token = json.loads(resp.read())["access_token"]

errors: list[str] = []


def shot(page, name: str) -> None:
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
    print(f"  截图 {name}.png")


with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    page.on("console", lambda m: errors.append(f"{m.type}: {m.text}") if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))

    page.goto(BASE + "/login", wait_until="domcontentloaded")
    page.evaluate("""([t]) => { localStorage.setItem('qh_token', t); localStorage.setItem('qh_role', 'student'); }""",
                  [token])

    # 1) 板块默认落在实战演练
    page.goto(BASE + "/student/interview", wait_until="networkidle")
    page.wait_for_timeout(2500)
    print("[1] 实战演练")
    shot(page, "hub-1-practice")
    print("   一级导航:", page.locator(".seg-btn").all_inner_texts())
    print("   侧栏含「面试实验室」:", "面试实验室" in page.inner_text(".sidebar, aside") if page.locator(".sidebar, aside").count() else "N/A")
    print("   含「让智能体陪你练到会」:", "让智能体陪你练到会" in page.inner_text("body"))

    # 2) 切到复盘实验室
    page.get_by_role("tab", name="复盘实验室").click()
    page.wait_for_timeout(2600)
    print("[2] 复盘实验室")
    shot(page, "hub-2-lab")
    body = page.inner_text("body")
    for kw in ("圆桌评审", "岗位就绪", "能力护照", "当面试官"):
        print(f"   含「{kw}」:", kw in body)
    print("   URL:", page.url)

    # 3) 岗位就绪：选第一个岗位看结果
    page.get_by_role("tab", name="岗位就绪").click()
    page.wait_for_timeout(2600)
    shot(page, "hub-3-ready-empty")
    cards = page.locator(".rd-job")
    print("   岗位候选元素数:", cards.count())
    if cards.count():
        cards.first.click()
        page.wait_for_timeout(3200)
        shot(page, "hub-4-ready-result")
        t = page.inner_text("body")
        print("   就绪度出现:", "就绪" in t or "被埋没" in t)

    # 4) 当面试官：开始 → 排序 → 揭晓
    page.get_by_role("tab", name="当面试官").click()
    page.wait_for_timeout(2200)
    shot(page, "hub-5-judge-intro")
    btns = page.get_by_role("button", name="开始评审")
    if btns.count():
        btns.first.click()
        page.wait_for_timeout(1200)
        shot(page, "hub-6-judge-rank")
        # 每题 9 个名次按钮：卡 i 的第 r 个 = i*3 + (r-1)
        def rank_page():
            btns = page.locator(".rank-btn")
            total = btns.count()
            print(f"   本题名次按钮 {total} 个")
            if total < 9:
                return
            for card, rank in ((0, 1), (1, 2), (2, 3)):
                btns.nth(card * 3 + (rank - 1)).click()
                page.wait_for_timeout(160)

        rank_page()
        for _ in range(4):                      # 最多 3 题，留一次冗余
            nxt = page.get_by_role("button", name="下一题")
            if nxt.count() and nxt.first.is_enabled():
                nxt.first.click()
                page.wait_for_timeout(500)
                rank_page()
                continue
            break
        reveal = page.get_by_role("button", name="揭晓结果")
        print("   揭晓按钮:", reveal.count())
        if reveal.count():
            reveal.first.click()
            page.wait_for_timeout(3000)
            shot(page, "hub-7-judge-result")
            t = page.inner_text("body")
            print("   揭晓页含「眼力」/「准」:", ("眼力" in t) or ("判断" in t))
            print("   含「结构偏好」:", "结构偏好" in t)

    browser.close()

print("\n控制台错误：", len(errors))
for e in errors[:10]:
    print("  ", e[:180])
