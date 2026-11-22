# agents/critic.py
# 职责：数值一致性审核守门——规则抽取 + 与引擎原始结果逐条比对
# 依赖：标准库 re / datetime / decimal；agents.tools.write_audit（审计落库复用工具层实现）
# 说明：**不是**让大模型自我检查；容差 1e-6，百分比与小数互相兼容；
#       出现「约/大概/估计 + 数字」直接判不通过，宁可降级也不放过。

from __future__ import annotations

import bisect
import re
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Iterable, Mapping, Sequence

CRITIC_VERSION = "critic-v3"
# 允许的重试次数（草稿重写），超限即降级
MAX_RETRY = 2
# 浮点比较容差
TOLERANCE = 1e-6

# 模糊词：与数值同时出现即判不通过
# v3：窗口从「数字前 8 字」扩到「前 8 后 6」——「75.83 左右」「约 3 门」两头都算。
# 旧版只看数字左侧，而「左右 / 上下 / 出头」这类中文惯用后缀全在右侧，
# 等于把最常见的一种模糊表述漏掉了。
FUZZY_WORDS: tuple[str, ...] = ("约", "大概", "估计", "大约", "差不多", "似乎", "左右",
                                "上下", "出头", "接近", "将近", "或许", "可能约")
FUZZY_WINDOW_BEFORE = 8
FUZZY_WINDOW_AFTER = 6

# 单位识别（数字后面紧跟的第一个单位符号/字）
_UNIT_TOKENS: tuple[tuple[str, str], ...] = (
    ("%", "percent"),
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
# 列表序号标记：「1. 外交部…」「2、法律…」「3）xxx」——序号不是数值论断
_ordinal_mark_re = re.compile(r"[.．、）)](\s|$)")

# v3 新增的两类「非论断数字」，抽数之前先抹掉：
#   1) 长编号：学号/工号/职位代码（20230533、300110001001）——8 位以上连续数字，
#      既不在工具白名单里、也不是任何结论，留着只会把合格草稿判成编造。
#   2) 日期：「2026年3月15日」「3月15日」——年月日各自成数，逐个核对毫无意义。
_long_id_re = re.compile(r"(?<!\d)\d{8,}(?!\d)")
_date_re = re.compile(r"\d{4}\s*年\s*\d{1,2}\s*月(?:\s*\d{1,2}\s*[日号])?"
                      r"|\d{4}\s*[-/.]\s*\d{1,2}\s*[-/.]\s*\d{1,2}"
                      r"|\d{1,2}\s*月\s*\d{1,2}\s*[日号]")


@dataclass(frozen=True)
class Claim:
    """从文本里抽出的一个数值论断。"""

    raw: str
    value: float
    unit: str
    span: tuple[int, int] = (0, 0)


@dataclass
class Verdict:
    """审核结论。passed=False 时 mismatches 给出逐条原因。

    v3 新增：
    - rounded：按草稿自己的小数位数四舍五入后能对上的论断。这类**不再判失败**
      （旧版容差 1e-6，「75.83 → 写 75.8」会被当成编造而触发无谓重写/降级），
      但会单独记下来，审计时能看到「这条是舍入，不是原文直引」。
    - stats：本条草稿的核对统计（论断数/命中数/舍入数/拒绝数/耗时），
      前端「智能体质量」页与审计日志可以直接读，不用再去解析自由文本。
    """

    passed: bool
    claims: list[Claim] = field(default_factory=list)
    mismatches: list[str] = field(default_factory=list)
    fuzzy: list[str] = field(default_factory=list)
    reason: str = ""
    rounded: list[str] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)

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
            "rounded": list(self.rounded),
            "stats": dict(self.stats),
            "version": CRITIC_VERSION,
        }


def _mask_ids(text: str) -> str:
    """先把学期号/版本号/学号/日期这类「非论断数字」抹掉，避免被当成数值断言。

    占位符必须与被替换内容**等长**（用 # 填充）：span 全程使用原文坐标，
    否则每个被抹掉的 token 都会让之后的 span 前移，模糊词窗口会查错位置。
    # 不是数字也不是字母，_number_re / _rowref_re 都不会再匹配到它。
    """
    def _blank(match: "re.Match") -> str:
        return "#" * (match.end() - match.start())

    masked = _version_token_re.sub(_blank, str(text or ""))
    # 日期必须在学期号之前抹：学期正则会把「2026年3月15日」先啃掉「2026年3」，
    # 剩下「15日」反而变成一个孤零零的论断数字。
    masked = _date_re.sub(_blank, masked)
    masked = _term_token_re.sub(_blank, masked)
    masked = _long_id_re.sub(_blank, masked)
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


