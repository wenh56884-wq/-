# scripts/verify_brain.py
# 职责：一键核对智能体大脑的能力矩阵，可选跑一轮真实任务看「规划→工具→观察→反思→汇总」。
# 依赖：agents.brain / agents.tools / engine.agent_memory / engine.web_search / app.config
# 用法：
#   .venv\Scripts\python.exe scripts\verify_brain.py
#   .venv\Scripts\python.exe scripts\verify_brain.py --live "帮我查重庆国考职位，同时看看我的预警"

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_ROOT / ".env")

import pymysql  # noqa: E402

from agents import auto_plan, brain, tools  # noqa: E402
from agents.tools import ToolContext  # noqa: E402
from app.config import get_settings  # noqa: E402
from engine import agent_memory, web_search  # noqa: E402


def _conn():
    s = get_settings()
    return pymysql.connect(host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
                           password=s.mysql_password, database=s.mysql_db,
                           charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)


def _demo_student(conn) -> ToolContext:
    with conn.cursor() as cur:
        # 优先用 README 里的演示学生，记忆/会话数据通常挂在他身上
        cur.execute("SELECT `编号`,`学号`,`租户编号` FROM `学生` WHERE `学号`=%s LIMIT 1",
                    ("AI20230001",))
        row = cur.fetchone()
        if not row:
            cur.execute("SELECT `编号`,`学号`,`租户编号` FROM `学生` ORDER BY `编号` LIMIT 1")
            row = cur.fetchone()
    if not row:
        raise RuntimeError("演示库里没有学生，先跑 scripts/seed_mock.py")
    return ToolContext(actor_type="student", tenant_id=int(row["租户编号"]),
                       student_id=int(row["编号"]))


def _memory_count(conn, ctx: ToolContext) -> int:
    try:
        agent_memory.ensure_schema(conn)
        conn.commit()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS n FROM `智能体记忆` WHERE `租户编号`=%s "
                "AND `角色`=%s AND `主体编号`=%s AND `状态`='active'",
                (ctx.tenant_id, ctx.actor_type, ctx.student_id))
            return int((cur.fetchone() or {}).get("n") or 0)
    except Exception:
        return 0


def _last_brain_audit(conn) -> list[dict]:
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT `动作` AS action, `对象` AS provider, `创建时间` AS ts "
                "FROM `审计日志` WHERE `动作` LIKE 'llm.brain_%' "
                "ORDER BY `编号` DESC LIMIT 5")
            return list(cur.fetchall())
    except Exception:
        return []


def print_matrix() -> ToolContext:
    info = brain.describe()
    conn = _conn()
    try:
        ctx = _demo_student(conn)
        memory_n = _memory_count(conn, ctx)
        audits = _last_brain_audit(conn)
    finally:
        conn.close()

    print("== 启航智能体能力自检 ==")
    print(f"大脑      : {info['brain_version']} | 模式 {info['mode']} | "
          f"最多 {info['max_rounds']} 轮 / {info['max_steps']} 步")
    print(f"工具      : 教师 {len(tools.TEACHER_TOOLS)} 个 / 学生 {len(tools.STUDENT_TOOLS)} 个 / "
          f"可执行 {len(auto_plan.EXECUTABLE)} 个")
    print(f"长期记忆  : {info['memory']} | {info['memory_vector_dim']} 维 hashing 向量 | "
          f"本人 {memory_n} 条")
    print(f"联网搜索  : {web_search.provider() or '未配置（会如实说没有联网能力）'}")
    print(f"阻断工具  : {', '.join(info['blocked_tools'])}（有副作用，不自动执行）")
    print("触发条件  : 含「同时/然后/对比/规划/先查/再查/帮我分析」等词自动走大脑；"
          "AGENT_BRAIN=1 可强制全部走大脑")
    if audits:
        print("最近调用  : " + "；".join(
            f"{row['action'].replace('llm.', '')}@{row['provider'] or '-'}"
            for row in audits))
    else:
        print("最近调用  : 还没有大脑调用记录")
    print("页面入口  : 右下角 AI 助手 → 输入多意图问题 → 回答下方「执行轨迹」")
    print("接口入口  : GET /chat/capabilities（登录后）、GET /chat/brain、GET /chat/memories")
    return ctx


def run_live(ctx: ToolContext, query: str) -> int:
    print(f"\n== 实跑：{query} ==")
    print("提示：星火单次调用约 5~20 秒，整轮可能 30~60 秒。\n")

    def on_event(event: dict) -> None:
        stage = event.get("stage") or ""
        text = event.get("text") or ""
        tool = event.get("tool") or ""
        print(f"  [{stage}] {tool} {text}".rstrip())

    result = brain.run_brain(ctx, query, on_event=on_event)
    if result is None:
        print("大脑没有产出计划（模型不可用或问题不需要多步取数），旧管线会接管。")
        return 1
    print(f"\n计划轮次 : {result.get('rounds')} | 步数 : {len(result.get('steps') or [])} | "
          f"耗时 : {result.get('elapsed_ms')} ms | 降级 : {result.get('degraded')}")
    for step in result.get("steps") or []:
        print(f"  {step['index']}. {step['tool']} 参数={step.get('args')} "
              f"{'成功' if step.get('ok') else '失败'} | {step.get('purpose')}")
    print(f"\n答案：\n{result.get('answer')}")
    if result.get("citations"):
        print(f"\n引用 {len(result['citations'])} 条：")
        for cite in result["citations"]:
            print(f"  - {cite.get('title')} {cite.get('url') or ''}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="核对智能体大脑能力，可选实跑")
    parser.add_argument("--live", metavar="QUERY", default=None,
                        help="跑一轮真实任务（会调用 LLM，较慢）")
    args = parser.parse_args(argv)
    ctx = print_matrix()
    if args.live:
        return run_live(ctx, args.live)
    print("\n想看完整工作循环：加 --live \"帮我查重庆国考职位，同时看看我的预警\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
