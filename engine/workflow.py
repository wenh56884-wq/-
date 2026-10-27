# engine/workflow.py
# 职责：把「一串工具调用」变成可定义、可复跑、可审计的工作流。
# 依赖：无（工具实现由调用方注入，便于离线测试）
# 铁律：
#   1. 只允许白名单工具。工作流是配置，不是代码——绝不执行任意脚本/表达式。
#   2. 顺序执行、失败即停（除非该步显式声明 on_error=continue），不做「猜一个结果继续跑」。
#   3. 每步都留痕：工具名、入参摘要、耗时、状态、输出摘要；输出摘要不含编造内容。

from __future__ import annotations

import json
import time
from typing import Any, Callable, Mapping, Sequence

WORKFLOW_VERSION = "wf-v1"
MAX_STEPS = 8

# 白名单：名称 → 中文说明。新增能力必须显式登记，防止配置里塞进任意函数名。
ALLOWED_TOOLS: dict[str, str] = {
    "my_warning": "本人学业预警",
    "my_recommendations": "本人岗位推荐",
    "class_list": "班级目录",
    "class_overview": "班级概览",
    "warning_list": "班级预警名单",
    "career_gap": "班级能力差距",
    "student_profile": "学生画像",
    "kb_search": "知识库检索",
    "job_search": "岗位检索",
}


class WorkflowError(Exception):
    """工作流定义非法或执行中断。消息直接给用户看，必须是人话。"""


def validate(steps: Sequence[Mapping[str, Any]] | None) -> list[str]:
    """校验定义：返回问题清单（空 = 通过）。不做任何修复式改写。"""
    problems: list[str] = []
    if not steps:
        return ["工作流至少要有 1 个步骤"]
    if len(steps) > MAX_STEPS:
        problems.append(f"步骤不能超过 {MAX_STEPS} 个（当前 {len(steps)}）")
    seen: set[str] = set()
    for i, st in enumerate(steps, start=1):
        sid = str(st.get("id") or "").strip()
        tool = str(st.get("tool") or "").strip()
        if not sid:
            problems.append(f"第 {i} 步缺少 id")
        elif sid in seen:
            problems.append(f"步骤 id 重复：{sid}")
        seen.add(sid)
        if tool not in ALLOWED_TOOLS:
            problems.append(f"第 {i} 步工具「{tool}」不在白名单内（可用：{', '.join(ALLOWED_TOOLS)}）")
        if not isinstance(st.get("args", {}), dict):
            problems.append(f"第 {i} 步 args 必须是对象")
        if st.get("on_error") not in (None, "stop", "continue"):
            problems.append(f"第 {i} 步 on_error 只能是 stop 或 continue")
    return problems


def _digest(value: Any, limit: int = 300) -> Any:
    """输出摘要：能直出的直出，结构体转 JSON 截断。不新增任何字段。"""
    if value is None or isinstance(value, (str, int, float, bool)):
        return str(value)[:limit] if isinstance(value, str) else value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)[:limit]
    except Exception:
        return str(value)[:limit]


def _lookup(outputs: Mapping[str, Any], ref: str) -> Any:
    """解析 {{steps.<id>.<path>}}：只做字典/列表取值，不执行任何表达式。"""
    node: Any = {"steps": outputs}
    for part in str(ref).split("."):
        if isinstance(node, Mapping) and part in node:
            node = node[part]
        elif isinstance(node, (list, tuple)) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            raise WorkflowError(f"引用 {{${ref}}} 取不到值（前序步骤没有这个字段）")
    return node


def _resolve(value: Any, outputs: Mapping[str, Any]) -> Any:
    """递归替换参数里的 {{steps.x.y}}；字符串整体就是一个引用时保留原类型。"""
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("{{") and stripped.endswith("}}") and stripped.count("{{") == 1:
            return _lookup(outputs, stripped[2:-2].strip())
        return value
    if isinstance(value, Mapping):
        return {k: _resolve(v, outputs) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve(v, outputs) for v in value]
    return value


def run(steps: Sequence[Mapping[str, Any]],
        impl: Mapping[str, Callable[..., Any]],
        extra_args: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """顺序执行。impl 由调用方注入（ctx 已在闭包里绑好），便于离线测试。"""
    problems = validate(steps)
    if problems:
        raise WorkflowError("；".join(problems))

    outputs: dict[str, Any] = {}
    records: list[dict[str, Any]] = []
    started = time.time()
    status = "success"
    error: str | None = None

    for st in steps:
        sid, tool = str(st["id"]), str(st["tool"])
        t0 = time.time()
        try:
            fn = impl.get(tool)
            if fn is None:
                raise WorkflowError(f"工具 {tool} 没有实现")
            args = _resolve(dict(st.get("args") or {}), outputs)
            if extra_args:
                # 顶层入参作为默认值，步骤里的显式参数优先
                merged = {**extra_args, **args}
                args = merged
            out = fn(**args)
            outputs[sid] = out
            records.append({"id": sid, "tool": tool, "title": st.get("title") or ALLOWED_TOOLS.get(tool),
                            "status": "success", "elapsed_ms": int((time.time() - t0) * 1000),
                            "output_digest": _digest(out)})
        except Exception as exc:
            msg = str(exc) or type(exc).__name__
            records.append({"id": sid, "tool": tool, "title": st.get("title") or ALLOWED_TOOLS.get(tool),
                            "status": "failed", "elapsed_ms": int((time.time() - t0) * 1000),
                            "error": msg[:300]})
            if st.get("on_error") != "continue":
                status, error = "failed", f"第 {sid} 步失败：{msg[:200]}"
                break

    return {"status": status, "error": error, "steps": records, "outputs": outputs,
            "elapsed_ms": int((time.time() - started) * 1000),
            "engine_version": WORKFLOW_VERSION}


def run_default(steps: Sequence[Mapping[str, Any]], ctx) -> dict[str, Any]:
    """用项目内置工具执行（延迟导入，避免 agents ↔ engine 循环依赖）。"""
    from agents import tools

    impl: dict[str, Callable[..., Any]] = {
        "my_warning": lambda **kw: tools.my_warning(ctx, **kw),
        "my_recommendations": lambda **kw: tools.my_recommendations(ctx, **kw),
        "class_list": lambda **kw: tools.class_list(ctx),
        "class_overview": lambda **kw: tools.class_overview(ctx, **kw),
        "warning_list": lambda **kw: tools.warning_list(ctx, **kw),
        "career_gap": lambda **kw: tools.career_gap(ctx, **kw),
        "student_profile": lambda **kw: tools.student_profile(ctx, **kw),
        "kb_search": lambda **kw: tools.kb_search(ctx, **kw),
        "job_search": lambda **kw: tools.search_jobs(ctx, **kw),
    }
    return run(steps, impl)


def render_summary(result: Mapping[str, Any]) -> str:
    """把运行结果说成人话：逐步成功/失败 + 关键产出，不加解释性结论。"""
    lines = []
    for st in result.get("steps") or []:
        mark = "✅" if st.get("status") == "success" else "❌"
        title = st.get("title") or st.get("tool")
        if st.get("status") == "success":
            lines.append(f"{mark} {title}（{st.get('elapsed_ms')}ms）")
        else:
            lines.append(f"{mark} {title}：{st.get('error')}")
    if result.get("error"):
        lines.append(f"整体状态：失败 —— {result['error']}")
    else:
        lines.append(f"整体状态：成功，共 {len(result.get('steps') or [])} 步，"
                     f"耗时 {result.get('elapsed_ms')}ms")
    return "\n".join(lines)
