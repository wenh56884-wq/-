# agents/brain.py
# 职责：智能体「大脑」——规划 → 调工具 → 观察 → 反思补计划 → 汇总，带长期记忆召回。
# 依赖：agents.llm / agents.auto_plan（工具清单）/ agents.critic / engine.agent_memory。
# 铁律：工具结果是唯一数值真相源；最终答案必须过 Critic，不过就退回模板直引。

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from agents import auto_plan, critic, llm
from agents.tools import ToolContext, _check_ctx, _connect
from engine import agent_memory

BRAIN_VERSION = "brain-v2"
MAX_ROUNDS = 3
MAX_STEPS = 6
MAX_STEPS_PER_PLAN = 4
OBSERVATION_CHARS = 1600
# v2 执行参数（都可用环境变量覆盖，方便现场按机器性能调）
#   STEP_TIMEOUT：单步上限。某一工具卡住（外部检索/大班聚合）不该拖垮整轮
#   DEADLINE    ：整轮上限。到点不再发起新步骤，用已有结果出稿
#   PARALLEL    ：同批步骤并发度。同一批步骤的 args 在规划时就已固定、
#                 相互没有数据依赖，天然可以并发——这是 v2 最大的一笔时延优化
STEP_TIMEOUT = float(os.getenv("BRAIN_STEP_TIMEOUT", "25"))
DEADLINE = float(os.getenv("BRAIN_DEADLINE", "70"))
PARALLEL = max(1, int(os.getenv("BRAIN_PARALLEL", "3")))
# 反思开关：auto = 只在「有失败/有空洞」时补计划；always = 每轮都问；never = 不问
REFLECT_MODE = str(os.getenv("BRAIN_REFLECT", "auto")).strip().lower()
# 有副作用的工具不交给大脑自动执行：必须走页面/用户明确确认
_BLOCKED_TOOLS: frozenset[str] = frozenset({
    "save_warning_thresholds", "save_career_intent", "mark_notices_read",
})

# 工具参数的口语提示：只写英文参数名，模型容易把「重庆」只写进 purpose 不填 place
_ARG_HINTS: dict[str, str] = {
    "place": "工作地点，如 重庆",
    "dept": "部门名称，如 国家税务总局",
    "education": "学历，如 本科 / 硕士研究生",
    "degree": "学位，如 学士 / 硕士",
    "political": "政治面貌，如 中共党员 / 不限",
    "keyword": "关键词（职位/部门/专业/职位代码）",
    "exam_type": "考试类型：civil=考公 / institution=考编 / postgraduate=考研",
    "only_open": "是否只看在招（true/false）",
    "query": "检索词",
    "family": "行业族，如 it_software",
    "qtype": "题型，如 project",
    "limit": "返回条数",
    "goal": "方向：考公 / 考研 / 考编 / 就业",
    "term": "学期，如 2025-2026-2",
    "class_name": "班级，如 AI2301",
    "student_no": "学号（教师端查具体学生时才用）",
    "major": "专业名称",
    "skill": "技能名称",
    "job_id": "岗位编号",
    "name": "工作流名称",
    "track": "赛道：就业 / 升学",
    "direction": "方向",
    "top_k": "返回条数",
}

_schema_lock = threading.Lock()
_schema_ready = False


@dataclass
class ExecutedStep:
    """一次工具调用的完整记录（结果只用于汇总与 Critic 白名单）。"""

    tool: str
    args: dict[str, Any]
    purpose: str
    ok: bool
    result: dict[str, Any] = field(default_factory=dict)
    observation: str = ""
    elapsed_ms: int = 0
    error: str = ""


def _brain_enabled() -> str:
    return str(os.getenv("AGENT_BRAIN", "auto")).strip().lower()


def should_run(query: str, history: Sequence[Mapping[str, str]] | None = None) -> bool:
    """是否走大脑：auto 只接多意图/任务型问法；1 强制；0 关闭。"""
    mode = _brain_enabled()
    if mode in ("0", "false", "off", "no"):
        return False
    text = str(query or "")
    if not text.strip():
        return False
    if mode in ("1", "true", "on", "yes"):
        return True
    markers = (
        "并且", "同时", "顺便", "然后", "再帮", "以及", "分别", "对比", "比较",
        "规划一下", "安排一下", "分步", "分几步", "多步", "自主", "先查", "再查",
        "综合分析", "帮我分析", "一起查", "顺便看看",
    )
    if any(marker in text for marker in markers):
        return True
    # 上一轮是任务型追问（「那接下来呢」「然后帮我准备」）也接住
    last_user = ""
    for turn in reversed(list(history or [])):
        if str(turn.get("role") or "") == "user":
            last_user = str(turn.get("text") or "")
            break
    return bool(last_user) and any(word in text for word in ("接下来", "然后", "再", "还有"))


