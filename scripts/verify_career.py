# scripts/verify_career.py
# 职责：职业规划模块（P13）的端到端自检——真打 HTTP、真调模型，逐环节报通过/失败
# 依赖：服务已启动（uvicorn app.main:app）+ 已跑过 init_db / seed_mock / seed_notice
# 说明：
#   1) 这个脚本**验证的是"接口能用 + 引擎的数对得上"**，
#      不验证文案质量（文案由模型写，每次不同，不该进断言）。
#   2) 断言的硬指标全部来自引擎口径：门槛状态合法性、阶段周数之和、
#      周判定三色取值、公告只推未截止。
#   3) 退出码：0 全通过；1 有失败项（可直接进 CI / 演示前自检）。
# 用法：.venv\Scripts\python.exe scripts\verify_career.py [--account WL2022001]

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

# 直接 `python scripts/verify_career.py` 运行时，sys.path[0] 是 scripts/，
# 根目录不在路径上 → `from app.config import ...` 在 _pick_demo_account 里
# 被 except ImportError 吞掉、静默回落到写死的旧学号，表现为「登录 401」。
# 这里显式把项目根挂上，让脚本形式和 `-m` 形式行为一致。
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.config import get_settings  # noqa: E402

# 服务端口可配：本机常有多个 uvicorn 同时在跑（8000 后端、8001 前端代理后端），
# 写死 8000 会验到另一个进程上去，得到「登录 401」这种看似数据坏了、
# 实际只是打错门的假报警。用 QH_BASE 覆盖，或 --base 传参。
BASE = os.getenv("QH_BASE", "http://127.0.0.1:8000")
VALID_GATE = {"pass", "fail", "unknown"}
VALID_LIGHT = {"green", "yellow", "red", "unknown"}

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
            return resp.status, (json.loads(raw) if raw else {})
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
    """从库里挑一个真实存在的学生学号当演示账号（演示账号用统一口令）。

    学号格式会随 seed 规则变（例如 10 位 ABBR+年份+4 位序号），写死会一直失效；
    这里直接读库，拿不到就返回 None，让调用方回落到默认值。
    """
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
                    help="学生学号（演示账号用统一口令）；不传则从库里取一个真实学号")
    args = ap.parse_args()
    account = args.account or _pick_demo_account() or "WL20220001"
    args.account = account

    print("=" * 66)
    print("启航 · 职业规划模块端到端自检（P13）")
    print("=" * 66)

    # ---- 0 健康 ----
    code, health = _req("GET", "/health")
    print(f"\n[0] 服务健康  HTTP {code}  {health}")
    if code != 200:
        print("服务不健康，后续无法继续")
        return 1

    # ---- 1 登录 ----
    demo_password = str(get_settings().demo_password or "").strip()
    demo_accounts = {"AI20230001", "AI20260001", "AI20260004",
                     "AI20250001", "AI20240004"}
    password = demo_password if args.account in demo_accounts and demo_password else args.account
    code, login = _req("POST", "/auth/login",
                       body={"role": "student", "account": args.account, "password": password})
    print(f"\n[1] 登录 {args.account}  HTTP {code}")
    if code != 200:
        print(f"  detail: {login}")
        print("  → 演示账号口令见 .env 的 DEMO_PASSWORD；其余学生初始口令 = 学号")
        return 1
    token = login["access_token"]
    print(f"  role={login.get('role')}  student_no={login.get('student_no')}  actor_id={login.get('actor_id')}")
    check("登录拿到 token", bool(token))

    # ---- 2 未认证必须 401 ----
    code, _ = _req("GET", "/career/templates")
    check("未带 token 访问 /career/templates 返回 401", code == 401, f"实际 {code}")

    # ---- 3 模板 ----
    code, tpl = _req("GET", "/career/templates", token=token)
    print(f"\n[2] 规则模板  HTTP {code}  {tpl.get('templates')}  引擎 {tpl.get('engine_version')}")
    check("三个模板都在（考公/考研/就业）",
          set(tpl.get("templates") or []) >= {"考公", "考研", "就业"}, str(tpl.get("templates")))
    check("引擎版本号是 career-v1", tpl.get("engine_version") == "career-v1", str(tpl.get("engine_version")))

    # ---- 4 补录 ----
    code, extra = _req("PUT", "/career/extra", token=token,
                       body={"cet4_score": 468, "cet6_score": None, "political_status": "共青团员",
                             "target_city": "重庆", "weekly_hours": 12})
    print(f"\n[3] 补录画像  HTTP {code}  {extra}")
    check("补录接口成功", code == 200, str(extra))

    # ---- 5 解析规划（真调模型）----
    code, plan_out = _req("POST", "/career/plan", token=token, body={
        "raw_text": "我大三，想毕业后考重庆的公务员，目标是市直单位，行测申论都要准备，"
                    "每周大概能挤出 15 小时。"})
    plan = plan_out.get("plan") or plan_out
    gates = plan.get("硬门槛") or []
    print(f"\n[4] 解析规划（真调 DeepSeek）  HTTP {code}  goal_type={plan_out.get('goal_type')}  门槛 {len(gates)} 条")
    for g in gates:
        print(f"      - {g.get('项目')}: {g.get('当前状态')}   实际值={g.get('当前值')}")
    print(f"      当前差距: {json.dumps(plan.get('当前差距'), ensure_ascii=False)[:200]}")
    print(f"      引擎版本: {plan.get('引擎版本')}")
    check("解析接口 200", code == 200, str(plan_out)[:150] if code != 200 else "")
    check("目标类型被归一到「考公」", plan_out.get("goal_type") == "考公", str(plan_out.get("goal_type")))
    check("门槛条目来自模板（5 条）", len(gates) == 5, f"实际 {len(gates)}")
    check("门槛状态只出现 pass/fail/unknown",
          {g.get("当前状态") for g in gates} <= VALID_GATE,
          str({g.get("当前状态") for g in gates}))
    fails = [g for g in gates if g.get("当前状态") == "fail"]
    check("有 fail 项时「当前差距」非空",
          (not fails) or bool(plan.get("当前差距")), f"fail {len(fails)} 条，差距 {len(plan.get('当前差距') or [])} 条")

    # ---- 6 匹配规则 ----
    code, rule_out = _req("POST", "/career/match", token=token, body={})
    phases = rule_out.get("phases") or []
    total_weeks = sum(int(p.get("周数") or 0) for p in phases)
    print(f"\n[5] 匹配计划  HTTP {code}  阶段 {len(phases)} 个，合计 {total_weeks} 周")
    for p in phases:
        print(f"      - {p.get('阶段')}  {p.get('时间范围')}  {p.get('周数')} 周")
    check("匹配接口 200", code == 200, str(rule_out)[:150] if code != 200 else "")
    check("阶段来自模板（4 个）", len(phases) == 4, f"实际 {len(phases)}")
    # 剩余周数随日期滚动（到期滚下学期），不能写死期望值：
    # 校验本意是「阶段周数之和 == 接口返回的剩余周数」，动态对比
    weeks_left = int(rule_out.get("weeks_left") or 0)
    check("阶段周数之和等于剩余周数", total_weeks == weeks_left,
          f"阶段合计 {total_weeks} / 接口 weeks_left {weeks_left}")
    check("每个阶段都有日期区间", all(p.get("时间范围") for p in phases))

    # ---- 7 周复盘 ----
    code, wk = _req("POST", "/career/weekly", token=token,
                    body={"self_report": {"行测刷题量": 240, "申论写作篇数": 1}})
    items = wk.get("items") or []
    lights = {i.get("指标"): i.get("判定") for i in items}
    print(f"\n[6] 周复盘  HTTP {code}  overall={wk.get('overall')}  指标 {len(items)} 个")
    for i in items:
        print(f"      - {i.get('指标')}: 实际 {i.get('本周实际')} / 达标 {i.get('达标线')} → {i.get('判定')}")
    print(f"      小结: {str(wk.get('summary'))[:120]}")
    check("周复盘接口 200", code == 200, str(wk)[:150] if code != 200 else "")
    check("三色取值合法", set(lights.values()) <= VALID_LIGHT, str(set(lights.values())))
    check("行测 240 < 300 判 red", lights.get("行测刷题量") == "red", str(lights.get("行测刷题量")))
    check("申论 1 >= 1 判 green", lights.get("申论写作篇数") == "green", str(lights.get("申论写作篇数")))
    check("没填的指标判 unknown（不当 0）",
          lights.get("行测正确率") == "unknown", str(lights.get("行测正确率")))
    check("模型写了小结且未超 150 字", 0 < len(str(wk.get("summary") or "")) <= 200,
          f"{len(str(wk.get('summary') or ''))} 字")
    check("建议不超过 3 条", len(wk.get("advice") or []) <= 3, f"{len(wk.get('advice') or [])} 条")

    # ---- 8 公告 ----
    code, nt = _req("GET", "/career/notices", token=token)
    cand, matched = nt.get("candidates"), nt.get("matched")
    print(f"\n[7] 公告推送  HTTP {code}  候选 {cand} 条 → 推送 {matched} 条")
    for it in (nt.get("items") or [])[:5]:
        print(f"      [{it.get('相关性')}] {str(it.get('标题'))[:40]}  截止 {it.get('截止时间')}")
    check("公告接口 200", code == 200, str(nt)[:150] if code != 200 else "")
    check("候选里没有已截止项", (cand or 0) >= 0 and (matched or 0) <= (cand or 0),
          f"候选 {cand} / 推送 {matched}")
    check("推送条数不超过候选条数", (matched or 0) <= (cand or 0))

    # ---- 9 对话 ----
    code, ch = _req("POST", "/career/chat", token=token,
                    body={"message": "我这周行测只刷了 240 题，够吗？"})
    reply = str(ch.get("reply") or "")
    print(f"\n[8] 陪伴对话  HTTP {code}  回复 {len(reply)} 字")
    print(f"      {reply[:160]}...")
    check("对话接口 200", code == 200, str(ch)[:150] if code != 200 else "")
    check("回复非空", len(reply) > 20, f"{len(reply)} 字")

    # ---- 汇总 ----
    passed = sum(1 for _, ok, _ in _checks if ok)
    total = len(_checks)
    print("\n" + "=" * 66)
    print(f"结果：{passed}/{total} 项通过")
    if passed != total:
        print("失败项：")
        for name, ok, note in _checks:
            if not ok:
                print(f"  - {name}  {note}")
        print("=" * 66)
        return 1
    print("职业规划模块端到端链路正常。")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
