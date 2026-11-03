# engine/assessment.py
# 职责：软技能测评确定性打分——维度得分 / 复合能力画像，全部由规则计算，不调大模型
# 依赖：仅标准库；题目与每道题的选项分值以数据库「测评题目」表为唯一真相源
# 说明：本模块只做纯计算（score_answers / composite_abilities），不连库、不决定题面与分值

from __future__ import annotations

from typing import Any, Mapping, Sequence

ASSESSMENT_ENGINE_VERSION = "assessment-v1"

# 五个复合能力（对齐岗位四维匹配的软技能维度，为后续多维匹配融合铺路）
ABILITY_PROFESSIONAL = "professional_skills"
ABILITY_LEARNING = "learning_ability"
ABILITY_INNOVATION = "innovation_ability"
ABILITY_STRESS = "stress_resistance"
ABILITY_COMMUNICATION = "communication_ability"

ABILITY_KEYS: tuple[str, ...] = (
    ABILITY_PROFESSIONAL,
    ABILITY_LEARNING,
    ABILITY_INNOVATION,
    ABILITY_STRESS,
    ABILITY_COMMUNICATION,
)

# 细粒度量表维度 → 复合能力（源自测评量表设计）
DIMENSION_TO_ABILITY: dict[str, str] = {
    "逻辑思维": ABILITY_PROFESSIONAL,
    "执行力": ABILITY_PROFESSIONAL,
    "成就导向": ABILITY_PROFESSIONAL,
    "项目经验": ABILITY_PROFESSIONAL,
    "问题解决": ABILITY_PROFESSIONAL,
    "协作工具": ABILITY_PROFESSIONAL,
    "现实型": ABILITY_PROFESSIONAL,
    "学习能力": ABILITY_LEARNING,
    "研究型": ABILITY_LEARNING,
    "工作环境": ABILITY_LEARNING,
    "发展空间": ABILITY_LEARNING,
    "技术热情": ABILITY_LEARNING,
    "技术视野": ABILITY_LEARNING,
    "创新能力": ABILITY_INNOVATION,
    "开放性": ABILITY_INNOVATION,
    "艺术型": ABILITY_INNOVATION,
    "自主性": ABILITY_INNOVATION,
    "抗压能力": ABILITY_STRESS,
    "情绪稳定性": ABILITY_STRESS,
    "尽责性": ABILITY_STRESS,
    "常规型": ABILITY_STRESS,
    "薪酬安全": ABILITY_STRESS,
    "沟通表达": ABILITY_COMMUNICATION,
    "团队协作": ABILITY_COMMUNICATION,
    "宜人性": ABILITY_COMMUNICATION,
    "外向性": ABILITY_COMMUNICATION,
    "社会型": ABILITY_COMMUNICATION,
    "企业型": ABILITY_COMMUNICATION,
    "社会贡献": ABILITY_COMMUNICATION,
    "人际关系": ABILITY_COMMUNICATION,
    "声望": ABILITY_COMMUNICATION,
    "智力激发": ABILITY_LEARNING,
}

# 量表维度权重：代表该维度对复合能力的贡献强度（量表设计定值，非模型产出）
DIMENSION_WEIGHTS: dict[str, float] = {
    "逻辑思维": 1.2, "学习能力": 1.2, "创新能力": 1.0, "抗压能力": 1.0,
    "沟通表达": 1.0, "团队协作": 1.0, "执行力": 0.8, "外向性": 0.6,
    "尽责性": 0.8, "开放性": 0.8, "情绪稳定性": 1.0, "宜人性": 0.6,
    "研究型": 0.8, "艺术型": 0.6, "社会型": 0.6, "企业型": 0.6,
    "常规型": 0.5, "成就导向": 0.7, "自主性": 0.5, "社会贡献": 0.3,
    "工作环境": 0.3, "发展空间": 0.7, "薪酬安全": 0.3, "人际关系": 0.5,
    "技术热情": 1.0, "项目经验": 1.0, "问题解决": 1.2, "技术视野": 0.8,
    "协作工具": 0.8,
    "现实型": 0.8, "智力激发": 0.9, "声望": 0.5,
}

# 复合能力无人映射到时的兜底分（量表设计约定：缺数据默认中性 50）
ABILITY_FALLBACK = 50.0

