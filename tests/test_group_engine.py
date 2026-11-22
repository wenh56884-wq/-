# tests/test_group_engine.py
# 职责：无领导小组讨论引擎（engine/group.py）的契约测试。
# 说明：全部离线；speak 一律注入假实现，绝不触达真实模型 / 网络 / 数据库。

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from engine.group import (  # noqa: E402
    CANDIDATES,
    CANDIDATE_FALLBACK,
    CONVERGE_WORDS,
    GROUP_VERSION,
    TOPIC_UNIVERSAL,
    TOPIC_VOCAB,
    ai_turn,
    evaluate,
    make_topic,
    opening,
    student_turn,
)

_NAMES = {c["id"]: c["name"] for c in CANDIDATES}
_NAMES["student"] = "我"


def _state(keywords: list[str], turns: list[tuple[str, str]]) -> dict:
    """按契约形状造 state；turns = [(speaker, text)]，idx 从 1 开始。"""
    rows = [{"idx": i + 1, "speaker": s, "name": _NAMES.get(s, s), "text": t, "at": i}
            for i, (s, t) in enumerate(turns)]
    return {"version": GROUP_VERSION,
            "topic": {"title": "测试议题", "brief": "测试用", "keywords": keywords, "minutes": 12},
            "turns": rows,
            "student_turns": [r["idx"] for r in rows if r["speaker"] == "student"],
            "elapsed_turns": len(rows)}


def _fake(text: str):
    """固定句 speak：同时记录收到的 prompt，便于验证「读到之前的全部发言」。"""
    seen: list[tuple[str, str]] = []

    def _speak(system: str, user: str) -> str:
        seen.append((system, user))
        return text

    _speak.seen = seen  # type: ignore[attr-defined]
    return _speak


def _boom(system: str, user: str) -> str:
    raise TimeoutError("模型超时")


# ---------------------------------------------------------------- make_topic
def test_make_topic_keywords_count_and_source():
    skills = ["Python", "MySQL", "数据可视化", "统计分析"]
    topic = make_topic("数据分析师", "互联网", skills)
    kws = topic["keywords"]
    assert 5 <= len(kws) <= 8
    assert len(set(kws)) == len(kws)
    assert topic["minutes"] == 12
    assert topic["title"] and topic["brief"]
    # 每个关键词必须来自 skills 或行业通用词，不许编造技术名词
    assert set(kws) <= set(skills) | set(TOPIC_VOCAB)
    assert {"Python", "MySQL"} <= set(kws)


def test_make_topic_without_skills_still_valid():
    topic = make_topic("", None, [])
    assert 5 <= len(topic["keywords"]) <= 8
    assert topic["keywords"][0] in TOPIC_UNIVERSAL
    # 十个技能也不许超过 8 个关键词
    many = make_topic("产品经理", "教育", [f"技能{i}" for i in range(10)])
    assert 5 <= len(many["keywords"]) <= 8
    assert set(many["keywords"]) <= {f"技能{i}" for i in range(10)} | set(TOPIC_VOCAB)
    # 同一输入必须得到同一议题（确定性）
    assert make_topic("后端开发", "互联网", ["Java"]) == make_topic("后端开发", "互联网", ["Java"])


# ---------------------------------------------------------------- opening
def test_opening_has_rules_and_ice_speech():
    topic = make_topic("后端开发", "互联网", ["Java", "MySQL"])
    op = opening(topic)
    blob = json.dumps(op, ensure_ascii=False)
    assert "12 分钟" in blob and "4 人" in blob and "一致结论" in blob
    first = op["first_turn"]
    assert first["speaker"] == "ice" and first["idx"] == 1
    assert topic["keywords"][0] in first["text"]
    assert len(op["rules"]) >= 3
    json.dumps(op, ensure_ascii=False)  # 可序列化


# ---------------------------------------------------------------- ai_turn
def test_ai_turn_appends_turn_and_keeps_input_immutable():
    state = _state(["成本", "交付"], [("student", "我觉得应该先控制成本。")])
    before = json.dumps(state, ensure_ascii=False, sort_keys=True)
    speak = _fake("林一说的框架我认，我先补一个成本口径。")
    res = ai_turn(state, "data", speak=speak)

    assert json.dumps(state, ensure_ascii=False, sort_keys=True) == before  # 入参未被修改
    assert res["state"] is not state
    assert len(res["state"]["turns"]) == len(state["turns"]) + 1
    assert res["turn"]["idx"] == 2 and res["turn"]["speaker"] == "data"
    assert res["turn"]["name"] == "赵敏"
    assert res["turn"]["text"] == "林一说的框架我认，我先补一个成本口径。"
    assert res["state"]["elapsed_turns"] == 2
    assert res["source"] == "llm"


