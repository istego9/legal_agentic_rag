"""Route normalization for taxonomy benchmarking.

Benchmark integrity rule:
- raw mapping aligns label space only;
- normalized mapping may use explicit runtime metadata only;
- no question-text inference is allowed in default scoring path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Literal, Mapping, Optional, Tuple

from packages.contracts.public_question_taxonomy import PRIMARY_ROUTES


BENCHMARK_ROUTE_NORMALIZATION_VERSION = "benchmark_route_normalization.v2"
UNMAPPED_TAXONOMY_ROUTE = "__unmapped__"

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

# Minimal alias mapping used for raw-route accuracy (label-space alignment only).
RAW_ROUTE_ALIAS_TO_TAXONOMY: Dict[str, str] = {
    "cross_case_compare": "case_cross_compare",
    "cross_law_compare": "cross_law_compare",
    "history_lineage": "law_relation_or_history",
    "no_answer": "negative_or_unanswerable",
}

# Optional metadata-based alignment (applied only when runtime emits explicit subroute metadata).
RAW_ROUTE_TO_SUBROUTE_NORMALIZATION: Dict[str, Dict[str, str]] = {
    "single_case_extraction": {
        "case_entity_lookup": "case_entity_lookup",
        "case_outcome_or_value": "case_outcome_or_value",
        "case_cross_compare": "case_cross_compare",
        "negative_or_unanswerable": "negative_or_unanswerable",
    },
    "article_lookup": {
        "law_article_lookup": "law_article_lookup",
        "law_scope_or_definition": "law_scope_or_definition",
        "law_relation_or_history": "law_relation_or_history",
        "cross_law_compare": "cross_law_compare",
        "negative_or_unanswerable": "negative_or_unanswerable",
    },
    "history_lineage": {
        "law_relation_or_history": "law_relation_or_history",
        "cross_law_compare": "cross_law_compare",
    },
    "cross_case_compare": {"case_cross_compare": "case_cross_compare"},
    "cross_law_compare": {"cross_law_compare": "cross_law_compare"},
    "no_answer": {"negative_or_unanswerable": "negative_or_unanswerable"},
}

_RUNTIME_METADATA_SUBROUTE_KEYS: Tuple[str, ...] = (
    "taxonomy_subroute",
    "route_subroute",
    "subroute",
)
_RUNTIME_METADATA_ROUTE_KEYS: Tuple[str, ...] = (
    "normalized_taxonomy_route",
    "taxonomy_route",
    "primary_route",
)


@dataclass(frozen=True)
class BenchmarkRouteNormalizationDecision:
    raw_runtime_route: str
    raw_taxonomy_route: str
    normalized_taxonomy_route: str
    normalization_source: str
    runtime_taxonomy_subroute: Optional[str]


def _normalize_raw_runtime_route(raw_runtime_route: str) -> str:
    normalized = str(raw_runtime_route or "").strip()
    if not normalized:
        return "unknown"
    if normalized in RAW_RUNTIME_ROUTES:
        return normalized
    if normalized in PRIMARY_ROUTES:
        return normalized
    return "unknown"


def map_raw_route_to_taxonomy(raw_runtime_route: str) -> str:
    normalized_raw = _normalize_raw_runtime_route(raw_runtime_route)
    if normalized_raw in PRIMARY_ROUTES:
        return normalized_raw
    return RAW_ROUTE_ALIAS_TO_TAXONOMY.get(normalized_raw, UNMAPPED_TAXONOMY_ROUTE)


def _coerce_runtime_metadata(runtime_metadata: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if runtime_metadata is None:
        return {}
    return dict(runtime_metadata)


def _extract_runtime_metadata_route(runtime_metadata: Mapping[str, Any]) -> Optional[str]:
    for key in _RUNTIME_METADATA_ROUTE_KEYS:
        value = runtime_metadata.get(key)
        if value is None:
            continue
        route = str(value).strip()
        if route in PRIMARY_ROUTES:
            return route
    return None


def _extract_runtime_metadata_subroute(runtime_metadata: Mapping[str, Any]) -> Optional[str]:
    for key in _RUNTIME_METADATA_SUBROUTE_KEYS:
        value = runtime_metadata.get(key)
        if value is None:
            continue
        subroute = str(value).strip()
        if subroute in BENCHMARK_SUBROUTES:
            return subroute
    return None


def normalize_runtime_route_for_taxonomy(
    raw_runtime_route: str,
    *,
    runtime_metadata: Optional[Mapping[str, Any]] = None,
) -> BenchmarkRouteNormalizationDecision:
    normalized_raw_route = _normalize_raw_runtime_route(raw_runtime_route)
    raw_taxonomy_route = map_raw_route_to_taxonomy(normalized_raw_route)
    normalized_taxonomy_route = raw_taxonomy_route
    normalization_source = (
        "raw_alias"
        if raw_taxonomy_route != UNMAPPED_TAXONOMY_ROUTE
        else "raw_unmapped"
    )
    runtime_taxonomy_subroute: Optional[str] = None

    metadata = _coerce_runtime_metadata(runtime_metadata)

    explicit_runtime_route = _extract_runtime_metadata_route(metadata)
    if explicit_runtime_route is not None:
        normalized_taxonomy_route = explicit_runtime_route
        normalization_source = "runtime_metadata.taxonomy_route"
    else:
        runtime_taxonomy_subroute = _extract_runtime_metadata_subroute(metadata)
        if runtime_taxonomy_subroute is not None:
            by_subroute = RAW_ROUTE_TO_SUBROUTE_NORMALIZATION.get(normalized_raw_route, {})
            metadata_route = by_subroute.get(runtime_taxonomy_subroute)
            if metadata_route is not None:
                normalized_taxonomy_route = metadata_route
                normalization_source = "runtime_metadata.taxonomy_subroute"

    return BenchmarkRouteNormalizationDecision(
        raw_runtime_route=normalized_raw_route,
        raw_taxonomy_route=raw_taxonomy_route,
        normalized_taxonomy_route=normalized_taxonomy_route,
        normalization_source=normalization_source,
        runtime_taxonomy_subroute=runtime_taxonomy_subroute,
    )


def validate_benchmark_mapping() -> list[str]:
    errors: list[str] = []
    primary_route_set = set(PRIMARY_ROUTES)
    subroute_set = set(BENCHMARK_SUBROUTES)

    for raw_route, route in RAW_ROUTE_ALIAS_TO_TAXONOMY.items():
        if raw_route not in RAW_RUNTIME_ROUTES:
            errors.append(f"raw alias key is not a known raw route: {raw_route!r}")
        if route not in primary_route_set:
            errors.append(f"raw alias target is not a taxonomy route: {route!r}")

    for raw_route, mapping in RAW_ROUTE_TO_SUBROUTE_NORMALIZATION.items():
        if raw_route not in RAW_RUNTIME_ROUTES:
            errors.append(f"subroute mapping key is not a known raw route: {raw_route!r}")
        for subroute, route in mapping.items():
            if subroute not in subroute_set:
                errors.append(f"unknown subroute {subroute!r} in mapping for raw route {raw_route!r}")
            if route not in primary_route_set:
                errors.append(f"unknown taxonomy route {route!r} in mapping for raw route {raw_route!r}")

    return errors
