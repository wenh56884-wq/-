# engine/peer.py
# 职责：同辈分位基准——把单场总分与四维分换算成「在本专业同年级里的位置」，样本不足时
#       诚实降级为课程成绩代理基准，再不足就明说给不出分位。
# 铁律：引擎定数，模型说话。纯函数、无随机、无网络、无 LLM、无数据库。
# 分位口径唯一：严格小于你的样本比例（并列不抬分），不插值、不四舍五入抬档。
#
# 为什么市面没有：商业面试产品只能给绝对分（「你 74 分」无法解释强弱），也没有同辈母体；
# 高校手握同专业同年级的完整样本与成绩，才能回答「你在同辈里排哪一档」。样本不够时
# 商业产品通常照样编一个分位，这里宁可降级并写明口径，也不让人误以为是面试实测。
#
# 口径澄清（契约第 9 节未写死处，按最合理方式定，改动须同步契约）：
# 1) rank 严格按契约公式 ceil((1-p/100)*cohort)，最小 1。契约示例 cohort=128、
#    percentile=77.0 写 rank=29，而公式算得 30（0.23×128=29.44）；公式是显式规则，
#    示例属笔误，以公式为准。
# 2) cohort<=0（未传或非法）时 rank 记 None——「0 人里的第 1 名」没有意义，不拿 1 冒充。
# 3) course_proxy 下只有维度能算代理分位；total 没有课程代理口径（课程分不等于面试总分），
#    故 total.percentile/rank/label 均为 null，绝不把维度均值拼成假总分。
# 4) 单个维度在 course_proxy 下没有代理数据时，该维 basis 记 "none"、percentile 为 null；
#    顶层 basis 仍按「有任一维可代理」定为 course_proxy，并在 note 里说明。
# 5) dims 固定按 content/structure/depth/evidence 输出，只输出传入的维度；契约外的
#    额外 key 追加在末尾（标签回落为 key），不静默丢数据。
# 6) percentile_of 的「严格小于」在顶部封顶：value >= 样本最大值记 100.0（同辈里没有更高的人），
#    否则「与最高分同分」会得到 (n-1)/n，学生看到「未进前 10%」是明显误导。中段并列仍不抬分。

from __future__ import annotations

import math
from typing import Any

PEER_VERSION = "peer-v1"

# 固定顺序与标签（契约示例 label 为「内容」等短词，与 panel 的「内容覆盖」不同，勿混用）
PEER_DIMS: tuple[str, ...] = ("content", "structure", "depth", "evidence")

PEER_DIM_LABELS: dict[str, str] = {
    "content": "内容",
    "structure": "结构",
    "depth": "深度",
    "evidence": "证据",
}

# 实测样本门槛：>=5 场才敢称「本专业同年级实测」
MIN_OBSERVED = 5

# 分位 → 档位标签，从高到低匹配
_LABEL_BANDS: tuple[tuple[float, str], ...] = (
    (90.0, "前 10%"), (75.0, "前 25%"), (50.0, "中上"), (25.0, "中下"),
)
_LABEL_LOW = "后 25%"


# ----------------------------------------------------------------
# 工具
# ----------------------------------------------------------------
def _num(value: Any) -> float | None:
    """安全取数：布尔/空串/NaN/非数字一律 None（缺失不冒充 0）。"""
    if isinstance(value, bool) or value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out:  # NaN
        return None
    return out


def _clean_samples(samples: Any) -> list[float]:
    """只保留有效数字样本；空值/脏值丢弃，不当作 0 分样本。"""
    if not isinstance(samples, (list, tuple)):
        return []
    out: list[float] = []
    for raw in samples:
        value = _num(raw)
        if value is not None:
            out.append(value)
    return out


def _label(percentile: float | None) -> str | None:
    """percentile>=90 前 10%，>=75 前 25%，>=50 中上，>=25 中下，否则后 25%。"""
    if percentile is None:
        return None
    for bound, label in _LABEL_BANDS:
        if percentile >= bound:
            return label
    return _LABEL_LOW


def _rank(percentile: float | None, cohort: int) -> int | None:
    """rank = ceil((1-p/100)*cohort)，最小 1；cohort 非法时为 None（不冒充第 1）。"""
    if percentile is None or cohort <= 0:
        return None
    return max(1, int(math.ceil((1.0 - percentile / 100.0) * cohort)))


def _cohort_size(value: Any) -> int:
    num = _num(value)
    if num is None or num < 0:
        return 0
    return int(num)


def _clean_proxy(proxy: Any) -> dict[str, list[float]]:
    """{dim: [课程分]} —— 只保留非空且含有效数字的维度。"""
    out: dict[str, list[float]] = {}
    if not isinstance(proxy, dict):
        return out
    for key, values in proxy.items():
        cleaned = _clean_samples(values)
        if cleaned:
            out[str(key)] = cleaned
    return out


