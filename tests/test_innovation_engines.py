# tests/test_innovation_engines.py
# 职责：面试实验室四个确定性引擎（panel / expression / passport / shadow）的契约测试。
# 说明：纯函数离线测试；不依赖 MySQL / LLM / 网络。

from __future__ import annotations

import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from engine.expression import EXPRESSION_VERSION, FILLERS, analyze  # noqa: E402
from engine.panel import (  # noqa: E402
    DIMS,
    PANEL_VERSION,
    dimension_percent,
    panel_prompt_facts,
    review,
)
from engine.passport import PASSPORT_VERSION, build_passport  # noqa: E402
from engine.shadow import SHADOW_VERSION, shadow  # noqa: E402


def _item(content: float, structure: float, depth: float, evidence: float,
          hits: list[str] | None = None, missed: list[str] | None = None,
          marks: list[str] | None = None) -> dict:
    """按四维百分制反推 score_answer 明细，便于精确构造极端场景。"""
    return {
        "score": round(0.30 * content + 0.25 * structure + 0.25 * depth + 0.20 * evidence, 2),
        "keyword_score": round(0.30 * content, 2),
        "keyword_hits": hits or [],
        "keyword_missed": missed or [],
        "struct_score": round(0.25 * structure, 2),
        "struct_marks": marks or [],
        "depth_score": round(0.25 * depth, 2),
        "length": 220,
        "evidence_score": round(0.20 * evidence, 2),
    }


_OUTLINE = [{"round": 1, "type": "project"}, {"round": 2, "type": "scenario"},
            {"round": 3, "type": "motivation"}]


# ----------------------------------------------------------------
# panel
# ----------------------------------------------------------------
def test_panel_all_high_recommend_and_low_spread():
    scores = [_item(100, 100, 100, 100, ["角色", "结果"], [], ["首先", "其次", "最后"])
              for _ in _OUTLINE]
    out = review(scores, _OUTLINE)
    assert out["version"] == PANEL_VERSION
    assert [p["verdict"] for p in out["panelists"]] == ["推荐", "推荐", "推荐"]
    assert out["consensus"]["verdict"] == "推荐"
    assert out["consensus"]["spread"] < 5
    assert out["consensus"]["level"] == "高度一致"
    assert out["divergence"] is None
    assert out["answered"] == 3 and out["skipped"] == 0


def test_panel_extreme_gap_spread_and_divergence():
    scores = [_item(10, 90, 50, 100, ["角色"], ["背景", "复盘"])]
    out = review(scores, _OUTLINE[:1])
    # 三人：45.7 / 74.4 / 43.2 → spread 31.2
    assert out["consensus"]["spread"] == 31.2
    assert out["consensus"]["level"] == "严重分歧"
    assert out["divergence"] is not None
    assert out["divergence"]["dimension"] == "evidence"
    assert out["divergence"]["gap"] == 20.0
    assert out["divergence"]["note"]


def test_panel_skipped_round_not_in_average():
    full = _item(80, 80, 80, 80)
    one = review([full], _OUTLINE[:1])
    two = review([full, None], _OUTLINE[:2])
    assert two["answered"] == 1 and two["skipped"] == 1
    for a, b in zip(one["panelists"], two["panelists"]):
        assert b["score"] == a["score"], "未答题不能拉低均分"
        assert b["rounds"][1]["score"] is None


def test_panel_all_skipped_consensus_score_none():
    out = review([None, None, None], _OUTLINE)
    assert out["consensus"]["score"] is None
    assert out["consensus"]["verdict"] is None
    assert out["divergence"] is None
    assert out["answered"] == 0 and out["skipped"] == 3
    assert len(out["panelists"]) == 3
    assert all(p["score"] is None for p in out["panelists"])


def test_panel_three_panelists_order_and_range():
    scores = [_item(70, 72, 66, 60), _item(80, 74, 70, 65), None]
    out = review(scores, _OUTLINE)
    assert [p["id"] for p in out["panelists"]] == ["tech", "hr", "pressure"]
    assert [p["name"] for p in out["panelists"]] == ["陈工", "李敏", "周总"]
    for p in out["panelists"]:
        assert 0 <= p["score"] <= 100
        assert len(p["comment"]) <= 110
        assert len(p["highlights"]) <= 3 and len(p["concerns"]) <= 3
        assert len(p["rounds"]) == 3
    assert 0 <= out["consensus"]["score"] <= 100
    assert 2 <= len(out["consensus"]["advice"]) <= 3
    assert len(panel_prompt_facts(out)) <= 600


