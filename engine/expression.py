# engine/expression.py
# 职责：表达力度量——语速 / 填充词 / 句长 / 停顿 / 结构词，五项扣分制给一个确定性分数。
# 铁律：引擎定数，模型说话。纯函数、无随机、无网络、无 LLM；同一段文本永远同一分数。
# 缺失不冒充：没有 duration_sec 就不算语速、不扣语速分；没有 segments 就不统计停顿。
#
# 口径澄清（契约未写死、按最合理方式定，改动须同步契约）：
# 1) chars 指去掉空白后的可见字符数（中文按 1 字计），与 score_answer 的 length 口径一致。
# 2) speed_cpm 取整数（字/分钟是计数语义）；filler_rate / pause_ratio 保留 3 位小数。
# 3) filler_rate 严格按契约公式 filler_total / max(1, chars/100)，即「每百字填充词数」。
# 4) 填充词按「长词优先、命中即消耗」计数：先扣「然后就是」，再把「就是」从剩余文本里数，
#    避免一个词被两个填充词重复记账。
# 5) 无 segments 时 pause 指标仍保留一条（值写「未提供停顿数据」），保证 metrics 至少 4 条；
#    无 duration 时不输出 speed 指标，避免用 100 分冒充「语速完美」。

from __future__ import annotations

import re
from typing import Any

EXPRESSION_VERSION = "expr-v1"

FILLERS: tuple[str, ...] = ("嗯", "呃", "那个", "就是", "然后就是", "这个", "对吧", "其实", "怎么说")

# 结构词（出现任一 +4 分）
STRUCTURE_WORDS: tuple[str, ...] = ("首先", "其次", "最后", "第一", "第二", "因此", "所以", "举个例子")

_SENT_SPLIT = re.compile(r"[。！？!?；;…\n\r]+")
_SPEED_BEST = (200, 260)


def _num(value: Any) -> float | None:
    """安全取数：非数字/布尔/空值 → None。"""
    if isinstance(value, bool) or value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out:  # NaN
        return None
    return out


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def _count_fillers(body: str) -> dict[str, int]:
    """长词优先计数并消耗，避免「然后就是」与「就是」重复计入。"""
    work = body
    counts: dict[str, int] = {}
    for filler in sorted(FILLERS, key=lambda f: -len(f)):
        if not filler or filler not in work:
            continue
        n = work.count(filler)
        if n:
            counts[filler] = n
            work = work.replace(filler, "\u0000")
    # 按 FILLERS 固定顺序输出，保证字典序列稳定
    return {f: counts[f] for f in FILLERS if f in counts}


def _sentences(text: str) -> list[str]:
    """按中文/英文句末标点切句；空白句丢弃。"""
    raw = _SENT_SPLIT.split(str(text or ""))
    return [s.strip() for s in raw if s.strip()]


def _pause_stats(segments: list[dict] | None, duration: float | None) -> tuple[int, float, float, bool]:
    """返回 (停顿次数, 最长停顿秒, 停顿占比, 是否有有效分段)。间隔 >1.2s 记一次停顿。"""
    rows: list[tuple[float, float]] = []
    for seg in segments or []:
        if not isinstance(seg, dict):
            continue
        start = _num(seg.get("start"))
        end = _num(seg.get("end"))
        if start is None or end is None or end < start:
            continue
        rows.append((start, end))
    if len(rows) < 2:
        return 0, 0.0, 0.0, False

    rows.sort(key=lambda r: (r[0], r[1]))
    gaps: list[float] = []
    for prev, cur in zip(rows, rows[1:]):
        gap = cur[0] - prev[1]
        if gap > 1.2:
            gaps.append(round(gap, 3))
    span = rows[-1][1] - rows[0][0]
    base = duration if duration is not None and duration > 0 else span
    ratio = round(sum(gaps) / base, 3) if gaps and base and base > 0 else 0.0
    longest = round(max(gaps), 1) if gaps else 0.0
    return len(gaps), longest, min(1.0, ratio), True


def _speed_band(cpm: int | None) -> str:
    if cpm is None:
        return "未知"
    if cpm < 170:
        return "偏慢"
    if cpm > 320:
        return "偏快"
    return "标准"


def _speed_penalty(cpm: int | None) -> int:
    """200~260 最佳；<150 或 >320 扣 18；其余边缘区间扣 8。无 duration 不扣。"""
    if cpm is None:
        return 0
    if cpm < 150 or cpm > 320:
        return 18
    if cpm < _SPEED_BEST[0] or cpm > _SPEED_BEST[1]:
        return 8
    return 0


def _filler_penalty(total: int, chars: int) -> tuple[float, int]:
    """返回 (每百字填充词数, 扣分)。"""
    rate = round(total / max(1.0, chars / 100.0), 3)
    if rate <= 0.5:
        return rate, 0
    if rate <= 1.5:
        return rate, 8
    if rate <= 3:
        return rate, 15
    return rate, 24


def _sentence_penalty(avg: float) -> int:
    if avg > 60:
        return 10
    if 0 < avg < 10:
        return 6
    return 0


def _pause_penalty(ratio: float) -> int:
    if ratio > 0.4:
        return 18
    if ratio > 0.25:
        return 10
    return 0


