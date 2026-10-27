# engine/interview_probe.py
# 职责：真实面试的追问决策——回答过浅/漏考点时，从同族题库取一道更深的题追问。
# 铁律：纯函数、确定性；追问原文来自题库（可回溯），取不到返回 None，绝不编题。
# 说明：本模块只做「要不要追问 + 追问哪道题 + 怎么把学生原话带进题干」，不改评分。

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from engine.question_bank import BANK_DIR, retrieve_for_job

# 追问阈值：分数低于此值、或回答过短、或考点覆盖率不足时触发
PROBE_SCORE_BELOW = 70.0
PROBE_ANSWER_MIN = 80
PROBE_COVERAGE_BELOW = 0.5
# 追问优先在同题型里找；同题型没有新题时，按这个顺序换题型深挖
_PROBE_ORDER: tuple[str, ...] = ("project", "scenario", "major")


def _coverage(item: Mapping[str, Any]) -> float:
    """考点覆盖率：命中 / (命中 + 漏掉)；没有考点时按 1.0（不因无考点而追问）。"""
    hits = list(item.get("keyword_hits") or [])
    missed = list(item.get("keyword_missed") or [])
    total = len(hits) + len(missed)
    return 1.0 if total == 0 else len(hits) / total


def should_probe(item: Mapping[str, Any] | None, answer: str | None,
                 qtype: str | None = None) -> bool:
    """是否值得追问：未答/反问环节不追问；答得浅或漏考点才追问。"""
    text = str(answer or "").strip()
    if item is None or not text:
        return False
    if qtype == "counter":
        return False
    if float(item.get("score") or 0) < PROBE_SCORE_BELOW:
        return True
    if len(text) < PROBE_ANSWER_MIN:
        return True
    return _coverage(item) < PROBE_COVERAGE_BELOW


def pick_probe(job: Mapping[str, Any] | None, qtype: str,
               used_ids: Sequence[str] = (),
               bank_dir: Path | str | None = None) -> dict[str, Any] | None:
    """从同题型题库取一道未用过的题；同题型没有则换题型；取不到返回 None。"""
    used = set(str(x) for x in used_ids)
    path = bank_dir if bank_dir is not None else BANK_DIR
    for target in (qtype, *[q for q in _PROBE_ORDER if q != qtype]):
        for hit in retrieve_for_job(job, target, k=5, bank_dir=path):
            if str(hit.get("id")) not in used:
                return hit
    return None


def _quote(text: str, limit: int = 30) -> str:
    """取学生原话片段作为追问锚点；太短就不引，避免生硬。"""
    clean = " ".join(str(text or "").split())
    return clean[:limit] if len(clean) >= 6 else ""


def build_probe_question(probe: Mapping[str, Any], answer: str | None) -> str:
    """题库原题 + 学生原话锚点；原题不改写，只在后面追加追问语境。"""
    raw = str(probe.get("question") or "").strip()
    quote = _quote(str(answer or ""))
    return f"{raw}（请结合你刚才提到的「{quote}」具体说明）" if quote else raw


def probe_plan(job: Mapping[str, Any] | None, qtype: str,
               item: Mapping[str, Any] | None, answer: str | None,
               used_ids: Sequence[str] = (),
               bank_dir: Path | str | None = None) -> dict[str, Any] | None:
    """追问计划：不需要追问/题库取不到 → None；否则返回可直接落库的结构。"""
    if not should_probe(item, answer, qtype):
        return None
    probe = pick_probe(job, qtype, used_ids=used_ids, bank_dir=bank_dir)
    if not probe:
        return None
    return {
        "question": build_probe_question(probe, answer),
        "question_raw": probe.get("question"),
        "qtype": probe.get("qtype") or qtype,
        "bank_id": probe.get("id"),
        "family": probe.get("family"),
        "source_name": probe.get("source_name"),
        "source_url": probe.get("source_url"),
        "engine_version": "probe-v1",
    }


def enabled() -> bool:
    """环境开关：真实演示可关掉追问（默认开）。"""
    return str(os.getenv("INTERVIEW_PROBE", "1")).strip().lower() not in ("0", "false", "off", "no")
