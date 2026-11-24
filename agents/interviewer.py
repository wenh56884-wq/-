# agents/interviewer.py
# 职责：模拟面试官 Agent——LangGraph 状态机（per-turn）：
#   grade → verify（防虚构：引文必须逐字在原文）→ (retry ≤ MAX_RETRY | fallback)
# 铁律：分数来自 engine.interview（引擎定数），LLM 只组织点评语言；
#       点评必须含「引文」且逐字可回溯，否则驳回重写，仍不过走模板降级并写审计。

from __future__ import annotations

import json
import os
import re
from typing import Any, Sequence, TypedDict

from langgraph.graph import END, StateGraph

from agents import llm as llm_client
from engine.interview import (
    INTERVIEW_ENGINE_VERSION,
    QUESTION_TYPES,
    fallback_comment,
    normalize_mode,
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
    history: list[dict[str, Any]] | None
    tone: str | None


def _llm_enabled() -> bool:
    return str(os.getenv("AGENT_LLM_DRAFT", "1")).strip().lower() not in ("0", "false", "off", "no")


# 整句切分：保留句末标点，候选必须能整句被「」包住后仍逐字命中原文
_SENTENCE_RE = re.compile(r"[^。！？；!?;\n]+[。！？；!?;]?")


def _quote_candidates(answer: str | None, evidence: Sequence[str]) -> list[str]:
    """从学生原话切出 3-5 个整句候选，并用 verify_comment 同一套逐字规则预校验。

    只做摘抄、不改写；校验不过的句子不进清单。清单只是给模型的「可选引文」，
    最终点评仍要过 _verify 的逐字校验，不存在放宽。
    """
    out: list[str] = []
    for segment in _SENTENCE_RE.findall(str(answer or "")):
        candidate = segment.strip()
        if not (6 <= len(candidate) <= 120) or candidate in out:
            continue
        ok, _bad = verify_comment(f"「{candidate}」", answer, evidence)
        if ok:
            out.append(candidate)
        if len(out) >= 5:
            break
    return out


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
    # 语气只写在 system prompt 里，tone 为 None/standard/未知时一字不追加；
    # 引文逐字规则与分数口径始终不变。
    mode = normalize_mode(state.get("tone"))
    if mode == "easy":
        system += (" 轻松模式：先肯定学生答到的点，再给一条具体建议；"
                   "禁止使用否定性定性词（如「很差」「不行」「失败」）。")
    elif mode == "stress":
        system += (" 压力模式：直接指出回答中的问题与缺口，但只评价回答内容，"
                   "不得出现人身评价；引文逐字规则不变。")
    user = (
        f"题型：{label}\n问题：{state['question']}\n学生回答：{answer}\n"
        f"命中要点：{hits}\n漏掉要点：{missed}\n引擎评分：{item['score']}\n"
        f"简历/JD 证据（引文只能出自回答或这些证据）：\n" + "\n".join(f"- {t[:200]}" for t in state.get("evidence") or [])
    )
    # 本场前情：参数为 None / 空时完全不追加，保持原有 prompt 一字不变
    history = list(state.get("history") or [])[-2:]
    if history:
        user += "\n本场前情（最多 2 轮，每轮回答截断 120 字）："
        for idx, turn in enumerate(history, start=1):
            user += (f"\n第{idx}轮 问：{str(turn.get('q') or '')}"
                     f"\n答：{str(turn.get('a') or '')[:120]}")

    if state.get("feedback"):
        # 驳回原因必须回传给模型，否则重试只是原样再生成一次
        user += f"\n上次点评未通过：{state['feedback']}\n请只用上述材料中逐字存在的原文作「引文」，重新点评。"
        candidates = _quote_candidates(state.get("answer"), state.get("evidence") or [])
        if candidates:
            # 清单里的每条都已用 verify_comment 逐字预校验；引导模型从中选，
            # 但返回内容仍要照常过 _verify，校验规则本身一律不改。
            user += ("\n可选引文清单（均为你原话中的整句，已逐字校验；"
                     "只能从中原样摘抄，禁止改写或另造引文）：\n")
            user += "\n".join(f"- {c}" for c in candidates)
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
             item: dict[str, Any] | None, evidence: list[str],
             history: list[dict] | None = None,
             tone: str | None = None) -> dict[str, Any]:
    """单轮点评：grade → verify → retry/fallback。history/tone 缺省时行为不变。"""
    global _TURN
    if _TURN is None:
        _TURN = build_turn_graph()
    out = _TURN.invoke({"question": question, "qtype": qtype, "answer": answer or "",
                        "item": item, "evidence": evidence, "history": history,
                        "tone": tone})
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


def _report_numbers(facts: dict[str, Any]) -> list[str]:
    """改写后必须逐字保留的引擎数字（总分/题数/各题得分）。"""
    values: list[str] = []
    for key in ("total", "answered", "skipped"):
        if facts.get(key) is not None:
            values.append(str(facts[key]))
    for item in facts.get("items") or []:
        if item.get("score") is not None:
            values.append(str(item["score"]))
    return values


def render_report_llm(facts: dict[str, Any]) -> str:
    """把模板报告改写成有温度的叙述；数字与结论原样保留，异常一律回退模板。"""
    template = render_report(facts)
    if not _llm_enabled():
        return template
    system = (
        "你是模拟面试报告撰写助手。只能重写叙述语气，不得改动任何事实："
        "1) 总分、各题得分、已答/跳过题数等所有数字必须逐字保留，禁止重新计算或改写；"
        "2) 强项、核心问题、改进计划、差距与行动等结论文字必须逐字保留；"
        "3) 条目顺序与数量不得变化；4) 只调整连接词与措辞，让语气更自然、有温度。"
    )
    user = (
        "【引擎事实（数字与结构，逐字为准）】\n"
        + json.dumps(facts, ensure_ascii=False, default=str)
        + "\n\n【模板报告（数字与结论必须原样出现在你的改写中）】\n" + template
    )
    try:
        text = llm_client.generate_reply("student", system_prompt=system,
                                         user_prompt=user, tag="interview.report")
        if not text or not str(text).strip():
            raise RuntimeError("LLM 未返回内容")
        result = str(text).strip()
        # 数字丢失宁可回退模板，绝不交付一份数字被改写的报告
        if any(number not in result for number in _report_numbers(facts)):
            raise RuntimeError("改写稿丢失了引擎数字")
        return result
    except Exception:
        return render_report(facts)
