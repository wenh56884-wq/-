# engine/group.py
# 职责：无领导小组讨论（群面）模拟引擎——议题生成 / 主持人开场 / AI 候选人发言 / 学生发言 / 确定性评估。
# 为什么市面没有：所有 AI 面试产品都只做 1v1，而无领导小组讨论是国内校招特有环节，
#   学生最怕、最缺练习机会。这里做「学生 + 3 个 AI 候选人」的四方抢话局，
#   三个 AI 候选人有人设差异（破冰 / 数据 / 搅局），并且必须互相点名回应。
# 降级策略：模型只负责组织语言。ai_turn 的 speak 可注入（路由带 20s 超时），
#   默认走 agents.llm.generate_reply；任何异常、空返回、非字符串一律回落 CANDIDATE_FALLBACK
#   模板句（每个角色 3 句按已发言次数轮换），断网也能跑完整场，绝不把模型故障抛给上层。
# 铁律：引擎定数，模型说话。evaluate 只读 state 里的文本，不调模型、无随机；
#   状态必须 json.dumps 可序列化（只有 dict/list/str/int/float），且任何函数都不修改传入 state。
#
# 口径澄清（契约未写死、按最合理方式定，改动须同步契约与本注释）：
# 1) new_points 取「此前无人说过」的严格读法：某议题关键词在全场第一次出现是在学生的发言里
#    才算新观点；AI 已经先说过的关键词一律不计（哪怕学生后面重复强调）。
# 2) interrupted 无法从顺序记录里真实回放抢话，改用文本标记（打断/插一句/我先说/等一下）
#    计数，并在 metrics 里如实给出该口径，不硬编 0 也不臆造。
# 3) 未知 candidate_id 抛 ValueError（路由层可转 400），不返回脏 state。
# 4) 四个分数是「指标 → 线性映射 → clamp 0~100 → 四舍五入取整」，overall 用四个整数分
#    加权后再四舍五入，前后一致，前端不会出现「四个分算不出 overall」的情况。

from __future__ import annotations

import re
from typing import Any, Callable, Mapping, Sequence

from engine.interview import _norm

GROUP_VERSION = "group-v1"
MINUTES_DEFAULT = 12

CANDIDATES: list[dict[str, str]] = [
    {"id": "ice", "name": "林一", "role": "破冰者", "tagline": "先把框架立起来", "color": "#38bdf8"},
    {"id": "data", "name": "赵敏", "role": "数据派", "tagline": "没有数字就没有说服力", "color": "#34d399"},
    {"id": "spark", "name": "王锐", "role": "搅局者", "tagline": "专问‘凭什么’", "color": "#fb923c"},
]

_CAND_BY_ID: dict[str, dict[str, str]] = {c["id"]: c for c in CANDIDATES}
_NAMES: dict[str, str] = {c["id"]: c["name"] for c in CANDIDATES}
_NAMES["student"] = "我"
# AI 互称用全名，称呼学生用「同学」（「我回应一下你」不成句）
_ADDRESS: dict[str, str] = {c["id"]: c["name"] for c in CANDIDATES}
_ADDRESS["student"] = "同学"

_SPEAKERS = ("ice", "data", "spark", "student")

# 契约给定的收口词表，顺序不可改（evaluate 的 converge_marks 逐词计数）
CONVERGE_WORDS: tuple[str, ...] = ("总结", "归纳", "共识", "建议我们", "综上", "分三步", "统一")

# 结构标记（分点 / 分层叙述），用于 structure 分
STRUCT_MARKS: tuple[str, ...] = (
    "首先", "其次", "然后", "最后", "第一", "第二", "第三",
    "一是", "二是", "一方面", "另一方面", "因此", "所以",
)

# 抢话文本标记（interrupted 的口径，见模块头注释第 2 条）。
# 只收明确的打断语；「我先说一句」这类抢话筒的中性开场不算。
_INTERRUPT_MARKS: tuple[str, ...] = ("打断", "插一句", "等一下", "先别急", "让我说完")

# 议题通用词：任何行业都成立，不是技术名词，用于 skills 不足时补齐 keywords
TOPIC_UNIVERSAL: tuple[str, ...] = (
    "成本", "效率", "风险", "优先级", "用户需求", "交付", "质量", "预算", "时间",
)

# 行业通用词（按行业名包含匹配，纯业务词，不编造技术栈）
_DOMAIN_POOL: dict[str, tuple[str, ...]] = {    "互联网": ("用户增长", "留存", "迭代", "数据指标"),
    "软件": ("交付", "迭代", "质量", "成本"),
    "计算机": ("交付", "迭代", "质量", "成本"),
    "金融": ("合规", "风险", "收益", "成本"),
    "银行": ("合规", "风险", "收益", "成本"),
    "制造": ("产能", "良率", "交付", "成本"),
    "机械": ("产能", "良率", "交付", "成本"),
    "教育": ("课程", "师资", "学习效果", "成本"),
    "医疗": ("合规", "安全", "效率", "成本"),
    "快消": ("渠道", "库存", "复购", "成本"),
    "咨询": ("假设", "验证", "结论", "成本"),
    "运营": ("用户增长", "留存", "活动", "成本"),
    "市场": ("渠道", "转化", "预算", "成本"),
    "人力": ("招聘", "培养", "留存", "成本"),
}

