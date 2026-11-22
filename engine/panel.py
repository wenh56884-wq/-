# engine/panel.py
# 职责：圆桌三面试官——同一份评分明细，按三种立场各自打分，再给共识与分歧归因。
# 铁律：引擎定数，模型说话。本模块全部纯函数，无随机、无网络、无 LLM。
# 缺失不冒充：未作答的题不进均分；全未答时 consensus.score 为 null，绝不当 0 分处理。
#
# 口径澄清（契约未写死、按最合理方式定，改动须同步契约）：
# 1) 四维 key 统一用 structure。契约 dimension_percent 的文档里写作 struct，但 PANELISTS
#    权重、passport 的 dims、radar 的 key 全部是 structure，只在这一处用 struct 会逼所有
#    调用方改名，故统一为 structure（同一维度，不新增字段）。
# 2) 每位面试官的维度取「已答题的四维均值」；单轮分用该轮自己的四维，公式同 persona 分。
# 3) 全未作答时 panelists 的 score/verdict/level/delta_vs_consensus/focus 均为 null——
#    没有作答就没有判断，不拿「不通过」冒充结论。

from __future__ import annotations

from typing import Any

PANEL_VERSION = "panel-v1"

# 四维固定顺序：面板、雷达、护照共用这一套 key 与顺序
DIMS: tuple[str, ...] = ("content", "structure", "depth", "evidence")

DIM_LABELS: dict[str, str] = {
    "content": "内容覆盖",
    "structure": "表达结构",
    "depth": "技术深度",
    "evidence": "证据支撑",
}

# score_answer 明细字段 → (字段名, 该维原始满分)
DIM_DETAIL: dict[str, tuple[str, float]] = {
    "content": ("keyword_score", 30.0),
    "structure": ("struct_score", 25.0),
    "depth": ("depth_score", 25.0),
    "evidence": ("evidence_score", 20.0),
}

# 每个维度的可执行补强动作（advice / 护照 next_action 共用同一套口径）
DIM_ACTION: dict[str, str] = {
    "content": "答题前先列 3 个岗位考点关键词，逐条对照是否说到",
    "structure": "按「背景-目标-行动-结果」四段组织，先说结论再展开",
    "depth": "每题补一个具体例子，并给出一个可核对的数字结果",
    "evidence": "点名简历里的项目名、课程名与数据出处，别用形容词代替事实",
}

PANELISTS: list[dict[str, Any]] = [
    {"id": "tech", "name": "陈工", "title": "技术面", "tagline": "只看你能不能落地",
     "weights": {"content": 0.46, "structure": 0.24, "depth": 0.18, "evidence": 0.12},
     "bias": -1.5},
    {"id": "hr", "name": "李敏", "title": "HR 面", "tagline": "看你是否值得长期投入",
     "weights": {"content": 0.18, "structure": 0.34, "depth": 0.16, "evidence": 0.32},
     "bias": 2.0},
    {"id": "pressure", "name": "周总", "title": "压力面", "tagline": "专挑你话里的空洞",
     "weights": {"content": 0.40, "structure": 0.18, "depth": 0.30, "evidence": 0.12},
     "bias": -4.0},
]

_SPREAD_LEVELS: tuple[tuple[float, str], ...] = (
    (5.0, "高度一致"), (12.0, "分歧可控"), (20.0, "分歧明显"),
)


# ----------------------------------------------------------------
# 工具
# ----------------------------------------------------------------
def _num(value: Any) -> float | None:
    """安全取数：非数字/布尔/空串一律 None（缺失不冒充 0）。"""
    if isinstance(value, bool) or value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out:  # NaN
        return None
    return out


def _verdict(score: float | None) -> str | None:
    if score is None:
        return None
    if score >= 78:
        return "推荐"
    if score >= 62:
        return "待定"
    return "不通过"


def _level(score: float | None) -> str | None:
    if score is None:
        return None
    if score >= 75:
        return "稳"
    if score >= 60:
        return "边缘"
    return "危险"


def _spread_level(spread: float | None) -> str | None:
    if spread is None:
        return None
    for bound, label in _SPREAD_LEVELS:
        if spread < bound:
            return label
    return "严重分歧"


