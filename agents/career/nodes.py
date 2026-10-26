# agents/career/nodes.py
# 职责：职业规划模块的 5 个 Agent 节点（画像解析 / 规则匹配 / 周监控 / 通知过滤 / 陪伴对话）
# 依赖：agents.llm（DeepSeek）/ engine.career_rules（确定性判定）/ agents.career.context（取数落库）
# 铁律：**引擎定数，模型说话**。
#       凡是"算"和"判"（门槛满不满足、还差几周、红黄绿、连续两周、是否截止、能不能写库）
#       全部由 engine.career_rules 完成；模型只做「自由文本→结构化」与「把结论说成人话」。

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any, Mapping, Sequence

from langchain_core.messages import HumanMessage, SystemMessage

from agents import llm as llm_module
from agents.career import context as cx
from engine import career_rules as cr

# 提示词版本（落库用，便于后续对比不同版本的产出）
PROMPT_VERSION = "career-v1"


# ----------------------------------------------------------------
# 通用工具
# ----------------------------------------------------------------
def _semester_deadline(today: date) -> date:
    """本学期教学周结束日（确定性规则，不让模型算日期）。

    秋季学期：8/25 开学，约 18 个教学周 → 次年 1 月 5 日前后结束
    春季学期：2/25 开学，约 18 个教学周 → 7 月 5 日前后结束
    若已过结束日，滚到下一个学期（保证 weeks_left 不会因日期过期变 0）。
    """
    year = today.year
    spring_end = date(year, 7, 5)
    autumn_end = date(year + 1, 1, 5)
    if today <= spring_end:
        return spring_end
    if today <= autumn_end:
        return autumn_end
    return date(year + 1, 7, 5)


def _extract_json(text: str) -> Any:
    """从模型输出里抠出第一个完整 JSON（容忍 ```json 围栏与前后废话）。"""
    if not text:
        return None
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", cleaned, re.S)
    if fence:
        cleaned = fence.group(1).strip()
    try:
        return json.loads(cleaned)
    except ValueError:
        pass
    # 兜底：找第一个 { 或 [ 到最后一个 } 或 ]
    for op, cl in (("{", "}"), ("[", "]")):
        i, j = cleaned.find(op), cleaned.rfind(cl)
        if i != -1 and j > i:
            try:
                return json.loads(cleaned[i : j + 1])
            except ValueError:
                continue
    return None


def _ask(system: str, user: str, temperature: float = 0.2) -> str:
    """调用 DeepSeek 拿纯文本（student 端单例，temperature 由调用方微调）。"""
    llm = llm_module.get_student_llm()
    msg = llm.invoke([SystemMessage(content=system), HumanMessage(content=user)])
    return str(getattr(msg, "content", "") or "")


# ================================================================
# 节点 1 · 画像解析（自由文本 → 结构化）
# ================================================================
PLAN_SYSTEM = """你是学生职业规划画像解析引擎。只做「文本抽取」，不做数值判定。

硬性约束（违反即视为失败）：
1. 只依据学生原文与给定事实，**不得臆造**学生经历、成绩、证书；
2. 时间线只允许写**相对学期**（如「大三上」「毕业前 3 个月」），
   **绝对日期一律不要写**——具体日期由系统按规则库计算；
3. 不得输出任何"当前绩点/是否达标/还差多少"之类判断，这些由系统计算后注入；
4. 若原文信息不足，把要问的问题放进 pending_questions（≤3 条）。

只输出 JSON，不要任何解释文字：
{
  "目标类型": "考公/考研/就业/混合",
  "目标描述": "一句话概括（≤40 字）",
  "时间线": [{"节点": "", "时间": "相对学期描述", "事项": ""}],
  "硬性指标": ["原文中提到的硬性要求"],
  "软性指标": ["原文中提到的加分项"],
  "待补充问题": ["需要学生补充的问题，≤3 条"]
}"""


