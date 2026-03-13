from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any, Dict, List, Tuple

from fastapi import APIRouter, HTTPException, Query

from legal_rag_api import corpus_pg, runtime_pg
from legal_rag_api.azure_llm import AzureLLMClient
from legal_rag_api.contracts import (
    AskBatchRequest,
    Question,
    QueryRequest,
    QueryResponse,
    RunQuestionReviewArtifact,
    RuntimePolicy,
)
from legal_rag_api.state import store
from legal_rag_api.telemetry import build_telemetry
from packages.contracts.corpus_scope import matches_corpus_scope
from packages.retrieval.search import score_candidate, search_pages
from services.runtime.law_article_lookup import resolve_law_article_lookup_intent
from services.runtime.cross_law_compare_lookup import (
    annotate_cross_law_candidate_instruments,
    build_cross_law_compare_retrieval_hints,
    resolve_cross_law_compare_intent,
    solve_cross_law_compare_deterministic,
)
from services.runtime.law_history_lookup import (
    build_law_history_retrieval_hints,
    resolve_law_history_lookup_intent,
    solve_law_history_deterministic,
)
from services.runtime.router import resolve_retrieval_profile, resolve_route_decision
from services.runtime.proposition_layer import proposition_match_features, try_direct_answer
from services.runtime.solvers import (
    build_latency_budget_assertion,
    build_route_recall_diagnostics,
    choose_used_sources_with_trace,
    normalize_answer,
    solve_deterministic,
)

router = APIRouter(prefix="/v1/qa", tags=["QA"])
llm_client = AzureLLMClient()

FREE_TEXT_NO_ANSWER = (
    "No confident answer could be derived from the indexed corpus with current evidence."
)
ALLOWED_ANSWER_TYPES = {"boolean", "number", "date", "name", "names", "free_text"}
REPO_ROOT = Path(__file__).resolve().parents[5]
PUBLIC_DATASET_PATH = REPO_ROOT / "datasets" / "official_fetch_2026-03-11" / "questions.json"
_WHITESPACE_PATTERN = re.compile(r"\s+")
_PART_REF_PATTERN = re.compile(r"\bpart\s+([A-Za-z0-9\-]+)\b", re.IGNORECASE)
_CASE_NUMBER_PATTERN = re.compile(r"\b[A-Z]{2,4}\s*\d{1,4}/\d{4}\b")
_CURRENT_LAW_MARKER = re.compile(r"\b(current|currently in force|valid|updated|as amended)\b", re.IGNORECASE)

_HISTORY_RELATION_EDGE_FILTER = {
    "amended_by": "enabled_by",
    "amends": "enabled_by",
    "repealed_by": "enabled_by",
    "repeals": "enabled_by",
    "superseded_by": "enabled_by",
    "supersedes": "enabled_by",
    "notice_mediated_commencement": "refers_to",
}


def _estimate_tokens(text: str) -> int:
    return max(1, len(text.split()))


def _uniq(values: List[str] | Tuple[str, ...] | Any) -> List[str]:
    out: List[str] = []
    seen = set()
    for value in values:
        token = str(value).strip()
        if not token:
            continue
        if token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def _collapse_ws(value: Any) -> str:
    return _WHITESPACE_PATTERN.sub(" ", str(value or "")).strip()


def _normalize_query_text(question_text: str) -> str:
    return _collapse_ws(question_text).lower()


def _normalize_title_token(value: str) -> str:
    return _collapse_ws(value).lower()


def _question_structure(question_text: str, lookup_intent: Dict[str, Any] | None = None) -> Dict[str, Any]:
    normalized = _normalize_query_text(question_text)
    intent = lookup_intent or resolve_law_article_lookup_intent(question_text)
    return {
        "normalized_query": normalized,
        "article_refs": _uniq(item for item in intent.get("article_refs", []) if item),
        "section_refs": _uniq(item for item in intent.get("section_refs", []) if item),
        "paragraph_refs": _uniq(item for item in intent.get("paragraph_refs", []) if item),
        "clause_refs": _uniq(item for item in intent.get("clause_refs", []) if item),
        "part_refs": _uniq(match.group(1).lower() for match in _PART_REF_PATTERN.finditer(question_text)),
        "schedule_refs": _uniq(item for item in intent.get("schedule_refs", []) if item),
        "law_numbers": _uniq(item for item in intent.get("law_numbers", []) if item),
        "law_years": _uniq(item for item in intent.get("law_years", []) if item),
        "law_titles": _uniq(_normalize_title_token(item) for item in intent.get("law_titles", []) if item),
        "case_numbers": _uniq(match.group(0).upper() for match in _CASE_NUMBER_PATTERN.finditer(question_text.upper())),
        "current_law_intent": bool(_CURRENT_LAW_MARKER.search(question_text)),
        "lookup_intent": intent,
    }


def _projection_for_candidate(candidate: Dict[str, Any]) -> Dict[str, Any]:
    projection = candidate.get("chunk_projection")
    return projection if isinstance(projection, dict) else {}


def _paragraph_for_candidate(candidate: Dict[str, Any]) -> Dict[str, Any]:
    paragraph = candidate.get("paragraph")
    return paragraph if isinstance(paragraph, dict) else {}


def _all_projected_candidates(project_id: str) -> List[Dict[str, Any]]:
    if corpus_pg.enabled():
        paragraphs = {
            str(item.get("paragraph_id", "")): item
            for item in corpus_pg.list_paragraphs(project_id=project_id)
        }
        pages = {
            str(item.get("page_id", "")): item
            for item in corpus_pg.list_pages(project_id=project_id)
        }
        projections = corpus_pg.list_chunk_search_documents(project_id=project_id)
    else:
        paragraphs = {
            str(item.get("paragraph_id", "")): item
            for item in store.paragraphs.values()
            if matches_corpus_scope(item.get("project_id"), project_id)
        }
        pages = {
            str(item.get("page_id", "")): item
            for item in store.pages.values()
            if matches_corpus_scope(item.get("project_id"), project_id)
        }
        projections = [
            item
            for item in store.chunk_search_documents.values()
            if str(item.get("document_id", "")) in {str(row.get("document_id", "")) for row in paragraphs.values()}
        ]
    out: List[Dict[str, Any]] = []
    for projection in projections:
        paragraph = paragraphs.get(str(projection.get("chunk_id", "")))
        if not paragraph:
            continue
        out.append(
            {
                "paragraph": paragraph,
                "page": pages.get(str(paragraph.get("page_id", "")), {}),
                "chunk_projection": projection,
                "score": 0.0,
            }
        )
    return out


def _structural_match(question_structure: Dict[str, Any], candidate: Dict[str, Any]) -> Dict[str, bool]:
    projection = _projection_for_candidate(candidate)
    paragraph = _paragraph_for_candidate(candidate)
    lookup_intent = question_structure.get("lookup_intent", {})
    raw_article_refs: List[Any] = [projection.get("article_number")]
    if isinstance(projection.get("article_refs"), list):
        raw_article_refs.extend(projection.get("article_refs", []))
    if isinstance(paragraph.get("article_refs"), list):
        raw_article_refs.extend(paragraph.get("article_refs", []))
    article_refs = [
        str(value).lower()
        for value in raw_article_refs
        if str(value).strip()
    ]
    section_ref = str(projection.get("section_ref", "")).lower().strip()
    paragraph_ref = str(projection.get("paragraph_ref", "")).lower().strip()
    clause_ref = str(projection.get("clause_ref", "")).lower().strip()
    part_ref = str(projection.get("part_ref", "")).lower().strip()
    heading_path = projection.get("heading_path", []) if isinstance(projection.get("heading_path"), list) else []
    if not part_ref and heading_path:
        part_ref = str(heading_path[0]).lower().strip()
    candidate_text = _normalize_query_text(
        " ".join(
            part
            for part in (
                str(paragraph.get("text", "")),
                str(projection.get("text_clean", "")),
                str(projection.get("retrieval_text", "")),
            )
            if part
        )
    )
    article_marker_hit = any(
        re.search(rf"\barticle\s+{re.escape(ref)}\b", candidate_text, re.IGNORECASE)
        for ref in question_structure["article_refs"]
    )
    schedule_number = str(projection.get("schedule_number", "")).lower().strip()
    law_number = str(projection.get("law_number", "")).strip()
    law_year = str(
        projection.get("law_year")
        or projection.get("regulation_year")
        or projection.get("notice_year")
        or ""
    ).strip()
    law_title = _normalize_title_token(
        str(
            projection.get("law_title")
            or projection.get("title")
            or projection.get("citation_title")
            or projection.get("document_title")
            or ""
        )
    )
    doc_type = str(projection.get("doc_type", "")).strip().lower()
    expected_doc_type = str(lookup_intent.get("resolved_doc_type_guess", "")).strip().lower()
    case_number = str(projection.get("case_number", "")).upper().strip()
    return {
        "article": bool(set(question_structure["article_refs"]).intersection(article_refs) or article_marker_hit),
        "section": bool(question_structure["section_refs"] and section_ref in question_structure["section_refs"]),
        "paragraph": bool(
            question_structure["paragraph_refs"]
            and (
                paragraph_ref in question_structure["paragraph_refs"]
                or any(ref in question_structure["paragraph_refs"] for ref in article_refs)
            )
        ),
        "clause": bool(
            question_structure["clause_refs"]
            and (
                clause_ref in question_structure["clause_refs"]
                or any(ref in question_structure["clause_refs"] for ref in article_refs)
            )
        ),
        "part": bool(question_structure["part_refs"] and part_ref in question_structure["part_refs"]),
        "schedule": bool(question_structure["schedule_refs"] and schedule_number in question_structure["schedule_refs"]),
        "law_number": bool(question_structure["law_numbers"] and law_number in question_structure["law_numbers"]),
        "law_year": bool(question_structure["law_years"] and law_year in question_structure["law_years"]),
        "law_title": bool(
            question_structure["law_titles"]
            and law_title
            and any(title in law_title for title in question_structure["law_titles"])
        ),
        "doc_type": bool(expected_doc_type and expected_doc_type != "unknown" and doc_type == expected_doc_type),
        "case_number": bool(question_structure["case_numbers"] and case_number in question_structure["case_numbers"]),
    }


def _candidate_retrieval_features(
    candidate: Dict[str, Any],
    *,
    question_structure: Dict[str, Any],
    route_name: str,
) -> Dict[str, Any]:
    projection = _projection_for_candidate(candidate)
    structure_hits = _structural_match(question_structure, candidate)
    exact_identifier_hit = any(structure_hits.values())
    lineage_signal = bool(
        route_name == "history_lineage"
        or projection.get("historical_relation_type")
        or (
            isinstance(projection.get("edge_types"), list)
            and any(edge in {"amends", "amended_by", "repeals", "restates", "supersedes"} for edge in projection.get("edge_types", []))
        )
    )
    return {
        "structure_hits": structure_hits,
        "exact_identifier_hit": exact_identifier_hit,
        "law_article_intent_aligned": bool(
            route_name == "article_lookup"
            and (
                structure_hits.get("article")
                or structure_hits.get("section")
                or structure_hits.get("paragraph")
                or structure_hits.get("clause")
                or structure_hits.get("schedule")
            )
        ),
        "current_version_hit": bool(projection.get("is_current_version")),
        "lineage_signal": lineage_signal,
    }


def _projection_matches_filters(chunk_projection: Dict[str, Any], filters: Dict[str, Any] | None) -> bool:
    if not filters:
        return True
    for key, value in filters.items():
        if value is None:
            continue
        if key == "edge_type":
            edge_types = chunk_projection.get("edge_types", [])
            if not isinstance(edge_types, list) or value not in edge_types:
                return False
            continue
        projected = chunk_projection.get(key)
        if isinstance(projected, list):
            if value not in projected:
                return False
            continue
        if projected != value:
            return False
    return True


