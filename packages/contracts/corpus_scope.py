from __future__ import annotations

from typing import Optional, Tuple


SHARED_CORPUS_PROJECT_ID = "00000000-0000-0000-0000-000000000000"


def resolve_corpus_import_project_id(project_id: Optional[str] = None) -> str:
    """Corpus imports are always written into the shared reusable corpus scope."""
    _ = project_id
    return SHARED_CORPUS_PROJECT_ID


def normalize_corpus_record_project_id(project_id: Optional[str]) -> str:
    normalized = str(project_id or "").strip()
    if not normalized:
        return SHARED_CORPUS_PROJECT_ID
    return normalized


def corpus_scope_ids(project_id: Optional[str]) -> Tuple[str, ...]:
    normalized = str(project_id or "").strip()
    if not normalized or normalized == SHARED_CORPUS_PROJECT_ID:
        return (SHARED_CORPUS_PROJECT_ID,)
    return (normalized, SHARED_CORPUS_PROJECT_ID)


def matches_corpus_scope(record_project_id: Optional[str], project_id: Optional[str]) -> bool:
    return normalize_corpus_record_project_id(record_project_id) in corpus_scope_ids(project_id)
