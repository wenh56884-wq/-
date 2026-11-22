# -*- coding: utf-8 -*-
"""群面语音版 UI 冒烟：登录 → 群面 → 开局 → 麦克风/播报按钮 → 聆听态 → 截图 + 控制台报错。

前提：本地 8000 已启动且 web/dist 为最新构建。
用法：.venv\\Scripts\\python.exe scripts\\verify_group_voice.py
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
    browser = p.chromium.launch(args=[
        "--use-fake-ui-for-media-stream",   # 自动允许麦克风权限弹窗
        "--use-fake-device-for-media-stream",
        "--autoplay-policy=no-user-gesture-required",
    ])
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    page.on("console", lambda m: errors.append(f"{m.type}: {m.text}") if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))

    page.goto(BASE + "/login", wait_until="domcontentloaded")
    page.evaluate(
        """([t, r]) => { localStorage.setItem('qh_token', t); localStorage.setItem('qh_role', r); }""",
        [auth["access_token"], "student"],
    )
    page.goto(BASE + "/student/lab", wait_until="networkidle")
    page.wait_for_timeout(2200)

    page.get_by_role("tab", name="群面").click()
    page.wait_for_timeout(1600)

    body = page.inner_text("body")
    has_rule = "语音模式" in body
    print("开始页含「语音模式」规则卡:", has_rule)
    page.screenshot(path=str(OUT / "group-voice-1-start.png"), full_page=True)

    page.get_by_role("button", name="进入会议室").click()
    page.wait_for_selector(".gr-composer", timeout=90000)
    page.wait_for_timeout(1200)
    print("已进入会议室")

    body = page.inner_text("body")
    tts_btn = "播报开" in body
    mic_btn = "语音发言" in body
    dim_hint = "HTTPS" in body or "Chrome" in body
    print("播报按钮(开):", tts_btn, "| 麦克风按钮:", mic_btn, "| 降级提示:", dim_hint)
    # 开场议题（主持人）不朗读；但 start 回应自带林一的破冰发言，属候选人开口，会被朗读
    print("候选人开场发言在朗读(林一破冰,应 True):", "播报中" in body)
    page.screenshot(path=str(OUT / "group-voice-2-live.png"), full_page=True)

    if mic_btn:
        page.get_by_role("button", name="语音发言").click()
        page.wait_for_timeout(1200)
        body = page.inner_text("body")
        print("进入聆听态(聆听中提示):", "聆听中" in body)
        page.screenshot(path=str(OUT / "group-voice-3-listening.png"), full_page=False)
        page.get_by_role("button", name="停止聆听").click()
        page.wait_for_timeout(800)
        print("退出聆听态:", "聆听中" not in page.inner_text("body"))
    else:
        print("该浏览器无识别 API，验证降级提示即可")

    if tts_btn:
        page.get_by_role("button", name="播报开").click()
        page.wait_for_timeout(400)
        print("播报切换为关:", "播报关" in page.inner_text("body"))
        page.get_by_role("button", name="播报关").click()
        page.wait_for_timeout(400)

    browser.close()

print("\n控制台错误：", len(errors))
for e in errors[:12]:
    print("  ", e[:220])
