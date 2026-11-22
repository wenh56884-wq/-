# tests/test_innovation_attr_peer.py
# 职责：第二批创新引擎（attribution 失分溯源 / peer 同辈分位）的契约测试。
# 说明：纯函数离线测试；不依赖 MySQL / LLM / 网络。字段与阈值逐条对齐契约第 8、9 节。

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from engine.attribution import (  # noqa: E402
    ATTRIBUTION_VERSION,
    TYPE_LABELS,
    attribute,
)
from engine.peer import (  # noqa: E402
    PEER_VERSION,
    benchmark,
    percentile_of,
)


def _course(cid: int | None, name: str, credit: float | None,
            score: float | None, percentile: float | None = None) -> dict:
    return {"course_id": cid, "name": name, "credit": credit,
            "score": score, "percentile": percentile}


# ================================================================
# attribution —— 分型
# ================================================================
def test_attr_foundation_when_all_missed_on_weak_course():
    """漏考点全落在 60 分课上 → foundation，且 narrative 点名课程与轮次。"""
    courses = [
        _course(12, "大数据治理", 3.0, 58.0, 22.0),
        _course(7, "市场营销学", 2.0, 88.0, 72.0),
    ]
    out = attribute({3: ["数据治理"], 5: ["数据治理"]}, courses)

    assert out["version"] == ATTRIBUTION_VERSION
    assert out["type"] == "foundation"
    assert out["type_label"] == "基础薄弱型"
    assert out["missed_share_weak"] == 1.0
    assert len(out["items"]) == 1
    item = out["items"][0]
    assert item["course"] == "大数据治理" and item["course_id"] == 12
    assert item["rounds"] == [3, 5]
    assert item["verdict"] == "课程基础薄弱"
    assert item["score"] == 58.0 and item["percentile"] == 22.0
    assert "大数据治理" in out["narrative"]
    assert "第3、5轮" in out["narrative"]
    # 结论必须明确指向「不是表达问题」
    assert "不是表达问题" in out["narrative"]


def test_attr_expression_when_courses_are_all_strong():
    """课都 85+ 仍漏考点 → expression，结论指向组织与表达。"""
    courses = [
        _course(1, "数据结构与算法", 4.0, 91.0, 85.0),
        _course(2, "计算机网络", 3.0, 86.0, 70.0),
    ]
    out = attribute({2: ["数据结构"], 4: ["计算机网络"]}, courses)

    assert out["type"] == "expression"
    assert out["type_label"] == "表达组织型"
    assert out["missed_share_weak"] == 0.0
    assert {it["verdict"] for it in out["items"]} == {"课程掌握良好"}
    assert "数据结构与算法" in out["narrative"]
    assert "第2轮" in out["narrative"] and "第4轮" in out["narrative"]
    assert "组织与表达" in out["narrative"]


def test_attr_mixed_when_half_on_weak_courses():
    courses = [
        _course(12, "大数据治理", 3.0, 58.0, 22.0),
        _course(2, "计算机网络", 3.0, 86.0, 70.0),
    ]
    out = attribute({3: ["数据治理"], 4: ["计算机网络"]}, courses)

    assert out["type"] == "mixed"
    assert out["type_label"] == "混合型"
    assert out["missed_share_weak"] == 0.5
    assert "大数据治理" in out["narrative"] and "计算机网络" in out["narrative"]
    assert "混合型" in out["narrative"]


def test_attr_unknown_when_nothing_matches():
    """匹配不到就不硬凑：unknown + unmatched 非空 + items 为空。"""
    courses = [_course(1, "大学英语", 3.0, 90.0, 80.0)]
    out = attribute({2: ["量子纠缠", "区块链共识"]}, courses)

    assert out["type"] == "unknown"
    assert out["type_label"] == "证据不足"
    assert out["items"] == []
    assert out["missed_share_weak"] is None  # 0/0 无定义，不填 0 冒充「不薄弱」
    assert set(out["unmatched"]) == {"量子纠缠", "区块链共识"}
    assert "无法判断" in out["narrative"]
    assert out["actions"]  # 仍然要给可执行的补数据动作


