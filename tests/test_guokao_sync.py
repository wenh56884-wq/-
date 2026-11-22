# tests/test_guokao_sync.py
# 职责：验证国考职位后台自动同步——间隔开关、失败告警、真实入库与运行日志。
# 方法：间隔/失败路径纯 monkeypatch（不发网络请求）；入库用例走真实 MySQL
#       （不可用时自动跳过，与 test_pet_store 同策略），用测试租户 999999 隔离。

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402

from app import guokao_sync  # noqa: E402
from etl import exam_positions  # noqa: E402

# 与 test_exam_positions.py 同一份合成表头/样例（不依赖网络与真实文件）
_HEADERS = [
    "部门代码", "部门名称", "用人司局", "机构性质", "招考职位", "职位属性",
    "职位分布", "职位简介", "职位代码", "机构层级", "考试类别", "招考人数",
    "专业", "学历", "学位", "政治面貌", "基层工作最低年限",
    "服务基层项目工作经历", "是否在面试阶段组织专业能力测试", "面试人员比例",
    "工作地点", "落户地点", "备注", "部门网站", "咨询电话1", "咨询电话2",
    "咨询电话3",
]

_TENANT = 999999  # 测试专用租户，用例前后清理
_FAKE_ZIP = _ROOT / "data" / "raw" / "guokao" / "2027" / "招考简章_2027.zip"


def _sample_records() -> list[dict]:
    rows = [
        ["招考职位由招录机关编报，专业、学历等由招录机关负责解释。"],
        _HEADERS,
        ["002000", "中央办公厅", "警卫局", "中央党群机关",
         "测试职位A一级主任科员及以下", "普通职位", "其他职位", "从事测试工作",
         "100190000001", "中央", "中央机关及其省级直属机构综合管理类", "1",
         "本科：082803风景园林", "本科或硕士研究生", "与最高学历相对应的学位",
         "中共党员", "二年", "无限制", "是", "5:1",
         "北京市", "北京市", "备注", "www.example.gov.cn", "010-1", "", ""],
        ["002000", "中央办公厅", "警卫局", "中央党群机关",
         "测试职位B一级主任科员及以下", "普通职位", "其他职位", "从事测试工作",
         "100190000002", "中央", "中央机关及其省级直属机构综合管理类", "2",
         "本科：082803风景园林", "本科或硕士研究生", "与最高学历相对应的学位",
         "不限", "无", "无限制", "否", "5:1",
         "北京市", "北京市", "备注", "www.example.gov.cn", "010-1", "", ""],
    ]
    return exam_positions.parse_rows(rows, 2027, "中央党群机关", "test.xls")


# ---------------------------------------------------------------- 间隔开关

def test_interval_default_is_daily(monkeypatch):
    monkeypatch.delenv("GUOKAO_SYNC_HOURS", raising=False)
    assert guokao_sync.sync_interval_hours() == 24.0


def test_interval_zero_disables(monkeypatch):
    monkeypatch.setenv("GUOKAO_SYNC_HOURS", "0")
    assert guokao_sync.sync_interval_hours() == 0.0
    assert guokao_sync.start_background_sync() is False  # 关闭时不拉线程


def test_interval_custom_hours(monkeypatch):
    monkeypatch.setenv("GUOKAO_SYNC_HOURS", "24")
    assert guokao_sync.sync_interval_hours() == 24.0


def test_interval_garbage_falls_back_to_daily(monkeypatch):
    monkeypatch.setenv("GUOKAO_SYNC_HOURS", "abc")
    assert guokao_sync.sync_interval_hours() == 24.0


def test_known_years_matches_registry():
    assert guokao_sync.known_years() == sorted(
        int(y) for y in exam_positions.DOWNLOAD_URLS)


def test_background_thread_never_starts_under_pytest(monkeypatch):
    """pytest 进程内不拉线程：否则会在 monkeypatch 期间把打桩数据写进真库。"""
    monkeypatch.setenv("GUOKAO_SYNC_HOURS", "1")
    assert guokao_sync.start_background_sync() is False


# ---------------------------------------------------------------- 启动防抖

def test_is_stale_decision():
    """防抖判定：从未跑过/满间隔 → 该跑；间隔内成功过 → 跳过。"""
    from datetime import datetime

    now = datetime(2026, 11, 10, 12, 0, 0)
    assert guokao_sync.is_stale(None, 3600, now=now) is True
    fresh = datetime(2026, 11, 10, 11, 30, 0)
    assert guokao_sync.is_stale(fresh, 3600, now=now) is False
    old = datetime(2026, 11, 10, 10, 0, 0)
    assert guokao_sync.is_stale(old, 3600, now=now) is True  # 恰好满 1 小时


def test_last_success_at_none_when_db_down(monkeypatch):
    """新鲜度查询失败按「该跑」处理：宁可多跑一次也不漏跑。"""
    from scripts import sync_guokao as sg

    def boom():
        raise RuntimeError("库不可用")

    monkeypatch.setattr(sg, "_connect", boom)
    assert guokao_sync.last_success_at() is None


