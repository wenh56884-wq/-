# tests/test_readiness.py
# 职责：岗位就绪度引擎（engine/readiness.py）的契约测试。
# 说明：纯函数离线测试；不依赖 MySQL / LLM / 网络 / catalog 缓存。

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from engine.readiness import (  # noqa: E402
    LEVEL_LABELS,
    READINESS_VERSION,
    STATUS_LABELS,
    STATUS_WEIGHTS,
    assess,
    find_courses_for_skill,
    skill_match,
)

# kg 映射里真实存在的对应关系（见 engine/kg.py COURSE_SKILL_MAP）：
#   数据库原理 → (SQL, 数据库设计)；大数据技术 → (Hive, 数据仓库)
#   统计类课 → (统计分析, Excel)；机器学习 → (机器学习, 算法)

_CATALOG = ["数据库原理", "大数据技术", "数据可视化", "市场营销基础", "概率论与数理统计"]

_RESUME = "熟悉 SQL，做过校园二手书交易平台；参与过市场营销相关的社团活动"


def _course(name: str, score: float | None = 88.0, credit: float | None = 4.0,
            percentile: float | None = 76.0) -> dict:
    return {"name": name, "score": score, "credit": credit, "percentile": percentile}


def _status_of(result: dict, skill: str) -> dict:
    hits = [it for it in result["items"] if it["skill"] == skill]
    assert len(hits) == 1, f"技能 {skill} 应恰好出现一次"
    return hits[0]


# ----------------------------------------------------------------
# skill_match
# ----------------------------------------------------------------
def test_skill_match_exact_hit_is_one():
    # 课程映射精确命中：数据库原理 培养 SQL
    assert skill_match("SQL", "数据库原理") == 1.0
    assert skill_match("Hive", "大数据技术") == 1.0


def test_skill_match_containment_both_long():
    # 双向包含且两边 >=2 字：「学习」⊂ 机器学习（课程映射技能）
    assert skill_match("学习", "机器学习") == 1.0


def test_skill_match_bigram_partial():
    # 无映射命中、靠 2-gram：数据库事务 vs 高级数据库系统 → cov 0.5
    m = skill_match("数据库事务", "高级数据库系统")
    assert 0 < m <= 0.9


def test_skill_match_no_relation_is_zero():
    assert skill_match("Hive", "市场营销基础") == 0.0
    assert skill_match("", "数据库原理") == 0.0


def test_skill_match_short_word_no_false_hit():
    # 短词不做包含匹配乱命中：「数」这种 1 字词不会命中任何课程
    assert skill_match("数", "数据库原理") == 0.0


# ----------------------------------------------------------------
# find_courses_for_skill
# ----------------------------------------------------------------
def test_find_courses_for_skill_uses_catalog():
    assert find_courses_for_skill("SQL", _CATALOG) == ["数据库原理"]
    assert find_courses_for_skill("Hive", _CATALOG) == ["大数据技术"]


def test_find_courses_for_skill_miss_is_empty():
    # catalog 里没有培养这门技能的课 → 空列表，绝不编造课程名
    assert find_courses_for_skill("区块链", _CATALOG) == []
    assert find_courses_for_skill("SQL", []) == []
    assert find_courses_for_skill("SQL", None) == []


# ----------------------------------------------------------------
# 状态判定
# ----------------------------------------------------------------
def test_proven_high_score_and_in_resume():
    job = {"title": "数据分析师", "industry": "互联网", "skills": ["SQL"]}
    r = assess(job, [_course("数据库原理", 88.0)], _RESUME, _CATALOG)
    it = _status_of(r, "SQL")
    assert it["status"] == "proven"
    assert it["status_label"] == STATUS_LABELS["proven"]
    assert it["course"] == "数据库原理"
    assert it["match"] == 1.0
    assert it["in_resume"] is True
    assert "数据库原理" in it["evidence"]


