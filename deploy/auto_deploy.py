"""启航系统 · 版本变动自动部署（指纹巡检 + 按需上传）

原理：对本地 web 前端源码与后端代码分别算指纹（相对路径+大小+mtime），
与上次成功部署的基线比对。只有变动的一侧才执行构建/上传/重建；
两侧都没变则直接返回 NO_CHANGE，不碰服务器。

前置条件：
  - ssh 免密：~/.ssh/qihang_deploy 已写入服务器 authorized_keys
  - 本机有 ssh / scp / tar / npx（Git Bash 或 Windows 自带均可）

用法：
  python deploy/auto_deploy.py            # 巡检，变动才部署
  python deploy/auto_deploy.py --force    # 忽略指纹，强制全量部署
  python deploy/auto_deploy.py --init     # 只把当前状态记为基线，不部署

输出约定（供自动化读取）：
  RESULT: NO_CHANGE   双侧无变动
  RESULT: DEPLOYED    部署成功，后跟变动摘要
  RESULT: FAILED      任一步失败（exit 1）
"""
import fnmatch
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEPLOY = os.path.join(ROOT, "deploy")
HOST = os.environ.get("QH_HOST", "101.34.254.115")
USER = os.environ.get("QH_USER", "root")
KEY = os.path.expanduser("~/.ssh/qihang_deploy")
FP_WEB = os.path.join(DEPLOY, ".fp_web.json")
FP_BACKEND = os.path.join(DEPLOY, ".fp_backend.json")

WEB_TRACK = ["web/src", "web/public", "web/index.html",
             "web/vite.config.js", "web/package.json"]
BACKEND_TRACK = ["app", "engine", "rules", "agents", "features", "etl", "db",
                 "scripts", "Dockerfile", "requirements.txt",
                 "docker-compose.yml", "pytest.ini", "deploy/run_stack.sh"]
SKIP_DIRS = {"__pycache__", "node_modules", ".git", "dist", "dist-twin",
             "dist-cloud", "logs"}
SKIP_PAT = ["*.pyc", "*.log", "*.tar.gz"]


def run(cmd, cwd=None, timeout=600):
    p = subprocess.run(cmd, cwd=cwd or ROOT, timeout=timeout,
                       capture_output=True, text=True,
                       errors="replace", shell=False)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def fingerprint():
    """返回 (web指纹, 后端指纹) 两个 dict: {相对路径: 大小_mtime}"""
    def walk(rel):
        full = os.path.join(ROOT, rel)
        if os.path.isfile(full):
            st = os.stat(full)
            return {rel.replace("\\", "/"): f"{st.st_size}:{int(st.st_mtime_ns)}"}
        out = {}
        for dirpath, dirnames, filenames in os.walk(full):
            dirnames[:] = [d for d in dirnames
                           if d not in SKIP_DIRS and not d.endswith(".egg-info")]
            for fn in filenames:
                if any(fnmatch.fnmatch(fn, p) for p in SKIP_PAT):
                    continue
                fp = os.path.join(dirpath, fn)
                try:
                    st = os.stat(fp)
                except OSError:
                    continue
                relp = os.path.relpath(fp, ROOT).replace("\\", "/")
                out[relp] = f"{st.st_size}:{int(st.st_mtime_ns)}"
        return out

    fw, fb = {}, {}
    for rel in WEB_TRACK:
        fw.update(walk(rel))
    for rel in BACKEND_TRACK:
        fb.update(walk(rel))
    return fw, fb


def load(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def save(path, data):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)


def ssh_cmd(script, timeout=900):
    return run(["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no",
                "-o", "LogLevel=ERROR",
                "-o", "ConnectTimeout=20", f"{USER}@{HOST}", script],
               timeout=timeout)


def changed_files(old, new):
    old = old or {}
    return sorted([k for k in new if old.get(k) != new[k]]
                  + [k for k in old if k not in new])


def rebuild_app():
    """web/dist 是 COPY 进镜像的（非挂载卷）：前端文件换完也必须重建镜像重启容器才生效。"""
    code, msg = ssh_cmd(
        "cd /opt/qihang && docker build -t qihang-app:latest . 2>&1 | tail -2 "
        "&& docker rm -f qihang-app && bash deploy/run_stack.sh app 2>&1 | tail -3",
        timeout=1200)
    if code != 0:
        return False, f"镜像重建失败: {msg[-600:]}"
    return True, "镜像重建+容器重启完成"


