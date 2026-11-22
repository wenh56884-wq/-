# engine/attribution.py
# 职责：把「第几轮漏了哪些考点」反查到学生的课程与成绩，判断这场失分是「基础薄弱」还是
#       「表达组织」——即把「你不会说」和「你没学扎实」分开。这是诊断分型，不是打分。
# 铁律：引擎定数，模型说话。纯函数、无随机、无网络、无 LLM、无数据库。
# 缺失不冒充：匹配不到课程就进 unmatched，绝不拿「最像的那门」硬凑；没有课程数据就不下结论。
#
# 为什么市面没有：商业面试产品只输出「表达分」，拿不到学生的课程、学分与专业内分位；
# 高校有完整成绩母体，才能把漏掉的考点反查到「哪门课、多少分、什么位次」，从而区分
# 「没学过 / 没学懂」与「学懂了但没讲出来」。这是启航独有数据才能成立的诊断。
#
# 口径澄清（契约第 8 节未写死或自相矛盾处，按最合理方式定，改动须同步契约）：
# 1) 2-gram 覆盖率按「考点被课程名覆盖」单向计算：|bigram(考点) ∩ bigram(课程名)|
#    / |bigram(考点)|。反向覆盖率不参与，避免长课程名把短考点吞掉。考点不足 2 个字符时
#    没有 2-gram，一律判不命中（宁缺勿滥，不靠单字硬猜）。
# 2) verdict 三档：契约原文「percentile<40 或 score<70 → 薄弱；<60 → 一般」中，第二个
#    「<60」若指 score 则永远不可达（score<60 已被 score<70 吞掉），故按 percentile 维度
#    解释：40<=percentile<60 → 课程掌握一般。percentile 缺失时「只按分数判」用 70/80
#    两档（对应正态分布下约 40/60 分位，与上面的分位阈值同构）。
# 3) 课程既无 score 又无 percentile：verdict 记「课程数据不足」，且不计入薄弱——
#    没有成绩就不说人家基础差，这是「缺失不冒充」的直接推论。
# 4) cohort_stats 仅用于给「有成绩、无分位」的课补一个分位估计（p25/p75 线性插值），
#    不给有分位的课覆盖真实分位，也不新增返回字段。
# 5) 无可匹配条目时 missed_share_weak=None（0/0 无定义），不填 0 冒充「不薄弱」。
# 6) 考点匹配上了、但所有对应课程都既无 score 又无 percentile 时，同样归 unknown
#    （share 也记 None）：分不出基础还是表达，就不假装分得出来。

from __future__ import annotations

from typing import Any

from engine.interview import _norm

ATTRIBUTION_VERSION = "attribution-v1"

# 分型 → 中文标签（契约固定四值，不得增删）
TYPE_LABELS: dict[str, str] = {
    "foundation": "基础薄弱型",
    "expression": "表达组织型",
    "mixed": "混合型",
    "unknown": "证据不足",
}

# 软性答题要点：动机 / 沟通 / 自我表达类，不对应任何课程。它们不参与课程匹配，
# 但必须被计入「表达型」判定——否则真实面试里大量通用失分会被误判成「证据不足」。
SOFT_TERMS: frozenset[str] = frozenset({
    "兴趣", "项目", "项目经历", "学习方法", "学习能力", "源码", "实践", "实习",
    "规划", "职业规划", "动机", "匹配", "沟通", "团队", "团队协作", "压力", "抗压",
    "为什么", "看法", "态度", "性格", "优缺点", "目标", "经历", "自我介绍",
    "岗位理解", "公司了解", "稳定性", "薪资", "反问", "细节", "结果", "动作",
})

# 考点 → 上位技能：面试考点多是下位概念（「交叉验证」），课程培养的是上位技能（「机器学习」）。
# 没有这层向上归并，技能桥几乎连不上任何课程——这是「知识图谱技能上下位」的轻量实现。
CONCEPT_PARENT: dict[str, str] = {
    "交叉验证": "机器学习", "过拟合": "机器学习", "欠拟合": "机器学习", "正则化": "机器学习",
    "泛化": "机器学习", "训练集": "机器学习", "验证集": "机器学习", "特征工程": "机器学习",
    "模型评估": "机器学习", "损失函数": "机器学习", "调参": "机器学习", "样本": "机器学习",
    "神经网络": "深度学习", "卷积": "深度学习", "反向传播": "深度学习",
    "数据漂移": "数据分析", "指标体系": "数据分析", "报表": "数据分析", "可视化": "数据分析",
    "数据清洗": "数据治理", "数据仓库": "数据治理", "ETL": "数据治理", "元数据": "数据治理",
    "索引": "数据库", "事务": "数据库", "范式": "数据库", "慢查询": "数据库",
    "缓存": "后端开发", "并发": "后端开发", "接口": "后端开发", "线程池": "后端开发",
    "日志": "运维", "监控": "运维", "回滚": "运维", "容器化": "运维", "自动化测试": "软件测试",
}