def test_hidden_high_score_not_in_resume():
    job = {"title": "数据分析师", "industry": None, "skills": ["SQL"]}
    r = assess(job, [_course("数据库原理", 88.0)], "会写周报", _CATALOG)
    it = _status_of(r, "SQL")
    assert it["status"] == "hidden"
    assert it["in_resume"] is False
    # hidden 资产必须带课程名，建议句可直接粘进简历
    assert len(r["hidden_assets"]) == 1
    ha = r["hidden_assets"][0]
    assert ha["skill"] == "SQL" and ha["course"] == "数据库原理"
    assert "数据库原理" in ha["suggestion"]
    assert "简历" in ha["why"]


def test_weak_low_score_any_resume():
    job = {"title": "数据分析师", "industry": None, "skills": ["SQL"]}
    r = assess(job, [_course("数据库原理", 62.0)], _RESUME, _CATALOG)
    assert _status_of(r, "SQL")["status"] == "weak"


def test_claimed_no_course_in_resume():
    job = {"title": "运营", "industry": None, "skills": ["新媒体运营"]}
    r = assess(job, [_course("高等数学", 95.0)], "做过新媒体运营，粉丝 2 万", _CATALOG)
    it = _status_of(r, "新媒体运营")
    assert it["status"] == "claimed"
    assert it["course"] is None and it["match"] == 0.0


def test_gap_no_course_not_in_resume():
    job = {"title": "运营", "industry": None, "skills": ["新媒体运营"]}
    r = assess(job, [_course("高等数学", 95.0)], "会写周报", _CATALOG)
    assert _status_of(r, "新媒体运营")["status"] == "gap"


def test_score_none_in_resume_is_claimed():
    job = {"title": "数据分析师", "industry": None, "skills": ["SQL"]}
    r = assess(job, [_course("数据库原理", None)], _RESUME, _CATALOG)
    assert _status_of(r, "SQL")["status"] == "claimed"


def test_score_none_not_in_resume_is_gap():
    job = {"title": "数据分析师", "industry": None, "skills": ["SQL"]}
    r = assess(job, [_course("数据库原理", None)], "会写周报", _CATALOG)
    assert _status_of(r, "SQL")["status"] == "gap"


def test_in_resume_two_char_skill_needs_exact():
    # 长度为 2 的技能只认精确包含：简历里只有「大数据」不含「数据」二字连写？有——
    # 这里反过来验证：二字技能「仓储」不在简历中，即使 2-gram 部分重叠也不算
    job = {"title": "供应链", "industry": None, "skills": ["仓储"]}
    r = assess(job, [], "仓库管理经验丰富", "")
    assert _status_of(r, "仓储")["status"] == "gap"


# ----------------------------------------------------------------
# 课程选择：多门命中取匹配度高者，同匹配取 credit 大者
# ----------------------------------------------------------------
def test_pick_higher_match_course():
    # 映射精确命中(1.0) 应压过 2-gram 候选(0.9)：数据仓库技术 仅名字覆盖
    job = {"title": "数据工程师", "industry": None, "skills": ["数据仓库"]}
    courses = [_course("数据仓库技术", 95.0, 2.0), _course("大数据技术", 85.0, 3.0)]
    r = assess(job, courses, "懂数据仓库", _CATALOG)
    assert _status_of(r, "数据仓库")["course"] == "大数据技术"


def test_pick_higher_credit_on_tie():
    # 同为映射精确命中（match 1.0）→ 取 credit 大者
    job = {"title": "数据分析师", "industry": None, "skills": ["统计分析"]}
    courses = [_course("统计学", 90.0, 2.0), _course("概率论与数理统计", 80.0, 4.0)]
    r = assess(job, courses, "会统计分析", _CATALOG)
    assert _status_of(r, "统计分析")["course"] == "概率论与数理统计"


def test_pick_higher_score_on_full_tie():
    # match、credit 全同 → 取 score 高者
    job = {"title": "数据分析师", "industry": None, "skills": ["统计分析"]}
    courses = [_course("统计学", 75.0, 3.0), _course("应用统计学", 91.0, 3.0)]
    r = assess(job, courses, "会统计分析", _CATALOG)
    assert _status_of(r, "统计分析")["course"] == "应用统计学"