def test_panel_deterministic_and_robust():
    scores = [_item(70, 72, 66, 60)]
    assert review(scores, _OUTLINE[:1]) == review(scores, _OUTLINE[:1])
    empty = review([], [])
    assert empty["consensus"]["score"] is None and empty["panelists"]
    # None / 空值不能抛异常
    assert panel_prompt_facts({}) != ""
    assert review(None, None)["answered"] == 0


def test_dimension_percent_marks():
    pct = dimension_percent(_item(50, 40, 30, 20))
    assert pct == {"content": 50.0, "structure": 40.0, "depth": 30.0, "evidence": 20.0}
    assert set(pct) == set(DIMS)


# ----------------------------------------------------------------
# expression
# ----------------------------------------------------------------
_TEXT = ("我在项目里负责接口开发与联调工作，遇到性能问题先定位再拆分优化，"
         "最终把响应时间降下来，并补齐了测试用例与文档。")


def test_expression_fast_speed_penalized():
    fast = analyze(_TEXT, duration_sec=6)     # ≈540 字/分，过快
    normal = analyze(_TEXT, duration_sec=14)  # ≈230 字/分，最佳区
    assert fast["speed_band"] == "偏快"
    assert normal["speed_band"] == "标准"
    assert fast["speed_cpm"] > 320
    assert fast["score"] < normal["score"]
    assert normal["score"] == 100


def test_expression_dense_fillers_penalized():
    clean = analyze("我负责接口开发。我完成了测试。", duration_sec=10)
    dirty = analyze("嗯我负责那个接口开发。其实我完成了就是测试。对吧", duration_sec=10)
    assert dirty["filler_total"] >= 4
    assert dirty["filler_rate"] > 1.5
    assert dirty["score"] < clean["score"]
    assert set(dirty["fillers"]) <= set(FILLERS)


def test_expression_without_duration():
    out = analyze(_TEXT)
    assert EXPRESSION_VERSION == out["version"]
    assert out["confidence"] == "low"
    assert out["speed_cpm"] is None
    assert out["speed_band"] == "未知"
    assert out["duration_sec"] is None
    assert out["score"] > 0
    assert 4 <= len(out["metrics"]) <= 5
    assert "speed" not in {m["key"] for m in out["metrics"]}


def test_expression_empty_text_safe():
    out = analyze("")
    assert out["score"] == 0
    assert out["chars"] == 0
    assert out["filler_total"] == 0
    assert out["fillers"] == {}
    assert out["avg_sentence_len"] == 0
    assert out["pause_count"] == 0
    assert 4 <= len(out["metrics"]) <= 5
    assert 2 <= len(out["tips"]) <= 3
    assert analyze(None, None, None)["score"] == 0  # type: ignore[arg-type]


def test_expression_pause_stats():
    segments = [
        {"text": "第一段", "start": 0.0, "end": 10.0},
        {"text": "第二段", "start": 13.0, "end": 20.0},
        {"text": "第三段", "start": 23.0, "end": 30.0},
    ]
    out = analyze(_TEXT, duration_sec=30, segments=segments)
    assert out["pause_count"] == 2
    assert out["longest_pause_sec"] == 3.0
    assert out["pause_ratio"] == 0.2
    dense = analyze(_TEXT, duration_sec=10, segments=segments)
    assert dense["pause_ratio"] > 0.4
    assert dense["score"] < out["score"]


# ----------------------------------------------------------------
# passport
# ----------------------------------------------------------------
def _sessions() -> list[dict]:
    return [
        {"session_id": 1, "date": "2026-11-01", "total": 65.0, "job_title": "后端",
         "dims": {"content": 62.0, "structure": 60.0, "depth": 64.0, "evidence": 52.0},
         "probes": 0, "spread": 9.5},
        {"session_id": 2, "date": "2026-11-05", "total": 68.5, "job_title": "后端",
         "dims": {"content": 68.0, "structure": 70.0, "depth": 66.0, "evidence": 58.0},
         "probes": 1, "spread": 6.0},
        {"session_id": 3, "date": "2026-11-10", "total": 71.2, "job_title": "后端",
         "dims": {"content": 74.0, "structure": 72.0, "depth": 70.0, "evidence": 62.0},
         "probes": 1, "spread": 4.0},
    ]


