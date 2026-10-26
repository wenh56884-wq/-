# engine/metrics.py
# 职责：考核指标纯函数（预警二分类、Critic 聚合、延迟分位数、推荐日志汇总）
# 依赖：仅标准库；不连库、不调模型
# 说明：指标口径固定在本模块，脚本只负责取数；同输入必得同输出

from __future__ import annotations

import json
import math
from typing import Any, Iterable, Mapping, Sequence

# 预警阳性口径：红/橙/黄均算“系统发出预警”；unknown 不算阳性（数据不足≠风险）
WARNING_POSITIVE_LEVELS: tuple[str, ...] = ("red", "orange", "yellow")


def _as_bool(value: Any) -> bool:
    """把 0/1、"0"/"1"、True/False 统一成 bool；无法识别按 False。"""
    if isinstance(value, bool):
        return value
    try:
        return int(value) == 1
    except (TypeError, ValueError):
        return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _safe_rate(numerator: int, denominator: int) -> float | None:
    """比率；分母为 0 返回 None，不拿 0 冒充。"""
    return round(numerator / denominator, 4) if denominator else None


def classification_metrics(
    y_true: Mapping[str, Any],
    y_pred: Mapping[str, Any],
    *,
    positive_levels: Sequence[str] = WARNING_POSITIVE_LEVELS,
) -> dict[str, Any]:
    """预警二分类指标。

    y_true: student_no -> 真实是否风险（0/1）
    y_pred: student_no -> 预警等级（red/orange/yellow/none/unknown）
    positive_levels: 哪些等级算“预警阳性”；默认红/橙/黄全预警，
                     传 ("red","orange") 可只看危机口径。
    缺失预测（无成绩/未评估）按“未预警”处理，但单独给出 coverage。
    """
    positive = {str(level) for level in positive_levels}
    tp = fp = tn = fn = 0
    matched = 0
    for student_no, truth in y_true.items():
        actual_positive = _as_bool(truth)
        if student_no in y_pred:
            matched += 1
        predicted = str(y_pred.get(student_no) or "unknown") in positive
        if actual_positive and predicted:
            tp += 1
        elif actual_positive and not predicted:
            fn += 1
        elif not actual_positive and predicted:
            fp += 1
        else:
            tn += 1

    total = tp + fp + tn + fn
    precision = _safe_rate(tp, tp + fp)
    recall = _safe_rate(tp, tp + fn)
    f1 = None
    if precision is not None and recall is not None and (precision + recall) > 0:
        f1 = round(2 * precision * recall / (precision + recall), 4)
    return {
        "sample": total,
        "matched": matched,
        "coverage": _safe_rate(matched, total),
        "positive_levels": sorted(positive),
        "actual_positive": tp + fn,
        "predicted_positive": tp + fp,
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "accuracy": _safe_rate(tp + tn, total),
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def level_distribution(levels: Iterable[Any]) -> dict[str, int]:
    """统计预警等级分布；未知等级归 unknown。"""
    known = {"red", "orange", "yellow", "none", "unknown"}
    out = {key: 0 for key in ("red", "orange", "yellow", "none", "unknown")}
    for value in levels:
        key = str(value or "unknown")
        out[key if key in known else "unknown"] += 1
    return out


def percentile(values: Sequence[Any], p: float) -> float | None:
    """最近秩分位数（nearest-rank），p 取 0~100；空序列返回 None。"""
    if not 0 <= float(p) <= 100:
        raise ValueError("p 必须在 0~100 之间")
    data = sorted(float(v) for v in values if v is not None)
    if not data:
        return None
    index = max(0, min(len(data) - 1, math.ceil(float(p) / 100 * len(data)) - 1))
    return round(data[index], 2)


def summarize_latency(values: Iterable[Any]) -> dict[str, Any]:
    """延迟汇总：count / avg / p50 / p95 / max（毫秒）。"""
    data = [float(v) for v in values if v is not None]
    if not data:
        return {"count": 0, "avg_ms": None, "p50_ms": None, "p95_ms": None, "max_ms": None}
    return {
        "count": len(data),
        "avg_ms": round(sum(data) / len(data), 2),
        "p50_ms": percentile(data, 50),
        "p95_ms": percentile(data, 95),
        "max_ms": round(max(data), 2),
    }


def _json_list(value: Any) -> list[Any]:
    """hit_items/gap_items 可能是 list 或 JSON 字符串；解析失败按空列表。"""
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except ValueError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def summarize_critic(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Critic 审核汇总：通过率、含不一致/模糊表述的行占比。"""
    total = len(rows)
    passed = sum(1 for row in rows if bool(row.get("passed")))
    mismatch_rows = sum(
        1 for row in rows
        if row.get("mismatches") or row.get("fuzzy")
    )
    fuzzy_rows = sum(1 for row in rows if row.get("fuzzy"))
    first_attempts = [row for row in rows if int(row.get("attempt") or 0) == 1]
    first_passed = sum(1 for row in first_attempts if bool(row.get("passed")))
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": _safe_rate(passed, total),
        "first_attempts": len(first_attempts),
        "first_passed": first_passed,
        "first_pass_rate": _safe_rate(first_passed, len(first_attempts)),
        "mismatch_rows": mismatch_rows,
        "fuzzy_rows": fuzzy_rows,
        "hallucination_rate": _safe_rate(mismatch_rows, total),
    }


def summarize_recommend(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """推荐日志汇总：覆盖学生数、均分、协同过滤覆盖率、平均命中/缺口项。"""
    total = len(rows)
    students = {str(row.get("student_no") or "") for row in rows if row.get("student_no")}
    scores = [float(row["final_score"]) for row in rows if row.get("final_score") is not None]
    cf_present = sum(1 for row in rows if row.get("cf_score") is not None)
    hit_total = sum(len(_json_list(row.get("hit_items"))) for row in rows)
    gap_total = sum(len(_json_list(row.get("gap_items"))) for row in rows)
    return {
        "total": total,
        "students": len(students),
        "avg_final_score": round(sum(scores) / len(scores), 4) if scores else None,
        "cf_present": cf_present,
        "cf_coverage": _safe_rate(cf_present, total),
        "avg_hit_items": round(hit_total / total, 2) if total else None,
        "avg_gap_items": round(gap_total / total, 2) if total else None,
    }


def summarize_chat(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """对话审计汇总：降级率、平均尝试次数。"""
    total = len(rows)
    degraded = sum(1 for row in rows if bool(row.get("degraded")))
    attempts = [int(row.get("attempts") or 0) for row in rows]
    return {
        "total": total,
        "degraded": degraded,
        "degraded_rate": _safe_rate(degraded, total),
        "avg_attempts": round(sum(attempts) / total, 2) if total else None,
    }
