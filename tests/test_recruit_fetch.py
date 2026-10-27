# tests/test_recruit_fetch.py
# 职责：招考抓取/解析的离线单测（不联网，全部用内嵌 HTML / 文本样例）。
#
# 重点覆盖「缺失不冒充」：抽不到就 None，绝不能填成 "不限" 或空字符串。

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from etl import recruit_fetch as rf  # noqa: E402


# ---------------------------------------------------------------- 列表解析


class TestParseList:
    """列表页 → (标题, 链接, 日期)。"""

    def test_picks_full_title_from_title_attr(self):
        """列表可见文字被截成「...」时，必须取 title 属性的完整标题。"""
        html = (
            '<a href="/zwxx/t20261020_16262763.html" '
            'title="重庆市万州区教育事业单位招聘工作人员公告">'
            "重庆市万州区教育事业单位招聘工作人员公...</a>"
        )
        items = rf.parse_list(html, "https://rlsbj.cq.gov.cn/")
        assert len(items) == 1
        assert items[0]["title"] == "重庆市万州区教育事业单位招聘工作人员公告"
        assert "..." not in items[0]["title"]

    def test_skips_non_article_links(self):
        """栏目入口（不带 .html）不应被当成公告。"""
        html = (
            '<a href="/zwxx/sydw/">事业单位公开招聘</a>'
            '<a href="/zwxx/t20261020_1.html">重庆市某单位公开招聘工作人员公告</a>'
        )
        items = rf.parse_list(html, "https://rlsbj.cq.gov.cn/")
        assert len(items) == 1
        assert items[0]["title"].startswith("重庆市某单位")

    def test_date_from_gov_url(self):
        """政府站 t20261020_xxx.html → 2026-10-20。"""
        html = '<a href="/a/t20261020_1.html">重庆市某事业单位2026年招聘工作人员公告</a>'
        items = rf.parse_list(html, "https://rlsbj.cq.gov.cn/")
        assert items[0]["publish_date"] == "2026-10-20"

    def test_date_from_exam_site_url(self):
        """考试院 /web/article/2026-09/30/xxx.html → 2026-09-30。"""
        html = (
            '<a href="/web/article/2026-09/30/content_7131.html">'
            "重庆市2027年全国硕士研究生招生考试报名公告</a>"
        )
        items = rf.parse_list(html, "https://www.cqksy.cn/")
        assert items[0]["publish_date"] == "2026-09-30"

    def test_no_duplicate_urls(self):
        html = (
            '<a href="/a/t20261020_1.html">重庆市某单位招聘工作人员公告一则</a>'
            '<a href="/a/t20261020_1.html">重庆市某单位招聘工作人员公告一则</a>'
        )
        assert len(rf.parse_list(html, "https://x.gov.cn/")) == 1


# ---------------------------------------------------------------- 正文清洗


class TestFlatten:
    """正文拼接：中文不能插入空格，否则 2026 会被拆成「202 6」。"""

    def test_chinese_lines_join_without_space(self):
        assert rf._flatten(["年龄计算截止时间为202", "6年10月"]) == "年龄计算截止时间为2026年10月"

    def test_english_keeps_space(self):
        assert rf._flatten(["Bachelor", "of Science"]) == "Bachelor of Science"


class TestExtractRequirements:
    """正文 → 要求字段。抽不到必须 None。"""

    def test_empty_text_returns_all_none(self):
        out = rf.extract_requirements("")
        for k in ("education_req", "degree_req", "major_req", "age_req",
                  "political_req", "exp_req", "cert_req", "other_req",
                  "signup_start", "signup_end", "exam_date", "headcount"):
            assert out[k] is None, f"{k} 应为 None，实际 {out[k]!r}"

    def test_age_section_extracted_cleanly(self):
        """年龄小节：去掉「年龄计算」标题，且数字不能被空格拆开。"""
        text = (
            "（二）年龄计算\n"
            "本公告所要求的年龄计算截止时间为2026年10月9日，如“38周岁以下”，"
            "指未满39周岁，在1987年10月10日及以后出生，以此类推。\n"
            "（三）毕业（学位）证书及专业\n"
            "考生凭已取得的符合招聘条件的毕业证书报考。\n"
        )
        out = rf.extract_requirements(text)
        age = out["age_req"]
        assert age is not None
        assert age.startswith("本公告所要求"), f"标题未剥离：{age!r}"
        assert "2026年10月9日" in age
        assert "202 6" not in age

    def test_missing_keywords_yield_none(self):
        """正文完全不提学历/专业 → 相应字段必须是 None，不能编。"""
        out = rf.extract_requirements("本公告仅说明报名方式与缴费标准。")
        assert out["education_req"] is None
        assert out["major_req"] is None
        assert out["political_req"] is None


