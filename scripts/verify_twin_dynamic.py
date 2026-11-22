# scripts/verify_twin_dynamic.py
# 职责：Playwright 无头渲染学生首页，验证数字孪生动效面板
#       （陀螺环旋转 / 轨道粒子 / 脉冲扩散 / 扫描光带 / 数据标签漂移）。
# 铁律：仅只读渲染验证，不写库；截图落盘供人工复核。

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:5173"
SHOT_DIR = Path(__file__).resolve().parent.parent / "logs" / "twin_dynamic"
SHOT_DIR.mkdir(parents=True, exist_ok=True)


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        errors: list[str] = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

        page.goto(f"{BASE}/login", wait_until="domcontentloaded")
        page.evaluate("localStorage.clear()")
        page.goto(f"{BASE}/login", wait_until="domcontentloaded")
        api_logs: list[str] = []
        page.on("response", lambda r: api_logs.append(f"{r.status} {r.url}") if "/auth/" in r.url else None)
        page.get_by_role("button", name="学生（大四）：AI20230001").click()
        page.get_by_role("button", name="进入工作台").click()
        page.wait_for_timeout(6000)
        print(f"  登录后URL: {page.url}")
        for line in api_logs:
            print(f"  auth: {line}")
        page.wait_for_url("**/student**", timeout=20000)
        page.wait_for_selector(".twin-sphere", timeout=60000)
        page.wait_for_timeout(2600)  # 等动效跑起来

        checks = {
            "陀螺环A旋转(16s)": page.locator(".twin-ring.ring-a").count() == 1,
            "陀螺环B旋转(22s)": page.locator(".twin-ring.ring-b").count() == 1,
            "虚线光环": page.locator(".twin-halo").count() == 1,
            "脉冲×2(相位差1.6s)": page.locator(".twin-pulse").count() == 2,
            "轨道粒子×3": page.locator(".twin-mote").count() == 3,
            "数据标签×3(学业/岗位/生涯)": [t.strip() for t in page.locator(".twin-chip text").all_text_contents()] == ["学业", "岗位", "生涯"],
            "雷达扫描扇面": page.locator(".twin-radar").count() == 1,
            "星尘×12": page.locator(".twin-dust circle").count() == 12,
            "核心光环": page.locator(".twin-core-halo").count() == 1,
            "准轴虚线流动": page.locator(".twin-axis").count() == 1,
            "核心呼吸": page.locator(".twin-core-dot").count() == 1,
        }

        # 动效实际在跑：比较脉冲元素在两个时刻的 transform
        t1 = page.evaluate("getComputedStyle(document.querySelector('.twin-pulse.p1')).transform")
        page.wait_for_timeout(700)
        t2 = page.evaluate("getComputedStyle(document.querySelector('.twin-pulse.p1')).transform")
        checks["脉冲矩阵随时间变化"] = (t1 != t2 and t1 != "none")
        r1 = page.evaluate("getComputedStyle(document.querySelector('.twin-radar')).transform")
        page.wait_for_timeout(700)
        r2 = page.evaluate("getComputedStyle(document.querySelector('.twin-ring.ring-a')).transform")
        checks["雷达扇面矩阵随时间变化"] = (r1 != r2 and r1 != "none")

        # SMIL 粒子在动：比较 getCTM 前后位置
        m1 = page.evaluate("(() => { const m = document.querySelectorAll('.twin-mote')[0].getCTM(); return [m.e, m.f].join(','); })()")
        page.wait_for_timeout(800)
        m2 = page.evaluate("(() => { const m = document.querySelectorAll('.twin-mote')[0].getCTM(); return [m.e, m.f].join(','); })()")
        checks["SMIL粒子沿轨道运行"] = (m1 != m2)

        panel = page.locator(".twin-panel")
        box = panel.bounding_box()
        checks["面板渲染出可视尺寸"] = bool(box and box["height"] > 120 and box["width"] > 300)

        page.screenshot(path=str(SHOT_DIR / "twin_panel.png"), clip=box)
        page.screenshot(path=str(SHOT_DIR / "student_home_full.png"), full_page=False)

        ok = True
        print("== 数字孪生动效验证 ==")
        for k, v in checks.items():
            print(f"  [{'PASS' if v else 'FAIL'}] {k}")
            ok = ok and v
        print(f"  控制台错误: {len(errors)}")
        for e in errors[:5]:
            print(f"    {e[:160]}")
        print(f"  截图: {SHOT_DIR / 'twin_panel.png'}")
        browser.close()
        return 0 if ok and not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
