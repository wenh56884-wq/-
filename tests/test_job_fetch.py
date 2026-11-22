# tests/test_job_fetch.py
# 职责：etl/job_fetch.py 的离线单测（不联网）。
#
# 重点验证三条铁律有没有被破坏：
#   1. 抓不到就是 None —— 不填 0、不默认「不限」（只测「没写」是否留 None）；
#   2. 「学历不限」是原文真信息，与「没抓到」必须区分开；
#   3. ASCII 技能词要卡边界，java 不能命中 javascript。

from __future__ import annotations

from datetime import date

import pytest

from etl import job_fetch as jf

# ---------------------------------------------------------------- 薪资


@pytest.mark.parametrize(
    "text,expect",
    [
        ("5-7k", (5000.0, 7000.0)),
        ("30-55k·15薪", (30000.0, 55000.0)),
        ("1.5-2.5万", (15000.0, 25000.0)),
        ("8千-1.2万", (8000.0, None)),      # 单位混写：只认得出前半段
        ("面议", (None, None)),
        ("", (None, None)),
        (None, (None, None)),
    ],
)
def test_parse_salary(text, expect):
    assert jf.parse_salary(text) == expect


def test_parse_salary_never_returns_zero():
    """「面议」绝不能被解析成 0 元月薪 —— 0 比 unknown 更误导。"""
    for text in ("面议", "薪资面谈", "待遇优厚", None):
        lo, hi = jf.parse_salary(text)
        assert lo is None and hi is None


# ---------------------------------------------------------------- 城市拆分


@pytest.mark.parametrize(
    "loc,expect",
    [
        ("重庆-南岸区南坪(商圈)", ("重庆", "南岸区")),
        ("重庆", ("重庆", None)),
        ("重庆-渝北区", ("重庆", "渝北区")),
        ("", (None, None)),
        (None, (None, None)),
    ],
)
def test_split_city(loc, expect):
    assert jf._split_city(loc) == expect


# ---------------------------------------------------------------- 学历/经验


def test_education_keeps_unlimited_as_real_info():
    """「学历不限」是站点原文，属真信息，要保留。"""
    assert jf._education_from_label("学历不限") == "不限"
    assert jf._education_from_label("本科") == "本科"
    assert jf._education_from_label("硕士") == "硕士"


def test_education_missing_stays_none():
    """没写学历要求 → None，不能因为「没写」就推断成「不限」。"""
    assert jf._education_from_label(None) is None
    assert jf._education_from_label("") is None
    assert jf._education_from_label("五险一金") is None


def test_experience_labels():
    assert jf._experience_from_label("经验不限") == "经验不限"
    assert jf._experience_from_label("3-10年") == "3-10年"
    assert jf._experience_from_label("2年以上") == "2年以上"
    assert jf._experience_from_label("五险一金") is None


# ---------------------------------------------------------------- 技能（词边界）

def test_skill_java_does_not_match_javascript():
    """java ⊥ javascript：这是相关性排序最容易踩的坑。"""
    assert "Java" not in (jf.extract_skills("JavaScript前端开发", "Vue + React") or [])
    assert "Java" in (jf.extract_skills("Java开发工程师", "Spring Boot") or [])


def test_skill_cpp_and_csharp_exact():
    assert "C++" in (jf.extract_skills("C++工程师", "熟悉STL") or [])
    assert "C#" in (jf.extract_skills("C#开发", ".NET平台") or [])


def test_skill_none_when_no_hit():
    """一个技能都没命中 → None，而不是空列表（空列表会被当成「查过了，没有」）。"""
    assert jf.extract_skills("文员", "整理资料、接待客户", "服务业") is None
    assert jf.extract_skills(None, None) is None


def test_skill_bigdata_stack():
    hits = jf.extract_skills("数据开发", "要求 Hive / Spark / Flink，熟悉 Python", "大数据")
    for kw in ("Hive", "Spark", "Flink", "Python"):
        assert kw in hits


# ---------------------------------------------------------------- 卡片解析（mohrss 内嵌 JSON 直采）
#
# 创新点：mohrss 把岗位数据以 JSON 内嵌在 <input id="findjoblist" value="..."> 里，
# 解码即得，无需渲染/DOM 解析。下面直接验证这条链路。

_MOHRSS_LIST_HTML = """
<html><body>
<input id="findjoblist" name="findjoblist" value="[
  {&#034;aab001&#034;:37346507,&#034;aab004&#034;:&#034;金城江区钰翎美容馆&#034;,
   &#034;aca112&#034;:&#034;康养师&#034;,&#034;aab302&#034;:&#034;河池市&#034;,
   &#034;dxs&#034;:&#034;&#034;,&#034;keyWords&#034;:&#034;&#034;,
   &#034;md5&#034;:&#034;key0000000000000000000000000001&#034;},
  {&#034;aab001&#034;:123,&#034;aab004&#034;:&#034;某科技公司&#034;,
   &#034;aca112&#034;:&#034;店员（3名），综合月薪：2500元+提成&#034;,
   &#034;aab302&#034;:&#034;重庆市&#034;,&#034;dxs&#034;:&#034;不限&#034;,
   &#034;keyWords&#034;:&#034;Python&#034;,
   &#034;md5&#034;:&#034;key0000000000000000000000000002&#034;}
]">
</body></html>
"""

