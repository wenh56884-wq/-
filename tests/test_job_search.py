# tests/test_job_search.py
# 职责：钉死岗位搜索的确定性口径——排序优先级、词边界、筛选器、分页、兜底
# 依赖：engine.job_search（纯函数，不打库不联网）
# 说明：这里断言的全是「用户能感知的行为」：
#       搜 java 不该出现前端岗、标题命中的必须排前面、筛选放宽只能变多不能变少。

from __future__ import annotations

import pytest

from engine import job_search as js


# ================================================================
# 夹具：一组构造得刚好能区分各种边界的岗位
# ================================================================
@pytest.fixture
def jobs() -> list[dict]:
    return [
        {   # 标题 + 技能双命中
            "id": 1, "title": "Java开发工程师", "company": "甲公司",
            "city": "南京", "education": "本科",
            "salary_min": 12000, "salary_max": 20000,
            "exp_min": 1, "exp_max": 3,
            "skill_tags": ["Java", "Spring"], "description": "后端服务开发",
        },
        {   # 只在 JD 里提到一次
            "id": 2, "title": "数据分析师", "company": "乙银行",
            "city": "上海", "education": "本科",
            "salary_min": 9000, "salary_max": 14000,
            "exp_min": 1, "exp_max": 3,
            "skill_tags": ["SQL"], "description": "需要与Java团队对接接口",
        },
        {   # 技能里有 JavaScript —— 搜 java 不该命中它
            "id": 3, "title": "前端开发", "company": "丙互联网",
            "city": "杭州", "education": "本科",
            "salary_min": 10000, "salary_max": 16000,
            "exp_min": 1, "exp_max": 3,
            "skill_tags": ["Vue", "JavaScript"], "description": "H5 页面开发",
        },
        {   # 应届可投、薪资低
            "id": 4, "title": "测试工程师", "company": "丁软件",
            "city": "南京", "education": "大专",
            "salary_min": 6000, "salary_max": 9000,
            "exp_min": 0, "exp_max": 1,
            "skill_tags": ["自动化测试"], "description": "",
        },
        {   # 无薪资、无经验：边界数据，不能崩
            "id": 5, "title": "运维工程师", "company": "戊科技",
            "city": "成都", "education": "学历不限",
            "salary_min": None, "salary_max": None,
            "exp_min": None, "exp_max": None,
            "skill_tags": [], "description": "",
        },
    ]


# ================================================================
# 一、关键词解析
# ================================================================
def test_parse_keywords_splits_on_common_separators():
    assert js.parse_keywords("Java 开发") == ["java", "开发"]
    assert js.parse_keywords("Java,开发") == ["java", "开发"]
    assert js.parse_keywords("Java、开发") == ["java", "开发"]
    assert js.parse_keywords("  java   JAVA  ") == ["java"], "大小写应视为同一个词"


def test_parse_keywords_keeps_compound_without_space():
    """用户没打空格时不该替他切：「Java开发」与「Java 开发」语义不同。"""
    assert js.parse_keywords("Java开发") == ["java开发"]


def test_parse_keywords_empty():
    assert js.parse_keywords("") == []
    assert js.parse_keywords("   ") == []


# ================================================================
# 二、词边界：搜 java 不能命中 javascript
# ================================================================
def test_english_keyword_respects_word_boundary(jobs):
    r = js.search_jobs(jobs, "java")
    titles = [i["title"] for i in r["items"]]
    assert "前端开发" not in titles, "JavaScript 不该被 java 命中（词边界）"
    assert "Java开发工程师" in titles


def test_english_keyword_matches_dotted_and_symbol_forms(jobs):
    """c++ / node.js 这类带符号的技能名要能精确命中。"""
    pool = [
        {"id": 10, "title": "C++工程师", "company": "A", "skill_tags": ["C++"], "description": ""},
        {"id": 11, "title": "C#工程师", "company": "B", "skill_tags": ["C#"], "description": ""},
    ]
    r = js.search_jobs(pool, "c++")
    assert [i["title"] for i in r["items"]] == ["C++工程师"]
    r2 = js.search_jobs(pool, "c#")
    assert [i["title"] for i in r2["items"]] == ["C#工程师"]


def test_chinese_keyword_uses_substring(jobs):
    """中文没有词边界，搜「前端」命中「前端开发」是对的。"""
    r = js.search_jobs(jobs, "前端")
    assert [i["title"] for i in r["items"]] == ["前端开发"]


# ================================================================
# 三、排序：标题 > 技能 > 公司 > JD
# ================================================================
def test_title_match_ranks_above_desc_match(jobs):
    """搜 java：标题命中的必须排在「JD 里顺便提一句」的前面。"""
    r = js.search_jobs(jobs, "java")
    assert r["items"][0]["title"] == "Java开发工程师"
    assert r["items"][0]["relevance_level"] == js.LEVEL_HIGH
    last = r["items"][-1]
    assert last["title"] == "数据分析师"
    assert last["relevance_level"] == js.LEVEL_LOW, "只有 JD 命中应为 low"