def _to_parent(concept: str) -> str:
    """考点先向上归并到技能；没登记的原样返回（不猜）。"""
    return CONCEPT_PARENT.get(_norm(concept), concept)

# 单门课的判定（契约三个值 + 数据不足这个诚实的第四值，见口径 3）
VERDICT_WEAK = "课程基础薄弱"
VERDICT_FAIR = "课程掌握一般"
VERDICT_GOOD = "课程掌握良好"
VERDICT_NO_DATA = "课程数据不足"

# 契约阈值：2-gram 覆盖率 >=0.5 命中；薄弱占比 >=0.6 foundation、<=0.25 expression
MATCH_MIN_COVERAGE = 0.5
FOUNDATION_MIN_SHARE = 0.6
EXPRESSION_MAX_SHARE = 0.25

# actions 的 when 只取契约允许的值：本周 / 两周内 / 本学期（本引擎只用前两个，按紧迫度排）
WHEN_SOON = "本周"
WHEN_LATER = "两周内"

_WEAK_RANK: dict[str, int] = {
    VERDICT_WEAK: 0, VERDICT_NO_DATA: 1, VERDICT_FAIR: 2, VERDICT_GOOD: 3,
}


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


def _clamp(value: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, value))


def _bigrams(text: str) -> set[str]:
    """对归一化后的文本取 2-gram（中文按字符切，英文按字母切，均已小写）。"""
    t = _norm(text)
    if len(t) < 2:
        return set()
    return {t[i:i + 2] for i in range(len(t) - 1)}


def _coverage(concept: str, course_name: str) -> float:
    """考点被课程名覆盖的 2-gram 比例，0~1。考点不足 2 字符 → 0（不硬猜）。"""
    cb = _bigrams(concept)
    if not cb:
        return 0.0
    return len(cb & _bigrams(course_name)) / len(cb)


def _rounds_text(rounds: list[int]) -> str:
    """[3,5] -> 第3、5轮；[2] -> 第2轮。"""
    if not rounds:
        return "本次"
    return "第" + "、".join(str(r) for r in rounds) + "轮"


def _clean_rounds(missed_by_round: Any) -> list[tuple[int, str]]:
    """把 {轮次: [考点]} 摊平成 [(轮次, 考点)]，保持轮次升序；脏数据丢弃不抛异常。"""
    pairs: list[tuple[int, str]] = []
    if not isinstance(missed_by_round, dict):
        return pairs
    for key, values in missed_by_round.items():
        rnd = _num(key)
        if rnd is None:
            continue
        if isinstance(values, (str, bytes)):
            values = [values]
        if not isinstance(values, (list, tuple, set)):
            continue
        for raw in values:
            concept = str(raw or "").strip()
            if concept:
                pairs.append((int(rnd), concept))
    pairs.sort(key=lambda p: p[0])
    return pairs


def _clean_courses(courses: Any) -> list[dict[str, Any]]:
    """只保留有名字的课程；分数/学分/分位取不到就是 None（不填 0）。"""
    out: list[dict[str, Any]] = []
    if not isinstance(courses, (list, tuple)):
        return out
    for raw in courses:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        cid = _num(raw.get("course_id"))
        percentile = _num(raw.get("percentile"))
        out.append({
            "course_id": int(cid) if cid is not None else None,
            "name": name,
            "credit": _num(raw.get("credit")),
            "score": _num(raw.get("score")),
            "percentile": _clamp(percentile, 0.0, 100.0) if percentile is not None else None,
            # 课程培养的技能（来自 engine.kg.skills_for_course）：考点命中技能即命中课程
            "skills": [str(x) for x in (raw.get("skills") or []) if str(x).strip()],
        })
    return out


