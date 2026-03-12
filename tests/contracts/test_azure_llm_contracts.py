from __future__ import annotations

import asyncio

from legal_rag_api import azure_llm as azure_llm_module
from legal_rag_api.azure_llm import AzureLLMClient, AzureOpenAIConfig


def test_azure_openai_config_promotes_reasoning_profile_from_env(monkeypatch) -> None:
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "secret")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "wf-router")
    monkeypatch.setenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
    monkeypatch.setenv("AZURE_OPENAI_REASONING_EFFORT", "minimal")
    monkeypatch.delenv("AZURE_OPENAI_TOKEN_PARAMETER", raising=False)

    config = AzureOpenAIConfig.from_env()

    assert config.enabled is True
    assert config.reasoning_effort == "minimal"
    assert config.token_parameter == "max_completion_tokens"


def test_reasoning_profile_uses_reasoning_payload_shape(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "choices": [{"message": {"content": "OK"}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 2},
            }

    class FakeAsyncClient:
        def __init__(self, *, timeout: float) -> None:
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> FakeResponse:
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr(azure_llm_module.httpx, "AsyncClient", FakeAsyncClient)
    client = AzureLLMClient(
        AzureOpenAIConfig(
            endpoint="https://example.openai.azure.com",
            api_key="secret",
            deployment="wf-router",
            api_version="2024-10-21",
            max_tokens=96,
            temperature=0.0,
            timeout_seconds=3.0,
            top_p=1.0,
            azure_tries=1,
            token_parameter="max_completion_tokens",
            reasoning_effort="minimal",
        )
    )

    text, usage = asyncio.run(
        client.complete_chat(
            "Reply with exactly OK.",
            max_tokens=64,
            temperature=0.0,
            top_p=1.0,
        )
    )

    assert text == "OK"
    assert usage == {"prompt_tokens": 11, "completion_tokens": 2}
    assert captured["timeout"] == 3.0
    assert str(captured["url"]).endswith(
        "/openai/deployments/wf-router/chat/completions?api-version=2024-10-21"
    )
    payload = captured["json"]
    assert isinstance(payload, dict)
    assert payload["max_completion_tokens"] == 64
    assert payload["reasoning_effort"] == "minimal"
    assert "temperature" not in payload
    assert "top_p" not in payload


def test_openai_provider_uses_direct_api_shape(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "choices": [{"message": {"content": "OK"}}],
                "usage": {"prompt_tokens": 9, "completion_tokens": 2},
            }

    class FakeAsyncClient:
        def __init__(self, *, timeout: float) -> None:
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> FakeResponse:
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr(azure_llm_module.httpx, "AsyncClient", FakeAsyncClient)
    client = AzureLLMClient(
        AzureOpenAIConfig(
            provider="openai",
            endpoint=None,
            api_key="openai-secret",
            deployment=None,
            model="gpt-4.1-nano",
            base_url="https://api.openai.com/v1",
            api_version="",
            max_tokens=32,
            temperature=0.0,
            timeout_seconds=2.5,
            top_p=1.0,
            azure_tries=1,
            token_parameter="max_tokens",
            reasoning_effort=None,
            service_tier="flex",
        )
    )

    text, usage = asyncio.run(client.complete_chat("Reply with exactly OK."))

    assert text == "OK"
    assert usage == {"prompt_tokens": 9, "completion_tokens": 2}
    assert captured["timeout"] == 2.5
    assert captured["url"] == "https://api.openai.com/v1/chat/completions"
    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert headers["Authorization"] == "Bearer openai-secret"
    payload = captured["json"]
    assert isinstance(payload, dict)
    assert payload["model"] == "gpt-4.1-nano"
    assert payload["service_tier"] == "flex"
    assert payload["max_tokens"] == 32
    assert payload["temperature"] == 0.0
