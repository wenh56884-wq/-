# scripts/shot_tech_ui.py
# 职责：本地 preview（dist-cloud）科技感视觉层截图，落盘 logs/tech_ui 供人工复核。
# 只做只读浏览与截图，不发通知、不写库。
from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Page, sync_playwright

BASE = "http://127.0.0.1:5173"
CHROME = (Path.home() / "AppData/Local/ms-playwright/chromium-1248/"
          "chrome-win64/chrome.exe")
SHOT_DIR = Path(__file__).resolve().parent.parent / "logs" / "tech_ui"
SHOT_DIR.mkdir(parents=True, exist_ok=True)


def shot(page: Page, name: str) -> None:
    page.screenshot(path=str(SHOT_DIR / f"{name}.png"), full_page=False)
    print(f"SHOT {name}.png")


def main() -> int:
    errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=str(CHROME))
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.on("console",
                lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))

        page.goto(f"{BASE}/login", wait_until="domcontentloaded")
        page.wait_for_timeout(900)
        shot(page, "01_login_gradient")

        page.get_by_role("button", name="学生（大四）：AI20230001").click()
        page.get_by_role("button", name="进入工作台").click()
        page.wait_for_url("**/student**", timeout=30000)
        page.wait_for_timeout(1600)
        shot(page, "02_student_home_glow")

        # hover 主卡：抓浮起 + 边光扫过 + 发光
        card = page.locator(".bento-card").first
        if card.count():
            card.hover()
            page.wait_for_timeout(280)
            shot(page, "03_card_hover_sweep")

        for path, name in (
            ("/student/academic", "04_academic_numbers"),
            ("/student/opportunity", "05_opportunity_bento"),
            ("/student/campus", "06_campus_chart"),
        ):
            page.goto(f"{BASE}{path}", wait_until="domcontentloaded")
            page.wait_for_timeout(1600)
            shot(page, name)

        page.goto(f"{BASE}/teacher", wait_until="domcontentloaded")
        page.wait_for_timeout(1600)
        shot(page, "07_teacher_topbar")

        print(f"CONSOLE_ERRORS={len(errors)}")
        for e in errors[:3]:
            print(f"  {e}")
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