def test_ai_turn_prompt_reads_all_prior_turns():
    state = _state(["成本", "交付", "风险"],
                   [("student", "我认为成本最要紧。"), ("spark", "我不同意，凭什么默认用户买账。")])
    speak = _fake("赵敏给你补个数字：同类项目两万上下。")
    ai_turn(state, "data", speak=speak)
    system, user = speak.seen[-1]

    assert "我认为成本最要紧" in user and "我不同意" in user      # 之前全部发言进 prompt
    assert "学生最新发言" in user and "我认为成本最要紧" in user
    assert "80~140" in system and "禁止重复" in system
    assert "数据派" in system and "赵敏" in system
    assert "本轮要求" in user


def test_ai_turn_unknown_candidate_raises():
    with pytest.raises(ValueError):
        ai_turn(_state([], []), "ghost")
    with pytest.raises(ValueError):
        ai_turn(_state([], []), "")


def test_ai_turn_speak_exception_falls_back():
    state = _state(["成本", "交付", "风险"], [("student", "我先说一句，成本要控。")])
    res = ai_turn(state, "ice", speak=_boom)
    assert res["source"] == "fallback"
    assert res["turn"]["text"] and "TimeoutError" in (res["error"] or "")
    assert len(res["state"]["turns"]) == 2
    assert "同学" in res["turn"]["text"]        # 降级句也会点名回应


def test_ai_turn_empty_reply_falls_back():
    state = _state(["成本", "交付", "风险"], [("student", "我先说一句，成本要控。")])
    for empty in ("", "   ", None, 123):
        res = ai_turn(state, "spark", speak=lambda s, u, _e=empty: _e)
        assert res["source"] == "fallback"
        assert res["turn"]["text"].strip()
        assert res["error"] == "empty_reply"


def test_ai_turn_fallback_rotates_by_spoken_count():
    state = _state(["成本", "交付", "风险"], [("student", "我先说一句。")])
    texts = []
    for _ in range(4):
        res = ai_turn(state, "ice", speak=_boom)
        texts.append(res["turn"]["text"])
        state = res["state"]                # 轮换按「该角色已发言次数」，必须把新 state 传回去
    assert len(CANDIDATE_FALLBACK["ice"]) == 3
    assert len(set(texts[:3])) == 3
    assert texts[3] == texts[0]             # 3 句取模轮换


def test_fallback_has_three_sentences_per_role():
    assert set(CANDIDATE_FALLBACK) == {"ice", "data", "spark"}
    for lines in CANDIDATE_FALLBACK.values():
        assert len(lines) == 3
        assert any("{peer}" in ln for ln in lines)   # 至少一句会点名回应，离线也有互动感


# ---------------------------------------------------------------- student_turn
def test_student_turn_records_and_rejects_empty():
    res = student_turn(_state(["成本"], [("ice", "先拆三个维度。")]), "  我补一个成本口径。  ")
    assert res["turn"]["speaker"] == "student" and res["turn"]["text"] == "我补一个成本口径。"
    assert res["state"]["student_turns"] == [2]
    with pytest.raises(ValueError):
        student_turn(_state([], []), "   ")


# ---------------------------------------------------------------- evaluate
def test_evaluate_single_sentence_is_silent_or_follower():
    state = _state(["成本", "交付", "风险"],
                   [("ice", "我建议先拆三个维度，优先级、成本、落地难度，逐条过一遍，最后收敛。"),
                    ("data", "同类项目三个人两周，成本两万上下，得先把口径说清楚。"),
                    ("student", "我觉得应该先做核心功能。")])
    out = evaluate(state)
    assert out["role"]["id"] in {"silent", "follower"}
    assert out["role"]["label"] in {"沉默者", "跟随者"}
    assert 0 < out["metrics"]["talk_ratio"] < 0.3
    assert out["metrics"]["new_points"] == 0


def test_evaluate_many_statements_with_two_new_points_is_leader():
    state = _state(["成本", "交付", "风险", "优先级", "用户需求"],
                   [("ice", "先把议题拆成几个维度。"),
                    ("student", "我认为先控制成本，两万以内能做完。"),
                    ("student", "成本这块我算过，三个人两周正好。"),
                    ("student", "交付上建议分三步走，先做能验证的部分。")])
    out = evaluate(state)
    assert out["metrics"]["new_points"] >= 2
    assert out["metrics"]["talk_ratio"] >= 0.3
    assert out["role"]["id"] == "leader"
    assert out["role"]["label"] == "推动者"
    assert out["role"]["reason"]


