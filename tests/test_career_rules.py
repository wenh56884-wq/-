# tests/test_career_rules.py
# 职责：把职业规划模块的确定性口径钉死（career-v1）
# 运行：.venv\Scripts\python.exe -m pytest tests\test_career_rules.py -v
# 说明：全部用例走纯函数，不连 MySQL / DuckDB，不调大模型

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from engine import career_rules as cr

ROOT = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------
# 一、硬门槛：模型不能把"不满足"改口成"满足"
# ------------------------------------------------------------
def test_gate_fail_is_deterministic():
    """gpa 2.8 < 要求 3.0 必须判 fail —— 这是防模型改口的核心断言。"""
    gates = [{"key": "gpa", "label": "绩点 3.0", "op": ">=", "value": 3.0, "hard": True}]
    out = cr.check_hard_gates(gates, {"gpa": 2.8})
    assert out[0]["当前状态"] == cr.GATE_FAIL
    assert out[0]["差额"] == pytest.approx(-0.2)


def test_gate_pass_when_equal():
    gates = [{"key": "cet4_score", "label": "四级 425", "op": ">=", "value": 425}]
    out = cr.check_hard_gates(gates, {"cet4_score": 425})
    assert out[0]["当前状态"] == cr.GATE_PASS


def test_gate_unknown_when_fact_missing():
    """缺数据必须 unknown，既不是 pass 也不是 fail（缺失不冒充）。"""
    gates = [{"key": "cet4_score", "label": "四级 425", "op": ">=", "value": 425}]
    out = cr.check_hard_gates(gates, {})  # facts 里没有 cet4_score
    assert out[0]["当前状态"] == cr.GATE_UNKNOWN
    assert out[0]["当前值"] is None
    assert cr.unknown_gates(out) == ["四级 425"]


def test_gate_string_ops():
    gates = [
        {"key": "degree", "label": "学历", "op": "in", "value": ["本科", "硕士"]},
        {"key": "grade", "label": "应届", "op": "contains", "value": "大四"},
    ]
    out = cr.check_hard_gates(gates, {"degree": "本科", "grade": "2026届大四"})
    assert [r["当前状态"] for r in out] == [cr.GATE_PASS, cr.GATE_PASS]

    out2 = cr.check_hard_gates(gates, {"degree": "专科", "grade": "大三"})
    assert [r["当前状态"] for r in out2] == [cr.GATE_FAIL, cr.GATE_FAIL]


def test_build_gaps_lists_only_failed():
    gates = [
        {"key": "gpa", "label": "绩点", "op": ">=", "value": 3.0},
        {"key": "cet4_score", "label": "四级", "op": ">=", "value": 425},
        {"key": "degree", "label": "学历", "op": "in", "value": ["本科"]},
    ]
    results = cr.check_hard_gates(gates, {"gpa": 2.8, "degree": "本科"})  # cet4 缺失
    gaps = cr.build_gaps(results)
    assert len(gaps) == 1
    assert "绩点" in gaps[0]
    assert "四级" not in gaps[0]


# ------------------------------------------------------------
# 二、时间倒推：日期由代码算，模型不许算
# ------------------------------------------------------------
def test_weeks_until_basic():
    out = cr.weeks_until("2026-12-20", today=date(2026, 11, 18))
    assert out["days_left"] == 32
    assert out["weeks_left"] == 4  # 32 // 7
    assert out["is_past"] is False


def test_weeks_until_past():
    out = cr.weeks_until("2026-10-01", today=date(2026, 11, 18))
    assert out["days_left"] == -48
    assert out["weeks_left"] == 0
    assert out["is_past"] is True


def test_weeks_until_bad_date_is_none():
    out = cr.weeks_until("待定", today=date(2026, 11, 18))
    assert out["days_left"] is None
    assert out["is_past"] is None
    assert out["error"]


def test_parse_date_multiple_formats():
    for text in ("2026-12-20", "2026/12/20", "2026.12.20", "2026年12月20日", "2026-12-20 09:00:00"):
        assert cr.parse_date(text) == date(2026, 12, 20), text


def test_plan_phases_sum_equals_weeks():
    phases = [
        {"阶段": "基础", "占比": 0.4, "核心任务": "a"},
        {"阶段": "强化", "占比": 0.3, "核心任务": "b"},
        {"阶段": "冲刺", "占比": 0.3, "核心任务": "c"},
    ]
    out = cr.plan_phases(phases, weeks_left=10, today=date(2026, 11, 18))
    assert sum(p["周数"] for p in out) == 10
    assert out[0]["起始周"] == 1
    assert out[-1]["结束周"] == 10