# 复合能力分封顶：权重放大（如 1.2）后可能超过 100，显示时封回 [0,100]
_ABILITY_CAP = 100.0


def _as_float(value: Any) -> float:
    """安全转 float；None / 非数字回 0.0（缺失不冒充有值）。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def scoring_of(question: Mapping[str, Any]) -> Mapping[str, float]:
    """取出某道题的「选项 → 分值」映射；缺失时回空映射（该题得 0，不算满分）。"""
    raw = question.get("scoring") or question.get("选项分值") or {}
    if not isinstance(raw, Mapping):
        return {}
    out: dict[str, float] = {}
    for option, score in raw.items():
        out[str(option)] = _as_float(score)
    return out


def score_answers(questions: Sequence[Mapping[str, Any]],
                  answers: Mapping[int, str]) -> dict[str, Any]:
    """按题目表的分值确定性打分。

    返回结构：
      {
        "total_score": 总原始分,
        "total_max": 总满分,
        "answered": 已计分题数,
        "dimensions": {维度: {"score": raw, "max": max, "count": n, "pct": 0-100}},
        "dimension_scores": {维度: 加权分(0-100 封顶)},
        "abilities": {复合能力: 0-100},
      }

    纯函数：同一输入必得同一输出，且不引用任何模型结果。
    """
    total_score = 0.0
    total_max = 0.0
    answered = 0

    dims: dict[str, dict[str, float]] = {}
    for q in questions:
        qid = int(q.get("id") or q.get("编号") or 0)
        if qid <= 0:
            continue
        answer = answers.get(qid)
        if answer is None:
            # 未作答的题：不参与计分，也不计入满分
            continue
        scored = scoring_of(q)
        if not scored:
            continue
        score = _as_float(scored.get(str(answer)))
        full = max(scored.values()) if scored else 0.0
        dimension = str(q.get("dimension") or q.get("维度") or "").strip() or "general"

        total_score += score
        total_max += full
        answered += 1

        dims.setdefault(dimension, {"score": 0.0, "max": 0.0, "count": 0.0})
        dims[dimension]["score"] += score
        dims[dimension]["max"] += full
        dims[dimension]["count"] += 1

    dimension_pct: dict[str, float] = {}
    for dim, agg in dims.items():
        pct = (agg["score"] / agg["max"] * 100.0) if agg["max"] > 0 else 0.0
        dimension_pct[dim] = round(pct, 1)

    dimension_scores = weighted_dimension_scores(dimension_pct)

    return {
        "total_score": round(total_score, 1),
        "total_max": round(total_max, 1),
        "answered": answered,
        "dimensions": {
            dim: {
                "score": round(agg["score"], 1),
                "max": round(agg["max"], 1),
                "count": int(agg["count"]),
                "pct": dimension_pct[dim],
            }
            for dim, agg in dims.items()
        },
        "dimension_scores": dimension_scores,
        "abilities": composite_abilities(dimension_scores),
    }


def weighted_dimension_scores(dimension_pct: Mapping[str, float]) -> dict[str, float]:
    """把细粒度维度百分比（0-100）按维度权重加权，得到维度得分（0-100 封顶）。

    单独暴露出来，供「历史结果」从已存的 pct 还原出与提交时一致的 dimension_scores，
    避免同一份结果「刚提交」和「刷新后」数字不一致。
    """
    out: dict[str, float] = {}
    for dim, pct in dimension_pct.items():
        weighted = _as_float(pct) * DIMENSION_WEIGHTS.get(dim, 0.8)
        out[dim] = round(min(weighted, _ABILITY_CAP), 1)
    return out


def composite_abilities(dimension_scores: Mapping[str, float]) -> dict[str, float]:
    """把细粒度维度加权分聚合为五个复合能力分（0-100 封顶）。"""
    sums: dict[str, float] = {k: 0.0 for k in ABILITY_KEYS}
    counts: dict[str, int] = {k: 0 for k in ABILITY_KEYS}

    for dim, score in dimension_scores.items():
        target = DIMENSION_TO_ABILITY.get(dim)
        if target and target in sums:
            sums[target] += _as_float(score)
            counts[target] += 1

    out: dict[str, float] = {}
    for key in ABILITY_KEYS:
        if counts[key] > 0:
            out[key] = round(min(sums[key] / counts[key], _ABILITY_CAP), 1)
        else:
            out[key] = ABILITY_FALLBACK
    return out