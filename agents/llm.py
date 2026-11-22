# agents/llm.py
# 职责：LLM 客户端封装——在线（星火/DeepSeek）优先、本地大模型兜底，供所有 Agent 节点复用。
# 依赖：langchain_openai.ChatOpenAI / app.config.get_settings
# 说明：api_key 只从 .env 读取，禁止硬编码；所有提供方均为 OpenAI 兼容接口，切换只换 base_url/model。
#      隐私分级：privacy="local" 只走本地大模型（数据不出机），适合学生个人隐私数据。

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

_PLACEHOLDERS = {"", "REPLACE_ME", "sk-REPLACE_ME", "ak-REPLACE_ME"}

# 提供方元信息：privacy_tier = online（数据上云）/ local（数据不出机）；requires_key 表示是否需真实密钥
_PROVIDER_META: dict[str, tuple[str, bool]] = {
    "spark": ("online", True),
    "deepseek": ("online", True),
    "local": ("local", False),
}


def _configured(key: str) -> bool:
    return str(key or "").strip() not in _PLACEHOLDERS


def provider_order(*, privacy: str = "any") -> tuple[str, ...]:
    """按配置返回提供方尝试顺序：在线优先、本地兜底。

    privacy="local" 只返回本地提供方（数据不出机，适合学生隐私数据）；
    privacy="online" 只返回在线提供方；privacy="any"（默认）返回全部已配置。
    """
    s = get_settings()
    spark_ok = _configured(s.spark_api_key)
    deepseek_ok = _configured(s.deepseek_api_key)
    local_ok = bool(str(s.local_llm_base_url or "").strip())
    mode = str(s.llm_provider or "auto").strip().lower()

    if mode == "spark":
        online = ("spark", "deepseek") if deepseek_ok else ("spark",)
    elif mode == "deepseek":
        online = ("deepseek", "spark") if spark_ok else ("deepseek",)
    elif spark_ok:
        online = ("spark", "deepseek") if deepseek_ok else ("spark",)
    else:
        online = ("deepseek",)

    online = tuple(n for n in online
                   if (n == "spark" and spark_ok) or (n == "deepseek" and deepseek_ok))
    order: list[str] = list(online)
    if local_ok:
        order.append("local")

    tier = privacy if privacy in ("online", "local") else "any"
    if tier != "any":
        order = [n for n in order if _PROVIDER_META[n][0] == tier]
    return tuple(order)


def _build_llm(provider: str, temperature: float) -> ChatOpenAI:
    """按提供方构建 ChatOpenAI；本地提供方无需真实密钥，留空则用占位。"""
    s = get_settings()
    if provider == "spark":
        base_url = str(s.spark_base_url or "").strip().rstrip("/")
        model = str(s.spark_model or "").strip() or "spark-x2.6"
        api_key = str(s.spark_api_key or "").strip()
        if not _configured(api_key):
            raise RuntimeError("SPARK_API_KEY 未配置")
    elif provider == "deepseek":
        base_url = str(s.deepseek_base_url or "https://api.deepseek.com").strip().rstrip("/")
        model = str(s.deepseek_model or "").strip() or "deepseek-chat"
        api_key = str(s.deepseek_api_key or "").strip()
        if not _configured(api_key):
            raise RuntimeError("DEEPSEEK_API_KEY 未配置")
    elif provider == "local":
        base_url = str(s.local_llm_base_url or "http://127.0.0.1:11434/v1").strip().rstrip("/")
        model = str(s.local_llm_model or "").strip() or "qwen2.5:7b"
        api_key = str(s.local_llm_api_key or "").strip() or "ollama"
    else:
        raise RuntimeError(f"未知 LLM 提供方: {provider}")

    return ChatOpenAI(
        base_url=base_url,
        model=model,
        api_key=api_key,
        temperature=temperature,
        timeout=60,
        max_retries=1,
    )


@lru_cache(maxsize=4)
def _cached_llm(provider: str, temperature: float) -> ChatOpenAI:
    return _build_llm(provider, temperature)


def get_llm(actor_type: str, *, privacy: str = "any") -> ChatOpenAI:
    """按 actor_type 取主 LLM；privacy="local" 时只走本地（数据不出机）。"""
    order = provider_order(privacy=privacy)
    if not order:
        raise RuntimeError(
            "没有可用的 LLM：请在 .env 配置在线 Key 或本地大模型端点")
    temperature = 0.2 if actor_type == "teacher" else 0.3
    return _cached_llm(order[0], temperature)


def get_private_llm(actor_type: str) -> ChatOpenAI:
    """隐私数据场景（如学生个人数据）：只走本地大模型，数据不出机。

    未配置本地提供方时抛错，绝不静默回退到在线提供方（避免隐私数据上云）。
    """
    order = provider_order(privacy="local")
    if not order:
        raise RuntimeError(
            "未配置本地大模型，无法处理隐私数据；"
            "请在 .env 配置 LOCAL_LLM_BASE_URL（如 Ollama）")
    temperature = 0.2 if actor_type == "teacher" else 0.3
    return _cached_llm(order[0], temperature)


