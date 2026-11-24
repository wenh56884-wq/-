# -*- coding: utf-8 -*-
# 职责：用 Playwright 对「创新全景」看板做四档宽度视觉验收（截图 + 横向溢出断言 + 卡片/canvas 计数）。
# 身份：直连后端 /auth/login 取 JWT，注入 localStorage(qh_token/qh_role)；页面 /api/* 请求拦截转发到后端端口。
# 用法：.venv\Scripts\python.exe scripts/innov_shot_check.py（后端默认 8001、前端默认 5173，未起先起）。
"""创新全景看板四档宽度视觉验收。

说明（与任务口径的两处差异，均为实测结论）：
- 路由：仓库没有裸 `/innovation`，看板按角色挂载为 `/teacher/innovation` 与
  `/student/innovation`（见 web/src/router/index.js）。T001 为教师，故进 /teacher/innovation。
- 代理：web/vite.config.js 的 dev proxy 把 /api 硬编码转发到 8000，而后端在 8001。
  本脚本不改任何现有文件，改用 Playwright 请求拦截把页面 /api/* 服务端转发到后端端口，
  从而绕开 8000 代理与浏览器 CORS 限制。

环境变量：QH_BACKEND(默认 http://127.0.0.1:8001)、QH_FRONTEND(默认 http://localhost:5173)、
QH_ACCOUNT(默认 T001)、QH_PASSWORD(默认 123456h)、QH_ROLE(默认按账号推断)、
QH_ROUTE(默认按角色推导)、QH_SHOT_PREFIX(默认 qwen_，避免覆盖既有截图)。任一档失败则退出码非 0。
"""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.sync_api import Route, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BACKEND = os.environ.get("QH_BACKEND", "http://127.0.0.1:8001").rstrip("/")
FRONTEND = os.environ.get("QH_FRONTEND", "http://localhost:5173").rstrip("/")
ACCOUNT = os.environ.get("QH_ACCOUNT", "T001")
PASSWORD = os.environ.get("QH_PASSWORD", "123456h")
ROLE = os.environ.get("QH_ROLE", "teacher" if ACCOUNT.startswith("T") else "student")
ROUTE = os.environ.get("QH_ROUTE", "")  # 空则按角色推导 /teacher/innovation 或 /student/innovation
SHOT_PREFIX = os.environ.get("QH_SHOT_PREFIX", "qwen_")
SHOTS = ROOT / "shots"
LOGS = ROOT / "logs"
WIDTHS: list[tuple[int, int]] = [(1920, 1080), (1440, 900), (1024, 768), (390, 844)]


def _host_port(url: str) -> tuple[str, int]:
    parsed = urlparse(url)
    return parsed.hostname or "127.0.0.1", parsed.port or (443 if parsed.scheme == "https" else 80)


def _port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _wait_port(host: str, port: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _port_open(host, port):
            return True
        time.sleep(0.5)
    return False


def ensure_backend() -> None:
    host, port = _host_port(BACKEND)
    if _port_open(host, port):
        return
    LOGS.mkdir(parents=True, exist_ok=True)
    log = open(LOGS / "innov_backend.log", "ab")
    subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", host, "--port", str(port)],
        cwd=str(ROOT), stdout=log, stderr=log,
    )
    if not _wait_port(host, port, 60):
        raise RuntimeError(f"后端 {BACKEND} 启动超时（见 logs/innov_backend.log）")


def ensure_frontend() -> None:
    host, port = _host_port(FRONTEND)
    if _port_open(host, port):
        return
    LOGS.mkdir(parents=True, exist_ok=True)
    log = open(LOGS / "innov_frontend.log", "ab")
    subprocess.Popen(
        "npm run dev", cwd=str(ROOT / "web"), shell=True, stdout=log, stderr=log,
    )
    if not _wait_port(host, port, 90):
        raise RuntimeError(f"前端 {FRONTEND} 启动超时（见 logs/innov_frontend.log）")


