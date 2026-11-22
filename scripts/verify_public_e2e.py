# scripts/verify_public_e2e.py
# 职责：公网 http://101.34.254.115/ 端到端只读验证
#   1) HTTP：首页 200、/health 四项、登录 API 可取 token
#   2) 页面：Playwright 登录学生/教师，遍历各板块页，校验标题与非空白
#   3) 控制台：全程 0 错误（含 pageerror）才 PASS；截图落盘 logs/public_e2e
# 铁律：只读验证（不发通知、不写库、不改配置），截图供人工复核。
from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

BASE = "http://101.34.254.115"
CHROME = (Path.home() / "AppData/Local/ms-playwright/chromium-1248/"
          "chrome-win64/chrome.exe")
SHOT_DIR = Path(__file__).resolve().parent.parent / "logs" / "public_e2e"
SHOT_DIR.mkdir(parents=True, exist_ok=True)

PASS: list[str] = []
FAIL: list[str] = []

STUDENT_PAGES = [
    ("/student", "我的画像", "student_home.png"),
    ("/student/academic", "学业", "student_academic.png"),
    ("/student/opportunity", "机会库", "student_opportunity.png"),
    ("/student/plan", "生涯规划", "student_plan.png"),
    ("/student/interview", "模拟面试", "student_interview.png"),
    ("/student/kg", "知识图谱", "student_kg.png"),
    ("/student/campus", "校园洞察", "student_campus.png"),
    ("/student/assistant", "AI 助手", "student_assistant.png"),
]
TEACHER_PAGES = [
    ("/teacher", "学生", "teacher_home.png"),
    ("/teacher/career", "生涯规划", "teacher_career.png"),
    ("/teacher/campus", "校园洞察", "teacher_campus.png"),
    ("/teacher/opportunity", "机会库", "teacher_opportunity.png"),
    ("/teacher/approvals", "工作流审批", "teacher_approvals.png"),
    ("/teacher/kg", "知识图谱", "teacher_kg.png"),
    ("/teacher/assistant", "AI 助手", "teacher_assistant.png"),
]


def check(name: str, ok: bool, detail: str = "") -> None:
    """记录一条 PASS/FAIL 并即时打印，detail 用于失败定位。"""
    line = f"{name}{' — ' + detail if detail else ''}"
    (PASS if ok else FAIL).append(line)
    print(("PASS " if ok else "FAIL ") + line, flush=True)


def http_get(path: str, token: str | None = None) -> dict:
    """只读 GET，返回 JSON dict；失败抛出由调用方归类。"""
    req = urllib.request.Request(BASE + path)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def login_api(role: str, account: str, password: str) -> str:
    """只读登录取 token，不做任何业务写入。"""
    req = urllib.request.Request(
        BASE + "/auth/login",
        data=json.dumps({"role": role, "account": account,
                         "password": password}).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))["access_token"]


def probe_http() -> None:
    """HTTP 层：首页、health 四项、登录 API。"""
    try:
        req = urllib.request.Request(BASE + "/", method="GET")
        with urllib.request.urlopen(req, timeout=30) as r:
            check("HTTP 首页返回 200", r.status == 200, f"status={r.status}")
    except Exception as exc:  # noqa: BLE001 - 验证脚本需归类任何访问失败
        check("HTTP 首页返回 200", False, str(exc))

    try:
        health = http_get("/health")
        check("health 四项 status=ok", health.get("status") == "ok",
              f"status={health.get('status')}")
        check("health 四项 db=ok", health.get("db") == "ok",
              f"db={health.get('db')}")
        check("health 四项 duckdb=ok", health.get("duckdb") == "ok",
              f"duckdb={health.get('duckdb')}")
        check("health 四项 llm=configured", health.get("llm") == "configured",
              f"llm={health.get('llm')}")
    except Exception as exc:  # noqa: BLE001
        check("health 四项可读", False, str(exc))

    try:
        token = login_api("student", "AI20230001", "123456h")
        check("API 登录可取 token（只读）", bool(token), f"len={len(token or '')}")
    except Exception as exc:  # noqa: BLE001
        check("API 登录可取 token（只读）", False, str(exc))


def do_login(page: Page, demo_button: str, url_fragment: str) -> None:
    """清态后点击演示账号登录，等待进入对应角色主页。"""
    page.goto(f"{BASE}/login", wait_until="domcontentloaded")
    page.evaluate("localStorage.clear()")
    page.goto(f"{BASE}/login", wait_until="domcontentloaded")
    page.get_by_role("button", name=demo_button).click()
    page.get_by_role("button", name="进入工作台").click()
    page.wait_for_url(f"**/{url_fragment}**", timeout=30000)


def visit(page: Page, path: str, title_kw: str, shot: str) -> None:
    """进入一个 SPA 路由，校验标题与非空白，并截图落盘。"""
    page.goto(f"{BASE}{path}", wait_until="domcontentloaded")
    page.wait_for_timeout(1200)
    title = page.title()
    body = page.inner_text("body").strip()
    ok = (title_kw in title) and len(body) > 80
    check(f"页面 {path} 渲染", ok,
          f"title={title!r} body={len(body)}字")
    page.screenshot(path=str(SHOT_DIR / shot), full_page=False)


def probe_browser() -> None:
    """浏览器层：控制台 0 错误 + 学生/教师各板块页渲染。"""
    console_errors: list[str] = []
    server_errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=str(CHROME))
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.on("console",
                lambda m: console_errors.append(f"[console] {m.text}")
                if m.type == "error" else None)
        page.on("pageerror", lambda e: console_errors.append(f"[pageerror] {e}"))
        page.on("response",
                lambda r: server_errors.append(f"{r.status} {r.url}")
                if r.status >= 500 else None)

        page.goto(f"{BASE}/login", wait_until="domcontentloaded")
        page.wait_for_timeout(800)
        check("登录页渲染", "进入工作台" in page.inner_text("body"))
        page.screenshot(path=str(SHOT_DIR / "00_login.png"), full_page=False)

        do_login(page, "学生（大四）：AI20230001", "student")
        check("学生登录进入工作台", "/student" in page.url, page.url)
        for path, title_kw, shot in STUDENT_PAGES:
            visit(page, path, title_kw, shot)

        do_login(page, "教师：T001", "teacher")
        check("教师登录进入工作台", "/teacher" in page.url, page.url)
        for path, title_kw, shot in TEACHER_PAGES:
            visit(page, path, title_kw, shot)

        check("控制台 0 错误", not console_errors,
              "；".join(console_errors[:3]))
        check("无 5xx 响应", not server_errors,
              "；".join(server_errors[:3]))
        browser.close()


def main() -> int:
    probe_http()
    probe_browser()
    print(f"\n=== {len(PASS)} PASS / {len(FAIL)} FAIL ===")
    if FAIL:
        print("失败项：")
        for item in FAIL:
            print(f"  - {item}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