def test_attr_unknown_when_matched_course_has_no_grades():
    """课程对上了但成绩单没分数：不许假装能分型，也不许说「课学得不错」。"""
    out = attribute(
        {2: ["数据治理"]},
        [{"course_id": 1, "name": "大数据治理", "credit": 3.0,
          "score": None, "percentile": None}],
    )
    assert out["type"] == "unknown"
    assert out["missed_share_weak"] is None
    assert out["items"][0]["verdict"] == "课程数据不足"
    assert "大数据治理" in out["narrative"]
    assert "学得不错" not in out["narrative"]


def test_attr_unknown_when_no_input():
    out = attribute({}, [], None)
    assert out["type"] == "unknown"
    assert out["unmatched"] == [] and out["items"] == []
    assert out["narrative"]
    assert 2 <= len(out["actions"]) <= 3


# ================================================================
# attribution —— 匹配规则
# ================================================================
def test_attr_picks_higher_credit_then_higher_coverage():
    """多课程同时命中：先比学分，同学分再比覆盖率（不依赖录入顺序）。"""
    same_credit = attribute(
        {1: ["数据治理"]},
        [_course(30, "数据治理", 2.0, 75.0, 50.0),
         _course(31, "数据治理与合规", 4.0, 66.0, 30.0)],
    )
    assert same_credit["items"][0]["course_id"] == 31

    higher_cov = attribute(
        {1: ["数据治理"]},
        [_course(40, "数据治", 3.0, 80.0, 60.0),      # 覆盖率 2/3
         _course(41, "数据治理", 3.0, 80.0, 60.0)],   # 覆盖率 3/3
    )
    assert higher_cov["items"][0]["course_id"] == 41


def test_attr_coverage_threshold_half():
    """2-gram 覆盖率 0.6 命中、0.4 不命中——阈值就是 0.5，宁缺勿滥。"""
    courses = [_course(1, "大数据治理", 3.0, 72.0, 45.0)]
    out = attribute({1: ["数据治理合规"], 2: ["数据安全治理"]}, courses)

    assert [it["concept"] for it in out["items"]] == ["数据治理合规"]
    assert out["unmatched"] == ["数据安全治理"]


def test_attr_verdict_without_percentile_uses_score_only():
    """percentile 缺失时只按分数判：<70 薄弱、<80 一般、其余良好。"""
    courses = [
        _course(1, "线性代数", 3.0, 65.0, None),
        _course(2, "概率论", 2.0, 78.0, None),
        _course(3, "大学物理", 2.0, 90.0, None),
    ]
    out = attribute({1: ["线性代数"], 2: ["概率论"], 3: ["大学物理"]}, courses)
    verdicts = {it["concept"]: it["verdict"] for it in out["items"]}

    assert verdicts == {"线性代数": "课程基础薄弱",
                        "概率论": "课程掌握一般",
                        "大学物理": "课程掌握良好"}
    assert all(it["percentile"] is None for it in out["items"])


def test_attr_cohort_stats_fills_missing_percentile():
    """有成绩无分位时，允许用同专业 p25/p75 估一个分位，并在 evidence 里写明是估算。"""
    out = attribute(
        {1: ["大数据治理"]},
        [_course(1, "大数据治理", 3.0, 65.0, None)],
        {"大数据治理": {"mean": 70.0, "p25": 60.0, "p75": 80.0, "n": 120}},
    )
    item = out["items"][0]
    assert item["percentile"] == 37.5  # 25 + (65-60)/20*50
    assert "估算" in item["evidence"]


# ================================================================
# attribution —— 结论与动作
# ================================================================
def test_attr_narrative_is_specific_not_generic():
    """narrative 必须点名课程与轮次，不能是「继续努力」这类空话。"""
    out = attribute(
        {2: ["数据治理"], 4: ["数据治理"]},
        [_course(12, "大数据治理", 3.0, 55.0, 18.0)],
    )
    text = out["narrative"]
    assert "《大数据治理》" in text
    assert "第2、4轮" in text
    assert "继续努力" not in text
    assert len(text) <= 220  # 两三句话，不是长篇


