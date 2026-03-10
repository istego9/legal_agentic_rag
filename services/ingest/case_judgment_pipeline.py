"""Orchestration helpers for case judgment extraction pipelines."""

from __future__ import annotations

from typing import Any, Dict, List

from legal_rag_api.azure_llm import AzureLLMClient
from services.ingest.case_judgment_chunk_extractor import extract_case_judgment_chunks
from services.ingest.case_judgment_document_extractor import extract_case_judgment_document
from services.ingest.case_judgment_projection import project_case_judgment_artifacts
from services.ingest.case_judgment_qc import evaluate_case_judgment_qc
from services.ingest.case_judgment_router import route_case_judgment_document


def run_case_judgment_router_pipeline(
    *,
    document: Dict[str, Any],
    pages: List[Dict[str, Any]],
    metadata: Dict[str, Any] | None = None,
    llm_client: AzureLLMClient | None = None,
) -> Dict[str, Any]:
    metadata = metadata or {}
    first_page_text = str((pages[0] if pages else {}).get("text", "") or "")
    second_page_text = str((pages[1] if len(pages) > 1 else {}).get("text", "") or "")
    decision = route_case_judgment_document(
        filename=str(document.get("pdf_id") or document.get("document_id") or "document"),
        first_page_text=first_page_text,
        second_page_text=second_page_text,
        metadata={
            "document_id": document.get("document_id"),
            "doc_type": document.get("doc_type"),
            "page_count": document.get("page_count"),
            **metadata,
        },
        llm_client=llm_client,
    )
    return {
        "doc_type": decision.doc_type,
        "document_subtype": decision.document_subtype,
        "routing_profile": decision.routing_profile,
        "confidence": decision.confidence,
        "route_status": decision.route_status,
        "one_line_rationale": decision.one_line_rationale,
        "rule_hits": decision.rule_hits,
        "conflicts": decision.conflicts,
        "missing_markers": decision.missing_markers,
        "marker_state": decision.marker_state,
        "feature_state": decision.feature_state,
        "llm_calls": decision.llm_calls,
        "token_usage": decision.token_usage,
    }


def run_case_judgment_extraction_pipeline(
    *,
    document: Dict[str, Any],
    pages: List[Dict[str, Any]],
    paragraphs: List[Dict[str, Any]],
    metadata: Dict[str, Any] | None = None,
    use_llm: bool = True,
    llm_client: AzureLLMClient | None = None,
    max_chunks: int | None = None,
) -> Dict[str, Any]:
    metadata = metadata or {}
    routing_state = run_case_judgment_router_pipeline(
        document=document,
        pages=pages,
        metadata=metadata,
        llm_client=llm_client,
    )

    document_result = extract_case_judgment_document(
        document=document,
        pages=pages,
        paragraphs=paragraphs,
        routing_state=routing_state,
        use_llm=use_llm,
        llm_client=llm_client,
    )

    chunk_result = extract_case_judgment_chunks(
        document_payload=document_result.payload,
        pages=pages,
        paragraphs=paragraphs,
        use_llm=use_llm,
        llm_client=llm_client,
        max_chunks=max_chunks,
    )

    qc_result = evaluate_case_judgment_qc(
        document_payload=document_result.payload,
        chunk_payloads=chunk_result.chunks,
    )

    projection = project_case_judgment_artifacts(
        document_payload=document_result.payload,
        chunk_payloads=chunk_result.chunks,
        paragraphs_by_id={str(row.get("paragraph_id", "")): row for row in paragraphs},
        pages_by_id={str(row.get("page_id", "")): row for row in pages},
    )

    total_prompt_tokens = int(routing_state["token_usage"].get("prompt_tokens", 0) or 0)
    total_completion_tokens = int(routing_state["token_usage"].get("completion_tokens", 0) or 0)
    total_llm_calls = int(routing_state.get("llm_calls", 0) or 0)

    total_prompt_tokens += int(document_result.token_usage.get("prompt_tokens", 0) or 0)
    total_completion_tokens += int(document_result.token_usage.get("completion_tokens", 0) or 0)
    total_llm_calls += int(document_result.llm_calls or 0)

    total_prompt_tokens += int(chunk_result.token_usage.get("prompt_tokens", 0) or 0)
    total_completion_tokens += int(chunk_result.token_usage.get("completion_tokens", 0) or 0)
    total_llm_calls += int(chunk_result.llm_calls or 0)

    return {
        "routing": routing_state,
        "document_extraction": {
            "payload": document_result.payload,
            "validation_errors": document_result.validation_errors,
            "validation_status": document_result.validation_status,
            "confidence_score": document_result.confidence_score,
            "token_usage": document_result.token_usage,
            "llm_calls": document_result.llm_calls,
        },
        "chunk_extraction": {
            "chunks": chunk_result.chunks,
            "validation_errors": chunk_result.validation_errors,
            "validation_status": chunk_result.validation_status,
            "token_usage": chunk_result.token_usage,
            "llm_calls": chunk_result.llm_calls,
        },
        "qc": {
            "checks": qc_result.checks,
            "blocking_failed": qc_result.blocking_failed,
        },
        "projection": projection,
        "token_usage": {
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_completion_tokens,
        },
        "llm_calls": total_llm_calls,
    }