def _is_list_ordinal(masked: str, match: "re.Match") -> bool:
    """行首整数紧跟列表标记（. ． 、 ） )）→ 是条目序号，不是数值论断。

    「列明细」型草稿（如职位列表「1. 外交部…招 15 人」）的序号 1~8
    不在工具返回的白名单里，此前会把整份合格草稿误判成编造数值。
    """
    raw = match.group(0)
    if "." in raw:                      # 小数（3.5）不是序号
        return False
    start = match.start()
    i = start
    while i > 0 and masked[i - 1] in " \t":   # 允许缩进，但不许前面还有正文
        i -= 1
    if i > 0 and masked[i - 1] != "\n":
        return False
    return bool(_ordinal_mark_re.match(masked[match.end():match.end() + 2]))


# 行引用枚举：「第1、2、4条」「第3条」「第 5 项」——引用的是返回列表的行号
_rowref_re = re.compile(r"第\s*\d+(?:\s*[、,]\s*\d+)*\s*[条项]")


def extract_numbers(text: str) -> list[Claim]:
    """抽取全部数值论断：返回原始值 + 单位上下文（"71%"→0.71 且保留 71 参与匹配）。

    「第N[、M]条/项」先按 rowref 论断抽出（行号本身是引擎列表的确定性事实，
    由 verify 按列表行数校验边界），再从扫描文本里抹掉，避免被当普通数值重复收。
    """
    masked = _mask_ids(text)
    claims: list[Claim] = []
    rowref_spans: list[tuple[int, int]] = []
    for enum in _rowref_re.finditer(masked):
        rowref_spans.append((enum.start(), enum.end()))
        for num in _number_re.finditer(enum.group(0)):
            claims.append(Claim(raw=num.group(0), value=float(num.group(0)),
                                unit="rowref",
                                span=(enum.start() + num.start(),
                                      enum.start() + num.end())))
    for start, end in sorted(rowref_spans, reverse=True):
        masked = masked[:start] + " <ROWREF> " + masked[end:]
    for match in _number_re.finditer(masked):
        if _is_list_ordinal(masked, match):
            continue
        raw = match.group(0)
        value = float(raw)
        unit = _unit_after(masked, match.end())
        if unit in ("term", "version"):
            continue  # 学期号 / 版本号不是数值论断
        claims.append(Claim(raw=raw, value=value, unit=unit,
                            span=(match.start(), match.end())))
    claims.sort(key=lambda c: c.span[0])
    return claims


def max_list_rows(tool_result: Any) -> int:
    """工具结果里最长列表的行数：行引用「第N条」的合法性边界。"""
    best = 0

    def walk(node: Any) -> None:
        nonlocal best
        if isinstance(node, (list, tuple, set)):
            best = max(best, len(node))
            for item in node:
                walk(item)
        elif isinstance(node, Mapping):
            for value in node.values():
                walk(value)

    walk(tool_result)
    return best


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    return None


def _collect_raw(tool_result: Any) -> list[float]:
    """工具结果里的全部原始数值（不换算、不扩张）。"""
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
            # 列表条数同样是引擎事实：「共 8 条职位」的 8 = len(返回列表)，
            # 不收的话对列表行数的合法总结会被误判成编造数值
            values.append(float(len(node)))
            for item in node:
                walk(item)

    walk(tool_result)
    return values


def _allowed_universe(raw: Iterable[float]) -> list[float]:
    """白名单：原始值 + 比例换算值，**单向**。

    旧版把所有 0~100 的值同时塞进「÷100」的孪生值，于是工具里只要有 3，
    「0.03」这种凭空捏的比例也能过审——这是最容易被放过的编造形态。
    v3 只保留「0~1 的比例 → ×100」一个方向：0.71 既能写 0.71 也能写 71%，
    而 3 不会再生出 0.03。
    """
    values = {float(v) for v in raw}
    values |= {round(v * 100, 6) for v in raw if 0.0 < abs(v) <= 1.0}
    return sorted(values)


def build_ground_truth(tool_result: Any) -> list[float]:
    """收集所有可核对数值（含 reasons 句子里的数字），形成白名单。"""
    return _allowed_universe(_collect_raw(tool_result))


def _nearest(candidates: Sequence[float], value: float, top: int = 3) -> list[float]:
    ordered = sorted(set(candidates), key=lambda c: abs(c - value))
    return [round(c, 4) for c in ordered[:top]]


