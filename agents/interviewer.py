# agents/interviewer.py
# 职责：模拟面试官 Agent——LangGraph 状态机（per-turn）：
#   grade → verify（防虚构：引文必须逐字在原文）→ (retry ≤ MAX_RETRY | fallback)
# 铁律：分数来自 engine.interview（引擎定数），LLM 只组织点评语言；
#       点评必须含「引文」且逐字可回溯，否则驳回重写，仍不过走模板降级并写审计。

from __future__ import annotations

import os
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from agents import llm as llm_client
from engine.interview import (
    INTERVIEW_ENGINE_VERSION,
    QUESTION_TYPES,
    fallback_comment,
    verify_comment,
)

# 与主图一致的版本约定
MAX_RETRY = int(os.getenv("INTERVIEW_MAX_RETRY", "2"))
COMMENT_VERSION = "comment-v1"
COMMENT_FALLBACK_VERSION = "comment-fallback-v1"


class TurnState(TypedDict, total=False):
    question: str
    qtype: str
    answer: str
    item: dict[str, Any]          # engine.interview.score_answer 的结果（None=未答）
    evidence: list[str]           # 简历原文片段 + JD 关键词（防虚构比对源）
    comment: str
    comment_version: str
    quotes_ok: bool
    bad_quotes: list[str]
    attempts: int
    feedback: str


def _llm_enabled() -> bool:
    return str(os.getenv("AGENT_LLM_DRAFT", "1")).strip().lower() not in ("0", "false", "off", "no")


# ----------------------------------------------------------------
# 节点 1：生成点评草稿（LLM 组织语言；分数与要点由 state 注入，模型无算分权）
# ----------------------------------------------------------------
def _grade(state: TurnState) -> dict[str, Any]:
    item = state.get("item")
    answer = state.get("answer")
    if item is None or not (answer or "").strip():
        return {"comment": "本题未作答，不计分。建议下一题务必作答，跳题会影响整体评价。",
                "comment_version": COMMENT_FALLBACK_VERSION, "quotes_ok": True, "bad_quotes": [],
                "attempts": 0}
    if not _llm_enabled():
        return {"comment": fallback_comment(state["question"], item, answer),
                "comment_version": COMMENT_FALLBACK_VERSION, "quotes_ok": True, "bad_quotes": [],
                "attempts": 0}
    label = QUESTION_TYPES.get(state["qtype"], {}).get("label", state["qtype"])
    hits = "、".join(list(item.get("keyword_hits") or [])[:4]) or "（无）"
    missed = "、".join(list(item.get("keyword_missed") or [])[:4]) or "（无）"
    system = (
        "你是模拟面试官，负责逐题点评。规则："
        "1) 禁止编造学生没有说过的内容，引用学生回答或简历时必须用「」原样摘抄，且逐字来自给定材料；"
        "2) 不得自行计算或修改分数，分数以给定的为准；"
        "3) 点评 80-160 字：先引「原文」肯定答到的点，再指漏掉的点，最后给一条具体改进动作。"
    )
    user = (
        f"题型：{label}\n问题：{state['question']}\n学生回答：{answer}\n"
        f"命中要点：{hits}\n漏掉要点：{missed}\n引擎评分：{item['score']}\n"
        f"简历/JD 证据（引文只能出自回答或这些证据）：\n" + "\n".join(f"- {t[:200]}" for t in state.get("evidence") or [])
    )
    if state.get("feedback"):
        # 驳回原因必须回传给模型，否则重试只是原样再生成一次
        user += f"\n上次点评未通过：{state['feedback']}\n请只用上述材料中逐字存在的原文作「引文」，重新点评。"
    try:
        text = llm_client.generate_reply("student", system_prompt=system, user_prompt=user,
                                         tag="interview.comment")
        if not text or not str(text).strip():
            raise RuntimeError("LLM 未返回内容")
        return {"comment": str(text).strip(), "comment_version": COMMENT_VERSION,
                "quotes_ok": False, "bad_quotes": [], "attempts": 0}
    except Exception:
        # LLM 不可用：直接降级（可回溯、可演示），不让一次网络抖动打断面试
        return {"comment": fallback_comment(state["question"], item, answer),
                "comment_version": COMMENT_FALLBACK_VERSION, "quotes_ok": True,
                "bad_quotes": [], "attempts": MAX_RETRY}


