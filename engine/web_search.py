# engine/web_search.py
# 职责：联网搜索适配层——把「搜到的网页」变成可引用的结构化结果。
# 依赖：httpx（已在 requirements），环境变量 SERPER_API_KEY 或 BING_SEARCH_KEY
# 铁律：
#   1. 没有配置密钥就返回 configured=False，并明说「没有联网能力」。
#      绝不返回假结果、绝不用模型记忆冒充搜索结果。
#   2. 每条结果必须带真实 URL；回答里引用网页必须能点开对照。
#   3. 结果缓存 10 分钟，避免同一问题把配额打光；缓存只是省流量，不改内容。

from __future__ import annotations

import os
import time
from typing import Any

WEB_SEARCH_VERSION = "web-v1"
CACHE_TTL = 600
_cache: dict[tuple, tuple[float, dict[str, Any]]] = {}


def provider() -> str | None:
    """按优先级选 provider；都没有就返回 None（上层据此诚实降级）。"""
    if os.getenv("SERPER_API_KEY", "").strip():
        return "serper"
    if os.getenv("BING_SEARCH_KEY", "").strip():
        return "bing"
    return None


def configured() -> bool:
    return provider() is not None


def _empty(query: str, reason: str) -> dict[str, Any]:
    return {"configured": False, "provider": None, "query": query,
            "results": [], "error": reason, "engine_version": WEB_SEARCH_VERSION}


def search(query: str, top_k: int = 5, timeout: float = 8.0) -> dict[str, Any]:
    """联网搜索。未配置 → configured=False；请求失败 → error 非空、results 为空。"""
    q = str(query or "").strip()
    if not q:
        return _empty(q, "查询为空")
    prov = provider()
    if prov is None:
        return _empty(q, "未配置联网搜索密钥（SERPER_API_KEY 或 BING_SEARCH_KEY），当前没有联网能力")

    key = (prov, q, int(top_k))
    hit = _cache.get(key)
    now = time.time()
    if hit and now - hit[0] < CACHE_TTL:
        return {**hit[1], "cached": True}

    started = time.time()
    try:
        if prov == "serper":
            out = _serper(q, top_k, timeout)
        else:
            out = _bing(q, top_k, timeout)
    except Exception as exc:  # 网络/配额异常一律如实返回，不编结果
        return {"configured": True, "provider": prov, "query": q, "results": [],
                "error": f"搜索请求失败：{type(exc).__name__}", "engine_version": WEB_SEARCH_VERSION}
    out["took_ms"] = int((time.time() - started) * 1000)
    out["engine_version"] = WEB_SEARCH_VERSION
    _cache[key] = (now, out)
    return out


def _serper(query: str, top_k: int, timeout: float) -> dict[str, Any]:
    import httpx

    resp = httpx.post(
        "https://google.serper.dev/search",
        headers={"X-API-KEY": os.environ["SERPER_API_KEY"].strip(),
                 "Content-Type": "application/json"},
        json={"q": query, "num": max(1, min(top_k, 10)), "gl": "cn", "hl": "zh-cn"},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    results = [{"title": str(it.get("title") or ""), "url": str(it.get("link") or ""),
                "snippet": str(it.get("snippet") or ""), "source": "google"}
               for it in (data.get("organic") or []) if it.get("link")]
    return {"configured": True, "provider": "serper", "query": query,
            "results": results[:top_k], "error": None}


def _bing(query: str, top_k: int, timeout: float) -> dict[str, Any]:
    import httpx

    endpoint = os.getenv("BING_SEARCH_ENDPOINT", "https://api.bing.microsoft.com/v7.0/search").strip()
    resp = httpx.get(
        endpoint,
        headers={"Ocp-Apim-Subscription-Key": os.environ["BING_SEARCH_KEY"].strip()},
        params={"q": query, "count": max(1, min(top_k, 10)), "mkt": "zh-CN"},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    results = [{"title": str(it.get("name") or ""), "url": str(it.get("url") or ""),
                "snippet": str(it.get("snippet") or ""), "source": "bing"}
               for it in ((data.get("webPages") or {}).get("value") or []) if it.get("url")]
    return {"configured": True, "provider": "bing", "query": query,
            "results": results[:top_k], "error": None}


def as_citations(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """搜索结果的引用卡片（编号与回答里的 [n] 对应）。"""
    return [{"no": i, "title": r.get("title") or r.get("url"), "url": r.get("url"),
             "snippet": (r.get("snippet") or "")[:160], "source": r.get("source")}
            for i, r in enumerate(results, start=1)]


def render_context(result: dict[str, Any], limit: int = 5) -> str:
    """把结果拼成给模型的「事实原文」；空结果时给出可解释的原因。"""
    if not result.get("configured"):
        return f"（无联网能力：{result.get('error')}）"
    if result.get("error"):
        return f"（联网搜索失败：{result['error']}）"
    rows = result.get("results") or []
    if not rows:
        return "（联网搜索没有返回结果）"
    lines = []
    for i, r in enumerate(rows[:limit], start=1):
        lines.append(f"[{i}] {r.get('title')}\n{r.get('url')}\n{r.get('snippet')}")
    return "\n\n".join(lines)


def clear_cache() -> None:
    _cache.clear()
