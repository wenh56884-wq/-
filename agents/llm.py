# agents/llm.py
# 职责：DeepSeek LLM 客户端封装，供所有 Agent 节点复用
# 依赖：langchain_openai.ChatOpenAI / app.config.get_settings
# 说明：api_key 与 model 只从 .env 读取，禁止硬编码

from __future__ import annotations

import time
from collections.abc import Callable
from functools import lru_cache

from langchain_openai import ChatOpenAI

from app.config import get_settings

# 所有 Agent 共享的系统级铁律提示词
SYSTEM_RULES: str = (
    "禁止输出任何具体数值；"
    "所有数值必须原样引用工具返回结果；"
    "不确定就调用工具，不要猜测"
)

# 固定 base_url，不允许从外部覆盖（防止被误指向其他端点）
_BASE_URL: str = "https://api.deepseek.com"


def _build_llm(temperature: float) -> ChatOpenAI:
    """根据 temperature 构建 ChatOpenAI 实例（内部函数）。"""
    settings = get_settings()

    api_key = settings.deepseek_api_key.strip()
    if not api_key or api_key == "sk-REPLACE_ME":
        raise RuntimeError(
            "DEEPSEEK_API_KEY 未配置：请在项目根目录 .env 文件中设置有效的 DEEPSEEK_API_KEY。"
        )

    model = settings.deepseek_model.strip() or "deepseek-chat"

    return ChatOpenAI(
        base_url=_BASE_URL,
        model=model,
        api_key=api_key,
        temperature=temperature,
        timeout=60,
        max_retries=2,
    )


@lru_cache(maxsize=1)
def get_teacher_llm() -> ChatOpenAI:
    """教师端 LLM 单例（temperature=0.2，偏严谨）。"""
    return _build_llm(temperature=0.2)


@lru_cache(maxsize=1)
def get_student_llm() -> ChatOpenAI:
    """学生端 LLM 单例（temperature=0.3，略活泼）。"""
    return _build_llm(temperature=0.3)


def _messages(system_prompt: str, user_prompt: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _invoke(actor_type: str, system_prompt: str, user_prompt: str, *, tag: str) -> str:
    """按角色取对应 LLM 实例发一次对话；返回纯文本正文。"""
    from app.audit import audit_event

    llm = get_teacher_llm() if actor_type == "teacher" else get_student_llm()
    started = time.perf_counter()
    try:
        resp = llm.invoke(_messages(system_prompt, user_prompt))
    except Exception as exc:  # Key 无效/限流/超时都归到这里，由调用方兜底
        audit_event(actor_type=actor_type, actor_id=0, action=f"llm.{tag}.failed",
                    target="", detail={"error": str(exc)[:200]})
        raise
    content = resp.content if isinstance(resp.content, str) else str(resp.content)
    audit_event(actor_type=actor_type, actor_id=0, action=f"llm.{tag}", target="",
                detail={"chars": len(content), "cost_ms": round((time.perf_counter() - started) * 1000)})
    return str(content).strip()


def _invoke_stream(actor_type: str, system_prompt: str, user_prompt: str, *, tag: str,
                   on_token: Callable[[str], None]) -> str:
    """流式调用：每收到一块就回调 on_token，最后返回完整正文（仍由 Critic 核验后定稿）。"""
    from app.audit import audit_event

    llm = get_teacher_llm() if actor_type == "teacher" else get_student_llm()
    started = time.perf_counter()
    parts: list[str] = []
    try:
        for chunk in llm.stream(_messages(system_prompt, user_prompt)):
            text = chunk.content if isinstance(chunk.content, str) else str(chunk.content)
            if not text:
                continue
            parts.append(text)
            on_token(text)
    except Exception as exc:  # 中途断流同样归到这里，草稿退回模板直引
        audit_event(actor_type=actor_type, actor_id=0, action=f"llm.{tag}.failed",
                    target="", detail={"error": str(exc)[:200], "partial_chars": len("".join(parts))})
        raise
    content = "".join(parts)
    audit_event(actor_type=actor_type, actor_id=0, action=f"llm.{tag}", target="",
                detail={"chars": len(content), "stream": True,
                        "cost_ms": round((time.perf_counter() - started) * 1000)})
    return str(content).strip()


def generate_reply(actor_type: str, *, system_prompt: str, user_prompt: str,
                   tag: str = "draft",
                   on_token: Callable[[str], None] | None = None) -> str | None:
    """生成一段回复；LLM 不可用时返回 None（让上层回退到模板，而不是给用户报错）。

    on_token 非空时走流式：每块正文实时回调，返回值仍是完整正文。
    """
    try:
        if on_token is None:
            return _invoke(actor_type, system_prompt, user_prompt, tag=tag)
        return _invoke_stream(actor_type, system_prompt, user_prompt, tag=tag,
                              on_token=on_token)
    except Exception:
        return None


def smoke() -> None:
    """冒烟测试：发一句话，打印回复内容与耗时（毫秒）。"""
    llm = get_student_llm()
    messages = [
        {"role": "system", "content": SYSTEM_RULES},
        {"role": "user", "content": "用一句话说明你能做什么"},
    ]
    start = time.perf_counter()
    resp = llm.invoke(messages)
    elapsed_ms = (time.perf_counter() - start) * 1000
    content = resp.content if isinstance(resp.content, str) else str(resp.content)
    print(content)
    print(f"耗时: {elapsed_ms:.0f}ms")


if __name__ == "__main__":
    smoke()
