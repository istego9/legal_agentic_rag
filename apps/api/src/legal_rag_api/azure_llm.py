"""Azure OpenAI integration with budget-aware defaults."""

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
    endpoint: Optional[str]
    api_key: Optional[str]
    deployment: Optional[str]
    api_version: str = "2024-02-15-preview"
    max_tokens: int = 96
    temperature: float = 0.0
    timeout_seconds: float = 6.0
    top_p: float = 1.0
    azure_tries: int = 1

    @property
    def enabled(self) -> bool:
        return bool(self.endpoint and self.api_key and self.deployment)

    @classmethod
    def from_env(cls) -> "AzureOpenAIConfig":
        return cls(
            endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            api_key=os.getenv("AZURE_OPENAI_API_KEY"),
            deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini"),
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview"),
            max_tokens=int(os.getenv("AZURE_OPENAI_MAX_TOKENS", "96")),
            temperature=float(os.getenv("AZURE_OPENAI_TEMPERATURE", "0.0")),
            timeout_seconds=float(os.getenv("AZURE_OPENAI_TIMEOUT_SECONDS", "6.0")),
            top_p=float(os.getenv("AZURE_OPENAI_TOP_P", "1.0")),
            azure_tries=int(os.getenv("AZURE_OPENAI_TRIES", "1")),
        )


class AzureLLMClient:
    """Thin Azure OpenAI completion helper."""

    def __init__(self, config: Optional[AzureOpenAIConfig] = None) -> None:
        self.config = config or AzureOpenAIConfig.from_env()
        if not self.config.endpoint:
            self.config.endpoint = None

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

        payload = {
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
            "temperature": self.config.temperature if temperature is None else temperature,
            "max_tokens": self.config.max_tokens if max_tokens is None else max_tokens,
            "top_p": self.config.top_p if top_p is None else top_p,
        }
        if user_context:
            payload["user"] = json.dumps(user_context)

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
