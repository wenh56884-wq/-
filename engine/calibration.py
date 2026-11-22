# engine/calibration.py
# 职责：面试官视角（评分校准）引擎——构造三位匿名候选人的作答（talker/doer/vague），
#       用 engine.interview.score_answer 算标准分，再按学生对三条答案的排序诊断评判偏误。
#       这是「让学生当一次面试官」的元认知训练：排序 → 揭晓标准分 → 暴露偏误。
#
# 为什么市面没有：所有 AI 面试产品都让你**被**面。但真正让人答题变准的，是当一次面试官——
#       你会立刻看清「什么答案听起来好、什么答案其实什么都没说」。这是教育学里的同伴评价
#       （peer assessment）与评分元认知训练，商业面试产品的商业模型（卖课时）里没有这一环。
#
# 三条答案的设计意图（本模块的灵魂）：
#       talker（话术型）：结构标记齐全、句句通顺、有职业感，但一个 rubric 关键词都不出现。
#           学生若读着觉得「这答案不错」，说明他正被结构话术带走——这是要暴露的核心偏误。
#       doer（实干型）：把 rubric 关键词嵌进具体动作与数字里，只带 1~2 个结构标记，口语化，
#           读起来像真实面试里「说得不太漂亮但确实干过」的人。
#       vague（空转型）：40~60 字，短、泛、没有信息量。
#       talker 与 doer 长度必须相当（都在 100~180 字之间），否则学生靠长度就能猜出来。
#
# 铁律：引擎定数，模型不参与。纯函数、无网络、无数据库、无 LLM、无 random——
#       短语选择一律用 hashlib.md5(question) 的字节取模，同题永远同结果；
#       rubric 为空 / keywords 为空 / 只有 1 个关键词 / struct_marks 为空 都不抛异常，
#       且 talker 与 doer 长度仍然相当；答案文本不含自指词、不含 markdown。

from __future__ import annotations

import hashlib
from typing import Any, Mapping, Sequence

from engine.interview import _norm, score_answer

CALIBRATION_VERSION = "calibration-v1"

PERSONAS: tuple[dict[str, str], ...] = (
    {"id": "talker", "label": "话术型", "hint": "结构漂亮，但把要点全绕开了"},
    {"id": "doer",   "label": "实干型", "hint": "要点踩得准，却不会包装"},
    {"id": "vague",  "label": "空转型", "hint": "两句说完，没有信息量"},
)

_PERSONA_LABEL: dict[str, str] = {p["id"]: p["label"] for p in PERSONAS}
# 标准分并列时的固定破并列顺序：talker < doer < vague
_PERSONA_ORDER: dict[str, int] = {p["id"]: i for i, p in enumerate(PERSONAS)}

# rubric 没给 struct_marks 时 talker 的兜底结构标记（顺序固定，截前 3 个）
_DEFAULT_MARKS: tuple[str, ...] = ("首先", "其次", "然后", "最后", "第一", "第二", "第三")
# 结构标记不足 3 个时的补位词（本身不是评分标记，只保句子通顺）
_MARK_PADS: tuple[str, ...] = ("接着", "再者", "另外")

# talker 的通用套话池：句句通顺、有职业感，但刻意避开高频考点词
# （问题/沟通/结果/目标/方案/流程/优先/确认/反馈/复盘/角色/负责/困难/解决/完成 等），
# 运行时还会按当前 rubric 关键词再过滤一遍，双保险保证「一个关键词都不出现」。
_TALKER_OPENERS: tuple[str, ...] = (
    "这个问题我分三层看。",
    "我会从整体到局部一层层说。",
    "这类事我有一套自己的拆法。",
)
_TALKER_PHRASES: tuple[str, ...] = (
    "把整件事拆成几个能落地的部分，一步一步往下推进",
    "想清楚每一块的分工和推进的顺序",
    "把各方面的情况都过一遍之后再动手",
    "多和有经验的人交流，少走一些弯路",
    "把时间和精力放在最要紧的那几块上",
    "边做边回头看，发现偏了就及时纠正",
    "每做完一块都回头检查一遍再继续",
    "把可能出岔子的地方提前都想到",
    "把要做的事情列清楚，一件一件来",
    "拿不准的地方多问一句，不硬扛",
)
_TALKER_EXTRAS: tuple[str, ...] = (
    "整个过程里我都会自己盯紧节奏",
    "中途发现偏差我会马上拉回来",
    "这三层走完基本就稳了",
    "方向上我不会跑偏",
)