def test_same_keyword_counted_once_per_field(jobs):
    """同一关键词在同一字段只算一次，避免 JD 反复提就刷分。"""
    a = js.score_one({"title": "Java", "company": "X", "skill_tags": [],
                      "description": "java java java java java"}, ["java"])["score"]
    b = js.score_one({"title": "Java", "company": "X", "skill_tags": [],
                      "description": "java"}, ["java"])["score"]
    assert a == b == js.W_TITLE + js.W_DESC


def test_matched_fields_are_reported(jobs):
    """前端要显示「命中：岗位名称、技能标签」，这个信息必须给出来。"""
    r = js.search_jobs(jobs, "java")
    top = r["items"][0]
    assert "title" in top["matched_fields"]
    assert "skill" in top["matched_fields"]
    # 对外字段的中文名映射齐全
    for f in top["matched_fields"]:
        assert f in js.FIELD_LABELS


def test_multi_keyword_must_hit_at_least_one(jobs):
    """多关键词是「或」：命中任一即入选，但同时命中更多的排前面。"""
    r = js.search_jobs(jobs, "java sql")
    titles = [i["title"] for i in r["items"]]
    assert "Java开发工程师" in titles and "数据分析师" in titles
    assert r["items"][0]["title"] == "Java开发工程师"


def test_no_match_returns_empty_not_noise(jobs):
    """搜不到就是搜不到——不许拿不相关岗位充数。"""
    r = js.search_jobs(jobs, "量子计算")
    assert r["total"] == 0 and r["items"] == []


# ================================================================
# 四、筛选器
# ================================================================
def test_filter_city(jobs):
    r = js.search_jobs(jobs, "", filters={"cities": ["南京"]})
    assert {i["city"] for i in r["items"]} == {"南京"}
    assert r["total"] == 2


def test_filter_education_allows_unlimited(jobs):
    """「学历不限」的岗位对任何学历都开放。"""
    r = js.search_jobs(jobs, "", filters={"educations": ["大专"]})
    titles = {i["title"] for i in r["items"]}
    assert "测试工程师" in titles, "岗位要求大专，应届大专生应能投"
    assert "运维工程师" in titles, "学历不限应放行"
    assert "Java开发工程师" not in titles


def test_filter_salary_none_is_excluded(jobs):
    """用户要「≥8K」时，没标薪资的岗位无法保证满足 → 不放行。"""
    r = js.search_jobs(jobs, "", filters={"salary_min_gte": 8000})
    titles = {i["title"] for i in r["items"]}
    assert "运维工程师" not in titles, "无薪资数据不能当作满足 ≥8K"
    assert titles == {"Java开发工程师", "数据分析师", "前端开发"}


def test_filter_experience_excludes_unknown(jobs):
    """用户要「应届可投」时，没写经验的岗位同样无法保证 → 不放行。"""
    r = js.search_jobs(jobs, "", filters={"exp_max_lte": 1})
    assert [i["title"] for i in r["items"]] == ["测试工程师"]


def test_filters_combine_with_and(jobs):
    r = js.search_jobs(jobs, "java", filters={"cities": ["南京"], "salary_min_gte": 10000})
    assert [i["title"] for i in r["items"]] == ["Java开发工程师"]


def test_relaxing_filter_never_reduces_result(jobs):
    """放宽筛选只能变多不能变少（这是筛选器最基本的正确性）。"""
    strict = js.search_jobs(jobs, "", filters={"cities": ["南京"], "salary_min_gte": 10000})
    loose = js.search_jobs(jobs, "", filters={"cities": ["南京"]})
    assert loose["total"] >= strict["total"]


# ================================================================
# 五、分页
# ================================================================
def test_pagination_has_no_overlap(jobs):
    p1 = js.search_jobs(jobs, "", limit=2, offset=0)
    p2 = js.search_jobs(jobs, "", limit=2, offset=2)
    ids1 = {i["id"] for i in p1["items"]}
    ids2 = {i["id"] for i in p2["items"]}
    assert not (ids1 & ids2), "两页不能出现同一条岗位"
    assert p1["total"] == p2["total"]


def test_pagination_bounds_regression(jobs):
    """页码越界不报错，返回空 items。"""
    r = js.search_jobs(jobs, "", limit=10, offset=999)
    assert r["items"] == [] and r["total"] == len(jobs)


def test_offset_does_not_change_total(jobs):
    a = js.search_jobs(jobs, "java", limit=1, offset=0)["total"]
    b = js.search_jobs(jobs, "java", limit=1, offset=5)["total"]
    assert a == b


# ================================================================
# 六、同公司限流（结果可浏览性）
# ================================================================
def test_diversify_caps_per_company():
    items = [{"id": i, "company": "同一家", "title": f"岗{i}"} for i in range(5)]
    items.append({"id": 99, "company": "另一家", "title": "岗99"})
    out = js.diversify(items, max_per_company=2)
    assert [i["id"] for i in out[:3]] == [0, 1, 99], "超额项应被挪到后面，不是丢弃"
    assert len(out) == len(items), "总数不能因限流而减少"


