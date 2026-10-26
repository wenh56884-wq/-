# engine/rules.py
# 职责：预警规则的默认阈值与权重（dataclass），支持被 MySQL warning_threshold 覆盖
# 依赖：无外部依赖（纯数据 + 纯函数，便于迁移 PySpark）
# 说明：三条指标的分档/区间/上限全部集中在此，DB 覆盖只改数值不改算式

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Iterable, Mapping

# --- 预警等级常量 ---
LEVEL_RED = "red"
LEVEL_ORANGE = "orange"
LEVEL_YELLOW = "yellow"
LEVEL_NONE = "none"
# 灰档：可用指标不足（data insufficient），UI 文案「数据不足 · 请联系教务补录」
# 排在最后：它不表示平静档，get_warning_list 用它过滤时被当成「数据不全」而非「正常」
LEVEL_UNKNOWN = "unknown"
LEVELS: tuple[str, ...] = (
    LEVEL_RED, LEVEL_ORANGE, LEVEL_YELLOW, LEVEL_NONE, LEVEL_UNKNOWN,
)

# --- warning_threshold.metric 取值（数据库行的键）---
METRIC_FAIL_COUNT = "fail_count"
METRIC_GPA_DROP = "gpa_drop"
METRIC_ATTENDANCE = "attendance_rate"
METRIC_LEVEL = "level"
METRIC_GPA_SLOPE = "gpa_drop_slope"


def to_float(value: Any) -> float | None:
    """把 MySQL Decimal / str / None 统一转成 float；不可转或空值返回 None。"""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class FailCountRule:
    """指标一：挂科门次（0→0，1→score_1，2→score_2，≥3→score_3 且为上限）。"""

    weight: float = 1.0
    score_1: float = 15.0
    score_2: float = 30.0
    score_3: float = 45.0

    def score(self, fail_count: int) -> float:
        """按挂科门次返回该项加权得分。"""
        n = max(0, int(fail_count))
        if n <= 0:
            return 0.0
        if n == 1:
            return self.weight * self.score_1
        if n == 2:
            return self.weight * self.score_2
        return self.weight * self.score_3


@dataclass(frozen=True)
class GpaDropRule:
    """指标二：均分下滑分（≥start 起算，base + (drop-start)*slope，上限 ceiling）。"""

    weight: float = 1.0
    start: float = 5.0
    base: float = 10.0
    slope: float = 2.0
    ceiling: float = 30.0

    def score(self, drop: float) -> float:
        """按下滑分数返回该项加权得分；下滑不足 start 返回 0.0。"""
        d = float(drop)
        if d < self.start:
            return 0.0
        raw = self.base + (d - self.start) * self.slope
        return self.weight * min(self.ceiling, max(0.0, raw))


@dataclass(frozen=True)
class AttendanceRule:
    """指标三：出勤率（低于 start 起算，线性到 floor 拿满，上限 ceiling）。"""

    weight: float = 1.0
    start: float = 0.85
    floor: float = 0.60
    ceiling: float = 25.0

    def score(self, rate: float) -> float:
        """按出勤率返回该项加权得分；出勤率不低于 start 返回 0.0。"""
        r = float(rate)
        if r >= self.start:
            return 0.0
        if self.start <= self.floor:
            return self.weight * self.ceiling
        ratio = (self.start - r) / (self.start - self.floor)
        return self.weight * min(self.ceiling, max(0.0, self.ceiling * ratio))


@dataclass(frozen=True)
class LevelRule:
    """分级门槛：分数 ≥ 对应门槛取该级别，全不满足为 none。"""

    red: float = 65.0
    orange: float = 45.0
    yellow: float = 25.0

    def of(self, score: int) -> str:
        """把 0~100 的整数风险分映射为等级字符串。"""
        if score >= self.red:
            return LEVEL_RED
        if score >= self.orange:
            return LEVEL_ORANGE
        if score >= self.yellow:
            return LEVEL_YELLOW
        return LEVEL_NONE


@dataclass(frozen=True)
class WarningRules:
    """某租户的完整预警规则集合（三条指标 + 分级门槛）。"""

    tenant_id: int = 0
    fail_count: FailCountRule = FailCountRule()
    gpa_drop: GpaDropRule = GpaDropRule()
    attendance: AttendanceRule = AttendanceRule()
    level: LevelRule = LevelRule()

    @classmethod
    def defaults(cls, tenant_id: int) -> "WarningRules":
        """返回该租户的默认规则（V1：各项权重 1.0）。"""
        return cls(
            tenant_id=tenant_id,
            fail_count=FailCountRule(),
            gpa_drop=GpaDropRule(),
            attendance=AttendanceRule(),
            level=LevelRule(),
        )

    def level_of(self, score: int) -> str:
        """按本租户的分级门槛返回等级。"""
        return self.level.of(score)


