# tests/test_llm_provider.py
# 职责：LLM 提供方顺序（星火优先 / DeepSeek 兜底）与失败切换逻辑。
# 依赖：pytest / agents.llm；不访问真实网络，全部用假客户端与假配置。

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402

from agents import llm  # noqa: E402


class _Settings:
    def __init__(self, spark: str = "", deepseek: str = "", mode: str = "auto"):
        self.spark_api_key = spark
        self.deepseek_api_key = deepseek
        self.llm_provider = mode
        self.spark_base_url = "https://spark.example/v2"
        self.spark_model = "spark-x2.6"
        self.deepseek_base_url = "https://deepseek.example"
        self.deepseek_model = "deepseek-chat"


class _Resp:
    def __init__(self, content: str):
        self.content = content


class _Model:
    def __init__(self, content: str | None = None, fail: bool = False):
        self.content = content
        self.fail = fail

    def invoke(self, _messages):
        if self.fail:
            raise RuntimeError("provider down")
        return _Resp(self.content or "")

    def stream(self, _messages):
        if self.fail:
            raise RuntimeError("provider down")
        yield _Resp(self.content or "")


def test_provider_order_prefers_spark(monkeypatch):
    monkeypatch.setattr(llm, "get_settings",
                        lambda: _Settings(spark="ak-x", deepseek="sk-x"))
    assert llm.provider_order() == ("spark", "deepseek")
    monkeypatch.setattr(llm, "get_settings",
                        lambda: _Settings(spark="ak-x", deepseek="", mode="auto"))
    assert llm.provider_order() == ("spark",)
    monkeypatch.setattr(llm, "get_settings",
                        lambda: _Settings(spark="", deepseek="sk-x", mode="spark"))
    assert llm.provider_order() == ("deepseek",)
    monkeypatch.setattr(llm, "get_settings",
                        lambda: _Settings(spark="", deepseek="", mode="auto"))
    assert llm.provider_order() == ()


def test_invoke_falls_back_to_second_provider(monkeypatch):
    calls: list[str] = []
    models = {
        "spark": _Model(fail=True),
        "deepseek": _Model(content="兜底回答"),
    }

    def fake_cached(provider, _temperature):
        calls.append(provider)
        return models[provider]

    monkeypatch.setattr(llm, "provider_order", lambda: ("spark", "deepseek"))
    monkeypatch.setattr(llm, "_cached_llm", fake_cached)
    monkeypatch.setattr("app.audit.audit_event", lambda **kwargs: None)

    assert llm._invoke("student", "系统", "问题", tag="test") == "兜底回答"
    assert calls == ["spark", "deepseek"]


def test_generate_reply_returns_none_when_all_providers_down(monkeypatch):
    monkeypatch.setattr(llm, "provider_order", lambda: ("spark", "deepseek"))
    monkeypatch.setattr(llm, "_cached_llm",
                        lambda provider, _temperature: _Model(fail=True))
    monkeypatch.setattr("app.audit.audit_event", lambda **kwargs: None)
    assert llm.generate_reply("student", system_prompt="s", user_prompt="u") is None


def test_stream_does_not_switch_after_partial_output(monkeypatch):
    class PartialModel:
        def stream(self, _messages):
            yield _Resp("半截")
            raise RuntimeError("断流")

    monkeypatch.setattr(llm, "provider_order", lambda: ("spark", "deepseek"))
    monkeypatch.setattr(llm, "_cached_llm",
                        lambda provider, _temperature: PartialModel())
    monkeypatch.setattr("app.audit.audit_event", lambda **kwargs: None)
    with pytest.raises(RuntimeError):
        llm._invoke_stream("student", "s", "u", tag="test", on_token=lambda _t: None)