def test_plan_phases_dates_contiguous():
    phases = [
        {"阶段": "基础", "占比": 0.5, "核心任务": "a"},
        {"阶段": "冲刺", "占比": 0.5, "核心任务": "b"},
    ]
    out = cr.plan_phases(phases, weeks_left=4, today=date(2026, 11, 18))
    assert out[0]["时间范围"].split(" ~ ")[0] == "2026-11-18"
    # 第二段应从第一段结束日 +1 天开始
    first_end = out[0]["时间范围"].split(" ~ ")[1]
    second_start = out[1]["时间范围"].split(" ~ ")[0]
    assert (cr.parse_date(second_start) - cr.parse_date(first_end)).days == 1


def test_plan_phases_zero_weeks_returns_empty():
    phases = [{"阶段": "基础", "占比": 1.0, "核心任务": "a"}]
    assert cr.plan_phases(phases, weeks_left=0, today=date(2026, 11, 18)) == []


# ------------------------------------------------------------
# 三、周监控三色：引擎判色，模型只写摘要
# ------------------------------------------------------------
def test_judge_metric_up_direction():
    assert cr.judge_metric(20, 20)["判定"] == cr.WEEK_GREEN
    assert cr.judge_metric(26, 20)["判定"] == cr.WEEK_GREEN  # 超额完成
    assert cr.judge_metric(19, 20)["判定"] == cr.WEEK_YELLOW  # 未达标但落在 10% 容忍带内
    assert cr.judge_metric(18, 20)["判定"] == cr.WEEK_YELLOW  # 容忍带边界
    assert cr.judge_metric(17, 20)["判定"] == cr.WEEK_RED  # 跌破容忍带


def test_judge_metric_down_direction():
    # 错题数：越少越好
    assert cr.judge_metric(3, 5, direction=cr.DIR_DOWN)["判定"] == cr.WEEK_GREEN
    assert cr.judge_metric(5, 5, direction=cr.DIR_DOWN)["判定"] == cr.WEEK_GREEN
    assert cr.judge_metric(5.4, 5, direction=cr.DIR_DOWN)["判定"] == cr.WEEK_YELLOW
    assert cr.judge_metric(9, 5, direction=cr.DIR_DOWN)["判定"] == cr.WEEK_RED


def test_judge_metric_missing_is_unknown_not_green():
    assert cr.judge_metric(None, 20)["判定"] == cr.WEEK_UNKNOWN
    assert cr.judge_metric(20, None)["判定"] == cr.WEEK_UNKNOWN


def test_judge_week_all_missing_is_unknown():
    """全部缺数据 → unknown；绝不能因为"没数据"就报绿。"""
    items = [{"指标": "学习时长", "达标线": 20, "本周实际": None}]
    out = cr.judge_week_items(items)
    assert out["overall"] == cr.WEEK_UNKNOWN
    assert out["missing"] == ["学习时长"]


def test_judge_week_overall_prefers_red():
    items = [
        {"指标": "学习时长", "达标线": 20, "本周实际": 25},   # green
        {"指标": "刷题量", "达标线": 100, "本周实际": 92},   # yellow
        {"指标": "正确率", "达标线": 65, "本周实际": 40},    # red
    ]
    out = cr.judge_week_items(items)
    assert out["overall"] == cr.WEEK_RED
    assert out["counts"][cr.WEEK_RED] == 1


def test_judge_week_partial_green_yellow():
    items = [
        {"指标": "学习时长", "达标线": 20, "本周实际": 25},
        {"指标": "刷题量", "达标线": 100, "本周实际": 92},
        {"指标": "面试场次", "达标线": 1, "本周实际": None},  # 缺数据
    ]
    out = cr.judge_week_items(items)
    assert out["overall"] == cr.WEEK_YELLOW
    assert out["missing"] == ["面试场次"]


# ------------------------------------------------------------
# 四、连续两周才升级（状态由代码记，模型不记忆）
# ------------------------------------------------------------
def test_escalate_after_two_weeks():
    last_week = [{"指标": "刷题量", "判定": cr.WEEK_RED}]
    this_week = [{"指标": "刷题量", "判定": cr.WEEK_RED}]
    hits = cr.escalate_risks([last_week], this_week)
    assert len(hits) == 1
    assert hits[0]["连续周数"] == 2


def test_escalate_not_on_single_week():
    """上周绿、本周红 —— 单周波动不升级。"""
    last_week = [{"指标": "刷题量", "判定": cr.WEEK_GREEN}]
    this_week = [{"指标": "刷题量", "判定": cr.WEEK_RED}]
    assert cr.escalate_risks([last_week], this_week) == []


def test_escalate_ignores_unknown():
    last_week = [{"指标": "刷题量", "判定": cr.WEEK_UNKNOWN}]
    this_week = [{"指标": "刷题量", "判定": cr.WEEK_RED}]
    assert cr.escalate_risks([last_week], this_week) == []