def _tips(*, cpm: int | None, f_ded: int, filler_total: int, sent_ded: int, avg: float,
          pause_ded: int, structure_hit: bool) -> list[str]:
    """按实际扣分点给 2~3 条具体建议，不堆通用鸡汤。"""
    out: list[str] = []
    if cpm is not None and cpm > 320:
        out.append("语速压到 200~260 字/分：每个观点说完停半秒，别抢下一句。")
    elif cpm is not None and cpm < 170:
        out.append("语速偏慢：先说 3 个关键词再展开，减少边想边说的空白。")
    if f_ded:
        out.append(f"本场 {filler_total} 个填充词：换成半秒停顿，每百字控制在 0.5 个以内。")
    if sent_ded == 10:
        out.append("长句拆成 2~3 句：一句一个动作，先说结论再补原因。")
    elif sent_ded == 6:
        out.append(f"平均句长只有 {avg:.1f} 字：补全主谓宾，让一句话有完整信息。")
    if pause_ded:
        out.append("卡壳时用「我分三点说」过渡，别用长时间沉默填空白。")
    if not structure_hit:
        out.append("开场先给结论，再用「首先/其次/最后」把理由串起来。")
    if len(out) < 2:
        out.append("保持当前节奏，下一场把结论放在第一句，再补一个具体例子。")
    if len(out) < 2:
        out.append("答完要点后停一秒，让面试官有时间记录。")
    return out[:3]


def analyze(text: str, duration_sec: float | None = None,
            segments: list[dict] | None = None) -> dict:
    """表达力度量。segments = [{"text": str, "start": float, "end": float}]，可空。

    返回：
    {
      "version": "expr-v1",
      "score": 78,                  # 0~100 整数；duration_sec 缺失时按文本指标给分
      "confidence": "high|low",     # 有 duration 且 >=5s → high，否则 low
      "chars": 236, "duration_sec": 68.0,
      "speed_cpm": 208, "speed_band": "偏快|标准|偏慢|未知",
      "filler_total": 3, "filler_rate": 0.013, "fillers": {"嗯": 2, "那个": 1},
      "avg_sentence_len": 23.6, "max_sentence_len": 48,
      "pause_count": 4, "longest_pause_sec": 2.4, "pause_ratio": 0.12,
      "metrics": [{"key","label","value","score","hint"}],   # 4~5 条
      "tips": ["…"]
    }
    """
    raw = str(text or "")
    body = _compact(raw)
    chars = len(body)

    dur = _num(duration_sec)
    if dur is not None and dur <= 0:
        dur = None
    duration = round(dur, 1) if dur is not None else None
    confidence = "high" if dur is not None and dur >= 5 else "low"

    # 空文本没有「语速」可言：不给 0 字/分（那会被读成「极慢」）
    cpm = int(round(chars / dur * 60.0)) if dur and chars else None
    band = _speed_band(cpm)

    fillers = _count_fillers(body)
    filler_total = sum(fillers.values())
    filler_rate, f_ded = _filler_penalty(filler_total, chars)

    sentences = _sentences(raw)
    lens = [len(_compact(s)) for s in sentences]
    lens = [n for n in lens if n > 0]
    avg_len = round(sum(lens) / len(lens), 1) if lens else 0.0
    max_len = max(lens) if lens else 0
    s_ded = _sentence_penalty(avg_len)

    pause_count, longest_pause, pause_ratio, has_seg = _pause_stats(segments, dur)
    p_ded = _pause_penalty(pause_ratio) if has_seg else 0

    structure_hit = any(w in raw for w in STRUCTURE_WORDS)
    speed_ded = _speed_penalty(cpm)

    if chars == 0:
        score = 0
    else:
        score = int(max(0, min(100, 100 - speed_ded - f_ded - s_ded - p_ded
                               + (4 if structure_hit else 0))))

    metrics: list[dict[str, Any]] = []
    if cpm is not None:
        metrics.append({"key": "speed", "label": "语速", "value": f"{cpm} 字/分",
                        "score": 100 - speed_ded,
                        "hint": "面试舒适区 200~260 字/分"})
    metrics.append({"key": "filler", "label": "填充词",
                    "value": f"{filler_total} 次 / 每百字 {filler_rate:.1f} 个",
                    "score": 100 - f_ded,
                    "hint": "每百字不超过 0.5 个，卡住就用停顿替代"})
    metrics.append({"key": "sentence", "label": "句长",
                    "value": f"平均 {avg_len:.1f} 字 / 最长 {max_len} 字",
                    "score": 100 - s_ded,
                    "hint": "单句 15~45 字最好跟，超过 60 字听感吃力"})
    metrics.append({"key": "pause", "label": "停顿",
                    "value": (f"{pause_count} 次 / 最长 {longest_pause:.1f} 秒"
                              if has_seg else "未提供停顿数据"),
                    "score": 100 - p_ded if has_seg else 100,
                    "hint": "单次停顿超过 1.2 秒会被记为卡壳"})
    metrics.append({"key": "structure", "label": "结构词",
                    "value": "有" if structure_hit else "没有",
                    "score": 100 if structure_hit else 60,
                    "hint": "用首先/其次/最后串起逻辑，听感更有条理"})

    return {
        "version": EXPRESSION_VERSION,
        "score": score,
        "confidence": confidence,
        "chars": chars,
        "duration_sec": duration,
        "speed_cpm": cpm,
        "speed_band": band,
        "filler_total": filler_total,
        "filler_rate": filler_rate,
        "fillers": fillers,
        "avg_sentence_len": avg_len,
        "max_sentence_len": max_len,
        "pause_count": pause_count,
        "longest_pause_sec": longest_pause,
        "pause_ratio": pause_ratio,
        "metrics": metrics,
        "tips": _tips(cpm=cpm, f_ded=f_ded, filler_total=filler_total, sent_ded=s_ded,
                      avg=avg_len, pause_ded=p_ded, structure_hit=structure_hit),
    }
