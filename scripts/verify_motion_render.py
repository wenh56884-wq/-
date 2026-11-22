# scripts/verify_motion_render.py
# 职责：Playwright 无头验证全站动效改造——登录/首页/工作台/校园洞察四场景截图 + reveal 可见性 + reduced-motion 降级。
# 铁律：只读渲染验证，不写库；不改任何按钮文案与路由；截图落盘 logs/motion_render/ 供人工复核。

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:5173"
SHOT_DIR = Path(__file__).resolve().parent.parent / "logs" / "motion_render"
SHOT_DIR.mkdir(parents=True, exist_ok=True)


def _login(page, button_pattern: str, url_glob: str) -> None:
    page.goto(f"{BASE}/login", wait_until="domcontentloaded")
    page.evaluate("localStorage.clear()")
    page.goto(f"{BASE}/login", wait_until="domcontentloaded")
    page.get_by_role("button", name=button_pattern).click()
    page.get_by_role("button", name="进入工作台").click()
    page.wait_for_url(url_glob, timeout=20000)


def _reveal_stats(page) -> str:
    """统计 .qh-reveal 元素总数与已揭示数，并抽查首个元素计算 opacity。"""
    return page.evaluate(
        """() => {
            const all = document.querySelectorAll('.qh-reveal');
            const revealed = document.querySelectorAll('.qh-reveal.is-revealed');
            let opacity = null;
            if (all.length) {
                opacity = getComputedStyle(all[0]).opacity;
            }
            return JSON.stringify({total: all.length, revealed: revealed.length,
                                   firstOpacity: opacity});
        }"""
    )


def _settle(page, ms: int = 2500) -> None:
    page.wait_for_timeout(ms)


def _shot(page, name: str) -> None:
    page.screenshot(path=str(SHOT_DIR / f"{name}.png"), full_page=True)
    print(f"SHOT={name}.png")


def main() -> int:
    errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        page.on("console", lambda m: errors.append(f"console[{m.type}]: {m.text}")
                if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))

        # ---- 登录页（电影感入场）----
        page.goto(f"{BASE}/login", wait_until="domcontentloaded")
        page.evaluate("localStorage.clear()")
        page.goto(f"{BASE}/login", wait_until="domcontentloaded")
        _settle(page, 3000)
        demo_ok = page.get_by_role("button", name="教师：T001").count() > 0
        submit_ok = page.get_by_role("button", name="进入工作台").count() > 0
        _shot(page, "01_login")
        print(f"== 登录页 == 演示按钮={demo_ok} 提交按钮={submit_ok} reveal={_reveal_stats(page)}")

        # ---- 学生端首页 + 校园洞察 ----
        _login(page, "学生（大四）：AI20230001", "**/student**")
        _settle(page, 3500)
        _shot(page, "02_student_home")
        print(f"== 学生首页 == URL={page.url} reveal={_reveal_stats(page)}")

        page.goto(f"{BASE}/student/campus", wait_until="domcontentloaded")
        page.wait_for_selector(".bento-grid", timeout=90000)
        page.wait_for_selector("canvas", timeout=90000)
        _settle(page, 3000)
        stu_charts = page.locator("canvas").count()
        ai_card = page.locator(".ai-card").count()
        _shot(page, "03_student_campus")
        print(f"== 学生校园洞察 == canvas={stu_charts} ai-card={ai_card} reveal={_reveal_stats(page)}")

        # ---- 教师端工作台 + 校园洞察 ----
        _login(page, "教师：T001", "**/teacher**")
        _settle(page, 3500)
        _shot(page, "04_teacher_dashboard")
        print(f"== 教师工作台 == URL={page.url} reveal={_reveal_stats(page)}")

        page.evaluate("localStorage.setItem('qh_last_class', 'AI2301')")
        page.goto(f"{BASE}/teacher/campus", wait_until="domcontentloaded")
        page.wait_for_selector(".list-card .el-table__row", timeout=180000)
        _settle(page, 3000)
        tea_charts = page.locator("canvas").count()
        rows = page.locator(".list-card .el-table__row").count()
        low_rows = page.locator(".low-card .el-table__row").count()
        _shot(page, "05_teacher_campus")
        print(f"== 教师校园洞察 == canvas={tea_charts} 学生行={rows} 低投入行={low_rows} reveal={_reveal_stats(page)}")

        # ---- reduced-motion 降级：reveal 必须直接可见 ----
        rm = browser.new_page(viewport={"width": 1600, "height": 1000},
                              reduced_motion="reduce")
        rm.goto(f"{BASE}/login", wait_until="domcontentloaded")
        rm.evaluate("localStorage.clear()")
        rm.goto(f"{BASE}/login", wait_until="domcontentloaded")
        rm.get_by_role("button", name="学生（大四）：AI20230001").click()
        rm.get_by_role("button", name="进入工作台").click()
        rm.wait_for_url("**/student**", timeout=20000)
        _settle(rm, 1500)
        rm_stats = rm.evaluate(
            """() => {
                const all = [...document.querySelectorAll('.qh-reveal')];
                const hidden = all.filter(el => parseFloat(getComputedStyle(el).opacity) < 0.99);
                const anims = document.getAnimations
                    ? document.getAnimations().filter(a => a.playState === 'running').length : -1;
                return JSON.stringify({total: all.length, hidden: hidden.length, runningAnimations: anims});
            }"""
        )
        _shot(rm, "06_reduced_motion_student")
        print(f"== reduced-motion == {rm_stats}")
        rm.close()

        print("--- 控制台错误 ---")
        if errors:
            for line in errors:
                print(line)
        else:
            print("(无)")
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())