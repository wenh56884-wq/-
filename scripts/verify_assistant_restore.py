# scripts/verify_assistant_restore.py
# 职责：公网验证 AI 助手「退出重进自动恢复上一轮对话」
#   1) 登录学生 AI20230001 → 进 AI 助手页
#   2) 记录当前会话与消息数 → 离开页面（模拟退出）→ 再回来
#   3) 断言：不点击任何会话的情况下，聊天区自动恢复出上一轮消息
# 铁律：只读验证（不发新消息、不写库），截图落盘供人工复核。
from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://101.34.254.115"
# 本机 playwright 未装配套 headless shell，直接指向已装的 chromium-1248
CHROME = (Path.home() / "AppData/Local/ms-playwright/chromium-1248/"
          "chrome-win64/chrome.exe")
SHOT_DIR = Path(__file__).resolve().parent.parent / "logs" / "asst_restore"
SHOT_DIR.mkdir(parents=True, exist_ok=True)


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=str(CHROME))
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors: list[str] = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

        # 登录
        page.goto(f"{BASE}/login", wait_until="domcontentloaded")
        page.evaluate("localStorage.clear()")
        page.goto(f"{BASE}/login", wait_until="domcontentloaded")
        page.get_by_role("button", name="学生（大四）：AI20230001").click()
        page.get_by_role("button", name="进入工作台").click()
        page.wait_for_url("**/student**", timeout=30000)

        # 进入 AI 助手
        page.goto(f"{BASE}/student/assistant", wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        sess_count = page.locator(".sess-item").count()
        msg_count_1 = page.locator(".msg").count()
        active_title = ""
        if sess_count:
            active_title = page.locator(".sess-item.is-active").inner_text()[:40]
        page.screenshot(path=str(SHOT_DIR / "first_visit.png"), full_page=False)
        print(f"  第一次进入：会话侧栏 {sess_count} 条，聊天区消息 {msg_count_1} 条"
              f"，选中会话「{active_title}」")

        # 退出（去别的页面）再回来，模拟用户离开后重进
        page.goto(f"{BASE}/student", wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
        page.goto(f"{BASE}/student/assistant", wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        msg_count_2 = page.locator(".msg").count()
        active_title_2 = ""
        if page.locator(".sess-item").count():
            active_title_2 = page.locator(".sess-item.is-active").inner_text()[:40]
        page.screenshot(path=str(SHOT_DIR / "revisit.png"), full_page=False)
        print(f"  退出重进：聊天区消息 {msg_count_2} 条，选中会话「{active_title_2}」")

        checks = {
            "侧栏有历史会话(该账号至少聊过一轮)": sess_count > 0,
            "首次进入自动恢复消息": sess_count == 0 or msg_count_1 > 0,
            "退出重进自动恢复上一轮": sess_count == 0 or (msg_count_2 > 0
                                                 and active_title_2 == active_title),
            "控制台0错误": not errors,
        }
        ok = True
        for name, passed in checks.items():
            print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
            ok = ok and passed
        if errors:
            print(f"  控制台错误样例: {errors[:3]}")
        browser.close()
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
