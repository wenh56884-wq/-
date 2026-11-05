# scripts/verify_pet.py
# 职责：AI 宠物陪伴模块的端到端自检——真打 HTTP、真调模型，逐环节报通过/失败
# 依赖：服务已启动（uvicorn app.main:app）+ MySQL 已就绪（pet 表由启动时幂等建表）
# 说明：
#   1) 这个脚本验证「接口能用 + 链路闭环 + 身份隔离」，不验证文案质量
#      （文案由模型写，每次不同，不该进断言）。
#   2) 长期记忆的编辑验证采用「改一次再改回」，不破坏演示账号的已有记忆；
#      删除验证只打不存在的编号（404 路径），不删真实数据。
#   3) 退出码：0 全通过；1 有失败项（可直接进 CI / 演示前自检）。
# 用法：.venv\Scripts\python.exe scripts\verify_pet.py [--account AI20260001]

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# 直接 `python scripts/verify_pet.py` 运行时，sys.path[0] 是 scripts/，
# 根目录不在路径上 → `from app.config import ...` 被 ImportError 吞掉，
# 表现为「登录 401」假报警。这里显式把项目根挂上，与 `-m` 形式行为一致。
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# 服务端口可配：本机常有多个 uvicorn 同时在跑，QH_BASE 覆盖，或 --base 传参。
BASE = os.getenv("QH_BASE", "http://127.0.0.1:8000")
VALID_MOOD = {"idle", "happy", "thinking", "sleepy"}

_checks: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, note: str = "") -> None:
    _checks.append((name, bool(ok), note))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {note}" if note else ""))


def _req(method: str, path: str, token: str | None = None, body: Any = None) -> tuple[int, Any]:
    url = BASE + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if data:
        headers["Content-Type"] = "application/json"
    rq = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(rq, timeout=180) as resp:
            raw = resp.read().decode("utf-8", "ignore")
            try:
                return resp.status, (json.loads(raw) if raw else {})
            except json.JSONDecodeError:
                # 200 + 非 JSON 多半是打到了旧版本服务（404 被 StaticFiles 兜底成 index.html）
                return resp.status, {"detail": "非 JSON 响应（服务可能是旧版本）", "_raw": raw[:120]}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "ignore")
        try:
            return exc.code, json.loads(raw)
        except Exception:
            return exc.code, {"detail": raw[:300]}
    except urllib.error.URLError as exc:
        print(f"\n[致命] 连不上 {BASE}：{exc.reason}")
        print("请先启动服务：.venv\\Scripts\\python.exe -m uvicorn app.main:app --port 8000")
        raise SystemExit(1)