# 公开词表：make_topic 只允许从这里（+ 传入的 skills）取关键词，便于测试「不编造名词」
TOPIC_VOCAB: tuple[str, ...] = tuple(dict.fromkeys(
    TOPIC_UNIVERSAL + tuple(w for words in _DOMAIN_POOL.values() for w in words)))

# 议题场景模板：12 种不同讨论题型（排期取舍 / 需求冲突 / 预算分配 / 方案评审 /
# 数据口径之争 / 突发应对 / 跨部门冲突 / 渠道取舍 / 复盘改进 / 招聘标准 / 定价决策 / 上线决策）。
# 选取：按岗位名稳定求和 + seed 取模——seed 由路由层每次开局随机给，
# 同一岗位不再永远同一道题；种子相同仍得到相同议题（引擎可复现铁律不破）。
_TOPIC_TEMPLATES: tuple[tuple[str, str], ...] = (
    ("项目排期取舍",
     "{job}团队只有 4 个人、2 周时间，既要保证「{skill_a}」这块不出问题，又要按时交付，"
     "还要把成本压住。请讨论先做什么、后做什么，并给出取舍依据。"),
    ("需求冲突处理",
     "上线前三天，客户临时追加需求，同时「{skill_a}」相关的稳定性问题冒了出来。"
     "团队只能先救一头，请讨论优先级与判断标准。"),
    ("培养预算分配",
     "部门只有一笔新人培养预算，投在「{skill_a}」还是「{skill_b}」上争议很大。"
     "请讨论怎么分、按什么依据分。"),
    ("方案评审分歧",
     "有人主张用「{skill_a}」快速出一版验证，有人坚持先把「{skill_b}」打磨到位。"
     "请讨论哪种做法更适合只有 4 个人的校招团队，并落成结论。"),
    ("数据口径之争",
     "两份报表对不上：「{skill_a}」口径算出的转化率差了 8 个百分点，周会马上要汇报，"
     "两个口径的支持者各不相让。请讨论先信哪个、怎么定一个大家都认的口径。"),
    ("突发应对",
     "周一早上「{skill_a}」出了故障，影响了一半用户；与此同时另一个项目的截止日就是明天。"
     "只有 4 个人，请讨论怎么分工、先保哪头、对外怎么说。"),
    ("跨部门协作冲突",
     "「{skill_a}」的项目需要另一个部门配合，但对方说排期已满只能给 2 天，"
     "而按现在的方案至少要一周。请讨论怎么破局：改方案、抢排期还是换路径。"),
    ("渠道取舍",
     "推广预算只够投一个渠道：投「{skill_a}」相关的老渠道稳定但增长见顶，"
     "新渠道数据好看但只有一个月的样本。请讨论怎么选、要补哪些证据。"),
    ("复盘改进",
     "上个月的项目延期了 10 天，复盘会上有人说「{skill_a}」环节没卡住，"
     "有人说是需求改太多。请讨论真正的原因排序，并给出一条下个月就能落地的改进动作。"),
    ("招聘标准之争",
     "只能发一个 offer：候选人甲「{skill_a}」很强但协作口碑一般，"
     "候选人乙各方面 80 分但没有突出项。请讨论团队现在最缺什么、选谁、依据是什么。"),
    ("定价决策",
     "新产品要定价：按成本加成最稳，但竞品比自己便宜 20%；"
     "「{skill_a}」是卖点，要不要为它定高价。请讨论定价策略与理由。"),
    ("上线决策",
     "「{skill_a}」功能测试通过率 92%，剩余问题都不致命但用户能感知；"
     "市场部希望赶上这个周末的节点。请讨论按时上线还是再修一轮，给出判断标准。"),
)

# 每个角色的降级模板句（3 句轮换，按该角色已发言次数取模）。
# {peer} 由最近一位其他发言人替换——离线也能演出「互相点名」的效果。
CANDIDATE_FALLBACK: dict[str, tuple[str, ...]] = {
    "ice": (
        "我先把框架立一下：这事可以分三个维度看，{peer}刚说的先记上，"
        "我们按优先级、成本、落地难度逐条过，最后收敛成一个结论。",
        "时间过半了，我建议先收敛：前两点争议最小，先定下来，第三点留四分钟，"
        "{peer}你看要不要补一个反例。",
        "我补一句流程上的：如果最后五分钟还在争第三点，我们就按「先做能验证的」投票，"
        "别再展开新话题了。",
    ),
    "data": (
        "我先接{peer}的话给个口径：同类项目一般 3 个人做 2 周，成本两万上下，"
        "所以我们说的「快」得先说清是省时间还是省钱。",
        "这里我得要个数字：{peer}说的提升幅度没有基数，按 20% 的转化差重算，"
        "结论会反过来，建议先把口径统一再往下聊。",
        "补一个对比：方案 A 交付 2 周、返工率 15%，方案 B 是 3 周、8%，"
        "按总成本算 A 不一定输，关键看我们能承受几次返工。",
    ),
    "spark": (
        "我不同意{peer}这个判断，凭什么默认用户会买账？如果预算砍一半，这套方案第一周就得停。",
        "我唱个反调：大家都说先做核心功能，可核心功能做完没人用怎么办？"
        "我觉得得先验证有没有人愿意为它花时间。",
        "我还是不服，{peer}说的前提是团队齐整，可我们只有 4 个人，真出问题谁兜底？"
        "这一条今天没人回答过。",
    ),
}

