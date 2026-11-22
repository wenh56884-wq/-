# tests/test_cert_guide.py
# 职责：考证推荐引擎契约——状态计算、个性化打分、持有去重、通知提醒、种子数据完整性。
# 说明：状态/打分/提醒为纯函数离线单测；目录取数走本地 MySQL（库里无考证数据时跳过）。

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402

from engine import cert_guide  # noqa: E402

TODAY = date(2026, 11, 19)

_ROW = {
    "id": 1,
    "name": "全国计算机等级考试（NCRE）二级",
    "short_name": "计算机二级",
    "org": "教育部教育考试院",
    "level_subject": "二级 Python / MySQL",
    "tracks_json": '["通用","就业","升学"]',
    "tags_json": '["全专业","计算机","大一可考","大二可考"]',
    "prerequisites": "无门槛",
    "benefits": "国家级计算机能力证书",
    "how_to_apply": "网上报名缴费",
    "apply_url": "https://ncre-bm.neea.edu.cn",
    "fee": "约105元/科",
    "reg_start": date(2026, 12, 20),
    "reg_deadline": date(2027, 1, 15),
    "exam_text": "2027年3月27日-29日（预计）",
    "exam_start": date(2027, 3, 27),
    "date_note": "下一批日期预计",
    "cycle": "每年3月、9月各一次",
    "level": "推荐",
    "source_title": "中国教育考试网",
    "source_url": "https://ncre.neea.edu.cn/",
    "verified_at": date(2026, 11, 19),
    "next_batch": "",
}


# ----------------------------------------------------------------
# 1. 状态计算：报名窗口三态 + 常年可报 + 考试临近
# ----------------------------------------------------------------
def test_status_upcoming_before_window():
    st = cert_guide.cert_status(_ROW, date(2026, 11, 19))
    assert st["status"] == "未开始"
    assert st["days_to_deadline"] == 31      # 距报名开始 31 天
    assert st["days_to_exam"] == 128


def test_status_enrolling_inside_window():
    st = cert_guide.cert_status(_ROW, date(2026, 12, 25))
    assert st["status"] == "报名中"
    assert st["days_to_deadline"] == 21
    assert "12月15日" not in st["status_note"] and "01月15日" in st["status_note"]


def test_status_closed_after_window():
    st = cert_guide.cert_status(_ROW, date(2027, 2, 1))
    assert st["status"] == "已截止"


def test_status_always_open_when_dates_null():
    row = dict(_ROW, reg_start=None, reg_deadline=None, exam_start=None)
    st = cert_guide.cert_status(row, TODAY)
    assert st["status"] == "常年可报"


# ----------------------------------------------------------------
# 2. 个性化推荐：打分 / 理由 / 差距（离线伪造目录，不走库）
# ----------------------------------------------------------------
def _recommend_with(rows, **kw):
    orig = cert_guide._query
    cert_guide._query = lambda sql, params=(): [dict(r) for r in rows]
    try:
        return cert_guide.recommend(today=TODAY, **kw)
    finally:
        cert_guide._query = orig


def test_recommend_orders_and_explains():
    cet = dict(_ROW, id=2, name="全国大学英语四级考试（CET-4）", short_name="英语四级",
               tracks_json='["通用","就业","考研","考公"]', tags_json='["全专业","大一可考"]',
               reg_start=date(2027, 3, 10), reg_deadline=date(2027, 3, 25),
               exam_start=date(2026, 12, 12), level="必备")
    result = _recommend_with([dict(_ROW), cet], student_id=0,
                             major="数据科学与大数据技术", grade="大三", intent="就业")
    names = [it["short_name"] for it in result["items"]]
    assert "计算机二级" in names and "英语四级" in names
    top = result["items"][0]
    assert top["match_reasons"], "每条推荐必须带可解释理由"
    assert any("就业" in r for it in result["items"] for r in it["match_reasons"])


def test_recommend_skips_owned_certs():
    orig_query, orig_owned = cert_guide._query, cert_guide._owned_cert_names
    cert_guide._query = lambda sql, params=(): [dict(_ROW)]
    cert_guide._owned_cert_names = lambda sid: ["全国计算机等级考试二级 Python"] if sid else []
    try:
        result = cert_guide.recommend(student_id=99, today=TODAY)
        assert result["items"] == [], "已持有同类证书不应再推荐"
    finally:
        cert_guide._query, cert_guide._owned_cert_names = orig_query, orig_owned


