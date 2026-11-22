"""app/recruit_sync.py
职责：后台守护线程，**每天**抓一次「招考公告 + 企业岗位」并增量入库。

两个目标（缺一不可，学生的「就业 / 考公 / 考编 / 考研」四条路都要有实时数据）：
- exam_notice：考公 / 考编 / 考研公告及要求
- recruit_job：企业岗位（全国职业岗位，不再只靠种子数据）

设计要点（与 competition_sync 保持一致）：
- 只抓官方/公开页面原文，抓不到就跳过，绝不写编造数据；
- 用 (source, source_key) 唯一键幂等，重复跑不会重复入库；
- 失败只告警不抛异常，不能拖垮接口服务；
- 间隔由环境变量 RECRUIT_SYNC_HOURS 控制（单位小时，默认 24 = 每天；0 = 关闭）。

为什么默认 24 小时：用户要求真实数据每日更新；招考公告与岗位都按天拉取，
抓取要进详情页（每题 1 次请求），每天一次在及时性与站点压力间取平衡。
"""

from __future__ import annotations

import os
import threading
from datetime import datetime

from app.audit import audit_event
from app.logging_config import get_logger

logger = get_logger("qihang.recruit_sync")


def sync_interval_hours() -> float:
    """后台同步间隔（小时）：默认 24（每天）；<=0 表示不启用。"""
    raw = str(os.getenv("RECRUIT_SYNC_HOURS", "24")).strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 24.0


def sync_once(trigger: str = "schedule") -> int:
    """抓一轮（招考 + 岗位）并入库，返回新增总条数。异常内部消化，返回 0。"""
    try:
        from scripts.sync_recruit import (
            _connect, ensure_tables, sync_job_source, sync_source,
        )
        from etl import job_fetch, recruit_fetch
    except Exception as exc:  # 依赖缺失不致命
        logger.warning("recruit sync import failed", exc_info=True)
        audit_event(tenant_id=1, actor_type="system", actor_id=0,
                    action="recruit.sync.failed",
                    target="", detail={"error": f"import: {exc}"[:200]})
        return 0

    conn = None
    try:
        conn = _connect()
        ensure_tables(conn)
        added = {"exam": 0, "job": 0}

        # 两个目标各自 try：岗位站挂了不能连累招考公告入库
        for sid in recruit_fetch.SOURCES:
            try:
                res = sync_source(conn, sid, limit=60, trigger=trigger)
                added["exam"] += res.get("inserted", 0)
            except Exception as exc:
                logger.warning("exam source sync failed sid=%s", sid, exc_info=True)
                audit_event(tenant_id=1, actor_type="system", actor_id=0,
                            action="recruit.sync.source_failed", target=sid,
                            detail={"error": str(exc)[:200]})
        for sid in job_fetch.JOB_SOURCES:
            try:
                res = sync_job_source(conn, sid, limit=40, trigger=trigger)
                added["job"] += res.get("inserted", 0)
            except Exception as exc:
                logger.warning("job source sync failed sid=%s", sid, exc_info=True)
                audit_event(tenant_id=1, actor_type="system", actor_id=0,
                            action="recruit.sync.source_failed", target=sid,
                            detail={"error": str(exc)[:200]})

        audit_event(tenant_id=1, actor_type="system", actor_id=0,
                    action="recruit.sync",
                    target="",
                    detail={"added": added, "total": sum(added.values()),
                            "at": datetime.now().isoformat(timespec="seconds")})
        return sum(added.values())
    except Exception as exc:  # 断网 / 库不可用
        logger.warning("recruit sync failed", exc_info=True)
        audit_event(tenant_id=1, actor_type="system", actor_id=0,
                    action="recruit.sync.failed",
                    target="", detail={"error": str(exc)[:200]})
        return 0
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                logger.warning("recruit sync connection close failed", exc_info=True)


def _stale_targets(interval_seconds: float) -> list[str]:
    """到点该重抓的目标列表（空=全部仍新鲜，整轮可跳过）。

    每个目标独立判断「最近一次成功是否已满间隔」：某个源持续失败时，
    它的最近成功时间会越来越旧，到点后整轮重跑——不会被其他成功源
    「捂住」。查询失败按全部到点处理，宁可多跑一次也不漏跑。

    启动防抖的动机：抓取要进详情页（每条 1 次请求），开发期频繁重启
    服务会对招聘/政府站点造成不必要的重复访问。
    """
    targets = ("civil", "institution", "postgraduate", "job")
    try:
        from scripts.sync_recruit import _connect

        conn = _connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT `目标`, MAX(`运行时间`) FROM `抓取运行日志` "
                    "WHERE `目标` IN (%s,%s,%s,%s) AND `是否成功` = 1 "
                    "GROUP BY `目标`", targets)
                fresh = {row[0]: row[1] for row in (cur.fetchall() or [])}
        finally:
            conn.close()
    except Exception:
        logger.warning("recruit sync freshness check failed", exc_info=True)
        return list(targets)
    now = datetime.now()
    return [
        t for t in targets
        if not isinstance(fresh.get(t), datetime)
        or (now - fresh[t]).total_seconds() >= interval_seconds
    ]


def _loop(interval_seconds: float) -> None:
    """守护线程：到点的目标才抓 → 睡 → 再检查（单轮失败不影响下一轮）。

    启动防抖：全部目标距上次成功都还不足一个间隔时跳过本轮。
    """
    while True:
        try:
            stale = _stale_targets(interval_seconds)
            if stale:
                logger.info("recruit sync due targets=%s", stale)
                sync_once("schedule")
            else:
                logger.info("recruit sync skipped: all targets fresh")
        except Exception:
            logger.exception("recruit sync loop failed")
        threading.Event().wait(interval_seconds)


_started = False
_lock = threading.Lock()


def start_background_sync() -> bool:
    """在 FastAPI 启动时拉起后台周更线程；已启动或已关闭时返回 False。"""
    global _started
    hours = sync_interval_hours()
    if hours <= 0:
        return False
    with _lock:
        if _started:
            return False
        _started = True
    t = threading.Thread(target=_loop, args=(hours * 3600,),
                         name="recruit-sync", daemon=True)
    t.start()
    return True