_PERSONA_PROMPT: dict[str, str] = {
    "ice": (
        "你的任务是控场：开场把议题拆成 2~3 个维度并排序，中途报时、推进议程、最后收口。"
        "你说话条理清楚，常用「第一/第二」「我们还有 X 分钟」这类推进语。"
    ),
    "data": (
        "你的任务是拿数字说话：每条判断都尽量给可核对的量（人数、周期、成本、比例、对比），"
        "并且会当场质疑没有数字支撑的观点（例如「这个提升有基数吗」）。"
    ),
    "spark": (
        "你的任务是把讨论搅出问题：专挑大家默认的前提唱反调（「我不同意，因为……」），"
        "但你的论据常常不够扎实，需要别人补数据或补方案。"
    ),
}

_MD_LINE_RE = re.compile(r"^\s*(?:[-*+]\s+|\d+[.、)]\s*|[一二三四五][、.]\s*)")
_FRAG_SPLIT_RE = re.compile(r"[，。；！？、,.!?;：:\n\r]")


# ----------------------------------------------------------------
# 状态层：只读入参，永远构造新的 dict（路由层可以放心持有旧 state）
# ----------------------------------------------------------------
def _empty_state() -> dict[str, Any]:
    return {"version": GROUP_VERSION,
            "topic": {"title": "", "brief": "", "keywords": [], "minutes": MINUTES_DEFAULT},
            "turns": [], "student_turns": [], "elapsed_turns": 0}


def _as_topic(topic: Any) -> dict[str, Any]:
    """把任意 topic 规整成契约形状：title/brief/keywords/minutes，全部是可序列化基本类型。"""
    if not isinstance(topic, Mapping):
        return {"title": "", "brief": "", "keywords": [], "minutes": MINUTES_DEFAULT}
    kws: list[str] = []
    for k in topic.get("keywords") or []:
        s = str(k).strip()
        if s and s not in kws:
            kws.append(s)
    try:
        minutes = int(topic.get("minutes") or MINUTES_DEFAULT)
    except (TypeError, ValueError):
        minutes = MINUTES_DEFAULT
    return {"title": str(topic.get("title") or "").strip(),
            "brief": str(topic.get("brief") or "").strip(),
            "keywords": kws, "minutes": max(1, minutes)}


def _as_state(state: Any) -> dict[str, Any]:
    """规整 state：重编 idx/at、丢掉空发言与未知 speaker，保证后续全是纯数据。"""
    out = _empty_state()
    if not isinstance(state, Mapping):
        return out
    out["version"] = str(state.get("version") or GROUP_VERSION)
    out["topic"] = _as_topic(state.get("topic"))
    turns: list[dict[str, Any]] = []
    for raw in state.get("turns") or []:
        if not isinstance(raw, Mapping):
            continue
        speaker = str(raw.get("speaker") or "")
        text = str(raw.get("text") or "").strip()
        if speaker not in _SPEAKERS or not text:
            continue
        turns.append({"idx": len(turns) + 1, "speaker": speaker,
                      "name": str(raw.get("name") or _NAMES.get(speaker, speaker)),
                      # at = 逻辑步号（与 idx-1 同值），不用真实时间：纯函数、可离线复现
                      "text": text, "at": len(turns)})
    out["turns"] = turns
    out["student_turns"] = [t["idx"] for t in turns if t["speaker"] == "student"]
    out["elapsed_turns"] = len(turns)
    return out


def _append_turn(state: dict[str, Any], speaker: str, text: str) -> tuple[dict[str, Any], dict[str, Any]]:
    turn = {"idx": len(state["turns"]) + 1, "speaker": speaker,
            "name": _NAMES.get(speaker, speaker), "text": text, "at": len(state["turns"])}
    state["turns"] = list(state["turns"]) + [turn]
    if speaker == "student":
        state["student_turns"] = list(state["student_turns"]) + [turn["idx"]]
    state["elapsed_turns"] = len(state["turns"])
    return state, turn


def _candidate(candidate_id: str) -> dict[str, str]:
    cand = _CAND_BY_ID.get(str(candidate_id or ""))
    if cand is None:
        raise ValueError(f"未知候选人：{candidate_id}（可选：{', '.join(_CAND_BY_ID)}）")
    return cand