def _cohort_lookup(cohort_stats: Any) -> dict[str, dict[str, Any]]:
    """cohort_stats 的键做同样的归一化，便于与课程名对齐。"""
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(cohort_stats, dict):
        return out
    for key, stats in cohort_stats.items():
        if isinstance(stats, dict):
            out[_norm(str(key))] = stats
    return out


def _cohort_percentile(score: float | None, name: str,
                       cohort: dict[str, dict[str, Any]]) -> float | None:
    """用同专业 p25/p75 线性插值估分位；只用于「有成绩、无分位」的课。"""
    if score is None:
        return None
    stats = cohort.get(_norm(name))
    if not stats:
        return None
    p25, p75 = _num(stats.get("p25")), _num(stats.get("p75"))
    if p25 is None or p75 is None:
        return None
    if p75 > p25:
        pct = 25.0 + (score - p25) / (p75 - p25) * 50.0
    elif score > p25:  # p25==p75 的退化分布：只能给个保守的三分位
        pct = 60.0
    elif score < p25:
        pct = 40.0
    else:
        pct = 50.0
    return round(_clamp(pct, 0.0, 100.0), 1)


def _verdict(score: float | None, percentile: float | None) -> str:
    """单门课判定（口径 2/3）：先看绝对分，再看分位，最后才是分位缺失下的分数分档。"""
    if score is None and percentile is None:
        return VERDICT_NO_DATA
    if score is not None and score < 70:
        return VERDICT_WEAK
    if percentile is not None and percentile < 40:
        return VERDICT_WEAK
    if percentile is not None:
        return VERDICT_FAIR if percentile < 60 else VERDICT_GOOD
    return VERDICT_FAIR if score is not None and score < 80 else VERDICT_GOOD


def _is_soft(concept: str) -> bool:
    """软性答题要点：精确命中黑名单才算（避免「项目管理」被误伤）。"""
    return _norm(concept) in SOFT_TERMS