# doer 的中段与补长句：具体动作 + 可核对的数字，绝不空谈
_DOER_MIDDLES: tuple[str, ...] = (
    "中间还专门拉了一次对齐，把各家的口径统一了下来。",
    "中间停了两天，把数全部对上才算真正收住。",
    "我们把每一步都写进了共享文档，谁来接手都能照着做。",
    "最难的一段是收尾，前后返了两版才定下来。",
)
_DOER_EXTRAS: tuple[str, ...] = (
    "后来这套做法被隔壁项目直接拿去用了。",
    "返工从一周两次降到几乎为零。",
    "那阵子每天下班前对一次进度，问题不过夜。",
)

# vague 的两条候选：40~60 字，短、泛、没信息量
_VAGUE_ANSWERS: tuple[str, ...] = (
    "这个我觉得按正常流程来就行，先把事情做完，中间遇到什么情况再随时调整，整体上看应该问题不大。",
    "这块我说不出太多细节，大概就是按部就班往前推，有什么情况再临场处理，一般不会有太大问题。",
)

_LEVEL_LABELS: dict[str, str] = {
    "sharp": "判断很准", "fair": "大体靠得住", "blunt": "还需要练眼力",
}

# 长度不是随便定的：engine.interview 的深度分档以 120 字为界（<30→0、<120→0.6、其余→1.0）。
# 话术型压在 120 字以内，才能做到「结构满分、深度拿不满、要点 0 命中」——
# 这正是现实里那种「听着挺像样，回头一想什么都没说」的候选人。
_TALKER_MAX = 120
_TALKER_LEN = (104, 119)
_DOER_LEN = (130, 169)

# 名词型结构标记（「背景/目标/行动/结果」）后面必须接「这块」才成句；
# 「首先/其次」这类副词型直接跟逗号即可。不加这一层判断，会写出「背景，要拿不准…」这种病句。
_NOMINAL_MARKS = frozenset({"背景", "目标", "行动", "结果", "现象", "原因", "措施", "收获"})


# ----------------------------------------------------------------
# 确定性工具（无 random：一切「选择」都来自题目 md5 的字节取模）
# ----------------------------------------------------------------
def _digest_of(question: str) -> bytes:
    return hashlib.md5(str(question or "").encode("utf-8")).digest()


def _b(digest: bytes, i: int, n: int) -> int:
    """digest 第 i 个字节对 n 取模；n<=0 时返回 0。"""
    if n <= 0:
        return 0
    return digest[i % len(digest)] % n


def _kw_list(rubric: Mapping[str, Any]) -> list[str]:
    """rubric 关键词：去重去空，最多取 6 个（契约口径）。"""
    if not isinstance(rubric, Mapping):
        return []
    kws: list[str] = []
    for k in rubric.get("keywords") or []:
        s = str(k).strip()
        if s and s not in kws:
            kws.append(s)
    return kws[:6]


def _marks_list(rubric: Mapping[str, Any], kws: Sequence[str]) -> list[str]:
    """talker 可用的结构标记：rubric 优先，不足用兜底补；撞上关键词的标记必须让位
    （score_answer 按「关键词是否出现在答案里」命中，标记里含关键词就等于送分）。"""
    raw: list[str] = []
    if isinstance(rubric, Mapping):
        for m in rubric.get("struct_marks") or []:
            s = str(m).strip()
            if s and s not in raw:
                raw.append(s)
    for m in _DEFAULT_MARKS:
        if m not in raw:
            raw.append(m)
    norm_kws = [k for k in (_norm(x) for x in kws) if k]
    return [m for m in raw if not any(k in _norm(m) for k in norm_kws)][:3]


def _kw_free(phrases: Sequence[str], norm_kws: Sequence[str]) -> list[str]:
    """过滤掉包含任何关键词的短语（talker 专用）。"""
    return [p for p in phrases if not any(k in _norm(p) for k in norm_kws)]


def _int_or_none(v: Any) -> int | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and float(v).is_integer():
        return int(v)
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def _round_key(v: Any) -> Any:
    """轮次键归一：2 / 2.0 / "2" 都归 2，保证 picks 与 block 能对上。"""
    n = _int_or_none(v)
    if n is not None:
        return n
    if v is None:
        return None
    return str(v).strip()


