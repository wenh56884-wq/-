# tests/test_career_forecast.py
# 职责：把「报考分析」的口径钉死（career-forecast-v1）
# 运行：.venv\Scripts\python.exe -m pytest tests\test_career_forecast.py -v
# 说明：全部走纯函数，不连 MySQL、不调大模型

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from engine import career_forecast as cf
from engine import career_rules as cr

ROOT = Path(__file__).resolve().parents[1]

FACTS = {
    "name": "测试生",
    "major": "智能科学与技术",
    "college": "人工智能学院",
    "grade": "大四",
    "degree": "本科",
    "gpa": 82.2,
    "fail_count": 2,
    "cet4_score": 468,
    "cet6_score": None,
    "political_status": "共青团员",
    "weekly_hours": 12,
}
PEER = {"total": 120, "rank": 33, "pct": 0.275, "median": 78.89, "max": 91.2, "min": 63.19}
GATE_SPECS = [
    {"key": "degree", "label": "学历层次", "op": "in", "value": ["本科", "硕士"], "hard": True},
    {"key": "cet4_score", "label": "英语四级 425", "op": ">=", "value": 425, "hard": False},
    {"key": "fail_count", "label": "无挂科记录", "op": "<=", "value": 0, "hard": False},
]
TODAY = date(2026, 10, 27)


def _gates(facts=None):
    return cr.check_hard_gates(GATE_SPECS, facts or FACTS)


# ------------------------------------------------------------
# 一、考试窗口：真实公告优先，且在最近窗口来不及时要往后选
# ------------------------------------------------------------
def test_real_exam_date_is_merged_and_marked():
    """真实公告里的考试日期要并进窗口列表并标注来源，
    不能被「历年规律」覆盖掉（两者性质不同，必须能区分）。"""
    out = cf.plan_windows("考公", TODAY, real_exam_dates=["2027-01-15"])
    real = [w for w in out if w["basis"] == "real_notice"]
    assert real and real[0]["date"] == date(2027, 1, 15)
    # 历年规律仍然保留，且不会被标成真实公告
    assert any(w["basis"] == "historical_pattern" for w in out)
    assert out == sorted(out, key=lambda w: w["date"])


def test_past_exam_dates_are_dropped():
    """已经过去的考试日期不能当窗口用。"""
    out = cf.plan_windows("考公", TODAY, real_exam_dates=["2024-11-29"])
    assert all(w["date"] > TODAY for w in out)


def test_primary_window_skips_infeasible_near_one():
    """大四 10 月看国考只剩 4 周，需要每周 175 小时 —— 这个窗口不成立，
    主窗口应自动落到 3 月省考，否则阶段排期会给出一个 4 周的假计划。"""
    windows = cf.plan_windows("考公", TODAY)
    assert windows[0]["date"] == date(2026, 11, 29)
    primary, reason = cf._pick_primary(cf.PATHS["考公"], windows, 12)
    assert primary["date"] == date(2027, 3, 20)
    assert "来不及" in reason


def test_primary_window_keeps_nearest_when_enough_time():
    """离两次考试都远时，最近窗口就是主窗口，不该无端往后推。
    （2025-03-01 那个时点离 3 月省考只剩 2 周，700 小时基准本就不成立，
      所以这里取 6 月，此时最近的 11 月国考有 26 周，够用。）"""
    early = date(2025, 6, 1)
    windows = cf.plan_windows("考公", early)
    primary, reason = cf._pick_primary(cf.PATHS["考公"], windows, 12)
    assert primary["date"] == windows[0]["date"]
    assert "够用" in reason


# ------------------------------------------------------------
# 二、逐维评分：缺数据 unknown，不拿默认值冒充
# ------------------------------------------------------------
def test_academic_band_and_fail_penalty():
    d = cf.score_academic(82.2, PEER, 2)
    assert d["score"] == pytest.approx(72.0 - 16.0)  # 前 27.5% 落 72 分档，2 门挂科各扣 8
    assert d["level"] == cf.LEVEL_WEAK


def test_academic_unknown_without_peer_sample():
    d = cf.score_academic(82.2, {"total": 2, "rank": None, "pct": None}, 0)
    assert d["score"] is None
    assert d["level"] == cf.LEVEL_UNKNOWN


def test_english_unknown_when_both_missing():
    """没考四六级 ≠ 未通过，必须 unknown。"""
    d = cf.score_english(None, None)
    assert d["score"] is None
    assert d["level"] == cf.LEVEL_UNKNOWN


def test_english_425_boundary_is_pass_band():
    assert cf.score_english(425, None)["score"] == pytest.approx(62.0)
    assert cf.score_english(424, None)["level"] == cf.LEVEL_POOR