def _is_fuzzy(text: str, claim: Claim, *, after: bool = True) -> str | None:
    """数字**前后**窗口里出现模糊词 → 返回原因串。

    v2 只看左侧 8 字；可中文的模糊语几乎都写在数字后面（「3 门左右」「接近 70 分」
    「75.83 上下」），只看前面等于放过最常见的估算话术。v3 补上右侧窗口。
    """
    start, end = claim.span
    before = str(text or "")[max(0, start - FUZZY_WINDOW_BEFORE):start]
    tail = str(text or "")[end:end + FUZZY_WINDOW_AFTER] if after else ""
    for word in FUZZY_WORDS:
        if word in before:
            return f"出现模糊表述「{word}」+ 数值「{claim.raw}」，不确定性话术一律判不通过"
    for word in FUZZY_WORDS:
        if word in tail:
            return f"出现模糊表述「{claim.raw} {word}」，不确定性话术一律判不通过"
    return None


def _value_allowed(sorted_ground: Sequence[float], value: float, tolerance: float) -> bool:
    """白名单成员判断：排序后二分，只看插入点两侧的邻居。

    白名单是排好序的，与 value 距离 ≤ tolerance 的值只可能落在插入点左右
    两个位置——原来对整个白名单线性扫一遍（O(N)×论断数），现在 O(log N)。
    """
    idx = bisect.bisect_left(sorted_ground, value)
    for j in (idx - 1, idx):
        if 0 <= j < len(sorted_ground) and abs(sorted_ground[j] - value) <= tolerance:
            return True
    return False


def _decimals(raw: str) -> int:
    """草稿里这个数字写了几位小数：决定「舍入到几位」的合法误差。"""
    text = str(raw or "").lstrip("-")
    return len(text.split(".", 1)[1]) if "." in text else 0


def _rounding_allowed(sorted_ground: Sequence[float], raw: str, value: float) -> float | None:
    """按草稿自己的小数位数做四舍五入，能否对上某个允许值。

    整数也参与（「68.4 写成 68」是报告里最常见的写法），但只给半个最小单位的
    空间：68.4→68 通过，78.4→78 依旧判编造。命中返回那个允许值，否则 None。
    """
    places = _decimals(raw)
    half = 0.5 * 10 ** -places + 1e-9
    idx = bisect.bisect_left(sorted_ground, value)
    for j in (idx - 1, idx, idx + 1):
        if not (0 <= j < len(sorted_ground)):
            continue
        candidate = sorted_ground[j]
        if abs(candidate - value) <= half and round(candidate, places) == round(value, places):
            return candidate
    return None


def verify(draft: str, tool_result: Any, *, tolerance: float = TOLERANCE,
           rounding: bool = True, fuzzy_after: bool = True) -> Verdict:
    """把草稿里的每个数值论断与工具结果白名单逐条比对。

    rounding / fuzzy_after 两个开关只为 A/B 对照与回归测试保留（默认都开）：
    线上永远走 v3 口径，测试里可以复现 v2 行为确认「改动到底影响了哪几条」。
    """
    started = time.perf_counter()
    claims = extract_numbers(draft)
    allowed = _allowed_universe(_collect_raw(tool_result))
    rows = max_list_rows(tool_result)
    mismatches: list[str] = []
    fuzzy: list[str] = []
    rounded: list[str] = []
    matched = 0

    for claim in claims:
        reason = _is_fuzzy(str(draft), claim, after=fuzzy_after)
        if reason:
            fuzzy.append(reason)
            continue
        if claim.unit == 'rowref':
            # 行引用（如「第3条」）：行号不超过返回列表行数即合法，超出才判编造
            if rows <= 0 or not (1 <= claim.value <= rows):
                mismatches.append(
                    f'行引用「第{claim.raw}条」超出返回列表行数（共 {rows} 行）')
            else:
                matched += 1
            continue
        if _value_allowed(allowed, claim.value, tolerance):
            matched += 1
            continue
        near = _rounding_allowed(allowed, claim.raw, claim.value) if rounding else None
        if near is not None:
            # 舍入显示不等于编造：记一条审计，但不算失败（旧版在这里会白跑一轮重写）
            rounded.append(f"数值「{claim.raw}」是 {near:g} 的舍入写法")
            matched += 1
            continue
        nearest = _nearest(allowed, claim.value)
        mismatches.append(
            f"数值「{claim.raw}」不在工具返回结果中"
            f"（最接近的允许值：{nearest if nearest else '无'}）"
        )

    passed = not mismatches and not fuzzy
    return Verdict(
        passed=passed,
        claims=claims,
        mismatches=mismatches,
        fuzzy=fuzzy,
        reason="" if passed else "数值未通过一致性核对",
        rounded=rounded,
        stats={
            "claims": len(claims),
            "matched": matched,
            "rounded": len(rounded),
            "rejected": len(mismatches) + len(fuzzy),
            "allowed_values": len(allowed),
            "elapsed_us": int((time.perf_counter() - started) * 1_000_000),
        },
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
            if tool_result.get("error_kind") == "unavailable":
                lines.append("- 这个数据暂时查不了，可能是数据服务忙，请稍后再试。")
            else:
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