def _uniq(values: list[str]) -> list[str]:
    """保序去重，空串丢弃。"""
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        s = str(v or "").strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _fit(text: str, lo: int = 60, hi: int = 110) -> str:
    """把点评压到契约要求的 60~110 字（按字计，含标点）。"""
    t = str(text or "").strip()
    if len(t) > hi:
        return t[:hi - 1] + "…"
    pad = "先把一件事说清楚，比说十句漂亮话更有用。"
    while len(t) < lo:
        t += pad
    return t[:hi]


# ----------------------------------------------------------------
# 维度折算
# ----------------------------------------------------------------
def dimension_percent(item: dict | None) -> dict:
    """把 score_answer 明细折算成四维百分制：content/structure/depth/evidence (0~100, 2 位小数)。

    折算口径：content=keyword_score/30，structure=struct_score/25，depth=depth_score/25，
    evidence=evidence_score/20。item 为空或字段缺失 → 该维按 0 计（调用方须先判空，
    本函数只负责折算，不负责判断「有没有作答」）。
    """
    src = item if isinstance(item, dict) else {}
    out: dict[str, float] = {}
    for dim in DIMS:
        field, full = DIM_DETAIL[dim]
        raw = _num(src.get(field)) or 0.0
        pct = raw / full * 100.0 if full else 0.0
        out[dim] = round(min(100.0, max(0.0, pct)), 2)
    return out


def _persona_score(weights: dict[str, float], dims: dict[str, float] | None,
                   bias: float) -> float | None:
    """Σ(权重×维度百分制) + bias，clamp [0,100]，1 位小数；无维度数据 → None。"""
    if not dims:
        return None
    total = sum(float(weights.get(d, 0.0)) * float(dims.get(d, 0.0)) for d in DIMS) + float(bias)
    return round(min(100.0, max(0.0, total)), 1)


# ----------------------------------------------------------------
# 主入口：三视角独立打分 + 共识
# ----------------------------------------------------------------
def _pairs(scores: list[dict | None], outline: list[dict]) -> list[tuple[int, dict | None]]:
    """把 scores 与 outline 对齐成 [(round, item|None)]；长度不一致时以长者为准，缺位视为未答。"""
    sc = list(scores or [])
    ol = list(outline or [])
    out: list[tuple[int, dict | None]] = []
    for i in range(max(len(sc), len(ol))):
        item = sc[i] if i < len(sc) else None
        if not isinstance(item, dict):
            item = None
        rnd = i + 1
        if i < len(ol) and isinstance(ol[i], dict):
            num = _num(ol[i].get("round"))
            if num is not None:
                rnd = int(num)
        out.append((rnd, item))
    return out


def _collect(items: list[dict | None]) -> dict[str, Any]:
    """汇总全体已答题目的事实：命中要点、漏掉要点、结构标记。"""
    hits: list[str] = []
    missed: list[str] = []
    marks: list[str] = []
    for item in items:
        if item is None:
            continue
        hits += [str(x) for x in (item.get("keyword_hits") or [])]
        missed += [str(x) for x in (item.get("keyword_missed") or [])]
        marks += [str(x) for x in (item.get("struct_marks") or [])]
    return {"hits": _uniq(hits), "missed": _uniq(missed), "marks": _uniq(marks)}


def _highlights(facts: dict[str, Any], answered: int) -> list[str]:
    """亮点 ≤3 条：要点命中优先，其次结构标记；都没有时只陈述「完成作答」这一事实。"""
    out: list[str] = [f"答到了「{h}」" for h in facts["hits"][:2]]
    if len(out) < 3 and len(facts["marks"]) >= 2:
        out.append("分点作答：" + "、".join(facts["marks"][:3]))
    if not out and answered > 0:
        out.append(f"完成 {answered} 题作答，没有跳题")
    return out[:3]


def _concerns(facts: dict[str, Any], avg: dict[str, float] | None,
              skipped: int) -> list[str]:
    """扣分点 ≤3 条：漏掉的要点优先，其次最弱维度，最后是跳题。"""
    out: list[str] = [f"漏掉了「{m}」" for m in facts["missed"][:2]]
    if len(out) < 3 and avg:
        weak_dim = _weak_dim(avg)
        out.append(f"{DIM_LABELS[weak_dim]}仅 {avg[weak_dim]:.1f} 分")
    if len(out) < 3 and skipped > 0:
        out.append(f"跳过 {skipped} 题，该维度没有分数")
    return out[:3]


