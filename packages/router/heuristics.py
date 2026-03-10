"""Deterministic routing rules for route family selection."""

from __future__ import annotations

from typing import Dict


def choose_route(question: Dict[str, object]) -> str:
    route_hint = question.get("route_hint")
    if isinstance(route_hint, str) and route_hint:
        return route_hint

    text = str(question.get("question", "")).lower()
    if any(k in text for k in ("compare", "difference", "compared to", "versus")):
        if "case" in text:
            return "cross_case_compare"
        return "cross_law_compare"
    if any(k in text for k in ("history", "amended", "repeal", "amendment", "supersede", "version")):
        return "history_lineage"
    if any(k in text for k in ("article", "clause", "section", "paragraph")):
        return "article_lookup"
    if any(k in text for k in ("case", "court", "judge", "appeal")):
        return "single_case_extraction"
    return "article_lookup"

