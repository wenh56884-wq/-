# engine/career_guide.py
# 职责：按年级与目标生成确定性生涯规划（大一先定方向，大二/大三给出路径）
# 依赖：仅标准库（datetime / typing）；不连库、不调模型
# 说明：文案与阶段全部由本模块常量决定，前端与模型不得自行改写数值或日期

from __future__ import annotations

from datetime import date
from typing import Any

GUIDE_ENGINE_VERSION = "career-guide-v1"

# 学生可选的四个方向（与前端选项顺序一致）
INTENTS: tuple[str, ...] = ("考公", "考研", "考编", "就业")

INTENT_OPTIONS: tuple[dict[str, str], ...] = (
    {"value": "考公", "label": "考公", "desc": "公务员 / 选调生"},
    {"value": "考研", "label": "考研", "desc": "硕士研究生"},
    {"value": "考编", "label": "考编", "desc": "事业单位 / 教师编"},
    {"value": "就业", "label": "就业", "desc": "企业 / 实习 / 校招"},
)

# 年级 → 机器可读阶段
GRADE_STAGE: dict[str, str] = {
    "大一": "freshman",
    "大二": "sophomore",
    "大三": "junior",
    "大四": "senior",
    "已毕业": "graduated",
}

_STAGE_INDEX = {"sophomore": 1, "junior": 2, "senior": 3, "graduated": 3}

# 四个方向的四年主线（每一步都是可执行动作，不含模型生成内容）
_PLANS: dict[str, list[dict[str, Any]]] = {
    "考公": [
        {"阶段": "大一 · 打基础", "目标": "确认公共部门方向，稳住学业基本盘",
         "行动": ["保持课程成绩与出勤稳定", "了解国考、省考、选调生的报考条件",
                  "开始积累时政与申论素材"]},
        {"阶段": "大二 · 建能力", "目标": "形成可持续的备考节奏",
         "行动": ["系统学习行测各模块", "参加公文写作、辩论或学生工作",
                  "关注暑期实习与基层实践"]},
        {"阶段": "大三 · 强实战", "目标": "用真题和模考检验水平",
         "行动": ["进入真题训练与限时模考", "补齐薄弱模块",
                  "关注报名时间与岗位表"]},
        {"阶段": "大四 · 冲上岸", "目标": "完成报名、笔试与面试",
         "行动": ["按公告完成报名与资格审查", "保持模考节奏",
                  "准备面试与政审材料"]},
    ],
    "考研": [
        {"阶段": "大一 · 打基础", "目标": "稳住绩点，打牢英语与数学基础",
         "行动": ["保持课程成绩，避免挂科", "坚持英语词汇与阅读",
                  "了解本专业考研科目"]},
        {"阶段": "大二 · 定方向", "目标": "确定报考专业与院校范围",
         "行动": ["对比目标院校的考试科目与复试要求", "参与科研或学科竞赛",
                  "补齐数学与专业课短板"]},
        {"阶段": "大三 · 进复习", "目标": "完成一轮系统复习",
         "行动": ["确定目标院校与专业", "按科目制定复习计划",
                  "开始真题与模拟训练"]},
        {"阶段": "大四 · 冲刺复试", "目标": "完成初试与复试准备",
         "行动": ["按考试时间完成报名与确认", "保持真题与模考节奏",
                  "准备复试材料与面试"]},
    ],
    "考编": [
        {"阶段": "大一 · 打基础", "目标": "了解事业单位与教师编的报考路径",
         "行动": ["保持课程成绩与出勤稳定", "了解事业单位、教师招聘的考试科目",
                  "积累公共基础知识素材"]},
        {"阶段": "大二 · 建能力", "目标": "形成公基与写作的复习节奏",
         "行动": ["系统学习公共基础知识", "练习公文写作与教育综合知识",
                  "关注实习与志愿服务机会"]},
        {"阶段": "大三 · 强实战", "目标": "用真题与模考检验水平",
         "行动": ["进入真题训练与限时模考", "补齐薄弱模块",
                  "关注各地招考公告与岗位表"]},
        {"阶段": "大四 · 冲上岸", "目标": "完成报名、笔试与面试",
         "行动": ["按公告完成报名与资格审查", "保持模考节奏",
                  "准备面试与政审材料"]},
    ],
    "就业": [
        {"阶段": "大一 · 探方向", "目标": "通过课程与社团探索职业兴趣",
         "行动": ["保持课程成绩与出勤稳定", "参加社团、竞赛或学生工作",
                  "了解本专业常见就业方向"]},
        {"阶段": "大二 · 练技能", "目标": "形成一项可展示的专业能力",
         "行动": ["掌握专业核心工具与技能", "完成至少一个课程项目",
                  "考取与方向相关的证书"]},
        {"阶段": "大三 · 找实习", "目标": "用实习验证方向并积累项目",
         "行动": ["投递暑期实习与日常实习", "打磨简历与作品集",
                  "关注校招提前批"]},
        {"阶段": "大四 · 拿 offer", "目标": "完成秋招、春招与入职准备",
         "行动": ["按节奏投递校招岗位", "准备笔试与面试", "比较 offer 并完成签约"]},
    ],
}

