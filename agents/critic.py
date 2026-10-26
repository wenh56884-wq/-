# agents/critic.py
# 职责：数值一致性审核守门——规则抽取 + 与引擎原始结果逐条比对
# 依赖：标准库 re / datetime / decimal；agents.tools.write_audit（审计落库复用工具层实现）
# 说明：**不是**让大模型自我检查；容差 1e-6，百分比与小数互相兼容；
#       出现「约/大概/估计 + 数字」直接判不通过，宁可降级也不放过。

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Iterable, Mapping, Sequence

CRITIC_VERSION = "critic-v1"
# 允许的重试次数（草稿重写），超限即降级
MAX_RETRY = 2
# 浮点比较容差
TOLERANCE = 1e-6

# 模糊词：与数值同时出现即判不通过
FUZZY_WORDS: tuple[str, ...] = ("约", "大概", "估计", "大约", "差不多", "似乎", "左右")

# 单位识别（数字后面紧跟的第一个单位符号/字）
_UNIT_TOKENS: tuple[tuple[str, str], ...] = (
    ("%", "percent"),
    ("分", "score"),
    ("分", "score"),
    ("门", "course"),
    ("人", "person"),
    ("次", "count"),
    ("条", "count"),
    ("名", "rank"),
    ("篇", "count"),
    ("学期", "term"),
    ("版", "version"),
)

_number_re = re.compile(r"(?<![A-Za-z0-9._\-])-?\d+(?:\.\d+)?")
_term_token_re = re.compile(r"\d{4}[-年/]\d{1,4}(-\d)?")
_version_token_re = re.compile(r"[vV]?\d+\.\d+\.\d+")
_digits_re = re.compile(r"\d")


@dataclass(frozen=True)
class Claim:
    """从文本里抽出的一个数值论断。"""

    raw: str
    value: float
    unit: str
    span: tuple[int, int] = (0, 0)


@dataclass
class Verdict:
    """审核结论。passed=False 时 mismatches 给出逐条原因。"""

    passed: bool
    claims: list[Claim] = field(default_factory=list)
    mismatches: list[str] = field(default_factory=list)
    fuzzy: list[str] = field(default_factory=list)
    reason: str = ""

    def feedback(self) -> str:
        """给草稿重写环节看的提示：错在哪、允许用哪些数。"""
        if self.passed:
            return ""
        lines = ["草稿存在以下问题，必须逐条改正："]
        lines += [f"- {m}" for m in self.mismatches]
        lines += [f"- {f}" for f in self.fuzzy]
        lines.append("要求：所有数值必须原样引用工具返回结果，禁止估算与四舍五入改写。")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "claims": [{"raw": c.raw, "value": c.value, "unit": c.unit}
                       for c in self.claims],
            "mismatches": list(self.mismatches),
            "fuzzy": list(self.fuzzy),
            "reason": self.reason,
        }


def _mask_ids(text: str) -> str:
    """先把学期号/版本号/学号这类「非论断数字」抹掉，避免被当成数值断言。"""
    masked = _term_token_re.sub(" <TERM> ", str(text or ""))
    masked = _version_token_re.sub(" <VER> ", masked)
    return masked


def _unit_after(text: str, end: int) -> str:
    tail = text[end:end + 6]
    for token, unit in _UNIT_TOKENS:
        if tail.startswith(token) or tail.lstrip().startswith(token):
            return unit
    head = text[max(0, end - 8):end]
    if head.endswith("第"):
        return "rank"
    return ""


def extract_numbers(text: str) -> list[Claim]:
    """抽取全部数值论断：返回原始值 + 单位上下文（"71%"→0.71 且保留 71 参与匹配）。"""
    masked = _mask_ids(text)
    claims: list[Claim] = []
    for match in _number_re.finditer(masked):
        raw = match.group(0)
        value = float(raw)
        unit = _unit_after(masked, match.end())
        if unit in ("term", "version"):
            continue  # 学期号 / 版本号不是数值论断
        claims.append(Claim(raw=raw, value=value, unit=unit,
                            span=(match.start(), match.end())))
    return claims


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    return None


