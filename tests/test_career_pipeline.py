# tests/test_career_pipeline.py
# 职责：验证职业规划模块的「引擎定数、模型说话」没有被破坏
# 依赖：agents.career.context / agents.career.nodes / engine.career_rules
# 说明：**不打网络、不调 DeepSeek**——所有模型调用被替身接管，
#       断言的全是「引擎算出来的数」与「模型越权是否被拦」。

from __future__ import annotations

import json
from datetime import date

import pytest

from agents.career import context as cx
from agents.career import nodes
from engine import career_rules as cr


# ================================================================
# 一、模型替身（把 _ask 换掉，不联网）
# ================================================================
@pytest.fixture
def fake_model(monkeypatch):
    """替换 nodes._ask，返回预设内容；记录最后一次收到的 user prompt。"""

    class Fake:
        def __init__(self):
            self.reply = "{}"
            self.last_user = ""
            self.calls = 0

        def __call__(self, system: str, user: str, temperature: float = 0.2) -> str:
            self.last_user = user
            self.calls += 1
            return self.reply

    fake = Fake()
    monkeypatch.setattr(nodes, "_ask", fake)
    return fake


@pytest.fixture
def seeded_plan(monkeypatch):
    """把「已有画像 + 已有规则」两处读库操作换成内存替身（测试不依赖数据库状态）。"""

    plan = {"目标类型": "考公", "目标描述": "毕业报考市直单位", "当前差距": []}
    rule = {
        "plan_id": 1,
        "metrics": [
            {"指标": "行测刷题量", "单位": "题", "达标线": 300, "方向": "up", "容忍带": 0.15},
        ],
    }
    monkeypatch.setattr(cx, "fetch_active_plan", lambda tid, sid: {"id": 1, "goal_type": "考公", "plan": plan})
    monkeypatch.setattr(cx, "fetch_active_rule", lambda tid, sid: rule)
    monkeypatch.setattr(cx, "fetch_week_history", lambda tid, sid, limit=4: [])
    return plan


# ================================================================
# 二、学期倒推（日期必须由代码算，不由模型算）
# ================================================================
def test_semester_deadline_is_deterministic():
    """同一日期永远算出同一截止日；跨年后滚到下学期，不会返回过去的日子。"""
    d1 = nodes._semester_deadline(date(2026, 10, 26))
    d2 = nodes._semester_deadline(date(2026, 10, 26))
    assert d1 == d2, "同一输入必须同一输出（禁止任何随机/时间漂移）"

    # 秋季学期（10 月）→ 次年 1 月
    assert d1 == date(2027, 1, 5)

    # 春季（4 月）→ 当年 7 月
    assert nodes._semester_deadline(date(2027, 4, 1)) == date(2027, 7, 5)

    # 已过 1/5 的冬季 → 滚到当年 7 月，绝不返回过期日期
    later = nodes._semester_deadline(date(2027, 2, 1))
    assert later > date(2027, 2, 1), "剩余周数不能因日期过期变成 0"
    assert later == date(2027, 7, 5)


def test_weeks_left_uses_engine_not_model():
    """weeks_left 由 engine.weeks_until 算，模型无权给。"""
    today = date(2026, 10, 26)
    deadline = nodes._semester_deadline(today)
    got = cr.weeks_until(deadline, today)["weeks_left"]
    # 10/26 → 2027-01-05 共 71 天 → 10 周
    assert got == 10


# ================================================================
# 二·补、年级推算（student.grade 是入学年份，不能直接比「大四」）
# ================================================================
def test_fetch_active_rule_parses_hard_baseline_and_adjustable(monkeypatch):
    """hard_baseline / adjustable 是 JSON 同名列（不是 *_json），不能被读成空列表。"""
    row = {
        "id": 7,
        "plan_id": 1,
        "main_template": "考公",
        "sub_template": None,
        "main_weight": 1.0,
        "gates_json": '[{"key": "degree", "current": "pass"}]',
        "phases_json": '[{"阶段": "基础"}]',
        "metrics_json": '[{"指标": "行测刷题量"}]',
        "calendar_json": "[]",
        "hard_baseline": '["本科", "应届"]',
        "adjustable": '["目标城市"]',
        "engine_version": "career-v1",
        "created_at": None,
    }

    class FakeCursor:
        def execute(self, sql, params=None):
            self.sql = sql

        def fetchone(self):
            return row

    class FakeConn:
        def cursor(self):
            return FakeCursor()

        def close(self):
            pass

    monkeypatch.setattr(cx, "connect", lambda: FakeConn())
    rule = cx.fetch_active_rule(1, 1)

    assert rule is not None
    assert rule["hard_baseline"] == ["本科", "应届"]
    assert rule["adjustable"] == ["目标城市"]
    assert rule["gates"] == [{"key": "degree", "current": "pass"}]
    assert rule["phases"] == [{"阶段": "基础"}]
    assert rule["metrics"] == [{"指标": "行测刷题量"}]


