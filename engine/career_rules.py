# engine/career_rules.py
# 职责：职业规划规培模块的确定性规则引擎（career-v1）
# 依赖：仅标准库（datetime / dataclasses / typing），不连数据库、不调大模型
# 铁律：一切"判定"必须由本模块给出，模型只负责组织语言。
#       ——硬门槛是否满足、剩余周数、阶段日期、周报三色、是否升级预警、
#         通知是否已截止、模型"系统记录"是否越权，全部在此完成。

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Mapping, Sequence

CAREER_ENGINE_VERSION = "career-v1"

# --- 目标类型 ---
GOAL_CIVIL = "考公"
GOAL_POSTGRAD = "考研"
GOAL_EMPLOY = "就业"
GOAL_MIXED = "混合"
GOALS: tuple[str, ...] = (GOAL_CIVIL, GOAL_POSTGRAD, GOAL_EMPLOY, GOAL_MIXED)

# --- 周监控三色（与 warning 的 red/orange/yellow/none 同构，但语义独立）---
WEEK_GREEN = "green"      # 达标
WEEK_YELLOW = "yellow"    # 落入容忍带，需关注
WEEK_RED = "red"          # 明显落后
WEEK_UNKNOWN = "unknown"  # 无数据，不冒充达标

# --- 指标方向 ---
DIR_UP = "up"      # 越高越好：学习时长、正确率、完成度
DIR_DOWN = "down"  # 越低越好：错题数、拖延天数

# --- 硬门槛比对状态 ---
GATE_PASS = "pass"
GATE_FAIL = "fail"
GATE_UNKNOWN = "unknown"  # 缺数据：不判满足也不判不满足

DEFAULT_TOLERANCE = 0.10  # 容忍带默认 10%

_DATE_PATTERNS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%Y.%m.%d",
    "%Y年%m月%d日",
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
)


# ----------------------------------------------------------------
# 基础工具
# ----------------------------------------------------------------
def parse_date(value: Any) -> date | None:
    """把多种写法的日期串解析成 date；解析失败返回 None（不猜）。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    # 去掉"截止""前"等中文尾巴，只留数字与分隔符
    text = re.sub(r"[^\d\-/.年月日: ]", "", text).strip()
    for fmt in _DATE_PATTERNS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _num(value: Any) -> float | None:
    """转 float；None / 空串 / 不可转 → None（缺失不冒充 0）。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        text = str(value).strip()
        if not text or text in {"-", "--", "无", "未填", "未知"}:
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def _round(value: float, digits: int = 2) -> float:
    return round(float(value) + 1e-12, digits)


# ----------------------------------------------------------------
# 一、硬门槛逐项比对（替代"让模型判断是否满足"）
# ----------------------------------------------------------------
@dataclass(frozen=True)
class Gate:
    """一条硬门槛。op 支持 >= > <= < == in contains。"""

    key: str
    label: str
    op: str
    value: Any
    hard: bool = True

    @classmethod
    def of(cls, row: Mapping[str, Any]) -> "Gate":
        return cls(
            key=str(row.get("key") or ""),
            label=str(row.get("label") or row.get("项目") or ""),
            op=str(row.get("op") or ">="),
            value=row.get("value", row.get("要求")),
            hard=bool(row.get("hard", True)),
        )


def _compare(actual: Any, op: str, target: Any) -> bool | None:
    """返回 True/False；类型不匹配返回 None（视为无法判定）。"""
    if op == "in":
        if isinstance(target, (list, tuple, set)):
            return str(actual) in {str(x) for x in target}
        return None
    if op == "contains":
        if actual is None or target is None:
            return None
        if not str(target).strip():
            # 规则库留空表示"该校不设此项"，视为无法判定而非默认通过
            return None
        return str(target) in str(actual)
    a = _num(actual)
    t = _num(target)
    if a is None or t is None:
        # 数值不可比时退化为字符串比较（仅 == 有意义）
        if op in {"==", "="}:
            return None if actual is None else str(actual) == str(target)
        return None
    if op in {">=", "≥"}:
        return a >= t
    if op in {"<=", "≤"}:
        return a <= t
    if op in {">", "＞"}:
        return a > t
    if op in {"<", "＜"}:
        return a < t
    if op in {"==", "="}:
        return abs(a - t) < 1e-9
    return None