def build_ground_truth(tool_result: Any) -> list[float]:
    """收集所有可核对数值（含 reasons 句子里的数字），形成白名单。"""
    values: list[float] = []

    def walk(node: Any) -> None:
        number = _to_float(node)
        if number is not None:
            values.append(number)
            return
        # 字符串叶子里的数字同样要收：reason 归因文案是引擎产物
        # （如 ["本学期挂科6门"] 这种 list[str] 里的 6），漏收会把合法直引判成编造
        if isinstance(node, (str, bytes)):
            for claim in extract_numbers(str(node)):
                values.append(claim.value)
            return
        if isinstance(node, Mapping):
            for key, value in node.items():
                if isinstance(value, (str, bytes)):
                    for claim in extract_numbers(str(value)):
                        values.append(claim.value)
                else:
                    walk(value)
        elif isinstance(node, (list, tuple, set)):
            for item in node:
                walk(item)

    walk(tool_result)

    # 百分比 ↔ 小数互相兼容：0.71 与 71 都算命中；同时保留 100 倍的安全区
    expanded: list[float] = []
    for value in values:
        expanded.append(value)
        if -1.001 <= value <= 1.001:
            expanded.append(round(value * 100, 6))
        elif 0.0 <= value <= 100.0:
            expanded.append(round(value / 100, 6))
    return expanded


def _nearest(candidates: Sequence[float], value: float, top: int = 3) -> list[float]:
    ordered = sorted(set(candidates), key=lambda c: abs(c - value))
    return [round(c, 4) for c in ordered[:top]]


def _is_fuzzy(text: str, claim: Claim) -> str | None:
    """数字前后几个字里出现模糊词 → 返回原因串。"""
    start, _end = claim.span
    window = str(text or "")[max(0, start - 8):start]
    for word in FUZZY_WORDS:
        if word in window:
            return f"出现模糊表述「{word}」+ 数值「{claim.raw}」，不确定性话术一律判不通过"
    return None


def verify(draft: str, tool_result: Any, *, tolerance: float = TOLERANCE) -> Verdict:
    """把草稿里的每个数值论断与工具结果白名单逐条比对。"""
    claims = extract_numbers(draft)
    ground = build_ground_truth(tool_result)
    mismatches: list[str] = []
    fuzzy: list[str] = []

    for claim in claims:
        reason = _is_fuzzy(str(draft), claim)
        if reason:
            fuzzy.append(reason)
            continue
        if not any(abs(claim.value - allowed) <= tolerance for allowed in ground):
            near = _nearest(ground, claim.value)
            mismatches.append(
                f"数值「{claim.raw}」不在工具返回结果中"
                f"（最接近的允许值：{near if near else '无'}）"
            )

    passed = not mismatches and not fuzzy
    return Verdict(
        passed=passed,
        claims=claims,
        mismatches=mismatches,
        fuzzy=fuzzy,
        reason="" if passed else "数值未通过一致性核对",
    )


def render_fallback(tool_result: Any) -> str:
    """降级模板：只描述结论方向，**不含任何阿拉伯数字**。

    超限（重试仍错）时用它兜底，宁可少说也不给错数。
    """
    lines = ["已为你查询到结果，本回答不转述任何具体数值，请以列表数据为准："]
    if isinstance(tool_result, Mapping):
        if "items" in tool_result:
            lines.append("- 预警名单已生成，可按红/橙/黄/数据不足等档位筛选查看。")
        if "gaps" in tool_result:
            lines.append("- 班级能力与目标岗位存在差距，差距明细请查看列表。")
        if "dimensions" in tool_result:
            lines.append("- 该生四维画像已生成，标签与分数请查看画像卡片。")
        if "headcount" in tool_result or "avg_gpa" in tool_result:
            lines.append("- 班级概貌已生成，明细请查看概览卡片。")
        if "error" in tool_result:
            lines.append("- 该数据你没有访问权限，或所属班级不在本租户内。")
    if len(lines) == 1:
        lines.append("- 结果已生成，请查看对应列表。")
    lines.append("（本次回答走的是降级话术，未做数值核对。）")
    text = "\n".join(lines)
    assert not _digits_re.search(text), "降级模板不得包含任何数字"
    return text


def as_text_summary(tool_result: Any, limit: int = 400) -> str:
    """把工具结果压成给 LLM 看的结构化摘要（原样引用，不做归纳）。"""
    import json

    try:
        blob = json.dumps(tool_result, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        blob = str(tool_result)
    return blob[:limit]


def collect_claim_values(claims: Iterable[Claim]) -> list[float]:
    """便于测试与审计：取出论断数值列表。"""
    return [c.value for c in claims]
