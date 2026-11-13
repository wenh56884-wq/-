# 职责：一键启动本地隔离的公网演示服务与 Cloudflare 临时隧道。
# 依赖：Python 标准库、Node.js/npm、cloudflared、项目虚拟环境及数据库。
# 说明：每次启动随机生成演示口令与 JWT 密钥，只允许指定的合成演示账号。

from __future__ import annotations

import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
DEMO_ACCOUNTS = (
    "teacher:T001,student:AI20260001,student:AI20250001,"
    "student:AI20240004,student:AI20230001"
)
TUNNEL_URL_PATTERN = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def _available_port() -> int:
    """获取一个当前可用的本机临时端口。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _http_ready(url: str) -> bool:
    """判断本机端口上是否已有可复用的 HTTP 服务。"""
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _start_local_stack() -> tuple[list[subprocess.Popen[bytes]], bool, bool]:
    """启动独立的本地开发登录入口；公网演示隔离服务不覆盖本地账号口令。"""
    processes: list[subprocess.Popen[bytes]] = []
    backend_ready = _http_ready("http://127.0.0.1:8000/health")
    frontend_ready = _http_ready("http://127.0.0.1:5173/")

    env = os.environ.copy()
    # 不让父 shell 偶然残留的公网演示开关污染本地账号认证。
    for key in ("PUBLIC_DEMO_MODE", "PUBLIC_DEMO_PASSWORD", "PUBLIC_DEMO_ACCOUNTS"):
        env.pop(key, None)
    env["APP_PORT"] = "8000"

    try:
        if not backend_ready:
            print("[本地] 正在启动标准账号登录服务（127.0.0.1:8000）…", flush=True)
            processes.append(subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "app.main:app", "--host",
                 "127.0.0.1", "--port", "8000", "--workers", "1"],
                cwd=ROOT,
                env=env,
            ))
            _wait_for_health(processes[-1], 8000)

        if not frontend_ready:
            npm = shutil.which("npm.cmd") or shutil.which("npm")
            if not npm:
                raise RuntimeError("未找到 npm，无法启动本地登录页面。")
            print("[本地] 正在启动标准登录页面（127.0.0.1:5173）…", flush=True)
            processes.append(subprocess.Popen(
                [npm, "run", "dev", "--", "--host", "127.0.0.1", "--port", "5173"],
                cwd=WEB,
                env=env,
            ))
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                if processes[-1].poll() is not None:
                    raise RuntimeError("本地前端意外退出，请检查 npm 启动日志。")
                if _http_ready("http://127.0.0.1:5173/"):
                    break
                time.sleep(0.5)
            else:
                raise RuntimeError("本地前端启动超时，请检查 5173 端口与 npm 日志。")
    except Exception:
        for process in reversed(processes):
            _stop_process(process)
        raise

    return processes, backend_ready, frontend_ready


def _run_frontend_build() -> None:
    """用公网登录页配置构建前端；缺少 Node 依赖时明确报错。"""
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if not npm:
        raise RuntimeError("未找到 npm，请先安装 Node.js 18 或更新版本。")
    if not (WEB / "node_modules").is_dir():
        raise RuntimeError("未找到 web/node_modules，请先在 web 目录执行 npm install。")

    env = os.environ.copy()
    env["VITE_PUBLIC_DEMO_MODE"] = "true"
    print("[1/4] 正在构建公网演示版前端…", flush=True)
    subprocess.run([npm, "run", "build"], cwd=WEB, env=env, check=True)


def _wait_for_health(process: subprocess.Popen[bytes], port: int) -> None:
    """等待本地服务健康检查通过，或在启动失败时给出提示。"""
    url = f"http://127.0.0.1:{port}/health"
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("网站服务意外退出；请检查刚才显示的启动错误。")
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(0.5)
    raise RuntimeError("网站服务启动超时；请检查 MySQL、DuckDB 与启动日志。")


def _start_tunnel(executable: str, port: int) -> tuple[subprocess.Popen[str], str]:
    """启动 Cloudflare Quick Tunnel 并等待其分配的 HTTPS 地址。"""
    print("[3/4] 正在建立 Cloudflare 临时公网隧道…", flush=True)
    process = subprocess.Popen(
        [executable, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    assert process.stdout is not None
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline and process.poll() is None:
        line = process.stdout.readline()
        if not line:
            continue
        print(line.rstrip(), flush=True)
        match = TUNNEL_URL_PATTERN.search(line)
        if match:
            return process, match.group(0)
    raise RuntimeError("等待 Cloudflare 公网网址超时；请检查网络后重试。")


def _stop_process(process: subprocess.Popen[object] | None) -> None:
    """优雅停止本启动器创建的子进程，不触碰其他已有服务。"""
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main() -> int:
    """构建前端、启动隔离服务和隧道，并在退出时清理子进程。"""
    cloudflared = shutil.which("cloudflared.exe") or shutil.which("cloudflared")
    if not cloudflared:
        default = Path(r"C:\Program Files (x86)\cloudflared\cloudflared.exe")
        if default.is_file():
            cloudflared = str(default)
        else:
            print("未找到 cloudflared，请先安装 Cloudflare Tunnel。", file=sys.stderr)
            return 1

    password = secrets.token_urlsafe(32)
    jwt_secret = secrets.token_urlsafe(48)
    port = _available_port()
    env = os.environ.copy()
    env.update(
        {
            "PUBLIC_DEMO_MODE": "true",
            "PUBLIC_DEMO_PASSWORD": password,
            "PUBLIC_DEMO_ACCOUNTS": DEMO_ACCOUNTS,
            "JWT_SECRET": jwt_secret,
            "APP_PORT": str(port),
        }
    )

    web_process: subprocess.Popen[bytes] | None = None
    tunnel_process: subprocess.Popen[str] | None = None
    local_processes: list[subprocess.Popen[bytes]] = []
    try:
        local_processes, backend_reused, frontend_reused = _start_local_stack()
        print(
            "[本地] 标准账号入口已就绪："
            f"http://127.0.0.1:5173/（后端 {'复用' if backend_reused else '新启动'}，"
            f"前端 {'复用' if frontend_reused else '新启动'}）",
            flush=True,
        )
        _run_frontend_build()
        print("\n[2/4] 正在启动仅绑定本机的演示服务…", flush=True)
        web_process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--workers",
                "1",
            ],
            cwd=ROOT,
            env=env,
        )
        _wait_for_health(web_process, port)
        print("网站健康检查通过；只允许以下演示账号登录：", flush=True)
        print("教师：T001", flush=True)
        print("大一：AI20260001", flush=True)
        print("大二：AI20250001", flush=True)
        print("大三：AI20240004", flush=True)
        print("大四：AI20230001", flush=True)
        print(f"本次共享口令：{password}", flush=True)
        tunnel_process, public_url = _start_tunnel(cloudflared, port)
        print("\n[4/4] 公网演示已启动", flush=True)
        print("本机标准账号：http://127.0.0.1:5173/（原有账号密码）", flush=True)
        print(f"本机公网演示版：http://127.0.0.1:{port}/（仅演示账号）", flush=True)
        print(f"公网访问：{public_url}/", flush=True)
        print("演示账号（教师和各年级学生共用以下密码）：", flush=True)
        print(f"教师：T001  / {password}", flush=True)
        print(f"大一：AI20260001  / {password}", flush=True)
        print(f"大二：AI20250001  / {password}", flush=True)
        print(f"大三：AI20240004  / {password}", flush=True)
        print(f"大四：AI20230001  / {password}", flush=True)
        print("请将公网地址和对应账号密码提供给访问者；运行期间勿关闭此窗口。", flush=True)
        print("\n按 Ctrl+C 可停止公网隧道和演示服务。", flush=True)

        assert tunnel_process.stdout is not None
        for line in tunnel_process.stdout:
            print(line.rstrip(), flush=True)
        return int(tunnel_process.wait() or 0)
    except KeyboardInterrupt:
        print("\n正在关闭公网演示…", flush=True)
        return 0
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"\n启动失败：{exc}", file=sys.stderr, flush=True)
        return 1
    finally:
        _stop_process(tunnel_process)
        _stop_process(web_process)
        for process in reversed(local_processes):
            _stop_process(process)
        print("演示服务已停止。", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
