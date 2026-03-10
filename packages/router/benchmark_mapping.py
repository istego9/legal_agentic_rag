"""Route normalization for taxonomy benchmarking.

This module intentionally keeps benchmark normalization logic isolated from
runtime routing logic so benchmark hygiene changes do not alter production
route selection behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Dict, Literal, Optional, Tuple

from packages.contracts.public_question_taxonomy import PRIMARY_ROUTES


BENCHMARK_ROUTE_NORMALIZATION_VERSION = "benchmark_route_normalization.v1"

RAW_RUNTIME_ROUTES: Tuple[str, ...] = (
    "article_lookup",
    "single_case_extraction",
    "cross_case_compare",
    "cross_law_compare",
    "history_lineage",
    "no_answer",
    "unknown",
)

BENCHMARK_SUBROUTES: Tuple[str, ...] = (
    "case_entity_lookup",
    "case_outcome_or_value",
    "case_cross_compare",
    "law_article_lookup",
    "law_relation_or_history",
    "law_scope_or_definition",
    "cross_law_compare",
    "negative_or_unanswerable",
)

BenchmarkSubroute = Literal[
    "case_entity_lookup",
    "case_outcome_or_value",
    "case_cross_compare",
    "law_article_lookup",
    "law_relation_or_history",
    "law_scope_or_definition",
    "cross_law_compare",
    "negative_or_unanswerable",
]


RAW_ROUTE_TO_SUBROUTE_NORMALIZATION: Dict[str, Dict[str, str]] = {
    "single_case_extraction": {
        "case_entity_lookup": "case_entity_lookup",
        "case_outcome_or_value": "case_outcome_or_value",
        "case_cross_compare": "case_cross_compare",
        "negative_or_unanswerable": "negative_or_unanswerable",
    },
    "cross_case_compare": {"*": "case_cross_compare"},
    "cross_law_compare": {"*": "cross_law_compare"},
    "history_lineage": {
        "law_relation_or_history": "law_relation_or_history",
        "cross_law_compare": "cross_law_compare",
    },
    "article_lookup": {
        "law_article_lookup": "law_article_lookup",
        "law_scope_or_definition": "law_scope_or_definition",
        "law_relation_or_history": "law_relation_or_history",
        "cross_law_compare": "cross_law_compare",
        "negative_or_unanswerable": "negative_or_unanswerable",
        "case_cross_compare": "case_cross_compare",
    },
    "no_answer": {"*": "negative_or_unanswerable"},
    "unknown": {"*": "negative_or_unanswerable"},
}

RAW_ROUTE_FALLBACK_NORMALIZATION: Dict[str, str] = {
    "single_case_extraction": "case_outcome_or_value",
    "cross_case_compare": "case_cross_compare",
    "cross_law_compare": "cross_law_compare",
    "history_lineage": "law_relation_or_history",
    "article_lookup": "law_scope_or_definition",
    "no_answer": "negative_or_unanswerable",
    "unknown": "negative_or_unanswerable",
}

_CASE_CITATION_PATTERN = re.compile(r"\b(?:CFI|ARB|CA|SCT|TCD|ENF|DEC)\s*\d+/\d{4}\b", flags=re.IGNORECASE)
_LAW_TOKEN_PATTERN = re.compile(r"\blaw(?:s)?\b", flags=re.IGNORECASE)
_REGULATION_TOKEN_PATTERN = re.compile(r"\bregulation(?:s)?\b", flags=re.IGNORECASE)

_ARTICLE_SIGNAL_TOKENS = ("article", "section", "clause", "paragraph", "schedule")
_HISTORY_SIGNAL_TOKENS = (
    "amend",
    "supersed",
    "repeal",
    "history",
    "version",
    "enacted",
    "commencement",
    "come into force",
    "consolidated",
    "latest",
)
_COMPARE_SIGNAL_TOKENS = (
    "compare",
    "difference",
    "compared",
    "versus",
    "both",
    "common",
    "same",
    "earlier",
    "higher",
)
_NEGATIVE_SIGNAL_TOKENS = ("jury", "parole", "miranda", "plea bargain")
_CASE_ENTITY_SIGNAL_TOKENS = ("claimant", "respondent", "party", "parties", "judge", "entity", "individual")


@dataclass(frozen=True)
class BenchmarkRouteMetadata:
    subroute: BenchmarkSubroute
    case_reference_count: int
    law_reference_count: int
    has_article_signal: bool
    has_history_signal: bool
    has_compare_signal: bool
    has_negative_signal: bool


@dataclass(frozen=True)
class BenchmarkRouteNormalizationDecision:
    raw_runtime_route: str
    normalization_subroute: BenchmarkSubroute
    normalized_taxonomy_route: str
    metadata: BenchmarkRouteMetadata


def _normalize_raw_runtime_route(raw_runtime_route: str) -> str:
    normalized = str(raw_runtime_route or "").strip()
    if not normalized:
        return "unknown"
    if normalized in RAW_RUNTIME_ROUTES:
        return normalized
    return "unknown"


def derive_benchmark_route_metadata(question: str, answer_type: str) -> BenchmarkRouteMetadata:
    text = str(question or "").strip().lower()
    normalized_answer_type = str(answer_type or "").strip().lower()

    case_reference_count = len(_CASE_CITATION_PATTERN.findall(text))
    law_reference_count = len(_LAW_TOKEN_PATTERN.findall(text)) + len(_REGULATION_TOKEN_PATTERN.findall(text))
    has_article_signal = any(token in text for token in _ARTICLE_SIGNAL_TOKENS)
    has_history_signal = any(token in text for token in _HISTORY_SIGNAL_TOKENS)
    has_compare_signal = any(token in text for token in _COMPARE_SIGNAL_TOKENS) or "which laws" in text
    has_negative_signal = any(token in text for token in _NEGATIVE_SIGNAL_TOKENS)

    subroute: BenchmarkSubroute
    if has_negative_signal:
        subroute = "negative_or_unanswerable"
    elif case_reference_count >= 2:
        subroute = "case_cross_compare"
    elif case_reference_count == 1:
        has_case_entity_signal = any(token in text for token in _CASE_ENTITY_SIGNAL_TOKENS)
        if normalized_answer_type in {"name", "names"} and has_case_entity_signal:
            subroute = "case_entity_lookup"
        else:
            subroute = "case_outcome_or_value"
    elif law_reference_count >= 2 and has_compare_signal:
        subroute = "cross_law_compare"
    elif has_history_signal:
        subroute = "law_relation_or_history"
    elif has_article_signal:
        subroute = "law_article_lookup"
    elif law_reference_count >= 2:
        subroute = "cross_law_compare"
    else:
        subroute = "law_scope_or_definition"

    return BenchmarkRouteMetadata(
        subroute=subroute,
        case_reference_count=case_reference_count,
        law_reference_count=law_reference_count,
        has_article_signal=has_article_signal,
        has_history_signal=has_history_signal,
        has_compare_signal=has_compare_signal,
        has_negative_signal=has_negative_signal,
    )


def normalize_runtime_route_for_taxonomy(
    raw_runtime_route: str,
    *,
    question: str,
    answer_type: str,
    metadata: Optional[BenchmarkRouteMetadata] = None,
) -> BenchmarkRouteNormalizationDecision:
    normalized_raw_route = _normalize_raw_runtime_route(raw_runtime_route)
    resolved_metadata = metadata or derive_benchmark_route_metadata(question, answer_type)
    subroute = resolved_metadata.subroute
    raw_mapping = RAW_ROUTE_TO_SUBROUTE_NORMALIZATION.get(normalized_raw_route, {})
    normalized_taxonomy_route = (
        raw_mapping.get(subroute)
        or raw_mapping.get("*")
        or RAW_ROUTE_FALLBACK_NORMALIZATION.get(normalized_raw_route, "negative_or_unanswerable")
    )
    return BenchmarkRouteNormalizationDecision(
        raw_runtime_route=normalized_raw_route,
        normalization_subroute=subroute,
        normalized_taxonomy_route=normalized_taxonomy_route,
        metadata=resolved_metadata,
    )


def validate_benchmark_mapping() -> list[str]:
    errors: list[str] = []
    primary_route_set = set(PRIMARY_ROUTES)
    subroute_set = set(BENCHMARK_SUBROUTES)

    for raw_route in RAW_RUNTIME_ROUTES:
        mapping = RAW_ROUTE_TO_SUBROUTE_NORMALIZATION.get(raw_route, {})
        fallback = RAW_ROUTE_FALLBACK_NORMALIZATION.get(raw_route)
        if not mapping and fallback is None:
            errors.append(f"raw route missing mapping and fallback: {raw_route}")

        for subroute, normalized in mapping.items():
            if subroute != "*" and subroute not in subroute_set:
                errors.append(f"unknown subroute {subroute!r} in mapping for raw route {raw_route!r}")
            if normalized not in primary_route_set:
                errors.append(f"unknown taxonomy route {normalized!r} in mapping for raw route {raw_route!r}")

        if fallback is not None and fallback not in primary_route_set:
            errors.append(f"unknown fallback taxonomy route {fallback!r} for raw route {raw_route!r}")

    return errors

