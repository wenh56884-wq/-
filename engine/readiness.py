# engine/readiness.py
# 职责：把「成绩单」和「简历」两条证据链对齐到岗位技能标签上，逐项判定
#       proven（成绩背书+简历写了）/ hidden（成绩背书但简历没写）/ claimed（只有自述）
#       / weak（学过没学牢）/ gap（完全空白），给出就绪度、被埋没的资产与补课路径。
#       这是证据分级，不是覆盖率——recommend.skill_cover_of 只数「覆盖了几项」，
#       本模块回答「每一项，你的证据到底是什么等级」。
# 铁律：引擎定数，模型说话。纯函数、无随机、无网络、无 LLM、无数据库；
#       catalog 缓存不进引擎，由路由层管。
# 缺失不冒充：成绩单里没这门课就是 gap/claimed，绝不拿「最像的那门」硬凑；
#       catalog 反查不到课程就 how="self"，绝不编造课程名。
#
# 为什么市面没有：招聘平台的「匹配度」只能读简历自述，它不知道你《数据库原理》考了
# 88 分；学校的教务系统知道你考了多少分，但不知道岗位要什么。启航两边都有，所以能
# 回答一个商业产品回答不了的问题："我明明学过、也考得不错，为什么简历上看起来
# 什么都不会？"——答案是这些技能大多躺在 hidden 里，被简历埋没了。
#
# 口径澄清（契约第 13 节未写死或表述有歧义处，按最合理方式定，改动须同步契约）：
# 1) in_resume 的 2-gram 匹配只对归一后长度 >=3 的技能启用；长度为 2 的技能只认
#    精确包含（契约原文即「长度 ≥3 才允许 2-gram」）。这比放宽到 2 字更保守：
#    「数据」「管理」这类高频二字词靠 2-gram 会大面积误命中。
# 2) find_courses_for_skill 与 skill_match 同口径：技能映射精确/双向包含命中优先，
#    课程名 2-gram 覆盖率 >=0.5 也算候选——保证 gaps 的 how="course" 判定与
#    条目里的课程命中逻辑一致，不会出现「条目命中了课、gaps 却说 self」的矛盾。
# 3) gaps 的 fix 按 gap / claimed 分开写话术：gap 是「没学」，补法是先修重学；
#    claimed 是「写了但没背书」，补法是做出可验证的成果。两种缺口的行动不同。
# 4) interview_hooks 对 proven 用「举例证明」话术，对 hidden 用「主动暴露资产」
#    话术——hidden 是本模块的卖点，同一句模板会把卖点浪费掉。
# 5) 多门课同匹配度、同学分、同分数时取录入顺序前者（确定性，保证幂等）。

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from engine.interview import _norm
from engine.kg import skills_for_course

READINESS_VERSION = "readiness-v1"

# 状态 → 中文标签（契约固定五值，不得增删）
STATUS_LABELS: dict[str, str] = {
    "proven":  "有成绩单背书",
    "hidden":  "被埋没的资产",
    "claimed": "只有自述，没有成绩支撑",
    "weak":    "学过，但没学牢",
    "gap":     "完全空白",
}

# 状态 → 就绪度权重（等权平均，不加权 credit）
# critical 叙事里用的极短标签（避免整句重复status_label）
_SHORT_LABEL: dict[str, str] = {
    "proven": "有背书", "hidden": "没写进简历", "claimed": "只有自述",
    "weak": "没学牢", "gap": "完全空白",
}
STATUS_WEIGHTS: dict[str, float] = {
    "proven": 1.0, "hidden": 0.72, "claimed": 0.45, "weak": 0.35, "gap": 0.0,
}

# counts 的五键固定顺序（契约原文）
_COUNT_ORDER = ("proven", "hidden", "claimed", "weak", "gap")

# 就绪度分档（契约阈值）
_LEVEL_HIGH = 80.0
_LEVEL_MID = 65.0
_LEVEL_LOW = 45.0
LEVEL_LABELS: dict[str, str] = {
    "high": "够投", "mid": "能投但需补说法", "low": "缺口明显", "critical": "一轮游",
}
LEVEL_UNKNOWN_LABEL = "岗位没给技能标签"