def deploy_frontend():
    # 1. 构建（dist-cloud 全新清空重建，避免旧 chunk 残留）
    npx = "npx.cmd" if os.name == "nt" else "npx"
    code, msg = run([npx, "vite", "build", "--outDir", "dist-cloud",
                     "--emptyOutDir", "true"],
                    cwd=os.path.join(ROOT, "web"), timeout=300)
    if code != 0:
        return False, f"前端构建失败: {msg[-600:]}"
    # 2. 打包上传（注意：产物在 web/dist-cloud，归档根为 web/dist-cloud/）
    tgz = os.path.join(DEPLOY, "web-auto.tar.gz")
    code, msg = run(["tar", "czf", tgz, "web/dist-cloud"], cwd=ROOT)
    if code != 0:
        return False, f"前端打包失败: {msg[-400:]}"
    code, msg = run(["scp", "-i", KEY, "-o", "StrictHostKeyChecking=no",
                     tgz, f"{USER}@{HOST}:/opt/qihang/"], timeout=300)
    if code != 0:
        return False, f"前端上传失败: {msg[-400:]}"
    # 3. 服务器换目录
    code, msg = ssh_cmd(
        "cd /opt/qihang && rm -rf web/dist-old && "
        "{ [ -d web/dist ] && mv web/dist web/dist-old || true; } && "
        "tar xzf web-auto.tar.gz && mv web/dist-cloud web/dist && "
        "rm -rf web/dist-old web-auto.tar.gz && "
        "grep -o 'assets/index[^\"]*\\.js' web/dist/index.html")
    if code != 0:
        return False, f"前端换目录失败: {msg[-400:]}"
    good, rmsg = rebuild_app()
    if not good:
        return False, f"前端已上传但未生效: {rmsg}"
    return True, f"前端已更新（{msg.strip().splitlines()[-1] if msg.strip() else 'ok'}）"


def deploy_backend():
    tgz = os.path.join(DEPLOY, "code-auto.tar.gz")
    names = [n for n in BACKEND_TRACK if os.path.exists(os.path.join(ROOT, n))]
    run(["tar", "czf", tgz] + names, cwd=ROOT)
    code, msg = run(["scp", "-i", KEY, "-o", "StrictHostKeyChecking=no",
                     tgz, f"{USER}@{HOST}:/opt/qihang/"], timeout=300)
    if code != 0:
        return False, f"后端上传失败: {msg[-400:]}"
    # 覆盖目录前先清掉旧目录（保证服务器上不残留已删除的文件）
    dirs = " ".join(n for n in names if "." not in n)
    code, msg = ssh_cmd(
        f"cd /opt/qihang && rm -rf {dirs} && tar xzf code-auto.tar.gz "
        f"&& rm -f code-auto.tar.gz")
    if code != 0:
        return False, f"后端解包失败: {msg[-400:]}"
    return rebuild_app()


def health():
    code, msg = ssh_cmd("docker exec qihang-app curl -sS "
                        "http://127.0.0.1:8000/health", timeout=60)
    if code == 0:
        for line in msg.strip().splitlines():
            if "status" in line:
                return line.strip()
    return f"health异常({code})"


def main():
    force = "--force" in sys.argv
    init = "--init" in sys.argv
    fw, fb = fingerprint()
    old_w, old_b = load(FP_WEB), load(FP_BACKEND)

    if init:
        save(FP_WEB, fw)
        save(FP_BACKEND, fb)
        print("RESULT: BASELINE_SET 基线已记录，未部署")
        return 0

    w_change = changed_files(old_w, fw)
    b_change = changed_files(old_b, fb)
    if not force and not w_change and not b_change:
        print("RESULT: NO_CHANGE 无版本变动，跳过部署")
        return 0

    print(f"[变动] 前端 {len(w_change)} 个文件 / 后端 {len(b_change)} 个文件")
    for k in (w_change + b_change)[:12]:
        print(f"  - {k}")
    if len(w_change) + len(b_change) > 12:
        print(f"  ... 共 {len(w_change) + len(b_change)} 个")

    steps = []
    ok = True
    if force or w_change:
        good, msg = deploy_frontend()
        steps.append(("前端", msg))
        ok = ok and good
    if force or b_change:
        good, msg = deploy_backend()
        steps.append(("后端", msg))
        ok = ok and good

    if ok:
        save(FP_WEB, fw)
        save(FP_BACKEND, fb)
        for tag, msg in steps:
            print(f"  [{tag}] {msg}")
        print(f"  [health] {health()}")
        print(f"RESULT: DEPLOYED {', '.join(t for t, _ in steps)} @ "
              f"http://{HOST}/ {time.strftime('%H:%M')}")
        return 0
    for tag, msg in steps:
        print(f"  [{tag}] {msg}")
    print("RESULT: FAILED 部署失败，指纹未更新（下次巡检会重试）")
    return 1


if __name__ == "__main__":
    sys.exit(main())
