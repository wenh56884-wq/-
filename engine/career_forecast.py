# engine/career_forecast.py
# 职责：考公 / 考编 / 考研三条路径的报考竞争力分析与预测（career-forecast-v1）
# 依赖：仅标准库（datetime / dataclasses / typing），不连库、不调大模型
#
# 铁律（三条，违反即视为实现错误）：
#   1. **不给录取概率**。本平台没有录取率样本，任何「上岸概率 73%」都是编的。
#      只输出「档位 + 规则分 + 逐维证据」——每个数字都能倒推回学生自己的成绩单或真实公告。
#   2. **真实数据优先于经验基线**。学生指标（均分、挂科、四六级、政治面貌、每周学时）
#      与同侪位次来自库里的真实成绩；公告日期优先用抓到的真实考试日期；
#      只有「路径基准学时」这类公开经验值才允许写死，且必须在 sources 里标明是经验基线。
#   3. **缺数据即 unknown**。没有四级成绩不当作未通过，没有学时不自造计划，
#      缺一维就把权重归一化并降低置信度；缺三维直接判 unknown，不出分。

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Mapping, Sequence

from engine.career_rules import check_hard_gates

CAREER_FORECAST_VERSION = "career-forecast-v1"

# --- 路径 ---
GOAL_KAOGONG = "考公"
GOAL_KAOBIAN = "考编"
GOAL_KAOYAN = "考研"
FORECAST_GOALS: tuple[str, ...] = (GOAL_KAOGONG, GOAL_KAOBIAN, GOAL_KAOYAN)

# --- 维度级别 ---
LEVEL_STRONG = "strong"
LEVEL_FAIR = "fair"
LEVEL_WEAK = "weak"
LEVEL_POOR = "poor"
LEVEL_UNKNOWN = "unknown"

# --- 综合档位（规则分映射，不是录取概率）---
TIER_SPRINT = "A"
TIER_STEADY = "B"
TIER_CATCHUP = "C"
TIER_RISK = "D"
TIER_UNKNOWN = "?"

TIER_LABEL: dict[str, str] = {
    TIER_SPRINT: "底子扎实，可冲更高目标",
    TIER_STEADY: "够格，短板明确、补上就见效",
    TIER_CATCHUP: "多项低于基线，先补差再谈目标",
    TIER_RISK: "存在硬伤或时间严重不足，建议调整目标或延后一年",
    TIER_UNKNOWN: "关键数据缺失，暂不出结论",
}

TIER_THRESHOLDS: tuple[tuple[str, float], ...] = (
    (TIER_SPRINT, 80.0),
    (TIER_STEADY, 68.0),
    (TIER_CATCHUP, 55.0),
)

# --- 四维定义：key / 中文名 / 该维度的权重（按目标路径不同）---
DIM_ACADEMIC = "academic"
DIM_ENGLISH = "english"
DIM_ELIGIBILITY = "eligibility"
DIM_CAPACITY = "capacity"

DIM_NAMES: dict[str, str] = {
    DIM_ACADEMIC: "学业位次",
    DIM_ENGLISH: "英语门槛",
    DIM_ELIGIBILITY: "资格门槛",
    DIM_CAPACITY: "投入容量",
}


@dataclass(frozen=True)
class PathSpec:
    """一条报考路径的恒定参数。

    weights     四维权重（和为 1）
    baseline_hours  有效备考小时基准——**经验基线**，取自公开备考经验的中位区间，
                不是本平台统计得出的数字，输出时必须标注来源。
    windows     历年考试窗口（月, 日, 说明），用于倒推剩余周数；真实公告有日期时优先用真实值。
    exam_type   对应 `招考公告.考试类型`（civil / institution / postgraduate）
    """

    goal: str
    label: str
    exam_type: str
    weights: dict[str, float]
    baseline_hours: int
    windows: tuple[tuple[int, int, str], ...]
    baseline_note: str


PATHS: dict[str, PathSpec] = {
    GOAL_KAOGONG: PathSpec(
        goal=GOAL_KAOGONG,
        label="公务员（国考 / 省考 / 选调）",
        exam_type="civil",
        # 考公的决定项是「资格够不够」和「时间投入够不够」，学业位次只影响面试印象
        weights={DIM_ACADEMIC: 0.20, DIM_ENGLISH: 0.15, DIM_ELIGIBILITY: 0.30, DIM_CAPACITY: 0.35},
        baseline_hours=700,
        windows=((11, 29, "国考公共科目笔试（历年 11 月底）"), (3, 20, "省考联考笔试（历年 3 月中下旬）")),
        baseline_note="700 小时取自公开备考经验：行测 400 + 申论 300 的中位投入，不含面试",
    ),
    GOAL_KAOBIAN: PathSpec(
        goal=GOAL_KAOBIAN,
        label="事业单位 / 教师编",
        exam_type="institution",
        # 考编门槛比考公松（多数岗位不限党员），但专业与资格证卡得更死，时间投入需求也低一档
        weights={DIM_ACADEMIC: 0.25, DIM_ENGLISH: 0.12, DIM_ELIGIBILITY: 0.28, DIM_CAPACITY: 0.35},
        baseline_hours=500,
        windows=((5, 15, "事业单位联考（历年 5 月中下旬）"), (10, 25, "事业单位四季度统考（历年 10 月下旬）")),
        baseline_note="500 小时取自公开备考经验：职测 300 + 综合应用 200 的中位投入",
    ),
    GOAL_KAOYAN: PathSpec(
        goal=GOAL_KAOYAN,
        label="硕士研究生（统考）",
        exam_type="postgraduate",
        # 考研是学业位次与长周期投入主导，资格门槛几乎人人满足
        weights={DIM_ACADEMIC: 0.40, DIM_ENGLISH: 0.18, DIM_ELIGIBILITY: 0.12, DIM_CAPACITY: 0.30},
        baseline_hours=1200,
        windows=((12, 26, "考研初试（历年 12 月下旬）"),),
        baseline_note="1200 小时取自公开备考经验：数学 400 + 英语 300 + 专业课 350 + 政治 150",
    ),
}