# 2-gram 命中门槛；命中后封顶 0.9，避免与精确命中并列
MATCH_MIN_COVERAGE = 0.5
MATCH_GRAM_CAP = 0.9

# advice 的 when 只取契约允许的三个值
WHEN_NOW = "本周"
WHEN_SOON = "两周内"
WHEN_TERM = "本学期"


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


def _bigrams(text: str) -> set[str]:
    """对归一化后的文本取 2-gram（中文按字符切，英文按字母切，均已小写）。"""
    t = _norm(text)
    if len(t) < 2:
        return set()
    return {t[i:i + 2] for i in range(len(t) - 1)}


def _coverage(skill: str, text: str) -> float:
    """技能被文本覆盖的 2-gram 比例，0~1。技能不足 2 字符 → 0（不硬猜）。"""
    sb = _bigrams(skill)
    if not sb:
        return 0.0
    return len(sb & _bigrams(text)) / len(sb)


def _fmt_score(score: float | None) -> str:
    """88.0 → '88'，88.5 → '88.5'：分数进文案不带多余的 .0。"""
    if score is None:
        return ""
    return f"{round(score, 2):g}"


def _top_txt(percentile: float | None) -> str:
    """分位 → 人话。缺分位返回空串。

    直接算 100-p 会出两种离谱说法：满分（p=100）变成「专业前 0%」，
    垫底（p=10）变成「专业前 90%」。所以高位改说「前列」，低于中位数改说「后 x%」。
    """
    if percentile is None:
        return ""
    p = max(0.0, min(100.0, float(percentile)))
    if p >= 95:
        return "专业前列"
    if p < 50:
        return f"专业后 {max(1, round(100 - p))}%"
    return f"专业前 {max(1, round(100 - p))}%"


def _clean_skills(job: Any) -> list[str]:
    """岗位技能标签：去空、按归一化去重、保留原始写法与录入顺序。"""
    if not isinstance(job, Mapping):
        return []
    raw = job.get("skills")
    if not isinstance(raw, (list, tuple, set)):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        text = str(item or "").strip()
        key = _norm(text)
        if not text or key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _clean_courses(courses: Any) -> list[dict[str, Any]]:
    """只保留有名字的课程；分数/学分/分位取不到就是 None（不填 0）。"""
    out: list[dict[str, Any]] = []
    if not isinstance(courses, (list, tuple)):
        return out
    for raw in courses:
        if not isinstance(raw, Mapping):
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        pct = _num(raw.get("percentile"))
        out.append({
            "name": name,
            "credit": _num(raw.get("credit")),
            "score": _num(raw.get("score")),
            "percentile": min(100.0, max(0.0, pct)) if pct is not None else None,
        })
    return out


# ----------------------------------------------------------------
# 技能 × 课程 / 技能 × 简历 的匹配
# ----------------------------------------------------------------
def skill_match(skill: str, course_name: str) -> float:
    """技能 × 课程名 的匹配度 0~1（纯函数，确定性）。

    1) 课程培养技能集（engine.kg.skills_for_course）里有技能与之相等、或双向包含
       且两边都 >=2 字 → 1.0（强证据：这门课确实培养这项技能）。
    2) 否则看技能对课程名的 2-gram 覆盖率：cov >= 0.5 记 min(cov, 0.9)
       （封顶 0.9，避免名字凑巧与精确命中并列）。
    """
    key = _norm(skill)
    if not key:
        return 0.0
    for cultivated in skills_for_course(course_name):
        ck = _norm(cultivated)
        if not ck:
            continue
        if key == ck or (len(key) >= 2 and len(ck) >= 2 and (key in ck or ck in key)):
            return 1.0
    cov = _coverage(key, course_name)
    if cov >= MATCH_MIN_COVERAGE:
        return round(min(cov, MATCH_GRAM_CAP), 4)
    return 0.0