def parse_plan(
    tenant_id: int,
    student_id: int,
    raw_text: str,
    *,
    persist: bool = True,
) -> dict[str, Any]:
    """提示词一：把规划原文解析成结构化画像。

    模型只负责抽取；目标类型再过一道 normalize_goal 归一；
    差距由 check_hard_gates + build_gaps 生成，模型无权决定。
    """
    if not raw_text or not raw_text.strip():
        raise ValueError("规划原文为空，无法解析")

    facts = cx.fetch_student_facts(tenant_id, student_id)
    user = (
        f"【学生基本信息】\n"
        f"年级：{facts.get('grade') or '未知'}\n"
        f"专业：{facts.get('major') or '未知'}\n"
        f"学院：{facts.get('college') or '未知'}\n\n"
        f"【职业规划原文】\n{raw_text.strip()}\n"
    )
    parsed = _extract_json(_ask(PLAN_SYSTEM, user, temperature=0.2))
    if not isinstance(parsed, Mapping):
        raise RuntimeError("模型未返回合法 JSON，请重试或检查 DeepSeek 配置")

    goal = cr.normalize_goal(parsed.get("目标类型") or raw_text)
    timeline = parsed.get("时间线") if isinstance(parsed.get("时间线"), list) else []
    questions = parsed.get("待补充问题") if isinstance(parsed.get("待补充问题"), list) else []

    # 硬门槛与差距：引擎算，模型不参与
    template = cx.load_template(goal)
    gates = template.get("hard_gates") or []
    gate_rows = cr.check_hard_gates(gates, facts) if gates else []
    gaps = cr.build_gaps(gate_rows)
    unknown = cr.unknown_gates(gate_rows)

    plan = {
        "目标类型": goal,
        "目标描述": str(parsed.get("目标描述") or "")[:80],
        "时间线": timeline,
        "硬性指标": parsed.get("硬性指标") if isinstance(parsed.get("硬性指标"), list) else [],
        "软性指标": parsed.get("软性指标") if isinstance(parsed.get("软性指标"), list) else [],
        "硬门槛": gate_rows,
        "当前差距": gaps,
        "未判定项": unknown,
        "待补充问题": questions[:3],
        "引擎版本": cr.CAREER_ENGINE_VERSION,
    }

    plan_id = 0
    if persist:
        plan_id = cx.save_plan(
            tenant_id, student_id,
            raw_text=raw_text,
            goal_type=goal,
            plan=plan,
            gaps=gaps,
            pending_questions=questions[:3],
            prompt_version=PROMPT_VERSION,
        )
    return {"plan_id": plan_id, "goal_type": goal, "plan": plan, "facts": facts}


# ================================================================
# 节点 2 · 规则匹配（模板由代码选，日期由引擎算，模型只写"为什么重要"）
# ================================================================
MATCH_SYSTEM = """你是规培规则说明撰写器。规则数值与日期**全部由系统给定**，你只负责解释。

硬性约束（违反即视为失败）：
1. **不得新增、删除或修改任何门槛数值、时间、周数**；
2. 不要自己算日期、不要自己排阶段——阶段划分已经算好了，你只按给定顺序写每个阶段的核心任务；
3. 只输出 JSON，不要解释文字。

只输出 JSON：
{
  "阶段任务": [{"阶段": "给定的阶段名（必须原样抄）", "核心任务": "该阶段做什么，≤40 字"}],
  "指标说明": [{"指标": "给定的指标名（必须原样抄）", "为什么重要": "≤30 字"}],
  "硬基线说明": "一句话说明哪些条件不可放宽（≤50 字）"
}"""


