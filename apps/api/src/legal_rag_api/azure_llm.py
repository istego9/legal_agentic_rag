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
    api_mode: str = "chat_completions"
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
    verbosity: Optional[str] = None

    @property
    def enabled(self) -> bool:
        if self.provider == "openai":
            return bool(self.api_key and self.model)
        return bool(self.endpoint and self.api_key and self.deployment)

    @property
    def uses_reasoning_profile(self) -> bool:
        return self.token_parameter == "max_completion_tokens" or bool(self.reasoning_effort)

    @property
    def uses_responses_api(self) -> bool:
        return self.api_mode == "responses"

    @classmethod
    def from_env(cls) -> "AzureOpenAIConfig":
        provider = (os.getenv("LLM_PROVIDER") or "").strip().lower()
        azure_present = bool(os.getenv("AZURE_OPENAI_ENDPOINT") and os.getenv("AZURE_OPENAI_API_KEY"))
        openai_present = bool(os.getenv("OPENAI_API_KEY"))
        if provider not in {"azure", "openai"}:
            provider = "azure" if azure_present or not openai_present else "openai"
        api_mode = (os.getenv("AZURE_OPENAI_API_MODE") or "").strip().lower() or "chat_completions"
        if api_mode not in {"chat_completions", "responses"}:
            api_mode = "chat_completions"
        reasoning_effort = (os.getenv("AZURE_OPENAI_REASONING_EFFORT") or "").strip() or None
        token_parameter = (os.getenv("AZURE_OPENAI_TOKEN_PARAMETER") or "").strip() or "max_tokens"
        if token_parameter not in {"max_tokens", "max_completion_tokens", "max_output_tokens"}:
            token_parameter = "max_tokens"
        if reasoning_effort and token_parameter == "max_tokens":
            token_parameter = "max_completion_tokens"
        if provider == "openai":
            openai_api_mode = (os.getenv("OPENAI_API_MODE") or "").strip().lower() or "chat_completions"
            if openai_api_mode not in {"chat_completions", "responses"}:
                openai_api_mode = "chat_completions"
            openai_reasoning_effort = (os.getenv("OPENAI_REASONING_EFFORT") or "").strip() or None
            openai_token_parameter = (os.getenv("OPENAI_TOKEN_PARAMETER") or "").strip() or "max_tokens"
            if openai_token_parameter not in {"max_tokens", "max_completion_tokens", "max_output_tokens"}:
                openai_token_parameter = "max_tokens"
            if openai_reasoning_effort and openai_token_parameter == "max_tokens":
                openai_token_parameter = "max_completion_tokens"
            return cls(
                provider="openai",
                api_mode=openai_api_mode,
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
                verbosity=(os.getenv("OPENAI_VERBOSITY") or "").strip() or None,
            )
        return cls(
            provider="azure",
            api_mode=api_mode,
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
            verbosity=(os.getenv("AZURE_OPENAI_VERBOSITY") or "").strip() or None,
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
        if self.config.uses_responses_api:
            return self._build_responses_payload(
                prompt,
                user_context=user_context,
                system_prompt=system_prompt,
                max_tokens=max_tokens,
            )
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

    def _build_responses_payload(
        self,
        prompt: str,
        *,
        user_context: Optional[Dict[str, Any]],
        system_prompt: Optional[str],
        max_tokens: Optional[int],
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "input": prompt,
            "instructions": system_prompt
            or (
                "You are a strict legal answering assistant. "
                "Return concise output, no extra prose."
            ),
            "max_output_tokens": self.config.max_tokens if max_tokens is None else max_tokens,
        }
        if self.config.provider == "openai":
            payload["model"] = self.config.model
            if self.config.service_tier:
                payload["service_tier"] = self.config.service_tier
        else:
            payload["model"] = self.config.deployment
        if self.config.reasoning_effort:
            payload["reasoning"] = {"effort": self.config.reasoning_effort}
        if self.config.verbosity:
            payload["text"] = {"verbosity": self.config.verbosity}
        if user_context:
            payload["metadata"] = {str(key): str(value)[:512] for key, value in user_context.items()}
        return payload

    def _build_request(self, payload: Dict[str, Any]) -> Tuple[str, Dict[str, str]]:
        if self.config.provider == "openai":
            if self.config.uses_responses_api:
                url = f"{self.config.base_url.rstrip('/')}/responses"
            else:
                url = f"{self.config.base_url.rstrip('/')}/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            }
            return url, headers

        if self.config.uses_responses_api:
            endpoint = (self.config.endpoint or "").rstrip("/")
            if endpoint.endswith("/openai/v1"):
                url = f"{endpoint}/responses"
            else:
                url = f"{endpoint}/openai/v1/responses"
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
        return url, headers

    @staticmethod
    def _extract_responses_text(body: Dict[str, Any]) -> str:
        output_text = body.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text.strip()
        output = body.get("output")
        if not isinstance(output, list):
            return ""
        parts: list[str] = []
        for item in output:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                text_block = block.get("text")
                if isinstance(text_block, str):
                    parts.append(text_block)
                    continue
                if isinstance(text_block, dict):
                    text_value = text_block.get("value")
                    if isinstance(text_value, str):
                        parts.append(text_value)
        return "\n".join(part.strip() for part in parts if part and part.strip()).strip()

    def _parse_response(self, body: Dict[str, Any]) -> Tuple[str, Dict[str, int]]:
        if self.config.uses_responses_api:
            usage = body.get("usage", {})
            return self._extract_responses_text(body), {
                "prompt_tokens": int(usage.get("input_tokens", 0)),
                "completion_tokens": int(usage.get("output_tokens", 0)),
            }
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

        url, headers = self._build_request(payload)

        tries = max(1, self.config.azure_tries)
        last_error: Optional[Exception] = None
        for _ in range(tries):
            try:
                async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
                    response = await client.post(url, headers=headers, json=payload)
                    response.raise_for_status()
                    body = response.json()
                return self._parse_response(body)
            except Exception as exc:  # broad catch: caller handles fallback
                last_error = exc
                await asyncio.sleep(0.05)

        error_text = ""
        if last_error is not None:
            detail = str(last_error).strip()
            error_text = f"{type(last_error).__name__}: {detail}" if detail else type(last_error).__name__
        raise RuntimeError(f"Azure OpenAI request failed: {error_text}") from last_error


def make_telemetry_tags(job: str, answer_type: str) -> str:
    return f"azure/{job}/{answer_type}/{uuid.uuid4().hex[:8]}"