# ----------------------------------------------------------------
# 议题与开场
# ----------------------------------------------------------------
def _skill_list(skills: Sequence[str] | None) -> list[str]:
    out: list[str] = []
    for s in skills or []:
        t = str(s).strip()
        if 1 < len(t) <= 20 and t not in out:
            out.append(t)
    return out


def _domain_words(industry: str | None) -> list[str]:
    text = str(industry or "")
    for key, words in _DOMAIN_POOL.items():
        if key in text:
            return list(words)
    return []


def _pick_title_index(job_title: str, seed: int = 0) -> int:
    """确定性选题：按字符码求和 + seed 取模（不用 hash()，它每进程随机）。

    seed 由调用方每次开局随机给——同一岗位每场议题不同；seed 固定时结果可复现。
    """
    total = sum(ord(ch) for ch in _norm(job_title))
    return (total + max(0, int(seed or 0))) % len(_TOPIC_TEMPLATES)


def make_topic(job_title: str, industry: str | None = None,
               skills: Sequence[str] | None = None, seed: int = 0) -> dict[str, Any]:
    """按岗位 / 行业 / 技能 / seed 生成群面议题。

    keywords 只从两类来源取，绝不编造技术名词：
      1) 传入的 skills（去重、截断到 6 个）；
      2) TOPIC_UNIVERSAL（成本/效率/风险…）与命中行业的 _DOMAIN_POOL 业务词。
    不足 5 个用通用词补齐，最多 8 个。seed 相同 → 议题完全相同（可复现）；
    路由层每次开局随机换 seed，同一岗位不再永远命中同一道题。
    """
    job = str(job_title or "").strip() or "目标岗位"
    sk = _skill_list(skills)
    seed = max(0, int(seed or 0))
    name, scenario = _TOPIC_TEMPLATES[_pick_title_index(job, seed)]
    skill_a = sk[0] if sk else "核心功能"
    skill_b = sk[1] if len(sk) > 1 else "交付质量"
    body = scenario.format(job=job, skill_a=skill_a, skill_b=skill_b)
    minutes = MINUTES_DEFAULT

    # 通用词按 seed 轮转起点，不同场次的关键词组合也不同
    rotated = TOPIC_UNIVERSAL[seed % len(TOPIC_UNIVERSAL):] + TOPIC_UNIVERSAL[:seed % len(TOPIC_UNIVERSAL)]
    kws: list[str] = []
    for s in sk[:3]:
        if s not in kws:
            kws.append(s)
    # 固定补 3 个通用维度：学生口语里最常出现、evaluate 才抓得到 new_points
    for w in rotated[:3]:
        if w not in kws:
            kws.append(w)
    for w in _domain_words(industry):
        if len(kws) >= 8:
            break
        if w not in kws:
            kws.append(w)
    for w in TOPIC_UNIVERSAL:
        if len(kws) >= 5:
            break
        if w not in kws:
            kws.append(w)
    kws = kws[:8]

    brief = (f"背景：{body}"
             f"要求：{minutes} 分钟内形成一致结论，说清取舍依据，并落到一个可执行动作上。")
    return {"title": f"{job}｜{name}", "brief": brief, "keywords": kws, "minutes": minutes}


def opening(topic: Mapping[str, Any]) -> dict[str, Any]:
    """主持人开场白 + 破冰者林一的开场发言。纯模板，不调模型，保证开局秒出。

    返回 {"host","rules","first_turn"}；first_turn 已经是契约形状的 turn，
    路由直接 append 进 state["turns"] 即可（idx=1 / at=0）。
    """
    t = _as_topic(topic)
    kws = list(t["keywords"])
    dims = "、".join(kws[:3]) if kws else "目标、成本、风险"
    minutes = t["minutes"]
    host = (
        f"欢迎参加无领导小组讨论。本场 4 人：你，以及林一（破冰者）、赵敏（数据派）、王锐（搅局者）；"
        f"议题是「{t['title'] or '现场议题'}」，讨论时间 {minutes} 分钟。"
        "规则：每人每次发言 80~140 字，可以点名回应或追问，但不要打断别人；"
        "结束前必须形成一条一致结论，并说清取舍依据。现在开始，谁先来？"
    )
    ice_text = (
        f"那我先起个头。我建议别急着给方案，先把议题拆成三个维度：{dims}，"
        "每个维度先用一句话定标准，再往里填事实。"
        f"另外提醒时间，我们只有 {minutes} 分钟，最后两分钟必须收敛到一条结论上。"
    )
    rules = [f"讨论时间 {minutes} 分钟", "本场 4 人（学生 + 3 位 AI 候选人）",
             "每次发言 80~140 字，可点名回应不可打断", "结束前形成一条一致结论并说明依据"]
    return {"host": host, "rules": rules,
            "first_turn": {"idx": 1, "speaker": "ice", "name": _NAMES["ice"],
                           "text": ice_text, "at": 0}}


# ----------------------------------------------------------------
# AI 候选人发言
# ----------------------------------------------------------------
def _count_turns(state: Mapping[str, Any], speaker: str) -> int:
    return sum(1 for t in state["turns"] if t.get("speaker") == speaker)