def match_rule(
    tenant_id: int,
    student_id: int,
    plan_id: int,
    *,
    persist: bool = True,
) -> dict[str, Any]:
    """提示词二：选模板 + 算阶段 + 生成个性化规则。

    分工：
      代码  → 选哪个模板、次模板与权重、剩余周数、阶段起止日期、周指标达标线
      引擎  → check_hard_gates / weeks_until / plan_phases
      模型  → 每个阶段"做什么"、每个指标"为什么重要"
    """
    plan_row = cx.fetch_active_plan(tenant_id, student_id)
    if not plan_row:
        raise ValueError("该生还没有职业规划画像，请先调用 parse_plan")
    plan = plan_row.get("plan") or {}
    goal = str(plan.get("目标类型") or plan_row.get("goal_type") or "")
    main_goal = cr.normalize_goal(goal)
    if main_goal == cr.GOAL_MIXED:
        # 混合目标：原文里先出现哪个就作主模板（确定性规则，不让模型选）
        main_goal = cr.normalize_goal(str(plan.get("目标描述") or ""))

    template = cx.load_template(main_goal)
    if not template:
        raise ValueError(f"找不到「{main_goal}」对应的规则模板，请检查 rules/ 目录")

    facts = cx.fetch_student_facts(tenant_id, student_id)
    gates = cr.check_hard_gates(template.get("hard_gates") or [], facts)

    # 剩余周数：规则库关键节点只写"10月中旬"这类季节描述，无法解析成绝对日期
    # （也不该解析——绝对日期必须来自真实公告，见 docs/数据来源说明.md）。
    # 这里按学期制倒推：默认冲刺到本学期教学周结束。
    today = date.today()
    deadline = _semester_deadline(today)
    weeks_left = max(0, int(cr.weeks_until(deadline, today).get("weeks_left") or 0))

    phases = cr.plan_phases(template.get("phases") or [], weeks_left, today)
    metrics = template.get("weekly_metrics") or []

    # 模型只写"核心任务"与"为什么重要"
    brief = {
        "目标": main_goal,
        "阶段名": [p.get("阶段") for p in phases],
        "指标名": [m.get("指标") for m in metrics],
        "硬基线": template.get("hard_baseline") or [],
    }
    user = (
        "【已知信息（不可更改，只能引用）】\n"
        + json.dumps(brief, ensure_ascii=False, indent=2)
        + "\n\n请按上述阶段名与指标名逐一给出解释。阶段名与指标名必须原样抄写。"
    )
    written = _extract_json(_ask(MATCH_SYSTEM, user, temperature=0.2)) or {}

    # 把模型写的解释贴回引擎算好的结构上（模型漏写的，保留模板原值）
    task_of = {
        str(x.get("阶段")): str(x.get("核心任务") or "")
        for x in (written.get("阶段任务") or [])
        if isinstance(x, Mapping)
    }
    why_of = {
        str(x.get("指标")): str(x.get("为什么重要") or "")
        for x in (written.get("指标说明") or [])
        if isinstance(x, Mapping)
    }
    for p in phases:
        task = task_of.get(str(p.get("阶段")))
        if task:
            p["核心任务_说明"] = task
    for m in metrics:
        why = why_of.get(str(m.get("指标")))
        if why:
            m["为什么重要"] = why

    if deadline:
        for p in phases:
            p["剩余周数"] = weeks_left

    rule_id = 0
    if persist:
        rule_id = cx.save_rule(
            tenant_id, student_id, plan_id or int(plan_row["id"]),
            main_template=str(template.get("template") or main_goal),
            sub_template=None,
            main_weight=1.0,
            gates=gates,
            phases=phases,
            metrics=metrics,
            calendar=template.get("key_nodes") or [],
            hard_baseline=template.get("hard_baseline") or [],
            adjustable=template.get("adjustable") or [],
        )

    return {
        "rule_id": rule_id,
        "goal_type": main_goal,
        "gates": gates,
        "gaps": cr.build_gaps(gates),
        "unknown": cr.unknown_gates(gates),
        "weeks_left": weeks_left,
        "deadline": deadline.isoformat() if deadline else None,
        "phases": phases,
        "metrics": metrics,
        "engine_version": cr.CAREER_ENGINE_VERSION,
    }


# ================================================================
# 节点 3 · 周监控（三色与升级由引擎判，模型只写摘要 + ≤3 条建议）
# ================================================================
WEEK_SYSTEM = """你是学业周报撰写器。三色判定与风险升级**已经由系统算好**，你只负责翻译成人话。

硬性约束（违反即视为失败）：
1. **不得自己判红黄绿**，只能引用给定判定结果；
2. 摘要必须以「客观、不施压」为基调，150 字以内；
3. 下周建议**最多 3 条**，每条都要有可量化目标（次数/时长/正确率/完成度）；
4. 不得编造学生未做过的事，不确定就写"需要你确认"；
5. 只输出 JSON，不要解释文字。

只输出 JSON：
{
  "周报摘要": "150 字以内",
  "下周建议": [{"建议": "具体做什么", "量化目标": "可验证的数字目标"}],
  "偏差说明": [{"指标": "原样抄给定的指标名", "说明": "为什么会落后，≤30 字"}]
}"""