def _catalog(ctx: ToolContext) -> list[dict[str, str]]:
    """可选工具清单（过滤有副作用的工具）；描述取第一行，避免提示词过长。"""
    out: list[dict[str, str]] = []
    for tool in auto_plan._tools_for(ctx.actor_type):  # noqa: SLF001 - 复用统一工具壳
        if tool.name in _BLOCKED_TOOLS:
            continue
        desc = (tool.description or "").strip().splitlines()
        args = getattr(tool, "args", {}) or {}
        params = ", ".join(f"{key}={_ARG_HINTS.get(key, key)}" for key in args)
        out.append({
            "name": tool.name,
            "description": (desc[0] if desc else "")[:160],
            "params": params,
        })
    return out


def _format_catalog(catalog: Sequence[Mapping[str, str]]) -> str:
    lines: list[str] = []
    for item in catalog:
        params = f"（参数：{item['params']}）" if item.get("params") else "（无参数）"
        lines.append(f"- {item['name']}{params}: {item['description']}")
    return "\n".join(lines)


def _format_history(history: Sequence[Mapping[str, str]] | None) -> str:
    lines: list[str] = []
    for turn in list(history or [])[-6:]:
        text = str(turn.get("text") or "").strip()
        if text:
            role = "用户" if str(turn.get("role") or "") == "user" else "助手"
            lines.append(f"{role}：{text[:200]}")
    return "\n".join(lines)