def find_courses_for_skill(skill: str, catalog: Sequence[str]) -> list[str]:
    """课程库反查：哪些课培养这项技能（复用 engine.kg.skills_for_course）。

    与 skill_match 同口径（口径 2）；按匹配度降序、同分按课程名，保证确定性。
    绝不编造课程名：catalog 里没有就是空列表。
    """
    scored: list[tuple[float, str]] = []
    seen: set[str] = set()
    for raw in catalog or ():
        name = str(raw or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        m = skill_match(skill, name)
        if m > 0:
            scored.append((m, name))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [name for _, name in scored]


def _in_resume(skill: str, resume_text: str) -> bool:
    """技能 ↔ 简历：精确包含，或（长度 >=3 且 2-gram 覆盖率 >=0.5）。

    短技能（<3 字）只认精确包含，不许 2-gram 瞎匹配（口径 1）。
    """
    key = _norm(skill)
    if not key:
        return False
    text = _norm(resume_text)
    if key in text:
        return True
    if len(key) < 3:
        return False
    return _coverage(key, text) >= MATCH_MIN_COVERAGE


def _pick_course(skill: str,
                 courses: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, float]:
    """多门课命中取匹配度高者；同匹配度取 credit 大者；再同取 score 高者；
    全同取录入顺序前者（确定性，口径 5）。"""
    best: dict[str, Any] | None = None
    best_key: tuple[float, float, float] | None = None
    for course in courses:
        m = skill_match(skill, course["name"])
        if m <= 0:
            continue
        score = course["score"] if course["score"] is not None else -1.0
        key = (m, course["credit"] if course["credit"] is not None else 0.0, score)
        if best is None or key > best_key:
            best, best_key = course, key
    if best is None:
        return None, 0.0
    return best, best_key[0]


def _decide_status(course: dict[str, Any] | None, in_resume: bool) -> str:
    """契约状态表：先看有没有命中课程，再看成绩，再看简历。"""
    if course is None:
        return "claimed" if in_resume else "gap"
    score = course["score"]
    if score is None:
        return "claimed" if in_resume else "gap"
    if score >= 70:
        return "proven" if in_resume else "hidden"
    return "weak"


# ----------------------------------------------------------------
# 组装：条目 / 资产 / 缺口 / 钩子 / 结论 / 动作
# ----------------------------------------------------------------
_EVIDENCE_TAIL: dict[str, str] = {
    "proven": "，简历里也写了这条技能",
    "hidden": "，但简历里一个字没提",
    "weak": "，学过但没学牢",
    "claimed": "，简历里写了但没有成绩支撑",
    "gap": "，简历里也没写",
}


def _evidence(skill: str, status: str, course: dict[str, Any] | None,
              in_resume: bool) -> str:
    """一句话证据：课程、分数、分位与简历状态，全部来自真实数据，不修饰。"""
    if course is None:
        if in_resume:
            return f"简历里写了「{skill}」，但成绩单里找不到对应课程"
        return f"简历没写「{skill}」，成绩单里也没有对应课程"
    seg = f"《{course['name']}》"
    if course["score"] is not None:
        seg += f" {_fmt_score(course['score'])} 分"
        if course["percentile"] is not None:
            seg += f"（{_top_txt(course['percentile'])}）"
    else:
        seg += "在成绩单里没有分数记录"
    return seg + _EVIDENCE_TAIL[status]


def _build_items(skills: list[str], courses: list[dict[str, Any]],
                 resume_text: str) -> list[dict[str, Any]]:
    """逐个岗位技能判状态；条目顺序 = 岗位技能标签顺序（契约未规定排序，取录入序）。"""
    items: list[dict[str, Any]] = []
    for skill in skills:
        course, match = _pick_course(skill, courses)
        in_resume = _in_resume(skill, resume_text)
        status = _decide_status(course, in_resume)
        score = course["score"] if course is not None else None
        pct = course["percentile"] if course is not None else None
        credit = course["credit"] if course is not None else None
        items.append({
            "skill": skill,
            "status": status,
            "status_label": STATUS_LABELS[status],
            "course": course["name"] if course is not None else None,
            "score": round(score, 2) if score is not None else None,
            "percentile": round(pct, 1) if pct is not None else None,
            "credit": round(credit, 1) if credit is not None else None,
            "match": round(match, 2),
            "in_resume": in_resume,
            "evidence": _evidence(skill, status, course, in_resume),
        })
    return items


def _hidden_assets(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """hidden 条目按 score 降序取前 4，给出可直接粘进简历的建议句。"""
    hidden = [it for it in items if it["status"] == "hidden"]
    hidden.sort(key=lambda it: -(it["score"] if it["score"] is not None else 0.0))
    out: list[dict[str, Any]] = []
    for it in hidden[:4]:
        score_txt = _fmt_score(it["score"])
        top = _top_txt(it["percentile"])
        why = f"岗位要求{it['skill']}，你这门课 {score_txt} 分"
        suggestion = (f"在简历「技能」栏加一行：{it['skill']}"
                      f"（《{it['course']}》{score_txt} 分")
        if top:
            why += f"（{top}）"
            suggestion += f"，{top}"
        why += "，但简历里一个字没提"
        suggestion += "）"
        out.append({
            "skill": it["skill"],
            "course": it["course"],
            "score": it["score"],
            "percentile": it["percentile"],
            "why": why,
            "suggestion": suggestion,
        })
    return out


def _gaps(items: list[dict[str, Any]],
          catalog: Sequence[str] | None) -> list[dict[str, Any]]:
    """gap + claimed 的补法：catalog 反查到课程就点名课程，查不到给方向性一句。"""
    out: list[dict[str, Any]] = []
    for it in items:
        if it["status"] not in ("gap", "claimed"):
            continue
        found = find_courses_for_skill(it["skill"], catalog or ())
        if found:
            first = found[0]
            if it["status"] == "gap":
                fix = f"先修/重学《{first}》，把「{it['skill']}」学到位再写进简历"
            else:
                fix = (f"在《{first}》里做出一个可写进简历的项目成果，"
                       f"给「{it['skill']}」补上成绩背书")
            out.append({"skill": it["skill"], "fix": fix,
                        "how": "course", "courses": found})
        else:
            if it["status"] == "gap":
                fix = (f"先补{it['skill']}基础：跟公开教程完整跑通一个小项目，"
                       f"做出结果后再写进简历")
            else:
                fix = (f"「{it['skill']}」目前只有自述：找一个小项目把它做实，"
                       f"再回简历补一条可验证的证据")
            out.append({"skill": it["skill"], "fix": fix,
                        "how": "self", "courses": []})
    return out


def _hooks(items: list[dict[str, Any]]) -> list[str]:
    """proven + hidden 按 score 降序取前 3；hidden 用「主动暴露资产」话术（口径 4）。"""
    pool = [it for it in items
            if it["status"] in ("proven", "hidden") and it["score"] is not None]
    pool.sort(key=lambda it: -it["score"])  # 稳定排序，同分保持条目顺序
    out: list[str] = []
    for it in pool[:3]:
        if it["status"] == "proven":
            out.append(f"你在《{it['course']}》里学过{it['skill']}，"
                       f"说一个你用「{it['skill']}」解决过的具体问题（背景、做法、结果数字）。")
        else:
            out.append(f"你《{it['course']}》考了 {_fmt_score(it['score'])} 分"
                       f"但简历没写{it['skill']}——面试时主动讲一个你用"
                       f"「{it['skill']}」做过的事，把这门课变成加分项。")
    return out


def _first(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    return items[0] if items else None


def _course_seg(it: dict[str, Any]) -> str:
    """「SQL（来自《数据库原理》88 分）」式短语：必须点名技能与课程。"""
    seg = f"「{it['skill']}」（来自《{it['course']}》"
    if it["score"] is not None:
        seg += f"{_fmt_score(it['score'])} 分"
    else:
        seg += "暂无成绩"
    return seg + "）"


def _lacks_text(items: list[dict[str, Any]], counts: dict[str, int]) -> str:
    """critical 用：点名差在哪几项 + 状态分布。

    早期版本给每项都挂一遍「（只有自述，没有成绩支撑）」，三项连着读像复读机；
    改成先点名字、再给一次分布，同样的信息量，读起来不啰嗦。
    """
    names = "、".join(f"「{it['skill']}」" for it in items[:3])
    # 有课程可查的失分点必须点名课程与分数——只说「技能不行」等于没说
    seg = ""
    for it in items[:3]:
        if it["status"] == "weak" and it["course"] is not None:
            seg = (f"，如「{it['skill']}」在《{it['course']}》"
                   f"只有 {_fmt_score(it['score']) if it['score'] is not None else '—'} 分")
            break
    dist = "、".join(f"{counts[k]} 项{_SHORT_LABEL[k]}"
                     for k in ("claimed", "gap", "weak") if counts.get(k))
    return f"其中最要紧的是{names}{seg}" + (f"；{dist}" if dist else "")


def _narrative(level: str, job_title: str, items: list[dict[str, Any]],
               counts: dict[str, int], hidden_assets: list[dict[str, Any]]) -> str:
    """按 level 四档给完全不同的结论：必须点名具体技能与课程（有课程数据时）。"""
    if level == "unknown":
        return (f"「{job_title}」没有给出任何技能标签，无法评估就绪度——"
                f"先换一个带技能要求的岗位，或手工补上技能标签再回来测。")

    by = {key: [it for it in items if it["status"] == key] for key in _COUNT_ORDER}
    anchored = [it for it in items if it["course"] is not None]
    anchor = _first(by["proven"]) or _first(by["hidden"]) or _first(anchored)

    if level == "high":
        seg = _course_seg(anchor) if anchor else ""
        tail = (f"{counts['hidden']} 项好成绩还没写进简历，把课程名补进去再投。"
                if counts["hidden"] else "简历与成绩单已经对得上，直接投。")
        return (f"「{job_title}」要求的 {len(items)} 项技能里，{counts['proven']} 项"
                f"有成绩单背书{('，如' + seg) if seg else ''}；{tail}"
                f"这份证据任何匹配度工具都给不了。")

    # mid / low 共用：只念非零项，否则会出现「0 项学过没学牢」这种废字
    def _bits(pairs: list[tuple[int, str]]) -> str:
        return "、".join(f"{n} 项{w}" for n, w in pairs if n)

    if level == "mid":
        lead = f"核心技能{_course_seg(anchor)}已经在手，但" if anchor is not None else ""
        detail = _bits([(counts["hidden"], "好成绩压根没写进简历"),
                        (counts["claimed"], "只有自述没有成绩背书"),
                        (counts["weak"], "学过但分数不到 70")]) or "缺口集中在没学过的技能上"
        return (f"{lead}{detail}。"
                f"先把被埋没的资产补进简历、给自述技能配上课程证据，说法补齐就能投。")

    if level == "low":
        weak = _first(by["weak"])
        seg = ""
        if weak is not None and weak["course"] is not None:
            seg = (f"（「{weak['skill']}」在《{weak['course']}》只考了 "
                   f"{_fmt_score(weak['score']) if weak['score'] is not None else '—'} 分）")
        body = _bits([(counts["gap"], "完全空白"),
                      (counts["weak"], "学过没学牢"),
                      (counts["claimed"], "只有自述")]) or "多数技能缺证据"
        cheap = ""
        if hidden_assets:
            top = hidden_assets[0]
            cheap = (f"不过你还有 {len(hidden_assets)} 项成绩很好的课没写进简历"
                     f"（如「{top['skill']}」{_fmt_score(top['score'])} 分），"
                     f"先补进去，等于白捡")
        return (f"「{job_title}」缺口明显：{body}{seg}。{cheap}"
                f"剩下的按 gaps 里的课程路径补，先补命中率最高的那一项。")

    # critical：说清差在哪几项上，禁止「加油」
    lacks = [it for it in items if it["status"] in ("gap", "weak", "claimed")]
    body = _lacks_text(lacks or items, counts) if (lacks or items) else "这个岗位的技能标签为空"
    return (f"离「{job_title}」还差得远：{len(lacks)} 项技能拿不出证据，{body}。"
            f"现在投大概率一轮游——先按 gaps 里的课程路径，把最关键的那一项补到位。")


def _advice(items: list[dict[str, Any]], hidden_assets: list[dict[str, Any]],
            gaps: list[dict[str, Any]]) -> list[dict[str, str]]:
    """2~3 条可直接执行的动作；when 只取契约允许的三个值。"""
    acts: list[dict[str, str]] = []

    if hidden_assets:
        top = hidden_assets[0]
        acts.append({
            "when": WHEN_NOW,
            "what": top["suggestion"],
            "why": (f"《{top['course']}》你考了 {_fmt_score(top['score'])} 分，"
                    f"这是有成绩单背书的证据，不写进简历是白白浪费。"),
        })

    gap0 = _first(gaps)
    if gap0 is not None:
        acts.append({
            "when": WHEN_TERM if gap0["how"] == "course" else WHEN_SOON,
            "what": gap0["fix"],
            "why": (f"「{gap0['skill']}」目前是{STATUS_LABELS[
                        next(it['status'] for it in items if it['skill'] == gap0['skill'])]}"
                    f"，这是离岗位要求最远的缺口之一。"),
        })

    weak = [it for it in items if it["status"] == "weak"]
    if weak and len(acts) < 3:
        it = weak[0]
        acts.append({
            "when": WHEN_TERM,
            "what": f"重学《{it['course']}》里与「{it['skill']}」对应的章节，"
                    f"做完课后题再自测一轮",
            "why": (f"《{it['course']}》只有 {_fmt_score(it['score'])} 分，"
                    f"学过没学牢，面试深挖两句就会露馅。"),
        })

    # 极端输入也要凑满 2 条，但绝不说空话之外的编造内容
    fallbacks = [
        {
            "when": WHEN_NOW,
            "what": "补齐成绩单（课程名 / 学分 / 成绩）并核对简历里的技能清单",
            "why": "证据链两边都齐了，就绪度评估才可信；缺一边就只能看到现象。",
        },
        {
            "when": WHEN_SOON,
            "what": "对照岗位技能标签逐条检查简历：写过的给证据，没写的评估是否补课",
            "why": "就绪度的每一项状态都对应一个简历动作，逐条过一遍不漏资产。",
        },
    ]
    for fb in fallbacks:
        if len(acts) >= 2:
            break
        acts.append(fb)
    return acts[:3]


# ----------------------------------------------------------------
# 主入口
# ----------------------------------------------------------------
def assess(job: Mapping[str, Any], courses: Sequence[Mapping[str, Any]],
           resume_text: str, catalog: Sequence[str] | None = None) -> dict:
    """岗位就绪度评估：逐技能判证据等级，产出就绪度、被埋没的资产与补课路径。

    参数：
      job: {"title": str, "industry": str | None, "skills": [str, ...]}
      courses: [{"name": str, "score": float | None, "credit": float | None,
                 "percentile": float | None}]（percentile 为 0~100 分位）
      resume_text: 简历全文（自由文本）
      catalog: 学校开设的全部课程名，用于给空白技能找补课路径，可为空

    返回字段与契约第 13 节逐字一致（version/job_title/industry/readiness/level/
    level_label/counts/items/hidden_assets/gaps/interview_hooks/narrative/advice），
    不增不减不改名。对 None / 空输入不抛异常；n_items == 0 时 readiness=None、
    level="unknown"。
    """
    title = str(job.get("title") or "").strip() if isinstance(job, Mapping) else ""
    industry = (str(job.get("industry") or "").strip()
                if isinstance(job, Mapping) else "") or None
    skills = _clean_skills(job)
    course_list = _clean_courses(courses)
    resume = str(resume_text or "")

    items = _build_items(skills, course_list, resume)

    # counts：五键齐全、顺序固定（缺失记 0）
    counts: dict[str, int] = {key: 0 for key in _COUNT_ORDER}
    for it in items:
        counts[it["status"]] += 1

    n_items = len(items)
    if n_items == 0:
        readiness: float | None = None
        level = "unknown"
        level_label = LEVEL_UNKNOWN_LABEL
    else:
        readiness = round(100.0 * sum(STATUS_WEIGHTS[it["status"]] for it in items) / n_items, 1)
        if readiness >= _LEVEL_HIGH:
            level = "high"
        elif readiness >= _LEVEL_MID:
            level = "mid"
        elif readiness >= _LEVEL_LOW:
            level = "low"
        else:
            level = "critical"
        level_label = LEVEL_LABELS[level]

    hidden_assets = _hidden_assets(items)
    gaps = _gaps(items, catalog)

    return {
        "version": READINESS_VERSION,
        "job_title": title or "未命名岗位",
        "industry": industry,
        "readiness": readiness,
        "level": level,
        "level_label": level_label,
        "counts": counts,
        "items": items,
        "hidden_assets": hidden_assets,
        "gaps": gaps,
        "interview_hooks": _hooks(items),
        "narrative": _narrative(level, title or "未命名岗位", items, counts, hidden_assets),
        "advice": _advice(items, hidden_assets, gaps),
    }
