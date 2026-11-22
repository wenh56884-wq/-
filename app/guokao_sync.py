"""app/guokao_sync.py
职责：后台守护线程，定期同步「国考职位」（《招考简章》年度数据）。

为什么单独一条线程：国考职位是**年度数据**（一年发布一次，期间偶有补录/更正），
与每日更新的招考公告节奏不同，故独立用 GUOKAO_SYNC_HOURS 控制间隔。

设计要点（与 recruit_sync / competition_sync 保持一致）：
- 数据源只认 `etl.exam_positions.DOWNLOAD_URLS` 里显式登记的官方地址，
  未知年度不猜 URL（宁可不跑，不编造）；
- 幂等：(租户编号, 年度, 部门代码, 职位代码) 唯一键，重复跑只刷新内容不产生重复行；
- 失败只告警不抛异常，不能拖垮接口服务；
- 间隔由环境变量 GUOKAO_SYNC_HOURS 控制（单位小时，默认 24 = 每天；0 = 关闭）。

为什么默认 24 小时：用户要求真实数据每日获取；招考简章虽一年只发布一次，
按天拉取（约 2MB）既能及时捕捉补录更正，又与全站统一抓取节奏一致。
"""

from __future__ import annotations

import os
import sys
import threading
from datetime import datetime
from pathlib import Path

from app.audit import audit_event
from app.logging_config import get_logger

logger = get_logger("qihang.guokao_sync")

_ROOT = Path(__file__).resolve().parent.parent
# 后台下载/解析产物统一放 data/raw/guokao/<年度>/（不入库，与手动脚本同目录）
_DATA_DIR = _ROOT / "data" / "raw" / "guokao"


def sync_interval_hours() -> float:
    """国考职位同步间隔（小时）：默认 24（每天）；<=0 表示不启用。"""
    raw = str(os.getenv("GUOKAO_SYNC_HOURS", "24")).strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 24.0


def known_years() -> list[int]:
    """已登记官方下载地址的考试年度（升序）。未知年度不会被自动同步。"""
    from etl import exam_positions

    return sorted(int(y) for y in exam_positions.DOWNLOAD_URLS)


def sync_year(year: int, trigger: str = "schedule", tenant_id: int = 1) -> int:
    """同步单个年度：下载 → 解析 → 增量入库 → 写运行日志。

    返回该年度新增+更新的职位条数；下载/解析/入库任一失败都向上抛
    （由 sync_guokao_once 统一告警），不在这里吞异常。
    """
    from etl import exam_positions
    from scripts.sync_guokao import (
        _connect, ensure_schema, log_run, upsert_positions,
    )

    zip_path = exam_positions.download_positions(year, _DATA_DIR / str(year))
    records = exam_positions.load_from_path(zip_path, year)
    conn = None
    inserted, updated = 0, 0
    try:
        conn = _connect()
        ensure_schema(conn)
        inserted, updated = upsert_positions(conn, records, tenant_id)
        log_run(conn, year=year, fetched=len(records), inserted=inserted,
                updated=updated, ok=True, trigger=trigger)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                logger.warning("guokao sync connection close failed", exc_info=True)

    audit_event(tenant_id=tenant_id, actor_type="system", actor_id=0,
                action="guokao.sync", target=f"scs-gk-{year}",
                detail={"fetched": len(records), "inserted": inserted,
                        "updated": updated, "source_file": zip_path.name,
                        "trigger": trigger,
                        "at": datetime.now().isoformat(timespec="seconds")})
    logger.info("guokao sync ok year=%s fetched=%s inserted=%s updated=%s",
                year, len(records), inserted, updated)
    return inserted + updated


def sync_guokao_once(trigger: str = "schedule") -> int:
    """把所有已登记年度同步一轮，返回入库条数总和。异常内部消化，返回 0。"""
    try:
        years = known_years()
    except Exception:  # 依赖缺失不致命
        logger.warning("guokao sync import failed", exc_info=True)
        audit_event(tenant_id=1, actor_type="system", actor_id=0,
                    action="guokao.sync.failed",
                    target="", detail={"error": "import failed"[:200]})
        return 0

    total = 0
    for year in years:
        try:
            total += sync_year(year, trigger=trigger)
        except Exception as exc:
            logger.warning("guokao sync failed year=%s", year, exc_info=True)
            audit_event(tenant_id=1, actor_type="system", actor_id=0,
                        action="guokao.sync.failed", target=f"scs-gk-{year}",
                        detail={"error": str(exc)[:200]})
    return total


def last_success_at() -> datetime | None:
    """最近一次成功的国考同步时间；查不到（无日志/表不存在/库不可用）返回 None。

    用于启动防抖：服务频繁重启时，若距上次成功不足一个间隔，就不再立刻
    下载全量《招考简章》（约 2MB）并 upsert 一遍。查询失败按「该跑」处理，
    宁可多跑一次也不漏跑。
    """
    try:
        from scripts.sync_guokao import _connect

        conn = _connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT MAX(`运行时间`) AS t FROM `抓取运行日志` "
                    "WHERE `目标` = 'guokao' AND `是否成功` = 1")
                row = cur.fetchone()
        finally:
            conn.close()
        # sync_guokao._connect 用 DictCursor，sync_recruit 是 tuple 游标，两种都兼容
        t = row.get("t") if isinstance(row, dict) else (row[0] if row else None)
        return t if isinstance(t, datetime) else None
    except Exception:
        logger.warning("guokao sync freshness check failed", exc_info=True)
        return None


def is_stale(last: datetime | None, interval_seconds: float,
             *, now: datetime | None = None) -> bool:
    """距上次成功同步是否已满一个间隔（last=None 视为从未跑过 → 该跑）。"""
    ref = now or datetime.now()
    if last is None:
        return True
    return (ref - last).total_seconds() >= interval_seconds


def _loop(interval_seconds: float) -> None:
    """守护线程：到点才同步 → 睡 → 再检查（单轮失败不影响下一轮）。

    启动防抖：距上次成功同步不足一个间隔时跳过本轮——
    数据是年度粒度，一周内的重启没有必要每次都全量拉一遍。
    """
    while True:
        try:
            if is_stale(last_success_at(), interval_seconds):
                sync_guokao_once("schedule")
            else:
                logger.info("guokao sync skipped: last success still fresh")
        except Exception:
            logger.exception("guokao sync loop failed")
        threading.Event().wait(interval_seconds)


_started = False
_lock = threading.Lock()


def _in_test_process() -> bool:
    """是否跑在 pytest 里。

    测试用 TestClient(create_app()) 会走到启动块，若真拉起线程，它会在
    测试 monkeypatch 生效期间跑一轮同步，把打桩数据以默认租户写进真库
    （已踩过一次坑）。测试进程内一律不拉线程。
    """
    return "pytest" in sys.modules or bool(os.getenv("PYTEST_CURRENT_TEST"))


def start_background_sync() -> bool:
    """在 FastAPI 启动时拉起国考职位同步线程；已启动或已关闭时返回 False。"""
    global _started
    hours = sync_interval_hours()
    if hours <= 0:
        return False
    if _in_test_process():
        return False
    with _lock:
        if _started:
            return False
        _started = True
    t = threading.Thread(target=_loop, args=(hours * 3600,),
                         name="guokao-sync", daemon=True)
    t.start()
    return True
