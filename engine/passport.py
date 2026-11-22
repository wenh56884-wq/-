# engine/passport.py
# 职责：能力护照——把多场已完成的模拟面试折成四维雷达、成长曲线、徽章与下一步动作。
# 铁律：引擎定数，模型说话。纯函数、无随机、无网络、无 LLM。
# 缺失不冒充：没有场次就是空护照；某维没数据就不参与均值，绝不用 0 分填空。
#
# 口径澄清（契约未写死、按最合理方式定，改动须同步契约）：
# 1) 四维折算复用 panel.dimension_percent（契约要求，不复制实现）。sessions 的 dims
#    既可直接传百分制，也可传 score_answer 原始明细（含 keyword_score 等），后者自动折算。
# 2) best_dim / worst_dim 按「全周期均值」取，不按最后一场——护照衡量的是长期能力，不是单场波动。
# 3) consistency = 1 - 总分总体标准差/30，clamp 到 0~1（30 分波动视为完全不稳定）。
# 4) 空护照的 badges 按契约给 []；有场次时徽章恒为 5 条，未达成为 earned:false。

from __future__ import annotations

from typing import Any

from engine.panel import DIMS, DIM_ACTION, DIM_LABELS, dimension_percent

PASSPORT_VERSION = "passport-v1"

TARGET_DEFAULT: dict[str, float] = {"content": 78, "structure": 76, "depth": 72, "evidence": 70}

# 徽章固定 5 个，顺序与契约一致
_BADGES: tuple[tuple[str, str, str], ...] = (
    ("first", "首战告捷", "完成第 1 场模拟面试"),
    ("streak3", "连续作战", "完成 3 场模拟面试"),
    ("improved10", "显著进步", "最后一场比首场总分提升 10 分"),
    ("allrounder", "四维均衡", "四维最新分都接近目标值（目标 -8 以内）"),
    ("steady", "稳定输出", "最近 3 场三人分歧都小于 8 分"),
)

# 维度补强动作与 drill 复用 panel 的口径，保证「同一短板同一处方」
_DRILL: dict[str, str] = {
    "content": "挑一道项目题，用 3 个岗位关键词各造一句话。",
    "structure": "拿上一场最低分那题，按四段结构重说一遍并录音。",
    "depth": "给最近一个项目写 3 行：做了什么、怎么做、结果多少。",
    "evidence": "把简历里 3 个项目各补一个可核对的数字。",
}


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out:  # NaN
        return None
    return out


def _target_of(target: dict | None) -> dict[str, float]:
    """目标值：用户传的覆盖默认值；非法/缺失的维度回落到默认。"""
    src = target if isinstance(target, dict) else {}
    out: dict[str, float] = {}
    for dim in DIMS:
        val = _num(src.get(dim))
        out[dim] = round(val, 2) if val is not None else float(TARGET_DEFAULT[dim])
    return out


def _dims_of(session: dict) -> dict[str, float]:
    """取一场的四维百分制：优先 dims 字段；若是 score_answer 原始明细则复用 panel 折算。"""
    dims = session.get("dims") if isinstance(session, dict) else None
    if not isinstance(dims, dict):
        return {}
    if any(k in dims for k in ("keyword_score", "struct_score", "depth_score", "evidence_score")):
        return dimension_percent(dims)
    out: dict[str, float] = {}
    for dim in DIMS:
        val = _num(dims.get(dim))
        if val is not None:
            out[dim] = round(min(100.0, max(0.0, val)), 2)
    return out


def _clean_sessions(sessions: list[dict] | None) -> list[dict]:
    return [s for s in (sessions or []) if isinstance(s, dict)]