# 没有明确目标时的探索型规划（大二/大三不强制先选方向）
_EXPLORE_PLANS: dict[str, list[dict[str, Any]]] = {
    "sophomore": [
        {"阶段": "大二 · 验证方向", "目标": "用课程、社团和实习验证兴趣",
         "行动": ["保持成绩稳定", "尝试一个与专业相关的项目或社团",
                  "记录自己对哪些工作更有持续兴趣"]},
        {"阶段": "大三 · 积累作品", "目标": "把兴趣变成可展示的能力",
         "行动": ["完成一个完整项目或实习", "考取一项方向相关证书",
                  "开始关注目标岗位的招聘要求"]},
        {"阶段": "大四 · 落地目标", "目标": "在就业与升学之间做出选择并执行",
         "行动": ["确定主攻方向", "按方向准备简历或备考", "利用校招与公告窗口"]},
    ],
    "junior": [
        {"阶段": "大三 · 快速试错", "目标": "用实习或项目确认毕业去向",
         "行动": ["优先争取一段对口实习", "向学长学姐了解真实工作内容",
                  "对比就业、考公、考研、考编的时间成本"]},
        {"阶段": "大四 · 落地目标", "目标": "把选择变成结果",
         "行动": ["确定主攻方向并制定时间表", "按方向准备简历或备考",
                  "利用校招与公告窗口"]},
    ],
    "senior": [
        {"阶段": "大四 · 毕业冲刺", "目标": "在毕业前完成去向落地",
         "行动": ["集中投递或备考", "补齐简历与面试短板",
                  "关注毕业手续与签约节点"]},
    ],
    "graduated": [
        {"阶段": "毕业后 · 过渡", "目标": "在过渡期内保持节奏并完成落地",
         "行动": ["继续投递或备考", "复盘每次面试与考试",
                  "按公告与招聘节奏调整计划"]},
    ],
    "unknown": [
        {"阶段": "当前阶段 · 补齐信息", "目标": "先确认年级与目标，再细化规划",
         "行动": ["在个人信息中补齐入学年份", "选定考公、考研、考编或就业方向",
                  "按选定方向执行下一步"]},
    ],
}


def grade_label(enroll_year: Any, today: date | None = None) -> str | None:
    """由入学年份推算年级标签（大一大二大三大四/已毕业）。

    与 agents.career.context 的历史实现保持同一口径：按学年计算，9 月进入新学年；
    这是确定性推算，不含随机或模型参与。
    """
    if not enroll_year:
        return None
    try:
        year = int(enroll_year)
    except (TypeError, ValueError):
        return None
    base = today or date.today()
    academic_year = base.year if base.month >= 9 else base.year - 1
    grade_no = academic_year - year + 1
    if grade_no <= 0:
        return "未入学"
    return {1: "大一", 2: "大二", 3: "大三", 4: "大四"}.get(grade_no, "已毕业")