def login() -> dict[str, Any]:
    req = urllib.request.Request(
        BACKEND + "/auth/login",
        data=json.dumps({"role": ROLE, "account": ACCOUNT, "password": PASSWORD}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def make_api_proxy() -> Any:
    """把页面 /api/* 服务端转发到后端（去掉 /api 前缀），绕开 vite 8000 代理与 CORS。"""
    drop_req = {"host", "accept-encoding", "content-length", "connection"}
    drop_resp = {"content-encoding", "content-length", "transfer-encoding", "connection"}

    def handler(route: Route) -> None:
        request = route.request
        parsed = urlparse(request.url)
        path = parsed.path
        path = path[len("/api"):] if path.startswith("/api") else path
        target = BACKEND + (path or "/") + (f"?{parsed.query}" if parsed.query else "")
        headers = {k: v for k, v in request.headers.items() if k.lower() not in drop_req}
        body = request.post_data_buffer
        try:
            req = urllib.request.Request(target, data=body, headers=headers, method=request.method)
            with urllib.request.urlopen(req, timeout=60) as resp:
                rh = {k: v for k, v in resp.headers.items() if k.lower() not in drop_resp}
                route.fulfill(status=resp.status, headers=rh, body=resp.read())
        except urllib.error.HTTPError as exc:
            rh = {k: v for k, v in exc.headers.items() if k.lower() not in drop_resp}
            route.fulfill(status=exc.code, headers=rh, body=exc.read())
        except Exception as exc:  # noqa: BLE001 - 转发失败如实回 502，便于看板报错而非静默
            route.fulfill(status=502, contentType="application/json",
                          body=json.dumps({"detail": f"api proxy error: {exc}"}))

    return handler


def goto_mounted(page: Any, url: str, selector: str, tries: int = 4) -> bool:
    """导航并等待 Vue 真正挂载；vite 首次 dep 优化可能整页重载，故重试。"""
    for _ in range(tries):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_selector(selector, state="attached", timeout=20000)
            return True
        except Exception:  # noqa: BLE001 - 预热重载/超时则重试
            continue
    return False


MEASURE_JS = """() => {
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
  };
  const count = (sel) => Array.from(document.querySelectorAll(sel)).filter(visible).length;
  const heat = document.querySelector('.chart-canvas.is-tall');
  return {
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
    kpi_visible: count('.kpi-card'),
    kpi_total: document.querySelectorAll('.kpi-card').length,
    step_visible: count('.step-card'),
    step_total: document.querySelectorAll('.step-card').length,
    canvas: document.querySelectorAll('canvas').length,
    heat_present: !!heat,
    heat_w: heat ? heat.clientWidth : 0,
    heat_h: heat ? heat.clientHeight : 0,
    path: location.pathname,
  };
}"""


def run() -> dict[str, Any]:
    ensure_backend()
    ensure_frontend()
    session = login()
    token = session["access_token"]
    role = session.get("role", ROLE)
    tenant_id = session.get("tenant_id")
    student_no = session.get("student_no")
    target = ROUTE or ("/teacher/innovation" if role == "teacher" else "/student/innovation")
    SHOTS.mkdir(parents=True, exist_ok=True)

    console_errors: list[str] = []
    console_warnings: list[str] = []
    rows: list[dict[str, Any]] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={"width": WIDTHS[0][0], "height": WIDTHS[0][1]})
        context.route(re.compile(r"^https?://[^/]+/api/"), make_api_proxy())
        page = context.new_page()
        def on_console(m: Any) -> None:
            if m.type == "error":
                console_errors.append(f"{m.type}: {m.text}")
            elif m.type == "warning":
                console_warnings.append(f"{m.type}: {m.text}")
        page.on("console", on_console)
        page.on("pageerror", lambda e: console_errors.append(f"pageerror: {e}"))

        if not goto_mounted(page, FRONTEND + "/login", "#app > *"):
            raise RuntimeError("前端登录页未能挂载（vite 模块加载失败，见 logs/innov_frontend.log）")
        page.evaluate(
            """([t, r, tid, sno]) => {
              localStorage.setItem('qh_token', t);
              localStorage.setItem('qh_role', r);
              if (tid !== null && tid !== undefined) localStorage.setItem('qh_tenant_id', String(tid));
              if (sno) localStorage.setItem('qh_student_no', String(sno));
            }""",
            [token, role, tenant_id, student_no],
        )

        for width, height in WIDTHS:
            page.set_viewport_size({"width": width, "height": height})
            mounted = goto_mounted(page, FRONTEND + target, ".innovation-hub")
            try:
                page.wait_for_selector(".kpi-card", state="attached", timeout=20000)
            except Exception:  # noqa: BLE001 - 数据缺失时卡片可能不渲染，仍如实计数
                pass
            page.wait_for_timeout(2000)
            # 滚动一遍触发 IntersectionObserver reveal，再回顶部，保证下方卡片也进入可见态
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(800)
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(400)
            metrics = page.evaluate(MEASURE_JS)
            shot = SHOTS / f"{SHOT_PREFIX.rstrip('_')}_innov_{width}.png"
            page.screenshot(path=str(shot), full_page=True)
            overflow_ok = metrics["scrollWidth"] <= metrics["innerWidth"] + 1
            on_route = metrics["path"].endswith("/innovation")
            heat_ok = metrics["heat_w"] > 0 and metrics["heat_h"] > 0
            ok = bool(mounted and overflow_ok and on_route and heat_ok)
            rows.append({
                "width": width, "height": height,
                "scrollWidth": metrics["scrollWidth"], "innerWidth": metrics["innerWidth"],
                "overflow_ok": overflow_ok, "on_route": on_route, "board_mounted": mounted,
                "kpi_visible": metrics["kpi_visible"], "kpi_total": metrics["kpi_total"],
                "step_visible": metrics["step_visible"], "step_total": metrics["step_total"],
                "canvas": metrics["canvas"],
                "heat_present": metrics["heat_present"], "heat_w": metrics["heat_w"],
                "heat_h": metrics["heat_h"], "heat_ok": heat_ok,
                "screenshot": str(shot.relative_to(ROOT)), "ok": ok,
            })
        browser.close()

    all_ok = all(r["ok"] for r in rows)
    return {
        "backend": BACKEND, "frontend": FRONTEND, "account": ACCOUNT, "role": role,
        "target": target, "all_ok": all_ok, "widths": rows,
        "console_errors": console_errors[:20], "console_error_count": len(console_errors),
        "console_warnings": console_warnings[:20], "console_warning_count": len(console_warnings),
    }


def main() -> int:
    try:
        result = run()
    except Exception as exc:  # noqa: BLE001 - 任何异常都以非 0 退出并打印 JSON
        print(json.dumps({"all_ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["all_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())