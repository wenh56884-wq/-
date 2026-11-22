# scripts/verify_public_twin.py
# 职责：公网回归验证学生首页数字孪生面板、首页哈希资源与控制台报错。
# 样例：python scripts/verify_public_twin.py
# 约束：仅只读验证，不发消息、不写库、不修改前端。
from __future__ import annotations

import re
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://101.34.254.115"
CHROME = (Path.home() / "AppData/Local/ms-playwright/chromium-1248/"
          "chrome-win64/chrome.exe")
SHOT_DIR = Path(__file__).resolve().parent.parent / "logs" / "public_twin"
SHOT_DIR.mkdir(parents=True, exist_ok=True)

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    """记录一条 PASS/FAIL，不拦截后续检查。"""
    (PASS if ok else FAIL).append(f"{name}{' — ' + detail if detail else ''}")
    print(("PASS " if ok else "FAIL ") + name + (f" | {detail}" if detail else ""))


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=str(CHROME))
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        errors: list[str] = []
        asset_failures: list[str] = []
        server_failures: list[str] = []
        page.on("console",
                lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(f"[pageerror] {e}"))
        page.on("response",
                lambda r: asset_failures.append(f"{r.status} {r.url}")
                if r.status >= 400 else None)
        page.on("response",
                lambda r: server_failures.append(f"{r.status} {r.url}")
                if r.status >= 400 else None)
        page.on("response",
                lambda r: server_failures.append(
                    f"{r.status} {r.request.method} {r.url} | "
                    f"auth={'yes' if r.request.headers.get('authorization') else 'no'}")
                if r.status == 401 else None)

        page.goto(f"{BASE}/", wait_until="domcontentloaded")
        html = page.content()
        hash_assets = list(dict.fromkeys(re.findall(
            r'(?:src|href)="/assets/[^"]+\.(?:js|css)"', html)))
        check("首页包含文件名 hash 版本资源", len(hash_assets) > 0,
              f"{len(hash_assets)} 个：{', '.join(hash_assets[:3])}")
        check("首页静态资源无 4xx/5xx", not asset_failures,
              "; ".join(asset_failures[:3]))
        page.screenshot(path=str(SHOT_DIR / "home.png"), full_page=False)

        page.goto(f"{BASE}/login", wait_until="domcontentloaded")
        page.evaluate("localStorage.clear()")
        page.goto(f"{BASE}/login", wait_until="domcontentloaded")
        page.get_by_role("button", name="学生（大四）：AI20230001").click()
        page.get_by_role("button", name="进入工作台").click()
        page.wait_for_url("**/student**", timeout=30000)
        page.wait_for_selector(".twin-sphere", timeout=30000)
        page.wait_for_timeout(2600)

        counts = {
            "数字孪生球体": page.locator(".twin-sphere").count(),
            "孪生环A": page.locator(".twin-ring.ring-a").count(),
            "孪生环B": page.locator(".twin-ring.ring-b").count(),
            "数据标签": page.locator(".twin-chip").count(),
            "画像面板": page.locator(".twin-panel").count(),
            "资料星图": page.locator(".twin-radar").count(),
        }
        check("数字孪生核心元素齐备",
              all(count > 0 for count in counts.values()),
              ", ".join(f"{k}={v}" for k, v in counts.items()))
        panel = page.locator(".twin-panel").first.bounding_box()
        check("数字孪生面板可读且有高度",
              bool(panel and panel["height"] > 120 and panel["width"] > 300),
              f"width={panel['width'] if panel else 0}, "
              f"height={panel['height'] if panel else 0}")
        page.screenshot(path=str(SHOT_DIR / "student_twin.png"), full_page=False)
        check("学生首页无失败请求", not server_failures,
              "; ".join(dict.fromkeys(server_failures[:8])))
        check("学生首页控制台 0 错误", not errors, "; ".join(errors[:3]))
        browser.close()

    print(f"\n=== {len(PASS)} PASS / {len(FAIL)} FAIL ===")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