def test_attr_actions_are_executable():
    courses = [
        _course(12, "大数据治理", 3.0, 55.0, 18.0),
        _course(13, "统计学", 2.0, 62.0, 35.0),
        _course(2, "计算机网络", 3.0, 88.0, 75.0),
    ]
    out = attribute({3: ["数据治理", "统计学"], 5: ["数据治理"]}, courses)

    acts = out["actions"]
    assert 2 <= len(acts) <= 3
    for act in acts:
        assert set(act) == {"when", "what", "why"}
        assert act["when"] in {"本周", "两周内", "本学期"}
        assert act["what"].strip() and act["why"].strip()
    # 动作要落到具体课程上，而不是「多练习」
    assert any("《大数据治理》" in a["what"] for a in acts)
    # 名额有限时按薄弱程度排序：55 分的大数据治理排在 62 分的统计学前面
    assert "大数据治理" in acts[0]["what"]


def test_attr_item_shape_is_exact():
    out = attribute(
        {1: ["数据治理"]},
        [_course(12, "大数据治理", 3.0, 58.0, 22.0)],
    )
    assert set(out) == {"version", "type", "type_label", "missed_share_weak",
                        "items", "unmatched", "narrative", "actions", "soft_skipped"}
    assert set(out["items"][0]) == {"concept", "course", "course_id", "score",
                                    "percentile", "credit", "rounds", "verdict", "evidence"}
    assert set(TYPE_LABELS) == {"foundation", "expression", "mixed", "unknown"}


def test_attr_is_robust_to_dirty_input():
    """None / 脏数据不抛异常：坏轮次、坏考点、坏课程全部丢弃。"""
    out = attribute(
        {None: ["x"], "2": [None, "", 3], 3: "数据治理"},
        [None, "not-a-dict", {"name": None}, {"name": "大数据治理", "score": "abc"}],
        {"大数据治理": None},
    )
    assert out["version"] == ATTRIBUTION_VERSION
    assert isinstance(out["items"], list) and isinstance(out["unmatched"], list)
    assert 2 <= len(out["actions"]) <= 3


# ================================================================
# peer —— percentile_of
# ================================================================
def test_peer_percentile_boundaries_and_ties():
    """严格小于：等于最大值 → 100，等于最小值 → 0，并列不抬分。"""
    samples = [50, 60, 70, 80, 90]
    assert percentile_of(90, samples) == 100.0
    assert percentile_of(50, samples) == 0.0
    assert percentile_of(70, [70, 70, 70, 70, 80]) == 0.0
    assert percentile_of(70, []) is None
    assert percentile_of(None, samples) is None


# ================================================================
# peer —— benchmark 降级链
# ================================================================
_SAMPLES_12 = [50, 55, 60, 62, 65, 68, 70, 72, 75, 78, 82, 90]


def test_peer_observed_when_enough_samples():
    out = benchmark(74.1, {"content": 74.0, "depth": 90.0}, _SAMPLES_12, 128)

    assert out["version"] == PEER_VERSION
    assert out["basis"] == "observed"
    assert out["sample_n"] == 12 and out["cohort"] == 128
    assert out["total"]["score"] == 74.1
    assert out["total"]["percentile"] == 66.7   # 8/12，严格小于
    assert out["total"]["rank"] == 43           # ceil(0.333*128)
    assert out["total"]["label"] == "中上"
    assert [d["key"] for d in out["dims"]] == ["content", "depth"]
    assert all(d["basis"] == "observed" for d in out["dims"])
    assert "实测" in out["note"] and "并列不抬分" in out["note"]
    assert out["honest"] is True


def test_peer_observed_top_score_rank_is_one():
    out = benchmark(95.0, {}, _SAMPLES_12, 128)
    assert out["total"]["percentile"] == 100.0
    assert out["total"]["rank"] == 1
    assert out["total"]["label"] == "前 10%"
    assert out["dims"] == []


def test_peer_course_proxy_when_samples_short():
    out = benchmark(
        70.0,
        {"content": 75.0, "structure": 70.0},
        [68.0, 71.0, 74.0],
        128,
        proxy={"content": [60, 70, 80, 90], "depth": []},
    )

    assert out["basis"] == "course_proxy"
    assert out["sample_n"] == 3
    assert out["total"]["percentile"] is None  # 课程分不冒充面试总分
    assert out["total"]["rank"] is None and out["total"]["label"] is None
    dims = {d["key"]: d for d in out["dims"]}
    assert dims["content"]["percentile"] == 50.0
    assert dims["content"]["basis"] == "course_proxy"
    assert dims["structure"]["percentile"] is None
    assert dims["structure"]["basis"] == "none"
    assert "代理" in out["note"] and "非面试实测" in out["note"]
    assert "样本不足 5 场" in out["note"]