def _std(values: list[float]) -> float:
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    return (sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5


def _radar(dims_list: list[dict[str, float]], target: dict[str, float]) -> list[dict[str, Any]]:
    """固定 4 维、固定顺序：latest 取最后一个有值的场次，avg/best 基于全部有值场次。"""
    radar: list[dict[str, Any]] = []
    for dim in DIMS:
        vals = [d[dim] for d in dims_list if dim in d]
        latest = next((d[dim] for d in reversed(dims_list) if dim in d), None)
        tgt = target[dim]
        radar.append({
            "key": dim,
            "label": DIM_LABELS[dim],
            "latest": round(latest, 2) if latest is not None else None,
            "avg": round(sum(vals) / len(vals), 2) if vals else None,
            "best": round(max(vals), 2) if vals else None,
            "target": tgt,
            "gap": round(tgt - latest, 2) if latest is not None else None,
            "hit": latest is not None and latest >= tgt,
        })
    return radar


def _trend(rows: list[dict]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for s in rows:
        total = _num(s.get("total"))
        sid = s.get("session_id")
        out.append({
            "date": str(s.get("date") or ""),
            "total": round(total, 1) if total is not None else None,
            "job_title": str(s.get("job_title") or ""),
            "session_id": int(sid) if isinstance(sid, int) else sid,
        })
    return out


def _growth(rows: list[dict], dims_list: list[dict[str, float]]) -> dict | None:
    totals = [round(float(_num(s.get("total"))), 1) for s in rows if _num(s.get("total")) is not None]
    if not totals:
        return None
    first, last = totals[0], totals[-1]
    best_dim = worst_dim = None
    if dims_list:
        avg = {d: sum(x[d] for x in dims_list if d in x) / max(1, sum(1 for x in dims_list if d in x))
               for d in DIMS}
        present = [d for d in DIMS if any(d in x for x in dims_list)]
        if present:
            best_dim = min(present, key=lambda d: (-round(avg[d], 6), DIMS.index(d)))
            worst_dim = min(present, key=lambda d: (round(avg[d], 6), DIMS.index(d)))
    consistency = round(max(0.0, min(1.0, 1.0 - _std(totals) / 30.0)), 2)
    return {"delta": round(last - first, 1), "first_total": first, "last_total": last,
            "best_dim": best_dim, "worst_dim": worst_dim, "consistency": consistency}


def _next_action(radar: list[dict[str, Any]], target: dict[str, float]) -> dict | None:
    """缺口最大的维度优先（目标 - 最新分）；只在有最新分的维度里挑，全无数据才返回 None。"""
    cands = [r for r in radar if r["gap"] is not None]
    if not cands:
        return None
    pick = min(cands, key=lambda r: (-round(float(r["gap"]), 6), DIMS.index(str(r["key"]))))
    dim = str(pick["key"])
    return {"dim": dim, "label": DIM_LABELS[dim], "gap": round(float(pick["gap"]), 2),
            "action": DIM_ACTION[dim], "drill": _DRILL[dim]}


def _badges(rows: list[dict], radar: list[dict[str, Any]], target: dict[str, float],
            growth: dict | None) -> list[dict[str, Any]]:
    n = len(rows)
    delta = float(growth["delta"]) if growth else 0.0
    latest_ok = [r for r in radar if r["latest"] is not None]
    allrounder = len(latest_ok) == len(DIMS) and all(
        float(r["latest"]) >= target[str(r["key"])] - 8 for r in radar)
    spreads = [_num(s.get("spread")) for s in rows[-3:]]
    steady = n >= 3 and all(v is not None and v < 8 for v in spreads)

    earned = {
        "first": n >= 1,
        "streak3": n >= 3,
        "improved10": n >= 2 and delta >= 10,
        "allrounder": allrounder,
        "steady": steady,
    }
    return [{"id": bid, "title": title, "desc": desc, "earned": bool(earned[bid])}
            for bid, title, desc in _BADGES]


def build_passport(sessions: list[dict], target: dict | None = None) -> dict:
    """能力护照。sessions 由路由按时间正序查好（只含 finished）：
       [{"session_id": 12, "date": "2026-11-10", "total": 71.2, "job_title": "...",
         "dims": {"content": 74.0, "structure": 68.0, "depth": 70.0, "evidence": 62.0},
         "probes": 1, "spread": 9.3}]

    返回：
    {
      "version": "passport-v1",
      "sessions": 4,
      "radar": [{"key","label","latest","avg","best","target","gap","hit"}],  # 固定 4 维
      "trend": [{"date","total","job_title","session_id"}],
      "growth": {"delta","first_total","last_total","best_dim","worst_dim","consistency"},
      "next_action": {"dim","label","gap","action","drill"},
      "badges": [{"id","title","desc","earned"}],   # 固定 5 条
      "empty": false
    }
    """
    rows = _clean_sessions(sessions)
    tgt = _target_of(target)
    if not rows:
        return {"version": PASSPORT_VERSION, "sessions": 0, "radar": [], "trend": [],
                "growth": None, "next_action": None, "badges": [], "empty": True}

    dims_list = [d for d in (_dims_of(s) for s in rows) if d]
    radar = _radar(dims_list, tgt)
    growth = _growth(rows, dims_list)
    return {
        "version": PASSPORT_VERSION,
        "sessions": len(rows),
        "radar": radar,
        "trend": _trend(rows),
        "growth": growth,
        "next_action": _next_action(radar, tgt),
        "badges": _badges(rows, radar, tgt, growth),
        "empty": False,
    }
