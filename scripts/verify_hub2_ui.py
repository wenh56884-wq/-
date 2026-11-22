# -*- coding: utf-8 -*-
"""板块合并 + 实验室总览的 UI 冒烟：逐个板块截图、收集控制台错误、检查关键节点。

前提：本地后端在跑，且 web/dist 是最新构建（后端直接托管 dist）。
用法：.venv\\Scripts\\python.exe scripts/verify_hub2_ui.py
"""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

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
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())["access_token"]


errors: list[str] = []


def shot(page, name: str) -> None:
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
    print(f"  截图 {name}.png")


def as_student(page, tok: str) -> None:
    page.goto(BASE + "/login")
    page.evaluate(
        """(t) => {
            localStorage.setItem('qh_token', t);
            localStorage.setItem('qh_role', 'student');
            localStorage.setItem('qh_student_no', 'AI20230001');
        }""",
        tok,
    )


def as_teacher(page, tok: str) -> None:
    page.goto(BASE + "/login")
    page.evaluate(
        """(t) => {
            localStorage.setItem('qh_token', t);
            localStorage.setItem('qh_role', 'teacher');
            localStorage.setItem('qh_tenant_id', '1');
        }""",
        tok,
    )


CHECKS: list[tuple[str, str, str]] = []


with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    page.on("console", lambda m: errors.append(f"{m.type}: {m.text}") if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))

    tok = login("student", "AI20230001")
    as_student(page, tok)

    print("[学生] 侧栏")
    page.goto(BASE + "/student")
    page.wait_for_timeout(2600)
    labels = page.locator(".side-item .side-label").all_inner_texts()
    print("  侧栏项：", labels)
    CHECKS.append(("student-nav", str(len(labels)), "8"))
    shot(page, "hub2-01-student-home")

    print("[学生] 学业板块")
    page.goto(BASE + "/student/academic")
    page.wait_for_timeout(2200)
    shot(page, "hub2-02-academic")
    tabs = page.locator(".hubbar .seg-btn").all_inner_texts()
    print("  Tabs：", tabs)
    CHECKS.append(("academic-tabs", str(len(tabs)), "3"))
    page.locator(".hubbar .seg-btn").nth(1).click()
    page.wait_for_timeout(1800)
    print("  切到 forecast，URL：", page.url)
    CHECKS.append(("academic-url", page.url.split("?")[-1], "tab=forecast"))
    shot(page, "hub2-03-academic-forecast")

    print("[学生] 机会库")
    page.goto(BASE + "/student/opportunity?tab=exams")
    page.wait_for_timeout(2600)
    shot(page, "hub2-04-opportunity-exams")

    print("[学生] 生涯规划")
    page.goto(BASE + "/student/plan")
    page.wait_for_timeout(2400)
    shot(page, "hub2-05-plan")

    print("[学生] 模拟面试 → 复盘实验室 总览")
    page.goto(BASE + "/student/interview?mode=lab")
    page.wait_for_timeout(3000)
    shot(page, "hub2-06-lab-overview")
    print("  工位数：", page.locator(".lab-tab").count())
    CHECKS.append(("lab-tabs", str(page.locator(".lab-tab").count()), "7"))
    has_hero = page.locator(".stat-hero .stat-num b").first.inner_text()
    print("  就绪度：", has_hero)
    CHECKS.append(("readiness", has_hero, "47.9"))
    steps = page.locator(".step-title").all_inner_texts()
    print("  下一步：", steps)

    print("  点第一条下一步")
    page.locator(".step").first.click()
    page.wait_for_timeout(2600)
    print("  当前工位：", page.locator(".lab-tab.on").inner_text())
    CHECKS.append(("jump-tab", page.locator(".lab-tab.on").inner_text(), "岗位就绪"))
    shot(page, "hub2-07-lab-jump-ready")

    print("[学生] 旧地址重定向")
    page.goto(BASE + "/student/forecast")
    page.wait_for_timeout(1600)
    print("  /student/forecast →", page.url)
    CHECKS.append(("redirect-forecast", page.url.split("/student/")[-1], "academic?tab=forecast"))

    tok_t = login("teacher", "T001")
    as_teacher(page, tok_t)
    print("[教师] 学生板块")
    page.goto(BASE + "/teacher")
    page.wait_for_timeout(3200)
    tlabels = page.locator(".side-item .side-label").all_inner_texts()
    print("  侧栏项：", tlabels)
    CHECKS.append(("teacher-nav", str(len(tlabels)), "8"))
    shot(page, "hub2-08-teacher-students")
    page.locator(".hubbar .seg-btn").nth(2).click()
    page.wait_for_timeout(2600)
    shot(page, "hub2-09-teacher-grades")

    print("[教师] 从档案点成绩（带 student_no）")
    page.goto(BASE + "/teacher?tab=roster")
    page.wait_for_timeout(2600)
    shot(page, "hub2-10-teacher-roster")

    print("[教师] 机会库")
    page.goto(BASE + "/teacher/opportunity")
    page.wait_for_timeout(2400)
    shot(page, "hub2-11-teacher-opportunity")

    print("[移动端] 学业 + 实验室")
    mob = browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    mob.on("console", lambda m: errors.append(f"[m] {m.type}: {m.text}") if m.type == "error" else None)
    as_student(mob, tok)
    mob.goto(BASE + "/student/interview?mode=lab")
    mob.wait_for_timeout(2800)
    mob.screenshot(path=str(OUT / "hub2-12-mobile-lab.png"), full_page=True)
    print("  截图 hub2-12-mobile-lab.png")

    browser.close()

print("\n=== 检查项 ===")
for name, got, want in CHECKS:
    print(("OK  " if str(got) == want else "FAIL") + f" {name}: {got} (期望 {want})")

print("\n=== 控制台错误 ===")
print("\n".join(errors[:12]) if errors else "无")
