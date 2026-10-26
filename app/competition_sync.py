"""app/competition_sync.py
职责：定时去重庆财经学院教务处「学科竞赛」栏目抓最新通知，新发布的自动入库，
      学生端据此拿到未读推送。

设计要点：
- 抓的是官方页面原始标题/日期/链接，不做任何推断补全；抓不到就跳过（绝不写编造数据）。
- 通过 (title, published_at) 唯一键做幂等：重复抓取不会重复入库，只有新通知才落库。
- 后台任务在 FastAPI 启动时拉起，间隔由环境变量 COMPETITION_SYNC_MINUTES 控制（0 = 关闭）。
"""

from __future__ import annotations

import asyncio
import os
import threading
from datetime import datetime
from typing import Any

from app.audit import audit_event

# 同步间隔（分钟）：默认 30 分钟；0 或负数表示不启用后台同步
def sync_interval_minutes() -> float:
    raw = str(os.getenv("COMPETITION_SYNC_MINUTES", "30")).strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 30.0


def sync_once() -> int:
    """抓一次栏目页并落库，返回「新增」条数（已存在的不计）。

    抓取逻辑复用 scripts/seed_competition.py，避免两处解析规则不一致。
    """
    from scripts.seed_competition import fetch_notices, save_notices

    try:
        notices = fetch_notices()
    except Exception as exc:  # 断网 / 官网改版只告警，不打断服务
        audit_event(actor_type="system", actor_id=0, action="competition.sync.failed",
                    target="", detail={"error": str(exc)[:200]})
        return 0
    if not notices:
        return 0
    added = save_notices(notices)
    if added:
        audit_event(actor_type="system", actor_id=0, action="competition.sync",
                    target="", detail={"added": added, "fetched": len(notices)})
    return added


def _loop(interval_seconds: float) -> None:
    """守护线程循环：抓 → 睡 → 再抓（失败不影响下一轮）。"""
    while True:
        try:
            sync_once()
        except Exception:
            pass
        threading.Event().wait(interval_seconds)


def start_background_sync() -> None:
    """在应用启动时拉起后台同步线程；间隔为 0 或未装依赖时静默跳过。"""
    minutes = sync_interval_minutes()
    if minutes <= 0:
        return
    thread = threading.Thread(
        target=_loop, args=(minutes * 60,), name="competition-sync", daemon=True)
    thread.start()


def latest_notices(limit: int = 20) -> list[dict[str, Any]]:
    """取最新通知（按发布日期倒序，同日按入库顺序）。"""
    from engine.competition import _connect

    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT title, published_at, url, source, fetched_at "
                "FROM competition_notice ORDER BY published_at DESC, id DESC LIMIT %s",
                (int(limit),),
            )
            rows = [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
    for row in rows:
        fetched = row.get("fetched_at")
        row["fetched_at"] = fetched.strftime("%Y-%m-%d %H:%M:%S") if isinstance(
            fetched, datetime) else (str(fetched) if fetched else "")
    return rows


def sync_now_async() -> None:
    """供接口/测试手动触发一次同步（不阻塞请求）。"""
    asyncio.get_event_loop().run_in_executor(None, sync_once)
