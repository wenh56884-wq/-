# tests/test_career_positions.py
# 职责：职业规划引擎「国考职位接入」回归（纯函数 + forecast 装配 + DB 门控）。
# 离线用例不连库；DB 用例在未同步国考职位时自动跳过（与 test_exam_positions 同口径）。

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402

from engine import career_forecast as cf  # noqa: E402
from agents.career import context as cx  # noqa: E402


# ----------------------------------------------------------------
# 1. 政治面貌匹配 SQL（纯函数，离线）
# ----------------------------------------------------------------
def test_pol_ok_sql_party_vs_mass_differ():
    """中共党员与群众（未采集）的 SQL 片段必须不同——党员口径更宽。"""
    party = cx._guoka_pol_ok_sql("中共党员")
    mass = cx._guoka_pol_ok_sql(None)
    assert "中共党员" not in mass or mass == cx._GUOKAO_POL_UNRESTRICTED
    # 党员片段包含「不干抢共青团员岗位」，群众片段则没有这段
    assert "共青团员" in party
    assert "共青团员" not in mass


def test_pol_ok_sql_league_rejects_party_only():
    league = cx._guoka_pol_ok_sql("共青团员")
    assert "科协" not in league
    assert "中共党员" in league


# ----------------------------------------------------------------
# 2. engine.forecast：guokao 摘要并入 opportunities（不连库）
# ----------------------------------------------------------------
def _fake_guokao():
    return {
        "available": True, "year": 2027,
        "matched_positions": 123, "matched_headcount": 456,
        "unrestricted_positions": 7,
        "total_positions": 19426, "total_headcount": 35691,
        "source_url": "http://bm.scs.gov.cn/kl2027/",
        "examples": [],
    }


def test_forecast_exposes_guokao_block_in_civil_path():
    res = cf.forecast(
        {"name": "甲同学", "major": "软件工程", "degree": "本科",
         "political_status": "中共党员"},
        goal="考公",
        guokao=_fake_guokao(),
        template={"phases": []},
    )
    assert res["available"] is True
    ops = res["opportunities"]
    assert ops["guokao_positions"]["matched_positions"] == 123
    assert ops["guokao_positions"]["matched_headcount"] == 456
    assert any("国考职位" in c for c in res["caveats"])


def test_forecast_ignores_guokao_for_other_goals():
    res = cf.forecast(
        {"name": "乙", "major": "软件工程", "degree": "本科"},
        goal="考研",  # 不是考公 → 不挂国考块
        guokao=_fake_guokao(),
        template={"phases": []},
    )
    assert res["available"] is True
    # 考研路径仍然 output 存在 opportunities，但 guokao_positions 应为 None
    assert res["opportunities"]["guokao_positions"] is None


# ----------------------------------------------------------------
# 3. DB 门控：国考职位表同步后才跑（与 test_exam_positions 同口径）
# ----------------------------------------------------------------
def _mysql_ok_positions() -> bool:
    try:
        import pymysql
        from app.config import get_settings

        s = get_settings()
        conn = pymysql.connect(host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
                               password=s.mysql_password, database=s.mysql_db,
                               charset="utf8mb4")
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(`年度`) AS y FROM `国考职位`")
            row = cur.fetchone()
            ok = int(row[0]) > 0 if row else False
        conn.close()
        return ok
    except Exception:
        return False


DB_OK = pytest.mark.skipif(
    not _mysql_ok_positions(), reason="需要已同步国考职位的 MySQL")


@DB_OK
def test_fetch_guokao_positions_returns_deterministic_match():
    facts = {"major": "计算机科学与技术", "degree": "本科",
             "political_status": "中共党员"}
    g = cx.fetch_guokao_positions(1, facts)
    assert g["available"] is True
    assert g["year"] == 2027
    assert g["matched_positions"] > 0
    assert g["total_positions"] == 19426
    assert g["matched_headcount"] >= 0
    assert isinstance(g["examples"], list)
