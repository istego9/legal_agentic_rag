from __future__ import annotations

from datetime import datetime, timezone

from legal_rag_api.contracts import Telemetry
from legal_rag_api.otel import current_trace_id, otel_trace_required_for_completeness


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_telemetry(
    request_started_at: datetime,
    answer_output_tokens: int,
    model_name: str,
    route_name: str,
    search_profile: str,
    input_tokens: int = 0,
    first_token_at: datetime | None = None,
    judge_model_name: str | None = None,
) -> Telemetry:
    completed_at = datetime.now(timezone.utc)
    ttft_ms = int(((first_token_at or completed_at) - request_started_at).total_seconds() * 1000)
    total_ms = int((completed_at - request_started_at).total_seconds() * 1000)
    otel_trace_id = current_trace_id()
    trace_id = otel_trace_id or f"trace-{request_started_at.timestamp():.0f}"
    telemetry_complete = True
    if otel_trace_required_for_completeness() and not otel_trace_id:
        telemetry_complete = False
    t = Telemetry(
        request_started_at=request_started_at,
        first_token_at=first_token_at,
        completed_at=completed_at,
        ttft_ms=max(0, ttft_ms),
        total_response_ms=max(0, total_ms),
        time_per_output_token_ms=(total_ms / answer_output_tokens) if answer_output_tokens else None,
        input_tokens=input_tokens,
        output_tokens=answer_output_tokens,
        model_name=model_name,
        route_name=route_name,
        judge_model_name=judge_model_name,
        search_profile=search_profile,
        telemetry_complete=telemetry_complete,
        trace_id=trace_id,
    )
    return t