def _round_goal(state: Mapping[str, Any], candidate_id: str) -> str:
    """本轮要求：按讨论进度与角色给出「立框架 / 给数字 / 唱反调 / 推进 / 质疑 / 收敛」。"""
    elapsed = len(state["turns"])
    if elapsed >= 10:
        return "收敛：把讨论收到一条结论上，说清取舍依据，别再开新话题"
    if _count_turns(state, candidate_id) == 0:
        return {"ice": "立框架：先把议题拆成 2~3 个维度并排出先后顺序",
                "data": "给数字：抛一个可核对的口径或一组对比数字",
                "spark": "唱反调：挑一个大家都默认的前提提出质疑"}[candidate_id]
    if candidate_id == "ice":
        return "推进流程：先报时，再把讨论收口到争议最小的前两个维度"
    if candidate_id == "data":
        return "质疑：点名一条没有数字支撑的观点，补上口径或反例"
    return "质疑：针对最新一条观点提出反例或风险，逼对方补证据"


def _clip(text: str, limit: int) -> str:
    s = str(text or "").replace("\n", " ").strip()
    return s if len(s) <= limit else s[:limit] + "…"


def _opinion_digest(state: Mapping[str, Any]) -> str:
    """已有观点摘要：每位在场者最近一次发言的截断，保持首次开口顺序。"""
    latest: dict[str, str] = {}
    for t in state["turns"]:
        if t["speaker"] != "student":
            latest[t["speaker"]] = t["text"]
    if not latest:
        return "（还没有人发言）"
    return "\n".join(f"- {_NAMES[k]}：{_clip(v, 40)}" for k, v in latest.items())


def _spoken_keywords(state: Mapping[str, Any]) -> list[str]:
    said = _norm("".join(t["text"] for t in state["turns"]))
    return [k for k in state["topic"]["keywords"] if _norm(k) and _norm(k) in said]


def _system_prompt(state: Mapping[str, Any], cand: Mapping[str, str], goal: str) -> str:
    topic = state["topic"]
    said = _spoken_keywords(state)
    elapsed = len(state["turns"])
    return f"""你是{cand['role']}「{cand['name']}」，正在参加一场无领导小组讨论（群面）。

【你的特点】{cand['tagline']}。{_PERSONA_PROMPT[cand['id']]}

【本场议题】{topic['title'] or '无领导小组讨论'}；{topic['brief'] or '请围绕议题形成一致结论。'}
【议题关键词】{'、'.join(topic['keywords']) or '暂无'}
【当前局面】第 {elapsed + 1} 次发言，全场共约 {topic['minutes']} 分钟，已经说了 {elapsed} 轮。
【场上已有观点】
{_opinion_digest(state)}
【已被说过的议题关键词】{'、'.join(said) or '还没有'}

【本轮要求】{goal}

【硬性要求（违反即视为失败）】
1. 必须点名回应至少一位在场者（用对方名字，学生称「同学」），例如「赵敏说的成本口径我补一点」；
2. 禁止重复别人已经说过的观点，也不要重复已被说过的关键词，必须新增信息（数字、反例、取舍标准、收敛建议）；
3. 80~140 字，中文口语，像真人在会上抢话，不要开场客套、不要自报姓名；
4. 不许输出 markdown、列表、编号、加粗、括号注释；
5. 只输出这段发言本身。"""


def _user_prompt(state: Mapping[str, Any], cand: Mapping[str, str], goal: str) -> str:
    recent = state["turns"][-4:]
    lines = [f"{i}. {_ADDRESS.get(t['speaker'], t['name'])}：{t['text']}"
             for i, t in enumerate(recent, start=1)]
    latest_student = next((t["text"] for t in reversed(state["turns"])
                           if t["speaker"] == "student"), "")
    parts = ["【最近发言原文（从旧到新）】",
             "\n".join(lines) if lines else "（暂无，你是本场第一个接话的人）",
             f"【学生最新发言】{latest_student or '（学生还没开口）'}",
             f"【本轮要求】{goal}",
             f"请以{cand['name']}的身份，直接输出下一句发言（80~140 字），不要加名字前缀。"]
    return "\n".join(parts)


def _clean_reply(raw: Any) -> str:
    """清掉模型爱输出的 markdown：代码围栏 / 列表符号 / 粗体 / 多余换行，并限长。"""
    if not isinstance(raw, str):
        return ""
    text = raw.replace("\r", "\n")
    text = re.sub(r"```[a-zA-Z]*", "", text)
    lines: list[str] = []
    for ln in text.split("\n"):
        ln = ln.replace("**", "").replace("__", "")
        ln = _MD_LINE_RE.sub("", ln)
        ln = ln.lstrip("#").strip()
        if ln:
            lines.append(ln)
    text = re.sub(r"\s+", " ", " ".join(lines)).strip()
    text = text.strip('"“”').strip()
    if len(text) > 240:
        text = text[:240].rstrip("，。；、,. ") + "…"
    return text


