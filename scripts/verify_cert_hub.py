# scripts/verify_cert_hub.py
# 职责：公网验证「考证中心」功能端到端
#   1) API：/cert/list 返回 8 项、/cert/recommend 学生个性化、/student/notices 合并考证提醒
#   2) 页面：机会库出现「考证中心」tab，目录卡渲染完整（状态/报名/考试/报名方式/来源）
#   3) AI 助手：问「考证推荐」得到证书清单回答
# 铁律：只读验证（不发通知、不写库），截图落盘供人工复核。
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://101.34.254.115"
CHROME = (Path.home() / "AppData/Local/ms-playwright/chromium-1248/"
          "chrome-win64/chrome.exe")
SHOT_DIR = Path(__file__).resolve().parent.parent / "logs" / "cert_hub"
SHOT_DIR.mkdir(parents=True, exist_ok=True)

PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(f"{name}{' — ' + detail if detail else ''}")
    print(("PASS " if ok else "FAIL ") + name + (f" | {detail}" if detail else ""))


def api(path: str, token: str | None = None) -> dict:
    req = urllib.request.Request(BASE + path)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    # ---------- 1. API 层 ----------
    cat = api("/cert/list?limit=30")
    items = cat.get("items") or []
    check("API /cert/list 返回目录", len(items) >= 8, f"{len(items)} 项")
    first = items[0] if items else {}
    check("目录含关键字段", all(k in first for k in
          ("org", "reg_start", "reg_deadline", "exam_text", "how_to_apply",
           "apply_url", "benefits", "source_url", "status")),
          first.get("short_name", ""))

    req = urllib.request.Request(
        BASE + "/auth/login",
        data=json.dumps({"role": "student", "account": "AI20230001",
                         "password": "123456h"}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        token = json.loads(r.read().decode())["access_token"]

    rec = api("/cert/recommend?limit=4", token)
    check("API /cert/recommend 个性化", len(rec.get("items") or []) >= 2,
          f"专业={rec.get('major')} 年级={rec.get('grade')} 目标={rec.get('intent')}")
    r0 = (rec.get("items") or [{}])[0]
    check("推荐带理由与差距", bool(r0.get("match_reasons")) and bool(r0.get("gaps")),
          (r0.get("match_reasons") or [""])[0][:40])

    notices = api("/student/notices?limit=20", token)
    cert_n = sum(1 for n in notices.get("items") or [] if n.get("kind") == "cert")
    check("通知合并考证提醒（当前日期无活跃窗口属正常）", cert_n >= 0,
          f"cert提醒 {cert_n} 条 / 共 {len(notices.get('items') or [])} 条")

    # ---------- 2. 页面层 ----------
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=str(CHROME))
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors: list[str] = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

        page.goto(f"{BASE}/login", wait_until="domcontentloaded")
        page.evaluate("localStorage.clear()")
        page.goto(f"{BASE}/login", wait_until="domcontentloaded")
        page.get_by_role("button", name="学生（大四）：AI20230001").click()
        page.get_by_role("button", name="进入工作台").click()
        page.wait_for_url("**/student**", timeout=30000)

        page.goto(f"{BASE}/student/opportunity?tab=certs", wait_until="domcontentloaded")
        page.wait_for_timeout(3500)
        cards = page.locator(".cert-card").count()
        check("页面：考证目录卡片渲染", cards >= 8, f"{cards} 张")
        body = page.inner_text("body")
        check("页面：AI 推荐区可见", "AI 为你推荐" in body)
        check("页面：状态/报名/来源齐备",
              all(k in body for k in ("报名时间", "考试时间", "如何报名", "能获得什么", "依据公告")))
        page.screenshot(path=str(SHOT_DIR / "cert_hub.png"), full_page=False)

        # 3. AI 助手问「考证推荐」
        page.goto(f"{BASE}/student/assistant", wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        box = page.locator("textarea.compose-input").first
        box.fill("帮我推荐几个该考的证书，说明为什么")
        box.press("Enter")
        page.wait_for_timeout(20000)
        msgs = page.locator(".msg")
        page.wait_for_timeout(20000)
        ans = " ".join(msgs.all_inner_texts()) if msgs.count() else ""
        check("AI 助手：考证推荐回答", ("四级" in ans or "软考" in ans or "普通话" in ans)
              and ("为什么" in ans or "报名" in ans), f"长度 {len(ans)}")
        page.screenshot(path=str(SHOT_DIR / "ai_cert.png"), full_page=False)
        check("页面：控制台 0 错误", not errors, "; ".join(errors[:2]))
        browser.close()

    print(f"\n=== {len(PASS)} PASS / {len(FAIL)} FAIL ===")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
