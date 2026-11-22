# scripts/verify_agent_ui.py
# 职责：用真实浏览器验证「自主大脑执行步骤」面板——线上/本地各跑一次，产出截图。
# 依赖：playwright（chromium）
# 用法：python scripts/verify_agent_ui.py [base_url] [问题]
#
# 关注点：/chat 响应里的 steps 是否真的渲染到了前端（这一步以前是空的）。

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8012"
QUESTION = (sys.argv[2] if len(sys.argv) > 2
            else "AI2301 这学期预警情况怎么样，同时帮我看看班级成绩")
OUT = Path(__file__).resolve().parent.parent / "logs" / "agent_ui"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 960})
        page.goto(f"{BASE}/login", wait_until="domcontentloaded")
        page.wait_for_timeout(1200)
        page.screenshot(path=str(OUT / "01-login.png"))

        # 直接填表 + 回车提交：比点按钮稳（登录页有装饰动画层，按钮会被短暂遮挡）
        page.locator("input[placeholder='如 T001']").fill("T001")
        page.locator("input[type='password']").first.fill("123456h")
        page.wait_for_timeout(300)
        page.screenshot(path=str(OUT / "01b-login-filled.png"))
        page.locator("input[type='password']").first.press("Enter")
        page.wait_for_url("**/teacher**", timeout=40000)
        page.wait_for_timeout(1500)

        page.goto(f"{BASE}/teacher/assistant", wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        page.screenshot(path=str(OUT / "02-assistant.png"))

        box = page.get_by_placeholder("给启航智能体发送消息，Enter 发送 / Shift+Enter 换行")
        box.fill(QUESTION)
        box.press("Enter")
        print("已发送，等待回答（自主大脑约 30~60 秒）…")
        page.wait_for_timeout(6000)
        # 等「执行与回查」面板出现（有 trace_id 即表示本轮结束）
        for _ in range(60):
            if page.get_by_text("自主大脑执行步骤", exact=False).count():
                break
            page.wait_for_timeout(3000)
        page.wait_for_timeout(1500)
        page.screenshot(path=str(OUT / "03-answer.png"), full_page=True)

        # 先展开「执行与回查」外层，再展开「自主大脑执行步骤」内层
        for label in ("执行与回查", "自主大脑执行步骤"):
            target = page.get_by_text(label, exact=False).first
            if not target.count():
                print(f"!! 没找到「{label}」")
                continue
            try:
                target.scroll_into_view_if_needed()
                target.click(force=True, timeout=8000)
                page.wait_for_timeout(700)
            except Exception as exc:  # noqa: BLE001
                print(f"!! 展开「{label}」失败：{type(exc).__name__}")
        page.screenshot(path=str(OUT / "04-steps.png"), full_page=True)
        steps = page.locator(".trace-step").all_inner_texts()
        print(f"步骤条数：{len(steps)}")
        for line in steps:
            print("  " + " | ".join(part.strip() for part in line.splitlines() if part.strip()))
        browser.close()
    print(f"截图目录：{OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
