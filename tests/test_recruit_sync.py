# tests/test_recruit_sync.py
# 职责：验证招考公告/岗位后台同步线程的启动防抖——每个目标独立判新鲜度，
#       失败源不会被成功源「捂住」；查询失败按全部到点处理（宁可多跑不漏跑）。
# 方法：纯 monkeypatch 假连接，不连真实库、不发网络请求。

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402

from app import recruit_sync  # noqa: E402
from scripts import sync_recruit as sr  # noqa: E402

_TARGETS = ("civil", "institution", "postgraduate", "job")


class _FakeCursor:
    """按预设行返回的假游标（tuple 型，与 sync_recruit._connect 同口径）。"""

    def __init__(self, rows):
        self._rows = rows
        self.sql = ""

    def execute(self, sql, params=None):
        self.sql = sql

    def fetchall(self):
        return self._rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeConn:
    def __init__(self, rows):
        self._cursor = _FakeCursor(rows)

    def cursor(self):
        return self._cursor

    def close(self):
        pass


def test_stale_targets_all_due_when_never_ran(monkeypatch):
    """日志里没有任何成功记录 → 全部目标到点，必须跑。"""
    monkeypatch.setattr(sr, "_connect", lambda: _FakeConn([]))
    assert sorted(recruit_sync._stale_targets(168 * 3600)) == sorted(_TARGETS)


def test_stale_targets_skips_fresh_keeps_old(monkeypatch):
    """间隔内成功过的目标跳过；某源一直失败（最近成功太旧）到点重跑。"""
    now = datetime.now()
    rows = [
        ("civil", now - timedelta(hours=1)),        # 1 小时前成功 → 新鲜
        ("institution", now - timedelta(days=8)),   # 8 天前 → 旧，该跑
        ("postgraduate", now - timedelta(hours=2)),
        ("job", now - timedelta(hours=3)),
    ]
    monkeypatch.setattr(sr, "_connect", lambda: _FakeConn(rows))
    assert recruit_sync._stale_targets(168 * 3600) == ["institution"]


def test_stale_targets_all_due_when_db_down(monkeypatch):
    """库不可用：按全部到点处理，不因防抖把同步卡死。"""
    def boom():
        raise RuntimeError("库不可用")

    monkeypatch.setattr(sr, "_connect", boom)
    assert sorted(recruit_sync._stale_targets(168 * 3600)) == sorted(_TARGETS)


def test_stale_targets_ignores_non_datetime(monkeypatch):
    """MAX(运行时间) 返回异常值时按没跑过处理。"""
    monkeypatch.setattr(
        sr, "_connect", lambda: _FakeConn([(t, "not-a-datetime") for t in _TARGETS]))
    assert sorted(recruit_sync._stale_targets(168 * 3600)) == sorted(_TARGETS)


def test_interval_default_and_disable(monkeypatch):
    monkeypatch.delenv("RECRUIT_SYNC_HOURS", raising=False)
    assert recruit_sync.sync_interval_hours() == 24.0
    monkeypatch.setenv("RECRUIT_SYNC_HOURS", "0")
    assert recruit_sync.start_background_sync() is False


@pytest.mark.parametrize("hours,expect", [("abc", 24.0), ("-5", 0.0), ("24", 24.0)])
def test_interval_parsing(monkeypatch, hours, expect):
    monkeypatch.setenv("RECRUIT_SYNC_HOURS", hours)
    assert recruit_sync.sync_interval_hours() == expect