def _fallback_line(candidate_id: str, spoken: int, state: Mapping[str, Any]) -> str:
    """模板降级：按该角色已发言次数取模轮换，并把 {peer} 换成最近一位其他发言人。"""
    tpls = CANDIDATE_FALLBACK[candidate_id]
    tpl = tpls[spoken % len(tpls)]
    peer_turn = next((t for t in reversed(state["turns"]) if t["speaker"] != candidate_id), None)
    peer = _ADDRESS.get(peer_turn["speaker"], "大家") if peer_turn else "大家"
    return tpl.replace("{peer}", peer)


def _ensure_reference(text: str, state: Mapping[str, Any], candidate_id: str) -> str:
    """模型忘了点名时补一句回应引子，保证「互相点名」这条人设不落空（纯编排，不改模型观点）。"""
    others = [n for cid, n in _ADDRESS.items() if cid != candidate_id]
    if any(name in text for name in others):
        return text
    peer_turn = next((t for t in reversed(state["turns"]) if t["speaker"] != candidate_id), None)
    if peer_turn is None:
        return text
    return f"我回应一下{_ADDRESS.get(peer_turn['speaker'], '大家')}：" + text


def _default_speak(system: str, user: str) -> str | None:
    """默认说话人：严格按 agents.llm.generate_reply 的签名调用，任何异常都吞掉返回 None。"""
    try:
        from agents import llm as llm_module
        return llm_module.generate_reply(
            "student", system_prompt=system, user_prompt=user, tag="group_turn")
    except Exception:
        return None


def ai_turn(state: Mapping[str, Any], candidate_id: str,
            speak: Callable[[str, str], str] | None = None) -> dict[str, Any]:
    """生成该候选人的下一条发言。

    speak(system, user) -> str 可注入（路由带超时）；缺省用 agents.llm.generate_reply。
    返回 {"state": 新 state, "turn": 新发言, "source": "llm|fallback", "error": 文本|null}：
    调用方若要整份替换状态，用返回的 state 覆盖即可；入参 state 永不被修改。
    未知 candidate_id 抛 ValueError。
    """
    cand = _candidate(candidate_id)
    st = _as_state(state)
    spoken = _count_turns(st, candidate_id)
    goal = _round_goal(st, candidate_id)
    system = _system_prompt(st, cand, goal)
    user = _user_prompt(st, cand, goal)

    raw: Any = None
    error: str | None = None
    if speak is None:
        raw = _default_speak(system, user)
    else:
        try:
            raw = speak(system, user)
        except Exception as exc:            # 超时/断网/任何注入实现抛错，一律降级
            error = f"{type(exc).__name__}: {str(exc)[:80]}"
            raw = None

    text = _clean_reply(raw)
    if text:
        text = _ensure_reference(text, st, candidate_id)
        source = "llm"
    else:
        text = _fallback_line(candidate_id, spoken, st)
        source = "fallback"
        if error is None:
            error = None if speak is None else "empty_reply"

    st, turn = _append_turn(st, candidate_id, text)
    return {"state": st, "turn": turn, "source": source, "error": error}


def student_turn(state: Mapping[str, Any], text: str) -> dict[str, Any]:
    """记录学生的一次抢话。空文本抛 ValueError（空发言不是一次发言，不占轮次）。"""
    st = _as_state(state)
    body = str(text or "").strip()
    if not body:
        raise ValueError("发言内容不能为空")
    st, turn = _append_turn(st, "student", body)
    return {"state": st, "turn": turn}


# ----------------------------------------------------------------
# 评估（确定性，只读 state 文本，不调模型）
# ----------------------------------------------------------------
def _round3(x: float) -> float:
    return round(float(x), 3)


def _clamp100(x: float) -> int:
    """clamp 0~100 后四舍五入取整（不用 round()，避免银行家舍入）。"""
    v = min(100.0, max(0.0, float(x)))
    return int(v + 0.5)


def _new_point_keywords(turns: Sequence[Mapping[str, Any]],
                        keywords: Sequence[str]) -> list[str]:
    """学生「率先提出」的议题关键词：该词全场第一次出现必须落在学生发言里。"""
    out: list[str] = []
    for kw in keywords:
        nk = _norm(kw)
        if len(nk) < 2:
            continue
        for t in turns:
            if nk in _norm(t["text"]):
                if t["speaker"] == "student":
                    out.append(str(kw))
                break
    return out


def _question_count(text: str) -> int:
    n = str(text).count("？") + str(text).count("?")
    if n:
        return n
    return sum(str(text).count(w) for w in ("为什么", "怎么", "是不是", "要不要", "多少", "如何"))


def _interrupt_count(text: str) -> int:
    return sum(str(text).count(w) for w in _INTERRUPT_MARKS)


def _fragments(text: str) -> list[str]:
    """把发言切成逐字可回引的片段（保持原文连续，不增删字）。"""
    out: list[str] = []
    for piece in _FRAG_SPLIT_RE.split(str(text or "")):
        frag = piece.strip()
        if len(frag) >= 4 and frag not in out:
            out.append(frag)
    return out