def test_grade_label_from_enroll_year():
    """入学年份 → 真实年级标签；这是确定性推算，不允许模型参与。"""
    today = date(2026, 10, 26)
    assert cx._grade_label(2023, today) == "大四"
    assert cx._grade_label(2024, today) == "大三"
    assert cx._grade_label(2025, today) == "大二"
    assert cx._grade_label(2022, today) == "已毕业"
    # 9 月前算上一学年（8 月时 2025 级仍是大一）
    assert cx._grade_label(2025, date(2026, 8, 1)) == "大一"
    # 脏数据不崩
    assert cx._grade_label(None) is None
    assert cx._grade_label("abc") is None


def test_kaogong_grade_gate_uses_grade_label_not_year():
    """考公「应届」门槛必须吃年级标签，不能拿入学年份 2025 去比「大四」。"""
    gate = next(g for g in cx.load_template("考公")["hard_gates"] if g["key"] == "grade")
    assert "大四" in gate["value"]

    # 大四学生应通过，大二学生应不通过
    pass_row = cr.check_hard_gates([gate], {"grade": "大四"})[0]
    fail_row = cr.check_hard_gates([gate], {"grade": "大二"})[0]
    assert pass_row["当前状态"] == cr.GATE_PASS
    assert fail_row["当前状态"] == cr.GATE_FAIL


# ================================================================
# 三、画像解析：门槛与差距由引擎算，模型的数字一律被覆盖
# ================================================================
def test_parse_plan_ignores_model_gate_verdicts(fake_model):
    """模型即使编了「门槛全满足」，差距仍以引擎判定为准。"""
    fake_model.reply = json.dumps(
        {
            "目标类型": "考公务员",
            "目标描述": "毕业报考市直单位",
            "时间线": [{"节点": "笔试", "时间": "大四下", "事项": "参加省考"}],
            "硬性指标": ["本科"],
            "软性指标": [],
            "待补充问题": ["是否接受异地"],
            "硬门槛": [{"项目": "英语四级", "当前状态": "pass"}],  # 模型伪造的判定
            "当前差距": [],  # 模型声称没有差距
        },
        ensure_ascii=False,
    )
    out = nodes.parse_plan(1, 1, "我想毕业后考公务员，目标是市直单位。", persist=False)
    plan = out["plan"]

    assert out["goal_type"] == "考公", "「考公务员」必须被归一到「考公」"
    assert plan["时间线"][0]["时间"] == "大四下", "相对学期描述应保留"

    # 引擎覆盖：模型写的「硬门槛」「当前差距」不作数
    assert plan["硬门槛"] != [{"项目": "英语四级", "当前状态": "pass"}]
    assert "引擎版本" in plan

    # 门槛条数与模板一致（模型只交了 1 条，引擎必须全部重算）
    template = cx.load_template("考公")
    assert len(plan["硬门槛"]) == len(template["hard_gates"]), (
        "门槛条目必须来自规则库模板，不是模型给的"
    )

    statuses = {g["项目"]: g["当前状态"] for g in plan["硬门槛"]}
    # 模型伪造「政治面貌 pass」，引擎按 DB 真实值（共青团员）判 fail
    political = next(k for k in statuses if "政治面貌" in k)
    assert statuses[political] == cr.GATE_FAIL, (
        f"模型伪造的 pass 必须被引擎覆盖，实际 {statuses}"
    )
    # 合法取值只有 pass / fail / unknown 三种，不许出现模型自造的状态
    assert set(statuses.values()) <= {cr.GATE_PASS, cr.GATE_FAIL, cr.GATE_UNKNOWN}

    # 模型声称「没有差距」，引擎必须按 fail 项算出真实差距
    assert plan["当前差距"], "存在 fail 门槛时「当前差距」不能为空"
    assert len(plan["当前差距"]) >= sum(1 for s in statuses.values() if s == cr.GATE_FAIL)