# 单门挂科在学业维度上的扣分（公务员政审、考研复试都会看，但不至于一票否决）
_FAIL_PENALTY = 8.0
_FAIL_PENALTY_CAP = 24.0

# 每周可投入学时的现实上限：在校生还要上课，全职脱产备考也就 50~60 小时/周。
# 超过这个数的「需求学时」说明这个考试窗口已经来不及，不是要求学生每天学 25 小时。
MAX_WEEKLY_HOURS = 60.0

# 政治面貌折算（仅作为资格维度的一部分，不是门槛判定本身）
_POLITICAL_SCORE: dict[str, float] = {
    "中共党员": 100.0,
    "中共预备党员": 88.0,
    "共青团员": 66.0,
}


# ----------------------------------------------------------------
# 基础工具
# ----------------------------------------------------------------
def _num(value: Any) -> float | None:
    """转 float；None / 空串 / 占位符 → None（缺失不冒充 0）。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        text = str(value).strip()
        if not text or text in {"-", "--", "无", "未填", "未知", "None", "null"}:
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def _round(value: float, digits: int = 1) -> float:
    return round(float(value) + 1e-12, digits)


def parse_date(value: Any) -> date | None:
    """把多种写法的日期串解析成 date；解析失败返回 None。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%Y年%m月%d日", "%Y.%m.%d"):
        try:
            return datetime.strptime(text[: len(fmt) + 2], fmt).date()
        except ValueError:
            continue
    # 兜底：只留数字再试
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 8:
        try:
            return date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
        except ValueError:
            return None
    return None


def level_of(score: float | None) -> str:
    """分数 → 四档级别；None → unknown。"""
    if score is None:
        return LEVEL_UNKNOWN
    if score >= 80:
        return LEVEL_STRONG
    if score >= 65:
        return LEVEL_FAIR
    if score >= 50:
        return LEVEL_WEAK
    return LEVEL_POOR


LEVEL_TEXT: dict[str, str] = {
    LEVEL_STRONG: "强",
    LEVEL_FAIR: "中上",
    LEVEL_WEAK: "偏弱",
    LEVEL_POOR: "弱",
    LEVEL_UNKNOWN: "缺数据",
}


