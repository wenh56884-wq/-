# scripts/verify_career_render.py
# 职责：用 Playwright 无头渲染教师端「生涯规划」页，验证筛选条/摘要/学生表/各域面板。
# 铁律：仅只读渲染验证，不写库、不调模型；截图落盘供人工复核。

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:5173"
SHOT_DIR = Path(__file__).resolve().parent.parent / "logs" / "career_render"
SHOT_DIR.mkdir(parents=True, exist_ok=True)


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 1000})

        logs: list[str] = []
        page.on("console", lambda m: logs.append(f"console[{m.type}]: {m.text}")
                if m.type in ("error", "warning") else None)
        page.on("request", lambda r: logs.append(f"REQ {r.method} {r.url}")
                if r.url.startswith("http://localhost:5173/api") else None)
        page.on("response", lambda r: logs.append(f"RES {r.status} {r.url}")
                if "/career-search" in r.url else None)

        # 登录页：点演示教师按钮自动填账号口令，再点进入工作台
        page.goto(f"{BASE}/login?role=teacher", wait_until="domcontentloaded")
        page.get_by_role("button", name="教师：T001").click()
        page.get_by_role("button", name="进入工作台").click()
        page.wait_for_url("**/teacher**", timeout=15000)

        # 进入站点，预置上次班级，再打开生涯规划页（挂载即自动查询）
        page.goto(f"{BASE}/", wait_until="domcontentloaded")
        page.evaluate("localStorage.setItem('qh_last_class', 'AI2301')")
        page.goto(f"{BASE}/teacher/career", wait_until="domcontentloaded",
                  timeout=30000)
        page.wait_for_selector(".career-body", timeout=60000)

        # 接口逐生编排较慢（约 40-60s），显式等学生表数据行
        try:
            page.wait_for_selector(".list-card .el-table__row", timeout=180000)
        except Exception:
            page.screenshot(path=str(SHOT_DIR / "career_fail.png"), full_page=True)
            print("!! 学生表未出现，诊断如下")
            print("URL=", page.url)
            print("body-text=", page.inner_text("body")[:500].replace("\n", " | "))
            for line in logs:
                print(line)
            raise SystemExit("学生表未渲染，见诊断")

        hero = page.locator(".route-hero, .hero").first
        hero_title = hero.inner_text() if hero.count() else "(无 hero)"
        row_count = page.locator(".list-card .el-table__row").count()

        # 先选一行学生，右侧详情卡才渲染各域面板，再采集面板与文本
        page.locator(".list-card .el-table__row").first.click()
        page.wait_for_timeout(2000)
        panels = page.locator(".detail-card .el-collapse-item__title").all_inner_texts()
        detail_text = page.inner_text(".detail-card").replace("\n", " | ")[:400]

        page.screenshot(path=str(SHOT_DIR / "career_page.png"), full_page=True)

        print(f"URL={page.url}")
        print(f"HERO={hero_title.replace(chr(10), ' | ')[:160]}")
        print(f"学生表行数={row_count}")
        print(f"域面板={panels}")
        print(f"详情文本={detail_text}")
        print("--- 网络/控制台 ---")
        for line in logs:
            print(line)

        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