def test_parse_plan_rejects_empty_text():
    with pytest.raises(ValueError):
        nodes.parse_plan(1, 1, "   ")


def test_parse_plan_rejects_bad_json(fake_model):
    """模型返回非 JSON 时必须报错，不能拿半成品继续跑。"""
    fake_model.reply = "好的，我已经帮你分析完了。"
    with pytest.raises(RuntimeError):
        nodes.parse_plan(1, 1, "我想考研，目标计算机。", persist=False)


# ================================================================
# 四、规则匹配：阶段名与指标名由模板定，模型只能填解释
# ================================================================
def test_match_rule_rejects_model_invented_phases(fake_model, seeded_plan):
    """模型自创的阶段名必须被丢弃，阶段列表只来自规则库。"""
    fake_model.reply = json.dumps(
        {
            "阶段任务": [
                {"阶段": "我编的阶段X", "核心任务": "随便写"},
            ],
            "指标说明": [{"指标": "我编的指标", "为什么重要": "因为重要"}],
            "硬基线说明": "不可放宽",
        },
        ensure_ascii=False,
    )
    tpl = cx.load_template("考公")
    template_phases = [p["阶段"] for p in tpl["phases"]]

    out = nodes.match_rule(1, 1, 0, persist=False)
    got = [p["阶段"] for p in out["phases"]]
    # 阶段名必须全部来自模板，且模型编的那个不能出现
    assert got, "阶段列表不应为空"
    assert all(name in template_phases for name in got), f"出现了模板外的阶段：{got}"
    assert "我编的阶段X" not in got

    # 模型编的指标也不能混进来
    metric_names = {m["指标"] for m in out["metrics"]}
    assert "我编的指标" not in metric_names


# ================================================================
# 五、周监控：红黄绿由引擎判，模型只写摘要
# ================================================================
def test_weekly_review_summary_from_model_but_color_from_engine(fake_model, seeded_plan):
    """模型返回「全绿」，但引擎判定是红 → 最终 overall 必须是红。"""
    fake_model.reply = json.dumps(
        {
            "周报摘要": "本周完成度很高，继续保持。",
            "下周建议": [{"建议": "刷题", "量化目标": "300 题"}],
            "偏差说明": [],
        },
        ensure_ascii=False,
    )
    # 达标线 300，实际只给了 60 → 引擎必判红
    out = nodes.weekly_review(
        1, 1,
        self_report={"行测刷题量": 60},
        today=date(2026, 10, 26),
        persist=False,
    )
    assert out["overall"] in {cr.WEEK_RED, cr.WEEK_YELLOW}, (
        f"实际值远低于达标线，必须判红/黄，实际 {out['overall']}"
    )
    # 摘要来自模型
    assert out["summary"] == "本周完成度很高，继续保持。"
    # 建议最多 3 条
    assert len(out["advice"]) <= 3


def test_weekly_review_reports_unknown_when_no_data(fake_model, seeded_plan):
    """全缺数据 → overall=unknown，绝不冒充绿。"""
    fake_model.reply = json.dumps({"周报摘要": "", "下周建议": [], "偏差说明": []}, ensure_ascii=False)
    out = nodes.weekly_review(1, 1, self_report={}, today=date(2026, 10, 26), persist=False)
    assert out["overall"] == cr.WEEK_UNKNOWN, f"无数据必须 unknown，实际 {out['overall']}"


def test_weekly_review_truncates_advice_to_three(fake_model, seeded_plan):
    """模型给 5 条建议，落库只能 3 条（避免压垮学生）。"""
    fake_model.reply = json.dumps(
        {
            "周报摘要": "x",
            "下周建议": [{"建议": f"建议{i}", "量化目标": f"{i}次"} for i in range(5)],
            "偏差说明": [],
        },
        ensure_ascii=False,
    )
    out = nodes.weekly_review(
        1, 1, self_report={"行测刷题量": 300}, today=date(2026, 10, 26), persist=False
    )
    assert len(out["advice"]) == 3


