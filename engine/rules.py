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