def build_rules(tenant_id: int, rows: Iterable[Mapping[str, Any]]) -> WarningRules:
    """用数据库行覆盖默认规则。

    warning_threshold 行的列含义随 metric 而定（None 的列表示不覆盖）：

    | metric            | weight | yellow_value | orange_value | red_value |
    |-------------------|--------|--------------|--------------|-----------|
    | fail_count        | 指标权重 | 挂 1 门得分   | 挂 2 门得分   | ≥3 门得分  |
    | gpa_drop          | 指标权重 | 起算下滑分差  | 起算固定分    | 得分上限   |
    | attendance_rate   | 指标权重 | 起算出勤率    | 拿满出勤率    | 得分上限   |
    | gpa_drop_slope    | 忽略    | 每分斜率      | 忽略         | 忽略      |
    | level             | 忽略    | 黄色门槛      | 橙色门槛      | 红色门槛   |

    未知 metric 一律忽略；rows 为空则返回默认规则。
    """
    rules = WarningRules.defaults(tenant_id)
    for row in rows or ():
        metric = str(row.get("metric") or "").strip()
        weight = to_float(row.get("weight"))
        yellow = to_float(row.get("yellow_value"))
        orange = to_float(row.get("orange_value"))
        red = to_float(row.get("red_value"))

        if metric == METRIC_FAIL_COUNT:
            old = rules.fail_count
            rules = replace(
                rules,
                fail_count=replace(
                    old,
                    weight=weight if weight is not None else old.weight,
                    score_1=yellow if yellow is not None else old.score_1,
                    score_2=orange if orange is not None else old.score_2,
                    score_3=red if red is not None else old.score_3,
                ),
            )
        elif metric == METRIC_GPA_DROP:
            old = rules.gpa_drop
            rules = replace(
                rules,
                gpa_drop=replace(
                    old,
                    weight=weight if weight is not None else old.weight,
                    start=yellow if yellow is not None else old.start,
                    base=orange if orange is not None else old.base,
                    ceiling=red if red is not None else old.ceiling,
                ),
            )
        elif metric == METRIC_GPA_SLOPE:
            slope = yellow if yellow is not None else rules.gpa_drop.slope
            rules = replace(rules, gpa_drop=replace(rules.gpa_drop, slope=slope))
        elif metric == METRIC_ATTENDANCE:
            old = rules.attendance
            rules = replace(
                rules,
                attendance=replace(
                    old,
                    weight=weight if weight is not None else old.weight,
                    start=yellow if yellow is not None else old.start,
                    floor=orange if orange is not None else old.floor,
                    ceiling=red if red is not None else old.ceiling,
                ),
            )
        elif metric == METRIC_LEVEL:
            old = rules.level
            rules = replace(
                rules,
                level=replace(
                    old,
                    yellow=yellow if yellow is not None else old.yellow,
                    orange=orange if orange is not None else old.orange,
                    red=red if red is not None else old.red,
                ),
            )
    return rules


# ===========================================================
# 岗位推荐（P9）——规则版推荐的全部权重与映射表集中在此
# 纯数据，不放散到 engine\recommend.py 里
# ===========================================================
RECOMMEND_ENGINE_VERSION = "v1.0"

# 四维权重（加权求和，总和 1.0）
RECOMMEND_WEIGHTS: dict[str, float] = {
    "major_match": 0.35,   # 专业匹配度
    "gpa_gate": 0.25,      # 成绩门槛达成度
    "skill_cover": 0.30,   # 技能覆盖率
    "interest_fit": 0.10,  # 兴趣重合度
}

# 方向 → 对口专业（完全匹配）
DIR_MAJORS: dict[str, tuple[str, ...]] = {
    "后端": ("软件工程", "计算机科学与技术", "网络工程", "信息安全", "人工智能", "物联网工程"),
    "前端": ("软件工程", "计算机科学与技术", "数字媒体技术"),
    "数据": ("数据科学与大数据技术", "统计学", "数学与应用数学", "软件工程", "信息管理与信息系统"),
    "算法": ("人工智能", "计算机科学与技术", "软件工程", "数学与应用数学", "统计学"),
    "测试": ("软件工程", "计算机科学与技术", "电子信息工程"),
    "运维": ("网络工程", "计算机科学与技术", "电子信息工程", "通信工程"),
    "产品": ("信息管理与信息系统", "工商管理", "软件工程"),
    "运营": ("工商管理", "市场营销", "电子商务", "新闻传播学"),
    "金融": ("金融学", "金融工程", "经济学", "国际经济与贸易"),
    "财务": ("会计学", "财务管理", "审计学", "财政学"),
    "设计": ("视觉传达设计", "数字媒体技术", "环境设计"),
    "物流": ("物流管理", "物流工程", "工商管理"),
    "人力": ("人力资源管理", "工商管理", "心理学"),
    "教育": ("教育学", "学前教育", "小学教育", "英语教育"),
}

