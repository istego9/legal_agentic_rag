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
from services.runtime.router import resolve_retrieval_profile, resolve_route
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
PUBLIC_DATASET_PATH = REPO_ROOT / "public_dataset.json"
_WHITESPACE_PATTERN = re.compile(r"\s+")
_ARTICLE_REF_PATTERN = re.compile(r"\barticle\s+(\d+[A-Za-z\-]*)\b", re.IGNORECASE)
_SECTION_REF_PATTERN = re.compile(r"\bsection\s+(\d+[A-Za-z\-]*)\b", re.IGNORECASE)
_PART_REF_PATTERN = re.compile(r"\bpart\s+([A-Za-z0-9\-]+)\b", re.IGNORECASE)
_SCHEDULE_REF_PATTERN = re.compile(r"\bschedule\s+([A-Za-z0-9\-]+)\b", re.IGNORECASE)
_LAW_NUMBER_PATTERN = re.compile(r"\blaw\s+(?:no\.?|number)?\s*(\d+)\b", re.IGNORECASE)
_CASE_NUMBER_PATTERN = re.compile(r"\b[A-Z]{2,4}\s*\d{1,4}/\d{4}\b")
_CURRENT_LAW_MARKER = re.compile(r"\b(current|currently in force|valid|updated|as amended)\b", re.IGNORECASE)


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


def _collapse_ws(value: str) -> str:
    return _WHITESPACE_PATTERN.sub(" ", value).strip()


def _normalize_query_text(question_text: str) -> str:
    return _collapse_ws(question_text).lower()


