"""Projection helpers from case extraction artifacts to retrieval facets."""

from __future__ import annotations

import re
from typing import Any, Dict, List


def _compact_text(value: str, limit: int) -> str:
    return re.sub(r"\s+", " ", value or "").strip()[:limit]


def build_case_chunk_facet(*, chunk_payload: Dict[str, Any], document_payload: Dict[str, Any]) -> Dict[str, Any]:
    party_names = [
        str(item.get("name", "")).strip()
        for item in chunk_payload.get("party_roles", [])
        if isinstance(item, dict) and str(item.get("name", "")).strip()
    ]
    party_roles = [
        str(item.get("role", "")).strip()
        for item in chunk_payload.get("party_roles", [])
        if isinstance(item, dict) and str(item.get("role", "")).strip()
    ]
    return {
        "chunk_id": chunk_payload.get("chunk_id"),
        "case_number": document_payload.get("proceeding_no"),
        "neutral_citation": document_payload.get("proceeding_no"),
        "court_name": document_payload.get("court_name"),
        "court_level": document_payload.get("court_level"),
        "decision_date": document_payload.get("decision_date"),
        "section_kind_case": chunk_payload.get("section_kind_case"),
        "party_names": party_names,
        "party_roles_present": party_roles,
        "judge_names": chunk_payload.get("judge_names", []),
        "presiding_judge": (chunk_payload.get("judge_names") or [None])[0],
        "claim_amounts": [],
        "relief_sought": [],
        "disposition_label": chunk_payload.get("order_effect_label"),
        "outcome_side": chunk_payload.get("ground_owner"),
        "cited_law_ids": chunk_payload.get("authority_refs", []),
        "cited_case_ids": chunk_payload.get("authority_refs", []),
    }


def build_chunk_search_document(
    *,
    chunk_payload: Dict[str, Any],
    document_payload: Dict[str, Any],
    paragraph: Dict[str, Any],
    page: Dict[str, Any],
) -> Dict[str, Any]:
    text_clean = _compact_text(str(chunk_payload.get("text_clean", "") or paragraph.get("text", "")), 1400)
    retrieval_text = _compact_text(
        " ".join(
            [
                str(document_payload.get("court_name", "") or ""),
                str(document_payload.get("proceeding_no", "") or ""),
                str(chunk_payload.get("section_kind_case", "") or ""),
                text_clean,
            ]
        ),
        1600,
    )
    party_names = [
        str(item.get("name", "")).strip().lower()
        for item in chunk_payload.get("party_roles", [])
        if isinstance(item, dict) and str(item.get("name", "")).strip()
    ]
    return {
        "chunk_id": chunk_payload.get("chunk_id"),
        "document_id": paragraph.get("document_id"),
        "pdf_id": page.get("pdf_id"),
        "page_id": paragraph.get("page_id"),
        "page_number": int(page.get("page_num", 0) or 0),
        "doc_type": "case",
        "title_normalized": _compact_text(str(document_payload.get("case_caption", "")), 240).lower(),
        "short_title": _compact_text(str(document_payload.get("case_caption", "")), 120),
        "jurisdiction": "",
        "status": "indexed",
        "is_current_version": True,
        "effective_start_date": document_payload.get("decision_date"),
        "effective_end_date": None,
        "heading_path": [],
        "section_kind": chunk_payload.get("section_kind_case"),
        "text_clean": text_clean,
        "retrieval_text": retrieval_text,
        "entity_names": [name.title() for name in party_names],
        "article_refs": [],
        "dates": chunk_payload.get("date_mentions", []),
        "money_values": [],
        "exact_terms": chunk_payload.get("authority_refs", [])[:6],
        "search_keywords": chunk_payload.get("issue_tags", [])[:6] + chunk_payload.get("authority_refs", [])[:4],
        "version_lineage_id": None,
        "canonical_concept_id": None,
        "historical_relation_type": None,
        "law_number": None,
        "law_year": None,
        "regulation_number": None,
        "regulation_year": None,
        "notice_number": None,
        "notice_year": None,
        "case_number": document_payload.get("proceeding_no"),
        "court_name": document_payload.get("court_name"),
        "decision_date": document_payload.get("decision_date"),
        "article_number": None,
        "section_ref": None,
        "schedule_number": None,
        "administering_authority": None,
        "enabled_by_law_id": None,
        "target_doc_id": None,
        "target_article_refs": [],
        "commencement_date": None,
        "commencement_scope_type": None,
        "judge_names": chunk_payload.get("judge_names", []),
        "party_names_normalized": party_names,
        "final_disposition": chunk_payload.get("order_effect_label"),
        "edge_types": ["refers_to"] if chunk_payload.get("authority_refs") else [],
    }


def project_case_judgment_artifacts(
    *,
    document_payload: Dict[str, Any],
    chunk_payloads: List[Dict[str, Any]],
    paragraphs_by_id: Dict[str, Dict[str, Any]],
    pages_by_id: Dict[str, Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    case_chunk_facets: List[Dict[str, Any]] = []
    chunk_search_documents: List[Dict[str, Any]] = []

    for chunk in chunk_payloads:
        paragraph = paragraphs_by_id.get(str(chunk.get("chunk_id", "")))
        if not isinstance(paragraph, dict):
            continue
        page = pages_by_id.get(str(paragraph.get("page_id", "")), {})
        case_chunk_facets.append(build_case_chunk_facet(chunk_payload=chunk, document_payload=document_payload))
        chunk_search_documents.append(
            build_chunk_search_document(
                chunk_payload=chunk,
                document_payload=document_payload,
                paragraph=paragraph,
                page=page,
            )
        )

    return {
        "case_chunk_facets": case_chunk_facets,
        "chunk_search_documents": chunk_search_documents,
    }