# ================================================================
# 六、通知过滤：已截止的被代码剔除，模型看不到
# ================================================================
def test_notice_filter_never_shows_expired_to_model(fake_model, monkeypatch):
    """已截止通知不能出现在送给模型的 prompt 里。"""
    sample = [
        {"id": 1, "标题": "已过期的比赛", "截止时间": "2020-01-01", "摘要": "x"},
        {"id": 2, "标题": "未截止的比赛", "截止时间": "2099-12-31", "摘要": "y"},
    ]
    monkeypatch.setattr(cx, "fetch_notices", lambda tid, limit=60: sample)
    fake_model.reply = json.dumps(
        [{"标题": "未截止的比赛", "相关性": "high", "推送理由": "与考公相关"}],
        ensure_ascii=False,
    )
    # 需要有画像才能进 filter_notices
    monkeypatch.setattr(
        cx, "fetch_active_plan",
        lambda tid, sid: {"id": 1, "goal_type": "考公", "plan": {"目标类型": "考公", "软性指标": []}},
    )

    out = nodes.filter_notices(1, 1, today=date(2026, 10, 26), persist=False)
    assert "已过期的比赛" not in fake_model.last_user, "已截止通知不得进入模型上下文"
    assert "未截止的比赛" in fake_model.last_user
    assert out["candidates"] == 1
    assert out["matched"] == 1


def test_notice_filter_drops_model_invented_titles(fake_model, monkeypatch):
    """模型编出来的通知标题（不在候选池）必须被丢弃。"""
    monkeypatch.setattr(
        cx, "fetch_notices",
        lambda tid, limit=60: [{"id": 2, "标题": "真实通知", "截止时间": "2099-12-31"}],
    )
    monkeypatch.setattr(
        cx, "fetch_active_plan",
        lambda tid, sid: {"id": 1, "goal_type": "考公", "plan": {"目标类型": "考公", "软性指标": []}},
    )
    fake_model.reply = json.dumps(
        [
            {"标题": "模型编的通知", "相关性": "high", "推送理由": "编的"},
            {"标题": "真实通知", "相关性": "medium", "推送理由": "相关"},
        ],
        ensure_ascii=False,
    )
    out = nodes.filter_notices(1, 1, today=date(2026, 10, 26), persist=False)
    titles = [i["标题"] for i in out["items"]]
    assert "模型编的通知" not in titles
    assert "真实通知" in titles


# ================================================================
# 七、陪伴对话：系统记录越权必须被拦
# ================================================================
def test_coach_chat_blocks_goal_type_change(fake_model):
    """模型试图改目标类型 → 系统记录整条 rejected。"""
    fake_model.reply = (
        "我建议你把目标改成考研会更合适。\n"
        '【系统记录】{"状态变化": [{"目标类型": "考研"}]}'
    )
    out = nodes.coach_chat(1, 1, "我考公是不是没戏了？")
    assert out["system_record"]["ok"] is False
    assert out["system_record"]["accepted"] == {}
    assert "reply" in out and out["reply"]


def test_coach_chat_accepts_valid_todo(fake_model):
    """白名单内的正常待办应被接收。"""
    fake_model.reply = (
        "这周先把错题本补上。\n"
        '【系统记录】{"新增待办": ["整理行测错题本"], "需更新画像": false}'
    )
    out = nodes.coach_chat(1, 1, "下周该干嘛")
    assert out["system_record"]["ok"] is True
    assert out["system_record"]["accepted"]["新增待办"] == ["整理行测错题本"]


# ================================================================
# 八、零侵入核验：career 模块不得反向依赖
# ================================================================
def test_career_nodes_do_not_compute_numbers():
    """nodes.py 不得出现随机数/自行打分（防止有人顺手加"临时逻辑"）。"""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "agents" / "career" / "nodes.py").read_text(
        encoding="utf-8"
    )
    for banned in ("import random", "random.", "np.random", "hash("):
        assert banned not in src, f"nodes.py 出现 {banned}：数值必须确定性可复现"