def _note(basis: str, sample_n: int, cohort: int, proxied: list[str]) -> str:
    """口径说明必须诚实：是实测就说实测，是代理就写「非面试实测」。"""
    if basis == "observed":
        return (f"基于本专业同年级 {sample_n} 场实测样本"
                f"（年级规模 {cohort} 人）计算，分位为严格小于你的样本比例，并列不抬分；"
                f"与样本最高分持平按 100 计（同辈里没有更高的）。")
    if basis == "course_proxy":
        dims_txt = "、".join(PEER_DIM_LABELS.get(d, d) for d in proxied) or "部分维度"
        return (f"样本不足 {MIN_OBSERVED} 场（当前仅 {sample_n} 场），改用课程成绩代理基准，"
                f"非面试实测：{dims_txt}的分位来自同专业相关课程分数，只说明课程成绩的相对位置，"
                f"不代表面试能力；总分不给分位。")
    return (f"本专业同年级仅 {sample_n} 场实测（不足 {MIN_OBSERVED} 场），"
            f"也没有可用的课程成绩代理基准，因此不给出分位——"
            f"宁可不给，也不拿假基准冒充同辈位置。")


# ----------------------------------------------------------------
# 分位
# ----------------------------------------------------------------
def percentile_of(value: float, samples: list[float]) -> float | None:
    """严格小于 value 的样本比例 ×100，保留 1 位小数；samples 为空或无有效样本返回 None。

    并列不抬分：与 value 相等的样本不计入分子（并列时分位偏低而不是偏高）。
    顶部边界单独处理：value >= 样本最大值记 100.0——同辈里没有比你更高的，分位条必须封顶，
    否则「和最高分同分」会被算成 (n-1)/n，学生看到「未进前 10%」会误判。值等于最小值时
    严格小于数为 0，自然得 0.0。中段并列不受这条影响。
    """
    target = _num(value)
    clean = _clean_samples(samples)
    if target is None or not clean:
        return None
    if target >= max(clean):
        return 100.0
    below = sum(1 for s in clean if s < target)
    return round(below / len(clean) * 100.0, 1)


# ----------------------------------------------------------------
# 主入口
# ----------------------------------------------------------------
def benchmark(total: float | None, dims: dict[str, float],
              samples: list[float], cohort_size: int,
              proxy: dict[str, list[float]] | None = None) -> dict:
    """同辈分位基准：observed（>=5 场实测）→ course_proxy（有代理）→ none（诚实地不给）。

    参数：
      total: 本场总分（0~100），缺失传 None
      dims: {"content":74.0, ...}，只输出传入的维度
      samples: 本专业同年级已练面试的 total 列表
      cohort_size: 本专业同年级总人数，用于换算名次
      proxy: {维度 key: 该维度相关课程分数列表}，可空

    返回字段与契约第 9 节逐字一致（version/basis/cohort/sample_n/total/dims/note/honest）。
    """
    clean = _clean_samples(samples)
    sample_n = len(clean)
    cohort = _cohort_size(cohort_size)
    proxy_map = _clean_proxy(proxy)
    proxied = [d for d in PEER_DIMS if d in proxy_map]

    if sample_n >= MIN_OBSERVED:
        basis = "observed"
    elif proxied:
        basis = "course_proxy"
    else:
        basis = "none"

    # ---- 总分 ----
    total_score = _num(total)
    total_pct = percentile_of(total_score, clean) if basis == "observed" else None
    total_block = {
        "score": round(total_score, 2) if total_score is not None else None,
        "percentile": total_pct,
        "rank": _rank(total_pct, cohort),
        "label": _label(total_pct),
    }

    # ---- 四维（固定顺序，只输出传入的维度） ----
    src = dims if isinstance(dims, dict) else {}
    keys = [d for d in PEER_DIMS if d in src] + [str(k) for k in src if k not in PEER_DIMS]
    dim_items: list[dict[str, Any]] = []
    for key in keys:
        score = _num(src.get(key))
        pct: float | None = None
        dim_basis = "none"
        if basis == "observed":
            pct = percentile_of(score, clean)
            dim_basis = "observed" if pct is not None else "none"
        elif basis == "course_proxy" and key in proxy_map:
            pct = percentile_of(score, proxy_map[key])
            dim_basis = "course_proxy" if pct is not None else "none"
        dim_items.append({
            "key": key,
            "label": PEER_DIM_LABELS.get(key, key),
            "score": round(score, 2) if score is not None else None,
            "percentile": pct,
            "basis": dim_basis,
        })

    return {
        "version": PEER_VERSION,
        "basis": basis,
        "cohort": cohort,
        "sample_n": sample_n,
        "total": total_block,
        "dims": dim_items,
        "note": _note(basis, sample_n, cohort, proxied),
        "honest": True,  # 恒为 True：本引擎从不把代理基准包装成实测
    }