def _skill_index(courses: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """归一化技能 → 开设该技能课程的索引（同一技能可能有多门课）。"""
    idx: dict[str, list[dict[str, Any]]] = {}
    for course in courses:
        for skill in course.get("skills") or []:
            key = _norm(skill)
            if key and course not in idx.setdefault(key, []):
                idx[key].append(course)
    return idx


def _skill_pick(concept: str, idx: dict[str, list[dict[str, Any]]]) -> dict[str, Any] | None:
    """考点命中所培养技能 → 返回该技能下学分最高的课程（强证据）。

    允许双向包含：「数据治理」命中技能「数据治理」；「数据分析」命中「数据分析与可视化」。
    短词（<2 字）不参与包含匹配，宁缺勿滥。
    """
    key = _norm(concept)
    if not key:
        return None
    best: dict[str, Any] | None = None
    for skill, courses in idx.items():
        if not skill:
            continue
        hit = key == skill or (len(key) >= 2 and (key in skill or skill in key))
        if not hit:
            continue
        for course in courses or []:
            if best is None:
                best = course
                continue
            if (course.get("credit") or 0.0) > (best.get("credit") or 0.0):
                best = course
    return best


def _pick_course(concept: str, courses: list[dict[str, Any]],
                 idx: dict[str, list[dict[str, Any]]] | None = None) -> tuple[dict[str, Any], float] | None:
    """先走技能桥（强命中），再退回课程名 2-gram；多门命中取学分大者。"""
    """多门命中取 credit 大者，同 credit 取覆盖率高者，再同则取录入顺序前者（确定性）。"""
    if idx:
        via_skill = _skill_pick(_to_parent(concept), idx)
        if via_skill is not None:
            return via_skill, 1.0
    best: tuple[dict[str, Any], float] | None = None
    for course in courses:
        cov = _coverage(concept, course["name"])
        if cov < MATCH_MIN_COVERAGE:
            continue
        if best is None:
            best = (course, cov)
            continue
        cur_course, cur_cov = best
        cur_credit = cur_course["credit"] if cur_course["credit"] is not None else 0.0
        new_credit = course["credit"] if course["credit"] is not None else 0.0
        if (new_credit, round(cov, 6)) > (cur_credit, round(cur_cov, 6)):
            best = (course, cov)
    return best


# ----------------------------------------------------------------
# 组装：条目 / 分型 / 结论 / 动作
# ----------------------------------------------------------------
def _build_items(pairs: list[tuple[int, str]], courses: list[dict[str, Any]],
                 cohort: dict[str, dict[str, Any]])         -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """考点 → 课程。同一考点多轮出现合并成一条；软性要点单独抽出（不参与课程匹配）。"""
    idx = _skill_index(courses)
    grouped: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    soft: list[str] = []
    for rnd, concept in pairs:
        if _is_soft(concept):
            if concept not in soft:
                soft.append(concept)
            continue
        key = _norm(concept)
        if key not in grouped:
            grouped[key] = {"concept": concept, "rounds": set()}
            order.append(key)
        grouped[key]["rounds"].add(rnd)

    items: list[dict[str, Any]] = []
    unmatched: list[str] = []
    for key in order:
        entry = grouped[key]
        hit = _pick_course(entry["concept"], courses, idx)
        if hit is None:
            if entry["concept"] not in unmatched:
                unmatched.append(entry["concept"])
            continue

        course, _cov = hit
        score = course["score"]
        percentile = course["percentile"]
        estimated = False
        if percentile is None:  # 有成绩无分位 → 用班级 p25/p75 估一个（口径 4）
            percentile = _cohort_percentile(score, course["name"], cohort)
            estimated = percentile is not None

        verdict = _verdict(score, percentile)
        rounds = sorted(entry["rounds"])
        rounds_txt = _rounds_text(rounds)
        evidence = f"{rounds_txt}都漏掉了这个考点" if len(rounds) > 1 else f"{rounds_txt}漏掉了这个考点"
        if score is not None:
            evidence += f"，该课 {score:.1f} 分"
        else:
            evidence += "，成绩单里没有这门课的分数"
        if percentile is not None:
            evidence += f"、专业内分位 {percentile:.1f}" + ("（由班级 p25/p75 估算）" if estimated else "")
        if verdict == VERDICT_WEAK:
            evidence += "，属于基础没吃透"
        elif verdict == VERDICT_FAIR:
            evidence += "，掌握一般"
        elif verdict == VERDICT_GOOD:
            evidence += "，课学得不错，属于会但没讲出来"
        else:
            evidence += "，暂不下判定"

        items.append({
            "concept": entry["concept"],
            "course": course["name"],
            "course_id": course["course_id"],
            "score": round(score, 2) if score is not None else None,
            "percentile": round(percentile, 1) if percentile is not None else None,
            "credit": round(course["credit"], 1) if course["credit"] is not None else None,
            "rounds": rounds,
            "verdict": verdict,
            "evidence": evidence,
        })

    # 薄弱在前，其次按分数低→高；同分按学分高→低，最后按课程名，保证确定性
    items.sort(key=lambda it: (
        _WEAK_RANK.get(str(it["verdict"]), 9),
        it["score"] if it["score"] is not None else 999.0,
        -(it["credit"] or 0.0),
        str(it["course"]),
    ))
    return items, unmatched, soft


def _name_scores(items: list[dict[str, Any]], limit: int) -> str:
    """《课名》（分数，分位）串，最多 limit 门。"""
    parts: list[str] = []
    seen: set[str] = set()
    for it in items:
        name = str(it.get("course") or "")
        if not name or name in seen:
            continue
        seen.add(name)
        seg = f"《{name}》"
        if it.get("score") is not None:
            seg += f"（{it['score']:.1f} 分"
            seg += f"，专业内分位 {it['percentile']:.1f}" if it.get("percentile") is not None else ""
            seg += "）"
        parts.append(seg)
        if len(parts) >= limit:
            break
    return "、".join(parts)


def _round_detail(items: list[dict[str, Any]], limit: int = 2) -> str:
    """第3、5轮漏「A」、第4轮漏「B」——点名轮次与考点。"""
    parts = [f"{_rounds_text(it['rounds'])}漏「{it['concept']}」"
             for it in items[:limit] if it.get("rounds")]
    return "、".join(parts)


def _has_data(item: dict[str, Any]) -> bool:
    """这门课到底有没有可判定的成绩证据（分数或分位至少一个）。"""
    return item.get("score") is not None or item.get("percentile") is not None


def _strength_phrase(others: list[dict[str, Any]]) -> str:
    """表达型结论里对「课学得好」的措辞必须与证据一致，不能一律吹成「学得不错」。"""
    scored = [it for it in others if _has_data(it)]
    scores = [it["score"] for it in scored if it.get("score") is not None]
    pcts = [it["percentile"] for it in scored if it.get("percentile") is not None]
    if not scored:
        return "成绩单里还没有分数，谈不上基础问题"
    if scores and min(scores) >= 80:
        return "最低也有 80 分，课本身没问题"
    if pcts and min(pcts) >= 50:
        return "分位都在中上，课本身没问题"
    return "都在 70 分以上，不属于没学"


def _first_with_data(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    """优先拿有成绩的条目写动作，避免动作里出现「你有成绩」这种空话。"""
    for it in items:
        if _has_data(it):
            return it
    return items[0] if items else None


def _narrative(kind: str, items: list[dict[str, Any]], weak: list[dict[str, Any]],
               others: list[dict[str, Any]], unmatched: list[str],
               share: float | None, course_count: int,
               soft: list[str] | None = None, soft_rounds: list[int] | None = None) -> str:
    """按分型给完全不同的结论：必须点名课程与轮次，禁止「继续努力」这类套话。"""
    soft = list(soft or [])
    if kind == "expression" and not items:
        # 失分全在动机/项目/沟通类要点上：这不是「证据不足」，而是明确的表达型
        rounds_txt = _rounds_text(sorted(set(soft_rounds or []))) if soft_rounds else "本场"
        soft_txt = "、".join(f"「{c}」" for c in soft[:3]) or "通用要点"
        return (f"{rounds_txt}漏掉的{soft_txt}都是动机与自我表达类要点，不涉及专业课程知识——"
                f"这类失分与你的成绩无关，是组织与表达的问题：你答了，但没按面试官要的顺序"
                f"把结论、论据、例子摆出来。先把已有经历压成 90 秒能讲完的答案，不需要重学课程。")
    if not items and not unmatched:
        return ("这一场没有传进来任何漏掉的考点，无法做归属判断。"
                "先完整跑一场有评分的模拟面试，再回来看课程溯源。")

    if kind == "unknown":
        all_rounds = sorted({r for it in items for r in it.get("rounds") or []})
        rounds_txt = _rounds_text(all_rounds) if all_rounds else "本轮"
        if items:  # 课程对上了，但成绩单里没有分数——不许假装能判定
            return (f"{rounds_txt}漏掉的考点能对上{_name_scores(items, 2)}，"
                    f"但这几门课在成绩单里既没有分数也没有专业内分位，"
                    f"所以无法判断是基础薄弱还是表达问题。先补齐成绩再回来看归因——"
                    f"没有成绩就下结论，是在猜。")
        concept_txt = "、".join(f"「{c}」" for c in (unmatched or [])[:3]) or "本轮漏掉的考点"
        return (f"{rounds_txt}漏掉的{concept_txt}，在已录入的 {course_count} 门课程里没有任何一门对得上"
                f"（2-gram 覆盖率都低于 {MATCH_MIN_COVERAGE:.1f}），所以无法判断是基础薄弱还是表达问题。"
                f"请先补齐成绩单，或把这些考点人工对应到具体课程——证据不足时我不给结论。")

    rounds_txt = _rounds_text(sorted({r for it in items for r in it.get("rounds") or []}))
    n_items, n_weak = len(items), len(weak)
    weak_txt = _name_scores(weak, 2)
    # 只有「有成绩」的课才配进结论：缺成绩的课不能被说成「学得好」
    others_data = [it for it in others if _has_data(it)]
    other_txt = _name_scores(others_data or others, 2)
    missing_n = len(others) - len(others_data)
    gap_note = (f"另有 {missing_n} 个考点对上的课程缺成绩，未参与判定。" if missing_n else "")
    detail = _round_detail(items)

    if kind == "foundation":
        typical = f"，最典型的是「{weak[0]['concept']}」" if weak else ""
        return (f"{rounds_txt}一共漏了 {n_items} 个考点，其中 {n_weak} 个"
                f"（{(share or 0.0) * 100:.0f}%）落在{weak_txt}上{typical}。"
                f"这不是表达问题，是这几门课的基础没打牢——先把课补到 70 分以上，再练话术才算对症。")

    if kind == "expression":
        n_course = len({it["course"] for it in others_data} or {it["course"] for it in others})
        which = "这门课" if n_course == 1 else "这些课"
        return (f"{detail}；而{other_txt}{which}{_strength_phrase(others_data)}。"
                f"知识在，问题在组织与表达：答题时没把学过的东西按面试官要的顺序调出来、讲清楚。"
                f"重点不是重学课程，而是把已有知识压成 90 秒能讲完的答案。{gap_note}")

    return (f"{rounds_txt}的 {n_items} 个考点里，{n_weak} 个落在{weak_txt}上（基础没打牢），"
            f"另外 {len(others_data)} 个落在{other_txt}上"
            f"（{_strength_phrase(others_data)}，却没答出来）；{detail}。"
            f"这是混合型失分：基础缺口要重学，表达缺口要练复述，两类问题分开补，别一起归咎于「紧张」。"
            f"{gap_note}")


def _course_action(item: dict[str, Any], when: str) -> dict[str, str]:
    """基础缺口动作：点名课程 + 知识点 + 为什么，学生当天就能动手。"""
    rounds_txt = _rounds_text(item["rounds"])
    score = item.get("score")
    pct = item.get("percentile")
    verb = "都漏了" if len(item["rounds"]) > 1 else "漏了"
    why = f"{rounds_txt}{verb}「{item['concept']}」，而这门课只有 {score:.1f} 分" if score is not None \
        else f"{rounds_txt}{verb}「{item['concept']}」，而这门课没有可用成绩"
    if pct is not None:
        why += f"（专业内分位 {pct:.1f}）"
    return {
        "when": when,
        "what": f"重学《{item['course']}》里「{item['concept']}」这一章，"
                f"先做 5 道该考点的自测题，再做下一场模拟",
        "why": why + "，这是本次失分的直接来源。",
    }


def _express_action(item: dict[str, Any], when: str) -> dict[str, str]:
    """表达缺口动作：课是好课，练的是提取与组织。"""
    score = item.get("score")
    pct = item.get("percentile")
    base = f"《{item['course']}》你 {score:.1f} 分" if score is not None \
        else f"《{item['course']}》你成绩单里没有分数"
    if pct is not None:
        base += f"（分位 {pct:.1f}）"
    return {
        "when": when,
        "what": f"把《{item['course']}》里的「{item['concept']}」写成 90 秒口述稿："
                f"先给结论，再给两条论据，最后补一个课程项目里的数字",
        "why": f"{base}，知识不缺；第{int(item['rounds'][0])}轮问到却没组织出来，缺的是提取与表达。",
    }


def _drill_action(item: dict[str, Any] | None, when: str = WHEN_LATER) -> dict[str, str]:
    """兜底但具体的练习动作：不空谈，给可计数的量。"""
    name = f"《{item['course']}》" if item else "最近一门专业课"
    return {
        "when": when,
        "what": f"把{name}的核心概念做成 10 张卡片，每天抽 3 张做 60 秒口头复述并录音回听",
        "why": "漏考点集中在概念层，复述能检验是「记不住」还是「说不出来」，两种问题补法不同。",
    }


def _actions(kind: str, weak: list[dict[str, Any]], others: list[dict[str, Any]],
             unmatched: list[str], items: list[dict[str, Any]],
             soft: list[str] | None = None) -> list[dict[str, str]]:
    """2~3 条可直接执行的动作，按薄弱程度排序；when 只取契约允许的三个值。"""
    acts: list[dict[str, str]] = []

    if kind == "unknown":
        acts.append({
            "when": WHEN_SOON,
            "what": "补齐本学期成绩单（课程名 / 学分 / 成绩），或绑定教务数据同步",
            "why": "现在漏掉的考点对不上课程或缺成绩，缺课程映射就只能看到现象，判断不了是基础还是表达问题。",
        })
        concepts = unmatched or [str(it["concept"]) for it in items]
        concept_txt = "、".join(f"「{c}」" for c in concepts[:2]) or "（本轮无记录）"
        acts.append({
            "when": WHEN_LATER,
            "what": f"把漏掉的考点{concept_txt}对应课程的成绩补进系统（课程名 / 学分 / 成绩）",
            "why": "考点与课程、成绩对上之后，才能给出可执行的重学清单，而不是泛泛建议多练。",
        })
        return acts[:3]

    if kind in ("foundation", "mixed"):
        used: set[str] = set()
        for item in weak:
            if item["course"] in used:
                continue
            used.add(item["course"])
            acts.append(_course_action(item, WHEN_SOON if not acts else WHEN_LATER))
            if len(acts) >= 2:
                break

    if kind == "expression" and not items:
        # 软性失分：不需要重学课程，练的是把经历说成结构化答案
        terms = "、".join(f"「{c}」" for c in (soft or [])[:2]) or "动机、项目类问题"
        acts.append({
            "when": WHEN_SOON,
            "what": f"针对{terms}各写一份 90 秒口述稿：结论一句话、两条论据、一个具体例子，写完录音回听",
            "why": "这类要点不考课程知识，考的是把已有经历按面试官要的顺序讲出来，写稿是最快的改法。",
        })
        acts.append({
            "when": WHEN_LATER,
            "what": "下一场模拟前，把简历里每段经历都压成「做了什么 / 怎么做 / 结果数字」三句",
            "why": "失分集中在表达层时，答案的骨架比知识量更决定分数。",
        })
        return acts[:3]

    if kind in ("expression", "mixed"):
        rep = _first_with_data(others)
        if rep is not None:
            acts.append(_express_action(rep, WHEN_SOON if kind == "expression" else WHEN_LATER))
        acts.append({
            "when": WHEN_LATER,
            "what": "每场模拟前用 3 分钟写答题提纲：结论 / 两条论据 / 一个例子，写完再开口",
            "why": "你的卡点是把知识排成面试官要的顺序，提纲能把「想得到」变成「说得出」。",
        })

    if kind == "foundation" and len(acts) < 3:
        acts.append(_drill_action(items[0] if items else None, WHEN_LATER))

    # 极端输入（例如只有一条命中且已用满）也要保证 2 条
    while len(acts) < 2:
        acts.append(_drill_action(items[0] if items else None, WHEN_LATER))

    return acts[:3]


# ----------------------------------------------------------------
# 主入口
# ----------------------------------------------------------------
def attribute(missed_by_round: dict[int, list[str]],
              courses: list[dict],
              cohort_stats: dict[str, dict] | None = None) -> dict:
    """失分溯源到课程：把漏掉的考点反查课程，判定基础薄弱 / 表达组织 / 混合 / 证据不足。

    参数：
      missed_by_round: {轮次: [漏掉的考点]}，轮次为 int（字符串数字也兼容）
      courses: [{"course_id","name","credit","score","percentile"}]，percentile 为 0~100 分位
      cohort_stats: {课程名: {"mean","p25","p75","n"}}，可空；只用于给缺分位的课估分位

    返回字段与契约第 8 节逐字一致（version/type/type_label/missed_share_weak/items/
    unmatched/narrative/actions），不增不减不改名。对 None / 空输入不抛异常。
    """
    pairs = _clean_rounds(missed_by_round)
    course_list = _clean_courses(courses)
    cohort = _cohort_lookup(cohort_stats)

    items, unmatched, soft = _build_items(pairs, course_list, cohort)
    weak = [it for it in items if it["verdict"] == VERDICT_WEAK]
    others = [it for it in items if it["verdict"] != VERDICT_WEAK]
    soft_rounds = sorted({rnd for rnd, concept in pairs if _is_soft(concept)})

    if not items and soft:
        # 全是动机/沟通类失分：结论明确——表达型，不是证据不足
        kind = "expression"
        share: float | None = 0.0
    elif not items:
        kind = "unknown"
        share = None
    elif not any(_has_data(it) for it in items):
        # 课程对上了、但一门课都没有分数/分位：分不出基础还是表达，诚实归为证据不足
        kind = "unknown"
        share = None
    else:
        share = round(len(weak) / len(items), 3)
        if share >= FOUNDATION_MIN_SHARE:
            kind = "foundation"
        elif share <= EXPRESSION_MAX_SHARE:
            kind = "expression"
        else:
            kind = "mixed"

    return {
        "version": ATTRIBUTION_VERSION,
        "type": kind,
        "type_label": TYPE_LABELS[kind],
        "missed_share_weak": share,
        "items": items,
        "unmatched": unmatched,
        "soft_skipped": len(soft),
        "narrative": _narrative(kind, items, weak, others, unmatched, share,
                                len(course_list), soft, soft_rounds),
        "actions": _actions(kind, weak, others, unmatched, items, soft),
    }