def test_evaluate_new_points_excludes_keywords_ai_said_first():
    # 「成本」被 data 先说 → 不计新观点；「交付」学生先说 → 计 1 个
    state = _state(["成本", "交付"],
                   [("data", "成本我先给个数：两万上下。"),
                    ("student", "成本这块我同意，交付也得看节奏。")])
    out = evaluate(state)
    assert out["metrics"]["new_points"] == 1


def test_evaluate_counts_converge_marks():
    state = _state(["成本", "交付"],
                   [("student", "综上，我建议我们统一到方案 A，分三步落地。")])
    out = evaluate(state)
    assert out["metrics"]["converge_marks"] >= 1
    assert all(w in CONVERGE_WORDS for w in CONVERGE_WORDS)   # 词表按契约原样


def test_evaluate_scores_are_clamped_ints_and_deterministic():
    state = _state(["成本", "交付", "风险"],
                   [("student", "综上，我建议我们先控成本，再谈交付，最后统一口径，风险我来兜。"),
                    ("ice", "时间不多了，先收敛。")])
    out = evaluate(state)
    s = out["scores"]
    assert set(s) == {"contribution", "collaboration", "structure", "overall"}
    for k, v in s.items():
        assert isinstance(v, int) and 0 <= v <= 100, k
    # 同输入必须同输出（evaluate 不许有随机 / 时钟依赖）
    assert evaluate(state)["scores"] == s
    # overall = .35 贡献 + .25 协作 + .25 结构 + .15 表达；表达不对外暴露，
    # 因此 overall 必须落在「已知三项加权和 ~ 再加满表达 15 分」之间
    base = 0.35 * s["contribution"] + 0.25 * s["collaboration"] + 0.25 * s["structure"]
    assert base - 0.5 <= s["overall"] <= base + 15 + 0.5


def test_evaluate_quotes_are_verbatim_from_student_text():
    said = "我认为先控制成本，两万以内能做完。交付上建议分三步走，最后统一口径。"
    state = _state(["成本", "交付", "风险"], [("student", said)])
    out = evaluate(state)
    assert 2 <= len(out["highlights"]) <= 3
    assert 2 <= len(out["improvements"]) <= 3
    quoted = []
    for line in out["highlights"] + out["improvements"]:
        quoted += line.split("「")[1:]
    for chunk in quoted:
        frag = chunk.split("」")[0]
        assert frag in said, frag            # 逐字来自 state，不编引文
    assert out["next_drill"] and len(out["next_drill"]) <= 60


def test_evaluate_empty_state_does_not_crash():
    out = evaluate({})
    assert out["role"]["id"] == "silent"
    assert out["metrics"]["chars"] == 0 and out["metrics"]["talk_ratio"] == 0.0
    assert out["scores"] == {"contribution": 0, "collaboration": 0,
                             "structure": 0, "overall": 0}
    assert out["transcript_digest"] == []
    assert len(out["highlights"]) >= 1 and len(out["improvements"]) >= 1
    json.dumps(out, ensure_ascii=False)


def test_evaluate_without_student_turns_is_silent():
    out = evaluate(_state(["成本"], [("ice", "我先拆三个维度。"), ("data", "给个数字。")]))
    assert out["role"]["id"] == "silent"
    assert out["metrics"]["first_speak_position"] == 1.0
    assert all("「" not in line for line in out["improvements"])   # 没发言就不编引文


# ---------------------------------------------------------------- 序列化约束
def test_state_is_json_serializable_and_free_of_callables():
    topic = make_topic("运营专员", "互联网", ["活动策划", "数据分析"])
    state = _state(topic["keywords"], [("ice", opening(topic)["first_turn"]["text"])])
    state = ai_turn(state, "spark", speak=_fake("我不同意林一的框架，缺了风险口径。"))["state"]
    state = student_turn(state, "风险我来兜，先做一版验证。")["state"]
    blob = json.dumps(state, ensure_ascii=False)
    back = json.loads(blob)
    assert back["elapsed_turns"] == 3
    assert [t["idx"] for t in back["turns"]] == [1, 2, 3]
    assert all(not callable(v) for v in state.values())


def test_evaluate_output_is_json_serializable():
    topic = make_topic("财务专员", "金融", ["成本核算", "预算"])
    state = _state(topic["keywords"], [("student", "综上，我建议我们统一口径。")])
    json.dumps(evaluate(state), ensure_ascii=False)
