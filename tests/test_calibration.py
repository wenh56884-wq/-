# tests/test_calibration.py
# 职责：面试官视角（评分校准）引擎的契约测试，逐条对齐契约第 14 节。
# 说明：纯函数离线测试；不依赖 MySQL / LLM / 网络 / random。

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from engine.calibration import (  # noqa: E402
    CALIBRATION_VERSION,
    PERSONAS,
    build_candidates,
    judge,
    score_candidates,
)
from engine.interview import _norm  # noqa: E402

RUBRIC = {"keywords": ["SQL", "数据清洗", "指标口径", "复盘"],
          "struct_marks": ["首先", "其次", "最后", "结果"]}
QUESTION = "请结合你做过的数据项目，讲讲你是怎么保证数据质量的？"

SELF_REF = ("作为一个AI", "候选人", "模型")


def _answers(rubric=RUBRIC, question=QUESTION):
    return {c["id"]: c["answer"] for c in build_candidates(question, rubric)}


def _scored(rubric=RUBRIC):
    return score_candidates(build_candidates(QUESTION, rubric), rubric, [])


def _blocks(rounds=(2, 3), rubric=RUBRIC):
    out = []
    for r in rounds:
        q = f"第{r}题：{QUESTION}"
        out.append({"round": r, "question": q,
                    "candidates": score_candidates(build_candidates(q, rubric), rubric, [])})
    return out


def _correct_picks(blocks):
    picks = []
    for b in blocks:
        for c in b["candidates"]:
            picks.append({"round": b["round"], "id": c["id"], "rank": c["standard_rank"]})
    return picks


# ================================================================
# PERSONAS 与版本
# ================================================================
def test_personas_contract():
    """PERSONAS 三人、id/label/hint 与契约逐字一致。"""
    assert [p["id"] for p in PERSONAS] == ["talker", "doer", "vague"]
    assert [p["label"] for p in PERSONAS] == ["话术型", "实干型", "空转型"]
    assert all(p.get("hint") for p in PERSONAS)
    assert CALIBRATION_VERSION == "calibration-v1"


# ================================================================
# build_candidates
# ================================================================
def test_build_three_nonempty_fixed_order():
    """三条答案都非空，顺序固定 talker/doer/vague。"""
    cands = build_candidates(QUESTION, RUBRIC)
    assert [c["id"] for c in cands] == ["talker", "doer", "vague"]
    assert all(isinstance(c["answer"], str) and len(c["answer"].strip()) > 0 for c in cands)


def test_talker_zero_keyword_hits():
    """talker 不含任何 rubric 关键词（逐词断言，按 score_answer 同款 _norm 口径）。"""
    talker = _answers()["talker"]
    for kw in RUBRIC["keywords"]:
        assert _norm(kw) not in _norm(talker), f"talker 泄漏了关键词：{kw}"


def test_doer_hits_at_least_two_keywords():
    """doer 把关键词嵌进动作里：至少命中 2 个 rubric 关键词。"""
    doer = _answers()["doer"]
    hits = [kw for kw in RUBRIC["keywords"] if _norm(kw) in _norm(doer)]
    assert len(hits) >= 2


def test_vague_length():
    """vague 短、泛：契约口径 40~60 字（且远小于 80）。"""
    n = len(_answers()["vague"])
    assert 40 <= n <= 60


def test_length_parity():
    """talker 与 doer 长度相当：都在 100~180 之间且相差 <60 字，否则靠长度就能猜出来。"""
    a = _answers()
    nt, nd = len(a["talker"]), len(a["doer"])
    assert 100 <= nt <= 180
    assert 100 <= nd <= 180
    assert abs(nt - nd) < 60


def test_deterministic_same_question():
    """同题两次调用结果完全相等（md5 取模，绝无随机）。"""
    assert build_candidates(QUESTION, RUBRIC) == build_candidates(QUESTION, RUBRIC)
    assert build_candidates(QUESTION, RUBRIC) != build_candidates(QUESTION + "？", RUBRIC)


def test_empty_rubric_robust():
    """rubric 为空 / None 都不抛异常，仍返回 3 条且 talker 与 doer 长度相当。"""
    for rubric in ({}, None):
        cands = build_candidates(QUESTION, rubric)
        assert [c["id"] for c in cands] == ["talker", "doer", "vague"]
        a = {c["id"]: c["answer"] for c in cands}
        assert 100 <= len(a["talker"]) <= 180
        assert 100 <= len(a["doer"]) <= 180
        assert abs(len(a["talker"]) - len(a["doer"])) < 60
        assert 40 <= len(a["vague"]) <= 60


def test_single_keyword_and_empty_struct_marks():
    """keywords 只有 1 个 + struct_marks 为空：不抛异常，talker 仍无关键词、长度相当。"""
    rubric = {"keywords": ["SQL"], "struct_marks": []}
    a = _answers(rubric)
    assert _norm("SQL") not in _norm(a["talker"])
    assert _norm("SQL") in _norm(a["doer"])
    assert abs(len(a["talker"]) - len(a["doer"])) < 60


def test_no_selfref_no_markdown():
    """三条答案都不含自指词与 markdown 符号。"""
    for ans in _answers().values():
        for w in SELF_REF:
            assert w not in ans
        assert "**" not in ans and "#" not in ans and "\n" not in ans
        assert not ans.lstrip().startswith(("-", "*", "1."))