def _frag_with(text: str, word: str) -> str:
    for frag in _fragments(text):
        if word in frag:
            return frag
    return ""


def _best_frag(frags: Sequence[str]) -> str:
    """回引时优先选信息量最大（最长）的片段，避免引到「我觉得」这种口水句。"""
    return max(frags, key=len) if frags else ""


def _pct(ratio: float) -> str:
    return f"{round(float(ratio) * 100, 1)}%"


def _role_of(talk_ratio: float, new_points: int) -> tuple[str, str]:
    if talk_ratio >= 0.3 and new_points >= 2:
        return "leader", "推动者"
    if talk_ratio >= 0.15 and new_points >= 1:
        return "contributor", "贡献者"
    if talk_ratio >= 0.08:
        return "follower", "跟随者"
    return "silent", "沉默者"


def _role_reason(role: str, talk_ratio: float, new_points: int,
                 new_kws: Sequence[str], turn_count: int) -> str:
    pct = _pct(talk_ratio)
    if turn_count == 0:
        return "本场没有任何发言记录，讨论里没有你的信息增量。"
    if role == "leader":
        return (f"发言占比 {pct}，并率先引入 {new_points} 个议题关键词"
                f"（{'、'.join(new_kws[:3])}），把讨论从复述推到了新增信息。")
    if role == "contributor":
        return (f"发言占比 {pct}，提出了 {new_points} 个新角度"
                f"（{'、'.join(new_kws[:3])}），但还没到主导议程的程度。")
    if role == "follower":
        # 有新观点但发言量不足，不能说成「没引入关键词」——那会和 new_points 打架
        if new_points > 0:
            kws = "、".join(new_kws[:3])
            return (f"发言占比 {pct}，提出了 {new_points} 个新角度"
                    + (f"（{kws}）" if kws else "")
                    + "，但开口次数和字数不够，没能把观点推到议程上。")
        return (f"发言占比 {pct}，只接住了别人已有的观点，没有引入议题关键词"
                "（或引入的都被别人先说过了）。")
    return f"发言占比 {pct}，本场几乎没有主动开口，讨论基本没被你影响。"


def _highlights(stu_text: str, new_kws: Sequence[str], converge: int,
                questions: int, frags: Sequence[str]) -> list[str]:
    if not str(stu_text).strip():
        # 全场没发言就没有可回引的片段：如实说，不编引文
        return ["本场你没有留下任何发言，无法评估观点贡献",
                "第一个开口的机会已经错过，下一场开场 30 秒内先接一句"]
    out: list[str] = []
    used: set[str] = set()
    if new_kws:
        frag = _frag_with(stu_text, new_kws[0])
        if frag:
            out.append(f"你提出「{frag}」，把「{new_kws[0]}」这个角度第一次带进了讨论")
            used.add(frag)
    if converge:
        word = next((w for w in CONVERGE_WORDS if w in stu_text), "")
        frag = _frag_with(stu_text, word) if word else ""
        if frag and frag not in used:
            out.append(f"你在「{frag}」里主动收口，推动了共识形成")
            used.add(frag)
    if questions:
        frag = _best_frag([f for f in frags if f not in used])
        if frag:
            out.append(f"你用「{frag}」把问题抛回给同伴，带动了讨论而不是自说自话")
            used.add(frag)
    for frag in sorted(frags, key=len, reverse=True):
        if len(out) >= 2:
            break
        if frag in used:
            continue
        out.append(f"你完整说完了「{frag}」，是一段能被人接住的话而不是碎句")
        used.add(frag)
    return out[:3]


def _improvements(chars: int, new_points: int, converge: int,
                  questions: int, talk_ratio: float, first_pos: float,
                  interrupted: int, frags: Sequence[str],
                  turn_count: int) -> list[str]:
    out: list[str] = []
    frag = _best_frag(frags)
    if turn_count == 0:
        return ["全场没有开口：群面不发言等于零分，下一场第一句话必须抢在前 60 秒",
                "练习时给自己设硬指标：12 分钟里至少 3 次发言、每次 80 字以上"]
    if new_points == 0:
        out.append("整场没有引入议题关键词，说的都是别人已经说过的；下次先给一个新角度再接话")
    if converge == 0:
        out.append("全场没有出现「总结/综上/共识」这类收口表达，最后两分钟要主动归纳成一条结论")
    if chars < 120:
        hint = f"；可以从「{frag}」再多说一层理由" if frag else ""
        out.append(f"你的总发言只有 {chars} 字，低于一场群面的基本盘（建议 200 字以上）{hint}")
    if questions == 0:
        out.append("一次都没有向同伴提问；群面里点名追问比独自陈述更加分")
    if talk_ratio > 0.55:
        out.append(f"发言占比 {_pct(talk_ratio)} 偏高，注意给别人留话口，否则会被判成不给队友空间")
    if first_pos > 0.5:
        out.append("你第一次开口偏晚（已过了半数发言），破冰位置被人占了；下次前两句内就接话")
    if interrupted:
        out.append(f"有 {interrupted} 次抢话痕迹（如「打断」「插一句」），群面里抢话扣分多于加分")
    for pad in ("把每条发言压成「结论 + 两条理由」，比铺陈更容易被组员接住",
                "每轮至少点名回应一位同伴，别只对着空气陈述"):
        if len(out) >= 2:
            break
        if pad not in out:
            out.append(pad)
    return out[:3]


