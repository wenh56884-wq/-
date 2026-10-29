# tests/test_warning.py
# 职责：学业预警引擎 V1 的确定性用例（离线运行，不连 MySQL）
# 依赖：pytest / engine.warning / engine.rules
# 说明：手工注入 metrics 与 rules，保证同输入必同输出

from __future__ import annotations

import sys
from pathlib import Path

# 把项目根目录加入 sys.path（无 conftest 时保证 engine 包可导入）
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest

from engine import warning
from engine.rules import LEVEL_RED, LEVEL_YELLOW, WarningRules, build_rules
from engine.warning import (
    ENGINE_VERSION,
    compute_class,
    compute_rank_pct,
    compute_student,
    get_warning_list,
    normalize_metrics,
    risk_score_of,
)

TENANT_A = 1
TENANT_B = 2
TERM = "2025-2026-2"
CLASS = "RJ2201"


def _rules(tenant_id: int = TENANT_A) -> WarningRules:
    """该租户使用的默认规则（不读库）。"""
    return WarningRules.defaults(tenant_id)


def _metrics(
    *,
    fail_count: int = 0,
    gpa: float = 80.0,
    gpa_drop: float = 0.0,
    attendance_rate: float = 0.95,
    rank_pct: float = 0.20,
    name: str = "张三",
) -> dict:
    """构造一条原始指标行。"""
    return {
        "student_no": "RJ2022001",
        "name": name,
        "fail_count": fail_count,
        "gpa": gpa,
        "gpa_drop": gpa_drop,
        "attendance_rate": attendance_rate,
        "rank_pct": rank_pct,
    }


def test_case1_all_normal_returns_none_zero():
    """用例 1：全指标正常 → none，score=0。"""
    result = compute_student(
        TENANT_A, "RJ2022001", TERM, metrics=_metrics(), rules=_rules()
    )
    assert result["risk_score"] == 0
    assert result["level"] == "none"
    assert result["reasons"] == []
    assert result["metrics"]["attendance_rate"] == 0.95


def test_case2_three_fails_at_least_orange():
    """用例 2：挂 3 门 → 至少 orange（默认规则下 45 分，正好踩橙线）。"""
    result = compute_student(
        TENANT_A,
        "RJ2022001",
        TERM,
        metrics=_metrics(fail_count=3, gpa=52.0, rank_pct=0.90),
        rules=_rules(),
    )
    assert result["risk_score"] == 45
    assert result["level"] in (LEVEL_RED, "orange")
    assert "本学期挂科3门" in result["reasons"]


def test_case3_gpa_drop_hits_second_metric():
    """用例 3：均分下滑 20 → 命中指标二，reasons 含"下滑"。"""
    result = compute_student(
        TENANT_A,
        "RJ2022001",
        TERM,
        metrics=_metrics(gpa=68.4, gpa_drop=20.0, attendance_rate=0.92),
        rules=_rules(),
    )
    # min(30, (20-5)*2+10) = 30
    assert result["risk_score"] == 30
    assert result["level"] == LEVEL_YELLOW
    assert any("下滑" in r for r in result["reasons"])
    assert "本学期平均成绩下滑20分" in result["reasons"]


def test_case4_low_attendance_hits_third_metric():
    """用例 4：出勤 0.60 → 命中指标三（拿满 25 分）。"""
    result = compute_student(
        TENANT_A,
        "RJ2022001",
        TERM,
        metrics=_metrics(attendance_rate=0.60),
        rules=_rules(),
    )
    assert result["risk_score"] == 25
    assert result["level"] == LEVEL_YELLOW
    assert any("出勤率降至60%" in r for r in result["reasons"])


def test_case5_three_worse_is_red_and_capped():
    """用例 5：三项同时恶化 → red，且 score 不超 100。"""
    result = compute_student(
        TENANT_A,
        "RJ2022001",
        TERM,
        metrics=_metrics(
            fail_count=3, gpa=48.5, gpa_drop=20.0,
            attendance_rate=0.60, rank_pct=0.97,
        ),
        rules=_rules(),
    )
    # 45 + 30 + 25 = 100，裁剪后仍为 100
    assert result["risk_score"] == 100
    assert result["level"] == LEVEL_RED
    assert 0 <= result["risk_score"] <= 100
    assert len(result["reasons"]) == 3
    # v2 新增接口字段 coverage / missing（缺失不冒充，字典第 3.2 节）
    assert set(result) == {
        "student_no", "name", "risk_score", "level", "reasons",
        "coverage", "missing", "metrics",
    }
    assert result["coverage"] == 3
    assert result["missing"] == []


def test_case6_same_input_same_output():
    """用例 6：同输入跑两次结果完全一致。"""
    kwargs = {
        "tenant_id": TENANT_A,
        "student_no": "RJ2022001",
        "term": TERM,
        "metrics": _metrics(fail_count=2, gpa=61.2, gpa_drop=11.6,
                            attendance_rate=0.71, rank_pct=0.83),
        "rules": _rules(),
    }
    first = compute_student(**kwargs)
    second = compute_student(**kwargs)
    assert first == second
    # 挂 2 门 30 分 + 下滑 11.6 分 23.2 分 + 出勤 0.71 计分 14 分 = 67
    assert first["risk_score"] == 67
    assert first["level"] == LEVEL_RED