def get_teacher_llm() -> ChatOpenAI:
    """教师端主 LLM（在线优先，temperature=0.2）。"""
    return get_llm("teacher")


def get_student_llm() -> ChatOpenAI:
    """学生端主 LLM（在线优先，temperature=0.3）。"""
    return get_llm("student")


def _messages(system_prompt: str, user_prompt: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _temperature(actor_type: str) -> float:
    return 0.2 if actor_type == "teacher" else 0.3


def _invoke(actor_type: str, system_prompt: str, user_prompt: str, *, tag: str,
            temperature: float | None = None, privacy: str = "any") -> str:
    """按提供方顺序尝试一次对话；失败自动换下一家，返回纯文本正文。

    privacy="local" 时只尝试本地提供方，数据不出机。
    """
    from app.audit import audit_event

    order = provider_order(privacy=privacy)
    if not order:
        raise RuntimeError("没有可用的 LLM")
    errors: list[str] = []
    temp = _temperature(actor_type) if temperature is None else temperature
    for provider in order:
        llm = _cached_llm(provider, temp)
        started = time.perf_counter()
        try:
            resp = llm.invoke(_messages(system_prompt, user_prompt))
        except Exception as exc:  # Key 无效/限流/超时：换下一家，不把堆栈抛给用户
            errors.append(f"{provider}: {type(exc).__name__}")
            audit_event(tenant_id=0, actor_type=actor_type, actor_id=0,
                        action=f"llm.{tag}.failed",
                        target=provider, detail={"error": str(exc)[:200]})
            continue
        content = resp.content if isinstance(resp.content, str) else str(resp.content)
        audit_event(tenant_id=0, actor_type=actor_type, actor_id=0,
                    action=f"llm.{tag}", target=provider,
                    detail={"chars": len(content),
                            "cost_ms": round((time.perf_counter() - started) * 1000)})
        return str(content).strip()
    raise RuntimeError("LLM 调用失败：" + "；".join(errors))


def _invoke_stream(actor_type: str, system_prompt: str, user_prompt: str, *, tag: str,
                   on_token: Callable[[str], None],
                   temperature: float | None = None, privacy: str = "any") -> str:
    """流式调用：每收到一块就回调 on_token。

    只有「一个字都还没吐」时才允许换提供方；已经输出半截，换家会拼出两段不同回答。
    privacy="local" 时只尝试本地提供方，数据不出机。
    """
    from app.audit import audit_event

    order = provider_order(privacy=privacy)
    if not order:
        raise RuntimeError("没有可用的 LLM")
    errors: list[str] = []
    temp = _temperature(actor_type) if temperature is None else temperature
    for provider in order:
        llm = _cached_llm(provider, temp)
        started = time.perf_counter()
        parts: list[str] = []
        try:
            for chunk in llm.stream(_messages(system_prompt, user_prompt)):
                text = chunk.content if isinstance(chunk.content, str) else str(chunk.content)
                if not text:
                    continue
                parts.append(text)
                on_token(text)
        except Exception as exc:
            if parts:
                audit_event(tenant_id=0, actor_type=actor_type, actor_id=0,
                            action=f"llm.{tag}.failed", target=provider,
                            detail={"error": str(exc)[:200],
                                    "partial_chars": len("".join(parts))})
                raise
            errors.append(f"{provider}: {type(exc).__name__}")
            audit_event(tenant_id=0, actor_type=actor_type, actor_id=0,
                        action=f"llm.{tag}.failed",
                        target=provider, detail={"error": str(exc)[:200]})
            continue
        content = "".join(parts)
        audit_event(tenant_id=0, actor_type=actor_type, actor_id=0,
                    action=f"llm.{tag}", target=provider,
                    detail={"chars": len(content), "stream": True,
                            "cost_ms": round((time.perf_counter() - started) * 1000)})
        return str(content).strip()
    raise RuntimeError("LLM 流式调用失败：" + "；".join(errors))


def generate_reply(actor_type: str, *, system_prompt: str, user_prompt: str,
                   tag: str = "draft",
                   on_token: Callable[[str], None] | None = None,
                   temperature: float | None = None,
                   privacy: str = "any") -> str | None:
    """生成一段回复；所有提供方都不可用时返回 None（上层回退模板，不报错给用户）。

    temperature 缺省按 actor_type 取默认值；career 等模块传显式温度保留各自语义。
    privacy="local" 时只走本地大模型（数据不出机），无本地提供方则返回 None 回退模板。
    """
    try:
        if on_token is None:
            return _invoke(actor_type, system_prompt, user_prompt, tag=tag,
                           temperature=temperature, privacy=privacy)
        return _invoke_stream(actor_type, system_prompt, user_prompt, tag=tag,
                              on_token=on_token, temperature=temperature,
                              privacy=privacy)
    except Exception:
        return None


def smoke() -> None:
    """冒烟测试：发一句话，打印回复内容、提供方与耗时（毫秒）。"""
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
    print(f"提供方: {provider_order()[0]}，耗时: {elapsed_ms:.0f}ms")


if __name__ == "__main__":
    smoke()