# 方向 → 相关专业（半匹配 0.6）：技术岗之间互通、经管岗之间互通
DIR_RELATED_MAJORS: dict[str, tuple[str, ...]] = {
    "后端": ("电子信息工程", "通信工程", "数据科学与大数据技术", "信息管理与信息系统"),
    "前端": ("信息安全", "电子信息工程"),
    "数据": ("计算机科学与技术", "金融工程", "经济学"),
    "算法": ("电子信息工程", "物联网工程"),
    "测试": ("网络工程", "通信工程"),
    "运维": ("软件工程", "物联网工程"),
    "产品": ("计算机科学与技术", "市场营销"),
    "运营": ("新闻传播学", "人力资源管理", "电子商务"),
    "金融": ("会计学", "财务管理", "经济学", "国际经济与贸易"),
    "财务": ("金融学", "经济学", "审计学"),
    "设计": ("软件工程", "市场营销"),
    "物流": ("工商管理", "市场营销"),
    "人力": ("心理学", "汉语言文学"),
    "教育": ("汉语言文学", "英语"),
}

# 相关方向（兴趣重合度给 0.5）
DIR_RELATED_DIRS: dict[str, tuple[str, ...]] = {
    "后端": ("算法", "前端", "数据", "测试"),
    "前端": ("设计", "产品", "后端"),
    "数据": ("算法", "金融", "后端"),
    "算法": ("数据", "后端"),
    "测试": ("后端", "运维"),
    "运维": ("测试", "后端"),
    "产品": ("运营", "设计", "前端"),
    "运营": ("产品", "人力"),
    "金融": ("财务", "数据"),
    "财务": ("金融",),
    "设计": ("前端", "产品"),
    "物流": ("运营",),
    "人力": ("运营", "教育"),
    "教育": ("人力", "运营"),
}

# 成绩门槛：min_gpa = 基准 + 学历溢价 + 经验溢价，上限 90
GPA_BASE = 60.0
GPA_EDU_PREMIUM: dict[str, float] = {"学历不限": 0.0, "初中": 0.0, "高中": 1.0, "中专": 1.0,
                                     "大专": 3.0, "本科": 6.0, "硕士": 10.0, "博士": 12.0}
GPA_EXP_PREMIUM = 1.5      # 每 1 年经验要求的溢价
GPA_MAX_GATE = 90.0
GPA_EXP_CAP = 6            # 经验上限（超过不再加码）

# 技能缺 → 建议课程（advice 模板用，无随机数、无大模型）
SKILL_ADVICE_COURSE: dict[str, str] = {
    "Java": "《Java 程序设计》", "Python": "《Python 程序设计》",
    "C++": "《C++ 程序设计》", "C": "《程序设计基础（C语言）》",
    "SQL": "《数据库原理》", "MySQL": "《数据库原理》", "数据库": "《数据库原理》",
    "数据结构": "《数据结构》", "算法": "《数据结构与算法》",
    "Linux": "《Linux 操作系统》", "网络": "《计算机网络》",
    "Android": "《移动应用开发》", "前端": "《Web 前端开发》",
    "Vue": "《Web 前端开发》", "Excel": "《数据处理与可视化》",
    "会计": "《基础会计》", "审计": "《审计学》", "税法": "《税法》",
    "财务分析": "《财务分析》", "投资": "《投资学》", "英语": "《大学英语》",
}
DEFAULT_ADVICE_COURSE = "对应方向的进阶选修课"

# 福利类噪声 tag（招聘站把「月休8天/年度体检/晋升渠道」也算进 skill_tags），
# 参与技能覆盖计算会污染结果，先剔除再做覆盖率
WELFARE_STOPWORDS: tuple[str, ...] = (
    "五险", "公积金", "一金", "社保", "年终", "带薪", "年假", "体检", "旅游", "月休",
    "双休", "包吃", "包住", "餐补", "补贴", "房补", "车补", "交通", "通讯补助",
    "晋升", "培训", "团建", "班车", "生日", "节日", "福利", "奖金", "加班补助",
    "年底双薪", "股票期权", "定期体检", "员工旅游", "零食下午茶", "免费班车",
    "通讯补贴", "出差补贴", "季度奖金", "绩效奖金", "六险一金", "五险一金",
    "弹性工作", "舒适办公", "人性化", "氛围好", "年轻化", "晋升渠道", "完善的",
    "能力优先", "平台大", "领导好", "前景好", "岗位晋升", "技能培训",
)