def _search_candidates_route_aware(
    *,
    project_id: str,
    query: str,
    top_k: int,
    filters: Dict[str, Any] | None = None,
    allow_generic_fallback: bool = True,
) -> Tuple[List[Dict[str, Any]], str]:
    if top_k <= 0:
        return [], "zero_budget"
    if corpus_pg.enabled():
        rows = corpus_pg.search_candidates(project_id=project_id, query=query, top_k=top_k, filters=filters)
        backend = "pg_search_candidates"
        if not allow_generic_fallback:
            rows = [row for row in rows if float(row.get("score", 0.0) or 0.0) > 0.01]
        return rows, backend

    if store.feature_flags.get("canonical_chunk_model_v1", True) and store.chunk_search_documents:
        scored: List[Dict[str, Any]] = []
        for chunk_projection in store.chunk_search_documents.values():
            paragraph = store.paragraphs.get(chunk_projection.get("chunk_id"))
            if not paragraph:
                continue
            if not matches_corpus_scope(paragraph.get("project_id"), project_id):
                continue
            if not _projection_matches_filters(chunk_projection, filters):
                continue
            score = score_candidate(query, chunk_projection.get("retrieval_text", chunk_projection.get("text_clean", "")))
            if score <= 0:
                continue
            scored.append(
                {
                    "paragraph": paragraph,
                    "page": store.pages.get(str(paragraph.get("page_id", "")), {}),
                    "score": float(score),
                    "chunk_projection": chunk_projection,
                }
            )
        scored.sort(key=lambda row: float(row.get("score", 0.0)), reverse=True)
        return scored[:top_k], "store_projection_search"

    paragraphs = list(store.paragraphs.values())
    rows: List[Dict[str, Any]] = []
    for paragraph, score in search_pages(paragraphs, query, top_k=max(top_k * 2, 12), project_id=project_id):
        pseudo_projection = {
            "chunk_id": paragraph.get("paragraph_id"),
            "document_id": paragraph.get("document_id"),
            "page_id": paragraph.get("page_id"),
            "doc_type": str((store.documents.get(str(paragraph.get("document_id", "")), {}) or {}).get("doc_type", "other")),
            "retrieval_text": paragraph.get("text", ""),
            "text_clean": paragraph.get("text", ""),
            "edge_types": [],
        }
        if not _projection_matches_filters(pseudo_projection, filters):
            continue
        if score <= 0:
            continue
        rows.append(
            {
                "paragraph": paragraph,
                "page": store.pages.get(str(paragraph.get("page_id", "")), {}),
                "score": float(score),
                "chunk_projection": pseudo_projection,
            }
        )
        if len(rows) >= top_k:
            break
    if rows:
        return rows, "legacy_paragraph_search"

    if not allow_generic_fallback:
        return [], "legacy_paragraph_search"

    fallback_rows: List[Dict[str, Any]] = []
    for paragraph in paragraphs:
        if not matches_corpus_scope(paragraph.get("project_id"), project_id):
            continue
        pseudo_projection = {
            "chunk_id": paragraph.get("paragraph_id"),
            "document_id": paragraph.get("document_id"),
            "page_id": paragraph.get("page_id"),
            "doc_type": str((store.documents.get(str(paragraph.get("document_id", "")), {}) or {}).get("doc_type", "other")),
            "retrieval_text": paragraph.get("text", ""),
            "text_clean": paragraph.get("text", ""),
            "edge_types": [],
        }
        if not _projection_matches_filters(pseudo_projection, filters):
            continue
        fallback_rows.append(
            {
                "paragraph": paragraph,
                "page": store.pages.get(str(paragraph.get("page_id", "")), {}),
                "score": 0.01,
                "chunk_projection": pseudo_projection,
            }
        )
        if len(fallback_rows) >= top_k:
            break
    return fallback_rows, "legacy_paragraph_search_fallback"


def _history_legal_context_flags(history_intent: Dict[str, Any]) -> Dict[str, bool]:
    return {
        "is_difc_context": bool(history_intent.get("is_difc_context")),
        "is_jurisdiction_question": bool(history_intent.get("is_jurisdiction_question")),
        "is_governing_law_question": bool(history_intent.get("is_governing_law_question")),
        "is_notice_mediated": bool(history_intent.get("is_notice_mediated")),
        "is_current_vs_historical_question": bool(history_intent.get("is_current_vs_historical_question")),
    }


def _history_resolution_guard(
    *,
    normalized_taxonomy_route: str | None,
    history_intent: Dict[str, Any],
) -> Tuple[bool, str]:
    if normalized_taxonomy_route != "law_relation_or_history":
        return False, ""
    if not history_intent:
        return True, "law_history_resolution_missing"
    requires_structural_resolution = bool(history_intent.get("requires_structural_resolution"))
    has_explicit_anchor = bool(history_intent.get("has_explicit_anchor"))
    if requires_structural_resolution and not has_explicit_anchor:
        return True, "law_history_resolution_missing"
    return False, ""


def _cross_law_compare_resolution_guard(
    *,
    normalized_taxonomy_route: str | None,
    compare_intent: Dict[str, Any],
) -> Tuple[bool, str]:
    if normalized_taxonomy_route != "cross_law_compare":
        return False, ""
    if not compare_intent:
        return True, "cross_law_compare_resolution_missing"
    compare_dimensions = (
        compare_intent.get("compare_dimensions", [])
        if isinstance(compare_intent.get("compare_dimensions"), list)
        else []
    )
    compare_operator = str(compare_intent.get("compare_operator") or "unknown")
    if not compare_dimensions or compare_operator == "unknown":
        return True, "cross_law_compare_resolution_missing"
    structural_resolution_required = bool(compare_intent.get("structural_resolution_required"))
    has_explicit_pair = bool(compare_intent.get("has_explicit_pair"))
    open_set_condition_query = bool(compare_intent.get("open_set_condition_query"))
    if structural_resolution_required and not has_explicit_pair and not open_set_condition_query:
        return True, "cross_law_compare_resolution_missing"
    if not open_set_condition_query and len(compare_intent.get("instrument_identifiers", []) or []) < 2:
        return True, "cross_law_compare_resolution_missing"
    return False, ""


def _history_doc_type(doc_type_raw: Any) -> str:
    value = str(doc_type_raw or "").strip().lower()
    if value in {"law", "regulation", "enactment_notice", "case"}:
        return value
    return "other"


def _cross_law_doc_type(doc_type_raw: Any) -> str:
    value = str(doc_type_raw or "").strip().lower()
    if value in {"law", "regulation", "enactment_notice"}:
        return value
    return "other"


def _cross_law_anchor_query(anchor: Dict[str, Any], *, question_text: str, expanded_query: str) -> str:
    parts: List[str] = [expanded_query or question_text]
    for key in ("title", "number", "year", "instrument_identifier"):
        token = _collapse_ws(anchor.get(key))
        if token:
            parts.append(token)
    instrument_type = _collapse_ws(anchor.get("instrument_type")).replace("_", " ")
    if instrument_type:
        parts.append(instrument_type)
    return _collapse_ws(" ".join(parts)) or question_text


def _cross_law_anchor_filters(anchor: Dict[str, Any], doc_type: str) -> Dict[str, Any]:
    filters: Dict[str, Any] = {"doc_type": doc_type}
    anchor_number = _collapse_ws(anchor.get("number"))
    anchor_year = _collapse_ws(anchor.get("year"))
    if not anchor_number and not anchor_year:
        return filters
    anchor_type = _cross_law_doc_type(anchor.get("instrument_type"))
    if anchor_type == "enactment_notice":
        if anchor_number:
            filters["notice_number"] = anchor_number
        if anchor_year:
            filters["notice_year"] = anchor_year
    elif anchor_type in {"law", "regulation"}:
        if anchor_number:
            filters["law_number"] = anchor_number
        if anchor_year:
            filters["law_year"] = anchor_year
    return filters