# ----------------------------------------------------------------
# readiness / level / counts
# ----------------------------------------------------------------
def test_readiness_manual_value_and_level():
    # 五种状态各一项：weights (1.0+0.72+0.45+0.35+0)/5*100 = 50.4 → low
    job = {"title": "数据分析师", "industry": "互联网",
           "skills": ["SQL", "Hive", "市场营销", "数据可视化", "算法"]}
    courses = [
        _course("数据库原理", 88.0),        # SQL   proven（简历有 SQL）
        _course("大数据技术", 90.0),        # Hive  hidden（简历没写）
        _course("市场营销基础", None),      # 市场营销 claimed（简历有写、无成绩）
        _course("数据可视化", 62.0),        # 数据可视化 weak
    ]
    # 算法：无课程、简历没写 → gap
    resume = "熟悉 SQL，做过市场营销相关的校园活动"
    r = assess(job, courses, resume, _CATALOG)
    assert r["readiness"] == 50.4
    assert r["level"] == "low"
    assert r["level_label"] == LEVEL_LABELS["low"]
    assert r["counts"] == {"proven": 1, "hidden": 1, "claimed": 1, "weak": 1, "gap": 1}


def test_empty_skills_unknown_level():
    r = assess({"title": "数据分析师", "industry": None, "skills": []},
               [_course("数据库原理", 88.0)], _RESUME, _CATALOG)
    assert r["readiness"] is None
    assert r["level"] == "unknown"
    assert r["level_label"] == "岗位没给技能标签"
    assert r["items"] == []
    assert r["hidden_assets"] == [] and r["gaps"] == []


def test_counts_five_keys_and_sum():
    job = {"title": "数据分析师", "industry": None,
           "skills": ["SQL", "Hive", "算法", "Python"]}
    r = assess(job, [_course("数据库原理", 88.0)], _RESUME, _CATALOG)
    assert list(r["counts"].keys()) == ["proven", "hidden", "claimed", "weak", "gap"]
    assert sum(r["counts"].values()) == len(r["items"])
    assert all(isinstance(v, int) for v in r["counts"].values())


# ----------------------------------------------------------------
# gaps / hooks / narrative / advice
# ----------------------------------------------------------------
def test_gaps_how_course_fix_names_course():
    job = {"title": "数据工程师", "industry": None, "skills": ["Hive"]}
    r = assess(job, [], "会写周报", _CATALOG)
    g = r["gaps"][0]
    assert g["how"] == "course"
    assert g["courses"] == ["大数据技术"]
    assert "大数据技术" in g["fix"]


def test_gaps_how_self_no_invented_course():
    job = {"title": "数据工程师", "industry": None, "skills": ["区块链"]}
    r = assess(job, [], "会写周报", _CATALOG)
    g = r["gaps"][0]
    assert g["how"] == "self"
    assert g["courses"] == []
    assert g["fix"].strip() != ""


def test_interview_hooks_at_most_three_with_course():
    job = {"title": "数据分析师", "industry": None,
           "skills": ["SQL", "Hive", "数据可视化"]}
    courses = [_course("数据库原理", 88.0), _course("大数据技术", 90.0),
               _course("数据可视化", 95.0, 3.0, 90.0)]
    r = assess(job, courses, _RESUME, _CATALOG)
    hooks = r["interview_hooks"]
    assert 0 < len(hooks) <= 3
    # score 降序：数据可视化 95 → 大数据技术 90 → 数据库原理 88
    assert "数据可视化" in hooks[0]
    assert "大数据技术" in hooks[1]
    assert "数据库原理" in hooks[2]


def test_narrative_critical_names_missing_skills():
    job = {"title": "数据工程师", "industry": None, "skills": ["Hive", "SQL"]}
    r = assess(job, [_course("数据库原理", 55.0)], "", _CATALOG)
    assert r["level"] == "critical"
    text = r["narrative"]
    assert "Hive" in text and "SQL" in text
    assert "数据库原理" in text
    assert "加油" not in text