def check_hard_gates(
    gates: Iterable[Mapping[str, Any] | Gate],
    facts: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """逐项比对硬门槛，返回带确定状态的清单。

    facts 缺失该键 → GATE_UNKNOWN（既不算满足也不算不满足），
    这是"缺失不冒充"在 career 模块的落地。
    """
    out: list[dict[str, Any]] = []
    for item in gates:
        gate = item if isinstance(item, Gate) else Gate.of(item)
        actual = facts.get(gate.key)
        ok = _compare(actual, gate.op, gate.value)
        if actual is None or ok is None:
            status = GATE_UNKNOWN
        else:
            status = GATE_PASS if ok else GATE_FAIL
        row: dict[str, Any] = {
            "key": gate.key,
            "项目": gate.label or gate.key,
            "要求": f"{gate.op} {gate.value}",
            "当前状态": status,
            "hard": gate.hard,
        }
        if status == GATE_UNKNOWN:
            row["当前值"] = None
            row["说明"] = "缺数据，未判定"
        else:
            row["当前值"] = actual
            a, t = _num(actual), _num(gate.value)
            if a is not None and t is not None and gate.op in {">=", ">", "<=", "<", "≥", "≤", "＞", "＜"}:
                row["差额"] = _round(a - t)
        out.append(row)
    return out


def build_gaps(gate_results: Sequence[Mapping[str, Any]]) -> list[str]:
    """由硬门槛结果生成"当前差距"（只列 fail 项，模型无权增删）。"""
    gaps: list[str] = []
    for row in gate_results:
        if row.get("当前状态") != GATE_FAIL:
            continue
        delta = row.get("差额")
        label = str(row.get("项目") or row.get("key") or "")
        if delta is None:
            gaps.append(f"{label}未达标（要求 {row.get('要求')}）")
        else:
            sign = "差" if delta < 0 else "超"
            gaps.append(f"{label}未达标（要求 {row.get('要求')}，{sign} {abs(delta):g}）")
    return gaps


def unknown_gates(gate_results: Sequence[Mapping[str, Any]]) -> list[str]:
    """列出因缺数据无法判定的门槛，供前端提示学生补充。"""
    return [
        str(row.get("项目") or row.get("key") or "")
        for row in gate_results
        if row.get("当前状态") == GATE_UNKNOWN
    ]


# ----------------------------------------------------------------
# 二、时间倒推（替代"让模型算日期"）
# ----------------------------------------------------------------
def weeks_until(deadline: Any, today: date | None = None) -> dict[str, Any]:
    """距某个截止日还有几天/几周。已过期 is_past=True、weeks_left=0。"""
    base = today or date.today()
    target = parse_date(deadline)
    if target is None:
        return {
            "deadline": None,
            "days_left": None,
            "weeks_left": None,
            "raw_weeks": None,
            "is_past": None,
            "error": "日期无法解析",
        }
    days = (target - base).days
    return {
        "deadline": target.isoformat(),
        "days_left": days,
        "weeks_left": max(0, days // 7),
        "raw_weeks": _round(days / 7.0),
        "is_past": days < 0,
    }


def plan_phases(
    phases: Sequence[Mapping[str, Any]],
    weeks_left: int,
    today: date | None = None,
) -> list[dict[str, Any]]:
    """按占比把剩余周数切成阶段，并算出每段起止日期。

    phases 形如 [{"阶段": "基础", "占比": 0.4, "核心任务": "..."}]，
    占比之和不必为 1（内部归一）；周数之和恒等于 weeks_left（余数补到最后一段）。
    剩余周数不足阶段数时，从后往前砍掉 0 周阶段。
    """
    base = today or date.today()
    weeks_left = max(0, int(weeks_left))
    if not phases or weeks_left == 0:
        return []

    weights = [_num(p.get("占比")) or 0.0 for p in phases]
    total_weight = sum(weights)
    if total_weight <= 0:
        weights = [1.0] * len(phases)
        total_weight = float(len(phases))

    # 先按占比分配，再修尾
    allocated = [int(weeks_left * w / total_weight) for w in weights]
    if weeks_left >= len(phases):
        # 保障每段至少 1 周
        for i in range(len(allocated)):
            if allocated[i] == 0:
                allocated[i] = 1
    drift = weeks_left - sum(allocated)
    allocated[-1] += drift
    if allocated[-1] < 0:  # 极端情况：全被前面的抢光
        allocated[-1] = 0

    out: list[dict[str, Any]] = []
    cursor = 0
    for spec, weeks in zip(phases, allocated):
        if weeks <= 0:
            continue
        start = base + timedelta(days=cursor * 7)
        end = start + timedelta(days=weeks * 7 - 1)
        out.append(
            {
                "阶段": str(spec.get("阶段") or ""),
                "周数": weeks,
                "起始周": cursor + 1,
                "结束周": cursor + weeks,
                "时间范围": f"{start.isoformat()} ~ {end.isoformat()}",
                "核心任务": str(spec.get("核心任务") or ""),
                "周监控指标": list(spec.get("周监控指标") or []),
            }
        )
        cursor += weeks
    return out


# ----------------------------------------------------------------
# 三、周监控三色判定（替代"让模型判红黄绿"）
# ----------------------------------------------------------------
def judge_metric(
    actual: Any,
    baseline: Any,
    direction: str = DIR_UP,
    tolerance: float = DEFAULT_TOLERANCE,
) -> dict[str, Any]:
    """单个指标判色。actual 缺失 → unknown（绝不默认达标）。"""
    a = _num(actual)
    b = _num(baseline)
    if a is None or b is None:
        return {"判定": WEEK_UNKNOWN, "缺口": None, "缺口率": None}

    tol = max(0.0, float(tolerance))
    if direction == DIR_DOWN:
        if b == 0:
            verdict = WEEK_GREEN if a <= 0 else WEEK_RED
            return {"判定": verdict, "缺口": _round(a - b), "缺口率": None}
        if a <= b:
            verdict = WEEK_GREEN
        elif a <= b * (1.0 + tol):
            verdict = WEEK_YELLOW
        else:
            verdict = WEEK_RED
        return {"判定": verdict, "缺口": _round(a - b), "缺口率": _round((a - b) / b, 4)}

    # 默认越高越好
    if b == 0:
        verdict = WEEK_GREEN
        return {"判定": verdict, "缺口": _round(a - b), "缺口率": None}
    if a >= b:
        verdict = WEEK_GREEN
    elif a >= b * (1.0 - tol):
        verdict = WEEK_YELLOW
    else:
        verdict = WEEK_RED
    return {"判定": verdict, "缺口": _round(a - b), "缺口率": _round((a - b) / b, 4)}


def judge_week_items(items: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """批量判色并汇总总体状态。

    items 元素：{"指标": str, "达标线": number, "本周实际": number|None,
                "方向": "up"|"down", "容忍带": 0.1}
    汇总规则：有 red → red；否则有 yellow → yellow；有 green 且无红黄 → green；
             全部缺数据 → unknown（不冒充绿）。
    """
    rows: list[dict[str, Any]] = []
    counts = {WEEK_RED: 0, WEEK_YELLOW: 0, WEEK_GREEN: 0, WEEK_UNKNOWN: 0}
    for item in items:
        verdict = judge_metric(
            item.get("本周实际"),
            item.get("达标线"),
            direction=str(item.get("方向") or DIR_UP),
            tolerance=_num(item.get("容忍带")) if item.get("容忍带") is not None else DEFAULT_TOLERANCE,
        )
        row = {
            "指标": str(item.get("指标") or ""),
            "达标线": item.get("达标线"),
            "本周实际": item.get("本周实际"),
            "方向": str(item.get("方向") or DIR_UP),
            "判定": verdict["判定"],
            "缺口": verdict["缺口"],
            "缺口率": verdict["缺口率"],
        }
        counts[verdict["判定"]] = counts.get(verdict["判定"], 0) + 1
        rows.append(row)

    if counts[WEEK_RED]:
        overall = WEEK_RED
    elif counts[WEEK_YELLOW]:
        overall = WEEK_YELLOW
    elif counts[WEEK_GREEN]:
        overall = WEEK_GREEN
    else:
        overall = WEEK_UNKNOWN

    return {
        "overall": overall,
        "items": rows,
        "missing": [r["指标"] for r in rows if r["判定"] == WEEK_UNKNOWN],
        "counts": counts,
        "engine": CAREER_ENGINE_VERSION,
    }


def escalate_risks(
    history: Sequence[Sequence[Mapping[str, Any]]],
    current: Sequence[Mapping[str, Any]],
    streak: int = 2,
) -> list[dict[str, Any]]:
    """连续 N 周同项非绿 → 升级为风险预警。

    history 按"由近到远"排列（history[0] 为上周）。current 为本周。
    单周波动不升级；缺数据（unknown）不计入连续落后。
    """
    need = max(2, int(streak))
    cur = {str(r.get("指标") or ""): str(r.get("判定") or "") for r in current}
    hits: list[dict[str, Any]] = []

    for label, verdict in cur.items():
        if verdict not in {WEEK_RED, WEEK_YELLOW}:
            continue
        run = 1
        for week in history:
            prev = {str(r.get("指标") or ""): str(r.get("判定") or "") for r in week}
            v = prev.get(label)
            if v in {WEEK_RED, WEEK_YELLOW}:
                run += 1
            else:
                break
        if run >= need:
            hits.append(
                {
                    "指标": label,
                    "连续周数": run,
                    "当前判定": verdict,
                    "动作": f"升级为风险预警（连续 {run} 周未达标）",
                }
            )
    return hits


# ----------------------------------------------------------------
# 四、通知截止过滤（替代"让模型判断今天几号"）
# ----------------------------------------------------------------
def filter_notices(
    notices: Iterable[Mapping[str, Any]],
    today: date | None = None,
    with_status_only: bool = False,
) -> list[dict[str, Any]]:
    """给每条通知打上确定性状态：open / expired / unknown_date。

    模型只能看到 open 的条目做相关性判断，已截止的一律不进推送。
    """
    base = today or date.today()
    out: list[dict[str, Any]] = []
    for item in notices:
        deadline = parse_date(item.get("截止时间") or item.get("deadline"))
        row = dict(item)
        if deadline is None:
            row["status"] = "unknown_date"
            row["days_left"] = None
        elif (deadline - base).days < 0:
            row["status"] = "expired"
            row["days_left"] = (deadline - base).days
        else:
            row["status"] = "open"
            row["days_left"] = (deadline - base).days
        row["deadline"] = deadline.isoformat() if deadline else None
        out.append(row)
    if with_status_only:
        return [{"标题": r.get("标题"), "status": r["status"], "days_left": r["days_left"]} for r in out]
    return out


def open_notices(
    notices: Iterable[Mapping[str, Any]],
    today: date | None = None,
) -> list[dict[str, Any]]:
    """只保留可推送的通知（未截止 + 日期可解析），送去给模型判相关性。"""
    return [r for r in filter_notices(notices, today) if r["status"] == "open"]


# ----------------------------------------------------------------
# 五、模型"系统记录"白名单校验（防止模型凭空写库）
# ----------------------------------------------------------------
SYSTEM_RECORD_KEYS = ("新增待办", "状态变化", "需更新画像")
IMMUTABLE_FIELDS = ("目标类型", "目标描述", "时间线")


def validate_system_record(
    record: Any,
    allowed_keys: Sequence[str] = SYSTEM_RECORD_KEYS,
    immutable: Sequence[str] = IMMUTABLE_FIELDS,
) -> dict[str, Any]:
    """校验模型返回的【系统记录】是否可以落库。

    - 出现白名单外的键 → rejected（整条丢弃，不部分采信）
    - 状态变化里出现不可变字段（目标类型/时间线等）→ rejected
    - 值类型不对 → rejected
    """
    if record is None:
        return {"ok": False, "accepted": {}, "rejected": [], "reason": "无系统记录"}
    if not isinstance(record, Mapping):
        return {"ok": False, "accepted": {}, "rejected": [], "reason": "系统记录不是对象"}

    allowed = {str(k) for k in allowed_keys}
    unknown = [k for k in record.keys() if str(k) not in allowed]
    if unknown:
        return {
            "ok": False,
            "accepted": {},
            "rejected": unknown,
            "reason": f"出现白名单外的键：{unknown}",
        }

    accepted: dict[str, Any] = {}
    rejected: list[str] = []
    for key, value in record.items():
        if key == "新增待办":
            if not isinstance(value, (list, tuple)):
                rejected.append(key)
                continue
            items = [str(v).strip() for v in value if str(v).strip()]
            accepted[key] = items[:5]  # 最多 5 条，防刷屏
        elif key == "状态变化":
            if not isinstance(value, (list, tuple)):
                rejected.append(key)
                continue
            changes: list[dict[str, Any]] = []
            for change in value:
                if not isinstance(change, Mapping):
                    rejected.append(key)
                    changes = []
                    break
                if any(str(f) in {str(x) for x in immutable} for f in change.keys()):
                    return {
                        "ok": False,
                        "accepted": {},
                        "rejected": [key],
                        "reason": f"试图修改不可变字段：{list(change.keys())}",
                    }
                changes.append(dict(change))
            if changes:
                accepted[key] = changes[:5]
        elif key == "需更新画像":
            if not isinstance(value, bool):
                rejected.append(key)
                continue
            accepted[key] = value

    return {
        "ok": bool(accepted) and not rejected,
        "accepted": accepted,
        "rejected": rejected,
        "reason": "" if not rejected else f"字段类型不合法：{rejected}",
    }


# ----------------------------------------------------------------
# 六、目标类型归一（模型输出用词不一致时兜底）
# ----------------------------------------------------------------
def normalize_goal(text: Any) -> str:
    """把"考公务员/国考/省考"归到考公，"读研/保研/研究生"归到考研，其余同上。"""
    raw = str(text or "").strip()
    if not raw:
        return ""
    civil = ("考公", "公务员", "国考", "省考", "选调", "事业单位", "事业编")
    postgrad = ("考研", "读研", "保研", "研究生", "硕士")
    employ = ("就业", "求职", "找工作", "实习", "秋招", "春招", "入职")
    hit_civil = any(k in raw for k in civil)
    hit_post = any(k in raw for k in postgrad)
    hit_emp = any(k in raw for k in employ)
    if (hit_civil + hit_post + hit_emp) >= 2 or "混合" in raw or "同时" in raw or "两手" in raw:
        return GOAL_MIXED
    if hit_civil:
        return GOAL_CIVIL
    if hit_post:
        return GOAL_POSTGRAD
    if hit_emp:
        return GOAL_EMPLOY
    return raw


__all__ = [
    "CAREER_ENGINE_VERSION",
    "GOAL_CIVIL",
    "GOAL_POSTGRAD",
    "GOAL_EMPLOY",
    "GOAL_MIXED",
    "GOALS",
    "WEEK_GREEN",
    "WEEK_YELLOW",
    "WEEK_RED",
    "WEEK_UNKNOWN",
    "DIR_UP",
    "DIR_DOWN",
    "GATE_PASS",
    "GATE_FAIL",
    "GATE_UNKNOWN",
    "SYSTEM_RECORD_KEYS",
    "IMMUTABLE_FIELDS",
    "parse_date",
    "check_hard_gates",
    "build_gaps",
    "unknown_gates",
    "weeks_until",
    "plan_phases",
    "judge_metric",
    "judge_week_items",
    "escalate_risks",
    "filter_notices",
    "open_notices",
    "validate_system_record",
    "normalize_goal",
]