# ------------------------------------------------------------
# 五、通知截止过滤：今天几号不能交给模型
# ------------------------------------------------------------
def test_filter_notices_marks_expired():
    notices = [
        {"标题": "已过期的报名", "截止时间": "2026-10-01"},
        {"标题": "还能报", "截止时间": "2026-12-01"},
        {"标题": "日期待定", "截止时间": ""},
    ]
    out = cr.filter_notices(notices, today=date(2026, 11, 18))
    assert out[0]["status"] == "expired"
    assert out[1]["status"] == "open"
    assert out[1]["days_left"] == 13
    assert out[2]["status"] == "unknown_date"


def test_open_notices_excludes_expired():
    notices = [
        {"标题": "过期", "截止时间": "2026-10-01"},
        {"标题": "有效", "截止时间": "2026-12-01"},
    ]
    kept = cr.open_notices(notices, today=date(2026, 11, 18))
    assert [n["标题"] for n in kept] == ["有效"]


# ------------------------------------------------------------
# 六、模型"系统记录"白名单
# ------------------------------------------------------------
def test_system_record_accepts_allowed_keys():
    rec = {"新增待办": ["本周补交申论作文"], "状态变化": [], "需更新画像": False}
    out = cr.validate_system_record(rec)
    assert out["ok"] is True
    assert out["accepted"]["新增待办"] == ["本周补交申论作文"]


def test_system_record_rejects_unknown_key():
    """模型想直接改绩点 —— 白名单外，整条丢弃。"""
    rec = {"新增待办": [], "绩点": 4.0}
    out = cr.validate_system_record(rec)
    assert out["ok"] is False
    assert "绩点" in out["rejected"]


def test_system_record_rejects_immutable_field_change():
    """目标类型是画像契约，模型无权在对话里偷偷改掉。"""
    rec = {"状态变化": [{"目标类型": "考研"}]}
    out = cr.validate_system_record(rec)
    assert out["ok"] is False
    assert "不可变字段" in out["reason"]


def test_system_record_caps_todo_count():
    rec = {"新增待办": [f"任务{i}" for i in range(9)]}
    out = cr.validate_system_record(rec)
    assert len(out["accepted"]["新增待办"]) == 5


# ------------------------------------------------------------
# 七、目标类型归一
# ------------------------------------------------------------
def test_normalize_goal():
    assert cr.normalize_goal("国考") == cr.GOAL_CIVIL
    assert cr.normalize_goal("想读研") == cr.GOAL_POSTGRAD
    assert cr.normalize_goal("秋招找工作") == cr.GOAL_EMPLOY
    assert cr.normalize_goal("考研和秋招同时准备") == cr.GOAL_MIXED


# ------------------------------------------------------------
# 八、规则库自洽（防止手改 JSON 改坏）
# ------------------------------------------------------------
@pytest.mark.parametrize("name", ["kaogong", "kaoyan", "jiuye"])
def test_rule_library_is_valid(name):
    data = json.loads((ROOT / "rules" / f"{name}.json").read_text(encoding="utf-8"))
    assert data["template"] == name
    assert data["hard_gates"], "硬门槛不能为空"
    assert data["weekly_metrics"], "周监控指标不能为空"
    assert data["phases"], "阶段划分不能为空"
    assert abs(sum(p["占比"] for p in data["phases"]) - 1.0) < 1e-6, "阶段占比之和须为 1"
    # 每个门槛都能被 check_hard_gates 无异常处理
    out = cr.check_hard_gates(data["hard_gates"], {})
    assert all(r["当前状态"] == cr.GATE_UNKNOWN for r in out), "缺 facts 时应全部 unknown"
    # 每个指标的方向必须合法
    for m in data["weekly_metrics"]:
        assert m["方向"] in (cr.DIR_UP, cr.DIR_DOWN)
        assert m["达标线"] > 0


# ------------------------------------------------------------
# 九、「要求」字段必须是中文人话
# ------------------------------------------------------------
@pytest.mark.parametrize(
    "op,value,expect",
    [
        ("contains", "党员", "包含「党员」"),
        ("in", ["本科", "硕士"], "属于「本科、硕士」"),
        (">=", 425, "不低于 425"),
        ("<=", 0, "不超过 0"),
        ("==", "应届", "等于 应届"),
    ],
)
def test_requirement_text_is_human_readable(op, value, expect):
    """前端与模型都会读到「要求」，不能出现 contains / >= 这类内部运算符。"""
    row = cr.check_hard_gates([{"key": "x", "label": "测试项", "op": op, "value": value}], {})[0]
    assert row["要求"] == expect, f"实际 {row['要求']}"
    for symbol in ("contains", ">=", "<=", " in ", "{", "["):
        assert symbol not in row["要求"], f"要求里不该出现内部符号 {symbol}"


def test_gap_text_never_leaks_operator():
    """差距文案同样不能漏运算符——它是直接展示给学生的那句话。"""
    gates = [{"key": "fail_count", "label": "无挂科记录", "op": "<=", "value": 0}]
    gaps = cr.build_gaps(cr.check_hard_gates(gates, {"fail_count": 2}))
    assert gaps == ["无挂科记录未达标（要求 不超过 0，超 2）"], gaps