def _weak_dim(avg: dict[str, float]) -> str:
    """最低分维度；同分按 DIMS 固定顺序取前者（确定性）。"""
    return min(DIMS, key=lambda d: (round(float(avg.get(d, 0.0)), 6), DIMS.index(d)))


def _focus_dim(persona: dict[str, Any], avg: dict[str, float] | None) -> str | None:
    """该面试官最在意且本场最弱的一维：权重 × 失分空间 取最大。"""
    if not avg:
        return None
    weights = persona.get("weights") or {}

    def key(d: str) -> tuple[float, int]:
        room = float(weights.get(d, 0.0)) * (100.0 - float(avg.get(d, 0.0)))
        return (-round(room, 6), DIMS.index(d))

    return sorted(DIMS, key=key)[0]


def _comment(persona: dict[str, Any], score: float | None, avg: dict[str, float] | None,
             focus: str | None, facts: dict[str, Any]) -> str:
    """按 persona 模板拼装点评，引用真实命中/漏掉的要点，压到 60~110 字。"""
    pid = str(persona.get("id") or "")
    if score is None or not avg or focus is None:
        return f"{persona.get('name')}没有可评的作答：本场题目全部跳过，先完整答完一题再谈判断。"

    hit_txt = "、".join(f"「{h}」" for h in facts["hits"][:2])
    miss_txt = "、".join(f"「{m}」" for m in facts["missed"][:2]) or "关键细节"
    focus_label = DIM_LABELS[focus]
    focus_val = float(avg.get(focus, 0.0))
    # 一个要点都没命中时不能再说「答到了关键考点」——那会和 0 分自相矛盾
    hit_phrase = f"你答到了{hit_txt}，这部分有实感" if hit_txt else "这一场一个要点都没答到"

    # 四维都在 85 以上时不再硬找短板：如实说「没挑出硬伤」，但保留该面试官的立场
    if min(float(v) for v in avg.values()) >= 85:
        if pid == "tech":
            text = (f"我只看能不能落地。{hit_phrase}，动作和结果都说得实；"
                    f"{focus_label}是 {focus_val:.1f} 分，我没挑出硬伤。"
                    f"别松，下一场换个更难的题再验一次。")
        elif pid == "hr":
            text = (f"我更看长期投入。{hit_phrase}，"
                    f"{focus_label}是 {focus_val:.1f} 分；动机、匹配、规划能串成一条线。"
                    f"保持这个结构，再补一段长期目标。")
        else:
            text = (f"我专挑话里的空洞。这一场没挑出大洞，"
                    f"{focus_label}是 {focus_val:.1f} 分。"
                    f"别把这当成稳，下一场我会问更细的数字。")
        return _fit(text)

    focus_phrase = (f"{focus_label}只有 {focus_val:.1f} 分" if focus_val < 62
                    else f"{focus_label}是 {focus_val:.1f} 分")
    miss_phrase = f"{miss_txt}还没说到" if facts["missed"] else "要点覆盖没有明显缺口"

    if pid == "tech":
        text = (f"我只看能不能落地。{hit_phrase}；"
                f"不过{focus_phrase}，{miss_phrase}。"
                f"下一场把动作和结果讲具体，我才敢判断你真做过。")
    elif pid == "hr":
        text = (f"我更看长期投入。你的{focus_label}是 {focus_val:.1f} 分，"
                f"{hit_phrase}；{miss_phrase}。"
                f"把动机、匹配和三年规划串成一条线，我会更放心。")
    else:
        closer = (f"你提到的{hit_txt}也要给数字。" if hit_txt
                  else "先把要点碰到，再谈数字。")
        text = (f"我专挑话里的空洞。{focus_phrase}，{miss_phrase}；{closer}"
                f"别绕，直接说做了什么、结果多少。")
    return _fit(text)