def test_recommend_cet6_requires_cet4():
    cet6 = dict(_ROW, id=3, name="全国大学英语六级考试（CET-6）", short_name="英语六级",
                reg_start=date(2027, 3, 10), reg_deadline=date(2027, 3, 25),
                exam_start=date(2026, 12, 12), level="推荐")
    result = _recommend_with([cet6], student_id=0, grade="大三", intent="就业")
    gaps = result["items"][0]["gaps"]
    assert any("425" in g for g in gaps), "没过四级时六级必须提示 425 分前提"


# ----------------------------------------------------------------
# 3. 通知提醒：报名中（阶段0）+ 临近考试（阶段1）+ 水位安全
# ----------------------------------------------------------------
def test_reminders_enrolling_phase():
    orig = cert_guide._query
    cert_guide._query = lambda sql, params=(): [dict(_ROW)]
    try:
        items = cert_guide.active_reminders(date(2026, 12, 25))
    finally:
        cert_guide._query = orig
    assert len(items) == 1 and items[0]["phase"] == cert_guide.PHASE_ENROLL
    assert items[0]["id"] == cert_guide.CERT_ID_OFFSET + 1 * 100 + cert_guide.PHASE_ENROLL


def test_reminders_exam_near_phase():
    orig = cert_guide._query
    cert_guide._query = lambda sql, params=(): [dict(_ROW)]
    try:
        items = cert_guide.active_reminders(date(2027, 3, 20))  # 考前 7 天
    finally:
        cert_guide._query = orig
    assert len(items) == 1 and items[0]["phase"] == cert_guide.PHASE_EXAM


def test_reminders_upcoming_phase():
    """未开始且距报名开通 ≤14 天：提醒「多久开始报名」（阶段0）。"""
    orig = cert_guide._query
    cert_guide._query = lambda sql, params=(): [dict(_ROW)]
    try:
        items = cert_guide.active_reminders(date(2026, 12, 12))  # 距开通 8 天
    finally:
        cert_guide._query = orig
    assert len(items) == 1
    it = items[0]
    assert it["phase"] == cert_guide.PHASE_UPCOMING
    assert it["id"] == cert_guide.CERT_ID_OFFSET + 1 * 100 + cert_guide.PHASE_UPCOMING
    assert "8 天后开通" in it["title"]


def test_reminders_silent_when_far():
    orig = cert_guide._query
    cert_guide._query = lambda sql, params=(): [dict(_ROW)]
    try:
        assert cert_guide.active_reminders(TODAY) == []      # 报名未开始、考试还远
        assert cert_guide.watermark_max(TODAY) == 0          # 无提醒时不得污染水位
    finally:
        cert_guide._query = orig


def test_merge_notices_keeps_watermark_semantics():
    comp = [{"id": 5, "title": "竞赛通知A", "url": "", "published_at": "2026-11-01"}]
    orig = cert_guide._query
    cert_guide._query = lambda sql, params=(): [dict(_ROW)]
    try:
        # 水位 0：竞赛通知 + 考证提醒都进列表
        merged = cert_guide.merge_notices(comp, 0, date(2026, 12, 25), limit=20)
        assert merged["cert_unread_cnt"] == 1
        assert {i["kind"] if "kind" in i else "competition" for i in merged["items"]} >= {"cert"}
        # 水位推到考证提醒 id 之后：考证提醒不再出现
        merged2 = cert_guide.merge_notices(comp, cert_guide.watermark_max(date(2026, 12, 25)),
                                           date(2026, 12, 25), limit=20)
        assert merged2["cert_unread_cnt"] == 0
    finally:
        cert_guide._query = orig


# ----------------------------------------------------------------
# 4. 种子数据完整性（本地 MySQL 有考证数据才跑）
# ----------------------------------------------------------------
def test_catalog_from_db():
    rows = cert_guide._query("SELECT COUNT(*) AS n FROM `考证目录`")
    if not rows or not int(rows[0].get("n") or 0):
        pytest.skip("本地库无考证目录数据")
    cat = cert_guide.catalog(limit=50)
    assert cat["candidate_cnt"] >= 8, "目录至少 8 本证书"
    for it in cat["items"]:
        assert it["org"] and it["apply_url"].startswith("http"), "主办方与官网必填"
        assert it["source_url"].startswith("http"), "每条必须有可核对的来源链接"
        assert it["verified_at"] == "2026-11-19", "种子数据必须带核实日期"
        if it["status"] == "未开始":
            assert "预计" in (it["date_note"] or "") or "预计" in it["exam_text"], \
                "未公布的批次必须标「预计」"
