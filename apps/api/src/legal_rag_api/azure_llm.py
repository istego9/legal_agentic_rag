"""LLM integration with budget-aware defaults for Azure OpenAI and OpenAI."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import httpx


@dataclass
class AzureOpenAIConfig:
    provider: str = "azure"
    endpoint: Optional[str] = None
    api_key: Optional[str] = None
    deployment: Optional[str] = None
    model: Optional[str] = None
    base_url: str = "https://api.openai.com/v1"
    api_version: str = "2024-02-15-preview"
    max_tokens: int = 256
    temperature: float = 0.0
    timeout_seconds: float = 6.0
    top_p: float = 1.0
    azure_tries: int = 1
    token_parameter: str = "max_tokens"
    reasoning_effort: Optional[str] = None
    service_tier: Optional[str] = None

    @property
    def enabled(self) -> bool:
        if self.provider == "openai":
            return bool(self.api_key and self.model)
        return bool(self.endpoint and self.api_key and self.deployment)

    @property
    def uses_reasoning_profile(self) -> bool:
        return self.token_parameter == "max_completion_tokens" or bool(self.reasoning_effort)

    @classmethod
    def from_env(cls) -> "AzureOpenAIConfig":
        provider = (os.getenv("LLM_PROVIDER") or "").strip().lower()
        azure_present = bool(os.getenv("AZURE_OPENAI_ENDPOINT") and os.getenv("AZURE_OPENAI_API_KEY"))
        openai_present = bool(os.getenv("OPENAI_API_KEY"))
        if provider not in {"azure", "openai"}:
            provider = "azure" if azure_present or not openai_present else "openai"
        reasoning_effort = (os.getenv("AZURE_OPENAI_REASONING_EFFORT") or "").strip() or None
        token_parameter = (os.getenv("AZURE_OPENAI_TOKEN_PARAMETER") or "").strip() or "max_tokens"
        if token_parameter not in {"max_tokens", "max_completion_tokens"}:
            token_parameter = "max_tokens"
        if reasoning_effort and token_parameter == "max_tokens":
            token_parameter = "max_completion_tokens"
        if provider == "openai":
            openai_reasoning_effort = (os.getenv("OPENAI_REASONING_EFFORT") or "").strip() or None
            openai_token_parameter = (os.getenv("OPENAI_TOKEN_PARAMETER") or "").strip() or "max_tokens"
            if openai_token_parameter not in {"max_tokens", "max_completion_tokens"}:
                openai_token_parameter = "max_tokens"
            if openai_reasoning_effort and openai_token_parameter == "max_tokens":
                openai_token_parameter = "max_completion_tokens"
            return cls(
                provider="openai",
                endpoint=None,
                api_key=os.getenv("OPENAI_API_KEY"),
                deployment=None,
                model=os.getenv("OPENAI_MODEL", "gpt-4.1-nano"),
                base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
                api_version="",
                max_tokens=int(os.getenv("OPENAI_MAX_TOKENS", os.getenv("AZURE_OPENAI_MAX_TOKENS", "256"))),
                temperature=float(os.getenv("OPENAI_TEMPERATURE", os.getenv("AZURE_OPENAI_TEMPERATURE", "0.0"))),
                timeout_seconds=float(
                    os.getenv("OPENAI_TIMEOUT_SECONDS", os.getenv("AZURE_OPENAI_TIMEOUT_SECONDS", "6.0"))
                ),
                top_p=float(os.getenv("OPENAI_TOP_P", os.getenv("AZURE_OPENAI_TOP_P", "1.0"))),
                azure_tries=int(os.getenv("OPENAI_TRIES", os.getenv("AZURE_OPENAI_TRIES", "1"))),
                token_parameter=openai_token_parameter,
                reasoning_effort=openai_reasoning_effort,
                service_tier=(os.getenv("OPENAI_SERVICE_TIER") or "").strip() or None,
            )
        return cls(
            provider="azure",
            endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            api_key=os.getenv("AZURE_OPENAI_API_KEY"),
            deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini"),
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview"),
            max_tokens=int(os.getenv("AZURE_OPENAI_MAX_TOKENS", "256")),
            temperature=float(os.getenv("AZURE_OPENAI_TEMPERATURE", "0.0")),
            timeout_seconds=float(os.getenv("AZURE_OPENAI_TIMEOUT_SECONDS", "6.0")),
            top_p=float(os.getenv("AZURE_OPENAI_TOP_P", "1.0")),
            azure_tries=int(os.getenv("AZURE_OPENAI_TRIES", "1")),
            token_parameter=token_parameter,
            reasoning_effort=reasoning_effort,
        )


class AzureLLMClient:
    """Thin Azure OpenAI completion helper."""

    def __init__(self, config: Optional[AzureOpenAIConfig] = None) -> None:
        self.config = config or AzureOpenAIConfig.from_env()
        if not self.config.endpoint:
            self.config.endpoint = None

    def _build_payload(
        self,
        prompt: str,
        *,
        user_context: Optional[Dict[str, Any]],
        system_prompt: Optional[str],
        max_tokens: Optional[int],
        temperature: Optional[float],
        top_p: Optional[float],
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt
                    or (
                        "You are a strict legal answering assistant. "
                        "Return concise output, no extra prose."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            self.config.token_parameter: self.config.max_tokens if max_tokens is None else max_tokens,
        }
        if self.config.provider == "openai" and self.config.model:
            payload["model"] = self.config.model
            if self.config.service_tier:
                payload["service_tier"] = self.config.service_tier
        if self.config.uses_reasoning_profile:
            if self.config.reasoning_effort:
                payload["reasoning_effort"] = self.config.reasoning_effort
        else:
            payload["temperature"] = self.config.temperature if temperature is None else temperature
            payload["top_p"] = self.config.top_p if top_p is None else top_p
        if user_context:
            payload["user"] = json.dumps(user_context)
        return payload

    async def complete_chat(
        self,
        prompt: str,
        *,
        user_context: Optional[Dict[str, Any]] = None,
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
    ) -> Tuple[str, Dict[str, int]]:
        if not self.config.enabled:
            return "", {"prompt_tokens": 0, "completion_tokens": 0}

        payload = self._build_payload(
            prompt,
            user_context=user_context,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
        )

        if self.config.provider == "openai":
            url = f"{self.config.base_url.rstrip('/')}/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            }
        else:
            url = (
                f"{self.config.endpoint.rstrip('/')}"
                f"/openai/deployments/{self.config.deployment}/chat/completions"
                f"?api-version={self.config.api_version}"
            )
            headers = {
                "api-key": self.config.api_key,
                "Content-Type": "application/json",
            }

        tries = max(1, self.config.azure_tries)
        last_error: Optional[Exception] = None
        for _ in range(tries):
            try:
                async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
                    response = await client.post(url, headers=headers, json=payload)
                    response.raise_for_status()
                    body = response.json()
                text = (
                    body.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                    .strip()
                )
                usage = body.get("usage", {})
                return text, {
                    "prompt_tokens": int(usage.get("prompt_tokens", 0)),
                    "completion_tokens": int(usage.get("completion_tokens", 0)),
                }
            except Exception as exc:  # broad catch: caller handles fallback
                last_error = exc
                await asyncio.sleep(0.05)

        raise RuntimeError(f"Azure OpenAI request failed: {last_error}") from last_error


def make_telemetry_tags(job: str, answer_type: str) -> str:
    return f"azure/{job}/{answer_type}/{uuid.uuid4().hex[:8]}"