def _divergence(avg: dict[str, float] | None, spread: float | None) -> dict | None:
    """分歧主因：三人加权贡献差最大的维度；三人分差 <5 视为无分歧。"""
    if not avg or spread is None or spread < 5.0:
        return None

    best: dict[str, Any] | None = None
    for dim in DIMS:
        contribs = [(idx, str(p.get("name") or ""),
                     float((p.get("weights") or {}).get(dim, 0.0)) * float(avg.get(dim, 0.0)))
                    for idx, p in enumerate(PANELISTS)]
        # 同分时按 PANELISTS 固定顺序取前者，保证确定性
        hi = max(contribs, key=lambda c: (round(c[2], 6), -c[0]))
        lo = min(contribs, key=lambda c: (round(c[2], 6), c[0]))
        gap = round(hi[2] - lo[2], 1)
        if best is None or gap > best["gap"]:
            best = {"dimension": dim, "gap": gap, "hi": hi, "lo": lo,
                    "w_hi": float((PANELISTS[hi[0]].get("weights") or {}).get(dim, 0.0)),
                    "w_lo": float((PANELISTS[lo[0]].get("weights") or {}).get(dim, 0.0))}
    if best is None or best["gap"] <= 0:
        return None

    dim = str(best["dimension"])
    hi_name, lo_name = best["hi"][1], best["lo"][1]
    w_hi, w_lo = best["w_hi"], best["w_lo"]
    note = (f"{hi_name}给「{DIM_LABELS[dim]}」的权重是 {w_hi:.2f}，{lo_name}只有 {w_lo:.2f}；"
            f"同一维度分下，两人的加权贡献相差 {best['gap']:.1f} 分，是本场分歧主因。")
    return {"dimension": dim, "gap": best["gap"], "note": note}


def _advice(avg: dict[str, float] | None, facts: dict[str, Any], skipped: int,
            divergence: dict | None, job_skills: list[str] | None) -> list[str]:
    """2~3 条可执行动作，必须点名具体维度与具体漏掉的要点。"""
    out: list[str] = []
    if avg:
        weak = _weak_dim(avg)
        out.append(f"先补{DIM_LABELS[weak]}（{avg[weak]:.1f} 分，全场最低）：{DIM_ACTION[weak]}。")
    if facts["missed"]:
        kws = "、".join(f"「{k}」" for k in facts["missed"][:2])
        prefix = "岗位要求的" if job_skills else ""
        out.append(f"下一场主动说到{prefix}{kws}，每个要点配一个具体例子，别只报名词。")
    if skipped > 0:
        out.append(f"{skipped} 题未作答按缺考处理：先把每题说满 30 秒，答错也比空着强。")
    if len(out) < 3 and divergence:
        out.append(f"复盘时对照「{DIM_LABELS[str(divergence['dimension'])]}」："
                   f"两位面试官判断相差 {divergence['gap']:.1f} 分，想清楚谁的标准更贴岗位。")
    while len(out) < 2:
        out.append("每题第一句先给结论，再展开两条理由，最后补一个数字或例子。")
    return out[:3]


def _summary(score: float | None, spread: float | None, level: str | None,
             skipped: int, divergence: dict | None) -> str:
    if score is None:
        return "本场没有有效作答，三位面试官无法给出共识分；先完整答完一题再来复盘。"
    parts = [f"三位面试官均分 {score:.1f} 分，最高与最低相差 {spread:.1f} 分，属于{level}。"]
    if divergence:
        parts.append(f"分歧主要来自{DIM_LABELS[str(divergence['dimension'])]}。")
    else:
        parts.append("三人判断接近，结论可直接采信。")
    if skipped > 0:
        parts.append(f"本场有 {skipped} 题未作答，已从均分中剔除。")
    return "".join(parts)