def test_eligibility_capped_when_hard_gate_fails():
    """硬门槛不满足时资格维度直接压到 40 以下——不是扣分，是根本报不了。"""
    specs = [{"key": "degree", "label": "学历层次", "op": "in",
              "value": ["硕士"], "hard": True}]
    judged = cr.check_hard_gates(specs, dict(FACTS))
    d = cf.score_eligibility("中共党员", judged)
    assert d["score"] <= 35.0
    assert "未满足的硬门槛" in d["evidence"]


def test_eligibility_unknown_without_any_input():
    d = cf.score_eligibility(None, [])
    assert d["score"] is None


def test_capacity_unknown_without_hours():
    d = cf.score_capacity(None, 20, 700)
    assert d["score"] is None and d["hours"] is None


def test_capacity_ratio_bands():
    # 12h × 20 周 = 240 / 700 = 34% → 24 分
    assert cf.score_capacity(12, 20, 700)["score"] == pytest.approx(24.0)
    # 40h × 20 周 = 800 / 700 = 114% → 85 分
    assert cf.score_capacity(40, 20, 700)["score"] == pytest.approx(85.0)


# ------------------------------------------------------------
# 三、综合档位：维度不足时不出结论
# ------------------------------------------------------------
def test_composite_unknown_when_less_than_three_dims():
    dims = [
        {"key": "academic", "score": 80.0},
        {"key": "english", "score": None},
        {"key": "eligibility", "score": None},
        {"key": "capacity", "score": None},
    ]
    comp = cf._composite(dims, cf.PATHS["考公"].weights)
    assert comp["tier"] == cf.TIER_UNKNOWN
    assert comp["score"] is None
    assert comp["confidence"] == "low"


def test_composite_renormalizes_weights_when_one_dim_missing():
    """缺一维时按剩余权重归一，而不是把缺的那维当 0 分。"""
    dims = [
        {"key": "academic", "score": 80.0},
        {"key": "english", "score": None},
        {"key": "eligibility", "score": 80.0},
        {"key": "capacity", "score": 80.0},
    ]
    comp = cf._composite(dims, cf.PATHS["考公"].weights)
    assert comp["score"] == pytest.approx(80.0)
    assert comp["confidence"] == "medium"


# ------------------------------------------------------------
# 四、提升杠杆：重算门槛，不虚报收益
# ------------------------------------------------------------
def _base(facts=None):
    f = dict(facts or FACTS)
    gates = _gates(f)
    weeks = 20
    dims = cf._score_all(cf.PATHS["考公"], f, PEER, gates, weeks)
    return f, gates, weeks, cf._composite(dims, cf.PATHS["考公"].weights)


def test_lever_clearing_failures_also_flips_the_gate():
    """清掉挂科后，「无挂科」那条门槛要从 fail 变 pass，
    所以资格维度也必须跟着涨——只涨学业分是漏算了。"""
    f, gates, weeks, comp = _base()
    levers = cf.build_leverage(cf.PATHS["考公"], f, PEER, GATE_SPECS, weeks, comp)
    hit = next((l for l in levers if l["key"] == "fail"), None)
    assert hit is not None
    assert hit["维度变化"].get("学业位次") == pytest.approx(16.0)
    assert "资格门槛" in hit["维度变化"]


def test_lever_skips_impossible_weekly_hours():
    """4 周窗口需要每周 175 小时，这种人做不到的量不能当建议。"""
    gates = _gates()
    dims = cf._score_all(cf.PATHS["考公"], FACTS, PEER, gates, 4)
    comp = cf._composite(dims, cf.PATHS["考公"].weights)
    levers = cf.build_leverage(cf.PATHS["考公"], FACTS, PEER, GATE_SPECS, 4, comp)
    assert all(l["key"] != "hours" for l in levers)


def test_lever_hours_generated_when_feasible():
    gates = _gates()
    dims = cf._score_all(cf.PATHS["考公"], FACTS, PEER, gates, 20)
    comp = cf._composite(dims, cf.PATHS["考公"].weights)
    levers = cf.build_leverage(cf.PATHS["考公"], FACTS, PEER, GATE_SPECS, 20, comp)
    hit = next((l for l in levers if l["key"] == "hours"), None)
    assert hit is not None
    # 700 / 20 = 35 小时/周
    assert "35" in str(hit["目标"])


def test_lever_sorted_by_delta_desc():
    f, gates, weeks, comp = _base()
    levers = cf.build_leverage(cf.PATHS["考公"], f, PEER, GATE_SPECS, weeks, comp)
    deltas = [l["综合分变化"] for l in levers]
    assert deltas == sorted(deltas, reverse=True)