def test_case7_rules_override_by_tenant_rows():
    """数据库行按租户覆盖：fail_count 权重 2.0 时挂 3 门得 90 分。"""
    rows = [
        {"metric": "fail_count", "weight": 2.0, "red_value": 45.0,
         "orange_value": 30.0, "yellow_value": 15.0},
    ]
    rules = build_rules(TENANT_A, rows)
    assert rules.tenant_id == TENANT_A
    assert rules.fail_count.weight == 2.0
    m = normalize_metrics(_metrics(fail_count=3))
    assert risk_score_of(m, rules) == 90

    # 另一租户不传行 → 仍是默认规则
    other = build_rules(TENANT_B, [])
    assert other.tenant_id == TENANT_B
    assert other.fail_count.weight == 1.0
    assert risk_score_of(m, other) == 45


def test_case8_class_and_level_filter():
    """compute_class 排序 + get_warning_list 按等级过滤。"""
    rows = [
        {**_metrics(name="甲"), "student_no": "S003"},
        {**_metrics(name="乙", fail_count=3, gpa_drop=20.0,
                    attendance_rate=0.60), "student_no": "S001"},
        {**_metrics(name="丙", fail_count=2), "student_no": "S002"},
    ]
    results = compute_class(TENANT_A, CLASS, TERM, rows=rows, rules=_rules())
    assert [r["student_no"] for r in results] == ["S001", "S002", "S003"]
    assert results[0]["level"] == LEVEL_RED

    red_list = get_warning_list(TENANT_A, CLASS, TERM, "red", rows=rows,
                                rules=_rules())
    assert [r["student_no"] for r in red_list] == ["S001"]
    none_list = get_warning_list(TENANT_A, CLASS, TERM, "none", rows=rows,
                                 rules=_rules())
    assert [r["student_no"] for r in none_list] == ["S003"]
    assert len(get_warning_list(TENANT_A, CLASS, TERM, None, rows=rows,
                                rules=_rules())) == 3

    with pytest.raises(ValueError):
        get_warning_list(TENANT_A, CLASS, TERM, "purple", rows=rows,
                         rules=_rules())


def test_case9_rank_pct_is_class_position():
    """班级落后百分位：最高分 0.0，末位 1.0，单人班级 0.0，同分按学号定序。"""
    rank = compute_rank_pct({"S001": 90.0, "S002": 60.0, "S003": 75.0})
    assert rank == {"S001": 0.0, "S003": 0.5, "S002": 1.0}
    assert compute_rank_pct({"S001": 80.0}) == {"S001": 0.0}
    tied = {"S001": 90.0, "S002": 60.0, "S003": 60.0}
    assert compute_rank_pct(tied) == {"S001": 0.0, "S002": 0.5, "S003": 1.0}


def test_class_threshold_overrides_tenant_default(monkeypatch):
    """班级覆盖必须压过租户默认，且只影响对应班级。"""
    monkeypatch.setattr(
        warning, "fetch_threshold_rows",
        lambda tenant_id: [
            {"metric": "fail_count", "weight": 1.0,
             "yellow_value": 15, "orange_value": 30, "red_value": 45},
        ],
    )
    monkeypatch.setattr(
        warning, "fetch_class_threshold_rows",
        lambda tenant_id, class_name: [
            {"metric": "fail_count", "weight": 1.5,
             "yellow_value": 5, "orange_value": 10, "red_value": 20},
        ] if class_name == CLASS else [],
    )

    class_rules = warning.get_rules(TENANT_A, CLASS)
    assert class_rules.fail_count.weight == 1.5
    assert class_rules.fail_count.score_1 == 5
    assert class_rules.fail_count.score_2 == 10
    assert class_rules.fail_count.score_3 == 20

    other_rules = warning.get_rules(TENANT_A, "OTHER")
    assert other_rules.fail_count.weight == 1.0
    assert other_rules.fail_count.score_1 == 15


def test_engine_has_no_llm_or_random():
    """自检：预警引擎不得引入 LLM 或随机数，且对外暴露版本号。"""
    for name in ("warning.py", "rules.py"):
        src = (_ROOT / "engine" / name).read_text(encoding="utf-8")
        for banned in ("random", "langchain", "langgraph", "openai", "ChatOpenAI"):
            assert banned not in src, f"{name} 出现禁用记号：{banned}"
    assert ENGINE_VERSION == "warning-v2"


def test_level_filter_multi_and_invalid():
    """level 支持逗号分隔多等级（红+黄一起拉），非法多值报错指明坏词。"""
    rows = [
        {**_metrics(name="甲"), "student_no": "S003"},
        {**_metrics(name="乙", fail_count=3, gpa_drop=20.0,
                    attendance_rate=0.60), "student_no": "S001"},
        {**_metrics(name="丙", fail_count=2), "student_no": "S002"},
    ]
    red = get_warning_list(TENANT_A, CLASS, TERM, "red", rows=rows, rules=_rules())
    red_yellow = get_warning_list(TENANT_A, CLASS, TERM, "red,yellow",
                                  rows=rows, rules=_rules())
    assert [r["student_no"] for r in red] == ["S001"]
    # 乙=红、丙=黄（挂 2 门）、甲=正常 → 多等级一起拉出两人
    assert [r["student_no"] for r in red_yellow] == ["S001", "S002"]
    # 带空格的多值也要能解析
    spaced = get_warning_list(TENANT_A, CLASS, TERM, " red , yellow ",
                              rows=rows, rules=_rules())
    assert [r["student_no"] for r in spaced] == ["S001", "S002"]
    # 空串等价于不过滤
    assert len(get_warning_list(TENANT_A, CLASS, TERM, "", rows=rows,
                                rules=_rules())) == 3
    with pytest.raises(ValueError) as ei:
        get_warning_list(TENANT_A, CLASS, TERM, "red,purple", rows=rows,
                         rules=_rules())
    assert "purple" in str(ei.value)