def review(scores: list[dict | None], outline: list[dict],
           job_skills: list[str] | None = None) -> dict:
    """三视角独立打分 + 共识。纯函数。

    返回：
    {
      "version": "panel-v1",
      "panelists": [
        {"id","name","title","tagline","score": 73.4, "verdict": "推荐|待定|不通过",
         "level": "稳|边缘|危险", "delta_vs_consensus": -2.1,
         "focus": "技术深度", "comment": "…", "highlights": ["…"], "concerns": ["…"],
         "rounds": [{"round":1,"score":68.2}]}
      ],   # 恰好 3 个，顺序 tech/hr/pressure
      "consensus": {"score","spread","level","verdict","summary","advice"},
      "divergence": {"dimension","gap","note"} | None,
      "answered": 5, "skipped": 1
    }
    """
    pairs = _pairs(scores, outline)
    items = [item for _, item in pairs]
    answered_items = [item for item in items if item is not None]
    skipped = len(items) - len(answered_items)
    answered = len(answered_items)
    facts = _collect(answered_items)

    dims_by_round = [dimension_percent(item) if item is not None else None for item in items]
    if answered_items:
        avg: dict[str, float] | None = {
            dim: round(sum(d[dim] for d in dims_by_round if d is not None) / answered, 2)
            for dim in DIMS
        }
    else:
        avg = None

    panelists: list[dict[str, Any]] = []
    for persona in PANELISTS:
        weights = {str(k): float(v) for k, v in (persona.get("weights") or {}).items()}
        bias = float(persona.get("bias") or 0.0)
        score = _persona_score(weights, avg, bias)
        focus = _focus_dim(persona, avg)
        rounds = []
        for (rnd, _item), dims in zip(pairs, dims_by_round):
            rounds.append({"round": rnd,
                           "score": _persona_score(weights, dims, bias) if dims else None})
        panelists.append({
            "id": persona["id"], "name": persona["name"],
            "title": persona["title"], "tagline": persona["tagline"],
            "score": score,
            "verdict": _verdict(score),
            "level": _level(score),
            "delta_vs_consensus": None,  # 共识分算出后回填
            "focus": DIM_LABELS[focus] if focus else None,
            "comment": _comment(persona, score, avg, focus, facts),
            "highlights": _highlights(facts, answered),
            "concerns": _concerns(facts, avg, skipped),
            "rounds": rounds,
        })

    scored = [p["score"] for p in panelists if p["score"] is not None]
    consensus_score = round(sum(scored) / len(scored), 1) if scored else None
    spread = round(max(scored) - min(scored), 1) if len(scored) >= 2 else (0.0 if scored else None)
    level = _spread_level(spread)
    divergence = _divergence(avg, spread)

    for p in panelists:
        if p["score"] is not None and consensus_score is not None:
            p["delta_vs_consensus"] = round(p["score"] - consensus_score, 1)

    return {
        "version": PANEL_VERSION,
        "panelists": panelists,
        "consensus": {
            "score": consensus_score,
            "spread": spread,
            "level": level,
            "verdict": _verdict(consensus_score),
            "summary": _summary(consensus_score, spread, level, skipped, divergence),
            "advice": _advice(avg, facts, skipped, divergence, job_skills),
        },
        "divergence": divergence,
        "answered": answered,
        "skipped": skipped,
    }


# ----------------------------------------------------------------
# 交给模型写「合议总结」的事实清单（模型不得改数）
# ----------------------------------------------------------------
def panel_prompt_facts(result: dict) -> str:
    """把 review() 结果压成一段 ≤600 字的事实清单，供路由层交给模型写「合议总结」。

    分数一律逐字带出（1 位小数），模型只负责组织语言，不得改数。
    """
    data = result if isinstance(result, dict) else {}
    cons = data.get("consensus") if isinstance(data.get("consensus"), dict) else {}

    def fmt(v: Any) -> str:
        num = _num(v)
        return "未评分" if num is None else f"{num:.1f}"

    cs = _num(cons.get("score"))
    sp = _num(cons.get("spread"))
    if cs is None:
        head = "共识 未评分（本场无有效作答）"
    else:
        head = f"共识 {cs:.1f} 分（{cons.get('verdict') or '未评'}）"
    spread_txt = f"{sp:.1f}" if sp is not None else "—"
    lines: list[str] = [
        f"版本 {data.get('version') or PANEL_VERSION}",
        f"{head}｜spread {spread_txt}（{cons.get('level') or '未评'}）｜"
        f"已答 {data.get('answered') or 0} 题/跳过 {data.get('skipped') or 0} 题",
    ]
    for p in data.get("panelists") or []:
        if not isinstance(p, dict):
            continue
        lines.append(f"{p.get('name') or '?'}（{p.get('title') or '?'}）"
                     f"{fmt(p.get('score'))} 分｜{p.get('verdict') or '未评'}"
                     f"｜{p.get('level') or '未评'}｜焦点 {p.get('focus') or '无'}")
    div = data.get("divergence")
    if cs is None:
        lines.append("无可评分数据：本场全部未作答")
    elif isinstance(div, dict):
        lines.append(f"分歧主因 {DIM_LABELS.get(str(div.get('dimension')), str(div.get('dimension')))}"
                     f"，加权贡献差 {fmt(div.get('gap'))} 分")
    else:
        lines.append("三人无显著分歧")
    for item in (cons.get("advice") or [])[:2]:
        lines.append(f"建议：{item}")
    text = "\n".join(lines)
    return text if len(text) <= 600 else text[:599] + "…"