# ------------------------------------------------------------
# 五、建议：时间来不及要压过其它建议
# ------------------------------------------------------------
def test_advice_puts_time_window_first_when_infeasible():
    windows = cf.plan_windows("考公", TODAY)
    dims = cf._score_all(cf.PATHS["考公"], FACTS, PEER, _gates(), 20)
    advice = cf.build_advice(cf.PATHS["考公"], FACTS, dims, _gates(),
                             windows, 0.34, TODAY)
    assert advice[0]["优先级"] == 1
    assert advice[0]["类型"] == "时间窗口"
    assert "来不及" in advice[0]["动作"]


def test_advice_flags_missing_data():
    dims = cf._score_all(cf.PATHS["考公"], dict(FACTS, weekly_hours=None, cet4_score=None),
                         PEER, _gates(), 20)
    advice = cf.build_advice(cf.PATHS["考公"], FACTS, dims, _gates(), [], None, TODAY)
    types = [a["类型"] for a in advice]
    assert "数据补齐" in types


# ------------------------------------------------------------
# 六、主入口：不给概率，不越界
# ------------------------------------------------------------
def test_forecast_never_outputs_probability():
    """全仓最容易造假的字段就是「上岸概率」。输出里不允许有概率类字段，
    并且必须显式声明「不是录取概率」。"""
    out = cf.forecast(FACTS, goal="考公", peer=PEER, gates=_gates(), template={"hard_gates": GATE_SPECS})

    def keys(node):
        if isinstance(node, dict):
            for k, v in node.items():
                yield str(k)
                yield from keys(v)
        elif isinstance(node, list):
            for v in node:
                yield from keys(v)

    banned = [k for k in keys(out) if "probab" in k.lower() or "概率" in k]
    assert not banned, f"出现概率类字段：{banned}"
    assert "不是录取概率" in out["composite"]["score_note"]


def test_forecast_reports_unknown_goal_honestly():
    out = cf.forecast(FACTS, goal="就业")
    assert out["available"] is False
    assert "不在报考分析范围内" in out["reason"]


def test_forecast_marks_empirical_baseline_as_empirical():
    out = cf.forecast(FACTS, goal="考编", peer=PEER, gates=_gates())
    kinds = {s["维度"]: s["性质"] for s in out["sources"]}
    assert "经验基线" in kinds["路径基准学时"]


def test_forecast_phase_weeks_sum_to_weeks_left():
    template = cf.PATHS  # 仅占位，真实模板从 rules/ 读
    tpl = json.loads((ROOT / "rules" / "kaogong.json").read_text(encoding="utf-8"))
    out = cf.forecast(FACTS, goal="考公", peer=PEER, gates=_gates(), template=tpl, today=TODAY)
    weeks = sum(p["周数"] for p in out["timeline"]["phases"])
    assert weeks <= out["timeline"]["weeks_left"]


# ------------------------------------------------------------
# 七、考编：模板存在、目标归一正确
# ------------------------------------------------------------
def test_normalize_goal_routes_public_institution_to_kaobian():
    """事业单位/事业编此前被归到考公，模板和排期全用错一套。"""
    assert cr.normalize_goal("我想考重庆的事业单位") == cr.GOAL_KAOBIAN
    assert cr.normalize_goal("考教师编") == cr.GOAL_KAOBIAN
    assert cr.normalize_goal("考公务员") == cr.GOAL_CIVIL


def test_normalize_goal_mixed_when_two_directions():
    assert cr.normalize_goal("考公和考编同时准备") == cr.GOAL_MIXED


def test_kaobian_template_is_loadable_and_complete():
    tpl = json.loads((ROOT / "rules" / "kaobian.json").read_text(encoding="utf-8"))
    for key in ("template", "hard_gates", "phases", "weekly_metrics", "key_nodes"):
        assert tpl.get(key), f"kaobian.json 缺字段 {key}"
    assert tpl["template"] == "kaobian"
    keys = {g["key"] for g in tpl["hard_gates"]}
    assert {"degree", "cet4_score"} <= keys
    # 每条门槛都必须能被 check_hard_gates 消费（op 合法）
    rows = cr.check_hard_gates(tpl["hard_gates"], FACTS)
    assert len(rows) == len(tpl["hard_gates"])
    assert all(r["当前状态"] in {"pass", "fail", "unknown"} for r in rows)


def test_kaobian_forecast_runs_end_to_end():
    tpl = json.loads((ROOT / "rules" / "kaobian.json").read_text(encoding="utf-8"))
    gates = cr.check_hard_gates(tpl["hard_gates"], FACTS)
    out = cf.forecast(FACTS, goal="考编", peer=PEER, gates=gates, template=tpl, today=TODAY)
    assert out["available"] is True
    assert out["opportunities"]["exam_type"] == "institution"
    assert out["timeline"]["baseline_hours"] == 500
