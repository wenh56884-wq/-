# engine/shadow.py
# 职责：示范回答骨架——只给结构与提示，不给整段范文（防幻觉、防背稿）。
# 铁律：引擎定数，模型说话。纯函数、无随机、无网络、无 LLM；模板拼装，不生成新事实。
# 缺失不冒充：rubric 没有 keywords 就用简历词兜底，都没有就给空列表，绝不编造要点。
#
# 口径澄清（契约未写死、按最合理方式定，改动须同步契约）：
# 1) 每一条提示、开场句、坑点都拆成 30 字以内的短句；不要长句，避免学生直接背整段范文。
# 2) 未知题型按 STAR 四段兜底（信息量最大、最通用），帧永不为空。
# 3) must_include 直接取 rubric.keywords 前 4 个；为空时用 resume_terms 前 4 个补位，
#    两者都为空则返回 []——宁可少提示，也不凭空造考点。

from __future__ import annotations

SHADOW_VERSION = "shadow-v1"

# 各题型的骨架：key 用短字母，前端按 key 排序渲染
_FRAMES: dict[str, list[tuple[str, str, str]]] = {
    "project": [
        ("S", "情境", "一句话交代项目背景：时间、团队、要解决的问题。"),
        ("T", "任务", "说清你的角色与目标，别用「我们」，用「我」。"),
        ("A", "行动", "挑 2 个关键动作，按先后顺序讲怎么做的。"),
        ("R", "结果", "给结果：上线了吗、数据变化多少、你学到什么。"),
    ],
    "scenario": [
        ("S", "情境", "先复述场景与约束：时间、资源、谁在等结果。"),
        ("J", "判断", "说出判断标准：先保什么、后放什么。"),
        ("A", "动作", "给 2~3 个动作，说明先找谁、怎么沟通。"),
        ("R", "结果", "补结果与复盘：事情成了吗、下次改哪步。"),
    ],
    "stress": [
        ("C", "承认", "先承认对方说的事实，别急着反驳。"),
        ("T", "转译", "把质疑转成你的证据：我理解您担心的是……"),
        ("E", "证据", "给一个可核对的事实，短句说完就停。"),
    ],
    "motivation": [
        ("M", "动机", "说一个具体触发点：哪件事让你想做这行。"),
        ("F", "匹配", "用 1 段经历证明你匹配，别只喊热爱。"),
        ("P", "规划", "给 1~3 年规划，落到可检查的动作。"),
    ],
    "counter": [
        ("R", "复述", "先复述刚才的关键点，证明你听进去了。"),
        ("A", "回应", "给一句具体回应：认同哪点、补充哪点。"),
        ("Q", "回问", "问一个与岗位相关的问题，别问薪资假期。"),
    ],
}

_PITFALLS: dict[str, list[str]] = {
    "project": ["只讲团队做了什么，听不出你的贡献", "结果只说「顺利完成」，没有数字"],
    "scenario": ["上来就说「我会积极沟通」，没有动作", "只给方案，不交代先后顺序与取舍"],
    "stress": ["情绪上头开始辩解，越说越虚", "承认完就没了，不补证据"],
    "motivation": ["只谈公司名气，不谈岗位本身", "规划停在「努力学习」，没有时间点"],
    "counter": ["反问变成「没有问题」，白白丢分", "问的是薪资假期，显得只关心待遇"],
}

_OPENINGS: dict[str, str] = {
    "project": "这个项目我分四段说：背景、任务、动作、结果。",
    "scenario": "我会先确认目标和优先级，再决定动作。",
    "stress": "您这个担心我理解，我用一件事回答。",
    "motivation": "我想做这行，起因是一件很具体的事。",
    "counter": "关于您刚提到的那点，我想先确认一下。",
}

# numbers_hint 也拆成短句：两段各不超过 30 字
_NUMBERS_HINT = "补 1 个可核对的数字（人数、耗时、提升比）。没有数字就写具体动作。"
_NUMBERS_HINT_COUNTER = "回问压到 1 个问题，问完就停。别连着问三个。"

_ALIASES: dict[str, str] = {"major": "project"}


def _frame_list(qtype: str) -> list[tuple[str, str, str]]:
    key = _ALIASES.get(str(qtype or "").strip().lower(), str(qtype or "").strip().lower())
    return _FRAMES.get(key) or _FRAMES["project"]


def _must_include(rubric: dict | None, resume_terms: list[str] | None) -> list[str]:
    """≤4 条，去重保序：rubric.keywords 优先，为空时用简历词兜底。"""
    kws: list[str] = []
    if isinstance(rubric, dict):
        kws = [str(k) for k in (rubric.get("keywords") or [])]
    terms = [str(t) for t in (resume_terms or [])]
    seen: set[str] = set()
    out: list[str] = []
    for raw in kws + terms:
        s = raw.strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
        if len(out) >= 4:
            break
    return out


def shadow(qtype: str, rubric: dict, resume_terms: list[str] | None = None) -> dict:
    """给出「回答骨架」，不生成整段范文（防幻觉、防背稿）。

    返回：
    {"version":"shadow-v1",
     "frames": [{"key":"S","label":"情境","hint":"…"}],   # STAR 或 观点-论据-结论
     "must_include": ["…"],        # ≤4 个，直接取 rubric.keywords
     "numbers_hint": "…",
     "pitfalls": ["…", "…"],       # 2 条
     "opening": "…"}
    """
    qkey = _ALIASES.get(str(qtype or "").strip().lower(), str(qtype or "").strip().lower())
    frames = [{"key": k, "label": label, "hint": hint} for k, label, hint in _frame_list(qtype)]
    pitfalls = list(_PITFALLS.get(qkey) or _PITFALLS["project"])[:2]
    opening = _OPENINGS.get(qkey) or _OPENINGS["project"]
    numbers_hint = _NUMBERS_HINT_COUNTER if qkey == "counter" else _NUMBERS_HINT

    return {
        "version": SHADOW_VERSION,
        "frames": frames,
        "must_include": _must_include(rubric, resume_terms),
        "numbers_hint": numbers_hint,
        "pitfalls": pitfalls,
        "opening": opening,
    }