# ----------------------------------------------------------------
# 节点 2：防虚构校验（引擎逐字比对，模型说了不算）
# ----------------------------------------------------------------
def _verify(state: TurnState) -> dict[str, Any]:
    if state.get("comment_version") == COMMENT_FALLBACK_VERSION:
        return {"quotes_ok": True, "bad_quotes": []}
    ok, bad = verify_comment(state.get("comment") or "", state.get("answer"),
                             state.get("evidence") or [])
    return {"quotes_ok": ok, "bad_quotes": bad}


def _decide(state: TurnState) -> str:
    if state.get("quotes_ok"):
        return "ok"
    if int(state.get("attempts") or 0) >= MAX_RETRY:
        return "fallback"
    return "retry"


def _retry(state: TurnState) -> dict[str, Any]:
    feedback = "上一版点评被驳回：存在不是原文的「引文」：" + "、".join(state.get("bad_quotes") or [])
    merged = dict(state)
    merged["attempts"] = int(state.get("attempts") or 0) + 1
    merged["feedback"] = feedback
    out = _grade(merged)
    out["attempts"] = merged["attempts"]
    out["feedback"] = feedback
    return out


def _fallback(state: TurnState) -> dict[str, Any]:
    return {"comment": fallback_comment(state["question"], state.get("item"), state.get("answer")),
            "comment_version": COMMENT_FALLBACK_VERSION, "quotes_ok": True, "bad_quotes": []}


def build_turn_graph():
    g = StateGraph(TurnState)
    g.add_node("grade", _grade)
    g.add_node("verify", _verify)
    g.add_node("retry", _retry)
    g.add_node("fallback", _fallback)
    g.set_entry_point("grade")
    g.add_edge("grade", "verify")
    g.add_conditional_edges("verify", _decide, {"ok": END, "retry": "retry", "fallback": "fallback"})
    g.add_edge("retry", "verify")
    g.add_edge("fallback", END)
    return g.compile()


_TURN = None


def run_turn(question: str, qtype: str, answer: str | None,
             item: dict[str, Any] | None, evidence: list[str]) -> dict[str, Any]:
    """单轮点评：grade → verify → retry/fallback。返回点评与版本。"""
    global _TURN
    if _TURN is None:
        _TURN = build_turn_graph()
    out = _TURN.invoke({"question": question, "qtype": qtype, "answer": answer or "",
                        "item": item, "evidence": evidence})
    return {"comment": out["comment"], "comment_version": out["comment_version"],
            "quotes_ok": bool(out.get("quotes_ok")), "bad_quotes": list(out.get("bad_quotes") or []),
            "attempts": int(out.get("attempts") or 0)}


# ----------------------------------------------------------------
# 报告生成（数字全部由引擎先算好拼进 prompt，模型只组织语言）
# ----------------------------------------------------------------
def render_report(facts: dict[str, Any]) -> str:
    """facts 必须已含总分/各题得分/差距清单/强项；interview-v2 起追加核心问题与改进计划。
    模型不可改动任何数字——这里在 prompt 里给出原文数字，产出后不做二次算术。"""
    lines = [
        f"模拟面试报告（引擎 {INTERVIEW_ENGINE_VERSION}）",
        f"总分：{facts['total']}（已答 {facts['answered']} 题，跳过 {facts['skipped']} 题）",
        "",
        "各题得分：",
    ]
    for it in facts["items"]:
        brief = it.get("brief") or (it.get("answer") or "")[:60] or "未作答"
        lines.append(f"- 第{it['round']}题[{it['label']}] {it['score'] if it['score'] is not None else '未作答'}：{brief}")
    lines.append("")
    lines.append("强项：" + ("、".join(facts["strengths"]) if facts["strengths"] else "暂无明显强项"))
    if facts.get("core_problems"):
        lines.append("")
        lines.append("核心问题（按严重度）：")
        for i, p in enumerate(facts["core_problems"], start=1):
            lines.append(f"{i}. [{p['dimension']}/{p['severity']}] {p['problem']} → {p['action']}")
    if facts.get("improvement_plan"):
        lines.append("")
        lines.append("改进计划：")
        for step in facts["improvement_plan"]:
            lines.append(f"- {step['when']}｜{step['focus']}：{step['action']}")
    lines.append("")
    lines.append("差距与下一步（按优先级）：")
    for i, g in enumerate(facts["gaps"], start=1):
        lines.append(f"{i}. [{g['dimension']}] {g['gap']} → {g['action']}")
    return "\n".join(lines)