def test_last_success_at_reads_log(monkeypatch):
    """从抓取运行日志读最近一次成功时间；非 datetime 值视同查不到。"""
    from datetime import datetime

    from scripts import sync_guokao as sg

    class _Cur:
        def execute(self, sql, params=None):
            assert "是否成功` = 1" in sql and "目标` = 'guokao'" in sql

        def fetchone(self):
            return (datetime(2026, 11, 10, 8, 0, 0),)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    class _Conn:
        def cursor(self):
            return _Cur()

        def close(self):
            pass

    monkeypatch.setattr(sg, "_connect", lambda: _Conn())
    assert guokao_sync.last_success_at() == datetime(2026, 11, 10, 8, 0, 0)

    class _DictCur(_Cur):
        """sync_guokao._connect 实际是 DictCursor——按别名取键，别用下标。"""

        def fetchone(self):
            return {"t": datetime(2026, 11, 10, 8, 0, 0)}

    class _DictConn(_Conn):
        def cursor(self):
            return _DictCur()

    monkeypatch.setattr(sg, "_connect", lambda: _DictConn())
    assert guokao_sync.last_success_at() == datetime(2026, 11, 10, 8, 0, 0)

    class _BadCur(_Cur):
        def fetchone(self):
            return (None,)

    class _BadConn(_Conn):
        def cursor(self):
            return _BadCur()

    monkeypatch.setattr(sg, "_connect", lambda: _BadConn())
    assert guokao_sync.last_success_at() is None


# ---------------------------------------------------------------- 失败路径

def test_sync_guokao_once_swallows_download_failure(monkeypatch):
    """官方地址挂了：只告警不抛异常，返回 0（守护线程不被拖垮）。"""
    calls: list[dict] = []
    monkeypatch.setattr(guokao_sync, "audit_event", lambda **kw: calls.append(kw))
    monkeypatch.setattr(guokao_sync, "known_years", lambda: [2027])

    def boom(*a, **k):
        raise RuntimeError("网络不可达")

    monkeypatch.setattr(exam_positions, "download_positions", boom)
    assert guokao_sync.sync_guokao_once("schedule") == 0
    failed = [c for c in calls if c.get("action") == "guokao.sync.failed"]
    assert len(failed) == 1
    assert failed[0]["target"] == "scs-gk-2027"
    assert "网络不可达" in failed[0]["detail"]["error"]


# ---------------------------------------------------------------- 入库（真库）

def _mysql_conn():
    import pymysql

    from app.config import get_settings

    s = get_settings()
    return pymysql.connect(
        host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
        password=s.mysql_password, database=s.mysql_db, charset="utf8mb4",
        autocommit=True, cursorclass=pymysql.cursors.DictCursor)


def _mysql_ok() -> bool:
    try:
        _mysql_conn().close()
        return True
    except Exception:
        return False


requires_mysql = pytest.mark.skipif(not _mysql_ok(), reason="MySQL 不可用")


@pytest.fixture
def mysql():
    conn = _mysql_conn()
    _clean(conn)
    try:
        yield conn
    finally:
        _clean(conn)
        conn.close()


def _clean(conn) -> None:
    # 日志表没有租户列，测试用专用触发方式 'test' 打标清理，
    # 绝不动真实守护线程（schedule）/人工（manual）留下的运行历史。
    with conn.cursor() as cur:
        cur.execute("DELETE FROM `国考职位` WHERE `租户编号` = %s", (_TENANT,))
        cur.execute(
            "DELETE FROM `抓取运行日志` WHERE `目标` = 'guokao' "
            "AND `触发方式` = 'test'")


@requires_mysql
def test_sync_year_downloads_parses_and_upserts(monkeypatch, mysql):
    """下载→解析→入库→运行日志全链路（下载与解析打桩，入库走真库）。"""
    from scripts.sync_guokao import ensure_schema

    monkeypatch.setattr(exam_positions, "download_positions",
                        lambda year, dest, url=None: _FAKE_ZIP)
    monkeypatch.setattr(exam_positions, "load_from_path",
                        lambda path, year: _sample_records())
    audits: list[dict] = []
    monkeypatch.setattr(guokao_sync, "audit_event", lambda **kw: audits.append(kw))

    ensure_schema(mysql)
    added = guokao_sync.sync_year(2027, trigger="test", tenant_id=_TENANT)
    assert added == 2  # 两条测试职位全部新增

    with mysql.cursor() as cur:
        cur.execute(
            "SELECT `招考职位`, `招考人数`, `简章分类` FROM `国考职位` "
            "WHERE `租户编号` = %s AND `年度` = 2027 ORDER BY `职位代码`",
            (_TENANT,))
        rows = cur.fetchall()
        cur.execute(
            "SELECT `是否成功` FROM `抓取运行日志` "
            "WHERE `目标` = 'guokao' AND `触发方式` = 'test' "
            "ORDER BY `编号` DESC LIMIT 1")
        log_row = cur.fetchone()

    assert [r["招考职位"] for r in rows] == [
        "测试职位A一级主任科员及以下", "测试职位B一级主任科员及以下"]
    assert [r["招考人数"] for r in rows] == [1, 2]
    assert rows[0]["简章分类"] == "中央党群机关"
    assert log_row is not None and log_row["是否成功"] == 1
    ok_audit = [a for a in audits if a.get("action") == "guokao.sync"]
    assert ok_audit and ok_audit[0]["detail"]["inserted"] == 2


@requires_mysql
def test_sync_year_is_idempotent(monkeypatch, mysql):
    """同一批职位跑两遍：第二遍只刷新不新增（唯一键幂等）。"""
    from scripts.sync_guokao import ensure_schema

    monkeypatch.setattr(exam_positions, "download_positions",
                        lambda year, dest, url=None: _FAKE_ZIP)
    monkeypatch.setattr(exam_positions, "load_from_path",
                        lambda path, year: _sample_records())
    monkeypatch.setattr(guokao_sync, "audit_event", lambda **kw: None)

    ensure_schema(mysql)
    assert guokao_sync.sync_year(2027, trigger="test",
                                 tenant_id=_TENANT) == 2
    second = guokao_sync.sync_year(2027, trigger="test", tenant_id=_TENANT)
    assert second == 2  # 全部算「更新」，不产生重复行
    with mysql.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM `国考职位` WHERE `租户编号` = %s",
                    (_TENANT,))
        assert cur.fetchone()["n"] == 2
