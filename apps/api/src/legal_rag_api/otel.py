from __future__ import annotations

import os
from typing import Any, Dict

from fastapi import FastAPI

_DISABLED_ENV_VALUES = {"", "0", "false", "off", "no", "n"}
_OTEL_STATUS: Dict[str, Any] = {
    "enabled": False,
    "reason": "not_configured",
}


def _env_enabled(name: str, default: str) -> bool:
    raw = str(os.getenv(name, default)).strip().lower()
    return raw not in _DISABLED_ENV_VALUES


def otel_enabled_by_env() -> bool:
    return _env_enabled("OTEL_ENABLED", "1")


def get_otel_status() -> Dict[str, Any]:
    return dict(_OTEL_STATUS)


def otel_trace_required_for_completeness() -> bool:
    if not bool(_OTEL_STATUS.get("enabled")):
        return False
    return _env_enabled("OTEL_TRACE_REQUIRED_FOR_COMPLETENESS", "1")


def current_trace_id() -> str | None:
    try:
        from opentelemetry import trace
    except Exception:
        return None
    try:
        context = trace.get_current_span().get_span_context()
    except Exception:
        return None
    if not context or not bool(getattr(context, "is_valid", False)):
        return None
    trace_id = int(getattr(context, "trace_id", 0) or 0)
    if trace_id <= 0:
        return None
    return format(trace_id, "032x")


def setup_fastapi_otel(app: FastAPI) -> Dict[str, Any]:
    global _OTEL_STATUS

    if not otel_enabled_by_env():
        _OTEL_STATUS = {"enabled": False, "reason": "disabled_by_env"}
        return get_otel_status()

    try:
        from opentelemetry import trace
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
    except Exception:
        _OTEL_STATUS = {"enabled": False, "reason": "missing_dependency"}
        return get_otel_status()

    provider = trace.get_tracer_provider()
    provider_name = provider.__class__.__name__
    if provider_name == "ProxyTracerProvider":
        resource = Resource.create(
            {
                "service.name": os.getenv("OTEL_SERVICE_NAME", "legal-agentic-rag-api"),
                "service.namespace": os.getenv("OTEL_SERVICE_NAMESPACE", "legal-rag"),
            }
        )
        trace.set_tracer_provider(TracerProvider(resource=resource))
        provider = trace.get_tracer_provider()

    if _env_enabled("OTEL_CONSOLE_EXPORTER_ENABLED", "0"):
        try:
            from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        except Exception:
            pass

    excluded_urls = os.getenv(
        "OTEL_FASTAPI_EXCLUDED_URLS",
        "/v1/health,/docs,/openapi.json",
    )
    if not getattr(app.state, "otel_instrumented", False):
        FastAPIInstrumentor.instrument_app(
            app,
            tracer_provider=provider,
            excluded_urls=excluded_urls,
        )
        app.state.otel_instrumented = True

    _OTEL_STATUS = {
        "enabled": True,
        "reason": "instrumented",
        "excluded_urls": excluded_urls,
    }
    return get_otel_status()