def _build_history_candidates(
    question_text: str,
    project_id: str,
    max_pages: int,
    *,
    route_name: str,
    answer_type: str,
    retrieval_profile: Any,
    history_intent: Dict[str, Any],
    history_retrieval_hints: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    if max_pages <= 0:
        return [], {
            "trace_version": "retrieval_stage_trace_v1",
            "route_name": route_name,
            "answer_type": answer_type,
            "profile_id": retrieval_profile.profile_id,
            "normalized_query": _normalize_query_text(question_text),
            "structural_lookup_enabled": retrieval_profile.structural_lookup_enabled,
            "lineage_expansion_enabled": retrieval_profile.lineage_expansion_enabled,
            "candidate_page_budget": int(max_pages),
            "used_page_budget": int(getattr(retrieval_profile, "used_page_limit", 0) or 0),
            "retrieval_skipped": True,
            "retrieval_skipped_reason": "zero_candidate_budget",
            "candidate_count": 0,
            "top_candidates": [],
            "law_history_lookup_resolution": history_intent,
            "legal_context_flags": _history_legal_context_flags(history_intent),
        }

    doc_type_priority = [
        _history_doc_type(item)
        for item in history_retrieval_hints.get("doc_type_priority", [])
        if _history_doc_type(item) in {"law", "regulation", "enactment_notice"}
    ]
    if not doc_type_priority:
        doc_type_priority = ["law", "regulation", "enactment_notice"]
    # Keep deterministic order while de-duplicating.
    doc_type_priority = list(dict.fromkeys(doc_type_priority))

    expanded_query = str(history_retrieval_hints.get("expanded_query") or question_text).strip() or question_text
    expansion_terms = _uniq(history_retrieval_hints.get("expansion_terms", []))
    relation_kind = str(history_intent.get("relation_kind") or "")
    version_filter = None
    if relation_kind == "current_version":
        version_filter = True
    elif relation_kind == "previous_version":
        version_filter = False

    top_k = max(max_pages * 2, 12)
    pass_trace: List[Dict[str, Any]] = []
    aggregated_candidates: List[Dict[str, Any]] = []
    retrieval_backends: List[str] = []

    def _run_pass(
        *,
        name: str,
        query: str,
        filters: Dict[str, Any] | None,
        allow_generic_fallback: bool,
    ) -> None:
        rows, backend = _search_candidates_route_aware(
            project_id=project_id,
            query=query,
            top_k=top_k,
            filters=filters,
            allow_generic_fallback=allow_generic_fallback,
        )
        retrieval_backends.append(backend)
        pass_trace.append(
            {
                "pass": name,
                "query": query,
                "filters": filters or {},
                "backend": backend,
                "candidate_count": len(rows),
            }
        )
        for row in rows:
            row.setdefault("retrieval_debug", {})
            row["retrieval_debug"]["history_pass"] = name
            aggregated_candidates.append(row)

    for doc_type in doc_type_priority:
        filters: Dict[str, Any] = {"doc_type": doc_type}
        if version_filter is not None:
            filters["is_current_version"] = version_filter
        _run_pass(
            name=f"history_doc_type_{doc_type}",
            query=expanded_query,
            filters=filters,
            allow_generic_fallback=False,
        )

    if relation_kind in {"notice_mediated_commencement", "commenced_on", "effective_from", "enacted_on"}:
        notice_query = _collapse_ws(f"{expanded_query} enactment notice commencement notice")
        _run_pass(
            name="history_notice_priority",
            query=notice_query,
            filters={"doc_type": "enactment_notice"},
            allow_generic_fallback=False,
        )

    if retrieval_profile.lineage_expansion_enabled and bool(history_retrieval_hints.get("lineage_expansion_enabled")):
        edge_type = _HISTORY_RELATION_EDGE_FILTER.get(relation_kind)
        if edge_type:
            lineage_filters: Dict[str, Any] = {"edge_type": edge_type}
            if version_filter is not None:
                lineage_filters["is_current_version"] = version_filter
            _run_pass(
                name="history_lineage_edge_expansion",
                query=_collapse_ws(f"{expanded_query} lineage history relation"),
                filters=lineage_filters,
                allow_generic_fallback=False,
            )

    fallback_used = False
    if not aggregated_candidates:
        fallback_used = True
        _run_pass(
            name="history_generic_lexical_fallback",
            query=expanded_query,
            filters=None,
            allow_generic_fallback=True,
        )

    # Deterministic dedupe by paragraph id while preserving strongest score and pass metadata.
    by_paragraph_id: Dict[str, Dict[str, Any]] = {}
    for candidate in aggregated_candidates:
        paragraph_id = str((_paragraph_for_candidate(candidate)).get("paragraph_id", ""))
        if not paragraph_id:
            continue
        doc_type = _history_doc_type(_projection_for_candidate(candidate).get("doc_type"))
        doc_priority_rank = (
            doc_type_priority.index(doc_type) if doc_type in doc_type_priority else len(doc_type_priority)
        )
        boosted_score = float(candidate.get("score", 0.0) or 0.0) + max(0.0, 0.06 - (doc_priority_rank * 0.02))
        existing = by_paragraph_id.get(paragraph_id)
        if not existing or boosted_score > float(existing.get("score", 0.0) or 0.0):
            candidate["score"] = round(boosted_score, 4)
            by_paragraph_id[paragraph_id] = candidate

    ordered, stage_trace = _rerank_candidates(
        question_text=expanded_query,
        route_name=route_name,
        answer_type=answer_type,
        candidates=list(by_paragraph_id.values()),
        retrieval_profile=retrieval_profile,
        lookup_intent=None,
        retrieval_backend="+".join(_uniq(retrieval_backends)) or "history_route_aware",
    )
    stage_trace["retrieval_strategy"] = "history_lineage_route_aware_v1"
    stage_trace["retrieval_profile_selected"] = retrieval_profile.profile_id
    stage_trace["history_doc_type_priority"] = doc_type_priority
    stage_trace["history_query_expansion_terms"] = expansion_terms
    stage_trace["history_relation_kind"] = relation_kind or None
    stage_trace["history_passes"] = pass_trace
    stage_trace["lineage_expansion_requested"] = bool(history_retrieval_hints.get("lineage_expansion_enabled"))
    stage_trace["retrieval_fallback_traced"] = fallback_used
    if fallback_used:
        stage_trace["retrieval_fallback_reason"] = "history_route_aware_candidates_empty"
    stage_trace["law_history_lookup_resolution"] = history_intent
    stage_trace["legal_context_flags"] = _history_legal_context_flags(history_intent)
    return ordered[:max_pages], stage_trace


def _build_cross_law_compare_candidates(
    question_text: str,
    project_id: str,
    max_pages: int,
    *,
    route_name: str,
    answer_type: str,
    retrieval_profile: Any,
    compare_intent: Dict[str, Any],
    compare_retrieval_hints: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    if max_pages <= 0:
        return [], {
            "trace_version": "retrieval_stage_trace_v1",
            "route_name": route_name,
            "answer_type": answer_type,
            "profile_id": retrieval_profile.profile_id,
            "normalized_query": _normalize_query_text(question_text),
            "structural_lookup_enabled": retrieval_profile.structural_lookup_enabled,
            "lineage_expansion_enabled": retrieval_profile.lineage_expansion_enabled,
            "candidate_page_budget": int(max_pages),
            "used_page_budget": int(getattr(retrieval_profile, "used_page_limit", 0) or 0),
            "retrieval_skipped": True,
            "retrieval_skipped_reason": "zero_candidate_budget",
            "candidate_count": 0,
            "top_candidates": [],
            "cross_law_compare_resolution": compare_intent,
            "cross_law_compare_retrieval_hints": compare_retrieval_hints,
        }

    doc_type_priority = [
        _cross_law_doc_type(item)
        for item in compare_retrieval_hints.get("doc_type_priority", [])
        if _cross_law_doc_type(item) in {"law", "regulation", "enactment_notice"}
    ]
    if not doc_type_priority:
        doc_type_priority = ["law", "regulation", "enactment_notice"]
    doc_type_priority = list(dict.fromkeys(doc_type_priority))

    expanded_query = str(compare_retrieval_hints.get("expanded_query") or question_text).strip() or question_text
    expansion_terms = _uniq(compare_retrieval_hints.get("expansion_terms", []))
    requires_notice_expansion = bool(compare_retrieval_hints.get("requires_notice_expansion"))
    requires_lineage_expansion = bool(compare_retrieval_hints.get("requires_lineage_expansion"))
    open_set_condition_query = bool(compare_intent.get("open_set_condition_query"))

    instrument_anchors = [
        item
        for item in (compare_intent.get("instrument_anchors", []) if isinstance(compare_intent.get("instrument_anchors"), list) else [])
        if isinstance(item, dict)
    ]
    if not instrument_anchors:
        for identifier in compare_intent.get("instrument_identifiers", []) if isinstance(compare_intent.get("instrument_identifiers"), list) else []:
            token = _collapse_ws(identifier)
            if not token:
                continue
            instrument_anchors.append(
                {
                    "instrument_identifier": token,
                    "title": token.replace("_", " "),
                    "instrument_type": "law",
                }
            )

    top_k = max(max_pages * 2, 16)
    pass_trace: List[Dict[str, Any]] = []
    aggregated_candidates: List[Dict[str, Any]] = []
    retrieval_backends: List[str] = []
    backfill_passes = 0

    def _run_pass(
        *,
        name: str,
        query: str,
        filters: Dict[str, Any] | None,
    ) -> None:
        rows, backend = _search_candidates_route_aware(
            project_id=project_id,
            query=query,
            top_k=top_k,
            filters=filters,
            allow_generic_fallback=False,
        )
        retrieval_backends.append(backend)
        pass_trace.append(
            {
                "pass": name,
                "query": query,
                "filters": filters or {},
                "backend": backend,
                "candidate_count": len(rows),
            }
        )
        for row in rows:
            row.setdefault("retrieval_debug", {})
            row["retrieval_debug"]["cross_law_pass"] = name
            aggregated_candidates.append(row)

    if instrument_anchors:
        for idx, anchor in enumerate(instrument_anchors):
            anchor_query = _cross_law_anchor_query(anchor, question_text=question_text, expanded_query=expanded_query)
            anchor_slug = _collapse_ws(anchor.get("instrument_identifier") or anchor.get("title") or f"instrument_{idx}")
            anchor_slug = re.sub(r"[^a-zA-Z0-9_]+", "_", anchor_slug).strip("_") or f"instrument_{idx}"
            for doc_type in doc_type_priority:
                _run_pass(
                    name=f"cross_law_anchor_{idx}_{anchor_slug}_{doc_type}",
                    query=anchor_query,
                    filters=_cross_law_anchor_filters(anchor, doc_type),
                )
    elif open_set_condition_query:
        for doc_type in doc_type_priority:
            _run_pass(
                name=f"cross_law_open_set_{doc_type}",
                query=expanded_query,
                filters={"doc_type": doc_type},
            )

    if requires_notice_expansion:
        _run_pass(
            name="cross_law_notice_expansion",
            query=_collapse_ws(f"{expanded_query} enactment notice commencement notice effective date came into force"),
            filters={"doc_type": "enactment_notice"},
        )

    if retrieval_profile.lineage_expansion_enabled and requires_lineage_expansion:
        for edge_type in ("enabled_by", "refers_to"):
            _run_pass(
                name=f"cross_law_lineage_{edge_type}",
                query=_collapse_ws(f"{expanded_query} amendment repeal supersession lineage history"),
                filters={"edge_type": edge_type},
            )

    def _dedupe_candidates(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        by_paragraph_id: Dict[str, Dict[str, Any]] = {}
        for candidate in rows:
            paragraph_id = str((_paragraph_for_candidate(candidate)).get("paragraph_id", ""))
            if not paragraph_id:
                continue
            doc_type = _cross_law_doc_type(_projection_for_candidate(candidate).get("doc_type"))
            doc_priority_rank = (
                doc_type_priority.index(doc_type) if doc_type in doc_type_priority else len(doc_type_priority)
            )
            boosted_score = float(candidate.get("score", 0.0) or 0.0) + max(0.0, 0.05 - (doc_priority_rank * 0.015))
            existing = by_paragraph_id.get(paragraph_id)
            if not existing or boosted_score > float(existing.get("score", 0.0) or 0.0):
                candidate["score"] = round(boosted_score, 4)
                by_paragraph_id[paragraph_id] = candidate
        return list(by_paragraph_id.values())

    deduped_candidates = _dedupe_candidates(aggregated_candidates)
    coverage_counts = annotate_cross_law_candidate_instruments(deduped_candidates, compare_intent)
    expected_instrument_ids = [
        token
        for token in (compare_intent.get("instrument_identifiers", []) if isinstance(compare_intent.get("instrument_identifiers"), list) else [])
        if _collapse_ws(token)
    ]
    missing_instruments = [
        token
        for token in expected_instrument_ids
        if token not in coverage_counts
    ]

    if missing_instruments and instrument_anchors:
        anchor_by_id = {
            str(item.get("instrument_identifier") or ""): item
            for item in instrument_anchors
            if str(item.get("instrument_identifier") or "").strip()
        }
        for missing_identifier in missing_instruments:
            anchor = anchor_by_id.get(missing_identifier)
            if not anchor:
                continue
            backfill_passes += 1
            _run_pass(
                name=f"cross_law_backfill_{re.sub(r'[^a-zA-Z0-9_]+', '_', missing_identifier)}",
                query=_cross_law_anchor_query(anchor, question_text=question_text, expanded_query=question_text),
                filters=None,
            )
        deduped_candidates = _dedupe_candidates(aggregated_candidates)
        coverage_counts = annotate_cross_law_candidate_instruments(deduped_candidates, compare_intent)
        missing_instruments = [
            token
            for token in expected_instrument_ids
            if token not in coverage_counts
        ]

    ordered, stage_trace = _rerank_candidates(
        question_text=expanded_query,
        route_name=route_name,
        answer_type=answer_type,
        candidates=deduped_candidates,
        retrieval_profile=retrieval_profile,
        lookup_intent=compare_intent.get("article_lookup_intent"),
        retrieval_backend="+".join(_uniq(retrieval_backends)) or "cross_law_route_aware",
    )
    annotate_cross_law_candidate_instruments(ordered, compare_intent)
    used_coverage_counts = annotate_cross_law_candidate_instruments(ordered[:max_pages], compare_intent)

    stage_trace["retrieval_strategy"] = "cross_law_compare_route_aware_v1"
    stage_trace["retrieval_profile_selected"] = retrieval_profile.profile_id
    stage_trace["cross_law_compare_resolution"] = compare_intent
    stage_trace["cross_law_compare_retrieval_hints"] = compare_retrieval_hints
    stage_trace["cross_law_compare_doc_type_priority"] = doc_type_priority
    stage_trace["cross_law_compare_query_expansion_terms"] = expansion_terms
    stage_trace["cross_law_compare_notice_expansion_requested"] = requires_notice_expansion
    stage_trace["cross_law_compare_lineage_expansion_requested"] = requires_lineage_expansion
    stage_trace["cross_law_compare_passes"] = pass_trace
    stage_trace["cross_law_compare_instrument_coverage"] = {
        "expected_instrument_ids": expected_instrument_ids,
        "candidate_counts_by_instrument": coverage_counts,
        "used_candidate_counts_by_instrument": used_coverage_counts,
        "missing_instrument_ids": missing_instruments,
        "coverage_complete": not bool(missing_instruments),
    }
    stage_trace["retrieval_fallback_traced"] = bool(backfill_passes)
    if backfill_passes:
        stage_trace["retrieval_fallback_reason"] = "cross_law_instrument_backfill_pass"
    return ordered[:max_pages], stage_trace


def _rerank_candidates(
    *,
    question_text: str,
    route_name: str,
    answer_type: str,
    candidates: List[Dict[str, Any]],
    retrieval_profile: Any,
    lookup_intent: Dict[str, Any] | None = None,
    retrieval_backend: str = "",
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    question_structure = _question_structure(question_text, lookup_intent=lookup_intent)
    structural_candidates: List[Dict[str, Any]] = []
    lexical_candidates: List[Dict[str, Any]] = []
    exact_identifier_hits = 0
    lineage_hits = 0
    current_version_hits = 0
    structural_identifier_hits = 0
    semantic_identifier_hits = 0

    for candidate in candidates:
        projection = _projection_for_candidate(candidate)
        paragraph = _paragraph_for_candidate(candidate)
        base_score = float(candidate.get("score", 0.0) or 0.0)
        if base_score <= 0:
            base_score = score_candidate(
                question_structure["normalized_query"],
                projection.get("retrieval_text", projection.get("text_clean", paragraph.get("text", ""))),
            )
        features = _candidate_retrieval_features(
            candidate,
            question_structure=question_structure,
            route_name=route_name,
        )
        exact_identifier_hit = bool(features["exact_identifier_hit"])
        lineage_signal = bool(features["lineage_signal"])
        current_version_hit = bool(features["current_version_hit"])
        structural_identifier_hit = bool(
            features["structure_hits"].get("article")
            or features["structure_hits"].get("section")
            or features["structure_hits"].get("paragraph")
            or features["structure_hits"].get("clause")
            or features["structure_hits"].get("schedule")
        )
        exact_identifier_hits += 1 if exact_identifier_hit else 0
        lineage_hits += 1 if lineage_signal else 0
        current_version_hits += 1 if current_version_hit else 0
        structural_identifier_hits += 1 if structural_identifier_hit else 0
        proposition_features = proposition_match_features(
            question_text=question_text,
            question_structure=question_structure,
            candidate=candidate,
        )
        semantic_identifier_hits += 1 if proposition_features.get("semantic_terms_hit_count", 0) else 0

        final_score = float(base_score)
        chunk_only_score = float(base_score)
        stage = "lexical_projected"
        reasons: List[str] = []
        if exact_identifier_hit:
            final_score += 0.35
            chunk_only_score += 0.35
            reasons.append("exact_identifier_hit")
        if current_version_hit and route_name != "history_lineage":
            final_score += 0.06
            chunk_only_score += 0.06
            reasons.append("current_version_soft_boost")
        if lineage_signal and route_name == "history_lineage":
            final_score += 0.15
            chunk_only_score += 0.15
            reasons.append("lineage_signal")
        if route_name == "article_lookup" and features["structure_hits"]["article"]:
            final_score += 0.2
            chunk_only_score += 0.2
            reasons.append("article_lookup_structural_match")
        if route_name == "article_lookup" and features["structure_hits"]["law_number"]:
            final_score += 0.15
            chunk_only_score += 0.15
            reasons.append("article_lookup_law_number_match")
        if route_name == "article_lookup" and features["structure_hits"]["law_year"]:
            final_score += 0.08
            chunk_only_score += 0.08
            reasons.append("article_lookup_law_year_match")
        if route_name == "article_lookup" and features["structure_hits"]["law_title"]:
            final_score += 0.12
            chunk_only_score += 0.12
            reasons.append("article_lookup_law_title_match")
        if route_name == "article_lookup" and features["structure_hits"]["doc_type"]:
            final_score += 0.05
            chunk_only_score += 0.05
            reasons.append("article_lookup_doc_type_match")
        if route_name == "single_case_extraction" and features["structure_hits"]["case_number"]:
            final_score += 0.2
            chunk_only_score += 0.2
            reasons.append("case_lookup_structural_match")
        semantic_boost = float(proposition_features.get("semantic_boost", 0.0))
        if proposition_features.get("semantic_boost", 0.0) > 0:
            final_score += semantic_boost
            reasons.append("semantic_proposition_match")
        if retrieval_profile.structural_lookup_enabled and any(features["structure_hits"].values()):
            final_score += 0.5
            chunk_only_score += 0.5
            stage = "structural_lookup"
            reasons.append("structural_lookup_priority")
        elif proposition_features.get("semantic_boost", 0.0) >= 0.18:
            stage = "semantic_proposition"

        row = {
            **candidate,
            "score": round(final_score, 4),
            "exact_identifier_hit": exact_identifier_hit,
            "lineage_signal": lineage_signal,
            "retrieval_debug": {
                "stage": stage,
                "base_score": round(base_score, 4),
                "chunk_only_score": round(chunk_only_score, 4),
                "final_score": round(final_score, 4),
                "semantic_boost": round(semantic_boost, 4),
                "reasons": reasons,
                "structure_hits": features["structure_hits"],
                "semantic_terms_hit_count": proposition_features.get("semantic_terms_hit_count", 0),
                "top_proposition_score": proposition_features.get("top_proposition_score", 0.0),
                "second_proposition_score": proposition_features.get("second_proposition_score", 0.0),
                "top_proposition": proposition_features.get("top_proposition"),
            },
        }
        if stage == "structural_lookup":
            structural_candidates.append(row)
        else:
            lexical_candidates.append(row)

    structural_candidates.sort(key=lambda row: float(row.get("score", 0.0)), reverse=True)
    lexical_candidates.sort(key=lambda row: float(row.get("score", 0.0)), reverse=True)
    ordered: List[Dict[str, Any]] = []
    seen = set()
    for row in [*structural_candidates, *lexical_candidates]:
        paragraph_id = str((_paragraph_for_candidate(row)).get("paragraph_id", ""))
        if not paragraph_id or paragraph_id in seen:
            continue
        seen.add(paragraph_id)
        ordered.append(row)
    chunk_only_ordered = sorted(
        ordered,
        key=lambda row: float(((row.get("retrieval_debug") or {}).get("chunk_only_score", row.get("score", 0.0)) or 0.0)),
        reverse=True,
    )

    stage_trace = {
        "trace_version": "retrieval_stage_trace_v1",
        "route_name": route_name,
        "answer_type": answer_type,
        "profile_id": retrieval_profile.profile_id,
        "retrieval_backend": retrieval_backend or "unspecified",
        "normalized_query": question_structure["normalized_query"],
        "structural_lookup_enabled": retrieval_profile.structural_lookup_enabled,
        "lineage_expansion_enabled": retrieval_profile.lineage_expansion_enabled,
        "exact_identifier_hit_count": exact_identifier_hits,
        "structural_identifier_hit_count": structural_identifier_hits,
        "lineage_signal_count": lineage_hits,
        "current_version_hit_count": current_version_hits,
        "semantic_identifier_hit_count": semantic_identifier_hits,
        "lookup_intent": question_structure.get("lookup_intent", {}),
        "candidate_count": len(ordered),
        "top_candidates": [
            {
                "paragraph_id": str(_paragraph_for_candidate(row).get("paragraph_id", "")),
                "source_page_id": str((_fetch_page_for_candidate(row) or {}).get("source_page_id", "")),
                "stage": str((row.get("retrieval_debug") or {}).get("stage", "")),
                "chunk_only_score": float((row.get("retrieval_debug") or {}).get("chunk_only_score", 0.0)),
                "score": float(row.get("score", 0.0)),
                "semantic_boost": float((row.get("retrieval_debug") or {}).get("semantic_boost", 0.0)),
                "reasons": list((row.get("retrieval_debug") or {}).get("reasons", [])),
            }
            for row in ordered[: min(8, len(ordered))]
        ],
        "chunk_only_top_candidates": [
            {
                "paragraph_id": str(_paragraph_for_candidate(row).get("paragraph_id", "")),
                "source_page_id": str((_fetch_page_for_candidate(row) or {}).get("source_page_id", "")),
                "stage": str((row.get("retrieval_debug") or {}).get("stage", "")),
                "chunk_only_score": float((row.get("retrieval_debug") or {}).get("chunk_only_score", 0.0)),
                "score": float(row.get("score", 0.0)),
                "semantic_boost": float((row.get("retrieval_debug") or {}).get("semantic_boost", 0.0)),
                "reasons": list((row.get("retrieval_debug") or {}).get("reasons", [])),
            }
            for row in chunk_only_ordered[: min(8, len(chunk_only_ordered))]
        ],
    }
    return ordered, stage_trace


def _build_candidates(
    question_text: str,
    project_id: str,
    max_pages: int,
    *,
    route_name: str,
    answer_type: str,
    retrieval_profile: Any,
    lookup_intent: Dict[str, Any] | None = None,
    enforce_structural_for_article: bool = False,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    intent = lookup_intent or resolve_law_article_lookup_intent(question_text)
    if max_pages <= 0:
        return [], {
            "trace_version": "retrieval_stage_trace_v1",
            "route_name": route_name,
            "answer_type": answer_type,
            "profile_id": retrieval_profile.profile_id,
            "normalized_query": _normalize_query_text(question_text),
            "lookup_intent": intent,
            "structural_lookup_enabled": retrieval_profile.structural_lookup_enabled,
            "lineage_expansion_enabled": retrieval_profile.lineage_expansion_enabled,
            "candidate_page_budget": int(max_pages),
            "used_page_budget": int(getattr(retrieval_profile, "used_page_limit", 0) or 0),
            "retrieval_skipped": True,
            "retrieval_skipped_reason": "zero_candidate_budget",
            "exact_identifier_hit_count": 0,
            "lineage_signal_count": 0,
            "current_version_hit_count": 0,
            "candidate_count": 0,
            "top_candidates": [],
        }

    retrieval_backend = "legacy_paragraph_search"
    if corpus_pg.enabled():
        retrieval_backend = "pg_search_candidates"
        base_candidates = corpus_pg.search_candidates(project_id=project_id, query=question_text, top_k=max(max_pages * 2, 12))
    elif store.feature_flags.get("canonical_chunk_model_v1", True) and store.chunk_search_documents:
        retrieval_backend = "store_projection_search"
        scored: List[Dict[str, Any]] = []
        for chunk_projection in store.chunk_search_documents.values():
            paragraph = store.paragraphs.get(chunk_projection.get("chunk_id"))
            if not paragraph:
                continue
            if not matches_corpus_scope(paragraph.get("project_id"), project_id):
                continue
            score = score_candidate(question_text, chunk_projection.get("retrieval_text", chunk_projection.get("text_clean", "")))
            if score <= 0:
                continue
            scored.append(
                {
                    "paragraph": paragraph,
                    "page": store.pages.get(str(paragraph.get("page_id", "")), {}),
                    "score": float(score),
                    "chunk_projection": chunk_projection,
                }
            )
        scored.sort(key=lambda row: row["score"], reverse=True)
        base_candidates = scored[: max(max_pages * 2, 12)]
    else:
        paragraphs = list(store.paragraphs.values())
        scored = search_pages(paragraphs, question_text, top_k=max(max_pages * 2, 12), project_id=project_id)
        base_candidates = [{"paragraph": p, "page": store.pages.get(str(p.get("page_id", "")), {}), "score": float(s)} for p, s in scored]

    question_structure = _question_structure(question_text, lookup_intent=intent)
    if retrieval_profile.structural_lookup_enabled and any(
        question_structure[key]
        for key in ("article_refs", "section_refs", "paragraph_refs", "clause_refs", "part_refs", "schedule_refs")
    ):
        projected_candidates = _all_projected_candidates(project_id)
        structural_only = [
            {
                **candidate,
                "score": 1.0,
            }
            for candidate in projected_candidates
            if any(_structural_match(question_structure, candidate).values())
        ]
        if structural_only:
            retrieval_backend = f"{retrieval_backend}+structural_lookup"
            base_candidates = structural_only + base_candidates

    ordered, stage_trace = _rerank_candidates(
        question_text=question_text,
        route_name=route_name,
        answer_type=answer_type,
        candidates=base_candidates,
        retrieval_profile=retrieval_profile,
        lookup_intent=intent,
        retrieval_backend=retrieval_backend,
    )
    if enforce_structural_for_article and route_name == "article_lookup":
        explicit_provision_identifier = any(
            bool(intent.get(key))
            for key in ("article_identifier", "section_identifier", "paragraph_identifier", "clause_identifier", "schedule_identifier")
        )
        structural_matches = [
            row
            for row in ordered
            if any(
                bool((row.get("retrieval_debug") or {}).get("structure_hits", {}).get(key, False))
                for key in ("article", "section", "paragraph", "clause", "schedule")
            )
        ]
        if intent.get("requires_structural_lookup") and not structural_matches and not explicit_provision_identifier:
            stage_trace["retrieval_blocked"] = True
            stage_trace["retrieval_blocked_reason"] = "law_article_no_structural_identifier_match"
            stage_trace["retrieval_fallback_traced"] = True
            stage_trace["retrieval_fallback_reason"] = "generic_lexical_fallback_disabled_for_law_article_lookup"
            stage_trace["candidate_count"] = 0
            stage_trace["top_candidates"] = []
            return [], stage_trace
        if intent.get("requires_structural_lookup") and not structural_matches and explicit_provision_identifier:
            stage_trace["retrieval_fallback_traced"] = True
            stage_trace["retrieval_fallback_reason"] = "article_lookup_explicit_provision_lexical_backstop"
    return ordered[:max_pages], stage_trace


def _normalize_source_page(page: Dict[str, Any], project_id: str) -> tuple[str, int, str]:
    source_page_id = str(page.get("source_page_id", f"{project_id or 'doc'}_0"))
    if "_" in source_page_id:
        base, suffix = source_page_id.rsplit("_", 1)
        if suffix.isdigit():
            return source_page_id, int(suffix), base
    return f"{source_page_id}_0", 0, source_page_id.split("_")[0] if source_page_id else (project_id or "doc")


def _to_page_ref(candidate: Dict[str, Any], project_id: str, used: bool, *, page_index_base: int) -> Dict[str, Any]:
    paragraph = candidate["paragraph"]
    page = candidate.get("page") or store.pages.get(paragraph.get("page_id"), {})
    projection = _projection_for_candidate(candidate)
    source_page_id, page_num, pdf_id = _normalize_source_page(page, project_id)
    return {
        "project_id": project_id,
        "document_id": paragraph.get("document_id"),
        "pdf_id": pdf_id.replace(" ", "_"),
        "page_num": page_num,
        "page_index_base": page_index_base,
        "source_page_id": source_page_id,
        "used": used,
        "evidence_role": "primary" if used else "supporting",
        "score": min(1.0, float(candidate["score"])),
        "chunk_id": paragraph.get("paragraph_id"),
        "chunk_text": str(paragraph.get("text", ""))[:320],
        "article_refs": list(paragraph.get("article_refs", [])) if isinstance(paragraph.get("article_refs"), list) else [],
        "entity_names": list(projection.get("entity_names", [])) if isinstance(projection.get("entity_names"), list) else [],
        "exact_terms": list(projection.get("exact_terms", [])) if isinstance(projection.get("exact_terms"), list) else [],
        "exact_identifier_hit": bool(candidate.get("exact_identifier_hit")),
        "lineage_signal": bool(candidate.get("lineage_signal")),
        "compare_instrument_identifier": _collapse_ws(candidate.get("compare_instrument_identifier")),
        "compare_instrument_label": _collapse_ws(candidate.get("compare_instrument_label")),
    }


def _build_question_from_dataset(
    project_id: str,
    dataset_id: str,
    question_id: str,
    runtime_policy: RuntimePolicy,
) -> QueryRequest:
    if runtime_pg.enabled():
        payload = runtime_pg.get_question_payload(dataset_id, question_id)
    else:
        payload = store.get_question_payload(dataset_id, question_id)
    if not isinstance(payload, dict):
        raise HTTPException(status_code=404, detail="dataset question not found")
    answer_type = str(payload.get("answer_type", "free_text"))
    if answer_type not in ALLOWED_ANSWER_TYPES:
        answer_type = "free_text"
    return QueryRequest(
        project_id=project_id,
        question=Question(
            id=question_id,
            question=str(payload.get("question", f"Question {question_id}")),
            answer_type=answer_type,
            source=payload.get("source", "manual"),
            difficulty=payload.get("difficulty", "easy"),
            route_hint=payload.get("route_hint"),
            dataset_id=dataset_id,
            tags=payload.get("tags", []),
        ),
        runtime_policy=runtime_policy,
    )


def _safe_json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_safe_json_value(item) for item in value[:8]]
    if isinstance(value, dict):
        return {str(key): _safe_json_value(item) for key, item in list(value.items())[:12]}
    return str(value)


def _build_answer_normalization_trace(
    *,
    raw_answer: Any,
    normalized_answer: Any,
    normalized_text: str | None,
    answer_type: str,
    abstained: bool,
) -> Dict[str, Any]:
    normalization_applied = raw_answer != normalized_answer or (
        isinstance(normalized_answer, list) and normalized_text is not None
    )
    return {
        "trace_version": "answer_normalization_trace_v1",
        "answer_type": answer_type,
        "abstained": abstained,
        "raw_answer": _safe_json_value(raw_answer),
        "normalized_answer": _safe_json_value(normalized_answer),
        "normalized_text": normalized_text,
        "normalization_applied": bool(normalization_applied),
    }


def _article_resolution_guard(
    *,
    route_name: str,
    normalized_taxonomy_route: str | None,
    lookup_intent: Dict[str, Any],
) -> Tuple[bool, str]:
    if route_name != "article_lookup":
        return False, ""
    if normalized_taxonomy_route != "law_article_lookup":
        return False, ""
    confidence = float(lookup_intent.get("provision_lookup_confidence", 0.0) or 0.0)
    requires_structural_lookup = bool(lookup_intent.get("requires_structural_lookup"))
    if requires_structural_lookup and confidence >= 0.5:
        return False, ""
    return True, "law_article_resolution_missing"


async def _free_text_with_llm(
    route_name: str,
    question_text: str,
    policy_version: str,
    *,
    evidence_snippets: List[str],
) -> Tuple[str, Dict[str, int]]:
    compact_snippets = [_collapse_ws(item) for item in evidence_snippets if _collapse_ws(item)]
    grounded_context = "\n".join(f"- {item[:280]}" for item in compact_snippets[:3]) or "- no grounded snippets provided"
    prompt = (
        "Answer in one short sentence only. Be factual, concise, and use only grounded evidence."
        f" Route family: {route_name}. "
        f"Scoring policy: {policy_version}. "
        f"Question: {question_text}\n"
        f"Evidence snippets:\n{grounded_context}"
    )
    return await llm_client.complete_chat(
        prompt,
        user_context={
            "route_name": route_name,
            "policy_version": policy_version,
            "grounded_snippet_count": len(compact_snippets),
        },
    )


def _normalize_question_payload(raw: Dict[str, Any], dataset_id: str) -> Dict[str, Any]:
    qid = str(raw.get("id") or "").strip()
    text = str(raw.get("question") or "").strip()
    answer_type = str(raw.get("answer_type") or "free_text").strip()
    if not qid:
        raise ValueError("question id is required")
    if not text:
        raise ValueError("question text is required")
    if answer_type not in ALLOWED_ANSWER_TYPES:
        answer_type = "free_text"

    question = Question(
        id=qid,
        dataset_id=dataset_id,
        question=text,
        answer_type=answer_type,
        source=raw.get("source", "manual"),
        difficulty=raw.get("difficulty", "easy"),
        route_hint=raw.get("route_hint"),
        tags=raw.get("tags", []),
    )
    return question.model_dump(mode="json", exclude_none=True)


def _load_public_dataset(limit: int) -> List[Dict[str, Any]]:
    if not PUBLIC_DATASET_PATH.exists():
        raise HTTPException(status_code=404, detail="official questions dataset not found")
    payload = json.loads(PUBLIC_DATASET_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise HTTPException(status_code=422, detail="public dataset must be a list")
    if limit > 0:
        return payload[:limit]
    return payload


def _fetch_page_for_candidate(candidate: Dict[str, Any]) -> Dict[str, Any]:
    paragraph = candidate.get("paragraph", {}) if isinstance(candidate.get("paragraph"), dict) else {}
    page = candidate.get("page")
    if isinstance(page, dict) and page:
        return page
    page_id = str(paragraph.get("page_id", ""))
    if not page_id:
        return {}
    if corpus_pg.enabled():
        return corpus_pg.get_page(page_id) or {}
    return store.pages.get(page_id, {})


def _fetch_document(document_id: str) -> Dict[str, Any]:
    if not document_id:
        return {}
    if corpus_pg.enabled():
        return corpus_pg.get_document_with_processing(document_id) or corpus_pg.get_document(document_id) or {}
    return store.documents.get(document_id, {})


def _build_document_viewer_state(
    *,
    project_id: str,
    candidates: List[Dict[str, Any]],
    used_source_page_ids: List[str],
) -> Dict[str, Any]:
    documents: Dict[str, Dict[str, Any]] = {}
    for candidate in candidates:
        paragraph = candidate.get("paragraph", {}) if isinstance(candidate.get("paragraph"), dict) else {}
        page = _fetch_page_for_candidate(candidate)
        source_page_id = str(page.get("source_page_id", ""))
        document_id = str(paragraph.get("document_id", ""))
        if not document_id:
            continue
        entry = documents.setdefault(
            document_id,
            {
                "document_id": document_id,
                "title": None,
                "pdf_id": None,
                "file_url": f"/v1/corpus/documents/{document_id}/file",
                "pages": [],
            },
        )
        document = _fetch_document(document_id)
        entry["title"] = document.get("title") or document.get("citation_title") or document.get("pdf_id") or document_id
        entry["pdf_id"] = document.get("pdf_id")
        entry["doc_type"] = document.get("doc_type")
        page_item = {
            "page_id": page.get("page_id"),
            "page_num": page.get("page_num", 0),
            "source_page_id": source_page_id,
            "used": source_page_id in used_source_page_ids,
            "chunk_id": paragraph.get("paragraph_id"),
            "chunk_text": str(paragraph.get("text", ""))[:320],
        }
        if page_item not in entry["pages"]:
            entry["pages"].append(page_item)

    ordered_docs = sorted(documents.values(), key=lambda row: str(row.get("title", "")))
    default_document = ordered_docs[0] if ordered_docs else {}
    default_used_page = next(
        (page for page in default_document.get("pages", []) if page.get("used")),
        (default_document.get("pages") or [{}])[0] if default_document.get("pages") else {},
    )
    return {
        "project_id": project_id,
        "documents": ordered_docs,
        "default_document_id": default_document.get("document_id"),
        "default_page_id": default_used_page.get("page_id"),
        "default_source_page_id": default_used_page.get("source_page_id"),
    }


def _telemetry_shadow_map(
    telemetry: Any,
    retrieval_profile: Any,
    *,
    route_name: str,
    no_answer_fast_path_triggered: bool,
) -> Dict[str, Any]:
    return {
        "mapping_version": "shadow_otel_genai_v1",
        "gen_ai": {
            "route_name": route_name,
            "profile_id": str(getattr(retrieval_profile, "profile_id", "")),
            "model_name": str(getattr(telemetry, "model_name", "")),
            "trace_id": str(getattr(telemetry, "trace_id", "")),
            "ttft_ms": int(getattr(telemetry, "ttft_ms", 0) or 0),
            "total_response_ms": int(getattr(telemetry, "total_response_ms", 0) or 0),
            "input_tokens": int(getattr(telemetry, "input_tokens", 0) or 0),
            "output_tokens": int(getattr(telemetry, "output_tokens", 0) or 0),
            "candidate_page_budget": int(getattr(retrieval_profile, "candidate_page_limit", 0) or 0),
            "used_page_budget": int(getattr(retrieval_profile, "used_page_limit", 0) or 0),
            "no_answer_fast_path_triggered": bool(no_answer_fast_path_triggered),
        },
    }


def _retrieval_quality_features(
    *,
    candidates: List[Dict[str, Any]],
    evidence_selection_trace: Dict[str, Any],
) -> Dict[str, Any]:
    scores = []
    exact_identifier_hits = 0
    consensus_values: List[str] = []
    for candidate in candidates:
        try:
            scores.append(float(candidate.get("score", 0.0)))
        except (TypeError, ValueError):
            scores.append(0.0)
        if candidate.get("exact_identifier_hit"):
            exact_identifier_hits += 1
        retrieval_debug = candidate.get("retrieval_debug")
        if isinstance(retrieval_debug, dict):
            consensus_values.extend(str(item) for item in retrieval_debug.get("reasons", []) if str(item).strip())
    top_score = scores[0] if scores else 0.0
    second_score = scores[1] if len(scores) > 1 else 0.0
    unique_page_count = len(list(evidence_selection_trace.get("retrieved_source_page_ids", [])))
    return {
        "feature_version": "retrieval_quality_features_v1",
        "top_candidate_score": round(top_score, 4),
        "top_candidate_score_gap": round(top_score - second_score, 4),
        "exact_identifier_hit_count": exact_identifier_hits,
        "unique_page_count": unique_page_count,
        "page_collapse_ratio": float(evidence_selection_trace.get("page_collapse_ratio", 0.0) or 0.0),
        "candidate_consensus_signal_count": len(_uniq(consensus_values)),
    }


def _apply_retrieval_aware_abstain(
    *,
    answer_type: str,
    route_name: str,
    candidates: List[Dict[str, Any]],
    current_abstained: bool,
    current_answer: Any,
    confidence: float,
    retrieval_features: Dict[str, Any],
) -> Tuple[bool, Any, float, str]:
    if current_abstained:
        if float(retrieval_features.get("top_candidate_score", 0.0)) <= 0.0:
            return True, current_answer, 0.0, "no_corpus_support"
        if float(retrieval_features.get("candidate_consensus_signal_count", 0.0)) <= 0.0:
            return True, current_answer, 0.0, "insufficient_uniqueness"
        return True, current_answer, 0.0, "conflicting_evidence"

    if answer_type != "free_text":
        return False, current_answer, confidence, ""

    top_gap = float(retrieval_features.get("top_candidate_score_gap", 0.0))
    top_score = float(retrieval_features.get("top_candidate_score", 0.0))
    unique_pages = int(retrieval_features.get("unique_page_count", 0) or 0)
    exact_hits = int(retrieval_features.get("exact_identifier_hit_count", 0) or 0)
    if top_score < 0.35 and top_gap < 0.05 and unique_pages >= 3 and exact_hits == 0:
        return True, FREE_TEXT_NO_ANSWER, 0.0, "low_retrieval_quality"
    return False, current_answer, confidence, ""


def _build_review_artifact(
    *,
    run_id: str,
    query_request: QueryRequest,
    response: QueryResponse,
    candidates: List[Dict[str, Any]],
    page_refs: List[Dict[str, Any]],
    retrieval_profile_id: str,
    solver_trace: Dict[str, Any],
    evidence_selection_trace: Dict[str, Any],
    route_recall_diagnostics: Dict[str, Any],
    latency_budget_assertion: Dict[str, Any],
) -> RunQuestionReviewArtifact:
    retrieved_chunk_ids = _uniq(
        str((candidate.get("paragraph") or {}).get("paragraph_id", ""))
        for candidate in candidates
        if isinstance(candidate.get("paragraph"), dict)
    )
    used_source_page_ids = list(evidence_selection_trace.get("used_source_page_ids", []))
    used_chunk_ids = _uniq(
        str((candidate.get("paragraph") or {}).get("paragraph_id", ""))
        for candidate in candidates
        if isinstance(candidate.get("paragraph"), dict)
        and str(_fetch_page_for_candidate(candidate).get("source_page_id", "")) in used_source_page_ids
    )
    document_viewer = _build_document_viewer_state(
        project_id=query_request.project_id,
        candidates=candidates,
        used_source_page_ids=used_source_page_ids,
    )
    notes = [
        f"run_id={run_id}",
        f"question_id={query_request.question.id}",
        f"used_chunk_ids={','.join(used_chunk_ids)}" if used_chunk_ids else "used_chunk_ids=",
    ]
    return RunQuestionReviewArtifact(
        run_id=run_id,
        question_id=query_request.question.id,
        question=query_request.question.model_dump(mode="json", exclude_none=True),
        response=response,
        evidence={
            "retrieval_profile_id": retrieval_profile_id,
            "retrieved_page_ids": list(evidence_selection_trace.get("retrieved_source_page_ids", [])),
            "used_page_ids": used_source_page_ids,
            "retrieved_chunk_ids": retrieved_chunk_ids,
            "used_chunk_ids": used_chunk_ids,
            "retrieved_pages": page_refs,
            "used_pages": [ref for ref in page_refs if ref.get("used")],
            "solver_trace": solver_trace,
            "evidence_selection_trace": evidence_selection_trace,
            "route_recall_diagnostics": route_recall_diagnostics,
            "latency_budget_assertion": latency_budget_assertion,
            "normalized_query": _normalize_query_text(str(query_request.question.question)),
            "candidate_count": len(candidates),
            "retrieval_stage_trace": evidence_selection_trace.get("retrieval_stage_trace", {}),
            "retrieval_quality_features": evidence_selection_trace.get("retrieval_quality_features", {}),
            "route_decision": evidence_selection_trace.get("route_decision", {}),
            "law_article_lookup_resolution": evidence_selection_trace.get("law_article_lookup_resolution", {}),
            "law_history_lookup_resolution": evidence_selection_trace.get("law_history_lookup_resolution", {}),
            "cross_law_compare_resolution": evidence_selection_trace.get("cross_law_compare_resolution", {}),
            "cross_law_compare_retrieval_hints": evidence_selection_trace.get("cross_law_compare_retrieval_hints", {}),
            "cross_law_compare_dimension_trace": solver_trace.get("cross_law_compare_dimension_trace", []),
            "legal_context_flags": evidence_selection_trace.get("legal_context_flags", {}),
            "answer_normalization_trace": evidence_selection_trace.get("answer_normalization_trace", {}),
            "no_silent_fallback": evidence_selection_trace.get("no_silent_fallback", {}),
            "abstain_reason": evidence_selection_trace.get("abstain_reason"),
            "telemetry_shadow": evidence_selection_trace.get("telemetry_shadow", {}),
        },
        document_viewer=document_viewer,
        promotion_preview={
            "question_id": query_request.question.id,
            "answer_type": query_request.question.answer_type,
            "canonical_answer": response.answer,
            "source_sets": [
                {
                    "is_primary": True,
                    "page_ids": used_source_page_ids,
                    "notes": "\n".join(notes),
                }
            ] if used_source_page_ids else [],
        },
        created_at=datetime.now(timezone.utc),
    )


async def _answer_query(payload: QueryRequest) -> Tuple[QueryResponse, Dict[str, Any]]:
    req_started = datetime.now(timezone.utc)
    q = payload.question
    route_decision = resolve_route_decision(q.model_dump())
    route_name = route_decision.raw_route
    route_decision_trace = {
        "decision_version": route_decision.decision_version,
        "raw_route": route_decision.raw_route,
        "taxonomy_subroute": route_decision.taxonomy_subroute,
        "normalized_taxonomy_route": route_decision.normalized_taxonomy_route,
        "route_signals": dict(route_decision.route_signals),
        "target_doc_types_guess": list(route_decision.target_doc_types_guess),
        "document_scope_guess": route_decision.document_scope_guess,
        "temporal_sensitivity_guess": route_decision.temporal_sensitivity_guess,
        "matched_rules": list(route_decision.matched_rules),
        "confidence": float(route_decision.confidence),
    }
    explicit_route_hint = str(q.route_hint or "").strip().lower()
    law_history_slice_active = bool(route_decision.normalized_taxonomy_route == "law_relation_or_history")
    cross_law_slice_active = bool(
        route_decision.normalized_taxonomy_route == "cross_law_compare"
        and (route_name == "cross_law_compare" or explicit_route_hint == "cross_law_compare")
    )
    law_article_lookup_resolution = (
        resolve_law_article_lookup_intent(q.question) if route_name == "article_lookup" else {}
    )
    law_article_slice_active = bool(
        route_name == "article_lookup"
        and route_decision.normalized_taxonomy_route == "law_article_lookup"
    )
    law_history_lookup_resolution = (
        resolve_law_history_lookup_intent(q.question) if law_history_slice_active else {}
    )
    cross_law_compare_resolution = (
        resolve_cross_law_compare_intent(q.question) if cross_law_slice_active else {}
    )
    legal_context_flags = _history_legal_context_flags(law_history_lookup_resolution) if law_history_lookup_resolution else {}
    history_retrieval_hints = (
        build_law_history_retrieval_hints(q.question, law_history_lookup_resolution)
        if law_history_slice_active
        else {}
    )
    cross_law_compare_retrieval_hints = (
        build_cross_law_compare_retrieval_hints(q.question, cross_law_compare_resolution)
        if cross_law_slice_active
        else {}
    )
    article_resolution_blocked, article_resolution_block_reason = _article_resolution_guard(
        route_name=route_name,
        normalized_taxonomy_route=route_decision.normalized_taxonomy_route,
        lookup_intent=law_article_lookup_resolution,
    )
    history_resolution_blocked, history_resolution_block_reason = _history_resolution_guard(
        normalized_taxonomy_route=route_decision.normalized_taxonomy_route,
        history_intent=law_history_lookup_resolution,
    )
    cross_law_resolution_blocked, cross_law_resolution_block_reason = (
        _cross_law_compare_resolution_guard(
            normalized_taxonomy_route=route_decision.normalized_taxonomy_route,
            compare_intent=cross_law_compare_resolution,
        )
        if cross_law_slice_active
        else (False, "")
    )
    policy = payload.runtime_policy
    retrieval_route_name = (
        "cross_law_compare"
        if cross_law_slice_active
        else "history_lineage"
        if law_history_slice_active
        else route_name
    )
    retrieval_profile = resolve_retrieval_profile(
        retrieval_route_name,
        policy.max_candidate_pages,
        answer_type=q.answer_type,
    )
    no_answer_fast_path_triggered = bool(
        route_name == "no_answer"
        and int(getattr(retrieval_profile, "candidate_page_limit", 0) or 0) <= 0
    )

    if no_answer_fast_path_triggered:
        candidates: List[Dict[str, Any]] = []
        retrieval_stage_trace = {
            "trace_version": "retrieval_stage_trace_v1",
            "route_name": route_name,
            "answer_type": q.answer_type,
            "profile_id": retrieval_profile.profile_id,
            "normalized_query": _normalize_query_text(q.question),
            "lookup_intent": law_article_lookup_resolution if law_article_lookup_resolution else {},
            "structural_lookup_enabled": retrieval_profile.structural_lookup_enabled,
            "lineage_expansion_enabled": retrieval_profile.lineage_expansion_enabled,
            "candidate_page_budget": retrieval_profile.candidate_page_limit,
            "used_page_budget": retrieval_profile.used_page_limit,
            "retrieval_skipped": True,
            "retrieval_skipped_reason": "route_no_answer_fast_path",
            "exact_identifier_hit_count": 0,
            "lineage_signal_count": 0,
            "current_version_hit_count": 0,
            "candidate_count": 0,
            "top_candidates": [],
        }
    elif article_resolution_blocked:
        candidates = []
        retrieval_stage_trace = {
            "trace_version": "retrieval_stage_trace_v1",
            "route_name": route_name,
            "answer_type": q.answer_type,
            "profile_id": retrieval_profile.profile_id,
            "normalized_query": _normalize_query_text(q.question),
            "lookup_intent": law_article_lookup_resolution,
            "structural_lookup_enabled": retrieval_profile.structural_lookup_enabled,
            "lineage_expansion_enabled": retrieval_profile.lineage_expansion_enabled,
            "candidate_page_budget": retrieval_profile.candidate_page_limit,
            "used_page_budget": retrieval_profile.used_page_limit,
            "retrieval_skipped": True,
            "retrieval_skipped_reason": article_resolution_block_reason,
            "retrieval_blocked": True,
            "retrieval_blocked_reason": article_resolution_block_reason,
            "retrieval_fallback_traced": True,
            "retrieval_fallback_reason": "generic_retrieval_disabled_without_law_article_resolution",
            "exact_identifier_hit_count": 0,
            "lineage_signal_count": 0,
            "current_version_hit_count": 0,
            "candidate_count": 0,
            "top_candidates": [],
        }
    elif history_resolution_blocked:
        candidates = []
        retrieval_stage_trace = {
            "trace_version": "retrieval_stage_trace_v1",
            "route_name": route_name,
            "answer_type": q.answer_type,
            "profile_id": retrieval_profile.profile_id,
            "normalized_query": _normalize_query_text(q.question),
            "law_history_lookup_resolution": law_history_lookup_resolution,
            "legal_context_flags": legal_context_flags,
            "structural_lookup_enabled": retrieval_profile.structural_lookup_enabled,
            "lineage_expansion_enabled": retrieval_profile.lineage_expansion_enabled,
            "candidate_page_budget": retrieval_profile.candidate_page_limit,
            "used_page_budget": retrieval_profile.used_page_limit,
            "retrieval_skipped": True,
            "retrieval_skipped_reason": history_resolution_block_reason,
            "retrieval_blocked": True,
            "retrieval_blocked_reason": history_resolution_block_reason,
            "retrieval_fallback_traced": True,
            "retrieval_fallback_reason": "generic_retrieval_disabled_without_law_history_resolution",
            "exact_identifier_hit_count": 0,
            "lineage_signal_count": 0,
            "current_version_hit_count": 0,
            "candidate_count": 0,
            "top_candidates": [],
        }
    elif cross_law_resolution_blocked:
        candidates = []
        retrieval_stage_trace = {
            "trace_version": "retrieval_stage_trace_v1",
            "route_name": "cross_law_compare",
            "answer_type": q.answer_type,
            "profile_id": retrieval_profile.profile_id,
            "normalized_query": _normalize_query_text(q.question),
            "cross_law_compare_resolution": cross_law_compare_resolution,
            "cross_law_compare_retrieval_hints": cross_law_compare_retrieval_hints,
            "structural_lookup_enabled": retrieval_profile.structural_lookup_enabled,
            "lineage_expansion_enabled": retrieval_profile.lineage_expansion_enabled,
            "candidate_page_budget": retrieval_profile.candidate_page_limit,
            "used_page_budget": retrieval_profile.used_page_limit,
            "retrieval_skipped": True,
            "retrieval_skipped_reason": cross_law_resolution_block_reason,
            "retrieval_blocked": True,
            "retrieval_blocked_reason": cross_law_resolution_block_reason,
            "retrieval_fallback_traced": True,
            "retrieval_fallback_reason": "generic_retrieval_disabled_without_cross_law_compare_resolution",
            "exact_identifier_hit_count": 0,
            "lineage_signal_count": 0,
            "current_version_hit_count": 0,
            "candidate_count": 0,
            "top_candidates": [],
        }
    else:
        if law_history_slice_active:
            candidates, retrieval_stage_trace = _build_history_candidates(
                question_text=q.question,
                project_id=payload.project_id,
                max_pages=retrieval_profile.candidate_page_limit,
                route_name="history_lineage",
                answer_type=q.answer_type,
                retrieval_profile=retrieval_profile,
                history_intent=law_history_lookup_resolution,
                history_retrieval_hints=history_retrieval_hints,
            )
        elif cross_law_slice_active:
            candidates, retrieval_stage_trace = _build_cross_law_compare_candidates(
                question_text=q.question,
                project_id=payload.project_id,
                max_pages=retrieval_profile.candidate_page_limit,
                route_name="cross_law_compare",
                answer_type=q.answer_type,
                retrieval_profile=retrieval_profile,
                compare_intent=cross_law_compare_resolution,
                compare_retrieval_hints=cross_law_compare_retrieval_hints,
            )
        else:
            candidates, retrieval_stage_trace = _build_candidates(
                question_text=q.question,
                project_id=payload.project_id,
                max_pages=retrieval_profile.candidate_page_limit,
                route_name=route_name,
                answer_type=q.answer_type,
                retrieval_profile=retrieval_profile,
                lookup_intent=law_article_lookup_resolution if law_article_lookup_resolution else None,
                enforce_structural_for_article=law_article_slice_active,
            )
            if law_article_slice_active and retrieval_stage_trace.get("retrieval_blocked"):
                article_resolution_blocked = True
                article_resolution_block_reason = str(
                    retrieval_stage_trace.get("retrieval_blocked_reason", "law_article_lookup_blocked")
                )
    retrieval_stage_trace["route_decision"] = route_decision_trace
    if law_article_lookup_resolution:
        retrieval_stage_trace["law_article_lookup_resolution"] = law_article_lookup_resolution
    if law_history_lookup_resolution:
        retrieval_stage_trace["law_history_lookup_resolution"] = law_history_lookup_resolution
        retrieval_stage_trace["legal_context_flags"] = legal_context_flags
    if history_retrieval_hints:
        retrieval_stage_trace["history_retrieval_hints"] = history_retrieval_hints
    if cross_law_compare_resolution:
        retrieval_stage_trace["cross_law_compare_resolution"] = cross_law_compare_resolution
    if cross_law_compare_retrieval_hints:
        retrieval_stage_trace["cross_law_compare_retrieval_hints"] = cross_law_compare_retrieval_hints
    if retrieval_route_name != route_name:
        retrieval_stage_trace["retrieval_profile_route_override"] = {
            "requested_route_name": route_name,
            "profile_route_name": retrieval_route_name,
        }

    solver_route_name = (
        "cross_law_compare"
        if cross_law_slice_active
        else "history_lineage"
        if law_history_slice_active
        else route_name
    )
    answer: Any = q.question
    abstained = False
    confidence = 0.0
    llm_usage = {"prompt_tokens": 0, "completion_tokens": 0}
    first_token_at = None
    model_name = "deterministic-router"
    page_refs: List[Dict[str, Any]] = []
    used_refs: List[Dict[str, Any]] = []
    solver_trace: Dict[str, Any] = {
        "solver_version": (
            "cross_law_compare_deterministic_solver_v1"
            if cross_law_slice_active
            else "law_history_deterministic_solver_v1"
            if law_history_slice_active
            else "typed_deterministic_solver_v1"
        ),
        "answer_type": q.answer_type,
        "route_name": solver_route_name,
        "execution_mode": "deterministic_abstain_fast_path" if no_answer_fast_path_triggered else "deterministic_fallback",
        "path": "no_answer_fast_path" if no_answer_fast_path_triggered else "no_candidates",
        "candidate_count": 0,
        "matched_candidate_count": 0,
        "matched_candidate_indices": [],
        "values_considered": [],
        "no_answer_fast_path_triggered": no_answer_fast_path_triggered,
        "route_decision": route_decision_trace,
        "law_article_lookup_resolution": law_article_lookup_resolution if law_article_lookup_resolution else {},
        "law_history_lookup_resolution": law_history_lookup_resolution if law_history_lookup_resolution else {},
        "cross_law_compare_resolution": cross_law_compare_resolution if cross_law_compare_resolution else {},
        "legal_context_flags": legal_context_flags,
    }
    evidence_selection_trace: Dict[str, Any] = {
        "trace_version": "evidence_selection_trace_v1",
        "route_name": solver_route_name,
        "answer_type": q.answer_type,
        "selection_rule": (
            "no_answer_fast_path"
            if no_answer_fast_path_triggered
            else "law_article_resolution_blocked"
            if article_resolution_blocked
            else "law_history_resolution_blocked"
            if history_resolution_blocked
            else "cross_law_compare_resolution_blocked"
            if cross_law_resolution_blocked
            else "no_candidates"
        ),
        "used_page_limit": retrieval_profile.used_page_limit,
        "candidate_page_budget": retrieval_profile.candidate_page_limit,
        "used_page_budget": retrieval_profile.used_page_limit,
        "no_answer_fast_path_triggered": no_answer_fast_path_triggered,
        "retrieval_skipped_reason": (
            "route_no_answer_fast_path"
            if no_answer_fast_path_triggered
            else article_resolution_block_reason
            if article_resolution_blocked
            else history_resolution_block_reason
            if history_resolution_blocked
            else cross_law_resolution_block_reason
            if cross_law_resolution_blocked
            else ""
        ),
        "retrieved_candidate_count": 0,
        "used_candidate_count": 0,
        "retrieved_source_page_ids": [],
        "used_source_page_ids": [],
        "page_collapse_ratio": 0.0,
        "retrieval_stage_trace": retrieval_stage_trace,
        "decisions": [],
        "route_decision": route_decision_trace,
        "law_article_lookup_resolution": law_article_lookup_resolution if law_article_lookup_resolution else {},
        "law_history_lookup_resolution": law_history_lookup_resolution if law_history_lookup_resolution else {},
        "cross_law_compare_resolution": cross_law_compare_resolution if cross_law_compare_resolution else {},
        "cross_law_compare_retrieval_hints": cross_law_compare_retrieval_hints if cross_law_compare_retrieval_hints else {},
        "legal_context_flags": legal_context_flags,
    }

    if not candidates:
        abstained = True
        confidence = 0.0
        answer = FREE_TEXT_NO_ANSWER if q.answer_type == "free_text" else None
        solver_trace["candidate_count"] = 0
        if no_answer_fast_path_triggered:
            evidence_selection_trace["abstain_reason"] = "route_no_answer_fast_path"
            solver_trace["path"] = "no_answer_fast_path"
        elif article_resolution_blocked:
            evidence_selection_trace["abstain_reason"] = article_resolution_block_reason
            solver_trace["path"] = "law_article_resolution_blocked"
            solver_trace["execution_mode"] = "deterministic_abstain_resolution_guard"
        elif history_resolution_blocked:
            evidence_selection_trace["abstain_reason"] = history_resolution_block_reason
            solver_trace["path"] = "law_history_resolution_blocked"
            solver_trace["execution_mode"] = "deterministic_abstain_resolution_guard"
        elif cross_law_resolution_blocked:
            evidence_selection_trace["abstain_reason"] = cross_law_resolution_block_reason
            solver_trace["path"] = "cross_law_compare_resolution_blocked"
            solver_trace["execution_mode"] = "deterministic_abstain_resolution_guard"
    else:
        proposition_direct_answer = try_direct_answer(
            question_text=q.question,
            answer_type=q.answer_type,
            route_name=solver_route_name,
            candidates=candidates,
        )
        if proposition_direct_answer:
            answer = proposition_direct_answer["answer"]
            abstained = False
            confidence = float(proposition_direct_answer.get("confidence", 0.0) or 0.0)
            solver_trace = proposition_direct_answer["trace"]
            solver_trace["execution_mode"] = "deterministic_proposition_direct_answer"
        elif law_history_slice_active:
            solver_result = solve_law_history_deterministic(
                q.model_dump(),
                "history_lineage",
                candidates,
                history_intent=law_history_lookup_resolution,
            )
            answer = solver_result.answer
            abstained = solver_result.abstained
            confidence = solver_result.confidence
            solver_trace = solver_result.trace
        elif cross_law_slice_active:
            solver_result = solve_cross_law_compare_deterministic(
                q.model_dump(),
                "cross_law_compare",
                candidates,
                compare_intent=cross_law_compare_resolution,
            )
            answer = solver_result.answer
            abstained = solver_result.abstained
            confidence = solver_result.confidence
            solver_trace = solver_result.trace
        elif not proposition_direct_answer:
            solver_result = solve_deterministic(q.model_dump(), route_name, candidates)
            answer = solver_result.answer
            abstained = solver_result.abstained
            confidence = solver_result.confidence
            solver_trace = solver_result.trace
        solver_trace["route_decision"] = route_decision_trace
        solver_trace["law_article_lookup_resolution"] = law_article_lookup_resolution if law_article_lookup_resolution else {}
        solver_trace["law_history_lookup_resolution"] = law_history_lookup_resolution if law_history_lookup_resolution else {}
        solver_trace["cross_law_compare_resolution"] = cross_law_compare_resolution if cross_law_compare_resolution else {}
        solver_trace["cross_law_compare_retrieval_hints"] = cross_law_compare_retrieval_hints if cross_law_compare_retrieval_hints else {}
        solver_trace["legal_context_flags"] = legal_context_flags

        if policy.use_llm and q.answer_type == "free_text" and not abstained and llm_client.config.enabled:
            if law_article_slice_active:
                solver_trace["llm_fallback_blocked"] = True
                solver_trace["llm_fallback_block_reason"] = "law_article_deterministic_only"
            elif law_history_slice_active:
                solver_trace["llm_fallback_blocked"] = True
                solver_trace["llm_fallback_block_reason"] = "law_history_deterministic_only"
            elif cross_law_slice_active:
                solver_trace["llm_fallback_blocked"] = True
                solver_trace["llm_fallback_block_reason"] = "cross_law_compare_deterministic_only"
            else:
                first_token_at = datetime.now(timezone.utc)
                model_name = llm_client.config.deployment or model_name
                evidence_snippets = [
                    str((_paragraph_for_candidate(candidate)).get("text", ""))[:320]
                    for candidate in candidates[:3]
                ]
                try:
                    llm_answer, llm_usage = await _free_text_with_llm(
                        route_name,
                        q.question,
                        policy.scoring_policy_version,
                        evidence_snippets=evidence_snippets,
                    )
                    if llm_answer:
                        answer = llm_answer
                        confidence = max(confidence, 0.85)
                        solver_trace["llm_fallback_used"] = True
                        solver_trace["llm_fallback_mode"] = "grounded_snippets_v1"
                except Exception:
                    answer = answer

        ranked_refs = [
            _to_page_ref(
                candidate,
                payload.project_id,
                used=False,
                page_index_base=policy.page_index_base_export,
            )
            for candidate in candidates[:retrieval_profile.candidate_page_limit]
        ]
        used_refs, evidence_selection_trace = choose_used_sources_with_trace(
            ranked_refs,
            solver_route_name,
            question_text=q.question,
            answer_type=q.answer_type,
            used_page_limit=retrieval_profile.used_page_limit,
        )
        used_ref_ids = {id(ref) for ref in used_refs}

        for ref in ranked_refs:
            if id(ref) in used_ref_ids:
                ref["used"] = True
                ref["evidence_role"] = "primary"
            page_refs.append(ref)

    retrieval_quality_features = _retrieval_quality_features(
        candidates=candidates,
        evidence_selection_trace=evidence_selection_trace,
    )
    abstained, answer, confidence, abstain_reason = _apply_retrieval_aware_abstain(
        answer_type=q.answer_type,
        route_name=route_name,
        candidates=candidates,
        current_abstained=abstained,
        current_answer=answer,
        confidence=confidence,
        retrieval_features=retrieval_quality_features,
    )
    if no_answer_fast_path_triggered and abstained:
        abstain_reason = "route_no_answer_fast_path"
    elif article_resolution_blocked and abstained:
        abstain_reason = article_resolution_block_reason
    elif history_resolution_blocked and abstained:
        abstain_reason = history_resolution_block_reason
    elif cross_law_resolution_blocked and abstained:
        abstain_reason = cross_law_resolution_block_reason
    elif retrieval_stage_trace.get("retrieval_blocked") and abstained:
        abstain_reason = str(retrieval_stage_trace.get("retrieval_blocked_reason", "retrieval_blocked"))
    if abstained:
        used_refs = []
        for ref in page_refs:
            ref["used"] = False
            ref["evidence_role"] = "supporting"
        evidence_selection_trace["used_candidate_count"] = 0
        evidence_selection_trace["used_source_page_ids"] = []
        evidence_selection_trace["abstain_reason"] = abstain_reason or "no_answer_empty_source_semantics"

    route_recall_diagnostics = build_route_recall_diagnostics(
        question_text=q.question,
        route_name=solver_route_name,
        retrieval_profile_id=retrieval_profile.profile_id,
        candidates=candidates,
        used_sources=used_refs,
    )

    normalized_answer, normalized_text = normalize_answer(answer, q.answer_type)
    answer_normalization_trace = _build_answer_normalization_trace(
        raw_answer=answer,
        normalized_answer=normalized_answer,
        normalized_text=normalized_text,
        answer_type=q.answer_type,
        abstained=abstained,
    )
    answer_for_response: Any = None if abstained and q.answer_type != "free_text" else normalized_answer

    telemetry = build_telemetry(
        request_started_at=req_started,
        answer_output_tokens=_estimate_tokens(str(answer_for_response or "")),
        model_name=model_name,
        route_name=route_name,
        search_profile=retrieval_profile.profile_id,
        first_token_at=first_token_at,
        input_tokens=int(llm_usage.get("prompt_tokens", 0)),
    )
    latency_budget_assertion = build_latency_budget_assertion(
        route_name=route_name,
        retrieval_profile_id=retrieval_profile.profile_id,
        observed_ttft_ms=telemetry.ttft_ms,
        budget_ttft_ms=retrieval_profile.ttft_budget_ms,
    )

    debug = None
    telemetry_shadow = _telemetry_shadow_map(
        telemetry,
        retrieval_profile,
        route_name=route_name,
        no_answer_fast_path_triggered=no_answer_fast_path_triggered,
    )
    evidence_selection_trace["retrieval_stage_trace"] = retrieval_stage_trace
    evidence_selection_trace["retrieval_quality_features"] = retrieval_quality_features
    evidence_selection_trace["telemetry_shadow"] = telemetry_shadow
    evidence_selection_trace["answer_normalization_trace"] = answer_normalization_trace
    evidence_selection_trace["law_history_lookup_resolution"] = law_history_lookup_resolution if law_history_lookup_resolution else {}
    evidence_selection_trace["cross_law_compare_resolution"] = cross_law_compare_resolution if cross_law_compare_resolution else {}
    evidence_selection_trace["cross_law_compare_retrieval_hints"] = (
        cross_law_compare_retrieval_hints if cross_law_compare_retrieval_hints else {}
    )
    evidence_selection_trace["legal_context_flags"] = legal_context_flags
    evidence_selection_trace["no_silent_fallback"] = {
        "law_article_slice_active": law_article_slice_active,
        "article_resolution_blocked": article_resolution_blocked,
        "article_resolution_block_reason": article_resolution_block_reason,
        "law_history_slice_active": law_history_slice_active,
        "history_resolution_blocked": history_resolution_blocked,
        "history_resolution_block_reason": history_resolution_block_reason,
        "cross_law_slice_active": cross_law_slice_active,
        "cross_law_resolution_blocked": cross_law_resolution_blocked,
        "cross_law_resolution_block_reason": cross_law_resolution_block_reason,
    }
    if policy.return_debug_trace:
        debug = {
            "candidate_pages": page_refs,
            "retrieved_pages": page_refs,
            "used_pages": [ref for ref in page_refs if ref.get("used")],
            "evidence_selection_trace": evidence_selection_trace,
            "policy_version": policy.scoring_policy_version,
            "retrieval_profile_id": retrieval_profile.profile_id,
            "candidate_page_budget": retrieval_profile.candidate_page_limit,
            "used_page_budget": retrieval_profile.used_page_limit,
            "no_answer_fast_path_triggered": no_answer_fast_path_triggered,
            "route_recall_diagnostics": route_recall_diagnostics,
            "latency_budget_assertion": latency_budget_assertion,
            "solver_trace": solver_trace,
            "retrieval_stage_trace": retrieval_stage_trace,
            "retrieval_quality_features": retrieval_quality_features,
            "telemetry_shadow": telemetry_shadow,
            "route_decision": route_decision_trace,
            "law_article_lookup_resolution": law_article_lookup_resolution if law_article_lookup_resolution else {},
            "law_history_lookup_resolution": law_history_lookup_resolution if law_history_lookup_resolution else {},
            "history_retrieval_hints": history_retrieval_hints if history_retrieval_hints else {},
            "cross_law_compare_resolution": cross_law_compare_resolution if cross_law_compare_resolution else {},
            "cross_law_compare_retrieval_hints": (
                cross_law_compare_retrieval_hints if cross_law_compare_retrieval_hints else {}
            ),
            "legal_context_flags": legal_context_flags,
            "answer_normalization_trace": answer_normalization_trace,
            "no_silent_fallback": {
                "law_article_slice_active": law_article_slice_active,
                "article_resolution_blocked": article_resolution_blocked,
                "article_resolution_block_reason": article_resolution_block_reason,
                "law_history_slice_active": law_history_slice_active,
                "history_resolution_blocked": history_resolution_blocked,
                "history_resolution_block_reason": history_resolution_block_reason,
                "cross_law_slice_active": cross_law_slice_active,
                "cross_law_resolution_blocked": cross_law_resolution_blocked,
                "cross_law_resolution_block_reason": cross_law_resolution_block_reason,
            },
            "abstain_reason": evidence_selection_trace.get("abstain_reason"),
            "entities": [],
        }

    response = QueryResponse(
        question_id=q.id,
        answer=answer_for_response,
        answer_normalized=normalized_text if not isinstance(normalized_answer, list) else ", ".join(normalized_answer),
        answer_type=q.answer_type,
        confidence=confidence if not abstained else 0.0,
        route_name=route_name,
        abstained=abstained,
        sources=page_refs if not abstained else [],
        telemetry=telemetry,
        debug=debug,
    )
    return response, {
        "query_request": payload,
        "candidates": candidates,
        "page_refs": page_refs,
        "retrieval_profile_id": retrieval_profile.profile_id,
        "solver_trace": solver_trace,
        "evidence_selection_trace": evidence_selection_trace,
        "route_recall_diagnostics": route_recall_diagnostics,
        "latency_budget_assertion": latency_budget_assertion,
        "retrieval_stage_trace": retrieval_stage_trace,
        "retrieval_quality_features": retrieval_quality_features,
        "telemetry_shadow": telemetry_shadow,
        "route_decision_trace": route_decision_trace,
        "law_article_lookup_resolution": law_article_lookup_resolution if law_article_lookup_resolution else {},
        "law_history_lookup_resolution": law_history_lookup_resolution if law_history_lookup_resolution else {},
        "history_retrieval_hints": history_retrieval_hints if history_retrieval_hints else {},
        "cross_law_compare_resolution": cross_law_compare_resolution if cross_law_compare_resolution else {},
        "cross_law_compare_retrieval_hints": (
            cross_law_compare_retrieval_hints if cross_law_compare_retrieval_hints else {}
        ),
        "legal_context_flags": legal_context_flags,
        "answer_normalization_trace": answer_normalization_trace,
        "no_answer_fast_path_triggered": no_answer_fast_path_triggered,
    }


@router.post("/datasets/{datasetId}/import-questions")
def import_questions(datasetId: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    source = str(payload.get("source") or "").strip()
    limit = int(payload.get("limit", 0) or 0)
    project_id = str(payload.get("project_id") or "").strip()

    questions_payload = payload.get("questions")
    if questions_payload is None and source == "public_dataset":
        questions_payload = _load_public_dataset(limit)
    if questions_payload is None:
        raise HTTPException(status_code=422, detail="questions or source=public_dataset is required")
    if not isinstance(questions_payload, list):
        raise HTTPException(status_code=422, detail="questions must be an array")

    if limit > 0:
        questions_payload = questions_payload[:limit]

    normalized: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    for idx, item in enumerate(questions_payload):
        if not isinstance(item, dict):
            errors.append({"index": idx, "error": "question item must be an object"})
            continue
        try:
            normalized.append(_normalize_question_payload(item, datasetId))
        except Exception as exc:
            errors.append({"index": idx, "error": str(exc)})

    if runtime_pg.enabled():
        imported = runtime_pg.upsert_dataset_questions(datasetId, project_id, normalized)
        listing = runtime_pg.list_dataset_questions(datasetId, limit=1)
        total_questions = int(listing.get("total", 0))
    else:
        dataset = store.datasets.setdefault(
            datasetId,
            {"dataset_id": datasetId, "project_id": project_id, "questions": {}},
        )
        if project_id:
            dataset["project_id"] = project_id
        questions_map = dataset.setdefault("questions", {})

        imported = 0
        for question in normalized:
            if question["id"] not in questions_map:
                imported += 1
            questions_map[question["id"]] = question
        total_questions = len(questions_map)

    return {
        "dataset_id": datasetId,
        "source": source or "payload",
        "imported": imported,
        "upserted": len(normalized),
        "total_questions": total_questions,
        "error_count": len(errors),
        "errors": errors[:20],
    }


@router.get("/datasets/{datasetId}/questions")
def list_dataset_questions(datasetId: str, limit: int = Query(default=50, ge=1, le=1000)) -> Dict[str, Any]:
    if runtime_pg.enabled():
        listing = runtime_pg.list_dataset_questions(datasetId, limit=limit)
        if not listing:
            raise HTTPException(status_code=404, detail="dataset not found")
        return {
            "dataset_id": datasetId,
            "items": listing.get("items", []),
            "total": int(listing.get("total", 0)),
        }
    dataset = store.datasets.get(datasetId)
    if not dataset:
        raise HTTPException(status_code=404, detail="dataset not found")
    questions_map = dataset.get("questions", {})
    if not isinstance(questions_map, dict):
        questions_map = {}
    items = list(questions_map.values())[:limit]
    return {
        "dataset_id": datasetId,
        "items": items,
        "total": len(questions_map),
    }


@router.post("/ask")
async def ask(payload: QueryRequest) -> QueryResponse:
    resp, _ = await _answer_query(payload)
    if runtime_pg.enabled():
        runtime_pg.upsert_question_telemetry(payload.question.id, resp.telemetry.model_dump(mode="json"))
    else:
        store.question_telemetry[payload.question.id] = resp.telemetry.model_dump(mode="json")
    return resp


@router.post("/ask-batch", status_code=202)
async def ask_batch(payload: AskBatchRequest) -> dict:
    question_ids = list(payload.question_ids)
    if not question_ids:
        if runtime_pg.enabled():
            listing = runtime_pg.list_dataset_questions(payload.dataset_id, limit=100000)
            if not listing:
                raise HTTPException(status_code=404, detail="dataset not found")
            question_ids = [str(item.get("id")) for item in listing.get("items", []) if item.get("id")]
        else:
            dataset = store.datasets.get(payload.dataset_id, {})
            questions_map = dataset.get("questions", {}) if isinstance(dataset, dict) else {}
            if isinstance(questions_map, dict):
                question_ids = list(questions_map.keys())
    if not question_ids:
        raise HTTPException(status_code=422, detail="dataset has no questions")

    if runtime_pg.enabled():
        run = runtime_pg.create_run(payload.dataset_id, len(question_ids), status="running")
    else:
        run = store.create_run(payload.dataset_id, len(question_ids), status="running")
    run_id = run["run_id"]

    for qid in question_ids:
        query_payload = _build_question_from_dataset(
            project_id=payload.project_id,
            dataset_id=payload.dataset_id,
            question_id=qid,
            runtime_policy=payload.runtime_policy,
        )
        result, answer_ctx = await _answer_query(query_payload)
        if runtime_pg.enabled():
            runtime_pg.upsert_run_question(run_id, qid, result)
            runtime_pg.upsert_run_question_review(
                run_id,
                qid,
                _build_review_artifact(
                    run_id=run_id,
                    query_request=query_payload,
                    response=result,
                    candidates=answer_ctx["candidates"],
                    page_refs=answer_ctx["page_refs"],
                    retrieval_profile_id=answer_ctx["retrieval_profile_id"],
                    solver_trace=answer_ctx["solver_trace"],
                    evidence_selection_trace=answer_ctx["evidence_selection_trace"],
                    route_recall_diagnostics=answer_ctx["route_recall_diagnostics"],
                    latency_budget_assertion=answer_ctx["latency_budget_assertion"],
                ),
            )
            runtime_pg.upsert_question_telemetry(qid, result.telemetry.model_dump(mode="json"))
        else:
            store.upsert_run_question(run_id, qid, result)
            store.upsert_run_question_review(
                run_id,
                qid,
                _build_review_artifact(
                    run_id=run_id,
                    query_request=query_payload,
                    response=result,
                    candidates=answer_ctx["candidates"],
                    page_refs=answer_ctx["page_refs"],
                    retrieval_profile_id=answer_ctx["retrieval_profile_id"],
                    solver_trace=answer_ctx["solver_trace"],
                    evidence_selection_trace=answer_ctx["evidence_selection_trace"],
                    route_recall_diagnostics=answer_ctx["route_recall_diagnostics"],
                    latency_budget_assertion=answer_ctx["latency_budget_assertion"],
                ).model_dump(mode="json"),
            )
            store.question_telemetry[qid] = result.telemetry.model_dump(mode="json")

    if runtime_pg.enabled():
        runtime_pg.set_run_status(run_id, "completed")
    else:
        store.set_run_status(run_id, "completed")
    return {"run_id": run_id, "status": "accepted"}