def weekly_review(
    tenant_id: int,
    student_id: int,
    *,
    self_report: Mapping[str, Any] | None = None,
    today: date | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """提示词三：周度对比 → 三色判定 → 升级预警 → 模型写摘要与建议。

    关键：判定用 judge_week_items，升级用 escalate_risks（吃 week_snapshot 历史），
    模型完全不参与判断，只负责表达。
    """
    base_day = today or date.today()
    plan_row = cx.fetch_active_plan(tenant_id, student_id)
    if not plan_row:
        raise ValueError("该生还没有职业规划画像")
    rule = cx.fetch_active_rule(tenant_id, student_id)
    if not rule:
        raise ValueError("该生还没有规培规则，请先调用 match_rule")

    metrics = rule.get("metrics") or []
    report = dict(self_report or {})

    # 组装本周实际值：只认学生自报里明确给出的键，缺就是 None（引擎会判 unknown）
    items: list[dict[str, Any]] = []
    for m in metrics:
        name = str(m.get("指标") or "")
        items.append(
            {
                "指标": name,
                "达标线": m.get("达标线"),
                "本周实际": report.get(name),
                "方向": m.get("方向") or cr.DIR_UP,
                "容忍带": m.get("容忍带"),
            }
        )
    judge = cr.judge_week_items(items)

    history = cx.fetch_week_history(tenant_id, student_id, limit=4)
    escalation = cr.escalate_risks(history, judge["items"])

    # 模型只写摘要/建议/偏差说明
    brief = {
        "总体状态": judge["overall"],
        "指标对比": [
            {k: v for k, v in row.items() if k in ("指标", "达标线", "本周实际", "判定")}
            for row in judge["items"]
        ],
        "风险预警": escalation,
    }
    user = (
        "【系统已判定的结果（只能引用，不可更改）】\n"
        + json.dumps(brief, ensure_ascii=False, indent=2)
        + "\n\n请据此写周报摘要、下周建议与偏差说明。"
    )
    written = _extract_json(_ask(WEEK_SYSTEM, user, temperature=0.3)) or {}

    advice = [
        {"建议": str(x.get("建议") or "")[:80], "量化目标": str(x.get("量化目标") or "")[:40]}
        for x in (written.get("下周建议") or [])
        if isinstance(x, Mapping)
    ][:3]
    summary = str(written.get("周报摘要") or "")[:150]

    iso = base_day.isocalendar()
    snapshot_id = 0
    if persist:
        snapshot_id = cx.save_week_snapshot(
            tenant_id, student_id, int(rule.get("plan_id") or plan_row["id"]),
            iso_year=iso[0], iso_week=iso[1],
            judge=judge, escalation=escalation, notice_push=[],
            summary=summary, advice=advice, self_report=report,
        )

    return {
        "snapshot_id": snapshot_id,
        "iso_year": iso[0],
        "iso_week": iso[1],
        "overall": judge["overall"],
        "items": judge["items"],
        "missing": judge["missing"],
        "counts": judge["counts"],
        "escalation": escalation,
        "summary": summary,
        "advice": advice,
        "engine_version": cr.CAREER_ENGINE_VERSION,
    }


# ================================================================
# 节点 4 · 通知相关性过滤（截止在代码里先过滤，模型只见未截止）
# ================================================================
NOTICE_SYSTEM = """你是通知相关性过滤器。判断通知是否与该学生画像相关。

硬性约束（违反即视为失败）：
1. 只能对**给定列表内**的条目判定，不得新增条目；
2. 相关性只有三档：high（直接服务目标）/ medium（可作加分项）/ low（无关）；
3. 推送理由 ≤30 字，且必须能对应画像里的具体字段（目标类型/专业/软性指标）；
4. 只输出 JSON 数组，不要解释文字。

只输出 JSON 数组：
[{"标题": "原样抄", "相关性": "high/medium/low", "推送理由": "≤30 字"}]"""


def filter_notices(
    tenant_id: int,
    student_id: int,
    *,
    today: date | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """提示词四：先由引擎剔除已截止，再让模型判相关性。

    模型永远看不到已截止的通知——它对"今天"没有可靠概念，这一步必须由代码做。
    """
    base_day = today or date.today()
    plan_row = cx.fetch_active_plan(tenant_id, student_id)
    if not plan_row:
        raise ValueError("该生还没有职业规划画像")
    plan = plan_row.get("plan") or {}

    raw = cx.fetch_notices(tenant_id)
    # 引擎先过滤：只把 open 的送去给模型
    candidates = cr.open_notices(raw, base_day)
    if not candidates:
        return {"candidates": 0, "matched": 0, "items": [], "note": "没有未截止的通知"}

    allowed_ids = {c.get("id"): c for c in candidates}
    brief = {
        "目标类型": plan.get("目标类型"),
        "专业": (cx.fetch_student_facts(tenant_id, student_id) or {}).get("major"),
        "软性指标": plan.get("软性指标") or [],
        "通知列表": [
            {"标题": c.get("标题"), "发布单位": c.get("发布单位"),
             "截止时间": c.get("截止时间"), "摘要": (c.get("摘要") or "")[:200]}
            for c in candidates
        ],
    }
    user = json.dumps(brief, ensure_ascii=False, indent=2) + "\n\n请逐条判定相关性。"
    verdicts = _extract_json(_ask(NOTICE_SYSTEM, user, temperature=0.1))
    if not isinstance(verdicts, list):
        verdicts = []

    # 把模型的判定贴回真实记录（标题→id；对不上的丢弃，不让模型凭空造通知）
    by_title = {str(c.get("标题")): c for c in candidates}
    items: list[dict[str, Any]] = []
    for v in verdicts:
        if not isinstance(v, Mapping):
            continue
        title = str(v.get("标题") or "")
        src = by_title.get(title)
        if not src:
            continue
        rel = str(v.get("相关性") or "low").lower()
        items.append(
            {
                "id": src.get("id"),
                "标题": title,
                "推送理由": str(v.get("推送理由") or "")[:30],
                "相关性": rel,
                "截止时间": src.get("截止时间"),
                "status": "open",
            }
        )

    kept = [i for i in items if i["相关性"] in {"high", "medium"}]
    if persist:
        cx.save_notice_match(tenant_id, student_id, kept)

    return {
        "candidates": len(candidates),
        "matched": len(kept),
        "items": kept,
        "engine_version": cr.CAREER_ENGINE_VERSION,
    }


# ================================================================
# 节点 5 · 陪伴对话（系统记录过白名单，不自动重跑画像）
# ================================================================
COACH_SYSTEM = """你是该学生的学业陪伴教练。基于画像、周报与历史对话进行对话式陪伴。

角色约束：
1. 语气像靠谱的学长/学姐，不居高临下、不制造焦虑；
2. 每次回复建议不超过 3 条，必须引用具体数据或时间节点；
3. 鼓励要具体（指出哪项做得好），不空泛夸奖；
4. 纠偏时给替代方案，不只指出问题；
5. 不确定的信息不编造，明确说"需要你确认"；
6. **不得修改目标类型、目标描述、时间线**——这些只能由学生本人重新提交规划原文来改。

回复正文用对话语气。若本次对话产生了新的待办或状态变化，在末尾单独附一行：
【系统记录】{"新增待办": ["..."], "状态变化": [{"指标": "...", "变化": "..."}], "需更新画像": false}"""


def coach_chat(
    tenant_id: int,
    student_id: int,
    message: str,
    *,
    history: Sequence[Mapping[str, Any]] | None = None,
    persist: bool = False,
) -> dict[str, Any]:
    """提示词五：陪伴对话。

    模型末尾的【系统记录】必须过 validate_system_record 白名单：
    白名单外的键、试图改目标类型/时间线的，整条丢弃并记录原因。
    """
    if not message or not message.strip():
        raise ValueError("消息为空")

    plan_row = cx.fetch_active_plan(tenant_id, student_id)
    rule = cx.fetch_active_rule(tenant_id, student_id)

    ctx_brief = {
        "目标类型": (plan_row or {}).get("goal_type"),
        "目标描述": ((plan_row or {}).get("plan") or {}).get("目标描述"),
        "当前差距": ((plan_row or {}).get("plan") or {}).get("当前差距") or [],
    }
    user = (
        "【学生画像（只读）】\n" + json.dumps(ctx_brief, ensure_ascii=False, indent=2)
        + "\n\n【历史对话摘要】\n"
        + (json.dumps(list(history or [])[-5:], ensure_ascii=False) if history else "（无）")
        + f"\n\n【学生本次输入】\n{message.strip()}"
    )
    reply = _ask(COACH_SYSTEM, user, temperature=0.4)

    # 拆出【系统记录】
    record_raw = None
    body = reply
    marker = "【系统记录】"
    if marker in reply:
        body, tail = reply.split(marker, 1)
        body = body.strip()
        record_raw = _extract_json(tail)

    check = cr.validate_system_record(record_raw)
    accepted = check.get("accepted") if check.get("ok") else {}

    if persist and accepted.get("新增待办"):
        # 待办只落到 week_snapshot 的 advice 里（不新建表），由下次周报继承
        pass

    return {
        "reply": body,
        "system_record": {
            "accepted": accepted,
            "ok": bool(check.get("ok")),
            "reason": check.get("reason") or "",
            "rejected": check.get("rejected") or [],
        },
        "engine_version": cr.CAREER_ENGINE_VERSION,
    }