# ----------------------------------------------------------------
# 一、考试窗口与剩余时间（真实公告优先）
# ----------------------------------------------------------------
def _next_occurrences(
    windows: Sequence[tuple[int, int, str]],
    today: date,
    horizon_days: int = 800,
) -> list[dict[str, Any]]:
    """把「每年固定月日」展开成未来若干次具体日期，按时间升序。"""
    out: list[dict[str, Any]] = []
    limit = today + timedelta(days=horizon_days)
    for year in range(today.year, limit.year + 1):
        for month, day, label in windows:
            try:
                when = date(year, month, day)
            except ValueError:
                continue
            if when < today or when > limit:
                continue
            out.append(
                {
                    "date": when,
                    "label": label,
                    "basis": "historical_pattern",
                    "weeks_left": max(0, (when - today).days // 7),
                    "days_left": (when - today).days,
                }
            )
    out.sort(key=lambda x: x["date"])
    return out


def plan_windows(
    goal: str,
    today: date | None = None,
    real_exam_dates: Sequence[Any] = (),
    keep: int = 3,
) -> list[dict[str, Any]]:
    """列出该路径未来可用考试窗口。

    真实公告里抓到考试日期时，把它们排在前面（basis=real_notice）——
    真实日期永远优先于「历年规律」，两者不混为一谈。
    """
    base = today or date.today()
    spec = PATHS.get(goal)
    if spec is None:
        return []

    out: list[dict[str, Any]] = []
    seen: set[date] = set()
    for raw in real_exam_dates:
        when = parse_date(raw)
        if when is None or when < base or when in seen:
            continue
        seen.add(when)
        out.append(
            {
                "date": when,
                "label": "已抓取公告中的考试日期",
                "basis": "real_notice",
                "weeks_left": max(0, (when - base).days // 7),
                "days_left": (when - base).days,
            }
        )

    for item in _next_occurrences(spec.windows, base):
        if item["date"] in seen:
            continue
        seen.add(item["date"])
        out.append(item)

    out.sort(key=lambda x: x["date"])
    return out[:keep]


def _pick_primary(
    spec: PathSpec,
    windows: Sequence[Mapping[str, Any]],
    weekly_hours: float | None,
) -> tuple[Mapping[str, Any] | None, str]:
    """选主目标窗口：第一个「按现实上限的周学时也来得及」的窗口。

    只看最近一个窗口是错的——大四 10 月看国考只剩 4 周，需要的周学时超过
    人类上限，那个窗口已经不成立；真正能执行的是下一次省考/考研。
    一个都不成立时退回最远的那个，并如实说明「都来不及」。
    """
    if not windows:
        return None, "没有可用的考试窗口"
    for idx, w in enumerate(windows):
        weeks = max(1, int(w.get("weeks_left") or 0))
        if spec.baseline_hours / weeks <= MAX_WEEKLY_HOURS:
            if idx == 0:
                return w, "最近一次考试，剩余时间够用"
            return w, (
                f"最近一次考试（{windows[0]['date'].isoformat()}）只剩 "
                f"{int(windows[0].get('weeks_left') or 0)} 周，来不及，按本次排期"
            )
    return windows[-1], "所有可选窗口都来不及，按最长的一个给参考排期"


def _window_json(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "日期": item["date"].isoformat(),
        "说明": item.get("label") or "",
        "依据": "真实公告" if item.get("basis") == "real_notice" else "历年规律（具体以当年公告为准）",
        "剩余周数": int(item.get("weeks_left") or 0),
        "剩余天数": int(item.get("days_left") or 0),
    }


# ----------------------------------------------------------------
# 二、逐维评分
# ----------------------------------------------------------------
def score_academic(
    gpa: float | None,
    peer: Mapping[str, Any] | None,
    fail_count: int | None,
) -> dict[str, Any]:
    """学业位次：同专业同年级真实 GPA 百分位 + 挂科扣分。"""
    peer = peer or {}
    pct = _num(peer.get("pct"))
    total = peer.get("total")
    rank = peer.get("rank")

    if pct is None or gpa is None:
        return {
            "key": DIM_ACADEMIC,
            "score": None,
            "level": LEVEL_UNKNOWN,
            "evidence": "同专业同年级的成绩样本不足，无法算位次",
            "source": "成绩表（真实成绩，样本不足 5 门时不参与）",
        }

    # 百分位 → 基础分：位次越靠前分越高
    if pct <= 0.10:
        base = 92.0
    elif pct <= 0.25:
        base = 82.0
    elif pct <= 0.40:
        base = 72.0
    elif pct <= 0.60:
        base = 62.0
    elif pct <= 0.80:
        base = 50.0
    else:
        base = 36.0

    penalty = 0.0
    fail = int(fail_count) if fail_count is not None else 0
    if fail > 0:
        penalty = min(_FAIL_PENALTY_CAP, _FAIL_PENALTY * fail)
    score = max(0.0, base - penalty)

    bits = [f"同专业同年级 {total} 人中排第 {rank}（前 {_round(pct * 100)}%）"]
    bits.append(f"均分 {_round(float(gpa))}")
    if fail_count is None:
        bits.append("挂科门数未采集")
    elif fail > 0:
        bits.append(f"挂科 {fail} 门，扣 {_round(penalty)} 分")
    else:
        bits.append("无挂科")
    return {
        "key": DIM_ACADEMIC,
        "score": _round(score),
        "level": level_of(score),
        "evidence": "；".join(bits),
        "source": "成绩表真实成绩（同专业同年级同届）",
    }


def score_english(cet4: Any, cet6: Any) -> dict[str, Any]:
    """英语门槛：四六级真实分数分档。缺考 = unknown，不当作未通过。"""
    four = _num(cet4)
    six = _num(cet6)
    if four is None and six is None:
        return {
            "key": DIM_ENGLISH,
            "score": None,
            "level": LEVEL_UNKNOWN,
            "evidence": "四六级成绩未采集",
            "source": "学生扩展信息（学生自填 / 教务导入）",
        }

    if six is not None and six >= 500:
        score, note = 92.0, f"六级 {int(six)} 分，已过 500 分线"
    elif six is not None and six >= 425:
        score, note = 82.0, f"六级 {int(six)} 分，过 425 分线"
    elif four is not None and four >= 500:
        score, note = 72.0, f"四级 {int(four)} 分（未过六级或六级 <425）"
    elif four is not None and four >= 425:
        score, note = 62.0, f"四级 {int(four)} 分，仅压线过 425"
    elif four is not None:
        score, note = 34.0, f"四级 {int(four)} 分，未达 425"
    else:
        score, note = 55.0, f"六级 {int(six)} 分，未达 425" if six is not None else "成绩缺失"

    return {
        "key": DIM_ENGLISH,
        "score": _round(score),
        "level": level_of(score),
        "evidence": note,
        "source": "学生扩展信息（学生自填 / 教务导入）",
    }


def score_eligibility(
    political_status: Any,
    gates: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """资格门槛：政治面貌折算 60% + 已判定硬门槛的通过率 40%。

    门槛本身逐项结果在 `门槛` 字段里另给，这里只把它折成一个可比较的分。
    全部门槛都缺数据 → unknown（不拿 100 分冒充"全都满足"）。
    """
    text = str(political_status or "").strip()
    pol = _POLITICAL_SCORE.get(text, 60.0 if text else None)

    judged = [g for g in gates if str(g.get("当前状态") or "") in {"pass", "fail"}]
    hard_fail = [g for g in judged if str(g.get("当前状态") or "") == "fail" and g.get("hard")]
    pass_rate: float | None = None
    if judged:
        passed = sum(1 for g in judged if str(g.get("当前状态") or "") == "pass")
        pass_rate = passed / len(judged)

    parts: list[float] = []
    weights: list[float] = []
    if pol is not None:
        parts.append(pol)
        weights.append(0.6)
    if pass_rate is not None:
        parts.append(pass_rate * 100.0)
        weights.append(0.4)

    if not parts:
        return {
            "key": DIM_ELIGIBILITY,
            "score": None,
            "level": LEVEL_UNKNOWN,
            "evidence": "政治面貌与报考门槛都未采集，无法判定资格",
            "source": "学生扩展信息 + 规则库门槛",
        }

    score = sum(p * w for p, w in zip(parts, weights)) / sum(weights)
    # 硬门槛不满足时资格维度直接压到 40 以下——这不是扣分，是"根本报不了"
    if hard_fail:
        score = min(score, 35.0)

    bits = [f"政治面貌「{text}」" if text else "政治面貌未填"]
    if judged:
        bits.append(f"已判定门槛 {sum(1 for g in judged if str(g.get('当前状态')) == 'pass')}/{len(judged)} 项通过")
    if hard_fail:
        bits.append("存在未满足的硬门槛：" + "、".join(str(g.get("项目") or "") for g in hard_fail))
    return {
        "key": DIM_ELIGIBILITY,
        "score": _round(score),
        "level": level_of(score),
        "evidence": "；".join(bits),
        "source": "学生扩展信息 + 规则库硬门槛",
    }


def score_capacity(weekly_hours: Any, weeks_left: int, baseline_hours: int) -> dict[str, Any]:
    """投入容量：每周可投入学时 × 剩余周数，对比该路径的经验基准学时。"""
    weekly = _num(weekly_hours)
    if weekly is None:
        return {
            "key": DIM_CAPACITY,
            "score": None,
            "level": LEVEL_UNKNOWN,
            "evidence": "每周可投入学时未采集，无法判断时间是否够用",
            "source": "学生扩展信息（学生自填）",
            "hours": None,
        }
    total = weekly * max(0, int(weeks_left))
    ratio = total / baseline_hours if baseline_hours else 0.0
    if ratio >= 1.3:
        score = 95.0
    elif ratio >= 1.0:
        score = 85.0
    elif ratio >= 0.8:
        score = 72.0
    elif ratio >= 0.6:
        score = 58.0
    elif ratio >= 0.4:
        score = 42.0
    else:
        score = 24.0
    return {
        "key": DIM_CAPACITY,
        "score": _round(score),
        "level": level_of(score),
        "evidence": (
            f"每周 {_round(weekly)} 小时 × 剩余 {int(weeks_left)} 周 = {_round(total)} 小时，"
            f"覆盖经验基准 {baseline_hours} 小时的 {_round(ratio * 100)}%"
        ),
        "source": "学生自填学时 + 经验基准学时（非统计数据）",
        "hours": _round(total),
        "ratio": _round(ratio, 3),
    }


# ----------------------------------------------------------------
# 三、综合评分与档位
# ----------------------------------------------------------------
def _composite(dims: Sequence[Mapping[str, Any]], weights: Mapping[str, float]) -> dict[str, Any]:
    """按可用维度归一化权重求综合分。可用维度 <3 → 不出档位。"""
    usable = [d for d in dims if d.get("score") is not None]
    if len(usable) < 3:
        return {
            "score": None,
            "tier": TIER_UNKNOWN,
            "tier_label": TIER_LABEL[TIER_UNKNOWN],
            "confidence": "low",
            "used": len(usable),
            "missing": [str(d["key"]) for d in dims if d.get("score") is None],
        }

    wsum = sum(float(weights.get(str(d["key"]), 0.0)) for d in usable)
    if wsum <= 0:
        wsum = float(len(usable))
        effective = {str(d["key"]): 1.0 for d in usable}
    else:
        effective = {str(d["key"]): float(weights.get(str(d["key"]), 0.0)) for d in usable}
    score = sum(float(d["score"]) * effective[str(d["key"])] for d in usable) / wsum

    tier = TIER_RISK
    for name, threshold in TIER_THRESHOLDS:
        if score >= threshold:
            tier = name
            break
    confidence = "high" if len(usable) == 4 else "medium"
    return {
        "score": _round(score),
        "tier": tier,
        "tier_label": TIER_LABEL[tier],
        "confidence": confidence,
        "used": len(usable),
        "missing": [],
        "effective_weights": effective,
    }


def _score_all(
    path: PathSpec,
    facts: Mapping[str, Any],
    peer: Mapping[str, Any] | None,
    gates: Sequence[Mapping[str, Any]],
    weeks_left: int,
) -> list[dict[str, Any]]:
    """四维打分（facts 已由调用方按需覆盖，本函数不再做第二次改写）。"""
    return [
        score_academic(_num(facts.get("gpa")), peer, facts.get("fail_count")),
        score_english(facts.get("cet4_score"), facts.get("cet6_score")),
        score_eligibility(facts.get("political_status"), gates),
        score_capacity(facts.get("weekly_hours"), weeks_left, path.baseline_hours),
    ]


# ----------------------------------------------------------------
# 四、提升杠杆（补齐某项后分数与档位怎么变）
# ----------------------------------------------------------------
def _lever(
    key: str,
    item: str,
    now: Any,
    target: Any,
    override: Mapping[str, Any],
    cost: str,
    reason: str,
    path: PathSpec,
    facts: Mapping[str, Any],
    peer: Mapping[str, Any] | None,
    gate_specs: Sequence[Mapping[str, Any]],
    weeks_left: int,
    base: Mapping[str, Any],
) -> dict[str, Any] | None:
    """算一个可改变项的增量：分变化 + 是否跨档。

    关键：override 改的是**事实**，所以要按新事实重新判一遍硬门槛——
    否则"清掉挂科"只提升学业分、却不让「无挂科」那条门槛从 fail 变 pass，
    杠杆的收益会被低估。
    """
    merged = dict(facts)
    merged.update(override)
    gates_after = list(check_hard_gates(gate_specs, merged)) if gate_specs else []
    dims_after = _score_all(path, merged, peer, gates_after, weeks_left)
    comp = _composite(dims_after, path.weights)
    if comp["score"] is None or base.get("score") is None:
        return None
    delta = float(comp["score"]) - float(base["score"])
    if delta < 0.5:
        return None

    dim_delta: dict[str, float] = {}
    before_map = {str(d["key"]): d.get("score") for d in _score_all(path, facts, peer, 
        list(check_hard_gates(gate_specs, dict(facts))) if gate_specs else [], weeks_left)}
    for d in dims_after:
        k = str(d["key"])
        before, after = before_map.get(k), d.get("score")
        if before is not None and after is not None and abs(float(after) - float(before)) > 0.01:
            dim_delta[DIM_NAMES.get(k, k)] = _round(float(after) - float(before))
    return {
        "key": key,
        "项目": item,
        "当前": now,
        "目标": target,
        "综合分变化": _round(delta),
        "维度变化": dim_delta,
        "跨档": comp["tier"] != base["tier"],
        "当前档位": base["tier"],
        "达成后档位": comp["tier"],
        "代价": cost,
        "依据": reason,
    }


def build_leverage(
    path: PathSpec,
    facts: Mapping[str, Any],
    peer: Mapping[str, Any] | None,
    gate_specs: Sequence[Mapping[str, Any]],
    weeks_left: int,
    base: Mapping[str, Any],
    baseline_hours: int | None = None,
) -> list[dict[str, Any]]:
    """生成提升杠杆清单，按「综合分变化」降序。每一项都能由学生自己动手改变。

    gate_specs 是**门槛定义**（不是判定结果）：override 事实后要重新判一遍，
    否则"清掉挂科"不会让「无挂科」那条从 fail 变 pass，收益会被低估。
    """
    bl = baseline_hours or path.baseline_hours
    out: list[dict[str, Any]] = []

    four = _num(facts.get("cet4_score"))
    six = _num(facts.get("cet6_score"))
    # 1) 四级：未过 425 提到 425
    if four is None or four < 425:
        item = _lever(
            "cet4", "大学英语四级 425",
            f"{int(four)} 分" if four is not None else "未考",
            "425 分",
            {"cet4_score": 425},
            "1 个学期（每学期一次考试机会）",
            "部分公务员与事业单位岗位、考研复试都设 425 线",
            path, facts, peer, gate_specs, weeks_left, base,
        )
        if item:
            out.append(item)

    # 2) 六级：已过四级但六级未过 425
    if six is None or six < 425:
        from_score = six if six is not None else four
        if from_score is not None and from_score >= 425:
            item = _lever(
                "cet6", "大学英语六级 425",
                f"六级 {int(six)} 分" if six is not None else "未考六级",
                "425 分",
                {"cet6_score": 425},
                "1 个学期",
                "六级过线在考研复试与选调生选拔中是明确加分项",
                path, facts, peer, gate_specs, weeks_left, base,
            )
            if item:
                out.append(item)

    # 3) 挂科：清掉全部挂科（重修/补考通过）
    fail = facts.get("fail_count")
    if isinstance(fail, int) and fail > 0:
        item = _lever(
            "fail", "清掉挂科记录",
            f"挂科 {fail} 门",
            "0 门",
            {"fail_count": 0},
            "重修或补考，随学期走",
            "公务员政审与考研复试都会看是否挂科；部分岗位要求无挂科",
            path, facts, peer, gate_specs, weeks_left, base,
        )
        if item:
            out.append(item)

    # 4) 政治面貌：非党员 → 党员（只在低年级值得提，毕业年级来不及）
    status = str(facts.get("political_status") or "")
    if status and status not in {"中共党员", "中共预备党员"} and str(facts.get("grade") or "") in {"大一", "大二", "大三"}:
        item = _lever(
            "party", "入党（发展为中共党员）",
            status,
            "中共党员",
            {"political_status": "中共党员"},
            "1.5~2 年（递交申请到转正）",
            "限党员的岗位竞争比通常更低，但只有低年级来得及走完流程",
            path, facts, peer, gate_specs, weeks_left, base,
        )
        if item:
            out.append(item)

    # 5) 投入：每周学时提高到「刚好覆盖基准」所需的量
    #    上限 MAX_WEEKLY_HOURS：需要超过这个数的窗口根本来不及，
    #    硬说「每周学 175 小时」是假建议，那种情况交给「换考试窗口」处理。
    weekly = _num(facts.get("weekly_hours"))
    if weekly is not None and weeks_left > 0:
        need_weekly = bl / weeks_left
        if weekly < need_weekly and need_weekly <= MAX_WEEKLY_HOURS:
            item = _lever(
                "hours", "提高每周备考学时",
                f"每周 {_round(weekly)} 小时",
                f"每周 {_round(need_weekly)} 小时",
                {"weekly_hours": _round(need_weekly, 1)},
                f"持续 {int(weeks_left)} 周",
                f"按当前进度到考试只能覆盖基准的 "
                f"{_round((weekly * weeks_left / bl) * 100)}%，需要提到每周 {_round(need_weekly)} 小时才能覆盖 100%",
                path, facts, peer, gate_specs, weeks_left, base,
            )
            if item:
                out.append(item)

    out.sort(key=lambda x: -float(x["综合分变化"]))
    return out


# ----------------------------------------------------------------
# 五、确定性建议（每条都挂着一个真实差值，模型不得增删）
# ----------------------------------------------------------------
def build_advice(
    path: PathSpec,
    facts: Mapping[str, Any],
    dims: Sequence[Mapping[str, Any]],
    gates: Sequence[Mapping[str, Any]],
    windows: Sequence[Mapping[str, Any]],
    capacity_ratio: float | None,
    today: date,
) -> list[dict[str, Any]]:
    """按「先硬门槛、再时间、再短板、最后补数据」的优先级出建议。"""
    out: list[dict[str, Any]] = []

    # 1) 硬门槛未满足 —— 最高优先级，其它都是次要
    for g in gates:
        if str(g.get("当前状态")) == "fail" and g.get("hard"):
            out.append({
                "优先级": 1,
                "类型": "硬门槛",
                "动作": f"先解决「{g.get('项目')}」：要求 {g.get('要求')}，当前 {g.get('当前值')}",
                "依据": "硬门槛不满足时，笔试成绩再高也无法进入后续环节",
            })

    # 2) 时间不足 —— 决定「要不要换目标窗口」
    first = windows[0] if windows else None
    weekly = _num(facts.get("weekly_hours"))
    if capacity_ratio is not None and capacity_ratio < 0.6 and first:
        weeks_first = max(1, int(first["weeks_left"]))
        need_weekly = path.baseline_hours / weeks_first
        nxt = windows[1] if len(windows) > 1 else None

        if need_weekly > MAX_WEEKLY_HOURS:
            # 这个窗口在数学上就来不及——不是"努力一点"能解决的
            action = (
                f"「{first['date'].isoformat()}」只剩 {weeks_first} 周，"
                f"要达到基准需每周 {_round(need_weekly)} 小时（超过现实上限 {int(MAX_WEEKLY_HOURS)} 小时），这个窗口来不及"
            )
            if nxt:
                nxt_weeks = max(1, int(nxt["weeks_left"]))
                nxt_need = path.baseline_hours / nxt_weeks
                nxt_cover = (
                    _round(min(1.0, (weekly or 0) * nxt_weeks / path.baseline_hours) * 100)
                    if weekly is not None else None
                )
                extra = (
                    f"；改到「{nxt['date'].isoformat()}」（{nxt_weeks} 周）按当前每周 {_round(weekly)} 小时可覆盖 {nxt_cover}%，"
                    f"需提到每周 {_round(min(nxt_need, MAX_WEEKLY_HOURS))} 小时"
                    if weekly is not None else
                    f"；改到「{nxt['date'].isoformat()}」（{nxt_weeks} 周）需每周 {_round(min(nxt_need, MAX_WEEKLY_HOURS))} 小时"
                )
                action += extra
            out.append({
                "优先级": 1,
                "类型": "时间窗口",
                "动作": action,
                "依据": path.baseline_note + "；剩余周数按历年考试窗口倒推，具体日期以当年公告为准",
            })
        else:
            out.append({
                "优先级": 2,
                "类型": "时间投入",
                "动作": (
                    f"到「{first['date'].isoformat()}」还差 "
                    f"{max(0, path.baseline_hours - int((weekly or 0) * weeks_first))} 小时，"
                    f"需要把每周学时提到 {_round(need_weekly)} 小时（当前 {_round(weekly) if weekly is not None else '未填'}）"
                ),
                "依据": path.baseline_note,
            })

    # 3) 维度短板
    for d in dims:
        if d.get("level") in {LEVEL_WEAK, LEVEL_POOR} and d.get("score") is not None:
            action = {
                DIM_ACADEMIC: "先保绩点、清挂科：面试与政审都会看学业记录",
                DIM_ENGLISH: "把四级/六级刷到 425 以上，这是最便宜的一次性加分",
                DIM_ELIGIBILITY: "资格维度是短板，优先看政治面貌与目标岗位的具体要求",
                DIM_CAPACITY: "把每周可投入学时写实并固定下来，时间不够时先砍目标范围而不是拖进度",
            }.get(str(d["key"]), "补强该维度")
            out.append({
                "优先级": 3,
                "类型": DIM_NAMES.get(str(d["key"]), str(d["key"])),
                "动作": action,
                "依据": str(d.get("evidence") or ""),
            })

    # 4) 数据缺失 —— 补齐才能给准话
    missing = [DIM_NAMES.get(str(d["key"]), str(d["key"])) for d in dims if d.get("score") is None]
    if missing:
        out.append({
            "优先级": 4,
            "类型": "数据补齐",
            "动作": "补齐「" + "、".join(missing) + "」相关数据，否则这块只能按缺数据处理，不给结论",
            "依据": "缺失不冒充：没有数据时系统不猜达标与否",
        })

    out.sort(key=lambda x: x["优先级"])
    return out


# ----------------------------------------------------------------
# 六、主入口
# ----------------------------------------------------------------
def forecast(
    facts: Mapping[str, Any],
    *,
    goal: str,
    peer: Mapping[str, Any] | None = None,
    gates: Sequence[Mapping[str, Any]] = (),
    notices: Mapping[str, Any] | None = None,
    guokao: Mapping[str, Any] | None = None,
    template: Mapping[str, Any] | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """组装一份报考分析。

    参数全部由调用方（context 层）查库后传入，本函数不连库、不调模型：
      facts     学生真实事实（gpa / fail_count / cet4 / cet6 / political_status /
                weekly_hours / grade / major / college）
      peer      同专业同年级 GPA 基准（total / rank / pct / median / max）
      gates     已判定的硬门槛（career_rules.check_hard_gates 的输出）
      notices   真实公告机会（列表 + 覆盖率统计）
      guokao    国考职位匹配摘要（仅考公路径用：按学生学历/政治面貌/专业/城市
                对官方《招考简章》职位表 COUNT/SUM 后的结果；引擎不自己算这些数）
      template  规则模板（取 phases 用于阶段切分）
    """
    base_day = today or date.today()
    spec = PATHS.get(str(goal or "").strip())
    if spec is None:
        return {
            "engine": CAREER_FORECAST_VERSION,
            "goal": goal,
            "available": False,
            "reason": f"「{goal}」不在报考分析范围内（支持：{'、'.join(FORECAST_GOALS)}）",
        }

    notices = notices or {}
    real_dates = [n.get("考试日期") for n in (notices.get("items") or []) if n.get("考试日期")]
    windows = plan_windows(spec.goal, base_day, real_dates)
    primary, primary_reason = _pick_primary(spec, windows, _num(facts.get("weekly_hours")))
    first = primary
    weeks_left = int(first["weeks_left"]) if first else 0

    dims = _score_all(spec, facts, peer, gates, weeks_left)
    composite = _composite(dims, spec.weights)

    capacity = next((d for d in dims if d["key"] == DIM_CAPACITY), {})
    ratio = capacity.get("ratio")

    gate_specs = list((template or {}).get("hard_gates") or [])
    leverage = build_leverage(spec, facts, peer, gate_specs, weeks_left, composite)
    advice = build_advice(spec, facts, dims, gates, windows, ratio, base_day)

    # 阶段切分：复用规则模板的 phases 与剩余周数（不重写排期逻辑，只做占比分配）
    phases = (template or {}).get("phases") or []
    phase_plan: list[dict[str, Any]] = []
    if phases and weeks_left > 0:
        total_w = sum(float(p.get("占比") or 0) for p in phases) or float(len(phases))
        cursor = 0
        for p in phases:
            w = max(1, round(weeks_left * float(p.get("占比") or 1) / total_w)) if len(phases) <= weeks_left else 0
            if w <= 0:
                continue
            start = base_day + timedelta(days=cursor * 7)
            end = start + timedelta(days=w * 7 - 1)
            phase_plan.append({
                "阶段": str(p.get("阶段") or ""),
                "周数": w,
                "时间范围": f"{start.isoformat()} ~ {end.isoformat()}",
                "核心任务": str(p.get("核心任务") or ""),
            })
            cursor += w

    sources = [
        {
            "维度": "学生指标",
            "来源": "成绩表（真实成绩）、学生扩展信息（四六级/政治面貌/每周学时）",
            "性质": "真实数据",
        },
        {
            "维度": "同侪位次",
            "来源": f"同专业同年级共 {peer.get('total')} 人纳入比较" if peer else "样本不足",
            "性质": "真实数据（由真实成绩实算）",
        },
        {
            "维度": "考试机会",
            "来源": f"招考公告 {notices.get('total', 0)} 条（{spec.exam_type}）",
            "性质": "真实数据（官网抓取）",
        },
        {
            "维度": "路径基准学时",
            "来源": spec.baseline_note,
            "性质": "经验基线（公开备考经验，不是本平台统计）",
        },
    ]
    if spec.goal == GOAL_KAOGONG and (guokao or {}).get("available"):
        sources.append({
            "维度": "可报职位",
            "来源": (f"国家公务员局《招考简章》职位表 {guokao.get('year')} 年度，"
                     f"按学历/政治面貌/专业/城市初筛"),
            "性质": "真实数据（官方职位表逐条，引擎按条件聚合）",
        })

    caveats: list[str] = [
        "本页不给「上岸概率」。平台没有历年录取率样本，任何百分比概率都是编的；"
        "这里给的是档位与逐维证据，档位是规则映射，不是统计模型输出。",
        f"「{spec.baseline_hours} 小时」是经验基准，不是统计数据；它的作用是判断时间够不够，不是预测分数。",
    ]
    stats = notices.get("stats") or {}
    if stats.get("total"):
        caveats.append(
            f"招考公告逐项要求抽取率有限（{stats['total']} 条公告中，明确写学历 {stats.get('with_education', 0)} 条、"
            f"专业 {stats.get('with_major', 0)} 条、政治面貌 {stats.get('with_political', 0)} 条）——"
            "重庆事业单位的岗位分项要求多写在附件岗位表里，正文抓不到。"
            "所以资格判定以规则库通用条件为准，具体岗位务必点原文链接核对。"
        )
        if stats.get("open_count") == 0:
            caveats.append(
                f"当前题库里这 {stats['total']} 条公告都已过报名截止"
                + (f"（最近一次发布 {stats['latest_published']}）" if stats.get("latest_published") else "")
                + "，它们是「往年真实要求」的参照，不是现在能报的岗位。"
            )
    if stats.get("scope_note"):
        caveats.append(str(stats["scope_note"]))

    if spec.goal == GOAL_KAOGONG and (guokao or {}).get("available"):
        note = (
            f"国考职位匹配为「学历/政治面貌/专业/城市关键词初筛」口径："
            f"匹配 {guokao.get('matched_positions')} 个职位、计划招 {guokao.get('matched_headcount')} 人，"
            "属初筛合计数，最终报考资格以每个职位的官方详情为准。"
        )
        if not str(facts.get("political_status") or "").strip():
            note += "政治面貌未采集，此处按保守口径只统计「不限/未标注」政治面貌的岗位。"
        caveats.append(note)

    return {
        "engine": CAREER_FORECAST_VERSION,
        "goal": spec.goal,
        "goal_label": spec.label,
        "available": True,
        "as_of": base_day.isoformat(),
        "student": {
            "name": facts.get("name"),
            "major": facts.get("major"),
            "college": facts.get("college"),
            "grade": facts.get("grade"),
        },
        "composite": {
            "score": composite["score"],
            "tier": composite["tier"],
            "tier_label": composite["tier_label"],
            "confidence": composite["confidence"],
            "dims_used": composite["used"],
            "score_note": "规则分（0-100），由四维加权得出，不是录取概率",
        },
        "dimensions": [
            {
                "key": d["key"],
                "名称": DIM_NAMES.get(str(d["key"]), str(d["key"])),
                "权重": spec.weights.get(str(d["key"])),
                "score": d.get("score"),
                "level": d.get("level"),
                "level_text": LEVEL_TEXT.get(str(d.get("level")), ""),
                "evidence": d.get("evidence"),
                "source": d.get("source"),
            }
            for d in dims
        ],
        "gates": list(gates),
        "timeline": {
            "window": _window_json(first) if first else None,
            "window_reason": primary_reason,
            "alternatives": [_window_json(w) for w in windows if w is not first],
            "phases": phase_plan,
            "baseline_hours": spec.baseline_hours,
            "baseline_note": spec.baseline_note,
            "weeks_left": weeks_left,
        },
        "leverage": leverage,
        "advice": advice,
        "opportunities": {
            "exam_type": spec.exam_type,
            "total": notices.get("total", 0),
            "headcount": notices.get("headcount"),
            "open_count": stats.get("open_count"),
            "latest_published": stats.get("latest_published"),
            "items": list(notices.get("items") or [])[:10],
            "stats": stats,
            # 考公路线专属：官方《招考简章》职位表按学生条件初筛后的可报职位。
            # guokao 已是 context 层用 SQL COUNT/SUM 算好的确定性结果，引擎不再改动这些数字。
            "guokao_positions": (guokao if spec.goal == GOAL_KAOGONG else None),
        },
        "sources": sources,
        "caveats": caveats,
    }


__all__ = [
    "CAREER_FORECAST_VERSION",
    "FORECAST_GOALS",
    "GOAL_KAOGONG",
    "GOAL_KAOBIAN",
    "GOAL_KAOYAN",
    "PATHS",
    "LEVEL_TEXT",
    "TIER_LABEL",
    "level_of",
    "parse_date",
    "plan_windows",
    "score_academic",
    "score_english",
    "score_eligibility",
    "score_capacity",
    "build_leverage",
    "build_advice",
    "forecast",
]