def stage_of(grade: str | None) -> str:
    """年级标签 → 机器阶段；未知年级返回 unknown。"""
    return GRADE_STAGE.get(str(grade or "").strip(), "unknown")


def normalize_intent(intent: Any) -> str | None:
    """只接受四个合法目标；其他值一律视为未选择。"""
    text = str(intent or "").strip()
    return text if text in INTENTS else None


def resolve_direction(direction: Any, intent: str | None) -> dict[str, str]:
    """方向优先级：画像方向 > 目标推导 > 待探索。"""
    name = str(direction or "").strip()
    if name:
        return {"name": name, "source": "profile.interest"}
    if intent in ("考公", "考编"):
        return {"name": "公共管理与综合事务", "source": "intent"}
    if intent == "考研":
        return {"name": "本专业深造", "source": "intent"}
    if intent == "就业":
        return {"name": "专业对口岗位", "source": "intent"}
    return {"name": "待探索", "source": "none"}


def _steps_for(stage: str, intent: str | None) -> list[dict[str, Any]]:
    """按阶段与目标取步骤；大一未选目标时不生成规划。"""
    if stage == "freshman":
        return [dict(step) for step in _PLANS.get(intent or "", [])]
    if stage in _STAGE_INDEX and intent in _PLANS:
        steps = _PLANS[intent][_STAGE_INDEX[stage]:]
        if stage == "graduated" and steps:
            steps = [dict(steps[0], **{"阶段": "毕业后 · 落地"})]
        return [dict(step) for step in steps]
    return [dict(step) for step in _EXPLORE_PLANS.get(stage, _EXPLORE_PLANS["unknown"])]


def _headline(stage: str, grade: str | None, intent: str | None) -> str:
    """一句确定性的规划标题（不含模型生成内容）。"""
    label = str(grade or "当前阶段")
    if stage == "freshman" and not intent:
        return "大一先定方向：考公、考研、考编还是就业？"
    if stage == "freshman":
        return f"大一 · {intent}方向：先打基础，再拉长线"
    if stage == "sophomore":
        return f"大二 · {intent or '方向验证'}：把方向变成能力"
    if stage == "junior":
        return f"大三 · {intent or '快速试错'}：实习/备考进入主战场"
    if stage == "senior":
        return f"大四 · {intent or '毕业冲刺'}：把准备兑换成结果"
    if stage == "graduated":
        return f"已毕业 · {intent or '过渡期'}：保持节奏，完成落地"
    return f"{label} · 先补齐年级与目标，再生成规划"


def build_guide(
    *,
    grade: str | None,
    intent: Any = None,
    direction: Any = None,
    major: Any = None,
) -> dict[str, Any]:
    """生成一份确定性生涯规划。

    大一且未选择目标：needs_intent=True、steps 为空，前端必须先让学选择；
    大二/大三未选择目标：直接给探索型规划，不强制先选；
    其余阶段按目标给出剩余阶段路径。
    """
    normalized_grade = str(grade or "").strip() or None
    stage = stage_of(normalized_grade)
    selected = normalize_intent(intent)
    needs_intent = stage == "freshman" and selected is None
    resolved_direction = resolve_direction(direction, selected)
    steps = [] if needs_intent else _steps_for(stage, selected)

    return {
        "grade": normalized_grade or "年级未知",
        "stage": stage,
        "intent": selected,
        "needs_intent": needs_intent,
        "headline": _headline(stage, normalized_grade, selected),
        "direction": resolved_direction,
        "major": str(major or ""),
        "steps": steps,
        "options": [dict(option) for option in INTENT_OPTIONS],
        "note": "规划由确定性规则生成；目标可随时调整，调整后重新生成路径。",
        "engine_version": GUIDE_ENGINE_VERSION,
    }
