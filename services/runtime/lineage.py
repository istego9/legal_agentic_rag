"""Lineage helpers for canonical document and relation-edge traversal."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional


def _coerce_sequence(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _coerce_iso_date(value: Any) -> str:
    if value is None:
        return ""
    candidate = str(value).strip()
    if not candidate:
        return ""
    normalized = candidate.replace("/", "-").replace(".", "-")
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%Y-%m", "%Y"):
        try:
            parsed = datetime.strptime(normalized, fmt).date()
            if fmt == "%Y":
                parsed = parsed.replace(month=1, day=1)
            elif fmt == "%Y-%m":
                parsed = parsed.replace(day=1)
            return parsed.isoformat()
        except ValueError:
            continue
    return ""


def _current_version_rank(row: Dict[str, Any]) -> tuple[int, str, str, str]:
    """Return deterministic ranking tuple for current-version resolution."""
    return (
        _coerce_sequence(row.get("version_sequence")),
        _coerce_iso_date(row.get("effective_start_date")),
        _coerce_iso_date(row.get("issued_date")),
        str(row.get("document_id") or ""),
    )


def resolve_current_document_version(
    document_id: str,
    documents: Dict[str, Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Return current version for the same group using explicit deterministic rules.

    Resolution order:
    1. Candidates with `is_current_version=True` are preferred.
    2. Within a pool, higher `version_sequence` wins.
    3. Ties fall back to newer `effective_start_date`, then `issued_date`.
    4. Final tie-break is lexical `document_id` (stable and testable).
    """
    base = documents.get(document_id)
    if not base:
        return None
    version_group_id = base.get("version_group_id")
    if not version_group_id:
        return base

    candidates = [d for d in documents.values() if d.get("version_group_id") == version_group_id]
    if not candidates:
        return base

    current = [d for d in candidates if d.get("is_current_version") is True]
    pool = current if current else candidates
    pool.sort(key=_current_version_rank, reverse=True)
    return pool[0]


def supersession_chain(document_id: str, documents: Dict[str, Dict[str, Any]]) -> List[str]:
    """Walk superseded_by chain from the provided document to newest known version."""
    chain: List[str] = []
    seen: set[str] = set()
    cursor = document_id
    while cursor and cursor not in seen:
        seen.add(cursor)
        chain.append(cursor)
        row = documents.get(cursor)
        if not row:
            break
        cursor = row.get("superseded_by_doc_id")
    return chain


def find_commencement_notices(
    target_doc_id: str,
    enactment_notice_documents: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Return notice rows tied to a target document for commencement lookups."""
    out: List[Dict[str, Any]] = []
    for row in enactment_notice_documents:
        if row.get("target_doc_id") == target_doc_id:
            out.append(row)
    out.sort(key=lambda item: item.get("commencement_date") or "")
    return out


def filter_relation_edges(
    relation_edges: Iterable[Dict[str, Any]],
    *,
    source_object_id: Optional[str] = None,
    target_object_id: Optional[str] = None,
    edge_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Filter edges by source/target/edge_type."""
    out: List[Dict[str, Any]] = []
    for edge in relation_edges:
        if source_object_id and edge.get("source_object_id") != source_object_id:
            continue
        if target_object_id and edge.get("target_object_id") != target_object_id:
            continue
        if edge_type and edge.get("edge_type") != edge_type:
            continue
        out.append(edge)
    return out