def _json_object(raw: str | None) -> dict[str, Any] | None:
    """从模型输出里抠 JSON 对象；抠不到/解析失败返回 None（交给上层回退）。"""
    if not raw:
        return None
    match = re.search(r"\{.*\}", raw, re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _json_array(raw: str | None) -> list[Any] | None:
    if not raw:
        return None
    match = re.search(r"\[.*\]", raw, re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    return data if isinstance(data, list) else None


def _signature(step: Mapping[str, Any] | ExecutedStep) -> str:
    """工具名 + 参数签名：用于跨轮去重，避免反复查同一次数据。"""
    if isinstance(step, ExecutedStep):
        tool, args = step.tool, step.args
    else:
        tool, args = step.get("tool") or "", step.get("args") or {}
    return (str(tool) + "|"
            + json.dumps(args, sort_keys=True, ensure_ascii=False, default=str))


def _valid_steps(raw: Any, allowed: set[str],
                 limit: int = MAX_STEPS_PER_PLAN) -> list[dict[str, Any]]:
    """校验模型给出的步骤：工具必须在白名单、参数必须是对象、目的可读。"""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw[:limit]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("tool") or "").strip()
        if name not in allowed or name in _BLOCKED_TOOLS:
            continue
        args = item.get("args")
        if not isinstance(args, dict):
            args = {}
        signature = _signature({"tool": name, "args": args})
        if signature in seen:
            continue
        seen.add(signature)
        out.append({
            "tool": name,
            "args": args,
            "purpose": str(item.get("purpose") or "")[:80],
        })
    return out


_PLAN_SYSTEM = (
    "你是「启航」自主执行智能体的规划器，只输出 JSON，不输出任何解释。\n"
    "任务：判断回答用户问题需要调用哪些只读工具，并拆成不超过 4 步。\n"
    "规则：\n"
    "1. 只列真正需要的工具；能一步查清就不要拆。\n"
    "2. args 必须是 JSON 对象，不需要参数就写 {}。\n"
    "3. 工具名只能从清单里选，禁止编造。\n"
    "4. 学生端不接受任何学号/学生编号参数；教师端查具体学生时才用 student_no，"
    "且必须从提问里拿到，拿不到就改用班级级工具，禁止编造学号。\n"
    "5. 问题无需取数（闲聊/问能力）时返回空 steps。\n"
    "6. 禁止用常识或记忆补数据；查不到就让工具返回空结果。\n"
    "7. 用户明确提到地点/学历/政治面貌/部门/专业时，必须填进对应参数，"
    "不能只写在 purpose 里，否则等于没过滤。\n"
    "输出格式：{\"thought\":\"一句话\",\"steps\":[{\"tool\":\"...\",\"args\":{},"
    "\"purpose\":\"这步要拿到什么\"}]}"
)

_REFLECT_SYSTEM = (
    "你是「启航」智能体的执行观察器，只输出 JSON。\n"
    "根据用户问题、已完成步骤与观察，判断信息是否足够。\n"
    "只输出两种格式之一：\n"
    "{\"done\":true,\"thought\":\"一句话\"}\n"
    "{\"done\":false,\"thought\":\"一句话\",\"steps\":[{\"tool\":\"...\","
    "\"args\":{},\"purpose\":\"...\"}]}\n"
    "新步骤不超过 3 步；不要重复已经成功执行过的相同工具+参数；"
    "同一个工具已经成功返回结果时，除非上次结果为空或这次参数明显不同，否则不要再调。"
)

_DRAFT_SYSTEM = (
    "你是「启航」智能助手。根据给定的工具事实回答用户问题。\n"
    "铁律：\n"
    "1. 只能使用事实里的数字，原样照抄；禁止换算、四舍五入、编造。\n"
    "2. 汇总数量必须用事实里的总数（position_total / notice_total / total_headcount），"
    "不能把示例条数写成总数。\n"
    "3. 不要出现「工具」「步骤」「系统」这类词；不要用 Markdown 标记（**、-、#、```）。\n"
    "4. 先给结论，再给 1~2 条依据；事实不足就直说没查到。\n"
    "5. 中文口语，200 字以内；但如果事实是逐条列表（如国考职位明细），"
    "必须像清单那样按条列出具体条目（部门/职位/人数/学历/地点等照抄），"
    "此时篇幅不受 200 字限制，一条一行、不再压缩。"
)


def _count_mismatches(draft: str, executed: Sequence[ExecutedStep]) -> list[str]:
    """汇总数语义校验：把「示例 3 条」写成「共 3 个职位」是最危险的数字错位。"""
    issues: list[str] = []
    for step in executed:
        if not step.ok:
            continue
        total = step.result.get("position_total")
        if isinstance(total, int) and total > 0:
            if re.search(r"(?:总数|共|合计)[^。；\n]{0,10}(?:没|未|没有)查(?:到|询)", draft) \
                    or "没查到总数" in draft or "总数没查到" in draft:
                issues.append(f"工具已经返回职位总数 {total}，不能说「没查到总数」")
            if str(total) not in draft:
                issues.append(f"必须写出职位总数 {total}（position_total）")
            for match in re.finditer(
                    r"(?:共|总共|合计|查到|匹配|有|只看到|只查到|仅有|只有|仅)\s*(\d+)\s*"
                    r"(?:(?:个|条)\s*(?:职位|岗位)?|职位|岗位)", draft):
                if int(match.group(1)) != total:
                    issues.append(
                        f"职位总数应写 {total}（position_total），草稿写成了 {match.group(1)}")
        notices = step.result.get("notice_total")
        if isinstance(notices, int):
            for match in re.finditer(
                    r"(?:共|总共|合计|查到|匹配|有)\s*(\d+)\s*条\s*公告", draft):
                if int(match.group(1)) != notices:
                    issues.append(
                        f"公告总数应写 {notices}（notice_total），草稿写成了 {match.group(1)}")
    return issues


def _plain(text: str) -> str:
    """去掉模型偶发输出的 Markdown 标记：前端按纯文本渲染，** 会原样露出来。"""
    value = re.sub(r"\*\*(.+?)\*\*", r"\1", str(text or ""))
    value = re.sub(r"^\s*[-*]\s+", "", value, flags=re.M)
    return value.strip()

_EXTRACT_SYSTEM = (
    "你负责从对话里提取值得长期记住的用户信息，只输出 JSON 数组。\n"
    "每条格式：{\"kind\":\"fact|preference|goal|constraint\",\"content\":\"...\","
    "\"importance\":1-5}\n"
    "规则：\n"
    "1. 只提取用户明确表达、跨会话仍然有效的信息（专业、方向、偏好、目标、限制）。\n"
    "2. 不提取具体分数、排名、人数、课表等易变数值；content 里不要出现数字。\n"
    "3. 不提取助手的推测；没有可记的就输出 []。\n"
    "4. content 用第三人称短句，20~80 字。"
)


def _plan(ctx: ToolContext, query: str, term: str | None,
          history: Sequence[Mapping[str, str]] | None,
          memories: Sequence[Mapping[str, Any]],
          catalog: Sequence[Mapping[str, str]]) -> list[dict[str, Any]] | None:
    """让模型拆任务；返回步骤列表，模型不可用/无步骤返回 None。"""
    who = "教师" if ctx.actor_type == "teacher" else "学生"
    user = "\n".join([
        f"用户身份：{who}",
        f"当前学期：{term or '未指定'}",
        agent_memory.format_for_prompt(list(memories)),
        "【最近对话】\n" + (_format_history(history) or "无"),
        "【可用工具】\n" + _format_catalog(catalog),
        f"【用户问题】{query}",
    ])
    raw = llm.generate_reply(ctx.actor_type, system_prompt=_PLAN_SYSTEM,
                             user_prompt=user, tag="brain_plan")
    data = _json_object(raw)
    if not data:
        return None
    steps = _valid_steps(data.get("steps"), {item["name"] for item in catalog})
    return steps or None


def _reflect(ctx: ToolContext, query: str, executed: Sequence[ExecutedStep],
             catalog: Sequence[Mapping[str, str]]) -> list[dict[str, Any]] | None:
    """观察已有结果，决定是否补步骤；模型失败/已足够返回 None。"""
    known = "\n".join(
        f"- {step.tool}({json.dumps(step.args, ensure_ascii=False)}) -> "
        f"{'成功' if step.ok else '失败'}：{step.observation[:500]}"
        for step in executed
    )
    user = "\n".join([
        f"【用户问题】{query}",
        "【已完成步骤与观察】\n" + known,
        "【可用工具】\n" + _format_catalog(catalog),
    ])
    raw = llm.generate_reply(ctx.actor_type, system_prompt=_REFLECT_SYSTEM,
                             user_prompt=user, tag="brain_reflect")
    data = _json_object(raw)
    if not data or data.get("done"):
        return None
    done_signatures = {_signature(step) for step in executed}
    fresh = [step for step in _valid_steps(
        data.get("steps"), {item["name"] for item in catalog}, limit=3)
        if _signature(step) not in done_signatures]
    return fresh or None


def _observe(result: Mapping[str, Any]) -> str:
    try:
        text = json.dumps(dict(result), ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(result)
    return text[:OBSERVATION_CHARS] + ("…" if len(text) > OBSERVATION_CHARS else "")


def _execute(ctx: ToolContext, step: Mapping[str, Any]) -> ExecutedStep:
    """执行一步工具；异常转成失败观察，不中断整轮。"""
    from agents import graph  # 延迟导入：graph 在 run_chat 里反过来调用 brain

    tool = str(step.get("tool") or "")
    args = dict(step.get("args") or {})
    purpose = str(step.get("purpose") or "")
    started = time.perf_counter()
    try:
        result = graph._dispatch(ctx, tool, args)  # noqa: SLF001 - 统一工具分发
        if not isinstance(result, Mapping):
            result = {"result": result}
        return ExecutedStep(tool=tool, args=args, purpose=purpose, ok=True,
                            result=dict(result), observation=_observe(result),
                            elapsed_ms=int((time.perf_counter() - started) * 1000))
    except Exception as exc:  # 工具层异常（参数错/越权/断库）都只影响这一步
        observation = f"{type(exc).__name__}: {exc}"[:300]
        return ExecutedStep(tool=tool, args=args, purpose=purpose, ok=False,
                            result={"error": observation}, observation=observation,
                            elapsed_ms=int((time.perf_counter() - started) * 1000),
                            error=type(exc).__name__)


def _skip_step(step: Mapping[str, Any], reason: str) -> ExecutedStep:
    return ExecutedStep(tool=str(step.get("tool") or ""),
                        args=dict(step.get("args") or {}),
                        purpose=str(step.get("purpose") or ""),
                        ok=False, result={"error": reason}, observation=reason,
                        error=reason)


def _run_steps(ctx: ToolContext, steps: Sequence[Mapping[str, Any]], on_event: Any,
               deadline_at: float) -> list[ExecutedStep]:
    """执行一批步骤，结果**按计划顺序**返回。

    同一批步骤之间没有数据依赖（args 在规划阶段就固定，不能引用前一步的返回值），
    所以并发是安全的；串行只是让「3 个工具 × 平均 8 秒」变成 24 秒的排队。
    v2 并发后同样的任务墙钟时间接近最慢的那一步。
    """
    if not steps:
        return []
    results: list[ExecutedStep | None] = [None] * len(steps)
    for step in steps:
        _emit(on_event, stage="tool", tool=str(step.get("tool") or ""),
              text=f"正在调用 {step.get('tool')}…")

    if len(steps) == 1 or PARALLEL <= 1:
        for index, step in enumerate(steps):
            if time.monotonic() >= deadline_at:
                results[index] = _skip_step(step, "整轮时间已到，这步没有执行")
                continue
            results[index] = _execute(ctx, step)
    else:
        from concurrent.futures import ThreadPoolExecutor, wait

        with ThreadPoolExecutor(max_workers=min(PARALLEL, len(steps)),
                                thread_name_prefix="brain-step") as pool:
            futures = {}
            for index, step in enumerate(steps):
                if time.monotonic() >= deadline_at:
                    results[index] = _skip_step(step, "整轮时间已到，这步没有执行")
                    continue
                futures[pool.submit(_execute, ctx, step)] = index
            remaining = max(1.0, deadline_at - time.monotonic())
            done, not_done = wait(futures, timeout=min(STEP_TIMEOUT, remaining))
            for future in done:
                index = futures[future]
                try:
                    results[index] = future.result()
                except Exception as exc:  # 线程内异常不能吞掉整轮
                    results[index] = _skip_step(steps[index], f"{type(exc).__name__}: {exc}")
            for future in not_done:
                future.cancel()
                index = futures[future]
                results[index] = _skip_step(
                    steps[index],
                    f"超过单步上限 {STEP_TIMEOUT:.0f}s 还没返回，已放弃这一步")

    for step, outcome in zip(steps, results):
        if outcome is not None:
            _emit(on_event, stage="observe", tool=outcome.tool, ok=outcome.ok,
                  text=(f"{outcome.tool} 返回结果（{outcome.elapsed_ms} ms）" if outcome.ok
                        else f"{outcome.tool} 未成功，继续下一步"))
    return [item if item is not None else _skip_step(steps[i], "未执行")
            for i, item in enumerate(results)]


def _is_empty_result(result: Mapping[str, Any]) -> bool:
    """结果是否「看起来什么都没拿到」——决定要不要补一轮反思。"""
    if not result:
        return True
    if result.get("error"):
        return True
    for key in ("items", "rows", "list", "data", "positions", "notices", "citations"):
        value = result.get(key)
        if isinstance(value, (list, tuple, dict)) and not value:
            return True
    return False


def _needs_reflect(executed: Sequence[ExecutedStep]) -> bool:
    """是否需要补计划。

    旧版每轮都问一次模型「够不够」，一个问题白烧 2~4 秒。
    auto 模式只在「有步骤失败」或「某步拿到了空结果」时才问——
    这两类才是真的可能缺信息；全都成功且有内容时，再问也只会得到 done。
    """
    if REFLECT_MODE in ("always", "1", "true", "on", "yes"):
        return True
    if REFLECT_MODE in ("never", "0", "false", "off", "no"):
        return False
    if not executed:
        return True
    if any(not step.ok for step in executed):
        return True
    return any(_is_empty_result(step.result) for step in executed)


def _template_facts(executed: Sequence[ExecutedStep]) -> str:
    from agents import graph  # 延迟导入

    lines: list[str] = []
    for index, step in enumerate([s for s in executed if s.ok], start=1):
        try:
            draft = graph._template_draft(step.result).strip()  # noqa: SLF001
        except Exception:
            draft = step.observation       # 单个结果形状异常不拖垮整轮汇总
        if draft:
            lines.append(f"【事实 {index}｜{step.tool}】{draft}")
    return "\n".join(lines)


def _synthesize(ctx: ToolContext, query: str,
                executed: Sequence[ExecutedStep]) -> tuple[str, bool, dict[str, Any], int]:
    """汇总：优先模型润色 + Critic 回查；不过就退回模板直引。"""
    ok_steps = [step for step in executed if step.ok]
    facts = _template_facts(executed)
    ground = {"steps": [step.result for step in ok_steps]}
    attempts = 0
    llm_failed = False
    if facts:
        user = f"【用户问题】{query}\n【工具事实】\n{facts}"
        # 大脑一次任务已经调了多个工具，草稿=初稿+至多一次重写；再多会拖到一分钟以上。
        # （旧写法 min(MAX_RETRY,1)+2 会给 3 次尝试，比注释承诺多跑一轮。）
        for attempt in (1, 2):
            attempts = attempt
            draft = llm.generate_reply(ctx.actor_type, system_prompt=_DRAFT_SYSTEM,
                                       user_prompt=user, tag="brain_draft")
            if not draft:
                llm_failed = True   # 模型没出稿也属于降级：最终走模板直引
                break
            verdict = critic.verify(draft, ground)
            semantic = _count_mismatches(draft, ok_steps)
            if verdict.passed and not semantic:
                return _plain(draft), False, verdict.to_dict(), attempts
            llm_failed = True
            feedback = verdict.feedback()
            if semantic:
                feedback = "\n".join(["草稿存在以下问题，必须逐条改正："]
                                     + [f"- {item}" for item in semantic])
            user += "\n【上一稿未通过数值回查，请修正】\n" + feedback
    if facts:
        verdict = critic.verify(facts, ground)
        return facts, llm_failed, verdict.to_dict(), attempts
    return "没有查到可用的数据。可以把问题说得更具体一些，我再查。", False, {}, attempts


_REMEMBER_RE = re.compile(r"^(?:请|帮我)?(?:记住|记一下|记得)[：:，,\s]*(.{2,200})$")


def _remember_command(conn, ctx: ToolContext, query: str,
                      session_id: int | None) -> dict[str, Any] | None:
    """用户明确说「记住…」：确定性写入，不经过模型。"""
    match = _REMEMBER_RE.match(str(query or "").strip())
    if not match:
        return None
    content = match.group(1).strip(" 。")
    if len(content) < 2:
        return None
    try:
        memory_id, created = agent_memory.add(conn, ctx, content, kind="fact",
                                              importance=4, session_id=session_id)
        conn.commit()
    except ValueError:
        return None
    return {
        "answer": f"已记住：{content}。以后对话我会把这条作为背景。",
        "trace_id": uuid.uuid4().hex[:12],
        "term": None,
        "degraded": False,
        "verdict": {},
        "attempts": 0,
        "tool_name": "memory",
        "citations": [],
        "suggested_followups": ["我刚才让你记住了什么", "把这些记忆列出来"],
        "planner": "brain",
        "agent_mode": "brain",
        "steps": [{"index": 1, "tool": "memory.add", "purpose": "写入长期记忆",
                   "ok": True, "args": {"kind": "fact"}, "observation": ""}],
        "memory_used": [],
        "memory_saved": [{"id": memory_id, "created": created, "content": content}],
    }


def _personal_cue(query: str) -> bool:
    return any(word in str(query or "") for word in
               ("我", "我的", "我想", "我打算", "我是", "偏好", "喜欢", "目标", "希望"))


def _maybe_extract_memories(conn, ctx: ToolContext, query: str, answer: str,
                            session_id: int | None) -> list[dict[str, Any]]:
    """从本轮对话提取长期记忆；失败/关闭时静默跳过，不影响回答。"""
    if str(os.getenv("AGENT_MEMORY_EXTRACT", "1")).strip().lower() in ("0", "false", "off", "no"):
        return []
    if not _personal_cue(query):
        return []
    user = f"用户问题：{query}\n助手回答：{answer[:800]}"
    raw = llm.generate_reply(ctx.actor_type, system_prompt=_EXTRACT_SYSTEM,
                             user_prompt=user, tag="brain_memory")
    items = _json_array(raw)
    if not items:
        return []
    saved: list[dict[str, Any]] = []
    for item in items[:5]:
        if not isinstance(item, dict):
            continue
        content = re.sub(r"\s+", " ", str(item.get("content") or "")).strip()
        if not (4 <= len(content) <= 200) or re.search(r"\d", content):
            continue                    # 带数字的记忆不存：避免日后被当答案数值直引
        kind = str(item.get("kind") or "fact")
        try:
            importance = max(1, min(int(item.get("importance") or 3), 5))
            memory_id, created = agent_memory.add(
                conn, ctx, content, kind=kind, importance=importance,
                session_id=session_id)
        except (ValueError, TypeError):
            continue
        saved.append({"id": memory_id, "created": created, "content": content})
    if saved:
        conn.commit()
    return saved


_memory_threads: list[threading.Thread] = []


def _extract_memories_async(ctx: ToolContext, query: str, answer: str,
                            session_id: int | None) -> None:
    """后台提取长期记忆：星火单次提取可能几十秒，不能卡住对话返回。"""
    if str(os.getenv("AGENT_MEMORY_EXTRACT", "1")).strip().lower() in ("0", "false", "off", "no"):
        return
    if not _personal_cue(query):
        return

    def worker() -> None:
        conn = None
        try:
            conn = _connect()
            _ensure_memory_schema(conn)
            saved = _maybe_extract_memories(conn, ctx, query, answer, session_id)
            conn.commit()
            if saved:
                print(f"[brain] 长期记忆已保存 {len(saved)} 条", file=sys.stderr)
        except Exception as exc:  # 后台失败只记日志，不影响已返回的回答
            print(f"[brain] 记忆提取失败：{exc}", file=sys.stderr)
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    # 保留线程引用，避免解释器提前回收；顺手清掉已结束的
    _memory_threads[:] = [item for item in _memory_threads if item.is_alive()]
    thread = threading.Thread(target=worker, daemon=True, name="brain-memory")
    _memory_threads.append(thread)
    thread.start()


def _ensure_memory_schema(conn) -> None:
    """每个进程只建一次记忆表；失败不阻塞对话。"""
    global _schema_ready
    if _schema_ready:
        return
    with _schema_lock:
        if _schema_ready:
            return
        try:
            agent_memory.ensure_schema(conn)
            conn.commit()
            _schema_ready = True
        except Exception as exc:  # 记忆不可用就退化：本轮照常回答
            print(f"[brain] 记忆表不可用：{exc}", file=sys.stderr)


def _emit(on_event: Any, **payload: Any) -> None:
    """把执行进度推给流式接口；回调本身出错不能影响任务执行。"""
    if on_event is None:
        return
    try:
        on_event(payload)
    except Exception:
        pass


def _last_user_text(history: Sequence[Mapping[str, str]] | None) -> str:
    for turn in reversed(list(history or [])):
        if str(turn.get("role") or "") == "user":
            return str(turn.get("text") or "").strip()
    return ""


def _recall_memories(conn, ctx: ToolContext, query: str,
                     history: Sequence[Mapping[str, str]] | None) -> list[dict[str, Any]]:
    """召回长期记忆；本轮召回不足时用上一轮用户原话再捞一次。

    追问型对话（「那考公呢」「这个专业呢」）本身几乎没有实词，
    只拿本轮问句去检索必然空手而归，而上下文恰恰在上一轮里。
    """
    hits = agent_memory.search(conn, ctx, query, top_k=4)
    if len(hits) >= 2:
        return hits
    previous = _last_user_text(history)
    if not previous or previous == str(query or "").strip():
        return hits
    merged = {int(hit["id"]): hit for hit in hits}
    for hit in agent_memory.search(conn, ctx, previous, top_k=2):
        merged.setdefault(int(hit["id"]), hit)
    return sorted(merged.values(), key=lambda item: -float(item.get("score") or 0))[:4]


def run_brain(ctx: ToolContext, query: str, term: str | None = None,
              history: Sequence[Mapping[str, str]] | None = None,
              session_id: int | None = None,
              on_event: Any = None) -> dict[str, Any] | None:
    """跑一轮自主任务；返回 None 表示模型不可用/无可执行计划，调用方回退旧管线。"""
    ctx = _check_ctx(ctx)
    started = time.perf_counter()
    trace_id = uuid.uuid4().hex[:12]
    catalog = _catalog(ctx)
    if not catalog:
        return None

    conn = None
    memories: list[dict[str, Any]] = []
    try:
        try:
            conn = _connect()
            _ensure_memory_schema(conn)
            try:
                memories = _recall_memories(conn, ctx, query, history)
                conn.commit()
            except Exception as exc:
                print(f"[brain] 记忆召回失败：{exc}", file=sys.stderr)
            remember = _remember_command(conn, ctx, query, session_id)
            if remember:
                remember["term"] = term
                return remember
            # 记忆召回完就释放连接：后面的 LLM 规划/反思可能几十秒，不占着 MySQL 连接
            conn.close()
            conn = None
        except Exception as exc:  # 连库失败：无记忆也能继续
            print(f"[brain] 记忆库连接失败：{exc}", file=sys.stderr)
            conn = None

        try:
            _emit(on_event, stage="plan", text="正在制定执行计划…")
            planned = _plan(ctx, query, term, history, memories, catalog)
            if not planned:
                return None
            _emit(on_event, stage="plan_done", steps=len(planned),
                  text=f"执行计划已生成（{len(planned)} 步）")
            executed: list[ExecutedStep] = []
            pending = planned
            rounds = 0
            deadline_at = started + DEADLINE
            while pending and len(executed) < MAX_STEPS and rounds < MAX_ROUNDS:
                rounds += 1
                batch = [step for step in pending
                         if not any(_signature(step) == _signature(done) for done in executed)]
                batch = batch[:MAX_STEPS - len(executed)]
                if not batch:
                    break
                executed.extend(_run_steps(ctx, batch, on_event, deadline_at))
                # 到这里三种情况都不该再问模型：时间到 / 轮次用完 / 信息已经够
                if (time.monotonic() >= deadline_at or rounds >= MAX_ROUNDS
                        or not _needs_reflect(executed)):
                    break
                _emit(on_event, stage="reflect", text="正在检查结果，判断是否补查…")
                pending = _reflect(ctx, query, executed, catalog) or []
            if not any(step.ok for step in executed):
                return None
            _emit(on_event, stage="draft", text="正在汇总并核对数值…")
            answer, degraded, verdict, attempts = _synthesize(ctx, query, executed)
        except Exception as exc:
            import traceback

            print(f"[brain] 执行失败：{exc}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            return None

        citations: list[dict[str, Any]] = []
        seen: set[str] = set()
        for step in executed:
            for cite in (step.result.get("citations") or []):
                key = json.dumps(cite, ensure_ascii=False, sort_keys=True, default=str)
                if key not in seen:
                    seen.add(key)
                    citations.append(dict(cite))

        # 记忆提取很慢（星火单次可到几十秒），放后台线程，不阻塞本轮回答
        _extract_memories_async(ctx, query, answer, session_id)
        saved: list[dict[str, Any]] = []

        tool_names = {step.tool for step in executed}
        return {
            "answer": answer,
            "trace_id": trace_id,
            "term": term,
            "degraded": degraded,
            "verdict": verdict,
            "attempts": attempts,
            "tool_name": next(iter(tool_names)) if len(tool_names) == 1 else "brain",
            "citations": citations,
            "suggested_followups": ["换个说法再问一次", "继续查另一个维度",
                                    "把结果按优先级排一下"],
            "planner": "brain",
            "agent_mode": "brain",
            "steps": [
                {"index": index, "tool": step.tool, "purpose": step.purpose,
                 "ok": step.ok, "args": step.args,
                 "elapsed_ms": step.elapsed_ms,
                 "observation": step.observation[:300]}
                for index, step in enumerate(executed, start=1)
            ],
            "memory_used": [item["id"] for item in memories],
            "memory_saved": saved,
            "memory_extract": "async",
            "brain_version": BRAIN_VERSION,
            "rounds": rounds,
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
        }
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def describe() -> dict[str, Any]:
    """能力自检用：告诉前端大脑开启了哪些能力。"""
    return {
        "brain_version": BRAIN_VERSION,
        "mode": _brain_enabled(),
        "max_rounds": MAX_ROUNDS,
        "max_steps": MAX_STEPS,
        "step_timeout_s": STEP_TIMEOUT,
        "deadline_s": DEADLINE,
        "parallel": PARALLEL,
        "reflect": REFLECT_MODE,
        "memory": agent_memory.MEMORY_VERSION,
        "memory_vector_dim": agent_memory.VECTOR_DIM,
        "blocked_tools": sorted(_BLOCKED_TOOLS),
    }
