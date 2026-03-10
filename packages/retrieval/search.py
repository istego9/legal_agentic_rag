"""Simple text-based retrieval fallback used by bootstrap runtime."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from packages.contracts.corpus_scope import matches_corpus_scope


def score_candidate(query: str, candidate_text: str) -> float:
    q = query.lower()
    c = candidate_text.lower()
    if not q:
        return 0.0
    matches = sum(1 for token in q.split() if token and token in c)
    return min(1.0, matches / max(1, len(q.split())))


def search_pages(
    paragraphs: List[Dict[str, Any]],
    query: str,
    top_k: int,
    *, 
    project_id: str | None = None,
) -> List[Tuple[Dict[str, Any], float]]:
    scored: List[Tuple[Dict[str, Any], float]] = []
    for paragraph in paragraphs:
        if not query:
            continue
        score = score_candidate(query, str(paragraph.get("text", "")))
        if score <= 0:
            continue
        if project_id and not matches_corpus_scope(paragraph.get("project_id"), project_id):
            continue
        scored.append((paragraph, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]