def test_passport_empty():
    out = build_passport([])
    assert out == {"version": PASSPORT_VERSION, "sessions": 0, "radar": [], "trend": [],
                   "growth": None, "next_action": None, "badges": [], "empty": True}
    assert build_passport(None)["empty"] is True  # type: ignore[arg-type]


def test_passport_single_session_growth_zero():
    out = build_passport(_sessions()[:1])
    assert out["empty"] is False
    assert out["growth"]["delta"] == 0.0
    assert out["growth"]["first_total"] == 65.0
    assert out["growth"]["last_total"] == 65.0
    assert out["growth"]["consistency"] == 1.0


def test_passport_radar_fixed_four_dims_in_order():
    out = build_passport(_sessions())
    assert [r["key"] for r in out["radar"]] == ["content", "structure", "depth", "evidence"]
    latest = out["radar"][0]
    assert latest["latest"] == 74.0
    assert latest["best"] == 74.0
    assert latest["avg"] == 68.0
    assert latest["target"] == 78
    assert latest["gap"] == 4.0
    assert latest["hit"] is False


def test_passport_five_badges_and_growth():
    out = build_passport(_sessions())
    assert [b["id"] for b in out["badges"]] == ["first", "streak3", "improved10",
                                                "allrounder", "steady"]
    assert all(set(b) == {"id", "title", "desc", "earned"} for b in out["badges"])
    assert out["growth"]["delta"] == 6.2
    assert len(out["trend"]) == 3
    assert out["next_action"]["dim"] == "evidence"
    assert out["next_action"]["label"] == "证据支撑"
    assert out["next_action"]["drill"]


def test_passport_target_override():
    out = build_passport(_sessions(), target={"evidence": 50, "content": 70})
    by_key = {r["key"]: r for r in out["radar"]}
    assert by_key["evidence"]["target"] == 50
    assert by_key["evidence"]["hit"] is True
    assert by_key["content"]["target"] == 70
    assert by_key["content"]["hit"] is True
    # 未传的维度回落默认值
    assert by_key["structure"]["target"] == 76


def test_passport_accepts_raw_score_detail():
    raw = [{"session_id": 1, "date": "2026-11-01", "total": 70.0, "job_title": "后端",
            "dims": _item(80, 40, 60, 20), "probes": 0, "spread": 3.0}]
    out = build_passport(raw)
    by_key = {r["key"]: r for r in out["radar"]}
    assert by_key["evidence"]["latest"] == 20.0
    assert by_key["structure"]["latest"] == 40.0


# ----------------------------------------------------------------
# shadow
# ----------------------------------------------------------------
_QTYPES = ("project", "major", "scenario", "stress", "motivation", "counter")


def _longest_clause(text: str) -> int:
    parts = re.split(r"[。！？!?；;，,\n\r]+", str(text))
    return max((len(p.strip()) for p in parts), default=0)


def test_shadow_all_question_types_have_frames():
    for qtype in _QTYPES:
        out = shadow(qtype, {"keywords": ["角色", "结果", "困难"]})
        assert out["version"] == SHADOW_VERSION
        assert len(out["frames"]) >= 3
        assert all({"key", "label", "hint"} == set(f) for f in out["frames"])
        assert out["opening"] and out["numbers_hint"]
        assert len(out["pitfalls"]) == 2


def test_shadow_must_include_at_most_four():
    out = shadow("project", {"keywords": ["a", "b", "c", "d", "e", "f"]})
    assert out["must_include"] == ["a", "b", "c", "d"]
    out2 = shadow("project", {"keywords": []}, ["Python", "MySQL", "FastAPI", "Docker", "Redis"])
    assert out2["must_include"] == ["Python", "MySQL", "FastAPI", "Docker"]
    assert shadow("project", {}, None)["must_include"] == []


def test_shadow_no_sentence_over_30_chars():
    for qtype in (*_QTYPES, "unknown"):
        out = shadow(qtype, {"keywords": ["角色"]})
        texts = [f["hint"] for f in out["frames"]]
        texts += [out["numbers_hint"], out["opening"], *out["pitfalls"]]
        for text in texts:
            assert _longest_clause(text) <= 30, f"{qtype} 出现超 30 字长句：{text}"


def test_shadow_unknown_type_fallback():
    out = shadow("", {}, None)
    assert out["frames"] and out["pitfalls"]
    assert out["must_include"] == []