_MOHRSS_LIST_URL = "http://job.mohrss.gov.cn/cjobs/jobinfolist/listJobinfolist?pageNo=1"


def test_mohrss_decode_records_full_fields():
    recs = jf._mohrss_decode_records(_MOHRSS_LIST_HTML)
    assert len(recs) == 2
    assert recs[0]["aab001"] == 37346507
    assert recs[0]["aab004"] == "金城江区钰翎美容馆"


def test_mohrss_card_mapping():
    recs = jf._mohrss_decode_records(_MOHRSS_LIST_HTML)
    cards = [jf._mohrss_card(r, _MOHRSS_LIST_URL) for r in recs]
    c0 = cards[0]
    assert c0["title"] == "康养师"
    assert c0["company"] == "金城江区钰翎美容馆"
    assert c0["city"] == "河池市"
    assert c0["source_key"] == "key0000000000000000000000000001"
    assert c0["apply_url"] == _MOHRSS_LIST_URL
    # 第二张：薪资/人数从岗位名里抽，「不限」是原文真信息
    c1 = cards[1]
    assert c1["salary_min"] == 2500.0
    assert c1["headcount"] == 3
    assert c1["education"] == "不限"
    assert c1["skill_tags"] == ["Python"]


def test_mohrss_decode_records_empty():
    assert jf._mohrss_decode_records("") == []
    assert jf._mohrss_decode_records("<html>no input</html>") == []


def test_mohrss_salary_from_title():
    assert jf._mohrss_salary("综合月薪：2500元") == (2500.0, None)
    assert jf._mohrss_salary("月薪3000-5000元") == (3000.0, 5000.0)
    assert jf._mohrss_salary("康养师") == (None, None)


# ---------------------------------------------------------------- 详情页

_DETAIL_TEXT = (
    "--> 【重庆 数据开发工程师招聘】-重庆某数据科技有限公司 重庆招聘信息-猎聘 全国 "
    "数据开发工程师 15-25k·14薪 重庆-渝北区 3-5年 本科 招2人 10月20日更新 "
    "投简历 聊一聊 --> 职位介绍 岗位职责： 1、负责数仓建设，使用 Hive / Spark； "
    "2、参与实时链路 Flink 开发。 任职要求： 1、熟悉 Python；2、本科及以上。 "
    "其他信息 行业要求：大数据 公司简介 " + "某公司成立于 2010 年。" * 5 +
    " 猎聘温馨提示： 如发现违规行为请举报。"
)


def test_parse_detail_extracts_jd_and_headcount():
    d = jf.parse_detail(_DETAIL_TEXT)
    assert d["headcount"] == 2
    assert d["description"] is not None
    assert "数仓建设" in d["description"]
    # JD 必须在「公司简介」处截断，不能把公司介绍也算进岗位描述
    assert "某公司成立于" not in d["description"]
    # 「猎聘温馨提示」属平台提示，不属于 JD
    assert "举报" not in d["description"]


def test_parse_detail_empty_returns_all_none():
    d = jf.parse_detail("")
    assert d["description"] is None
    assert d["headcount"] is None


def test_parse_detail_short_body_is_not_a_jd():
    """「职位介绍」后面只有几个字（页面没渲染完）→ 不算 JD，留 None。"""
    d = jf.parse_detail("职位介绍 暂无")
    assert d["description"] is None


# ---------------------------------------------------------------- 日期推断

def test_guess_year_prev_for_future_month():
    """「10月26日更新」，若当前是 3 月，则该日期属去年。"""
    assert jf._guess_year(10, date(2026, 3, 1)) == 2025
    assert jf._guess_year(2, date(2026, 3, 1)) == 2026


# ---------------------------------------------------------------- 组装

def test_build_job_keeps_missing_as_none():
    """卡片缺学历/经验时，落库字段必须是 None，不能补默认值。"""
    card = {
        "title": "文员", "company": "某公司", "industry": None,
        "city": "重庆", "district": None,
        "salary_min": None, "salary_max": None,
        "education": None, "experience": None,
        "apply_url": "https://www.liepin.com/job/1.shtml",
    }
    row = jf.build_job("mohrss", card, None)
    assert row["education"] is None
    assert row["experience"] is None
    assert row["salary_min"] is None
    assert row["description"] is None
    assert row["deadline"] is None      # 站点不给截止日 → 不猜


def test_build_job_source_key_is_stable():
    card = {"title": "文员", "company": "A", "apply_url": "https://x/job/1.shtml",
            "city": "重庆"}
    a = jf.build_job("mohrss", card, None)["source_key"]
    b = jf.build_job("mohrss", card, None)["source_key"]
    assert a == b and len(a) == 32


def test_build_job_skills_from_title_and_jd():
    card = {"title": "Python数据开发", "company": "A",
            "apply_url": "https://x/job/2.shtml", "city": "重庆"}
    row = jf.build_job("mohrss", card, "职位介绍 熟悉 Hive 与 Spark，本科以上。" * 2)
    assert "Python" in row["skill_tags"]
    assert "Hive" in row["skill_tags"]