def _question_structure(question_text: str) -> Dict[str, Any]:
    normalized = _normalize_query_text(question_text)
    return {
        "normalized_query": normalized,
        "article_refs": _uniq(match.group(1).lower() for match in _ARTICLE_REF_PATTERN.finditer(question_text)),
        "section_refs": _uniq(match.group(1).lower() for match in _SECTION_REF_PATTERN.finditer(question_text)),
        "part_refs": _uniq(match.group(1).lower() for match in _PART_REF_PATTERN.finditer(question_text)),
        "schedule_refs": _uniq(match.group(1).lower() for match in _SCHEDULE_REF_PATTERN.finditer(question_text)),
        "law_numbers": _uniq(match.group(1) for match in _LAW_NUMBER_PATTERN.finditer(question_text)),
        "case_numbers": _uniq(match.group(0).upper() for match in _CASE_NUMBER_PATTERN.finditer(question_text.upper())),
        "current_law_intent": bool(_CURRENT_LAW_MARKER.search(question_text)),
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
    part_ref = ""
    heading_path = projection.get("heading_path", []) if isinstance(projection.get("heading_path"), list) else []
    if heading_path:
        part_ref = str(heading_path[0]).lower().strip()
    schedule_number = str(projection.get("schedule_number", "")).lower().strip()
    law_number = str(projection.get("law_number", "")).strip()
    case_number = str(projection.get("case_number", "")).upper().strip()
    return {
        "article": bool(set(question_structure["article_refs"]).intersection(article_refs)),
        "section": bool(question_structure["section_refs"] and section_ref in question_structure["section_refs"]),
        "part": bool(question_structure["part_refs"] and part_ref in question_structure["part_refs"]),
        "schedule": bool(question_structure["schedule_refs"] and schedule_number in question_structure["schedule_refs"]),
        "law_number": bool(question_structure["law_numbers"] and law_number in question_structure["law_numbers"]),
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
        "current_version_hit": bool(projection.get("is_current_version")),
        "lineage_signal": lineage_signal,
    }


def _rerank_candidates(
    *,
    question_text: str,
    route_name: str,
    answer_type: str,
    candidates: List[Dict[str, Any]],
    retrieval_profile: Any,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    question_structure = _question_structure(question_text)
    structural_candidates: List[Dict[str, Any]] = []
    lexical_candidates: List[Dict[str, Any]] = []
    exact_identifier_hits = 0
    lineage_hits = 0
    current_version_hits = 0

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
        exact_identifier_hits += 1 if exact_identifier_hit else 0
        lineage_hits += 1 if lineage_signal else 0
        current_version_hits += 1 if current_version_hit else 0

        final_score = float(base_score)
        stage = "lexical_projected"
        reasons: List[str] = []
        if exact_identifier_hit:
            final_score += 0.35
            reasons.append("exact_identifier_hit")
        if current_version_hit and route_name != "history_lineage":
            final_score += 0.06
            reasons.append("current_version_soft_boost")
        if lineage_signal and route_name == "history_lineage":
            final_score += 0.15
            reasons.append("lineage_signal")
        if route_name == "article_lookup" and features["structure_hits"]["article"]:
            final_score += 0.2
            reasons.append("article_lookup_structural_match")
        if route_name == "single_case_extraction" and features["structure_hits"]["case_number"]:
            final_score += 0.2
            reasons.append("case_lookup_structural_match")
        if retrieval_profile.structural_lookup_enabled and any(features["structure_hits"].values()):
            final_score += 0.5
            stage = "structural_lookup"
            reasons.append("structural_lookup_priority")

        row = {
            **candidate,
            "score": round(final_score, 4),
            "exact_identifier_hit": exact_identifier_hit,
            "lineage_signal": lineage_signal,
            "retrieval_debug": {
                "stage": stage,
                "base_score": round(base_score, 4),
                "final_score": round(final_score, 4),
                "reasons": reasons,
                "structure_hits": features["structure_hits"],
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

    stage_trace = {
        "trace_version": "retrieval_stage_trace_v1",
        "route_name": route_name,
        "answer_type": answer_type,
        "profile_id": retrieval_profile.profile_id,
        "normalized_query": question_structure["normalized_query"],
        "structural_lookup_enabled": retrieval_profile.structural_lookup_enabled,
        "lineage_expansion_enabled": retrieval_profile.lineage_expansion_enabled,
        "exact_identifier_hit_count": exact_identifier_hits,
        "lineage_signal_count": lineage_hits,
        "current_version_hit_count": current_version_hits,
        "candidate_count": len(ordered),
        "top_candidates": [
            {
                "paragraph_id": str(_paragraph_for_candidate(row).get("paragraph_id", "")),
                "source_page_id": str((_fetch_page_for_candidate(row) or {}).get("source_page_id", "")),
                "stage": str((row.get("retrieval_debug") or {}).get("stage", "")),
                "score": float(row.get("score", 0.0)),
                "reasons": list((row.get("retrieval_debug") or {}).get("reasons", [])),
            }
            for row in ordered[: min(8, len(ordered))]
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
            "exact_identifier_hit_count": 0,
            "lineage_signal_count": 0,
            "current_version_hit_count": 0,
            "candidate_count": 0,
            "top_candidates": [],
        }

    if corpus_pg.enabled():
        base_candidates = corpus_pg.search_candidates(project_id=project_id, query=question_text, top_k=max(max_pages * 2, 12))
    elif store.feature_flags.get("canonical_chunk_model_v1", True) and store.chunk_search_documents:
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

    question_structure = _question_structure(question_text)
    if retrieval_profile.structural_lookup_enabled and any(question_structure[key] for key in ("article_refs", "section_refs", "part_refs", "schedule_refs")):
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
            base_candidates = structural_only + base_candidates

    ordered, stage_trace = _rerank_candidates(
        question_text=question_text,
        route_name=route_name,
        answer_type=answer_type,
        candidates=base_candidates,
        retrieval_profile=retrieval_profile,
    )
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


async def _free_text_with_llm(route_name: str, question_text: str, policy_version: str) -> Tuple[str, Dict[str, int]]:
    prompt = (
        "Answer in one short sentence only. Be factual and concise."
        f" Route family: {route_name}. "
        f"Scoring policy: {policy_version}. "
        f"Question: {question_text}"
    )
    return await llm_client.complete_chat(
        prompt,
        user_context={"route_name": route_name, "policy_version": policy_version},
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
        raise HTTPException(status_code=404, detail="public_dataset.json not found")
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
    route_name = resolve_route(q.model_dump())
    policy = payload.runtime_policy
    retrieval_profile = resolve_retrieval_profile(
        route_name,
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
    else:
        candidates, retrieval_stage_trace = _build_candidates(
            question_text=q.question,
            project_id=payload.project_id,
            max_pages=retrieval_profile.candidate_page_limit,
            route_name=route_name,
            answer_type=q.answer_type,
            retrieval_profile=retrieval_profile,
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
        "solver_version": "typed_deterministic_solver_v1",
        "answer_type": q.answer_type,
        "route_name": route_name,
        "execution_mode": "deterministic_abstain_fast_path" if no_answer_fast_path_triggered else "deterministic_fallback",
        "path": "no_answer_fast_path" if no_answer_fast_path_triggered else "no_candidates",
        "candidate_count": 0,
        "matched_candidate_count": 0,
        "matched_candidate_indices": [],
        "values_considered": [],
        "no_answer_fast_path_triggered": no_answer_fast_path_triggered,
    }
    evidence_selection_trace: Dict[str, Any] = {
        "trace_version": "evidence_selection_trace_v1",
        "route_name": route_name,
        "answer_type": q.answer_type,
        "selection_rule": "no_answer_fast_path" if no_answer_fast_path_triggered else "no_candidates",
        "used_page_limit": retrieval_profile.used_page_limit,
        "candidate_page_budget": retrieval_profile.candidate_page_limit,
        "used_page_budget": retrieval_profile.used_page_limit,
        "no_answer_fast_path_triggered": no_answer_fast_path_triggered,
        "retrieval_skipped_reason": "route_no_answer_fast_path" if no_answer_fast_path_triggered else "",
        "retrieved_candidate_count": 0,
        "used_candidate_count": 0,
        "retrieved_source_page_ids": [],
        "used_source_page_ids": [],
        "page_collapse_ratio": 0.0,
        "retrieval_stage_trace": retrieval_stage_trace,
        "decisions": [],
    }

    if not candidates:
        abstained = True
        confidence = 0.0
        answer = FREE_TEXT_NO_ANSWER if q.answer_type == "free_text" else None
        solver_trace["candidate_count"] = 0
        if no_answer_fast_path_triggered:
            evidence_selection_trace["abstain_reason"] = "route_no_answer_fast_path"
    else:
        solver_result = solve_deterministic(q.model_dump(), route_name, candidates)
        answer = solver_result.answer
        abstained = solver_result.abstained
        confidence = solver_result.confidence
        solver_trace = solver_result.trace

        if policy.use_llm and q.answer_type == "free_text" and not abstained and llm_client.config.enabled:
            first_token_at = datetime.now(timezone.utc)
            model_name = llm_client.config.deployment or model_name
            try:
                llm_answer, llm_usage = await _free_text_with_llm(
                    route_name,
                    q.question,
                    policy.scoring_policy_version,
                )
                if llm_answer:
                    answer = llm_answer
                    confidence = max(confidence, 0.85)
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
            route_name,
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
        route_name=route_name,
        retrieval_profile_id=retrieval_profile.profile_id,
        candidates=candidates,
        used_sources=used_refs,
    )

    normalized_answer, normalized_text = normalize_answer(answer, q.answer_type)
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