def _next_drill(role: str, new_points: int, converge: int, questions: int, chars: int) -> str:
    if role == "silent" or chars == 0:
        return "下一场开场 30 秒内说第一句：先复述议题，再给一个你看重的维度。"
    if new_points == 0:
        return "把议题关键词写在纸上，之后每次发言至少套进一个还没人说过的词。"
    if converge == 0:
        return "用「综上，我建议先做 A 再做 B」收尾，30 秒讲完，练三遍。"
    if questions == 0:
        return "每轮至少点名一位同伴提问一次，例如「赵敏这个数字的基数是多少」。"
    return "把自己的观点压成「结论-两条理由-一个数字」，控制在 100 字内说一遍。"


def evaluate(state: Mapping[str, Any]) -> dict[str, Any]:
    """群面评估。确定性：只依赖 state 里的文本与议题关键词，不调模型、无随机。"""
    st = _as_state(state)
    kws = list(st["topic"]["keywords"])
    turns = st["turns"]
    stu = [t for t in turns if t["speaker"] == "student"]
    stu_text = "".join(t["text"] for t in stu)
    chars = len(stu_text)
    all_chars = sum(len(t["text"]) for t in turns)
    talk_ratio = _round3(chars / all_chars) if all_chars else 0.0

    new_kws = _new_point_keywords(turns, kws)
    new_points = len(new_kws)
    converge_marks = sum(stu_text.count(w) for w in CONVERGE_WORDS)
    question_asked = _question_count(stu_text)
    interrupted = _interrupt_count(stu_text)
    first_idx = next((t["idx"] for t in turns if t["speaker"] == "student"), None)
    first_pos = _round3(first_idx / len(turns)) if first_idx and turns else 1.0
    struct_marks = sum(1 for m in STRUCT_MARKS if m in stu_text)
    avg_chars = chars / len(stu) if stu else 0.0

    metrics = {"talk_ratio": talk_ratio, "chars": chars, "new_points": new_points,
               "converge_marks": converge_marks, "first_speak_position": first_pos,
               "question_asked": question_asked, "interrupted": interrupted}

    # 四维线性映射（口径写死在注释里，前端展示时可原样解释）：
    #   贡献 = 新观点(55%) + 发言量(30%) + 占比(15%)
    #   协作 = 占比合理度(45%) + 提问(30%) + 收口(25%)
    #   结构 = 分点标记(45%) + 收口(35%) + 越早开口越好(20%)
    #   表达 = 单次均长(70%) + 总字数(30%)
    contribution = _clamp100(100.0 * (
        0.55 * min(1.0, new_points / 3.0)
        + 0.30 * min(1.0, chars / 300.0)
        + 0.15 * min(1.0, talk_ratio / 0.30)))
    collaboration = _clamp100(100.0 * (
        0.45 * min(1.0, talk_ratio / 0.25)
        + 0.30 * min(1.0, question_asked / 2.0)
        + 0.25 * min(1.0, converge_marks / 2.0)))
    structure = _clamp100(100.0 * (
        0.45 * min(1.0, struct_marks / 3.0)
        + 0.35 * min(1.0, converge_marks / 1.0)
        + 0.20 * max(0.0, 1.0 - first_pos)))
    expression = _clamp100(100.0 * (
        0.70 * min(1.0, avg_chars / 90.0)
        + 0.30 * min(1.0, chars / 300.0)))
    overall = _clamp100(0.35 * contribution + 0.25 * collaboration
                        + 0.25 * structure + 0.15 * expression)

    role_id, role_label = _role_of(talk_ratio, new_points)
    # 短发言（如只说了「同意」）切不出 ≥4 字的片段时，整句回引，保证 highlights 不空
    frags = _fragments(stu_text) or ([stu_text.strip()] if stu_text.strip() else [])
    digest = [{"speaker": t["speaker"], "gist": _clip(t["text"], 36)} for t in turns]

    return {"version": GROUP_VERSION,
            "role": {"id": role_id, "label": role_label,
                     "reason": _role_reason(role_id, talk_ratio, new_points, new_kws, len(stu))},
            "metrics": metrics,
            "scores": {"contribution": contribution, "collaboration": collaboration,
                       "structure": structure, "overall": overall},
            "highlights": _highlights(stu_text, new_kws, converge_marks, question_asked, frags),
            "improvements": _improvements(chars, new_points, converge_marks,
                                          question_asked, talk_ratio, first_pos,
                                          interrupted, frags, len(stu)),
            "next_drill": _next_drill(role_id, new_points, converge_marks, question_asked, chars),
            "transcript_digest": digest}