def test_diversify_keeps_all_items():
    items = [{"id": i, "company": "A"} for i in range(4)]
    assert len(js.diversify(items, max_per_company=1)) == 4


# ================================================================
# 七、同义词兜底（没命中时不硬凑，给「是不是想找」）
# ================================================================
def test_suggest_keywords_for_known_direction():
    sug = js.suggest_keywords("前端")
    assert sug and sug[0]["direction"] == "前端"
    assert "vue" in [k.lower() for k in sug[0]["keywords"]]


def test_suggest_keywords_excludes_query_itself():
    sug = js.suggest_keywords("vue")
    if sug:
        assert "vue" not in [k.lower() for k in sug[0]["keywords"]]


def test_suggest_keywords_returns_empty_for_gibberish():
    assert js.suggest_keywords("zzzzqqq") == []


def test_directions_dict_loads():
    table = js.load_directions()
    assert len(table) >= 10, "方向词典应至少 10 个方向"
    assert all(d["keywords"] for d in table)


# ================================================================
# 八、分面
# ================================================================
def test_build_facets_counts(jobs):
    f = js.build_facets(jobs)
    cities = {c["value"]: c["count"] for c in f["cities"]}
    assert cities["南京"] == 2
    assert cities["上海"] == 1
    # 按数量降序，南京 2 条应排第一
    assert f["cities"][0]["value"] == "南京"


def test_build_facets_skips_empty_values(jobs):
    f = js.build_facets(jobs)
    assert all(c["value"] for c in f["cities"])
    assert all(e["value"] for e in f["educations"])


# ================================================================
# 九、SQL 注入形状的输入不应造成异常
# ================================================================
@pytest.mark.parametrize("q", [
    "' OR 1=1 --",
    "'; DROP TABLE job; --",
    "100%",
    "java%",
    "_",
    "a" * 100,
])
def test_search_survives_sql_like_input(jobs, q):
    """搜索参数全部经 if not 参数化 + 纯函数过滤，这类输入只该返回空或正常结果。"""
    r = js.search_jobs(jobs, q)
    assert isinstance(r["total"], int)


def test_search_tolerates_missing_fields():
    """脏数据（缺 title/缺 company/缺 tags）不能让搜索崩。"""
    pool = [{"id": 1}, {"id": 2, "title": None, "company": None},
            {"id": 3, "title": "Java", "skill_tags": None}]
    r = js.search_jobs(pool, "java")
    assert r["total"] >= 1


def test_search_tolerates_str_skill_tags():
    """skill_tags 从 MySQL 取出来可能是 JSON 字符串，要能解析。"""
    pool = [{"id": 1, "title": "岗", "company": "C",
             "skill_tags": '["Java", "Spring"]', "description": ""}]
    r = js.search_jobs(pool, "spring")
    assert r["total"] == 1
    assert r["items"][0]["relevance_level"] == js.LEVEL_MID


# ================================================================
# 十、筛选命中说明（filter_notes）
#
# 用户筛「硕士」，结果里出现「学历不限」的岗位时，界面上必须解释一句，
# 否则用户会以为筛选器坏了。这类"正确但反直觉"的行为要能被断言住。
# ================================================================
def test_filter_notes_explain_open_education():
    pool = [{"id": 1, "title": "Java", "company": "C",
             "education": "学历不限", "skill_tags": []}]
    r = js.search_jobs(pool, "java", filters={"educations": ["硕士"]})
    assert r["total"] == 1
    assert "该岗位不限学历" in r["items"][0]["filter_notes"]


def test_filter_notes_empty_when_education_matches():
    pool = [{"id": 1, "title": "Java", "company": "C",
             "education": "硕士", "skill_tags": []}]
    r = js.search_jobs(pool, "java", filters={"educations": ["硕士"]})
    assert r["items"][0]["filter_notes"] == []


def test_filter_notes_explain_zero_experience():
    pool = [{"id": 1, "title": "Java", "company": "C",
             "exp_min": 0, "exp_max": 0, "skill_tags": []}]
    r = js.search_jobs(pool, "java", filters={"exp_max_lte": 1})
    assert "该岗位不限经验" in r["items"][0]["filter_notes"]


def test_filter_notes_present_in_browse_mode():
    """空 query（浏览模式）也要带 filter_notes，前端只写一套渲染逻辑。"""
    pool = [{"id": 1, "title": "Java", "company": "C",
             "education": "学历不限", "skill_tags": []}]
    r = js.search_jobs(pool, "", filters={"educations": ["博士"]})
    assert r["items"][0]["filter_notes"] == ["该岗位不限学历"]


def test_filter_notes_absent_without_filters():
    pool = [{"id": 1, "title": "Java", "company": "C",
             "education": "学历不限", "skill_tags": []}]
    r = js.search_jobs(pool, "java")
    assert r["items"][0]["filter_notes"] == []