def test_narrative_four_levels_all_distinct():
    job = {"title": "数据分析师", "industry": None, "skills": ["SQL"]}
    texts: dict[str, str] = {}
    for level, score, resume in (("high", 95.0, _RESUME), ("mid", 88.0, "会写周报"),
                                 ("low", None, _RESUME), ("critical", None, "会写周报")):
        if level == "critical":
            # 造 readiness 0：课程与技能无任何关联 → gap
            r = assess(job, [_course("市场营销基础", 95.0)], resume, _CATALOG)
        else:
            # high=proven 100 / mid=hidden 72 / low=claimed 45（resume 有写、无成绩）
            r = assess(job, [_course("数据库原理", score)], resume, _CATALOG)
        assert r["level"] == level, f"{level} 档构造失败：{r['level']}"
        texts[level] = r["narrative"]
    assert len(set(texts.values())) == 4  # 四档文案互不相同


def test_advice_two_to_three_legal_when():
    job = {"title": "数据分析师", "industry": None, "skills": ["SQL", "Hive"]}
    r = assess(job, [_course("数据库原理", 88.0)], _RESUME, _CATALOG)
    assert 2 <= len(r["advice"]) <= 3
    assert all(a["when"] in {"本周", "两周内", "本学期"} for a in r["advice"])
    assert all(a["what"].strip() and a["why"].strip() for a in r["advice"])


# ----------------------------------------------------------------
# 健壮性与幂等
# ----------------------------------------------------------------
def test_robust_against_none_and_empty():
    r1 = assess(None, None, None, None)
    r2 = assess({}, [], "", [])
    for r in (r1, r2):
        assert r["readiness"] is None and r["level"] == "unknown"
        assert r["counts"] == {"proven": 0, "hidden": 0, "claimed": 0, "weak": 0, "gap": 0}
    # score/credit/percentile 全 None 的课程也不抛异常
    r3 = assess({"title": "x", "industry": None, "skills": ["SQL"]},
                [{"name": "数据库原理", "score": None, "credit": None, "percentile": None}],
                None, None)
    assert _status_of(r3, "SQL")["status"] == "gap"


def test_version_and_shape():
    job = {"title": "数据分析师", "industry": "互联网", "skills": ["SQL"]}
    r = assess(job, [_course("数据库原理", 88.0)], _RESUME, _CATALOG)
    assert r["version"] == READINESS_VERSION == "readiness-v1"
    assert r["job_title"] == "数据分析师" and r["industry"] == "互联网"
    keys = list(r.keys())
    assert keys == ["version", "job_title", "industry", "readiness", "level",
                    "level_label", "counts", "items", "hidden_assets", "gaps",
                    "interview_hooks", "narrative", "advice"]
    assert list(r["items"][0].keys()) == ["skill", "status", "status_label", "course",
                                          "score", "percentile", "credit", "match",
                                          "in_resume", "evidence"]


def test_hidden_assets_sorted_and_capped():
    # 5 门高分课、简历全没写 → 最多 4 条，score 降序
    job = {"title": "数据分析师", "industry": None,
           "skills": ["SQL", "Hive", "统计分析", "机器学习", "Python"]}
    courses = [_course("数据库原理", 85.0), _course("大数据技术", 86.0),
               _course("统计学", 87.0), _course("机器学习", 88.0),
               _course("Python程序设计", 89.0)]
    r = assess(job, courses, "会写周报", _CATALOG)
    assert r["counts"]["hidden"] == 5
    assert len(r["hidden_assets"]) == 4
    scores = [ha["score"] for ha in r["hidden_assets"]]
    assert scores == sorted(scores, reverse=True) == [89.0, 88.0, 87.0, 86.0]


def test_idempotent_same_input_same_output():
    job = {"title": "数据分析师", "industry": None,
           "skills": ["SQL", "Hive", "算法"]}
    courses = [_course("数据库原理", 88.0), _course("大数据技术", 90.0)]
    kw = dict(courses=courses, resume_text=_RESUME, catalog=_CATALOG)
    a = json.dumps(assess(job, **kw), ensure_ascii=False, sort_keys=True)
    b = json.dumps(assess(job, **kw), ensure_ascii=False, sort_keys=True)
    assert a == b