def _pick_demo_account() -> str | None:
    """从库里挑一个真实存在的学生学号当演示账号（口令同学号）。"""
    try:
        import pymysql

        from app.config import get_settings
    except ImportError:
        return None
    s = get_settings()
    try:
        conn = pymysql.connect(
            host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
            password=s.mysql_password, database=s.mysql_db, charset="utf8mb4",
        )
    except pymysql.MySQLError:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT `学号` FROM `学生` WHERE `租户编号` = 1 "
                "ORDER BY `学号` LIMIT 1"
            )
            row = cur.fetchone()
            return str(row[0]) if row else None
    except pymysql.MySQLError:
        return None
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", default=None,
                    help="学生学号（演示账号口令同学号）；不传则从库里取一个真实学号")
    ap.add_argument("--base", default=None, help="服务基地址，默认 http://127.0.0.1:8000")
    args = ap.parse_args()
    global BASE
    if args.base:
        BASE = args.base
    account = args.account or _pick_demo_account() or "AI20260001"

    print("=" * 66)
    print("启航 · AI 宠物陪伴模块端到端自检")
    print("=" * 66)

    # ---- 0 健康 ----
    code, health = _req("GET", "/health")
    print(f"\n[0] 服务健康  HTTP {code}")
    if code != 200:
        print("服务不健康，后续无法继续")
        return 1

    # ---- 1 登录 ----
    code, login = _req("POST", "/auth/login",
                       body={"role": "student", "account": account, "password": account})
    print(f"\n[1] 登录 {account}  HTTP {code}")
    if code != 200:
        print(f"  detail: {login}")
        print("  → 演示账号口令 = 学号本身；确认 seed_mock 已跑过")
        return 1
    token = login["access_token"]
    check("登录拿到 token", bool(token))

    # ---- 2 未认证必须 401 ----
    code, _ = _req("GET", "/pet/state")
    check("未带 token 访问 /pet/state 返回 401", code == 401, f"实际 {code}")

    # ---- 3 状态 ----
    code, state = _req("GET", "/pet/state", token=token)
    print(f"\n[3] 宠物状态  HTTP {code}  mood={state.get('mood')}  name={state.get('name')}")
    check("状态接口返回合法心情", state.get("mood") in VALID_MOOD,
          f"实际 {state.get('mood')}")
    check("人格名字非空", bool(state.get("name")))

    # ---- 4 对话（真调 LLM，失败也有模板兜底）----
    code, chat = _req("POST", "/pet/chat", token=token,
                      body={"text": "今天有点累，陪我聊两句"})
    print(f"\n[4] 对话  HTTP {code}  degraded={chat.get('degraded')}  mood={chat.get('mood')}")
    check("对话返回非空回复", bool(chat.get("reply")), str(chat.get("reply"))[:30])
    check("对话心情合法", chat.get("mood") in VALID_MOOD)
    check("degraded 标志为布尔", isinstance(chat.get("degraded"), bool))

    # ---- 5 专注模式 ----
    code, on = _req("POST", "/pet/focus", token=token, body={"on": True})
    check("开启专注后 focus_mode=True", on.get("focus_mode") is True)
    code, off = _req("POST", "/pet/focus", token=token, body={"on": False})
    check("关闭专注后 focus_mode=False", off.get("focus_mode") is False)

    # ---- 6 长期记忆列表 ----
    code, mems = _req("GET", "/pet/memories", token=token)
    items = mems.get("items") or []
    print(f"\n[6] 长期记忆  HTTP {code}  total={mems.get('total')}")
    check("记忆列表字段齐全", isinstance(items, list)
          and all("id" in i and "content" in i for i in items))

    # ---- 7 记忆编辑（改走"加标记 → 改回"两次真实变更，不破坏演示数据）----
    # 注意：MySQL 对「新值 == 旧值」的 UPDATE 报 affected rows = 0，不能用相同内容验编辑
    if items:
        target = items[0]
        original = target["content"]
        marked = f"{original}（核对）"[:60]
        code, upd = _req("PUT", f"/pet/memories/{target['id']}", token=token,
                         body={"content": marked})
        check("编辑本人记忆返回 updated", code == 200 and upd.get("updated") is True)
        code, back = _req("PUT", f"/pet/memories/{target['id']}", token=token,
                          body={"content": original})
        check("改回原文返回 updated", code == 200 and back.get("updated") is True)
        code, again = _req("GET", "/pet/memories", token=token)
        same = any(i["id"] == target["id"] and i["content"] == original
                   for i in (again.get("items") or []))
        check("编辑后内容可回读", same)
    else:
        check("暂无记忆可编辑（聊几句后再跑可获得）", True, "跳过编辑验证")

    # ---- 8 编辑/删除不存在的记忆必须 404 ----
    code, _ = _req("PUT", "/pet/memories/999999999", token=token,
                   body={"content": "不存在的记忆"})
    check("编辑不存在的记忆返回 404", code == 404, f"实际 {code}")
    code, _ = _req("DELETE", "/pet/memories/999999999", token=token)
    check("删除不存在的记忆返回 404", code == 404, f"实际 {code}")

    # ---- 9 校验拦截 ----
    code, _ = _req("PUT", "/pet/memories/1", token=token, body={"content": "  "})
    check("空白内容编辑返回 422", code == 422, f"实际 {code}")

    # ---- 10 人格 ----
    code, pers = _req("GET", "/pet/personality", token=token)
    print(f"\n[10] 人格  HTTP {code}  name={pers.get('name')}")
    check("人格接口返回名字与鼓励池",
          bool(pers.get("name")) and isinstance(pers.get("encourage"), list))

    # ---- 11 主动说话（到点才说话，未到点静默，两者都是合法返回）----
    code, pro = _req("POST", "/pet/proactive", token=token)
    check("主动说话接口结构合法",
          code == 200 and isinstance(pro.get("spoke"), bool))

    # ---- 汇总 ----
    failed = [c for c in _checks if not c[1]]
    print("\n" + "=" * 66)
    print(f"自检完成：{len(_checks) - len(failed)}/{len(_checks)} 通过")
    if failed:
        print("失败项：")
        for name, _, note in failed:
            print(f"  - {name}" + (f"（{note}）" if note else ""))
        return 1
    print("全部通过 ✔")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