def test_peer_none_when_no_samples_and_no_proxy():
    out = benchmark(70.0, {"content": 70.0}, [68.0, 71.0, 74.0], 128)

    assert out["basis"] == "none"
    assert out["total"]["percentile"] is None
    assert out["total"]["rank"] is None
    assert all(d["percentile"] is None and d["basis"] == "none" for d in out["dims"])
    assert "不给出分位" in out["note"]
    assert out["honest"] is True


def test_peer_none_on_empty_input():
    out = benchmark(None, {}, [], 0)
    assert out["basis"] == "none"
    assert out["sample_n"] == 0 and out["cohort"] == 0
    assert out["total"] == {"score": None, "percentile": None, "rank": None, "label": None}
    assert out["dims"] == []


def test_peer_rank_respects_cohort_bounds():
    """p=0 时 rank 落在最后一名；cohort=1 时最小 1；cohort 非法则不给名次。"""
    bottom = benchmark(10.0, {}, _SAMPLES_12, 40)
    assert bottom["total"]["percentile"] == 0.0
    assert bottom["total"]["rank"] == 40

    tiny = benchmark(95.0, {}, _SAMPLES_12, 1)
    assert tiny["total"]["rank"] == 1

    no_cohort = benchmark(74.1, {}, _SAMPLES_12, 0)
    assert no_cohort["total"]["percentile"] == 66.7
    assert no_cohort["total"]["rank"] is None


def test_peer_label_bands():
    """label 分档边界：90 / 75 / 50 / 25（含恰好等于边界）。"""
    samples = [float(i) for i in range(40)]
    cases = {35.5: "前 10%", 29.5: "前 25%", 19.5: "中上", 9.5: "中下", 8.5: "后 25%"}
    for value, label in cases.items():
        out = benchmark(value, {}, samples, 100)
        assert out["total"]["label"] == label, (value, out["total"])


def test_peer_dims_follow_contract_order_and_drop_nothing_called():
    out = benchmark(
        74.1,
        {"evidence": 60.0, "content": 70.0, "structure": 66.0, "depth": 64.0},
        _SAMPLES_12,
        128,
    )
    assert [d["key"] for d in out["dims"]] == ["content", "structure", "depth", "evidence"]
    assert [d["label"] for d in out["dims"]] == ["内容", "结构", "深度", "证据"]
    assert all(isinstance(d["score"], float) for d in out["dims"])


# ---------------------------------------------------------------
# 软性要点：全是动机/沟通类失分时应判表达型，而不是「证据不足」
# ---------------------------------------------------------------
def test_attr_all_soft_terms_is_expression():
    out = attribute({1: ["兴趣", "项目", "学习方法"]},
                    [_course(12, "大数据治理", 3.0, 88.0, 70.0)])
    assert out["type"] == "expression"
    assert out["soft_skipped"] == 3
    assert out["items"] == []
    assert "表达" in out["narrative"]
    assert "证据不足" not in out["type_label"]
    assert 2 <= len(out["actions"]) <= 3


def test_attr_soft_terms_not_in_unmatched():
    out = attribute({2: ["项目", "沟通"]}, [_course(12, "大数据治理", 3.0, 88.0, 70.0)])
    assert out["unmatched"] == []


def test_attr_skill_bridge_matches_course():
    # 考点「数据治理」不在课程名里，但课程培养该技能 → 应命中（而不是 2-gram 硬匹配）
    course = _course(12, "数据仓库与ETL", 3.0, 61.0, 30.0)
    course["skills"] = ["数据治理", "数据仓库"]
    out = attribute({3: ["数据治理"], 5: ["数据治理"]}, [course])
    assert out["items"], "技能桥应命中课程"
    assert out["items"][0]["course"] == "数据仓库与ETL"
    assert out["items"][0]["rounds"] == [3, 5]
