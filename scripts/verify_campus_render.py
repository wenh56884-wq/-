# scripts/verify_campus_render.py
# 职责：Playwright 无头渲染学生/教师端「校园行为洞察」页，验证图表、AI 解读卡与低投入名单。
# 铁律：仅只读渲染验证，不写库；AI 解读走真实后端（LLM 或模板兜底）；截图落盘供人工复核。

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:5173"
SHOT_DIR = Path(__file__).resolve().parent.parent / "logs" / "campus_render"
SHOT_DIR.mkdir(parents=True, exist_ok=True)


def _login(page, button_pattern: str, url_glob: str) -> None:
    # 先到同源页面才能访问 localStorage；清掉上一角色登录态，
    # 否则 /login 会按已登录身份重定向，演示按钮不出现
    page.goto(f"{BASE}/login", wait_until="domcontentloaded")
    page.evaluate("localStorage.clear()")
    page.goto(f"{BASE}/login", wait_until="domcontentloaded")
    page.get_by_role("button", name=button_pattern).click()
    page.get_by_role("button", name="进入工作台").click()
    page.wait_for_url(url_glob, timeout=20000)


def _wait_ai(page, logs: list[str]) -> str:
    """等 AI 卡出正文（LLM 可达分钟级）；返回 source 标签文本。"""
    page.wait_for_selector(".ai-card .ai-text:not(.ai-placeholder)", timeout=180000)
    tag = page.locator(".ai-card .el-tag").first
    return tag.inner_text() if tag.count() else "(无标签)"


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        logs: list[str] = []
        page.on("console", lambda m: logs.append(f"console[{m.type}]: {m.text}")
                if m.type == "error" else None)
        page.on("response", lambda r: logs.append(f"RES {r.status} {r.url}")
                if "campus-insight" in r.url else None)

        # ---- 学生端 ----
        _login(page, "学生（大四）：AI20230001", "**/student**")
        page.goto(f"{BASE}/student/campus", wait_until="domcontentloaded")
        page.wait_for_selector(".bento-grid", timeout=60000)
        page.wait_for_selector(".ai-card", timeout=10000)
        stu_ai = _wait_ai(page, logs)
        stu_charts = page.locator(".bento-card canvas").count()
        stu_hero = page.locator(".route-hero, .hero").first.inner_text()[:160]
        stu_ai_text = page.locator(".ai-card .ai-text").first.inner_text()[:200]
        page.screenshot(path=str(SHOT_DIR / "student_campus.png"), full_page=True)
        print("== 学生端 ==")
        print(f"URL={page.url}")
        print(f"HERO={stu_hero.replace(chr(10), ' | ')}")
        print(f"图表canvas数={stu_charts}")
        print(f"AI来源={stu_ai}")
        print(f"AI正文={stu_ai_text.replace(chr(10), ' | ')}")

        # ---- 教师端 ----
        _login(page, "教师：T001", "**/teacher**")
        page.evaluate("localStorage.setItem('qh_last_class', 'AI2301')")
        page.goto(f"{BASE}/teacher/campus", wait_until="domcontentloaded")
        page.wait_for_selector(".list-card .el-table__row", timeout=180000)
        tea_ai = _wait_ai(page, logs)
        tea_charts = page.locator(".chart-card canvas").count()
        row_count = page.locator(".list-card .el-table__row").count()
        low_rows = page.locator(".low-card .el-table__row").count()
        page.locator(".list-card .el-table__row").first.click()
        page.wait_for_timeout(1500)
        panels = page.locator(".el-collapse-item__title").all_inner_texts()
        page.screenshot(path=str(SHOT_DIR / "teacher_campus.png"), full_page=True)
        print("== 教师端 ==")
        print(f"URL={page.url}")
        print(f"图表canvas数={tea_charts}")
        print(f"学生表行数={row_count} 低投入名单行数={low_rows}")
        print(f"AI来源={tea_ai}")
        print(f"详情面板={panels}")
        print("--- 网络/控制台 ---")
        for line in logs:
            print(line)
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