# ================================================================
# score_candidates
# ================================================================
def test_score_talker_kw_zero_doer_higher():
    """talker 的 keyword_score 为 0；doer 的 standard 明显高于 talker（要点踩得准才值钱）。"""
    scored = {c["id"]: c for c in _scored()}
    assert scored["talker"]["dims"]["keyword_score"] == 0.0
    assert scored["doer"]["dims"]["keyword_score"] == 30.0
    assert scored["doer"]["standard"] > scored["talker"]["standard"]
    # standard 与 dims 各分项都是 2 位小数
    for c in scored.values():
        assert round(c["standard"], 2) == c["standard"]
        assert set(c["dims"]) == {"keyword_score", "struct_score", "depth_score", "evidence_score"}


def test_score_standard_rank_distinct():
    """standard_rank 是 1/2/3 三个不同值，且与 standard 降序一致。"""
    scored = _scored()
    ranks = {c["id"]: c["standard_rank"] for c in scored}
    assert set(ranks.values()) == {1, 2, 3}
    order = sorted(scored, key=lambda c: c["standard_rank"])
    assert all(order[i]["standard"] >= order[i + 1]["standard"] for i in range(2))


# ================================================================
# judge
# ================================================================
def test_judge_all_correct():
    """全对：accuracy=100、level=sharp、无偏误、insights 2~3 条、next_drill 非空。"""
    blocks = _blocks()
    out = judge(_correct_picks(blocks), blocks)
    assert out["version"] == CALIBRATION_VERSION
    assert out["accuracy"] == 100.0
    assert out["level"] == "sharp" and out["level_label"] == "判断很准"
    assert out["biases"] == []
    assert 2 <= len(out["insights"]) <= 3 and all(s.strip() for s in out["insights"])
    assert out["next_drill"].strip()
    for item in out["items"]:
        for c in item["candidates"]:
            assert c["my_rank"] == c["standard_rank"]
            assert c["revealed"] is True
        assert item["verdict"].strip()


def test_judge_talker_bias():
    """把 talker 排第一 → talker_bias 命中，detail 引用 talker 答案的真实片段。"""
    blocks = _blocks()
    picks = []
    for b in blocks:
        picks += [{"round": b["round"], "id": "talker", "rank": 1},
                  {"round": b["round"], "id": "vague", "rank": 2},
                  {"round": b["round"], "id": "doer", "rank": 3}]
    out = judge(picks, blocks)
    keys = [b["key"] for b in out["biases"]]
    assert "talker_bias" in keys
    tb = next(b for b in out["biases"] if b["key"] == "talker_bias")
    assert tb["label"] == "结构偏好" and tb["tip"].strip()
    talker_ans = next(c["answer"] for c in blocks[0]["candidates"] if c["id"] == "talker")
    import re as _re
    quoted = _re.findall(r"「([^」]+)」", tb["detail"])
    assert quoted and all(q in talker_ans for q in quoted), "detail 必须逐字引用 talker 的答案"


def test_judge_doer_bias():
    """把 doer 排最后 → doer_bias 命中且 detail 引用 doer 的真实片段。"""
    blocks = _blocks()
    picks = []
    for b in blocks:
        picks += [{"round": b["round"], "id": "vague", "rank": 1},
                  {"round": b["round"], "id": "talker", "rank": 2},
                  {"round": b["round"], "id": "doer", "rank": 3}]
    out = judge(picks, blocks)
    keys = [b["key"] for b in out["biases"]]
    assert "doer_bias" in keys and "talker_bias" not in keys
    db = next(b for b in out["biases"] if b["key"] == "doer_bias")
    assert db["label"] == "实干低估"
    doer_ans = next(c["answer"] for c in blocks[0]["candidates"] if c["id"] == "doer")
    import re as _re
    quoted = _re.findall(r"「([^」]+)」", db["detail"])
    assert quoted and all(q in doer_ans for q in quoted)


def test_judge_empty_picks():
    """picks 为空：accuracy=None、my_rank 全 None、revealed=True、固定 insights、不抛异常。"""
    blocks = _blocks()
    out = judge([], blocks)
    assert out["accuracy"] is None
    assert out["insights"] == ["还没排序，没有可校准的判断。"]
    assert out["next_drill"].strip()
    for item in out["items"]:
        assert all(c["my_rank"] is None and c["revealed"] is True for c in item["candidates"])


def test_judge_duplicate_rank_invalidates_only_that_question():
    """同题 rank 重复 → 该题 my_rank 全 None；其它题不受影响。"""
    blocks = _blocks(rounds=(2, 3))
    picks = [{"round": 2, "id": "talker", "rank": 1},
             {"round": 2, "id": "doer", "rank": 1}]  # rank 重复
    picks += [p for p in _correct_picks([b for b in blocks if b["round"] == 3])]
    out = judge(picks, blocks)
    by_round = {it["round"]: it for it in out["items"]}
    assert all(c["my_rank"] is None for c in by_round[2]["candidates"])
    assert all(c["my_rank"] == c["standard_rank"] for c in by_round[3]["candidates"])
    # 只统计有效题：第 3 题全对 → accuracy 仍 100
    assert out["accuracy"] == 100.0
    assert out["biases"] == []


def test_judge_partial_only_valid_question_counted():
    """只给两道题中的一道排序 → 只统计有效题，另一题 my_rank 全 None。"""
    blocks = _blocks(rounds=(2, 3))
    picks = [p for p in _correct_picks([b for b in blocks if b["round"] == 3])]
    out = judge(picks, blocks)
    by_round = {it["round"]: it for it in out["items"]}
    assert all(c["my_rank"] is None for c in by_round[2]["candidates"])
    assert out["accuracy"] == 100.0
    assert out["level"] == "sharp"
    assert 2 <= len(out["insights"]) <= 3


def test_judge_idempotent():
    """同一输入两次 judge 结果完全相等（纯函数，不改入参）。"""
    blocks = _blocks()
    picks = _correct_picks(blocks)
    r1 = judge(picks, blocks)
    r2 = judge(picks, blocks)
    assert r1 == r2