class TestSignupDates:
    """报名时间三种常见写法都要能解析。"""

    @pytest.mark.parametrize("text,start,end", [
        ("报名时间：2026年10月9日9:00至10月15日18:00", "2026-10-09", "2026-10-15"),
        ("报名时间为2026年10月9日至2026年10月15日", "2026-10-09", "2026-10-15"),
        ("报名时间：2026年10月9日—10月15日", "2026-10-09", "2026-10-15"),
    ])
    def test_signup_range(self, text, start, end):
        out = rf.extract_requirements(text)
        assert out["signup_start"] == start
        assert out["signup_end"] == end

    def test_exam_date(self):
        out = rf.extract_requirements("笔试时间：2026年11月28日 9:00-11:00")
        assert out["exam_date"] == "2026-11-28"

    def test_headcount(self):
        out = rf.extract_requirements("本次面向社会招聘12名工作人员。")
        assert out["headcount"] == 12


# ---------------------------------------------------------------- 状态判定


class TestBuildNotice:
    """build_notice：状态只按截止日判，没截止日就 unknown（不猜「在招」）。"""

    def _item(self, title="重庆市某事业单位2026年招聘工作人员公告"):
        return {"title": title, "url": "https://x.gov.cn/a/t20261020_1.html",
                "publish_date": "2026-10-20"}

    def test_status_unknown_without_signup_end(self):
        row = rf.build_notice("cq-sydw", self._item(), "公告正文，未写报名时间。")
        assert row["status"] == "unknown"

    def test_status_open_when_deadline_future(self):
        text = "报名时间：2099年1月1日至2099年1月10日"
        row = rf.build_notice("cq-sydw", self._item(), text)
        assert row["status"] == "open"

    def test_status_closed_when_deadline_past(self):
        text = "报名时间：2020年1月1日至2020年1月10日"
        row = rf.build_notice("cq-sydw", self._item(), text)
        assert row["status"] == "closed"

    def test_exam_type_from_source(self):
        assert rf.build_notice("cq-sydw", self._item(), "")["exam_type"] == "institution"
        assert rf.build_notice("cq-rsks", self._item(), "")["exam_type"] == "civil"
        assert rf.build_notice("yz-chsi", self._item(), "")["exam_type"] == "postgraduate"

    def test_source_key_stable(self):
        """同一 url 反复抓，幂等键必须一致（否则每次都会插新行）。"""
        a = rf.build_notice("cq-sydw", self._item(), "")["source_key"]
        b = rf.build_notice("cq-sydw", self._item(), "")["source_key"]
        assert a == b and len(a) == 32

    def test_raw_text_kept_for_traceability(self):
        row = rf.build_notice("cq-sydw", self._item(), "正文内容")
        assert row["raw_text"] == "正文内容"


# ---------------------------------------------------------------- 源配置


class TestSources:
    def test_three_exam_types_covered(self):
        types = {cfg["exam_type"] for cfg in rf.SOURCES.values()}
        assert types == {"civil", "institution", "postgraduate"}

    def test_civil_excludes_institution(self):
        """考公源必须把「事业单位遴选」排除掉（那属于考编）。"""
        deny = rf.SOURCES["cq-rsks"].get("title_deny") or ()
        assert "事业单位" in deny

    def test_notice_filter_rejects_nav_titles(self):
        assert rf._looks_like_notice("重庆市2026年度考试录用公务员公告")
        assert not rf._looks_like_notice("专业技术人员资格考试常见问题解答")
        assert not rf._looks_like_notice("艺体招生考试专栏")