def _clip_frag(answer: str, limit: int = 26) -> str:
    """回引用答案片段：逐字来自原文（不加省略号，防虚构校验可比对）。

    优先退到最近的句读处再截，否则诊断语里会出现「…当时兴趣那段最卡，我先」这种断头句。
    """
    text = str(answer or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    for i in range(len(cut) - 1, max(4, limit // 2) - 1, -1):
        if cut[i] in "。！？；，、":
            return cut[:i + 1]
    return cut


def _rounds_txt(rounds: Sequence[Any]) -> str:
    """[2,3] -> 第 2、3 题；[2] -> 第 2 题；空 -> 本题。"""
    rs = [str(r) for r in rounds if r is not None]
    if not rs:
        return "本题"
    return "第 " + "、".join(rs) + " 题"


# ----------------------------------------------------------------
# build_candidates：三位候选人的作答（确定性模板 + md5 选短语）
# ----------------------------------------------------------------
def _talker_answer(kws: Sequence[str], marks: Sequence[str], digest: bytes) -> str:
    """话术型：结构标记齐全 + 通用套话，一个 rubric 关键词都不出现。

    长度压在 120 字以内（见 _TALKER_MAX 的注释），所以它结构分 25、深度分 15、要点 0 命中。
    """
    norm_kws = [k for k in (_norm(x) for x in kws) if k]
    openers = _kw_free(_TALKER_OPENERS, norm_kws) or ["我分三层说。"]
    pool = _kw_free(_TALKER_PHRASES, norm_kws) or list(_TALKER_PHRASES)
    extras = _kw_free(_TALKER_EXTRAS, norm_kws) or list(_TALKER_EXTRAS)

    opener = openers[_b(digest, 0, len(openers))]
    off = _b(digest, 1, len(pool))
    picked = [pool[(off + t) % len(pool)] for t in range(min(4, len(pool)))]
    while len(picked) < 4:
        picked.append(picked[len(picked) % len(picked)])

    marks_used = list(marks)
    for pad in _MARK_PADS:
        if len(marks_used) >= 3:
            break
        if pad not in marks_used and not any(k in _norm(pad) for k in norm_kws):
            marks_used.append(pad)

    layers: list[str] = []
    for t in range(3):
        mark = marks_used[t] if t < len(marks_used) else ""
        if not mark:
            layers.append(picked[t])
            continue
        lead = (mark + "这块，") if mark in _NOMINAL_MARKS else (mark + "，")
        layers.append(lead + ("要" if t == 0 else "") + picked[t])
    base = opener + "；".join(layers) + "。总的来说，" + picked[3] + "，我有信心做好。"

    used: list[str] = []
    i = 2
    while len(used) < 3:
        cand = extras[_b(digest, i, len(extras))]
        trial = base + "".join(x + "。" for x in used) + cand + "。"
        if len(trial) >= _TALKER_MAX:      # 一旦跨过 120 字深度分就跳档，宁可少说一句
            break
        used.append(cand)
        i += 1
    return base + "".join(x + "。" for x in used)


def _doer_answer(kws: Sequence[str], digest: bytes) -> str:
    """实干型：关键词嵌进具体动作与数字，只带 1~2 个结构标记，130~169 字。

    句式刻意写成「当时{术语}那块最卡」——只有这样真实技术术语（机器学习、数据漂移、基线）
    嵌进去才通顺。如果术语是「负责」「背景」这种结构词，说明选题选错了（见路由层按硬关键词排序）。
    """
    ks = [str(k) for k in kws][:6]
    if ks:
        slots = 6 if len(ks) >= 6 else max(4, len(ks))
        seq = [ks[i % len(ks)] for i in range(slots)]
        parts = [f"这块我们真做过。当时{seq[0]}那块最卡，我先把{seq[1]}从头理了一遍"]
        if len(seq) >= 3:
            parts.append(f"，接着把{seq[2]}补上")
        if len(seq) >= 4:
            parts.append(f"，最后拿{seq[3]}做了一次全量校验")
        if len(seq) >= 5:
            parts.append(f"；{seq[4]}那块是后补的，单独立了一版")
        if len(seq) >= 6:
            parts.append(f"，{seq[5]}也同步记了下来")
        head = "".join(parts) + "。"
    else:
        head = ("这块我们真做过。当时最难的是收尾那段，我把手头的活拆成三份，一天清一份，"
                "再腾出半天专门核对，前后改了三版。")

    middle = _DOER_MIDDLES[_b(digest, 2, len(_DOER_MIDDLES))]
    tail = "最后两周收口，返工率从30%降到8%。"
    used: list[str] = []
    i = 5
    while len(head + middle + "".join(used) + tail) < _DOER_LEN[0] and len(used) < 3:
        cand = _DOER_EXTRAS[_b(digest, i, len(_DOER_EXTRAS))]
        i += 1
        if cand in used:
            continue
        used.append(cand)
    text = head + middle + "".join(used) + tail
    if len(text) > _DOER_LEN[1]:
        text = head + tail   # 关键词特别长时砍中段，保住动作与数字
    return text


def build_candidates(question: str, rubric: Mapping[str, Any]) -> list[dict]:
    """构造三位候选人的作答：[{"id":"talker","answer":str}, ...]，顺序固定 talker/doer/vague。

    确定性：同一道题（question 逐字相同 + 同一 rubric）永远得到同样的三条答案。
    rubric 为空 / keywords 为空 / 只有 1 个关键词 / struct_marks 为空 都不抛异常，
    且 talker 与 doer 长度仍然相当。
    """
    q = str(question or "")
    digest = _digest_of(q)
    kws = _kw_list(rubric)
    marks = _marks_list(rubric, kws)
    return [
        {"id": "talker", "answer": _talker_answer(kws, marks, digest)},
        {"id": "doer", "answer": _doer_answer(kws, digest)},
        {"id": "vague", "answer": _VAGUE_ANSWERS[_b(digest, 3, len(_VAGUE_ANSWERS))]},
    ]


# ----------------------------------------------------------------
# score_candidates：标准分（直接复用 engine.interview.score_answer，不自建评分）
# ----------------------------------------------------------------
def _ranks_of(cands: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """standard_rank：按 standard 降序；并列按 talker<doer<vague 固定顺序稳定破并列。"""
    valid = [c for c in cands if c.get("standard") is not None]
    order = sorted(valid, key=lambda c: (-float(c["standard"]),
                                         _PERSONA_ORDER.get(str(c.get("id") or ""), 9)))
    return {str(c["id"]): r for r, c in enumerate(order, 1)}


def score_candidates(candidates: Sequence[Mapping], rubric: Mapping,
                     evidence: Sequence[str]) -> list[dict]:
    """用 engine.interview.score_answer 算标准分，返回带 standard / dims / standard_rank 的列表。

    dims 里各分项保留 score_answer 的原始 2 位小数；standard 即其 score（2 位小数）。
    空答案（score_answer 返回 None）→ standard 与 standard_rank 为 None，缺失不冒充。
    """
    rub = rubric if isinstance(rubric, Mapping) else {}
    ev = [str(t) for t in (evidence or []) if t]
    out: list[dict] = []
    for c in candidates or []:
        if not isinstance(c, Mapping):
            continue
        cid = str(c.get("id") or "")
        answer = str(c.get("answer") or "")
        label = str(c.get("label") or _PERSONA_LABEL.get(cid, cid))
        detail = score_answer(answer, rub, ev)
        if detail is None:
            out.append({"id": cid, "label": label, "answer": answer,
                        "standard": None, "standard_rank": None,
                        "dims": {}, "keyword_hits": [], "keyword_missed": []})
            continue
        out.append({
            "id": cid, "label": label, "answer": answer,
            "standard": detail["score"],
            "standard_rank": None,
            "dims": {"keyword_score": detail["keyword_score"],
                     "struct_score": detail["struct_score"],
                     "depth_score": detail["depth_score"],
                     "evidence_score": detail["evidence_score"]},
            "keyword_hits": list(detail.get("keyword_hits") or []),
            "keyword_missed": list(detail.get("keyword_missed") or []),
        })
    ranks = _ranks_of(out)
    for c in out:
        c["standard_rank"] = ranks.get(c["id"])
    return out


# ----------------------------------------------------------------
# judge：按学生的排序诊断评判偏误
# ----------------------------------------------------------------
def _as_blocks(candidates: Sequence[Mapping]) -> list[dict[str, Any]]:
    """把入参规整成题块列表：[{"round","question","candidates":[...]}]。

    契约主形态是 score_candidates 按题组装后的块；若直接传入扁平的候选人列表
    （无 candidates 键），视为单题（round=None, question=""）。
    """
    if not candidates:
        return []
    if all(isinstance(c, Mapping) and "candidates" in c for c in candidates):
        blocks: list[dict[str, Any]] = []
        for b in candidates:
            if not isinstance(b, Mapping):
                continue
            blocks.append({
                "round": b.get("round"),
                "question": str(b.get("question") or ""),
                "candidates": [c for c in (b.get("candidates") or []) if isinstance(c, Mapping)],
            })
        return blocks
    return [{"round": None, "question": "",
             "candidates": [c for c in candidates if isinstance(c, Mapping)]}]


def _my_ranks(round_picks: Sequence[Mapping], cands: Sequence[Mapping]) -> dict[str, int]:
    """该题的 my_rank 映射。rank 不在 {1,2,3}、同一 id 重复、同一 rank 重复 → 整题作废（返回空）。"""
    ids = {str(c.get("id") or "") for c in cands}
    out: dict[str, int] = {}
    seen_ids: set[str] = set()
    seen_ranks: set[int] = set()
    for p in round_picks:
        if not isinstance(p, Mapping):
            return {}
        cid = str(p.get("id") or "")
        r = _int_or_none(p.get("rank"))
        if cid not in ids or r not in (1, 2, 3):
            return {}
        if cid in seen_ids or r in seen_ranks:
            return {}
        seen_ids.add(cid)
        seen_ranks.add(r)
        out[cid] = r
    return out


def _verdict_of(block_items: list[dict], raw_by_id: dict[str, Mapping],
                tb: int, db: int) -> str:
    """单题揭晓语：点名把谁排错、错在哪个要点上，必须落到具体内容。"""
    valid = [it for it in block_items if it["my_rank"] is not None]
    if not valid:
        return "这一题没有有效排序，下面只看引擎标准分。"
    t = raw_by_id.get("talker")
    d = raw_by_id.get("doer")
    if tb > 0 and t is not None:
        missed = len(t.get("keyword_missed") or [])
        reason = (f"它结构齐全，但 {missed} 个要点一个都没踩到。"
                  if missed else "它结构齐全，却没有踩到任何要点。")
        talker_my = next((it["my_rank"] for it in block_items if it["id"] == "talker"), None)
        return f"你把话术型排到了第 {talker_my}：{reason}"
    if db > 0 and d is not None:
        hits = len(d.get("keyword_hits") or [])
        reason = (f"它说得糙，但 {hits} 个要点都踩到了。"
                  if hits else "它说得糙，没有可核对的要点。")
        doer_my = next((it["my_rank"] for it in block_items if it["id"] == "doer"), None)
        return f"你把实干型排到了第 {doer_my}：{reason}"
    mine_top = next((it for it in valid if it["my_rank"] == 1), None)
    std_top = next((it for it in block_items if it["standard_rank"] == 1), None)
    if mine_top and std_top and mine_top["id"] == std_top["id"]:
        return f"这一题你和标准分判断一致：第一名都是{mine_top['label']}。"
    if mine_top and std_top:
        return (f"这一题你的第一是{mine_top['label']}，标准分的第一是{std_top['label']}"
                f"——对照三条答案里谁踩到的要点多，再想一层。")
    return "这一题已揭晓标准分，对照看看差在哪一条要点上。"


def judge(picks: Sequence[Mapping], candidates: Sequence[Mapping]) -> dict:
    """按学生的排序揭晓标准分并诊断评判偏误。纯函数，不改入参。

    picks: [{"round":int,"id":"talker","rank":int}]（单题块时 round 可省），
           rank ∈ {1,2,3} 且同一题内互不重复；重复 → 该题所有项 my_rank=None，不影响其它题。
    candidates: score_candidates 的输出按题组装的块（含 standard / standard_rank / dims）。

    返回契约第 14 节结构：version/accuracy/level/level_label/items/biases/insights/next_drill。
    """
    blocks = _as_blocks(candidates)
    single = len(blocks) == 1
    grouped: dict[Any, list[Mapping]] = {}
    for p in picks or []:
        if not isinstance(p, Mapping):
            continue
        rnd = p.get("round")
        if rnd is None and single:
            rnd = blocks[0].get("round")
        grouped.setdefault(_round_key(rnd), []).append(p)

    items: list[dict] = []
    devs: list[int] = []
    talker_bias_total = doer_bias_total = harsh_total = lenient_total = 0
    talker_evidence: list[tuple[Any, str, int]] = []
    doer_evidence: list[tuple[Any, str, int]] = []
    strict_evidence: list[tuple[Any, str]] = []
    loose_evidence: list[tuple[Any, str]] = []
    top_refs: list[tuple[Any, str, str]] = []

    for block in blocks:
        rnd = block["round"]
        cands = block["candidates"]
        raw_by_id = {str(c.get("id") or ""): c for c in cands}
        std_rank = _ranks_of(cands)
        my_rank = _my_ranks(grouped.get(_round_key(rnd), []), cands)

        block_items: list[dict] = []
        for c in cands:
            cid = str(c.get("id") or "")
            block_items.append({
                "id": cid,
                "label": str(c.get("label") or _PERSONA_LABEL.get(cid, cid)),
                "answer": str(c.get("answer") or ""),
                "standard": c.get("standard"),
                "standard_rank": std_rank.get(cid),
                "my_rank": my_rank.get(cid),
                "dims": dict(c.get("dims") or {}),
                "revealed": True,
            })

        by_id = {it["id"]: it for it in block_items}
        tb_add = db_add = 0
        t, d = by_id.get("talker"), by_id.get("doer")
        if (t and t["my_rank"] is not None and t["standard_rank"] is not None
                and t["my_rank"] < t["standard_rank"]):
            tb_add = t["standard_rank"] - t["my_rank"]
            talker_evidence.append((rnd, _clip_frag(t["answer"]),
                                    len((raw_by_id.get("talker") or {}).get("keyword_missed") or [])))
        if (d and d["my_rank"] is not None and d["standard_rank"] is not None
                and d["my_rank"] > d["standard_rank"]):
            db_add = d["my_rank"] - d["standard_rank"]
            doer_evidence.append((rnd, _clip_frag(d["answer"]),
                                  len((raw_by_id.get("doer") or {}).get("keyword_hits") or [])))
        talker_bias_total += tb_add
        doer_bias_total += db_add

        # harsh/lenient：本题既没有高估话术型也没有低估实干型时，才看整体偏差方向
        if tb_add == 0 and db_add == 0:
            qdevs = [(it["my_rank"] - it["standard_rank"], it["answer"]) for it in block_items
                     if it["my_rank"] is not None and it["standard_rank"] is not None]
            if qdevs:
                avg = sum(x for x, _ in qdevs) / len(qdevs)
                if avg > 0:
                    harsh_total += 1
                    strict_evidence.append((rnd, _clip_frag(max(qdevs, key=lambda x: x[0])[1])))
                elif avg < 0:
                    lenient_total += 1
                    loose_evidence.append((rnd, _clip_frag(min(qdevs, key=lambda x: x[0])[1])))

        devs += [abs(it["my_rank"] - it["standard_rank"]) for it in block_items
                 if it["my_rank"] is not None and it["standard_rank"] is not None]
        std_top = next((it for it in block_items if it["standard_rank"] == 1), None)
        if std_top:
            top_refs.append((rnd, std_top["label"], _clip_frag(std_top["answer"])))

        items.append({"round": rnd, "question": block["question"],
                      "candidates": block_items,
                      "verdict": _verdict_of(block_items, raw_by_id, tb_add, db_add)})

    biases: list[dict[str, str]] = []
    if talker_evidence:
        rnd, frag, missed = talker_evidence[0]
        biases.append({
            "key": "talker_bias", "label": "结构偏好",
            "detail": (f"{_rounds_txt([r for r, _, _ in talker_evidence])}你把「{frag}」排到了标准分前面："
                       f"结构齐全，但 {missed} 个要点一个没踩到。"),
            "tip": "先听要点，再看结构：结构只是包装。",
        })
    if doer_evidence:
        rnd, frag, hits = doer_evidence[0]
        biases.append({
            "key": "doer_bias", "label": "实干低估",
            "detail": (f"{_rounds_txt([r for r, _, _ in doer_evidence])}你把「{frag}」往后排了："
                       f"它说得糙，但 {hits} 个要点都嵌在动作和数字里。"),
            "tip": "先找具体做了什么、结果是什么，再听它说得顺不顺。",
        })
    if harsh_total > 0 and strict_evidence:
        rnd, frag = strict_evidence[0]
        biases.append({
            "key": "harsh", "label": "整体偏严",
            "detail": f"{_rounds_txt([r for r, _ in strict_evidence])}你整体把答案往低排了，比如「{frag}」的实际水平比你给的名次更靠前。",
            "tip": "评分前先把每条答案踩到的要点数出来，再定名次。",
        })
    if lenient_total > 0 and loose_evidence:
        rnd, frag = loose_evidence[0]
        biases.append({
            "key": "lenient", "label": "整体偏松",
            "detail": f"{_rounds_txt([r for r, _ in loose_evidence])}你整体把答案往高排了，比如「{frag}」并没有踩到那么多要点。",
            "tip": "对听起来顺的答案多问一句：它到底答到了哪个要点？",
        })

    if not devs:
        return {"version": CALIBRATION_VERSION,
                "accuracy": None, "level": None, "level_label": None,
                "items": items, "biases": biases,
                "insights": ["还没排序，没有可校准的判断。"],
                "next_drill": "先把三题各排一次名次再回来：重点听每条答案踩到了几个要点，而不是说得顺不顺。"}

    accuracy = round(100.0 * (1.0 - (sum(devs) / len(devs)) / 2.0), 1)
    level = "sharp" if accuracy >= 85 else ("fair" if accuracy >= 65 else "blunt")
    dev_mean = sum(devs) / len(devs)

    insights: list[str] = []
    if talker_evidence:
        _, frag, missed = talker_evidence[0]
        insights.append(f"最典型的一次：{_rounds_txt([r for r, _, _ in talker_evidence])}你被「{frag}」的结构带走"
                        f"——结构标记齐全，但 {missed} 个要点一个没踩到。")
    if doer_evidence:
        _, frag, hits = doer_evidence[0]
        insights.append(f"你在{_rounds_txt([r for r, _, _ in doer_evidence])}把「{frag}」往后排了："
                        f"它说得糙，但 {hits} 个要点都嵌在动作和数字里。")
    if accuracy >= 85:
        insights.append(f"你的名次与标准分平均只差 {dev_mean:.1f} 档：你已经在按要点听答案，而不是按包装。")
    elif accuracy >= 65:
        insights.append(f"判断大体靠得住，平均还差 {dev_mean:.1f} 档：差距主要来自对「听起来顺」的容忍度。")
    else:
        insights.append(f"平均差 {dev_mean:.1f} 档：先练「数要点」再排名次，别让流畅度替内容说话。")
    while len(insights) < 2:
        if top_refs:
            rnd, label, frag = top_refs[0]
            insights.append(f"对照着看：{_rounds_txt([r for r, _, _ in top_refs])}标准分最高的是{label}，"
                            f"赢在「{frag}」这些具体内容上。")
        else:
            insights.append("把每条答案先数出踩到的要点数、再排名次，眼力会快很多。")
    insights = insights[:3]

    if talker_bias_total > 0:
        drill = ("把你上一场面试里最顺的一段回答重写：删掉所有形容词和结构词，"
                 "只留动作、数字和要点，再给自己重打一次分。")
    elif doer_bias_total > 0:
        drill = "找一段你自己的答案，把踩到的要点逐个标出来：标不出 3 个就重写，写到能标出为止。"
    elif lenient_total > 0:
        drill = "给自己的名次加一道闸：每条答案先数出踩到的要点数，数不出 2 个的不许排进前二。"
    elif harsh_total > 0:
        drill = "把「说得糙」和「没答到」分开：排名前先问它踩到了几个要点，而不是听顺不顺。"
    elif accuracy >= 85:
        drill = "保持这个眼力：下一场模拟面完，先自己预测每题得分再看引擎分，误差控制在 5 分内。"
    else:
        drill = "拿本页三条答案再排一次：先遮住结构词，只数每条踩到的要点数，再看标准分对不对得上。"

    return {"version": CALIBRATION_VERSION,
            "accuracy": accuracy, "level": level, "level_label": _LEVEL_LABELS[level],
            "items": items, "biases": biases, "insights": insights, "next_drill": drill}
